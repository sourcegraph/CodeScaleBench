```python
"""
PulseStream Nexus – module_45
Author: PulseStream Nexus Core Team

This module implements a transformation subsystem that can be plugged into the
overall PulseStream ETL/ELT pipeline.  It demonstrates the Strategy and Observer
patterns while adhering to the Clean-Architecture philosophy (pure domain code,
framework-agnostic, fully testable).

Key responsibilities
--------------------
1. Validation:
   • Pydantic models ensure schema correctness for inbound social events.

2. Transformation:
   • BaseTransformer (Strategy) provides an interface for data enrichment.
   • ToxicitySentimentTransformer computes sentiment polarity and toxicity
     scores and annotates events in-place.

3. Observability:
   • Prometheus metrics (counters + histograms).
   • Structured logging (structlog) with contextual information.
   • Simple event hooks (Observer) for downstream subscribers.

4. Error handling:
   • Custom exceptions map operational faults to domain errors without leaking
     third-party details.
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, Iterable, List, Optional

import structlog
from better_profanity import profanity
from pydantic import BaseModel, Field, ValidationError
from prometheus_client import Counter, Histogram
from textblob import TextBlob

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

DEFAULT_MAX_WORKERS: int = int(os.getenv("PULSESTREAM_MAX_WORKERS", "4"))
SENTIMENT_MODEL: str = os.getenv("PULSESTREAM_SENTIMENT_MODEL", "textblob")
TOKEN_LIMIT: int = int(os.getenv("PULSESTREAM_CONTENT_TOKEN_LIMIT", "512"))

# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        min_level=os.getenv("LOG_LEVEL", "INFO").upper()
    ),
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger(module="module_45")

# --------------------------------------------------------------------------- #
# Prometheus metrics                                                          #
# --------------------------------------------------------------------------- #

_METRIC_PREFIX = "pulse_module45"

transform_counter = Counter(
    name=f"{_METRIC_PREFIX}_events_transformed_total",
    documentation="Total number of events successfully transformed",
    labelnames=("transformer",),
)

transform_errors = Counter(
    name=f"{_METRIC_PREFIX}_errors_total",
    documentation="Total number of transformation errors",
    labelnames=("transformer", "error_type"),
)

transform_latency = Histogram(
    name=f"{_METRIC_PREFIX}_transform_latency_seconds",
    documentation="Latency of transformations in seconds",
    labelnames=("transformer",),
    buckets=(
        0.001,
        0.01,
        0.05,
        0.1,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
        float("inf"),
    ),
)

# --------------------------------------------------------------------------- #
# Domain models                                                               #
# --------------------------------------------------------------------------- #


class SocialEvent(BaseModel):
    """Pure immutable representation of a social interaction event."""

    event_id: str = Field(..., alias="id")
    platform: str
    user_id: str
    content: str = Field(..., max_length=TOKEN_LIMIT)
    timestamp: _dt.datetime
    metadata: Dict[str, str] = Field(default_factory=dict)

    class Config:
        allow_population_by_field_name = True
        frozen = True


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #


class TransformationError(RuntimeError):
    """Raised when a transformer fails irrecoverably."""


class ValidationException(TransformationError):
    """Raised when incoming data fails validation."""


# --------------------------------------------------------------------------- #
# Observer pattern                                                            #
# --------------------------------------------------------------------------- #


class EventHook:
    """A light-weight Observer allowing subscribers to be notified."""

    def __init__(self) -> None:
        self._subscribers: List[Callable[[SocialEvent], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: Callable[[SocialEvent], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def fire(self, event: SocialEvent) -> None:
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "event_hook_callback_failed",
                    callback=callback.__name__,
                    exc=str(exc),
                )


# --------------------------------------------------------------------------- #
# Strategy pattern – Transformation                                           #
# --------------------------------------------------------------------------- #


class BaseTransformer(ABC):
    """
    Abstract base class every transformation strategy must implement.
    """

    name: str

    def __init__(self) -> None:
        self.after_transform = EventHook()

    @abstractmethod
    def transform(self, event: SocialEvent) -> SocialEvent:  # noqa: D401
        """
        Perform an in-place or copy-based transformation of the event.

        Returns
        -------
        SocialEvent
            The (possibly) modified event.
        """
        raise NotImplementedError


class ToxicitySentimentTransformer(BaseTransformer):
    """
    Enriches events with toxicity and sentiment attributes.
    """

    name = "toxicity_sentiment"

    def __init__(
        self,
        *,
        profanity_threshold: float = 0.1,
        polarity_threshold: float = 0.05,
    ) -> None:
        super().__init__()
        self.profanity_threshold = profanity_threshold
        self.polarity_threshold = polarity_threshold

        # Ensure profanity list is initialized; idempotent call
        profanity.load_censor_words()

    def _detect_toxicity(self, content: str) -> float:
        """
        Very naive toxicity proxy leveraging profanity ratio.
        """
        censored = profanity.censor(content)
        # ratio of censored characters versus original as toxicity proxy
        diff = sum(1 for a, b in zip(content, censored) if a != b)
        ratio = diff / max(len(content), 1)
        return ratio

    def _compute_sentiment(self, content: str) -> float:
        """
        Sentiment polarity using TextBlob (-1 negative, +1 positive).
        """
        blob = TextBlob(content)
        return blob.sentiment.polarity

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def transform(self, event: SocialEvent) -> SocialEvent:  # noqa: D401
        start = time.perf_counter()
        transformer_label = self.name

        try:
            toxicity = self._detect_toxicity(event.content)
            polarity = self._compute_sentiment(event.content)

            toxicity_flag = toxicity >= self.profanity_threshold
            sentiment_flag = abs(polarity) >= self.polarity_threshold

            # Construct a new metadata dict (immutable model)
            new_meta = {
                **event.metadata,
                "toxicity_score": f"{toxicity:.4f}",
                "sentiment_polarity": f"{polarity:.4f}",
                "is_toxic": str(toxicity_flag).lower(),
                "is_sentiment_strong": str(sentiment_flag).lower(),
                "sentiment_model": SENTIMENT_MODEL,
                "transformer_version": "1.0.0",
            }

            enriched_event = event.copy(update={"metadata": new_meta})
            transform_counter.labels(transformer_label).inc()
            self.after_transform.fire(enriched_event)
            return enriched_event
        except Exception as exc:  # noqa: BLE001
            transform_errors.labels(transformer_label, type(exc).__name__).inc()
            logger.exception(
                "transformation_failed",
                transformer=transformer_label,
                event_id=event.event_id,
            )
            raise TransformationError(str(exc)) from exc
        finally:
            latency = time.perf_counter() - start
            transform_latency.labels(transformer_label).observe(latency)


# --------------------------------------------------------------------------- #
# Orchestration – Transform Manager                                           #
# --------------------------------------------------------------------------- #


class TransformManager:
    """
    Coordinates a chain of transformers for a stream or batch of events.
    """

    def __init__(
        self,
        transformers: Iterable[BaseTransformer],
        *,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        self._transformers = list(transformers)
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

        logger.info(
            "transform_manager_initialized",
            transformers=[t.name for t in self._transformers],
            max_workers=max_workers,
        )

    # --------------------------------------------------------------------- #
    # Core processing                                                       #
    # --------------------------------------------------------------------- #

    def process_events(
        self, raw_events: Iterable[Dict[str, object]]
    ) -> List[SocialEvent]:
        """
        Validate and transform incoming raw events in parallel.

        Parameters
        ----------
        raw_events
            An iterable of raw dictionaries that represent social interactions.

        Returns
        -------
        List[SocialEvent]
            List of fully validated and enriched events.
        """
        validated_events: List[SocialEvent] = []
        futures = []

        for raw in raw_events:
            futures.append(self._pool.submit(self._validate_and_enrich, raw))

        for future in as_completed(futures):
            try:
                result = future.result()
                validated_events.append(result)
            except ValidationException as ve:
                logger.warning("discarding_invalid_event", error=str(ve))
            except TransformationError as te:
                logger.error("transformation_error_unhandled", error=str(te))

        return validated_events

    # --------------------------------------------------------------------- #
    # Helper logic                                                          #
    # --------------------------------------------------------------------- #

    def _validate_and_enrich(self, raw: Dict[str, object]) -> SocialEvent:
        try:
            event = SocialEvent.parse_obj(raw)
        except ValidationError as exc:
            transform_errors.labels("validator", "ValidationError").inc()
            logger.debug("validation_failed", raw=raw, errors=exc.errors())
            raise ValidationException(str(exc)) from exc

        # Pass through transformers sequentially
        for transformer in self._transformers:
            event = transformer.transform(event)

        return event

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)
        logger.info("transform_manager_shutdown", wait=wait)


# --------------------------------------------------------------------------- #
# Convenience factory                                                         #
# --------------------------------------------------------------------------- #


def default_transform_manager(
    *,
    toxicity_threshold: float = 0.1,
    polarity_threshold: float = 0.05,
    max_workers: Optional[int] = None,
) -> TransformManager:
    """
    Creates a default TransformManager with standard transformers.

    Use this helper in application code to stay DRY.
    """
    transformer = ToxicitySentimentTransformer(
        profanity_threshold=toxicity_threshold,
        polarity_threshold=polarity_threshold,
    )

    max_workers = max_workers or DEFAULT_MAX_WORKERS

    return TransformManager(
        transformers=[transformer],
        max_workers=max_workers,
    )


# --------------------------------------------------------------------------- #
# Entry point for manual testing                                              #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    # Example usage (manual kick-off, not used in production runner)
    example_events = [
        {
            "id": "evt-001",
            "platform": "twitter",
            "user_id": "u123",
            "content": "I absolutely love the new features! 😍",
            "timestamp": _dt.datetime.utcnow(),
            "metadata": {"lang": "en"},
        },
        {
            "id": "evt-002",
            "platform": "reddit",
            "user_id": "u456",
            "content": "This is bull****.",
            "timestamp": _dt.datetime.utcnow(),
            "metadata": {"lang": "en"},
        },
    ]

    manager = default_transform_manager()
    enriched = manager.process_events(example_events)
    for evt in enriched:
        print(evt.json(indent=2))

    manager.shutdown()
```