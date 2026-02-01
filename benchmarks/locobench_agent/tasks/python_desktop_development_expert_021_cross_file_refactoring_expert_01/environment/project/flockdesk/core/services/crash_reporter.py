```python
"""
flockdesk.core.services.crash_reporter
--------------------------------------

Centralised crash-reporting facility for the FlockDesk desktop client.

The reporter fulfils several goals:

1. Registers global hooks (sys.excepthook, threading.excepthook, Qt message
   handler) so that *any* uncaught exception that bubbles up inside the main
   process or one of the micro-front-ends is intercepted.

2. Serialises rich diagnostic payloads (stacktrace, runtime information,
   plugin metadata, recent event-bus traffic) and uploads them to Sentry.
   When Sentry is not available or a DSN has not been configured, it silently
   downgrades to local logging – never crashing the host application.

3. Listens on the internal event bus so that sandboxed services running in
   separate processes/threads can push their crash reports via IPC without
   a hard dependency on Sentry.

Usage
~~~~~
    from flockdesk.core.services.crash_reporter import crash_reporter

    try:
        1 / 0
    except ZeroDivisionError:
        crash_reporter.capture_exception()

The singleton `crash_reporter` is initialised automatically on import.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import queue
import sys
import threading
import time
import traceback
import typing as _t
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

try:
    import sentry_sdk
    from sentry_sdk.integrations.threading import ThreadingIntegration
except ImportError:  # pragma: no cover – sentry is an optional external
    sentry_sdk = None  # type: ignore

# -----------------------------------------------------------------------------
# Internal dependencies – they may not exist when this file is unit-tested in
# isolation, therefore we fall back to lightweight stubs.
# -----------------------------------------------------------------------------
try:
    from flockdesk.core.bus import EventBus, Event  # pragma: no cover
except Exception:  # pylint: disable=broad-except
    class Event(_t.TypedDict, total=False):
        topic: str
        payload: dict

    class EventBus:  # simple stub
        def __init__(self) -> None:
            self._subscribers: dict[str, list[_t.Callable[[Event], None]]] = {}

        def subscribe(self, topic: str, callback: _t.Callable[[Event], None]) -> None:
            self._subscribers.setdefault(topic, []).append(callback)

        def publish(self, topic: str, payload: dict | None = None) -> None:
            for cb in self._subscribers.get(topic, []):
                try:
                    cb({"topic": topic, "payload": payload or {}})
                except Exception:  # pragma: no cover
                    logging.getLogger(__name__).exception("CrashReporter bus stub error")

        # Singleton stub
    _GLOBAL_BUS = EventBus()

    def get_global_event_bus() -> EventBus:
        return _GLOBAL_BUS
else:
    from flockdesk.core.bus import get_global_event_bus


__all__ = ["CrashReporter", "crash_reporter"]

_LOG = logging.getLogger(__name__)


class CrashReporter:
    """
    Encapsulates crash capturing and forwarding logic.

    Instantiate once (see the module-level singleton `crash_reporter`).
    """

    # How many crash reports we keep in memory for on-demand retrieval
    RING_BUFFER_SIZE = 32

    # Topic names for inter-service communication
    BUS_TOPIC_CRASH = "core.crash"

    def __init__(
        self,
        bus: EventBus | None = None,
        *,
        dsn: str | None = None,
        release: str | None = None,
        environment: str | None = None,
        enabled: bool | None = None,
        debug: bool = False,
    ) -> None:
        self._bus = bus or get_global_event_bus()
        self._ring_buffer: deque[dict] = deque(maxlen=self.RING_BUFFER_SIZE)
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="crash-reporter-worker",
        )
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._session_id = str(uuid4())
        self._debug = debug

        self._configured = False
        self._dsn = dsn or os.getenv("FLOCKDESK_SENTRY_DSN")
        self._enabled = (enabled if enabled is not None else True) and bool(self._dsn)

        self._init_sentry(
            dsn=self._dsn,
            release=release,
            environment=environment or os.getenv("FLOCKDESK_ENV", "production"),
        )
        self._install_global_hooks()
        self._bus.subscribe(self.BUS_TOPIC_CRASH, self._on_bus_crash_report)

        # Start background consumer thread
        self._stop_flag = threading.Event()
        self._consumer_thread = threading.Thread(
            target=self._consumer_loop,
            name="crash-reporter-consumer",
            daemon=True,
        )
        self._consumer_thread.start()

        _LOG.debug("CrashReporter initialised – enabled=%s, sentry=%s", self._enabled, bool(sentry_sdk))
        if self._debug:
            _LOG.setLevel(logging.DEBUG)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def capture_exception(
        self,
        exc: BaseException | None = None,
        *,
        context: dict | None = None,
        handled: bool = False,
        notify_bus: bool = True,
    ) -> str:
        """
        Capture the supplied exception (or *current* one if `exc` is None) and
        forward it to Sentry / local log. Returns the generated report id.
        """
        exc = exc or sys.exc_info()[1]
        if exc is None:
            raise ValueError("capture_exception called with no active exception")

        report_id = str(uuid4())
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        payload = {
            "id": report_id,
            "session": self._session_id,
            "timestamp": time.time(),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "stack_trace": tb_str,
            "context": context or {},
            "handled": handled,
            "process_id": os.getpid(),
            "thread_name": threading.current_thread().name,
        }

        self._enqueue(payload)

        if notify_bus:
            # Broadcast so other interested services (analytics, UI) can react
            self._bus.publish(self.BUS_TOPIC_CRASH, payload)

        return report_id

    def last_reports(self) -> list[dict]:
        """Return a list of the most recent crash reports in chronological order."""
        return list(self._ring_buffer)

    # --------------------------------------------------------------------- #
    # Internal plumbing
    # --------------------------------------------------------------------- #

    def _init_sentry(
        self,
        *,
        dsn: str | None,
        release: str | None,
        environment: str,
    ) -> None:
        if not self._enabled:
            _LOG.info("CrashReporter disabled – no DSN configured")
            return
        if not sentry_sdk:
            _LOG.warning("sentry-sdk package missing – crash reporting disabled")
            self._enabled = False
            return

        try:
            sentry_sdk.init(
                dsn=dsn,
                release=release,
                environment=environment,
                integrations=[ThreadingIntegration(propagate_hub=True)],
                send_default_pii=False,
                traces_sample_rate=0.0,  # We only care about crashes here
            )
            self._configured = True
            _LOG.info("Sentry initialised – env=%s, release=%s", environment, release)
        except Exception:  # pylint: disable=broad-except
            _LOG.exception("Failed to initialise Sentry – crash reporting disabled")
            self._enabled = False

    def _enqueue(self, payload: dict) -> None:
        """Queue a payload for asynchronous upload + local buffering."""
        try:
            # Keep in memory for local retrieval
            self._ring_buffer.append(payload)
            self._queue.put_nowait(payload)
        except queue.Full:  # pragma: no cover
            _LOG.error("CrashReporter queue is full – dropping report")

    # ------------------ Global hook installation -------------------------

    def _install_global_hooks(self) -> None:
        # Python uncaught exceptions
        sys.excepthook = self._sys_excepthook  # type: ignore[assignment]

        # Threading exceptions (Python ≥3.8)
        if hasattr(threading, "excepthook"):
            threading.excepthook = self._threading_excepthook  # type: ignore

        # Qt logging – only if PySide6 is present
        try:
            from PySide6.QtCore import qInstallMessageHandler, QtMsgType  # type: ignore

            def qt_message_handler(msg_type, context, message):  # pylint: disable=unused-argument
                if msg_type in (QtMsgType.QtFatalMsg, QtMsgType.QtCriticalMsg):
                    self.capture_exception(RuntimeError(message), handled=False)
            qInstallMessageHandler(qt_message_handler)  # type: ignore[arg-type]
        except ImportError:  # pragma: no cover
            pass  # Qt not installed in this runtime

    # --------------------- Hook implementations --------------------------

    def _sys_excepthook(self, exc_type, exc_val, exc_tb):  # noqa: D401
        """sys.excepthook replacement."""
        try:
            self.capture_exception(exc_val, handled=False, notify_bus=True)
        finally:
            # Original behaviour – print to stderr so developers see it
            traceback.print_exception(exc_type, exc_val, exc_tb)

    def _threading_excepthook(self, args):  # noqa: D401
        """threading.excepthook replacement (Python ≥3.8)."""
        self.capture_exception(args.exc_value, handled=False, notify_bus=True)

    # ------------------------ Event bus bridge --------------------------

    def _on_bus_crash_report(self, event: Event) -> None:
        """
        Receive crash reports sent by other micro-front-ends. We treat them as
        regular payloads but mark `handled=True` because the originating
        service decided to push the report explicitly.
        """
        payload = event.get("payload", {})
        payload.setdefault("relayed", True)
        self._enqueue(payload)

    # ------------------ Background consumer + uploader ------------------

    def _consumer_loop(self) -> None:
        while not self._stop_flag.is_set():
            try:
                payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            self._process_payload(payload)

    def _process_payload(self, payload: dict) -> None:
        if self._enabled and self._configured and sentry_sdk:
            self._executor.submit(self._send_to_sentry, payload)
        else:
            self._executor.submit(self._log_local, payload)

    # --------------------- Transmission helpers -------------------------

    def _send_to_sentry(self, payload: dict) -> None:
        try:
            with sentry_sdk.push_scope() as scope:
                scope.set_context("flockdesk", {"session": payload["session"], "pid": payload["process_id"]})
                scope.set_extra("payload", json.dumps(payload, indent=2) if self._debug else "<payload redacted>")
                sentry_sdk.capture_message(
                    f"FlockDesk crash report [{payload['exception_type']}]",
                    level="fatal" if not payload.get("handled") else "error",
                )
        except Exception:  # pylint: disable=broad-except
            # Sentry call failed – fall back to local logging
            self._log_local(payload)

    def _log_local(self, payload: dict) -> None:
        log_path = (
            Path(os.getenv("FLOCKDESK_USER_DATA", Path.home() / ".flockdesk"))
            / "logs"
            / "crash_reports.log"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, indent=2))
                fp.write("\n\n")
            _LOG.info("Crash payload written to %s (id=%s)", log_path, payload["id"])
        except Exception:  # pylint: disable=broad-except
            _LOG.exception("Failed to write crash payload locally")

    # ----------------------------------------------------------------- #
    # Shutdown
    # ----------------------------------------------------------------- #

    def shutdown(self, timeout: float = 2.0) -> None:
        """Flush queues and stop background threads. Call at application exit."""
        self._stop_flag.set()
        self._consumer_thread.join(timeout=timeout)
        self._executor.shutdown(wait=False)
        _LOG.debug("CrashReporter shutdown complete")


# ---------------------------------------------------------------------
# Public singleton – import this from other modules
# ---------------------------------------------------------------------
crash_reporter = CrashReporter()

```