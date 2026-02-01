```python
"""
PulseStream Nexus
src/module_34.py

This module defines the `EventStreamProcessor`, a reusable, streaming-pipeline
building block that

1. Consumes raw, high-volume social events from Kafka.
2. Performs schema validation + data-quality checks.
3. Applies one or more registered transformation strategies (sentiment,
   toxicity, virality, etc.).
4. Emits the enriched event to a downstream Kafka topic.
5. Exposes Prometheus metrics for operational observability.

The implementation purposefully avoids framework-coupled code, so it can be
plug-and-played inside the Clean Architecture “interface adapters” layer.

Author: PulseStream Nexus Core Team
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, MutableMapping, Optional, Type

from pydantic import BaseModel, Field, ValidationError, validator

# Runtime (optional) dependencies.  They are imported lazily to avoid hard failure
# during unit tests or when running in minimal environments.
with suppress(ImportError):
    from confluent_kafka import Consumer, Producer, KafkaException  # type: ignore

with suppress(ImportError):
    from prometheus_client import Counter, Histogram, start_http_server  # type: ignore


###############################################################################
# Configuration
###############################################################################

@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: str
    group_id: str
    input_topic: str
    output_topic: str
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    security_protocol: str = "PLAINTEXT"


@dataclass(frozen=True)
class ProcessorConfig:
    kafka: KafkaConfig
    metrics_port: int = 9405
    max_poll_interval_sec: int = 5
    shutdown_grace_sec: int = 30
    # toggle transformations with a list of transformer IDs
    enabled_transformers: List[str] = field(default_factory=lambda: ["sentiment"])
    # optional: custom transform kwargs
    transform_kwargs: Dict[str, Dict[str, Any]] = field(default_factory=dict)


###############################################################################
# Domain Model
###############################################################################

class SocialEvent(BaseModel):
    """
    Canonical social event model understood by the platform.
    NOTE: The model is intentionally minimal here; real-world usage would include
    many more attributes.
    """

    event_id: str = Field(..., regex=r"^[a-zA-Z0-9\-_]+$")
    network: str
    user_id: str
    text: str
    timestamp: float  # epoch seconds
    metadata: Dict[str, Any] = Field(default_factory=dict)

    ###########################################################################
    # Pydantic validators
    ###########################################################################
    @validator("network")
    def _validate_network(cls, v: str) -> str:
        allowed = {"twitter", "reddit", "mastodon", "discord"}
        if v.lower() not in allowed:
            raise ValueError(f"network '{v}' not supported")
        return v.lower()

    @validator("timestamp")
    def _validate_timestamp(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("timestamp must be positive epoch seconds")
        return v


###############################################################################
# Transformation Strategy Pattern
###############################################################################

class TransformerContext(Dict[str, Any]):
    """
    Mutable mapping passed to each transformer.  Allows transformers to share
    information without mutating the underlying SocialEvent.
    """


class BaseTransformer(ABC):
    """
    Strategy interface for event enrichment.
    """

    # unique identifier for configuration toggling
    transformer_id: str

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    @abstractmethod
    def transform(self, event: SocialEvent, context: TransformerContext) -> None:
        """Enrich event in-place; may modify context dict as well."""

    # --------------------------------------------------------------------- #
    # Factory & Registry
    # --------------------------------------------------------------------- #
    _registry: Dict[str, Type["BaseTransformer"]] = {}

    @classmethod
    def register(cls, transformer_cls: Type["BaseTransformer"]) -> Type["BaseTransformer"]:
        """
        Class decorator for registering concrete transformers.
        """
        cls._registry[transformer_cls.transformer_id] = transformer_cls
        return transformer_cls

    @classmethod
    def create_instances(
        cls,
        enabled: List[str],
        kwargs_mapping: MutableMapping[str, Dict[str, Any]],
    ) -> List["BaseTransformer"]:
        """
        Instantiate transformer objects based on config.
        """
        instances: List[BaseTransformer] = []
        for transformer_id in enabled:
            try:
                t_cls = cls._registry[transformer_id]
            except KeyError as exc:
                raise ValueError(f"Transformer '{transformer_id}' not found") from exc

            instances.append(t_cls(**kwargs_mapping.get(transformer_id, {})))
        return instances


# ------------------------------------------------------------------------- #
# Concrete Transformers
# ------------------------------------------------------------------------- #

@BaseTransformer.register
class SentimentTransformer(BaseTransformer):
    """
    Adds a naive sentiment polarity score in the metadata.
    Uses TextBlob where available; falls back to a trivial heuristic.
    """

    transformer_id = "sentiment"
    _default_polarity: float = 0.0

    def _compute_polarity(self, text: str) -> float:
        with suppress(ImportError):
            from textblob import TextBlob  # type: ignore

            return float(TextBlob(text).sentiment.polarity)

        # Fallback heuristic: positive if contains ':)', negative if ':('.
        lowered = text.lower()
        if ":)" in lowered:
            return 1.0
        if ":(" in lowered:
            return -1.0
        return self._default_polarity

    def transform(self, event: SocialEvent, context: TransformerContext) -> None:
        polarity = self._compute_polarity(event.text)
        context["sentiment_polarity"] = polarity
        event.metadata["sentiment"] = {"polarity": polarity}


@BaseTransformer.register
class ToxicityTransformer(BaseTransformer):
    """
    Very naive toxicity classifier (placeholder for Perspective/ToxiPi, etc.).
    """

    transformer_id = "toxicity"

    _bad_words = {"hate", "kill", "die", "stupid"}

    def transform(self, event: SocialEvent, context: TransformerContext) -> None:
        score = float(
            sum(1 for word in event.text.lower().split() if word in self._bad_words)
        )
        context["toxicity_score"] = score
        event.metadata["toxicity"] = {"score": score}


@BaseTransformer.register
class ViralityTransformer(BaseTransformer):
    """
    Estimate virality potential based on simple metrics supplied in metadata.
    """

    transformer_id = "virality"

    def transform(self, event: SocialEvent, context: TransformerContext) -> None:
        raw = event.metadata.get("engagement", {})
        likes = int(raw.get("likes", 0))
        shares = int(raw.get("shares", 0))
        replies = int(raw.get("replies", 0))
        virality = (likes + 2 * shares + 0.5 * replies) / max(len(event.text), 1)
        context["virality_score"] = virality
        event.metadata["virality"] = {"score": virality}


###############################################################################
# Metrics
###############################################################################

# Use no-op objects if prometheus_client is unavailable.
class _NoopMetric:
    def inc(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        pass

    def observe(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        pass


_request_counter: Any = Counter(  # type: ignore
    "psn_events_processed_total",
    "Total number of events processed",
    ["status"],
) if "Counter" in globals() else _NoopMetric()

_latency_histogram: Any = Histogram(  # type: ignore
    "psn_event_processing_latency_seconds",
    "Latency per event",
) if "Histogram" in globals() else _NoopMetric()


###############################################################################
# Event Processor
###############################################################################

class EventStreamProcessor:
    """
    Consumes from a Kafka topic, validates & transforms each message, then
    produces the enriched event downstream.
    """

    def __init__(self, config: ProcessorConfig) -> None:
        self._cfg = config
        self._shutdown_flag = threading.Event()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.setLevel(logging.INFO)

        self._consumer: Optional["Consumer"] = None
        self._producer: Optional["Producer"] = None

        # ------------------------------------------------------------------ #
        # Prepare transformations
        # ------------------------------------------------------------------ #
        self._transformers = BaseTransformer.create_instances(
            self._cfg.enabled_transformers, self._cfg.transform_kwargs
        )
        self._logger.info(
            "Initialized with transformers: %s",
            [t.transformer_id for t in self._transformers],
        )

    # ---------------------------------------------------------------------- #
    # Life-cycle
    # ---------------------------------------------------------------------- #
    def start(self) -> None:
        self._setup_metrics()
        self._setup_kafka()
        self._install_signal_handlers()
        self._logger.info("EventStreamProcessor started (PID=%s)", os.getpid())

        try:
            self._processing_loop()
        finally:
            self._shutdown()

    def _setup_metrics(self) -> None:
        if "start_http_server" in globals():
            start_http_server(self._cfg.metrics_port)
            self._logger.info("Prometheus metrics server running at :%s", self._cfg.metrics_port)
        else:
            self._logger.warning("prometheus_client not available ‑ metrics disabled")

    def _setup_kafka(self) -> None:
        if "Consumer" not in globals() or "Producer" not in globals():
            self._logger.error(
                "confluent_kafka library not found. Install it to enable streaming."
            )
            sys.exit(1)

        consumer_conf = {
            "bootstrap.servers": self._cfg.kafka.bootstrap_servers,
            "group.id": self._cfg.kafka.group_id,
            "auto.offset.reset": self._cfg.kafka.auto_offset_reset,
            "enable.auto.commit": self._cfg.kafka.enable_auto_commit,
            "security.protocol": self._cfg.kafka.security_protocol,
        }
        producer_conf = {"bootstrap.servers": self._cfg.kafka.bootstrap_servers}
        self._consumer = Consumer(consumer_conf)
        self._producer = Producer(producer_conf)

        self._consumer.subscribe([self._cfg.kafka.input_topic])
        self._logger.info(
            "Subscribed to topic '%s' (group=%s)",
            self._cfg.kafka.input_topic,
            self._cfg.kafka.group_id,
        )

    def _install_signal_handlers(self) -> None:
        def _signal_handler(signum: int, _frame: Any) -> None:
            self._logger.info("Received signal %s; shutting down gracefully.", signum)
            self._shutdown_flag.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _signal_handler)

    # ---------------------------------------------------------------------- #
    # Main Loop
    # ---------------------------------------------------------------------- #
    def _processing_loop(self) -> None:
        assert self._consumer is not None  # for mypy
        poll_timeout = 1.0  # seconds
        last_commit: float = time.time()

        while not self._shutdown_flag.is_set():
            msg = self._consumer.poll(poll_timeout)
            if msg is None:
                continue
            if msg.error():
                # Non-fatal: continue processing
                self._logger.error("Kafka error: %s", msg.error())
                _request_counter.labels(status="kafka_error").inc()
                continue

            with _latency_histogram.time():
                self._process_message(msg.value())

            # manual offset commit every max_poll_interval_sec
            if (
                not self._cfg.kafka.enable_auto_commit
                and time.time() - last_commit >= self._cfg.max_poll_interval_sec
            ):
                self._consumer.commit(asynchronous=False)
                last_commit = time.time()

    def _process_message(self, raw_bytes: bytes) -> None:
        status = "ok"
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
            event = SocialEvent.parse_obj(payload)
            context: TransformerContext = TransformerContext()

            for transformer in self._transformers:
                transformer.transform(event, context)

            self._emit_event(event)
        except (json.JSONDecodeError, ValidationError) as exc:
            status = "invalid"
            self._logger.warning("Invalid message dropped: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except
            status = "error"
            self._logger.exception("Unexpected processing error: %s", exc)
        finally:
            _request_counter.labels(status=status).inc()

    def _emit_event(self, event: SocialEvent) -> None:
        """
        Serialize the enriched event and push to the downstream topic.
        """
        assert self._producer is not None  # for mypy
        try:
            serialized = event.json().encode("utf-8")
            self._producer.produce(
                self._cfg.kafka.output_topic,
                serialized,
                on_delivery=self._delivery_report,
            )
            self._producer.poll(0)  # trigger delivery callbacks
        except KafkaException as exc:
            self._logger.error("Failed to produce event: %s", exc)
            _request_counter.labels(status="produce_error").inc()

    @staticmethod
    def _delivery_report(err: Optional[Exception], _msg: "Any") -> None:
        if err:
            logging.getLogger("EventStreamProcessor").error(
                "Delivery failed: %s", err
            )

    # ---------------------------------------------------------------------- #
    # Shutdown & Cleanup
    # ---------------------------------------------------------------------- #
    def _shutdown(self) -> None:
        self._logger.info("Shutting down …")
        deadline = time.time() + self._cfg.shutdown_grace_sec

        if self._producer:
            self._producer.flush(self._cfg.shutdown_grace_sec)

        if self._consumer:
            self._consumer.close()

        remaining = max(deadline - time.time(), 0)
        self._logger.info("Cleanup complete, exiting in %.2fs", remaining)
        time.sleep(remaining)


###############################################################################
# Entry-Point Helper
###############################################################################

def _from_env(var: str, default: str) -> str:
    return os.environ.get(var, default)


def build_default_config() -> ProcessorConfig:
    kafka_cfg = KafkaConfig(
        bootstrap_servers=_from_env("KAFKA_BOOTSTRAP", "localhost:9092"),
        group_id=_from_env("KAFKA_GROUP_ID", "psn-processor"),
        input_topic=_from_env("KAFKA_INPUT_TOPIC", "social_raw"),
        output_topic=_from_env("KAFKA_OUTPUT_TOPIC", "social_enriched"),
    )
    enabled_transformers = (
        os.environ.get("PSN_TRANSFORMERS", "sentiment,toxicity")
        .strip()
        .split(",")
    )
    return ProcessorConfig(
        kafka=kafka_cfg,
        metrics_port=int(_from_env("METRICS_PORT", "9405")),
        enabled_transformers=[t for t in enabled_transformers if t],
    )


###############################################################################
# CLI
###############################################################################

def main() -> None:
    """
    Example usage:

    $ export KAFKA_BOOTSTRAP="kafka:9092"
    $ python -m src.module_34
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    processor = EventStreamProcessor(build_default_config())
    processor.start()


if __name__ == "__main__":
    main()
```