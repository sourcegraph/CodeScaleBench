```python
"""
FlockDesk – Social Workspace Orchestrator
----------------------------------------

Co-Editor / ViewModel layer
===========================

This module contains the MVVM *View-Model* that bridges the Qt front-end
(co_editor.widgets.editor_view) with the underlying domain model
(co_editor.model.document) and the shared event-bus used for real-time
collaboration.

Responsibilities
----------------
1.  Provide reactive Qt properties (content, path, isModified…) that the
    view can bind to.
2.  Translate user-intent coming from the view (open/save/undo/redo …)
    into domain-level commands.
3.  Listen for and apply remote changes that arrive through the internal
    event-bus → keeps local document in sync with peers.
4.  Handle optimistic concurrency + conflict resolution (last-write-wins
    fallback).

The class is deliberately *headless*; all UI widgets must talk to it via
signals/slots or property bindings.  This ensures the co-editor can be
embedded in other shells (stand-alone window, tabbed dock, plug-in, …)
without recompilation.

Author  : FlockDesk Core Team
License : MIT
"""

from __future__ import annotations

import json
import logging
import pathlib
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Property, Signal, Slot, QMutex, QMutexLocker

# ───────────────────────────────────────────────────────────────────────────────
# Internal stubs (to be provided by other FlockDesk packages)
# -----------------------------------------------------------------------------


class EventBus:
    """
    Simplified publish/subscribe interface.

    The real implementation lives in `flockdesk.core.bus` and offers a fully
    typed API plus automatic process-boundary marshalling.  For the sake of
    keeping this module self-contained we re-declare only the subset we need.
    """

    def subscribe(self, topic: str, callback) -> None:
        raise NotImplementedError

    def publish(self, topic: str, payload) -> None:
        raise NotImplementedError


class DocumentConflictError(RuntimeError):
    """Raised when two conflicting remote changes cannot be merged automatically."""


# ───────────────────────────────────────────────────────────────────────────────
# Domain model
# -----------------------------------------------------------------------------


@dataclass
class DocumentSnapshot:
    """
    Immutable document snapshot used for optimistic concurrency.

    Snapshots are exchanged over the event-bus and therefore must be JSON
    serialisable. The `to_json` / `from_json` helpers keep the wire-format
    stable across micro-services.
    """

    path: str
    content: str
    version: int
    modified_at: float

    # ------------------------------------------------------------------ factory

    @classmethod
    def initial(cls, path: str = "") -> "DocumentSnapshot":
        return cls(path=path, content="", version=0, modified_at=time.time())

    # ------------------------------------------------------------------- serial

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, serialized: str) -> "DocumentSnapshot":
        data = json.loads(serialized)
        return cls(**data)


class EditorModel:
    """
    Headless document editor.

    Thread-safe, single-writer model that supports basic operations needed by
    the View-Model.  In the production build this class is more sophisticated
    (OT, CRDT, roles/permissions…) but here we only need the minimal API.
    """

    _lock: QMutex
    _snapshot: DocumentSnapshot

    def __init__(self, snapshot: Optional[DocumentSnapshot] = None) -> None:
        self._lock = QMutex()
        self._snapshot = snapshot or DocumentSnapshot.initial()
        self._logger = logging.getLogger(self.__class__.__name__)

    # ---------------------------------------------------------------- snapshot

    def snapshot(self) -> DocumentSnapshot:
        with QMutexLocker(self._lock):
            return DocumentSnapshot(
                path=self._snapshot.path,
                content=self._snapshot.content,
                version=self._snapshot.version,
                modified_at=self._snapshot.modified_at,
            )

    # ---------------------------------------------------------------- mutate

    def apply_local_edit(self, new_content: str) -> DocumentSnapshot:
        """
        Applies a local edit performed by the user.  Increments version counter
        so remote peers can detect stale updates.
        """
        with QMutexLocker(self._lock):
            self._snapshot = DocumentSnapshot(
                path=self._snapshot.path,
                content=new_content,
                version=self._snapshot.version + 1,
                modified_at=time.time(),
            )
            self._logger.debug("Local edit applied → v%s", self._snapshot.version)
            return self._snapshot

    def apply_remote_snapshot(self, incoming: DocumentSnapshot) -> DocumentSnapshot:
        """
        Merge remote state.  If incoming version is older we ignore it, if newer
        we accept.  On equal version but diverging content raise conflict.
        """
        with QMutexLocker(self._lock):
            if incoming.version < self._snapshot.version:
                self._logger.debug(
                    "Ignoring stale remote snapshot (remote v%s < local v%s)",
                    incoming.version,
                    self._snapshot.version,
                )
                return self._snapshot

            if incoming.version == self._snapshot.version:
                if incoming.content != self._snapshot.content:
                    # Diverged at same version: conflict
                    self._logger.warning("Conflict detected @v%s", incoming.version)
                    raise DocumentConflictError
                return self._snapshot  # identical – nothing to do

            # Remote is newer → accept wholesale
            self._logger.debug("Remote snapshot accepted → v%s", incoming.version)
            self._snapshot = incoming
            return self._snapshot

    # ---------------------------------------------------------------- file I/O

    def load_from_disk(self, path: str) -> DocumentSnapshot:
        """Blocking disk read (caller should off-load to thread‐pool)."""
        data = pathlib.Path(path).read_text(encoding="utf-8")
        with QMutexLocker(self._lock):
            self._snapshot = DocumentSnapshot(
                path=path, content=data, version=0, modified_at=time.time()
            )
            return self._snapshot

    def save_to_disk(self, path: Optional[str] = None) -> None:
        """Blocking disk write."""
        with QMutexLocker(self._lock):
            target = pathlib.Path(path or self._snapshot.path)
            target.write_text(self._snapshot.content, encoding="utf-8")
            self._snapshot = DocumentSnapshot(
                path=str(target),
                content=self._snapshot.content,
                version=self._snapshot.version,
                modified_at=time.time(),
            )
            self._logger.debug("Document saved to %s", target)


# ───────────────────────────────────────────────────────────────────────────────
# View-Model
# -----------------------------------------------------------------------------


class EditorViewModel(QObject):
    """
    Qt friendly *View-Model* for the collaborative editor.

    Exposes properties that the QtQuick / QWidget front-ends can data-bind to
    and emits signals whenever the underlying model changes.
    """

    # --------------------------- signals (notify=) ----------------------------
    contentChanged = Signal(str)
    pathChanged = Signal(str)
    modifiedChanged = Signal(bool)
    titleChanged = Signal(str)
    remoteChangeReceived = Signal(str)  # JSON snapshot → view may animate diff

    # ------------------------------ constructor -------------------------------

    def __init__(self, bus: EventBus, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model = EditorModel()
        self._bus = bus
        self._logger = logging.getLogger(self.__class__.__name__)
        self._is_modified_local = False

        # Subscribe to remote events
        self._bus.subscribe("co_editor.snapshot", self._on_bus_snapshot)

    # --------------------------- Qt properties -------------------------------

    def _get_content(self) -> str:  # noqa: D401
        return self._model.snapshot().content

    def _set_content(self, new_content: str) -> None:
        snapshot = self._model.apply_local_edit(new_content)
        self._is_modified_local = True
        self.contentChanged.emit(snapshot.content)
        self.modifiedChanged.emit(True)
        self._publish_snapshot(snapshot)

    content = Property(str, _get_content, _set_content, notify=contentChanged)

    # ..........................................................................

    def _get_path(self) -> str:
        return self._model.snapshot().path

    path = Property(str, _get_path, notify=pathChanged)

    # ..........................................................................

    def _get_modified(self) -> bool:
        return self._is_modified_local

    modified = Property(bool, _get_modified, notify=modifiedChanged)

    # ..........................................................................

    def _get_title(self) -> str:
        p = pathlib.Path(self._get_path()) if self._get_path() else pathlib.Path("Untitled")
        return f"{p.name}{'*' if self._is_modified_local else ''}"

    title = Property(str, _get_title, notify=titleChanged)

    # ------------------------------ commands ----------------------------------

    @Slot()
    def new_document(self) -> None:
        """Creates a blank document (without touching the disk)."""
        self._logger.info("Creating new document")
        self._model = EditorModel()  # discard previous
        self._is_modified_local = False
        self._emit_full_refresh()

    # ..........................................................................

    @Slot(str)
    def open_document(self, path: str) -> None:
        """Loads a document from disk on the caller thread."""
        try:
            self._logger.info("Opening %s", path)
            self._model.load_from_disk(path)
        except (IOError, FileNotFoundError) as exc:
            self._logger.error("Cannot open %s – %s", path, exc, exc_info=True)
            return

        self._is_modified_local = False
        self._emit_full_refresh()
        self._publish_snapshot(self._model.snapshot())

    # ..........................................................................

    @Slot()
    def save_document(self) -> None:
        """Saves the current document in-place."""
        if not self._get_path():
            # UI should call *save_as* first
            self._logger.warning("No path set; redirecting to save_as")
            return

        try:
            self._model.save_to_disk()
        except IOError as exc:
            self._logger.error("Save failed – %s", exc, exc_info=True)
            return

        self._is_modified_local = False
        self.modifiedChanged.emit(False)
        self.titleChanged.emit(self._get_title())

    # ..........................................................................

    @Slot(str)
    def save_document_as(self, path: str) -> None:
        """Saves the current document to a new path."""
        try:
            self._model.save_to_disk(path)
        except IOError as exc:
            self._logger.error("Save-as failed – %s", exc, exc_info=True)
            return

        self.pathChanged.emit(path)
        self._is_modified_local = False
        self.modifiedChanged.emit(False)
        self.titleChanged.emit(self._get_title())

    # ..........................................................................

    @Slot()
    def undo(self) -> None:
        """
        Undo is non-trivial with CRDTs, but for the minimal implementation we
        just log a warning.  Real implementation would integrate with *pyot*.
        """
        self._logger.warning("Undo requested – not implemented in stub")

    @Slot()
    def redo(self) -> None:
        self._logger.warning("Redo requested – not implemented in stub")

    # ------------------------------ private -----------------------------------

    def _emit_full_refresh(self) -> None:
        """Notify view of complete model replacement."""
        snap = self._model.snapshot()
        self.contentChanged.emit(snap.content)
        self.pathChanged.emit(snap.path)
        self.modifiedChanged.emit(self._is_modified_local)
        self.titleChanged.emit(self._get_title())

    # ..........................................................................

    def _publish_snapshot(self, snapshot: DocumentSnapshot) -> None:
        """Broadcast local state to peers."""
        try:
            self._bus.publish("co_editor.snapshot", snapshot.to_json())
            self._logger.debug("Snapshot v%s published", snapshot.version)
        except Exception as exc:  # noqa: BLE001
            self._logger.error("Failed to publish snapshot – %s", exc, exc_info=True)

    # ..........................................................................

    def _on_bus_snapshot(self, payload: str) -> None:
        """
        Executed in bus thread – must be thread-safe.
        Dispatch to Qt main thread for model mutation if needed.
        """

        def _process() -> None:
            try:
                incoming = DocumentSnapshot.from_json(payload)
                self._logger.debug(
                    "Received remote snapshot v%s (path=%s)",
                    incoming.version,
                    incoming.path,
                )
                self._model.apply_remote_snapshot(incoming)
            except DocumentConflictError:
                self._logger.error("Unresolvable conflict – keeping local state")
                return

            # Notify UI
            self.remoteChangeReceived.emit(incoming.content)
            self.contentChanged.emit(incoming.content)
            self.modifiedChanged.emit(self._is_modified_local)
            self.titleChanged.emit(self._get_title())

        # Move to main thread if invoked from another thread
        if threading.current_thread() is threading.main_thread():
            _process()
        else:
            self.metaObject().invokeMethod(self, _process, Qt.QueuedConnection)

    # ------------------------- drag-and-drop helper ---------------------------

    @Slot("QMimeData", result=bool)
    def can_import_mime(self, mime) -> bool:  # noqa: ANN001
        """
        Quick util for the view layer – checks if the payload contains a file
        drop we can open.  Keeps MIME logic encapsulated in the VM.
        """
        return mime.hasUrls()

    @Slot("QMimeData")
    def import_mime(self, mime) -> None:  # noqa: ANN001
        """Handles external drop of a single text file."""
        urls = mime.urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        self.open_document(path)

    # ------------------------- debug / diagnostics ---------------------------

    @Slot(result=str)
    def dump_state(self) -> str:
        """
        Returns JSON debug string of the current snapshot.
        The inspector panel uses this to render diagnostics.
        """
        snap = self._model.snapshot()
        meta = {
            "path": snap.path,
            "version": snap.version,
            "modified_at": datetime.fromtimestamp(snap.modified_at).isoformat(),
            "length": len(snap.content),
        }
        debug = json.dumps(meta, indent=2)
        self._logger.debug("State dump requested\n%s", debug)
        return debug


# ───────────────────────────────────────────────────────────────────────────────
# Module init
# -----------------------------------------------------------------------------


def _configure_logging() -> None:
    root = logging.getLogger(__name__)
    if not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(h)
    root.setLevel(logging.INFO)


_configure_logging()
```