```python
"""
PulseStream Nexus – module_36.py
================================

This module hosts an opinionated reference-implementation of a *streaming*
ingestion and transformation component that is fully aligned with the
PulseStream Nexus Clean Architecture guidelines.

The component:

1. Consumes social events from a Kafka topic (JSON/Avro payloads).
2. Validates payloads against the Confluent Schema Registry *and* a Great
   Expectations expectation suite.
3. Passes the validated events through a configurable **Strategy Pattern**
   transformation pipeline (sentiment, toxicity, virality, …).
4. Emits the enriched events to a downstream Kafka topic, while pushing
   rich Prometheus metrics and routing all raised exceptions to Sentry.

The code is purposely structured so it can be embedded into a micro-service
or imported into batch jobs (e.g. Spark Structured Streaming).  It remains
framework-agnostic and purely focused on the business / domain logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from asyncio import AbstractEventLoop
from dataclasses import dataclass, field
from textwrap import shorten
from types import TracebackType
from typing import Any, Dict, List, Optional, Protocol, Type

# --------------------------------------------------------------------------- #
# Optional «heavy» third-party dependencies. Fall back gracefully if missing. #
# --------------------------------------------------------------------------- #
try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
except ModuleNotFoundError:  # pragma: no-cover
    AIOKafkaConsumer = AIOKafkaProducer = None  # type: ignore

try:
    from fastavro import parse_schema, schemaless_reader
except ModuleNotFoundError:  # pragma: no-cover
    parse_schema = schemaless_reader = None  # type: ignore

try:
    import great_expectations as ge
except ModuleNotFoundError:  # pragma: no-cover
    ge = None  # type: ignore

try:
    import sentry_sdk
except ModuleNotFoundError:  # pragma: no-cover
    sentry_sdk = None  # type: ignore

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
except ModuleNotFoundError:  # pragma: no-cover
    # Cheap polyfill to keep code running when prometheus-client is absent.
    class _Noop:  # noqa: D401,E302
        def __init__(self, *a: Any, **kw: Any): ...

        def inc(self, *a: Any, **kw: Any): ...

        def set(self, *a: Any, **kw: Any): ...

        def observe(self, *a: Any, **kw: Any): ...

    Counter = Gauge = Histogram = _Noop  # type: ignore

# ------------------------------ Logging setup ------------------------------ #

_LOG_FORMAT = (
    "%(asctime)s [%(levelname)8s] [%(name)s] – "
    "%(message)s (%(filename)s:%(lineno)d)"
)
logging.basicConfig(
    level=os.getenv("PULSE_LOG_LEVEL", "INFO").upper(),
    format=_LOG_FORMAT,
    stream=sys.stdout,
)
logger = logging.getLogger("psn.module_36")

# -------------------------------- Metrics ---------------------------------- #

STREAM_EVENTS_TOTAL = Counter(
    "psn_stream_events_total",
    "Total number of events processed.",
    ["topic", "phase"],
)
STREAM_EXCEPTIONS_TOTAL = Counter(
    "psn_stream_exceptions_total", "Number of exceptions thrown by phase.", ["phase"]
)
STREAM_LATENCY_SEC = Histogram(
    "psn_stream_latency_seconds",
    "End-to-end event processing latency.",
    ["topic"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

HEALTH_GAUGE = Gauge("psn_ingestor_up", "Is the ingestor running? (1/0)")

# ----------------------------- Configuration --------------------------------#


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    input_topic: str = os.getenv("PULSE_INPUT_TOPIC", "social.raw")
    output_topic: str = os.getenv("PULSE_OUTPUT_TOPIC", "social.enriched")
    group_id: str = os.getenv("PULSE_CONSUMER_GROUP", "psn_ingestor")
    auto_offset_reset: str = os.getenv("PULSE_OFFSET_RESET", "earliest")
    security_protocol: str = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    sasl_mechanism: Optional[str] = os.getenv("KAFKA_SASL_MECHANISM")
    sasl_username: Optional[str] = os.getenv("KAFKA_SASL_USERNAME")
    sasl_password: Optional[str] = os.getenv("KAFKA_SASL_PASSWORD")
    ssl_cafile: Optional[str] = os.getenv("KAFKA_SSL_CAFILE")


@dataclass(frozen=True)
class SchemaConfig:
    registry_url: Optional[str] = os.getenv("SCHEMA_REGISTRY_URL")
    subject: Optional[str] = os.getenv("SCHEMA_SUBJECT")
    version: Optional[str] = os.getenv("SCHEMA_VERSION")
    # A pre-parsed schema can be injected for tests
    schema: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class TransformationConfig:
    enable_sentiment: bool = os.getenv("ENABLE_SENTIMENT", "true").lower() == "true"
    enable_toxicity: bool = os.getenv("ENABLE_TOXICITY", "true").lower() == "true"
    enable_virality: bool = os.getenv("ENABLE_VIRALITY", "false").lower() == "true"


@dataclass
class IngestorConfig:
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    schema: SchemaConfig = field(default_factory=SchemaConfig)
    transform: TransformationConfig = field(default_factory=TransformationConfig)
    metrics_port: int = int(os.getenv("METRICS_PORT", 9102))
    sentry_dsn: Optional[str] = os.getenv("SENTRY_DSN")
    expectation_suite_path: Optional[str] = os.getenv(
        "EXPECTATION_SUITE", "conf/expectations/social_events.json"
    )


# ------------------------ Strategy Pattern Classes ------------------------- #


class Transformer(Protocol):
    """Represents a domain transformation performed on a single event."""

    name: str

    async def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply the transformation to *event* and return the mutated object.
        Implementations should never mutate the given dict in-place.
        """


class SentimentTransformer:
    name = "sentiment"

    async def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        # Simplified rule-based sentiment analysis for demonstration.
        text: str = event.get("text", "")
        score = text.count("good") - text.count("bad")  # toy logic
        enriched = {**event, "sentiment_score": score}
        logger.debug("SentimentTransformer → %s", shortened(enriched))
        return enriched


class ToxicityTransformer:
    name = "toxicity"

    async def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        text = event.get("text", "").lower()
        toxic_words = {"hate", "kill", "stupid", "idiot"}
        toxicity = sum(word in text for word in toxic_words) / len(toxic_words)
        enriched = {**event, "toxicity_score": round(toxicity, 3)}
        logger.debug("ToxicityTransformer → %s", shortened(enriched))
        return enriched


class ViralityTransformer:
    name = "virality"

    async def transform(self, event: Dict[str, Any]) -> Dict[str, Any]:
        metrics = event.get("metrics", {})
        likes, replies, retweets = (
            metrics.get("likes", 0),
            metrics.get("replies", 0),
            metrics.get("retweets", 0),
        )
        virality = (likes * 0.5 + replies + retweets * 0.75) / max(
            likes + replies + retweets, 1
        )
        enriched = {**event, "virality_score": round(virality, 3)}
        logger.debug("ViralityTransformer → %s", shortened(enriched))
        return enriched


class TransformerRegistry:
    """
    Helper that wires config → concrete transformer instances.  Acts as a
    single façade from which the ingest service can iterate through the
    configured transformation chain.
    """

    _registry: Dict[str, Type[Transformer]] = {
        "sentiment": SentimentTransformer,
        "toxicity": ToxicityTransformer,
        "virality": ViralityTransformer,
    }

    def __init__(self, config: TransformationConfig) -> None:
        self._enabled: List[Transformer] = []
        for key, cls in self._registry.items():
            if getattr(config, f"enable_{key}", False):
                self._enabled.append(cls())
        enabled_names = [t.name for t in self._enabled]
        logger.info("Enabled transformers: %s", ", ".join(enabled_names))

    @property
    def chain(self) -> List[Transformer]:
        return self._enabled


# ---------------------- Validation / Quality Gate Layer -------------------- #


class SchemaValidator:
    """Lightweight Avro/JSON Schema validator."""

    def __init__(self, cfg: SchemaConfig) -> None:
        self._cfg = cfg
        self._parsed_schema: Optional[Dict[str, Any]] = None
        if parse_schema is None:
            logger.warning("fastavro not available; schema validation disabled.")

    def _load_schema(self) -> None:
        if parse_schema is None or self._cfg.schema:
            self._parsed_schema = self._cfg.schema
            return

        # A real codebase would query the Confluent Schema Registry here.
        # We skip the HTTP call for brevity and demonstration purposes.
        logger.debug("Fetching schema from registry is not implemented.")
        self._parsed_schema = None  # act as if not enforced

    def validate(self, raw: bytes) -> Dict[str, Any]:
        if self._parsed_schema is None:
            self._load_schema()

        if self._parsed_schema:
            try:
                # We assume Avro binary payloads if a schema is present.
                from io import BytesIO

                with BytesIO(raw) as bio:
                    record = schemaless_reader(bio, self._parsed_schema)
                logger.debug("Avro decoded event: %s", shortened(record))
                return record
            except Exception as exc:  # noqa: BLE001
                STREAM_EXCEPTIONS_TOTAL.labels(phase="avro_decode").inc()
                logger.exception("Schema validation failed.")
                raise ValueError("Invalid schema") from exc

        # Fallback: assume raw is UTF-8 encoded JSON.
        try:
            record = json.loads(raw.decode("utf-8"))
            logger.debug("JSON decoded event: %s", shortened(record))
            return record
        except json.JSONDecodeError as exc:
            STREAM_EXCEPTIONS_TOTAL.labels(phase="json_decode").inc()
            logger.error("JSON decode failed: %s", exc)
            raise

    # --------------------------------------------------------------------- #
    # Optional Great Expectations validation                                #
    # --------------------------------------------------------------------- #

    def assert_quality(self, record: Dict[str, Any], suite_path: Optional[str]) -> None:
        if ge is None or not suite_path:
            return  # Great Expectations not installed or disabled
        try:
            suite = ge.core.ExpectationSuite(**json.load(open(suite_path, encoding="utf-8")))
            validator = ge.validator.validator.Validator(record, suite)
            result = validator.validate()
            if not result.success:  # pragma: no-cover
                raise ValueError(
                    f"Great Expectations validation failed: {result.statistics}"
                )
        except FileNotFoundError:
            logger.warning("Expectation suite not found at %s; skipping validation.", suite_path)


# ----------------------- Sentry Error Reporting Layer ---------------------- #


class ErrorReporter:
    """Wrapper around Sentry's SDK that degrades gracefully when absent."""

    def __init__(self, dsn: Optional[str]) -> None:
        self._enabled = False
        if dsn and sentry_sdk is not None:
            sentry_sdk.init(dsn=dsn)
            self._enabled = True
            logger.info("Sentry integration enabled.")
        elif dsn:
            logger.warning("sentry-sdk missing; Sentry disabled.")

    def capture_exception(self, exc: BaseException) -> None:
        if self._enabled:
            sentry_sdk.capture_exception(exc)  # type: ignore[arg-type]


# ------------------------- Ingestor Service Layer -------------------------- #


class IngestorService:
    """
    A resilient, asynchronous service that acts as *orchestrator* around all
    previously defined layers: Kafka I/O, validation, transformation, output.
    """

    def __init__(self, cfg: IngestorConfig) -> None:
        self.cfg = cfg
        self.schema_validator = SchemaValidator(cfg.schema)
        self.transformers = TransformerRegistry(cfg.transform)
        self.error_reporter = ErrorReporter(cfg.sentry_dsn)
        self._producer: Optional[AIOKafkaProducer] = None
        self._consumer: Optional[AIOKafkaConsumer] = None

    # ------------------------------------------------------------------ #
    # Public life-cycle methods                                          #
    # ------------------------------------------------------------------ #

    async def start(self, loop: AbstractEventLoop | None = None) -> None:
        loop = loop or asyncio.get_event_loop()
        await self._setup_metrics()
        await self._setup_kafka(loop)
        HEALTH_GAUGE.set(1)
        logger.info("IngestorService successfully started.")

        try:
            await self._run()
        finally:
            HEALTH_GAUGE.set(0)

    async def stop(self) -> None:
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    # ------------------------------------------------------------------ #
    # Private helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _setup_metrics(self) -> None:
        start_http_server(self.cfg.metrics_port)
        logger.info("Prometheus metrics exposed at :%d", self.cfg.metrics_port)

    async def _setup_kafka(self, loop: AbstractEventLoop) -> None:
        if AIOKafkaConsumer is None or AIOKafkaProducer is None:  # pragma: no-cover
            raise RuntimeError("aiokafka is not installed.")

        self._consumer = AIOKafkaConsumer(
            self.cfg.kafka.input_topic,
            loop=loop,
            bootstrap_servers=self.cfg.kafka.bootstrap_servers,
            group_id=self.cfg.kafka.group_id,
            auto_offset_reset=self.cfg.kafka.auto_offset_reset,
            security_protocol=self.cfg.kafka.security_protocol,
            sasl_mechanism=self.cfg.kafka.sasl_mechanism,
            sasl_plain_username=self.cfg.kafka.sasl_username,
            sasl_plain_password=self.cfg.kafka.sasl_password,
            ssl_cafile=self.cfg.kafka.ssl_cafile,
            value_deserializer=lambda v: v,  # raw bytes
        )
        await self._consumer.start()

        self._producer = AIOKafkaProducer(
            loop=loop,
            bootstrap_servers=self.cfg.kafka.bootstrap_servers,
            security_protocol=self.cfg.kafka.security_protocol,
            sasl_mechanism=self.cfg.kafka.sasl_mechanism,
            sasl_plain_username=self.cfg.kafka.sasl_username,
            sasl_plain_password=self.cfg.kafka.sasl_password,
            ssl_cafile=self.cfg.kafka.ssl_cafile,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await self._producer.start()

    async def _run(self) -> None:
        assert self._consumer and self._producer  # mypy re-assurance

        async for raw_msg in self._consumer:
            ingest_start = time.perf_counter()
            try:
                STREAM_EVENTS_TOTAL.labels(
                    topic=self.cfg.kafka.input_topic, phase="consumed"
                ).inc()
                logger.debug("Message received: %s bytes", len(raw_msg.value))
                event = self.schema_validator.validate(raw_msg.value)
                self.schema_validator.assert_quality(
                    event, self.cfg.expectation_suite_path
                )
                for transformer in self.transformers.chain:
                    event = await transformer.transform(event)
                await self._producer.send_and_wait(
                    self.cfg.kafka.output_topic, value=event
                )
                STREAM_EVENTS_TOTAL.labels(
                    topic=self.cfg.kafka.output_topic, phase="produced"
                ).inc()
                STREAM_LATENCY_SEC.labels(topic=self.cfg.kafka.input_topic).observe(
                    time.perf_counter() - ingest_start
                )
            except Exception as exc:  # noqa: BLE001
                STREAM_EXCEPTIONS_TOTAL.labels(phase="ingestion").inc()
                self.error_reporter.capture_exception(exc)
                logger.exception("Failed to process message: %s", exc)
                # Decide whether to *commit* or *not* commit the offset.
                # Here we *do* commit to avoid poison-pill loops.
                continue

    # context manager sugar (useful in tests) ---------------------------- #

    async def __aenter__(self) -> "IngestorService":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.stop()


# ------------------------- CLI / Service Entrypoint ------------------------ #


def shortened(obj: Any, width: int = 120) -> str:
    """Utility for logging overly verbose objects."""
    return shorten(str(obj), width=width, placeholder="…")


def cli() -> None:  # pragma: no-cover
    """
    Fire-and-forget CLI entrypoint so `python -m src.module_36` just *works*.
    """
    cfg = IngestorConfig()
    service = IngestorService(cfg)

    # Windows event loop policy compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]

    try:
        logger.info("Starting PulseStream Nexus Ingestor… (press Ctrl+C to quit)")
        asyncio.run(service.start())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested by user – exiting.")
    finally:
        try:
            asyncio.run(service.stop())
        except Exception:  # noqa: BLE001
            logger.exception("Error during shutdown clean-up.")


if __name__ == "__main__":  # pragma: no-cover
    cli()
```