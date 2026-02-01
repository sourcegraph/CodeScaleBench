```python
"""
FlockDesk – Social Workspace Orchestrator
Module  : dashboard.viewmodel.dashboard_vm
Author  : FlockDesk Core Team

DashboardViewModel is the glue layer between the DashboardView (Qt widgets)
and the underlying application services (event-bus, plugin-manager, settings).

Responsibilities
----------------
• Maintain an in-memory representation of the dashboard layout
• React to runtime events (plugin hot-load/unload, theme switch, etc.)
• Expose a command API that Views can bind to (MVVM)
• Persist and restore the user’s layout/preferences in a non-blocking way
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal, Slot, QTimer

# ---------------------------------------------------------------------------#
# Fallback stubs for optional runtime imports (unit-test / static-analysis)  #
# ---------------------------------------------------------------------------#
try:
    from flockdesk.core.event_bus import EventBus, EventSubscription
    from flockdesk.core.plugin import PluginManager
    from flockdesk.core.settings import Settings
except ModuleNotFoundError:  # pragma: no cover
    EventBus = PluginManager = Settings = object  # type: ignore
    EventSubscription = object  # type: ignore

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------#
# Datamodels                                                                  #
# ---------------------------------------------------------------------------#
@dataclass
class DashboardWidget:
    """Lightweight serialisable representation of a dashboard widget."""
    id: str
    plugin_id: str
    title: str
    position: Dict[str, Any] = field(default_factory=dict)
    user_config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_plugin(
        cls,
        plugin_id: str,
        *,
        title: str,
        position: Optional[Dict[str, Any]] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> "DashboardWidget":
        return cls(
            id=str(uuid.uuid4()),
            plugin_id=plugin_id,
            title=title,
            position=position or {},
            user_config=user_config or {},
        )


@dataclass
class DashboardState:
    """Complete dashboard state that is safely JSON-serialisable."""
    widgets: List[DashboardWidget] = field(default_factory=list)
    active_theme: str = "default"

    def to_json(self) -> str:
        # Dataclasses → dict → json
        serialisable = asdict(self)
        return json.dumps(serialisable, indent=2)

    @classmethod
    def from_json(cls, data: str) -> "DashboardState":
        raw = json.loads(data)
        return cls(
            widgets=[DashboardWidget(**w) for w in raw.get("widgets", [])],
            active_theme=raw.get("active_theme", "default"),
        )


# ---------------------------------------------------------------------------#
# Dashboard View-Model                                                        #
# ---------------------------------------------------------------------------#
class DashboardViewModel(QObject):
    """
    Exposes reactive Qt signals + imperative command API for the dashboard.
    """

    # ---------------------------- Qt-Signals --------------------------------#
    widgetsChanged = Signal(list)          # List[DashboardWidget]
    busyChanged = Signal(bool)             # bool
    themeChanged = Signal(str)             # str
    errorOccurred = Signal(str)            # str

    # ------------------------- Construction ---------------------------------#
    def __init__(
        self,
        *,
        event_bus: EventBus,
        plugin_manager: PluginManager,
        settings: Settings,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        auto_save_delay_ms: int = 750,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent=parent)
        self._event_bus = event_bus
        self._plugin_manager = plugin_manager
        self._settings = settings
        self._loop = loop or asyncio.get_event_loop()

        self._state: DashboardState = DashboardState()
        self._busy: bool = False
        self._subscriptions: List[EventSubscription] = []

        #             COMMAND NAME          # Callable implementing command
        self._commands: Dict[str, Callable[..., Any]] = {
            "addWidget": self.add_widget,
            "removeWidget": self.remove_widget,
            "reloadLayout": self.reload_layout,
            "saveLayout": self.save_layout_sync,
            "switchTheme": self.switch_theme,
        }

        # Debounce timer – we persist layout only when idle for X ms
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setInterval(auto_save_delay_ms)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.timeout.connect(self.save_layout_async)

        self._register_event_listeners()
        self._restore_persisted_state_async()

    # --------------------------- Properties ---------------------------------#
    @property
    def widgets(self) -> List[DashboardWidget]:
        return list(self._state.widgets)  # Return copy

    @property
    def busy(self) -> bool:
        return self._busy

    # --------------------------- Commands -----------------------------------#
    def run_command(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Public command entrypoint used by view. Raises KeyError if command
        is unknown; any exception from the command itself is propagated.
        """
        if name not in self._commands:
            raise KeyError(f"Unknown command: {name}")

        _logger.debug("Executing command '%s' with args=%s kwargs=%s",
                      name, args, kwargs)
        return self._commands[name](*args, **kwargs)

    # ----------------------- Widget management ------------------------------#
    @Slot(str)
    def add_widget(self, plugin_id: str, **options: Any) -> None:
        """
        Instantiate a plugin widget and track it in the dashboard model.
        Emits widgetsChanged on success.
        """
        _logger.info("Adding widget from plugin '%s'", plugin_id)
        try:
            plugin_meta = self._plugin_manager.metadata_for(plugin_id)
            widget = DashboardWidget.from_plugin(
                plugin_id=plugin_id,
                title=plugin_meta.display_name,
                position=options.get("position"),
                user_config=options.get("user_config"),
            )
            self._state.widgets.append(widget)
            self.widgetsChanged.emit(self.widgets)
            self._trigger_auto_save()
        except Exception as exc:  # pragma: no cover
            _logger.exception("Failed adding widget: %s", exc)
            self.errorOccurred.emit(str(exc))

    @Slot(str)
    def remove_widget(self, widget_id: str) -> None:
        before = len(self._state.widgets)
        self._state.widgets = [
            w for w in self._state.widgets if w.id != widget_id
        ]
        after = len(self._state.widgets)
        if before != after:
            _logger.info("Removed widget '%s'", widget_id)
            self.widgetsChanged.emit(self.widgets)
            self._trigger_auto_save()
        else:
            _logger.warning("Widget '%s' not found for removal", widget_id)

    # ----------------------- Theme & layout ---------------------------------#
    @Slot(str)
    def switch_theme(self, theme_name: str) -> None:
        if self._state.active_theme == theme_name:
            return

        _logger.debug("Switching theme from '%s' → '%s'",
                      self._state.active_theme, theme_name)
        self._state.active_theme = theme_name
        self.themeChanged.emit(theme_name)
        self._trigger_auto_save()
        # Notify global bus so other modules can react.
        self._event_bus.publish("theme.switched", theme=theme_name)

    def _layout_file(self) -> Path:
        """Return the absolute path used to persist the dashboard layout."""
        root: Path = Path(self._settings.user_data_dir)
        root.mkdir(parents=True, exist_ok=True)
        return root / "dashboard_layout.json"

    # ---------------------- Persistence helpers -----------------------------#
    def _restore_persisted_state_async(self) -> None:
        async def _task() -> None:
            try:
                await self._loop.run_in_executor(None, self.reload_layout)
            except Exception as exc:  # pragma: no cover
                _logger.error("Layout restore failed: %s", exc, exc_info=True)
                self.errorOccurred.emit(f"Layout restore failed: {exc}")

        asyncio.ensure_future(_task(), loop=self._loop)

    def reload_layout(self) -> None:
        """
        Load dashboard layout from disk (blocking). Emits widgetsChanged/themeChanged
        on success.
        """
        file_path = self._layout_file()
        if not file_path.exists():
            _logger.info("No persisted layout found (%s), skipping restore",
                         file_path)
            return

        _logger.info("Restoring dashboard layout from '%s'", file_path)
        try:
            raw = file_path.read_text(encoding="utf-8")
            self._state = DashboardState.from_json(raw)
            self.widgetsChanged.emit(self.widgets)
            self.themeChanged.emit(self._state.active_theme)
        except Exception as exc:  # pragma: no cover
            _logger.exception("Failed restoring layout: %s", exc)
            self.errorOccurred.emit(f"Restore failed: {exc}")

    def save_layout_sync(self) -> None:
        """Blocking save helper, safe to call from worker threads."""
        file_path = self._layout_file()
        _logger.debug("Persisting dashboard layout to '%s'", file_path)
        try:
            file_path.write_text(self._state.to_json(), encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            _logger.exception("Saving layout failed: %s", exc)
            # Forward to UI; we don't re-raise to avoid crashing the caller
            self.errorOccurred.emit(f"Saving layout failed: {exc}")

    def save_layout_async(self) -> None:
        """Schedule an asynchronous layout persistence in a thread-pool."""
        async def _task() -> None:
            self._set_busy(True)
            try:
                await self._loop.run_in_executor(None, self.save_layout_sync)
            finally:
                self._set_busy(False)

        asyncio.ensure_future(_task(), loop=self._loop)

    def _trigger_auto_save(self) -> None:
        """Reset debounce timer to delay disk writes during rapid changes."""
        self._auto_save_timer.start()

    # -------------------------- Event-Bus glue ------------------------------#
    def _register_event_listeners(self) -> None:
        self._subscriptions.extend([
            self._event_bus.subscribe("plugin.loaded", self._on_plugin_loaded),
            self._event_bus.subscribe("plugin.unloaded", self._on_plugin_unloaded),
            self._event_bus.subscribe("theme.external_switch",
                                      self._on_external_theme_switch),
        ])

    async def _on_plugin_loaded(self, *, plugin_id: str, **_: Any) -> None:
        # Example reaction: automatically add analytics widget when plugin loads
        _logger.debug("Handling plugin.loaded for '%s'", plugin_id)
        meta = self._plugin_manager.metadata_for(plugin_id)
        if meta.auto_attach_to_dashboard:
            self.add_widget(plugin_id)

    async def _on_plugin_unloaded(self, *, plugin_id: str, **_: Any) -> None:
        _logger.debug("Handling plugin.unloaded for '%s'", plugin_id)
        stale = [w.id for w in self._state.widgets if w.plugin_id == plugin_id]
        for wid in stale:
            self.remove_widget(wid)

    async def _on_external_theme_switch(self, *, theme: str, **_: Any) -> None:
        # Keep internal state in sync with theme changes initiated elsewhere
        _logger.debug("Received external theme switch '%s'", theme)
        self.switch_theme(theme)

    # --------------------------- Misc helpers -------------------------------#
    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit(value)

    def dispose(self) -> None:
        """Explicitly unsubscribe from the event-bus (call on window close)."""
        for sub in self._subscriptions:
            try:
                sub.unsubscribe()
            except Exception:  # pragma: no cover
                _logger.debug("Subscription cleanup failed", exc_info=True)
        self._subscriptions.clear()

    # -------------------------- Dunder helpers ------------------------------#
    def __del__(self) -> None:  # pragma: no cover
        # Best-effort dispose; avoid reference cycles
        try:
            self.dispose()
        except Exception:
            pass
```