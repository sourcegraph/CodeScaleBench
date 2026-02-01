```python
"""
Unit-tests for flockdesk.core.plugin.manager.PluginManager

These tests assume the following public contract:

class PluginManager:
    def __init__(self, event_bus: EventBus, sandbox: bool = True): ...
    def discover_plugins(self, *search_paths: Path | str) -> list[PluginMetadata]: ...
    def load_plugin(self, metadata: PluginMetadata) -> None: ...
    def unload_plugin(self, plugin_name: str, *, force: bool = False) -> None: ...
    def broadcast_event(self, event: Event) -> None: ...
    @property
    def installed_plugins(self) -> dict[str, ModuleType]: ...

class PluginMetadata(NamedTuple):
    name: str
    version: str
    path:  Path
    entrypoint: str

class PluginLoadError(Exception): ...

The concrete implementation can vary, yet as long as the public surface above
is respected the test-suite will operate correctly.
"""
from __future__ import annotations

import json
import importlib
import sys
import types
from pathlib import Path
from typing import Callable
from unittest import mock

import pytest

# NOTE: If the FlockDesk codebase moves or renames the module, only this
# import section needs to be updated.
from flockdesk.core.plugin.manager import (
    PluginLoadError,
    PluginManager,
    PluginMetadata,
)


# --------------------------------------------------------------------------- #
#                              Helper utilities                               #
# --------------------------------------------------------------------------- #
def _write_file(path: Path, content: str) -> None:
    """Utility for writing files with parent directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_fake_plugin(directory: Path, *, name: str, version: str = "1.0.0") -> Path:
    """
    Build a minimal yet valid plugin package on disk and return its root path.

    Layout:
        <directory>/
            <name>/
                __init__.py
            plugin.json
    """
    pkg_dir = directory / name
    _write_file(
        pkg_dir / "__init__.py",
        # language=python
        f"""
from __future__ import annotations

_loaded = False
_teardown_invoked = False
_received_events = []

def setup(event_bus):
    global _loaded
    _loaded = True

    def _echo(event):
        _received_events.append(event)

    event_bus.subscribe("{name}:ping", _echo)
    return {{  # Plugin public contract
        "teardown": _teardown,
    }}

def _teardown():
    global _teardown_invoked
    _teardown_invoked = True
""",
    )

    manifest = {
        "name": name,
        "version": version,
        "entrypoint": f"{name}:setup",
    }
    _write_file(directory / "plugin.json", json.dumps(manifest, indent=2))
    return directory


def _make_faulty_plugin(directory: Path, *, name: str) -> Path:
    """
    Create a plugin that raises an exception during setup
    to assert the manager's fault-isolation guarantees.
    """
    pkg_dir = directory / name
    _write_file(
        pkg_dir / "__init__.py",
        # language=python
        """
def setup(event_bus):
    raise RuntimeError("💥 boom!")
""",
    )

    manifest = {
        "name": name,
        "version": "0.0.1",
        "entrypoint": f"{name}:setup",
    }
    _write_file(directory / "plugin.json", json.dumps(manifest))
    return directory


# --------------------------------------------------------------------------- #
#                                   Fixtures                                  #
# --------------------------------------------------------------------------- #
@pytest.fixture()
def tmp_plugin_dir(tmp_path: Path) -> Path:
    """
    Temporary base directory where plugin packages are materialised.
    Each test receives a pristine folder.
    """
    return tmp_path / "plugins"


@pytest.fixture()
def event_bus() -> mock.Mock:
    """
    Provide a very small stub for the event-bus used by PluginManager.

    The real implementation is vastly more complex, yet for unit-testing
    plugin-lifecycle scenarios only subscribe/emit are required.
    """
    callbacks: dict[str, list[Callable]] = {}

    def subscribe(event_type: str, cb: Callable):
        callbacks.setdefault(event_type, []).append(cb)

    def publish(event_type: str, payload=None):
        for cb in callbacks.get(event_type, []):
            cb(payload)

    bus = mock.Mock()
    bus.subscribe.side_effect = subscribe
    bus.publish.side_effect = publish
    return bus


@pytest.fixture()
def plugin_manager(event_bus: mock.Mock) -> PluginManager:
    """
    Instantiate a fresh PluginManager for every test.

    Using a dedicated fixture keeps tests isolated and avoids
    inter-leakage through singleton state.
    """
    return PluginManager(event_bus=event_bus, sandbox=True)


# --------------------------------------------------------------------------- #
#                                   Tests                                     #
# --------------------------------------------------------------------------- #
def test_discover_plugins_success(
    tmp_plugin_dir: Path,
    plugin_manager: PluginManager,
) -> None:
    """The manager locates plugin manifests and returns valid metadata."""
    # Arrange
    _make_fake_plugin(tmp_plugin_dir / "hello", name="hello_world")
    _make_fake_plugin(tmp_plugin_dir / "bye", name="bye_world", version="2.1.0")

    # Act
    metadata_list = plugin_manager.discover_plugins(tmp_plugin_dir)

    # Assert
    assert {m.name for m in metadata_list} == {"hello_world", "bye_world"}
    # Ensure that metadata has sensible defaults
    meta_hello = next(m for m in metadata_list if m.name == "hello_world")
    assert meta_hello.version == "1.0.0"
    assert (meta_hello.path / "plugin.json").exists()
    assert meta_hello.entrypoint.endswith("setup")


def test_load_and_unload_lifecycle(
    tmp_plugin_dir: Path,
    plugin_manager: PluginManager,
) -> None:
    """
    Loading a plugin must import the module, call setup, register it,
    and unloading must call its teardown exactly once.
    """
    # Arrange
    _make_fake_plugin(tmp_plugin_dir, name="echo_plugin")
    (meta,) = plugin_manager.discover_plugins(tmp_plugin_dir)

    # Act
    plugin_manager.load_plugin(meta)

    # Assert load-side effects
    assert "echo_plugin" in plugin_manager.installed_plugins
    mod: types.ModuleType = plugin_manager.installed_plugins["echo_plugin"]
    assert getattr(mod, "_loaded") is True

    # Act – unload
    plugin_manager.unload_plugin("echo_plugin")

    # Assert teardown executed exactly once
    assert getattr(mod, "_teardown_invoked") is True
    assert "echo_plugin" not in plugin_manager.installed_plugins


def test_event_bus_interaction(
    tmp_plugin_dir: Path,
    plugin_manager: PluginManager,
    event_bus: mock.Mock,
) -> None:
    """Plugin should be able to listen to events via the central event bus."""
    _make_fake_plugin(tmp_plugin_dir, name="listener")
    (meta,) = plugin_manager.discover_plugins(tmp_plugin_dir)
    plugin_manager.load_plugin(meta)

    # The stub event-bus will call the registered handler and
    # mutate the plugin module's _received_events
    event_bus.publish("listener:ping", payload={"hello": "world"})

    listener_mod = plugin_manager.installed_plugins["listener"]
    assert listener_mod._received_events == [{"hello": "world"}]  # type: ignore[attr-defined]


def test_faulty_plugin_isolated(
    tmp_plugin_dir: Path,
    plugin_manager: PluginManager,
) -> None:
    """
    A plugin throwing during setup must raise PluginLoadError but must not
    break the manager nor pollute sys.modules.
    """
    _make_faulty_plugin(tmp_plugin_dir, name="explosive")
    (meta,) = plugin_manager.discover_plugins(tmp_plugin_dir)

    with pytest.raises(PluginLoadError):
        plugin_manager.load_plugin(meta)

    # The plugin must *not* appear as installed
    assert "explosive" not in plugin_manager.installed_plugins
    # And the partially imported module must be purged
    assert "explosive" not in sys.modules


@pytest.mark.parametrize(
    "missing_key",
    ["name", "version", "entrypoint"],
)
def test_malformed_manifest_rejected(
    tmp_plugin_dir: Path,
    plugin_manager: PluginManager,
    missing_key: str,
) -> None:
    """
    The manager should refuse to discover manifests that miss crucial keys.
    """
    # Build a minimal plugin skeleton
    plug_root = tmp_plugin_dir / "malformed"
    pkg_dir = plug_root / "malformed"
    _write_file(pkg_dir / "__init__.py", "")

    manifest = {
        "name": "malformed",
        "version": "0.0.1",
        "entrypoint": "malformed:setup",
    }
    manifest.pop(missing_key)
    _write_file(plug_root / "plugin.json", json.dumps(manifest))

    # Act
    discovered = plugin_manager.discover_plugins(tmp_plugin_dir)

    # Assert
    assert all(meta.name != "malformed" for meta in discovered)
```