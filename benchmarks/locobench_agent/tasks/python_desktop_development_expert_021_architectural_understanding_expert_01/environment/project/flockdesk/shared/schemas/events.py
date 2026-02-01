```python
"""
FlockDesk – Social Workspace Orchestrator
========================================

Centralised, versioned event-schema definitions that are shared between every
micro-frontend and backend helper running inside the FlockDesk desktop shell.

The public surface of this module purposefully stays small and *stable*; every
other process in the stack relies on it for validation and introspection.  To
avoid accidental breaking changes, **never remove or re-purpose fields**—
always add new schema versions when required.

The implementation below embraces a *plugin-first* design: 3rd-party extensions
can register their own events at runtime while still benefitting from the same
strict Pydantic validation enjoyed by core services.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Type, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator

_LOGGER = logging.getLogger("flockdesk.events")
T_Event = TypeVar("T_Event", bound="BaseEvent")

###############################################################################
# Exceptions
###############################################################################


class EventError(RuntimeError):
    """Base-class for all event-related exceptions."""


class UnknownEventType(EventError):
    """Raised when the incoming envelope references an unregistered event."""


###############################################################################
# Event Registry
###############################################################################

_EVENT_REGISTRY: Dict[str, Type["BaseEvent"]] = {}


def register_event_type(cls: Type[T_Event]) -> Type[T_Event]:  # noqa: N802
    """
    Decorator used by subclasses of BaseEvent to register themselves for
    deserialisation.  The registration key is taken from `cls.EVENT_TYPE`.
    """
    event_type = getattr(cls, "EVENT_TYPE", None)
    if not event_type or not isinstance(event_type, str):
        raise ValueError(
            f"{cls.__name__} must define a non-empty class attribute "
            "`EVENT_TYPE` of type `str` to be used as a registry key."
        )

    if event_type in _EVENT_REGISTRY:
        raise EventError(
            f"Duplicate event-type '{event_type}' "
            f"(already registered by {_EVENT_REGISTRY[event_type].__name__})."
        )

    _EVENT_REGISTRY[event_type] = cls
    _LOGGER.debug("Registered event-type %s → %s", event_type, cls.__qualname__)
    return cls


###############################################################################
# Common helpers
###############################################################################


class SemVer(str):
    """
    Very small helper that guarantees a value follows the semantic version
    pattern (e.g. '1.2.3').  Meant for extension-version fields.
    """

    _PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

    @classmethod
    def __get_validators__(cls):  # type: ignore[override]
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> "SemVer":
        if not isinstance(value, str) or not cls._PATTERN.match(value):
            raise ValueError("value must be semantic version: MAJOR.MINOR.PATCH")
        return cls(value)


def _utcnow() -> datetime:
    """Helper for `default_factory` to avoid late binding of *now*."""
    return datetime.now(tz=timezone.utc)


###############################################################################
# Base Event
###############################################################################


class BaseEvent(BaseModel):
    """
    All concrete events MUST inherit from `BaseEvent`.

    Subclasses **must** provide a class-attribute `EVENT_TYPE` that will be
    propagated to the envelope for run-time routing.
    """

    # --- envelope metadata  -------------------------------------------------
    event_id: UUID = Field(
        default_factory=uuid4,
        description="Unique event identifier for idempotency/replay protection.",
        json_schema_extra={"example": "8d34f2af-cf9f-42e4-9889-1d46f8ed1561"},
    )
    emitted_at: datetime = Field(
        default_factory=_utcnow,
        description="UTC timestamp at which the event was emitted.",
        json_schema_extra={"example": "2025-05-21T14:36:19.123456+00:00"},
    )
    source: str = Field(
        ...,
        min_length=3,
        max_length=64,
        regex=r"^[a-z][a-z0-9_\-.]*$",
        description="Service or extension name that emitted the event.",
        json_schema_extra={"example": "chat-service"},
    )
    correlation_id: Optional[UUID] = Field(
        default=None,
        description="Identifier used for tracing a flow that spans multiple "
        "events across services.",
        json_schema_extra={"example": "b607bc55-a3ab-4f68-8f81-9124a4a1ab22"},
    )

    # -----------------------------------------------------------------------
    # The following fields/attrs are *not* part of the Pydantic payload.  They
    # are implemented as `@property` / `ClassVar` to avoid duplication.
    # -----------------------------------------------------------------------

    # This attribute is used by the registry to route envelopes.
    EVENT_TYPE: ClassVar[str] = "base"

    @property
    def type(self) -> str:  # noqa: D401
        """Return the fully-qualified event-type (e.g. 'chat.message')."""
        return self.EVENT_TYPE

    # -----------------------------------------------------------------------
    # Serialisation helpers
    # -----------------------------------------------------------------------

    def to_envelope(self, *, indent: int | None = None) -> str:
        """
        Serialise the event into a JSON envelope that carries the type
        metadata alongside the validated payload.
        """
        envelope = {"type": self.type, "payload": self.model_dump(mode="json")}
        return json.dumps(envelope, indent=indent, default=str)

    # -----------------------------------------------------------------------
    # Validators ‑ applied to all subclasses
    # -----------------------------------------------------------------------
    @field_validator("emitted_at")
    @classmethod
    def _ensure_tzaware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("emitted_at must be timezone-aware (UTC).")
        return v

    # -----------------------------------------------------------------------
    # Equality / hashing
    # -----------------------------------------------------------------------
    def __hash__(self) -> int:  # noqa: D401
        return hash(self.event_id)

    def __str__(self) -> str:  # noqa: D401
        return f"<{self.__class__.__name__} {self.event_id}>"


###############################################################################
# Enums used by concrete events
###############################################################################


class PresenceStatus(str, Enum):
    online = "online"
    away = "away"
    dnd = "dnd"
    offline = "offline"


###############################################################################
# Concrete Event Implementations
###############################################################################


@register_event_type
class ChatMessageEvent(BaseEvent):
    """
    Event fired when a user sends a chat message in a channel or DM.
    """

    EVENT_TYPE: ClassVar[str] = "chat.message"

    channel_id: str = Field(
        ..., description="Chat channel identifier",
        json_schema_extra={"example": "general"}
    )
    user_id: str = Field(
        ..., min_length=3, description="User who sent the message",
        json_schema_extra={"example": "u_42"}
    )
    message: str = Field(
        ..., min_length=1, max_length=10_000, description="UTF-8 encoded message"
    )
    mentions: List[str] = Field(
        default_factory=list,
        description="User-IDs referenced with @mention.",
        json_schema_extra={"example": ["u_99", "u_101"]}
    )

    @field_validator("message")
    @classmethod
    def _strip_whitespace(cls, v: str) -> str:
        return v.rstrip("\n")


@register_event_type
class PresenceUpdateEvent(BaseEvent):
    """
    Event fired when a user's presence changes.
    """

    EVENT_TYPE: ClassVar[str] = "presence.update"

    user_id: str = Field(..., description="Affected user ID", json_schema_extra={"example": "u_42"})
    status: PresenceStatus = Field(..., description="New presence status")
    activity: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Optional free-text describing the activity (e.g. 'editing app.py').",
    )


@register_event_type
class FileSharedEvent(BaseEvent):
    """
    Event emitted by the file-sharing service once a file becomes available.
    """

    EVENT_TYPE: ClassVar[str] = "file.shared"

    user_id: str = Field(..., description="Uploader's user ID")
    vault_path: str = Field(
        ..., description="Canonical path inside the shared vault."
    )
    file_size: int = Field(..., ge=0, description="Size in bytes")
    sha256: str = Field(
        ...,
        regex=r"^[A-Fa-f0-9]{64}$",
        description="Hex-encoded SHA-256 digest to guarantee integrity.",
    )


@register_event_type
class ExtensionLoadedEvent(BaseEvent):
    """
    Event broadcasted when a plugin/extension is successfully loaded.
    """

    EVENT_TYPE: ClassVar[str] = "extension.loaded"

    extension_name: str = Field(..., min_length=3, max_length=64)
    extension_version: SemVer = Field(..., description="Semantic version string")


@register_event_type
class SettingsChangedEvent(BaseEvent):
    """
    Event raised after user settings/preferences have been modified.
    """

    EVENT_TYPE: ClassVar[str] = "settings.changed"

    user_id: str = Field(..., description="User that changed the setting")
    path: str = Field(
        ..., regex=r"^[a-z][a-z0-9_\-.]*(\.[a-z0-9_\-.]+)+$",
        description="Dot-separated path of the setting (e.g. 'editor.theme')."
    )
    new_value: Any = Field(
        ..., description="JSON-serialisable representation of the new value."
    )


###############################################################################
# Envelope utilities
###############################################################################


def parse_envelope(raw: str | bytes) -> BaseEvent:
    """
    High-level helper used by message brokers / IPC layers.

    Parameters
    ----------
    raw:
        UTF-8 encoded JSON string where the root object must contain
        the keys ``type`` and ``payload``.

    Returns
    -------
    BaseEvent
        A fully-validated *subclass* of `BaseEvent`.

    Raises
    ------
    UnknownEventType
        When the ``type`` part of the envelope refers to an unregistered event.
    ValidationError
        Forwarded from Pydantic when the payload doesn't match the schema.
    JSONDecodeError
        When the envelope is not valid JSON.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="strict")

    envelope = json.loads(raw)
    event_type = envelope.get("type")
    payload = envelope.get("payload")

    if event_type not in _EVENT_REGISTRY:
        raise UnknownEventType(f"Event-type '{event_type}' is not registered.")

    model_cls = _EVENT_REGISTRY[event_type]
    _LOGGER.debug("Deserialising envelope into %s", model_cls.__qualname__)
    return model_cls.model_validate(payload)  # type: ignore[return-value]


###############################################################################
# Public re-exports
###############################################################################

__all__ = [
    # Helpers
    "EventError",
    "UnknownEventType",
    "parse_envelope",
    # Base / registry (for plugins)
    "BaseEvent",
    "register_event_type",
    # Core event definitions
    "ChatMessageEvent",
    "PresenceUpdateEvent",
    "FileSharedEvent",
    "ExtensionLoadedEvent",
    "SettingsChangedEvent",
    # Enums
    "PresenceStatus",
    "SemVer",
]
```