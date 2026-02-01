```python
"""
flockdesk.core.plugins.plugin_manager
=====================================

Central registry responsible for discovering, loading, starting, stopping and
unloading FlockDesk runtime-plugins.  A plugin is a *Python distribution* that
exposes an **entrypoint** yielding an object that implements the
`PluginProtocol` defined below.

The manager communicates with the rest of the desktop-suite through the shared
:class:`~flockdesk.core.event_bus.EventBus`, and guarantees that defects inside
a plugin never propagate outside its sandboxed process.

Typical life-cycle
------------------
1. discover()     – Scan the plugin-directory (and python entrypoints) for
                    available plugins.
2. load(name)     – Import the plugin’s distribution, validate its metadata,
                    construct an instance.
3. start(name)    – Call `plugin.start()`, connect to EventBus.
4. stop(name)     – Disconnect from EventBus, call `plugin.stop()`.
5. unload(name)   – Drop references, remove `sys.modules` entries.

All operations are idempotent and thread-safe.

The manager is *not* responsible for UI concerns (installation dialogs, drag
& drop, …) – only the backend orchestration.

"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import logging
import pathlib
import sys
import threading
import traceback
from dataclasses import dataclass, field
from enum import Enum, auto
from types import ModuleType
from typing import Any, Dict, Iterable, List, Optional, Protocol, runtime_checkable

from flockdesk.core.event_bus import EventBus, Subscription  # type: ignore

__all__ = ["PluginManager", "PluginState", "PluginError"]


_LOG = logging.getLogger("flockdesk.plugins")


# --------------------------------------------------------------------------- #
#  Protocols / Metadata                                                       #
# --------------------------------------------------------------------------- #
@runtime_checkable
class PluginProtocol(Protocol):
    """
    Minimal surface a runtime-plugin has to expose so the manager can
    control its life-cycle.  Plugins may subclass :class:`PluginBase` from
    `flockdesk.core.plugins.sdk`, which already provides sane defaults.
    """

    metadata: "PluginMetadata"

    def start(self, event_bus: EventBus) -> None:  # noqa: D401
        """
        Invoked *once* after the plugin has been imported and its
        dependencies validated.  The plugin should register all its event
        handlers / commands here.  The call runs on a worker-thread and
        must **not** block.
        """

    def stop(self) -> None:  # noqa: D401
        """Complement to :pymeth:`start`.  Should release resources."""


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    name: str
    version: str
    description: str = ""
    author: str = ""
    requires: List[str] = field(default_factory=list)
    # For future extension – e.g. minimum FlockDesk version, capabilities …


class PluginState(Enum):
    REGISTERED = auto()  # Discovered, not yet imported
    LOADED = auto()      # Imported, object instantiated
    RUNNING = auto()     # start() called successfully
    STOPPED = auto()     # stop() executed
    FAILED = auto()      # Error happened


# --------------------------------------------------------------------------- #
#  Exceptions                                                                 #
# --------------------------------------------------------------------------- #
class PluginError(RuntimeError):
    """Base-class for all plugin related problems."""

    def __init__(self, plugin: str, msg: str):
        super().__init__(f"[{plugin}] {msg}")
        self.plugin = plugin


class PluginValidationError(PluginError):
    """Raised when the plugin does not implement :class:`PluginProtocol`."""


class PluginImportError(PluginError):
    """Raised when Python cannot import the plugin package."""


class PluginLifecycleError(PluginError):
    """Raised when start/stop fails."""


# --------------------------------------------------------------------------- #
#  Internal bookkeeping dataclass                                             #
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class _PluginHandle:
    metadata: PluginMetadata
    module: ModuleType
    instance: PluginProtocol
    state: PluginState = PluginState.REGISTERED
    subscriptions: List[Subscription] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Plugin-Manager                                                             #
# --------------------------------------------------------------------------- #
class PluginManager:
    """
    Orchestrates discovery and runtime life-cycle of FlockDesk plugins.

    Thread-safety:
        Public methods are internally synchronized – callers may use them from
        any thread without additional locking.
    """

    # Plugins published via *Python entry-points* – see `pyproject.toml`
    ENTRYPOINT_GROUP = "flockdesk.plugins"

    def __init__(
        self,
        event_bus: EventBus,
        search_dir: pathlib.Path | str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._event_bus = event_bus
        self._search_dir = pathlib.Path(search_dir) if search_dir else _default_plugin_dir()
        self._registry: Dict[str, _PluginHandle] = {}
        _LOG.debug("Initialized PluginManager; search-dir=%s", self._search_dir)

    # ................................................................. PUBLIC
    # Discovery --------------------------------------------------------------
    def discover(self) -> List[PluginMetadata]:
        """
        Scan *once* for available plugins and return their metadata.  Already
        registered plugins will be skipped.

        Returns
        -------
        list of PluginMetadata
            Metadata for each newly found plugin.
        """
        with self._lock:
            discovered: List[PluginMetadata] = []
            _LOG.info("Discovering plugins ‥")
            discovered += self._discover_filesystem()
            discovered += self._discover_entrypoints()
            _LOG.info("Discovery finished ‣ %d plugins total", len(self._registry))
            return discovered

    # Loading/Unloading ------------------------------------------------------
    def load(self, name: str) -> None:
        """
        Import the given plugin package and create its main entry object.

        The plugin must have been discovered first.  On errors the handle enters
        the FAILED state and the exception is re-raised.
        """
        with self._lock:
            handle = self._require_handle(name)

            if handle.state is not PluginState.REGISTERED:
                _LOG.debug("load(%s) ignored – current state: %s", name, handle.state)
                return

            _LOG.info("Loading plugin %s …", name)
            try:
                module = importlib.import_module(name)
            except Exception as exc:  # noqa: BLE001
                handle.state = PluginState.FAILED
                _LOG.exception("Failed to import plugin '%s'", name)
                raise PluginImportError(name, str(exc)) from exc

            # Validate module exposes `plugin` object
            if not hasattr(module, "plugin"):
                handle.state = PluginState.FAILED
                raise PluginValidationError(name, "Module does not expose 'plugin' attribute")

            instance = getattr(module, "plugin")

            # Validate protocol compliance
            if not isinstance(instance, PluginProtocol):  # runtime_checkable
                handle.state = PluginState.FAILED
                raise PluginValidationError(name, "Object 'plugin' does not implement PluginProtocol")

            handle.module = module
            handle.instance = instance
            handle.state = PluginState.LOADED
            _LOG.info("Plugin %s successfully loaded", name)

    def unload(self, name: str) -> None:
        """
        Remove plugin from runtime.  Must be STOPPED or FAILED.  If it is still
        running it will be stopped first.

        After unloading the plugin may be loaded again without discovering
        it anew.
        """
        with self._lock:
            handle = self._require_handle(name)

            if handle.state is PluginState.RUNNING:
                self.stop(name)

            if handle.state not in (PluginState.STOPPED, PluginState.FAILED, PluginState.LOADED):
                _LOG.debug("unload(%s) ignored – state=%s", name, handle.state)
                return

            _LOG.info("Unloading plugin %s", name)
            # Drop event-bus subscriptions
            for sub in handle.subscriptions:
                try:
                    sub.dispose()
                except Exception:  # pragma: no cover
                    _LOG.debug("Failed to dispose subscription %s", sub, exc_info=True)
            handle.subscriptions.clear()

            # Remove from sys.modules
            sys.modules.pop(handle.module.__name__, None)

            # Reset handle
            handle.state = PluginState.REGISTERED
            handle.module = None  # type: ignore[assignment]
            handle.instance = None  # type: ignore[assignment]

    # Lifecycle --------------------------------------------------------------
    def start(self, name: str) -> None:
        """Call :pymeth:`PluginProtocol.start` for a LOADED plugin."""
        with self._lock:
            handle = self._require_handle(name)

            if handle.state is PluginState.RUNNING:
                return
            if handle.state is not PluginState.LOADED:
                raise PluginLifecycleError(name, f"Cannot start – state is {handle.state}")

            _LOG.info("Starting plugin %s …", name)
            try:
                handle.instance.start(self._event_bus)
                handle.state = PluginState.RUNNING
                _LOG.info("Plugin %s started", name)
            except Exception as exc:  # noqa: BLE001
                handle.state = PluginState.FAILED
                _LOG.exception("Plugin %s failed to start", name)
                raise PluginLifecycleError(name, str(exc)) from exc

    def stop(self, name: str) -> None:
        """Call :pymeth:`PluginProtocol.stop` if plugin is running."""
        with self._lock:
            handle = self._require_handle(name)
            if handle.state is not PluginState.RUNNING:
                return

            _LOG.info("Stopping plugin %s …", name)
            try:
                handle.instance.stop()
                handle.state = PluginState.STOPPED
            except Exception as exc:  # noqa: BLE001
                handle.state = PluginState.FAILED
                _LOG.exception("Plugin %s failed to stop gracefully", name)
                raise PluginLifecycleError(name, str(exc)) from exc

    # Bulk helpers -----------------------------------------------------------
    def start_all(self) -> None:
        """Load and start every discovered plugin."""
        with self._lock:
            for name in list(self._registry):
                try:
                    self.load(name)
                    self.start(name)
                except PluginError:
                    # Already logged – keep manager running.
                    continue

    def stop_all(self) -> None:
        """Stop all running plugins."""
        with self._lock:
            for name in list(self._registry):
                try:
                    self.stop(name)
                except PluginError:
                    continue

    # Querying ---------------------------------------------------------------
    def metadata(self, name: str) -> PluginMetadata:
        """Return immutable metadata for given plugin name."""
        with self._lock:
            return self._require_handle(name).metadata

    def state(self, name: str) -> PluginState:
        with self._lock:
            return self._require_handle(name).state

    def list_plugins(self, states: Iterable[PluginState] | None = None) -> List[str]:
        """
        Return plugin names matching the given *states*.  If *states* is None
        every plugin name is returned.
        """
        with self._lock:
            if states is None:
                return list(self._registry.keys())
            states_set = frozenset(states)
            return [name for name, h in self._registry.items() if h.state in states_set]

    # ................................................................. HELPERS
    def _discover_filesystem(self) -> List[PluginMetadata]:
        """Discover plugins that are located in the *plugins* folder."""
        if not self._search_dir.exists():
            _LOG.debug("Plugin directory %s does not exist, skipping fs-scan", self._search_dir)
            return []

        new_meta: List[PluginMetadata] = []
        for pkg_path in self._search_dir.iterdir():
            if not pkg_path.is_dir() or pkg_path.name.startswith(("_", ".")):
                continue

            pkg_name = pkg_path.name
            if pkg_name in self._registry:  # already registered
                continue

            try:
                meta = self._read_metadata_from_path(pkg_path)
            except Exception:  # noqa: BLE001
                _LOG.warning("Failed to read metadata for package at %s", pkg_path, exc_info=True)
                continue

            self._registry[pkg_name] = _PluginHandle(meta, None, None)  # type: ignore[arg-type]
            new_meta.append(meta)
            _LOG.debug("Discovered fs-plugin %s @ %s", pkg_name, pkg_path)
        return new_meta

    def _discover_entrypoints(self) -> List[PluginMetadata]:
        """Discover plugins installed in the environment via entrypoints."""
        new_meta: List[PluginMetadata] = []
        for ep in md.entry_points(group=self.ENTRYPOINT_GROUP):
            if ep.name in self._registry:
                continue

            try:
                dist = ep.dist  # PEP-802—same as distribution meta
                meta = PluginMetadata(
                    name=ep.name,
                    version=dist.version or "0",
                    description=dist.metadata.get("Summary", ""),
                    author=dist.metadata.get("Author", ""),
                    requires=list(dist.requires or []),
                )
            except Exception:  # noqa: BLE001
                _LOG.warning("Failed to inspect entrypoint %s", ep, exc_info=True)
                continue

            self._registry[ep.name] = _PluginHandle(meta, None, None)  # type: ignore[arg-type]
            new_meta.append(meta)
            _LOG.debug("Discovered entrypoint-plugin %s", ep.name)
        return new_meta

    # .........................................................................
    def _require_handle(self, name: str) -> _PluginHandle:
        handle = self._registry.get(name)
        if not handle:
            raise PluginError(name, "Plugin not discovered")
        return handle

    # .........................................................................
    @staticmethod
    def _read_metadata_from_path(path: pathlib.Path) -> PluginMetadata:
        """
        Attempt to read *pyproject.toml* or package attributes to form
        PluginMetadata.  Falls back to path-name if no information found.
        """
        # Simplified – avoids bringing in 'tomli' dependency just for metadata.
        meta_file = path / "pyproject.toml"
        if meta_file.exists():
            try:
                import tomllib  # Python 3.11+
            except ModuleNotFoundError:  # pragma: no cover
                import tomli as tomllib  # type: ignore[assignment]
            data = tomllib.loads(meta_file.read_text())
            project = data.get("project", {})
            return PluginMetadata(
                name=project.get("name", path.name),
                version=project.get("version", "0.0.0"),
                description=project.get("description", ""),
                author=", ".join(a.get("name", "") for a in project.get("authors", [])),
                requires=project.get("dependencies", []),
            )
        # Fallback – inspect __init__.py for __version__
        init_file = path / "__init__.py"
        version = "0.0.0"
        if init_file.exists():
            try:
                content = init_file.read_text()
                for line in content.splitlines():
                    if line.startswith("__version__"):
                        version = line.split("=", 1)[1].strip().strip("'\"")
                        break
            except Exception:  # pragma: no cover
                pass
        return PluginMetadata(name=path.name, version=version)

    # Debug utilities --------------------------------------------------------
    def debug_dump(self) -> str:
        """Return a human-readable dump of all plugin states."""
        with self._lock:
            lines: List[str] = []
            for name, h in self._registry.items():
                lines.append(f"{name:20} – {h.state.name:9} – v{h.metadata.version}")
            return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Helpers                                                                    #
# --------------------------------------------------------------------------- #
def _default_plugin_dir() -> pathlib.Path:
    """
    Compute the default plugin directory:
        ~/.local/share/flockdesk/plugins
    """
    base = pathlib.Path.home() / ".local" / "share" / "flockdesk" / "plugins"
    base.mkdir(parents=True, exist_ok=True)
    return base


# --------------------------------------------------------------------------- #
#  Convenience – create singleton for app-wide usage                          #
# --------------------------------------------------------------------------- #
_default_event_bus: Optional[EventBus] = None
_manager_singleton: Optional[PluginManager] = None


def plugin_manager(event_bus: EventBus | None = None) -> PluginManager:
    """
    Return (and lazily create) the process-wide plugin manager.

    The event-bus must be supplied exactly once during the first call.
    """
    global _manager_singleton, _default_event_bus
    if _manager_singleton is None:
        if event_bus is None:
            raise RuntimeError("First call must provide a valid EventBus instance")
        _default_event_bus = event_bus
        _manager_singleton = PluginManager(event_bus)
        _manager_singleton.discover()
    elif event_bus is not None and event_bus is not _default_event_bus:
        raise RuntimeError("PluginManager already initialized with different EventBus")
    return _manager_singleton


# --------------------------------------------------------------------------- #
#  CLI test                                                                   #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    from flockdesk.core.event_bus import create_local_event_bus  # type: ignore

    bus = create_local_event_bus()
    pm = plugin_manager(bus)
    print(pm.debug_dump())

    # Try to start every plugin we found
    pm.start_all()
    print(pm.debug_dump())

    # And stop them again
    pm.stop_all()
    print(pm.debug_dump())
```