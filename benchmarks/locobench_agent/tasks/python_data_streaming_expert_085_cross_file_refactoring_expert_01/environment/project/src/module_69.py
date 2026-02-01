```python
"""
src/module_69.py
~~~~~~~~~~~~~~~~

PulseStream Nexus – Streaming Instrumentation Utilities
------------------------------------------------------

This module provides *production-grade* instrumentation helpers that can be used
to wrap any callable pipeline stage and transparently emit metrics / alerts
without polluting domain code with operational concerns.  It strongly embraces
Clean-Architecture and the Observer-Pattern:

    +----------------+        +-------------------+
    |  Domain Stage  | ---->  |  ObservableStage  |  <-- inject observers
    +----------------+        +---------+---------+
                                        |
                        +---------------+---------------+
                        |               |               |
          +-------------------+  +---------------+  +---------------+
          | PrometheusObserver|  | LoggingObserver |  | SentryObserver|
          +-------------------+  +---------------+  +---------------+

Key features
~~~~~~~~~~~~
*   Per-record latency, error and throughput counters.
*   Thread-safe observer registry (allows dynamic subscription).
*   Prometheus exposition that **survives missing dependencies** (no-ops).
*   Optional Sentry integration for structured error capture.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from types import TracebackType
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Sequence, Type, Union

# --------------------------------------------------------------------------- #
# 3rd-party (soft) dependencies
# --------------------------------------------------------------------------- #

try:  # Prometheus is recommended but not strictly required at runtime.
    from prometheus_client import Counter, Histogram, start_http_server
except ImportError:  # pragma: no cover – fallback for environments without prometheus_client
    Counter = Histogram = None  # type: ignore
    start_http_server = lambda *_, **__: None  # type: ignore


try:  # Optional sentry error reporting
    import sentry_sdk
except ImportError:  # pragma: no cover
    sentry_sdk = None  # type: ignore

# --------------------------------------------------------------------------- #
# Logging configuration (library-friendly)
# --------------------------------------------------------------------------- #

logger = logging.getLogger(__name__)
if not logger.handlers:  # library default: avoid duplicate handlers on re-import
    _ch = logging.StreamHandler()
    _ch.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d – %(message)s"
        )
    )
    logger.addHandler(_ch)
    logger.setLevel(logging.INFO)

# --------------------------------------------------------------------------- #
# Domain events
# --------------------------------------------------------------------------- #


class StreamEventType(Enum):
    """Semantic categories for pipeline-stage notifications."""

    RECORD_PROCESSED = auto()
    BATCH_COMPLETED = auto()
    PIPELINE_ERROR = auto()
    BACKPRESSURE = auto()  # emitted when latency exceeds threshold


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """POPO representing a single observer event."""

    type: StreamEventType
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


# --------------------------------------------------------------------------- #
# Observer protocol & concrete implementations
# --------------------------------------------------------------------------- #


class Observer(Protocol):
    """PEP-544 protocol — any observer must implement ``update``."""

    def update(self, event: StreamEvent) -> None:  # pragma: no cover
        ...


class LoggingObserver:
    """Simple observer that forwards events to the stdlib *logging* module."""

    def __init__(self, *, level: int = logging.INFO) -> None:
        self._level = level

    def update(self, event: StreamEvent) -> None:  # noqa: D401
        logger.log(self._level, "Event %s – payload=%s", event.type.name, event.payload)


class SentryObserver:
    """Observer that captures PIPELINE_ERROR events in Sentry."""

    def __init__(self, dsn: Optional[str] = None, **sdk_options: Any) -> None:
        if sentry_sdk is None:  # pragma: no cover
            raise RuntimeError(
                "SentryObserver requested but `sentry-sdk` is not installed."
            )

        # Initialize Sentry *only once* globally to prevent duplicate hubs.
        self._init_sentry(dsn=dsn, **sdk_options)

    @staticmethod
    def _init_sentry(**kwargs: Any) -> None:
        # Because `init` is idempotent, calling it multiple times has no effect
        sentry_sdk.init(**{k: v for k, v in kwargs.items() if v is not None})

    def update(self, event: StreamEvent) -> None:  # noqa: D401
        if event.type is StreamEventType.PIPELINE_ERROR:
            exc: BaseException = event.payload.get("exception")  # type: ignore[assignment]
            sentry_sdk.capture_exception(exc)


class PrometheusObserver:
    """Observer that updates Prometheus counters/histograms in real-time.

    Parameters
    ----------
    namespace:
        Metric namespace (e.g. *psn*).  Recommended to avoid collisions.
    port:
        If given, automatically expose the default registry on the given HTTP
        port.  Pass *None* to use an already running exporter.
    """

    _REGISTRATION_LOCK = threading.Lock()
    _EXPORTER_STARTED: bool = False

    def __init__(self, *, namespace: str = "psn", port: Optional[int] = 8000) -> None:
        if Counter is None:  # pragma: no cover
            raise RuntimeError(
                "PrometheusObserver requested but `prometheus_client` is not installed."
            )

        self.namespace = namespace
        self._metrics = self._create_metrics(namespace)

        # Lazily start one exporter per process
        if port is not None and not PrometheusObserver._EXPORTER_STARTED:
            with PrometheusObserver._REGISTRATION_LOCK:
                if not PrometheusObserver._EXPORTER_STARTED:
                    logger.info("Starting Prometheus HTTP exporter on :%d", port)
                    start_http_server(port)
                    PrometheusObserver._EXPORTER_STARTED = True

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def update(self, event: StreamEvent) -> None:  # noqa: D401
        if event.type is StreamEventType.RECORD_PROCESSED:
            self._metrics["records_total"].inc()
            self._metrics["latency"].observe(event.payload["latency"])
        elif event.type is StreamEventType.BATCH_COMPLETED:
            self._metrics["batches_total"].inc()
        elif event.type is StreamEventType.PIPELINE_ERROR:
            self._metrics["errors_total"].inc()
        elif event.type is StreamEventType.BACKPRESSURE:
            self._metrics["backpressure_total"].inc()

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    @staticmethod
    def _create_metrics(namespace: str) -> Dict[str, Any]:
        """Create (or reuse) Prometheus metric objects."""
        metrics: Dict[str, Any] = {
            "records_total": Counter(
                f"{namespace}_records_total",
                "Total number of records processed",
            ),
            "batches_total": Counter(
                f"{namespace}_batches_total",
                "Total number of batches completed",
            ),
            "errors_total": Counter(
                f"{namespace}_errors_total",
                "Total number of unhandled exceptions",
            ),
            "backpressure_total": Counter(
                f"{namespace}_backpressure_total",
                "Number of backpressure notifications",
            ),
            "latency": Histogram(
                f"{namespace}_record_latency_seconds",
                "Latency per record in seconds",
                buckets=(
                    0.0005,
                    0.001,
                    0.005,
                    0.01,
                    0.05,
                    0.1,
                    0.25,
                    0.5,
                    1,
                    2,
                    5,
                ),
            ),
        }
        return metrics


# --------------------------------------------------------------------------- #
# Observable pipeline wrapper
# --------------------------------------------------------------------------- #


class ObservablePipelineStage:
    """Wraps a processing callable with event emission & instrumentation.

    The wrapped callable must take a *single* record and return the processed
    record. Batch-aware orchestration can be achieved via higher-order
    functions outside of this class to keep the surface area minimal.

    Example
    -------
    >>> def transform(r): ...
    >>> stage = ObservablePipelineStage("sentiment", transform)
    >>> for row in stream:
    ...     out = stage(row)
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        name: str,
        processor: Callable[[Any], Any],
        observers: Optional[Sequence[Observer]] = None,
        *,
        backpressure_threshold_s: float = 10.0,
    ) -> None:
        self.name = name
        self._processor = processor
        self._backpressure_threshold_s = backpressure_threshold_s

        self._observers: List[Observer] = list(observers or [])
        self._lock = threading.RLock()  # protect observer registry modifications

    # --------------------------------------------------------------------- #
    # Public observer registry
    # --------------------------------------------------------------------- #

    def register(self, observer: Observer) -> None:
        """Subscribe an observer at runtime."""
        with self._lock:
            self._observers.append(observer)

    def unregister(self, observer: Observer) -> None:
        """Remove a previously registered observer."""
        with self._lock:
            self._observers.remove(observer)

    # --------------------------------------------------------------------- #
    # Core callable API (acts like a function)
    # --------------------------------------------------------------------- #

    def __call__(self, record: Any) -> Any:  # noqa: D401
        start_t = time.perf_counter()
        try:
            result = self._processor(record)
        except Exception as exc:  # pylint: disable=broad-except
            self._notify(
                StreamEventType.PIPELINE_ERROR,
                payload={"exception": exc, "record": record},
            )
            raise  # re-raise after notification
        finally:
            latency_s = time.perf_counter() - start_t
            self._notify(
                StreamEventType.RECORD_PROCESSED,
                payload={"latency": latency_s, "record": record},
            )
            if latency_s > self._backpressure_threshold_s:
                self._notify(
                    StreamEventType.BACKPRESSURE,
                    payload={"latency": latency_s, "record": record},
                )

        return result

    # --------------------------------------------------------------------- #
    # Context-manager sugar — allows usage with *with* statements
    # --------------------------------------------------------------------- #

    def __enter__(self) -> "ObservablePipelineStage":  # noqa: D401
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> bool:  # noqa: D401
        # Convert any exception into PIPELINE_ERROR; propagate afterwards
        if exc_value is not None:
            self._notify(
                StreamEventType.PIPELINE_ERROR,
                payload={"exception": exc_value},
            )
        return False  # do not suppress

    # --------------------------------------------------------------------- #
    # Batch helpers — explicit flushing
    # --------------------------------------------------------------------- #

    def flush(self) -> None:
        """Emit a BATCH_COMPLETED event (e.g. after a *for* loop)."""
        self._notify(StreamEventType.BATCH_COMPLETED, payload={})

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    def _notify(self, event_type: StreamEventType, *, payload: Dict[str, Any]) -> None:
        event = StreamEvent(type=event_type, payload=payload)
        # snapshot observers to avoid deadlocks if they register/unregister
        with self._lock:
            observers = tuple(self._observers)

        for obs in observers:
            try:
                obs.update(event)
            except Exception:  # pragma: no cover
                # Never allow observer failures to crash the pipeline
                logger.exception("Observer %s failed to handle event %s", obs, event)


# --------------------------------------------------------------------------- #
# Convenience factory
# --------------------------------------------------------------------------- #


def make_instrumented_stage(
    name: str,
    processor: Callable[[Any], Any],
    *,
    prometheus: bool = True,
    sentry: bool = False,
    logging_level: int = logging.INFO,
    prometheus_port: int = 8000,
    backpressure_threshold_s: float = 10.0,
) -> ObservablePipelineStage:
    """Factory helper used by microservices to quickly bootstrap a stage."""
    observers: List[Observer] = [LoggingObserver(level=logging_level)]

    if prometheus:
        try:
            observers.append(
                PrometheusObserver(namespace="psn", port=prometheus_port)
            )
        except RuntimeError:
            logger.warning("PrometheusObserver disabled – dependency missing")

    if sentry:
        try:
            observers.append(SentryObserver())
        except RuntimeError:
            logger.warning("SentryObserver disabled – dependency missing")

    return ObservablePipelineStage(
        name,
        processor,
        observers,
        backpressure_threshold_s=backpressure_threshold_s,
    )
```