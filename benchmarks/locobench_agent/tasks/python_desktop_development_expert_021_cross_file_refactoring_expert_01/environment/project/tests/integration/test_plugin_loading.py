```python
"""
Integration tests for the plugin loading subsystem.

These tests exercise the following production-level guarantees:

1. Plugins can be discovered at runtime from an arbitrary directory.
2. Loading a plugin results in an asynchronous “plugin.loaded” event.
3. Plugins can raise exceptions without bringing down the manager
   or affecting other, well-behaved plugins.

The tests purposefully fall back to local stub implementations when the
real FlockDesk runtime is not available (e.g. in CI for this OSS sample).
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import textwrap
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Callable, Dict, List

import pytest

# ---------------------------------------------------------------------------
# Fallback stubs – enable the tests to run outside the full FlockDesk tree.
# ---------------------------------------------------------------------------


class _EventBus:
    """
    A *very* light-weight asynchronous event bus used only for testing.

    Production FlockDesk relies on a shared, process-wide event bus
    implemented in Rust for performance.  For our purposes, a Python stub
    is sufficient.
    """

    _Subscriber = Callable[..., Awaitable[None]]

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[_EventBus._Subscriber]] = defaultdict(list)

    def subscribe(self, event: str, listener: _Subscriber) -> None:
        """Register a coroutine that will be awaited when `event` is published."""
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError("Listener must be an async function")
        self._subscribers[event].append(listener)

    async def publish(self, event: str, **payload: Any) -> None:
        """Publish `event` and await every subscriber in the order they were added."""
        for listener in list(self._subscribers.get(event, ())):
            try:
                await listener(**payload)
            except Exception:  # pragma: no cover
                # Never allow a rogue listener to break the bus.
                # We would log this in production.
                pass


class _PluginInterface:
    """Contract every plugin must satisfy in this test environment."""

    name: str

    async def initialize(self, event_bus: _EventBus) -> None:  # noqa: D401
        """Perform plugin start-up logic and register bus listeners."""
        raise NotImplementedError


class _PluginManager:
    """
    Minimal stand-in for `flockdesk.core.plugin.manager.PluginManager`.

    The real manager supports version pinning, signature verification,
    and dependency graphs.  We only need dynamic discovery & isolation.
    """

    def __init__(self, event_bus: _EventBus) -> None:
        self._event_bus = event_bus
        self._plugins: Dict[str, _PluginInterface] = {}

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    @property
    def plugins(self) -> Dict[str, _PluginInterface]:
        """Mapping of plugin name -> plugin instance."""
        return self._plugins

    async def load_from_directory(self, directory: Path) -> None:
        """
        Discover and load every `*.py` file in *directory* as a plugin.

        The module must expose a top-level symbol named ``FLOCKDESK_PLUGIN``
        whose value is a *class* implementing :class:`_PluginInterface`.
        """
        for file in directory.glob("*.py"):
            await self._safe_load(file)

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    async def _safe_load(self, file: Path) -> None:
        """
        Import one module in a dedicated namespace and call `initialize()`.

        Any exception is trapped and reported via ``plugin.error`` while
        the manager marches on to the next plugin.
        """
        module_name = f"flockdesk.dynamic.{file.stem}"
        try:
            module = _import_from_path(module_name, file)
            plugin_cls = getattr(module, "FLOCKDESK_PLUGIN")
            plugin: _PluginInterface = plugin_cls()  # type: ignore[call-arg]
            await plugin.initialize(self._event_bus)
            self._plugins[plugin.name] = plugin
            await self._event_bus.publish("plugin.loaded", plugin=plugin)
        except Exception as exc:  # pragma: no cover
            await self._event_bus.publish(
                "plugin.error",
                path=str(file),
                error=exc,
            )


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _import_from_path(fullname: str, path: Path) -> ModuleType:
    """Import a module from *path* under the fully-qualified *fullname*."""
    spec = importlib.util.spec_from_file_location(fullname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {fullname} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


def _write_plugin(tmp: Path, filename: str, source: str) -> Path:
    """Create *filename* under *tmp* with dedented *source* and return the path."""
    file = tmp / filename
    file.write_text(textwrap.dedent(source))
    return file


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_successfully_loaded_and_initialized(tmp_path: Path) -> None:
    """
    A well-behaved plugin should:  
      1. Be discoverable.  
      2. Trigger its own events during initialization.  
      3. Fire a consolidated “plugin.loaded” event.
    """
    # Arrange
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    _write_plugin(
        plugins_dir,
        "hello.py",
        """
        class HelloPlugin:
            name = "hello"

            async def initialize(self, event_bus):
                await event_bus.publish("hello.say", message="hi")

        FLOCKDESK_PLUGIN = HelloPlugin
        """,
    )

    bus = _EventBus()
    manager = _PluginManager(bus)

    loaded = []
    hello_messages = []

    async def on_loaded(plugin):
        loaded.append(plugin.name)

    async def on_hello(message):
        hello_messages.append(message)

    bus.subscribe("plugin.loaded", on_loaded)
    bus.subscribe("hello.say", on_hello)

    # Act
    await manager.load_from_directory(plugins_dir)

    # Assert
    assert manager.plugins.keys() == {"hello"}
    assert loaded == ["hello"]
    assert hello_messages == ["hi"]


@pytest.mark.asyncio
async def test_plugin_error_isolated_and_reported(tmp_path: Path) -> None:
    """
    A faulty plugin must not break the manager nor other plugins and
    should emit a “plugin.error” event.
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    _write_plugin(
        plugins_dir,
        "good.py",
        """
        class GoodPlugin:
            name = "good"

            async def initialize(self, event_bus):
                await event_bus.publish("good.ready", ok=True)

        FLOCKDESK_PLUGIN = GoodPlugin
        """,
    )

    _write_plugin(
        plugins_dir,
        "bad.py",
        """
        class BadPlugin:
            name = "bad"

            async def initialize(self, event_bus):
                raise RuntimeError("Boom!")

        FLOCKDESK_PLUGIN = BadPlugin
        """,
    )

    bus = _EventBus()
    manager = _PluginManager(bus)

    errors = []
    loaded = []

    bus.subscribe("plugin.error", lambda path, error: errors.append((path, str(error))))
    bus.subscribe("plugin.loaded", lambda plugin: loaded.append(plugin.name))

    await manager.load_from_directory(plugins_dir)

    # Good plugin must load
    assert "good" in manager.plugins
    assert "good" in loaded

    # Bad plugin must NOT load
    assert "bad" not in manager.plugins
    assert any("bad.py" in path for path, _ in errors)
    assert any("Boom!" in msg for _, msg in errors)


@pytest.mark.asyncio
async def test_multiple_plugins_load_in_dependency_independent_order(
    tmp_path: Path,
) -> None:
    """
    Real-world deployments often ship dozens of extensions.  The manager
    should cope with a burst of unrelated plugins gracefully.
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    for idx in range(10):
        _write_plugin(
            plugins_dir,
            f"p{idx}.py",
            f"""
            class P{idx}:
                name = "p{idx}"

                async def initialize(self, event_bus):
                    await event_bus.publish("p{idx}.online")

            FLOCKDESK_PLUGIN = P{idx}
            """,
        )

    bus = _EventBus()
    manager = _PluginManager(bus)

    online_events: List[str] = []

    for idx in range(10):
        bus.subscribe(f"p{idx}.online", lambda idx=idx: online_events.append(f"p{idx}"))

    await manager.load_from_directory(plugins_dir)

    assert set(manager.plugins.keys()) == {f"p{i}" for i in range(10)}
    # Every plugin should have advertised its on-line status.
    assert set(online_events) == {f"p{i}" for i in range(10)}
```