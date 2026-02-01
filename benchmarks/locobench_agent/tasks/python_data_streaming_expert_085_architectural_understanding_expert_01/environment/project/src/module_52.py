```python
"""
module_52.py
PulseStream Nexus – Data Streaming Platform
-------------------------------------------

This module implements an extensible, strategy-based transformation pipeline
for social-media events.  It demonstrates how domain logic can remain
framework-agnostic while still being pluggable into the broader streaming
topology (Kafka consumers, Beam jobs, etc.).

Key design patterns:
    • Strategy Pattern     – interchangeable transformation strategies
    • Observer Pattern     – pluggable monitoring / metric sinks
    • Fail-Fast Philosophy – validation & safeguarding around third-party deps

Author  : PulseStream Nexus Core Team
License : Apache-2.0
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Dict, Iterable, List, MutableMapping, Protocol, runtime_checkable

logger = logging.getLogger(__name__)
DEFAULT_LOG_LEVEL = os.getenv("PULSESTREAM_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=DEFAULT_LOG_LEVEL,
    format=(
        "%(asctime)s | %(levelname)s | %(name)s | "
        "%(funcName)s:%(lineno)d – %(message)s"
    ),
)


# --------------------------------------------------------------------------- #
# Domain Entities
# --------------------------------------------------------------------------- #

@dataclass(slots=True, frozen=True)
class SocialEvent:
    """
    Domain entity representing an immutable, validated slice of social activity.

    Attributes
    ----------
    event_id : str
        Globally unique identifier for the event (same across shards).
    actor_id : str
        User identifier (platform-native).
    platform : str
        Source platform (twitter, reddit, mastodon, discord…).
    payload : Dict[str, Any]
        Raw JSON payload as dictated by originating API.
    created_at : datetime
        Timestamp (UTC) when the platform recorded the activity.
    """

    event_id: str
    actor_id: str
    platform: str
    payload: Dict[str, Any]
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


@dataclass(slots=True)
class EnrichedSocialEvent:
    """
    Mutable representation with calculated enrichment fields.

    It purposefully mirrors SocialEvent but allows mutation, making it suitable
    for transformation pipelines.  Downstream, the object can be frozen again
    (or converted back to dict) before persistence.
    """

    base: SocialEvent
    enriched_fields: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a canonical JSON-serialisable representation."""
        data = asdict(self.base)
        data.update(self.enriched_fields)
        return data


# --------------------------------------------------------------------------- #
# Transformation Strategy Interfaces
# --------------------------------------------------------------------------- #

class TransformationError(RuntimeError):
    """Raised when a transform strategy fails in a non-recoverable way."""


class RecoverableTransformationError(TransformationError):
    """Raised when a transform strategy fails, but retry could succeed."""


@runtime_checkable
class TransformStrategy(Protocol):
    """Contract for all enrichment strategies."""

    name: str

    @abstractmethod
    def transform(self, event: EnrichedSocialEvent) -> None:
        """
        Mutate `event.enriched_fields` with domain-specific enrichment data.

        Implementation SHOULD be side-effect-free outside of the passed event.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Concrete Strategies
# --------------------------------------------------------------------------- #

class _SentimentModelSingleton:
    """
    A defensive singleton wrapper around external NLP libraries.

    TextBlob is used if available; otherwise, fallback to a naïve rule-based
    sentiment scorer (keyword count).  The singleton ensures we only perform
    expensive model initialisation once per process.
    """

    _instance: "_SentimentModelSingleton | None" = None

    positive_keywords = {"nice", "great", "awesome", "love", "good", "fantastic"}
    negative_keywords = {"hate", "terrible", "awful", "bad", "worst", "ugly"}

    def __new__(cls) -> "_SentimentModelSingleton":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            try:
                from textblob import TextBlob  # type: ignore
                cls._instance._analyser = TextBlob
                cls._instance._mode = "textblob"
                logger.info("Sentiment analysis backed by TextBlob")
            except ModuleNotFoundError:
                cls._instance._analyser = None
                cls._instance._mode = "keywords"
                logger.warning(
                    "TextBlob not found – falling back to keyword sentiment analyser"
                )
        return cls._instance

    def polarity(self, text: str) -> float:
        if self._mode == "textblob":
            return float(self._analyser(text).sentiment.polarity)
        # Keyword fallback
        tokens = text.lower().split()
        pos_score = sum(1 for t in tokens if t in self.positive_keywords)
        neg_score = sum(1 for t in tokens if t in self.negative_keywords)
        if pos_score + neg_score == 0:
            return 0.0
        return (pos_score - neg_score) / (pos_score + neg_score)


class SentimentTransform(TransformStrategy):
    """
    Annotate event with `sentiment_score` in range [-1.0, 1.0].

    Uses _SentimentModelSingleton for efficient model reuse.
    """

    name = "sentiment_transform"

    def __init__(self) -> None:
        self._model = _SentimentModelSingleton()

    def transform(self, event: EnrichedSocialEvent) -> None:  # noqa: D401
        text = self._extract_text(event.base)
        if not text:
            event.enriched_fields["sentiment_score"] = None
            return
        try:
            event.enriched_fields["sentiment_score"] = self._model.polarity(text)
        except Exception as exc:  # pragma: no cover
            raise RecoverableTransformationError(
                f"Sentiment transform failed for event {event.base.event_id}"
            ) from exc

    @staticmethod
    def _extract_text(base_event: SocialEvent) -> str | None:
        # Platform-specific heuristics:
        if base_event.platform.lower() in {"twitter", "reddit", "mastodon"}:
            return base_event.payload.get("text")
        if base_event.platform.lower() == "discord":
            return base_event.payload.get("content")
        return None


class ToxicityTransform(TransformStrategy):
    """
    Dummy toxicity classifier.

    In production this may call Perspective API or a fine-tuned transformer,
    but we emulate logic for this example.
    """

    name = "toxicity_transform"

    def __init__(self, threshold: float = 0.7) -> None:
        self._threshold = threshold

    def transform(self, event: EnrichedSocialEvent) -> None:
        text = event.base.payload.get("text") or ""
        score = self._naive_toxicity(text)
        is_toxic = score >= self._threshold
        event.enriched_fields["toxicity_score"] = score
        event.enriched_fields["is_toxic"] = is_toxic

    @staticmethod
    def _naive_toxicity(text: str) -> float:
        """
        Count swear words from a minimal lexicon and map to 0-1.

        This approach is obviously insufficient for real usage but suffices
        for demonstration, keeping the module self-contained.
        """
        swear_words = {
            "fuck",
            "shit",
            "bitch",
            "asshole",
            "bastard",
            "dick",
            "damn",
        }
        tokens = text.lower().split()
        if not tokens:
            return 0.0
        ratio = sum(1 for t in tokens if t in swear_words) / len(tokens)
        return min(1.0, ratio * 3)  # gentle scale


class ViralityTransform(TransformStrategy):
    """
    Adds a basic virality score based on engagement counters.

    Intended to run after ETL stage that ensures engagement metrics exist
    in the payload (retweet_count, reply_count, like_count…).
    """

    name = "virality_transform"

    _PLATFORM_MAPPING: Dict[str, Iterable[str]] = {
        "twitter": ("retweet_count", "reply_count", "like_count", "quote_count"),
        "reddit": ("score", "num_comments"),
        "mastodon": ("reblogs_count", "favourites_count", "replies_count"),
        "discord": ("reaction_count",),  # synthetic field from aggregator
    }

    def transform(self, event: EnrichedSocialEvent) -> None:
        keys = self._PLATFORM_MAPPING.get(event.base.platform.lower())
        if not keys:
            logger.debug(
                "No virality metric mapping for platform %s", event.base.platform
            )
            return

        counts: List[int] = []
        for k in keys:
            try:
                counts.append(int(event.base.payload.get(k, 0)))
            except (ValueError, TypeError):
                logger.debug(
                    "Invalid count '%s' for key '%s' on event %s",
                    event.base.payload.get(k),
                    k,
                    event.base.event_id,
                )

        if not counts:
            return

        score = mean(counts) / 100  # Arbitrary scaling – refine offline
        event.enriched_fields["virality_score"] = round(score, 4)


# --------------------------------------------------------------------------- #
# Observer Interface & Concrete Observers
# --------------------------------------------------------------------------- #

class Observer(Protocol):
    @abstractmethod
    def update(
        self,
        strategy: str,
        event_id: str,
        latency_ms: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Receive a notification from an observable subject."""
        raise NotImplementedError


class LoggingObserver(Observer):
    """Emit transformation stats to the application logger."""

    def update(
        self,
        strategy: str,
        event_id: str,
        latency_ms: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        level = logging.INFO if success else logging.ERROR
        logger.log(
            level,
            "Strategy=%s event_id=%s latency_ms=%.2f success=%s error=%s",
            strategy,
            event_id,
            latency_ms,
            success,
            error or "",
        )


class InMemoryMetricsObserver(Observer):
    """
    Simple observer accumulating metrics in memory.

    Suitable for unit tests.  Real deployments would push to Prometheus,
    OpenTelemetry, or StatsD.
    """

    def __init__(self) -> None:
        self.counters: MutableMapping[str, int] = {}
        self.latencies: MutableMapping[str, List[float]] = {}

    def update(
        self,
        strategy: str,
        event_id: str,
        latency_ms: float,
        success: bool,
        error: str | None = None,
    ) -> None:  # noqa: D401
        key = f"{strategy}.success" if success else f"{strategy}.failure"
        self.counters[key] = self.counters.get(key, 0) + 1
        self.latencies.setdefault(strategy, []).append(latency_ms)


# --------------------------------------------------------------------------- #
# Transformation Pipeline (Observable Subject)
# --------------------------------------------------------------------------- #

class TransformerPipeline:
    """
    Compose multiple `TransformStrategy` instances with observer notifications.

    Example
    -------
    >>> pipeline = TransformerPipeline(
    ...     strategies=[SentimentTransform(), ToxicityTransform()],
    ...     observers=[LoggingObserver()],
    ... )
    >>> enriched = pipeline.process(social_event)
    >>> print(enriched.to_dict())
    """

    def __init__(
        self,
        strategies: List[TransformStrategy],
        observers: List[Observer] | None = None,
    ) -> None:
        self._strategies = strategies
        self._observers: List[Observer] = observers or [LoggingObserver()]
        self._validate_unique_names()

    def _validate_unique_names(self) -> None:
        seen = set()
        for s in self._strategies:
            if s.name in seen:
                raise ValueError(f"Duplicate strategy name detected: {s.name}")
            seen.add(s.name)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def process(self, event: SocialEvent) -> EnrichedSocialEvent:
        """Apply all strategies in sequence and notify observers."""
        enriched = EnrichedSocialEvent(base=event)
        for strategy in self._strategies:
            start = time.perf_counter()
            success, err_msg = self._apply_strategy(strategy, enriched)
            latency = (time.perf_counter() - start) * 1000.0
            self._notify(strategy.name, event.event_id, latency, success, err_msg)
        return enriched

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _apply_strategy(
        self,
        strategy: TransformStrategy,
        event: EnrichedSocialEvent,
    ) -> tuple[bool, str | None]:
        try:
            strategy.transform(event)
            return True, None
        except RecoverableTransformationError as exc:
            logger.warning(str(exc))
            return False, str(exc)
        except Exception as exc:  # pragma: no cover
            logger.exception(
                "Fatal error in strategy '%s' for event_id=%s",
                strategy.name,
                event.base.event_id,
            )
            # Reraise: fatal – propagate up the stack
            raise TransformationError from exc

    def _notify(
        self,
        strategy: str,
        event_id: str,
        latency_ms: float,
        success: bool,
        error: str | None,
    ) -> None:
        for obs in self._observers:
            try:
                obs.update(strategy, event_id, latency_ms, success, error)
            except Exception:  # pragma: no cover
                logger.exception(
                    "Observer '%s' failed while processing notification",
                    type(obs).__name__,
                )


# --------------------------------------------------------------------------- #
# JSON (De)Serialisation Helpers
# --------------------------------------------------------------------------- #

def social_event_from_json(data: str | bytes | bytearray) -> SocialEvent:
    """
    Parse a JSON string or bytes into a SocialEvent.

    Raises
    ------
    ValueError
        If mandatory fields are missing / malformed.
    """
    obj = json.loads(data)
    try:
        event = SocialEvent(
            event_id=obj["event_id"],
            actor_id=obj["actor_id"],
            platform=obj["platform"],
            payload=obj["payload"],
            created_at=datetime.fromisoformat(obj["created_at"]),
        )
        return event
    except KeyError as exc:
        raise ValueError(f"Missing mandatory field: {exc}") from exc
    except Exception as exc:
        raise ValueError("Invalid SocialEvent JSON") from exc


# --------------------------------------------------------------------------- #
# Example entrypoint (for local debugging)
# --------------------------------------------------------------------------- #

def _example() -> None:  # pragma: no cover
    """Run a local pipeline example on synthetic data."""
    logger.info("Running module_52 example pipeline…")

    raw_json = json.dumps(
        {
            "event_id": "evt_123",
            "actor_id": "user_789",
            "platform": "twitter",
            "payload": {
                "text": "I love the new PulseStream! This is awesome.",
                "retweet_count": 42,
                "reply_count": 3,
                "like_count": 120,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    se = social_event_from_json(raw_json)
    pipeline = TransformerPipeline(
        strategies=[
            SentimentTransform(),
            ToxicityTransform(),
            ViralityTransform(),
        ],
        observers=[LoggingObserver(), InMemoryMetricsObserver()],
    )

    enriched = pipeline.process(se)
    print(json.dumps(enriched.to_dict(), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    _example()
```