```python
"""
crowdpay_connect.services.kyc_service.app.events.producer
========================================================

As part of the CrowdPay Connect KYC micro-component, this module is
responsible for emitting **domain events** to the platform’s event bus
(Kafka).  Down-stream consumers—such as risk-assessment, compliance
reporting, and the notification service—subscribe to these events to
maintain read models, execute sagas, and produce user-facing updates.

A thin layer of abstraction is provided to make sure every outgoing
message is:

* JSON‐serialisable and validated (via `pydantic`)
* Enriched with tracing / correlation identifiers
* Persisted with **at-least-once** semantics (configurable retries)
* Logged in a structured manner suitable for centralised logging
  solutions (e.g. ELK, CloudWatch)

The implementation relies on `aiokafka` for the actual transport,
`tenacity` for resiliency, and `uvloop` (optional) for event-loop
performance.  All external dependencies should be declared in
`pyproject.toml` / `requirements.txt`.

Usage
-----

    from crowdpay_connect.services.kyc_service.app.events.producer import (
        KYCEventProducer,
        KYCVerificationCompleted,
    )

    async with KYCEventProducer.from_env() as producer:
        event = KYCVerificationCompleted.build(
            user_id="usr_123",
            pod_id="pod_456",
            kyc_level="tier_2",
            approved_by="system"
        )
        await producer.publish(event)

"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

import aiokafka
from pydantic import BaseModel, Field, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

# -----------------------------------------------------------------------------
# Configuration & Constants
# -----------------------------------------------------------------------------

logger = logging.getLogger("crowdpay.kyc.event_producer")

DEFAULT_KAFKA_TOPIC = os.getenv("CROWDPAY_KYC_TOPIC", "kyc.events.v1")
DEFAULT_CLIENT_ID = f"kyc-service-{socket.gethostname()}"

_KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
_KAFKA_SASL_USERNAME = os.getenv("KAFKA_SASL_USERNAME")  # optional
_KAFKA_SASL_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD")  # optional


class ProducerError(RuntimeError):
    """Raised when an event could not be published after retries."""


# -----------------------------------------------------------------------------
# Event Models
# -----------------------------------------------------------------------------

class EventType(str, Enum):
    """Enum containing all supported event types."""
    VERIFICATION_REQUESTED = "kyc.verification.requested"
    VERIFICATION_COMPLETED = "kyc.verification.completed"
    VERIFICATION_FAILED = "kyc.verification.failed"


class BaseEvent(BaseModel):
    """
    Shared structure for all outbound KYC events.

    CrowdPay Connect follows the CloudEvents specification (v1.0) with a few
    custom extensions for compliance/audit requirements.
    """

    # CloudEvent required attributes
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="event_id")
    source: str = Field("kyc-service", description="Micro-service emitting the event")
    specversion: str = Field("1.0", alias="spec_version")
    type: EventType
    datacontenttype: str = Field("application/json")
    time: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ"))

    # Custom extensions --------------------------------------------------------
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    # -------------------------------------------------------------------------

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            Enum: lambda e: e.value,  # serialise Enum as plain value
        }

    # -------------------------------------------------------------------------
    # Helper API for building new events
    # -------------------------------------------------------------------------
    @classmethod
    def _create(
        cls,
        *,
        data: Dict[str, Any],
        event_type: EventType,
        correlation_id: Optional[str] = None,
    ) -> "BaseEvent":
        return cls(
            type=event_type,
            correlation_id=correlation_id,
            **data,
        )

    def json_bytes(self) -> bytes:
        """Return the validated JSON representation as bytes."""
        return self.json(by_alias=True).encode("utf-8")


class KYCVerificationRequested(BaseEvent):
    """Event emitted when a new KYC verification flow is initiated."""

    class Data(BaseModel):
        user_id: str
        pod_id: str
        kyc_level: str  # e.g. "tier_1", "tier_2"
        requested_at: float = Field(default_factory=time.time)

    data: Data

    @classmethod
    def build(
        cls,
        *,
        user_id: str,
        pod_id: str,
        kyc_level: str,
        correlation_id: Optional[str] = None,
    ) -> "KYCVerificationRequested":
        data = cls.Data(user_id=user_id, pod_id=pod_id, kyc_level=kyc_level)
        return cls._create(data={"data": data}, event_type=EventType.VERIFICATION_REQUESTED,
                           correlation_id=correlation_id)  # type: ignore[arg-type]


class KYCVerificationCompleted(BaseEvent):
    """Event emitted when a KYC verification succeeds."""

    class Data(BaseModel):
        user_id: str
        pod_id: str
        kyc_level: str
        approved_by: str
        completed_at: float = Field(default_factory=time.time)

    data: Data

    @classmethod
    def build(
        cls,
        *,
        user_id: str,
        pod_id: str,
        kyc_level: str,
        approved_by: str,
        correlation_id: Optional[str] = None,
    ) -> "KYCVerificationCompleted":
        data = cls.Data(
            user_id=user_id,
            pod_id=pod_id,
            kyc_level=kyc_level,
            approved_by=approved_by,
        )
        return cls._create(data={"data": data},
                           event_type=EventType.VERIFICATION_COMPLETED,
                           correlation_id=correlation_id)  # type: ignore[arg-type]


class KYCVerificationFailed(BaseEvent):
    """Event emitted when a KYC verification fails."""

    class Data(BaseModel):
        user_id: str
        pod_id: str
        kyc_level: str
        failure_code: str
        failure_reason: str
        failed_at: float = Field(default_factory=time.time)

    data: Data

    @classmethod
    def build(
        cls,
        *,
        user_id: str,
        pod_id: str,
        kyc_level: str,
        failure_code: str,
        failure_reason: str,
        correlation_id: Optional[str] = None,
    ) -> "KYCVerificationFailed":
        data = cls.Data(
            user_id=user_id,
            pod_id=pod_id,
            kyc_level=kyc_level,
            failure_code=failure_code,
            failure_reason=failure_reason,
        )
        return cls._create(data={"data": data},
                           event_type=EventType.VERIFICATION_FAILED,
                           correlation_id=correlation_id)  # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# Kafka Producer Abstraction
# -----------------------------------------------------------------------------

class KYCEventProducer:
    """
    Wrapper around `aiokafka.AIOKafkaProducer` that handles serialisation,
    structured logging, retries, and graceful shutdown.

    Use `async with` to ensure resources are cleaned up:

        async with KYCEventProducer.from_env() as producer:
            await producer.publish(some_event)
    """

    _producer: aiokafka.AIOKafkaProducer
    _topic: str

    def __init__(
        self,
        producer: aiokafka.AIOKafkaProducer,
        topic: str = DEFAULT_KAFKA_TOPIC,
    ) -> None:
        self._producer = producer
        self._topic = topic

    # ---------------------------------------------------------------------
    # Factory helpers
    # ---------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> "KYCEventProducer":
        """
        Build a producer using environment variables. Abstracting this logic
        keeps config centralised and consistent across micro-services.
        """

        security_protocol = "PLAINTEXT"
        sasl_mechanism = None
        sasl_plain_username = None
        sasl_plain_password = None

        if _KAFKA_SASL_USERNAME and _KAFKA_SASL_PASSWORD:
            security_protocol = "SASL_SSL"
            sasl_mechanism = "PLAIN"
            sasl_plain_username = _KAFKA_SASL_USERNAME
            sasl_plain_password = _KAFKA_SASL_PASSWORD

        producer = aiokafka.AIOKafkaProducer(
            bootstrap_servers=_KAFKA_BOOTSTRAP_SERVERS,
            client_id=DEFAULT_CLIENT_ID,
            security_protocol=security_protocol,
            sasl_mechanism=sasl_mechanism,
            sasl_plain_username=sasl_plain_username,
            sasl_plain_password=sasl_plain_password,
            value_serializer=lambda v: v,  # pass raw bytes
            key_serializer=str.encode,
            linger_ms=50,
            acks="all",
        )
        return cls(producer=producer)

    # ---------------------------------------------------------------------
    # Async context manager API
    # ---------------------------------------------------------------------
    async def __aenter__(self) -> "KYCEventProducer":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ---------------------------------------------------------------------
    # Public methods
    # ---------------------------------------------------------------------
    async def start(self) -> None:
        """Connect to Kafka cluster."""
        await self._producer.start()
        logger.info(
            "KYCEventProducer connected to Kafka %s [%s]",
            _KAFKA_BOOTSTRAP_SERVERS,
            self._topic,
        )

    async def close(self) -> None:
        """Flush outstanding messages and close the underlying producer."""
        await self._producer.stop()
        logger.info("KYCEventProducer shut down")

    # ---------------------------------------------------------------------
    # Core publishing logic
    # ---------------------------------------------------------------------
    async def publish(
        self,
        event: BaseEvent,
        *,
        partition_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Validate and publish the provided event. An exception is raised if the
        event cannot be delivered after retries.
        """
        try:
            # `BaseModel` validation runs on instantiation, but calling it
            # again guards against mutated instances.
            event = event.copy(update={})
        except ValidationError as exc:
            logger.error("Event validation failed: %s", exc, extra={"event": event.dict(by_alias=True)})
            raise

        # Kafka (key, value, headers) preparation
        key: bytes = (partition_key or event.correlation_id or event.id).encode()
        value: bytes = event.json_bytes()
        kafka_headers = _format_headers(event, headers)

        await self._send_with_retry(key=key, value=value, headers=kafka_headers)

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type(aiokafka.errors.KafkaError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=0.5, max=8.0),
        reraise=True,
    )
    async def _send_with_retry(self, *, key: bytes, value: bytes, headers: list[tuple[str, bytes]]) -> None:
        """
        Send a message to Kafka with retry logic.  Any `KafkaError` will be
        retried with exponential back-off up to five attempts.
        """
        try:
            await self._producer.send_and_wait(
                topic=self._topic,
                key=key,
                value=value,
                headers=headers,
            )
            logger.debug("Event published to %s | key=%s", self._topic, key.decode())
        except aiokafka.errors.KafkaError as exc:
            logger.warning("Kafka error while publishing: %s", exc)
            raise

# -----------------------------------------------------------------------------
# Private Utility Functions
# -----------------------------------------------------------------------------


def _format_headers(event: BaseEvent, extra: Optional[Dict[str, str]]) -> list[tuple[str, bytes]]:
    """
    Prepare Kafka headers. CrowdPay Connect propagates a subset of HTTP/trace
    headers through Kafka for observability.
    """
    headers: Dict[str, str] = {
        "event_id": event.id,
        "trace_id": event.trace_id,
        "correlation_id": event.correlation_id or "",
        "event_type": event.type.value,
        "spec_version": event.specversion,
    }
    if extra:
        headers.update(extra)

    # Kafka headers are bytes-only
    return [(k, v.encode()) for k, v in headers.items()]
```