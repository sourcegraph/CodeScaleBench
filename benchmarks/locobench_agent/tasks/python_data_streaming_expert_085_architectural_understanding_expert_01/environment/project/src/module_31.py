```python
"""
PulseStream Nexus – Streaming Transformation Module
---------------------------------------------------

This module provides an opinionated, production-ready implementation of a
pluggable streaming transformer that consumes events from a Kafka topic,
validates the payload against a JSONSchema, enriches / transforms it using a
Strategy registry, and publishes the result to an output topic.  Metrics are
exported to Prometheus and extensive logging / error-handling safeguards are in
place to ensure operational transparency.

The public surface of this module is intentionally small:

    1. TransformerRegistry  – registers and resolves transformation strategies
    2. StreamProcessor      – orchestrates consumption, validation,
                              transformation, and production
    3. BaseTransformer      – abstract parent class for concrete strategies
    4. ProcessorConfig      – type-safe runtime configuration

Usage
-----

>>> from module_31 import (
...     TransformerRegistry,
...     StreamProcessor,
...     ProcessorConfig,
...     BaseTransformer,
... )
>>>
>>> class LowercaseTransformer(BaseTransformer):
...     event_type = "tweet"
...
...     def transform(self, event: dict) -> dict:
...         event["text"] = event["text"].lower()
...         return event
...
>>> registry = TransformerRegistry()
>>> registry.register(LowercaseTransformer())
>>> cfg = ProcessorConfig(
...     bootstrap_servers=["localhost:9092"],
...     input_topic="raw_tweets",
...     output_topic="clean_tweets",
...     consumer_group="tweet_transformer_v1",
... )
>>> processor = StreamProcessor(config=cfg, registry=registry)
>>> processor.start()   # blocking call – use .run_async() for asyncio variant
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Type

try:
    # kafka-python ≥ 2.0
    from kafka import KafkaConsumer, KafkaProducer
    from kafka.errors import KafkaError
except ModuleNotFoundError:  # pragma: no cover
    # CI / local environment might not have Kafka installed. Provide no-op stubs
    class _KafkaStub:
        def __init__(self, *_, **__):
            raise RuntimeError(
                "Kafka libraries not available. "
                "Install with `pip install kafka-python`."
            )

    KafkaProducer = KafkaConsumer = _KafkaStub  # type: ignore
    KafkaError = Exception  # type: ignore

try:
    from prometheus_client import Counter, Histogram, start_http_server
except ModuleNotFoundError:  # pragma: no cover
    # Fallback dummy metrics that behave like their counterparts but do nothing.
    class _NoOpMetric:
        def __getattr__(self, name):  # noqa: D401
            def _noop(*_, **__):
                return None

            return _noop

    def start_http_server(*_, **__):  # type: ignore
        pass

    Counter = Histogram = _NoOpMetric  # type: ignore

try:
    import jsonschema
except ModuleNotFoundError:  # pragma: no cover
    jsonschema = None  # type: ignore

logger = logging.getLogger("pulstream.module_31")
logging.basicConfig(
    level=os.getenv("PULSESTREAM_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


# --------------------------------------------------------------------------- #
#  Configuration DataClass
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProcessorConfig:
    """
    Runtime configuration for StreamProcessor.

    Parameters
    ----------
    bootstrap_servers:
        List of Kafka brokers.
    input_topic:
        Name of the input topic from which raw events are consumed.
    output_topic:
        Name of the output topic to which transformed events are produced.
    consumer_group:
        Kafka consumer group id.
    max_batch_size:
        Upper bound of records processed before flush/commit.
    metrics_port:
        Port exposed for Prometheus to scrape.
    schema:
        Optional JSONSchema dict to validate incoming payloads.
    """

    bootstrap_servers: List[str]
    input_topic: str
    output_topic: str
    consumer_group: str
    max_batch_size: int = 500
    metrics_port: int = 8000
    schema: Optional[Dict] = None
    # Additional Kafka-specific overrides
    consumer_options: Dict = field(default_factory=dict)
    producer_options: Dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  Strategy / Registry
# --------------------------------------------------------------------------- #
class BaseTransformer:
    """
    Abstract base class for event transformers.

    Sub-classes must define:
        - event_type: str  – descriptor used to route events
        - transform(self, event: dict) -> dict
    """

    event_type: str = "<undefined>"

    def transform(self, event: Dict) -> Dict:  # noqa: D401
        raise NotImplementedError


class TransformerRegistry:
    """
    A threadsafe in-memory registry mapping event_type -> transformer instance.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._registry: Dict[str, BaseTransformer] = {}

    # --------------------------------------------------------------------- #
    #  Registry Manipulation
    # --------------------------------------------------------------------- #
    def register(self, transformer: BaseTransformer) -> None:
        """
        Register a new transformer for the transformer's `event_type`.
        If a transformer for the same event_type already exists, it is replaced.
        """
        with self._lock:
            self._registry[transformer.event_type] = transformer
            logger.debug("Registered transformer for event_type=%s", transformer.event_type)

    def unregister(self, event_type: str) -> None:
        """
        Remove transformer associated with `event_type` if present.
        """
        with self._lock:
            self._registry.pop(event_type, None)
            logger.debug("Unregistered transformer event_type=%s", event_type)

    def get(self, event_type: str) -> Optional[BaseTransformer]:
        """
        Retrieve transformer for a given event_type, or None.
        """
        with self._lock:
            return self._registry.get(event_type)

    # --------------------------------------------------------------------- #
    #  Iteration / Inspection
    # --------------------------------------------------------------------- #
    def __iter__(self) -> Iterable[BaseTransformer]:
        with self._lock:
            return iter(self._registry.values())

    def snapshot(self) -> Dict[str, str]:
        """
        Return a lightweight snapshot of the registry for diagnostics.
        """
        with self._lock:
            return {k: v.__class__.__name__ for k, v in self._registry.items()}


# --------------------------------------------------------------------------- #
#  Internal: Metrics
# --------------------------------------------------------------------------- #
_EVENTS_CONSUMED = Counter(
    "pulstream_events_consumed_total", "Total number of raw events consumed"
)
_EVENTS_PRODUCED = Counter(
    "pulstream_events_produced_total", "Total number of transformed events output"
)
_EVENTS_FAILED_VALIDATION = Counter(
    "pulstream_events_failed_validation_total", "Events that failed JSONSchema validation"
)
_EVENT_LATENCY = Histogram(
    "pulstream_event_processing_latency_seconds",
    "Time taken to process a single event",
    buckets=(0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)


# --------------------------------------------------------------------------- #
#  Internal: JSONSchema Validation
# --------------------------------------------------------------------------- #
class _Validator:
    def __init__(self, schema: Optional[Dict]) -> None:
        self._schema = schema
        if schema and not jsonschema:  # pragma: no cover
            raise RuntimeError(
                "jsonschema not available but a schema was provided. "
                "Run `pip install jsonschema`."
            )
        self._compiled = jsonschema.Draft7Validator(schema) if schema else None

    def validate(self, payload: Dict) -> bool:
        if not self._compiled:
            return True
        errors = sorted(self._compiled.iter_errors(payload), key=lambda e: e.path)
        if errors:
            _EVENTS_FAILED_VALIDATION.inc()
            logger.debug("Validation errors: %s", errors)
            return False
        return True


# --------------------------------------------------------------------------- #
#  Stream Processor
# --------------------------------------------------------------------------- #
class StreamProcessor:
    """
    Main entry-point class that coordinates streaming ETL.

    The processor is intentionally synchronous / blocking to simplify back-pressure.
    For async workloads use `.run_async()` which spins a thread and returns
    immediately.
    """

    def __init__(
        self,
        config: ProcessorConfig,
        registry: TransformerRegistry,
        consumer_cls: Type = KafkaConsumer,
        producer_cls: Type = KafkaProducer,
    ):
        self._cfg = config
        self._registry = registry
        self._validator = _Validator(config.schema)
        self._running = threading.Event()
        self._running.clear()

        # Start Prometheus exposition early
        if os.getenv("PULSESTREAM_ENABLE_PROM_METRICS", "1") == "1":
            start_http_server(self._cfg.metrics_port)
            logger.info("Prometheus metrics server started on port %d", self._cfg.metrics_port)

        # Build Kafka consumer/producer
        self._consumer = consumer_cls(
            self._cfg.input_topic,
            bootstrap_servers=self._cfg.bootstrap_servers,
            group_id=self._cfg.consumer_group,
            enable_auto_commit=False,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            **(self._cfg.consumer_options or {}),
        )
        self._producer = producer_cls(
            bootstrap_servers=self._cfg.bootstrap_servers,
            value_serializer=lambda m: json.dumps(m).encode("utf-8"),
            **(self._cfg.producer_options or {}),
        )

    # --------------------------------------------------------------------- #
    #  Public API
    # --------------------------------------------------------------------- #
    def start(self) -> None:
        """
        Start the processing loop (blocking).
        """
        self._running.set()
        logger.info(
            "StreamProcessor starting with config: in=%s out=%s group=%s",
            self._cfg.input_topic,
            self._cfg.output_topic,
            self._cfg.consumer_group,
        )
        self._setup_signal_handlers()
        self._main_loop()

    def run_async(self) -> threading.Thread:
        """
        Start the processor in a background daemon thread.
        """
        thread = threading.Thread(target=self.start, daemon=True, name="StreamProcessor")
        thread.start()
        return thread

    def stop(self, *_: object) -> None:
        """
        Signal the processor to stop gracefully. Can be used as a signal handler.
        """
        logger.info("Termination requested. Draining & shutting down …")
        self._running.clear()

    # --------------------------------------------------------------------- #
    #  Internal helpers
    # --------------------------------------------------------------------- #
    def _setup_signal_handlers(self) -> None:
        # Ensure only the main thread registers signal handlers
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self.stop)

    @contextmanager
    def _timed_event(self) -> Iterable[None]:
        """
        Context manager used to observe per-event processing latency.
        """
        start_ts = time.time()
        try:
            yield
        finally:
            _EVENT_LATENCY.observe(time.time() - start_ts)

    # --------------------------------------------------------------------- #
    #  Core loop
    # --------------------------------------------------------------------- #
    def _main_loop(self) -> None:  # noqa: C901 – complex but acceptable
        try:
            while self._running.is_set():
                records = self._consumer.poll(timeout_ms=1000, max_records=self._cfg.max_batch_size)
                if not records:
                    continue

                for message in records:
                    with self._timed_event():
                        try:
                            self._process_record(message.value)
                            _EVENTS_CONSUMED.inc()
                        except Exception as exc:  # pragma: no cover
                            logger.exception("Unexpected error while processing record: %s", exc)

                # Commit offsets & flush producer
                try:
                    self._consumer.commit()
                except KafkaError as err:  # pragma: no cover
                    logger.warning("Kafka commit failed: %s", err)

                self._producer.flush()
        finally:
            self._shutdown()

    def _process_record(self, payload: Dict) -> None:
        if not self._validator.validate(payload):
            logger.debug("Dropping invalid payload: %s", payload)
            return

        event_type = payload.get("event_type")
        transformer = self._registry.get(event_type)
        if not transformer:
            logger.debug("No transformer registered for event_type=%s. Skipping.", event_type)
            return

        transformed = transformer.transform(payload)

        # Publish result
        self._producer.send(self._cfg.output_topic, transformed)
        _EVENTS_PRODUCED.inc()
        logger.debug(
            "Produced transformed event_type=%s key=%s",
            event_type,
            payload.get("id") or "<unknown>",
        )

    def _shutdown(self) -> None:
        """
        Ensure all network buffers are flushed and the consumer group leaves cleanly.
        """
        logger.info("Shutting down StreamProcessor …")
        with contextlib.suppress(Exception):
            self._producer.flush(10)
            self._producer.close()
        with contextlib.suppress(Exception):
            self._consumer.close()
        logger.info("Shutdown complete.")


# --------------------------------------------------------------------------- #
#  Default CLI entrypoint
# --------------------------------------------------------------------------- #
def _build_default_registry() -> TransformerRegistry:
    """
    Build a registry with built-in transformers shipped with PulseStream Nexus.
    Real deployments will likely override this with DI frameworks.
    """
    registry = TransformerRegistry()

    class _EchoTransformer(BaseTransformer):
        event_type = "echo"

        def transform(self, event: Dict) -> Dict:
            event.setdefault("meta", {})["echo_processed_at"] = time.time()
            return event

    registry.register(_EchoTransformer())
    return registry


def main() -> None:  # pragma: no cover
    """
    Executed when running `python -m module_31`.
    Provides a quick-start with sane defaults for local development.
    """
    cfg = ProcessorConfig(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "localhost:9092").split(","),
        input_topic=os.getenv("INPUT_TOPIC", "pulstream.raw"),
        output_topic=os.getenv("OUTPUT_TOPIC", "pulstream.enriched"),
        consumer_group=os.getenv("CONSUMER_GROUP", "pulstream_demo"),
        metrics_port=int(os.getenv("METRICS_PORT", "8000")),
    )

    registry = _build_default_registry()
    processor = StreamProcessor(cfg, registry)
    processor.start()


if __name__ == "__main__":  # pragma: no cover
    main()
```