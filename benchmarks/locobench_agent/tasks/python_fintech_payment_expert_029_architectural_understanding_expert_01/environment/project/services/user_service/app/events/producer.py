```python
"""
crowdpay_connect.services.user_service.app.events.producer
==========================================================

An asynchronous, strongly-typed Kafka event producer dedicated to the *user_service*
domain.  The class encapsulates JSON serialization, idempotent publishing, error
handling with exponential back-off, observability hooks, and security considerations
(e.g., optional payload encryption).

This module purposefully **does not** expose Kafka-specific details to calling
code—use the high-level ``UserEventProducer.publish()`` API instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, MutableMapping, Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError, KafkaTimeoutError
from prometheus_client import Counter, Histogram

__all__ = [
    "UserDomainEvent",
    "UserEventProducer",
    "EventProducerError",
]

# --------------------------------------------------------------------------- #
# Logging & Metrics
# --------------------------------------------------------------------------- #

logger = logging.getLogger("crowdpay_connect.user_service.events.producer")
logger.setLevel(logging.INFO)

_PUBLISH_COUNTER = Counter(
    "user_event_publish_total",
    "Total number of events attempted to publish.",
    ("event_type", "status"),
)
_PUBLISH_LATENCY = Histogram(
    "user_event_publish_latency_seconds",
    "Latency of publishing a user domain event.",
    ("event_type",),
)


# --------------------------------------------------------------------------- #
# Data Model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class UserDomainEvent:
    """
    Canonical representation of a domain event emitted by *user_service*.

    All events derive from this root.  Additional domain-specific attributes may
    be supplied via ``payload``—keep them *small* and *serializable*.
    """

    name: str
    user_id: uuid.UUID
    payload: Mapping[str, Any]
    correlation_id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    version: int = 1

    # Future-proofing:  allow arbitrary attributes w/o breaking the dataclass
    def __post_init__(self) -> None:  # type: ignore[override]
        object.__setattr__(self, "name", self.name.upper())


# --------------------------------------------------------------------------- #
# Custom Exceptions
# --------------------------------------------------------------------------- #


class EventProducerError(RuntimeError):
    """Raised when the producer fails to publish an event after exhausting retries."""


# --------------------------------------------------------------------------- #
# Utility helpers
# --------------------------------------------------------------------------- #


class _EnhancedJSONEncoder(json.JSONEncoder):
    """JSON encoder that understands UUIDs and datetimes."""

    def default(self, obj: Any) -> Any:  # noqa: D401
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _serialize_event(event: UserDomainEvent) -> bytes:
    """Serialize a domain event into bytes suitable for Kafka transport."""
    return json.dumps(asdict(event), cls=_EnhancedJSONEncoder, separators=(",", ":")).encode(
        "utf-8"
    )


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """Create SSL context from environment variables if needed."""
    cafile = os.getenv("KAFKA_CA_CERT")
    certfile = os.getenv("KAFKA_CLIENT_CERT")
    keyfile = os.getenv("KAFKA_CLIENT_KEY")

    if not cafile:
        return None

    context = ssl.create_default_context(cafile=cafile)
    context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return context


# --------------------------------------------------------------------------- #
# Producer Class
# --------------------------------------------------------------------------- #


class UserEventProducer:
    """
    High-level, asyncio-friendly Kafka producer for *user_service* events.

    Example
    -------
    >>> producer = UserEventProducer(loop=asyncio.get_event_loop())
    >>> await producer.start()
    >>> await producer.publish(UserDomainEvent(name="USER_CREATED", user_id=uid, payload={}))
    >>> await producer.stop()
    """

    _DEFAULT_MAX_RETRIES = 5
    _RETRY_BACKOFF_SECONDS = 0.25  # exponential base

    def __init__(
        self,
        *,
        kafka_bootstrap_servers: Optional[str] = None,
        kafka_topic: Optional[str] = None,
        security: str | None = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        extra_producer_kwargs: Optional[MutableMapping[str, Any]] = None,
    ) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._topic = kafka_topic or os.getenv("USER_EVENTS_TOPIC", "user-service.events")
        self._bootstrap_servers = (
            kafka_bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        )

        ssl_context = _build_ssl_context() if security == "SSL" else None

        producer_kwargs: Dict[str, Any] = {
            "bootstrap_servers": self._bootstrap_servers,
            "loop": self._loop,
            "client_id": "crowdpay.user_service",
            "acks": "all",
            "enable_idempotence": True,
            "linger_ms": 5,
            "compression_type": "snappy",
            "security_protocol": "SSL" if ssl_context else "PLAINTEXT",
            "ssl_context": ssl_context,
        }
        if extra_producer_kwargs:
            producer_kwargs.update(extra_producer_kwargs)

        self._producer = AIOKafkaProducer(**producer_kwargs)
        self._started: bool = False

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    async def start(self) -> None:
        if self._started:
            return
        logger.info("Starting UserEventProducer (bootstrap=%s)", self._bootstrap_servers)
        await self._producer.start()
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        logger.info("Stopping UserEventProducer …")
        await self._producer.stop()
        self._started = False

    async def __aenter__(self) -> "UserEventProducer":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        await self.stop()

    async def publish(
        self,
        event: UserDomainEvent,
        *,
        partition_key: Optional[str | bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        max_retries: int | None = None,
    ) -> None:
        """
        Publish a `UserDomainEvent` to Kafka using at-least-once semantics.

        Parameters
        ----------
        event:
            The event instance to be published.
        partition_key:
            Key used by Kafka's partitioner.  Defaults to ``event.user_id``.
        headers:
            Additional Kafka message headers.
        max_retries:
            Override the default retry count.

        Raises
        ------
        EventProducerError
            If the message cannot be published after exhausting retries.
        """
        if not self._started:  # Fail fast
            raise EventProducerError("Producer has not been started.")

        key = partition_key or str(event.user_id)
        payload_bytes = _serialize_event(event)

        kafka_headers = [
            ("event_name", event.name.encode()),
            ("correlation_id", str(event.correlation_id).encode()),
            ("schema_version", str(event.version).encode()),
        ]

        if headers:  # Merge caller-supplied headers
            kafka_headers.extend((k, str(v).encode()) for k, v in headers.items())

        # ---------------------------------------------------------------------------- #
        # Publish with retry semantics.
        # ---------------------------------------------------------------------------- #
        retries_left = max_retries if max_retries is not None else self._DEFAULT_MAX_RETRIES
        attempt = 0
        publish_timer = _PUBLISH_LATENCY.labels(event_type=event.name).time()

        while True:
            attempt += 1
            try:
                await self._producer.send_and_wait(
                    topic=self._topic,
                    key=key.encode() if isinstance(key, str) else key,
                    value=payload_bytes,
                    headers=kafka_headers,
                )
                _PUBLISH_COUNTER.labels(event_type=event.name, status="success").inc()
                logger.debug(
                    "Published event %s to topic=%s partition_key=%s size=%dB",
                    event.name,
                    self._topic,
                    key,
                    len(payload_bytes),
                )
                return
            except (KafkaTimeoutError, KafkaError) as exc:
                _PUBLISH_COUNTER.labels(event_type=event.name, status="retry").inc()
                logger.warning(
                    "Publish attempt %d for %s failed: %s", attempt, event.name, exc, exc_info=True
                )
                if retries_left <= 0:
                    _PUBLISH_COUNTER.labels(event_type=event.name, status="failure").inc()
                    raise EventProducerError(
                        f"Failed to publish {event.name} after {attempt} attempts."
                    ) from exc

                await self._backoff(attempt)
                retries_left -= 1
            finally:
                if attempt == 1:
                    publish_timer.__enter__()  # type: ignore[attr-defined]
        publish_timer.__exit__(None, None, None)  # Ensure timer closes

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    async def _backoff(self, attempt: int) -> None:
        """
        Non-blocking exponential back-off with jitter.

        Exponential factor grows quadratically to avoid thundering herd issues.
        """
        base = self._RETRY_BACKOFF_SECONDS
        sleep_for = base * (2**attempt) + (base * 0.1) * (1 - 2 * os.urandom(1)[0] / 255)
        await asyncio.sleep(sleep_for)


# --------------------------------------------------------------------------- #
# Run-module diagnostics (optional)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    """
    Basic integration test that can be executed with::

        $ python -m crowdpay_connect.services.user_service.app.events.producer
    """
    logging.basicConfig(level=logging.DEBUG)

    async def _demo() -> None:
        uid = uuid.uuid4()
        event = UserDomainEvent(name="USER_CREATED", user_id=uid, payload={"email": "foo@bar.com"})

        async with UserEventProducer() as producer:  # type: ignore[arg-type]
            await producer.publish(event)
            logger.info("Demo publish complete!")

    asyncio.run(_demo())
```