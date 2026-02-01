```python
"""
ledgerquest.services.networking.message_handler
================================================

Centralised message dispatching entry-point for the LedgerQuest Engine
networking stack.  Deployed as an AWS Lambda function behind an
API-Gateway WebSocket API, this module receives *player messages*,
validates them, authorises the caller, and fans the request out to the
appropriate domain-specific command handler.

Design goals
------------
1.   Keep the Lambda **stateless** – game state is externalised to
     DynamoDB and S3.
2.   Provide **pluggable command handlers** that encapsulate game logic
     (Command Pattern).
3.   Support **multi-tenant isolation** – every message carries a
     `tenant_id` and is validated against an allow-list.
4.   Emit **structured logs and metrics** for audit and observability.
5.   **Fail closed**: invalid or unknown messages are rejected with a
     generic error to the client while detailed diagnostics are logged
     internally.

The module has intentionally *zero* knowledge about concrete game
domains (physics, AI, etc.).  It merely acts as a façade between the
outside world and the internal event bus/Step-Functions workflows.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Final, MutableMapping, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# ---------------------------------------------------------------------------#
# Configuration / Constants
# ---------------------------------------------------------------------------#

# Environment variables supplied via Serverless framework / CDK
EVENT_BUS_NAME: Final[str] = os.getenv("LEDGERQUEST_EVENT_BUS", "ledgerquest-event-bus")
ALLOWED_TENANTS: Final[set[str]] = {
    # Populated via parameter store or replaced at deploy time
    t.strip() for t in os.getenv("LEDGERQUEST_ALLOWED_TENANTS", "").split(",") if t
}

LOG_LEVEL: Final[str] = os.getenv("LOG_LEVEL", "INFO").upper()

# Configure root logger once – Lambda may re-use the execution context
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s[%(lineno)d] – %(message)s",
)
LOGGER = logging.getLogger("ledgerquest.message_handler")


# ---------------------------------------------------------------------------#
# Exceptions
# ---------------------------------------------------------------------------#


class MessageError(Exception):
    """Base-class for all message-handling related errors."""


class MessageValidationError(MessageError):
    """Raised when an inbound message does not satisfy the expected schema."""


class HandlerNotFoundError(MessageError):
    """Raised when no handler is registered for a message type."""


class UnauthorizedTenantError(MessageError):
    """Raised when the caller is not allowed to act on behalf of a tenant."""


# ---------------------------------------------------------------------------#
# Data structures
# ---------------------------------------------------------------------------#


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """
    Canonical representation of a player/client message.

    Attributes
    ----------
    correlation_id
        Unique identifier used for tracing a message across distributed
        components.  Will be auto-generated if not provided by the client.
    tenant_id
        Logical tenant the player belongs to.  Used for data isolation.
    player_id
        Identifier of the client/player making the request.
    msg_type
        Domain command, e.g. ``PING``, ``MOVE_ENTITY``.
    payload
        Arbitrary JSON-serialisable object understood by the domain
        handler.
    timestamp
        Epoch milliseconds when the message was created on the client.
    received_at
        Epoch milliseconds when the API Gateway delivery event hit this
        Lambda.  Populated server-side for observability.
    """

    tenant_id: str
    player_id: str
    msg_type: str
    payload: Dict[str, Any]

    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    received_at: int = field(
        default_factory=lambda: int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    )

    @staticmethod
    def from_raw(raw: str | bytes | Dict[str, Any]) -> "MessageEnvelope":
        """
        Parse a raw JSON string/bytes or already-dict message emitted by
        API Gateway and convert it into a validated MessageEnvelope.
        """
        if isinstance(raw, (str, bytes, bytearray)):
            try:
                raw_dict: Dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise MessageValidationError("Message body is not valid JSON") from exc
        elif isinstance(raw, MutableMapping):
            raw_dict = dict(raw)
        else:
            raise MessageValidationError("Unsupported message body type")

        required_fields = {"tenant_id", "player_id", "msg_type", "payload"}
        missing = required_fields - raw_dict.keys()
        if missing:
            raise MessageValidationError(f"Missing required fields: {', '.join(missing)}")

        return MessageEnvelope(
            tenant_id=str(raw_dict["tenant_id"]),
            player_id=str(raw_dict["player_id"]),
            msg_type=str(raw_dict["msg_type"]).upper(),
            payload=raw_dict["payload"],
            correlation_id=raw_dict.get("correlation_id") or str(uuid.uuid4()),
            timestamp=int(raw_dict.get("timestamp", int(time.time() * 1000))),
        )

    # Helper for easy serialisation back to JSON
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "player_id": self.player_id,
            "msg_type": self.msg_type,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "received_at": self.received_at,
        }


@dataclass(slots=True)
class HandlerResponse:
    """
    Normalised response returned by command handlers.  The message is sent
    back to the client via API-Gateway 'callback' route by the upstream
    Lambda wrapper (not implemented here).
    """

    ok: bool
    data: Any = None
    error: Optional[str] = None
    correlation_id: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "data": self.data,
                "error": self.error,
                "correlation_id": self.correlation_id,
            }
        )


# ---------------------------------------------------------------------------#
# Rate limiting (simple in-memory token bucket for burst protection)
# ---------------------------------------------------------------------------#


class TokenBucket:
    """
    A naïve in-memory token bucket limiter.  Good enough for burst control
    at the Lambda-invocation level.  Does *not* guarantee global rate
    limiting across cold starts.
    """

    def __init__(self, capacity: int, refill_rate_per_second: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate_per_second
        self.last_refill = time.time()

    def allow(self) -> bool:
        now = time.time()
        elapsed = now - self.last_refill
        # Refill
        refill_amount = elapsed * self.refill_rate
        if refill_amount > 0:
            self.tokens = min(self.capacity, self.tokens + refill_amount)
            self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


# One token bucket per (tenant, player)
_RATE_LIMIT_CACHE: dict[str, TokenBucket] = {}
_BUCKET_CAPACITY = 20
_BUCKET_RATE = 5  # 5 tokens per second sustained


def _get_bucket(tenant_id: str, player_id: str) -> TokenBucket:
    key = f"{tenant_id}:{player_id}"
    if key not in _RATE_LIMIT_CACHE:
        _RATE_LIMIT_CACHE[key] = TokenBucket(_BUCKET_CAPACITY, _BUCKET_RATE)
    return _RATE_LIMIT_CACHE[key]


# ---------------------------------------------------------------------------#
# Command Dispatcher
# ---------------------------------------------------------------------------#


class MessageHandler:
    """
    Registers and dispatches message types to *command handlers*.

    Command handler signature:
    ``handler(envelope: MessageEnvelope) -> HandlerResponse``

    Handlers should be idempotent and side-effect free where possible.  Any
    *long-running* or *state-changing* operations must be off-loaded to the
    event bus (see ``_fanout``) to keep the Lambda duration minimal.
    """

    def __init__(self) -> None:
        self._registry: Dict[str, Callable[[MessageEnvelope], HandlerResponse]] = {}
        # Lazily instantiate AWS clients to reduce cold-start
        self._eventbridge = boto3.client("events", region_name=os.getenv("AWS_REGION", "us-east-1"))

    # ------------- Registration -------------

    def register(self, msg_type: str) -> Callable[[Callable[[MessageEnvelope], HandlerResponse]], None]:
        """
        Decorator for registering a handler::

            @handler.register("PING")
            def _handle_ping(msg: MessageEnvelope) -> HandlerResponse:
                return HandlerResponse(ok=True, data={"pong": True})

        """

        def decorator(fn: Callable[[MessageEnvelope], HandlerResponse]) -> None:
            self._registry[msg_type.upper()] = fn
            LOGGER.debug("Registered message handler for %s → %s", msg_type.upper(), fn)
            return None

        return decorator

    # ------------- Runtime -------------

    def handle_raw(self, raw: str | bytes | Dict[str, Any]) -> HandlerResponse:
        """
        Entry-point expected to be called by the Lambda function handler.
        """
        envelope = MessageEnvelope.from_raw(raw)

        LOGGER.debug("Received message: %s", envelope.to_dict())
        self._enforce_tenant(envelope.tenant_id)
        self._enforce_rate_limit(envelope)

        handler = self._registry.get(envelope.msg_type)
        if not handler:
            LOGGER.warning("No handler registered for message type: %s", envelope.msg_type)
            raise HandlerNotFoundError(f"Unsupported message type '{envelope.msg_type}'")

        try:
            response = handler(envelope)
        except Exception as exc:  # noqa: BLE001 – catch-all to protect invocation
            LOGGER.exception("Handler for %s raised exception", envelope.msg_type)
            response = HandlerResponse(
                ok=False,
                error="Internal server error",
                correlation_id=envelope.correlation_id,
            )

        # Fan out async event for audit/logging
        self._fanout(envelope)

        LOGGER.debug("Returning response: %s", response.to_json())
        return response

    # ------------- Guards -------------

    @staticmethod
    def _enforce_tenant(tenant_id: str) -> None:
        if ALLOWED_TENANTS and tenant_id not in ALLOWED_TENANTS:
            LOGGER.warning("Unauthorized tenant attempted access: %s", tenant_id)
            raise UnauthorizedTenantError(f"Tenant '{tenant_id}' is not authorised")

    @staticmethod
    def _enforce_rate_limit(envelope: MessageEnvelope) -> None:
        bucket = _get_bucket(envelope.tenant_id, envelope.player_id)
        if not bucket.allow():
            LOGGER.warning(
                "Rate limit exceeded for tenant=%s player=%s",
                envelope.tenant_id,
                envelope.player_id,
            )
            raise MessageError("Rate limit exceeded")

    # ------------- Side-effects -------------

    def _fanout(self, envelope: MessageEnvelope) -> None:
        """
        Push a copy of the envelope to EventBridge for downstream consumers
        (analytics, audit, or other micro-services).  Non-blocking.
        """
        try:
            self._eventbridge.put_events(
                Entries=[
                    {
                        "EventBusName": EVENT_BUS_NAME,
                        "Source": "ledgerquest.client",
                        "DetailType": envelope.msg_type,
                        "Time": datetime.utcnow(),
                        "Detail": json.dumps(envelope.to_dict(), default=str),
                    }
                ]
            )
        except (BotoCoreError, ClientError) as exc:
            # Do not crash the main flow – log and move on
            LOGGER.error("Failed to publish event to EventBridge: %s", exc, exc_info=False)


# ---------------------------------------------------------------------------#
# Built-in Command Handlers
# ---------------------------------------------------------------------------#


handler = MessageHandler()


@handler.register("PING")
def _handle_ping(msg: MessageEnvelope) -> HandlerResponse:
    """
    Basic healthcheck roundtrip for latency measurements.
    """
    duration_ms = int(time.time() * 1000) - msg.timestamp
    return HandlerResponse(
        ok=True,
        data={"pong": True, "rt_ms": duration_ms},
        correlation_id=msg.correlation_id,
    )


@handler.register("MOVE_ENTITY")
def _handle_move_entity(msg: MessageEnvelope) -> HandlerResponse:
    """
    Example command that moves an entity inside the ECS world.

    In a real deployment the heavy lifting would be pushed to a state
    machine or ECS task; here we only perform input validation and
    respond synchronously.
    """

    required = {"entity_id", "x", "y", "z"}
    missing = required - msg.payload.keys()
    if missing:
        return HandlerResponse(
            ok=False,
            error=f"Missing fields in payload: {', '.join(missing)}",
            correlation_id=msg.correlation_id,
        )

    # Publish 'EntityMoveRequested' event for downstream (physics worker)
    try:
        handler._eventbridge.put_events(
            Entries=[
                {
                    "EventBusName": EVENT_BUS_NAME,
                    "Source": "ledgerquest.gameplay",
                    "DetailType": "EntityMoveRequested",
                    "Time": datetime.utcnow(),
                    "Detail": json.dumps(
                        {
                            "tenant_id": msg.tenant_id,
                            "entity_id": msg.payload["entity_id"],
                            "target": {"x": msg.payload["x"], "y": msg.payload["y"], "z": msg.payload["z"]},
                            "requested_by": msg.player_id,
                            "correlation_id": msg.correlation_id,
                        }
                    ),
                }
            ]
        )
    except (BotoCoreError, ClientError) as exc:
        LOGGER.exception("Failed to emit EntityMoveRequested event: %s", exc)
        return HandlerResponse(
            ok=False,
            error="Unable to process move request",
            correlation_id=msg.correlation_id,
        )

    return HandlerResponse(
        ok=True,
        data={"accepted": True},
        correlation_id=msg.correlation_id,
    )


# ---------------------------------------------------------------------------#
# Lambda function entry point
# ---------------------------------------------------------------------------#


def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    """
    AWS Lambda runtime entry-point.  Expects an API-Gateway WebSocket
    payload (version 2.0).  The function only handles the *MESSAGE* route
    key; connect/disconnect pings are handled elsewhere.
    """
    try:
        body = event.get("body") or event.get("detail") or "{}"
        response = handler.handle_raw(body)

        # Prepare message for the API-Gateway "callback" invocation
        return {
            "statusCode": 200,
            "body": response.to_json(),
            "headers": {"Content-Type": "application/json"},
        }
    except MessageError as err:
        LOGGER.info("Client error: %s", err)
        return {
            "statusCode": 400,
            "body": json.dumps({"ok": False, "error": str(err)}),
            "headers": {"Content-Type": "application/json"},
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Unhandled exception")
        return {
            "statusCode": 500,
            "body": json.dumps({"ok": False, "error": "Internal server error"}),
            "headers": {"Content-Type": "application/json"},
        }
```