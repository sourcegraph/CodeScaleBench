```python
"""
flockdesk.core.shell.menu_bar
=============================

Declarative, plugin-aware menu-bar implementation for the FlockDesk
desktop shell.  The class defined here is responsible for:

* Rendering the top-level menu structure (File / Edit / View / Plugins / Help)
* Wiring each action to the command / event-bus infrastructure
* Hot-reloading plugin menu entries whenever the plugin-registry changes
* Exposing user-facing features such as theme switching and global
  preferences
* Failing gracefully when individual actions raise exceptions so that a
  single bad handler cannot bring down the entire UI process

The code purposefully avoids hard-wiring too many implementation details
and instead relies on light-weight “facade” / “protocol” types that are
fulfilled elsewhere in the application.
"""

from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import dataclass
from functools import partial
from typing import Callable, Iterable, Protocol

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QMenu, QMenuBar, QMessageBox,
                               QWidget)

_logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Generic facades / protocols                                               #
# --------------------------------------------------------------------------- #
class EventBus(Protocol):
    """Minimal façade that the local menu-bar needs from the global event bus."""

    def publish(self, topic: str, **payload) -> None:
        ...

    def subscribe(self, topic: str, handler: Callable[..., None]) -> None:
        ...


class Plugin(Protocol):
    """API subset that a plugin instance has to expose to be integrated here."""

    @dataclass
    class MenuContribution:
        text: str
        icon: str | None = None
        shortcut: str | None = None
        handler: Callable[[], None] | None = None
        tooltip: str | None = None

    def menu_contributions(self) -> Iterable[MenuContribution]:
        ...


class PluginRegistry(Protocol):
    def loaded_plugins(self) -> Iterable[Plugin]:
        ...

    def on_plugin_loaded(self, handler: Callable[[Plugin], None]) -> None:
        ...

    def on_plugin_unloaded(self, handler: Callable[[Plugin], None]) -> None:
        ...


class ThemeManager(Protocol):
    def available_themes(self) -> Iterable[str]:
        ...

    def current_theme(self) -> str:
        ...

    def set_theme(self, theme_name: str) -> None:
        ...


class SettingsFacade(Protocol):
    def show_preferences_dialog(self) -> None:
        ...


# --------------------------------------------------------------------------- #
#  Utility helpers                                                            #
# --------------------------------------------------------------------------- #
class _SafeSlot(QObject):
    """
    Wrap an arbitrary callable into a QObject-bound *slot* that handles
    all exceptions in a centralized manner.

    This prevents a rogue signal handler from propagating uncaught
    exceptions through Qt’s event loop.
    """

    _triggered = Signal()

    def __init__(self, fn: Callable[[], None], title: str | None = None) -> None:
        super().__init__()
        self._fn = fn
        self._title = title or "FlockDesk – Unexpected error"
        self._triggered.connect(self._execute)

    @Slot()
    def _execute(self) -> None:  # noqa: D401
        try:
            self._fn()
        except Exception as exc:  # noqa: BLE001
            _logger.error("handler raised: %s", exc, exc_info=True)
            self._handle_exception(exc)

    # public proxy ----------------------------------------------------------------
    def __call__(self) -> None:  # pragma: no cover
        self._triggered.emit()

    # helpers ---------------------------------------------------------------------
    def _handle_exception(self, exc: Exception) -> None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        QMessageBox.critical(
            None,
            self._title,
            (
                "An unexpected error occurred while performing the requested "
                "operation.  The error has been logged and diagnostics have "
                "been sent."
                f"\n\n{tb}"
            ),
        )


# --------------------------------------------------------------------------- #
#  Threaded execution helper                                                  #
# --------------------------------------------------------------------------- #
class _BackgroundTask(QRunnable):
    """Simple QRunnable that executes a function in a background thread."""

    def __init__(self, fn: Callable[[], None]) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._fn = fn

    def run(self) -> None:  # noqa: D401
        try:
            self._fn()
        except Exception as exc:  # noqa: BLE001
            _logger.error("Background task failed: %s", exc, exc_info=True)


# --------------------------------------------------------------------------- #
#  Main component                                                             #
# --------------------------------------------------------------------------- #
class MenuBar(QMenuBar):
    """
    Application-wide menu bar.

    Parameters
    ----------
    parent:
        Owning widget
    event_bus:
        Application-level event bus for pub/sub communication
    plugin_registry:
        Registry emitting plugin loaded/unloaded signals
    theme_manager:
        Component that controls theme switching
    settings_facade:
        Entry point for application settings / preferences
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        event_bus: EventBus,
        plugin_registry: PluginRegistry,
        theme_manager: ThemeManager,
        settings_facade: SettingsFacade,
    ) -> None:
        super().__init__(parent)

        self._bus = event_bus
        self._plugins = plugin_registry
        self._themes = theme_manager
        self._settings = settings_facade
        self._thread_pool = QThreadPool.globalInstance()

        self._plugins_menu: QMenu | None = None
        self._theme_group: dict[str, QAction] = {}

        # Because building the menu is idempotent we can safely call it on
        # construction and every time we need to refresh dynamic entries.
        self._init_static_structure()
        self._populate_dynamic_sections()

        # listen for plugin lifecycle events ---------------------------------
        self._plugins.on_plugin_loaded(self._on_plugin_loaded)
        self._plugins.on_plugin_unloaded(self._on_plugin_unloaded)

    # --------------------------------------------------------------------- #
    #  Construction helpers                                                 #
    # --------------------------------------------------------------------- #
    def _init_static_structure(self) -> None:
        """Create the static skeleton of the menu bar."""
        # File --------------------------------------------------------------
        file_menu = self.addMenu("&File")
        file_menu.addAction(self._make_action("New Window", "Ctrl+N", self._new_window))
        file_menu.addSeparator()
        file_menu.addAction(self._make_action("Preferences…", "Ctrl+,", self._open_preferences))
        file_menu.addSeparator()
        file_menu.addAction(self._make_action("Exit", "Ctrl+Q", self._quit_app))

        # Edit --------------------------------------------------------------
        edit_menu = self.addMenu("&Edit")
        edit_menu.addAction(self._make_action("Undo", QKeySequence.Undo, self._bus_publish_factory("edit.undo")))
        edit_menu.addAction(self._make_action("Redo", QKeySequence.Redo, self._bus_publish_factory("edit.redo")))
        edit_menu.addSeparator()
        edit_menu.addAction(self._make_action("Cut", QKeySequence.Cut, self._bus_publish_factory("edit.cut")))
        edit_menu.addAction(self._make_action("Copy", QKeySequence.Copy, self._bus_publish_factory("edit.copy")))
        edit_menu.addAction(self._make_action("Paste", QKeySequence.Paste, self._bus_publish_factory("edit.paste")))

        # View --------------------------------------------------------------
        view_menu = self.addMenu("&View")
        theme_menu = view_menu.addMenu("Theme")
        self._theme_menu = theme_menu  # used later for dynamic population

        # Plugins (dynamic) -------------------------------------------------
        self._plugins_menu = self.addMenu("&Plugins")

        # Help --------------------------------------------------------------
        help_menu = self.addMenu("&Help")
        help_menu.addAction(self._make_action("About FlockDesk", None, self._about_dialog))

    def _populate_dynamic_sections(self) -> None:
        """(Re-)create dynamic sub-menus: themes and plugin contributions."""
        self._populate_theme_menu()
        self._populate_plugin_menu()

    # --------------------------------------------------------------------- #
    #  Theme handling                                                       #
    # --------------------------------------------------------------------- #
    def _populate_theme_menu(self) -> None:
        self._theme_menu.clear()
        self._theme_group.clear()

        current = self._themes.current_theme()
        for theme in sorted(self._themes.available_themes()):
            action = QAction(theme, self, checkable=True)
            action.setChecked(theme == current)
            action.triggered.connect(_SafeSlot(partial(self._apply_theme, theme)))
            self._theme_menu.addAction(action)
            self._theme_group[theme] = action

    def _apply_theme(self, theme_name: str) -> None:
        _logger.info("Switching theme to %s", theme_name)
        self._themes.set_theme(theme_name)
        # ensure only one item is checked
        for name, action in self._theme_group.items():
            action.setChecked(name == theme_name)

    # --------------------------------------------------------------------- #
    #  Plugin handling                                                      #
    # --------------------------------------------------------------------- #
    def _populate_plugin_menu(self) -> None:
        self._plugins_menu.clear()

        # collect contributions
        contributions: list[Plugin.MenuContribution] = []
        for plugin in self._plugins.loaded_plugins():
            try:
                contributions.extend(plugin.menu_contributions())
            except Exception as exc:  # noqa: BLE001
                _logger.error("Failed to obtain menu contributions: %s", exc, exc_info=True)

        if not contributions:
            placeholder = QAction("(no plugins loaded)", self)
            placeholder.setEnabled(False)
            self._plugins_menu.addAction(placeholder)
            return

        # sort contributions alphabetically
        contributions.sort(key=lambda c: c.text.lower())

        for contrib in contributions:
            self._plugins_menu.addAction(self._menu_action_from_contribution(contrib))

    def _on_plugin_loaded(self, plugin: Plugin) -> None:
        _logger.debug("Plugin loaded – refreshing menu: %s", plugin)
        self._populate_plugin_menu()

    def _on_plugin_unloaded(self, plugin: Plugin) -> None:
        _logger.debug("Plugin unloaded – refreshing menu: %s", plugin)
        self._populate_plugin_menu()

    # --------------------------------------------------------------------- #
    #  Action factory helpers                                               #
    # --------------------------------------------------------------------- #
    def _make_action(
        self,
        text: str,
        shortcut: str | QKeySequence | None,
        handler: Callable[[], None],
        *,
        icon: str | None = None,
        tooltip: str | None = None,
    ) -> QAction:
        action = QAction(QIcon(icon) if icon else QIcon(), text, self)
        if shortcut:
            action.setShortcut(shortcut)
        if tooltip:
            action.setToolTip(tooltip)
        # wrap handler in exception-safe slot
        action.triggered.connect(_SafeSlot(handler))
        return action

    def _menu_action_from_contribution(self, contrib: Plugin.MenuContribution) -> QAction:
        return self._make_action(
            contrib.text,
            contrib.shortcut or "",
            contrib.handler or (lambda: None),
            icon=contrib.icon,
            tooltip=contrib.tooltip,
        )

    # --------------------------------------------------------------------- #
    #  Built-in command handlers                                            #
    # --------------------------------------------------------------------- #
    # File menu ------------------------------------------------------------
    def _new_window(self) -> None:
        # Spawning a new window is potentially expensive -> run in background
        self._run_in_background(lambda: self._bus.publish("shell.new_window"))
        _logger.info("Requested new window")

    def _open_preferences(self) -> None:
        self._settings.show_preferences_dialog()

    def _quit_app(self) -> None:
        _logger.info("Quit requested by user")
        QApplication.quit()

    # Help menu ------------------------------------------------------------
    def _about_dialog(self) -> None:
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton

        dialog = QDialog(self)
        dialog.setWindowTitle("About FlockDesk")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("<b>FlockDesk</b><br/>Social Workspace Orchestrator"))
        btn = QPushButton("OK")
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn)
        dialog.exec()

    # --------------------------------------------------------------------- #
    #  Misc helpers                                                         #
    # --------------------------------------------------------------------- #
    def _bus_publish_factory(self, topic: str) -> Callable[[], None]:
        return partial(self._bus.publish, topic)

    def _run_in_background(self, fn: Callable[[], None]) -> None:
        self._thread_pool.start(_BackgroundTask(fn))


# --------------------------------------------------------------------------- #
#  Debug / manual test run                                                   #
# --------------------------------------------------------------------------- #
if __name__ == "__main__" and not QApplication.instance():
    # Quick perfunctory smoke-test
    from pathlib import Path
    from types import SimpleNamespace

    logging.basicConfig(level=logging.DEBUG)

    class DummyBus:
        def publish(self, topic: str, **payload):  # noqa: ANN001
            print(f"[bus] {topic} – {payload}")

        def subscribe(self, topic: str, handler):  # noqa: ANN001
            pass

    class DummyPlugin:
        def __init__(self, name: str):
            self.name = name

        def menu_contributions(self):
            return [
                Plugin.MenuContribution(
                    text=f"Do {self.name}",
                    shortcut="Alt+D",
                    handler=lambda: print(f"Plugin {self.name} did something!"),
                )
            ]

    class DummyRegistry:
        _loaded = [DummyPlugin("Stuff"), DummyPlugin("Things")]

        def loaded_plugins(self):
            return list(self._loaded)

        def on_plugin_loaded(self, handler):  # noqa: ANN001
            pass

        def on_plugin_unloaded(self, handler):  # noqa: ANN001
            pass

    class DummyTheme:
        _themes = ["Light", "Dark"]

        def available_themes(self):
            return self._themes

        def current_theme(self):
            return self._themes[0]

        def set_theme(self, name):
            print(f"Theme switched to {name}")

    class DummySettings:
        def show_preferences_dialog(self):
            print("Preferences dialog!")

    app = QApplication(sys.argv)
    win = QWidget()
    menubar = MenuBar(
        win,
        event_bus=DummyBus(),
        plugin_registry=DummyRegistry(),
        theme_manager=DummyTheme(),
        settings_facade=DummySettings(),
    )
    win.setWindowTitle("FlockDesk – MenuBar Test")
    win.setGeometry(200, 200, 600, 400)
    # Note: For a real main window you would use QMainWindow and setMenuBar
    menubar.setParent(win)
    win.show()
    sys.exit(app.exec())
```