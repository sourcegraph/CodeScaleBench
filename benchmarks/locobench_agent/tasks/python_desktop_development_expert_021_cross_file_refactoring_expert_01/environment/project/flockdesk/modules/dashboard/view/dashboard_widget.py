```python
"""
flockdesk.modules.dashboard.view.dashboard_widget
=================================================

The DashboardWidget is the visual host for *cards* inside the FlockDesk
Dashboard micro-front-end.  Each card is a plugin that exposes a QWidget
and registers itself to the internal event-bus.  Users can re-arrange,
remove, and add cards simply by dragging & dropping new plugins from the
plugin-palette or by right-clicking a card and selecting *Remove*.

Design goals
------------
1. MVVM separation – the widget delegates all non-UI work to the
   DashboardViewModel.
2. Event driven – real-time updates via the global EventBus.
3. Plugin friendly – cards are loaded/unloaded via the PluginManager.
4. Robustness – every plugin is sandboxed; a faulty widget is replaced
   with a red *crash card* rather than crashing the entire dashboard.

The implementation purposefully stays clear of concrete business-logic.
Projects embedding this component must provide:

* flockdesk.core.event_bus.EventBus              (pub/sub)
* flockdesk.core.plugins.manager.PluginManager   (plugin life-cycle)
* flockdesk.core.settings.AppSettings            (persistent settings)
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Type

from PySide6.QtCore import Qt, QEvent, QObject, QMimeData, QPoint, Signal, Slot, QSize
from PySide6.QtGui import QAction, QContextMenuEvent, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# External project modules (imported lazily to keep this file compile-time safe)
# -----------------------------------------------------------------------------


def _lazy_import(path: str):
    """
    Lazy import helper so that unit-tests can stub out heavy deps like Qt.
    """
    import importlib

    module, _, sym = path.rpartition(".")
    mod = importlib.import_module(module)
    return getattr(mod, sym)


logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------


@dataclass
class CardMeta:
    """
    Meta information stored for every card inside the dashboard grid.
    """

    plugin_id: str
    plugin_name: str
    widget: QWidget
    col_span: int = 1
    row_span: int = 1


# -----------------------------------------------------------------------------
# View-Model
# -----------------------------------------------------------------------------


class DashboardViewModel(QObject):
    """
    The *VM* coordinating event-bus messages, plugin life-cycle and layout
    persistence.  The view (DashboardWidget) only performs tasks strictly
    related to UI rendering.
    """

    # Signals exposed to the view
    themeChanged = Signal(str)  # dark / light / custom-name
    settingsChanged = Signal()
    cardCrashed = Signal(str)  # plugin_id

    # Internal MIME-type used to drag plugins from palette to the dashboard
    MIME_TYPE = "application/x-flockdesk-plugin-id"

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._event_bus: "EventBus" = _lazy_import(
            "flockdesk.core.event_bus.EventBus"
        ).instance()
        self._plugin_manager: "PluginManager" = _lazy_import(
            "flockdesk.core.plugins.manager.PluginManager"
        ).instance()
        self._settings: "AppSettings" = _lazy_import(
            "flockdesk.core.settings.AppSettings"
        ).instance()

        # plugin_id -> CardMeta
        self._cards: Dict[str, CardMeta] = {}

        self._subscribe_events()

    # --------------------------------------------------------------------- API

    def load_initial_cards(self) -> None:
        """
        Load cards remembered from the previous session, honoring the user’s
        persistent layout.
        """
        stored_cards = self._settings.dashboard.cards
        logger.debug("Loading persisted dashboard cards: %s", stored_cards)
        for plugin_id in stored_cards:
            self.add_card(plugin_id)

    def add_card(self, plugin_id: str) -> None:
        """Instantiate a plugin widget and register it as a CardMeta."""
        if plugin_id in self._cards:
            logger.info("Card for plugin '%s' already present – skipping", plugin_id)
            return
        try:
            plugin_cls: Type["BasePlugin"] = self._plugin_manager.get_plugin(plugin_id)
            plugin: "BasePlugin" = plugin_cls()
            widget = plugin.build_widget()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not instantiate plugin '%s': %s", plugin_id, exc)
            self.cardCrashed.emit(plugin_id)
            return

        meta = CardMeta(
            plugin_id=plugin_id,
            plugin_name=plugin.meta.name,  # type: ignore[attr-defined]
            widget=widget,
        )
        self._cards[plugin_id] = meta
        self._settings.dashboard.cards.append(plugin_id)
        self._settings.save()

        # Must be emitted so the view can insert the widget in the layout.
        self.settingsChanged.emit()

    def remove_card(self, plugin_id: str) -> None:
        """Remove plugin card from internal model and persist change."""
        if plugin_id not in self._cards:
            return

        meta = self._cards.pop(plugin_id)
        meta.widget.deleteLater()

        with suppress(ValueError):
            self._settings.dashboard.cards.remove(plugin_id)
        self._settings.save()
        self.settingsChanged.emit()

    def cards(self) -> Dict[str, CardMeta]:
        """Return the currently active cards."""
        return self._cards

    # ----------------------------------------------------------------- Events

    def _subscribe_events(self) -> None:
        # Theme changes
        self._event_bus.subscribe("ui.theme.changed", self._on_theme_changed)
        # Global settings updated
        self._event_bus.subscribe("settings.updated", self._on_settings_updated)

    async def _on_theme_changed(self, event: "Event") -> None:  # noqa: D401
        theme_name = event.payload.get("theme")
        logger.debug("Theme change event received: %s", theme_name)
        self.themeChanged.emit(theme_name)

    async def _on_settings_updated(self, event: "Event") -> None:  # noqa: D401
        logger.debug("Settings updated event received")
        self.settingsChanged.emit()


# -----------------------------------------------------------------------------
# View
# -----------------------------------------------------------------------------


class CrashCard(QFrame):
    """
    Fallback widget shown when a plugin fails to initialise or crashes
    during runtime.  It keeps the dashboard operational while making it
    obvious which plugin misbehaved.
    """

    def __init__(self, plugin_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("crashCard")
        self.setFrameStyle(QFrame.Panel | QFrame.Raised)
        self.setLineWidth(2)

        layout = QVBoxLayout(self)
        label = QLabel(
            f"⚠️ Plugin '{plugin_id}' failed to load.\n"
            "Right-click to remove the card."
        )
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.setStyleSheet(
            """
            #crashCard {
                background: #b00020;
                color: white;
                border-radius: 6px;
            }
            """
        )


class DashboardWidget(QWidget):
    """
    The UI surface showing multiple plugin cards in a responsive grid.
    """

    GRID_COLUMNS = 4  # TODO: make configurable

    def __init__(self, view_model: Optional[DashboardViewModel] = None) -> None:
        super().__init__()

        # If not injected (unit-tests), create a default one
        self._vm = view_model or DashboardViewModel()

        self.setAcceptDrops(True)
        self.setObjectName("flockdeskDashboard")
        self._build_ui()

        # Connect signals
        self._vm.themeChanged.connect(self._apply_theme)
        self._vm.settingsChanged.connect(self._rebuild_cards)
        self._vm.cardCrashed.connect(self._handle_card_crash)

        # Initial population
        self._vm.load_initial_cards()
        self._rebuild_cards()

    # ---------------------------------------------------------------- UI init

    def _build_ui(self) -> None:
        self._grid = QGridLayout()
        self._grid.setSpacing(12)
        self._grid.setContentsMargins(12, 12, 12, 12)
        self.setLayout(self._grid)

    # ------------------------------------------------------------ Card helpers

    def _handle_card_crash(self, plugin_id: str) -> None:
        logger.debug("Handling crash of plugin '%s'", plugin_id)
        crash_card = CrashCard(plugin_id)
        self._insert_widget(crash_card)

    def _rebuild_cards(self) -> None:
        """
        Re-create the grid whenever cards were added/removed or when a plugin
        crashed.
        """
        while self._grid.count():
            item = self._grid.takeAt(0)
            if widget := item.widget():
                widget.setParent(None)
                widget.deleteLater()

        col, row = 0, 0
        for meta in self._vm.cards().values():
            self._insert_widget(meta.widget, row=row, col=col)
            col += 1
            if col >= self.GRID_COLUMNS:
                col = 0
                row += 1

        self._grid.setRowStretch(row + 1, 1)
        self._grid.setColumnStretch(self.GRID_COLUMNS, 1)
        self.updateGeometry()

    def _insert_widget(self, widget: QWidget, *, row: int | None = None, col: int | None = None) -> None:
        """
        Insert `widget` into the next free cell unless `row/col` is provided.
        """
        if row is None or col is None:
            position = self._next_free_cell()
            row, col = position

        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._grid.addWidget(widget, row, col)
        logger.debug("Inserted widget at row=%s col=%s", row, col)

    def _next_free_cell(self) -> tuple[int, int]:
        """
        Calculate the next free slot in the grid using a simple left-to-right,
        top-to-bottom algorithm.
        """
        count = self._grid.count()
        col = count % self.GRID_COLUMNS
        row = count // self.GRID_COLUMNS
        return row, col

    # ----------------------------------------------------------- Drag & drop

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime: QMimeData = event.mimeData()
        if mime.hasFormat(DashboardViewModel.MIME_TYPE):
            event.setDropAction(Qt.CopyAction)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime: QMimeData = event.mimeData()
        if not mime.hasFormat(DashboardViewModel.MIME_TYPE):
            super().dropEvent(event)
            return

        plugin_id_bytes = mime.data(DashboardViewModel.MIME_TYPE)
        plugin_id = bytes(plugin_id_bytes).decode()

        logger.debug("Plugin dropped on dashboard: %s", plugin_id)
        self._vm.add_card(plugin_id)
        event.acceptProposedAction()

    # ---------------------------------------------------------- Context menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        pos = event.globalPos()
        widget_at_pos = self.childAt(event.pos())

        menu = QMenu(self)
        if isinstance(widget_at_pos, CrashCard):
            plugin_id = self._plugin_id_for_widget(widget_at_pos)
            if plugin_id:
                remove_action = QAction("Remove card", self)
                remove_action.triggered.connect(
                    lambda _=False, pid=plugin_id: self._vm.remove_card(pid)
                )
                menu.addAction(remove_action)
        elif plugin_id := self._plugin_id_for_widget(widget_at_pos):
            remove_action = QAction("Remove card", self)
            remove_action.triggered.connect(
                lambda _=False, pid=plugin_id: self._vm.remove_card(pid)
            )
            settings_action = QAction("Card settings…", self)
            settings_action.triggered.connect(
                lambda _=False, pid=plugin_id: self._open_plugin_settings(pid)
            )
            menu.addActions([settings_action, remove_action])
        else:
            refresh_action = QAction("Refresh dashboard", self)
            refresh_action.triggered.connect(self._rebuild_cards)
            menu.addAction(refresh_action)

        menu.exec(pos)

    def _plugin_id_for_widget(self, child: Optional[QWidget]) -> Optional[str]:
        if child is None:
            return None
        for pid, meta in self._vm.cards().items():
            if meta.widget is child or child.isAncestorOf(meta.widget):
                return pid
        return None

    # --------------------------------------------------------------- Helpers

    def _open_plugin_settings(self, plugin_id: str) -> None:
        """Call the plugin’s settings UI or show fallback dialog."""
        plugin = self._vm._plugin_manager.get_plugin(plugin_id)  # pylint: disable=protected-access
        if hasattr(plugin, "open_settings"):  # type: ignore[attr-defined]
            plugin.open_settings(self)  # type: ignore[attr-defined]
        else:
            QMessageBox.information(
                self,
                "Settings",
                f"Plugin '{plugin_id}' does not expose a settings panel.",
            )

    # --------------------------------------------------------------- Theming

    @Slot(str)
    def _apply_theme(self, theme_name: str) -> None:  # noqa: D401
        """
        Apply QSS from the theme directory.  Blocks the UI minimally thanks to
        async file I/O.
        """

        async def _load_qss(name: str) -> str:  # noqa: D401
            theme_dir = Path(QApplication.instance().property("themePath"))  # type: ignore[arg-type]
            qss_file = theme_dir / f"{name}.qss"
            try:
                return qss_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                logger.warning("Theme file missing: %s", qss_file)
                return ""

        async def _apply() -> None:  # noqa: D401
            qss = await _load_qss(theme_name)
            QApplication.instance().setStyleSheet(qss)

        asyncio.create_task(_apply(), name="dashboard.apply_theme")

    # ---------------------------------------------------------- Event filter

    def event(self, e: QEvent):  # noqa: D401, N802
        """
        Override event() to intercept plugin widget crashes.  Qt does not
        natively raise Python exceptions that occur during event processing
        inside child widgets.  By installing a global *except-hook* we can at
        least replace the faulty widget with a CrashCard.
        """
        try:
            return super().event(e)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            crashed_widget = self.childAt(self.mapFromGlobal(QCursor.pos()))
            plugin_id = self._plugin_id_for_widget(crashed_widget)
            if plugin_id:
                self._handle_card_crash(plugin_id)
            return True  # Event handled


# -----------------------------------------------------------------------------
# Stand-alone test shim
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)

    app = QApplication(sys.argv)
    dash = DashboardWidget()
    dash.resize(QSize(900, 600))
    dash.show()

    sys.exit(app.exec())
```