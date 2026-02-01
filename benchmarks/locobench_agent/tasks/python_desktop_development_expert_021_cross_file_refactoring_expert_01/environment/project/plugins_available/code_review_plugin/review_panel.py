```python
"""
FlockDesk – Code-Review Panel Plugin
-----------------------------------

This file implements the UI, View-Model, and Plugin glue code that turns the
code-review panel into a first-class citizen inside the FlockDesk desktop
orchestrator.  The panel enables collaborators to open diff snapshots, attach
inline comments, and publish review events onto the internal event bus.

Architecture
============
The plugin adheres to the MVVM pattern used throughout FlockDesk:

    ┌──────────────────┐
    │ DockWidget(Frame)│  (Qt View – CodeReviewPanelWidget)
    └──────────┬───────┘
               │ Qt signals/slots
    ┌──────────▼───────────┐
    │ CodeReviewViewModel  │  (Domain & state)
    └──────────┬───────────┘
               │ publish/subscribe
    ┌──────────▼───────────┐
    │    EventBus          │
    └──────────────────────┘

The code purposefully avoids any expensive parsing of diff files; it expects
the upstream service to deliver unified diff strings over the event bus or via
a file-drop operation.
"""
from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6 import QtCore, QtGui, QtWidgets

# --------------------------------------------------------------------------- #
# 3rd-party / FlockDesk imports (soft for static analysers)
# --------------------------------------------------------------------------- #
try:  # pragma: no-cover – these are available in a real FlockDesk runtime.
    from flockdesk.core.event_bus import EventBus, Event  # type: ignore
    from flockdesk.plugin_api import PluginBase, PluginContext  # type: ignore
    from flockdesk.ui.icons import get_icon  # type: ignore
except Exception:  # noqa: BLE001 – graceful degradation for linters
    class Event:  # dummy stand-in
        topic: str
        payload: dict

        def __init__(self, topic: str, payload: dict):
            self.topic, self.payload = topic, payload

    class EventBus:  # dummy stand-in
        def subscribe(self, *_a, **_kw):
            return lambda: None

        def publish(self, _event: Event):
            pass

    class PluginBase:  # dummy stand-in
        pass

    class PluginContext:  # dummy stand-in
        event_bus: EventBus = EventBus()

        class DocArea:
            Right = 2

        def add_dock_widget(self, *_a, **_kw):
            pass

        def remove_dock_widget(self, *_a, **_kw):
            pass

    def get_icon(_name: str) -> QtGui.QIcon:  # noqa: D401
        return QtGui.QIcon()

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
LOGGER = logging.getLogger("flockdesk.plugins.code_review_panel")
if not LOGGER.handlers:
    # When running inside the full app, the root logger is already configured.
    logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

# --------------------------------------------------------------------------- #
# Domain objects
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ReviewComment:
    """Represents a single inline code review comment."""
    file_path: Path
    line_number: int
    author: str
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def as_json(self) -> dict:
        return {
            "file": str(self.file_path),
            "line": self.line_number,
            "author": self.author,
            "message": self.message,
            "ts": self.timestamp.isoformat(timespec="seconds"),
        }


# --------------------------------------------------------------------------- #
# View-Model
# --------------------------------------------------------------------------- #
class CodeReviewViewModel(QtCore.QObject):
    """
    Acts as the binding layer between the UI and the domain/event-bus layer.

    Exposes high-level slots such as `load_diff()` or `add_comment()` and pushes
    updates to the view through Qt signals.
    """

    diff_loaded = QtCore.Signal(str, str)  # file_path, unified diff text
    comments_changed = QtCore.Signal(str, list)  # file_path, list[ReviewComment]
    error_occurred = QtCore.Signal(str)

    _SUBJECT_OPEN_DIFF = "code.review.open_diff"
    _SUBJECT_COMMENT_PUBLISHED = "code.review.comment"

    def __init__(self, event_bus: EventBus, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._bus = event_bus
        self._comments: Dict[Path, List[ReviewComment]] = {}
        self._current_file: Optional[Path] = None

        # Subscribe to diff open requests fired from other collaborators.
        self._sub_handle = self._bus.subscribe(
            topic=self._SUBJECT_OPEN_DIFF,
            handler=self._on_external_diff_opened,
        )

    # --------------------------------------------------------------------- #
    # Public API callable from the View
    # --------------------------------------------------------------------- #
    @QtCore.Slot(Path)
    def load_diff(self, file_path: Path) -> None:
        """
        Load a unified diff from disk and broadcast it locally.

        Parameters
        ----------
        file_path:
            Absolute path to the diff file to load.
        """
        try:
            diff_text = file_path.read_text(encoding="utf-8")
            self._current_file = file_path
            LOGGER.info("Loaded diff: %s (%d bytes)", file_path, len(diff_text))
            self.diff_loaded.emit(str(file_path), diff_text)
        except Exception as exc:  # noqa: BLE001 – capture any IO problem
            LOGGER.error("Failed to load diff '%s' – %s", file_path, exc, exc_info=True)
            self.error_occurred.emit(f"Failed to load diff: {exc}")

    @QtCore.Slot(int, str)
    def add_comment(self, line_number: int, message: str) -> None:
        """
        Append a new inline comment to the current diff file.

        The comment is stored locally **and** broadcast via the event bus so
        that all peers receive the update in real-time.
        """
        if self._current_file is None:
            self.error_occurred.emit("No diff is currently loaded.")
            return

        comment = ReviewComment(
            file_path=self._current_file,
            line_number=line_number,
            author=self._determine_author(),
            message=message,
        )
        self._comments.setdefault(self._current_file, []).append(comment)

        # Inform the local UI
        self.comments_changed.emit(str(self._current_file), self._comments[self._current_file])
        LOGGER.debug("Added comment on %s:%d", self._current_file, line_number)

        # Broadcast over event bus
        self._bus.publish(Event(self._SUBJECT_COMMENT_PUBLISHED, payload=comment.as_json()))

    def dispose(self) -> None:
        """Clean up any allocated resources / subscriptions."""
        try:
            self._sub_handle()  # Unsubscribe
        except Exception:  # noqa: BLE001
            pass

    # --------------------------------------------------------------------- #
    # Event-bus handlers
    # --------------------------------------------------------------------- #
    def _on_external_diff_opened(self, event: Event) -> None:
        """Handle a diff opened by another collaborator."""
        try:
            file_path = Path(event.payload["file"])
            diff_text = event.payload["diff"]
            self._current_file = file_path
            self.diff_loaded.emit(str(file_path), diff_text)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self.error_occurred.emit("Malformed event received on open_diff.")

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    @staticmethod
    def _determine_author() -> str:
        # Future: hook into presence service / profile
        return QtCore.QSettings().value("profile/username", "Anonymous")  # type: ignore[no-any-return]


# --------------------------------------------------------------------------- #
# Qt Widgets
# --------------------------------------------------------------------------- #
class _DiffViewer(QtWidgets.QPlainTextEdit):
    """Read-only text field with mono-space font for displaying unified diffs."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        font.setPointSizeF(font.pointSizeF() - 1)
        self.setFont(font)
        self.setWordWrapMode(QtGui.QTextOption.NoWrap)
        self.setPlaceholderText("Open a diff file to display its content…")


class CodeReviewPanelWidget(QtWidgets.QWidget):
    """
    Qt/Widget implementation of the code-review panel.

    The widget is purely presentation logic: it does not touch the event bus
    and delegates everything to the provided ViewModel (`vm`).
    """

    _LINE_ROLE = QtCore.Qt.UserRole + 1

    def __init__(self, vm: CodeReviewViewModel, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._vm = vm

        # ----------------------------------------------------------------- #
        # UI Elements
        # ----------------------------------------------------------------- #
        self._file_picker = QtWidgets.QPushButton(get_icon("file-open"), "Open Diff…")
        self._diff_viewer = _DiffViewer()
        self._comment_list = QtWidgets.QListWidget()
        self._comment_list.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        self._comment_editor = QtWidgets.QTextEdit()
        self._comment_editor.setFixedHeight(80)
        self._comment_editor.setPlaceholderText("Type inline comment…")

        self._line_input = QtWidgets.QSpinBox()
        self._line_input.setMinimum(1)
        self._line_input.setPrefix("Line ")

        self._btn_add_comment = QtWidgets.QPushButton(get_icon("send"), "Add Comment")
        self._btn_add_comment.setEnabled(False)

        # Layouting
        form = QtWidgets.QHBoxLayout()
        form.addWidget(self._line_input)
        form.addWidget(self._btn_add_comment, 1)

        side_bar = QtWidgets.QVBoxLayout()
        side_bar.addWidget(self._comment_list)
        side_bar.addLayout(form)
        side_bar.addWidget(self._comment_editor)

        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Horizontal)
        splitter.addWidget(self._diff_viewer)

        side_container = QtWidgets.QWidget()
        side_container.setLayout(side_bar)
        splitter.addWidget(side_container)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(self._file_picker)
        root.addWidget(splitter)

        # ----------------------------------------------------------------- #
        # Connections
        # ----------------------------------------------------------------- #
        self._file_picker.clicked.connect(self._on_browse_diff)
        self._btn_add_comment.clicked.connect(self._on_add_comment_clicked)

        # ViewModel -> View
        vm.diff_loaded.connect(self._on_diff_loaded)
        vm.comments_changed.connect(self._on_comments_changed)
        vm.error_occurred.connect(self._show_error)

        # Reactive: enable send button only when comment not empty
        self._comment_editor.textChanged.connect(
            lambda: self._btn_add_comment.setEnabled(bool(self._comment_editor.toPlainText().strip()))
        )

    # --------------------------------------------------------------------- #
    # ViewModel callbacks
    # --------------------------------------------------------------------- #
    def _on_diff_loaded(self, path_str: str, diff_text: str) -> None:
        self._diff_viewer.setPlainText(diff_text)
        self._comment_list.clear()
        self._line_input.setMaximum(max(1, diff_text.count("\n") + 1))
        self._comment_editor.clear()
        self._btn_add_comment.setEnabled(False)
        self.setWindowTitle(f"Code Review – {Path(path_str).name}")

    def _on_comments_changed(self, path_str: str, comments: Sequence[ReviewComment]) -> None:
        self._comment_list.clear()
        for comment in comments:
            itm = QtWidgets.QListWidgetItem(
                f"L{comment.line_number}: {comment.author} – {comment.message}"
            )
            itm.setData(self._LINE_ROLE, comment.line_number)
            self._comment_list.addItem(itm)

    def _show_error(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Code Review Error", message)

    # --------------------------------------------------------------------- #
    # Slots
    # --------------------------------------------------------------------- #
    @QtCore.Slot()
    def _on_browse_diff(self) -> None:
        """Open a file dialog so the user can pick a diff file from disk."""
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Unified Diff",
            str(Path.home()),
            "Patch Files (*.diff *.patch);;All Files (*)",
        )
        if fn:
            self._vm.load_diff(Path(fn))

    @QtCore.Slot()
    def _on_add_comment_clicked(self) -> None:
        line_no = self._line_input.value()
        message = self._comment_editor.toPlainText().strip()
        if not message:
            return  # Should not happen because of the button enable/disable logic.
        self._vm.add_comment(line_no, message)
        self._comment_editor.clear()


# --------------------------------------------------------------------------- #
# Plugin entry point
# --------------------------------------------------------------------------- #
class CodeReviewPanelPlugin(PluginBase):
    """
    Public plugin object discovered by FlockDesk’s plugin loader.

    The plugin owns the dock widget lifetime and wires the global menu / action
    integration.  All other logic is delegated to the ViewModel and Widget.
    """

    # Meta information used by the marketplace
    plugin_id = "fd.code_review_panel"
    api_version = "1.0"
    repo_url = "https://github.com/flockdesk/flockdesk-plugins"

    _DOCK_OBJECT_NAME = "fd.CodeReviewPanel"

    def __init__(self) -> None:  # noqa: D401 – simple constructor
        super().__init__()
        self._ctx: Optional[PluginContext] = None
        self._dock: Optional[QtWidgets.QDockWidget] = None
        self._vm: Optional[CodeReviewViewModel] = None

    # --------------------------------------------------------------------- #
    # PluginBase overrides
    # --------------------------------------------------------------------- #
    def activate(self, ctx: PluginContext) -> None:
        """Called by the framework once the plugin gets loaded."""
        self._ctx = ctx
        self._vm = CodeReviewViewModel(ctx.event_bus)

        panel = CodeReviewPanelWidget(self._vm)
        dock = QtWidgets.QDockWidget("Code Review", None)
        dock.setObjectName(self._DOCK_OBJECT_NAME)
        dock.setWidget(panel)
        dock.setWindowIcon(get_icon("code-review"))

        ctx.add_dock_widget(dock, area=ctx.DocArea.Right)
        self._dock = dock

        LOGGER.info("CodeReviewPanel activated.")

    def deactivate(self) -> None:
        """Clean up resources before the plugin is unloaded."""
        if self._dock and self._ctx:
            self._ctx.remove_dock_widget(self._dock)
            self._dock.deleteLater()
            self._dock = None

        if self._vm:
            self._vm.dispose()
            self._vm.deleteLater()
            self._vm = None

        LOGGER.info("CodeReviewPanel deactivated.")
```