```python
"""
src/module_50.py

PulseStream Nexus – Data Streaming Platform
-------------------------------------------

This module implements a production-grade, pluggable *Transformation Pipeline*
that ❶ validates incoming social-network events, ❷ enriches them through a
chain-of-responsibility of *Strategy* objects (sentiment, toxicity, virality,
etc.), and ❸ emits the final artefacts to interested *Observers* (e.g.
Prometheus, Kafka, Grafana dashboards).

Design patterns utilised
~~~~~~~~~~~~~~~~~~~~~~~~
1. Clean Architecture: Business rules are isolated from I/O.
2. Strategy Pattern : Each transformation is a strategy.
3. Observer Pattern : Observers react to pipeline results.
4. Pipeline Pattern : Ordered execution of strategies.

External libraries required
~~~~~~~~~~~~~~~~~~~~~~~~~~~
pydantic        – schema validation
textblob        – sentiment (optional; gracefully degraded)
prometheus-client – metrics (optional)
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import ModuleType
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Protocol,
    Sequence,
)

try:
    from prometheus_client import Counter  # type: ignore
except ImportError:  # pragma: no cover – metrics are optional
    Counter = None  # pylint: disable=invalid-name

from pydantic import BaseModel, Field, ValidationError

# -----------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------
LOGGER = logging.getLogger("pulse_stream.pipeline")
if not LOGGER.handlers:  # Avoid duplicate handlers in some REPLs
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(name)s] %(funcName)s:%(lineno)d | %(message)s"
        )
    )
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)


# -----------------------------------------------------------
# Domain Model
# -----------------------------------------------------------
class SocialEvent(BaseModel):
    """
    Canonical schema for an incoming social event.
    Only essential fields for demo purposes.
    """

    event_id: str = Field(..., description="Unique identifier for the social event")
    network: str = Field(..., description="Social network source, e.g., twitter, reddit")
    author_id: str
    content: str
    created_at: float  # Unix timestamp
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Enriched/derived fields
    sentiment: Optional[float] = None
    toxicity: Optional[float] = None
    virality_score: Optional[float] = None


# -----------------------------------------------------------
# Strategy Pattern – Transformation Strategies
# -----------------------------------------------------------
class TransformationStrategy(ABC):
    """Abstract transformation strategy."""

    @abstractmethod
    async def transform(self, event: SocialEvent) -> SocialEvent:
        """Perform an in-place or new-object transformation and return it."""


class SentimentStrategy(TransformationStrategy):
    """Compute sentiment via TextBlob if available."""

    def __init__(self) -> None:
        try:
            from textblob import TextBlob  # pylint: disable=import-error
        except ImportError as exc:  # pragma: no cover
            LOGGER.warning(
                "TextBlob is not available. Sentiment strategy will be skipped."
            )
            self._blob_cls: Optional[ModuleType] = None
            self._err = exc
        else:
            self._blob_cls = TextBlob
            self._err = None

    async def transform(self, event: SocialEvent) -> SocialEvent:
        if not self._blob_cls:
            LOGGER.debug("SentimentStrategy skipped due to missing dependency.")
            return event

        # TextBlob is CPU-bound; offload to executor to avoid blocking loop
        loop = asyncio.get_running_loop()
        blob = await loop.run_in_executor(None, self._blob_cls, event.content)
        polarity: float = blob.sentiment.polarity  # type: ignore[attr-defined]
        event.sentiment = polarity
        LOGGER.debug("Sentiment computed: %.3f for event %s", polarity, event.event_id)
        return event


class ToxicityStrategy(TransformationStrategy):
    """Placeholder toxicity calculation. Replace with real ML model call."""

    async def transform(self, event: SocialEvent) -> SocialEvent:
        # Dummy implementation; a real one would call a Detoxify-like model
        event.toxicity = min(len(event.content) / 280.0, 1.0)
        LOGGER.debug(
            "Toxicity approximated: %.3f for event %s", event.toxicity, event.event_id
        )
        return event


class ViralityStrategy(TransformationStrategy):
    """Compute a naive virality score based on metadata signals."""

    async def transform(self, event: SocialEvent) -> SocialEvent:
        meta = event.metadata
        likes = meta.get("likes", 0)
        shares = meta.get("shares", 0)
        comments = meta.get("comments", 0)
        score = (likes + 2 * shares + 0.5 * comments) / 100.0
        event.virality_score = round(score, 3)
        LOGGER.debug(
            "Virality score %.3f computed for event %s", score, event.event_id
        )
        return event


# -----------------------------------------------------------
# Observer Pattern – Metrics & Logging
# -----------------------------------------------------------
class EventObserver(Protocol):
    """Observer interface (duck-typed, no inheritance required)."""

    async def notify(self, event: SocialEvent) -> None:  # pragma: no cover
        ...


@dataclass
class LoggingObserver:
    """Simply logs the transformed event."""

    level: int = logging.DEBUG

    async def notify(self, event: SocialEvent) -> None:
        LOGGER.log(self.level, "Observer saw event: %s", event.json())


@dataclass
class PrometheusObserver:
    """
    Push success/error counters to Prometheus.

    Requires `prometheus_client` – gracefully disabled if missing.
    """

    _succ_counter: Optional[Any] = None
    _err_counter: Optional[Any] = None

    def __post_init__(self) -> None:
        if Counter is None:
            LOGGER.warning(
                "prometheus_client not installed. PrometheusObserver disabled."
            )
            return
        self._succ_counter = Counter(
            "pulsestream_transform_success_total",
            "Number of successfully transformed events",
        )
        self._err_counter = Counter(
            "pulsestream_transform_error_total",
            "Number of events that failed transformation",
        )

    async def notify(self, event: SocialEvent) -> None:  # type: ignore[override]
        if self._succ_counter:
            self._succ_counter.inc()


# -----------------------------------------------------------
# Pipeline Configuration & Execution
# -----------------------------------------------------------
@dataclass(frozen=True)
class PipelineConfig:
    """
    Configuration object determining which strategies & observers are applied.
    """

    strategies: Sequence[str] = (
        "SentimentStrategy",
        "ToxicityStrategy",
        "ViralityStrategy",
    )
    observers: Sequence[str] = (
        "LoggingObserver",
        "PrometheusObserver",
    )

    def instantiate_strategies(self) -> List[TransformationStrategy]:
        return [self._load_component(name, strategy=True) for name in self.strategies]

    def instantiate_observers(self) -> List[EventObserver]:
        return [self._load_component(name, strategy=False) for name in self.observers]

    @staticmethod
    def _load_component(name: str, *, strategy: bool) -> Any:  # noqa: ANN401
        """
        Dynamically import & instantiate component classes by name
        within this module's namespace.
        """
        try:
            cls: type = globals()[name]
        except KeyError as exc:
            raise ImportError(f"Component {name} not found.") from exc

        if strategy and not issubclass(cls, TransformationStrategy):
            raise TypeError(f"{name} is not a valid TransformationStrategy.")
        if not strategy and not hasattr(cls, "notify"):
            raise TypeError(f"{name} is not a valid EventObserver.")

        return cls()  # type: ignore[call-arg]


# -----------------------------------------------------------
# Public API – Async Pipeline
# -----------------------------------------------------------
class TransformationPipeline:
    """
    Orchestrates strategy execution & observer notification.
    """

    def __init__(self, config: Optional[PipelineConfig] = None) -> None:
        self.config = config or PipelineConfig()
        self.strategies: List[TransformationStrategy] = (
            self.config.instantiate_strategies()
        )
        self.observers: List[EventObserver] = self.config.instantiate_observers()
        LOGGER.info(
            "Pipeline initialised with %d strategies, %d observers",
            len(self.strategies),
            len(self.observers),
        )

    async def process_stream(
        self, stream: AsyncGenerator[Dict[str, Any], None]
    ) -> AsyncGenerator[SocialEvent, None]:
        """
        Validate raw dictionaries, execute transformation chain,
        and yield enriched SocialEvent objects.

        Errors in individual events are logged and skipped; the stream
        continues unaffected (fail-soft behaviour).
        """

        async for raw_event in stream:
            try:
                event = self._validate(raw_event)
                start = time.perf_counter()

                for strategy in self.strategies:
                    event = await strategy.transform(event)

                # Dispatch to observers (fire-and-forget)
                await asyncio.gather(
                    *(observer.notify(event) for observer in self.observers),
                    return_exceptions=True,
                )

                LOGGER.debug(
                    "Event %s processed in %.2f ms",
                    event.event_id,
                    (time.perf_counter() - start) * 1000,
                )
                yield event

            except ValidationError as exc:
                LOGGER.error(
                    "Schema validation failed for raw event %s: %s", raw_event, exc
                )
                self._notify_error()
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.exception("Unhandled exception during processing: %s", exc)
                self._notify_error()

    # -------------------------------------------------------
    # Internal helper methods
    # -------------------------------------------------------
    @staticmethod
    def _validate(raw_event: Dict[str, Any]) -> SocialEvent:
        event = SocialEvent.parse_obj(raw_event)
        LOGGER.debug("Validated event %s", event.event_id)
        return event

    def _notify_error(self) -> None:
        for obs in self.observers:
            if isinstance(obs, PrometheusObserver) and obs._err_counter:
                obs._err_counter.inc()


# -----------------------------------------------------------
# Convenience Utilities
# -----------------------------------------------------------
async def run_pipeline_on_iterable(
    iterable: Iterable[Dict[str, Any]],
    *,
    config: Optional[PipelineConfig] = None,
) -> List[SocialEvent]:
    """
    Synchronous convenience wrapper to process a finite iterable of raw events.
    Intended primarily for unit tests and ad-hoc scripts.
    """

    async def _gen() -> AsyncGenerator[Dict[str, Any], None]:
        for item in iterable:
            yield item

    pipeline = TransformationPipeline(config)
    results: List[SocialEvent] = []
    async for transformed in pipeline.process_stream(_gen()):
        results.append(transformed)
    return results


# -----------------------------------------------------------
# Example runnable entry-point (debug/demo only)
# -----------------------------------------------------------
if __name__ == "__main__":
    async def _demo() -> None:
        sample_events = [
            {
                "event_id": "e1",
                "network": "twitter",
                "author_id": "u123",
                "content": "I love PulseStream! Amazing day.",
                "created_at": time.time(),
                "metadata": {"likes": 42, "shares": 10, "comments": 3},
            },
            {
                # Invalid event to show validation error handling
                "event_id": "e2",
                "network": "reddit",
                "author_id": "u456",
                "content": "Missing timestamp!",
            },
        ]

        results = await run_pipeline_on_iterable(sample_events)
        for ev in results:
            print(ev.json(indent=2))

    asyncio.run(_demo())
```