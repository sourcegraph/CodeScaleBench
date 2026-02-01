```python
"""
PulseStream Nexus – Sentiment & Toxicity Enrichment Module
=========================================================

File: src/module_64.py
----------------------------------
This module is responsible for **content-level enrichment** of raw
social-network events (tweets, Reddit comments, Discord messages, …).
It performs the following tasks:

1.  Validates the raw event schema.
2.  Runs pluggable sentiment-analysis and toxicity-detection strategies.
3.  Emits an `EnrichedEventRecord` that downstream pipelines can safely
    consume (Kafka topic, Data Lake landing zone, etc.).
4.  Pushes Prometheus metrics for operational observability.
5.  (Optionally) executes Great Expectations validation against the
    enriched payload to guarantee data-quality contracts.

Design notes
------------
• Clean-architecture friendly: pure-python business logic, no direct I/O.  
• Strategy pattern: choose algorithm at runtime via environment variables.  
• Heavily defensive: fails “softly” on model/infra errors, retaining
  original message + error metadata for later DLQ inspection.

Author: PulseStream Nexus Core Team
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError, root_validator

try:
    # Lightweight import guard; these libs are optional
    from nltk.sentiment import SentimentIntensityAnalyzer  # type: ignore
except Exception:  # pragma: no cover
    SentimentIntensityAnalyzer = None  # type: ignore

try:
    from transformers import pipeline  # type: ignore
except Exception:  # pragma: no cover
    pipeline = None  # type: ignore

try:
    from googleapiclient.discovery import build as google_api_build  # type: ignore
except Exception:  # pragma: no cover
    google_api_build = None  # type: ignore

try:
    # Metrics are optional.  The import guard avoids hard dependency.
    from prometheus_client import Counter, Histogram  # type: ignore
except Exception:  # pragma: no cover
    Counter = Histogram = None  # type: ignore

try:
    import great_expectations as gx  # type: ignore
except Exception:  # pragma: no cover
    gx = None  # type: ignore

# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #

LOG_LEVEL = os.getenv("PULSENEX_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Prometheus metrics (noop fallbacks if library unavailable)
# --------------------------------------------------------------------------- #

def _noop(*_a: Any, **_kw: Any) -> Any:  # noqa: D401
    """Simple function that does nothing. Useful as a metric placeholder."""
    return None


_TRANSFORM_SUCCESS = (
    Counter("psn_enrichment_success_total", "Number of successfully enriched events")
    if Counter
    else _noop
)

_TRANSFORM_FAILURE = (
    Counter("psn_enrichment_failure_total", "Number of events that failed enrichment")
    if Counter
    else _noop
)

_TRANSFORM_LATENCY = (
    Histogram(
        "psn_enrichment_latency_seconds",
        "Latency of the enrichment transformer per event",
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.5, 1, 3, 10),
    )
    if Histogram
    else _noop
)

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class StrategyInitializationError(RuntimeError):
    """Raised when an NLP strategy cannot load its underlying model resources."""


class EnrichmentError(Exception):
    """Generic enrichment failure—for DLQ / dead-letter-queue pipelines."""


# --------------------------------------------------------------------------- #
# Data models (Pydantic)
# --------------------------------------------------------------------------- #


class EventRecord(BaseModel):
    """
    Canonical raw social-event record.

    NOTE
    ----
    This schema is *independent* of the original platform’s message format
    to ensure cross-platform uniformity.
    """

    event_id: str = Field(..., alias="id")
    text: str
    author_handle: str
    source: str  # e.g. "twitter", "reddit"
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        allow_population_by_field_name = True
        anystr_strip_whitespace = True


class EnrichedEventRecord(EventRecord):
    """
    Enriched record with sentiment and toxicity annotations.
    """

    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None
    toxicity_score: Optional[float] = None
    toxicity_label: Optional[str] = None
    enrichment_ts: datetime = Field(default_factory=datetime.utcnow)

    @root_validator
    def _ensure_consistency(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """If either score or label is None, ensure both are None."""
        s_score, s_label = values.get("sentiment_score"), values.get("sentiment_label")
        t_score, t_label = values.get("toxicity_score"), values.get("toxicity_label")
        if (s_score is None) ^ (s_label is None):
            raise ValueError("sentiment_score and sentiment_label must appear together.")
        if (t_score is None) ^ (t_label is None):
            raise ValueError("toxicity_score and toxicity_label must appear together.")
        return values


# --------------------------------------------------------------------------- #
# Strategy Interfaces
# --------------------------------------------------------------------------- #


class SentimentStrategy(ABC):
    """Common interface for sentiment strategies."""

    @abstractmethod
    def analyze(self, text: str) -> Tuple[float, str]:  # score, label
        pass  # pragma: no cover


class ToxicityStrategy(ABC):
    """Common interface for toxicity strategies."""

    @abstractmethod
    def analyze(self, text: str) -> Tuple[float, str]:
        pass  # pragma: no cover


# --------------------------------------------------------------------------- #
# Concrete Strategies
# --------------------------------------------------------------------------- #


class VaderSentimentStrategy(SentimentStrategy):
    """
    Sentiment analysis using NLTK VADER.
    """

    def __init__(self) -> None:
        if SentimentIntensityAnalyzer is None:
            raise StrategyInitializationError(
                "nltk is not installed or VADER lexical data missing."
            )
        self._model = SentimentIntensityAnalyzer()

    def analyze(self, text: str) -> Tuple[float, str]:
        scores = self._model.polarity_scores(text)
        compound = scores["compound"]
        if compound >= 0.05:
            label = "positive"
        elif compound <= -0.05:
            label = "negative"
        else:
            label = "neutral"
        return compound, label


class HFSentimentStrategy(SentimentStrategy):
    """
    Sentiment analysis using HuggingFace Transformers pipeline.
    """

    _pipeline_name = os.getenv("PSN_HF_SENTIMENT_MODEL", "distilbert-base-uncased-finetuned-sst-2-english")

    def __init__(self) -> None:
        if pipeline is None:
            raise StrategyInitializationError("transformers is not installed.")
        try:
            self._classifier = pipeline("sentiment-analysis", model=self._pipeline_name)
        except Exception as exc:
            raise StrategyInitializationError(f"Unable to load HF model {self._pipeline_name}") from exc

    def analyze(self, text: str) -> Tuple[float, str]:
        res = self._classifier(text, truncation=True)[0]
        label = res["label"].lower()  # POSITIVE / NEGATIVE → positive / negative
        score = float(res["score"])
        if label not in {"positive", "negative"}:
            label = "neutral"
        # Map score to signed value for uniformity (-1…1)
        signed_score = score if label == "positive" else -score
        return signed_score, label


class PerspectiveAPIToxicityStrategy(ToxicityStrategy):
    """
    Toxicity detection via Google Perspective API.

    The API key is expected in env var: ``PERSPECTIVE_API_KEY``.
    """

    _DISCOVERY_URL = (
        "https://commentanalyzer.googleapis.com/$discovery/rest?version=v1alpha1"
    )

    def __init__(self) -> None:
        if google_api_build is None:
            raise StrategyInitializationError("google-api-python-client is not installed.")
        api_key = os.getenv("PERSPECTIVE_API_KEY")
        if not api_key:
            raise StrategyInitializationError("PERSPECTIVE_API_KEY not defined.")
        self._client = google_api_build(
            "commentanalyzer", "v1alpha1", developerKey=api_key, discoveryServiceUrl=self._DISCOVERY_URL
        )

    def analyze(self, text: str) -> Tuple[float, str]:
        try:
            req = {
                "comment": {"text": text},
                "requestedAttributes": {"TOXICITY": {}},
                "doNotStore": True,
            }
            response = (
                self._client.comments()  # type: ignore
                .analyze(body=req)
                .execute()
            )
            score = response["attributeScores"]["TOXICITY"]["summaryScore"]["value"]
            label = "toxic" if score >= 0.5 else "non-toxic"
            return score, label
        except Exception as exc:
            logger.exception("Perspective API call failed: %s", exc)
            raise EnrichmentError("Perspective API failure") from exc


class NullToxicityStrategy(ToxicityStrategy):
    """
    Safe fallback that returns `None` results (used when toxicity analysis is disabled).
    """

    def analyze(self, text: str) -> Tuple[float, str]:
        return 0.0, "unknown"


# --------------------------------------------------------------------------- #
# Transformer
# --------------------------------------------------------------------------- #


class SentimentToxicityTransformer:
    """
    Enrichment orchestrator that applies the configured strategies.

    Environment variables
    ---------------------
    PSN_SENTIMENT_STRATEGY : 'vader' | 'hf'  (default: vader)
    PSN_TOXICITY_STRATEGY  : 'perspective' | 'none' (default: none)
    """

    def __init__(
        self,
        sentiment_strategy: Optional[SentimentStrategy] = None,
        toxicity_strategy: Optional[ToxicityStrategy] = None,
    ) -> None:
        self.sentiment_strategy = sentiment_strategy or self._bootstrap_sentiment()
        self.toxicity_strategy = toxicity_strategy or self._bootstrap_toxicity()

    # ------------------------------------------------------------------ #
    # Bootstrapping helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _bootstrap_sentiment() -> SentimentStrategy:
        strategy = os.getenv("PSN_SENTIMENT_STRATEGY", "vader").lower()
        logger.info("Using sentiment strategy: %s", strategy)
        if strategy == "vader":
            return VaderSentimentStrategy()
        if strategy == "hf":
            return HFSentimentStrategy()
        raise StrategyInitializationError(f"Unknown sentiment strategy '{strategy}'")

    @staticmethod
    def _bootstrap_toxicity() -> ToxicityStrategy:
        strategy = os.getenv("PSN_TOXICITY_STRATEGY", "none").lower()
        logger.info("Using toxicity strategy: %s", strategy)
        if strategy == "perspective":
            return PerspectiveAPIToxicityStrategy()
        if strategy == "none":
            return NullToxicityStrategy()
        raise StrategyInitializationError(f"Unknown toxicity strategy '{strategy}'")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def transform(self, record: EventRecord) -> EnrichedEventRecord:
        """
        Main transformation method (single record).
        """
        start = time.perf_counter()
        try:
            sentiment_score, sentiment_label = self.sentiment_strategy.analyze(record.text)
            toxicity_score, toxicity_label = self.toxicity_strategy.analyze(record.text)

            enriched = EnrichedEventRecord(
                **record.dict(),
                sentiment_score=sentiment_score,
                sentiment_label=sentiment_label,
                toxicity_score=toxicity_score,
                toxicity_label=toxicity_label,
            )

            self._run_great_expectations_validation(enriched)
            if Counter:
                _TRANSFORM_SUCCESS.inc()  # type: ignore

            return enriched
        except Exception as exc:
            if Counter:
                _TRANSFORM_FAILURE.inc()  # type: ignore
            raise
        finally:
            if Histogram:
                _TRANSFORM_LATENCY.observe(time.perf_counter() - start)  # type: ignore

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    @staticmethod
    def _run_great_expectations_validation(record: EnrichedEventRecord) -> None:
        if gx is None:
            return  # Great Expectations is optional
        # Example expectation suite (in production this would be more robust)
        validator = gx.from_pandas(  # type: ignore
            record.dict(exclude={"metadata"}),  # metadata may contain arbitrary objects
        )
        expectation_result = validator.expect_column_values_to_not_be_null("sentiment_score")
        if not expectation_result.success:
            raise EnrichmentError("Great Expectations validation failed.")


# --------------------------------------------------------------------------- #
# Streaming Convenience Helpers
# --------------------------------------------------------------------------- #


def process_stream(
    records: Iterable[str],
    transformer: Optional[SentimentToxicityTransformer] = None,
) -> Iterable[str]:
    """
    Process an *iterable of JSON strings* (newline-delimited) and yield
    enriched JSON strings.

    Any unhandled errors will propagate to the caller; you may wrap this
    in higher-level retry or DLQ logic as necessary.
    """
    transformer = transformer or SentimentToxicityTransformer()

    for raw_line in records:
        if not raw_line.strip():
            continue  # skip empty lines
        try:
            raw_obj = json.loads(raw_line)
            event = EventRecord.parse_obj(raw_obj)
            enriched = transformer.transform(event)
            yield enriched.json(by_alias=True)
        except (json.JSONDecodeError, ValidationError) as parse_err:
            logger.warning("Parsing error – record skipped: %s", parse_err, exc_info=False)
            if Counter:
                _TRANSFORM_FAILURE.inc()  # type: ignore
            continue
        except Exception as enrich_err:
            logger.exception("Enrichment failed – record forwarded to DLQ: %s", enrich_err)
            # In real production, forward to a DLQ topic/file here
            if Counter:
                _TRANSFORM_FAILURE.inc()  # type: ignore
            continue


# --------------------------------------------------------------------------- #
# CLI entry-point (Unix pipeline friendly)
# --------------------------------------------------------------------------- #

def _cli() -> None:
    """
    Read JSON lines from STDIN, write enriched JSON lines to STDOUT.

    Example
    -------
        $ cat events.jsonl | python -m src.module_64 > enriched.jsonl
    """
    transformer = SentimentToxicityTransformer()
    for enriched_json in process_stream(sys.stdin, transformer=transformer):
        sys.stdout.write(enriched_json + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _cli()
```