```python
"""
FlockDesk – Co-Editor: Editor Widget

This module hosts the *view* component of the co-editing micro-front-end.  It
is responsible only for painting and routing UI events; no business logic is
embedded here.  The concrete OT/CRDT algorithm as well as network dispatch are
encapsulated by the *view-model* (see ``flockdesk.modules.co_editor.viewmodel``).

Key Responsibilities
--------------------
1. Render text buffer with line-numbers and syntax highlighting.
2. Display presence information (remote cursors / selections).
3. Forward local edits, caret moves, and viewport changes to the view-model via
   an event-bus message contract.
4. React to incoming document mutations / state changes published on the bus.
5. Apply theming and user preferences at runtime (font, colors, key-bindings).

While the code depends on the larger FlockDesk runtime, it can still be
executed in isolation for unit testing by providing a stub ``EventBus``.
"""

from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

# --------------------------------------------------------------------------- #
#  Stubbed dependencies (facade interfaces)                                   #
# --------------------------------------------------------------------------- #
# NOTE: In production these are imported from `flockdesk.core.<module>`.


class EventBus:
    """
    Very small façade over the project-wide event-bus to keep the widget
    testable.  In production this will forward to the real, asynchronous
    message broker (ZeroMQ, QtEventDispatcher, …).
    """

    message_published = QtCore.Signal(str, dict)

    def publish(self, topic: str, payload: dict) -> None:
        logging.debug("EventBus.publish – topic=%s payload=%s", topic, payload)
        self.message_published.emit(topic, payload)

    def subscribe(self, topic: str, slot: QtCore.Slot) -> None:
        self.message_published.connect(
            lambda t, p: slot(p) if t == topic else None
        )


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: str
    display_name: str
    color: QtGui.QColor


@dataclass(slots=True)
class Theme:
    # Simplified theme container
    name: str
    background: QtGui.QColor
    foreground: QtGui.QColor
    gutter_background: QtGui.QColor
    gutter_foreground: QtGui.QColor
    remote_caret_indicator_size: int = 2


# --------------------------------------------------------------------------- #
#  Line-Number Area                                                           #
# --------------------------------------------------------------------------- #
class _LineNumberArea(QtWidgets.QWidget):
    """
    A QWidget that draws line numbers for the associated QPlainTextEdit.
    """

    def __init__(self, editor: "EditorWidget"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self._editor.line_number_area_width(), 0)

    # Repaint ---------------------------------------------------------------- #
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        self._editor._paint_line_numbers(event)


# --------------------------------------------------------------------------- #
#  Highlighter                                                                #
# --------------------------------------------------------------------------- #
class _PlainTextHighlighter(QtGui.QSyntaxHighlighter):
    """
    Very small demo highlighter.  The real implementation hooks into project
    plug-ins (Python, Markdown, JSON).
    """

    KEYWORD_FORMAT = QtGui.QTextCharFormat()
    KEYWORDS = {"def", "class", "import", "from", "return", "yield"}

    def __init__(self, parent: QtGui.QTextDocument):
        super().__init__(parent)
        self.KEYWORD_FORMAT.setForeground(QtGui.QColor("#CC7832"))
        self.KEYWORD_FORMAT.setFontWeight(QtGui.QFont.Bold)

    # Algorithm -------------------------------------------------------------- #
    def highlightBlock(self, text: str) -> None:
        for word in self.KEYWORDS:
            i = text.find(word)
            while i >= 0:
                length = len(word)
                # ensure we highlight isolated words
                is_left_ok = i == 0 or not text[i - 1].isalnum()
                is_right_ok = (
                    i + length == len(text) or not text[i + length].isalnum()
                )
                if is_left_ok and is_right_ok:
                    self.setFormat(i, length, self.KEYWORD_FORMAT)
                i = text.find(word, i + length)


# --------------------------------------------------------------------------- #
#  Editor Widget                                                              #
# --------------------------------------------------------------------------- #
class EditorWidget(QtWidgets.QPlainTextEdit):
    """
    Rich text editor with collaborative-editing overlays.  It does *not* hold
    any logic on how to merge concurrent edits; instead it exposes a signal
    contract consumed by the `CoEditorViewModel`.
    """

    # Signals ---------------------------------------------------------------- #
    caretMoved = QtCore.Signal(int, int)  # line, column
    viewportScrolled = QtCore.Signal(int)  # first visible line
    contentChanged = QtCore.Signal(str)  # whole document text
    requestUserPreferences = QtCore.Signal()

    # --------------------------------------------------------------------- #
    # Construction                                                          #
    # --------------------------------------------------------------------- #
    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
        profile: Optional[UserProfile] = None,
        theme: Optional[Theme] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._bus = bus or EventBus()
        self._profile = profile or UserProfile(
            user_id="local",
            display_name="Me",
            color=QtGui.QColor("#3DAEE9"),
        )
        self._theme = theme or self._default_theme()

        # line-numbers
        self._line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)

        # highlighter
        self._highlighter = _PlainTextHighlighter(self.document())

        # remote collaborators (user_id -> (cursor, color))
        self._remote_caret_map: Dict[
            str, Tuple[QtGui.QTextCursor, QtGui.QColor]
        ] = {}

        # preferences
        self._load_user_preferences()

        # event bus wiring
        self._register_event_handlers()

        self._update_line_number_area_width(0)

    # --------------------------------------------------------------------- #
    # Helper functions                                                      #
    # --------------------------------------------------------------------- #
    @staticmethod
    def _default_theme() -> Theme:
        return Theme(
            name="FlockDesk Light",
            background=QtGui.QColor("#FFFFFF"),
            foreground=QtGui.QColor("#2B2B2B"),
            gutter_background=QtGui.QColor("#F7F7F7"),
            gutter_foreground=QtGui.QColor("#A0A0A0"),
        )

    # preferences ---------------------------------------------------------- #
    def _load_user_preferences(self) -> None:
        """
        In production this would pull from `UserSettingsService`.
        """
        # font
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        font.setPointSize(11)
        self.setFont(font)

        # colors
        palette = self.palette()
        palette.setColor(QtGui.QPalette.Base, self._theme.background)
        palette.setColor(QtGui.QPalette.Text, self._theme.foreground)
        self.setPalette(palette)

        # tab / indent policy
        self.setTabStopDistance(
            QtGui.QFontMetricsF(font).horizontalAdvance(" ") * 4
        )

    # bus wiring ----------------------------------------------------------- #
    def _register_event_handlers(self) -> None:
        self._bus.subscribe("co_editor.remote_edit", self._on_remote_edit)
        self._bus.subscribe(
            "co_editor.remote_cursor", self._on_remote_cursor_moved
        )
        self.textChanged.connect(self._on_text_changed)

    # --------------------------------------------------------------------- #
    # UI calculations                                                       #
    # --------------------------------------------------------------------- #
    def line_number_area_width(self) -> int:
        # digits = number of digits of total blocks
        digits = len(str(max(1, self.blockCount())))
        space = 3 + self.fontMetrics().horizontalAdvance("9") * digits
        return space

    # events --------------------------------------------------------------- #
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QtCore.QRect(
                cr.left(), cr.top(), self.line_number_area_width(), cr.height()
            )
        )

    def _update_line_number_area_width(self, _: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(
        self, rect: QtCore.QRect, dy: int
    ) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )

        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

        # emit scroll signal
        first_visible_block = self.firstVisibleBlock()
        self.viewportScrolled.emit(first_visible_block.blockNumber())

    def _paint_line_numbers(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self._line_number_area)
        painter.fillRect(
            event.rect(), QtGui.QBrush(self._theme.gutter_background)
        )

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = (
            self.blockBoundingGeometry(block)
            .translated(self.contentOffset())
            .top()
        )
        bottom = top + self.blockBoundingRect(block).height()
        height = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(self._theme.gutter_foreground)
                painter.drawText(
                    0,
                    int(top),
                    self._line_number_area.width() - 4,
                    height,
                    QtCore.Qt.AlignRight,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    # --------------------------------------------------------------------- #
    # Local events                                                          #
    # --------------------------------------------------------------------- #
    def _on_text_changed(self) -> None:
        """
        Forward full document text to the view-model.  For the sake of
        simplicity we ship the entire content; in production we send a delta
        patch.
        """
        text = self.toPlainText()
        self.contentChanged.emit(text)
        try:
            self._bus.publish(
                "co_editor.local_edit", {"text": text, "user_id": self._profile.user_id}
            )
        except Exception as exc:  # pragma: no cover
            self._logger.warning(
                "Failed to publish local_edit – %s\n%s",
                exc,
                traceback.format_exc(),
            )

    def _on_cursor_position_changed(self) -> None:
        cursor = self.textCursor()
        line = cursor.blockNumber()
        column = cursor.columnNumber()
        self.caretMoved.emit(line, column)
        try:
            self._bus.publish(
                "co_editor.local_cursor",
                {
                    "user_id": self._profile.user_id,
                    "line": line,
                    "column": column,
                },
            )
        except Exception as exc:  # pragma: no cover
            self._logger.warning("Failed to publish local_cursor – %s", exc)

    # --------------------------------------------------------------------- #
    # Remote events                                                         #
    # --------------------------------------------------------------------- #
    def _on_remote_edit(self, payload: dict) -> None:
        if payload.get("user_id") == self._profile.user_id:
            return  # ignore our own event

        # naive implementation: replace entire text, preserve scroll/cursor
        self._logger.debug("Applying remote edit: %s", payload)
        saved_scroll = self.verticalScrollBar().value()
        saved_cursor = self.textCursor()

        self.blockSignals(True)
        self.setPlainText(payload.get("text", ""))
        self.blockSignals(False)

        self.setTextCursor(saved_cursor)
        self.verticalScrollBar().setValue(saved_scroll)

    def _on_remote_cursor_moved(self, payload: dict) -> None:
        user_id = payload.get("user_id")
        if user_id == self._profile.user_id:
            return

        line = payload.get("line")
        column = payload.get("column")
        if line is None or column is None:
            return

        color = self._remote_caret_map.get(user_id, (None, None))[1]
        if color is None:
            # assign deterministic pastel color
            color = QtGui.QColor.fromHsv(hash(user_id) % 360, 160, 240)
        self._remote_caret_map[user_id] = (
            self._cursor_at(line, column),
            color,
        )
        self.viewport().update()

    # painting ------------------------------------------------------------- #
    def _cursor_at(self, line: int, column: int) -> QtGui.QTextCursor:
        block = self.document().findBlockByNumber(line)
        cursor = QtGui.QTextCursor(block)
        cursor.setPosition(block.position() + column)
        return cursor

    def paintEvent(self, e: QtGui.QPaintEvent) -> None:
        """
        Extend paintEvent to overlay remote caret indicators.
        """
        super().paintEvent(e)

        painter = QtGui.QPainter(self.viewport())
        for user_id, (cursor, color) in self._remote_caret_map.items():
            if not cursor.isValid():
                continue
            rect = self.cursorRect(cursor)
            # draw caret line
            pen = QtGui.QPen(color)
            pen.setWidth(self._theme.remote_caret_indicator_size)
            painter.setPen(pen)
            painter.drawLine(rect.topLeft(), rect.bottomLeft())

            # draw user label
            label_rect = QtCore.QRect(
                rect.left() + 4,
                rect.top() - 18,
                120,
                16,
            )
            painter.fillRect(label_rect, color.lighter(130))
            painter.setPen(QtGui.QColor("white"))
            font = painter.font()
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(label_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                             user_id)

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #
    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._load_user_preferences()
        self.viewport().update()
        self._line_number_area.update()

    def add_remote_user(self, profile: UserProfile) -> None:
        # used by view-model to register new collaborator
        self._remote_caret_map.setdefault(profile.user_id, (QtGui.QTextCursor(), profile.color))

    def remove_remote_user(self, user_id: str) -> None:
        self._remote_caret_map.pop(user_id, None)
        self.viewport().update()


# --------------------------------------------------------------------------- #
#  Debug runner                                                               #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    app = QtWidgets.QApplication(sys.argv)

    bus = EventBus()
    editor = EditorWidget(bus=bus)
    editor.show()

    # simulate remote collaborator
    def poke_remote():
        bus.publish(
            "co_editor.remote_cursor",
            {"user_id": "albert", "line": 0, "column": 0},
        )

    QtCore.QTimer.singleShot(2000, poke_remote)

    sys.exit(app.exec())
```