```python
"""
src/module_2.py
======================================
Domain: Transformation / Enrichment Layer
Module: transformer_pipeline

This module implements a pluggable, metrics-aware transformation pipeline that
enriches raw social-network events with sentiment, toxicity, and virality
signals.  It showcases the Strategy Pattern (for interchangeable transformers),
the Observer Pattern (Prometheus metrics), and solid error-handling semantics
expected in a production data-streaming stack such as PulseStream Nexus.

The API is intentionally framework-agnostic; callers can use the synchronous
`TransformationPipeline.process(record)` method from a Kafka consumer, an
Apache Beam DoFn, or a FastAPI route without modification.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from types import MappingProxyType
from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError, validator
from prometheus_client import Counter, Histogram

# ------------------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------------------

_LOGGER = logging.getLogger("pulsetream.transformer_pipeline")
_LOGGER.addHandler(logging.NullHandler())

# ------------------------------------------------------------------------------
# Metrics (Prometheus)
# ------------------------------------------------------------------------------

METRIC_TRANSFORMER_ERRORS = Counter(
    "psn_transformer_errors_total",
    "Total number of transformation errors.",
    labelnames=("transformer",),
)

METRIC_TRANSFORMER_DURATION = Histogram(
    "psn_transformer_duration_seconds",
    "Time spent applying a transformer.",
    labelnames=("transformer",),
    buckets=(0.001, 0.01, 0.1, 0.5, 1, 5, 10),
)

METRIC_PIPELINE_PROCESSED = Counter(
    "psn_pipeline_processed_total",
    "Total number of records successfully processed by the pipeline.",
)

METRIC_PIPELINE_FAILED = Counter(
    "psn_pipeline_failed_total",
    "Total number of records that failed during pipeline processing.",
)

# ------------------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------------------


class SocialRecord(BaseModel):
    """
    Canonical representation of a raw social network event.

    NOTE: All timestamps are expected to be POSIX milliseconds to ensure
    cross-platform compatibility.
    """

    id: str = Field(..., example="1516653023001")
    network: str = Field(..., example="reddit")
    user_id: str = Field(..., alias="userId", example="u_9f02cf")
    text: str = Field(..., min_length=1, example="Hello, world!")
    created_at_ms: int = Field(..., alias="createdAtMs", example=1700032994000)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # --- Validators ----------------------------------------------------------
    @validator("network")
    def _network_lower(cls, v: str) -> str:
        return v.lower()

    class Config:
        allow_population_by_field_name = True
        frozen = True  # Immutability guards against accidental mutation


class EnrichedSocialRecord(SocialRecord):
    """
    Record after enrichment.  Additional analytical fields are nullable because
    not every pipeline will configure every transformer.
    """

    sentiment_score: float | None = Field(
        default=None, ge=-1.0, le=1.0, description="Polarity score in [-1, 1]"
    )
    toxicity_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Probability the text is toxic"
    )
    virality_score: float | None = Field(
        default=None,
        ge=0.0,
        description="Heuristic score correlating with potential virality",
    )


# ------------------------------------------------------------------------------
# Transformer abstraction
# ------------------------------------------------------------------------------


class Transformer(ABC):
    """
    Abstract base class for all record transformers.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable identifier used for logging/metrics."""

    @abstractmethod
    def transform(self, record: EnrichedSocialRecord) -> EnrichedSocialRecord:
        """
        Perform in-place transformation of the supplied record and return it.

        Implementations MUST treat models as immutable and create a copy
        (record.copy(update={...})) when modifying fields.
        """
        raise NotImplementedError


# ------------------------------------------------------------------------------
# Concrete transformer implementations
# ------------------------------------------------------------------------------


class SentimentTransformer(Transformer):
    """
    Adds `sentiment_score` to the record using TextBlob as a placeholder.  In a
    production setting, switch to a domain-tuned model (e.g., VADER,
    roberta-base-go_emotions, etc.).
    """

    def __init__(self, language: str = "en") -> None:
        # Lazy import to keep optional dependency footprint minimal.
        try:
            from textblob import TextBlob  # pylint: disable=import-error

            self._sentiment_fn = lambda txt: TextBlob(txt).sentiment.polarity
        except ModuleNotFoundError:
            _LOGGER.warning(
                "TextBlob not installed; falling back to dummy sentiment implementation."
            )
            self._sentiment_fn = lambda txt: 0.0

        self._language = language

    # ------------------------------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        return "sentiment"

    # ------------------------------------------------------------------

    def transform(self, record: EnrichedSocialRecord) -> EnrichedSocialRecord:
        score = self._sentiment_fn(record.text)
        return record.copy(update={"sentiment_score": score})


class ToxicityTransformer(Transformer):
    """
    Annotates record with probability of toxicity using detoxify.  If detoxify is
    unavailable, falls back to 0.0.
    """

    def __init__(self) -> None:
        try:
            from detoxify import Detoxify  # pylint: disable=import-error

            self._model = Detoxify("original", device="cpu")
        except ModuleNotFoundError:
            _LOGGER.warning("Detoxify not installed; toxicity will be 0.0.")
            self._model = None

    # ------------------------------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        return "toxicity"

    # ------------------------------------------------------------------

    def transform(self, record: EnrichedSocialRecord) -> EnrichedSocialRecord:
        if self._model:
            score: float = float(self._model.predict(record.text)["toxicity"])
        else:
            score = 0.0

        return record.copy(update={"toxicity_score": score})


class ViralityTransformer(Transformer):
    """
    Computes a naive virality score based on text length and presence of
    amplification markers (exclamation marks, @mentions, hashtags).  Serves as a
    placeholder until replaced with an ML model trained on historical
    engagement data.
    """

    @property
    def name(self) -> str:  # noqa: D401
        return "virality"

    # ------------------------------------------------------------------

    @staticmethod
    def _heuristic(text: str) -> float:
        weight_len = min(len(text) / 280, 1)  # longer posts up to tweet size
        weight_exclaim = text.count("!") * 0.05
        weight_mentions = text.count("@") * 0.1
        weight_hashtags = text.count("#") * 0.07
        score = weight_len + weight_exclaim + weight_mentions + weight_hashtags
        return min(score, 1.0)

    # ------------------------------------------------------------------

    def transform(self, record: EnrichedSocialRecord) -> EnrichedSocialRecord:
        score = self._heuristic(record.text)
        return record.copy(update={"virality_score": score})


# ------------------------------------------------------------------------------
# Pipeline orchestrator
# ------------------------------------------------------------------------------


class TransformationPipeline:
    """
    Orchestrates sequential execution of a set of transformers.  Provides
    Prometheus instrumentation, robust error-handling, and Pydantic-backed I/O
    validation.
    """

    __slots__ = ("_transformers",)

    def __init__(self, transformers: List[Transformer] | None = None) -> None:
        if transformers is None:
            transformers = [
                SentimentTransformer(),
                ToxicityTransformer(),
                ViralityTransformer(),
            ]
        self._transformers: tuple[Transformer, ...] = tuple(transformers)
        _LOGGER.info(
            "TransformationPipeline configured with transformers: %s",
            [t.name for t in self._transformers],
        )

    # ------------------------------------------------------------------

    @property
    def transformers(self) -> tuple[Transformer, ...]:
        """Read-only view of configured transformers."""
        return self._transformers

    # ------------------------------------------------------------------

    def process(self, raw_record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate the incoming record, perform enrichment, and return the
        resulting dict.  All Pydantic models are converted back to plain dicts
        with aliases for ergonomic downstream serialization.

        Errors are logged and bubbled up *after* metrics indicate failure, so
        callers may decide whether to retry, DLQ, or ignore.
        """
        try:
            model: EnrichedSocialRecord = EnrichedSocialRecord.parse_obj(raw_record)
        except ValidationError as exc:
            METRIC_PIPELINE_FAILED.inc()
            _LOGGER.error("Input validation failed: %s", exc)
            raise

        for transformer in self._transformers:
            start = time.perf_counter()
            try:
                model = self._apply_transformer(transformer, model)
            except Exception:  # pylint: disable=broad-except
                METRIC_TRANSFORMER_ERRORS.labels(transformer=transformer.name).inc()
                METRIC_PIPELINE_FAILED.inc()
                _LOGGER.exception(
                    "Transformer '%s' failed for record id=%s",
                    transformer.name,
                    model.id,
                )
                raise
            finally:
                METRIC_TRANSFORMER_DURATION.labels(transformer=transformer.name).observe(
                    time.perf_counter() - start
                )

        METRIC_PIPELINE_PROCESSED.inc()
        # `dict(by_alias=True)` ensures camelCase aliases propagate.
        return model.dict(by_alias=True)

    # ------------------------------------------------------------------

    @staticmethod
    def _apply_transformer(
        transformer: Transformer, record: EnrichedSocialRecord
    ) -> EnrichedSocialRecord:
        return transformer.transform(record)


# ------------------------------------------------------------------------------
# Convenience: shared singleton instance
# ------------------------------------------------------------------------------

DEFAULT_PIPELINE = TransformationPipeline()

# ------------------------------------------------------------------------------
# Public RE-exports
# ------------------------------------------------------------------------------

__all__ = [
    # Models
    "SocialRecord",
    "EnrichedSocialRecord",
    # Transformers
    "Transformer",
    "SentimentTransformer",
    "ToxicityTransformer",
    "ViralityTransformer",
    # Pipeline
    "TransformationPipeline",
    "DEFAULT_PIPELINE",
    # Metrics (primarily for unit tests)
    "METRIC_TRANSFORMER_ERRORS",
    "METRIC_TRANSFORMER_DURATION",
    "METRIC_PIPELINE_PROCESSED",
    "METRIC_PIPELINE_FAILED",
]
```