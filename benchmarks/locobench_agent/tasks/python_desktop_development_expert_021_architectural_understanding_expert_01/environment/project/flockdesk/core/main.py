```python
"""
FlockDesk – Social Workspace Orchestrator
=========================================
core/main.py

This module is the primary entry-point for the entire desktop suite.  It is
responsible for:

1.  Boot-strapping a Qt application with sane defaults.
2.  Wiring up the internal asyncio-powered event-bus.
3.  Loading, validating and life-cycling runtime plugins.
4.  Registering global diagnostics (loggers, Sentry, unhandled-exception hooks).
5.  Spawning the root window and handing execution over to the Qt event-loop.

The code is intentionally separated from any concrete UI widgets;  micro-front-
ends are loaded at runtime as plugins.  This keeps the core slim, testable and
agnostic of any particular feature.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Set

# ────────────────────────────────────────────────────────────────
# Optional runtime dependencies
# ────────────────────────────────────────────────────────────────
try:
    import sentry_sdk
except ImportError:  # pragma: no cover – soft dependency
    sentry_sdk = None  # type: ignore

try:
    from PySide6.QtCore import Qt, QObject, Signal, Slot, QTimer  # noqa
    from PySide6.QtGui import QIcon  # noqa
    from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox  # noqa
except ImportError:  # pragma: no cover
    raise RuntimeError(
        "PySide6 is not installed.  Install with `pip install PySide6`."
    ) from None

# ────────────────────────────────────────────────────────────────
# Globals & Constants
# ────────────────────────────────────────────────────────────────

APP_NAME = "FlockDesk"
ORG_NAME = "Flockware Inc."
CFG_DIR = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "flockdesk"
PLUGIN_DIR = Path.home() / ".flockdesk" / "plugins"
DEFAULT_CONFIG_FILE = CFG_DIR / "settings.json"
SENTRY_DSN_ENV = "FLOCKDESK_SENTRY_DSN"
_log = logging.getLogger("flockdesk.core")


# ────────────────────────────────────────────────────────────────
# Utility wrappers
# ────────────────────────────────────────────────────────────────


def async_slot(func: Callable[..., Awaitable[Any]]) -> Callable:
    """
    Decorator to make an `async def` Qt slot look synchronous.

    Qt does not understand `async def` methods directly.  Wrapping the coroutine
    ensures any exceptions are captured and re-routed to the central handler.
    """

    @Slot()
    @wraps(func)
    def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        loop.create_task(func(*args, **kwargs))

    return wrapper


# ────────────────────────────────────────────────────────────────
# Runtime configuration
# ────────────────────────────────────────────────────────────────


@dataclass
class RuntimeConfig:
    """
    In-memory representation of user / workspace configuration.
    """

    theme: str = "dark"
    autoupdate: bool = True
    plugin_search_paths: List[str] = field(
        default_factory=lambda: [str(PLUGIN_DIR.resolve())]
    )
    sentry_dsn: Optional[str] = None

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_FILE) -> "RuntimeConfig":
        if not path.exists():
            _log.warning("No config file found at %s – falling back to defaults.", path)
            return cls()
        try:
            with path.open("r") as fp:
                data = json.load(fp)
            return cls(**data)
        except Exception:  # pragma: no cover
            _log.exception("Failed to parse configuration – using defaults.")
            return cls()

    def save(self, path: Path = DEFAULT_CONFIG_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fp:
            json.dump(self.__dict__, fp, indent=2)
        _log.debug("Configuration persisted to %s", path)


# ────────────────────────────────────────────────────────────────
# Event bus
# ────────────────────────────────────────────────────────────────


class Event:
    """
    Simple event container.
    """

    __slots__ = ("type", "payload", "origin")

    def __init__(self, type: str, payload: Any = None, origin: Optional[str] = None):
        self.type = type
        self.payload = payload
        self.origin = origin

    def __repr__(self) -> str:  # pragma: no cover
        return f"Event(type={self.type!r}, origin={self.origin!r}, payload={self.payload!r})"


class EventBus(QObject):
    """
    Cross-process global event-bus.

    Internally implemented with:
    • A Qt `Signal` for UI thread-safe broadcasting.
    • A singleton asyncio event-loop for async subscribers.
    """

    qt_broadcast = Signal(object)  # Event

    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._loop = loop
        self._subscribers: Dict[str, List[Callable[[Event], Coroutine | None]]] = {}

        # Connect Qt → async
        self.qt_broadcast.connect(self._dispatch_qt)

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------

    def subscribe(
        self, event_type: str, callback: Callable[[Event], Awaitable | None]
    ) -> None:
        """
        Register a callback (async or sync) for a given event type.
        """
        self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event: Event) -> None:
        """
        Publish an event globally – thread safe via Qt signal.
        """
        self.qt_broadcast.emit(event)

    # ------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------

    @Slot(object)
    def _dispatch_qt(self, event: Event) -> None:
        """
        Fan out an event to registered callbacks.
        """
        for callback in self._subscribers.get(event.type, []):
            result = callback(event)
            if inspect.iscoroutine(result):
                self._loop.create_task(result)


# ────────────────────────────────────────────────────────────────
# Plugin manager
# ────────────────────────────────────────────────────────────────


@dataclass
class PluginMeta:
    """
    Metadata extracted from the plugin module.
    """

    name: str
    version: str
    module: ModuleType
    provides: Set[str] = field(default_factory=set)


class PluginManager:
    """
    Discovers and loads plugins from a configurable search path.
    """

    MANIFEST_ATTR = "FD_PLUGIN_MANIFEST"

    def __init__(self, bus: EventBus, cfg: RuntimeConfig):
        self._bus = bus
        self._cfg = cfg
        self._loaded: Dict[str, PluginMeta] = {}

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def discover(self) -> List[Path]:
        manifests: List[Path] = []
        for raw_dir in self._cfg.plugin_search_paths:
            path = Path(raw_dir).expanduser()
            if not path.exists():
                _log.debug("Plugin path %s does not exist – skipping.", path)
                continue
            manifests.extend(path.glob("*/__init__.py"))
        _log.info("Discovered %d potential plugins.", len(manifests))
        return manifests

    # ------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------

    def load_all(self) -> None:
        for manifest in self.discover():
            try:
                meta = self._load_plugin_module(manifest)
                self._loaded[meta.name] = meta
                _log.info("Loaded plugin %s v%s", meta.name, meta.version)
            except Exception:
                _log.error("Failed to load plugin at %s", manifest)
                _log.debug(traceback.format_exc())

    def _load_plugin_module(self, manifest: Path) -> PluginMeta:
        package_root = manifest.parent
        spec = importlib.util.spec_from_file_location(
            package_root.name, manifest, submodule_search_locations=[str(package_root)]
        )
        if spec is None or spec.loader is None:  # pragma: no cover
            raise ImportError(f"Cannot load plugin from {manifest}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)  # type: ignore[arg-type]

        manifest_dict = getattr(module, self.MANIFEST_ATTR, None)
        if manifest_dict is None:
            raise ValueError(
                f"Plugin {module.__name__} does not expose {self.MANIFEST_ATTR}"
            )

        meta = PluginMeta(
            name=manifest_dict["name"],
            version=manifest_dict.get("version", "0.0.0"),
            module=module,
            provides=set(manifest_dict.get("provides", [])),
        )

        # Call plugin initialiser if present
        init_callable = getattr(module, "setup", None)
        if callable(init_callable):
            init_callable(bus=self._bus, config=self._cfg)
        return meta


# ────────────────────────────────────────────────────────────────
# Crash handling / diagnostics
# ────────────────────────────────────────────────────────────────


def _init_logging(verbose: bool = False) -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    fmt = "[%(asctime)s] %(levelname)s %(name)s – %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, handlers=[handler]
    )


def _init_sentry(dsn: Optional[str]) -> None:
    if not dsn:
        _log.debug("Sentry disabled – no DSN provided.")
        return

    if sentry_sdk is None:
        _log.warning("sentry-sdk not installed;  skipping error reporting.")
        return

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.1,
        release=f"{APP_NAME}@{_read_version()}",
    )
    _log.info("Sentry initialised.")


def _read_version() -> str:
    try:
        from importlib.metadata import version

        return version("flockdesk")
    except Exception:
        return "0.0.0"


# ────────────────────────────────────────────────────────────────
# Qt Application bootstrap
# ────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    """
    Placeholder root window.  Real UI components are contributed via plugins.
    """

    def __init__(self, bus: EventBus, cfg: RuntimeConfig, plugin_manager: PluginManager):
        super().__init__()
        self._bus = bus
        self._cfg = cfg
        self._plugin_manager = plugin_manager
        self._init_ui()
        self._wire_events()

    # ------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------

    def _init_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 800)
        icon_path = Path(__file__).with_name("logo.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _wire_events(self) -> None:
        # Example: listen for global notifications
        self._bus.subscribe("global.notification", self._on_global_notification)

    async def _on_global_notification(self, ev: Event) -> None:
        """
        Display passive notification.
        """
        QMessageBox.information(self, "Notification", str(ev.payload))


# ────────────────────────────────────────────────────────────────
# Application life-cycle
# ────────────────────────────────────────────────────────────────


@dataclass
class Application:
    """
    The orchestrator that drives Qt <-> asyncio cooperation.
    """

    argv: List[str]
    cfg: RuntimeConfig = field(default_factory=RuntimeConfig)
    loop: asyncio.AbstractEventLoop = field(
        default_factory=lambda: asyncio.new_event_loop()
    )

    # ------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------

    def run(self) -> None:
        """
        Main entrypoint.  Does not return until application exit.
        """
        asyncio.set_event_loop(self.loop)
        self._parse_cli()

        _init_logging(verbose=os.getenv("FLOCKDESK_DEBUG", "").lower() in ("1", "true"))
        _init_sentry(self.cfg.sentry_dsn or os.getenv(SENTRY_DSN_ENV))

        # Qt must run in main thread
        app = QApplication(self.argv)
        app.setApplicationName(APP_NAME)
        app.setOrganizationName(ORG_NAME)

        # Prepare core services
        bus = EventBus(self.loop)
        plugin_manager = PluginManager(bus, self.cfg)

        # Load plugins in background to avoid UI freeze
        self.loop.create_task(self._load_plugins_async(plugin_manager))

        window = MainWindow(bus, self.cfg, plugin_manager)
        window.show()

        # Let Qt drive the asyncio loop
        timer = QTimer()
        timer.timeout.connect(lambda: None)
        timer.start(20)

        # Integrate loops
        self.loop.call_soon(lambda: _log.debug("Event loop started."))
        with self._enter_exception_handler():
            self.loop.run_until_complete(self._qt_event_loop(app))

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    async def _qt_event_loop(self, qt_app: QApplication) -> None:
        """
        Run Qt event loop inside asyncio until Qt exits.
        """
        await asyncio.get_running_loop().run_in_executor(None, qt_app.exec)

    async def _load_plugins_async(self, pm: PluginManager) -> None:
        await asyncio.sleep(0)  # yield to Qt render
        pm.load_all()
        _log.info("All plugins loaded (%d).", len(pm._loaded))

    def _parse_cli(self) -> None:
        parser = argparse.ArgumentParser(APP_NAME)
        parser.add_argument(
            "--config",
            type=Path,
            help="Override configuration file (JSON).",
        )
        parser.add_argument(
            "--disable-autoupdate",
            action="store_true",
            help="Disable automatic update checks.",
        )
        args, unknown = parser.parse_known_args(self.argv[1:])

        if args.config:
            self.cfg = RuntimeConfig.load(args.config)

        if args.disable_autoupdate:
            self.cfg.autoupdate = False

        if unknown:
            _log.debug("Ignored unknown CLI args: %s", unknown)

    # ------------------------------------------------------------
    # Context managers
    # ------------------------------------------------------------

    from contextlib import contextmanager

    @contextmanager
    def _enter_exception_handler(self):
        """
        Wrap event-loop execution to catch unhandled exceptions,
        send them to Sentry, and display a user-friendly message.
        """
        try:
            yield
        except Exception as exc:
            _log.critical("Unhandled exception: %s", exc, exc_info=exc)
            if sentry_sdk:
                sentry_sdk.capture_exception(exc)
            QMessageBox.critical(
                None,
                f"{APP_NAME} crashed",
                "Uh-oh!  Something went terribly wrong.  "
                "A crash report has been sent, and we're sorry for the inconvenience.",
            )
            sys.exit(1)


# ────────────────────────────────────────────────────────────────
# Main script entrypoint
# ────────────────────────────────────────────────────────────────


def main() -> None:  # noqa
    Application(sys.argv).run()


if __name__ == "__main__":
    main()
```