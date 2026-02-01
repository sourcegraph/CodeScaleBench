```python
"""
flockdesk.modules.presence.service
=================================

PresenceService is responsible for tracking the local user’s presence
status, broadcasting updates to the internal event-bus, and consuming
presence-events from other peers so that the rest of the desktop suite
(i.e. chat panes, user lists, dashboards) can present up-to-date
availability information.

Key responsibilities
--------------------
1. Detect local activity / idleness and derive an appropriate
   `PresenceState`.
2. Expose an explicit `set_status` API so plugins (e.g. “Do-Not-Disturb
   scheduler”) or GUI controls can override the automatic heuristic.
3. Maintain an in-memory registry of *all* known users’ presence data.
4. Publish `presence.updated` events and subscribe to the same topic for
   remote updates—guaranteeing eventual consistency across processes.
5. Provide a coroutine-driven lifecycle that can be started / stopped
   from the application’s service-loader infrastructure.

The implementation purposely avoids any hard dependency on a concrete
EventBus or IPC layer.  Instead, it relies on a lightweight protocol
interface (`EventBusProtocol`) so that different deployments (embedded
in-proc, ZeroMQ, or an HTTP bridge) can supply their own bus adapter.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    MutableMapping,
    Optional,
    Protocol,
    Type,
)

LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Protocols & Data Models
# --------------------------------------------------------------------------- #
class EventBusProtocol(Protocol):
    """
    A minimal protocol any event-bus implementation has to satisfy so the
    PresenceService can remain transport-agnostic.
    """

    def subscribe(
        self, topic: str, callback: Callable[[str, Dict[str, Any]], Awaitable[None]]
    ) -> None:  # pragma: no cover
        ...

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:  # noqa: D401
        ...


class PresenceState(str, enum.Enum):
    """Enumeration of all presence states supported by FlockDesk."""

    ONLINE = "online"
    AWAY = "away"
    DND = "dnd"  # Do-Not-Disturb
    OFFLINE = "offline"

    def __str__(self) -> str:
        return self.value


@dataclass(slots=True)
class PresenceInfo:
    """
    Canonical presence payload that gets serialized to the event-bus.
    """

    user_id: str
    state: PresenceState
    updated_at: datetime = field(default_factory=datetime.utcnow)
    # Free-form metadata for plugins (e.g. custom emoji, busy_reason)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "state": self.state.value,
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "PresenceInfo":
        return cls(
            user_id=raw["user_id"],
            state=PresenceState(raw["state"]),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
            metadata=raw.get("metadata", {}),
        )


# --------------------------------------------------------------------------- #
# Helper Utilities
# --------------------------------------------------------------------------- #
def _system_idle_seconds() -> float:
    """
    Cross-platform(ish) API for fetching idle time. We degrade gracefully to
    returning `0` when platform integration is unavailable rather than
    raising—presence detection will still work albeit less smart.

    Notes
    -----
    • Windows:   GetLastInputInfo via `ctypes`.
    • macOS:     IOKit wrapper (❌ not yet implemented).
    • X11/Wayland:  XScreenSaver (❌ not yet implemented).
    """
    try:
        if sys.platform == "win32":
            import ctypes  # pylint: disable=import-error

            class LASTINPUTINFO(ctypes.Structure):  # type: ignore
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            plii = LASTINPUTINFO()
            plii.cbSize = ctypes.sizeof(plii)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(plii)) == 0:  # type: ignore  # noqa
                return 0.0
            millis = ctypes.windll.kernel32.GetTickCount() - plii.dwTime  # type: ignore
            return millis / 1000.0
    except Exception:  # noqa: BLE001
        LOGGER.debug("Idle time detection failed", exc_info=True)

    # Unsupported OS or error—fallback.
    return 0.0


# --------------------------------------------------------------------------- #
# Presence Service
# --------------------------------------------------------------------------- #
class PresenceService:
    """
    High-level façade exposed to the rest of the desktop suite.

    Lifecycle (`async with PresenceService(...):`) is preferred so that the
    activity watchdog coroutine shuts down cleanly during application exit.
    """

    HEARTBEAT_INTERVAL = timedelta(seconds=30)
    IDLE_THRESHOLD = timedelta(minutes=5)

    def __init__(
        self,
        *,
        user_id: str,
        bus: EventBusProtocol,
        idle_provider: Callable[[], float] | None = None,
    ) -> None:
        self._user_id: str = user_id
        self._bus = bus
        self._idle_provider = idle_provider or _system_idle_seconds

        self._registry: MutableMapping[str, PresenceInfo] = {}
        self._local_state: PresenceState = PresenceState.ONLINE
        self._override_state: PresenceState | None = None

        # Concurrency
        self._loop = asyncio.get_running_loop()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._stop_event = asyncio.Event()

        # Register bus subscription early so we don't miss events during `await __aenter__`
        self._bus.subscribe("presence.updated", self._on_presence_event)

    # --------------------------------------------------------------------- #
    # Context Manager Helpers
    # --------------------------------------------------------------------- #
    async def __aenter__(self) -> "PresenceService":
        self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Optional[bool]:
        await self.stop()
        # Don't suppress any exception
        return None

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def start(self) -> None:
        """Spawn background coroutines (watchdog + heartbeat)."""
        if self._tasks:
            return  # Already started
        LOGGER.debug("PresenceService starting")
        self._tasks.add(self._loop.create_task(self._activity_watchdog()))
        self._tasks.add(self._loop.create_task(self._heartbeat_publisher()))

    async def stop(self) -> None:
        """Signal background tasks to stop and wait for graceful exit."""
        LOGGER.debug("PresenceService stopping")
        self._stop_event.set()
        # Wait for tasks to finish with timeout
        await asyncio.wait(self._tasks, timeout=2.0)
        self._tasks.clear()

    async def set_status(
        self,
        state: PresenceState,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        override: bool = True,
    ) -> None:
        """
        Explicitly set the local user’s status.

        Parameters
        ----------
        state:
            One of PresenceState values.
        metadata:
            Optional free-form metadata blob.
        override:
            If `True` automatic idle detection is disabled until
            `clear_manual_override()` is called.  This prevents race
            conditions when the user explicitly picks *DND* but is
            technically “active” according to the heuristic.
        """
        self._override_state = state if override else None
        await self._broadcast_local_state(state, metadata or {})

    async def clear_manual_override(self) -> None:
        """
        Re-enable automatic presence detection that may have been
        suspended via `set_status(..., override=True)`.
        """
        LOGGER.debug("Presence manual override cleared")
        self._override_state = None
        # Force immediate reconsideration
        await self._evaluate_local_state()

    def get_presence(self, user_id: str) -> Optional[PresenceInfo]:
        """Return the latest presence data we have for `user_id`."""
        return self._registry.get(user_id)

    # --------------------------------------------------------------------- #
    # Internal – Background Tasks
    # --------------------------------------------------------------------- #
    async def _activity_watchdog(self) -> None:
        """
        Periodically check system idle time and update `self._local_state`
        accordingly.
        """
        LOGGER.debug("Presence watchdog started")
        while not self._stop_event.is_set():
            try:
                await self._evaluate_local_state()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Presence watchdog error")
            await asyncio.sleep(5)  # Poll frequency

        LOGGER.debug("Presence watchdog terminated")

    async def _heartbeat_publisher(self) -> None:
        """
        Consolidated heartbeat ensuring that *some* presence update is sent
        at least every `HEARTBEAT_INTERVAL`, even if the state hasn’t
        changed.  This aids recovery in case any bus message was missed.
        """
        LOGGER.debug("Presence heartbeat started")
        while not self._stop_event.is_set():
            try:
                await self._broadcast_local_state(self._local_state, {})
            except Exception:  # noqa: BLE001
                LOGGER.exception("Presence heartbeat error")
            await asyncio.sleep(self.HEARTBEAT_INTERVAL.total_seconds())

        LOGGER.debug("Presence heartbeat terminated")

    # --------------------------------------------------------------------- #
    # Internal – State Evaluation & Publishing
    # --------------------------------------------------------------------- #
    async def _evaluate_local_state(self) -> None:
        """
        Decide which `PresenceState` the local user should be in based on
        idle time and manual overrides.
        """
        # Manual override takes precedence
        if self._override_state:
            state = self._override_state
        else:
            idle_seconds = self._idle_provider()
            state = (
                PresenceState.AWAY
                if idle_seconds >= self.IDLE_THRESHOLD.total_seconds()
                else PresenceState.ONLINE
            )

        if state != self._local_state:
            LOGGER.debug(
                "Presence state transition: %s → %s (override=%s)",
                self._local_state,
                state,
                bool(self._override_state),
            )
            await self._broadcast_local_state(state, {})

    async def _broadcast_local_state(
        self, state: PresenceState, metadata: Dict[str, Any]
    ) -> None:
        """
        Update internal registry and publish the change.
        """
        self._local_state = state
        payload = PresenceInfo(
            user_id=self._user_id,
            state=state,
            metadata=metadata,
        )
        # Update local registry synchronously
        self._registry[self._user_id] = payload
        await self._bus.publish("presence.updated", payload.to_json())

    # --------------------------------------------------------------------- #
    # Event-Bus Handlers
    # --------------------------------------------------------------------- #
    async def _on_presence_event(self, topic: str, data: Dict[str, Any]) -> None:
        """
        Called for *all* presence.updated events—including the one we just
        broadcast ourselves.  We update our registry and forward the
        information to any interested observers (plugins, UI model, etc.).
        """
        try:
            info = PresenceInfo.from_json(data)
        except (ValueError, KeyError) as exc:
            LOGGER.warning("Malformed presence payload: %s (err=%s)", data, exc)
            return

        # Ignore outdated events – ensure monotonic update per user
        current = self._registry.get(info.user_id)
        if current and info.updated_at <= current.updated_at:
            return

        self._registry[info.user_id] = info
        LOGGER.debug(
            "Presence updated: %s state=%s meta=%s",
            info.user_id,
            info.state,
            json.dumps(info.metadata, ensure_ascii=False),
        )

        # Fan-out to local observers by publishing an *internal* asyncio.Event.
        # A more sophisticated implementation might rely on RxPy, signal
        # dispatchers, or other observer patterns.  For now we stick with the
        # event-bus only.
        # NOTE: Nothing to do here; UI layers will subscribe to the same bus
        # topic, or they can query `get_presence()` directly.

```