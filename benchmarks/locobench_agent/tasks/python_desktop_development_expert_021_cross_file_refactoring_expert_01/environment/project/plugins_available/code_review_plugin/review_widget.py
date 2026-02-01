```python
"""
FlockDesk – Code-Review Panel Plugin
===================================

This file implements the GUI layer (“View”) of the Code-Review plugin.
The widget presents a two-pane diff viewer with an attachable comments
sidebar.  It follows an MVVM pattern:

    ┌─────────────────────┐
    │  CodeReviewWidget   │  (Qt View)
    └─────────────────────┘
               ▲
               │ binds / signals
               ▼
    ┌─────────────────────┐
    │ CodeReviewViewModel │  (business logic)
    └─────────────────────┘
               ▲
               │  domain objects / commands
               ▼
    ┌─────────────────────┐
    │   Event   Bus       │  (application backbone)
    └─────────────────────┘

The widget does *not* talk to other plugins or services directly—it only
publishes/consumes events through the shared event-bus that the host
injects via the plugin context.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

# ---------------------------------------------------------------------------#
# Domain / DTOs
# ---------------------------------------------------------------------------#


@dataclass(slots=True, frozen=True)
class ReviewComment:
    """
    Immutable representation of a single code-review comment.
    """
    cid: str
    author: str
    line_no: int
    text: str
    created_at: datetime.datetime = datetime.datetime.utcnow()

    def short_repr(self, maxlen: int = 72) -> str:
        """
        Return a truncated single-line version used by the list view.
        """
        blob = f"L{self.line_no}: {self.author} – {self.text}"
        return (blob[: maxlen - 3] + "...") if len(blob) > maxlen else blob


# ---------------------------------------------------------------------------#
# List-Model for the comments sidebar
# ---------------------------------------------------------------------------#


class CommentListModel(QtCore.QAbstractListModel):
    """
    QAbstractListModel that exposes ReviewComment objects to a QListView.
    """

    CommentRole = QtCore.Qt.UserRole + 1
    _ROLE_NAMES = {
        QtCore.Qt.DisplayRole: b"display",
        CommentListModel.CommentRole: b"comment",
    }

    def __init__(self, comments: Optional[List[ReviewComment]] = None, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._comments: List[ReviewComment] = comments or []

    # ---- Qt required overrides -------------------------------------------#
    def rowCount(self, _parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self._comments)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole) -> Any:  # noqa: N802
        if not index.isValid() or not (0 <= index.row() < len(self._comments)):
            return None

        comment = self._comments[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return comment.short_repr()
        elif role == self.CommentRole:
            return comment

        return None

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return self._ROLE_NAMES

    # ---- Public API -------------------------------------------------------#
    def append(self, comment: ReviewComment) -> None:
        """
        Append a new comment to the list.
        """
        self.beginInsertRows(QtCore.QModelIndex(), len(self._comments), len(self._comments))
        self._comments.append(comment)
        self.endInsertRows()

    def remove_by_cid(self, cid: str) -> None:
        """
        Remove comment by unique ID.
        """
        for idx, cm in enumerate(self._comments):
            if cm.cid == cid:
                self.beginRemoveRows(QtCore.QModelIndex(), idx, idx)
                self._comments.pop(idx)
                self.endRemoveRows()
                break


# ---------------------------------------------------------------------------#
# View-Model
# ---------------------------------------------------------------------------#


class CodeReviewViewModel(QtCore.QObject):
    """
    Handles business logic, diff loading, and event-bus interaction.
    """

    diffChanged = QtCore.Signal(str, str)        # old_text, new_text
    commentAdded = QtCore.Signal(ReviewComment)  # emitted after event-bus ACK

    # Event-bus topic names (string consts to avoid typos)
    EVT_ADD_COMMENT = "code_review.comment.add"
    EVT_THEME_CHANGED = "application.theme.changed"

    def __init__(self, event_bus: "EventBus", parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._bus = event_bus
        self._comments_model = CommentListModel()
        self._logger = logging.getLogger(__name__)

        # --- Subscribe to global events ----------------------------------#
        self._bus.subscribe(self.EVT_THEME_CHANGED, self._on_theme_changed)
        self._bus.subscribe(self.EVT_ADD_COMMENT, self._on_comment_added)

    # ---------------------------------------------------------------------#
    # Public API
    # ---------------------------------------------------------------------#
    @property
    def comments_model(self) -> CommentListModel:
        return self._comments_model

    def load_diff(self, old_file: Path, new_file: Path) -> None:
        """
        Load diff from two files and notify UI.
        """
        try:
            old_text = old_file.read_text(encoding="utf-8")
            new_text = new_file.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            self._logger.error("Diff files not found: %s", exc)
            QtWidgets.QMessageBox.warning(None, "File not found", str(exc))
            return
        except OSError as exc:
            self._logger.error("Cannot read diff files: %s", exc)
            QtWidgets.QMessageBox.critical(None, "IO error", str(exc))
            return

        self._logger.debug("Diff loaded: %s ↔ %s", old_file, new_file)
        self.diffChanged.emit(old_text, new_text)

    def submit_comment(self, author: str, line_no: int, text: str) -> None:
        """
        Build a comment and publish on the bus.
        """
        comment = ReviewComment(cid=str(uuid.uuid4()), author=author, line_no=line_no, text=text)
        # Publish synchronously—if the event-bus acknowledges by invoking
        # _on_comment_added, the model will be updated.
        self._bus.publish(self.EVT_ADD_COMMENT, comment)

    # ---------------------------------------------------------------------#
    # Event-bus listeners
    # ---------------------------------------------------------------------#
    def _on_comment_added(self, comment: ReviewComment) -> None:
        """
        Called when the event bus confirms a comment was added.
        """
        self._logger.debug("Comment received from bus: %s", comment)
        self._comments_model.append(comment)
        self.commentAdded.emit(comment)

    def _on_theme_changed(self, palette: QtGui.QPalette) -> None:  # noqa: D401
        """
        React to application-wide theme changes.
        """
        self._logger.debug("Theme changed → forwarding to consumer widget.")
        # Here we would shuttle the palette to any sub-views that do not use
        # Qt's automatic propagation.  For the sake of example, nothing to do.


# ---------------------------------------------------------------------------#
# View
# ---------------------------------------------------------------------------#


class CodeReviewWidget(QtWidgets.QWidget):
    """
    Composite widget containing:

        ┌──────────────┐  ┌────────────┐
        │ old file     │  │ new file   │  Diff panes
        └──────────────┘  └────────────┘
        ┌──────────────────────────────┐
        │  comments QListView          │  Sidebar
        └──────────────────────────────┘
        [Add comment]  [Reload diff]
    """

    # Signal emitted when the user wants to reload diff
    diffReloadRequested = QtCore.Signal()

    def __init__(self, view_model: CodeReviewViewModel, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._vm = view_model
        self.setWindowTitle("FlockDesk – Code Review")

        # Widgets ----------------------------------------------------------#
        self._old_edit = QtWidgets.QPlainTextEdit(readOnly=True)
        self._new_edit = QtWidgets.QPlainTextEdit(readOnly=True)

        # Use monospace fonts for code
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self._old_edit.setFont(font)
        self._new_edit.setFont(font)

        self._comments_view = QtWidgets.QListView()
        self._comments_view.setModel(self._vm.comments_model)
        self._comments_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        self._add_btn = QtWidgets.QPushButton("Add Comment")
        self._reload_btn = QtWidgets.QPushButton("Reload Diff")

        # Layout -----------------------------------------------------------#
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self._old_edit)
        splitter.addWidget(self._new_edit)
        splitter.setSizes([1, 1])

        right_side = QtWidgets.QVBoxLayout()
        right_side.addWidget(self._comments_view)
        right_side.addWidget(self._add_btn)
        right_side.addWidget(self._reload_btn)

        container = QtWidgets.QHBoxLayout(self)
        container.addWidget(splitter, 2)
        container.addLayout(right_side, 1)

        # Connections ------------------------------------------------------#
        self._vm.diffChanged.connect(self._on_diff_changed)
        self._add_btn.clicked.connect(self._on_add_comment_clicked)
        self._reload_btn.clicked.connect(self.diffReloadRequested.emit)

        # Keyboard shortcut for adding comment
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Enter"), self, self._on_add_comment_clicked)

    # ---------------------------------------------------------------------#
    # Slot implementations
    # ---------------------------------------------------------------------#
    @QtCore.Slot(str, str)
    def _on_diff_changed(self, old_text: str, new_text: str) -> None:
        """
        Update diff panes when view-model notifies a change.
        """
        self._old_edit.setPlainText(old_text)
        self._new_edit.setPlainText(new_text)

        # Basic visual diff: mark changed lines (placeholder for a real diff)
        self._highlight_differences(old_text, new_text)

    def _on_add_comment_clicked(self) -> None:
        """
        Prompt user for a new comment.
        """
        cursor = self._new_edit.textCursor()
        line_no = cursor.blockNumber() + 1

        text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self,
            "Add Comment",
            f"Comment for line {line_no}:",
        )
        if not ok or not text.strip():
            return

        author, ok = QtWidgets.QInputDialog.getText(self, "Author", "Your name:")
        if not ok or not author.strip():
            return

        self._vm.submit_comment(author=author.strip(), line_no=line_no, text=text.strip())

    # ---------------------------------------------------------------------#
    # Utility
    # ---------------------------------------------------------------------#
    def _highlight_differences(self, old_text: str, new_text: str) -> None:
        """
        VERY naive diff highlighter – for demo purposes only.
        Lines that differ are given a yellow background.
        """
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        max_len = max(len(old_lines), len(new_lines))

        old_cursor = QtGui.QTextCursor(self._old_edit.document())
        new_cursor = QtGui.QTextCursor(self._new_edit.document())

        highlight_format = QtGui.QTextCharFormat()
        highlight_format.setBackground(QtGui.QColor("#fff79a"))

        # Clear previous formatting
        def _clear_format(edit: QtWidgets.QPlainTextEdit) -> None:
            cursor = QtGui.QTextCursor(edit.document())
            cursor.beginEditBlock()
            cursor.select(QtGui.QTextCursor.Document)
            cursor.setCharFormat(QtGui.QTextCharFormat())
            cursor.endEditBlock()

        _clear_format(self._old_edit)
        _clear_format(self._new_edit)

        for i in range(max_len):
            old_line = old_lines[i] if i < len(old_lines) else ""
            new_line = new_lines[i] if i < len(new_lines) else ""
            if old_line != new_line:
                # Highlight old pane
                pos = self._old_edit.document().findBlockByLineNumber(i).position()
                old_cursor.setPosition(pos)
                old_cursor.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
                old_cursor.mergeCharFormat(highlight_format)
                # Highlight new pane
                pos = self._new_edit.document().findBlockByLineNumber(i).position()
                new_cursor.setPosition(pos)
                new_cursor.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
                new_cursor.mergeCharFormat(highlight_format)


# ---------------------------------------------------------------------------#
# Minimal Event-Bus skeleton (to keep this file self-contained)
# ---------------------------------------------------------------------------#

class EventBus:
    """
    Very small publish/subscribe façade used by the plugin.  The real
    application passes an implementation that is thread-safe, can cross
    processes, etc.  Here we build a Qt signal-based stand-in so the
    module can be executed standalone for manual testing.
    """

    def __init__(self) -> None:
        self._subs: dict[str, List] = {}

    def subscribe(self, topic: str, callback) -> None:
        self._subs.setdefault(topic, []).append(callback)

    def publish(self, topic: str, payload) -> None:
        for cb in self._subs.get(topic, []):
            cb(payload)


# ---------------------------------------------------------------------------#
# Stand-alone test driver (optional)
# ---------------------------------------------------------------------------#

if __name__ == "__main__":  # pragma: no cover
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(name)s:%(message)s")

    app = QtWidgets.QApplication(sys.argv)
    bus = EventBus()

    vm = CodeReviewViewModel(event_bus=bus)
    widget = CodeReviewWidget(view_model=vm)
    widget.resize(1200, 700)
    widget.show()

    # Wire reload diff
    def _reload() -> None:
        # For demo, load two python files in the repo (or fallback to self)
        base = Path(__file__).resolve()
        vm.load_diff(base, base)  # Re-use same file → no diff
    widget.diffReloadRequested.connect(_reload)
    _reload()

    sys.exit(app.exec())
```