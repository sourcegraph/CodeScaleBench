```python
"""
PulseStream Nexus – Stream Health Monitor & Dynamic Throttling
==============================================================

Module overview
---------------
`module_9` implements an asynchronous service that continuously gauges the
health of PulseStream Nexus Kafka topics and dynamically throttles the
associated consumer groups when anomalies (lag, error-rate spikes, CPU / memory
saturation, etc.) are detected.

Clean-architecture wise, this module is considered an _infrastructure adapter_.
It orchestrates:

1. Metric acquisition
   • Prometheus HTTP API for node / JVM / application counters
   • Kafka AdminClient for consumer-group lag

2. Policy evaluation
   • Strategy-pattern based throttling policies (e.g., *Static*, *PID*)

3. Actuation
   • Kafka AdminClient to alter `max.poll.records`
   • Pause / resume partitions through `aiokafka` (when running side-by-side)

Key design goals
----------------
• Fully asynchronous (leverages `asyncio`)
• Pluggable strategies (easy A/B testing of throttling algorithms)
• Production safety (circuit-breakers, exponential back-off, graceful shutdown)

External dependencies
---------------------
• requests                (HTTP calls to Prometheus)
• kafka-python            (Admin operations) *or* confluent-kafka
• aiokafka                (optional; for run-time pausing)
All imports are wrapped in try/except blocks to degrade gracefully when a
dependency is missing. In production, **pin exact versions** in `pyproject.toml`.

Author
------
PulseStream Nexus core team
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Protocol, Tuple

try:
    # Lightweight admin interface (will internally use a thread pool)
    from kafka import KafkaAdminClient, KafkaConsumer
    from kafka.errors import KafkaError
except ModuleNotFoundError:  # pragma: no cover
    KafkaAdminClient = None  # type: ignore
    KafkaConsumer = None  # type: ignore
    KafkaError = Exception  # type: ignore

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover
    requests = None  # type: ignore

__all__ = [
    "StreamMetrics",
    "PrometheusMetricsClient",
    "KafkaLagFetcher",
    "ThrottlingStrategy",
    "StaticThrottlingStrategy",
    "PIDThrottlingStrategy",
    "ThrottlingController",
    "StreamHealthMonitor",
    "main",
]

_LOGGER = logging.getLogger("pulse.mon.monitor")
_LOGGER.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(
    logging.Formatter(
        "[%(levelname)s] %(asctime)s - %(name)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )
)
_LOGGER.addHandler(_handler)

###############################################################################
#                   D A T A   &   V A L U E   O B J E C T S                   #
###############################################################################


@dataclass(frozen=True, slots=True)
class StreamMetrics:
    """
    Immutable container for the current KPI snapshot of a Kafka consumer group.
    """

    consumer_group: str
    topic: str
    partition_lag: Dict[int, int]
    total_lag: int
    error_rate: float  # errors / sec
    throughput: float  # messages / sec
    cpu_pct: float  # host CPU %
    mem_pct: float  # host Memory %
    ts: datetime

    def is_healthy(self, lag_threshold: int, err_threshold: float) -> bool:
        """
        Quick heuristic to determine if the stream is OK.
        """
        return self.total_lag < lag_threshold and self.error_rate < err_threshold


###############################################################################
#                        P R O M E T H E U S   C L I E N T                     #
###############################################################################


class PrometheusMetricsClient:
    """
    Lightweight client for Prometheus HTTP API.

    Only the `/api/v1/query` endpoint is used, which keeps things simple while
    still powerful enough for single-vector queries.
    """

    def __init__(self, base_url: str, session: Optional[requests.Session] = None):
        if requests is None:
            raise RuntimeError("Prometheus client requested but 'requests' missing.")

        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = (2, 5)  # connect, read seconds

    def _query(self, expr: str) -> float:
        """
        Fire an instant PromQL query and return the first numeric value.

        Raises RuntimeError if Prometheus returns an error or no data.
        """
        params = {"query": expr}
        url = f"{self._base_url}/api/v1/query"
        _LOGGER.debug("Prometheus query: %s", expr)
        resp = self._session.get(url, params=params, timeout=self._timeout)
        if not resp.ok:
            raise RuntimeError(
                f"Prometheus error [{resp.status_code}]: {resp.text[:200]}"
            )
        data = resp.json()
        if data.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {json.dumps(data)[:200]}")
        try:
            value = float(data["data"]["result"][0]["value"][1])
        except (IndexError, KeyError, ValueError) as exc:
            raise RuntimeError(
                f"No numeric data for expression '{expr}': {json.dumps(data)[:200]}"
            ) from exc
        return value

    # --------------------------------------------------------------------- #
    # Public metric helpers                                                 #
    # --------------------------------------------------------------------- #

    def get_error_rate(self, service: str) -> float:
        expr = f"rate({service}_error_total[1m])"
        return self._query(expr)

    def get_throughput(self, service: str) -> float:
        expr = f"rate({service}_ingest_total[1m])"
        return self._query(expr)

    def get_cpu_pct(self, instance: str) -> float:
        expr = (
            f"100 - (avg by(instance)(irate(node_cpu_seconds_total"
            f"{{mode='idle',instance='{instance}'}}[1m])) * 100)"
        )
        return self._query(expr)

    def get_mem_pct(self, instance: str) -> float:
        expr = (
            f"(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)"
            f"/ node_memory_MemTotal_bytes * 100"
            f"{{instance='{instance}'}}"
        )
        return self._query(expr)


###############################################################################
#                             K A F K A   L A G                               #
###############################################################################


class KafkaLagFetcher:
    """
    Thin wrapper around Kafka Admin API for computing consumer-group lag.
    """

    def __init__(self, bootstrap_servers: str, timeout_ms: int = 3000):
        if KafkaAdminClient is None:
            raise RuntimeError(
                "KafkaLagFetcher requires 'kafka-python' or 'confluent-kafka'."
            )
        self._bootstrap_servers = bootstrap_servers
        self._timeout_ms = timeout_ms
        self._admin = KafkaAdminClient(
            bootstrap_servers=bootstrap_servers, request_timeout_ms=timeout_ms
        )

    # --------------------------------------------------------------------- #
    # Helpers                                                               #
    # --------------------------------------------------------------------- #

    @staticmethod
    def _get_end_offsets(
        consumer: KafkaConsumer, topic: str
    ) -> Dict[int, int]:  # pragma: no cover (network)
        """
        Using a *temporary* consumer object (lightweight) to fetch last offsets.
        """
        partitions = consumer.partitions_for_topic(topic)
        if not partitions:
            return {}
        tpl = [TopicPartition(topic, p) for p in partitions]  # type: ignore
        end_offsets = consumer.end_offsets(tpl, timeout=5.0)  # type: ignore
        return {tp.partition: offset for tp, offset in end_offsets.items()}

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def lag_per_partition(
        self, topic: str, consumer_group: str
    ) -> Tuple[Dict[int, int], int]:
        """
        Returns (partition_lag_map, total_lag).
        """
        try:
            # 1) Consumer group offsets
            desc = self._admin.list_consumer_group_offsets(
                group_id=consumer_group, timeout=self._timeout_ms / 1000.0
            )
            current_offsets = {
                p.partition: o
                for p, o in desc.items()
                if p.topic == topic and o is not None
            }

            # 2) Latest offsets
            consumer = KafkaConsumer(
                bootstrap_servers=self._bootstrap_servers,
                enable_auto_commit=False,
                group_id=None,
            )
            latest_offsets = self._get_end_offsets(consumer, topic)
            consumer.close()

            lag_map = {
                p: max(latest_offsets.get(p, 0) - current_offsets.get(p, 0), 0)
                for p in latest_offsets
            }
            total = sum(lag_map.values())
            return lag_map, total
        except KafkaError as exc:  # pragma: no cover
            _LOGGER.exception("Kafka error while computing lag: %s", exc)
            return {}, -1


###############################################################################
#                        T H R O T T L I N G   P O L I C Y                    #
###############################################################################


class ThrottlingStrategy(Protocol):
    """
    Strategy interface; input = current metrics, output = desired poll size.
    """

    async def propose(self, metrics: StreamMetrics) -> int: ...


class StaticThrottlingStrategy:
    """
    Fixed poll size. Useful for smoke testing or as a fallback.
    """

    def __init__(self, fixed_size: int = 500):
        self._fixed_size = fixed_size

    async def propose(self, metrics: StreamMetrics) -> int:
        return self._fixed_size


class PIDThrottlingStrategy:
    """
    Classic PID controller to smooth lag fluctuations.

    The controller tries to keep `total_lag` around `setpoint`.
    """

    def __init__(
        self,
        setpoint: int = 5_000,
        kp: float = 0.2,
        ki: float = 0.05,
        kd: float = 0.1,
        window: int = 30,
        min_poll: int = 50,
        max_poll: int = 5_000,
    ):
        self._setpoint = setpoint
        self._kp = kp
        self._ki = ki
        self._kd = kd
        self._window = window
        self._min_poll = min_poll
        self._max_poll = max_poll

        self._prev_error: Optional[float] = None
        self._integral = 0.0

    async def propose(self, metrics: StreamMetrics) -> int:
        error = self._setpoint - metrics.total_lag
        self._integral += error
        derivative = 0.0 if self._prev_error is None else error - self._prev_error
        self._prev_error = error

        output = (
            self._kp * error
            + self._ki * self._integral
            + self._kd * derivative / max(1, self._window)
        )
        poll_size = int(
            max(self._min_poll, min(self._max_poll, self._setpoint + output))
        )
        _LOGGER.debug(
            "PID propose: error=%s, integral=%s, derivative=%s, poll=%s",
            error,
            self._integral,
            derivative,
            poll_size,
        )
        return poll_size


###############################################################################
#                         T H R O T T L I N G   A C T O R                     #
###############################################################################


class ThrottlingController:
    """
    Applies the desired `max.poll.records` to the consumer group at run-time.
    """

    def __init__(self, bootstrap_servers: str):
        if KafkaAdminClient is None:
            raise RuntimeError("'kafka-python' is required for throttling.")
        self._bootstrap_servers = bootstrap_servers
        self._admin = KafkaAdminClient(bootstrap_servers=bootstrap_servers)

    async def apply(self, consumer_group: str, poll_size: int) -> None:
        """
        Update a consumer-group configuration.

        Because Kafka doesn't allow dynamic tuning of `max.poll.records` on an
        **existing** client session, the recommended approach is:

        1. Write to the _static_ config (affects next restart)
        2. Broadcast control message to live consumers (if they support it)

        Here we do #1 to keep the demo tangible.
        """
        _LOGGER.info(
            "Applying poll_size=%s to consumer_group=%s", poll_size, consumer_group
        )
        try:
            self._admin.alter_consumer_group_configs(
                configs={
                    (consumer_group, "max.poll.records"): str(poll_size),
                }
            )
        except KafkaError as exc:  # pragma: no cover
            _LOGGER.exception("Failed to update consumer group config: %s", exc)


###############################################################################
#                       S T R E A M   H E A L T H   L O O P                   #
###############################################################################


class StreamHealthMonitor:
    """
    Top-level coordinator that periodically collects metrics, runs the chosen
    policy, and triggers the controller.
    """

    def __init__(
        self,
        *,
        topic: str,
        consumer_group: str,
        prometheus_url: str,
        kafka_bootstrap: str,
        prometheus_service: str,
        host_instance: str,
        period_sec: int = 15,
        lag_threshold: int = 20_000,
        err_threshold: float = 1.0,
        strategy: ThrottlingStrategy | None = None,
    ):
        self._topic = topic
        self._consumer_group = consumer_group
        self._period = period_sec
        self._lag_threshold = lag_threshold
        self._err_threshold = err_threshold
        self._strategy = strategy or StaticThrottlingStrategy(500)

        self._prom = PrometheusMetricsClient(prometheus_url)
        self._lag_fetcher = KafkaLagFetcher(kafka_bootstrap)
        self._controller = ThrottlingController(kafka_bootstrap)

        self._prom_service = prometheus_service
        self._instance = host_instance
        self._task: Optional[asyncio.Task[None]] = None
        self._shutdown_event = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Metrics Acquisition                                                #
    # ------------------------------------------------------------------ #

    async def _gather_metrics(self) -> StreamMetrics:
        loop = asyncio.get_running_loop()

        lag_map, total_lag = await loop.run_in_executor(
            None, self._lag_fetcher.lag_per_partition, self._topic, self._consumer_group
        )

        # Run Prometheus queries in threadpool to avoid blocking
        def _prom(fn, *args):
            return fn(*args)

        error_rate = await loop.run_in_executor(
            None,
            _prom,
            self._prom.get_error_rate,
            self._prom_service,
        )
        throughput = await loop.run_in_executor(
            None,
            _prom,
            self._prom.get_throughput,
            self._prom_service,
        )
        cpu_pct = await loop.run_in_executor(
            None, _prom, self._prom.get_cpu_pct, self._instance
        )
        mem_pct = await loop.run_in_executor(
            None, _prom, self._prom.get_mem_pct, self._instance
        )

        return StreamMetrics(
            consumer_group=self._consumer_group,
            topic=self._topic,
            partition_lag=lag_map,
            total_lag=total_lag,
            error_rate=error_rate,
            throughput=throughput,
            cpu_pct=cpu_pct,
            mem_pct=mem_pct,
            ts=datetime.utcnow(),
        )

    # ------------------------------------------------------------------ #
    # Control Loop                                                       #
    # ------------------------------------------------------------------ #

    async def _control_loop(self) -> None:
        jitter_range = min(3, self._period // 3)  # avoid thundering herd
        _LOGGER.info(
            "🚀 Starting StreamHealthMonitor for (%s/%s) period=%ss",
            self._topic,
            self._consumer_group,
            self._period,
        )
        try:
            while not self._shutdown_event.is_set():
                started = time.time()
                metrics = await self._gather_metrics()
                _LOGGER.info(
                    "Metrics@%s lag=%s err/s=%.2f thr/s=%.1f cpu=%.1f%% mem=%.1f%%",
                    metrics.ts.isoformat(),
                    metrics.total_lag,
                    metrics.error_rate,
                    metrics.throughput,
                    metrics.cpu_pct,
                    metrics.mem_pct,
                )

                # Health evaluation
                if not metrics.is_healthy(self._lag_threshold, self._err_threshold):
                    _LOGGER.warning(
                        "Health degraded! lag=%s (th=%s) err=%.2f (th=%.2f)",
                        metrics.total_lag,
                        self._lag_threshold,
                        metrics.error_rate,
                        self._err_threshold,
                    )

                # Policy -> target poll size
                poll_size = await self._strategy.propose(metrics)
                await self._controller.apply(self._consumer_group, poll_size)

                # Sleep with jitter
                elapsed = time.time() - started
                to_sleep = max(
                    0.0,
                    self._period
                    - elapsed
                    + random.uniform(-jitter_range, jitter_range),
                )
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=to_sleep)
        except asyncio.CancelledError:
            _LOGGER.info("Health monitor cancelled.")
        finally:
            _LOGGER.info("StreamHealthMonitor stopped.")

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._task and not self._task.done():
            _LOGGER.warning("Monitor already running.")
            return
        self._task = asyncio.create_task(self._control_loop())

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._task:
            await self._task

    async def __aenter__(self) -> "StreamHealthMonitor":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401
        await self.stop()


###############################################################################
#                               E N T R Y P O I N T                           #
###############################################################################


async def _run() -> None:  # pragma: no cover
    """
    Local development runner:

        poetry run python -m src.module_9
    """
    monitor = StreamHealthMonitor(
        topic=os.getenv("TOPIC", "social-events"),
        consumer_group=os.getenv("CONSUMER_GRP", "nexus-stream"),
        prometheus_url=os.getenv("PROM_URL", "http://localhost:9090"),
        kafka_bootstrap=os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
        prometheus_service=os.getenv("PROM_SERVICE", "nexus_ingestor"),
        host_instance=os.getenv("NODE_INSTANCE", "localhost:9100"),
        strategy=PIDThrottlingStrategy(),
        period_sec=int(os.getenv("PERIOD_SEC", "15")),
    )
    async with monitor:
        await monitor._task  # type: ignore[attr-defined]


def main() -> None:  # pragma: no cover
    """
    Blocking wrapper so we can `python -m src.module_9` easily.
    """
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        _LOGGER.info("Keyboard interrupt -> shutting down.")


if __name__ == "__main__":  # pragma: no cover
    main()
```