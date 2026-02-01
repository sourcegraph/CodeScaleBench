```python
"""
PulseStream Nexus – module_62
=============================

A lightweight yet production-ready implementation of a **Transform Strategy
Registry** and **Transformation Pipeline** used by PulseStream Nexus during the
social-event enrichment stage.

Key capabilities
----------------
1. Strategy Pattern implementation for pluggable event transformers.
2. Runtime registration / deregistration of strategies (useful for A/B testing
   or canary deployments).
3. Great-Expectations based data-quality guardrails (optional).
4. Prometheus metrics for latency & error tracking (degraded-mode fallback
   provided for environments without the `prometheus_client` package).
5. Fail-fast & fail-safe execution semantics: individual transform failures
   are surfaced while the pipeline continues processing subsequent events.

Example
-------
>>> from src.module_62 import (
...     TransformerRegistry,
...     SentimentTransformer,
...     TransformationPipeline,
... )
>>>
>>> registry = TransformerRegistry()
>>> registry.register(SentimentTransformer())
>>> pipeline = TransformationPipeline.from_names(["sentiment"])
>>>
>>> in_event  = {"id": "42", "text": "I love open-source!"}
>>> out_event = pipeline.transform(in_event)
>>> out_event["sentiment"]
'positive'

NOTE: This file purposefully avoids heavyweight ML dependencies.  Replace the
placeholder implementations with your production-grade models when integrating
into your stack.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

# --------------------------------------------------------------------------- #
#                               Observability                                 #
# --------------------------------------------------------------------------- #

try:
    from prometheus_client import Counter, Summary
except ModuleNotFoundError:  # pragma: no cover
    # Lightweight fallbacks so the rest of the code keeps working without the
    # real prometheus_client.  Only used in development / testing.
    class _NoOpMetric:  # pylint: disable=too-few-public-methods
        def __init__(self, *_, **__):
            pass

        def labels(self, *_, **__):
            return self

        def inc(self, *_):
            pass

        def observe(self, *_):
            pass

    Counter = Summary = _NoOpMetric  # type: ignore


# Metric instances
PIPELINE_LATENCY = Summary(
    "psn_pipeline_latency_seconds",
    "Latency for processing an event in the transformation pipeline",
    ["pipeline"],
)
PIPELINE_ERRORS = Counter(
    "psn_pipeline_errors_total",
    "Total number of transformation errors",
    ["pipeline", "stage"],
)

logger = logging.getLogger("pulse_stream_nexus.transform")
logging.basicConfig(
    level=os.environ.get("PSN_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

# --------------------------------------------------------------------------- #
#                               Data Classes                                  #
# --------------------------------------------------------------------------- #


@dataclass
class SocialEvent:
    """
    Canonical in-memory representation of a social event.

    The model is deliberately lean – transformer strategies can add arbitrary
    keys via the `.metadata` map.
    """

    raw: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """Return a single flattened dict that merges raw & metadata."""
        return {**self.raw, **self.metadata}


# --------------------------------------------------------------------------- #
#                          Transformer Strategy API                           #
# --------------------------------------------------------------------------- #


class EventTransformer(ABC):
    """
    Abstract base class for an event transformer strategy.

    Each subclass _must_ implement:
        • name          – unique snake-case identifier
        • transform()   – pure function that enriches the event
    """

    # Unique human readable identifier; subclasses should override.
    name: str = "abstract"

    @abstractmethod
    def transform(self, event: SocialEvent) -> SocialEvent:  # pragma: no cover
        """Enrich the given event in place and return it."""
        raise NotImplementedError

    # --------------------------- Helper methods --------------------------- #

    def __repr__(self) -> str:  # noqa: D401
        return f"<{self.__class__.__name__} name='{self.name}'>"

    # Convenience so strategies can be registered with the registry
    def __call__(self, event: SocialEvent) -> SocialEvent:
        return self.transform(event)


# --------------------------------------------------------------------------- #
#                           Built-in Transformers                             #
# --------------------------------------------------------------------------- #


class SentimentTransformer(EventTransformer):
    """
    Naïve lexical sentiment classifier.

    Production installations of PulseStream Nexus commonly replace this with a
    finetuned Roberta-base or custom CNN model served via TensorFlow Serving /
    TorchServe.  The reference implementation keeps external dependencies at a
    minimum while still providing usable semantics for testing & demo
    environments.
    """

    name = "sentiment"

    _positive_lexicon = {
        "good",
        "great",
        "love",
        "excellent",
        "fantastic",
        "happy",
        "awesome",
        "positive",
        "enjoy",
    }
    _negative_lexicon = {
        "bad",
        "terrible",
        "hate",
        "awful",
        "horrible",
        "sad",
        "negative",
        "angry",
    }

    def transform(self, event: SocialEvent) -> SocialEvent:  # noqa: D401
        text: str = event.raw.get("text", "")
        lowered = text.lower()
        score = 0.0

        # Very naïve lexical tally.
        for token in lowered.split():
            if token in self._positive_lexicon:
                score += 1
            elif token in self._negative_lexicon:
                score -= 1

        sentiment = "neutral"
        if score > 0:
            sentiment = "positive"
        elif score < 0:
            sentiment = "negative"

        event.metadata["sentiment"] = sentiment
        event.metadata["sentiment_score"] = score
        return event


class ToxicityTransformer(EventTransformer):
    """
    Simple toxicity filter using heuristic bad-word list.

    Highly simplified replacement for production Jigsaw or Detoxify models.
    """

    name = "toxicity"

    _toxic_tokens = {
        "idiot",
        "stupid",
        "moron",
        "sucks",
        "jerk",
        "dumb",
    }

    def transform(self, event: SocialEvent) -> SocialEvent:
        text: str = event.raw.get("text", "")
        lowered = text.lower()

        toxic_hits = [tok for tok in self._toxic_tokens if tok in lowered]
        event.metadata["is_toxic"] = bool(toxic_hits)
        event.metadata["toxic_hits"] = toxic_hits
        return event


class ViralityTransformer(EventTransformer):
    """
    Compute a rudimentary virality score based on engagement metrics.
    """

    name = "virality"

    _weights = {"likes": 0.4, "replies": 0.3, "shares": 0.3}

    def transform(self, event: SocialEvent) -> SocialEvent:
        engagement = {
            "likes": event.raw.get("likes", 0),
            "replies": event.raw.get("replies", 0),
            "shares": event.raw.get("shares", 0),
        }

        score = sum(
            value * self._weights.get(metric, 0.0)
            for metric, value in engagement.items()
        )
        event.metadata["virality_score"] = score
        return event


# Map built-ins so they can be auto-registered.
_BUILTIN_TRANSFORMERS: List[EventTransformer] = [
    SentimentTransformer(),
    ToxicityTransformer(),
    ViralityTransformer(),
]

# --------------------------------------------------------------------------- #
#                           Transformer Registry                              #
# --------------------------------------------------------------------------- #


class TransformerRegistry:
    """
    Registry holding mappings of transformer name ↦ strategy instance.

    Thread-safe for the common read-mostly workload via CPython GIL.  If you
    intend to mutate the registry concurrently across threads, protect calls
    with an external lock or upgrade to `collections.abc.MutableMapping`.
    """

    _registry: Dict[str, EventTransformer]

    def __init__(self) -> None:
        self._registry = {}
        for transformer in _BUILTIN_TRANSFORMERS:
            self.register(transformer)

    # ------------------------ Public API ------------------------ #

    def register(self, transformer: EventTransformer) -> None:
        """Register / overwrite a transformer strategy by name."""
        logger.debug("Registering transformer %s", transformer)
        self._registry[transformer.name] = transformer

    def deregister(self, name: str) -> None:
        """Remove a transformer from the registry."""
        with suppress(KeyError):
            logger.debug("Deregistering transformer '%s'", name)
            self._registry.pop(name)

    def get(self, name: str) -> EventTransformer:
        """Retrieve transformer or raise KeyError."""
        try:
            return self._registry[name]
        except KeyError as exc:  # pragma: no cover
            raise KeyError(f"Transformer '{name}' not found") from exc

    def available(self) -> List[str]:
        """Return list of transformer names present in the registry."""
        return list(self._registry)

    # ---------------------- Dict-like methods ---------------------- #

    def __contains__(self, item: str) -> bool:
        return item in self._registry

    def __getitem__(self, item: str) -> EventTransformer:
        return self.get(item)

    def __len__(self) -> int:  # noqa: D401
        return len(self._registry)

    def __iter__(self):  # noqa: D401
        return iter(self._registry.items())


# --------------------------------------------------------------------------- #
#                       Transformation Pipeline Runner                        #
# --------------------------------------------------------------------------- #


class TransformationPipeline:
    """
    Compose an ordered list of transformer strategies into a pipeline.

    Provides end-to-end error handling & metrics recording.  By default,
    exceptions inside a stage are _swallowed_ and surfaced via `event.metadata`
    to avoid interrupting stream processing.  Toggle `strict=True` to escalate.
    """

    _registry = TransformerRegistry()  # shared default registry

    def __init__(
        self,
        stages: List[EventTransformer],
        *,
        name: Optional[str] = None,
        strict: bool = False,
    ) -> None:
        self._stages = stages
        self.name = name or "->".join(stage.name for stage in stages)
        self.strict = strict

    # --------------------------- Factory --------------------------- #

    @classmethod
    def from_names(
        cls, names: Iterable[str], *, strict: bool = False, name: str | None = None
    ) -> "TransformationPipeline":
        """Instantiate pipeline from transformer names registered in registry."""
        stages: List[EventTransformer] = []
        for _name in names:
            stages.append(cls._registry.get(_name))
        return cls(stages, strict=strict, name=name)

    # ------------------------- Public API ------------------------- #

    def transform(self, raw_event: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Apply all stages sequentially.

        Parameters
        ----------
        raw_event
            The incoming (unvalidated) event payload.

        Returns
        -------
        Dict[str, Any]
            Consolidated event dict (original + metadata).
        """
        social_event = SocialEvent(dict(raw_event))  # defensive copy
        timer = PIPELINE_LATENCY.labels(pipeline=self.name).time()  # type: ignore
        logger.debug("Pipeline '%s' starting for event=%s", self.name, raw_event)
        try:
            self._validate_incoming(social_event.raw)

            for stage in self._stages:
                logger.debug("Running stage '%s'", stage.name)
                try:
                    social_event = stage.transform(social_event)
                except Exception as exc:  # noqa: BLE001
                    PIPELINE_ERRORS.labels(
                        pipeline=self.name, stage=stage.name
                    ).inc()  # type: ignore
                    logger.exception(
                        "Stage '%s' failed for event id=%s",
                        stage.name,
                        social_event.raw.get("id"),
                    )
                    if self.strict:
                        raise
                    social_event.metadata.setdefault("stage_errors", {})[
                        stage.name
                    ] = str(exc)
        finally:
            # Stop timer regardless of outcome
            timer.observe_duration()

        logger.debug(
            "Pipeline '%s' completed. Metadata=%s",
            self.name,
            social_event.metadata,
        )
        return social_event.as_dict()

    # ------------------------- Validation ------------------------- #

    _ge_validator = None  # lazy initialisation

    @classmethod
    def _validator(cls):
        """Return / build Great-Expectations validator (optional dependency)."""
        if cls._ge_validator is not None:
            return cls._ge_validator

        try:
            import great_expectations as gx  # type: ignore
            from great_expectations.core.batch import BatchRequest  # noqa: WPS433
            from great_expectations.validator.validator import Validator  # noqa: WPS433

            # Minimalistic in-memory validator using GX's runtime datasource
            context = gx.get_context()  # uses `great_expectations/` folder
            datasource_name = "__psn_runtime_ds"
            if datasource_name not in context.datasources:
                context.sources.add_or_update_runtime_datasource(
                    name=datasource_name,
                    batch_spec_passthrough={"reader_method": "read_json"},
                )

            batch_request = BatchRequest(
                datasource_name=datasource_name,
                data_connector_name="default_runtime_data_connector_name",
                data_asset_name="__psn_asset",
                batch_identifiers={"id": "single_batch"},
                runtime_parameters={"batch_data": []},
            )

            cls._ge_validator = context.get_validator(
                batch_request=batch_request,
                expectation_suite_name="psn_event_schema",
            )
        except ModuleNotFoundError:
            cls._ge_validator = None
        except Exception:  # Catch-all to avoid breaking pipeline startup
            logger.exception("Failed initialising Great Expectations validator")
            cls._ge_validator = None

        return cls._ge_validator

    def _validate_incoming(self, raw_event: Mapping[str, Any]) -> None:
        """
        Optional runtime schema validation.

        This is a best-effort step: validation errors are logged & metered but
        will not disrupt event flow unless `strict=True`.
        """
        validator = self._validator()
        if validator is None:
            return

        try:
            # Great Expectations expects a dataframe-like object.  Wrap the event
            # in a list of dicts so GX can treat it as tabular.
            import pandas as pd  # type: ignore  # noqa: WPS433

            df = pd.json_normalize([raw_event])
            validator.active_batch = validator.get_batch(data=df)
            res = validator.validate(only_return_failures=True, raise_on_error=False)
            if not res["success"]:
                PIPELINE_ERRORS.labels(
                    pipeline=self.name, stage="validation"
                ).inc()  # type: ignore
                logger.warning("Validation failed for event id=%s: %s", raw_event.get("id"), res)

                if self.strict:
                    raise ValueError(f"Validation failed: {res}")
        except Exception as exc:  # noqa: BLE001
            PIPELINE_ERRORS.labels(
                pipeline=self.name, stage="validation"
            ).inc()  # type: ignore
            logger.exception("Validator raised error for event id=%s", raw_event.get("id"))
            if self.strict:
                raise exc

    # -------------------------- Utilities -------------------------- #

    def __repr__(self) -> str:  # noqa: D401
        stages = ", ".join(stage.name for stage in self._stages)
        return f"<TransformationPipeline name='{self.name}' stages=[{stages}]>"


# --------------------------------------------------------------------------- #
#                            Module Public API                                #
# --------------------------------------------------------------------------- #

__all__ = [
    # Data models
    "SocialEvent",
    # Strategy API
    "EventTransformer",
    "SentimentTransformer",
    "ToxicityTransformer",
    "ViralityTransformer",
    "TransformerRegistry",
    # Pipeline
    "TransformationPipeline",
]

# --------------------------------------------------------------------------- #
#                        Basic Self-Test (debug only)                         #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    # Run a quick smoke test when executed directly.
    logging.getLogger().setLevel(logging.DEBUG)
    registry = TransformerRegistry()
    pipeline = TransformationPipeline.from_names(
        ["sentiment", "toxicity", "virality"]
    )

    sample_events = [
        {
            "id": 1,
            "text": "I absolutely love this project, great work!",
            "likes": 10,
            "replies": 2,
            "shares": 1,
        },
        {
            "id": 2,
            "text": "You idiot, this idea is terrible.",
            "likes": 1,
            "replies": 5,
            "shares": 0,
        },
    ]

    for ev in sample_events:
        print("INPUT ", ev)
        print("OUTPUT", pipeline.transform(ev))
        print("-" * 50)
```