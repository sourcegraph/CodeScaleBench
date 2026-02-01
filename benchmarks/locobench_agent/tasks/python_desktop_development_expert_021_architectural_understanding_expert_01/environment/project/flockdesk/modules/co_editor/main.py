```python
"""
FlockDesk – Co-Editor Micro-Frontend
flockdesk/modules/co_editor/main.py

This module bootstraps the co-editing micro-frontend, exposing a Qt based UI
backed by an event-driven, CRDT-powered document model.  The micro-frontend
is completely decoupled from the rest of the desktop suite and communicates
exclusively over the internal event-bus.

╭───────────────────────────────────────────╮
│  Dependency Diagram (simplified)          │
├────────────────────────────┬──────────────┤
│ EventBus (core)            │ <-> CoEditor │
│ ├─ publish() / subscribe() │              │
├────────────────────────────┴──────────────┤
│ CoEditor                      ┌─────────┐ │
│ ├─ Controller  ──────────────▶│ View    │ │
│ ├─ ViewModel (Observable)     └─────────┘ │
│ └─ CRDTDocument (Domain)                    │
╰───────────────────────────────────────────╯

Notes:
    • “CRDTDocument” is a *very* thin WYSIWYG-agnostic representation of a
      text buffer implementing the RGA (Replicated Growable Array) algorithm.
      In production it would be swapped for a mature library (e.g., Ypy).
    • All Qt-widgets live on the GUI thread; event-bus callbacks are proxied
      via signals to avoid thread contention.

Author:  FlockDesk Team
License: MIT
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QMutex, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QWidget

# --------------------------------------------------------------------------- #
# Logging Setup
# --------------------------------------------------------------------------- #

_logger = logging.getLogger("flockdesk.co_editor")
_logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Event-Bus – Minimal façade
# --------------------------------------------------------------------------- #

class EventBus:
    """
    Extremely simplified event-bus abstraction.  The real implementation is
    application-wide and thread-safe.  We keep the interface identical so that
    swapping to the production bus is trivial.
    """

    _SUBSCRIBERS: Dict[str, List[Callable[[str, Dict[str, Any]], None]]] = {}
    _LOCK = threading.Lock()

    @classmethod
    def subscribe(cls, topic: str, handler: Callable[[str, Dict[str, Any]], None]) -> None:
        with cls._LOCK:
            cls._SUBSCRIBERS.setdefault(topic, []).append(handler)
        _logger.debug("Subscribed %s to topic %s", handler, topic)

    @classmethod
    def publish(cls, topic: str, payload: Dict[str, Any]) -> None:
        with cls._LOCK:
            subscribers = cls._SUBSCRIBERS.get(topic, []).copy()
        for sub in subscribers:
            try:
                sub(topic, payload)
            except Exception:
                _logger.exception("Unhandled exception in event handler for topic %s", topic)


# --------------------------------------------------------------------------- #
# Domain Model – Very small RGA CRDT demo
# --------------------------------------------------------------------------- #

@dataclass
class _RGAElement:
    id: str
    char: str
    tombstone: bool = False


class CRDTDocument:
    """
    Replicated Growable Array implementation (highly pruned).
    This is *not* production grade but demonstrates intent.
    """

    def __init__(self, document_id: str):
        self.document_id = document_id
        self._elements: List[_RGAElement] = []
        self._index: Dict[str, int] = {}
        self._lock = threading.RLock()

    # -------------- Public API ------------------------------------------------

    def insert(self, char: str, left_id: Optional[str]) -> str:
        with self._lock:
            elem_id = uuid.uuid4().hex
            if left_id is None:
                idx = 0
            else:
                idx = self._index[left_id] + 1
            elem = _RGAElement(id=elem_id, char=char)
            self._elements.insert(idx, elem)
            self._reindex(start=idx)
            return elem_id

    def delete(self, elem_id: str) -> None:
        with self._lock:
            idx = self._index.get(elem_id)
            if idx is None:
                return
            self._elements[idx].tombstone = True

    def to_string(self) -> str:
        with self._lock:
            return "".join(e.char for e in self._elements if not e.tombstone)

    # -------------- Replication ----------------------------------------------

    def apply_remote_insert(self, elem_id: str, char: str, left_id: Optional[str]) -> None:
        with self._lock:
            if elem_id in self._index:  # duplicate
                return
            if left_id is None:
                idx = 0
            else:
                idx = self._index.get(left_id, -1) + 1
            elem = _RGAElement(id=elem_id, char=char)
            self._elements.insert(idx, elem)
            self._reindex(start=idx)

    def apply_remote_delete(self, elem_id: str) -> None:
        self.delete(elem_id)

    # -------------- Internal helpers -----------------------------------------

    def _reindex(self, start: int = 0) -> None:
        for idx in range(start, len(self._elements)):
            self._index[self._elements[idx].id] = idx


# --------------------------------------------------------------------------- #
# ViewModel
# --------------------------------------------------------------------------- #

class CoEditorViewModel(QObject):
    """
    Acts as the observable state for the view layer.  Every field that may
    change is exposed through Qt signals to keep the UI reactive.
    """

    documentChanged = Signal(str)
    connectionStatusChanged = Signal(str)

    def __init__(self, document: CRDTDocument, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._document = document
        self._connection_status: str = "offline"

    # --- property: documentText ----------------------------------------------

    @property
    def documentText(self) -> str:  # noqa: N802
        return self._document.to_string()

    def updateDocument(self) -> None:  # noqa: N802
        """Emit signal indicating the document changed."""
        self.documentChanged.emit(self._document.to_string())

    # --- property: connectionStatus ------------------------------------------

    @property
    def connectionStatus(self) -> str:  # noqa: N802
        return self._connection_status

    @connectionStatus.setter
    def connectionStatus(self, value: str) -> None:  # noqa: N802
        if value != self._connection_status:
            self._connection_status = value
            self.connectionStatusChanged.emit(value)


# --------------------------------------------------------------------------- #
# Controller
# --------------------------------------------------------------------------- #

class CoEditorController(QObject):
    """
    Bridges the event-bus and the ViewModel (MVVM).  All heavy lifting, i.e.,
    CRDT operations, incoming network changes, autosave, happens here.
    """

    # -------- Signals forwarded to UI thread ---------------------------------
    remoteInsert = Signal(str, str, object)    # elem_id, char, left_id
    remoteDelete = Signal(str)                 # elem_id

    AUTOSAVE_INTERVAL_SEC = 30

    def __init__(self, document_id: str, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.document = CRDTDocument(document_id=document_id)
        self.viewmodel = CoEditorViewModel(self.document, parent=self)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(self.AUTOSAVE_INTERVAL_SEC * 1000)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

        # Create background worker for event-bus IO ---------------------------
        self._io_thread = _EventBusWorkerThread(document_id=document_id)
        self._io_thread.remoteInsert.connect(self._on_remote_insert)
        self._io_thread.remoteDelete.connect(self._on_remote_delete)
        self._io_thread.connectionStatusChanged.connect(self._on_connection_status)

        self.remoteInsert.connect(self._apply_remote_insert)  # internal Qt thread hop
        self.remoteDelete.connect(self._apply_remote_delete)

        self._io_thread.start()

    # --------------------------------------------------------------------- #
    # Local Editing (UI → Controller)                                       #
    # --------------------------------------------------------------------- #

    @Slot(int, str, str)
    def local_insert(self, idx: int, char: str, left_id: Optional[str]) -> None:
        """
        Called by the view when the local user inserts a character.  idx is
        present for the UI but not required by the CRDT.  We broadcast the op
        to other peers via the event-bus.
        """
        new_elem_id = self.document.insert(char=char, left_id=left_id)
        self.viewmodel.updateDocument()

        EventBus.publish(
            topic=f"doc.{self.document.document_id}.insert",
            payload={
                "id": new_elem_id,
                "char": char,
                "left_id": left_id,
            },
        )

    @Slot(str)
    def local_delete(self, elem_id: str) -> None:
        self.document.delete(elem_id)
        self.viewmodel.updateDocument()

        EventBus.publish(
            topic=f"doc.{self.document.document_id}.delete",
            payload={
                "id": elem_id,
            },
        )

    # --------------------------------------------------------------------- #
    # Remote Editing (Controller IO thread → Qt UI thread)                  #
    # --------------------------------------------------------------------- #

    @Slot(str, str, object)
    def _apply_remote_insert(self, elem_id: str, char: str, left_id: Optional[str]) -> None:
        self.document.apply_remote_insert(elem_id=elem_id, char=char, left_id=left_id)
        self.viewmodel.updateDocument()

    @Slot(str)
    def _apply_remote_delete(self, elem_id: str) -> None:
        self.document.apply_remote_delete(elem_id)
        self.viewmodel.updateDocument()

    # --------------------------------------------------------------------- #
    # Autosave                                                              #
    # --------------------------------------------------------------------- #

    def _autosave(self) -> None:
        try:
            content = self.document.to_string()
            # This would go to the user's profile / cloud sync etc.
            path = f"/tmp/flockdesk_autosave_{self.document.document_id}.txt"
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(content)
            _logger.debug("Autosaved document %s (%d bytes) → %s", self.document.document_id, len(content), path)
        except Exception:
            _logger.exception("Autosave failed for document %s", self.document.document_id)

    # --------------------------------------------------------------------- #
    # Event-bus thread callbacks                                            #
    # --------------------------------------------------------------------- #

    @Slot(str, str, object)
    def _on_remote_insert(self, elem_id: str, char: str, left_id: Optional[str]) -> None:
        self.remoteInsert.emit(elem_id, char, left_id)

    @Slot(str)
    def _on_remote_delete(self, elem_id: str) -> None:
        self.remoteDelete.emit(elem_id)

    @Slot(str)
    def _on_connection_status(self, status: str) -> None:
        self.viewmodel.connectionStatus = status

    # --------------------------------------------------------------------- #
    # Shutdown                                                              #
    # --------------------------------------------------------------------- #

    def shutdown(self) -> None:
        self._autosave_timer.stop()
        self._io_thread.stop()
        self._io_thread.wait(2000)


# --------------------------------------------------------------------------- #
# Event-Bus Worker (runs in background thread)                                #
# --------------------------------------------------------------------------- #

class _EventBusWorkerThread(threading.Thread, QObject):
    """
    Long-lived thread subscribed to document topics.  We could have used
    QThread but bundling with QObject lets us re-emit signals easily.
    """

    remoteInsert = Signal(str, str, object)
    remoteDelete = Signal(str)
    connectionStatusChanged = Signal(str)

    POLL_INTERVAL_SEC = 0.5

    def __init__(self, document_id: str) -> None:
        QObject.__init__(self)
        threading.Thread.__init__(self, daemon=True, name=f"CoEditor-EventBus-{document_id}")

        self._document_id = document_id
        self._stop_evt = threading.Event()
        self._queue: "queue.Queue[tuple[str, dict[str, Any]]]" = queue.Queue()

        # Subscribe to event-bus
        EventBus.subscribe(f"doc.{self._document_id}.insert", self._enqueue_event)
        EventBus.subscribe(f"doc.{self._document_id}.delete", self._enqueue_event)

    # ------------------------------------------------------------------ #

    def _enqueue_event(self, topic: str, payload: Dict[str, Any]) -> None:
        self._queue.put((topic, payload))

    def stop(self) -> None:
        self._stop_evt.set()

    # ------------------------------------------------------------------ #

    def run(self) -> None:
        self.connectionStatusChanged.emit("online")
        _logger.info("Event-bus worker started for document %s", self._document_id)
        try:
            while not self._stop_evt.is_set():
                try:
                    topic, payload = self._queue.get(timeout=self.POLL_INTERVAL_SEC)
                except queue.Empty:
                    continue

                if topic.endswith(".insert"):
                    self.remoteInsert.emit(payload["id"], payload["char"], payload.get("left_id"))
                elif topic.endswith(".delete"):
                    self.remoteDelete.emit(payload["id"])

        except Exception:
            _logger.exception("Fatal error in event-bus worker thread")
        finally:
            self.connectionStatusChanged.emit("offline")
            _logger.info("Event-bus worker stopped for document %s", self._document_id)


# --------------------------------------------------------------------------- #
# Qt View (extremely stripped down)                                           #
# --------------------------------------------------------------------------- #

class _CoEditorWidget(QWidget):
    """
    Minimal text widget hooked up to the ViewModel.  Real implementation would
    use a full code-editor widget (Qsci, Monaco, etc.) and expose ‘left_id’
    mapping between buffer index and CRDT IDs.
    """

    def __init__(self, controller: CoEditorController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._viewmodel = controller.viewmodel

        self._text_edit = QTextEdit(self)
        self._text_edit.setAcceptRichText(False)
        self._text_edit.setLineWrapMode(QTextEdit.NoWrap)

        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self._text_edit)

        # Bind viewmodel → view
        self._viewmodel.documentChanged.connect(self._on_document_changed)

        # Bind user actions → controller
        self._text_edit.textChanged.connect(self._on_local_text_changed)

        # Initial populate
        self._text_edit.setPlainText(self._viewmodel.documentText)

        self._mutex = QMutex()
        self._updating_from_remote = False

    # ------------------------------------------------------------------ #
    # ViewModel callbacks                                                #
    # ------------------------------------------------------------------ #

    @Slot(str)
    def _on_document_changed(self, text: str) -> None:
        self._mutex.lock()
        try:
            self._updating_from_remote = True
            cursor_pos = self._text_edit.textCursor().position()
            self._text_edit.setPlainText(text)
            # Try to keep caret stable
            cursor = self._text_edit.textCursor()
            cursor.setPosition(min(cursor_pos, len(text)))
            self._text_edit.setTextCursor(cursor)
        finally:
            self._updating_from_remote = False
            self._mutex.unlock()

    # ------------------------------------------------------------------ #
    # Local Editing                                                      #
    # ------------------------------------------------------------------ #

    @Slot()
    def _on_local_text_changed(self) -> None:
        if self._updating_from_remote:
            return
        # Naïve diff–ing for demo. Real implementation uses incremental ops.
        text = self._text_edit.toPlainText()
        doc_text = self._viewmodel.documentText

        if len(text) > len(doc_text):  # insert
            idx = next(i for i in range(len(text)) if doc_text[i:i + 1] != text[i])
            char = text[idx]
            left_id = None  # For demo we ignore left_id
            self._controller.local_insert(idx, char, left_id)
        elif len(text) < len(doc_text):  # delete
            idx = next(i for i in range(len(doc_text)) if doc_text[i:i + 1] != text[i:i + 1])
            # Without CRDT mapping we cannot get elem_id; drop to full sync
            _logger.debug("Full document diff delete at idx=%d (not mapped)", idx)
            # TODO: Build index<->elem_id mapping

    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:  # noqa: N802
        self._controller.shutdown()
        super().closeEvent(event)


# --------------------------------------------------------------------------- #
# Entry API (Plugin Hooks)                                                    #
# --------------------------------------------------------------------------- #

def launch(document_id: Optional[str] = None) -> None:
    """
    Standard plugin entry-point invoked by the FlockDesk shell.

    Args:
        document_id: Existing document session.  If None, a new session is
                     created and announced via the event-bus.
    """
    app = QApplication.instance() or QApplication([])

    if document_id is None:
        document_id = uuid.uuid4().hex
        _logger.info("Created new document session: %s", document_id)
        EventBus.publish("co_editor.session.created", {"id": document_id})

    controller = CoEditorController(document_id=document_id)
    widget = _CoEditorWidget(controller)
    widget.setWindowTitle(f"FlockDesk – Co-Editor [{document_id[:8]}]")
    widget.resize(800, 600)
    widget.show()

    # Only exec_ if we created the QApplication
    if QApplication.instance() == app and not app.property("_flockdesk_embedded"):
        _logger.info("Starting Co-Editor Qt event-loop.")
        app.exec()


# If the module is launched standalone via `python -m ...`
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    launch()
```