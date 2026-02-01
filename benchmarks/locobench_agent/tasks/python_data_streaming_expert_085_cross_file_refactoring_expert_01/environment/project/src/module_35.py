```python
"""
src/module_35.py
================

PulseStream Nexus – Event Transformation Pipeline
-------------------------------------------------

This module contains the production-grade implementation of a **Clean-Architecture
use-case interactor** that converts a raw social-network event into a set of
enriched, analytics-ready records.  It demonstrates the following architectural
concerns:

* Strategy Pattern – Pluggable transformation strategies (sentiment, toxicity,
  virality, …).
* Pipeline/Observer Pattern – Sequential event processing with life-cycle
  callbacks for monitoring and error handling.
* Operational Telemetry – Metrics, structured logging and graceful shutdown.
* Validation – Pydantic schema enforcement prior to business-rule execution.

The code purposefully avoids concrete I/O (Kafka, DB, etc.) so that it remains
independent of framework or infrastructure, thus staying true to Clean-Architecture
principles.  Adapters may call the exposed `build_pipeline` factory from their
respective process boundaries.

Author: PulseStream Core Team
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    # pydantic is listed as a project dependency; fallback for type-checking
    from pydantic import BaseModel, Field, ValidationError
except ImportError:  # pragma: no cover
    BaseModel = object            # type: ignore
    ValidationError = Exception   # type: ignore

# ------------------------------------------------------------------------------
# Configuration & Logging
# ------------------------------------------------------------------------------

_LOG_LEVEL = os.getenv("PULSENEX_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pulsenex.module_35")

# ------------------------------------------------------------------------------
# Domain Layer
# ------------------------------------------------------------------------------


class SocialEvent(BaseModel):  # type: ignore[misc]
    """
    Canonical schema for all inbound events in PulseStream Nexus.
    This is intentionally compact; nested meta-information is placed beneath
    the `attributes` root.
    """

    event_id: str = Field(..., description="Globally unique identifier")
    platform: str = Field(..., regex="^(twitter|reddit|mastodon|discord)$")
    author_id: str
    text: str
    timestamp: datetime = Field(..., description="UTC timestamp")
    attributes: Dict[str, Any] = Field(default_factory=dict)

    class Config:  # Pydantic config
        allow_mutation = False
        anystr_strip_whitespace = True
        orm_mode = True
        json_encoders = {datetime: lambda dt: int(dt.timestamp() * 1000)}


class EnrichedSocialEvent(SocialEvent):
    """
    Output schema after enrichment strategies are applied.
    """

    sentiment: Optional[float] = None
    toxicity: Optional[float] = None
    virality_score: Optional[float] = None


# ------------------------------------------------------------------------------
# Strategy Layer
# ------------------------------------------------------------------------------


class TransformationStrategy(ABC):
    """
    Common interface for a transformation strategy.
    Every subclass should return a **new** instance of `EnrichedSocialEvent`
    (i.e., no side-effects on the input).
    """

    name: str

    @abstractmethod
    async def transform(self, event: EnrichedSocialEvent) -> EnrichedSocialEvent:  # noqa: D401
        """Asynchronously transform the event and return a new enriched instance."""


class SentimentAnalysisStrategy(TransformationStrategy):
    """
    Simple sentiment analysis stub.

    In the real implementation, this would issue an RPC to a hosted sentiment
    model (e.g., HuggingFace Inference API, Vertex AI, or an internal micro-
    service).  For demonstration it returns pseudo-random values.
    """

    name = "sentiment"

    async def transform(self, event: EnrichedSocialEvent) -> EnrichedSocialEvent:
        # Simulate network latency
        await asyncio.sleep(0.001)
        sentiment_score = self._mock_sentiment(event.text)
        logger.debug("Sentiment for %s: %s", event.event_id, sentiment_score)
        return event.copy(update={"sentiment": sentiment_score})

    @staticmethod
    def _mock_sentiment(text: str) -> float:
        # Very naive: positivity proportional to presence of "good" words.
        positive_tokens = ("good", "great", "love", "excellent", "😊")
        negative_tokens = ("bad", "hate", "terrible", "awful", "😡")
        score = 0.0
        for token in positive_tokens:
            score += text.lower().count(token) * 0.1
        for token in negative_tokens:
            score -= text.lower().count(token) * 0.1
        # Clamp to [-1, 1]
        return max(min(score, 1.0), -1.0)


class ToxicityAnalysisStrategy(TransformationStrategy):
    """
    Placeholder toxicity detection strategy.
    """

    name = "toxicity"

    async def transform(self, event: EnrichedSocialEvent) -> EnrichedSocialEvent:
        await asyncio.sleep(0.001)
        toxicity_score = self._mock_toxicity(event.text)
        logger.debug("Toxicity for %s: %s", event.event_id, toxicity_score)
        return event.copy(update={"toxicity": toxicity_score})

    @staticmethod
    def _mock_toxicity(text: str) -> float:
        toxic_keywords = ("idiot", "stupid", "moron", "hate", "damn")
        hits = sum(text.lower().count(word) for word in toxic_keywords)
        return min(hits * 0.2, 1.0)  # Cap at 1.0


class ViralityScoreStrategy(TransformationStrategy):
    """
    Estimate virality by simple heuristics (retweets + favorites + replies).

    The real implementation would involve features such as community spreads,
    network centrality, and real-time counters from source APIs.
    """

    name = "virality"

    async def transform(self, event: EnrichedSocialEvent) -> EnrichedSocialEvent:
        await asyncio.sleep(0.0005)
        attributes = event.attributes or {}
        popularity = attributes.get("popularity_metrics", {})
        virality = self._compute_virality(popularity)
        logger.debug("Virality for %s: %s", event.event_id, virality)
        return event.copy(update={"virality_score": virality})

    @staticmethod
    def _compute_virality(popularity: Dict[str, Any]) -> float:
        # Basic weighted sum (retweets:2, likes:1, replies:1)
        retweets = popularity.get("retweets", 0)
        likes = popularity.get("likes", 0)
        replies = popularity.get("replies", 0)
        score = (2 * retweets + likes + replies) / 1000.0
        return min(score, 1.0)


# ------------------------------------------------------------------------------
# Pipeline / Use-Case Interactor
# ------------------------------------------------------------------------------


class EventTransformationPipeline:
    """
    Coordinates validation + sequential application of transformation strategies.
    This class is designed to be instantiated once per adapter process and
    re-used across messages for efficiency.
    """

    def __init__(
        self,
        strategies: Sequence[TransformationStrategy] | None = None,
        validation_enabled: bool = True,
    ) -> None:
        self._strategies: List[TransformationStrategy] = list(
            strategies
            or (
                SentimentAnalysisStrategy(),
                ToxicityAnalysisStrategy(),
                ViralityScoreStrategy(),
            )
        )
        self._validation_enabled = validation_enabled

    # Public API ----------------------------------------------------------------

    async def process(self, raw_event: Dict[str, Any]) -> EnrichedSocialEvent:
        """
        Entry-point consumed by external adapters (Kafka consumer, REST endpoint,
        etc.).  Accepts a **raw dict** as parsed from JSON and produces an
        `EnrichedSocialEvent`.
        """
        event = self._validate(raw_event)
        logger.debug("Processing event %s", event.event_id)

        enriched = EnrichedSocialEvent.parse_obj(event.dict())
        for strategy in self._strategies:
            start = time.perf_counter()
            try:
                enriched = await strategy.transform(enriched)
            except Exception:  # pragma: no cover
                logger.exception(
                    "Transformation '%s' failed for event_id=%s",
                    strategy.name,
                    event.event_id,
                )
                # Failed transformation does not block further processing
            finally:
                latency_ms = (time.perf_counter() - start) * 1000
                MetricsCollector.observe_latency(strategy.name, latency_ms)

        MetricsCollector.increment("events_processed_total")
        return enriched

    # Internals -----------------------------------------------------------------

    def _validate(self, raw: Dict[str, Any]) -> SocialEvent:
        """
        Performs schema validation (when enabled) and returns a typed model.
        """
        if not self._validation_enabled:
            return SocialEvent.construct(**raw)  # type: ignore[arg-type]

        try:
            return SocialEvent.parse_obj(raw)
        except ValidationError as exc:
            MetricsCollector.increment("events_failed_validation_total")
            logger.error(
                "Event validation failed: %s | payload=%s", exc, json.dumps(raw)[:256]
            )
            raise


# ------------------------------------------------------------------------------
# Metrics & Monitoring  (minimal stub – adapter integrates with Prometheus etc.)
# ------------------------------------------------------------------------------


class MetricsCollector:
    """
    Very thin abstraction around a real metrics system (Prometheus, StatsD…).
    Keeps in-memory counters so that the module is self-contained and easily
    testable.
    """

    _counters: Dict[str, int] = {}
    _observations: Dict[str, List[float]] = {}

    @classmethod
    def increment(cls, name: str, delta: int = 1) -> None:
        cls._counters[name] = cls._counters.get(name, 0) + delta

    @classmethod
    def observe_latency(cls, operation: str, value_ms: float) -> None:
        key = f"latency_ms_{operation}"
        cls._observations.setdefault(key, []).append(value_ms)

    # Convenience for debugging
    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        return {"counters": cls._counters.copy(), "latencies": cls._observations.copy()}


# ------------------------------------------------------------------------------
# Graceful-Shutdown Helper
# ------------------------------------------------------------------------------


@dataclass(slots=True)
class _ShutdownEvent:
    """
    Helper dataclass to implement graceful shutdown of asyncio pipelines.
    """

    _triggered: bool = False

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal, sig)

    def _handle_signal(self, sig: signal.Signals) -> None:  # pragma: no cover
        logger.warning("Received %s – initiating graceful shutdown …", sig.name)
        self._triggered = True

    def triggered(self) -> bool:
        return self._triggered


# ------------------------------------------------------------------------------
# Factory / Convenience Entrypoint
# ------------------------------------------------------------------------------


def build_pipeline() -> EventTransformationPipeline:
    """
    Factory function to build the default transformation pipeline.

    Keeping a tiny public surface like this ensures that *adapters* do not
    couple themselves to the actual class names – we may replace or decorate
    strategies later without breaking the callers.
    """
    return EventTransformationPipeline()


# ------------------------------------------------------------------------------
# Optional Stand-Alone Demo
# ------------------------------------------------------------------------------

async def _demo_stream() -> None:  # pragma: no cover
    """
    An illustrative, stand-alone asyncio demo that runs the pipeline against a
    mock stream.  This code is *never* executed in production and may be removed
    without impacting business logic.
    """
    shutdown = _ShutdownEvent()
    shutdown.install_signal_handlers()

    pipeline = build_pipeline()

    async def _produce_events() -> Iterable[Dict[str, Any]]:
        i = 0
        while not shutdown.triggered():
            i += 1
            yield {
                "event_id": f"evt_{i}",
                "platform": "twitter",
                "author_id": f"user_{i%10}",
                "text": "I love PulseStream 😊" if i % 2 else "You are an idiot 😡",
                "timestamp": datetime.now(tz=timezone.utc),
                "attributes": {
                    "popularity_metrics": {"retweets": i * 2, "likes": i * 5, "replies": i}
                },
            }
            await asyncio.sleep(0.05)

    async for raw in _produce_events():
        enriched = await pipeline.process(raw)
        logger.info("Enriched Event: %s", enriched.json())

    logger.info("Final metrics snapshot: %s", MetricsCollector.snapshot())


if __name__ == "__main__":  # pragma: no cover
    try:
        asyncio.run(_demo_stream())
    except KeyboardInterrupt:
        pass
```