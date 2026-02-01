```python
"""
PulseStream Nexus – Streaming Validation & Transformation Engine
================================================================

This module contains an opinionated implementation of a *single* pipeline
stage that performs three critical responsibilities often required in
near-real-time social-media ingestion pipelines:

1. Decode raw wire messages (usually JSON strings coming from Kafka/Redis).
2. Validate the decoded object against an explicit JSONSchema contract.
3. Apply one or more enrichment / transformation strategies
   (e.g., sentiment or toxicity scoring).

The resulting record is emitted to a downstream “sink” which may be a message
queue, a REST endpoint, or an in-memory observer (Strategy & Observer pattern).

The code purposefully avoids framework-specific dependencies.  Top-level
objects can therefore be used inside a Celery task, FastAPI endpoint,
Spark/Beam `map` function, or a bare Python thread.  Operational metrics are
exported through Prometheus’ client library to facilitate production SLIs.

Author: PulseStream Nexus Core Team
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from functools import partial
from typing import Any, Callable, Dict, Optional

import jsonschema
from jsonschema import Draft7Validator
from prometheus_client import Counter, Histogram, CollectorRegistry

# --------------------------------------------------------------------------- #
# Logging configuration (can be overridden by application-level config)
# --------------------------------------------------------------------------- #
logger = logging.getLogger("pulsetream.module_46")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# --------------------------------------------------------------------------- #
# Prometheus metrics (per-process; shared across StreamProcessor instances)
# --------------------------------------------------------------------------- #
_METRIC_REGISTRY = CollectorRegistry()

# Records number of successfully processed events
EVENTS_PROCESSED = Counter(
    name="psn_events_processed_total",
    documentation="Total number of messages successfully validated and transformed.",
    registry=_METRIC_REGISTRY,
)

# Records number of processing failures
EVENTS_FAILED = Counter(
    name="psn_events_failed_total",
    documentation="Total number of messages that failed validation, decoding, or transformation.",
    registry=_METRIC_REGISTRY,
)

# Duration histogram for processing latency
PROCESSING_LATENCY = Histogram(
    name="psn_processing_latency_seconds",
    documentation="End-to-end latency for processing a single event.",
    registry=_METRIC_REGISTRY,
    buckets=(
        0.001,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2,
        5,
        10,
    ),
)

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ValidationError(Exception):
    """Raised when an event fails JSONSchema validation."""

    pass


class TransformationError(Exception):
    """Raised when an enrichment / transform strategy fails."""

    pass


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


class SchemaValidator:
    """
    Runtime JSONSchema validator.

    Parameters
    ----------
    schema: Dict[str, Any]
        JSONSchema definition conforming to draft-07.
    """

    def __init__(self, schema: Dict[str, Any]) -> None:
        self._schema = schema
        self._validator = Draft7Validator(schema)

    def validate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a JSON object. Raises ValidationError if the object is invalid.

        Returns the original payload on success to enable method chaining.
        """
        errors = sorted(self._validator.iter_errors(payload), key=lambda e: e.path)
        if errors:
            error_messages = "; ".join(e.message for e in errors)
            raise ValidationError(f"Schema validation failed: {error_messages}")
        return payload


# --------------------------------------------------------------------------- #
# Transformation strategy definitions (Strategy Pattern)
# --------------------------------------------------------------------------- #


class TransformStrategy(ABC):
    """Abstract strategy interface for event enrichment."""

    @abstractmethod
    def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply the transformation to `event`.

        Must return the modified event dictionary (may mutate in-place).
        """
        raise NotImplementedError


class _DummyNLPSentiment:
    """
    Lightweight, dependency-free sentiment scorer.

    Replaces heavyweight libraries in contexts where wheels cannot be shipped.
    """

    POSITIVE_WORDS = {"good", "great", "love", "awesome", "excellent", "wonderful"}
    NEGATIVE_WORDS = {"bad", "terrible", "hate", "awful", "worst", "horrible"}

    @classmethod
    def score(cls, text: str) -> float:
        """Return sentiment polarity in the range [-1.0, 1.0]."""
        if not text:
            return 0.0

        tokens = {t.lower().strip(".,!?") for t in text.split()}
        pos = len(tokens & cls.POSITIVE_WORDS)
        neg = len(tokens & cls.NEGATIVE_WORDS)
        total = pos + neg
        if total == 0:
            return 0.0
        polarity = (pos - neg) / total
        return max(min(polarity, 1.0), -1.0)


class SentimentTransformStrategy(TransformStrategy):
    """
    Naïve sentiment analysis enrichment.

    Adds `sentiment` key to event with a numeric polarity score.
    """

    def __init__(self, source_field: str = "text") -> None:
        self._source_field = source_field

    def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        try:
            text = event.get(self._source_field, "")
            event["sentiment"] = _DummyNLPSentiment.score(text)
            return event
        except Exception as exc:  # noqa: BLE001
            raise TransformationError("Sentiment transformation failed.") from exc


class ToxicityTransformStrategy(TransformStrategy):
    """
    Rudimentary toxicity checker using banned keywords.

    Adds `toxicity` boolean field to the event indicating presence of toxicity.
    """

    _BANNED_KEYWORDS = {
        "stupid",
        "idiot",
        "noob",
        "shut up",
        "kill yourself",
    }

    def __init__(self, source_field: str = "text") -> None:
        self._source_field = source_field

    def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        try:
            text: str = event.get(self._source_field, "").lower()
            is_toxic = any(keyword in text for keyword in self._BANNED_KEYWORDS)
            event["toxicity"] = is_toxic
            return event
        except Exception as exc:  # noqa: BLE001
            raise TransformationError("Toxicity transformation failed.") from exc


class TransformFactory:
    """
    Factory for assembling a composite strategy at runtime.

    Example
    -------
    >>> factory = TransformFactory({"sentiment": {}, "toxicity": {}})
    >>> strategy = factory.build()
    >>> strategy.transform({...})
    """

    _MAPPING: Dict[str, Callable[..., TransformStrategy]] = {
        "sentiment": SentimentTransformStrategy,
        "toxicity": ToxicityTransformStrategy,
    }

    def __init__(self, config: Dict[str, Dict[str, Any]]) -> None:
        """
        Parameters
        ----------
        config: Dict[str, Dict[str, Any]]
            Mapping of strategy name to kwargs.
            Example: {"sentiment": {"source_field": "body"}, ...}
        """
        self._config = config

    def build(self) -> TransformStrategy:
        """
        Build a *composite* strategy which delegates sequentially
        to each configured strategy.
        """

        strategies = []
        for name, kwargs in self._config.items():
            if name not in self._MAPPING:
                raise ValueError(f"Unknown transform strategy '{name}'.")
            strategies.append(self._MAPPING[name](**kwargs))

        class _CompositeStrategy(TransformStrategy):
            def __init__(self, parts: list[TransformStrategy]) -> None:
                self._parts = parts

            def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
                for part in self._parts:
                    event = part.transform(event)
                return event

        return _CompositeStrategy(strategies)


# --------------------------------------------------------------------------- #
# Stream Processor (Pipeline stage implementation)
# --------------------------------------------------------------------------- #


class StreamProcessor:
    """
    End-to-end message processing unit.

    The processor is intentionally synchronous – callers may execute it inside
    thread or async contexts as required (e.g., via `asyncio.to_thread`).

    Parameters
    ----------
    validator : SchemaValidator
        JSONSchema validator for input messages.
    transformer : TransformStrategy
        Enrichment strategy applied on validated payloads.
    sink : Callable[[Dict[str, Any]], None]
        Consumer of transformed events (e.g., Kafka producer, repository).
    metrics_registry : Optional[prometheus_client.CollectorRegistry]
        Registry to which custom metrics will register themselves so they can
        be scraped by Prometheus.  Defaults to internal registry.
    """

    def __init__(
        self,
        validator: SchemaValidator,
        transformer: TransformStrategy,
        sink: Callable[[Dict[str, Any]], None],
        *,
        metrics_registry: Optional[CollectorRegistry] = None,
    ) -> None:
        self._validator = validator
        self._transformer = transformer
        self._sink = sink
        self._metrics_registry = metrics_registry or _METRIC_REGISTRY

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def process(self, raw_message: str) -> None:
        """
        Process a single raw message. Emits validation/transform/sink metrics.
        """
        start = time.perf_counter()

        try:
            # Step 1: Decode
            payload = self._decode(raw_message)

            # Step 2: Schema validation
            self._validator.validate(payload)

            # Step 3: Transform
            enriched = self._transformer.transform(payload)

            # Step 4: Sink
            self._sink(enriched)

            EVENTS_PROCESSED.inc()
            logger.debug("Successfully processed event.")
        except Exception as exc:  # noqa: BLE001
            EVENTS_FAILED.inc()
            logger.exception("Processing failed: %s", exc)
            # Optionally implement retry logic here.
        finally:
            duration = time.perf_counter() - start
            PROCESSING_LATENCY.observe(duration)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _decode(raw_message: str) -> Dict[str, Any]:
        """
        Decode raw JSON string. Raises ValidationError on JSON decode failure.
        """
        try:
            return json.loads(raw_message)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid JSON payload: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Convenience factory methods
    # ------------------------------------------------------------------ #

    @classmethod
    def from_schema_and_config(  # noqa: D401
        cls,
        schema: Dict[str, Any],
        transform_config: Dict[str, Dict[str, Any]],
        sink: Callable[[Dict[str, Any]], None],
    ) -> "StreamProcessor":
        """
        Create StreamProcessor from raw schema and transform configuration.
        """
        validator = SchemaValidator(schema)
        transformer = TransformFactory(transform_config).build()
        return cls(validator, transformer, sink)


# --------------------------------------------------------------------------- #
# Default sink implementation for demonstration purposes
# --------------------------------------------------------------------------- #


def _stdout_sink(event: Dict[str, Any]) -> None:
    """Simple sink that prints the enriched event to STDOUT."""
    print(json.dumps(event, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# CLI Entrypoint (for local smoke testing)
# --------------------------------------------------------------------------- #

def _load_default_schema() -> Dict[str, Any]:
    """
    Minimal schema ensuring field types are correct.
    In production, schemas should reside in a schema registry.
    """
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["id", "text", "created_at", "platform"],
        "properties": {
            "id": {"type": "string"},
            "text": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
            "platform": {"type": "string", "enum": ["twitter", "reddit", "mastodon", "discord"]},
        },
        "additionalProperties": True,
    }


def _demo_messages() -> list[str]:
    return [
        json.dumps(
            {
                "id": "123",
                "text": "I love this community! It is awesome.",
                "created_at": "2023-10-18T15:15:34Z",
                "platform": "reddit",
            }
        ),
        json.dumps(
            {
                "id": "124",
                "text": "You are the worst! Shut up.",
                "created_at": "2023-10-18T15:16:02Z",
                "platform": "discord",
            }
        ),
        "🦄 not json 🦄",
    ]


def main() -> None:  # pragma: no cover
    """
    Execute a very simple demonstration run if called as a script.
    """
    processor = StreamProcessor.from_schema_and_config(
        schema=_load_default_schema(),
        transform_config={
            "sentiment": {"source_field": "text"},
            "toxicity": {"source_field": "text"},
        },
        sink=_stdout_sink,
    )

    for raw in _demo_messages():
        processor.process(raw)


if __name__ == "__main__":  # pragma: no cover
    main()
```