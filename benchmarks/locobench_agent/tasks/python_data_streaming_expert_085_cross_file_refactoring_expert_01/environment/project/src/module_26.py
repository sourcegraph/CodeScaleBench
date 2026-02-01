```python
"""
PulseStream Nexus – Sentiment Enrichment Module
===============================================

This module provides a production-ready SentimentEnricher service that
extends the ETL/ELT pipeline with configurable, strategy-based sentiment
analysis.  It demonstrates several of the architecture patterns used
throughout the project (Strategy, Observer, Pipeline) while remaining
infrastructure-agnostic so that it can be imported by either streaming
micro-services (Kafka) or batch jobs (Spark/Beam).

Key Features
------------
1. StrategyPattern: Multiple interchangeable sentiment analyzers
   (VADER, HuggingFace transformers, third-party APIs, etc.).
2. Data Validation: Strict message schema validation via Pydantic.
3. Monitoring / Observability: Prometheus metrics & structured logging.
4. Robustness: Exponential back-off retries (tenacity) and graceful
   degradation if the preferred analyzer is unavailable.
5. Async-friendly: Works inside asyncio event-loops and streaming
   consumers such as aiokafka without blocking.

Usage
-----
from src.module_26 import SentimentEnricher, HuggingFaceStrategy
enricher = SentimentEnricher(strategy=HuggingFaceStrategy())
async for enriched_event in enricher.enrich_stream(event_stream()):
    ...

Author: PulseStream Nexus Team
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Optional

import pydantic
from prometheus_client import Counter, Histogram
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

# ---------------------------------------------------------------------------#
# Configuration & Constants
# ---------------------------------------------------------------------------#

# Default HuggingFace model (lightweight; good for CPU inference).
HF_MODEL_NAME = os.getenv("PSN_HF_MODEL_NAME", "distilbert-base-uncased-finetuned-sst-2-english")

LOG_LEVEL = os.getenv("PSN_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("psn.sentiment_enricher")

# Prometheus metrics
SENTIMENT_SUCCESS = Counter(
    "psn_sentiment_success_total",
    "Number of successfully enriched messages",
    ["strategy"],
)
SENTIMENT_FAILURE = Counter(
    "psn_sentiment_failure_total",
    "Number of messages that failed enrichment",
    ["strategy", "exception"],
)
SENTIMENT_LATENCY = Histogram(
    "psn_sentiment_latency_seconds",
    "Latency of sentiment analysis in seconds",
    ["strategy"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

# ---------------------------------------------------------------------------#
# Domain Models
# ---------------------------------------------------------------------------#


class SocialEvent(pydantic.BaseModel):
    """
    Canonical event representation flowing through the pipeline.
    """

    event_id: str
    network: str  # e.g. "twitter", "reddit"
    user_id: str
    text: str
    created_at: pydantic.datetime.datetime

    # Optional enrichment fields
    sentiment: Optional[Dict[str, float]] = None

    class Config:
        allow_mutation = True
        json_encoders = {pydantic.datetime.datetime: lambda v: v.isoformat()}


# ---------------------------------------------------------------------------#
# Strategy Pattern – Sentiment Analyzers
# ---------------------------------------------------------------------------#


class SentimentAnalyzerStrategy(ABC):
    """
    Strategy interface for interchangeable sentiment analyzers.
    """

    name: str

    @abstractmethod
    async def analyze(self, text: str) -> Dict[str, float]:
        """
        Perform sentiment analysis on the supplied text.

        Returns
        -------
        Dict[str, float]
            A mapping with keys such as "positive", "negative", "neutral",
            or any model-specific score labels.
        """
        ...


class VADERStrategy(SentimentAnalyzerStrategy):
    """
    Lightweight, rule-based sentiment via NLTK's VADER.
    """

    name = "vader"

    def __init__(self) -> None:
        try:
            from nltk.sentiment.vader import SentimentIntensityAnalyzer

            self._analyzer = SentimentIntensityAnalyzer()
        except (LookupError, ModuleNotFoundError) as exc:
            logger.exception("NLTK resource download failed. Install or download VADER lexicon.")
            raise RuntimeError("VADERStrategy unavailable") from exc

    async def analyze(self, text: str) -> Dict[str, float]:
        # VADER is synchronous; wrap it in a thread pool to keep the event loop snappy
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(None, self._analyzer.polarity_scores, text)
        return scores  # Already in desired dict format


class HuggingFaceStrategy(SentimentAnalyzerStrategy):
    """
    Transformer-based sentiment leveraging HuggingFace pipelines.
    """

    name = "huggingface"

    def __init__(self, model_name: str = HF_MODEL_NAME, device: int = -1) -> None:
        from transformers import pipeline  # noqa: WPS433 (external import)

        # Lazy load heavy model to avoid blocking startup; done in thread pool later
        self._model_name = model_name
        self._device = device
        self._classifier = None

    async def _load(self) -> None:
        if self._classifier is None:
            logger.info("Loading HuggingFace sentiment model '%s' (device=%s)…", self._model_name, self._device)
            loop = asyncio.get_event_loop()
            from transformers import pipeline  # local import

            self._classifier = await loop.run_in_executor(
                None,
                lambda: pipeline("sentiment-analysis", model=self._model_name, device=self._device),
            )

    async def analyze(self, text: str) -> Dict[str, float]:
        await self._load()

        async def _infer() -> Dict[str, float]:
            result = self._classifier(text, truncation=True)[0]
            score_map = {
                result["label"].lower(): float(result["score"]),
            }
            return score_map

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _infer)


class DummyStrategy(SentimentAnalyzerStrategy):
    """
    Fallback strategy that always returns neutral sentiment.
    Useful when sentiment analysis models are not available.
    """

    name = "dummy"

    async def analyze(self, text: str) -> Dict[str, float]:  # noqa: D401 (imperative mood)
        return {"neutral": 1.0}


# ---------------------------------------------------------------------------#
# Sentiment Enricher – ETL Component
# ---------------------------------------------------------------------------#


class SentimentEnricher:
    """
    Reactive component that enriches `SocialEvent` objects with sentiment
    using the provided strategy. Designed for streaming pipelines.
    """

    def __init__(self, strategy: SentimentAnalyzerStrategy) -> None:
        self._strategy = strategy
        self._logger = logging.getLogger(f"psn.sentiment_enricher.{strategy.name}")

    # Tenacity retry: handle transient errors (e.g., model server hiccups)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _safe_analyze(self, text: str) -> Dict[str, float]:
        return await self._strategy.analyze(text)

    async def enrich_event(self, event: SocialEvent) -> SocialEvent:
        """
        Enrich a single event with sentiment scores.

        Raises
        ------
        RuntimeError
            If sentiment analysis ultimately fails after retries.
        """
        if event.sentiment is not None:
            # Already enriched; skip computation.
            return event

        self._logger.debug("Analyzing sentiment for event_id=%s", event.event_id)

        with SENTIMENT_LATENCY.labels(strategy=self._strategy.name).time():
            try:
                scores = await self._safe_analyze(event.text)
                event.sentiment = scores
                SENTIMENT_SUCCESS.labels(strategy=self._strategy.name).inc()
                self._logger.debug(
                    "Sentiment for event_id=%s computed: %s",
                    event.event_id,
                    json.dumps(scores),
                )
            except RetryError as err:
                last_exc = err.last_attempt.exception()  # type: ignore[assignment]
                SENTIMENT_FAILURE.labels(
                    strategy=self._strategy.name,
                    exception=type(last_exc).__name__,
                ).inc()
                self._logger.error(
                    "Sentiment analysis failed for event_id=%s after retries: %s",
                    event.event_id,
                    last_exc,
                    exc_info=True,
                )
                raise RuntimeError("Sentiment enrichment failed") from last_exc

        return event

    async def enrich_stream(self, stream: AsyncIterator[SocialEvent]) -> AsyncIterator[SocialEvent]:
        """
        Apply enrichment to an asynchronous stream of events.

        Example
        -------
        async for enriched in enricher.enrich_stream(kafka_consumer()):
            process(enriched)
        """
        async for event in stream:
            try:
                yield await self.enrich_event(event)
            except RuntimeError:
                # Swallow or redirect failed messages based on business rules.
                # Here, we simply continue to the next message.
                continue


# ---------------------------------------------------------------------------#
# Helper – Sample Async Generator (for demo/testing)
# ---------------------------------------------------------------------------#


async def _demo_event_stream() -> AsyncIterator[SocialEvent]:  # pragma: no cover
    """
    Yields a sequence of mock SocialEvent objects for demo purposes.
    """
    sample_texts = [
        "I absolutely love the new PulseStream features!",
        "Ugh, the latest update totally broke my workflow. Really disappointed.",
        "Meh, it's okay I guess. Nothing special.",
    ]
    import uuid
    import random
    import datetime as dt

    for text in sample_texts:
        yield SocialEvent(
            event_id=str(uuid.uuid4()),
            network=random.choice(["twitter", "reddit"]),
            user_id=str(uuid.uuid4()),
            text=text,
            created_at=dt.datetime.utcnow(),
        )
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------#
# CLI Entrypoint (python -m src.module_26)
# ---------------------------------------------------------------------------#


async def _main() -> None:  # pragma: no cover
    """
    Simple CLI entrypoint that enriches events from `_demo_event_stream`
    and prints them as pretty JSON. Intended for local smoke testing.
    """
    strategy_name = os.getenv("PSN_SENTIMENT_STRATEGY", "vader").lower()
    strategy_map = {
        "vader": VADERStrategy,
        "huggingface": HuggingFaceStrategy,
        "dummy": DummyStrategy,
    }

    strategy_cls = strategy_map.get(strategy_name, DummyStrategy)
    try:
        strategy = strategy_cls()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to initialize strategy '%s': %s; falling back to Dummy.", strategy_name, exc)
        strategy = DummyStrategy()

    enricher = SentimentEnricher(strategy=strategy)

    async for enriched in enricher.enrich_stream(_demo_event_stream()):
        print(json.dumps(enriched.dict(), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Sentiment enrichment demo interrupted by user.")
```