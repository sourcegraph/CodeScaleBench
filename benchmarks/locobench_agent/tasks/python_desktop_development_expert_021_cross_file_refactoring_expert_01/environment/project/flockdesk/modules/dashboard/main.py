```python
"""
FlockDesk – Social Workspace Orchestrator
Dashboard Micro-Frontend

This module is the executable entry-point and core implementation of the “community
dashboard” micro-frontend.  It wires together

    • the event-bus bridge          (async, publish/subscribe)
    • extension/plugin loading      (hot-swap, sandboxed)
    • MVVM layers                   (Qt/PySide6)
    • user-preference integration   (roaming cloud profiles)

Running this file will spin-up a standalone dashboard process that automatically
connects to the shared message-bus used by the rest of FlockDesk.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from PySide6 import QtCore, QtGui, QtWidgets
from pydantic import BaseModel, ValidationError


# --------------------------------------------------------------------------------------
# Logging configuration
# --------------------------------------------------------------------------------------
LOG_FORMAT = (
    "%(asctime)s [%(process)d] [%(levelname)8s] "
    "%(name)s:%(lineno)d | %(message)s"
)
logging.basicConfig(
    level=os.getenv("FLOCKDESK_LOGLEVEL", "INFO"),
    format=LOG_FORMAT,
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("flockdesk.dashboard")

# --------------------------------------------------------------------------------------
# Abstractions & Protocols
# --------------------------------------------------------------------------------------
@runtime_checkable
class EventBusProtocol(Protocol):
    """
    Narrow interface expected from the shared event-bus.  Deliberately small so the
    dashboard stays decoupled from the actual message-bus backend.
    """

    async def publish(self, topic: str, payload: dict) -> None: ...
    async def subscribe(
        self, topic: str, handler: Callable[[str, dict], None | asyncio.Future]
    ) -> None: ...


@runtime_checkable
class DashboardPlugin(Protocol):
    """
    Interface all dashboard plugins must fulfil.
    """

    id: str  # unique, snake_case id

    def bootstrap(self, api: "PluginAPI") -> QtWidgets.QWidget:
        """
        Called once after the plugin is imported & validated.  Must return a QWidget that
        will be inserted into the dashboard’s layout.
        """


# --------------------------------------------------------------------------------------
# Configuration & Preferences
# --------------------------------------------------------------------------------------
class DashboardPreferences(BaseModel):
    theme: str = "dark"
    show_welcome: bool = True
    layout: Optional[str] = None  # Serialized Qt geometry/state


def load_preferences(profile_dir: Path) -> DashboardPreferences:
    """Load user preferences from disk, falling back to sensible defaults."""
    pref_file = profile_dir / "dashboard_prefs.json"
    if not pref_file.exists():
        logger.info("No existing prefs – generating defaults at %s", pref_file)
        default = DashboardPreferences()
        pref_file.write_text(default.json(indent=2))
        return default

    try:
        data = json.loads(pref_file.read_text())
        return DashboardPreferences(**data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error("Invalid preference file – resetting to defaults: %s", exc)
        traceback.print_exc()
        pref_file.rename(pref_file.with_suffix(".corrupt"))
        return DashboardPreferences()


def save_preferences(profile_dir: Path, prefs: DashboardPreferences) -> None:
    """Safely persist preferences back to disk."""
    dest = profile_dir / "dashboard_prefs.json"
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(prefs.json(indent=2))
    tmp.replace(dest)
    logger.debug("Preferences saved to %s", dest)


# --------------------------------------------------------------------------------------
# Event-Bus Bridge
# --------------------------------------------------------------------------------------
class LocalDummyBus:  # pragma: no cover – fallback, mainly for dev/tests
    """
    If the real bus isn’t available (unit-test or standalone dev launch),
    we fall back to an in-process asyncio pub/sub.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable]] = {}

    async def publish(self, topic: str, payload: dict) -> None:
        for cb in self._subscribers.get(topic, []):
            try:
                result = cb(topic, payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa
                logger.exception("Error in local dummy subscriber")

    async def subscribe(self, topic: str, handler: Callable) -> None:
        self._subscribers.setdefault(topic, []).append(handler)


def resolve_event_bus() -> EventBusProtocol:
    """
    Dynamically import the shared event-bus.  If not present, default to a dummy.
    """
    try:
        bus_mod = importlib.import_module("flockdesk.core.bus")
        bus: EventBusProtocol = bus_mod.get_global_bus()
        logger.info("Attached to shared event-bus.")
        return bus
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to attach to shared bus – using dummy: %s", exc)
        return LocalDummyBus()


# --------------------------------------------------------------------------------------
# Plugin System
# --------------------------------------------------------------------------------------
PLUGIN_DIRS: List[Path] = [
    Path(os.getenv("FLOCKDESK_PLUGIN_PATH", "")).expanduser(),
    Path(__file__).parent / "plugins",
]

class PluginAPI:
    """
    Surface exposed to 3rd-party plugins; limits what they can poke at.
    """

    def __init__(self, bus: EventBusProtocol, prefs: DashboardPreferences) -> None:
        self.bus = bus
        self.prefs = prefs

    async def send_notification(self, title: str, body: str) -> None:
        await self.bus.publish(
            "system.notifications",
            {"title": title, "body": body, "origin": "dashboard"},
        )


class PluginLoader:
    """
    Discovers and validates Dashboard plugins.
    """

    def __init__(self, api: PluginAPI) -> None:
        self._api = api
        self._loaded: Dict[str, ModuleType] = {}

    def discover(self) -> List[DashboardPlugin]:
        plugins: List[DashboardPlugin] = []
        for directory in PLUGIN_DIRS:
            if not directory or not directory.exists():
                continue
            sys.path.insert(0, str(directory))
            for entry in directory.glob("*.py"):
                name = entry.stem
                if name.startswith("_"):
                    continue

                mod_name = f"flockdesk.userplugin.{name}"

                try:
                    logger.debug("Attempting to import plugin: %s", mod_name)
                    module = importlib.import_module(mod_name)
                    plugin: DashboardPlugin = getattr(module, "PLUGIN")  # type: ignore
                    assert isinstance(plugin, DashboardPlugin)  # runtime check
                    self._loaded[plugin.id] = module
                    plugins.append(plugin)
                    logger.info("Plugin loaded: %s", plugin.id)
                except Exception:
                    logger.exception("Failed to load plugin %s", entry.name)
        return plugins


# --------------------------------------------------------------------------------------
# MVVM layers – ViewModel, Model & View
# --------------------------------------------------------------------------------------
class DashboardState(QtCore.QObject):
    """
    Centralised, observable state container (ViewModel).
    """

    themeChanged = QtCore.Signal(str)
    widgetAdded = QtCore.Signal(QtWidgets.QWidget)

    def __init__(self, prefs: DashboardPreferences) -> None:
        super().__init__()
        self._theme = prefs.theme

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def theme(self) -> str:
        return self._theme

    def set_theme(self, theme: str) -> None:
        if theme == self._theme:
            return
        self._theme = theme
        self.themeChanged.emit(theme)

    def add_plugin_widget(self, widget: QtWidgets.QWidget) -> None:
        self.widgetAdded.emit(widget)


# --------------------------------------------------------------------------------------
# Qt View (Main Window)
# --------------------------------------------------------------------------------------
class DashboardWindow(QtWidgets.QMainWindow):
    """
    Qt View – listens to DashboardState (ViewModel) & updates UI.
    """

    def __init__(
        self,
        state: DashboardState,
        prefs: DashboardPreferences,
        save_prefs_cb: Callable[[DashboardPreferences], None],
    ) -> None:
        super().__init__()
        self.setWindowTitle("FlockDesk – Community Dashboard")
        self._state = state
        self._prefs = prefs
        self._save_prefs = save_prefs_cb

        self._central = QtWidgets.QStackedWidget()
        self.setCentralWidget(self._central)

        # Restore geometry/layout
        if prefs.layout:
            logger.debug("Restoring saved layout/geometry")
            try:
                geometry, state_b = prefs.layout.split("|", 1)
                self.restoreGeometry(QtCore.QByteArray.fromHex(geometry.encode()))
                self.restoreState(QtCore.QByteArray.fromHex(state_b.encode()))
            except Exception:
                logger.warning("Failed to restore window layout")

        # Connect signals
        state.themeChanged.connect(self._on_theme_changed)
        state.widgetAdded.connect(self._on_widget_added)

        # Show welcome panel
        if prefs.show_welcome:
            welcome = QtWidgets.QLabel(
                "Welcome to the FlockDesk Dashboard!\n\n"
                "Drag plugins into /plugins and watch them appear here.",
                alignment=QtCore.Qt.AlignCenter,
            )
            self._central.addWidget(welcome)

    # ------------------------------------------------------------------
    # Qt Event overrides
    # ------------------------------------------------------------------
    def closeEvent(self, evt: QtGui.QCloseEvent) -> None:  # noqa: N802
        # Persist Qt geometry/state into prefs before shutdown
        geo = self.saveGeometry().toHex().data().decode()
        st = self.saveState().toHex().data().decode()
        self._prefs.layout = f"{geo}|{st}"
        self._save_prefs(self._prefs)
        evt.accept()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @QtCore.Slot(str)
    def _on_theme_changed(self, theme: str) -> None:
        logger.info("Applying theme: %s", theme)
        # Real implementation would swap out stylesheets; simplified here:
        self.setStyleSheet("QWidget { background: #232629; color: #f0f0f0 }" if theme == "dark" else "")

    @QtCore.Slot(QtWidgets.QWidget)
    def _on_widget_added(self, widget: QtWidgets.QWidget) -> None:
        logger.debug("Adding plugin widget to UI stack")
        self._central.addWidget(widget)
        self._central.setCurrentWidget(widget)


# --------------------------------------------------------------------------------------
# Async event loop integration (Qt + asyncio)
# --------------------------------------------------------------------------------------
class AsyncBridge(QtCore.QObject):
    """
    Periodically spins the asyncio event-loop so Qt remains responsive.
    """

    TICK_MS = 12  # roughly 60fps

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop
        self._timer = QtCore.QTimer(self, timeout=self._on_tick)
        self._timer.start(self.TICK_MS)

    # ------------------------------------------------------------------
    # Qt Slot
    # ------------------------------------------------------------------
    @QtCore.Slot()
    def _on_tick(self) -> None:
        self._loop.call_soon(self._loop.stop)
        self._loop.run_forever()


# --------------------------------------------------------------------------------------
# Bootstrapping
# --------------------------------------------------------------------------------------
def _fatal_dialog(exc: BaseException) -> None:
    """
    Display a modal crash dialog – gives user feedback even if Sentry logging fails.
    """
    msg = QtWidgets.QMessageBox()
    msg.setIcon(QtWidgets.QMessageBox.Critical)
    msg.setWindowTitle("Dashboard – Unhandled Error")
    msg.setText("The dashboard encountered a fatal error and will exit.")
    msg.setDetailedText("".join(traceback.format_exception(exc)))
    msg.exec()


def main() -> None:  # noqa: C901 – high cyclomatic is acceptable for entrypoint
    # --------------------------------------------------------------------------------------------------
    # Resolve profile directory
    # --------------------------------------------------------------------------------------------------
    profile_dir = Path(os.getenv("FLOCKDESK_PROFILE_DIR", "~/.config/flockdesk")).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------------------------------
    # Preferences
    # --------------------------------------------------------------------------------------------------
    prefs = load_preferences(profile_dir)

    # --------------------------------------------------------------------------------------------------
    # Event-Bus
    # --------------------------------------------------------------------------------------------------
    bus = resolve_event_bus()

    # --------------------------------------------------------------------------------------------------
    # Qt Application
    # --------------------------------------------------------------------------------------------------
    app = QtWidgets.QApplication(sys.argv)
    asyncio_loop = asyncio.new_event_loop()
    QtCore.QThread.currentThread().setObjectName("main-thread")

    bridge = AsyncBridge(asyncio_loop)  # noqa: F841  – hold reference

    state = DashboardState(prefs=prefs)
    window = DashboardWindow(state, prefs, lambda p: save_preferences(profile_dir, p))
    window.resize(1024, 720)
    window.show()

    # --------------------------------------------------------------------------------------------------
    # Plugin discovery
    # --------------------------------------------------------------------------------------------------
    api = PluginAPI(bus, prefs)
    loader = PluginLoader(api)
    plugins = loader.discover()

    for plugin in plugins:
        try:
            widget = plugin.bootstrap(api)
            state.add_plugin_widget(widget)
        except Exception:
            logger.exception("Plugin '%s' raised during bootstrap; skipping.", plugin.id)

    # --------------------------------------------------------------------------------------------------
    # Event-Bus subscriptions (example)
    # --------------------------------------------------------------------------------------------------
    async def on_theme_change(_topic: str, payload: Dict[str, Any]) -> None:
        new_theme = payload.get("theme")
        if new_theme:
            state.set_theme(new_theme)

    # Register async subscription
    asyncio_loop.create_task(bus.subscribe("ui.theme.changed", on_theme_change))

    # --------------------------------------------------------------------------------------------------
    # Execute Qt event-loop
    # --------------------------------------------------------------------------------------------------
    try:
        exit_code = app.exec()
    except Exception as exc:  # noqa: BLE001
        logger.critical("Fatal error, shutting down…")
        traceback.print_exc()
        _fatal_dialog(exc)
        exit_code = 1
    finally:
        # Ensure async loop closes
        asyncio_loop.stop()
        asyncio_loop.close()

    sys.exit(exit_code)


# --------------------------------------------------------------------------------------
# Script Entrypoint
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()

```