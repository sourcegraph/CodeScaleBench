```python
"""
PulseStream Nexus – Metrics & Alerting Subsystem
================================================

This module implements a lightweight Observer-Pattern–driven dispatch
mechanism for internal metric events emitted by PulseStream Nexus ETL /
streaming pipelines.

A `MetricDispatcher` instance can be embedded into any component
(e.g. Kafka consumer, Spark driver, Beam DoFn) and is responsible for
forwarding `MetricEvent` objects to _n_ registered observers.  Concrete
observers convert high-level events into:

* Prometheus counters / gauges pushed to a Pushgateway
* Sentry alert messages / breadcrumbs
* Plain log lines (fallback)

The design keeps the core domain completely agnostic to monitoring
back-ends, promoting testability and clean separation of concerns.

Usage
-----

>>> dispatcher = MetricDispatcher()
>>> dispatcher.register(PrometheusObserver())
>>> dispatcher.register(SentryObserver())
>>>
>>> with timed_event(dispatcher, name="tweets_processed"):
...     run_expensive_job()

"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Protocol

# --------------------------------------------------------------------------- #
# Optional, best-effort third-party imports
# --------------------------------------------------------------------------- #
try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway  # type: ignore
except ImportError:  # pragma: no cover
    CollectorRegistry = None  # type: ignore
    Gauge = None  # type: ignore
    push_to_gateway = None  # type: ignore

try:
    import sentry_sdk  # type: ignore
except ImportError:  # pragma: no cover
    sentry_sdk = None  # type: ignore


__all__ = [
    "MetricEvent",
    "Observer",
    "MetricDispatcher",
    "PrometheusObserver",
    "SentryObserver",
    "timed_event",
]


# --------------------------------------------------------------------------- #
# Domain objects
# --------------------------------------------------------------------------- #
@dataclass(slots=True, frozen=True)
class MetricEvent:
    """
    Domain object representing an emitted metric.

    Attributes
    ----------
    name : str
        Metric name; should follow the '<component>_<action>' convention,
        e.g., 'ingestor_messages_consumed'.
    value : float
        Numeric value associated with the metric.
    tags : Mapping[str, str]
        Arbitrary key-value pairs for labeling / filtering.
    severity : str
        One of {'info', 'warning', 'error'}.  Severity levels may be
        interpreted differently by observers (e.g. Sentry sends
        'error' as an Exception vs. 'info' as breadcrumb).
    timestamp : datetime
        UTC timestamp of the metric.
    """

    name: str
    value: float
    tags: Mapping[str, str] = field(default_factory=dict)
    severity: str = "info"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_prometheus(self) -> Dict[str, Any]:
        """Convert to Prometheus labels / value dict."""
        data = {
            "name": self.name,
            "value": self.value,
            "labels": dict(self.tags, severity=self.severity),
        }
        return data

    def to_json(self) -> str:
        """Serialize event to JSON for logging or transport."""
        return json.dumps(
            {
                "name": self.name,
                "value": self.value,
                "tags": self.tags,
                "severity": self.severity,
                "timestamp": self.timestamp.isoformat(),
            },
            ensure_ascii=False,
        )


# --------------------------------------------------------------------------- #
# Observer protocol
# --------------------------------------------------------------------------- #
class Observer(Protocol):
    """Observer interface for receiving metric events."""

    def on_event(self, event: MetricEvent) -> None:
        """Handle a metric event."""


# --------------------------------------------------------------------------- #
# Metric dispatcher
# --------------------------------------------------------------------------- #
class MetricDispatcher:
    """
    Subject, responsible for distributing events to observers.

    Thread-safe, non-blocking dispatch using a dedicated worker thread.
    """

    _QUEUE_TIMEOUT_SEC = 0.2

    def __init__(self, max_queue_size: int = 10_000) -> None:
        self._observers: List[Observer] = []
        self._queue: "queue.Queue[MetricEvent]" = queue.Queue(maxsize=max_queue_size)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._stop_event = threading.Event()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._executor = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)
        self._thread.start()

    # Observer management --------------------------------------------------- #
    def register(self, observer: Observer) -> None:
        self._logger.debug("Registering observer: %s", observer)
        self._observers.append(observer)

    def unregister(self, observer: Observer) -> None:
        self._logger.debug("Unregistering observer: %s", observer)
        try:
            self._observers.remove(observer)
        except ValueError:
            self._logger.warning("Attempted to unregister unknown observer: %s", observer)

    # Event emission -------------------------------------------------------- #
    def emit(self, event: MetricEvent) -> None:
        """Put an event on the queue, dropping if the queue is full."""
        try:
            self._queue.put_nowait(event)
            self._logger.debug("Queued event %s", event)
        except queue.Full:
            self._logger.error("Metric queue full; dropping event %s", event.to_json())

    # Lifecycle ------------------------------------------------------------ #
    def close(self, wait: bool = True) -> None:
        """Stop the worker thread and flush outstanding work."""
        self._stop_event.set()
        if wait:
            self._thread.join(timeout=3)
        self._executor.shutdown(wait=wait)
        self._logger.debug("MetricDispatcher closed.")

    # Internal worker ------------------------------------------------------- #
    def _worker(self) -> None:  # pragma: no cover
        """
        Internal worker reading from the queue and notifying observers.

        Each observer call is offloaded to a thread pool to avoid
        blocking the dispatcher.
        """
        self._logger.debug("MetricDispatcher worker started.")
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=self._QUEUE_TIMEOUT_SEC)
            except queue.Empty:
                continue

            for observer in list(self._observers):  # shallow copy to allow mutation
                self._executor.submit(self._safe_call, observer, event)

            self._queue.task_done()

    def _safe_call(self, observer: Observer, event: MetricEvent) -> None:
        try:
            observer.on_event(event)
        except Exception:  # pragma: no cover
            self._logger.exception(
                "Observer %s raised an exception handling event %s", observer, event
            )


# --------------------------------------------------------------------------- #
# Concrete observers
# --------------------------------------------------------------------------- #
class PrometheusObserver:
    """
    Observer that pushes metrics to a Prometheus Pushgateway.

    Environment variables:
        * PROM_PUSHGATEWAY_URL   – URL of the Pushgateway
        * PROM_JOB_NAME          – Job label (default: 'pulse_stream_nexus')
    """

    _DEFAULT_JOB_NAME = "pulse_stream_nexus"

    def __init__(
        self,
        pushgateway_url: Optional[str] = None,
        job_name: Optional[str] = None,
        registry: Optional[CollectorRegistry] = None,
    ) -> None:
        if push_to_gateway is None or CollectorRegistry is None:  # pragma: no cover
            raise RuntimeError(
                "prometheus_client is required for PrometheusObserver but is not installed."
            )

        self._pushgateway_url = (
            pushgateway_url or os.environ.get("PROM_PUSHGATEWAY_URL", "http://localhost:9091")
        )
        self._job_name = job_name or os.environ.get("PROM_JOB_NAME", self._DEFAULT_JOB_NAME)
        self._registry = registry or CollectorRegistry()
        self._gauges: MutableMapping[str, Gauge] = {}
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.debug(
            "PrometheusObserver configured with gateway=%s job=%s",
            self._pushgateway_url,
            self._job_name,
        )

    def on_event(self, event: MetricEvent) -> None:
        metric_name = event.name
        labels = event.to_prometheus()["labels"]

        # Retrieve or create gauge
        gauge = self._gauges.get(metric_name)
        if gauge is None:
            gauge = Gauge(metric_name, f"Auto-generated metric: {metric_name}", labels.keys(), registry=self._registry)
            self._gauges[metric_name] = gauge
            self._logger.debug("Created new Prometheus gauge: %s", metric_name)

        gauge.labels(**labels).set(event.value)
        self._logger.debug("Set gauge %s labels=%s value=%s", metric_name, labels, event.value)

        # Push to gateway
        try:
            push_to_gateway(self._pushgateway_url, job=self._job_name, registry=self._registry)
            self._logger.debug("Pushed metrics to Prometheus gateway %s", self._pushgateway_url)
        except Exception:  # pragma: no cover
            self._logger.exception("Failed to push metrics to Prometheus gateway %s", self._pushgateway_url)


class SentryObserver:
    """
    Observer that forwards severe events to Sentry.

    Environment variables:
        * SENTRY_DSN – DSN for the Sentry project
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        if sentry_sdk is None:  # pragma: no cover
            raise RuntimeError("sentry_sdk is required for SentryObserver but is not installed.")

        self._dsn = dsn or os.environ.get("SENTRY_DSN")
        if not self._dsn:
            raise ValueError("Sentry DSN missing; set SENTRY_DSN env var or pass dsn parameter")

        sentry_sdk.init(dsn=self._dsn, traces_sample_rate=0.0)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.debug("SentryObserver initialized with DSN %s", self._dsn)

    def on_event(self, event: MetricEvent) -> None:
        if event.severity in {"error", "warning"}:
            sentry_sdk.capture_message(event.to_json(), level=event.severity)
            self._logger.debug("Sent event to Sentry: %s", event)


# --------------------------------------------------------------------------- #
# Utility context manager / decorator
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def timed_event(
    dispatcher: MetricDispatcher,
    name: str,
    tags: Optional[Mapping[str, str]] = None,
    severity: str = "info",
) -> Iterable[None]:
    """
    Context manager that measures execution duration and emits a metric.

    Example
    -------
    >>> with timed_event(dispatcher, "transform_latency", tags={"stage": "enrich"}):
    ...     enrich_records()
    """
    start = time.monotonic()
    try:
        yield
    except Exception as exc:
        # Emit event with 'error' severity before re-raising
        dispatcher.emit(
            MetricEvent(
                name=f"{name}_exception",
                value=1.0,
                tags={**(tags or {}), "exception": exc.__class__.__name__},
                severity="error",
            )
        )
        raise
    else:
        duration = time.monotonic() - start
        dispatcher.emit(
            MetricEvent(
                name=name,
                value=duration,
                tags=tags or {},
                severity=severity,
            )
        )


# --------------------------------------------------------------------------- #
# Default root logger configuration (may be overridden by application)
# --------------------------------------------------------------------------- #
def _configure_default_logging() -> None:
    level = os.environ.get("PULSE_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


_configure_default_logging()
```