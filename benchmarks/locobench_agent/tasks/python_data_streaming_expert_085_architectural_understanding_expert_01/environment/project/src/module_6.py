```python
"""
src/module_6.py

PulseStream Nexus – Real-time ETL/ELT streaming processor.

This module wires together:
    • Kafka-based ingestion / emission
    • Pluggable transformation strategies (Strategy Pattern)
    • Great Expectations data-quality safeguards
    • Prometheus runtime metrics
    • Sentry error capture
    • Graceful shutdown & back-pressure management

The code purposefully avoids framework-specific logic bleeding into
the core business rules, staying loyal to the Clean Architecture ethos.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Protocol, runtime_checkable

# ─────────────────────────────────────────────────────────────────────────────
# 3-rd-party dependencies guarded for optional availability
# ─────────────────────────────────────────────────────────────────────────────
try:
    from confluent_kafka import Consumer, KafkaError, Producer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – dev-only fallback
    Consumer = Producer = KafkaError = None  # type: ignore

try:
    import great_expectations as ge  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – optional
    ge = None  # type: ignore

from prometheus_client import Counter, Histogram, start_http_server  # type: ignore

import sentry_sdk  # type: ignore

# ─────────────────────────────────────────────────────────────────────────────
# Logging configuration
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pulse_stream.module_6")

# ─────────────────────────────────────────────────────────────────────────────
# Metrics (Prometheus)
# ─────────────────────────────────────────────────────────────────────────────
METRIC_MESSAGES_CONSUMED = Counter(
    "pulse_stream_messages_consumed_total",
    "Total number of messages consumed from source topic",
)
METRIC_MESSAGES_PRODUCED = Counter(
    "pulse_stream_messages_produced_total",
    "Total number of messages produced to sink topic",
)
METRIC_PROCESSING_LATENCY = Histogram(
    "pulse_stream_processing_latency_seconds",
    "Time spent processing a single record",
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5),
)

# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses & Configuration
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StreamConfig:
    """Runtime configuration for the streaming processor."""

    bootstrap_servers: str
    consume_topic: str
    produce_topic: str
    group_id: str = "pulse_stream_processor"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    max_poll_records: int = 100
    security_protocol: str | None = None
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None

    @classmethod
    def from_env(cls) -> "StreamConfig":
        """Build configuration from environment variables (12-factor compliance)."""
        return cls(
            bootstrap_servers=_require_env("KAFKA_BOOTSTRAP_SERVERS"),
            consume_topic=_require_env("KAFKA_CONSUME_TOPIC"),
            produce_topic=_require_env("KAFKA_PRODUCE_TOPIC"),
            group_id=os.getenv("KAFKA_GROUP_ID", "pulse_stream_processor"),
            auto_offset_reset=os.getenv("KAFKA_OFFSET_RESET", "earliest"),
            enable_auto_commit=_str2bool(os.getenv("KAFKA_ENABLE_AUTO_COMMIT", "false")),
            security_protocol=os.getenv("KAFKA_SECURITY_PROTOCOL"),
            sasl_mechanism=os.getenv("KAFKA_SASL_MECHANISM"),
            sasl_username=os.getenv("KAFKA_SASL_USERNAME"),
            sasl_password=os.getenv("KAFKA_SASL_PASSWORD"),
        )


@dataclass
class Record:
    """Domain representation of a social event."""

    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_kafka(cls, raw_value: bytes, headers: list[tuple[str, bytes]] | None = None) -> "Record":
        """Deserialize message from Kafka into Record."""
        try:
            payload = json.loads(raw_value.decode("utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover – invalid JSON
            raise MalformedPayloadError("JSON decoding failed") from exc
        meta_dict = {k: v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v for k, v in (headers or [])}
        return cls(payload=payload, metadata=meta_dict)

    def to_kafka(self) -> bytes:
        """Serialize Record back to bytes for Kafka."""
        return json.dumps(self.payload, separators=(",", ":")).encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────
class ProcessorError(Exception):
    """Base class for all processing-related errors."""


class MalformedPayloadError(ProcessorError):
    """Raised when incoming payload cannot be parsed."""


class ValidationError(ProcessorError):
    """Raised when Great Expectations validation fails."""


# ─────────────────────────────────────────────────────────────────────────────
# Validation layer (Great Expectations)
# ─────────────────────────────────────────────────────────────────────────────
class RecordValidator:
    """Encapsulates Great Expectations validation logic."""

    def __init__(self) -> None:
        if ge is None:
            logger.warning("Great Expectations not installed – skipping validation.")
        self._enabled = ge is not None
        if self._enabled:
            self._context = ge.get_context()

    def validate(self, record: Record) -> Record:
        """Validate the record against pre-defined expectation suite."""
        if not self._enabled:
            return record

        try:
            batch = ge.dataset.PandasDataset([record.payload])  # type: ignore[attr-defined]
            # Expect crucial fields to exist & be non-null
            batch.expect_column_to_exist("text")
            batch.expect_column_values_to_not_be_null("text")
            batch.expect_column_to_exist("timestamp")
            if not batch.validate().success:
                raise ValidationError("Expectation suite failed")
        except Exception as exc:
            raise ValidationError("Great Expectations errored") from exc
        return record


# ─────────────────────────────────────────────────────────────────────────────
# Transformation strategies
# ─────────────────────────────────────────────────────────────────────────────
@runtime_checkable
class TransformationStrategy(Protocol):
    name: str

    def transform(self, record: Record) -> Record: ...


class SentimentTransformer:
    """Adds naive sentiment score using a placeholder algorithm."""

    name = "sentiment"

    def transform(self, record: Record) -> Record:
        text = record.payload.get("text", "")
        # Placeholder sentiment score [-1, 1] based on simple heuristics.
        positive_words = {"love", "great", "awesome", "good", "happy"}
        negative_words = {"hate", "bad", "terrible", "sad", "angry"}
        score = 0
        tokens = {t.strip(".,!?").lower() for t in text.split()}
        score += len(tokens & positive_words)
        score -= len(tokens & negative_words)
        record.payload["sentiment_score"] = max(min(score / 5, 1), -1)
        return record


class ToxicityTransformer:
    """Flags messages with potential toxicity using keyword search."""

    name = "toxicity"

    def transform(self, record: Record) -> Record:
        toxic_keywords = {"idiot", "stupid", "dumb", "kill"}
        tokens = {t.strip(".,!?").lower() for t in record.payload.get("text", "").split()}
        record.payload["is_toxic"] = bool(tokens & toxic_keywords)
        return record


class ViralityTransformer:
    """Estimates virality (rough approximation)."""

    name = "virality"

    def transform(self, record: Record) -> Record:
        payload = record.payload
        reactions = payload.get("reactions", 0)  # likes/upvotes
        shares = payload.get("shares", 0)
        comments = payload.get("comments", 0)
        raw_score = reactions * 0.4 + shares * 0.4 + comments * 0.2
        payload["virality_score"] = raw_score
        return record


# ─────────────────────────────────────────────────────────────────────────────
# Processor (observer of Kafka topic)
# ─────────────────────────────────────────────────────────────────────────────
class StreamingProcessor:
    """Kafka consumer → transformation pipeline → producer."""

    def __init__(
        self,
        config: StreamConfig,
        transformers: Iterable[TransformationStrategy] | None = None,
        validator: RecordValidator | None = None,
    ) -> None:
        if Consumer is None or Producer is None:  # pragma: no cover
            raise RuntimeError("confluent-kafka library is required")

        self._cfg = config
        self._validator = validator or RecordValidator()
        self._transformers: List[TransformationStrategy] = list(transformers or [])
        self._consumer = Consumer(self._build_consumer_conf())
        self._producer = Producer(self._build_producer_conf())
        self._running = False

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def run_forever(self) -> None:
        """Blocking entry point. Starts event loop, handles signals."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._shutdown(s)))

        self._running = True
        logger.info("Subscribing to topic '%s'", self._cfg.consume_topic)
        self._consumer.subscribe([self._cfg.consume_topic])

        try:
            loop.run_until_complete(self._consume_loop())
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            logger.info("Processor terminated.")

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    async def _consume_loop(self) -> None:
        """Core polling loop – poll Kafka, transform, produce."""
        while self._running:
            msg_pack = self._consumer.consume(num_messages=self._cfg.max_poll_records, timeout=1.0)
            if not msg_pack:
                await asyncio.sleep(0.01)
                continue

            for msg in msg_pack:
                if msg is None:
                    continue
                if msg.error():  # pragma: no cover – consumer errors
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue  # expected
                    logger.error("Consumer error: %s", msg.error())
                    continue

                METRIC_MESSAGES_CONSUMED.inc()
                start_time = time.perf_counter()
                try:
                    record = Record.from_kafka(msg.value(), headers=msg.headers())
                    record = self._validator.validate(record)
                    record = self._apply_transformations(record)
                    self._emit(record)
                    METRIC_PROCESSING_LATENCY.observe(time.perf_counter() - start_time)
                except ProcessorError as exc:
                    sentry_sdk.capture_exception(exc)
                    logger.warning("Record skipped – %s", exc, exc_info=False)

            # Manual commit for precise offset control
            if not self._cfg.enable_auto_commit:
                self._consumer.commit(asynchronous=True)

    async def _shutdown(self, sig: signal.Signals) -> None:  # noqa: D401
        """Initiate graceful shutdown."""
        logger.info("Shutdown requested by %s", sig.name)
        if not self._running:
            return
        self._running = False
        self._consumer.close()
        # Wait for producer delivery callbacks
        await asyncio.to_thread(self._producer.flush, timeout=5.0)

    # --------------------------------------------------------------------- #
    # Kafka config assembly
    # --------------------------------------------------------------------- #
    def _build_consumer_conf(self) -> Mapping[str, Any]:
        common = {
            "bootstrap.servers": self._cfg.bootstrap_servers,
            "group.id": self._cfg.group_id,
            "auto.offset.reset": self._cfg.auto_offset_reset,
            "enable.auto.commit": self._cfg.enable_auto_commit,
        }
        common.update(self._security_conf())
        return common

    def _build_producer_conf(self) -> Mapping[str, Any]:
        conf: Dict[str, Any] = {"bootstrap.servers": self._cfg.bootstrap_servers}
        conf.update(self._security_conf())
        conf["queue.buffering.max.messages"] = 100000
        conf["retries"] = 3
        return conf

    def _security_conf(self) -> Dict[str, Any]:
        if not self._cfg.security_protocol:
            return {}
        return {
            "security.protocol": self._cfg.security_protocol,
            "sasl.mechanisms": self._cfg.sasl_mechanism,
            "sasl.username": self._cfg.sasl_username,
            "sasl.password": self._cfg.sasl_password,
        }

    # --------------------------------------------------------------------- #
    # Transformation pipeline
    # --------------------------------------------------------------------- #
    def _apply_transformations(self, record: Record) -> Record:
        for transformer in self._transformers:
            record = transformer.transform(record)
        return record

    # --------------------------------------------------------------------- #
    # Emission
    # --------------------------------------------------------------------- #
    def _emit(self, record: Record) -> None:
        try:
            self._producer.produce(
                topic=self._cfg.produce_topic,
                key=record.payload.get("id", "").encode("utf-8"),
                value=record.to_kafka(),
                on_delivery=lambda err, _: self._delivery_report(err),
            )
            METRIC_MESSAGES_PRODUCED.inc()
        except BufferError as exc:  # pragma: no cover
            sentry_sdk.capture_exception(exc)
            logger.error("Producer buffer full – dropping message")

    @staticmethod
    def _delivery_report(err: KafkaError | None) -> None:  # noqa: D401
        if err is not None:  # pragma: no cover
            logger.error("Delivery failed: %s", err)


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────
def _require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        logger.critical("Environment variable '%s' is required", key)
        raise SystemExit(1)
    return value


def _str2bool(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "y"}


# ─────────────────────────────────────────────────────────────────────────────
# Module entrypoint
# ─────────────────────────────────────────────────────────────────────────────
def _init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment=os.getenv("ENVIRONMENT", "development"),
        )
        logger.info("Sentry initialised.")


def _init_prometheus() -> None:
    port = int(os.getenv("PROMETHEUS_PORT", "8001"))
    start_http_server(port)
    logger.info("Prometheus metrics exposed on :%d", port)


def main() -> None:  # pragma: no cover
    """CLI wrapper – bootstraps runtime components and starts processor."""
    _init_sentry()
    _init_prometheus()

    cfg = StreamConfig.from_env()
    processor = StreamingProcessor(
        config=cfg,
        transformers=[SentimentTransformer(), ToxicityTransformer(), ViralityTransformer()],
    )
    processor.run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
```