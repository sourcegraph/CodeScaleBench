```python
"""
src/module_63.py
PulseStream Nexus – Data-Streaming Platform
-------------------------------------------

This module provides a production-ready, self-contained implementation of a small
(yet realistic) slice of the PulseStream Nexus platform:

1. A strategy-based validation layer for raw social events.
2. A transformation/enrichment stage that augments events with
   sentiment & toxicity scores.
3. An observer-driven monitoring subsystem that publishes metrics to
   Prometheus and captures errors in Sentry.
4. A simple dispatcher that glues the above parts together, suitable
   for use in an ETL/ELT micro-pipeline or as part of a Kafka consumer
   loop.

The implementation adheres to Clean Architecture principles: business rules
(`domain`) are kept free from external dependencies, whereas integrations
(`infra`) are isolated behind thin abstractions.
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, MutableMapping, Protocol, Sequence

# ------------------------------------------------------------------------------
# Optional (3rd-party) integrations
# ------------------------------------------------------------------------------

try:
    from pydantic import BaseModel, ValidationError  # type: ignore
except ImportError:  # pragma: no cover
    BaseModel = object  # fallback; validation will be disabled
    ValidationError = Exception

try:
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore
except ImportError:  # pragma: no cover
    Counter = Gauge = Histogram = None

try:
    import sentry_sdk  # type: ignore
except ImportError:  # pragma: no cover
    sentry_sdk = None

# ------------------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------------------

logger = logging.getLogger("pulstream.module_63")
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s › %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
logger.addHandler(handler)
logger.setLevel(os.environ.get("PULSTREAM_LOG_LEVEL", "INFO").upper())

# ------------------------------------------------------------------------------
# Domain objects
# ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SocialEvent:
    """
    Immutable representation of a social event emitted from an upstream producer.

    Attributes
    ----------
    id            : Unique identifier of the event within the upstream network.
    network       : The source network (e.g., 'twitter', 'reddit').
    author_id     : Identifier of the user that produced the event.
    text          : Raw textual payload.
    timestamp_ms  : Epoch-millis at which the event was created.
    meta          : Additional metadata (schema varies by network).
    """

    id: str
    network: str
    author_id: str
    text: str
    timestamp_ms: int
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize event to JSON string (UTF-8, compact)."""
        return json.dumps(asdict(self), separators=(",", ":"))


# ------------------------------------------------------------------------------
# Validation strategies
# ------------------------------------------------------------------------------


class ValidationStrategy(Protocol):
    """Validates raw event dictionaries prior to domain conversion."""

    def validate(self, raw: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        """Return a validated/possibly coerced representation or raise."""


class NullValidationStrategy:
    """
    No-op validator used when `pydantic` is unavailable or validation is disabled.
    """

    def validate(self, raw: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        return raw  # trust upstream producer


if BaseModel is not object:

    class _EventSchema(BaseModel):
        id: str
        network: str
        author_id: str
        text: str
        timestamp_ms: int
        meta: Dict[str, Any] = {}

    class PydanticValidationStrategy:
        """Validate events using a Pydantic schema."""

        def validate(
            self, raw: MutableMapping[str, Any]
        ) -> MutableMapping[str, Any]:
            try:
                # Validation & type coercion
                validated = _EventSchema.model_validate(raw)
                return validated.model_dump()
            except ValidationError as exc:
                logger.debug("Validation failed: %s", exc.json())
                raise

else:
    PydanticValidationStrategy = NullValidationStrategy  # type: ignore


# ------------------------------------------------------------------------------
# Enrichment / Transformation
# ------------------------------------------------------------------------------


class SentimentModel(ABC):
    """
    Abstract base class for sentiment & toxicity inference back-ends.
    Concrete implementations may delegate to HF Transformers, spaCy, etc.
    """

    @abstractmethod
    def score(self, text: str) -> Dict[str, float]:
        """
        Return a mapping with at least:

        sentiment    (−1 … 1) : negative to positive sentiment
        toxicity     ( 0 … 1) : probability of toxic content
        """
        raise NotImplementedError


class HeuristicSentimentModel(SentimentModel):
    """
    Extremely lightweight heuristic model (for demo / fallback use only).
    DO NOT use in production for real sentiment detection.
    """

    _positive = {"love", "awesome", "great", "amazing", "superb", "fantastic"}
    _negative = {"hate", "terrible", "awful", "worst", "horrible", "sucks"}

    def score(self, text: str) -> Dict[str, float]:
        text_lower = text.lower()
        pos_hits = sum(1 for w in self._positive if w in text_lower)
        neg_hits = sum(1 for w in self._negative if w in text_lower)
        total = pos_hits + neg_hits or 1
        sentiment = (pos_hits - neg_hits) / total
        toxicity = min(max(neg_hits / total, 0.0), 1.0)
        logger.debug(
            "HeuristicSentimentModel.score: pos=%d neg=%d sentiment=%.3f toxicity=%.3f",
            pos_hits,
            neg_hits,
            sentiment,
            toxicity,
        )
        return {"sentiment": sentiment, "toxicity": toxicity}


class ToxicitySentimentEnricher:
    """
    Pipeline stage that augments a `SocialEvent` with sentiment/toxicity fields.
    """

    def __init__(self, model: SentimentModel | None = None, toxicity_threshold: float = 0.8):
        self.model = model or HeuristicSentimentModel()
        self.toxicity_threshold = toxicity_threshold

    def enrich(self, event: SocialEvent) -> SocialEvent:
        scores = self.model.score(event.text)

        # Copy is required because SocialEvent is frozen (immutable)
        mutated = dict(asdict(event))
        mutated.update(scores)
        mutated["is_toxic"] = scores["toxicity"] >= self.toxicity_threshold
        enriched = SocialEvent(**mutated)  # type: ignore[arg-type]

        logger.debug(
            "Enriched event %s with scores %s (toxic=%s)",
            event.id,
            scores,
            enriched.meta.get("is_toxic"),
        )
        return enriched


# ------------------------------------------------------------------------------
# Observer pattern for metrics & error tracking
# ------------------------------------------------------------------------------


class EventObserver(Protocol):
    """Defines a contract for subscribers interested in post-processing updates."""

    def update(self, event: SocialEvent) -> None: ...


class PrometheusObserver:
    """
    Emits prometheus metrics for processed events, sentiment and toxicity levels.
    """

    def __init__(self) -> None:
        if Counter is None:
            raise RuntimeError(
                "prometheus_client is not installed — cannot use PrometheusObserver"
            )

        # Metrics are registered in the default registry
        self.total_events = Counter(
            "pulstream_events_total",
            "Total number of events processed by module_63",
            ["network"],
        )
        self.toxic_events = Counter(
            "pulstream_toxic_events_total",
            "Number of events flagged as toxic",
            ["network"],
        )
        self.sentiment_histogram = Histogram(
            "pulstream_sentiment_score",
            "Histogram of sentiment scores (−1 … 1)",
            buckets=[-1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1],
            labelnames=["network"],
        )

    def update(self, event: SocialEvent) -> None:
        self.total_events.labels(event.network).inc()
        if getattr(event, "is_toxic", False):
            self.toxic_events.labels(event.network).inc()
        sentiment_score = getattr(event, "sentiment", 0.0)
        self.sentiment_histogram.labels(event.network).observe(sentiment_score)


class SentryObserver:
    """
    Sends enriched events that exceed a toxicity threshold to Sentry as breadcrumbs
    or issues for trust-and-safety teams to audit.
    """

    def __init__(self, dsn: str | None = None) -> None:
        if sentry_sdk is None:
            raise RuntimeError("sentry_sdk not available in environment")
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0)  # disable perf tracing

    def update(self, event: SocialEvent) -> None:
        if getattr(event, "is_toxic", False):
            sentry_sdk.capture_message(
                f"Toxic event detected ({event.network}): {event.id}",
                level="warning",
            )
        # Push event info as breadcrumb for context
        sentry_sdk.add_breadcrumb(
            category="social_event",
            message=event.text[:140],
            data={"id": event.id, "network": event.network},
            level="info",
        )


# ------------------------------------------------------------------------------
# Dispatcher (Observer coordinator)
# ------------------------------------------------------------------------------


class EventDispatcher:
    """
    Observer hub. Maintains a registry of observers and dispatches events.
    """

    _observers: List[EventObserver]

    def __init__(self, observers: Sequence[EventObserver] | None = None):
        self._observers = list(observers or [])

    def register(self, observer: EventObserver) -> None:
        self._observers.append(observer)

    def dispatch(self, event: SocialEvent) -> None:
        for observer in self._observers:
            try:
                observer.update(event)
            except Exception:
                logger.exception("Observer %s threw while handling event %s", observer, event.id)


# ------------------------------------------------------------------------------
# ETL-like processing pipeline
# ------------------------------------------------------------------------------


class PipelineError(RuntimeError):
    """Raised on unrecoverable pipeline failures."""


class SimpleETLPipeline:
    """
    A very small ETL pipeline bucket that:

    1. Validates raw event dictionaries (Extract).
    2. Converts to domain object (Transform).
    3. Enriches with sentiment/toxicity (Transform).
    4. Pushes to observers (Load).

    This class is intentionally synchronous & single-threaded. In production,
    it would be wrapped by a Kafka or Beam consumer to process in parallel.
    """

    def __init__(
        self,
        validator: ValidationStrategy | None = None,
        enricher: ToxicitySentimentEnricher | None = None,
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        self.validator = validator or PydanticValidationStrategy()  # type: ignore
        self.enricher = enricher or ToxicitySentimentEnricher()
        self.dispatcher = dispatcher or EventDispatcher()

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def process_stream(self, raw_events: Iterable[MutableMapping[str, Any]]) -> List[SocialEvent]:
        """
        Consume an iterable of raw events, apply validation & enrichment,
        and notify all observers.

        Returns
        -------
        List[SocialEvent]
            List of fully-processed (enriched) events. Retained for the caller's
            convenience; in a real stream processor, they would be forwarded to
            downstream Kafka topics or data sinks.
        """
        processed: List[SocialEvent] = []

        for raw in raw_events:
            try:
                logger.debug("Processing raw event: %s", raw)
                validated = self.validator.validate(raw)
                event = SocialEvent(**validated)
                enriched_event = self.enricher.enrich(event)
                self.dispatcher.dispatch(enriched_event)
                processed.append(enriched_event)
            except Exception as exc:
                logger.warning("Event dropped due to error: %s", exc, exc_info=logger.isEnabledFor(logging.DEBUG))
                # Depending on the severity, re-raise or continue. Here, we skip bad events.
                continue

        logger.info("Processed %d events (success)", len(processed))
        return processed


# ------------------------------------------------------------------------------
# Convenience CLI (for local smoke tests)
# ------------------------------------------------------------------------------

def _bootstrap_prometheus() -> None:
    """Expose prometheus metrics on :8000/metrics for `prometheus_client`."""
    if Counter is None:
        return
    from prometheus_client import start_http_server  # type: ignore

    port = int(os.environ.get("PULSTREAM_PROM_PORT", "8000"))
    start_http_server(port)
    logger.info("Prometheus metrics available on http://0.0.0.0:%d/metrics", port)


def _example_stream() -> List[Dict[str, Any]]:
    """Generate a small set of dummy events for demonstration purposes."""
    now_ms = int(time.time() * 1000)
    return [
        {
            "id": "evt-1",
            "network": "twitter",
            "author_id": "u123",
            "text": "I love this new open-source project! It's fantastic 😊",
            "timestamp_ms": now_ms,
            "meta": {"lang": "en"},
        },
        {
            "id": "evt-2",
            "network": "reddit",
            "author_id": "u456",
            "text": "This update sucks. Worst release ever. I hate it.",
            "timestamp_ms": now_ms,
            "meta": {"subreddit": "python"},
        },
        # malformed event – will be dropped
        {
            "id": "evt-3",
            "network": "discord",
            "author_id": "u789",
            # Missing 'text' field!
            "timestamp_ms": now_ms,
            "meta": {},
        },
    ]


def main() -> None:  # pragma: no cover
    """Run a tiny stand-alone demo if the module is executed as a script."""
    if Counter is not None:
        _bootstrap_prometheus()

    observers: List[EventObserver] = []

    if Counter is not None:
        observers.append(PrometheusObserver())

    if sentry_sdk is not None and os.getenv("SENTRY_DSN"):
        observers.append(SentryObserver(dsn=os.environ["SENTRY_DSN"]))

    pipeline = SimpleETLPipeline(dispatcher=EventDispatcher(observers))

    processed_events = pipeline.process_stream(_example_stream())

    for evt in processed_events:
        logger.info("Final event: %s", evt.to_json())


# ------------------------------------------------------------------------------
# Export public symbols
# ------------------------------------------------------------------------------

__all__ = [
    # Domain
    "SocialEvent",
    # Validation
    "ValidationStrategy",
    "PydanticValidationStrategy",
    "NullValidationStrategy",
    # Enrichment
    "ToxicitySentimentEnricher",
    "SentimentModel",
    "HeuristicSentimentModel",
    # Monitoring
    "EventObserver",
    "PrometheusObserver",
    "SentryObserver",
    # Pipeline
    "SimpleETLPipeline",
    "PipelineError",
    # Dispatcher
    "EventDispatcher",
]

if __name__ == "__main__":  # pragma: no cover
    main()
```