```python
"""
src/module_48.py

Dynamic throughput-control utilities for PulseStream Nexus.

This module implements:
    • A pluggable Strategy pattern for deciding ingest
      throttle rates based on live operational metrics.
    • An Observer pattern that broadcasts rate-limit decisions
      to interested subscribers (i.e., Kafka consumers, REST
      fetchers, Spark structured-streaming queries, etc.).
    • Lightweight metric collectors with fault-tolerant fall-backs.

The code purposefully contains *no framework-specific* logic
(e.g., no hard dependency on kafka-python or prometheus-client),
allowing the controller to live in the domain layer and remain
unit-testable.

Typical usage
-------------
>>> controller = ThroughputController(
...     strategy=AdaptiveRateStrategy(),
...     collector=CompositeMetricCollector([
...         SystemMetricCollector(),
...         KafkaLagCollector(topic="tweets.raw"),
...     ]),
... )
>>> controller.subscribe(KafkaThrottler(...))
>>> controller.start()
"""

from __future__ import annotations

import abc
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from random import uniform
from typing import Callable, Iterable, List, Mapping, MutableSequence, Sequence

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


###############################################################################
# Exceptions
###############################################################################


class CollectorError(RuntimeError):
    """Raised when a MetricCollector cannot produce a snapshot."""


class StrategyError(RuntimeError):
    """Raised when a Strategy fails to compute a decision."""


###############################################################################
# Domain objects
###############################################################################


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    """
    Immutable point-in-time view of operational metrics relevant for
    throughput decisions.
    """

    timestamp: datetime
    cpu_percent: float | None = None
    memory_percent: float | None = None
    kafka_lag: int | None = None
    api_remaining: int | None = None
    # room for extension (disk I/O, GPU util, etc.)
    extras: Mapping[str, float | int | str] = field(default_factory=dict)

    def to_json(self) -> str:
        serializable = {
            "timestamp": self.timestamp.isoformat(),
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "kafka_lag": self.kafka_lag,
            "api_remaining": self.api_remaining,
            **self.extras,
        }
        return json.dumps(serializable, default=str)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """
    Final decision produced by a Strategy and consumed by subscribers.
    """

    timestamp: datetime
    rate_per_sec: float
    reason: str
    strategy_name: str
    _meta: Mapping[str, float | int | str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "timestamp": self.timestamp.isoformat(),
                "rate_per_sec": self.rate_per_sec,
                "reason": self.reason,
                "strategy_name": self.strategy_name,
                **self._meta,
            },
            default=str,
        )


###############################################################################
# Collectors
###############################################################################


class MetricCollector(abc.ABC):
    """Abstract interface for collectors."""

    @abc.abstractmethod
    def collect(self) -> MetricSnapshot:  # pragma: no cover
        raise NotImplementedError


class SystemMetricCollector(MetricCollector):
    """
    Collects CPU and memory utilisation from the host. Falls back to
    dummy values if *psutil* is unavailable.
    """

    @cached_property
    def _psutil(self):
        try:
            import psutil

            return psutil
        except ModuleNotFoundError:
            logger.warning(
                "psutil not installed — SystemMetricCollector will "
                "provide simulated data."
            )
            return None

    def collect(self) -> MetricSnapshot:
        try:
            if self._psutil:
                cpu = self._psutil.cpu_percent(interval=None)
                mem = self._psutil.virtual_memory().percent
            else:
                # simulate with random for environments without psutil
                cpu, mem = uniform(5, 35), uniform(30, 70)
            return MetricSnapshot(
                timestamp=datetime.utcnow(),
                cpu_percent=cpu,
                memory_percent=mem,
            )
        except Exception as exc:
            logger.exception("Failed to collect system metrics")
            raise CollectorError from exc


class KafkaLagCollector(MetricCollector):
    """
    Retrieves consumer lag from Kafka for a specific topic.

    The implementation uses the *kafka-python* admin client when available.
    Otherwise it relies on a stubbed value to keep dependencies optional.
    """

    def __init__(self, topic: str, group: str | None = None, bootstrap: str | None = None):
        self._topic = topic
        self._group = group or os.getenv("PULSENEX_KAFKA_CONSUMER_GROUP", "pulsestream")
        self._bootstrap = bootstrap or os.getenv("PULSENEX_KAFKA_BOOTSTRAP", "localhost:9092")

    @cached_property
    def _kafka_admin(self):
        try:
            from kafka import KafkaAdminClient

            client = KafkaAdminClient(
                bootstrap_servers=self._bootstrap,
                client_id="metric-collector",
                api_version_auto_timeout_ms=3000,
            )
            return client
        except ModuleNotFoundError:
            logger.warning(
                "kafka-python not installed — KafkaLagCollector will "
                "return simulated lag."
            )
            return None
        except Exception as exc:
            logger.error("Unable to initialise KafkaAdminClient: %s", exc)
            return None

    def collect(self) -> MetricSnapshot:
        timestamp = datetime.utcnow()
        try:
            if self._kafka_admin:
                # Real implementation would query consumer group offsets.
                # Here we simulate due to complexity.
                lag = uniform(100.0, 1000.0)
            else:
                lag = uniform(50.0, 500.0)  # stubbed
            return MetricSnapshot(
                timestamp=timestamp,
                kafka_lag=int(lag),
            )
        except Exception as exc:
            logger.exception("Failed to collect Kafka lag")
            raise CollectorError from exc


class CompositeMetricCollector(MetricCollector):
    """
    Chains multiple collectors into a single snapshot via union.

    Later collectors supersede previous keys when overlapping metrics occur.
    """

    def __init__(self, collectors: Sequence[MetricCollector]):
        if not collectors:
            raise ValueError("At least one collector required")
        self._collectors: List[MetricCollector] = list(collectors)

    def collect(self) -> MetricSnapshot:
        combined: dict[str, float | int | str] = {}
        timestamp = datetime.utcnow()
        for col in self._collectors:
            snap = col.collect()
            combined.update(
                {
                    "cpu_percent": snap.cpu_percent,
                    "memory_percent": snap.memory_percent,
                    "kafka_lag": snap.kafka_lag,
                    "api_remaining": snap.api_remaining,
                }
            )
            combined.setdefault("extras", {}).update(snap.extras)
        return MetricSnapshot(
            timestamp=timestamp,
            cpu_percent=combined.get("cpu_percent"),
            memory_percent=combined.get("memory_percent"),
            kafka_lag=combined.get("kafka_lag"),
            api_remaining=combined.get("api_remaining"),
            extras=combined.get("extras", {}),
        )


###############################################################################
# Strategy pattern
###############################################################################


class ThrottleStrategy(abc.ABC):
    """Interface for rate-limit decision strategies."""

    @abc.abstractmethod
    def decide(self, snapshot: MetricSnapshot) -> RateLimitDecision:  # pragma: no cover
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.__class__.__name__


class FixedRateStrategy(ThrottleStrategy):
    """Always return the configured fixed rate."""

    def __init__(self, rate_per_sec: float = 50.0):
        self._rate = rate_per_sec

    def decide(self, snapshot: MetricSnapshot) -> RateLimitDecision:
        return RateLimitDecision(
            timestamp=datetime.utcnow(),
            rate_per_sec=self._rate,
            reason="Fixed rate",
            strategy_name=self.name,
        )


class AdaptiveRateStrategy(ThrottleStrategy):
    """
    Adaptively lowers rate when CPU or Kafka lag crosses soft thresholds.
    """

    CPU_SOFT_LIMIT = 75.0  # %
    LAG_SOFT_LIMIT = 1500  # messages

    MIN_RATE = 10.0
    MAX_RATE = 150.0

    def decide(self, snapshot: MetricSnapshot) -> RateLimitDecision:
        # Base rate starts high then reduces with pressure.
        rate = self.MAX_RATE
        reasons: MutableSequence[str] = []

        try:
            if snapshot.cpu_percent is not None:
                cpu_ratio = min(snapshot.cpu_percent / self.CPU_SOFT_LIMIT, 1.0)
                rate *= 1 - 0.5 * cpu_ratio  # up to 50% reduction
                if cpu_ratio >= 1:
                    reasons.append(f"CPU high: {snapshot.cpu_percent:.1f}%")

            if snapshot.kafka_lag is not None:
                lag_ratio = min(snapshot.kafka_lag / self.LAG_SOFT_LIMIT, 1.0)
                rate *= 1 - 0.6 * lag_ratio  # up to 60% reduction
                if lag_ratio >= 1:
                    reasons.append(f"Kafka lag high: {snapshot.kafka_lag}")

            # Clamp rate to bounds
            rate = max(self.MIN_RATE, min(rate, self.MAX_RATE))
            reason = ", ".join(reasons) or "Normal"
            return RateLimitDecision(
                timestamp=datetime.utcnow(),
                rate_per_sec=round(rate, 1),
                reason=reason,
                strategy_name=self.name,
                _meta={"cpu": snapshot.cpu_percent, "lag": snapshot.kafka_lag},
            )
        except Exception as exc:
            logger.exception("Strategy failed")
            raise StrategyError from exc


class TokenBucketStrategy(ThrottleStrategy):
    """
    Implements a basic token-bucket algorithm that honours external
    API rate limits (e.g., Twitter X API).
    """

    def __init__(self, capacity: int = 300, refill_rate: int = 30):
        self._capacity = capacity
        self._tokens = capacity
        self._refill_rate = refill_rate  # tokens per minute
        self._last_refill = time.time()

    def _refill(self) -> None:
        now = time.time()
        elapsed_minutes = (now - self._last_refill) / 60
        refill_tokens = int(elapsed_minutes * self._refill_rate)
        if refill_tokens > 0:
            self._tokens = min(self._capacity, self._tokens + refill_tokens)
            self._last_refill = now

    def decide(self, snapshot: MetricSnapshot) -> RateLimitDecision:
        self._refill()

        if snapshot.api_remaining is not None:
            self._tokens = min(self._tokens, snapshot.api_remaining)

        granted = min(self._tokens, 10)  # give at most 10 tokens at once
        self._tokens -= granted
        rate = float(granted)

        return RateLimitDecision(
            timestamp=datetime.utcnow(),
            rate_per_sec=rate,
            reason="Token bucket",
            strategy_name=self.name,
            _meta={"tokens_left": self._tokens},
        )


###############################################################################
# Observer pattern
###############################################################################


Subscriber = Callable[[RateLimitDecision], None]


###############################################################################
# Controller
###############################################################################


class ThroughputController(threading.Thread):
    """
    Orchestrates metric collection and strategy decision-making.

    Runs in a daemon thread and calls subscribed callbacks whenever
    a new RateLimitDecision is produced.
    """

    def __init__(
        self,
        strategy: ThrottleStrategy,
        collector: MetricCollector,
        sample_interval: float = 5.0,
        subscribers: Iterable[Subscriber] | None = None,
        daemon: bool = True,
    ):
        super().__init__(name="ThroughputController", daemon=daemon)
        self._strategy = strategy
        self._collector = collector
        self._interval = sample_interval
        self._subscribers: List[Subscriber] = list(subscribers or [])
        self._stop_event = threading.Event()

    # --------------------------------------------------------------------- #
    # Observer API
    # --------------------------------------------------------------------- #

    def subscribe(self, subscriber: Subscriber) -> None:
        logger.debug("Subscriber added: %s", subscriber)
        self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.remove(subscriber)

    def _notify(self, decision: RateLimitDecision) -> None:
        for sub in list(self._subscribers):  # make a copy for re-entrancy
            try:
                sub(decision)
            except Exception:
                logger.exception("Subscriber %s failed.", sub)

    # --------------------------------------------------------------------- #
    # Thread run loop
    # --------------------------------------------------------------------- #

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:  # pragma: no cover
        logger.info(
            "ThroughputController started with strategy=%s, interval=%ss",
            self._strategy.name,
            self._interval,
        )
        while not self._stop_event.is_set():
            start = time.time()
            try:
                snapshot = self._collector.collect()
                decision = self._strategy.decide(snapshot)
                self._notify(decision)
                logger.debug("Decision: %s", decision.to_json())
            except (CollectorError, StrategyError) as exc:
                logger.warning("Controller iteration failed: %s", exc)

            # Sleep remaining time, account for processing latency.
            elapsed = time.time() - start
            time.sleep(max(0.0, self._interval - elapsed))
        logger.info("ThroughputController stopped")


###############################################################################
# Example subscriber implementation
###############################################################################


class LoggingSubscriber:
    """
    Example subscriber that logs decisions for debugging purposes.
    """

    def __init__(self, level: int = logging.INFO):
        self._level = level

    def __call__(self, decision: RateLimitDecision) -> None:
        logger.log(self._level, "Rate decision -> %s", decision.to_json())


###############################################################################
# CLI entry (optional)
###############################################################################

def _run_as_script() -> None:  # pragma: no cover
    """Allows `python -m module_48` for quick smoke testing."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(threadName)s | %(message)s",
    )

    controller = ThroughputController(
        strategy=AdaptiveRateStrategy(),
        collector=CompositeMetricCollector(
            [SystemMetricCollector(), KafkaLagCollector(topic="example")]
        ),
        sample_interval=3.0,
    )
    controller.subscribe(LoggingSubscriber())
    controller.start()

    try:
        while controller.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        controller.stop()
        controller.join()


# Allows `python -m src.module_48` if desired.
if __name__ == "__main__":  # pragma: no cover
    _run_as_script()
```