```python
"""
ledgerquest.shared.models
~~~~~~~~~~~~~~~~~~~~~~~~~

Domain and transport models that are reused across the LedgerQuest Engine
code-base.  These objects act as “contracts” between otherwise independent
micro-services/Lambda functions and are thus intentionally designed to be
framework-agnostic and strictly *data-only*.

The majority of objects below inherit from `pydantic.BaseModel` in order to
take advantage of:

* Runtime data-validation (defensive programming when functions are invoked
  directly, e.g. by Step Functions).
* JSON-serialisation that is compatible with both API Gateway and DynamoDB’s
  Document API.
* Type-hints that IDEs can surface to game-designers writing Python-based
  scenario scripts.

These models **must never** contain heavy business logic—keep them free of
side-effects so that the same class may safely be imported by untrusted
extension code executed in sandboxed environments.
"""
from __future__ import annotations

import enum
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Type, TypeVar, Union

from pydantic import BaseModel, Field, NonNegativeInt, validator

# ────────────────────────────────────────────────────────────────────────────────
# Logging setup
# ────────────────────────────────────────────────────────────────────────────────
_logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────────
ISO8601 = "%Y-%m-%dT%H:%M:%S.%fZ"
T = TypeVar("T", bound="LedgerQuestModel")


def utcnow() -> datetime:
    """Return an *aware* ``datetime`` in UTC with micro-second precision."""
    return datetime.now(tz=timezone.utc)


def new_ulid() -> str:  # pragma:  no cover
    """
    Return a lexicographically sortable unique identifier.

    Uses UUIDv4 as a fall-back if the ``ulid-py`` package is not available.
    """
    try:
        import ulid  # type: ignore

        return str(ulid.new())
    except ModuleNotFoundError:  # pragma: no cover
        # Fall back to UUIDv4 (lexicographical ordering is worse but acceptable)
        return uuid.uuid4().hex


def _to_dynamodb(value: Any) -> Any:
    """
    Convert a Python value into something that can be stored using DynamoDB’s
    *Document* API.

    DynamoDB does not accept ``float`` due to potential precision issues; the
    *decimal* module is mandated instead.  We keep this helper internal—
    repositories will handle full recursive conversion.
    """
    if isinstance(value, float):
        return Decimal(str(value))  # preserve precision
    return value


# ────────────────────────────────────────────────────────────────────────────────
# Base Classes
# ────────────────────────────────────────────────────────────────────────────────
class LedgerQuestModel(BaseModel):
    """
    Root Pydantic model with some convenience utilities shared by *all*
    serialisable objects in LedgerQuest.
    """

    class Config:
        allow_mutation = False
        json_encoders = {
            datetime: lambda v: v.strftime(ISO8601),
            Decimal: lambda v: float(v),
        }
        orm_mode = True

    # --------------------------------------------------------------------- #
    # Convenience Constructors
    # --------------------------------------------------------------------- #
    @classmethod
    def from_event(cls: Type[T], event: Mapping[str, Any]) -> T:
        """
        Instantiate a model from a generic AWS event (API Gateway, EventBridge,
        Step Functions, etc.).

        Any keys that are not part of the model specification are ignored.
        """
        return cls.parse_obj(event)

    # --------------------------------------------------------------------- #
    # Dynamo Helpers
    # --------------------------------------------------------------------- #
    def dynamodb_item(self) -> Dict[str, Any]:
        """
        Convert the model into a flat *item* ready for
        ``boto3.Table.put_item``.  Nested structures are serialised to JSON
        strings to avoid DynamoDB deep nesting limits.
        """
        item: Dict[str, Any] = {}
        for f, v in self.dict().items():
            # Primitive conversion
            converted = _to_dynamodb(v)
            # Convert containers
            if isinstance(converted, (dict, list)):
                converted = json.dumps(converted, separators=(",", ":"))
            item[f] = converted
        return item


# ────────────────────────────────────────────────────────────────────────────────
# Enumerations
# ────────────────────────────────────────────────────────────────────────────────
class TenantTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class ComponentType(str, enum.Enum):
    TRANSFORM = "transform"
    RENDERABLE = "renderable"
    PHYSICS_BODY = "physics_body"
    SCRIPT = "script"
    CUSTOM = "custom"


class EventType(str, enum.Enum):
    ENTITY_CREATED = "entity_created"
    ENTITY_REMOVED = "entity_removed"
    COMPONENT_ADDED = "component_added"
    COMPONENT_REMOVED = "component_removed"
    INPUT_ACTION = "input_action"
    SYSTEM_HEARTBEAT = "system_heartbeat"
    CUSTOM = "custom"


class AuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ACCESS = "access"
    ERROR = "error"


# ────────────────────────────────────────────────────────────────────────────────
# Core Domain Models
# ────────────────────────────────────────────────────────────────────────────────
class TenantContext(LedgerQuestModel):
    """
    Information that uniquely identifies and scopes a customer (“tenant”) in the
    multi-tenant LedgerQuest deployment.
    """

    tenant_id: str = Field(..., regex=r"^[a-zA-Z0-9_\-]{3,64}$")
    tier: TenantTier = TenantTier.FREE
    # Optional customer-provided correlation data (e.g. subscription ID)
    external_ref: Optional[str]


class EntityId(LedgerQuestModel):
    """
    Unique identifier for an Entity in an ECS world.  We keep this object
    separate so that additional metadata (e.g. *entity archetype*) may be added
    later without changing primary keys in DynamoDB.
    """

    hex: str = Field(default_factory=lambda: uuid.uuid4().hex, regex=r"^[0-9a-f]{32}$")

    # NOTE: helper methods __str__ and __hash__ make EntityId usable as dict key
    def __str__(self) -> str:
        return self.hex

    def __hash__(self) -> int:
        return hash(self.hex)


class PhysicsVector(LedgerQuestModel):
    """Generic 3-D vector model used by physics and transform components."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    magnitude: Optional[float] = None

    @validator("magnitude", always=True)
    def _compute_magnitude(cls, v: Optional[float], values: Mapping[str, Any]) -> float:
        if v is not None:
            return v
        return (values["x"] ** 2 + values["y"] ** 2 + values["z"] ** 2) ** 0.5


class TransformComponent(LedgerQuestModel):
    """Simple Transform component for an ECS entity."""

    position: PhysicsVector = Field(default_factory=PhysicsVector)
    rotation: PhysicsVector = Field(default_factory=PhysicsVector)
    scale: PhysicsVector = Field(default_factory=lambda: PhysicsVector(x=1.0, y=1.0, z=1.0))


class ComponentEnvelope(LedgerQuestModel):
    """
    Dynamically-typed container that wraps *any* component payload and annotates
    it with metadata required for proper deserialisation.
    """

    type: ComponentType
    data: Dict[str, Any]

    def unpack(self) -> LedgerQuestModel:
        """
        Convert the generic dictionary payload into its corresponding strongly
        typed model.  Custom components registered at runtime via plug-ins can
        provide their own mapping by calling `ComponentEnvelope.register`.
        """
        model_cls = _COMPONENT_REGISTRY.get(self.type, None)
        if not model_cls:
            raise ValueError(f"Unknown component type: {self.type}")
        return model_cls.parse_obj(self.data)

    # --------------------------------------------------------------------- #
    # Registry helpers
    # --------------------------------------------------------------------- #
    _COMPONENT_REGISTRY: Dict[ComponentType, Type[LedgerQuestModel]] = {}

    @classmethod
    def register(cls, component_type: ComponentType, model_cls: Type[LedgerQuestModel]) -> None:
        if component_type in cls._COMPONENT_REGISTRY:
            _logger.warning("Overwriting component registration for %s", component_type)
        cls._COMPONENT_REGISTRY[component_type] = model_cls


# Pre-register core components
ComponentEnvelope.register(ComponentType.TRANSFORM, TransformComponent)


class EventEnvelope(LedgerQuestModel):
    """
    Canonical event wrapper used for all messages traversing the internal
    EventBridge bus.  Envelopes are versioned to ensure forward-compatibility
    across independently deployable services.
    """

    # --------------------------------------------------------------------- #
    # Envelope metadata
    # --------------------------------------------------------------------- #
    id: str = Field(default_factory=new_ulid, description="Globally unique event identifier")
    version: str = "1.0"
    type: EventType
    timestamp: datetime = Field(default_factory=utcnow)
    tenant: TenantContext

    # Allows distributed tracing à-la Honeycomb, X-Ray, etc.
    correlation_id: Optional[str]
    causation_id: Optional[str]

    # --------------------------------------------------------------------- #
    # Actual payload (domain specific)
    # --------------------------------------------------------------------- #
    data: Mapping[str, Any]

    # --------------------------------------------------------------------- #
    # Convenience API
    # --------------------------------------------------------------------- #
    def embed(self, model: LedgerQuestModel) -> "EventEnvelope":
        """
        Helper that serialises an arbitrary Pydantic model as the *data* payload.
        """
        object.__setattr__(self, "data", model.dict())
        return self

    def for_tenant(self, tenant: TenantContext) -> "EventEnvelope":
        object.__setattr__(self, "tenant", tenant)
        return self


class AuditLogRecord(LedgerQuestModel):
    """
    Immutable audit log entry written by all mutating Lambda functions.
    """

    tenant_id: str
    action: AuditAction
    actor_id: str  # Could be a user GUID, service-principal, etc.
    target_ref: str  # e.g. "ENTITY#<entity-id>" or "COMPONENT#<guid>"
    timestamp: datetime = Field(default_factory=utcnow)
    request_id: Optional[str]  # Lambda request identifier
    remote_addr: Optional[str]  # Extracted from API Gateway, if present
    details: Optional[Mapping[str, Any]]

    # DynamoDB partition/sort keys (Projection-friendly)
    pk: str = Field(init=False)
    sk: str = Field(init=False)

    @validator("pk", always=True)
    def _compute_pk(cls, v: str, values: Mapping[str, Any]) -> str:  # type: ignore[override]
        return f"TENANT#{values['tenant_id']}#AUDIT"

    @validator("sk", always=True)
    def _compute_sk(cls, v: str, values: Mapping[str, Any]) -> str:  # type: ignore[override]
        ts = values["timestamp"].strftime("%Y%m%dT%H%M%S%f")
        return f"{ts}#{values['action'].value.upper()}#{values['target_ref']}"


# ────────────────────────────────────────────────────────────────────────────────
# Example System Heartbeat (used by Step Functions watchdog)
# ────────────────────────────────────────────────────────────────────────────────
class SystemHeartbeat(LedgerQuestModel):
    service: str = Field(..., description="Name of the Lambda function or Fargate task")
    uptime_ms: NonNegativeInt
    build_sha: str
    extras: Optional[Dict[str, Any]]


# Registering the heartbeat as a dedicated envelope type for convenience
ComponentEnvelope.register(ComponentType.CUSTOM, SystemHeartbeat)
```