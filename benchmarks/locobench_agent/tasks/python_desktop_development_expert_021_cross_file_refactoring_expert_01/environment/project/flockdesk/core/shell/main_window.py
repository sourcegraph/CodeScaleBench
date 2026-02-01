```python
"""
flockdesk/core/shell/main_window.py

Main application window for FlockDesk.  Sets up the Qt container shell,
wires the intra-process event-bus, hosts micro-front-ends inside docks,
and provides convenience UX features such as drag-and-drop plugin
installation, theme switching, and keyboard-shortcut mapping.

This file purposefully avoids putting any domain logic in the widget
tree; instead it delegates to services (event-bus, plugin-manager,
settings, etc.) so that the GUI remains a thin shell around the core
application state (MVVM).
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import (
    QAction,
    QIcon,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
    QDockWidget,
)

# Local, project-internal imports.  These modules are assumed to exist
# elsewhere in the code-base; importing them here keeps the main window
# de-coupled from the implementation details.
from flockdesk.core.event_bus import EventBus, Event  # type: ignore
from flockdesk.core.plugin import PluginManager       # type: ignore
from flockdesk.core.settings import Settings          # type: ignore

LOGGER = logging.getLogger(__name__)


def safe_gui_call(fn: Callable) -> Callable:
    """
    Decorator that wraps a slot / handler in a try/except block and
    surfaces any exception to the user while still letting the program
    limp along.  Crashes are also propagated to the logger so that
    Sentry (or similar) can pick them up.
    """

    def _wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Uncaught exception in GUI callback: %s", exc)
            traceback_str = traceback.format_exc()
            parent: Optional[QWidget] = args[0] if args else None
            QMessageBox.critical(
                parent,
                "Unexpected Error",
                f"An unexpected error occurred:\n\n{traceback_str}",
            )
            # re-raise so upstream crash-reporter gets a record if desired
            raise

    return _wrapper


class MainWindow(QMainWindow):
    """
    The primary window container for FlockDesk.  Responsible for
    orchestrating high-level UI concerns, but *not* for business logic
    (which lives in ViewModels, command handlers, or services).
    """

    # ---------------------------------------------------------------------#
    # Construction / initialisation
    # ---------------------------------------------------------------------#

    def __init__(
        self,
        event_bus: EventBus,
        plugin_manager: PluginManager,
        settings: Settings,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self._event_bus = event_bus
        self._plugin_manager = plugin_manager
        self._settings = settings

        self.setObjectName("FlockDeskMainWindow")
        self.setWindowTitle("FlockDesk – Social Workspace Orchestrator")
        self.setWindowIcon(QIcon.fromTheme("flockdesk"))

        # Enable plugin drag-and-drop
        self.setAcceptDrops(True)

        # Central workspace (micro-apps will swap in/out as docks)
        self._central_stack = QStackedWidget()
        self.setCentralWidget(self._central_stack)

        self._create_menus()
        self._create_initial_docks()
        self._register_shortcuts()
        self._wire_event_bus()
        self._apply_initial_theme()

        # Restore geometry/state
        self._restore_gui_state()

        LOGGER.debug("Main window initialised")

    # ------------------------------------------------------------------ #
    # Qt lifecycle overrides
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):  # noqa: N802 (Qt API case)
        """
        Persist UI state before the window closes, then propagate close
        to children.
        """
        self._save_gui_state()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # Drag-and-drop support for plugin installation
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QDragEnterEvent):  # noqa: N802
        if event.mimeData().hasUrls():
            # Allow drag if any of the URLs look like plugin packages.
            if any(self._is_plugin_candidate(url.toLocalFile()) for url in event.mimeData().urls()):
                event.acceptProposedAction()
                return
        event.ignore()

    @safe_gui_call
    def dropEvent(self, event: QDropEvent):  # noqa: N802
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        plugin_paths = [Path(p) for p in paths if self._is_plugin_candidate(p)]
        if not plugin_paths:
            return

        for p in plugin_paths:
            LOGGER.info("Installing plugin from dropped file %s", p)
            self._plugin_manager.install_from_path(p)

        # Broadcast that new plugins may now be available
        self._event_bus.publish(Event("plugin.installed"))

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _is_plugin_candidate(self, path: str) -> bool:
        return Path(path).suffix.lower() in {".fdp", ".zip"}

    def _create_initial_docks(self) -> None:
        """
        Creates empty docks for micro-front-ends.  The real UI for each
        service is lazily loaded on-demand when its process comes online
        (signalled over the event-bus).
        """
        placeholder = QWidget()
        placeholder.setObjectName("ChatPlaceholder")
        placeholder.setMinimumSize(200, 200)

        chat_dock = QDockWidget("Chat", self)
        chat_dock.setWidget(placeholder)
        chat_dock.setObjectName("ChatDock")
        self.addDockWidget(Qt.LeftDockWidgetArea, chat_dock)

        # Additional pre-allocated docks can be appended here.
        # Whiteboard, Presence, etc.

    def _create_menus(self) -> None:
        # File ----------------------------------------------------------------
        file_menu = self.menuBar().addMenu("&File")

        action_new_window = QAction("&New Window", self)
        action_new_window.setShortcut(QKeySequence.New)
        action_new_window.triggered.connect(self._spawn_new_window)
        file_menu.addAction(action_new_window)

        file_menu.addSeparator()

        action_preferences = QAction("&Preferences…", self)
        action_preferences.setShortcut(QKeySequence("Ctrl+,"))
        action_preferences.triggered.connect(self._open_preferences)
        file_menu.addAction(action_preferences)

        file_menu.addSeparator()

        action_quit = QAction("&Quit", self)
        action_quit.setShortcut(QKeySequence.Quit)
        action_quit.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(action_quit)

        # View ----------------------------------------------------------------
        view_menu = self.menuBar().addMenu("&View")

        self._action_toggle_theme = QAction("Toggle &Dark / Light", self)
        self._action_toggle_theme.setShortcut(QKeySequence("Ctrl+T"))
        self._action_toggle_theme.triggered.connect(self._toggle_theme)
        view_menu.addAction(self._action_toggle_theme)

        # Plugins -------------------------------------------------------------
        plugin_menu = self.menuBar().addMenu("&Plugins")

        action_install_plugin = QAction("&Install Plugin…", self)
        action_install_plugin.triggered.connect(self._prompt_install_plugin)
        plugin_menu.addAction(action_install_plugin)

        action_manage_plugins = QAction("&Manage Plugins…", self)
        action_manage_plugins.triggered.connect(self._open_plugin_manager_dialog)
        plugin_menu.addAction(action_manage_plugins)

        # Help ----------------------------------------------------------------
        help_menu = self.menuBar().addMenu("&Help")
        action_about = QAction("&About FlockDesk", self)
        action_about.triggered.connect(self._show_about_dialog)
        help_menu.addAction(action_about)

    def _register_shortcuts(self) -> None:
        """
        Any global shortcuts not tied to an existing QAction can be
        registered here.  Users may later remap them in preferences, so
        the key sequence should come from the Settings service.
        """
        toggle_theme_seq = self._settings.shortcuts.get(
            "view.toggle_theme", default="Ctrl+T"
        )
        self._action_toggle_theme.setShortcut(QKeySequence(toggle_theme_seq))

    # ------------------------------------------------------------------ #
    # Event-bus integration
    # ------------------------------------------------------------------ #

    def _wire_event_bus(self) -> None:
        self._event_bus.subscribe("theme.change", self._on_theme_change)
        self._event_bus.subscribe("plugin.error", self._on_plugin_error)
        # Additional subscriptions can be added as needed.

    # Event-bus callbacks ------------------------------------------------

    @safe_gui_call
    def _on_theme_change(self, event: Event) -> None:  # pylint: disable=unused-argument
        theme_name = event.payload.get("name")
        self._apply_theme(theme_name)

    @safe_gui_call
    def _on_plugin_error(self, event: Event) -> None:
        plugin_name = event.payload.get("plugin")
        message = event.payload.get("message", "Unknown error")
        QMessageBox.warning(
            self,
            "Plugin Error",
            f"The plugin '{plugin_name}' raised an error:\n\n{message}",
        )

    # ------------------------------------------------------------------ #
    # Theme handling
    # ------------------------------------------------------------------ #

    def _apply_initial_theme(self) -> None:
        prefer_dark = self._settings.ui.get("theme", default="light") == "dark"
        self._apply_theme("dark" if prefer_dark else "light")

    @safe_gui_call
    def _toggle_theme(self) -> None:
        current = self._settings.ui.get("theme", default="light")
        new_value = "dark" if current != "dark" else "light"
        self._settings.ui["theme"] = new_value
        self._settings.save()
        self._apply_theme(new_value)
        self._event_bus.publish(Event("theme.toggled", {"name": new_value}))

    def _apply_theme(self, name: str) -> None:
        LOGGER.info("Applying theme: %s", name)
        qss_path = Path(__file__).with_name(f"{name}.qss")
        if not qss_path.exists():
            LOGGER.warning("Theme stylesheet %s not found; skipping", qss_path)
            return

        try:
            with qss_path.open("r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except Exception:  # pylint: disable=broad-except
            LOGGER.exception("Failed to apply theme %s", name)

    # ------------------------------------------------------------------ #
    # Menu / action callbacks
    # ------------------------------------------------------------------ #

    @safe_gui_call
    def _spawn_new_window(self) -> None:
        LOGGER.debug("Spawning new window instance")
        new_window = MainWindow(self._event_bus, self._plugin_manager, self._settings)
        new_window.show()

    @safe_gui_call
    def _open_preferences(self) -> None:
        # PreferencesDialog is assumed to be implemented elsewhere.
        from flockdesk.core.preferences.dialog import PreferencesDialog  # type: ignore

        dialog = PreferencesDialog(self._settings, self)
        dialog.exec()
        # After closing, reflect any changed shortcuts.
        self._register_shortcuts()

    @safe_gui_call
    def _prompt_install_plugin(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "Install Plugin",
            "",
            "FlockDesk Plugin (*.fdp *.zip)",
        )
        if fname:
            self._plugin_manager.install_from_path(Path(fname))
            self._event_bus.publish(Event("plugin.installed"))

    @safe_gui_call
    def _open_plugin_manager_dialog(self) -> None:
        from flockdesk.core.plugin.manager_dialog import PluginManagerDialog  # type: ignore

        dlg = PluginManagerDialog(self._plugin_manager, self)
        dlg.exec()

    @safe_gui_call
    def _show_about_dialog(self) -> None:
        QMessageBox.about(
            self,
            "About FlockDesk",
            (
                "<b>FlockDesk</b><br/>"
                "Social Workspace Orchestrator<br/><br/>"
                "Version 1.0.0<br/>"
                "© 2024 FlockDesk Contributors"
            ),
        )

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #

    def _restore_gui_state(self) -> None:
        geo = self._settings.ui.get_bytes("main_window.geometry")
        state = self._settings.ui.get_bytes("main_window.state")

        if geo:
            self.restoreGeometry(geo)
        if state:
            self.restoreState(state)

    def _save_gui_state(self) -> None:
        self._settings.ui.set_bytes("main_window.geometry", self.saveGeometry())
        self._settings.ui.set_bytes("main_window.state", self.saveState())
        self._settings.save()

    # ------------------------------------------------------------------ #
    # Convenience factory
    # ------------------------------------------------------------------ #

    @classmethod
    def create_default(cls) -> "MainWindow":
        """
        Standard factory used by the application entry-point when it
        just wants a working main window with the default service
        instances.
        """
        from flockdesk.core.bootstrap import (
            bootstrap_event_bus,
            bootstrap_plugin_manager,
            bootstrap_settings,
        )  # type: ignore

        event_bus = bootstrap_event_bus()
        plugin_manager = bootstrap_plugin_manager(event_bus)
        settings = bootstrap_settings()

        return cls(event_bus, plugin_manager, settings)
```