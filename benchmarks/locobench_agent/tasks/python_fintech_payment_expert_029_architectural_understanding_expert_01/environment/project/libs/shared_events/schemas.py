```python
"""
crowdpay_connect.libs.shared_events.schemas
==========================================

Strongly-typed, versioned domain-event schemas used across the CrowdPay
Connect micro-service landscape.  All events MUST inherit from
`BaseDomainEvent` which guarantees a minimal interoperable contract that
is enforced by the event-bus, consumers, the Saga orchestrator, and the
audit-trail subsystem.

The schemas defined here are intentionally *pure* (no side-effects) so
that they can be safely imported by any project component—including
those running inside untrusted plugin sandboxes—without risk.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Dict, Mapping, MutableMapping, Optional, Type, TypeVar

from pydantic import BaseModel, Field, ValidationError, root_validator, validator

__all__ = [
    # core
    "BaseDomainEvent",
    "Envelope",
    "EventParsingError",
    "EventRegistry",
    # enumerations
    "Currency",
    # events
    "CrowdPodCreated",
    "PaymentInitiated",
    "PaymentAuthorized",
    "PaymentSettled",
    "PaymentFailed",
    "KycVerified",
    "RiskScoreComputed",
]

logger = logging.getLogger(__name__)
_T = TypeVar("_T", bound="BaseDomainEvent")

###############################################################################
# Exceptions
###############################################################################


class EventParsingError(RuntimeError):
    """Raised when raw payload cannot be mapped onto an event schema."""


###############################################################################
# Generic type helpers
###############################################################################


class StrEnum(str, Enum):
    """
    Enum whose members are also (and must be) strings.  Useful for pydantic
    compatibility & JSON serialisation.
    """

    def __str__(self) -> str:
        return str.__str__(self)


###############################################################################
# Enumerations (shared constants)
###############################################################################


class Currency(StrEnum):
    """Simplified ISO-4217 currency codes subset used in CrowdPay."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    NGN = "NGN"
    GHS = "GHS"
    ZAR = "ZAR"


###############################################################################
# Core event abstractions
###############################################################################


class BaseDomainEvent(BaseModel):
    """
    Base class for all domain events.

    The base contract is intentionally minimal; concrete services MAY
    extend/override as needed, but *must not* break backwards
    compatibility once an event has been published.
    """

    # --- CloudEvent-like metadata ------------------------------------------------
    event_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique event identifier (automatically generated if absent).",
    )
    event_type: str = Field(
        ...,
        description="Fully-qualified name of the event class.",
        example="PaymentInitiated",
    )
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="Timestamp (UTC) at which the event occurred.",
    )

    # --- Correlation for distributed tracing / sagas ----------------------------
    correlation_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Identifier that ties a set of related events together (Saga).",
    )
    causation_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Identifier of the event that directly caused this event.",
    )

    # --- Misc --------------------------------------------------------------------
    producer: str = Field(
        ...,
        description="Name of the micro-service or component that emitted the event.",
        example="payments-service",
    )
    schema_version: int = Field(
        1,
        ge=1,
        description="Revision of the event schema (bump when breaking changes happen).",
    )

    # --------------------------------------------------------------------------- #
    # Pydantic / validation hooks
    # --------------------------------------------------------------------------- #

    @validator("occurred_at", pre=True, always=True)
    def _ensure_timezone(cls, v: datetime) -> datetime:  # noqa: N805
        """Guarantee that *all* datetime values are timezone-aware (UTC)."""
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            # auto-convert naive datetime to UTC
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @root_validator(pre=True)
    def _auto_event_type(cls, values: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N805
        """
        Inject `event_type` automatically when the caller forgot to provide one.
        """
        values.setdefault("event_type", cls.__name__)
        return values

    # --------------------------------------------------------------------------- #
    # Public helpers
    # --------------------------------------------------------------------------- #

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """
        Serialise the event to JSON.  The serialisation is strictly
        lossless—`from_json()` MUST return an *equivalent* event.
        """
        return self.json(indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls: Type[_T], raw: str | bytes | bytearray) -> _T:
        """
        Parse raw JSON into an event instance of *this* class.

        NB: If you do not know the concrete event class ahead of time use
        `EventRegistry.loads(...)` instead.
        """
        try:
            return cls.parse_raw(raw)
        except (ValidationError, ValueError) as exc:
            logger.exception("Error parsing %s from json", cls.__name__)
            raise EventParsingError(str(exc)) from exc

    # To avoid pydantic recursion issues in generic containers
    class Config:
        json_encoders = {uuid.UUID: lambda v: str(v)}


###############################################################################
# Concrete event definitions (immutable value objects)
###############################################################################


class CrowdPodCreated(BaseDomainEvent):
    """
    Emitted when a new CrowdPod (social wallet) is created.
    """

    pod_id: uuid.UUID = Field(..., description="CrowdPod identifier")
    owner_id: uuid.UUID = Field(..., description="User ID of CrowdPod creator")
    pod_name: str = Field(..., description="Human friendly name of the CrowdPod")
    base_currency: Currency = Field(..., description="Primary operating currency")

    # Example of backward-compatible evolution: the "description" field was
    # optional in v1, mandatory in v2, etc.  Keep the default for v1.
    description: Optional[str] = Field(
        default=None,
        description="Longer CrowdPod description shown to followers",
    )


class PaymentInitiated(BaseDomainEvent):
    """
    Raised when a payment is initiated by a user against a CrowdPod.
    """

    payment_id: uuid.UUID = Field(..., description="Payment identifier")
    pod_id: uuid.UUID = Field(..., description="Target CrowdPod id")
    payer_id: uuid.UUID = Field(..., description="User executing the payment")
    amount_minor: int = Field(
        ...,
        gt=0,
        description="Payment amount in *minor* units (e.g. cents).",
    )
    currency: Currency = Field(..., description="Currency of the payment")


class PaymentAuthorized(BaseDomainEvent):
    """
    Raised when a payment has passed risk / KYC checks and has been
    authorised with the underlying payment rail or banking partner.
    """

    payment_id: uuid.UUID
    authorised_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="Timestamp at which payment was authorised",
    )


class PaymentSettled(BaseDomainEvent):
    """
    Raised once funds have settled into the CrowdPod wallet.
    """

    payment_id: uuid.UUID
    settled_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="Timestamp at which payment settlement completed",
    )
    fx_rate: Optional[float] = Field(
        default=None,
        ge=0,
        description="Applied FX rate if currency conversion occurred",
    )


class PaymentFailed(BaseDomainEvent):
    """
    Raised when a payment fails any stage of processing.
    """

    payment_id: uuid.UUID
    reason: str = Field(..., description="Human readable failure reason")
    recoverable: bool = Field(
        ...,
        description="True if the payment can be retried automatically",
    )


class KycVerified(BaseDomainEvent):
    """
    Raised when a user successfully passes KYC verification.
    """

    user_id: uuid.UUID
    verified_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="Timestamp at which KYC check completed",
    )
    provider: str = Field(..., description="KYC provider/vendor name")
    country_code: str = Field(
        ...,
        regex=r"^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 country code used for verification",
    )


class RiskScoreComputed(BaseDomainEvent):
    """
    Raised by the risk-assessment micro-service whenever a (re)-calculation
    of a user or payment risk profile completes.
    """

    entity_id: uuid.UUID = Field(..., description="ID of user or payment")
    entity_type: str = Field(
        ...,
        description="`user` or `payment` — determines type of 'entity_id'",
    )
    risk_score: int = Field(..., ge=0, le=100, description="0=low, 100=high risk")
    model_version: str = Field(
        ...,
        description="Semantic version of the ML model used for scoring",
    )


###############################################################################
# Event envelope & registry
###############################################################################


class Envelope(BaseModel):
    """
    Wraps a concrete event with additional broker-level metadata such as
    topic name or partition key.  The envelope allows us to transport a
    heterogeneous stream without losing typing information.
    """

    # ----------------------------------------------------------------------- #
    # Required
    event: BaseDomainEvent = Field(..., description="The actual domain event")

    # ----------------------------------------------------------------------- #
    # Broker-specific metadata (Kafka/AMQP etc.)
    topic: str = Field(..., description="Event-bus topic")
    partition_key: str = Field(
        ...,
        description="Value used by broker for partition selection "
        "(often user id or CrowdPod id)",
    )
    headers: MutableMapping[str, str] = Field(
        default_factory=dict,
        description="Arbitrary key/value pairs forwarded as broker headers",
    )

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="Producer-side timestamp used by the broker",
    )

    # Helper shortcuts
    def to_json(self, *, indent: Optional[int] = None) -> str:
        return self.json(indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str | bytes | bytearray) -> "Envelope":
        try:
            return cls.parse_raw(raw)
        except (ValidationError, ValueError) as exc:
            raise EventParsingError(str(exc)) from exc

    class Config:
        json_encoders = BaseDomainEvent.Config.json_encoders


class EventRegistry:
    """
    Dynamically resolves event_type (string) into the correct
    pydantic schema class.  Used by consumers that subscribe to the
    global stream and need to deserialize an unknown event.
    """

    _registry: ClassVar[Dict[str, Type[BaseDomainEvent]]] = {}

    # ------------------------------------------------------------------- #
    # Public API
    # ------------------------------------------------------------------- #

    @classmethod
    def register(cls, model: Type[BaseDomainEvent]) -> None:
        key = model.__name__
        if key in cls._registry:  # pragma: no cover
            logger.warning("Overwriting event '%s' in registry", key)
        cls._registry[key] = model
        logger.debug("Registered event %s", key)

    @classmethod
    def get(cls, name: str) -> Type[BaseDomainEvent]:
        try:
            return cls._registry[name]
        except KeyError as exc:  # pragma: no cover
            raise EventParsingError(f"Unknown event type '{name}'") from exc

    @classmethod
    def loads(cls, raw: str | bytes | bytearray) -> BaseDomainEvent:
        """
        Deserialize arbitrarily typed JSON payload into the correct
        `BaseDomainEvent` subclass using the embedded `event_type`.
        """
        try:
            payload: Mapping[str, Any] = json.loads(raw)
            event_type: str = payload["event_type"]
        except (KeyError, ValueError, TypeError) as exc:
            raise EventParsingError(
                "Invalid raw event: missing or malformed 'event_type'"
            ) from exc

        model_cls = cls.get(event_type)
        try:
            return model_cls.parse_obj(payload)
        except ValidationError as exc:
            raise EventParsingError(
                f"Failed to parse '{event_type}' – {exc}"
            ) from exc

    # ------------------------------------------------------------------- #
    # Convenience helpers
    # ------------------------------------------------------------------- #

    @classmethod
    def dump_schema(cls) -> Dict[str, Any]:
        """
        Return a JSON-schema dictionary for *all* registered events.
        Useful for documentation or schema-registry pipelines.
        """
        return {name: model.schema() for name, model in cls._registry.items()}


###############################################################################
# Auto-registration of all events defined in this module
###############################################################################

_current_module = globals()
for obj in list(_current_module.values()):
    if (
        isinstance(obj, type)
        and issubclass(obj, BaseDomainEvent)
        and obj is not BaseDomainEvent
    ):
        EventRegistry.register(obj)
```