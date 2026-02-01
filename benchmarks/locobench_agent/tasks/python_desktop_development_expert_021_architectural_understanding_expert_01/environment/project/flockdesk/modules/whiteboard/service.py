```python
"""
flockdesk.modules.whiteboard.service
====================================

WhiteboardService orchestrates collaborative whiteboard sessions. It is the
single authority for loading / persisting board state, brokering draw events
across the local event-bus, and dispatching those same events to interested
plugins (pen tools, laser pointers, stickers, etc).

The module purposefully does *not* deal with Qt paint events directly—GUI
widgets publish semantic “draw” commands over the bus, which we serialise,
version, and replicate to all peers.

Core responsibilities
---------------------
• Open / close sessions – A session corresponds 1-to-1 with a file on disk.  
• Event fan-out – Local draw events → event-bus → network / plugins.  
• Autosave – Debounces writes to disk so sessions survive crashes.  
• Plugin support – Tools can register to mutate board state (e.g. shape
  recogniser).  

The implementation relies only on the public EventBus / PluginManager surface
so the unit can be exercised outside of the full desktop runtime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, MutableMapping, Optional

__all__ = ["WhiteboardService", "WhiteboardSession", "Stroke", "WhiteboardError"]

LOGGER = logging.getLogger(__name__)
AUTOSAVE_DEBOUNCE_SECONDS = 2.5
SUPPORTED_STATE_VERSION = 1


# -----------------------------------------------------------------------------
# Lightweight local EventBus stub – the real one is provided by FlockDesk core.
# -----------------------------------------------------------------------------


class EventBus:
    """A minimal pub/sub hub used by FlockDesk for inter-service messaging."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[str, Any], None]]] = {}

    def subscribe(self, topic: str, callback: Callable[[str, Any], None]) -> None:
        LOGGER.debug("Subscribing to topic=%s -> %s", topic, callback)
        self._subscribers.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[str, Any], None]) -> None:
        self._subscribers.get(topic, []).remove(callback)

    def publish(self, topic: str, payload: Any) -> None:
        LOGGER.debug("Publishing topic=%s payload=%s", topic, payload)
        for cb in list(self._subscribers.get(topic, [])):
            try:
                cb(topic, payload)
            except Exception:  # pylint: disable=broad-except
                LOGGER.exception("EventBus subscriber failure on topic=%s", topic)


# -----------------------------------------------------------------------------
# Plugin system
# -----------------------------------------------------------------------------


class WhiteboardToolPlugin:
    """
    Interface every whiteboard tool plugin **must** implement.

    A plugin typically transforms or augments draw events (e.g. converts
    freehand strokes into perfect rectangles).
    """

    plugin_id: str = "undefined"
    plugin_name: str = "Unnamed Tool"

    async def on_draw_event(self, session_id: str, event: "DrawEvent") -> None:
        raise NotImplementedError


class PluginManager:
    """
    Very small façade over the global PluginManager inside FlockDesk core.
    Only the subset required by WhiteboardService is reproduced here.
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, WhiteboardToolPlugin] = {}

    def register(self, plugin: WhiteboardToolPlugin) -> None:
        LOGGER.info("Registering whiteboard plugin %s (%s)", plugin.plugin_name, plugin.plugin_id)
        self._plugins[plugin.plugin_id] = plugin

    def unregister(self, plugin_id: str) -> None:
        LOGGER.info("Unregistering whiteboard plugin %s", plugin_id)
        self._plugins.pop(plugin_id, None)

    async def dispatch_draw_event(self, session_id: str, event: "DrawEvent") -> None:
        # Broadcast draw event to all installed plugins.
        coros: List[Awaitable[Any]] = [
            plugin.on_draw_event(session_id, event) for plugin in self._plugins.values()
        ]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)


# -----------------------------------------------------------------------------
# Datamodel
# -----------------------------------------------------------------------------

DrawEvent = Dict[str, Any]  # freeform JSON, see `Stroke` for base shape


@dataclass
class Stroke:  # pylint: disable=too-many-instance-attributes
    """
    Canonical representation of a hand-drawn stroke.

    A stroke is a series of points (x, y) in board coordinates, along with
    metadata describing colour, pressure, etc.
    """

    points: List[List[float]]  # [[x1, y1], [x2, y2], ...]
    color: str = "#000000"
    width: float = 1.5
    author: str = "anonymous"
    pressure: Optional[List[float]] = None
    timestamp: float = field(default_factory=time.time)
    stroke_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_event(self) -> DrawEvent:
        """Convert this Stroke into a serialisable draw event dict."""
        return {
            "type": "stroke",
            "id": self.stroke_id,
            "points": self.points,
            "color": self.color,
            "width": self.width,
            "author": self.author,
            "pressure": self.pressure,
            "timestamp": self.timestamp,
        }


@dataclass
class WhiteboardSession:
    """
    In-memory representation of a collaborative whiteboard.

    The state dictionary mirrors what is persisted to disk.
    """

    session_id: str
    file_path: pathlib.Path
    state: MutableMapping[str, Any] = field(default_factory=lambda: {"version": SUPPORTED_STATE_VERSION, "objects": []})
    participants: List[str] = field(default_factory=list)
    # Each session has its own lock so draws can be processed concurrently across sessions.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _dirty: bool = field(default=False, init=False)

    def mark_dirty(self) -> None:
        self._dirty = True

    @property
    def is_dirty(self) -> bool:
        return self._dirty


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------


class WhiteboardError(RuntimeError):
    """Generic exception raised by WhiteboardService."""


# -----------------------------------------------------------------------------
# WhiteboardService
# -----------------------------------------------------------------------------


class WhiteboardService:
    """
    WhiteboardService – central runtime for collaborative whiteboards.

    It binds together persistence, event routing, and plugin dispatch in a
    concurrency-safe manner so that multiple windows (and possibly networked
    peers) can interact with the same board.
    """

    DRAW_TOPIC = "whiteboard.draw"

    def __init__(
        self,
        event_bus: EventBus,
        storage_dir: pathlib.Path,
        plugin_manager: Optional[PluginManager] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._event_bus = event_bus
        self._sessions: Dict[str, WhiteboardSession] = {}
        self._storage_dir = storage_dir.expanduser().resolve()
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._plugin_mgr = plugin_manager or PluginManager()
        self._loop = loop or asyncio.get_event_loop()

        # Background autosave watcher
        self._autosave_task: Optional[asyncio.Task[None]] = None
        self._shutdown_event = asyncio.Event()

        # Subscribe to draw events from peers
        self._event_bus.subscribe(self.DRAW_TOPIC, self._on_bus_draw_event)

    # --------------------------------------------------------------------- #
    # Life-cycle                                                             #
    # --------------------------------------------------------------------- #

    async def start(self) -> None:
        """Kick-off background tasks (autosave)."""
        LOGGER.info("Starting WhiteboardService. Storage dir=%s", self._storage_dir)
        self._autosave_task = self._loop.create_task(self._autosave_loop(), name="whiteboard-autosave")

    async def shutdown(self) -> None:
        """Flush everything and stop background workers."""
        LOGGER.info("Shutting down WhiteboardService")
        self._shutdown_event.set()
        if self._autosave_task:
            await self._autosave_task
        await self._flush_all()

        # Remove bus subscription to help GC in tests
        self._event_bus.unsubscribe(self.DRAW_TOPIC, self._on_bus_draw_event)

    # --------------------------------------------------------------------- #
    # Session management                                                     #
    # --------------------------------------------------------------------- #

    async def open_session(self, session_id: Optional[str] = None) -> WhiteboardSession:
        """
        Load or create a whiteboard session.

        If a ``session_id`` is omitted a new board is initialised.
        """
        if not session_id:
            session_id = uuid.uuid4().hex

        if session_id in self._sessions:
            return self._sessions[session_id]

        file_path = self._storage_dir / f"{session_id}.json"
        session = WhiteboardSession(session_id=session_id, file_path=file_path)
        self._sessions[session_id] = session

        if file_path.exists():
            try:
                LOGGER.debug("Loading whiteboard session %s from %s", session_id, file_path)
                session.state = json.loads(file_path.read_text("utf-8"))
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.exception("Failed to load whiteboard %s: %s", session_id, exc)
                raise WhiteboardError(f"Unable to load whiteboard {session_id}") from exc
        else:
            # Persist initial state immediately so peers can join.
            await self._write_session_to_disk(session)

        return session

    async def close_session(self, session_id: str) -> None:
        """Close session and write any outstanding changes."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return

        async with session.lock:
            if session.is_dirty:
                await self._write_session_to_disk(session)

    # --------------------------------------------------------------------- #
    # Drawing                                                                #
    # --------------------------------------------------------------------- #

    async def add_stroke(self, session_id: str, stroke: Stroke) -> None:
        """
        Add a stroke to the whiteboard and broadcast to peers and plugins.

        The stroke is immediately added to the in-memory state, marked dirty,
        and published over the event-bus for any delegates to replicate.
        """
        session = await self.open_session(session_id)
        event = stroke.to_event()

        async with session.lock:
            session.state["objects"].append(event)
            session.mark_dirty()

        # Broadcast draw event so other views (and possibly network peers) update.
        self._event_bus.publish(self.DRAW_TOPIC, {"session_id": session_id, "event": event})

        # Dispatch to plugins asynchronously (fire-and-forget).
        self._loop.create_task(
            self._plugin_mgr.dispatch_draw_event(session_id, event), name=f"wb-plugin-dispatch-{session_id}"
        )

    # --------------------------------------------------------------------- #
    # Event-bus callbacks                                                    #
    # --------------------------------------------------------------------- #

    def _on_bus_draw_event(self, topic: str, payload: Dict[str, Any]) -> None:
        """
        Local subscriber that receives draw events from the bus and
        incorporates them into the session if they originated from another
        process.
        """
        try:
            session_id: str = payload["session_id"]
            event: DrawEvent = payload["event"]
        except (KeyError, TypeError):
            LOGGER.warning("Malformed draw payload: %s", payload)
            return

        # Sanity: ignore if we generated the event (no-op optimisation):
        # The spec reserves author == "local" to identify local strokes.
        if event.get("author") == "local":
            return

        # Async hand-off to not block the event-bus
        self._loop.create_task(self._apply_draw_event(session_id, event), name=f"wb-apply-{session_id}")

    async def _apply_draw_event(self, session_id: str, event: DrawEvent) -> None:
        """Merge remote draw event into session state."""
        session = await self.open_session(session_id)
        async with session.lock:
            session.state["objects"].append(event)
            session.mark_dirty()

    # --------------------------------------------------------------------- #
    # Autosave                                                               #
    # --------------------------------------------------------------------- #

    async def _autosave_loop(self) -> None:
        """Periodically flush dirty sessions to disk."""
        LOGGER.debug("Autosave loop started")
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=AUTOSAVE_DEBOUNCE_SECONDS)
            except asyncio.TimeoutError:
                await self._flush_all()
            except Exception:  # pylint: disable=broad-except
                LOGGER.exception("Autosave loop failed")
        LOGGER.debug("Autosave loop stopped")

    async def _flush_all(self) -> None:
        """Persist every dirty session to disk."""
        flush_coros = [self._write_session_to_disk(s) for s in self._sessions.values() if s.is_dirty]
        if flush_coros:
            LOGGER.debug("Flushing %d whiteboard(s) to disk", len(flush_coros))
            await asyncio.gather(*flush_coros, return_exceptions=True)

    async def _write_session_to_disk(self, session: WhiteboardSession) -> None:
        """Write the session state to its json file atomically."""
        async with session.lock:
            path_tmp = session.file_path.with_suffix(".json.tmp")
            try:
                path_tmp.write_text(json.dumps(session.state, separators=(",", ":")), encoding="utf-8")
                path_tmp.replace(session.file_path)
                session._dirty = False  # pylint: disable=protected-access
                LOGGER.debug("Session %s persisted (%s bytes)", session.session_id, session.file_path.stat().st_size)
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.exception("Failed to persist whiteboard %s: %s", session.session_id, exc)

    # --------------------------------------------------------------------- #
    # Diagnostic helpers                                                     #
    # --------------------------------------------------------------------- #

    def session_state(self, session_id: str) -> Optional[MutableMapping[str, Any]]:
        """Return a copy of the current in-memory state for inspection."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        # intentionally deep-copy for safety
        return json.loads(json.dumps(session.state))


# -----------------------------------------------------------------------------
# Module level helper to quickly spin up a service for scripts / debugging
# -----------------------------------------------------------------------------


async def _demo() -> None:  # pragma: no cover
    """Run a self-contained demo when executed directly."""
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    service = WhiteboardService(event_bus=EventBus(), storage_dir=pathlib.Path("~/flockdesk-wb"))
    await service.start()

    session = await service.open_session("demo")

    # Draw a random stroke
    stroke = Stroke(points=[[0, 0], [1, 1], [2, 2]], color="#FF00FF", author="local")
    await service.add_stroke(session.session_id, stroke)

    await asyncio.sleep(5)  # let autosave run

    await service.shutdown()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_demo())
```