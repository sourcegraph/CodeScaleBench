```python
"""
module_16.py

Community Health Aggregator for PulseStream Nexus
=================================================

This module implements an asynchronous service that consumes *validated &
enriched* social-network events from Kafka, aggregates community-level
health metrics (toxicity rate, sentiment, virality, …) in a sliding-window
fashion, and periodically pushes the resulting KPIs to:

    1. A downstream Kafka topic for further streaming consumers
    2. A Prometheus PushGateway for dashboard visualisation / alerting

Design notes
------------
• Pluggable metric calculation via the Strategy pattern
• Non-blocking I/O using asyncio + aiokafka
• Robust shutdown on SIGINT/SIGTERM with at-least-once delivery semantics
• Extensive logging & error handling suitable for production workloads
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

# ────────────────────────────────────────────────────────────────────────────────
# Optional / third-party dependencies
# ────────────────────────────────────────────────────────────────────────────────
try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
except ModuleNotFoundError:  # pragma: no cover – handled in unit tests
    AIOKafkaConsumer = None  # type: ignore
    AIOKafkaProducer = None  # type: ignore

try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
except ModuleNotFoundError:  # pragma: no cover
    CollectorRegistry = None  # type: ignore
    Gauge = None  # type: ignore
    push_to_gateway = None  # type: ignore

# ────────────────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────────────────
LOGGER = logging.getLogger("pulse.community_health_agg")
LOG_LEVEL = os.getenv("PULSE_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    stream=sys.stdout,
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)

# ────────────────────────────────────────────────────────────────────────────────
# Configuration dataclass
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AggregatorConfig:
    """
    Runtime configuration for the CommunityHealthAggregator
    """

    kafka_bootstrap_servers: str
    consumer_topic: str = "pulse.enriched"
    producer_topic: str = "pulse.community_health"
    consumer_group: str = "community_health_agg"
    window_seconds: int = 300  # 5-minute sliding window
    flush_interval: int = 15   # flush every N seconds
    prometheus_pushgateway: Optional[str] = field(
        default_factory=lambda: os.getenv("PROM_PUSHGATEWAY")
    )
    prometheus_job: str = "community_health_agg"

    @classmethod
    def from_env(cls) -> "AggregatorConfig":
        return cls(
            kafka_bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            consumer_topic=os.getenv("KAFKA_CONSUMER_TOPIC", "pulse.enriched"),
            producer_topic=os.getenv("KAFKA_PRODUCER_TOPIC", "pulse.community_health"),
            consumer_group=os.getenv("KAFKA_CONSUMER_GROUP", "community_health_agg"),
            window_seconds=int(os.getenv("WINDOW_SECONDS", "300")),
            flush_interval=int(os.getenv("FLUSH_INTERVAL", "15")),
        )


# ────────────────────────────────────────────────────────────────────────────────
# Metric Strategy Pattern
# ────────────────────────────────────────────────────────────────────────────────


class MetricStrategy(abc.ABC):
    """
    Base class for calculating a particular metric over a collection of events.
    """

    def __init__(self, window_seconds: int) -> None:
        self._window_seconds = window_seconds

    @abc.abstractmethod
    def consume(self, community_id: str, payload: Mapping[str, Any]) -> None:
        """
        Ingest a single event into the strategy’s internal state.
        """

    @abc.abstractmethod
    def snapshot(self) -> Mapping[str, Mapping[str, float]]:
        """
        Return the current metric values per community.

        Returns
        -------
        Mapping: {community_id: {metric_name: value}}
        """

    @abc.abstractmethod
    def reset(self) -> None:
        """
        Reset any time-bounded counters. Called after each flush.
        """


# ────────────────────────────────────────────────────────────────────────────────
# Concrete Strategies
# ────────────────────────────────────────────────────────────────────────────────


class ToxicityRateStrategy(MetricStrategy):
    """
    Calculates the proportion of toxic messages within the current window.
    The event payload **must** contain a pre-computed "toxicity" boolean field.
    """

    METRIC_NAME = "toxicity_rate"

    def __init__(self, window_seconds: int) -> None:
        super().__init__(window_seconds)
        self._total: MutableMapping[str, int] = defaultdict(int)
        self._toxic: MutableMapping[str, int] = defaultdict(int)

    def consume(self, community_id: str, payload: Mapping[str, Any]) -> None:
        toxic_flag = bool(payload.get("toxicity", False))
        self._total[community_id] += 1
        if toxic_flag:
            self._toxic[community_id] += 1
        LOGGER.debug(
            "ToxicityStrategy consume: community=%s toxic=%s", community_id, toxic_flag
        )

    def snapshot(self) -> Mapping[str, Mapping[str, float]]:
        result: Dict[str, Dict[str, float]] = {}
        for community, total in self._total.items():
            toxic = self._toxic.get(community, 0)
            rate = toxic / total if total else 0.0
            result[community] = {self.METRIC_NAME: rate}
        return result

    def reset(self) -> None:
        self._total.clear()
        self._toxic.clear()


class SentimentAvgStrategy(MetricStrategy):
    """
    Aggregates the average sentiment score for each community.
    Expected sentiment value range: [-1.0, 1.0]
    """

    METRIC_NAME = "sentiment_avg"

    def __init__(self, window_seconds: int) -> None:
        super().__init__(window_seconds)
        self._total_sentiment: MutableMapping[str, float] = defaultdict(float)
        self._count: MutableMapping[str, int] = defaultdict(int)

    def consume(self, community_id: str, payload: Mapping[str, Any]) -> None:
        score = float(payload.get("sentiment_score", 0.0))
        self._total_sentiment[community_id] += score
        self._count[community_id] += 1
        LOGGER.debug(
            "SentimentStrategy consume: community=%s score=%.2f", community_id, score
        )

    def snapshot(self) -> Mapping[str, Mapping[str, float]]:
        result: Dict[str, Dict[str, float]] = {}
        for community, c in self._count.items():
            avg = self._total_sentiment[community] / c if c else 0.0
            result[community] = {self.METRIC_NAME: avg}
        return result

    def reset(self) -> None:
        self._total_sentiment.clear()
        self._count.clear()


# ────────────────────────────────────────────────────────────────────────────────
# Aggregator Service
# ────────────────────────────────────────────────────────────────────────────────


class CommunityHealthAggregator:
    """
    Orchestrates metric strategies, Kafka I/O, and Prometheus integration.
    """

    def __init__(
        self,
        cfg: AggregatorConfig,
        strategies: Iterable[MetricStrategy] | None = None,
    ) -> None:
        self._cfg = cfg
        self._strategies: List[MetricStrategy] = list(strategies) if strategies else [
            ToxicityRateStrategy(cfg.window_seconds),
            SentimentAvgStrategy(cfg.window_seconds),
        ]

        # Prometheus
        self._registry = CollectorRegistry() if CollectorRegistry else None
        self._gauges: Dict[str, Gauge] = {}

        # Kafka
        if not AIOKafkaConsumer or not AIOKafkaProducer:
            LOGGER.warning(
                "aiokafka not available ‑ running in ‘dry’ mode (no Kafka I/O)."
            )
            self._consumer = None
            self._producer = None
        else:
            self._consumer = AIOKafkaConsumer(
                self._cfg.consumer_topic,
                bootstrap_servers=self._cfg.kafka_bootstrap_servers,
                group_id=self._cfg.consumer_group,
                enable_auto_commit=False,
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            )
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._cfg.kafka_bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )

        # Internal
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    # ────────────────────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Initialise resources and commence consuming.
        """
        if self._consumer and self._producer:
            await self._consumer.start()
            await self._producer.start()
        self._setup_prometheus_metrics()

        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flusher())

        # Main consume loop
        LOGGER.info("Aggregator started, awaiting events …")
        try:
            while self._running:
                if not self._consumer:  # Dry mode
                    await asyncio.sleep(1.0)
                    continue

                msg = await self._consumer.getone()
                await self._handle_message(msg.value)
                await self._consumer.commit()
        except asyncio.CancelledError:
            LOGGER.info("Consume loop cancelled")
        finally:
            await self._shutdown()

    # ────────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ────────────────────────────────────────────────────────────────────────────

    async def _handle_message(self, payload: Mapping[str, Any]) -> None:
        """
        Dispatch the incoming event to all metric strategies.
        """
        community_id = str(payload.get("community_id", "unknown"))
        for strategy in self._strategies:
            try:
                strategy.consume(community_id, payload)
            except Exception:  # pragma: no cover
                LOGGER.exception("Strategy %s failed to consume payload", strategy)

    async def _periodic_flusher(self) -> None:
        """
        Flush metrics at a fixed interval, independent of event throughput.
        """
        while self._running:
            await asyncio.sleep(self._cfg.flush_interval)
            try:
                snapshot = self._collect_snapshot()
                await self._publish_snapshot(snapshot)
                self._reset_strategies()
            except Exception:  # pragma: no cover
                LOGGER.exception("Failed during periodic flush")

    def _collect_snapshot(self) -> Mapping[str, Mapping[str, float]]:
        """
        Merge snapshots from all strategies into a single structure.
        """
        merged: Dict[str, Dict[str, float]] = defaultdict(dict)
        for strat in self._strategies:
            snap = strat.snapshot()
            for community, metrics in snap.items():
                merged[community].update(metrics)
        LOGGER.debug("Collected snapshot: %s", merged)
        return merged

    async def _publish_snapshot(self, data: Mapping[str, Mapping[str, float]]) -> None:
        """
        Publish metrics to Kafka and Prometheus.
        """
        timestamp = time.time()
        for community, metrics in data.items():
            record = {
                "community_id": community,
                "timestamp": timestamp,
                "metrics": metrics,
            }

            # Kafka
            if self._producer:
                await self._producer.send_and_wait(
                    self._cfg.producer_topic,
                    record,
                    key=community.encode("utf-8"),
                )

            # Prometheus
            if self._registry:
                for metric_name, value in metrics.items():
                    gauge = self._gauges.get(metric_name)
                    if not gauge:  # dynamically create Gauge
                        gauge = Gauge(
                            metric_name,
                            f"{metric_name} computed by CommunityHealthAggregator",
                            labelnames=("community_id",),
                            registry=self._registry,
                        )
                        self._gauges[metric_name] = gauge
                    gauge.labels(community_id=community).set(value)

        # PushGateway
        if (
            self._cfg.prometheus_pushgateway
            and push_to_gateway
            and self._registry
            and self._gauges
        ):
            push_to_gateway(
                self._cfg.prometheus_pushgateway,
                job=self._cfg.prometheus_job,
                registry=self._registry,
            )
        LOGGER.info("Published snapshot for %d communities", len(data))

    def _reset_strategies(self) -> None:
        for strat in self._strategies:
            strat.reset()

    async def _shutdown(self) -> None:
        """
        Close Kafka connections and cancel background tasks.
        """
        LOGGER.info("Shutting down gracefully…")
        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()
        LOGGER.info("Shutdown complete")

    # ────────────────────────────────────────────────────────────────────────────
    # Prometheus helpers
    # ────────────────────────────────────────────────────────────────────────────

    def _setup_prometheus_metrics(self) -> None:
        if not self._registry:
            LOGGER.warning("prometheus_client not installed ‑ metrics disabled")
            return
        # Gauges will be created dynamically when first used.


# ────────────────────────────────────────────────────────────────────────────────
# Entrypoint util
# ────────────────────────────────────────────────────────────────────────────────
import contextlib  # pylint: disable=wrong-import-position


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_cb) -> None:
    """
    Register SIGTERM / SIGINT to trigger coroutine *stop_cb* once.
    """

    def _handler(sig):  # noqa: D401
        LOGGER.info("Received %s, initiating shutdown", sig.name)
        loop.create_task(stop_cb())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handler, sig)


async def _run_service() -> None:
    cfg = AggregatorConfig.from_env()
    aggregator = CommunityHealthAggregator(cfg)

    async def _stop() -> None:
        aggregator._running = False  # pylint: disable=protected-access

    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop, _stop)
    await aggregator.start()


def main() -> None:  # pragma: no cover
    """
    CLI entrypoint for `python -m module_16`
    """
    try:
        asyncio.run(_run_service())
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt ‑ exiting")


if __name__ == "__main__":  # pragma: no cover
    main()
```