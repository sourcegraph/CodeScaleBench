```python
"""
flockdesk.modules.presence.model.user_status
===========================================

Model abstractions that represent a user’s *presence* state inside FlockDesk.
The model is intentionally agnostic of the underlying transport/event-bus
implementation so it can be reused on the server as well as within micro-UIs.

The responsibilities of this module are:

    • Offer a strict, exhaustive enumeration of valid presence states
    • Provide a value-object (`UserStatus`) that encapsulates all status-related
      metadata (state, message, timestamps, …)
    • Enforce *legal* state-transitions via a tiny state-machine
    • Offer (de)serialization helpers for round-tripping over the event-bus
    • Provide an Observer API so interested parties can subscribe to status
      changes in a decoupled fashion

The code purposefully stays dependency-light (only stdlib) to keep the model
portable across the frontend and backend code-bases.
"""

from __future__ import annotations

import enum
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Final, Iterable, List, Mapping, MutableSet

__all__ = [
    "PresenceState",
    "IllegalStatusTransition",
    "UserStatus",
]

_LOGGER: Final = logging.getLogger(__name__)


class PresenceState(enum.Enum):
    """
    Exhaustive list of presence states a user can be in.
    """

    OFFLINE = "offline"          # The user is not connected
    INVISIBLE = "invisible"      # Connected, but appears offline
    ONLINE = "online"            # Active and available
    AWAY = "away"                # Idle or temporarily away
    DND = "do_not_disturb"       # Does not want to be interrupted
    BUSY = "busy"                # Actively working, but may respond
    PRESENTING = "presenting"    # Sharing screen / in focus-mode

    @classmethod
    def from_str(cls, value: str) -> "PresenceState":
        """
        Convert a string to a PresenceState. Case-insensitive.
        """
        try:
            return cls(value.lower())
        except ValueError as exc:
            raise ValueError(f"Unknown presence state: {value!r}") from exc


# Legal state transitions ----------------------------------------------------


_ALLOWED_TRANSITIONS: Mapping[PresenceState, MutableSet[PresenceState]] = {
    PresenceState.OFFLINE: {
        PresenceState.ONLINE,
        PresenceState.INVISIBLE,
    },
    PresenceState.INVISIBLE: {
        PresenceState.ONLINE,
        PresenceState.DND,
        PresenceState.AWAY,
        PresenceState.OFFLINE,
    },
    PresenceState.ONLINE: {
        PresenceState.AWAY,
        PresenceState.BUSY,
        PresenceState.DND,
        PresenceState.PRESENTING,
        PresenceState.INVISIBLE,
        PresenceState.OFFLINE,
    },
    PresenceState.AWAY: {
        PresenceState.ONLINE,
        PresenceState.OFFLINE,
        PresenceState.INVISIBLE,
    },
    PresenceState.BUSY: {
        PresenceState.ONLINE,
        PresenceState.DND,
        PresenceState.OFFLINE,
    },
    PresenceState.DND: {
        PresenceState.ONLINE,
        PresenceState.OFFLINE,
    },
    PresenceState.PRESENTING: {
        PresenceState.ONLINE,
        PresenceState.OFFLINE,
    },
}


class IllegalStatusTransition(RuntimeError):
    """
    Raised when an attempt is made to switch to a state that is not legal.
    """


# Observer pattern helpers ----------------------------------------------------


Observer = Callable[["UserStatus"], None]


@dataclass(slots=True, frozen=True)
class _Metadata:
    """Container for fields we do *not* expose via asdict()."""

    sequence: int = 0


# Main model ------------------------------------------------------------------


@dataclass(slots=True)
class UserStatus:
    """
    Value-object carrying the status of a single user.

    The object is *mutable* so that UI components can hold a shared reference
    that reflects live changes. Thread-safety is guaranteed via an internal
    re-entrant lock.
    """

    user_id: str
    state: PresenceState = PresenceState.OFFLINE
    message: str = ""
    last_changed: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    # Private fields ----------------------------------------------------------
    _observers: List[Observer] = field(default_factory=list, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _meta: _Metadata = field(default_factory=_Metadata, init=False, repr=False)

    # Public API --------------------------------------------------------------

    # --------------------------------------------------------------------- #
    # Status mutation                                                        #
    # --------------------------------------------------------------------- #

    def update(
        self,
        new_state: PresenceState,
        /,
        *,
        message: str | None = None,
        force: bool = False,
    ) -> None:
        """
        Transition to *new_state*.

        Parameters
        ----------
        new_state:
            The desired presence state.
        message:
            Optional user-visible status-message (e.g. “Grabbing lunch”). ``None``
            keeps the current message untouched, an *empty* string clears it.
        force:
            Skip the allowed-transition validation. Reserved for system-level
            code (e.g. session-restore) that needs to restore an older snapshot
            verbatim.
        """
        with self._lock:
            if not force and not self._is_transition_allowed(new_state):
                raise IllegalStatusTransition(
                    f"{self.state.value} ➔ {new_state.value} is not allowed."
                )

            self.state = new_state
            if message is not None:
                self.message = message

            self.last_changed = datetime.now(tz=timezone.utc)
            object.__setattr__(
                self._meta,
                "sequence",
                self._meta.sequence + 1,
            )

        _LOGGER.debug(
            "User '%s' changed status to %s (seq=%d)",
            self.user_id,
            new_state.value,
            self._meta.sequence,
        )
        self._notify_observers()

    # --------------------------------------------------------------------- #
    # Observer utilities                                                    #
    # --------------------------------------------------------------------- #

    def attach(self, cb: Observer, /) -> None:
        """
        Subscribe *cb* to future status changes. Duplicate registrations
        are ignored.
        """
        with self._lock:
            if cb not in self._observers:
                self._observers.append(cb)

    def detach(self, cb: Observer, /) -> None:
        """
        Unsubscribe *cb*. Calls to unknown observers are ignored.
        """
        with self._lock:
            try:
                self._observers.remove(cb)
            except ValueError:
                pass

    # --------------------------------------------------------------------- #
    # Serialization                                                         #
    # --------------------------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the object into a JSON-compatible dict.
        """
        with self._lock:
            payload = asdict(self)
            # Replace complex objects
            payload["state"] = self.state.value
            payload["last_changed"] = self.last_changed.isoformat()
            # Strip private fields added by dataclasses.asdict()
            payload.pop("_observers", None)
            payload.pop("_lock", None)
            payload.pop("_meta", None)
            payload["sequence"] = self._meta.sequence
            return payload

    def to_json(self, *, pretty: bool = False) -> str:
        """
        Serialize the object to a JSON string.
        """
        if pretty:
            return json.dumps(self.to_dict(), indent=2, sort_keys=True)
        return json.dumps(self.to_dict(), separators=(",", ":"))

    # --------------------------------------------------------------------- #
    # Static helpers                                                        #
    # --------------------------------------------------------------------- #

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], /) -> "UserStatus":
        """
        Restore a *UserStatus* from the mapping created by :py:meth:`to_dict`.
        """
        try:
            instance = cls(
                user_id=str(data["user_id"]),
                state=PresenceState.from_str(data["state"]),
                message=data.get("message", ""),
                last_changed=datetime.fromisoformat(data["last_changed"]),
            )
        except KeyError as exc:
            raise ValueError("Malformed user-status payload (missing field)") from exc

        # Restore the monotonically increasing sequence number (private)
        object.__setattr__(instance._meta, "sequence", int(data.get("sequence", 0)))
        return instance

    @classmethod
    def from_json(cls, raw: str | bytes, /) -> "UserStatus":
        """
        Restore a *UserStatus* from its JSON representation.
        """
        return cls.from_dict(json.loads(raw))

    # --------------------------------------------------------------------- #
    # Misc. utilities                                                       #
    # --------------------------------------------------------------------- #

    def copy(self) -> "UserStatus":
        """
        Return a deep copy that is detached from observers and locks.
        """
        return UserStatus.from_dict(self.to_dict())

    # --------------------------------------------------------------------- #
    # Private helpers                                                       #
    # --------------------------------------------------------------------- #

    def _is_transition_allowed(self, new_state: PresenceState) -> bool:
        return new_state in _ALLOWED_TRANSITIONS[self.state]

    def _notify_observers(self) -> None:
        """
        Notify subscribers in a *thread-safe* manner – but call them *outside*
        the lock to avoid re-entrancy deadlocks. A failing observer will be
        logged and *detached* automatically so that one bad plugin does not
        block further updates.
        """
        # Snapshot list to keep iteration stable even when observers detach
        with self._lock:
            observers: Iterable[Observer] = tuple(self._observers)

        for cb in observers:
            try:
                cb(self)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception(
                    "Observer %r failed while processing status-change for '%s'. "
                    "Observer has been removed.",
                    cb,
                    self.user_id,
                )
                self.detach(cb)
```