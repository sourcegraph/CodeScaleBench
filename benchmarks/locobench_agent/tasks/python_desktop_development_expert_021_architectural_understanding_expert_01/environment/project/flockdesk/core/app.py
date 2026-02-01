```python
"""
flockdesk.core.app
==================

The central orchestration runtime for the FlockDesk desktop suite.
Responsible for:

* Application-wide lifecycle & graceful shutdown
* Global event-bus for intra-service communication
* Plugin discovery, dependency wiring and hot-reload hooks
* Persisted user settings & dynamic preference updates
* Crash-reporting funnel to Sentry ( sandboxed per-service )
* Asyncio <-> Qt/GUI message-pump coherency
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import signal
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    Iterable,
    List,
    Optional,
    Protocol,
    Set,
    Tuple,
    Union,
)

# --------------------------------------------------------------------------- #
# Optional / soft dependencies                                               #
# --------------------------------------------------------------------------- #
try:
    from PySide6.QtCore import QCoreApplication, QObject, QTimer  # type: ignore
except ModuleNotFoundError:  # Headless / non-GUI environments
    QCoreApplication = None  # type: ignore
    QObject = object  # type: ignore
    QTimer = None  # type: ignore

try:
    import appdirs  # type: ignore
except ModuleNotFoundError:
    appdirs = None

try:
    import sentry_sdk  # type: ignore
except ModuleNotFoundError:
    sentry_sdk = None  # noqa: N816

# --------------------------------------------------------------------------- #
# Logging setup                                                              #
# --------------------------------------------------------------------------- #
logger = logging.getLogger("flockdesk.core")
logger.setLevel(logging.INFO)

_handler = logging.StreamHandler(stream=sys.stdout)
_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logger.addHandler(_handler)

# --------------------------------------------------------------------------- #
# Typing                                                                     #
# --------------------------------------------------------------------------- #
JSON_T = Union[str, int, float, bool, None, Dict[str, "JSON_T"], List["JSON_T"]]


class Event:
    """
    A lightweight event envelope exchanged over the FlockDesk event bus.
    """

    __slots__ = ("topic", "payload", "meta")

    def __init__(self, topic: str, payload: Any = None, **meta: Any) -> None:
        self.topic: str = topic
        self.payload: Any = payload
        self.meta: Dict[str, Any] = meta

    # --------------------------------------------------------------------- #
    # Convenience helpers                                                   #
    # --------------------------------------------------------------------- #
    def __repr__(self) -> str:  # pragma: no cover
        return f"Event({self.topic!r}, payload={self.payload!r}, meta={self.meta!r})"


Listener = Callable[[Event], Union[None, Awaitable[None]]]


# --------------------------------------------------------------------------- #
# Event Bus Implementation                                                   #
# --------------------------------------------------------------------------- #
class EventBus:
    """
    A minimal in-process publish/subscribe mechanism.

    The bus is intentionally *naïve* but good enough for inter-plugin traffic.
    More advanced requirements (wildcards, QoS, type routing) can be layered
    on top by dedicated broker services.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[Listener]] = {}
        self._loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()

    # --------------------------------------------------------------------- #
    # Subscription                                                          #
    # --------------------------------------------------------------------- #
    def subscribe(self, topic: str, listener: Listener) -> None:
        listeners = self._subscribers.setdefault(topic, set())
        listeners.add(listener)
        logger.debug("Listener %s subscribed to topic %s", listener, topic)

    def unsubscribe(self, topic: str, listener: Listener) -> None:
        try:
            self._subscribers[topic].discard(listener)
            logger.debug("Listener %s unsubscribed from topic %s", listener, topic)
        except KeyError:
            logger.warning("Attempted to unsubscribe unknown topic %s", topic)

    # --------------------------------------------------------------------- #
    # Publishing                                                            #
    # --------------------------------------------------------------------- #
    def publish(self, topic: str, payload: Any = None, **meta: Any) -> None:
        """
        Schedule the dispatch of an event to all interested listeners.
        """
        event = Event(topic, payload, **meta)
        logger.debug("Publishing event %s", event)
        listeners = self._subscribers.get(topic, set()).copy()

        for listener in listeners:
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    # Fire-and-forget, but capture exceptions.
                    task = self._loop.create_task(result)  # type: ignore[arg-type]
                    task.add_done_callback(self._capture_async_exception)
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception(
                    "Synchronous listener %s crashed while handling %s: %s",
                    listener,
                    topic,
                    exc,
                )

    # --------------------------------------------------------------------- #
    # Helpers                                                               #
    # --------------------------------------------------------------------- #
    def _capture_async_exception(self, task: asyncio.Task[Any]) -> None:  # noqa: D401
        """
        Funnel unhandled exceptions from background tasks into the logger.
        """
        if task.cancelled():
            return
        if exc := task.exception():
            logger.exception("Async listener raised: %s", exc)


# --------------------------------------------------------------------------- #
# Plugin System                                                              #
# --------------------------------------------------------------------------- #
class Plugin(Protocol):
    """
    Public interface that all plugins must comply with.
    """

    name: str
    version: str

    def setup(self, bus: EventBus) -> None: ...
    async def start(self) -> None: ...
    async def shutdown(self) -> None: ...


class PluginLoader:
    """
    Discover & instantiate plugins.

    *User* plugins are loaded from the following search order:

    1. `$FLOCKDESK_PLUGINS` (semicolon separated list of paths)
    2. `~/.flockdesk/plugins`
    3. `<install-root>/flockdesk/plugins`
    """

    SEARCH_LOCATIONS: Tuple[Path, ...] = (
        Path(os.getenv("FLOCKDESK_PLUGINS", "")),
        Path.home() / ".flockdesk" / "plugins",
        Path(__file__).resolve().parent.parent / "plugins",
    )

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._plugins: List[Plugin] = []

    # --------------------------------------------------------------------- #
    # Discovery                                                             #
    # --------------------------------------------------------------------- #
    def discover(self) -> List[Plugin]:
        logger.info("Discovering plugins …")
        for location in self.SEARCH_LOCATIONS:
            if not location or not location.exists():
                continue
            for path in location.glob("*/__init__.py"):
                try:
                    plugin = self._load_module(path)
                    self._plugins.append(plugin)
                    logger.info("Loaded plugin: %s %s", plugin.name, plugin.version)
                except Exception:  # pylint: disable=broad-except
                    logger.error(
                        "Failed to load plugin at %s:\n%s",
                        path,
                        traceback.format_exc(),
                    )
        return self._plugins

    def _load_module(self, init_file: Path) -> Plugin:
        module_name = f"flockdesk.plugin.{init_file.parent.name}"
        spec = importlib.util.spec_from_file_location(module_name, init_file)
        if not spec or not spec.loader:
            raise ImportError(f"Cannot build spec for {init_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[arg-type]

        if not hasattr(module, "Plugin"):
            raise AttributeError(
                f"{module_name} does not expose a 'Plugin' class"
            )  # noqa: TRY003

        plugin_cls = getattr(module, "Plugin")
        plugin: Plugin = plugin_cls()  # type: ignore[call-arg]

        plugin.setup(self._bus)
        return plugin

    # --------------------------------------------------------------------- #
    # Lifecycle                                                             #
    # --------------------------------------------------------------------- #
    async def start_all(self) -> None:
        for plugin in self._plugins:
            try:
                await plugin.start()
                logger.info("Plugin started: %s", plugin.name)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Plugin %s failed to start", plugin.name)

    async def shutdown_all(self) -> None:
        for plugin in reversed(self._plugins):
            try:
                await plugin.shutdown()
                logger.info("Plugin stopped: %s", plugin.name)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Plugin %s failed to shutdown", plugin.name)


# --------------------------------------------------------------------------- #
# Settings / Configuration                                                   #
# --------------------------------------------------------------------------- #
class SettingsManager:
    """
    Persisted key/value store backed by a JSON blob in the user's config dir.
    """

    FILE_NAME = "settings.json"

    def __init__(self) -> None:
        self._data: Dict[str, JSON_T] = {}
        self._path = self._resolve_path()
        self._load()

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #
    def get(self, key: str, default: JSON_T | None = None) -> JSON_T | None:
        return self._data.get(key, default)

    def set(self, key: str, value: JSON_T) -> None:
        self._data[key] = value
        self._save_async()

    def all(self) -> Dict[str, JSON_T]:
        return dict(self._data)

    # --------------------------------------------------------------------- #
    # Persistence                                                           #
    # --------------------------------------------------------------------- #
    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                logger.debug("Settings loaded from %s", self._path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load settings (%s), starting fresh", exc)
            self._data = {}

    def _save_async(self) -> None:
        """
        Off-load writing to disk to avoid blocking the GUI / event-loop.
        """

        async def _writer() -> None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
                logger.debug("Settings persisted to %s", self._path)
            except OSError as exc:
                logger.error("Could not persist settings: %s", exc)

        asyncio.get_event_loop().create_task(_writer())

    # --------------------------------------------------------------------- #
    # Helpers                                                               #
    # --------------------------------------------------------------------- #
    @staticmethod
    def _resolve_path() -> Path:
        if appdirs:
            cfg_dir = Path(appdirs.user_config_dir("FlockDesk", "Flockware"))
        else:
            cfg_dir = Path.home() / ".config" / "flockdesk"
        return cfg_dir / SettingsManager.FILE_NAME


# --------------------------------------------------------------------------- #
# Crash / Diagnostics                                                        #
# --------------------------------------------------------------------------- #
class CrashReporter:
    """
    Thin wrapper around Sentry so we can easily replace/disable later on.
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        self._enabled: bool = False
        if dsn and sentry_sdk:
            sentry_sdk.init(dsn=dsn, release="flockdesk@1.0.0")
            self._enabled = True
            logger.info("Crash reporting enabled")
        elif dsn:
            logger.warning("sentry-sdk not installed, crash reporting disabled")

    async def capture_exception(self, exc: BaseException) -> None:
        if self._enabled:
            sentry_sdk.capture_exception(exc)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Core Application                                                           #
# --------------------------------------------------------------------------- #
class FlockDeskCoreApp(QObject if QObject is not object else object):  # type: ignore[misc]
    """
    Central bootstrap for FlockDesk.

    Spins up the event-bus, plugin runtime, setting manager, and bridges
    between the asyncio reactor and Qt's message-pump if available.
    """

    def __init__(self, *, headless: bool = False) -> None:
        if not headless and QCoreApplication is None:
            raise RuntimeError(
                "PySide6 not installed ‑ cannot run in GUI mode. "
                "Pass `headless=True` to run without Qt."
            )

        super().__init__()  # type: ignore[misc]
        self._headless = headless
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self.bus = EventBus()
        self.settings = SettingsManager()
        self.crash = CrashReporter(
            dsn=self.settings.get("sentry_dsn")  # type: ignore[arg-type]
        )
        self._plugin_loader = PluginLoader(self.bus)

        self._closing = asyncio.Event()

        # Connect SIGINT / SIGTERM
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)

        if not self._headless:
            self._qt_app: QCoreApplication = QCoreApplication(sys.argv)  # type: ignore[assignment]
            # Pump asyncio via Qt's event loop every 15ms
            QTimer.singleShot(0, self._qt_asyncio_integration_tick)  # type: ignore[arg-type]

    # --------------------------------------------------------------------- #
    # Bootstrap                                                             #
    # --------------------------------------------------------------------- #
    def run(self) -> None:
        """
        Synchronous entry-point; block until shutdown completes.
        """
        logger.info("Starting FlockDesk …")
        try:
            self._loop.run_until_complete(self._async_main())
        finally:
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()
            logger.info("FlockDesk stopped")

    async def _async_main(self) -> None:
        """
        Coroutine that manages the asynchronous lifecycle.
        """
        # Plugin discovery/startup
        self._plugin_loader.discover()
        await self._plugin_loader.start_all()

        # Run until a shutdown signal is received
        await self._closing.wait()

        # Tear-down
        await self._plugin_loader.shutdown_all()

    # --------------------------------------------------------------------- #
    # Shutdown & Signals                                                    #
    # --------------------------------------------------------------------- #
    def _signal_handler(self, signum: int, _frame: Any | None = None) -> None:
        logger.info("Received signal %s, shutting down …", signum)
        self._loop.call_soon_threadsafe(self._closing.set)

    # --------------------------------------------------------------------- #
    # Qt / Async Integration                                                #
    # --------------------------------------------------------------------- #
    def _qt_asyncio_integration_tick(self) -> None:  # pragma: no cover
        """
        Execute all asyncio tasks waiting on the loop & re-schedule next tick.
        """
        try:
            self._loop.call_soon(self._loop.stop)
            self._loop.run_forever()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Error during asyncio-Qt integration tick: %s", exc)
            self._loop.create_task(self.crash.capture_exception(exc))
        finally:
            # Re-schedule as long as the application is alive
            if not self._closing.is_set():
                QTimer.singleShot(15, self._qt_asyncio_integration_tick)  # type: ignore[arg-type]

    # --------------------------------------------------------------------- #
    # Convenience helpers                                                   #
    # --------------------------------------------------------------------- #
    def quit(self) -> None:
        """
        Can be called by plugins/UI to request a graceful shutdown.
        """
        self._closing.set()


# --------------------------------------------------------------------------- #
# Entrypoint                                                                 #
# --------------------------------------------------------------------------- #
def _main() -> None:  # pragma: no cover
    """
    CLI bootstrap mainly for development/testing purposes.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Launch FlockDesk core service")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without Qt (no GUI) – suitable for CI or server mode.",
    )
    args = parser.parse_args()

    app = FlockDeskCoreApp(headless=args.headless)
    app.run()


if __name__ == "__main__":
    _main()
```