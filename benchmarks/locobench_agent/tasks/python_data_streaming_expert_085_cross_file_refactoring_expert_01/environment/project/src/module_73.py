```python
"""
PulseStream Nexus – Sentiment Rolling Aggregator
------------------------------------------------

module_73.py

This module contains a production-quality micro-service component that ingests
sentiment-annotated social events from a Kafka topic, computes rolling
statistics (e.g., average sentiment, volatility) over configurable windows,
and publishes the enriched aggregates back to Kafka (or any user-supplied
sink).  The design follows:

* Strategy Pattern – interchangeable windowing algorithms.
* Observer Pattern – pluggable monitoring / telemetry back-ends.
* Clean Architecture – business rules are kept framework-agnostic.

The implementation handles graceful shutdown, back-pressure, and
runtime-optional dependencies (Confluent-Kafka, Prometheus).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Deque, Dict, Iterable, List, MutableMapping, Optional, Tuple, Union

# --------------------------------------------------------------------------- #
# Optional third-party dependencies – we degrade gracefully if they are absent
# --------------------------------------------------------------------------- #
try:
    from confluent_kafka import Consumer, Producer, KafkaException
except ModuleNotFoundError:  # pragma: no cover
    # Lightweight stubs so type checkers are happy and unit tests can run
    class KafkaException(Exception):
        pass

    class _DummyKafkaIO:  # pylint: disable=too-few-public-methods
        def __init__(self, *_, **__):
            raise KafkaException(
                "confluent-kafka not installed – install or mock for production."
            )

    Consumer = _DummyKafkaIO  # type: ignore
    Producer = _DummyKafkaIO  # type: ignore

try:
    from prometheus_client import Counter, Gauge, start_http_server
except ModuleNotFoundError:  # pragma: no cover
    # Fallback no-ops
    class _Metric:  # pylint: disable=too-few-public-methods
        def inc(self, *_args, **_kwargs):
            pass

        def set(self, *_args, **_kwargs):
            pass

        def observe(self, *_args, **_kwargs):
            pass

    Counter = Gauge = _Metric  # type: ignore[assignment]

    def start_http_server(*_args, **_kwargs):
        pass

# --------------------------------------------------------------------------- #
# Configuration Data Classes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class KafkaConfig:
    """Configuration properties for Kafka clients."""

    brokers: str
    source_topic: str
    sink_topic: str
    group_id: str = "pulse_stream.sentiment_aggregator"
    auto_offset_reset: str = "latest"
    security_protocol: str = "PLAINTEXT"
    ssl_cafile: Optional[str] = None
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None

    def consumer_conf(self) -> Dict[str, Union[str, int]]:
        """Translate to Confluent consumer config."""
        config = {
            "bootstrap.servers": self.brokers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": False,
            "security.protocol": self.security_protocol,
        }
        if self.ssl_cafile:
            config["ssl.ca.location"] = self.ssl_cafile
        if self.ssl_certfile:
            config["ssl.certificate.location"] = self.ssl_certfile
        if self.ssl_keyfile:
            config["ssl.key.location"] = self.ssl_keyfile
        return config

    def producer_conf(self) -> Dict[str, Union[str, int]]:
        """Translate to Confluent producer config."""
        config = {
            "bootstrap.servers": self.brokers,
            "security.protocol": self.security_protocol,
        }
        if self.ssl_cafile:
            config["ssl.ca.location"] = self.ssl_cafile
        if self.ssl_certfile:
            config["ssl.certificate.location"] = self.ssl_certfile
        if self.ssl_keyfile:
            config["ssl.key.location"] = self.ssl_keyfile
        return config


@dataclass
class ServiceConfig:
    """Top-level aggregator configuration."""

    kafka: KafkaConfig
    window_size: int = 300  # seconds
    slide_interval: int = 60  # seconds
    min_samples: int = 10
    metrics_port: int = 9095
    max_queue_size: int = 5_000
    flush_interval: int = 1.0  # seconds


# --------------------------------------------------------------------------- #
# Strategy Pattern – rolling window algorithms
# --------------------------------------------------------------------------- #


class WindowStrategy(ABC):
    """Strategy interface for rolling window calculations."""

    @abstractmethod
    def add(self, event_ts: float, value: float) -> None:
        """Add a new data point."""
        raise NotImplementedError

    @abstractmethod
    def aggregate(self) -> Optional[Dict[str, float]]:
        """Return aggregation results (mean, stdev, count)."""
        raise NotImplementedError


class TumblingWindow(WindowStrategy):
    """
    Standard fixed (non-overlapping) tumbling windows.

    A new window starts immediately after the previous one completes.
    """

    def __init__(self, window_size: int):
        self._window_size = timedelta(seconds=window_size)
        self._bucket: List[float] = []
        self._window_end: Optional[datetime] = None

    def add(self, event_ts: float, value: float) -> None:
        ts = datetime.fromtimestamp(event_ts)
        if self._window_end is None:
            self._window_end = ts + self._window_size

        if ts >= self._window_end:
            # Overflow → current window finished; reset and start new
            self._bucket.clear()
            self._window_end += self._window_size

        self._bucket.append(value)

    def aggregate(self) -> Optional[Dict[str, float]]:
        if not self._bucket:
            return None
        return {
            "count": len(self._bucket),
            "mean": mean(self._bucket),
            "stdev": pstdev(self._bucket) if len(self._bucket) > 1 else 0.0,
        }


class SlidingWindow(WindowStrategy):
    """
    Sliding window with overlap.

    Uses a deque as ring-buffer to drop expired samples.
    """

    def __init__(self, window_size: int, slide_interval: int):
        if slide_interval <= 0 or window_size <= 0:
            raise ValueError("Window and slide sizes must be positive")

        self._window_size = window_size
        self._slide_interval = slide_interval
        self._events: Deque[Tuple[float, float]] = deque()  # (ts, value)
        self._last_slide: float = 0.0

    def add(self, event_ts: float, value: float) -> None:
        self._events.append((event_ts, value))
        self._evict(event_ts)

    def _evict(self, current_ts: float) -> None:
        eviction_threshold = current_ts - self._window_size
        while self._events and self._events[0][0] < eviction_threshold:
            self._events.popleft()

    def aggregate(self) -> Optional[Dict[str, float]]:
        if not self._events:
            return None

        current_ts = self._events[-1][0]
        if current_ts - self._last_slide < self._slide_interval:
            return None  # Not time yet

        self._last_slide = current_ts
        values = [v for _, v in self._events]
        return {
            "count": len(values),
            "mean": mean(values),
            "stdev": pstdev(values) if len(values) > 1 else 0.0,
        }


# --------------------------------------------------------------------------- #
# Observer Pattern – monitoring / telemetry
# --------------------------------------------------------------------------- #


class Monitor(ABC):
    """Observer interface for monitoring back-ends."""

    @abstractmethod
    def on_event_processed(self) -> None:
        pass

    @abstractmethod
    def on_aggregate_emitted(self, aggregate: Dict[str, float]) -> None:
        pass

    @abstractmethod
    def on_exception(self, exc: Exception) -> None:
        pass


class LoggingMonitor(Monitor):
    """Simple monitor that logs to Python logging module."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def on_event_processed(self) -> None:
        pass  # Noise reduction – only aggregates are logged

    def on_aggregate_emitted(self, aggregate: Dict[str, float]) -> None:
        self._logger.info("Aggregate emitted: %s", aggregate)

    def on_exception(self, exc: Exception) -> None:
        self._logger.exception("Aggregator exception: %s", exc)


class PrometheusMonitor(Monitor):
    """Monitor that exports metrics to Prometheus."""

    _EVENT_COUNTER = Counter(
        "psn_events_processed_total", "Total sentiment events processed"
    )
    _AGG_COUNTER = Counter(
        "psn_aggregates_emitted_total", "Total sentiment aggregates emitted"
    )
    _AGG_MEAN = Gauge("psn_last_mean_sentiment", "Mean sentiment of last aggregate")
    _AGG_COUNT = Gauge("psn_last_aggregate_count", "Sample count of last aggregate")

    def on_event_processed(self) -> None:
        self._EVENT_COUNTER.inc()

    def on_aggregate_emitted(self, aggregate: Dict[str, float]) -> None:
        self._AGG_COUNTER.inc()
        self._AGG_MEAN.set(aggregate["mean"])
        self._AGG_COUNT.set(aggregate["count"])

    def on_exception(self, exc: Exception) -> None:
        # Prometheus remote write not supported here – silently ignore
        pass


# --------------------------------------------------------------------------- #
# Core Aggregator Service
# --------------------------------------------------------------------------- #


class SentimentRollingAggregator:
    """
    Service that bridges raw sentiment events to rolling aggregates.

    This class is *framework-free* and purely contains business rules +
    dependency inversion interfaces (Kafka in/out, monitoring).
    """

    def __init__(
        self,
        *,
        config: ServiceConfig,
        window_strategy: WindowStrategy,
        monitors: Optional[List[Monitor]] = None,
    ):
        self._cfg = config
        self._window = window_strategy
        self._monitors = monitors or []
        self._consumer: Optional[Consumer] = None
        self._producer: Optional[Producer] = None
        self._stop_event = threading.Event()
        self._logger = logging.getLogger(self.__class__.__name__)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def start(self) -> None:
        self._logger.info("SentimentRollingAggregator starting…")
        self._setup_kafka_clients()
        self._setup_signal_handlers()
        self._start_metrics_http_server()
        self._run_event_loop()

    def stop(self) -> None:
        self._logger.info("Shutting down aggregator…")
        self._stop_event.set()

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _setup_kafka_clients(self) -> None:
        self._consumer = Consumer(self._cfg.kafka.consumer_conf())
        self._consumer.subscribe([self._cfg.kafka.source_topic])

        self._producer = Producer(self._cfg.kafka.producer_conf())

    def _setup_signal_handlers(self) -> None:
        def _handler(_sig, _frame):  # noqa: D401
            self.stop()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _start_metrics_http_server(self) -> None:
        if any(isinstance(m, PrometheusMonitor) for m in self._monitors):
            start_http_server(self._cfg.metrics_port)
            self._logger.info("Prometheus metrics HTTP server on :%d", self._cfg.metrics_port)

    # --------------------------------------------------------------------- #

    def _run_event_loop(self) -> None:  # pylint: disable=too-many-locals
        assert self._consumer and self._producer  # Assured by _setup_kafka_clients

        flush_deadline = time.monotonic() + self._cfg.flush_interval

        try:
            while not self._stop_event.is_set():
                msg = self._consumer.poll(0.1)
                if msg is None:
                    self._maybe_flush(flush_deadline)
                    continue

                if msg.error():  # pragma: no cover
                    raise KafkaException(msg.error())

                try:
                    payload = json.loads(msg.value().decode("utf-8"))
                    event_ts, sentiment_value = self._parse_event(payload)
                except (ValueError, KeyError) as exc:
                    self._notify_exception(exc)
                    # Skip malformed message but commit offset
                    self._consumer.commit(msg, asynchronous=False)
                    continue

                # Business logic
                self._window.add(event_ts, sentiment_value)
                self._notify_event_processed()

                aggregate = self._window.aggregate()
                if aggregate and aggregate["count"] >= self._cfg.min_samples:
                    self._emit_aggregate(aggregate, event_ts)

                # Offset management
                self._consumer.commit(msg, asynchronous=False)
                self._maybe_flush(flush_deadline)
        except Exception as exc:  # pylint: disable=broad-except
            self._notify_exception(exc)
        finally:
            self._cleanup()

    # --------------------------------------------------------------------- #

    def _emit_aggregate(self, aggregate: Dict[str, float], event_ts: float) -> None:
        assert self._producer
        aggregate_record = {
            "timestamp": int(event_ts),
            "aggregate": aggregate,
        }
        self._producer.produce(
            topic=self._cfg.kafka.sink_topic,
            value=json.dumps(aggregate_record).encode("utf-8"),
        )
        self._notify_aggregate_emitted(aggregate)

    def _maybe_flush(self, deadline: float) -> None:
        assert self._producer
        if time.monotonic() >= deadline:
            with suppress(BufferError):
                self._producer.flush(0.0)
            deadline = time.monotonic() + self._cfg.flush_interval

    # --------------------------------------------------------------------- #

    @staticmethod
    def _parse_event(payload: MutableMapping[str, object]) -> Tuple[float, float]:
        """
        Validates and extracts timestamp + sentiment value.

        Expected schema:
        {
            "timestamp": 1689012345,  # unix seconds
            "sentiment":  0.42        # normalized float
        }
        """
        ts = float(payload["timestamp"])
        sentiment = float(payload["sentiment"])
        if not -1.0 <= sentiment <= 1.0:
            raise ValueError("Sentiment value out of range [-1, 1]")
        return ts, sentiment

    def _cleanup(self) -> None:  # pragma: no cover
        self._logger.info("Cleaning up Kafka clients…")
        with suppress(Exception):
            if self._producer:
                self._producer.flush(5.0)
        with suppress(Exception):
            if self._consumer:
                self._consumer.close()

    # --------------------------------------------------------------------- #
    # Monitoring helpers
    # --------------------------------------------------------------------- #

    def _notify_event_processed(self) -> None:
        for m in self._monitors:
            with suppress(Exception):
                m.on_event_processed()

    def _notify_aggregate_emitted(self, aggregate: Dict[str, float]) -> None:
        for m in self._monitors:
            with suppress(Exception):
                m.on_aggregate_emitted(aggregate)

    def _notify_exception(self, exc: Exception) -> None:
        for m in self._monitors:
            with suppress(Exception):
                m.on_exception(exc)

    # --------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Factory helpers – decouple wiring from business logic
# --------------------------------------------------------------------------- #


def build_service_from_env() -> SentimentRollingAggregator:
    """
    Instantiate the aggregator using environment variables.

    This allows the Docker image / Kubernetes chart to inject config without
    modifying code.
    """
    kafka_cfg = KafkaConfig(
        brokers=os.environ.get("KAFKA_BROKERS", "localhost:9092"),
        source_topic=os.environ.get("SOURCE_TOPIC", "sentiment.raw"),
        sink_topic=os.environ.get("SINK_TOPIC", "sentiment.aggregate"),
        group_id=os.environ.get("GROUP_ID", "pulse_stream.sentiment_aggregator"),
    )

    service_cfg = ServiceConfig(
        kafka=kafka_cfg,
        window_size=int(os.environ.get("WINDOW_SIZE", "300")),
        slide_interval=int(os.environ.get("SLIDE_INTERVAL", "60")),
        min_samples=int(os.environ.get("MIN_SAMPLES", "10")),
        metrics_port=int(os.environ.get("METRICS_PORT", "9095")),
    )

    # Strategy selection
    window_type = os.environ.get("WINDOW_TYPE", "sliding").lower()
    if window_type == "tumbling":
        strategy = TumblingWindow(service_cfg.window_size)
    else:
        strategy = SlidingWindow(service_cfg.window_size, service_cfg.slide_interval)

    # Monitoring – always include logging, Prometheus optional
    logger = logging.getLogger("psn.aggregator")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())

    monitors: List[Monitor] = [LoggingMonitor(logger)]
    if os.environ.get("PROMETHEUS_ENABLED", "true").lower() == "true":
        monitors.append(PrometheusMonitor())

    return SentimentRollingAggregator(
        config=service_cfg,
        window_strategy=strategy,
        monitors=monitors,
    )


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

def main() -> None:  # pragma: no cover
    service = build_service_from_env()
    service.start()


if __name__ == "__main__":  # pragma: no cover
    main()
```