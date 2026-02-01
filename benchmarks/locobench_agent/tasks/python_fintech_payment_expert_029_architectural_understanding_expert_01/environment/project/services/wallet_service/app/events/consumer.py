```python
"""
crowdpay_connect.services.wallet_service.app.events.consumer
===========================================================

High-level, production-grade event consumer for CrowdPay Connect's Wallet
Service.  The consumer is responsible for:

1. Subscribing to the Kafka **wallet.events** topic (and other clusterwide
   topics when required, e.g. **system.events** for KYC / Risk events).
2. Deserialising the (CloudEvents-compatible) payloads into strongly-typed
   `Event` objects.
3. Dispatching the event to the correct *domain* handler or *projection*
   updater.
4. Persisting an **outbox** record for at-least-once delivery guarantees.
5. Providing robust observability, graceful shutdown, and error isolation.

This module purposefully avoids tight coupling with any single broker
implementation.  The default runtime uses **aiokafka**, but swapping to
RabbitMQ (via **aio-pika**) or AWS MSK/IAM is trivial — simply implement
`AbstractBrokerConsumer` and plug it into `EventConsumer`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Final, List, Mapping, Type

import aiokafka
from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# --------------------------------------------------------------------------- #
# Configuration & Constants
# --------------------------------------------------------------------------- #

_LOGGER: Final = logging.getLogger("crowdpay.wallet.events.consumer")

KAFKA_BOOTSTRAP: Final[str] = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
WALLET_EVENTS_TOPIC: Final[str] = os.getenv("WALLET_EVENTS_TOPIC", "wallet.events")
SYSTEM_EVENTS_TOPIC: Final[str] = os.getenv("SYSTEM_EVENTS_TOPIC", "system.events")
CONSUMER_GROUP: Final[str] = os.getenv("WALLET_CONSUMER_GROUP", "wallet_service")

# --------------------------------------------------------------------------- #
# Event Model
# --------------------------------------------------------------------------- #


class Event(BaseModel):
    """
    Base CloudEvent-ish model.

    All events MUST include at least the following metadata contract:
    """

    id: str
    source: str
    type: str
    spec_version: str = "1.0"
    data: Dict[str, Any]
    subject: str | None = None
    time: float | None = None  # Epoch (ms)


# Wallet domain-specific events ------------------------------------------------


class WalletCreated(Event):
    type: str = "wallet.created"
    data: Dict[str, Any]  # { "wallet_id": str, "owner_id": str, "currency": str, ... }


class FundsDeposited(Event):
    type: str = "wallet.funds_deposited"
    data: Dict[str, Any]  # { "wallet_id": str, "amount": str, "currency": str, ... }


class FundsWithdrawn(Event):
    type: str = "wallet.funds_withdrawn"
    data: Dict[str, Any]  # { "wallet_id": str, "amount": str, "currency": str, ... }


class TransferInitiated(Event):
    type: str = "wallet.transfer_initiated"
    data: Dict[str, Any]


class TransferCompleted(Event):
    type: str = "wallet.transfer_completed"
    data: Dict[str, Any]


class TransferFailed(Event):
    type: str = "wallet.transfer_failed"
    data: Dict[str, Any]


# Register event type mapping for dynamic deserialisation
_EVENT_REGISTRY: Dict[str, Type[Event]] = {
    WalletCreated.type: WalletCreated,
    FundsDeposited.type: FundsDeposited,
    FundsWithdrawn.type: FundsWithdrawn,
    TransferInitiated.type: TransferInitiated,
    TransferCompleted.type: TransferCompleted,
    TransferFailed.type: TransferFailed,
}


# --------------------------------------------------------------------------- #
# Domain Handlers (placeholders — would live elsewhere in real code)
# --------------------------------------------------------------------------- #

async def handle_wallet_created(event: WalletCreated) -> None:
    _LOGGER.info("🪙 Wallet created ‑ id=%s owner=%s", event.data["wallet_id"], event.data["owner_id"])
    # TODO: Persist wallet aggregate / outbox integration event
    # await wallet_repository.create_wallet(...)
    # await outbox.publish_async("wallet.read_model.updated", ...)


async def handle_funds_deposited(event: FundsDeposited) -> None:
    _LOGGER.info("💰 Funds deposited ‑ wallet=%s amount=%s%s",
                 event.data["wallet_id"], event.data["amount"], event.data["currency"])
    # TODO: Balance updates / risk checks / ledger postings


async def handle_funds_withdrawn(event: FundsWithdrawn) -> None:
    _LOGGER.info("🏧 Funds withdrawn ‑ wallet=%s amount=%s%s",
                 event.data["wallet_id"], event.data["amount"], event.data["currency"])
    # TODO: Balance validations / AML scanning / ledger postings


async def handle_transfer_initiated(event: TransferInitiated) -> None:
    _LOGGER.info("🔄 Transfer initiated ‑ ref=%s", event.data.get("transfer_ref"))
    # TODO: Saga orchestrator handshake


async def handle_transfer_completed(event: TransferCompleted) -> None:
    _LOGGER.info("✅ Transfer completed ‑ ref=%s", event.data.get("transfer_ref"))
    # TODO: Finalise ledger / notify parties


async def handle_transfer_failed(event: TransferFailed) -> None:
    _LOGGER.warning("❌ Transfer failed ‑ ref=%s reason=%s",
                    event.data.get("transfer_ref"), event.data.get("reason"))


# Map event *classes* to concrete async handlers
_EVENT_HANDLER_MAP: Dict[Type[Event], Callable[[Event], Awaitable[None]]] = {
    WalletCreated: handle_wallet_created,
    FundsDeposited: handle_funds_deposited,
    FundsWithdrawn: handle_funds_withdrawn,
    TransferInitiated: handle_transfer_initiated,
    TransferCompleted: handle_transfer_completed,
    TransferFailed: handle_transfer_failed,
}


# --------------------------------------------------------------------------- #
# Broker Abstraction
# --------------------------------------------------------------------------- #

class AbstractBrokerConsumer(ABC):
    """Strategy interface to allow pluggable broker implementations."""

    @abstractmethod
    async def __aenter__(self) -> "AbstractBrokerConsumer":  # noqa: D401
        ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        ...

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def __anext__(self) -> tuple[str, bytes]:
        """Yields (topic, raw_bytes) each iteration."""
        ...


class KafkaConsumerAdapter(AbstractBrokerConsumer):
    """
    Concrete implementation for Kafka (powered by **aiokafka**).

    Each call to `__anext__` returns the next *raw* (topic, value) message; all
    offset management is handled internally (manual commit on success).
    """

    def __init__(
        self,
        topics: List[str],
        bootstrap_servers: str,
        group_id: str,
        *,
        enable_auto_commit: bool = False,
        auto_offset_reset: str = "earliest",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._consumer: AIOKafkaConsumer = AIOKafkaConsumer(
            *topics,
            loop=loop,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=enable_auto_commit,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=lambda v: v,  # raw bytes -> handled later
        )
        self._records: List[ConsumerRecord] = []

    async def __aenter__(self) -> "KafkaConsumerAdapter":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401
        await self.stop()

    async def start(self) -> None:
        _LOGGER.info("Starting Kafka consumer against %s", KAFKA_BOOTSTRAP)
        await self._consumer.start()

    async def stop(self) -> None:
        _LOGGER.info("Closing Kafka consumer…")
        await self._consumer.stop()

    async def __anext__(self) -> tuple[str, bytes]:
        """
        Polls until a message is available.  We purposefully block with an
        infinite timeout to maximise throughput (co-operative cancellation
        handled by enclosing task).
        """
        try:
            record: ConsumerRecord = await self._consumer.getone()
            self._records.append(record)
            return record.topic, record.value
        except asyncio.CancelledError:
            raise StopAsyncIteration
        except Exception:
            _LOGGER.exception("Fatal error during Kafka polling loop.")
            await asyncio.sleep(1)
            raise

    async def commit(self) -> None:
        """Commit offsets for all buffered records (if any)."""
        if not self._records:
            return
        await self._consumer.commit()
        self._records.clear()


# --------------------------------------------------------------------------- #
# EventConsumer Orchestrator
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class ProcessingContext:
    """Runtime context used during event processing."""
    topic: str
    raw_payload: bytes
    attempts: int = 0
    received_epoch: float = time.time()


class EventConsumer:
    """
    Wallet Service top-level event consumer.

    Usage (from `uvicorn` or dedicated entrypoint):

        asyncio.run(EventConsumer().run_forever())

    The **run_forever** coroutine registers a clean shutdown handler (SIGINT /
    SIGTERM) and blocks the main thread until cancellation.
    """

    def __init__(
        self,
        broker_consumer: AbstractBrokerConsumer | None = None,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._broker_consumer = broker_consumer or KafkaConsumerAdapter(
            topics=[WALLET_EVENTS_TOPIC, SYSTEM_EVENTS_TOPIC],
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=CONSUMER_GROUP,
            loop=self._loop,
        )
        self._shutdown_event: asyncio.Event = asyncio.Event()

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    async def run_forever(self) -> None:
        self._register_signal_handlers()
        async with self._broker_consumer:
            _LOGGER.info("WalletService EventConsumer started — awaiting messages…")
            while not self._shutdown_event.is_set():
                try:
                    topic, raw = await self._broker_consumer.__anext__()
                    ctx = ProcessingContext(topic=topic, raw_payload=raw)
                    await self._process_with_retry(ctx)
                    await self._broker_consumer.commit()
                except StopAsyncIteration:
                    break
                except asyncio.CancelledError:
                    break
                except Exception:
                    _LOGGER.exception("Unhandled exception escaped main loop — continuing.")
                    # Sleep briefly to avoid tight loop cascade
                    await asyncio.sleep(1)
        _LOGGER.info("EventConsumer shutdown complete.")

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _process_with_retry(self, ctx: ProcessingContext) -> None:
        """Process an event with exponential back-off retries."""
        ctx.attempts += 1
        try:
            event = self._deserialize(ctx.raw_payload)
            await self._dispatch(event)
        except ValidationError as ve:
            _LOGGER.error("Deserialisation error — dropping event (payload=%s) err=%s",
                          ctx.raw_payload, ve)
        except Exception:
            _LOGGER.exception("Processing attempt=%d failed — will retry.", ctx.attempts)
            raise

    def _deserialize(self, raw: bytes) -> Event:
        try:
            payload: Mapping[str, Any] = json.loads(raw.decode("utf8"))
        except json.JSONDecodeError as err:
            _LOGGER.error("JSON decode error: %s", err)
            raise

        evt_type: str | None = payload.get("type")
        model_cls = _EVENT_REGISTRY.get(evt_type, Event)  # Fallback to generic

        return model_cls.parse_obj(payload)

    async def _dispatch(self, event: Event) -> None:
        handler = _EVENT_HANDLER_MAP.get(type(event))
        if not handler:
            _LOGGER.debug("No handler registered for event type=%s — ignoring.", event.type)
            return
        _LOGGER.debug("Dispatching event id=%s type=%s", event.id, event.type)
        await handler(event)

    # --------------------------------------------------------------------- #
    # Graceful shutdown helpers
    # --------------------------------------------------------------------- #

    def _register_signal_handlers(self) -> None:
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                self._loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._shutdown(s)))
        except NotImplementedError:
            # Signals are not available on Windows (depending on interpreter)
            _LOGGER.warning("Signal handlers not available — relying on other shutdown hooks.")

    async def _shutdown(self, sig: signal.Signals) -> None:  # noqa: D401
        _LOGGER.info("Received signal %s — initiating shutdown.", sig.name)
        self._shutdown_event.set()
        # Give consumer some time to flush
        await asyncio.sleep(0.5)
        await self._broker_consumer.stop()


# --------------------------------------------------------------------------- #
# Entrypoint (python -m crowdpay_connect.services.wallet_service.app.events.consumer)
# --------------------------------------------------------------------------- #

def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        stream=sys.stdout,
    )


def main() -> None:  # pragma: no cover
    _configure_logging()
    _LOGGER.info("Bootstrapping WalletService EventConsumer…")
    consumer = EventConsumer()
    try:
        asyncio.run(consumer.run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
```