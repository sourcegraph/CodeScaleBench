```python
"""
PulseStream Nexus – Data-Streaming Platform
-------------------------------------------

module_44.py  –  Virality Scoring Engine
========================================
This module implements an asyncio-driven, strategy-based virality scoring engine
capable of ingesting heterogeneous social-network events in near-real-time.
Scores are computed with pluggable strategies (one per provider) and exposed
via Prometheus gauges for operational monitoring.  The module is entirely
framework-agnostic and can therefore be wired into any I/O layer (Kafka
consumer, HTTP web-hook, etc.) without modification.

Clean-Architecture Layer
------------------------
Entities       → Event, ViralityScore
Use-Cases      → ViralityEngine
Interface/IO   →  *left to composition root*
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from datetime import datetime, timedelta
from enum import Enum
from statistics import mean
from typing import Callable, Deque, Dict, List, MutableMapping, Optional, Protocol, Tuple, Type

from pydantic import BaseModel, Field, ValidationError, root_validator
from prometheus_client import Gauge, start_http_server

# ---------------------------------------------------------------------------#
# Logging Configuration
# ---------------------------------------------------------------------------#

logger = logging.getLogger("pulsestream.virality")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d | %(message)s"
    )
)
logger.addHandler(_handler)


# ---------------------------------------------------------------------------#
# Entities
# ---------------------------------------------------------------------------#


class Network(str, Enum):
    """Supported social-network providers"""

    TWITTER = "twitter"
    REDDIT = "reddit"
    MASTODON = "mastodon"
    DISCORD = "discord"
    UNKNOWN = "unknown"


class Event(BaseModel):
    """
    Canonical social event envelop used internally by PulseStream Nexus.
    Pydantic is employed here strictly for validation—no I/O leaks.
    """

    network: Network
    event_id: str = Field(..., description="Provider-specific event identifier")
    user_id: str = Field(..., description="Originating user identifier")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="UTC timestamp emitted by source"
    )
    reactions: int = Field(ge=0, description="Total # of reactions (likes/upvotes)")
    replies: int = Field(ge=0, description="# of direct replies/comments")
    reposts: int = Field(ge=0, description="# of shares/retweets/etc.")
    # Additional raw payload omitted for brevity

    @root_validator(pre=True)
    def ensure_network(cls, values):  # noqa: D401
        """Ensure that a network enum instance is produced from raw string(s)."""
        n = values.get("network", Network.UNKNOWN)
        if not isinstance(n, Network):
            try:
                values["network"] = Network(str(n).lower())
            except ValueError:
                values["network"] = Network.UNKNOWN
        return values


class ViralityScore(BaseModel):
    """Calculated virality score for a single event."""

    event_id: str
    score: float
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------#
# Strategy Pattern – Virality Scoring
# ---------------------------------------------------------------------------#


class ViralityStrategy(Protocol):
    """
    Strategy interface for computing virality scores.

    Implementations **must** be idempotent and thread-safe.
    """

    @staticmethod
    @abstractmethod
    def compute(event: Event) -> float:  # pragma: no cover
        """Return a virality score in the interval [0, ∞)."""


class TwitterViralityStrategy:
    """Twitter/X specific virality heuristics."""

    @staticmethod
    def compute(event: Event) -> float:
        weight_reactions = 1.0
        weight_replies = 2.0
        weight_reposts = 2.5
        freshness_penalty = _age_penalty(event.timestamp)

        score = (
            weight_reactions * event.reactions
            + weight_replies * event.replies
            + weight_reposts * event.reposts
        ) * freshness_penalty

        logger.debug("Twitter strategy computed %.3f for %s", score, event.event_id)
        return score


class RedditViralityStrategy:
    """Reddit specific virality heuristics."""

    @staticmethod
    def compute(event: Event) -> float:
        # Reddit upvotes & comments behave differently; treat comments heavier
        weight_reactions = 0.8
        weight_replies = 2.2
        weight_reposts = 0.4  # crossposts not as common
        freshness_penalty = _age_penalty(event.timestamp)

        score = (
            weight_reactions * event.reactions
            + weight_replies * event.replies
            + weight_reposts * event.reposts
        ) * freshness_penalty

        logger.debug("Reddit strategy computed %.3f for %s", score, event.event_id)
        return score


class GenericViralityStrategy:
    """Fallback strategy for unknown providers."""

    @staticmethod
    def compute(event: Event) -> float:
        # Simple aggregate w/ mild penalty
        freshness_penalty = _age_penalty(event.timestamp)

        score = (event.reactions + event.replies + event.reposts) * freshness_penalty
        logger.debug("Generic strategy computed %.3f for %s", score, event.event_id)
        return score


STRATEGY_REGISTRY: Dict[Network, Type[ViralityStrategy]] = {
    Network.TWITTER: TwitterViralityStrategy,
    Network.REDDIT: RedditViralityStrategy,
    Network.UNKNOWN: GenericViralityStrategy,
    # Extend via plugin system if necessary
}


def _age_penalty(ts: datetime) -> float:
    """
    Apply an exponential decay based on the age of the event.
    0–5 min  -> 1.0
    5–60 min -> down to 0.5
    >60 min  -> asymptotically approaches 0
    """
    delta = datetime.utcnow() - ts
    minutes = delta.total_seconds() / 60.0
    if minutes <= 5:
        return 1.0
    elif minutes <= 60:
        return max(0.5, 1.0 - (minutes - 5) / 110)  # linear slope to 0.5 at 60 min
    else:
        # exponential decay beyond an hour
        return 0.5 * 0.8 ** (minutes - 60)


# ---------------------------------------------------------------------------#
# Use-Case – Virality Engine
# ---------------------------------------------------------------------------#


class ViralityEngine:
    """
    High-level orchestrator that converts events into scores and maintains
    sliding-window aggregation for downstream consumers.
    """

    DEFAULT_WINDOW = timedelta(minutes=5)

    def __init__(
        self,
        *,
        window: timedelta | None = None,
        retention_limit: int = 10_000,
        metrics_port: int = 9102,
    ) -> None:
        self.window: timedelta = window or self.DEFAULT_WINDOW
        self._scores: MutableMapping[str, ViralityScore] = {}  # keyed by event_id
        self._buckets: Deque[Tuple[datetime, str]] = deque()
        self._lock = threading.RLock()
        self._retention_limit = retention_limit

        # Prometheus metrics
        self.metric_score_latest = Gauge(
            "psn_virality_score_latest",
            "Latest computed virality score",
            labelnames=("event_id", "network"),
        )
        self.metric_score_mean = Gauge(
            "psn_virality_score_mean_window",
            "Mean virality score in the sliding window",
        )
        start_http_server(metrics_port)
        logger.info("Prometheus metrics exporter started on port %d", metrics_port)

    # ---------------------------------------------------------------------#
    # Public API
    # ---------------------------------------------------------------------#

    def ingest(self, raw_event: dict | Event) -> ViralityScore | None:
        """
        Validate, compute and record a virality score for the given event.

        Returns
        -------
        ViralityScore | None
            None is returned when validation fails or event is discarded due to
            retention policy.
        """
        try:
            event: Event = raw_event if isinstance(raw_event, Event) else Event(**raw_event)
        except ValidationError as exc:
            logger.warning("Invalid event skipped: %s", exc)
            return None

        strategy_cls = STRATEGY_REGISTRY.get(event.network, GenericViralityStrategy)
        score_value = strategy_cls.compute(event)

        score = ViralityScore(event_id=event.event_id, score=score_value)

        with self._lock:
            # Insert or overwrite score
            self._scores[event.event_id] = score
            self._buckets.append((score.created_at, event.event_id))

            self._enforce_window()
            self._enforce_retention()

        # Metric update
        self.metric_score_latest.labels(event_id=event.event_id, network=event.network.value).set(
            score_value
        )
        self.metric_score_mean.set(self._mean_score())

        logger.debug("Score %.3f recorded for %s", score_value, event.event_id)
        return score

    def top_n(self, n: int = 10) -> List[ViralityScore]:
        """Return the top-N hottest events inside the current window."""
        with self._lock:
            return sorted(self._scores.values(), key=lambda s: s.score, reverse=True)[:n]

    # ---------------------------------------------------------------------#
    # Internal Helpers
    # ---------------------------------------------------------------------#

    def _enforce_window(self) -> None:
        """Drop any scores falling outside of the sliding window."""
        now = datetime.utcnow()
        while self._buckets and now - self._buckets[0][0] > self.window:
            _, event_id = self._buckets.popleft()
            removed = self._scores.pop(event_id, None)
            if removed:
                logger.debug("Score for %s expired from window", event_id)

    def _enforce_retention(self) -> None:
        """Ensure in-memory retention cap."""
        if len(self._scores) <= self._retention_limit:
            return
        # Remove scores with the lowest virality
        sorted_scores = sorted(self._scores.values(), key=lambda s: s.score)
        for score in sorted_scores[: len(self._scores) - self._retention_limit]:
            self._scores.pop(score.event_id, None)
            logger.debug("Score for %s evicted due to retention cap", score.event_id)

    def _mean_score(self) -> float:
        """Mean score inside the window (0 if empty)."""
        if not self._scores:
            return 0.0
        return mean(s.score for s in self._scores.values())


# ---------------------------------------------------------------------------#
# Async wrapper for streaming pipelines
# ---------------------------------------------------------------------------#


class AsyncViralityConsumer:
    """
    Convenience wrapper that feeds the ViralityEngine from an async iterator
    (e.g. aiokafka consumer, websockets, etc.).
    """

    def __init__(
        self,
        event_iter: Callable[[], asyncio.AsyncIterator[dict]],
        engine: Optional[ViralityEngine] = None,
    ):
        self._event_iter_factory = event_iter
        self._engine = engine or ViralityEngine()
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        """Start consumption loop until `stop()` is called."""
        logger.info("Async virality consumer started")
        try:
            async for raw_event in self._event_iter_factory():
                if self._shutdown.is_set():
                    break
                self._engine.ingest(raw_event)
        except asyncio.CancelledError:
            logger.info("Async consumer cancelled")
        finally:
            logger.info("Async virality consumer stopped")

    def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._shutdown.set()


# ---------------------------------------------------------------------------#
# Entrypoint (for manual/standalone execution)
# ---------------------------------------------------------------------------#


async def _dummy_event_stream() -> asyncio.AsyncIterator[dict]:
    """
    Yield a continuous stream of random events for demonstration purposes only.
    Avoids importing heavy faker packages to keep dependency footprint small.
    """
    import random
    import uuid

    networks = [n for n in Network if n != Network.UNKNOWN]
    while True:
        yield {
            "network": random.choice(networks).value,
            "event_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4())[:8],
            "reactions": random.randint(0, 500),
            "replies": random.randint(0, 200),
            "reposts": random.randint(0, 100),
            "timestamp": datetime.utcnow().isoformat(),
        }
        await asyncio.sleep(random.uniform(0.1, 0.5))


def _run_demo() -> None:
    """Blocking demo execution function."""
    engine = ViralityEngine(window=timedelta(seconds=30))
    consumer = AsyncViralityConsumer(event_iter=_dummy_event_stream, engine=engine)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _main():
        runner = asyncio.create_task(consumer.run())

        try:
            while True:
                await asyncio.sleep(5)
                top5 = engine.top_n(5)
                logger.info("Top 5 scores: %s", [(s.event_id[:6], f"{s.score:.1f}") for s in top5])
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt – shutting down")
            consumer.stop()
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner

    import contextlib

    loop.run_until_complete(_main())


if __name__ == "__main__":
    # Running this module directly kicks off a self-contained demo
    _run_demo()
```