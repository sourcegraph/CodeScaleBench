```python
"""
src/module_17.py
PulseStream Nexus – Streaming Transformation Processor

This module implements a self-contained, production-ready enrichment processor
that consumes raw social-network events from Kafka (or an in-memory stub when
Kafka is unavailable), validates the incoming records, applies one or more
pluggable enrichment strategies (sentiment, toxicity, virality, …), publishes
the enriched payloads back to Kafka, and reports internal metrics through an
Observer interface.

Pattern highlights
------------------
• Strategy Pattern        – `BaseTransformer` & concrete implementations
• Observer Pattern        – `EventObservableMixin` + `EventObserver`
• Clean Architecture      – business logic isolated from I/O concerns
• Graceful degradation    – runs even when external libs (aiokafka, GE) are
                            missing, thanks to fall-back stubs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Type

# --------------------------------------------------------------------------- #
# Optional third-party dependencies                                           #
# --------------------------------------------------------------------------- #
try:
    # Kafka client
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – Kafka is optional
    AIOKafkaConsumer = None
    AIOKafkaProducer = None

try:
    # Great Expectations for rich data-quality enforcement
    import great_expectations as ge  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ge = None

# --------------------------------------------------------------------------- #
# Logging configuration                                                       #
# --------------------------------------------------------------------------- #
logger = logging.getLogger("pulstream.module_17")

# --------------------------------------------------------------------------- #
# Observer pattern helpers                                                    #
# --------------------------------------------------------------------------- #
class EventObserver(ABC):
    """Interface for consumers interested in processor events."""

    @abstractmethod
    async def update(self, event_type: str, payload: Dict[str, Any]) -> None: ...


class MetricsObserver(EventObserver):
    """
    Very small Prometheus/Grafana friendly stub that simply calls the supplied
    backend (sync) function from a thread.  Users may inject any callable that
    takes `(event_type, payload)`.
    """

    def __init__(
        self,
        metrics_backend: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self._backend = metrics_backend or self._default_backend

    async def update(self, event_type: str, payload: Dict[str, Any]) -> None:  # noqa: D401
        await asyncio.to_thread(self._backend, event_type, payload)

    def _default_backend(self, event_type: str, payload: Dict[str, Any]) -> None:
        logger.info("METRIC | %-16s | %s", event_type, payload)


class EventObservableMixin:
    """Mixin that allows attaching/detaching observers."""

    def __init__(self) -> None:
        self._observers: List[EventObserver] = []

    def attach(self, observer: EventObserver) -> None:
        self._observers.append(observer)

    async def _notify(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self._observers:
            return
        coros = (obs.update(event_type, payload) for obs in self._observers)
        await asyncio.gather(*coros, return_exceptions=True)


# --------------------------------------------------------------------------- #
# Data validation                                                             #
# --------------------------------------------------------------------------- #
class DataValidator:
    """
    Lightweight validator that falls back to a manual schema when Great
    Expectations is unavailable.
    """

    DEFAULT_SCHEMA: Dict[str, Any] = {
        "id": str,
        "source": str,
        "timestamp": (int, float),
        "payload": dict,
    }

    def __init__(self, schema: Optional[Dict[str, Any]] = None) -> None:
        self._schema = schema or self.DEFAULT_SCHEMA

        if ge is not None:
            # We keep a GE context around, but use it only when an expectation
            # suite for the processor already exists. Creating a full suite on
            # the fly would be overkill.
            self._ge_context = ge.get_context()
        else:
            self._ge_context = None

    # --------------------------------------------------------------------- #
    # Simple static-type validation (always available)                      #
    # --------------------------------------------------------------------- #
    def _validate_static_schema(self, data: Dict[str, Any]) -> bool:
        for field, expected in self._schema.items():
            if field not in data:
                logger.error("Validation error – missing field '%s' in %s", field, data)
                return False
            if not isinstance(data[field], expected):
                logger.error(
                    "Validation error – field '%s' expected %s, got %s (%r)",
                    field,
                    expected,
                    type(data[field]),
                    data[field],
                )
                return False
        return True

    # --------------------------------------------------------------------- #
    # Great Expectations validation (optional)                              #
    # --------------------------------------------------------------------- #
    def _validate_with_ge(self, data: Dict[str, Any]) -> bool:
        suite_name = "pulstream_core_stream_events"
        try:
            suite = self._ge_context.get_expectation_suite(suite_name)  # type: ignore[union-attr]
        except ge.exceptions.DataContextError:  # type: ignore
            # Suite missing -> fallback to static schema.
            logger.debug("GE suite '%s' not found – falling back to static schema.", suite_name)
            return self._validate_static_schema(data)

        # GE payload wrapper
        batch_kwargs = {
            "datasource": "default_runtime_datasource",
            "dataset": [data],
            "runtime_parameters": {"data": [data]},
            "batch_identifiers": {"default_identifier_name": "single_batch"},
        }

        results = self._ge_context.run_validation_operator(  # type: ignore[union-attr]
            "action_list_operator",
            assets_to_validate=[(batch_kwargs, suite)],
        )

        return results["success"]  # type: ignore[index]

    # --------------------------------------------------------------------- #
    # Unified entry point                                                   #
    # --------------------------------------------------------------------- #
    def validate(self, data: Dict[str, Any]) -> bool:
        if ge is not None and self._ge_context is not None:
            return self._validate_with_ge(data)
        return self._validate_static_schema(data)


# --------------------------------------------------------------------------- #
# Transformation strategies                                                   #
# --------------------------------------------------------------------------- #
class BaseTransformer(ABC):
    """Shared interface for enrichment steps."""

    @abstractmethod
    async def transform(self, data: Dict[str, Any]) -> Dict[str, Any]: ...


# Sentiment ---------------------------------------------------------------- #
class SentimentTransformer(BaseTransformer):
    """Extremely naive sentiment estimator (placeholder for ML model)."""

    async def transform(self, data: Dict[str, Any]) -> Dict[str, Any]:
        text: str = data.get("payload", {}).get("text", "")
        score = (sum(ord(c) for c in text) % 100) / 100  # Fake score in [0, 1]
        label: str
        if score > 0.6:
            label = "positive"
        elif score < 0.4:
            label = "negative"
        else:
            label = "neutral"

        data.setdefault("enrichments", {})["sentiment"] = {"score": score, "label": label}
        return data


# Toxicity ------------------------------------------------------------------ #
class ToxicityTransformer(BaseTransformer):
    """Extremely naive toxicity flagger."""

    async def transform(self, data: Dict[str, Any]) -> Dict[str, Any]:
        text: str = data.get("payload", {}).get("text", "")
        score = (sum(ord(c) for c in reversed(text)) % 100) / 100
        data.setdefault("enrichments", {})["toxicity"] = {"score": score, "flagged": score > 0.8}
        return data


# Virality ------------------------------------------------------------------ #
class ViralityTransformer(BaseTransformer):
    """Simple, deterministic virality calculation."""

    async def transform(self, data: Dict[str, Any]) -> Dict[str, Any]:
        metrics = data.get("payload", {}).get("metrics", {})
        score = (
            metrics.get("likes", 0) * 0.4
            + metrics.get("retweets", 0) * 0.5
            + metrics.get("replies", 0) * 0.1
        ) / 1_000.0
        data.setdefault("enrichments", {})["virality"] = {"score": min(1.0, score)}
        return data


# Registry ------------------------------------------------------------------ #
class TransformationStrategy(Enum):
    SENTIMENT = "sentiment"
    TOXICITY = "toxicity"
    VIRALITY = "virality"


_TRANSFORMER_REGISTRY: Dict[TransformationStrategy, Type[BaseTransformer]] = {
    TransformationStrategy.SENTIMENT: SentimentTransformer,
    TransformationStrategy.TOXICITY: ToxicityTransformer,
    TransformationStrategy.VIRALITY: ViralityTransformer,
}


def build_transformers(names: List[str]) -> List[BaseTransformer]:
    """Factory that converts CLI strings to transformer instances."""
    transformers: List[BaseTransformer] = []

    for name in names:
        try:
            strat = TransformationStrategy(name.lower())
        except ValueError:
            logger.warning("Unknown transformation '%s' – ignored.", name)
            continue

        cls = _TRANSFORMER_REGISTRY[strat]
        transformers.append(cls())
    return transformers


# --------------------------------------------------------------------------- #
# Kafka fall-back (when aiokafka is absent)                                   #
# --------------------------------------------------------------------------- #
if AIOKafkaConsumer is None:

    logger.warning("aiokafka is not installed – falling back to in-memory stubs.")

    class _DummyKafkaMessage:  # pylint: disable=too-few-public-methods
        """Mimics the minimal aiokafka message API we rely on."""

        def __init__(self, value: Any) -> None:
            self.value = value

    class DummyConsumer:  # noqa: D101
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._queue: asyncio.Queue[_DummyKafkaMessage] = asyncio.Queue()
            self._running = False

        async def start(self) -> None:
            self._running = True
            # inject a single message so that the processor does something
            sample_payload = {
                "id": "dummy-id",
                "source": "unit-test",
                "timestamp": datetime.utcnow().timestamp(),
                "payload": {"text": "hello world 🎉", "metrics": {"likes": 27, "retweets": 3}},
            }
            await self._queue.put(_DummyKafkaMessage(sample_payload))

        async def stop(self) -> None:
            self._running = False

        async def getone(self) -> _DummyKafkaMessage:
            return await self._queue.get()

        async def commit(self) -> None:  # noqa: D401
            pass

    class DummyProducer:  # noqa: D101
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def start(self) -> None: ...

        async def stop(self) -> None: ...

        async def send_and_wait(self, topic: str, value: Any) -> None:
            logger.info("[DummyProducer] topic=%s | payload=%s", topic, value)

else:
    # If aiokafka is available, we simply alias to the real class names.
    DummyConsumer = AIOKafkaConsumer  # type: ignore[assignment]
    DummyProducer = AIOKafkaProducer  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Main stream processor                                                       #
# --------------------------------------------------------------------------- #
class StreamProcessor(EventObservableMixin):
    """
    Async processor responsible for:
    1. Consuming raw events
    2. Validating payloads
    3. Applying enrichment transformations
    4. Emitting processed events
    """

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        transformer_names: List[str],
        *,
        validator: Optional[DataValidator] = None,
        kafka_bootstrap_servers: str = "localhost:9092",
        in_topic: str = "raw_events",
        out_topic: str = "enriched_events",
        group_id: str = "pulstream_module17",
        consumer_factory: Optional[Callable[..., Any]] = None,
        producer_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        super().__init__()

        self._transformers = build_transformers(transformer_names)
        self._validator = validator or DataValidator()

        # Kafka / stub plumbing
        self._bootstrap = kafka_bootstrap_servers
        self._in_topic = in_topic
        self._out_topic = out_topic
        self._group_id = group_id
        self._consumer_factory = consumer_factory or DummyConsumer
        self._producer_factory = producer_factory or DummyProducer
        self._consumer: Optional[DummyConsumer] = None
        self._producer: Optional[DummyProducer] = None

        # Async control
        self._stop_event = asyncio.Event()

    # Lifecycle ----------------------------------------------------------- #
    async def _setup(self) -> None:
        self._consumer = self._consumer_factory(
            self._in_topic,
            bootstrap_servers=self._bootstrap,
            group_id=self._group_id,
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")) if isinstance(v, (bytes, bytearray)) else v,  # type: ignore[arg-type]
        )

        self._producer = self._producer_factory(
            bootstrap_servers=self._bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        await self._consumer.start()
        await self._producer.start()
        logger.info("StreamProcessor online – in: '%s' | out: '%s'", self._in_topic, self._out_topic)
        await self._notify("startup", {"in_topic": self._in_topic, "out_topic": self._out_topic})

    async def _shutdown(self) -> None:
        await self._notify("shutdown", {})
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()
        logger.info("StreamProcessor shutdown complete.")

    # Main event loop ----------------------------------------------------- #
    async def run(self) -> None:
        await self._setup()
        try:
            async for event in self._consume():
                await self._process_event(event)
                if self._stop_event.is_set():
                    break
        finally:
            await self._shutdown()

    async def _consume(self) -> AsyncIterator[Dict[str, Any]]:
        assert self._consumer is not None  # nosec – guaranteed by _setup()
        while not self._stop_event.is_set():
            try:
                msg = await self._consumer.getone()
                yield msg.value  # type: ignore[attr-defined]
                await self._consumer.commit()
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Error while consuming – %s", exc)
                await self._notify("consume_error", {"error": str(exc)})
                await asyncio.sleep(1)

    async def _process_event(self, data: Dict[str, Any]) -> None:
        ts_start = datetime.utcnow()

        if not self._validator.validate(data):
            await self._notify("validation_failed", {"id": data.get("id")})
            return

        for transformer in self._transformers:
            try:
                data = await transformer.transform(data)
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Transformer '%s' failed – %s", transformer.__class__.__name__, exc)
                await self._notify(
                    "transform_error",
                    {"transformer": transformer.__class__.__name__, "error": str(exc)},
                )
                return

        latency_ms = (datetime.utcnow() - ts_start).total_seconds() * 1000.0
        await self._notify("processed", {"id": data.get("id"), "latency_ms": latency_ms})

        if self._producer:
            await self._producer.send_and_wait(self._out_topic, data)

    # Public helpers ------------------------------------------------------ #
    def stop(self) -> None:
        """Signal the main loop to exit gracefully."""
        self._stop_event.set()


# --------------------------------------------------------------------------- #
# CLI entry-point                                                             #
# --------------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pulstream-processor",
        description="PulseStream Nexus – Module 17 Streaming Processor",
    )
    parser.add_argument(
        "--strategies",
        metavar="NAME",
        nargs="+",
        default=[s.value for s in TransformationStrategy],
        help="Enrichment strategies to apply (sentiment, toxicity, virality, …)",
    )
    parser.add_argument("--bootstrap", default="localhost:9092", help="Kafka bootstrap servers")
    parser.add_argument("--in-topic", default="raw_events", help="Kafka topic for raw events")
    parser.add_argument("--out-topic", default="enriched_events", help="Kafka topic for enriched events")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Root logging level",
    )
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    processor = StreamProcessor(
        transformer_names=args.strategies,
        kafka_bootstrap_servers=args.bootstrap,
        in_topic=args.in_topic,
        out_topic=args.out_topic,
    )

    # Attach a basic observer so we at least see metrics in logs
    processor.attach(MetricsObserver())

    try:
        asyncio.run(processor.run())
    except KeyboardInterrupt:
        processor.stop()
        logger.info("Interrupted by user – shutting down.")


if __name__ == "__main__":  # pragma: no cover
    main()
```