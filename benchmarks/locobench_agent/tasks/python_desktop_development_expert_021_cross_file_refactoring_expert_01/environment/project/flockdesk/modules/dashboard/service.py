```python
"""
FlockDesk – Social Workspace Orchestrator
Module: dashboard.service

This module implements the DashboardService which is responsible for orchestrating
dashboard-level concerns such as:

    • Loading/unloading dashboard widgets that originate from plugins.
    • Persisting layout/state so that dashboards roam with the user profile.
    • Listening to the internal event-bus and reacting to system-wide changes
      (e.g., theme switched, presence updated, plugin hot-reloaded, etc.).
    • Acting as façade for the DashboardViewModel so that UI layers remain
      oblivious of implementation details.

The code purposefully avoids any GUI related imports so that it can be tested
head-less.  All UI interaction must go through the event-bus.

Author:  FlockDesk core team
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import sys
import uuid
from contextlib import suppress
from dataclasses import dataclass, field, asdict
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Protocol, runtime_checkable

# ─────────────────────────────────────────────────────────────────────────────
# Logging configuration for the module
# (The root logger is configured at application bootstrap time; keep this lean.)
# ─────────────────────────────────────────────────────────────────────────────
_logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Event-bus interfaces (simplified, because the real implementation lives
# in `flockdesk.core.event_bus`).  Stubs allow type-checking & unit-testing.
# ─────────────────────────────────────────────────────────────────────────────
@runtime_checkable
class EventBus(Protocol):
    def subscribe(self, topic: str, handler: Callable[[str, Any], None]) -> Callable[[], None]: ...
    def publish(self, topic: str, payload: Any | None = None) -> None: ...
    async def publish_async(self, topic: str, payload: Any | None = None) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# Plugin registry interfaces (similar reasoning as above)
# ─────────────────────────────────────────────────────────────────────────────
@runtime_checkable
class PluginRegistry(Protocol):
    def get_plugin_meta(self, name: str) -> "PluginMeta": ...
    def list_plugins(self, category: str | None = None) -> List["PluginMeta"]: ...
    def reload_plugin(self, name: str) -> None: ...


@dataclass(slots=True, frozen=True)
class PluginMeta:
    name: str
    module: str
    entrypoint: str
    version: str
    category: str  # e.g. 'dashboard-widget'


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard domain objects
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Widget:
    """
    In-memory representation of a Dashboard widget,
    independent of the GUI technology.
    """
    id: str
    plugin_name: str
    state: dict = field(default_factory=dict)

    def serialize(self) -> dict:
        """Convert to a JSON-serialisable structure."""
        return asdict(self)

    @staticmethod
    def deserialize(data: dict) -> "Widget":
        return Widget(
            id=data["id"],
            plugin_name=data["plugin_name"],
            state=data.get("state", {}),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────
class DashboardError(RuntimeError):
    """Base-class for all dashboard-specific exceptions."""


class PluginLoadError(DashboardError):
    """Raised when a plugin fails to load."""


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard Service
# ─────────────────────────────────────────────────────────────────────────────
class DashboardService:
    """
    Orchestrates dashboard widgets and keeps the persisted layout in sync
    with runtime events.  Life-cycle:

        >>> service = DashboardService(event_bus, plugin_registry, state_path)
        >>> await service.start()
        >>> ...
        >>> await service.stop()

    The service is intentionally kept event-loop agnostic: it does *not*
    create its own loop but expects the caller (e.g., the application
    bootstrapper) to manage one.
    """

    STATE_FILE_NAME = "dashboard_state.json"
    EVENT_WIDGET_ADDED = "dashboard.widget.added"
    EVENT_WIDGET_REMOVED = "dashboard.widget.removed"
    EVENT_DASHBOARD_READY = "dashboard.ready"

    # --------------------------------------------------------------------- #
    # Construction & life-cycle
    # --------------------------------------------------------------------- #
    def __init__(
        self,
        event_bus: EventBus,
        plugin_registry: PluginRegistry,
        state_dir: Path,
    ) -> None:
        self._bus: EventBus = event_bus
        self._plugins: PluginRegistry = plugin_registry
        self._state_path: Path = state_dir / self.STATE_FILE_NAME

        self._widgets: Dict[str, Widget] = {}
        self._subscriptions: List[Callable[[], None]] = []

        self._started = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if self._started.is_set():
            _logger.debug("DashboardService.start() called twice – ignoring.")
            return

        _logger.debug("DashboardService starting …")
        self._setup_bus_subscriptions()
        await self._restore_state()
        self._started.set()
        # Notify others that dashboard is ready
        await self._bus.publish_async(self.EVENT_DASHBOARD_READY, {"widget_count": len(self._widgets)})
        _logger.info("DashboardService started with %d widget(s).", len(self._widgets))

    async def stop(self) -> None:
        if not self._started.is_set():
            _logger.debug("DashboardService.stop() called but service was never started.")
            return

        _logger.debug("DashboardService stopping …")
        self._teardown_bus_subscriptions()
        await self._persist_state()
        self._started.clear()
        _logger.info("DashboardService stopped cleanly.")

    # ------------------------------ #
    # Widget commands (public)
    # ------------------------------ #
    async def add_widget(self, plugin_name: str, *, initial_state: dict | None = None) -> Widget:
        """
        Adds a widget to the dashboard by loading its plugin entry-point.
        """
        _logger.debug("Adding widget for plugin '%s'…", plugin_name)
        meta = self._plugins.get_plugin_meta(plugin_name)
        if meta.category != "dashboard-widget":
            raise DashboardError(f"Plugin '{plugin_name}' is not a dashboard widget (category: {meta.category!r}).")

        # Import plugin module dynamically
        try:
            module = self._import_plugin(meta)
        except Exception as exc:  # pragma: no cover
            _logger.exception("Failed to import plugin '%s'.", plugin_name)
            raise PluginLoadError(f"Could not load plugin '{plugin_name}'.") from exc

        # Instantiate widget object. The plugin must provide a `create_widget`
        # callable returning an initial widget state.
        creator: Callable[[dict | None], dict] | None = getattr(module, meta.entrypoint, None)
        if creator is None:
            raise PluginLoadError(
                f"Plugin '{plugin_name}' does not expose required entry-point '{meta.entrypoint}'."
            )

        widget_state = creator(initial_state or {})
        widget = Widget(id=str(uuid.uuid4()), plugin_name=plugin_name, state=widget_state)
        self._widgets[widget.id] = widget

        # Fire bus event (fire-and-forget)
        self._bus.publish(self.EVENT_WIDGET_ADDED, widget.serialize())
        await self._persist_state()
        _logger.info("Widget %s added.", widget.id)
        return widget

    async def remove_widget(self, widget_id: str) -> None:
        """
        Removes the widget from dashboard.  Silently ignores unknown ids.
        """
        widget = self._widgets.pop(widget_id, None)
        if widget is None:
            _logger.warning("Widget '%s' not found – nothing to remove.", widget_id)
            return

        self._bus.publish(self.EVENT_WIDGET_REMOVED, {"id": widget_id})
        await self._persist_state()
        _logger.info("Widget %s removed.", widget_id)

    def list_widgets(self) -> List[Widget]:
        """Return a copy of currently active widgets (read-only)."""
        return list(self._widgets.values())

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _import_plugin(self, meta: PluginMeta) -> ModuleType:
        """
        Import or reload the plugin module, depending on whether it's already
        present in `sys.modules`.  This enables hot-reloading without restarting
        the whole application.
        """
        if meta.module in sys.modules:
            _logger.debug("Reloading plugin module %s …", meta.module)
            return importlib.reload(sys.modules[meta.module])
        _logger.debug("Importing plugin module %s …", meta.module)
        return importlib.import_module(meta.module)

    # ------------------------------ #
    # State persistence
    # ------------------------------ #
    async def _persist_state(self) -> None:
        """
        Persist current widget layout to a JSON file.  The operation is off-loaded
        to a thread-pool to avoid blocking the event-loop on slower file-systems.
        """
        widgets_data = [w.serialize() for w in self._widgets.values()]
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_state_file, widgets_data)

    async def _restore_state(self) -> None:
        """
        Load dashboard widgets from state-file.  Widgets whose plugins cannot be
        loaded are skipped with a warning.
        """
        loop = asyncio.get_running_loop()
        widgets_data: List[dict] | None = await loop.run_in_executor(None, self._read_state_file)

        if not widgets_data:
            _logger.debug("No persisted dashboard state found.")
            return

        for raw in widgets_data:
            with suppress(Exception):
                widget = Widget.deserialize(raw)
                # Best-effort restore; skip if plugin fails to load.
                with suppress(Exception):
                    await self.add_widget(widget.plugin_name, initial_state=widget.state)
                    # Overwrite generated id with persisted one so references remain stable
                    self._widgets[widget.id].id = widget.id

        _logger.debug("Restored %d widget(s) from persisted state.", len(self._widgets))

    def _write_state_file(self, data: List[dict]) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            _logger.debug("Dashboard state written to %s.", self._state_path)
        except Exception:  # pragma: no cover
            _logger.exception("Failed to write dashboard state to disk.")

    def _read_state_file(self) -> List[dict] | None:
        if not self._state_path.exists():
            return None
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover
            _logger.exception("Failed to read dashboard state – file will be ignored.")
            return None

    # ------------------------------ #
    # Event-bus subscriptions
    # ------------------------------ #
    def _setup_bus_subscriptions(self) -> None:
        """
        Connects to the internal event-bus so that the service reacts to
        cross-cutting events (e.g., plugin reloads).
        """
        self._subscriptions.append(
            self._bus.subscribe("plugins.reloaded", self._on_plugin_reloaded)
        )
        self._subscriptions.append(
            self._bus.subscribe("settings.theme.changed", self._on_theme_changed)
        )
        _logger.debug("DashboardService subscribed to %d bus topic(s).", len(self._subscriptions))

    def _teardown_bus_subscriptions(self) -> None:
        for unsubscribe in self._subscriptions:
            with suppress(Exception):
                unsubscribe()
        self._subscriptions.clear()
        _logger.debug("DashboardService unsubscribed from all bus topics.")

    # ------------------------------ #
    # Event-handlers
    # ------------------------------ #
    def _on_plugin_reloaded(self, topic: str, payload: Any) -> None:
        """
        If a plugin is hot-reloaded, rebuild the corresponding widgets so that
        users immediately see the new version.
        """
        plugin_name: str = payload.get("name") if isinstance(payload, dict) else str(payload)
        affected = [w for w in self._widgets.values() if w.plugin_name == plugin_name]
        if not affected:
            return

        _logger.info("Plugin '%s' reloaded – refreshing %d dashboard widget(s)…", plugin_name, len(affected))
        # Remove & re-add widgets, preserving order/state.
        asyncio.create_task(self._refresh_widgets(affected))

    def _on_theme_changed(self, topic: str, payload: Any) -> None:
        """
        Relay theme change to all widgets (which may adjust colours, icons, …);
        the actual rendering happens in each widget's view-model.
        """
        theme_name: str = payload.get("theme")
        for widget in self._widgets.values():
            self._bus.publish(f"widget.{widget.id}.theme_changed", {"theme": theme_name})

    # ------------------------------ #
    # Complex background tasks
    # ------------------------------ #
    async def _refresh_widgets(self, widgets: List[Widget]) -> None:
        """
        Remove & re-add widgets.  This is done sequentially so that the order in
        the dashboard remains stable.
        """
        for widget in widgets:
            await self.remove_widget(widget.id)
            # Re-use previously saved state
            await self.add_widget(widget.plugin_name, initial_state=widget.state)
        _logger.debug("Widget refresh completed for %d widget(s).", len(widgets))


# ─────────────────────────────────────────────────────────────────────────────
# Module entry-point for manual, local testing
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":  # pragma: no cover
    import argparse
    from tempfile import TemporaryDirectory

    # Quick-and-dirty in-memory bus and plugin registry for demo purposes
    class SimpleBus:
        def __init__(self) -> None:
            self._subs: Dict[str, List[Callable[[str, Any], None]]] = {}

        def subscribe(self, topic: str, handler: Callable[[str, Any], None]) -> Callable[[], None]:
            self._subs.setdefault(topic, []).append(handler)

            def _unsubscribe() -> None:
                self._subs[topic].remove(handler)

            return _unsubscribe

        def publish(self, topic: str, payload: Any | None = None) -> None:
            for h in self._subs.get(topic, []):
                h(topic, payload)

        async def publish_async(self, topic: str, payload: Any | None = None) -> None:
            self.publish(topic, payload)

    class SimpleRegistry:
        def __init__(self, plugins: Dict[str, PluginMeta]) -> None:
            self._plugins = plugins

        def get_plugin_meta(self, name: str) -> PluginMeta:
            return self._plugins[name]

        def list_plugins(self, category: str | None = None) -> List[PluginMeta]:
            return [p for p in self._plugins.values() if category is None or p.category == category]

        def reload_plugin(self, name: str) -> None: ...

    # Dummy plugin dynamically created
    dummy_meta = PluginMeta(
        name="hello-world-widget",
        module="hello_world_widget",
        entrypoint="create_widget",
        version="1.0.0",
        category="dashboard-widget",
    )

    mod = ModuleType(dummy_meta.module)
    sys.modules[dummy_meta.module] = mod

    def _create_widget(initial_state: dict | None = None) -> dict:
        return {"text": "Hello, World!", **(initial_state or {})}

    setattr(mod, dummy_meta.entrypoint, _create_widget)

    async def main() -> None:
        with TemporaryDirectory() as tmp_dir:
            bus = SimpleBus()
            registry = SimpleRegistry({dummy_meta.name: dummy_meta})
            service = DashboardService(bus, registry, Path(tmp_dir))

            await service.start()
            await service.add_widget("hello-world-widget")
            await asyncio.sleep(0.1)  # let events propagate
            await service.stop()

    asyncio.run(main())
```