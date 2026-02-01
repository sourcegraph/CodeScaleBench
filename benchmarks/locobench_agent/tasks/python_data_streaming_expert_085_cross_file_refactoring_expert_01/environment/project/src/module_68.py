```python
"""
PulseStream Nexus – Transformation Strategy Framework
=====================================================

This module implements a Strategy-Pattern–based framework that enriches raw
social-stream events with higher-level signals (sentiment, toxicity, virality
scores, etc.).  It is deliberately self-contained so it can be embedded in
either streaming micro-services (Kafka consumers) or in batch Spark/Beam jobs
without code changes.

Key Capabilities
----------------
* StrategyPattern – Plug-and-play enrichment algorithms
* ObserverPattern – Hook system for downstream subscribers (metrics, logging)
* Prometheus Integration – Latency / error counters (optional dependency)
* Async-Friendly – Can be driven by `async for` pipelines

External, *optional* dependencies are auto-detected at run-time.  The module
functions even when they are missing, although advanced features will be
disabled.

"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import (
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Dict,
    Final,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Type,
)

LOGGER: Final = logging.getLogger("pulstream.transformation")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03dZ  %(levelname)s  %(name)s – %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

try:
    # optional dependency
    from prometheus_client import Counter, Histogram  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    Counter = Histogram = None  # type: ignore


try:
    # optional dependency
    from textblob import TextBlob  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    TextBlob = None  # type: ignore


# --------------------------------------------------------------------------- #
# Domain Objects
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class SocialEvent:
    """
    A minimally viable social-stream event used across PulseStream Nexus.
    """

    event_id: str
    network: str
    user_id: str
    content: str
    timestamp: float
    metadata: MutableMapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TransformationReport:
    """
    Advisory object emitted by strategies to summarize side-effects & scores.
    Useful for analytics dashboards and ML training.
    """

    strategy: str
    scores: Mapping[str, float]
    processing_ms: float
    extra: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Strategy Pattern Interface
# --------------------------------------------------------------------------- #


class TransformationStrategy(abc.ABC):
    """
    An abstract enrichment step.  Implementations MUST be stateless or at
    least thread-safe; they will often be reused across greenlets/threads.
    """

    name: str  # Human-friendly unique name

    @abc.abstractmethod
    def transform(
        self, event: SocialEvent
    ) -> Tuple[SocialEvent, TransformationReport]:
        """
        Enrich the event synchronously.

        Returns
        -------
        Tuple[SocialEvent, TransformationReport]
            The (possibly mutated) event and an accompanying report.
        """
        raise NotImplementedError

    async def transform_async(
        self, event: SocialEvent
    ) -> Tuple[SocialEvent, TransformationReport]:
        """
        Async wrapper – may be overridden for truly async operations (e.g. HTTP
        calls).  By default simply delegates to sync method.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.transform, event)

    # Factories ----------------------------------------------------------------

    @classmethod
    def register(cls, impl: Type["TransformationStrategy"]) -> Type[
        "TransformationStrategy"
    ]:
        """
        Register a strategy subclass globally, so it can be resolved from
        configuration files or CLI flags.
        """
        _STRATEGY_REGISTRY[impl.name] = impl
        return impl

    @classmethod
    def from_name(cls, name: str) -> "TransformationStrategy":
        if name not in _STRATEGY_REGISTRY:
            raise KeyError(f"Unknown strategy '{name}'")
        return _STRATEGY_REGISTRY[name]()  # type: ignore[call-arg]


_STRATEGY_REGISTRY: Dict[str, Type[TransformationStrategy]] = {}

# --------------------------------------------------------------------------- #
# Built-in Strategy Implementations
# --------------------------------------------------------------------------- #


@TransformationStrategy.register
class SentimentStrategy(TransformationStrategy):
    """
    Sentiment analysis leveraging TextBlob if available; otherwise, falls back
    to a naive keyword-based heuristic.
    """

    name = "sentiment"

    POSITIVE_WORDS: Final[Sequence[str]] = (
        "great",
        "good",
        "awesome",
        "fantastic",
        "love",
        "like",
        "win",
    )
    NEGATIVE_WORDS: Final[Sequence[str]] = (
        "bad",
        "terrible",
        "hate",
        "awful",
        "loser",
        "worst",
        "sad",
    )

    def _heuristic_polarity(self, text: str) -> float:
        # crude count of positive vs. negative words; normalized to [-1, 1]
        text_lower = text.lower()
        pos = sum(word in text_lower for word in self.POSITIVE_WORDS)
        neg = sum(word in text_lower for word in self.NEGATIVE_WORDS)
        if pos + neg == 0:
            return 0.0
        return (pos - neg) / (pos + neg)

    def transform(
        self, event: SocialEvent
    ) -> Tuple[SocialEvent, TransformationReport]:
        start = time.perf_counter()
        if TextBlob:  # happy path
            polarity = float(TextBlob(event.content).sentiment.polarity)
        else:
            polarity = self._heuristic_polarity(event.content)

        event.metadata["sentiment"] = polarity
        elapsed = (time.perf_counter() - start) * 1000.0  # ms
        report = TransformationReport(
            strategy=self.name,
            scores={"polarity": polarity},
            processing_ms=elapsed,
        )
        return event, report


@TransformationStrategy.register
class ToxicityStrategy(TransformationStrategy):
    """
    Naive implementation built on a curated list of toxic keywords.  In the
    real PulseStream deployment this is replaced by a TensorFlow or Perspective
    API backend.
    """

    name = "toxicity"

    # A non-exhaustive list obviously; placeholder for demonstration purposes.
    TOXIC_PHRASES: Final[Sequence[str]] = (
        "kill yourself",
        "kys",
        "idiot",
        "trash",
        "stupid",
        "moron",
        "racist",
        "bigot",
    )

    def transform(
        self, event: SocialEvent
    ) -> Tuple[SocialEvent, TransformationReport]:
        start = time.perf_counter()
        text_lower = event.content.lower()
        hits = [phrase for phrase in self.TOXIC_PHRASES if phrase in text_lower]
        score = min(len(hits) * 0.25, 1.0)  # cap at 1.0
        event.metadata["toxicity"] = score

        elapsed = (time.perf_counter() - start) * 1_000.0
        report = TransformationReport(
            strategy=self.name,
            scores={"toxicity": score},
            processing_ms=elapsed,
            extra={"hits": hits},
        )
        return event, report


@TransformationStrategy.register
class ViralityStrategy(TransformationStrategy):
    """
    Quick-and-dirty virality predictor based on user metadata and message
    attributes.  Real implementation would rely on network-wide graphs.
    """

    name = "virality"

    def transform(
        self, event: SocialEvent
    ) -> Tuple[SocialEvent, TransformationReport]:
        start = time.perf_counter()

        length_score = min(len(event.content) / 280.0, 1.0)
        richness_score = 1.0 if any(
            token in event.content for token in ("#", "@", "http")
        ) else 0.0
        aggregated = mean((length_score, richness_score))
        event.metadata["virality"] = aggregated

        elapsed = (time.perf_counter() - start) * 1_000.0
        report = TransformationReport(
            strategy=self.name,
            scores={
                "length": length_score,
                "richness": richness_score,
                "virality": aggregated,
            },
            processing_ms=elapsed,
        )
        return event, report


# --------------------------------------------------------------------------- #
# Observer Pattern – Result Subscribers
# --------------------------------------------------------------------------- #


class TransformationObserver(Protocol):
    """
    Observer interface; implement `.notify(event, report)` to react to
    transformation outputs (e.g. send to Kafka, push metrics, etc.).
    """

    async def notify(self, event: SocialEvent, report: TransformationReport) -> None:
        ...


class LoggingObserver:
    """
    Default observer that logs every report.  Suitable for debugging, but will
    produce a lot of output under high TPS.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or LOGGER

    async def notify(self, event: SocialEvent, report: TransformationReport) -> None:
        self._logger.debug(
            "Event %s – %s: %s (%.1f ms)",
            event.event_id,
            report.strategy,
            report.scores,
            report.processing_ms,
        )


class MetricsObserver:
    """
    Pushes runtime metrics to Prometheus, if the `prometheus_client` package is
    available.
    """

    _COUNTER_CACHE: Dict[str, Counter] = {}
    _LATENCY_CACHE: Dict[str, Histogram] = {}

    def __init__(self) -> None:
        if Counter is None or Histogram is None:  # pragma: no cover
            raise RuntimeError(
                "`prometheus_client` not installed; MetricsObserver unavailable."
            )

    async def notify(self, event: SocialEvent, report: TransformationReport) -> None:
        counter = self._COUNTER_CACHE.get(report.strategy)
        latency = self._LATENCY_CACHE.get(report.strategy)

        if counter is None:
            counter = Counter(
                f"psn_{report.strategy}_total",
                f"Total events processed by {report.strategy}",
            )
            self._COUNTER_CACHE[report.strategy] = counter

        if latency is None:
            latency = Histogram(
                f"psn_{report.strategy}_latency_ms",
                f"Processing latency (ms) for {report.strategy}",
                buckets=(1, 2, 5, 10, 20, 50, 100, 250, 500, 1000),
            )
            self._LATENCY_CACHE[report.strategy] = latency

        counter.inc()
        latency.observe(report.processing_ms)


# --------------------------------------------------------------------------- #
# Pipeline Runner
# --------------------------------------------------------------------------- #


class TransformationPipeline:
    """
    Orchestrates a sequence of strategies and observers.  Reusable by both
    batch jobs (`run_iterable`) and async streaming code (`run_async`).

    Example
    -------
    >>> pipeline = TransformationPipeline(strategies=['sentiment', 'toxicity'])
    >>> for enriched_event, reports in pipeline.run_iterable(events):
    ...     handle(enriched_event)
    """

    def __init__(
        self,
        strategies: Sequence[str | TransformationStrategy] | None = None,
        observers: Sequence[TransformationObserver] | None = None,
    ) -> None:
        if not strategies:
            strategies = ["sentiment"]  # sensible default
        self._strategies: List[TransformationStrategy] = [
            s if isinstance(s, TransformationStrategy) else TransformationStrategy.from_name(s)
            for s in strategies
        ]
        self._observers: List[TransformationObserver] = list(
            observers or [LoggingObserver()]
        )

    # Synchronous -------------------------------------------------------------

    def run_iterable(
        self, events: Iterable[SocialEvent]
    ) -> Iterable[Tuple[SocialEvent, List[TransformationReport]]]:
        """
        Process a finite iterable; yields `(event, [reports])` per input.

        Raises exceptions as-is, so callers can retry or abort.
        """
        for event in events:
            reports: List[TransformationReport] = []
            for strategy in self._strategies:
                try:
                    event, report = strategy.transform(event)
                    reports.append(report)
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.exception(
                        "Transformation error [%s] for event %s: %s",
                        strategy.name,
                        event.event_id,
                        exc,
                    )
            # notify observers
            for observer in self._observers:
                for report in reports:
                    asyncio.run(observer.notify(event, report))
            yield event, reports

    # Async -------------------------------------------------------------------

    async def run_async(
        self, events: AsyncIterable[SocialEvent]
    ) -> AsyncIterable[Tuple[SocialEvent, List[TransformationReport]]]:
        """
        Async generator version; suitable for high-volume Kafka consumers.
        """
        async for event in events:
            reports: List[TransformationReport] = []
            for strategy in self._strategies:
                try:
                    event, report = await strategy.transform_async(event)
                    reports.append(report)
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.exception(
                        "Transformation error [%s] for event %s: %s",
                        strategy.name,
                        event.event_id,
                        exc,
                    )
            # observers
            await asyncio.gather(
                *(
                    observer.notify(event, report)
                    for observer in self._observers
                    for report in reports
                ),
                return_exceptions=True,
            )
            yield event, reports


# --------------------------------------------------------------------------- #
# Helper – Demo CLI Entrypoint
# --------------------------------------------------------------------------- #

def _demo_events() -> List[SocialEvent]:
    import uuid
    sample_texts = [
        "I absolutely love this! 🥳 #excited",
        "kys idiot",
        "Check this out http://example.com",
        "This is the worst product ever.",
    ]
    ts = time.time()
    return [
        SocialEvent(
            event_id=str(uuid.uuid4()),
            network="twitter",
            user_id=f"user_{i}",
            content=text,
            timestamp=ts + i,
        )
        for i, text in enumerate(sample_texts)
    ]


def _run_demo() -> None:  # pragma: no cover
    pipeline = TransformationPipeline(
        strategies=["sentiment", "toxicity", "virality"],
        observers=[LoggingObserver()],
    )
    for evt, rep in pipeline.run_iterable(_demo_events()):
        print(
            f"\n{evt.content!r}\nmeta={evt.metadata}\n"
            + ", ".join(f"{r.strategy}={r.scores}" for r in rep)
        )


if __name__ == "__main__":  # pragma: no cover
    _run_demo()
```