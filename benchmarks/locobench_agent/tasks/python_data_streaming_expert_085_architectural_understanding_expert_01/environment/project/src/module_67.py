```python
"""
PulseStream Nexus – Event Ingestion Telemetry & Monitoring Module
=================================================================

This module provides run-time telemetry for high-volume event ingestions.
It implements an Observer pattern so that external systems (Prometheus,
Grafana dashboards, Sentry, etc.) can subscribe to real-time throughput
statistics without taking a hard dependency on the ingestion pipeline.

Key capabilities
----------------
1. Collect event-level diagnostics (records/sec, bytes/sec, lag, jitter).
2. Publish metrics to Prometheus via `prometheus_client`.
3. Automatic schema validation of incoming events via Great Expectations.
4. Pluggable error reporting (Sentry is the default implementation).
5. Thread-safe, zero-GC data structures for low-latency pipelines.

Usage
-----
>>> from src.module_67 import EventRateMonitor, PrometheusExporter
>>>
>>> monitor = EventRateMonitor(window_size_sec=30)
>>> exporter = PrometheusExporter(namespace="pulsestream_nexus")
>>>
>>> monitor.register(exporter)
>>> monitor.start()   # Starts a background sampling thread
>>>
>>> # Ingest events from your Kafka consumer / webhook etc.
>>> monitor.ingest_event({"source": "twitter", "bytes": 512})
>>> ...
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from statistics import mean
from typing import Deque, Dict, List, Protocol

try:
    # Third-party (optional) dependencies ‑ they gracefully degrade.
    from prometheus_client import Gauge, Counter, start_http_server
except ImportError:  # pragma: no cover
    Gauge = Counter = None  # type: ignore
    start_http_server = lambda *_, **__: None  # type: ignore

try:
    import sentry_sdk
except ImportError:  # pragma: no cover
    sentry_sdk = None  # type: ignore

try:
    import great_expectations as ge
except ImportError:  # pragma: no cover
    ge = None  # type: ignore

__all__ = ["EventRateMonitor", "ThroughputSubscriber", "PrometheusExporter"]

LOGGER = logging.getLogger("pulsestream.monitor")
LOGGER.setLevel(os.getenv("PULSESTREAM_LOG_LEVEL", "INFO"))


# --------------------------------------------------------------------------- #
# Domain models
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class IngestEvent:
    """Lightweight, immutable value object for an ingested event."""
    source: str
    bytes: int
    ts: float = time.time()  # noqa: A003  (shadowing built-in allowed here)


# --------------------------------------------------------------------------- #
# Observer interfaces
# --------------------------------------------------------------------------- #
class ThroughputSubscriber(Protocol):
    """Interface that any monitor subscriber must implement."""

    def update(self, metrics: Dict[str, float]) -> None:  # noqa: D401
        """Receive updated throughput metrics."""


# --------------------------------------------------------------------------- #
# Core monitor
# --------------------------------------------------------------------------- #
class EventRateMonitor:
    """Tracks event throughput using a sliding time window."""

    _DEFAULT_SAMPLING_INTERVAL = 5.0

    def __init__(
        self,
        window_size_sec: int = 60,
        sampling_interval: float = _DEFAULT_SAMPLING_INTERVAL,
        sentry_dsn: str | None = None,
    ) -> None:
        self.window_size_sec = window_size_sec
        self.sampling_interval = sampling_interval
        self._events: Deque[IngestEvent] = deque()
        self._lock = threading.RLock()
        self._subscribers: List[ThroughputSubscriber] = []
        self._stop_event = threading.Event()
        self._sampling_thread: threading.Thread | None = None

        self._configure_sentry(sentry_dsn)

        LOGGER.debug(
            "EventRateMonitor initialised "
            "(window=%ss, sampling_interval=%ss)",
            window_size_sec,
            sampling_interval,
        )

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def ingest_event(self, event: Dict[str, int | str | float]) -> None:
        """Validate and enqueue a raw ingest event."""
        try:
            self._validate_event(event)
            ingest_event = IngestEvent(
                source=str(event["source"]),
                bytes=int(event["bytes"]),
                ts=float(event.get("ts", time.time())),
            )
        except Exception as exc:  # pragma: no cover
            self._report_error(exc)
            raise

        with self._lock:
            self._events.append(ingest_event)
            LOGGER.debug("Event enqueued: %s", ingest_event)

    def register(self, subscriber: ThroughputSubscriber) -> None:
        """Attach a new observer."""
        self._subscribers.append(subscriber)
        LOGGER.debug("Subscriber registered: %s", subscriber)

    def unregister(self, subscriber: ThroughputSubscriber) -> None:
        """Detach an existing observer."""
        self._subscribers.remove(subscriber)
        LOGGER.debug("Subscriber unregistered: %s", subscriber)

    def start(self) -> None:
        """Spawn the background sampler thread."""
        if self._sampling_thread and self._sampling_thread.is_alive():
            LOGGER.warning("Sampling thread already running")
            return

        self._stop_event.clear()
        self._sampling_thread = threading.Thread(
            target=self._sampling_loop,
            name="EventRateSampler",
            daemon=True,
        )
        self._sampling_thread.start()
        LOGGER.info("EventRateMonitor started")

    def stop(self, timeout: float | None = None) -> None:
        """Gracefully shut down the sampler."""
        self._stop_event.set()
        if self._sampling_thread:
            self._sampling_thread.join(timeout=timeout)
            LOGGER.info("EventRateMonitor stopped")

    # --------------------------------------------------------------------- #
    # Private helpers
    # --------------------------------------------------------------------- #
    def _sampling_loop(self) -> None:
        """Continuously evaluate windowed stats & notify observers."""
        while not self._stop_event.is_set():
            time.sleep(self.sampling_interval)
            try:
                metrics = self._calculate_metrics()
                self._broadcast(metrics)
            except Exception as exc:  # pragma: no cover
                # Keep the thread alive; notify sentry if configured.
                self._report_error(exc)

    def _calculate_metrics(self) -> Dict[str, float]:
        """Compute rolling throughput statistics."""
        cutoff = time.time() - self.window_size_sec
        with self._lock:
            # Drop events outside the window
            while self._events and self._events[0].ts < cutoff:
                dropped = self._events.popleft()
                LOGGER.debug("Dropped event outside window: %s", dropped)

            count = len(self._events)
            total_bytes = sum(evt.bytes for evt in self._events)
            window_span = self.window_size_sec or 1  # prevent div-zero

        events_per_sec = count / window_span
        bytes_per_sec = total_bytes / window_span

        # record jitter (variance in inter-arrival times)
        with self._lock:
            if count > 1:
                diffs = [
                    self._events[i].ts - self._events[i - 1].ts
                    for i in range(1, count)
                ]
                jitter = mean(diffs)
            else:
                jitter = 0.0

        metrics = {
            "events_per_sec": events_per_sec,
            "bytes_per_sec": bytes_per_sec,
            "window_size_sec": self.window_size_sec,
            "jitter": jitter,
            "event_count": count,
        }
        LOGGER.debug("Calculated metrics: %s", metrics)
        return metrics

    def _broadcast(self, metrics: Dict[str, float]) -> None:
        """Notify all registered subscribers."""
        for subscriber in list(self._subscribers):  # copy to avoid mutation
            try:
                subscriber.update(metrics)
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("Subscriber %s failed: %s", subscriber, exc)
                self._report_error(exc)

    # --------------------------------------------------------------------- #
    # Validation & Error reporting
    # --------------------------------------------------------------------- #
    def _validate_event(self, event: Dict[str, int | str | float]) -> None:
        """Run a simple Great Expectations suite (noop if GE is absent)."""
        if ge is None:
            return  # Soft-fail: assume valid

        batch = ge.dataset.PandasDataset(**{"value": [event]})  # type: ignore
        batch.expect_column_to_exist("source")
        batch.expect_column_values_to_not_be_null("source")
        batch.expect_column_values_to_match_regex("source", r"^[\w\-]+$")

        batch.expect_column_to_exist("bytes")
        batch.expect_column_values_to_be_between("bytes", 1, 10_000_000)

        if not batch.validate().success:  # pragma: no cover
            raise ValueError(f"Event validation failed: {event}")

    def _configure_sentry(self, dsn: str | None) -> None:
        if dsn and sentry_sdk:
            sentry_sdk.init(dsn=dsn, traces_sample_rate=0.1)
            LOGGER.info("Sentry configured with DSN: %s", dsn)

    def _report_error(self, exc: Exception) -> None:
        if sentry_sdk and sentry_sdk.Hub.current.client:  # noqa: SLF001
            sentry_sdk.capture_exception(exc)
        LOGGER.exception("Unhandled exception: %s", exc)


# --------------------------------------------------------------------------- #
# Prometheus implementation
# --------------------------------------------------------------------------- #
class PrometheusExporter(ThroughputSubscriber):
    """Exposes throughput metrics as Prometheus Gauges/Counters."""

    def __init__(
        self,
        namespace: str = "pulsestream",
        host: str = "0.0.0.0",
        port: int = 9100,
        start_server: bool = True,
    ) -> None:
        if Gauge is None:  # pragma: no cover
            raise RuntimeError(
                "prometheus_client is required for PrometheusExporter"
            )

        self.events_per_sec = Gauge(
            "events_per_sec", "Ingested events per second", namespace=namespace
        )
        self.bytes_per_sec = Gauge(
            "bytes_per_sec", "Ingested bytes per second", namespace=namespace
        )
        self.jitter = Gauge("jitter", "Mean inter-arrival jitter", namespace=namespace)
        self.event_count = Gauge(
            "event_count", "Event count in sliding window", namespace=namespace
        )
        self.total_events = Counter(
            "total_events", "Total ingested events", namespace=namespace
        )
        self.total_bytes = Counter(
            "total_bytes", "Total ingested bytes", namespace=namespace
        )

        if start_server:
            # Running multiple exporters in same process is fine;
            # start_http_server is idempotent for identical addr/port pairs.
            start_http_server(port, addr=host)
            LOGGER.info(
                "Prometheus exporter running at http://%s:%d/metrics", host, port
            )

    def update(self, metrics: Dict[str, float]) -> None:  # noqa: D401
        self.events_per_sec.set(metrics["events_per_sec"])
        self.bytes_per_sec.set(metrics["bytes_per_sec"])
        self.jitter.set(metrics["jitter"])
        self.event_count.set(metrics["event_count"])

        # Convert rates * window to absolute increments.
        self.total_events.inc(metrics["events_per_sec"] * metrics["window_size_sec"])
        self.total_bytes.inc(metrics["bytes_per_sec"] * metrics["window_size_sec"])

        LOGGER.debug("Prometheus metrics updated: %s", metrics)


# --------------------------------------------------------------------------- #
# Lightweight CLI for ad-hoc usage
# --------------------------------------------------------------------------- #
def _demo() -> None:  # pragma: no cover
    """Standalone demo for manual testing."""
    logging.basicConfig(level=logging.DEBUG)
    monitor = EventRateMonitor(window_size_sec=15, sampling_interval=5)
    exporter = PrometheusExporter(namespace="pulsestream_demo", port=9200)
    monitor.register(exporter)
    monitor.start()

    try:
        while True:
            # Simulate a bursty ingest pattern
            monitor.ingest_event({"source": "demo", "bytes": 128})
            time.sleep(0.2)
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received; shutting down...")
    finally:
        monitor.stop(timeout=10)


if __name__ == "__main__":
    _demo()
```