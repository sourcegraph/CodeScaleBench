```python
"""
PulseStream Nexus – src/module_18.py
------------------------------------

This module encapsulates a reusable, strategy-driven component for estimating the
“virality” of social-media events in (near-)real-time streaming pipelines.

Key concepts
============
1. SocialEvent (pydantic model)
   – Strict runtime validation / coercion of incoming event payloads.

2. ViralityStrategy (Strategy Pattern)
   – Pluggable algorithms for converting raw engagement metrics into a
     comparable virality score. Three reference implementations are provided:
       * LinearViralityStrategy
       * LogisticViralityStrategy
       * ExponentialViralityStrategy

3. ViralityScorer
   – Stateful observer that consumes SocialEvent objects, applies a configured
     ViralityStrategy, and returns a ViralityScoreResult. Internally maintains a
     sliding-window of recent scores to compute relative trends.

4. Prometheus metrics
   – Counter and Histogram instances for operational transparency.  Runtime
     import failure is gracefully degraded to no-op stubs.

The component is intentionally framework-agnostic (Kafka, Beam, Spark, Flink…)
and can be wired into both batch or streaming jobs.

"""

from __future__ import annotations

import logging
import math
import sys
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, Optional

from pydantic import BaseModel, Field, root_validator, validator

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ------------------------------------------------------------------------------
# Prometheus metrics
# ------------------------------------------------------------------------------

try:
    # Prometheus is an optional dependency in certain deployment modes.
    from prometheus_client import Counter, Histogram
except ModuleNotFoundError:  # pragma: no cover – fallback for non-metrics envs
    class _NoOpMetric:  # pylint: disable=too-few-public-methods
        """Drop-in replacement that silently ignores all metric calls."""

        def __init__(self, *_, **__) -> None:
            pass

        def inc(self, *_, **__) -> None:  # noqa: D401  pylint: disable=unused-argument
            pass

        def observe(self, *_, **__) -> None:  # noqa: D401 pylint: disable=unused-argument
            pass

    Counter = Histogram = _NoOpMetric  # type: ignore

# Define actual metrics (or no-op)
EVENT_PROCESSED_TOTAL = Counter(
    "virality_scorer_events_total",
    "Total number of events processed by ViralityScorer",
)
EVENT_PROCESSING_LATENCY_SECONDS = Histogram(
    "virality_scorer_latency_seconds",
    "Latency for processing individual events in ViralityScorer",
    buckets=(0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

# ------------------------------------------------------------------------------
# Domain models
# ------------------------------------------------------------------------------


class SocialEvent(BaseModel):
    """
    Canonical representation of a social interaction captured by PulseStream.

    Note:
        – All numerical engagement metrics are coerced to non-negative ints.
        – The model purposefully excludes nested child objects to remain
          serialization-friendly (e.g., for Kafka/JSON).
    """

    event_id: str = Field(..., description="Globally unique identifier for the event")
    platform: str = Field(..., description="Source platform (twitter, reddit, …)")
    user_id: str = Field(..., description="Originating user identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the interaction occurred",
    )
    content: str = Field(..., description="Raw textual content of the event")

    likes: int = Field(0, ge=0, description="Number of likes/favorites")
    shares: int = Field(0, ge=0, description="Number of shares/retweets")
    comments: int = Field(0, ge=0, description="Number of comments/replies")

    sentiment_score: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Sentiment polarity in range [-1, 1]",
    )
    toxicity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Toxicity probability in range [0, 1]",
    )

    class Config:
        frozen = True  # immutability
        allow_mutation = False
        json_encoders = {datetime: lambda v: v.isoformat()}

    # --------------------------------------------------------------------- #
    # Validators
    # --------------------------------------------------------------------- #

    @validator("platform")
    def _platform_lowercase(cls, v: str) -> str:
        return v.lower()

    @root_validator
    def _sanity_checks(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        likes, shares, comments = values.get("likes"), values.get("shares"), values.get("comments")
        if likes + shares + comments == 0:
            logger.debug("Event %s has zero engagement metrics.", values.get("event_id"))
        return values


class ViralityScoreResult(BaseModel):
    """
    Output envelope for virality scoring results.
    """

    event_id: str
    platform: str
    timestamp: datetime
    virality_score: float
    window_mean: float
    window_std: float

    class Config:
        frozen = True
        allow_mutation = False
        json_encoders = {datetime: lambda v: v.isoformat()}


# ------------------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------------------


class ViralityComputationError(RuntimeError):
    """Raised when a strategy fails to compute a score."""


# ------------------------------------------------------------------------------
# Strategy Pattern
# ------------------------------------------------------------------------------

class ViralityStrategy(ABC):  # pylint: disable=too-few-public-methods
    """
    Abstract base class for virality scoring strategies.
    """

    name: str

    @abstractmethod
    def compute_score(self, event: SocialEvent) -> float:
        """
        Derive a normalized virality score for a single event.

        Implementations may leverage any subset of event attributes,
        but must return a non-negative float.  Implementations SHOULD
        be pure functions – internal state is discouraged.

        Raises:
            ViralityComputationError: On failure.

        Returns:
            float: Virality score (higher ⇒ more viral)
        """

    # Convenience dunder
    def __call__(self, event: SocialEvent) -> float:
        return self.compute_score(event)


class LinearViralityStrategy(ViralityStrategy):
    """
    Simple linear weighted sum of engagement metrics and sentiment/toxicity.
    """

    name = "linear"

    def __init__(
        self,
        w_likes: float = 1.0,
        w_shares: float = 3.0,
        w_comments: float = 2.0,
        sentiment_multiplier: float = 1.2,
        toxicity_penalty: float = 0.5,
    ) -> None:
        self._weights = {
            "likes": w_likes,
            "shares": w_shares,
            "comments": w_comments,
        }
        self._sentiment_multiplier = sentiment_multiplier
        self._toxicity_penalty = toxicity_penalty

    def compute_score(self, event: SocialEvent) -> float:  # noqa: D401
        try:
            base = (
                event.likes * self._weights["likes"]
                + event.shares * self._weights["shares"]
                + event.comments * self._weights["comments"]
            )
            sentiment_factor = 1 + (event.sentiment_score * self._sentiment_multiplier)
            toxicity_factor = 1 - (event.toxicity_score * self._toxicity_penalty)
            score = max(base * sentiment_factor * toxicity_factor, 0.0)
            logger.debug(
                "Linear strategy – Event %s base=%s sentiment_factor=%.3f toxicity_factor=%.3f score=%.3f",
                event.event_id,
                base,
                sentiment_factor,
                toxicity_factor,
                score,
            )
            return score
        except Exception as exc:  # pylint: disable=broad-except
            raise ViralityComputationError("Linear strategy failed") from exc


class LogisticViralityStrategy(ViralityStrategy):
    """
    Logistic growth curve to bound score between 0 and 1.
    """

    name = "logistic"

    def __init__(self, growth_rate: float = 0.01, midpoint: float = 50.0) -> None:
        self._growth_rate = growth_rate
        self._midpoint = midpoint

    def compute_score(self, event: SocialEvent) -> float:  # noqa: D401
        try:
            exposure = event.likes + 2 * event.shares + 0.5 * event.comments
            raw = 1 / (1 + math.exp(-self._growth_rate * (exposure - self._midpoint)))
            sentiment_boost = 1 + event.sentiment_score * 0.2
            toxicity_penalty = 1 - event.toxicity_score * 0.3
            score = max(raw * sentiment_boost * toxicity_penalty, 0.0)
            logger.debug(
                "Logistic strategy – exposure=%.3f raw=%.3f score=%.3f", exposure, raw, score
            )
            return score
        except OverflowError as exc:
            logger.warning("Overflow in logistic computation for event %s", event.event_id)
            raise ViralityComputationError("Numeric overflow") from exc
        except Exception as exc:  # pylint: disable=broad-except
            raise ViralityComputationError("Logistic strategy failed") from exc


class ExponentialViralityStrategy(ViralityStrategy):
    """
    Exponential emphasis on shares to accentuate viral cascades.
    """

    name = "exponential"

    def __init__(self, alpha: float = 0.05) -> None:
        self._alpha = alpha

    def compute_score(self, event: SocialEvent) -> float:  # noqa: D401
        try:
            score = math.exp(self._alpha * event.shares) - 1
            # Sentiment/toxicity adjustments (simple multipliers)
            score *= 1 + 0.1 * event.sentiment_score
            score *= 1 - 0.2 * event.toxicity_score
            logger.debug(
                "Exponential strategy – shares=%d alpha=%.3f score=%.3f",
                event.shares,
                self._alpha,
                score,
            )
            return max(score, 0.0)
        except OverflowError as exc:
            logger.error("Overflow in exponential computation for event %s", event.event_id)
            raise ViralityComputationError("Numeric overflow") from exc
        except Exception as exc:  # pylint: disable=broad-except
            raise ViralityComputationError("Exponential strategy failed") from exc


# ------------------------------------------------------------------------------
# Virality Scorer (Observer)
# ------------------------------------------------------------------------------


class ViralityScorer:
    """
    Observer/handler that computes virality for a stream of SocialEvent objects.

    The scorer maintains a deque as a rolling window of recent scores to provide
    contextual statistics (mean and standard deviation).  This allows consumers
    to detect bursts/spikes relative to recent baseline activity.
    """

    def __init__(
        self,
        strategy: ViralityStrategy,
        window_size: int = 500,
        time_horizon: timedelta = timedelta(minutes=30),
    ) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be > 0")
        self._strategy = strategy
        self._window_size = window_size
        self._time_horizon = time_horizon

        self._window: Deque[ViralityScoreResult] = deque(maxlen=window_size)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def process_event(self, event: SocialEvent) -> ViralityScoreResult:
        """
        Compute virality score and update sliding window.

        This method is synchronous but lightweight — suitable for direct use in
        frameworks such as Kafka Streams, Beam ParDo, or Spark mapPartitions.
        """
        start_time = time_monotonic = getattr(sys.modules.get("time"), "monotonic", None)
        if callable(time_monotonic):
            monotonic_start = time_monotonic()
        try:
            score = self._strategy(event)
            mean, std_dev = self._update_window(datetime.now(timezone.utc), score)
            result = ViralityScoreResult(
                event_id=event.event_id,
                platform=event.platform,
                timestamp=event.timestamp,
                virality_score=score,
                window_mean=mean,
                window_std=std_dev,
            )
            logger.debug(
                "Processed event %s – score=%.3f window_mean=%.3f window_std=%.3f",
                event.event_id,
                score,
                mean,
                std_dev,
            )
            EVENT_PROCESSED_TOTAL.inc()
            return result
        finally:
            if callable(time_monotonic):
                latency = time_monotonic() - monotonic_start
                EVENT_PROCESSING_LATENCY_SECONDS.observe(latency)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _update_window(self, now: datetime, score: float) -> tuple[float, float]:
        """
        Append score to the rolling window, evicting stale entries by either
        window_size or time_horizon.  Returns (mean, std_dev).
        """
        self._window.append(
            ViralityScoreResult(
                event_id="",  # placeholder, not needed for stats
                platform="",
                timestamp=now,
                virality_score=score,
                window_mean=0.0,
                window_std=0.0,
            )
        )

        # Evict by time horizon (optional)
        while self._window and now - self._window[0].timestamp > self._time_horizon:
            self._window.popleft()

        # Compute stats
        scores = [r.virality_score for r in self._window]
        count = len(scores)
        if count == 0:
            return 0.0, 0.0

        mean = sum(scores) / count
        variance = sum((s - mean) ** 2 for s in scores) / count
        std_dev = math.sqrt(variance)
        return mean, std_dev


# ------------------------------------------------------------------------------
# Convenience factory for dependency injection
# ------------------------------------------------------------------------------


def build_default_scorer(strategy_name: str = "linear") -> ViralityScorer:
    """
    Factory that instantiates a ViralityScorer with one of the built-in
    strategies based on a human-readable name.
    """
    strategy_map: Dict[str, ViralityStrategy] = {
        "linear": LinearViralityStrategy(),
        "logistic": LogisticViralityStrategy(),
        "exponential": ExponentialViralityStrategy(),
    }
    if strategy_name not in strategy_map:
        raise KeyError(f"Unknown strategy '{strategy_name}'")

    scorer = ViralityScorer(strategy=strategy_map[strategy_name])
    logger.info("Initialized ViralityScorer with %s strategy", strategy_name)
    return scorer


# ------------------------------------------------------------------------------
# dunder exports
# ------------------------------------------------------------------------------

__all__ = [
    "SocialEvent",
    "ViralityScoreResult",
    "ViralityStrategy",
    "LinearViralityStrategy",
    "LogisticViralityStrategy",
    "ExponentialViralityStrategy",
    "ViralityScorer",
    "build_default_scorer",
    "ViralityComputationError",
]
```