```python
"""
FlockDesk – Whiteboard View-Model
---------------------------------

This module lives inside the *whiteboard* micro-front-end and represents the
MVVM “VM” layer.  It binds the Qt/PySide6 widgets (View) with the drawing/
collaboration domain (Model) and the global event-bus (infrastructure).

Responsibilities
================
1. UI state orchestration (selected tool, color, thickness, etc.).
2. Performing local drawing commands and maintaining an undo/redo stack.
3. Publishing user actions to the event bus so that other peers may replicate.
4. Consuming remote events and mutating local state accordingly.
5. Providing Qt signals so that views can react reactively.

The ViewModel never imports the concrete whiteboard widgets, keeping the
dependency flow unidirectional (Model ← ViewModel ← View).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Protocol, Tuple

from PySide6 import QtCore

__all__ = ["WhiteboardViewModel", "Stroke", "WhiteboardState"]

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
#  Domain objects                                                             
# --------------------------------------------------------------------------- #

@dataclasses.dataclass(frozen=True)
class Point:
    """A single 2D coordinate on the whiteboard canvas."""
    x: float
    y: float


@dataclasses.dataclass(frozen=True)
class Stroke:
    """
    A continuous stroke drawn by a user.

    When synchronised across the event bus, the object is serialised to JSON.
    """
    user_id: str
    points: Tuple[Point, ...]
    color: str                # hex ‑ encoded #RRGGBB
    thickness: float
    timestamp: float          # epoch seconds

    def to_payload(self) -> Dict[str, Any]:
        """Serialise stroke to payload dictionary safe for JSON."""
        return {
            "user_id": self.user_id,
            "points": [(p.x, p.y) for p in self.points],
            "color": self.color,
            "thickness": self.thickness,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> "Stroke":
        """Reconstruct a stroke object from event-bus payload."""
        return cls(
            user_id=data["user_id"],
            points=tuple(Point(x, y) for x, y in data["points"]),
            color=data["color"],
            thickness=float(data["thickness"]),
            timestamp=float(data["timestamp"]),
        )


@dataclasses.dataclass
class WhiteboardState:
    """
    Current whiteboard state.

    The data structure is intentionally mutable for quick in-memory operations
    but should never be exposed directly to the View.
    """
    strokes: List[Stroke] = dataclasses.field(default_factory=list)
    undo_stack: Deque[Stroke] = dataclasses.field(default_factory=deque)

    def clear(self) -> None:
        """Remove all strokes and empty undo stack."""
        self.strokes.clear()
        self.undo_stack.clear()


# --------------------------------------------------------------------------- #
#  Infrastructure                                                             
# --------------------------------------------------------------------------- #

class IEventBus(Protocol):
    """
    Minimal interface for the global event bus.

    Real implementation lives in *flockdesk/core/event_bus.py* and is
    dependency-injected at runtime.
    """
    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        ...

    def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        ...


class ICommand(Protocol):
    """An undo-able command interface."""
    def execute(self) -> None: ...
    def undo(self) -> None: ...


# --------------------------------------------------------------------------- #
#  ViewModel implementation                                                   
# --------------------------------------------------------------------------- #

class WhiteboardViewModel(QtCore.QObject):
    """
    The ViewModel orchestrating user interaction and synchronisation.

    Signals
    -------
    strokeAdded(Stroke):
        Emitted whenever a new stroke is appended to *strokes* (both local and
        remote).

    strokeUndone(Stroke):
        Emitted when a stroke has been undone (either local user action or
        remote event).

    strokeRedone(Stroke):
        Emitted when a stroke has been reapplied from the undo stack.

    boardCleared():
        Emitted after the whiteboard has been cleared.
    """

    # Qt Signals exposed to the View layer
    strokeAdded = QtCore.Signal(Stroke)
    strokeUndone = QtCore.Signal(Stroke)
    strokeRedone = QtCore.Signal(Stroke)
    boardCleared = QtCore.Signal()

    # Event bus naming convention
    EVT_STROKE_ADDED = "whiteboard/stroke_added"
    EVT_STROKE_UNDONE = "whiteboard/stroke_undone"
    EVT_STROKE_REDONE = "whiteboard/stroke_redone"
    EVT_BOARD_CLEARED = "whiteboard/board_cleared"

    # --------------------------------------------------------------------- #

    def __init__(
        self,
        *,
        user_id: str,
        event_bus: IEventBus,
        autosave_file: Optional[Path] = None,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent=parent)

        self._user_id = user_id
        self._bus = event_bus
        self._autosave_file = autosave_file or Path.home() / ".flockdesk_whiteboard_autosave.json"
        self._state = WhiteboardState()

        # Current drawing context
        self._current_points: List[Point] = []
        self._current_color: str = "#000000"
        self._current_thickness: float = 2.0

        self._register_event_bus_handlers()
        self._restore_autosave()

    # -- Public API -------------------------------------------------------- #

    # region – Drawing  -----------------------------------------------------

    @QtCore.Slot(float, float)
    def add_point(self, x: float, y: float) -> None:
        """Add a 2D coordinate to the currently active stroke."""
        self._current_points.append(Point(x, y))

    @QtCore.Slot()
    def finish_stroke(self) -> None:
        """Complete the current stroke and broadcast it to peers."""
        if not self._current_points:
            return  # Nothing to commit

        stroke = Stroke(
            user_id=self._user_id,
            points=tuple(self._current_points),
            color=self._current_color,
            thickness=self._current_thickness,
            timestamp=time.time(),
        )
        cmd = _AddStrokeCommand(stroke, self._state, self)
        cmd.execute()
        self._push_to_undo_stack(cmd)

        # Broadcast
        self._bus.publish(self.EVT_STROKE_ADDED, stroke.to_payload())
        self._current_points.clear()
        self._persist_autosave()

    # endregion

    # region – Commands -----------------------------------------------------

    @QtCore.Slot()
    def undo(self) -> None:
        """Undo the last stroke."""
        if not self._state.strokes:
            return

        stroke = self._state.strokes.pop()
        self._state.undo_stack.append(stroke)
        self.strokeUndone.emit(stroke)

        self._bus.publish(self.EVT_STROKE_UNDONE, {"timestamp": stroke.timestamp, "user_id": self._user_id})
        self._persist_autosave()

    @QtCore.Slot()
    def redo(self) -> None:
        """Redo the most recently undone stroke."""
        if not self._state.undo_stack:
            return

        stroke = self._state.undo_stack.pop()
        self._state.strokes.append(stroke)
        self.strokeRedone.emit(stroke)

        self._bus.publish(self.EVT_STROKE_REDONE, {"timestamp": stroke.timestamp, "user_id": self._user_id})
        self._persist_autosave()

    @QtCore.Slot()
    def clear_board(self) -> None:
        """Clear the whiteboard entirely."""
        if not self._state.strokes:
            return

        self._state.clear()
        self.boardCleared.emit()
        self._bus.publish(self.EVT_BOARD_CLEARED, {"user_id": self._user_id})
        self._persist_autosave()

    # endregion

    # region – State-change helpers ----------------------------------------

    def set_pen_color(self, color: str) -> None:
        """Change the active pen color (#RRGGBB)."""
        self._current_color = color

    def set_pen_thickness(self, thickness: float) -> None:
        """Change the active pen thickness in pixels."""
        self._current_thickness = thickness

    # endregion

    # --------------------------------------------------------------------- #
    #  Event bus handlers                                                    #
    # --------------------------------------------------------------------- #

    def _register_event_bus_handlers(self) -> None:
        """Subscribe to remote whiteboard events."""
        self._bus.subscribe(self.EVT_STROKE_ADDED, self._on_remote_stroke_added)
        self._bus.subscribe(self.EVT_STROKE_UNDONE, self._on_remote_stroke_undone)
        self._bus.subscribe(self.EVT_STROKE_REDONE, self._on_remote_stroke_redone)
        self._bus.subscribe(self.EVT_BOARD_CLEARED, self._on_remote_board_cleared)

    # Remote event handlers -------------------------------------------------

    def _on_remote_stroke_added(self, payload: Dict[str, Any]) -> None:
        """Handler for strokes arriving from other users."""
        # Ignore our own events (they are processed locally already)
        if payload.get("user_id") == self._user_id:
            return

        try:
            stroke = Stroke.from_payload(payload)
        except Exception as exc:
            logger.error("Failed to parse remote stroke payload: %s", exc)
            return

        self._state.strokes.append(stroke)
        self.strokeAdded.emit(stroke)
        self._persist_autosave()

    def _on_remote_stroke_undone(self, payload: Dict[str, Any]) -> None:
        """Undo event coming from another user."""
        if payload.get("user_id") == self._user_id:
            return

        timestamp = payload.get("timestamp")
        stroke = self._pop_stroke_by_timestamp(timestamp)
        if stroke:
            self.strokeUndone.emit(stroke)
            self._state.undo_stack.append(stroke)
            self._persist_autosave()

    def _on_remote_stroke_redone(self, payload: Dict[str, Any]) -> None:
        """Redo event coming from another user."""
        if payload.get("user_id") == self._user_id:
            return

        timestamp = payload.get("timestamp")
        stroke = self._pop_from_undo_stack_by_timestamp(timestamp)
        if stroke:
            self._state.strokes.append(stroke)
            self.strokeRedone.emit(stroke)
            self._persist_autosave()

    def _on_remote_board_cleared(self, payload: Dict[str, Any]) -> None:
        """Board cleared by remote user."""
        if payload.get("user_id") == self._user_id:
            return

        self._state.clear()
        self.boardCleared.emit()
        self._persist_autosave()

    # --------------------------------------------------------------------- #
    #  Persistence                                                           #
    # --------------------------------------------------------------------- #

    def _persist_autosave(self) -> None:
        """Keep a lightweight backup of the current board on disk."""
        try:
            data = [stroke.to_payload() for stroke in self._state.strokes]
            self._autosave_file.write_text(json.dumps(data))
        except Exception as exc:
            logger.warning("Autosave failed: %s", exc)

    def _restore_autosave(self) -> None:
        """Load strokes from the autosave file, if present."""
        if not self._autosave_file.exists():
            return
        try:
            raw = json.loads(self._autosave_file.read_text())
            for item in raw:
                stroke = Stroke.from_payload(item)
                self._state.strokes.append(stroke)
                self.strokeAdded.emit(stroke)
        except Exception as exc:
            logger.error("Failed to restore whiteboard autosave: %s", exc)

    # --------------------------------------------------------------------- #
    #  Internal utilities                                                    #
    # --------------------------------------------------------------------- #

    def _pop_stroke_by_timestamp(self, ts: float) -> Optional[Stroke]:
        """Remove and return a stroke from strokes list by timestamp."""
        for idx in range(len(self._state.strokes) - 1, -1, -1):
            if abs(self._state.strokes[idx].timestamp - ts) < 1e-6:
                return self._state.strokes.pop(idx)
        return None

    def _pop_from_undo_stack_by_timestamp(self, ts: float) -> Optional[Stroke]:
        """Remove and return a stroke from undo stack by timestamp."""
        for idx in range(len(self._state.undo_stack) - 1, -1, -1):
            if abs(self._state.undo_stack[idx].timestamp - ts) < 1e-6:
                return self._state.undo_stack.pop(idx)
        return None

    def _push_to_undo_stack(self, cmd: "_AddStrokeCommand") -> None:
        """Maintain a bounded command history for smarter memory usage."""
        max_size = 1024  # Hard limit (enough for hours of drawing)
        if len(self._state.undo_stack) >= max_size:
            self._state.undo_stack.popleft()
        # We only keep the Stroke, not the Command, to save memory footprint.
        self._state.undo_stack.append(cmd.stroke)


# --------------------------------------------------------------------------- #
#  Commands                                                                   
# --------------------------------------------------------------------------- #

class _AddStrokeCommand:
    """
    Concrete command for adding a stroke.

    We purposefully implement a lightweight command to avoid excessive memory
    usage when thousands of points are being produced in a session.
    """

    def __init__(self, stroke: Stroke, state: WhiteboardState, vm: WhiteboardViewModel) -> None:
        self.stroke = stroke
        self._state = state
        self._vm = vm

    # ICommand interface ----------------------------------------------------

    def execute(self) -> None:
        self._state.strokes.append(self.stroke)
        self._vm.strokeAdded.emit(self.stroke)

    def undo(self) -> None:
        try:
            self._state.strokes.remove(self.stroke)
        except ValueError:
            logger.debug("Stroke already removed from state during undo")
        self._vm.strokeUndone.emit(self.stroke)
```