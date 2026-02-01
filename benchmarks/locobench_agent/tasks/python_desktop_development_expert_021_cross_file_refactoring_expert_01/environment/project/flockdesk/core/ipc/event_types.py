```python
"""
flockdesk.core.ipc.event_types
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Canonical declaration of event topics, event names, and helper utilities
for the in-process / cross-process event-bus powering FlockDesk’s desktop
micro-front-ends.

The goal of this module is to provide one single source of truth regarding
what events exist, what their *fully–qualified names* (FQN) are, and which
Python object is expected as the payload.

Why does that matter?
---------------------
1. **Type-Safety / Static Analysis** – Editors & CI pipelines can leverage
   this module for auto-completion and mypy/pyright validation.
2. **Documentation** – Event definitions live close to code instead of
   being scattered across wikis.
3. **Plug-in Friendliness** – 3rd-party extensions can *register* their own
   events at runtime without monkey-patching anything.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    MutableMapping,
    Optional,
    Type,
    TypeVar,
)

__all__ = [
    "EventTopic",
    "Event",
    "EventRegistry",
    "event",
    "PayloadT",
]

###############################################################################
# Event Topic & Name Declarations
###############################################################################

class EventTopic(str, Enum):
    """
    Logical top-level buckets for events flowing through the FlockDesk bus.

    Topics loosely correspond to micro-front-ends or backend domains and help
    routing as well as access-control decisions.
    """

    # User-facing / collaborative domains
    CHAT = "chat"
    WHITEBOARD = "whiteboard"
    PRESENCE = "presence"
    FILES = "files"
    SETTINGS = "settings"
    PLUGIN = "plugin"

    # System / infrastructure domains
    SYSTEM = "system"
    LOGGING = "logging"
    METRICS = "metrics"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


###############################################################################
# Base Event Dataclass
###############################################################################

PayloadT = TypeVar("PayloadT", bound=Mapping[str, Any])


@dataclass(slots=True, frozen=True)
class Event:
    """
    Runtime instance of an Event exchanged on the bus.

    Immutable on purpose – mutability would open the door for tricky bugs
    once the same event instance is fanned-out to multiple subscribers.
    """

    topic: EventTopic
    name: str
    payload: PayloadT
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    reply_to: Optional[str] = None

    # --------------------------------------------------------------------- #
    # Convenience helpers
    # --------------------------------------------------------------------- #

    @property
    def fqn(self) -> str:
        """
        Fully-qualified event name (Topic + sub-name).

        Example:
        >>> evt.fqn
        'chat.message.sent'
        """
        return f"{self.topic.value}.{self.name}"

    def to_json(self) -> str:
        """
        Serialize event to JSON for IPC (e.g. when crossing process boundary).
        """
        as_dict = {
            "topic": self.topic.value,
            "name": self.name,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "reply_to": self.reply_to,
        }
        return json.dumps(as_dict, separators=(",", ":"))


###############################################################################
# Registry Infrastructure
###############################################################################

class _SingletonMeta(type):
    """Thread-safe singleton metaclass used for `EventRegistry`."""

    _instance: Optional["EventRegistry"] = None
    _lock: threading.Lock = threading.Lock()

    def __call__(cls, *args: Any, **kwargs: Any):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # double-checked locking
                    cls._instance = super().__call__(*args, **kwargs)
        return cls._instance


class EventRegistry(metaclass=_SingletonMeta):
    """
    Keep track of *all* event classes and their associated FQNs.

    Plugins are allowed to add to this registry at runtime.
    """

    def __init__(self) -> None:
        # _events maps FQN -> payload dataclass (or a typing.Mapping subclass)
        self._events: Dict[str, Type[Mapping[str, Any]]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def register(
        self,
        *,  # keyword-only for clarity
        topic: EventTopic,
        name: str,
        payload_type: Type[Mapping[str, Any]],
        override: bool = False,
    ) -> None:
        """
        Register a new event definition.

        Parameters
        ----------
        topic:
            Top-level domain of the event.
        name:
            Sub-name without topic prefix (e.g. 'message.sent').
        payload_type:
            A `dataclass` *or* any `Mapping[str, Any]` derived type describing
            the contract of the event's payload.
        override:
            Whether an already registered FQN should be overwritten.
        """
        if not name or "." not in name and topic not in (
            EventTopic.SYSTEM,
            EventTopic.LOGGING,
            EventTopic.METRICS,
        ):
            raise ValueError(
                "Event name must contain at least one '.' to express hierarchy "
                f"(got '{name}')"
            )

        fqn = f"{topic.value}.{name}"

        with self._lock:
            if fqn in self._events and not override:
                raise KeyError(
                    f"Event '{fqn}' already registered. "
                    "Use 'override=True' to update the definition."
                )
            self._events[fqn] = payload_type

    def payload_type_for(self, fqn: str) -> Type[Mapping[str, Any]]:
        """
        Retrieve the expected payload type for a given event FQN.
        """
        try:
            return self._events[fqn]
        except KeyError as exc:
            raise KeyError(
                f"Event '{fqn}' not known to registry – did you forget to "
                "import or register the corresponding plugin?"
            ) from exc

    def is_known(self, fqn: str) -> bool:
        return fqn in self._events

    @property
    def all_events(self) -> Mapping[str, Type[Mapping[str, Any]]]:
        """
        Immutable view on currently registered event types.
        """
        return MappingProxyType(self._events)


###############################################################################
# Decorator – ergonomic way to register events
###############################################################################

def event(
    *,
    topic: EventTopic,
    name: str,
) -> Callable[[Type[PayloadT]], Type[PayloadT]]:
    """
    Class decorator registering the decorated payload dataclass as
    the canonical representation of `topic.name`.

    Example
    -------
    >>> @event(topic=EventTopic.CHAT, name="message.sent")
    ... @dataclass(slots=True, frozen=True)
    ... class MessageSentPayload(Mapping[str, Any]):
    ...     message_id: str
    ...     author_id: str
    ...     content: str
    """

    def decorator(payload_cls: Type[PayloadT]) -> Type[PayloadT]:
        EventRegistry().register(
            topic=topic,
            name=name,
            payload_type=payload_cls,
            override=False,
        )
        return payload_cls

    return decorator


###############################################################################
# Built-in Event Payloads
###############################################################################

# --- CHAT ------------------------------------------------------------------- #


@dataclass(slots=True, frozen=True)
class _PayloadBase(Mapping[str, Any]):
    """
    Minimal Mapping implementation so payloads can be treated
    like dictionaries while still enjoying dataclass benefits.
    """

    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return getattr(self, key)

    def __iter__(self):  # noqa: D401
        return (field.name for field in dataclasses.fields(self))

    def __len__(self) -> int:  # noqa: D401
        return len(dataclasses.fields(self))

    # ------------------------------------------------------------------ #
    # Dict & JSON helpers
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


@event(topic=EventTopic.CHAT, name="message.sent")
@dataclass(slots=True, frozen=True)
class ChatMessageSent(_PayloadBase):
    message_id: str
    author_id: str
    room_id: str
    content: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@event(topic=EventTopic.CHAT, name="message.deleted")
@dataclass(slots=True, frozen=True)
class ChatMessageDeleted(_PayloadBase):
    message_id: str
    author_id: str
    room_id: str
    deleted_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- PRESENCE --------------------------------------------------------------- #

@event(topic=EventTopic.PRESENCE, name="user.online")
@dataclass(slots=True, frozen=True)
class PresenceUserOnline(_PayloadBase):
    user_id: str
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    client_version: str = "unknown"


@event(topic=EventTopic.PRESENCE, name="user.offline")
@dataclass(slots=True, frozen=True)
class PresenceUserOffline(_PayloadBase):
    user_id: str
    reason: Optional[str] = None
    ended_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- SETTINGS --------------------------------------------------------------- #

@event(topic=EventTopic.SETTINGS, name="changed")
@dataclass(slots=True, frozen=True)
class SettingsChanged(_PayloadBase):
    user_id: str
    key: str
    old_value: Any
    new_value: Any
    changed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


###############################################################################
# Helper Functions
###############################################################################

def validate_event(event: Event) -> None:
    """
    Ensure that *event.payload* is an *instance* of the registered payload
    type for the event’s FQN.

    Raises
    ------
    TypeError:
        If the payload's type does not match.
    KeyError:
        If the event or its payload type is unknown to the registry.
    """
    registry = EventRegistry()
    expected_type = registry.payload_type_for(event.fqn)

    if not isinstance(event.payload, expected_type):
        raise TypeError(
            f"Invalid payload type for '{event.fqn}'. "
            f"Expected '{expected_type.__name__}', got '{type(event.payload).__name__}'."
        )


###############################################################################
# Pre-warm registry for internal events
###############################################################################

# Accessing EventRegistry once at import ensures singleton instantiation.
_registry = EventRegistry()
assert _registry.is_known("chat.message.sent")
assert _registry.is_known("presence.user.online")
```