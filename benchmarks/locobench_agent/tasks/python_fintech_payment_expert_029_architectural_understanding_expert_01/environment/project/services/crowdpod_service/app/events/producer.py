```python
"""
CrowdPay Connect – CrowdPod Service
-----------------------------------

Producer module responsible for publishing domain and integration
events originating from the CrowdPod bounded-context to the central
event bus (Kafka in this implementation).

The producer:

* Adds envelope metadata (correlation, causation, timestamps, etc.).
* Serialises the event payload using canonical JSON.
* Publishes with exactly-once semantics (Kafka idempotence).
* Implements graceful start-up / shutdown hooks.
* Respects asyncio event-loop concurrency.
* Exposes a synchronous façade for usage from non-async code paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

try:
    # aiokafka is the de-facto async Kafka client for Python.
    from aiokafka import AIOKafkaProducer
    from aiokafka.errors import KafkaError
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "aiokafka must be installed to use CrowdPodEventProducer"
    ) from exc


__all__ = ["EventMessage", "CrowdPodEventProducer"]


LOGGER = logging.getLogger("crowdpay.events.producer")
LOGGER.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
#                          Domain Event Envelope                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class EventMessage:
    """
    Canonical event message envelope used across the CrowdPay platform.
    All business events MUST be wrapped in this envelope to guarantee
    consistent routing, tracing, and auditing.
    """

    # --- required --------------------------------------------------------- #
    event_name: str
    aggregate_id: UUID
    data: Dict[str, Any]

    # --- optional / system-managed metadata ------------------------------- #
    version: int = 1
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    correlation_id: UUID = field(default_factory=uuid4)
    causation_id: Optional[UUID] = None
    schema: str = "crowdpay.event.1"

    # --- helper ----------------------------------------------------------- #
    def to_json(self) -> bytes:
        """
        Serialise event to UTF-8 encoded JSON bytes suitable for transport.
        We purposefully exclude *None* values to reduce payload size.
        """
        def _filter_none(d: Dict[str, Any]) -> Dict[str, Any]:
            return {k: v for k, v in d.items() if v is not None}

        raw_dict: Dict[str, Any] = asdict(self)
        # convert non-serialisable types
        raw_dict["aggregate_id"] = str(raw_dict["aggregate_id"])
        raw_dict["correlation_id"] = str(raw_dict["correlation_id"])
        if raw_dict.get("causation_id"):
            raw_dict["causation_id"] = str(raw_dict["causation_id"])
        raw_dict["timestamp"] = raw_dict["timestamp"].isoformat()

        payload_dict = _filter_none(raw_dict)
        return json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------- #
#                             Producer Class                                  #
# --------------------------------------------------------------------------- #
class CrowdPodEventProducer:
    """
    Async Kafka producer wrapper that publishes `EventMessage` objects to the
    correct topic (`crowdpod.<event_name>.v<version>`).

    Usage:

    >>> async with CrowdPodEventProducer() as producer:
    ...     await producer.send_event(EventMessage(...))

    A blocking `produce_event_sync` is also available for scenarios where an
    event needs to be fired from sync code (e.g., Django signal handlers).
    """

    DEFAULT_TOPIC_PREFIX: str = "crowdpod"

    def __init__(
        self,
        *,
        bootstrap_servers: str | None = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        client_id: str | None = None,
        topic_prefix: str | None = None,
        max_request_size: int = 1024 * 1024,
        linger_ms: int = 5,
    ) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._bootstrap_servers = (
            bootstrap_servers
            or os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
        )
        self._client_id = (
            client_id
            or os.getenv("SERVICE_NAME", "crowdpod_service_producer")
            + f".{os.getpid()}"
        )
        self._topic_prefix = topic_prefix or self.DEFAULT_TOPIC_PREFIX
        self._producer: Optional[AIOKafkaProducer] = None
        self._closed: bool = True
        self._linger_ms = linger_ms
        self._max_request_size = max_request_size

    # ------------------------------------------------------------------ #
    #                          Life-cycle                                #
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """
        Lazily create underlying AIOKafkaProducer and connect to the
        Kafka cluster.
        """
        if self._producer:  # already started
            return

        LOGGER.info(
            "Starting CrowdPodEventProducer (bootstrap=%s)",
            self._bootstrap_servers,
        )
        self._producer = AIOKafkaProducer(
            loop=self._loop,
            bootstrap_servers=self._bootstrap_servers,
            client_id=self._client_id,
            acks="all",  # durability
            enable_idempotence=True,  # exactly-once
            linger_ms=self._linger_ms,
            max_request_size=self._max_request_size,
            value_serializer=lambda v: v,  # pre-encoded bytes passed through
            key_serializer=lambda v: v.encode("utf-8") if v else None,
        )
        await self._producer.start()
        self._closed = False

    async def stop(self) -> None:
        """
        Flush outstanding messages and close connection.
        """
        if not self._producer or self._closed:
            return
        LOGGER.info("Stopping CrowdPodEventProducer.")
        try:
            await self._producer.stop()
        finally:
            self._closed = True
            self._producer = None

    async def __aenter__(self) -> "CrowdPodEventProducer":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    # ------------------------------------------------------------------ #
    #                         Public API                                 #
    # ------------------------------------------------------------------ #
    async def send_event(
        self,
        message: EventMessage,
        *,
        key: str | None = None,
        partition: int | None = None,
        timeout: float = 10.0,
        retries: int = 3,
    ) -> None:
        """
        Publish an EventMessage to Kafka.

        Parameters
        ----------
        message:
            EventMessage instance to publish.
        key:
            Optional partition key. If omitted, Kafka will hash by key=None.
        partition:
            Explicit partition override.
        timeout:
            Max seconds to await confirmation.
        retries:
            Number of retry attempts when encountering transient errors.

        Raises
        ------
        KafkaError
            If Kafka sends back an error or delivery fails after retries.
        """
        await self._ensure_started()

        topic = self._build_topic(message.event_name, message.version)
        payload = message.to_json()

        attempt = 0
        backoff = 0.25  # seconds
        # retry loop
        while True:
            try:
                fut = self._producer.send(
                    topic=topic,
                    value=payload,
                    key=key,
                    partition=partition,
                )
                # Wait for acknowledgment
                await asyncio.wait_for(fut, timeout=timeout)
                LOGGER.debug(
                    "Event published: topic=%s offset=%s",
                    topic,
                    fut.result().offset,
                )
                return
            except (asyncio.TimeoutError, KafkaError) as exc:
                attempt += 1
                LOGGER.warning(
                    "Failed to publish event (attempt %s/%s): %s",
                    attempt,
                    retries,
                    exc,
                    exc_info=LOGGER.isEnabledFor(logging.DEBUG),
                )
                if attempt > retries:
                    LOGGER.error(
                        "Giving up after %s attempts (topic=%s, key=%s).",
                        attempt,
                        topic,
                        key,
                    )
                    raise
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)  # exponential backoff

    # ---------------------------- Helpers -------------------------------- #
    def _build_topic(self, event_name: str, version: int) -> str:
        """
        Construct topic name based on convention:

            <prefix>.<event_name>.v<version>

        Example:
            "crowdpod.funds_deposited.v1"
        """
        return f"{self._topic_prefix}.{event_name}.v{version}"

    async def _ensure_started(self) -> None:
        """
        Assert that the producer is started. Convenience guard for public
        methods that may be called before `start()`.
        """
        if self._producer is None or self._closed:
            await self.start()

    # ------------------------------------------------------------------ #
    #              Synchronous convenience façade                        #
    # ------------------------------------------------------------------ #
    def produce_event_sync(
        self,
        message: EventMessage,
        *,
        key: str | None = None,
        partition: int | None = None,
        timeout: float = 10.0,
        retries: int = 3,
    ) -> None:
        """
        Blocking wrapper around `send_event` for call-sites that are not
        running inside an asyncio loop (e.g., management commands, tests).

        CAUTION: If called from a context where an event-loop is already
        running (e.g., FastAPI request handler), this method will deadlock.
        Prefer the async `send_event` method in such situations.
        """
        # If an event loop is already running we cannot run nested loops.
        if asyncio.get_event_loop().is_running():
            raise RuntimeError(
                "produce_event_sync cannot be called from within an "
                "existing asyncio event loop."
            )

        async def _wrapper() -> None:
            async with self:
                await self.send_event(
                    message,
                    key=key,
                    partition=partition,
                    timeout=timeout,
                    retries=retries,
                )

        asyncio.run(_wrapper())


# --------------------------------------------------------------------------- #
#                     Simple smoke test (invoked directly)                    #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover
    # Allow quick manual testing by running:
    #
    #   $ python -m crowdpay_connect.services.crowdpod_service.app.events.producer
    #
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.DEBUG,
        format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    )

    async def _demo() -> None:
        producer = CrowdPodEventProducer()
        test_event = EventMessage(
            event_name="crowdpod_created",
            aggregate_id=uuid4(),
            data={
                "creator_id": str(uuid4()),
                "currency": "USD",
                "initial_balance": "0.00",
            },
        )
        async with producer:
            await producer.send_event(test_event, key=str(test_event.aggregate_id))
        LOGGER.info("Demo event produced successfully.")

    asyncio.run(_demo())
```