```python
"""
module_40.py
PulseStream-Nexus – Monitoring & Observability Utilities
-------------------------------------------------------

This module implements a lightweight, framework-agnostic Observer layer that can
be attached to any PulseStream pipeline component (use-cases, interactors,
transformers, etc.).  It ships with batteries-included observers for Prometheus,
structured logging, and Sentry, whilst remaining agnostic of those libraries at
import-time.  Fallback stubs are used when an optional dependency is missing so
that the core business logic never fails because of monitoring concerns.

Usage
-----

>>> from src import module_40 as m40
>>>
>>> @m40.observe_pipeline("twitter_ingest")
... def ingest(record):
...     # ... business logic ...
...     return transformed
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import threading
import time
import types
import typing as _t
from enum import Enum, auto

###############################################################################
# Public constants & typing aliases
###############################################################################

ObserverT = _t.Protocol  # alias for readability

LOGGER_NAME = "pulsestream.monitoring"
DEFAULT_PROM_PORT = int(os.getenv("PULSE_PROM_PORT", "9095"))


###############################################################################
# Logging setup (can be overridden by application bootstrap)
###############################################################################

_logger = logging.getLogger(LOGGER_NAME)
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    _handler.setFormatter(_formatter)
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)


###############################################################################
# Base Observer pattern implementation
###############################################################################

class PipelineEvent(Enum):
    """
    Enumerates lifecycle events emitted by an instrumented function.
    """
    STARTED = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    TIMEOUT = auto()


class PipelineSubject:
    """
    A thread-safe subject that manages a collection of observers.  Observers can
    be shared at the process level *or* scoped to the current thread.
    """

    _global_observers: set["Observer"] = set()
    _thread_local = threading.local()

    @classmethod
    def register(cls, observer: "Observer", thread_local: bool = False) -> None:
        """
        Register a new observer.

        Parameters
        ----------
        observer: Observer
            The observer instance to register.
        thread_local: bool, default False
            When True, the observer will only receive events from the current
            thread, allowing tests to attach / isolate observers easily.
        """
        if thread_local:
            bag = getattr(cls._thread_local, "observers", None)
            if bag is None:
                bag = cls._thread_local.observers = set()
            bag.add(observer)
        else:
            cls._global_observers.add(observer)
        _logger.debug("Registered observer %s (thread_local=%s)", observer, thread_local)

    @classmethod
    def unregister(cls, observer: "Observer") -> None:
        """
        Unregister an observer from both global and thread-local contexts.
        """
        cls._global_observers.discard(observer)
        bag = getattr(cls._thread_local, "observers", set())
        bag.discard(observer)
        _logger.debug("Unregistered observer %s", observer)

    # --------------------------------------------------------------------- #
    # The actual “notify” implementation
    # --------------------------------------------------------------------- #

    @classmethod
    def notify(
        cls,
        event: PipelineEvent,
        timer_name: str,
        exc: BaseException | None,
        duration_ms: float | None,
        **meta,
    ) -> None:
        """
        Deliver an event to all observers.  The method intentionally swallows
        any exception raised by observers, logging it to avoid cascading
        failures in the business code.
        """
        observers: set["Observer"] = set(cls._global_observers)
        observers.update(getattr(cls._thread_local, "observers", set()))

        for observer in observers:
            try:
                observer.on_event(
                    event=event,
                    timer_name=timer_name,
                    exc=exc,
                    duration_ms=duration_ms,
                    meta=meta,
                )
            except Exception as err:  # pylint: disable=broad-except
                _logger.error("Observer %s failed: %s", observer, err, exc_info=err)


class Observer:
    """
    Base class / interface for observers.  Concrete implementations should
    implement :py:meth:`on_event`.
    """

    def on_event(
        self,
        *,
        event: PipelineEvent,
        timer_name: str,
        exc: BaseException | None,
        duration_ms: float | None,
        meta: dict[str, _t.Any],
    ) -> None:  # pragma: no cover
        raise NotImplementedError


###############################################################################
# Concrete observers
###############################################################################

class PrometheusObserver(Observer):
    """
    Emits latency / counter metrics to Prometheus using `prometheus_client`.
    """

    #: lazily initialised members
    _counter: "types.ModuleType" | None = None
    _hist: "types.ModuleType" | None = None
    _started_httpd: bool = False
    _lock = threading.Lock()

    def __init__(self, port: int = DEFAULT_PROM_PORT):
        # Optionally start the HTTP exposition
        self._port = port
        self._ensure_client()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def _ensure_client(cls) -> None:
        with cls._lock:
            if cls._counter is not None:
                return

            try:
                import prometheus_client as prom
            except ModuleNotFoundError:  # pragma: no cover
                _logger.warning("Prometheus client not installed; metrics disabled.")
                cls._counter = cls._hist = None
                return

            cls._counter = prom.Counter(
                "pulsestream_pipeline_events_total",
                "PulseStream pipeline events",
                ["name", "event"],
            )
            cls._hist = prom.Histogram(
                "pulsestream_pipeline_duration_ms",
                "PulseStream pipeline duration in milliseconds",
                ["name"],
                buckets=(
                    .5,
                    1,
                    5,
                    10,
                    50,
                    100,
                    250,
                    500,
                    1000,
                    2500,
                    5000,
                    10000,
                ),
            )

            if not cls._started_httpd:
                prom.start_http_server(DEFAULT_PROM_PORT, addr="0.0.0.0")
                cls._started_httpd = True
                _logger.info("Prometheus metrics HTTP server started on :%d", DEFAULT_PROM_PORT)

    # ------------------------------------------------------------------ #
    # Observer API
    # ------------------------------------------------------------------ #

    def on_event(
        self,
        *,
        event: PipelineEvent,
        timer_name: str,
        exc: BaseException | None,
        duration_ms: float | None,
        meta: dict[str, _t.Any],
    ) -> None:
        if self._counter is None:  # libs not available
            return

        # increment counter
        self._counter.labels(timer_name, event.name.lower()).inc()

        # record latency only on success
        if event is PipelineEvent.SUCCEEDED and duration_ms is not None:
            self._hist.labels(timer_name).observe(duration_ms)


class LogObserver(Observer):
    """
    Sends structured pipeline events to the application logger.
    """

    def __init__(self, level: int = logging.INFO) -> None:
        self._level = level

    def on_event(
        self,
        *,
        event: PipelineEvent,
        timer_name: str,
        exc: BaseException | None,
        duration_ms: float | None,
        meta: dict[str, _t.Any],
    ) -> None:
        message = f"[{timer_name}] {event.name}"
        if duration_ms is not None:
            message += f" | {duration_ms:.2f} ms"

        if exc:
            _logger.log(self._level, "%s | exception=%s", message, exc)
        else:
            _logger.log(self._level, message)


class SentryObserver(Observer):
    """
    Reports failures to Sentry using `sentry_sdk`, but only when exceptions
    occur.
    """

    def __init__(self) -> None:
        try:
            import sentry_sdk  # noqa: F401
            self._enabled = True
        except ModuleNotFoundError:  # pragma: no cover
            _logger.warning("sentry_sdk not installed; SentryObserver disabled.")
            self._enabled = False

    def on_event(
        self,
        *,
        event: PipelineEvent,
        timer_name: str,
        exc: BaseException | None,
        duration_ms: float | None,
        meta: dict[str, _t.Any],
    ) -> None:
        if not self._enabled or exc is None:
            return

        import sentry_sdk

        sentry_sdk.capture_exception(
            error=exc,
            scope=lambda s: s.set_extra("pipeline_name", timer_name),
        )


###############################################################################
# Decorators & Context Managers
###############################################################################

_F = _t.TypeVar("_F", bound=_t.Callable[..., _t.Any])


def observe_pipeline(name: str | None = None, *, timeout: float | None = None) -> _t.Callable[[_F], _F]:
    """
    Decorator that automatically instruments a function, emitting lifecycle
    events to registered observers.

    Parameters
    ----------
    name : str, optional
        Logical name of the pipeline step.  When omitted, the wrapped function’s
        ``__qualname__`` is used.
    timeout : float, optional
        Maximum allowed runtime in seconds.  If the wrapped function exceeds
        this threshold, a TIMEOUT event is emitted (the function keeps running).

    Returns
    -------
    Callable
        The wrapped function.
    """

    def decorator(func: _F) -> _F:  # type: ignore[misc]
        step_name = name or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: _t.Any, **kwargs: _t.Any):  # type: ignore[override]
            start_ns = time.perf_counter_ns()
            PipelineSubject.notify(
                PipelineEvent.STARTED, step_name, exc=None, duration_ms=None
            )

            timed_out = False
            timer: threading.Timer | None = None

            def _timeout():
                nonlocal timed_out
                timed_out = True
                PipelineSubject.notify(
                    PipelineEvent.TIMEOUT, step_name, exc=None, duration_ms=None
                )

            if timeout is not None:
                timer = threading.Timer(timeout, _timeout)
                timer.daemon = True
                timer.start()

            exc: BaseException | None = None
            try:
                result = func(*args, **kwargs)
                return result
            except BaseException as error:  # pylint: disable=broad-except
                exc = error
                raise
            finally:
                if timer is not None:
                    timer.cancel()

                duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
                event = (
                    PipelineEvent.FAILED if exc else
                    (PipelineEvent.TIMEOUT if timed_out else PipelineEvent.SUCCEEDED)
                )
                PipelineSubject.notify(
                    event, step_name, exc=exc, duration_ms=duration_ms
                )

        return typing.cast(_F, wrapper)

    return decorator


@contextlib.contextmanager
def scoped_observer(observer: Observer) -> _t.Iterator[None]:
    """
    Convenience context manager that registers an observer for the current
    thread and automatically unregisters it upon exit.  Useful in unit tests.

    Example
    -------
    >>> with scoped_observer(LogObserver()):
    ...     run_pipeline()
    """
    PipelineSubject.register(observer, thread_local=True)
    try:
        yield
    finally:
        PipelineSubject.unregister(observer)


###############################################################################
# On-import bootstrap – attach default observers if disabled explicitly
###############################################################################

if os.getenv("PULSE_DISABLE_DEFAULT_METRICS", "").lower() not in {"1", "true"}:
    PipelineSubject.register(LogObserver())
    PipelineSubject.register(PrometheusObserver())
    PipelineSubject.register(SentryObserver())

###############################################################################
# Guard for “python -m” test runs
###############################################################################

if __name__ == "__main__":  # pragma: no cover
    # Simple smoke test
    @observe_pipeline("demo_step", timeout=2)
    def _demo():
        time.sleep(0.1)
        return "✓"

    print(_demo())
```