```python
"""
ledgerquest.engine.core.event_bus
================================

A hybrid in-memory / AWS EventBridge event-bus used across LedgerQuest Engine.
The bus supports three primary use-cases:

1. Local, synchronous dispatch inside the same Lambda invocation / container.
2. Fire-and-forget publication to EventBridge so that *other* serverless
   components (Step Functions, Lambdas, EventBridge Pipes, etc.) can react.
3. A composite mode that does **both** 1 & 2 in a single call, letting a game
   loop work locally while also emitting state transitions for audit, metering
   and cross-service orchestration.

The implementation purposefully avoids any hard dependency on `boto3` to keep
unit-tests fast and platform-agnostic.  When `boto3` is unavailable the remote
publisher is disabled automatically.
"""

from __future__ import annotations

import abc
import datetime as _dt
import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Generic, Iterable, List, MutableMapping, Optional, Type, TypeVar

# ---------------------------------------------------------------------------#
# Logging configuration                                                       #
# ---------------------------------------------------------------------------#
_logger = logging.getLogger("ledgerquest.engine.event_bus")
if not _logger.handlers:
    # Prevent library code from configuring logging twice in Lambda cold starts
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s", "%Y-%m-%d %H:%M:%S"
        )
    )
    _logger.addHandler(_handler)
_logger.setLevel(os.getenv("LEDGERQUEST_EVENT_BUS_LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------#
# Optional AWS SDK import                                                     #
# ---------------------------------------------------------------------------#
try:
    import boto3
    from botocore.exceptions import ClientError
except ModuleNotFoundError:  # pragma: no cover — boto3 absent in local env
    boto3 = None  # type: ignore
    ClientError = Exception  # type: ignore
    _logger.debug("boto3 not available – remote EventBridge publisher disabled.")

# ---------------------------------------------------------------------------#
# Typing helpers                                                              #
# ---------------------------------------------------------------------------#
T_EventPayload = TypeVar("T_EventPayload", bound=MutableMapping[str, Any])
T_Callback = Callable[["EventEnvelope[T_EventPayload]"], None]

# ---------------------------------------------------------------------------#
# Event domain models                                                         #
# ---------------------------------------------------------------------------#


@dataclass(frozen=True, slots=True)
class EventEnvelope(Generic[T_EventPayload]):
    """
    A lightweight, immutable envelope wrapping raw event payloads with metadata.

    LedgerQuest treats every message as fully self-describing so that auditors
    (and other consumers) can inspect archived events out of band.
    """

    id: str
    type: str
    tenant_id: str
    timestamp: str  # ISO-8601, always UTC
    correlation_id: str
    payload: T_EventPayload = field(repr=False)

    # ----------------------  convenience factory  --------------------------#
    @classmethod
    def create(
        cls,
        *,
        type_: str,
        tenant_id: str,
        payload: T_EventPayload,
        correlation_id: Optional[str] = None,
    ) -> "EventEnvelope[T_EventPayload]":
        now = _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="milliseconds")
        return cls(
            id=str(uuid.uuid4()),
            type=type_,
            tenant_id=tenant_id,
            timestamp=now,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload=payload,
        )

    # ----------------------  (de)serialisation   ---------------------------#
    def to_json(self) -> str:
        """
        Convert the envelope to a canonical JSON string sorted by keys to allow
        for deterministic sig-verification & hashing.
        """
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "EventEnvelope[Any]":
        data = json.loads(raw)
        if not {"id", "type", "tenant_id", "timestamp", "correlation_id", "payload"}.issubset(
            data.keys()
        ):
            raise ValueError("Invalid EventEnvelope JSON")
        return cls(**data)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------#
# EventBus abstractions                                                       #
# ---------------------------------------------------------------------------#


class AbstractEventBus(abc.ABC):
    """
    Strategy interface for event busses.  The engine primarily uses the global
    :pydata:`event_bus` singleton configured at import-time, but nothing stops
    power-users from wiring their own implementation.
    """

    @abc.abstractmethod
    def subscribe(self, event_type: str, handler: T_Callback) -> None:
        """Register a new synchronous handler for an event type."""

    @abc.abstractmethod
    def publish(self, envelope: EventEnvelope[Any]) -> None:
        """
        Send the event to *local* subscribers synchronously.
        Handlers are invoked in the publishing thread.
        """

    @abc.abstractmethod
    def publish_async(self, envelope: EventEnvelope[Any]) -> None:
        """
        Publish the event asynchronously (fire-and-forget).  The default
        implementation may be a no-op if the environment lacks a remote bus.
        """


# ---------------------------------------------------------------------------#
# In-memory event bus implementation                                          #
# ---------------------------------------------------------------------------#


class LocalEventBus(AbstractEventBus):
    """
    A threadsafe, in-memory pub/sub bus.  Designed for Lambda runtimes and
    unit-tests where latency is sub-millisecond and the call graph is small.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: Dict[str, List[T_Callback]] = {}

    # -------------------------------------------------------------------#
    # Public API                                                          #
    # -------------------------------------------------------------------#
    def subscribe(self, event_type: str, handler: T_Callback) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)
            _logger.debug("Handler %s subscribed to '%s'", handler, event_type)

    def publish(self, envelope: EventEnvelope[Any]) -> None:
        _logger.debug("Publishing %s locally", envelope.type)
        handlers = self._handlers.get(envelope.type, [])

        for hdl in handlers:
            try:
                hdl(envelope)
            except Exception:  # pragma: no cover
                _logger.exception("Unhandled exception in event handler %s", hdl)

    def publish_async(self, envelope: EventEnvelope[Any]) -> None:
        # Local bus has nothing to do async beyond delegating to publish
        self.publish(envelope)


# ---------------------------------------------------------------------------#
# AWS EventBridge implementation                                              #
# ---------------------------------------------------------------------------#


class EventBridgeBus(AbstractEventBus):
    """
    A lightweight wrapper around AWS EventBridge `PutEvents`.  Automatically
    falls back to a NO-OP if boto3 is absent or credentials are mis-configured.
    """

    _ENV_BUS_NAME = os.getenv("LEDGERQUEST_EVENT_BUS_NAME", "ledgerquest-bus")
    _ENV_REGION = os.getenv("AWS_REGION", "us-east-1")

    def __init__(self) -> None:
        self._client = None
        if boto3:
            try:
                self._client = boto3.client("events", region_name=self._ENV_REGION)
                _logger.debug("EventBridge client configured for %s", self._ENV_REGION)
            except Exception as ex:  # pragma: no cover
                _logger.warning("Failed to create EventBridge client: %s", ex, exc_info=True)

        self._local_delegate = LocalEventBus()  # Re-use for sync publishing

    # -------------------------------------------------------------------#
    # AbstractEventBus implementation                                    #
    # -------------------------------------------------------------------#
    def subscribe(self, event_type: str, handler: T_Callback) -> None:
        self._local_delegate.subscribe(event_type, handler)

    def publish(self, envelope: EventEnvelope[Any]) -> None:
        self._local_delegate.publish(envelope)

    def publish_async(self, envelope: EventEnvelope[Any]) -> None:
        if not self._client:
            _logger.debug("EventBridge client unavailable – async publication skipped.")
            return

        try:
            response = self._client.put_events(
                Entries=[
                    {
                        "EventBusName": self._ENV_BUS_NAME,
                        "Time": _dt.datetime.utcnow(),
                        "Source": f"ledgerquest.{envelope.tenant_id}",
                        "DetailType": envelope.type,
                        "Detail": envelope.to_json(),
                    }
                ]
            )
            if (failed := response.get("FailedEntryCount", 0)) > 0:  # pragma: no cover
                _logger.error("EventBridge dropped %s messages: %s", failed, response)
        except ClientError:  # pragma: no cover
            _logger.exception("Error publishing event to EventBridge")
        except Exception:  # pragma: no cover
            _logger.exception("Unexpected error publishing event to EventBridge")


# ---------------------------------------------------------------------------#
# Composite bus – combines local and remote                                  #
# ---------------------------------------------------------------------------#


class HybridEventBus(AbstractEventBus):
    """
    Publishes synchronously to the in-process bus **and** asynchronously to
    EventBridge in a single call.  The pattern keeps micro-latency for game
    loops while guaranteeing that a durable copy is sent for cross-service
    orchestration and analytics.
    """

    def __init__(
        self,
        local_bus: Optional[LocalEventBus] = None,
        remote_bus: Optional[EventBridgeBus] = None,
    ) -> None:
        self._local = local_bus or LocalEventBus()
        self._remote = remote_bus or EventBridgeBus()

    # -------------------------------------------------------------------#
    # AbstractEventBus implementation                                    #
    # -------------------------------------------------------------------#
    def subscribe(self, event_type: str, handler: T_Callback) -> None:
        self._local.subscribe(event_type, handler)

    def publish(self, envelope: EventEnvelope[Any]) -> None:
        self._local.publish(envelope)

    def publish_async(self, envelope: EventEnvelope[Any]) -> None:
        # Delegate first to local so the caller can trust the side-effects
        self._local.publish(envelope)
        # Fire-and-forget remote copy
        self._remote.publish_async(envelope)


# ---------------------------------------------------------------------------#
# Global bus singleton                                                        #
# ---------------------------------------------------------------------------#

# Choose implementation based on env variable
_mode = os.getenv("LEDGERQUEST_EVENT_BUS_MODE", "").lower()  # 'local', 'eventbridge', 'hybrid'
if _mode == "local":
    _GLOBAL_BUS: AbstractEventBus = LocalEventBus()
elif _mode == "eventbridge":
    _GLOBAL_BUS = EventBridgeBus()
else:
    # default: hybrid for production or fallback to local if boto3 missing
    _GLOBAL_BUS = HybridEventBus()

# Public facade
def subscribe(event_type: str, handler: T_Callback) -> None:  # noqa: D401
    """
    Subscribe a handler to a given event type using the global bus.

    Example
    -------
        >>> from ledgerquest.engine.core.event_bus import subscribe
        >>> subscribe("PLAYER_JOINED", handle_new_player)
    """
    _GLOBAL_BUS.subscribe(event_type, handler)


def publish(
    type_: str,
    tenant_id: str,
    payload: Dict[str, Any],
    correlation_id: Optional[str] = None,
    *,
    async_: bool = False,  # `async` is a reserved keyword
) -> None:
    """
    Convenience API mirroring AWS SDK behaviour while hiding envelope details.

    Parameters
    ----------
    type_:
        The logical event name, e.g. ``"LEVEL_COMPLETED"``.
    tenant_id:
        The SaaS tenant to which the event belongs.
    payload:
        Arbitrary JSON-serialisable dict with domain-specific fields.
    correlation_id:
        Optional trace identifier used by distributed-tracing tools.
    async_:
        If ``True`` the event is sent using :pymeth:`publish_async` otherwise
        :pymeth:`publish` is used.
    """
    envelope = EventEnvelope.create(
        type_=type_, tenant_id=tenant_id, payload=payload, correlation_id=correlation_id
    )

    if async_:
        _GLOBAL_BUS.publish_async(envelope)
    else:
        _GLOBAL_BUS.publish(envelope)


# Expose raw envelope publishing for advanced use-cases
def publish_envelope(envelope: EventEnvelope[Any], *, async_: bool = False) -> None:
    if async_:
        _GLOBAL_BUS.publish_async(envelope)
    else:
        _GLOBAL_BUS.publish(envelope)


__all__ = [
    "EventEnvelope",
    "subscribe",
    "publish",
    "publish_envelope",
    "AbstractEventBus",
    "LocalEventBus",
    "EventBridgeBus",
    "HybridEventBus",
]
```