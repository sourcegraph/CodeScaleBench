```python
"""
PulseStream Nexus – Stream Lag Monitoring Module
================================================

This module provides a production-ready component that measures end-to-end
stream-processing delay (“ingestion lag”) for high-volume message brokers
(currently Kafka) and exports the metrics to Prometheus.  It also implements
an Observer pattern allowing arbitrary downstream handlers (e.g., paging,
Slack, e-mail) to react to threshold breaches in near-real time.

The code follows Clean-Architecture principles: the “domain” objects
(`LagReading`, `LagAlert`) are framework-agnostic value objects, while the
I/O-specific concerns (Kafka Admin client, Prometheus exporter, threads) are
isolated behind well-defined strategy/observer interfaces.

Typical usage
-------------
python -m src.module_65 --brokers localhost:9092 --topics topicA,topicB \
       --threshold-ms 5000

Dependencies
------------
pip install kafka-python prometheus-client
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from queue import Queue, Empty
from typing import Dict, Iterable, List, Optional

from prometheus_client import Gauge, start_http_server

try:
    from kafka import KafkaAdminClient, KafkaConsumer
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "kafka-python is required for the KafkaLagStrategy.\n"
        "Install with: pip install kafka-python"
    ) from exc

# --------------------------------------------------------------------------- #
#                              Domain objects                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LagReading:
    """A single measurement of ingestion lag for one topic/partition."""
    topic: str
    partition: int
    lag_ms: int
    timestamp_unix_ms: int


@dataclass(frozen=True, slots=True)
class LagAlert:
    """Raised when lag breaches a user-defined SLA threshold."""
    reading: LagReading
    threshold_ms: int
    severity: str  # e.g., "warning", "critical"


# --------------------------------------------------------------------------- #
#                          Strategy pattern (Brooker)                         #
# --------------------------------------------------------------------------- #


class BrokerLagStrategy(ABC):
    """
    Strategy interface that hides broker-specific logic for retrieving
    consumer lag.  Each implementation *must* be thread-safe.
    """

    @abstractmethod
    def topic_partitions(self) -> Iterable[str]:
        """Return all topic names that the strategy can measure."""

    @abstractmethod
    def measure(self) -> List[LagReading]:
        """
        Return the current lag, in milliseconds, for **all**
        topic/partitions that the strategy manages.
        """


class KafkaLagStrategy(BrokerLagStrategy):
    """
    Kafka implementation that leverages the kafka-python client.  It
    calculates lag as the delta between the latest log end offset (LEO) and
    the committed consumer offset, then converts it to an approximate
    millisecond delay using timestamp fetches.
    """

    _OFFSET_FETCH_BATCH_SIZE = 50

    def __init__(
        self,
        bootstrap_servers: str | List[str],
        group_id: str,
        topics: Iterable[str],
        timeout_ms: int = 5_000,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._topics = list(topics)
        self._timeout_ms = timeout_ms

        # Admin & consumer clients are thread-safe for reads
        self._admin = KafkaAdminClient(bootstrap_servers=bootstrap_servers)
        self._consumer = KafkaConsumer(
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            consumer_timeout_ms=timeout_ms,
            max_poll_records=1,
        )

        # Preseek topics to eliminate first-call latency
        self._consumer.subscribe(self._topics)
        logging.getLogger(__name__).debug("KafkaLagStrategy initialized")

    # ------------- BrokerLagStrategy contract -------------------------------- #

    def topic_partitions(self) -> Iterable[str]:
        return list(self._topics)

    def measure(self) -> List[LagReading]:
        readings: List[LagReading] = []

        for topic in self._topics:
            partitions_info = self._admin.describe_topics([topic])[0].partitions
            for p in partitions_info:
                tp = (topic, p.partition)
                # Latest broker timestamp for the partition
                # NB: Using time based offset fetch (may require Kafka ≥ 0.10)
                end_offsets = self._consumer.end_offsets([tp])
                end_offset = end_offsets[tp]

                committed_offset = self._consumer.committed(tp)
                if committed_offset is None:
                    committed_offset = 0

                # Seek end to get timestamp
                self._consumer.assign([tp])
                self._consumer.seek(tp, end_offset - 1)
                recs = self._consumer.poll(timeout_ms=self._timeout_ms)
                if not recs:  # Partition empty
                    continue

                # Convert epoch (μs) to ms
                last_event_ts = next(iter(recs.values()))[0].timestamp // 1000
                now_ms = int(time.time() * 1000)
                lag_ms = max(now_ms - last_event_ts, 0)

                readings.append(
                    LagReading(
                        topic=topic,
                        partition=p.partition,
                        lag_ms=lag_ms,
                        timestamp_unix_ms=now_ms,
                    )
                )
        return readings


# --------------------------------------------------------------------------- #
#                        Observer pattern (Alerting)                          #
# --------------------------------------------------------------------------- #


class LagObserver(ABC):
    """Receives LagAlert notifications."""

    @abstractmethod
    def notify(self, alert: LagAlert) -> None:
        """Handle alert synchronously (callers may dispatch in thread)."""


class LoggingLagObserver(LagObserver):
    """Default observer that logs alerts."""

    LEVEL_MAPPING = {
        "info": logging.INFO,
        "warning": logging.WARNING,
        "critical": logging.CRITICAL,
    }

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def notify(self, alert: LagAlert) -> None:  # pragma: no cover
        level = self.LEVEL_MAPPING.get(alert.severity, logging.WARNING)
        self._logger.log(
            level,
            "Lag alert! topic=%s partition=%s lag_ms=%s threshold=%s severity=%s",
            alert.reading.topic,
            alert.reading.partition,
            alert.reading.lag_ms,
            alert.threshold_ms,
            alert.severity,
        )


# --------------------------------------------------------------------------- #
#                       Stream Lag Monitor (Orchestrator)                     #
# --------------------------------------------------------------------------- #


class StreamLagMonitor(threading.Thread):
    """
    Background thread that schedules measurement, Prometheus export and alert
    dispatch.  Designed to be embedded inside a FastAPI, Flask, or Celery
    worker process, or run as a standalone daemon.
    """

    def __init__(
        self,
        strategy: BrokerLagStrategy,
        *,
        polling_interval_s: float = 10.0,
        lag_threshold_ms: int = 5_000,
        slack: float = 0.25,
        observers: Optional[List[LagObserver]] = None,
        prometheus_port: int = 8001,
    ) -> None:
        super().__init__(daemon=True, name="StreamLagMonitor")
        self._strategy = strategy
        self._polling_interval_s = polling_interval_s
        self._lag_threshold_ms = lag_threshold_ms
        self._slack = slack  # Fraction that defines critical vs warning
        self._observers = observers or [LoggingLagObserver()]
        self._prometheus_port = prometheus_port
        self._stop_event = threading.Event()

        # Prometheus metric registration
        self._prom_gauge = Gauge(
            "pulsestream_ingestion_lag_ms",
            "Current end-to-end ingestion lag per topic partition",
            labelnames=("topic", "partition"),
        )

        # Backpressure queue for observer notifications
        self._alert_queue: Queue[LagAlert] = Queue(maxsize=10_000)

        logging.getLogger(__name__).info(
            "StreamLagMonitor initialized (interval=%ss threshold=%sms)",
            polling_interval_s,
            lag_threshold_ms,
        )

    # ------------- Thread API ------------------------------------------------ #

    def run(self) -> None:  # pragma: no cover
        # Prometheus HTTP endpoint
        start_http_server(self._prometheus_port)
        logging.getLogger(__name__).info(
            "Serving Prometheus metrics at http://0.0.0.0:%s", self._prometheus_port
        )

        # Start worker thread for observer delivery
        delivery_thread = threading.Thread(
            target=self._deliver_alerts, name="LagAlertDelivery", daemon=True
        )
        delivery_thread.start()

        while not self._stop_event.is_set():
            start_ts = time.perf_counter()
            try:
                self._collect_and_evaluate()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).exception("Lag collection failed: %s", exc)

            elapsed = time.perf_counter() - start_ts
            time_to_sleep = max(self._polling_interval_s - elapsed, 0.1)
            time.sleep(time_to_sleep)

    def stop(self) -> None:
        """Initiates a graceful shutdown."""
        self._stop_event.set()

    # ------------- Internal helpers ----------------------------------------- #

    def _collect_and_evaluate(self) -> None:
        readings = self._strategy.measure()
        logging.getLogger(__name__).debug("Collected %d lag readings", len(readings))

        for reading in readings:
            # Update Prometheus
            self._prom_gauge.labels(
                topic=reading.topic, partition=str(reading.partition)
            ).set(reading.lag_ms)

            # Evaluate against thresholds
            if reading.lag_ms >= self._lag_threshold_ms:
                severity = (
                    "critical"
                    if reading.lag_ms >= self._lag_threshold_ms * (1 + self._slack)
                    else "warning"
                )
                alert = LagAlert(
                    reading=reading,
                    threshold_ms=self._lag_threshold_ms,
                    severity=severity,
                )
                # Non-blocking put; drop if queue is saturated
                try:
                    self._alert_queue.put_nowait(alert)
                except:  # noqa: E722  # pragma: no cover
                    logging.getLogger(__name__).warning(
                        "Dropping alert due to saturated queue"
                    )

    def _deliver_alerts(self) -> None:  # pragma: no cover
        while not self._stop_event.is_set():
            try:
                alert = self._alert_queue.get(timeout=0.5)
            except Empty:
                continue

            for observer in self._observers:
                try:
                    observer.notify(alert)
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).error(
                        "Alert observer %s failed: %s", observer, exc
                    )
            self._alert_queue.task_done()


# --------------------------------------------------------------------------- #
#                                   CLI                                       #
# --------------------------------------------------------------------------- #

def _install_signal_handlers(monitor: StreamLagMonitor) -> None:  # pragma: no cover
    def _handler(signum, _):
        logging.getLogger(__name__).info("Received signal %s, shutting down", signum)
        monitor.stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _parse_args(argv: List[str]) -> Dict[str, str]:  # noqa: C901
    """
    Ultra-lightweight argument parsing to avoid heavy deps in this isolated
    module. Expected args:

    --brokers <host:port[,host:port...]>
    --group-id <consumer-group>
    --topics <topicA,topicB>
    --threshold-ms <int>
    --interval-s <float>
    --prom-port <int>
    """
    args = {
        "--brokers": os.getenv("KAFKA_BROKERS", "localhost:9092"),
        "--group-id": os.getenv("KAFKA_GROUP_ID", "pulsestream-monitor"),
        "--topics": os.getenv("KAFKA_TOPICS", ""),
        "--threshold-ms": os.getenv("LAG_THRESHOLD_MS", "5000"),
        "--interval-s": os.getenv("LAG_POLL_INTERVAL_S", "10"),
        "--prom-port": os.getenv("PROMETHEUS_PORT", "8001"),
    }

    key = None
    for token in argv:
        if token.startswith("--"):
            key = token
            continue
        if key:
            args[key] = token
            key = None

    if not args["--topics"]:
        raise SystemExit("Missing --topics")

    return args


def _configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main(argv: List[str] | None = None) -> None:  # pragma: no cover
    """
    Launches the background monitor. This function is intentionally located in
    the same file to make `python -m src.module_65` work without pkg resources.
    """
    _configure_logging()

    argv = argv or sys.argv[1:]
    args = _parse_args(argv)

    strategy = KafkaLagStrategy(
        bootstrap_servers=args["--brokers"].split(","),
        group_id=args["--group-id"],
        topics=args["--topics"].split(","),
    )

    monitor = StreamLagMonitor(
        strategy,
        polling_interval_s=float(args["--interval-s"]),
        lag_threshold_ms=int(args["--threshold-ms"]),
        prometheus_port=int(args["--prom-port"]),
    )

    _install_signal_handlers(monitor)
    monitor.start()
    monitor.join()


if __name__ == "__main__":  # pragma: no cover
    main()
```