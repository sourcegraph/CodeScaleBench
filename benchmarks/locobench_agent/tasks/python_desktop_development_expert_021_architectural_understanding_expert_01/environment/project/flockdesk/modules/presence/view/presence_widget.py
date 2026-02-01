```python
"""
flockdesk.modules.presence.view.presence_widget
------------------------------------------------
Qt / PySide6 visual component that renders presence information for teammates
inside the FlockDesk desktop suite.

This widget plays the V (View) part in the MVVM triad.  It is intentionally
*thin*: all business-logic lives in the ViewModel and/or EventBus handlers,
allowing us to hot-swap or unit-test the UI without touching domain code.

The widget is:

    • Subscribing to the global EventBus for presence/theme updates.
    • Displaying colleagues in a QListView with custom item-delegates so we
      can paint avatars, names and activity indicators.
    • Drag-and-drop aware – users can drag a colleague into another micro-UI
      (e.g. chat or whiteboard) to open a contextual collaboration pane.
    • Lightweight – starts instantly and survives theme changes without leaks.

Author:  The FlockDesk team
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import (QAbstractListModel, QByteArray, QModelIndex,
                            QObject, QPoint, Qt, Signal, Slot)
from PySide6.QtGui import (QColor, QDrag, QIcon, QPainter, QPixmap,
                           QStandardItemModel, QTextOption)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListView,
                               QPushButton, QSpacerItem, QStyle, QStyleOptionViewItem,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

# --------------------------------------------------------------------------- #
# Optional project-local imports                                              #
# --------------------------------------------------------------------------- #

try:
    from flockdesk.core.event_bus import EventBus, Topic  # type: ignore
    from flockdesk.modules.presence.model import PresenceState  # type: ignore
    from flockdesk.shared.theming import ThemeManager  # type: ignore
except (ModuleNotFoundError, ImportError):
    # Fallback stubs to keep linters and RT preview alive
    class EventBus:  # noqa: D401
        """Very small stub when running in isolation."""
        @staticmethod
        def subscribe(topic: str, listener: QObject, slot: str) -> None: ...
        @staticmethod
        def publish(topic: str, payload) -> None: ...

    class PresenceState:  # noqa: D401
        """Enum stub for online/offline/etc."""
        ONLINE = "online"
        AWAY = "away"
        OFFLINE = "offline"

    class ThemeManager:  # noqa: D401
        """Simplistic theme stub."""
        theme_changed = Signal(dict)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Dataclasses & Models                                                        #
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class Colleague:
    """Lightweight data container for a colleague row."""
    uid: str
    display_name: str
    avatar_path: str
    presence: PresenceState


class _PresenceListModel(QAbstractListModel):
    """
    A trivial QAbstractListModel that exposes colleagues to the QListView.

    This model is intentionally 100 % dumb: all mutations come from the
    PresenceViewModel which will feed new lists in one go.
    """

    # Roles used by the delegate for painting
    UID_ROLE = Qt.UserRole + 1
    DISPLAY_NAME_ROLE = Qt.UserRole + 2
    AVATAR_ROLE = Qt.UserRole + 3
    PRESENCE_ROLE = Qt.UserRole + 4

    _ROLE_NAMES = {
        UID_ROLE: QByteArray(b"uid"),
        DISPLAY_NAME_ROLE: QByteArray(b"display_name"),
        AVATAR_ROLE: QByteArray(b"avatar"),
        PRESENCE_ROLE: QByteArray(b"presence"),
    }

    def __init__(self, colleagues: Optional[List[Colleague]] = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._colleagues: List[Colleague] = colleagues or []

    # --------------------------------------------------------------------- #
    # Required overrides                                                    #
    # --------------------------------------------------------------------- #

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._colleagues)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None

        try:
            colleague = self._colleagues[index.row()]
        except IndexError:
            return None

        if role == Qt.DisplayRole:
            return colleague.display_name
        if role == self.UID_ROLE:
            return colleague.uid
        if role == self.DISPLAY_NAME_ROLE:
            return colleague.display_name
        if role == self.AVATAR_ROLE:
            return colleague.avatar_path
        if role == self.PRESENCE_ROLE:
            return colleague.presence
        return None

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return self._ROLE_NAMES

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def update_content(self, colleagues: List[Colleague]) -> None:
        """Replace the entire model dataset in one shot."""
        self.beginResetModel()
        self._colleagues = colleagues
        self.endResetModel()


# --------------------------------------------------------------------------- #
# Custom Delegate                                                             #
# --------------------------------------------------------------------------- #

class PresenceItemDelegate(QStyledItemDelegate):
    """Paints each list item with avatar, name and presence indicator icon."""

    AVATAR_SIZE = 32
    PADDING = 6

    _PRESENCE_ICONS = {
        PresenceState.ONLINE: QIcon(":/presence/online.svg"),
        PresenceState.AWAY: QIcon(":/presence/away.svg"),
        PresenceState.OFFLINE: QIcon(":/presence/offline.svg"),
    }

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        try:
            # Draw selection highlight
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())

            # Fetch data
            name: str = index.data(_PresenceListModel.DISPLAY_NAME_ROLE)
            avatar_path: str = index.data(_PresenceListModel.AVATAR_ROLE)
            presence: PresenceState = index.data(_PresenceListModel.PRESENCE_ROLE)

            # Avatar
            avatar_rect = option.rect.adjusted(self.PADDING, self.PADDING,
                                               -(option.rect.width() - self.AVATAR_SIZE - self.PADDING),
                                               -self.PADDING)
            avatar_pix = QPixmap(avatar_path).scaled(self.AVATAR_SIZE, self.AVATAR_SIZE,
                                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(avatar_rect.topLeft(), avatar_pix)

            # Presence indicator bottom-right of avatar
            presence_icon: QIcon = self._PRESENCE_ICONS.get(presence, QIcon())
            indicator_sz = 10
            indicator_rect = avatar_rect.adjusted(self.AVATAR_SIZE - indicator_sz,
                                                  self.AVATAR_SIZE - indicator_sz,
                                                  0, 0)
            presence_pix = presence_icon.pixmap(indicator_sz, indicator_sz)
            painter.drawPixmap(indicator_rect.topLeft(), presence_pix)

            # User name
            text_rect = option.rect.adjusted(self.AVATAR_SIZE + 2 * self.PADDING,
                                             0, -self.PADDING, 0)
            painter.setPen(option.palette.text().color())
            text_option = QTextOption()
            text_option.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            painter.drawText(text_rect, name, text_option)

        except Exception:  # pragma: no cover
            logger.exception("Failed to paint presence delegate.")
        finally:
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):  # noqa: N802
        base = super().sizeHint(option, index)
        return base.expandedTo(QSize(0, self.AVATAR_SIZE + 2 * self.PADDING))


# --------------------------------------------------------------------------- #
# PresenceWidget                                                              #
# --------------------------------------------------------------------------- #

class PresenceWidget(QWidget):
    """
    QWidget exposing team presence.

    Responsibilities
    ----------------
    1. Build UI (list-view, refresh button)
    2. Bind ViewModel (subscribe to signals / event-bus)
    3. Bridge drag-and-drop to external micro-front-ends
    """

    # Emitted when the user drags a colleague over somewhere else
    colleagueDragStarted = Signal(str)  # uid

    def __init__(self, view_model: "PresenceViewModel", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = view_model

        self._build_ui()
        self._bind_view_model()
        self._connect_theme_changes()

        # Enable drag source
        self._list_view.setDragEnabled(True)
        self._list_view.viewport().setAcceptDrops(False)
        self._list_view.setDefaultDropAction(Qt.IgnoreAction)

        logger.debug("PresenceWidget initialised.")

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        self._list_view = QListView(self, objectName="presenceListView")
        self._list_view.setSpacing(4)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setSelectionMode(QListView.NoSelection)
        self._list_view.setItemDelegate(PresenceItemDelegate(self._list_view))

        self._refresh_btn = QPushButton(self.tr("Refresh"))
        self._refresh_btn.setToolTip(self.tr("Force a manual presence refresh"))

        # Top bar
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel(self.tr("Presence")))
        top_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        top_layout.addWidget(self._refresh_btn)

        # Main layout
        layout = QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addWidget(self._list_view)
        self.setLayout(layout)

        # Model
        self._model = _PresenceListModel([])
        self._list_view.setModel(self._model)

    # ------------------------------------------------------------------ #
    # Data Binding                                                       #
    # ------------------------------------------------------------------ #

    def _bind_view_model(self) -> None:
        self._refresh_btn.clicked.connect(self._vm.refresh)
        self._vm.presence_changed.connect(self._on_presence_changed)

        # For initial data
        self._on_presence_changed(self._vm.snapshot())

    # ------------------------------------------------------------------ #
    # Theme                                                              #
    # ------------------------------------------------------------------ #

    def _connect_theme_changes(self) -> None:
        if hasattr(ThemeManager, "theme_changed"):
            ThemeManager.theme_changed.connect(self._on_theme_changed)

    @Slot(dict)
    def _on_theme_changed(self, theme_meta: dict) -> None:
        """
        Triggered when the global theme changed.

        For the sake of demo we only update the list spacing/palette; more
        thorough implementation would adapt colors in the delegate, etc.
        """
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(theme_meta.get("window", "#FFFFFF")))
        self.setPalette(palette)

    # ------------------------------------------------------------------ #
    # ViewModel slot                                                     #
    # ------------------------------------------------------------------ #

    @Slot(list)
    def _on_presence_changed(self, colleagues: List[Colleague]) -> None:
        logger.debug("PresenceWidget received %d colleagues.", len(colleagues))
        self._model.update_content(colleagues)

    # ------------------------------------------------------------------ #
    # Drag-and-drop                                                      #
    # ------------------------------------------------------------------ #

    def startDrag(self, supportedActions: Qt.DropActions) -> None:  # noqa: N802
        """Override QListView drag start behaviour."""
        index = self._list_view.currentIndex()
        if not index.isValid():
            return

        uid = index.data(_PresenceListModel.UID_ROLE)
        display_name = index.data(_PresenceListModel.DISPLAY_NAME_ROLE)
        avatar_path = index.data(_PresenceListModel.AVATAR_ROLE)

        logger.debug("Start drag for user %s", display_name)
        drag = QDrag(self)
        mime_data = self._vm.build_mime_data(uid)
        drag.setMimeData(mime_data)

        # Pixmap for drag feedback
        pixmap = QPixmap(avatar_path).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        drag.exec_(Qt.MoveAction)
        self.colleagueDragStarted.emit(uid)


# --------------------------------------------------------------------------- #
# ViewModel interface placeholder                                             #
# --------------------------------------------------------------------------- #

class PresenceViewModel(QObject):
    """
    This interface is implemented elsewhere in the presence module.

    PresenceWidget only relies on the signals described below.
    """

    presence_changed = Signal(list)  # List[Colleague]

    # ------------------------------------------------------------------ #
    # API expected by the widget                                         #
    # ------------------------------------------------------------------ #

    def refresh(self) -> None: ...  # noqa: D400

    def snapshot(self) -> List[Colleague]:
        """Return current presence list synchronously."""
        return []

    def build_mime_data(self, uid: str) -> "QMimeData": ...  # noqa: D401


# --------------------------------------------------------------------------- #
# Debug entry-point (can be stripped for prod)                                #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    # Minimal harness to showcase the widget in isolation.
    logging.basicConfig(level=logging.DEBUG)

    class _DummyVM(PresenceViewModel):

        def __init__(self) -> None:
            super().__init__()
            self._colleagues = [
                Colleague("1", "Alice", ":/avatars/alice.png", PresenceState.ONLINE),
                Colleague("2", "Bob", ":/avatars/bob.png", PresenceState.AWAY),
                Colleague("3", "Charlie", ":/avatars/charlie.png", PresenceState.OFFLINE),
            ]

        def refresh(self) -> None:
            logger.info("Refresh called from UI")
            # In real case we might ask server; here we just toggle Bob
            import random
            self._colleagues[1].presence = random.choice(
                [PresenceState.ONLINE, PresenceState.AWAY, PresenceState.OFFLINE])
            self.presence_changed.emit(self._colleagues)

        def snapshot(self) -> List[Colleague]:
            return self._colleagues

        def build_mime_data(self, uid: str):
            from PySide6.QtCore import QMimeData
            md = QMimeData()
            md.setText(uid)
            return md

    app = QApplication(sys.argv)
    w = PresenceWidget(_DummyVM())
    w.resize(240, 320)
    w.show()
    sys.exit(app.exec())
```