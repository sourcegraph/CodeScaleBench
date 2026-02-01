```python
"""
flockdesk.modules.whiteboard.model.canvas_state
==============================================

Shared white-board *model* that lives in the whiteboard micro-front-end’s
process and synchronises its state over the internal event-bus so that
other whiteboard instances (or plugins) can react to changes in real-time.

Responsibilities
----------------
1. Maintain an authoritative list of drawable objects (strokes, shapes,
   images, text boxes, …) on the canvas.
2. Provide an *undo/redo* stack that works across distributed peers.
3. Emit fine-grained diff events so that the transport layer can keep
   bandwidth low by sending only incremental updates.
4. Persist / restore snapshots so that a session can be recovered after
   a crash or reload.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
#  Event bus integration                                                      #
# --------------------------------------------------------------------------- #
class _EventBus(Protocol):  # pragma: no cover
    """Private protocol so that we don’t import the real event-bus here."""

    def publish(self, topic: str, payload: dict) -> None: ...
    def subscribe(
        self, topic: str, handler: Callable[[dict], None], *, replay: bool = False
    ) -> None: ...


# --------------------------------------------------------------------------- #
#  Data models                                                                #
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class CanvasObject:
    """
    A single drawable entity on the whiteboard.

    The payload inside `props` is deliberately unstructured so that
    plugins can attach arbitrary metadata (e.g., `{"shape": "rect",
    "width": 200, "height": 100, "fill": "#FF0000"}`).
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    # Type of object (stroke, text, image, shape, ...)
    kind: str = field(default="stroke")
    z_index: int = field(default=0)
    props: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "CanvasObject":
        return cls(
            id=raw["id"],
            created_at=raw["created_at"],
            kind=raw["kind"],
            z_index=raw["z_index"],
            props=raw.get("props", {}),
        )


@dataclass(slots=True)
class _Action:
    """Internal structure for undo/redo stack."""

    # 'add', 'remove', 'update'
    verb: str
    before: Optional[CanvasObject]
    after: Optional[CanvasObject]


# --------------------------------------------------------------------------- #
#  Exceptions                                                                 #
# --------------------------------------------------------------------------- #
class CanvasStateError(RuntimeError):
    """Base exception for model-related errors."""


class ObjectNotFoundError(CanvasStateError):
    """Raised when attempting to update/remove a non-existing object."""


class UndoRedoError(CanvasStateError):
    """Raised when the undo / redo stack is in an invalid state."""


# --------------------------------------------------------------------------- #
#  CanvasState implementation                                                 #
# --------------------------------------------------------------------------- #
class CanvasState:
    """
    In-memory representation of the current whiteboard canvas.

    Thread-safe. All public mutating methods acquire a re-entrant lock
    so multiple background threads (UI, network sync, plugins) can
    operate concurrently without corrupting internal structures.
    """

    UNDO_LIMIT = 200
    PERSIST_FILE = Path.home() / ".flockdesk" / "whiteboard_state.json"

    def __init__(self, event_bus: _EventBus | None = None) -> None:
        self._objects: Dict[str, CanvasObject] = {}
        self._undo_stack: List[_Action] = []
        self._redo_stack: List[_Action] = []
        self._lock = threading.RLock()
        self._event_bus = event_bus
        self._dirty = False  # marks whether the state changed since last persist
        self._subscribe_to_remote_events()

    # -------------------------- Public API -------------------------------- #

    def add_object(self, obj: CanvasObject) -> None:
        with self._atomic_change():
            self._objects[obj.id] = obj
            self._record_action(_Action("add", None, deepcopy(obj)))
            self._broadcast("object.added", obj.to_dict())

    def update_object(self, obj_id: str, **patch: Any) -> None:
        with self._atomic_change():
            original = self._get_object_or_raise(obj_id)
            before = deepcopy(original)
            for key, value in patch.items():
                if key == "props" and isinstance(value, dict):
                    original.props.update(value)
                elif hasattr(original, key):
                    setattr(original, key, value)
                else:
                    logger.warning("Ignored unknown attribute %s", key)
            self._record_action(_Action("update", before, deepcopy(original)))
            self._broadcast("object.updated", {"id": obj_id, "patch": patch})

    def remove_object(self, obj_id: str) -> None:
        with self._atomic_change():
            obj = self._objects.pop(obj_id, None)
            if obj is None:
                raise ObjectNotFoundError(f"Object {obj_id!r} not found.")
            self._record_action(_Action("remove", deepcopy(obj), None))
            self._broadcast("object.removed", {"id": obj_id})

    def clear(self) -> None:
        with self._atomic_change():
            for obj in list(self._objects.values()):
                self.remove_object(obj.id)  # record each removal

    # --------------------------- Undo / Redo ------------------------------ #

    def undo(self) -> None:
        with self._atomic_change(broadcast=False):
            if not self._undo_stack:
                raise UndoRedoError("Undo stack is empty.")
            action = self._undo_stack.pop()
            self._apply_reverse(action, record=False)
            self._redo_stack.append(action)
            self._broadcast("canvas.undo", {"action": self._action_to_dict(action)})

    def redo(self) -> None:
        with self._atomic_change(broadcast=False):
            if not self._redo_stack:
                raise UndoRedoError("Redo stack is empty.")
            action = self._redo_stack.pop()
            self._apply_forward(action, record=False)
            self._undo_stack.append(action)
            self._broadcast("canvas.redo", {"action": self._action_to_dict(action)})

    # -------------------------- Query helpers ----------------------------- #

    def objects(self, *, z_sorted: bool = True) -> List[CanvasObject]:
        """Return a (shallow) copy of all objects."""
        objs = list(self._objects.values())
        return sorted(objs, key=lambda o: o.z_index) if z_sorted else objs

    def get(self, obj_id: str) -> Optional[CanvasObject]:
        return self._objects.get(obj_id)

    # ------------------------- Persistence -------------------------------- #

    def save_snapshot(self, file: Path | None = None) -> None:
        file = file or self.PERSIST_FILE
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("w", encoding="utf8") as fh:
            json.dump(self._serialize(), fh, indent=2)
        self._dirty = False
        logger.info("Canvas snapshot saved to %s", file)

    def restore_snapshot(self, file: Path | None = None) -> None:
        file = file or self.PERSIST_FILE
        if not file.exists():
            logger.warning("No snapshot to restore from %s", file)
            return
        with file.open("r", encoding="utf8") as fh:
            raw = json.load(fh)
        with self._atomic_change(broadcast=False):
            self._objects = {
                obj["id"]: CanvasObject.from_dict(obj) for obj in raw.get("objects", [])
            }
            self._undo_stack.clear()
            self._redo_stack.clear()
        logger.info("Canvas snapshot restored from %s", file)
        self._broadcast("canvas.restored", self._serialize())

    # ----------------------- Internal helpers ----------------------------- #

    def _broadcast(self, topic: str, payload: dict) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(f"whiteboard.{topic}", payload)
        except Exception:  # pragma: no cover
            logger.exception("Failed to publish whiteboard event: %s", topic)

    def _subscribe_to_remote_events(self) -> None:
        """Subscribe to events coming from remote peers to keep state in sync."""
        if self._event_bus is None:
            return

        def _handler(envelope: dict) -> None:
            """Handle remote diff events and merge them locally."""
            topic = envelope.get("topic", "")
            data = envelope.get("payload", envelope)
            if topic.endswith("object.added"):
                self._merge_remote_add(data)
            elif topic.endswith("object.updated"):
                self._merge_remote_update(data)
            elif topic.endswith("object.removed"):
                self._merge_remote_remove(data)
            elif topic.endswith("canvas.undo"):
                self._replay_remote_undo(data)
            elif topic.endswith("canvas.redo"):
                self._replay_remote_redo(data)

        for t in (
            "whiteboard.object.added",
            "whiteboard.object.updated",
            "whiteboard.object.removed",
            "whiteboard.canvas.undo",
            "whiteboard.canvas.redo",
        ):
            self._event_bus.subscribe(t, _handler, replay=False)

    # Merge strategies ----------------------------------------------------- #

    def _merge_remote_add(self, payload: dict) -> None:
        obj = CanvasObject.from_dict(payload)
        with self._atomic_change(broadcast=False):
            if obj.id in self._objects:
                logger.debug("Remote add ignored. Object already exists: %s", obj.id)
                return
            self._objects[obj.id] = obj

    def _merge_remote_update(self, payload: dict) -> None:
        obj_id = payload["id"]
        patch = payload.get("patch", {})
        with self._atomic_change(broadcast=False):
            try:
                self.update_object(obj_id, **patch)
            except ObjectNotFoundError:
                logger.warning("Received update for unknown object %s", obj_id)

    def _merge_remote_remove(self, payload: dict) -> None:
        obj_id = payload["id"]
        with self._atomic_change(broadcast=False):
            self._objects.pop(obj_id, None)

    def _replay_remote_undo(self, payload: dict) -> None:
        action_dict = payload.get("action", {})
        action = self._dict_to_action(action_dict)
        with self._atomic_change(broadcast=False):
            self._apply_reverse(action, record=False)

    def _replay_remote_redo(self, payload: dict) -> None:
        action_dict = payload.get("action", {})
        action = self._dict_to_action(action_dict)
        with self._atomic_change(broadcast=False):
            self._apply_forward(action, record=False)

    # Core state-mutation machinery --------------------------------------- #

    def _apply_forward(self, action: _Action, *, record: bool) -> None:
        if action.verb == "add" and action.after:
            self._objects[action.after.id] = deepcopy(action.after)
        elif action.verb == "remove" and action.before:
            self._objects.pop(action.before.id, None)
        elif action.verb == "update" and action.after:
            self._objects[action.after.id] = deepcopy(action.after)
        else:
            logger.error("Invalid action for forward apply: %s", action)
            return
        if record:
            self._record_action(action)

    def _apply_reverse(self, action: _Action, *, record: bool) -> None:
        """Apply inverse of an action (used for undo)."""
        inverse = {
            "add": "remove",
            "remove": "add",
            "update": "update",
        }[action.verb]
        rev = _Action(
            verb=inverse,
            before=deepcopy(action.after),
            after=deepcopy(action.before),
        )
        self._apply_forward(rev, record=record)

    def _record_action(self, action: _Action) -> None:
        self._undo_stack.append(action)
        self._redo_stack.clear()
        if len(self._undo_stack) > self.UNDO_LIMIT:
            self._undo_stack.pop(0)

    # Utility context manager --------------------------------------------- #

    from contextlib import contextmanager

    @contextmanager
    def _atomic_change(self, *, broadcast: bool = True):
        """Ensure thread-safety and mark state as dirty."""
        with self._lock:
            yield
            self._dirty = True
            # Auto-persist asynchronously if the app goes idle
            # (Real implementation would hook into idle-timer.)
            if self._dirty:
                threading.Thread(target=self.save_snapshot, daemon=True).start()

    # Helpers -------------------------------------------------------------- #

    def _get_object_or_raise(self, obj_id: str) -> CanvasObject:
        obj = self._objects.get(obj_id)
        if obj is None:
            raise ObjectNotFoundError(f"Object {obj_id!r} not found.")
        return obj

    def _serialize(self) -> dict:
        return {
            "objects": [o.to_dict() for o in self._objects.values()],
            "timestamp": time.time(),
        }

    @staticmethod
    def _action_to_dict(action: _Action) -> dict:
        return {
            "verb": action.verb,
            "before": action.before.to_dict() if action.before else None,
            "after": action.after.to_dict() if action.after else None,
        }

    @staticmethod
    def _dict_to_action(raw: dict) -> _Action:
        return _Action(
            verb=raw["verb"],
            before=CanvasObject.from_dict(raw["before"])
            if raw.get("before")
            else None,
            after=CanvasObject.from_dict(raw["after"]) if raw.get("after") else None,
        )

    # --------------------------------------------------------------------- #
    #  Dunder methods                                                       #
    # --------------------------------------------------------------------- #

    def __len__(self) -> int:
        return len(self._objects)

    def __iter__(self) -> Iterable[CanvasObject]:
        return iter(self._objects.values())

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CanvasState objects={len(self._objects)} "
            f"undo={len(self._undo_stack)} redo={len(self._redo_stack)}>"
        )
```