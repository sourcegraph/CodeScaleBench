"""PulseStream Nexus – Stream Lag Monitoring Module (module_58.py)

This module implements a production–grade Kafka consumer–lag monitoring
service that fits into the overall PulseStream Nexus architecture:

• Observer pattern – Observers may subscribe to lag / error events.
• Strategy pattern – Multiple lag–calculation strategies are pluggable.
• Prometheus integration – Lag metrics can be pushed to a Pushgateway.
• Robust error handling, thread-safe observer list, clean shutdown.

Typical usage
-------------
$ python -m src.module_58          # runs as a stand-alone microservice
or embed the `StreamLagMonitor` inside a larger service.

Environment variables
---------------------
KAFKA_BOOTSTRAP_SERVERS   – comma-separated broker list
KAFKA_CONSUMER_GROUP      – consumer group to monitor
LAG_POLL_INTERVAL_SEC     – polling cadence (seconds, default 10)
LAG_STRATEGY              – 'latest' or 'average'
PROM_PUSHGATEWAY          – host:port of Prometheus Pushgateway
ENABLE_PROM_METRICS       – 'true' / 'false' to toggle Prometheus
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol

# --------------------------------------------------------------------------- #
# Optional third-party dependencies. We degrade gracefully if they are absent #
# --------------------------------------------------------------------------- #
try:
    from kafka import KafkaAdminClient, KafkaConsumer
    from kafka.structs import TopicPartition
except ImportError:  # pragma: no cover
    KafkaAdminClient = None
    KafkaConsumer = None
    TopicPartition = None  # type: ignore

try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
except ImportError:  # pragma: no cover
    CollectorRegistry = None  # type: ignore
    Gauge = None  # type: ignore

    def push_to_gateway(*_args: Any, **_kwargs: Any) -> None:  # type: ignore
        """No-op stub when prometheus_client is not available."""
        pass


# -------------------------- Common event definitions ----------------------- #


@dataclass(slots=True, frozen=True)
class Event:
    """Base class for all events emitted by the monitor."""

    timestamp: float
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class LagEvent(Event):
    """Event representing consumer lag for a specific topic/partition."""

    topic: str = ""
    partition: int = -1


@dataclass(slots=True, frozen=True)
class ErrorEvent(Event):
    """Signals an unexpected error raised inside the monitor."""

    error: Exception | None = None


# --------------------------- Observer infrastructure ----------------------- #


class Observer(Protocol):
    """Observer interface (Strategy Pattern)."""

    def update(self, event: Event) -> None: ...


class Observable:
    """Thread-safe observable base with classic attach/detach/notify."""

    __slots__ = ("_observers", "_lock")

    def __init__(self) -> None:
        self._observers: List[Observer] = []
        self._lock = threading.Lock()

    # ‑- subscription management ‑- #

    def register(self, obs: Observer) -> None:
        with self._lock:
            if obs not in self._observers:
                self._observers.append(obs)

    def unregister(self, obs: Observer) -> None:
        with self._lock:
            if obs in self._observers:
                self._observers.remove(obs)

    # ‑- event dispatch ‑- #

    def notify(self, event: Event) -> None:
        with self._lock:
            observers_snapshot = list(self._observers)

        for observer in observers_snapshot:
            try:
                observer.update(event)
            except Exception as exc:  # pragma: no cover
                logging.getLogger(__name__).exception(
                    "Observer %s raised error on event %s: %s",
                    observer,
                    type(event).__name__,
                    exc,
                )


# -------------------- Lag computation strategy interface ------------------- #


class LagComputationStrategy(Protocol):
    """Strategy interface for converting raw offsets to lag numbers."""

    def compute_lag(
        self, offsets: Dict[int, Dict[str, int]]
    ) -> Dict[int, int | float]: ...


class LatestOffsetStrategy:
    """Most common lag definition: latest − committed."""

    def compute_lag(self, offsets: Dict[int, Dict[str, int]]) -> Dict[int, int]:
        return {
            partition: max(values["latest"] - values["committed"], 0)
            for partition, values in offsets.items()
        }


class TimeWindowAverageStrategy:
    """Smoothed lag over a sliding window (size=N polls)."""

    def __init__(self, window_size: int = 5) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be > 0")
        self.window_size = window_size
        self._history: Dict[int, List[int]] = {}

    def compute_lag(
        self, offsets: Dict[int, Dict[str, int]]
    ) -> Dict[int, float]:  # noqa: D401
        latest_strategy = LatestOffsetStrategy()
        raw_lags = latest_strategy.compute_lag(offsets)
        averaged: Dict[int, float] = {}

        for partition, lag in raw_lags.items():
            hist = self._history.setdefault(partition, [])
            hist.append(lag)
            if len(hist) > self.window_size:
                hist.pop(0)
            averaged[partition] = sum(hist) / len(hist)

        return averaged


# ------------------- Observer implementations (Logging, Prom) -------------- #


class LoggingObserver:
    """Simple observer that logs lag & error events."""

    def __init__(self, level: int = logging.INFO) -> None:
        self._logger = logging.getLogger("PulseStream.LagMonitor")
        self._logger.setLevel(level)

    # Dispatcher
    def update(self, event: Event) -> None:
        if isinstance(event, LagEvent):
            self._logger.debug(
                "LagEvent: topic=%s partition=%s lag=%s",
                event.topic,
                event.partition,
                event.payload.get("lag"),
            )
        elif isinstance(event, ErrorEvent):
            self._logger.error("ErrorEvent: %s", event.error, exc_info=event.error)


class PrometheusLagObserver:
    """Pushes per-partition lag metrics to a Prometheus Pushgateway."""

    def __init__(
        self,
        job_name: str = "pulsestream_nexus_lag",
        gateway: str | None = None,
    ) -> None:
        if Gauge is None:  # pragma: no cover
            raise RuntimeError(
                "prometheus_client package must be installed for PrometheusLagObserver"
            )

        self.registry: CollectorRegistry = CollectorRegistry()
        self.gauge: Gauge = Gauge(
            "kafka_consumer_partition_lag",
            "Lag of Kafka consumer per partition",
            ["topic", "partition"],
            registry=self.registry,
        )
        self.job_name = job_name
        self.gateway = gateway or os.getenv("PROM_PUSHGATEWAY", "localhost:9091")

    def update(self, event: Event) -> None:  # noqa: D401
        if not isinstance(event, LagEvent):
            return

        partition_label = str(event.partition)
        lag_value = event.payload.get("lag", 0)
        self.gauge.labels(topic=event.topic, partition=partition_label).set(lag_value)

        try:
            push_to_gateway(self.gateway, job=self.job_name, registry=self.registry)
        except Exception as exc:  # pragma: no cover
            logging.getLogger(__name__).warning(
                "Failed to push Prometheus metrics: %s", exc
            )


# -------------------------- Kafka offset reader ---------------------------- #


class KafkaLagReader:
    """
    Retrieves committed & latest offsets for a consumer group via the
    Kafka AdminClient + a lightweight KafkaConsumer.

    Returned structure:
        {
            "<topic>": {
                <partition>: {"committed": int, "latest": int},
                ...
            },
            ...
        }
    """

    def __init__(
        self,
        brokers: str,
        consumer_group: str,
        admin_client_kwargs: Dict[str, Any] | None = None,
    ) -> None:
        if KafkaAdminClient is None:  # pragma: no cover
            raise RuntimeError(
                "kafka-python package must be installed for KafkaLagReader"
            )

        admin_params = {
            "bootstrap_servers": brokers,
            "client_id": f"lag_monitor_{consumer_group}",
        }
        if admin_client_kwargs:
            admin_params.update(admin_client_kwargs)

        self.consumer_group = consumer_group
        self._admin = KafkaAdminClient(**admin_params)

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #
    def fetch_consumer_offsets(self) -> Dict[str, Dict[int, Dict[str, int]]]:
        """
        Query Kafka for committed and log-end offsets.

        Raises
        ------
        RuntimeError
            If Kafka queries fail for any reason.
        """
        if TopicPartition is None or KafkaConsumer is None:  # pragma: no cover
            raise RuntimeError("kafka-python package is required to perform lags")

        try:
            group_offsets = self._admin.list_consumer_group_offsets(
                self.consumer_group
            )
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                f"Failed to list consumer group offsets: {exc}"
            ) from exc

        # ‑- build partial structure with committed offsets ‑- #
        offsets: Dict[str, Dict[int, Dict[str, int]]] = {}
        topic_partitions: List[TopicPartition] = []

        for tp, oam in group_offsets.items():
            topic_offsets = offsets.setdefault(tp.topic, {})
            topic_offsets[tp.partition] = {"committed": oam.offset}
            topic_partitions.append(tp)

        # ‑- fetch latest offsets via a temporary consumer ‑- #
        consumer = KafkaConsumer(
            bootstrap_servers=self._admin.config["bootstrap_servers"],
            enable_auto_commit=False,
            consumer_timeout_ms=1500,
        )

        try:
            end_offsets = consumer.end_offsets(topic_partitions)
        finally:
            consumer.close()

        for tp, latest_offset in end_offsets.items():
            offsets[tp.topic][tp.partition]["latest"] = latest_offset

        return offsets


# ------------------------- High-level lag monitor -------------------------- #


class StreamLagMonitor(Observable):
    """
    Periodically polls Kafka lag and notifies all attached observers.

    The monitor runs in its own daemon thread and supports clean shutdown.
    """

    def __init__(
        self,
        reader: KafkaLagReader,
        strategy: LagComputationStrategy | None = None,
        poll_interval: int = 10,
    ) -> None:
        super().__init__()
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0 seconds")

        self._reader = reader
        self._strategy: LagComputationStrategy = strategy or LatestOffsetStrategy()
        self._poll_interval = poll_interval

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._logger = logging.getLogger(self.__class__.__name__)

    # ‑- lifecycle ‑- #

    def start(self) -> None:
        """Start the background monitoring loop."""
        if not self._thread.is_alive():
            self._stop_event.clear()
            self._thread.start()
            self._logger.info("StreamLagMonitor started with interval=%s", self._poll_interval)

    def stop(self) -> None:
        """Signal the monitor to stop and wait for thread termination."""
        self._stop_event.set()
        self._thread.join(timeout=self._poll_interval * 2)
        self._logger.info("StreamLagMonitor stopped")

    # ‑- internal loop ‑- #

    def _run(self) -> None:  # pragma: no cover
        while not self._stop_event.is_set():
            loop_start = time.time()
            try:
                topic_offsets = self._reader.fetch_consumer_offsets()

                for topic, partitions in topic_offsets.items():
                    lags = self._strategy.compute_lag(partitions)
                    for partition_id, lag in lags.items():
                        evt = LagEvent(
                            timestamp=time.time(),
                            topic=topic,
                            partition=partition_id,
                            payload={"lag": lag},
                        )
                        self.notify(evt)

            except Exception as exc:  # noqa: BLE001
                self.notify(ErrorEvent(timestamp=time.time(), error=exc))

            # Smooth scheduling independent of processing time
            elapsed = time.time() - loop_start
            sleep_for = max(self._poll_interval - elapsed, 0)
            time.sleep(sleep_for)


# ------------------------------ CLI entry-point ---------------------------- #


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )


def main() -> None:  # pragma: no cover
    """Minimal runnable example (can be deployed as its own microservice)."""
    _configure_logging()
    logger = logging.getLogger(__name__)

    brokers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    group_id = os.getenv("KAFKA_CONSUMER_GROUP", "pulsestream_ingestor")
    interval = int(os.getenv("LAG_POLL_INTERVAL_SEC", "10"))

    # Pick lag strategy
    strategy_env = os.getenv("LAG_STRATEGY", "latest").lower()
    if strategy_env == "average":
        strategy: LagComputationStrategy = TimeWindowAverageStrategy(window_size=5)
    else:
        strategy = LatestOffsetStrategy()

    # Instantiate reader & monitor
    reader = KafkaLagReader(brokers=brokers, consumer_group=group_id)
    monitor = StreamLagMonitor(reader=reader, strategy=strategy, poll_interval=interval)

    # Attach observers
    monitor.register(LoggingObserver())
    metrics_enabled = os.getenv("ENABLE_PROM_METRICS", "true").lower() in {"1", "true", "yes"}
    if metrics_enabled:
        try:
            monitor.register(PrometheusLagObserver())
        except RuntimeError as exc:  # pragma: no cover
            logger.warning("Prometheus metrics disabled: %s", exc)

    # Graceful shutdown handling
    def _shutdown_handler(_signum: int, _frame: Any) -> None:
        logger.info("Shutdown signal received – stopping monitor")
        monitor.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _shutdown_handler)

    # Start and block (main thread sleeps while worker thread does the job)
    monitor.start()
    while monitor._thread.is_alive():
        time.sleep(1)


if __name__ == "__main__":  # pragma: no cover
    main()
