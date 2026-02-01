```python
"""
PulseStream Nexus – Stream Monitoring & Metrics Collector
=========================================================

This module implements a lightweight yet production-grade monitoring layer
for PulseStream Nexus.  It utilises the Observer Pattern to decouple the
ETL/ELT pipeline execution from metric aggregation and exposition.  The core
building blocks are:

1.  `StreamEvent`: A dataclass encapsulating timing, record-count, and error
    metadata emitted by any pipeline stage.
2.  `StreamEventDispatcher`: A subject that broadcasts `StreamEvent` objects
    to a set of subscribed observers.
3.  `StreamEventObserver`: The interface observers must implement.
4.  `PrometheusMetricsObserver`: A concrete observer that transforms raw
    events into Prometheus counters, summaries and gauges.

The module is deliberately framework-agnostic and carries **zero runtime
dependencies on the rest of the PulseStream Nexus codebase**; it can be
reused by any micro-service or batch job with a single import.

Usage
-----

>>> from module_72 import StreamEventDispatcher, PrometheusMetricsObserver
>>> dispatcher = StreamEventDispatcher()
>>> dispatcher.attach(PrometheusMetricsObserver(service_name="psn-ingestor"))
>>>
>>> # In a pipeline step:
>>> event = StreamEvent(
...     stage="ingest.twitter",
...     records=25_000,
...     start_time=time.monotonic(),
...     end_time=time.monotonic() + 1.2
... )
>>> dispatcher.notify(event)

The Prometheus client will now expose metrics on the default HTTP port
(8000) if `prometheus_client.start_http_server` was called (see below).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Protocol, runtime_checkable

# External dependency. Make sure it is included in service requirements.
from prometheus_client import Counter, Gauge, Summary, start_http_server

__all__ = [
    "StreamEvent",
    "StreamEventObserver",
    "StreamEventDispatcher",
    "PrometheusMetricsObserver",
]

_logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Data Model
# -----------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class StreamEvent:
    """
    A value object representing the outcome of a single pipeline stage.

    Attributes
    ----------
    stage:
        Hierarchical stage identifier, e.g. ``"transform.sentiment"``.
    records:
        Number of records processed inside this stage.
    start_time:
        Epoch timestamp in seconds when stage execution started.
    end_time:
        Epoch timestamp in seconds when stage execution finished.
    success:
        ``True`` if the stage finished successfully, ``False`` if an
        exception was raised (soft-failed).
    created_at:
        Wall-clock time the event object was created.  Mainly useful for
        offline analysis / backfill correlation.
    extra:
        Additional metadata in arbitrary key/value pairs, e.g. host,
        partition, etc.
    """

    stage: str
    records: int
    start_time: float
    end_time: float
    success: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    extra: dict[str, str] | None = field(default=None)

    # --------------------------------------------------------------------- #
    # Convenience helpers
    # --------------------------------------------------------------------- #

    @property
    def duration(self) -> float:
        """Return the stage latency in seconds as a float."""
        return self.end_time - self.start_time


# -----------------------------------------------------------------------------
# Observer Infrastructure
# -----------------------------------------------------------------------------


@runtime_checkable
class StreamEventObserver(Protocol):
    """Interface that observers of ``StreamEvent`` must implement."""

    def update(self, event: StreamEvent) -> None:  # noqa: D401
        """Handle a notified ``StreamEvent``."""


class StreamEventDispatcher:
    """
    Subject in the Observer pattern that propagates ``StreamEvent`` messages.

    Thread-safe attachment / detachment is provided to guarantee correctness
    in highly concurrent ingestion pipelines.
    """

    def __init__(self, observers: Iterable[StreamEventObserver] | None = None) -> None:
        self._observers: List[StreamEventObserver] = list(observers or [])
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Observer management
    # ------------------------------------------------------------------ #

    def attach(self, observer: StreamEventObserver) -> None:
        """
        Attach (subscribe) a new observer.

        Duplicate observers are ignored silently.
        """
        with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)
                _logger.debug("Attached observer %s", observer)

    def detach(self, observer: StreamEventObserver) -> None:
        """Detach (unsubscribe) an existing observer."""
        with self._lock:
            with suppress(ValueError):
                self._observers.remove(observer)
                _logger.debug("Detached observer %s", observer)

    # ------------------------------------------------------------------ #
    # Notification
    # ------------------------------------------------------------------ #

    def notify(self, event: StreamEvent) -> None:
        """Fire an event to all observers. Exceptions are logged & swallowed."""
        _logger.debug("Dispatching StreamEvent: %s", event)
        with self._lock:
            observers_snapshot = list(self._observers)

        for observer in observers_snapshot:
            try:
                observer.update(event)
            except Exception:  # pragma: no cover  # defensive catch all
                _logger.exception("Observer %s raised during update()", observer)


# -----------------------------------------------------------------------------
# Concrete Observer
# -----------------------------------------------------------------------------


class PrometheusMetricsObserver(StreamEventObserver):
    """
    Observer that converts `StreamEvent`s into Prometheus metrics.

    The observer is *cheap* with respect to allocations: metric objects are
    instantiated once per stage and cached for subsequent events to avoid
    leaking Prometheus internal state (otherwise you end up with unbounded
    time series cardinality).
    """

    #: Port on which the Prometheus HTTP server is started automatically.
    #: Can be overridden via the ``PSN_PROM_PORT`` env var.
    DEFAULT_PORT: int = int(os.getenv("PSN_PROM_PORT", "8000"))

    _server_started: bool = False
    _server_lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------ #

    def __init__(
        self,
        service_name: str,
        start_http_server_on_init: bool = True,
    ) -> None:
        self.service_name = service_name
        self._latency: dict[str, Summary] = {}
        self._throughput: dict[str, Counter] = {}
        self._success_gauge: dict[str, Gauge] = {}

        if start_http_server_on_init:
            self._maybe_start_http_server()

    # ------------------------------------------------------------------ #
    # StreamEventObserver compliance
    # ------------------------------------------------------------------ #

    def update(self, event: StreamEvent) -> None:
        _logger.debug("Prometheus observer processing event: %s", event)

        # Avoid high cardinality: force stage names to Prometheus-safe labels
        sanitized_stage = event.stage.replace(".", "_").replace("-", "_")

        # Metric initialisation (idempotent / cached)
        latency_metric = self._latency.get(sanitized_stage)
        if latency_metric is None:
            latency_metric = Summary(
                name=f"psn_stage_latency_seconds",
                documentation="Latency (seconds) of PulseStream Nexus pipeline stages.",
                labelnames=("service", "stage"),
            )
            self._latency[sanitized_stage] = latency_metric

        throughput_metric = self._throughput.get(sanitized_stage)
        if throughput_metric is None:
            throughput_metric = Counter(
                name="psn_stage_records_total",
                documentation="Total records processed by PulseStream Nexus stages.",
                labelnames=("service", "stage"),
            )
            self._throughput[sanitized_stage] = throughput_metric

        success_metric = self._success_gauge.get(sanitized_stage)
        if success_metric is None:
            success_metric = Gauge(
                name="psn_stage_success",
                documentation=(
                    "Stage health indicator (1=success, 0=failure) for "
                    "PulseStream Nexus pipeline stages."
                ),
                labelnames=("service", "stage"),
            )
            self._success_gauge[sanitized_stage] = success_metric

        # Actual metric recording
        latency_metric.labels(self.service_name, sanitized_stage).observe(event.duration)
        throughput_metric.labels(self.service_name, sanitized_stage).inc(event.records)
        success_metric.labels(self.service_name, sanitized_stage).set(float(event.success))

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def _maybe_start_http_server(cls) -> None:
        """
        Spin up the Prometheus HTTP server once per process.

        The method is concurrency-safe and idempotent.
        """
        if cls._server_started:  # Fast path
            return

        with cls._server_lock:
            if cls._server_started:  # Double-check
                return

            try:
                start_http_server(cls.DEFAULT_PORT)
                cls._server_started = True
                _logger.info("Prometheus HTTP server started on port %s", cls.DEFAULT_PORT)
            except OSError:
                # Port conflict or permission denied; log and continue.
                # Metrics will still be collected but NOT exposed externally.
                _logger.exception(
                    "Failed to start Prometheus HTTP server on port %s; "
                    "metrics exposition disabled.",
                    cls.DEFAULT_PORT,
                )

# -----------------------------------------------------------------------------
# Demo / Self-Test
# -----------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    dispatcher = StreamEventDispatcher()
    prometheus_observer = PrometheusMetricsObserver(service_name="demo-service")
    dispatcher.attach(prometheus_observer)

    # Emit 3 dummy events to showcase runtime behaviour
    for i in range(3):
        start = time.monotonic()
        # Simulated workload
        time.sleep(0.1)
        end = time.monotonic()

        dispatcher.notify(
            StreamEvent(
                stage="ingest.twitter",
                records=1_000,
                start_time=start,
                end_time=end,
                success=i != 2,  # Fail the last event for demo
                extra={"shard": str(i)},
            )
        )

    print(
        "Prometheus server is up at "
        f"http://localhost:{PrometheusMetricsObserver.DEFAULT_PORT}/metrics"
    )
    # Keep the script alive so the metrics endpoint remains reachable.
    # This should not be done in a production microservice; the service
    # framework (e.g., FastAPI, Faust, etc.) owns process lifetime.
    while True:
        time.sleep(60)
```