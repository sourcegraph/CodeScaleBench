```python
"""
crowdpay_connect.libs.shared_events
==================================

This package bundles the event-sourcing primitives that every CrowdPay
micro–service shares.  All domain events inherit from :class:`BaseEvent`
which provides:

    • Strong data–validation (powered by *pydantic*)
    • Globally unique identifiers (ULIDs preferred, UUIDs as fallback)
    • Schema versioning
    • Correlation / Causation metadata for distributed tracing
    • A zero-dependency JSON/ORJSON codec with pluggable encryption hooks
    • A dynamic registry allowing run-time event deserialisation

The module is deliberately placed inside ``__init__.py`` to remove the
need for deep import paths:

    from crowdpay_connect.libs.shared_events import BaseEvent, register_event
"""
from __future__ import annotations

import datetime as _dt
import importlib
import json
import types
import typing as _t
import uuid
from pathlib import Path

try:  # Prefer ultra-fast ORJSON when available.
    import orjson as _orjson

    def _dumps(obj: _t.Any) -> bytes:  # type: ignore[override]
        return _orjson.dumps(obj)

    def _loads(b: _t.Union[str, bytes, bytearray]) -> _t.Any:  # type: ignore[override]
        return _orjson.loads(b)
except ModuleNotFoundError:  # pragma: no cover
    _orjson = None

    def _dumps(obj: _t.Any) -> bytes:  # type: ignore[override]
        return json.dumps(obj, separators=(",", ":"), default=str).encode()

    def _loads(b: _t.Union[str, bytes, bytearray]) -> _t.Any:  # type: ignore[override]
        if isinstance(b, (bytes, bytearray)):
            b = b.decode()
        return json.loads(b)


from pydantic import BaseModel, Field, validator

__all__ = [
    "BaseEvent",
    "register_event",
    "EVENT_REGISTRY",
    "Codec",
    "EncryptionHook",
    "EventId",
]


class EventId(str):
    """Strongly-typed event identifier (ULID/UUID)."""

    _ULID_LEN = 26  # Crockford Base32 ULID length

    @classmethod
    def new(cls) -> "EventId":
        """
        Attempt to create a lexicographically sortable ULID.  Fallback to
        a RFC-4122 v4 UUID when the *ulid* package is not installed.
        """
        try:
            import ulid  # pylint: disable=import-error

            return cls(str(ulid.new()))
        except ModuleNotFoundError:  # pragma: no cover
            return cls(str(uuid.uuid4()))

    @classmethod
    def __get_validators__(cls):  # pydantic hook
        yield cls.validate  # type: ignore[misc]

    @classmethod
    def validate(cls, v):  # noqa: ANN001
        if isinstance(v, cls):
            return v
        if isinstance(v, str) and v:
            return cls(v)
        raise TypeError("EventId must be a non-empty string")


class EncryptionHook(_t.Protocol):
    """
    A callable that optionally encrypts/decrypts raw bytes.  The hook is
    injected via dependency-injection inside the gateway service.
    """

    def __call__(self, payload: bytes, *, decrypt: bool = False) -> bytes:  # noqa: D401
        ...


class Codec:
    """
    Handles (de)serialisation of events including optional encryption.

    The codec is intentionally *stateless*; services can therefore
    create an instance and swap the encryption hook at runtime without
    concern for thread safety.
    """

    __slots__ = ("_encryptor",)

    def __init__(self, encryptor: _t.Optional[EncryptionHook] = None) -> None:
        self._encryptor = encryptor

    # Public API -------------------------------------------------------------

    def encode(self, event: "BaseEvent") -> bytes:
        """
        Serialise *event* into an encrypted JSON/ORJSON byte‐string.

        Raises:
            ValueError: if serialisation fails.
        """
        try:
            payload = _dumps(event.dict())
            if self._encryptor:
                payload = self._encryptor(payload, decrypt=False)
            return payload
        except Exception as exc as exc:  # noqa: E722
            raise ValueError(f"Failed to encode event: {exc}") from exc

    def decode(self, payload: _t.Union[bytes, str]) -> "BaseEvent":
        """
        Transform raw payload back into a fully-typed event instance.

        Raises:
            ValueError: if deserialisation or event lookup fails.
        """
        try:
            if self._encryptor:
                payload = self._encryptor(payload, decrypt=True)
            data = _loads(payload)
            event_cls = EVENT_REGISTRY[data["type"]]
            return event_cls.parse_obj(data)
        except KeyError as exc:
            raise ValueError(f"Unrecognised event type: {exc}") from exc
        except Exception as exc:  # noqa: E722
            raise ValueError(f"Failed to decode event: {exc}") from exc


class BaseEvent(BaseModel):
    """
    Base-class for all domain and integration events.

    Sub-classes are automatically registered in :data:`EVENT_REGISTRY`
    via :func:`register_event`.
    """

    id: EventId = Field(default_factory=EventId.new)
    type: str = Field(..., regex=r"^[a-z0-9_.-]+$", description="Snake-cased event type.")
    schema_version: int = Field(1, ge=1)
    # Temporal metadata ------------------------------------------------------
    emitted_at: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    # Distributed tracing ----------------------------------------------------
    correlation_id: _t.Optional[str] = Field(
        None,
        description="Identifier connecting logically related operations.",
    )
    causation_id: _t.Optional[str] = Field(
        None,
        description="Identifier of the parent event/command which triggered this event.",
    )

    class Config:  # noqa: D106
        allow_mutation = False
        json_loads = _loads
        json_dumps = lambda obj, *_, **__: _dumps(obj).decode()
        orm_mode = True

    @validator("type", pre=True, always=True)
    def _default_event_type(cls, v):  # noqa: ANN001
        # Use fully-qualified class path as a deterministic, snake-cased type.
        return v or f"{cls.__module__}.{cls.__name__}".lower()

    # Misc helpers -----------------------------------------------------------

    def upgrade(self) -> "BaseEvent":
        """
        Override in child classes that require backwards-compatibility
        upgrades.  The default implementation returns *self* unchanged.
        """
        return self


EVENT_REGISTRY: dict[str, _t.Type[BaseEvent]] = {}


def register_event(cls: _t.Type[BaseEvent]) -> _t.Type[BaseEvent]:
    """
    Class decorator that injects *cls* into :data:`EVENT_REGISTRY`.

    Usage:

        @register_event
        class FundDeposited(BaseEvent):
            ...

    The decorator enforces that ``type`` is unique and immutability is
    respected.
    """
    if not issubclass(cls, BaseEvent):
        raise TypeError("Only BaseEvent sub-classes can be registered.")

    event_type = f"{cls.__module__}.{cls.__name__}".lower()
    if event_type in EVENT_REGISTRY:
        raise ValueError(f"Duplicate event type registration: '{event_type}'")

    cls.__fields__["type"].default = event_type  # Inject default type.
    EVENT_REGISTRY[event_type] = cls
    return cls


# ---------------------------------------------------------------------------#
# Example Event Definitions                                                  #
# ---------------------------------------------------------------------------#
@register_event
class CrowdPodCreated(BaseEvent):
    crowdpod_id: str = Field(..., min_length=12, max_length=64)
    owner_user_id: str = Field(..., min_length=12, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    currency: str = Field(..., regex=r"^[A-Z]{3}$")
    initial_balance_minor: int = Field(0, ge=0)


@register_event
class FundDeposited(BaseEvent):
    crowdpod_id: str = Field(..., min_length=12, max_length=64)
    deposit_txn_id: str = Field(..., min_length=12, max_length=64)
    amount_minor: int = Field(..., gt=0)
    currency: str = Field(..., regex=r"^[A-Z]{3}$")


@register_event
class FundWithdrawn(BaseEvent):
    crowdpod_id: str = Field(..., min_length=12, max_length=64)
    withdrawal_txn_id: str = Field(..., min_length=12, max_length=64)
    amount_minor: int = Field(..., gt=0)
    currency: str = Field(..., regex=r"^[A-Z]{3}$")
    risk_assessment_score: float = Field(..., ge=0.0, le=1.0)


@register_event
class KYCVerified(BaseEvent):
    user_id: str = Field(..., min_length=12, max_length=64)
    verification_reference: str = Field(..., min_length=12, max_length=64)
    provider: str = Field(..., min_length=2, max_length=64)
    # Schema evolution example ----------------------------------------------
    schema_version: int = 2  # Incremented due to breaking change

    def upgrade(self) -> BaseEvent:  # pragma: no cover
        """
        Downgrade path for legacy consumers pinned to ``schema_version=1``.
        """
        if self.schema_version == 1:
            return self
        # Simulated downgrade transformation.
        return self.copy(update={"schema_version": 1, "provider": "legacy"})


# ---------------------------------------------------------------------------#
# Dynamic Discovery (optional)                                               #
# ---------------------------------------------------------------------------#
def _auto_import_events() -> None:
    """
    Eagerly import event modules declared under *crowdpay_connect.events*.
    Allows plug-ins to register themselves without direct imports.
    """
    pkg = "crowdpay_connect.events"
    try:
        package_path = Path(importlib.import_module(pkg).__file__).parent  # type: ignore[attr-defined]
    except (ModuleNotFoundError, AttributeError):
        return

    for py in package_path.rglob("*.py"):
        rel = py.relative_to(package_path).with_suffix("")
        if rel.name.startswith("__"):
            continue
        dotted = f"{pkg}.{'.'.join(rel.parts)}"
        importlib.import_module(dotted)


_auto_import_events()
```