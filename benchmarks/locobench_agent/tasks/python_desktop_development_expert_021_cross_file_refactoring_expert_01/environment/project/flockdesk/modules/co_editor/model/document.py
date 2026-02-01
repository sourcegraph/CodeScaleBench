```python
"""
flockdesk.modules.co_editor.model.document
=========================================

Domain model for a collaboratively-edited document used by the *Co-Editor*
micro-front-end.

The class below is **not** a full-blown operational-transform or CRDT
implementation—that lives in the service layer.  The goal of this module is to
encapsulate:

1.  Lightweight local state management (content, metadata, revision counters …)
2.  A persistence hook (JSON-file based fallback store for offline scenarios)
3.  Publication of high-level document events to the internal event-bus
4.  Thread-safe/async-safe mutation APIs (undo/redo, patch application, …)

The heavy lifting (conflict resolution, delta compression, cross-client
broadcasts) is delegated to the *co_editor.sync_engine* package; this object is
meant to be embedded inside view-models or background services.

Typical usage
-------------

    >>> from flockdesk.modules.co_editor.model.document import Document
    >>> doc = Document.open(Path("~/Notes/todo.md").expanduser())
    >>> doc.apply_patch(EditPatch(start=13, end=18, text="coffee"))
    >>> await doc.save()     # async!
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable, List, MutableSequence, Optional

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------#
#  Event-Bus Integration                                                     #
# ---------------------------------------------------------------------------#

try:  # pragma: no-cover – real bus provided by the FlockDesk core runtime
    from flockdesk.core.eventbus import EventBus
except ImportError:  # fallback stub for isolated testing
    class EventBus:  # type: ignore
        """Very small in-process pub/sub replacement used during unit tests."""

        def __init__(self) -> None:
            self._subs: dict[str, List[Callable[..., None]]] = {}

        def subscribe(self, topic: str, fn: Callable[..., None]) -> None:
            self._subs.setdefault(topic, []).append(fn)

        def publish(self, topic: str, *args, **kwargs) -> None:
            for fn in self._subs.get(topic, []):
                try:
                    fn(*args, **kwargs)
                except Exception:  # pylint: disable=broad-except
                    LOGGER.exception("Event handler %s failed", fn)


# ---------------------------------------------------------------------------#
#  Exceptions                                                                #
# ---------------------------------------------------------------------------#


class DocumentError(RuntimeError):
    """Base-class for *Document* specific errors."""


class RevisionMismatch(DocumentError):
    """Raised when a patch is applied against an outdated revision."""


class PersistenceError(DocumentError):
    """Any problem while reading/writing from the underlying store."""


# ---------------------------------------------------------------------------#
#  Data-Transfer Objects                                                     #
# ---------------------------------------------------------------------------#


@dataclass(frozen=True, slots=True)
class EditPatch:
    """
    A minimalistic *text* patch.

    start / end are *character* offsets (not lines).  For simplicity we rely on
    Python string slicing internally.
    """

    start: int
    end: int
    text: str
    base_revision: int | None = None  # Detect stale edits from the UI


@dataclass(slots=True)
class _HistoryItem:
    patch: EditPatch
    previous_content: str


# ---------------------------------------------------------------------------#
#  Document Implementation                                                   #
# ---------------------------------------------------------------------------#


class Document:
    """
    Local representation of a collaboratively editable document.

    Operations are guarded by an `asyncio.Lock` to protect against concurrent
    updates coming from network vs. UI threads.
    """

    EVENT_TOPIC_PREFIX = "co_editor.document"

    def __init__(
        self,
        *,
        doc_id: str,
        title: str,
        content: str,
        path: Optional[Path],
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        revision: int = 0,
        autosave_seconds: float = 15.0,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.id: str = doc_id
        self.title: str = title
        self._content: str = content
        self._path: Optional[Path] = path
        self.revision: int = revision
        self.created_at = created_at or datetime.now(tz=timezone.utc)
        self.updated_at = updated_at or self.created_at

        self._lock = asyncio.Lock()
        self._undo_stack: MutableSequence[_HistoryItem] = []
        self._redo_stack: MutableSequence[_HistoryItem] = []

        # infra
        self._event_bus: EventBus = event_bus or EventBus()
        self._autosave_seconds = autosave_seconds
        self._autosave_task: Optional[asyncio.Task[None]] = None
        self._shutdown = asyncio.Event()

        self._start_autosave_worker()

        LOGGER.debug(
            "Document %s (rev=%d) instantiated for %s",
            self.id,
            self.revision,
            self.title,
        )

    # --------------------------------------------------------------------- #
    #  Factory helpers                                                      #
    # --------------------------------------------------------------------- #

    @classmethod
    def new(cls, title: str, directory: Path | str | None = None) -> "Document":
        """
        Create a brand-new untitled document.

        Persistence kicks in only after the first *save()*.
        """
        path = None
        if directory:
            directory = Path(directory).expanduser().absolute()
        return cls(
            doc_id=str(uuid.uuid4()),
            title=title,
            content="",
            path=path,  # not saved yet
        )

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        event_bus: Optional[EventBus] = None,
        autosave_seconds: float = 15.0,
    ) -> "Document":
        """
        Load a document from a JSON-based store on disk.

        The payload layout on disk is intentionally naïve:

        {
            "id": "...",
            "title": "...",
            "content": "...",
            "revision": 42,
            "created_at": "...",
            "updated_at": "..."
        }
        """
        path = Path(path).expanduser().absolute()

        try:
            with path.open("r", encoding="utf-8") as fp:
                raw = json.load(fp)
        except (OSError, json.JSONDecodeError) as err:
            raise PersistenceError(f"Unable to read {path}") from err

        LOGGER.info("Opening document `%s` (rev=%d)", path.name, raw["revision"])

        return cls(
            doc_id=raw["id"],
            title=raw["title"],
            content=raw["content"],
            path=path,
            revision=raw["revision"],
            created_at=_as_dt(raw["created_at"]),
            updated_at=_as_dt(raw["updated_at"]),
            autosave_seconds=autosave_seconds,
            event_bus=event_bus,
        )

    # --------------------------------------------------------------------- #
    #  Public state accessors                                               #
    # --------------------------------------------------------------------- #

    @property
    def content(self) -> str:
        return self._content

    # NOTE: There is intentionally no public setter for *content*.  All
    # mutations must go through the patch APIs to guarantee revision handling.

    # --------------------------------------------------------------------- #
    #  Editing API                                                          #
    # --------------------------------------------------------------------- #

    async def apply_patch(self, patch: EditPatch) -> int:
        """
        Apply a **single** text patch and return the new revision number.

        If `patch.base_revision` is provided, a mismatch raises
        `RevisionMismatch` instead of silently accepting the change.
        """
        async with self._lock:
            if (
                patch.base_revision is not None
                and patch.base_revision != self.revision
            ):
                raise RevisionMismatch(
                    "Patch based on rev %s, current rev is %s",
                    patch.base_revision,
                    self.revision,
                )

            LOGGER.debug("Applying patch %s on rev %d", patch, self.revision)
            prev_content = self._content

            try:
                self._content = (
                    self._content[: patch.start] + patch.text + self._content[patch.end :]
                )
            except Exception as exc:  # pragma: no-cover
                # Reset to previous state on any unexpected failure
                self._content = prev_content
                raise DocumentError("Patch failed") from exc

            # update history
            self._undo_stack.append(_HistoryItem(patch=patch, previous_content=prev_content))
            self._redo_stack.clear()

            # bump rev & timestamps
            self.revision += 1
            self.updated_at = datetime.now(tz=timezone.utc)

            # publish
            self._publish("updated", self.snapshot())

            return self.revision

    async def undo(self) -> int:
        """Revert the last action (if any) and return the new revision."""
        async with self._lock:
            if not self._undo_stack:
                LOGGER.debug("Undo requested but history is empty")
                return self.revision

            hist = self._undo_stack.pop()
            self._redo_stack.append(
                _HistoryItem(
                    patch=hist.patch,
                    previous_content=self._content,
                )
            )
            self._content = hist.previous_content
            self.revision += 1
            self.updated_at = datetime.now(tz=timezone.utc)
            self._publish("undone", self.snapshot())
            return self.revision

    async def redo(self) -> int:
        """Re-apply an action that has just been undone."""
        async with self._lock:
            if not self._redo_stack:
                LOGGER.debug("Redo requested but redo stack is empty")
                return self.revision

            hist = self._redo_stack.pop()
            # we don't reuse apply_patch to avoid additional history entry
            prev = self._content
            self._content = (
                self._content[: hist.patch.start]
                + hist.patch.text
                + self._content[hist.patch.end :]
            )
            self._undo_stack.append(_HistoryItem(patch=hist.patch, previous_content=prev))
            self.revision += 1
            self.updated_at = datetime.now(tz=timezone.utc)
            self._publish("redone", self.snapshot())
            return self.revision

    # --------------------------------------------------------------------- #
    #  Autosave                                                             #
    # --------------------------------------------------------------------- #

    def _start_autosave_worker(self) -> None:
        if self._autosave_task is not None:  # already running
            return

        loop = asyncio.get_event_loop()
        self._autosave_task = loop.create_task(self._autosave_loop(), name=f"autosave-{self.id}")

    async def _autosave_loop(self) -> None:
        LOGGER.debug("Autosave task for %s started (interval=%.1fs)", self.id, self._autosave_seconds)
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._autosave_seconds)
                # .wait() completed, shutdown requested
                break
            except asyncio.TimeoutError:
                # periodic tick
                try:
                    await self.save()
                except Exception:  # pylint: disable=broad-except
                    LOGGER.exception("Autosave for %s failed", self.title)

    # --------------------------------------------------------------------- #
    #  Persistence                                                          #
    # --------------------------------------------------------------------- #

    async def save(self, path: Optional[Path | str] = None) -> None:
        """
        Persist the current state to *path* (if given) or the
        previously-associated path.

        The actual write happens in a thread-pool to avoid blocking the event-loop.
        """
        if path is not None:
            self._path = Path(path).expanduser().absolute()

        if self._path is None:
            raise PersistenceError("No path specified for saving")

        payload = {
            "id": self.id,
            "title": self.title,
            "content": self._content,
            "revision": self.revision,
            "created_at": self.created_at.isoformat(),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,  # default thread-pool
                _write_json_atomic,
                self._path,
                payload,
            )
            LOGGER.debug("Document `%s` successfully saved", self._path)
            self._publish("saved", self.snapshot())
        except (OSError, json.JSONDecodeError) as err:
            raise PersistenceError(f"Unable to write to {self._path}") from err

    async def close(self) -> None:
        """
        Gracefully stop background workers (autosave) and publish a *closed*
        event.  Does **not** remove the document from disk.
        """
        LOGGER.debug("Closing document %s", self.id)
        self._shutdown.set()
        if self._autosave_task:
            await self._autosave_task
        self._publish("closed", {"id": self.id})

    # --------------------------------------------------------------------- #
    #  Context-manager helper                                               #
    # --------------------------------------------------------------------- #

    @asynccontextmanager
    async def edit(self) -> AsyncIterator["Document"]:
        """
        A convenience async-context-manager that yields the document locked for
        mutation—useful for batching several changes without interleaving
        network updates.
        """
        async with self._lock:
            yield self

    # --------------------------------------------------------------------- #
    #  Utilities                                                            #
    # --------------------------------------------------------------------- #

    def snapshot(self) -> dict:
        """Return the *current* state as plain Python dict (deep-copy safe)."""
        return {
            "id": self.id,
            "title": self.title,
            "content": self._content,
            "revision": self.revision,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    # --------------------------------------------------------------------- #
    #  Internal helpers                                                     #
    # --------------------------------------------------------------------- #

    def _publish(self, verb: str, payload: dict | None = None) -> None:
        topic = f"{self.EVENT_TOPIC_PREFIX}.{self.id}.{verb}"
        self._event_bus.publish(topic, payload or {})
        LOGGER.debug("Published event %s", topic)


# ---------------------------------------------------------------------------#
#  Helper functions                                                          #
# ---------------------------------------------------------------------------#


def _as_dt(value: str | float | int) -> datetime:
    """Parse an ISO 8601 date or a nanosecond epoch into a *datetime*."""
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return datetime.fromisoformat(value)


def _write_json_atomic(path: Path, payload: dict) -> None:
    """
    Write *payload* to *path* using an **atomic-rename** strategy to avoid
    partial files in case of crashes.
    """
    tmp = Path(f"{path}.{int(time.time() * 1000)}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX
```