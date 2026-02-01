```python
"""
PulseStream Nexus – Streaming Health Monitor
============================================

File: src/module_57.py

This module implements a real-time health-monitoring component for the PulseStream
Nexus data-streaming platform.  It consumes fine-grained metric events emitted by
ingestion/processing micro-services, aggregates them in-memory, performs anomaly
detection, and notifies downstream observers (Prometheus, Sentry, etc.) when a
potential incident is discovered.

The code follows Clean Architecture principles:

* Domain entities live in `dataclasses` (pure business objects)
* Use-case interactor (`StreamHealthMonitor`) is framework-agnostic
* Interface abstractions (`AlertObserver`, `AnomalyDetectionStrategy`) decouple
  high-level policies from low-level details
* Concrete implementations (Prometheus/Sentry observers) are plugged-in at run
  time or swapped out during unit testing

The module is fully self-contained and can be integrated into the broader
pipeline or executed stand-alone for demonstration purposes::

    python -m module_57  # sends synthetic metrics and prints anomalies
"""
from __future__ import annotations

import asyncio
import collections
import dataclasses
import logging
import math
import os
import random
import statistics
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Deque, Dict, Iterable, List, Optional

# --------------------------------------------------------------------------- #
# Logging configuration                                                       #
# --------------------------------------------------------------------------- #

LOG_LEVEL = os.getenv("PULSESTREAM_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pulsestream.monitor")


# --------------------------------------------------------------------------- #
# Domain entities                                                             #
# --------------------------------------------------------------------------- #

@dataclasses.dataclass(frozen=True, slots=True)
class StreamHealthEvent:
    """
    A single metric sample emitted by a PulseStream micro-service.

    Attributes
    ----------
    timestamp : datetime
        Event creation time in UTC.
    service_id : str
        Identifier of the producing service (e.g., "ingester-twitter-01").
    metric : str
        Canonical metric name (e.g., "kafka.lag", "ingest.rate").
    value : float
        Observed numeric value.
    tags : Dict[str, str]
        Arbitrary key/value tags for grouping (e.g., {"topic":"twitter_stream"}).
    """

    timestamp: datetime
    service_id: str
    metric: str
    value: float
    tags: Dict[str, str]


@dataclasses.dataclass(frozen=True, slots=True)
class Anomaly:
    """
    Result of anomaly detection.

    Attributes
    ----------
    event : StreamHealthEvent
        Offending event that triggered the anomaly.
    severity : str
        Severity tag, free form but recommended values are: "INFO", "WARN", "CRIT".
    message : str
        Human-friendly explanation.
    """

    event: StreamHealthEvent
    severity: str
    message: str


# --------------------------------------------------------------------------- #
# Strategy pattern: Anomaly detection                                         #
# --------------------------------------------------------------------------- #

class AnomalyDetectionStrategy(ABC):
    """
    Strategy interface for anomaly detection.
    """

    @abstractmethod
    def observe(self, event: StreamHealthEvent) -> Iterable[Anomaly]:
        """
        Process a new event and yield zero or more Anomaly instances.
        """


class ZScoreAnomalyStrategy(AnomalyDetectionStrategy):
    """
    Simple rolling Z-score anomaly detector.

    An observation is reported anomalous if its absolute Z-score exceeds
    `threshold`.

    Parameters
    ----------
    window : int
        Rolling window size in number of samples.
    threshold : float
        Z-score threshold for anomaly detection.
    """

    def __init__(self, window: int = 50, threshold: float = 3.0) -> None:
        self._window = window
        self._threshold = threshold
        # Maps (service_id, metric) → deque[float]
        self._history: Dict[tuple[str, str], Deque[float]] = collections.defaultdict(
            lambda: collections.deque(maxlen=self._window)
        )

    def observe(self, event: StreamHealthEvent) -> Iterable[Anomaly]:
        buf = self._history[(event.service_id, event.metric)]
        buf.append(event.value)

        # Not enough data yet
        if len(buf) < max(10, self._window // 10):
            return ()

        mean = statistics.mean(buf)
        stdev = statistics.stdev(buf)
        if stdev == 0:  # avoid division by zero
            return ()

        z_score = abs((event.value - mean) / stdev)
        logger.debug(
            "ZScore: svc=%s metric=%s val=%s mean=%.2f stdev=%.2f z=%.2f",
            event.service_id,
            event.metric,
            event.value,
            mean,
            stdev,
            z_score,
        )

        if z_score >= self._threshold:
            severity = "CRIT" if z_score > self._threshold * 2 else "WARN"
            msg = (
                f"Anomalous {event.metric}: value={event.value:.2f}, "
                f"mean={mean:.2f}, stdev={stdev:.2f}, z={z_score:.2f}"
            )
            return (
                Anomaly(
                    event=event,
                    severity=severity,
                    message=msg,
                ),
            )
        return ()


# --------------------------------------------------------------------------- #
# Observer pattern: Alert observers                                           #
# --------------------------------------------------------------------------- #

class AlertObserver(ABC):
    """
    Observer interface notified on anomalies.
    """

    @abstractmethod
    async def update(self, anomaly: Anomaly) -> None:
        """
        React to a raised anomaly.  Concrete implementations may forward the
        information to monitoring systems, on-call rotations, etc.
        """


class LoggingAlertObserver(AlertObserver):
    """
    Fallback observer that simply logs anomalies.
    """

    async def update(self, anomaly: Anomaly) -> None:
        level = logging.WARNING if anomaly.severity == "WARN" else logging.ERROR
        logger.log(
            level,
            "Anomaly detected | svc=%s | metric=%s | %s",
            anomaly.event.service_id,
            anomaly.event.metric,
            anomaly.message,
        )


class PrometheusAlertObserver(AlertObserver):
    """
    Observer pushing anomalies as Prometheus metrics via the Pushgateway.

    Notes
    -----
    * Requires `prometheus_client` extra.  If not available, the observer falls
      back to logging.
    * Uses a Gauge named `pulsestream_anomaly_count` with labels to encode
      context.
    """

    def __init__(self, gateway_addr: str) -> None:
        self._gateway_addr = gateway_addr
        try:
            from prometheus_client import CollectorRegistry, Gauge, push_to_gateway  # type: ignore

            self._registry = CollectorRegistry()
            self._gauge = Gauge(
                "pulsestream_anomaly_count",
                "Total anomalies detected by PulseStream Nexus",
                labelnames=["service_id", "metric", "severity"],
                registry=self._registry,
            )
            self._push_to_gateway = push_to_gateway
            self._enabled = True
        except ModuleNotFoundError:
            logger.warning("prometheus_client missing; PrometheusAlertObserver disabled")
            self._enabled = False

    async def update(self, anomaly: Anomaly) -> None:
        if not self._enabled:
            await LoggingAlertObserver().update(anomaly)
            return

        self._gauge.labels(
            service_id=anomaly.event.service_id,
            metric=anomaly.event.metric,
            severity=anomaly.severity,
        ).inc()

        loop = asyncio.get_running_loop()
        # Offload blocking IO to thread executor
        await loop.run_in_executor(
            None,
            self._push_to_gateway,
            self._gateway_addr,
            "pulsestream_monitor",
            self._registry,
        )


class SentryAlertObserver(AlertObserver):
    """
    Observer forwarding anomalies to Sentry as custom events.
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        dsn = dsn or os.getenv("SENTRY_DSN")
        try:
            import sentry_sdk  # type: ignore

            sentry_sdk.init(
                dsn=dsn,
                traces_sample_rate=0.0,
                # Tag events generated by this module
                environment=os.getenv("ENVIRONMENT", "development"),
            )
            self._sentry_sdk = sentry_sdk
            self._enabled = True
        except ModuleNotFoundError:
            logger.warning("sentry_sdk missing; SentryAlertObserver disabled")
            self._enabled = False

    async def update(self, anomaly: Anomaly) -> None:
        if not self._enabled:
            await LoggingAlertObserver().update(anomaly)
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._sentry_sdk.capture_message,
            f"[{anomaly.severity}] {anomaly.message}",
            {"level": "warning" if anomaly.severity == "WARN" else "error"},
        )


# --------------------------------------------------------------------------- #
# Use-case interactor                                                         #
# --------------------------------------------------------------------------- #

class StreamHealthMonitor:
    """
    Coordinates metric ingestion, anomaly detection, and alert notification.
    """

    def __init__(
        self,
        strategy: AnomalyDetectionStrategy,
        observers: Optional[List[AlertObserver]] = None,
    ) -> None:
        self._strategy = strategy
        self._observers = observers or [LoggingAlertObserver()]

    def register_observer(self, observer: AlertObserver) -> None:
        self._observers.append(observer)

    async def process_event(self, event: StreamHealthEvent) -> None:
        """
        Ingest a single health event.
        """
        try:
            anomalies = self._strategy.observe(event)
        except Exception:  # noqa: BLE001
            logger.exception("Anomaly strategy failed for event %s", event)
            return

        # Fan-out to observers
        for anomaly in anomalies:
            for obs in self._observers:
                try:
                    await obs.update(anomaly)
                except Exception:  # noqa: BLE001
                    logger.exception("Observer %s failed", obs.__class__.__name__)


# --------------------------------------------------------------------------- #
# Application wiring & demonstration                                          #
# --------------------------------------------------------------------------- #

async def _generate_synthetic_events(
    queue: "asyncio.Queue[StreamHealthEvent]",
    services: List[str],
) -> None:
    """
    Create synthetic metric samples for testing.
    """
    metrics = ["ingest.rate", "kafka.lag", "toxicity.avg", "sentiment.avg"]
    while True:
        await asyncio.sleep(0.5)  # 2 Hz event rate
        svc = random.choice(services)
        metric = random.choice(metrics)
        base_val = {
            "ingest.rate": 1000.0,
            "kafka.lag": 300.0,
            "toxicity.avg": 0.2,
            "sentiment.avg": 0.0,
        }[metric]
        # Random walk with occasional spikes
        val = base_val + random.gauss(0, base_val * 0.05)
        if random.random() < 0.01:  # 1 % spike chance
            val *= random.uniform(2, 4)

        event = StreamHealthEvent(
            timestamp=datetime.utcnow(),
            service_id=svc,
            metric=metric,
            value=val,
            tags={"source": "synthetic"},
        )
        await queue.put(event)


async def _event_consumer(
    queue: "asyncio.Queue[StreamHealthEvent]",
    monitor: StreamHealthMonitor,
) -> None:
    """
    Consumer that drains events from the queue and feeds the monitor.
    """
    while True:
        event = await queue.get()
        await monitor.process_event(event)
        queue.task_done()


async def _main() -> None:
    """
    Entrypoint for stand-alone execution.
    """
    event_q: "asyncio.Queue[StreamHealthEvent]" = asyncio.Queue(maxsize=1000)

    monitor = StreamHealthMonitor(
        strategy=ZScoreAnomalyStrategy(window=100, threshold=3.0),
        observers=[
            LoggingAlertObserver(),
            # PrometheusAlertObserver("http://localhost:9091"),
            # SentryAlertObserver(),  # requires SENTRY_DSN env var
        ],
    )

    producers = asyncio.create_task(
        _generate_synthetic_events(
            queue=event_q,
            services=[f"ingester-twitter-{i:02d}" for i in range(3)],
        )
    )
    consumers = asyncio.create_task(_event_consumer(event_q, monitor))

    try:
        await asyncio.gather(producers, consumers)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nInterrupted by user, shutting down...", file=sys.stderr)
```