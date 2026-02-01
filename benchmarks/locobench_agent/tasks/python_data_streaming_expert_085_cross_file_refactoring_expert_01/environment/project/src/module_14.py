```python
"""
PulseStream Nexus
=================
src/module_14.py

Module 14 – Kafka Consumer Lag Monitor
--------------------------------------
This module houses the `LagMonitor`, a reusable, production-hardened component
that tracks consumer lag for one or more Kafka consumer groups and exposes the
values as Prometheus metrics.  When lag exceeds a configurable threshold the
component will log with `WARNING` level and (optionally) forward an event to
Sentry.  It is designed to be embedded in any micro-service belonging to
PulseStream Nexus that consumes Kafka topics in (near-)real-time.

Patterns & Principles
~~~~~~~~~~~~~~~~~~~~~
* Observer Pattern – internal observers can subscribe to lag updates.
* Strategy Pattern – pluggable `LagProviderStrategy` implementations make it
  possible to swap out the underlying Kafka client (e.g. confluent-kafka,
  kafka-python, AWS MSK SDK) without impacting the monitor’s public contract.
* Clean Architecture – the class lives in the “interface adapters” ring.  It
  depends only on stable abstractions (`LagProviderStrategy`) and emits
  domain-free metrics.

The implementation purposely avoids heavyweight frameworks; dependencies that
might be missing in certain environments are imported lazily with graceful
degradation.

Author: PulseStream Nexus Core Team
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Optional runtime dependencies – imported lazily / guarded
# --------------------------------------------------------------------------- #
try:
    from prometheus_client import Gauge, start_http_server  # type: ignore
except ImportError:  # pragma: no cover
    Gauge = None  # type: ignore
    start_http_server = None  # type: ignore

try:
    import sentry_sdk  # type: ignore
except ImportError:  # pragma: no cover
    sentry_sdk = None  # type: ignore

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

# --------------------------------------------------------------------------- #
# Domain-free data classes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LagRecord:
    """Data object that captures lag for a single topic/partition."""
    topic: str
    partition: int
    lag: int


@dataclass
class LagMonitorConfig:
    """
    Configuration for `LagMonitor`.

    Attributes
    ----------
    consumer_group : str
        The consumer group id whose lag will be tracked.
    poll_interval_secs : int
        How frequently to check lag (in seconds).
    lag_alert_threshold : int
        Emit alert when total lag >= threshold.
    prometheus_export : bool
        Whether to expose Prometheus metrics.
    prometheus_port : int
        TCP port for Prometheus HTTP exporter.
    """
    consumer_group: str
    poll_interval_secs: int = 15
    lag_alert_threshold: int = 10_000
    prometheus_export: bool = True
    prometheus_port: int = 8000

    # Strategy-specific opaque dictionary (e.g. bootstrap servers)
    strategy_kwargs: Dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Strategy Interface
# --------------------------------------------------------------------------- #


class LagProviderStrategy(ABC):
    """
    Strategy interface: supplies consumer lag information.

    A concrete implementation is responsible for connecting to the Kafka cluster
    and returning the current end offset minus the committed offset for every
    topic/partition assigned to the consumer group.
    """

    @abstractmethod
    def fetch_lag(
        self, *, consumer_group: str
    ) -> Iterable[LagRecord]:  # pragma: no cover
        """
        Retrieve lag for the given consumer group.

        Returns
        -------
        Iterable[LagRecord]
            One LagRecord per topic/partition.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Kafka-Python Strategy Implementation
# --------------------------------------------------------------------------- #
# NOTE: We purposely use kafka-python (lightweight, pure-Python) for portability
#       and avoid de-facto library wars. Organisations preferring confluent-kafka
#       can create an alternative strategy adhering to `LagProviderStrategy`.


class KafkaPythonLagProvider(LagProviderStrategy):
    """
    Lag provider based on the official `kafka-python` package.

    The implementation:
    * Uses `KafkaConsumer` to query end offsets (latest) per partition.
    * Uses `KafkaAdminClient` to inspect committed offsets for the consumer
      group (via ListConsumerGroupOffsetsRequest V0).
    """

    def __init__(self, bootstrap_servers: str, security_protocol: str = "PLAINTEXT"):
        # Lazy import to avoid mandatory runtime dependency
        try:
            from kafka import KafkaAdminClient, KafkaConsumer  # type: ignore
            from kafka.errors import KafkaError  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "'kafka-python' is required for KafkaPythonLagProvider"
            ) from exc

        self._KafkaAdminClient = KafkaAdminClient
        self._KafkaConsumer = KafkaConsumer
        self._KafkaError = KafkaError
        self._bootstrap_servers = bootstrap_servers
        self._security_protocol = security_protocol

    def fetch_lag(self, *, consumer_group: str) -> Iterable[LagRecord]:
        """
        Gather lag information for `consumer_group`.

        Returns
        -------
        List[LagRecord]
        """
        from collections import defaultdict

        admin = self._KafkaAdminClient(
            bootstrap_servers=self._bootstrap_servers,
            security_protocol=self._security_protocol,
            client_id="lag-monitor-admin",
            api_version_auto_timeout_ms=60_000,
        )

        # Fetch committed offsets for consumer group
        group_offsets = admin.list_consumer_group_offsets(consumer_group)
        topic_partitions = [
            (tp.topic, tp.partition) for tp in group_offsets.keys()
        ]

        if not topic_partitions:
            logger.debug("No topic partitions found for consumer group '%s'", consumer_group)
            return []

        # Group partitions by topic for efficient fetch of end offsets
        topic_to_partitions: Dict[str, List[int]] = defaultdict(list)
        for topic, partition in topic_partitions:
            topic_to_partitions[topic].append(partition)

        # Use KafkaConsumer to query latest offsets
        consumer = self._KafkaConsumer(
            bootstrap_servers=self._bootstrap_servers,
            security_protocol=self._security_protocol,
            enable_auto_commit=False,
            api_version_auto_timeout_ms=60_000,
        )

        records: List[LagRecord] = []

        try:
            for topic, partitions in topic_to_partitions.items():
                tp_list = [self._topic_partition(topic, p) for p in partitions]
                end_offsets = consumer.end_offsets(tp_list)  # type: ignore

                for tp in tp_list:
                    committed_offset = group_offsets[tp].offset
                    latest_offset = end_offsets[tp]
                    lag_value = max(latest_offset - committed_offset, 0)
                    records.append(
                        LagRecord(topic=tp.topic, partition=tp.partition, lag=lag_value)
                    )
        finally:
            consumer.close()
            admin.close()

        return records

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _topic_partition(self, topic: str, partition: int):
        """Helper to create TopicPartition instance without importing in client code."""
        from kafka.structs import TopicPartition  # type: ignore

        return TopicPartition(topic, partition)


# --------------------------------------------------------------------------- #
# Lag Monitor
# --------------------------------------------------------------------------- #


class LagMonitor:
    """
    Periodically polls lag for a consumer group and makes it observable.

    Example
    -------
    >>> provider = KafkaPythonLagProvider(bootstrap_servers="kafka-broker:9092")
    >>> cfg = LagMonitorConfig(consumer_group="twitter_ingestor")
    >>> monitor = LagMonitor(config=cfg, provider=provider)
    >>> monitor.start()               # start background thread
    >>> ...
    >>> monitor.stop()                # stop gracefully
    """

    _GAUGE_NAME = "kafka_consumer_partition_lag"
    _GAUGE_DOC = "Lag of Kafka consumer group per topic and partition."

    def __init__(self, config: LagMonitorConfig, provider: LagProviderStrategy):
        self._config = config
        self._provider = provider
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._subscribers: List = []

        self._prom_gauge = None
        if self._config.prometheus_export and Gauge is not None:
            # Labels: consumer_group, topic, partition
            self._prom_gauge = Gauge(
                self._GAUGE_NAME,
                self._GAUGE_DOC,
                labelnames=["consumer_group", "topic", "partition"],
            )
            if start_http_server is not None:
                start_http_server(self._config.prometheus_port)
                logger.info(
                    "Prometheus exporter listening on port %d",
                    self._config.prometheus_port,
                )
        elif self._config.prometheus_export:
            logger.warning(
                "prometheus_client not installed; disabling Prometheus metrics."
            )

    # --------------------------------------------------------------------- #
    # Public interface
    # --------------------------------------------------------------------- #

    def start(self) -> None:
        """Spawn daemon thread that loops until `stop()` is called."""
        if self._thread and self._thread.is_alive():
            logger.debug("LagMonitor already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="LagMonitorThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("LagMonitor started for consumer group '%s'", self._config.consumer_group)

    def stop(self, timeout: int = 5) -> None:
        """Signal the background thread to finish and wait for completion."""
        if not self._thread:
            return

        self._stop_event.set()
        self._thread.join(timeout=timeout)
        logger.info("LagMonitor stopped.")

    def subscribe(self, callback) -> None:
        """
        Register an observer callback invoked with signature:

        `callback(total_lag: int, lag_details: List[LagRecord])`
        """
        self._subscribers.append(callback)

    # --------------------------------------------------------------------- #
    # Internal
    # --------------------------------------------------------------------- #

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                lag_records = list(
                    self._provider.fetch_lag(
                        consumer_group=self._config.consumer_group
                    )
                )
                total_lag = sum(r.lag for r in lag_records)
                # Publish to observers
                for cb in self._subscribers:
                    self._safe_invoke(cb, total_lag, lag_records)

                # Export metrics
                self._export_prometheus_metrics(lag_records)

                # Log / alert
                self._handle_alerting(total_lag, lag_records)

            except Exception as exc:  # pragma: no cover
                logger.exception("Unexpected error while fetching lag: %s", exc)
                if sentry_sdk:
                    sentry_sdk.capture_exception(exc)

            # Wait until next poll or until stop is requested
            self._stop_event.wait(self._config.poll_interval_secs)

    def _export_prometheus_metrics(self, lag_records: Iterable[LagRecord]) -> None:
        if not self._prom_gauge:
            return

        # Reset all previous gauge values for this consumer group
        self._prom_gauge.clear()

        for record in lag_records:
            self._prom_gauge.labels(
                consumer_group=self._config.consumer_group,
                topic=record.topic,
                partition=str(record.partition),
            ).set(record.lag)

    def _handle_alerting(
        self, total_lag: int, lag_records: List[LagRecord]
    ) -> None:
        if total_lag >= self._config.lag_alert_threshold:
            logger.warning(
                "Lag threshold exceeded for group '%s': lag=%d (threshold=%d)",
                self._config.consumer_group,
                total_lag,
                self._config.lag_alert_threshold,
            )
            if sentry_sdk:
                sentry_sdk.capture_message(
                    f"Lag threshold exceeded: {total_lag}",
                    level="warning",
                )
        else:
            logger.debug(
                "Lag for group '%s': %d (threshold: %d)",
                self._config.consumer_group,
                total_lag,
                self._config.lag_alert_threshold,
            )

    @staticmethod
    def _safe_invoke(callback, *args, **kwargs) -> None:
        try:
            callback(*args, **kwargs)
        except Exception as exc:  # pragma: no cover
            logger.exception("LagMonitor subscriber raised exception: %s", exc)


# --------------------------------------------------------------------------- #
# CLI Bootstrap
# --------------------------------------------------------------------------- #
def _build_default_provider(config: LagMonitorConfig) -> LagProviderStrategy:
    """
    Factory for default provider using kafka-python, with graceful fallback.
    """
    try:
        return KafkaPythonLagProvider(**config.strategy_kwargs)
    except RuntimeError as exc:  # pragma: no cover
        logger.error(exc)
        raise SystemExit(1) from exc


def main() -> None:  # pragma: no cover
    """
    Ad-hoc CLI entry-point, useful for local debugging.
    Example
    -------
    $ python -m src.module_14 --bootstrap-servers localhost:9092 --group my_group
    """
    import argparse

    parser = argparse.ArgumentParser(description="Kafka Consumer Lag Monitor")
    parser.add_argument("--bootstrap-servers", required=True, help="Kafka brokers")
    parser.add_argument("--group", required=True, help="Consumer group id")
    parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="Polling interval in seconds (default: 15)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=10_000,
        help="Alert threshold for total lag",
    )
    parser.add_argument(
        "--prom-port",
        type=int,
        default=8000,
        help="Prometheus exporter port (default: 8000)",
    )

    args = parser.parse_args()

    cfg = LagMonitorConfig(
        consumer_group=args.group,
        poll_interval_secs=args.interval,
        lag_alert_threshold=args.threshold,
        prometheus_port=args.prom_port,
        strategy_kwargs={"bootstrap_servers": args.bootstrap_servers},
    )

    monitor = LagMonitor(config=cfg, provider=_build_default_provider(cfg))
    monitor.start()

    try:
        # Block the main thread until user interruption
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
        monitor.stop()


if __name__ == "__main__":  # pragma: no cover
    main()
```