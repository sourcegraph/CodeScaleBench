```python
"""
crowdpay_connect.services.crowdpod_service.app.events.consumer
----------------------------------------------------------------
Asynchronous Kafka consumer for CrowdPod domain events.  Responsible for:

* Validating & decoding incoming event envelopes
* Persisting raw events in the event-store (append-only, event-sourcing)
* Dispatching the domain events to registered handlers (CQRS projections,
  risk-engine, notification service, etc.)
* Gracefully handling back-pressure, retries and dead-lettering
* Exposing lifecycle hooks for health-checks and graceful shutdown
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

import backoff
from aiokafka import AIOKafkaConsumer, ConsumerRecord
from aiokafka.helpers import create_ssl_context
from pydantic import BaseModel, Field, ValidationError, validator

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_KAFKA_BROKERS = "kafka-broker:9092"
DEFAULT_TOPIC = "crowdpod-events"
DEFAULT_CONSUMER_GROUP = "crowdpod_service"
DEFAULT_DEAD_LETTER_TOPIC = "crowdpod-events-dlx"

LOGGER = logging.getLogger("crowdpay.crowdpod.event_consumer")
logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)8s | %(name)s | %(message)s "
        "[%(filename)s:%(lineno)d]"
    ),
)


# ============================================================================
# Event primitives
# ============================================================================


class EventEnvelope(BaseModel):
    """
    Standardised wrapper for all CrowdPay domain events.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, alias="event_id")
    type: str = Field(..., alias="event_type")
    version: int = Field(..., gt=0, alias="schema_version")
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    payload: Dict[str, Any]

    class Config:
        allow_population_by_field_name = True
        json_encoders = {uuid.UUID: str, datetime: lambda v: v.isoformat()}

    @validator("occurred_at", pre=True)
    def _parse_dt(cls, v):
        return (
            datetime.fromisoformat(v)
            if isinstance(v, str)
            else v.astimezone(timezone.utc)
        )

    def model_dump_json(self) -> str:  # pragma: no cover
        return self.model_dump(by_alias=True, json_encoders=self.__config__.json_encoders)


class DomainEvent(BaseModel):
    """
    Marker base-class for strongly-typed domain events.
    """

    envelope: EventEnvelope

    @property
    def type(self) -> str:
        return self.envelope.type


# ============================================================================
# Event handling contracts
# ============================================================================


class EventHandler(Protocol):
    """
    Handler callable contract (async or sync).
    """

    def __call__(self, event: DomainEvent) -> Awaitable[None] | None: ...


class EventStore(Protocol):
    """
    Minimal event-store contract for append-only persistence.
    """

    async def append(self, envelope: EventEnvelope) -> None: ...


# ============================================================================
# Concrete, in-memory event-store (dev/test only)
# ============================================================================


class InMemoryEventStore:
    """
    Debug-friendly, volatile event-store implementation.
    """

    def __init__(self) -> None:
        self._events: list[EventEnvelope] = []
        self._lock = asyncio.Lock()

    async def append(self, envelope: EventEnvelope) -> None:
        async with self._lock:
            self._events.append(envelope)
            LOGGER.debug("Event appended to in-memory store [total=%s]", len(self._events))

    # Convenience for tests / REPL
    def all_events(self) -> list[EventEnvelope]:  # pragma: no cover
        return list(self._events)


# ============================================================================
# Exponential back-off helpers
# ============================================================================


def _exponential_backoff_hdlr(details: dict[str, Any]) -> None:
    LOGGER.warning(
        "Back-off %s: retrying %s in %.1fs",
        details["tries"],
        details["target"].__name__,
        details["wait"],
    )


def _exponential_giveup_hdlr(details: dict[str, Any]) -> None:  # pragma: no cover
    LOGGER.error(
        "Function %s failed permanently after %s tries",
        details["target"].__name__,
        details["tries"],
    )


# ============================================================================
# Kafka consumer
# ============================================================================


@dataclass
class KafkaAuthConfig:
    enable_ssl: bool = False
    ssl_cafile: Optional[str] = None
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None
    sasl_username: Optional[str] = None
    sasl_password: Optional[str] = None
    sasl_mechanism: str = "SCRAM-SHA-512"

    def ssl_context(self):
        if not self.enable_ssl:
            return None
        if not self.ssl_cafile:
            raise ValueError("ssl_cafile is required when SSL is enabled")
        return create_ssl_context(
            cafile=self.ssl_cafile,
            certfile=self.ssl_certfile,
            keyfile=self.ssl_keyfile,
        )


class EventConsumer:
    """
    Production-grade, asyncio-based Kafka consumer.

    Usage
    -----
        consumer = EventConsumer(
            bootstrap_servers=DEFAULT_KAFKA_BROKERS,
            topic=DEFAULT_TOPIC,
            handlers=handlers,
            event_store=event_store,
        )
        await consumer.run_forever()
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str = DEFAULT_KAFKA_BROKERS,
        topic: str = DEFAULT_TOPIC,
        group_id: str = DEFAULT_CONSUMER_GROUP,
        auth: Optional[KafkaAuthConfig] = None,
        handlers: Dict[str, EventHandler] | None = None,
        event_store: EventStore | None = None,
        dlx_topic: str = DEFAULT_DEAD_LETTER_TOPIC,
        max_retries: int = 5,
        auto_offset_reset: str = "latest",
    ) -> None:
        self._running = False
        self._topic = topic
        self._dlx_topic = dlx_topic
        self._handlers: Dict[str, EventHandler] = handlers or {}
        self._event_store: EventStore = event_store or InMemoryEventStore()
        self._max_retries = max_retries

        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,  # manual commit for at-least-once
            auto_offset_reset=auto_offset_reset,
            security_protocol="SSL" if auth and auth.enable_ssl else "PLAINTEXT",
            ssl_context=auth.ssl_context() if auth else None,
            sasl_mechanism=(auth.sasl_mechanism if auth and auth.sasl_username else None),
            sasl_plain_username=auth.sasl_username if auth else None,
            sasl_plain_password=auth.sasl_password if auth else None,
            value_deserializer=lambda v: v,  # raw bytes
        )

    # --------------------------------------------------------------------- #
    # Registration API
    # --------------------------------------------------------------------- #

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        if event_type in self._handlers:
            LOGGER.warning("Overwriting existing handler for %s", event_type)
        self._handlers[event_type] = handler

    # --------------------------------------------------------------------- #
    # Lifecycle management
    # --------------------------------------------------------------------- #

    async def run_forever(self) -> None:
        if self._running:
            LOGGER.warning("EventConsumer is already running")
            return
        self._running = True

        await self._consumer.start()
        LOGGER.info(
            "Kafka consumer started on [%s], subscribed to [%s]",
            ",".join(self._consumer._client.cluster.brokers()),
            self._topic,
        )

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.shutdown(s)))

        try:
            while self._running:
                messages = await self._consumer.getmany(timeout_ms=1000)
                await self._process_batch(messages)
        finally:
            await self._consumer.stop()
            LOGGER.info("Kafka consumer stopped.")

    async def shutdown(self, signum: signal.Signals | None = None) -> None:
        if not self._running:
            return
        LOGGER.info("Shutdown requested due to signal=%s", getattr(signum, "name", signum))
        self._running = False  # will break the loop

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    async def _process_batch(self, messages: Dict[str, list[ConsumerRecord]]) -> None:
        """
        Process a batch of Kafka ConsumerRecord(s).
        """
        for tp, records in messages.items():
            for record in records:
                try:
                    await self._process_record(record)
                    # Commit offset once processing succeeds
                    await self._consumer.commit({tp: record.offset + 1})
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Failed to process record offset=%s: %s", record.offset, exc)
                    # Do not commit offset so that we can retry (at-least-once)

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=lambda self: self._max_retries,
        on_backoff=_exponential_backoff_hdlr,
        on_giveup=_exponential_giveup_hdlr,
        jitter=None,
    )
    async def _process_record(self, record: ConsumerRecord) -> None:
        """
        Decode JSON, validate schema, dispatch to handler + persist.

        Retries with exponential back-off for transient failures.
        """

        LOGGER.debug("Processing Kafka record offset=%s", record.offset)
        raw_json: str = record.value.decode()
        envelope = self._parse_envelope(raw_json)

        # Persist to the event-store BEFORE side effects (event sourcing)
        await self._event_store.append(envelope)

        # Dispatch
        await self._dispatch(envelope)

    def _parse_envelope(self, raw_json: str) -> EventEnvelope:
        try:
            data = json.loads(raw_json)
            envelope = EventEnvelope.parse_obj(data)
            return envelope
        except (json.JSONDecodeError, ValidationError) as exc:
            # Publish to Dead-Letter Queue and move on
            LOGGER.error("Invalid envelope, publishing to DLX: %s", exc)
            asyncio.create_task(self._publish_to_dlx(raw_json))
            # Re-raise to trigger back-off logic (commit offset once retries done)
            raise

    async def _dispatch(self, envelope: EventEnvelope) -> None:
        event_type = envelope.type
        handler = self._handlers.get(event_type)

        if handler is None:
            LOGGER.warning("No handler registered for event_type=%s", event_type)
            return

        result = handler(DomainEvent(envelope=envelope))
        if asyncio.iscoroutine(result):
            await result

    async def _publish_to_dlx(self, payload: str | bytes) -> None:
        """
        Push invalid / poison message into a dead-letter topic.

        Note: This method intentionally uses a *new* producer per call to avoid
        blocking the consumer in the hot path.
        """
        from aiokafka import AIOKafkaProducer  # local import to reduce cold-start

        producer = AIOKafkaProducer(
            bootstrap_servers=",".join(self._consumer._client.cluster.brokers()),
            value_serializer=lambda v: v if isinstance(v, (bytes, bytearray)) else v.encode(),
        )
        try:
            await producer.start()
            await producer.send_and_wait(self._dlx_topic, payload)
            LOGGER.info("Poison message forwarded to DLX topic '%s'", self._dlx_topic)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Unable to publish message to DLX: %s", exc)
        finally:
            await producer.stop()


# ============================================================================
# Example handlers (to be replaced by real implementations)
# ============================================================================


async def handle_crowdpod_created(event: DomainEvent) -> None:  # pragma: no cover
    LOGGER.info("CrowdPod created -> %s", event.envelope.payload)


def handle_crowdpod_funded(event: DomainEvent) -> None:  # pragma: no cover
    LOGGER.info("CrowdPod funded -> %s", event.envelope.payload)


# ============================================================================
# Entry-point (local development)
# ============================================================================

if __name__ == "__main__":  # pragma: no cover
    # Quick-start for local development: `python -m consumer`
    # -------------------------------------------------------
    handlers_registry: Dict[str, EventHandler] = {
        "CrowdPodCreated": handle_crowdpod_created,
        "CrowdPodFunded": handle_crowdpod_funded,
    }

    consumer = EventConsumer(
        bootstrap_servers=DEFAULT_KAFKA_BROKERS,
        topic=DEFAULT_TOPIC,
        handlers=handlers_registry,
        event_store=InMemoryEventStore(),
    )

    try:
        asyncio.run(consumer.run_forever())
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user – exiting.")
        sys.exit(0)
```