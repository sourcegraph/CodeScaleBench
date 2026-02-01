```python
"""
FlockDesk – Social Workspace Orchestrator
-----------------------------------------

core.ipc.event_bus
~~~~~~~~~~~~~~~~~~

A lightweight, **process-safe** event-bus implementation that acts as the glue
between the independent micro-front-ends that compose the FlockDesk desktop
suite.  The implementation purposefully avoids external dependencies and
relies solely on the standard library (``asyncio``/``multiprocessing``) so that
plugins do not need to vendor additional wheels.

Design goals
============

1. Publish / subscribe with topic-based routing and Unix‐shell wild-card
   matching (``fnmatch``) so that a handler can listen to groups
   (e.g. ``"presence.*"``).

2. Support both synchronous **and** asynchronous handlers without forcing plugin
   authors to learn ``asyncio``.

3. Provide a *request / reply* pattern with correlation-IDs and automatic
   timeout handling—essential for client–server style interactions.

4. Remain safe across processes.  A *broker* process (spawned lazily and managed
   via :pymod:`multiprocessing.managers`) forwards events between producer and
   consumer processes transparently.

5. Offer graceful shutdown semantics so that the application can quit quickly
   even under heavy traffic.

The broker architecture may feel heavyweight for local desktop IPC, but it
guarantees that crashing micro-front-ends cannot bring down the other windows.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import inspect
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from multiprocessing import Event as MpEvent
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Tuple,
    Type,
    Union,
)

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
_log = logging.getLogger("flockdesk.ipc.event_bus")
_log.addHandler(logging.NullHandler())

# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------


class EventBusError(RuntimeError):
    """Base-class for all event-bus exceptions."""


class HandlerTimeout(EventBusError):
    """Raised by ``request`` when no reply arrived in time."""


# -----------------------------------------------------------------------------
# Event primitives
# -----------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Event:
    """
    A single immutable message traveling through the *in-memory* event bus.

    Attributes
    ----------
    topic:
        Hierarchical, ``dot``-separated topic name
        (e.g. ``"presence.updated"``).
    payload:
        Opaque data expected by subscribers.  Must be *pickleable* because the
        broker relies on :pymod:`multiprocessing.Queue`.
    headers:
        Optional free-form metadata such as authentication tokens or tracing
        information.  Header values must again be pickleable.
    event_id:
        Unique identifier for tracing/debugging purposes.
    timestamp:
        Epoch seconds (float) at creation time.
    origin_pid:
        The operating-system process identifier of the sender.  Helpful when the
        same user runs multiple instances of FlockDesk on the same machine.
    """

    topic: str
    payload: Any
    headers: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex, init=False)
    timestamp: float = field(default_factory=time.time, init=False)
    origin_pid: int = field(default_factory=lambda: threading.get_native_id(), init=False)

    def __post_init__(self) -> None:  # noqa: D401
        """Validate that the topic is non-empty."""
        if not self.topic or not isinstance(self.topic, str):
            raise ValueError("Event.topic must be a non-empty string")


# -----------------------------------------------------------------------------
# Subscription Handle
# -----------------------------------------------------------------------------


class _Subscription:
    """
    Lightweight handle that allows clients to stop listening without keeping
    implementation details around.  Instances can also be used as *async*
    context-managers.

    NOTE: Users are **not** expected to instantiate this class directly.
    """

    __slots__ = ("_topic", "_handler", "_bus", "_active")

    def __init__(
        self,
        topic: str,
        handler: "Handler",
        bus: "EventBus",
    ) -> None:
        self._topic = topic
        self._handler = handler
        self._bus = bus
        self._active = True

    async def __aenter__(self) -> "_Subscription":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.unsubscribe()

    def unsubscribe(self) -> None:
        """Remove the handler from the bus."""
        if self._active:
            self._bus._remove_handler(self._topic, self._handler)  # noqa: SLF001
            self._active = False


# -----------------------------------------------------------------------------
# Type aliases
# -----------------------------------------------------------------------------

SyncHandler = Callable[[Event], None]
AsyncHandler = Callable[[Event], Awaitable[None]]
Handler = Union[SyncHandler, AsyncHandler]

# Internal maps
_HandlerMap = Dict[str, List[Handler]]


# -----------------------------------------------------------------------------
# Broker (separate process)
# -----------------------------------------------------------------------------

# Queues are *multiprocessing* queues, therefore pickle based and safe between
# forked/spawned processes.
_InboundQueue = Queue  # alias for readability
_OutboundQueue = Queue


class _Broker(Process):
    """
    Spin-up a separate process that forwards a single *inbound* queue to many
    *outbound* queues (fan-out).

    Each process that calls ``EventBus.connect()`` will create its own outbound
    queue, while the producing bus writes to a single inbound queue.

    Diagram::

        ┌────────────────────┐
        │  client process A  │──┐
        └────────────────────┘  │  ┌────────────┐
                                ├─▶│            │
        ┌────────────────────┐  │  │            │
        │  client process B  │──┼─▶│   BROKER   │──▶ Inbound
        └────────────────────┘  │  │            │    Queue
                                └─▶│            │
                                   └────────────┘

    """

    def __init__(self, inbound: _InboundQueue, shutdown_evt: MpEvent):
        super().__init__(name="FlockDeskEventBroker", daemon=True)
        self._inbound: _InboundQueue = inbound
        self._shutdown_evt: MpEvent = shutdown_evt
        self._outbounds: List[_OutboundQueue] = []

    # ------------------------------------------------------------------#
    # Public API for other processes (via SyncManager)
    # ------------------------------------------------------------------#
    def register_consumer(self) -> _OutboundQueue:
        """
        Called by a client process to obtain a dedicated outbound queue.
        """
        q: _OutboundQueue = Queue()
        self._outbounds.append(q)
        _log.debug("Broker registered new consumer queue (total=%d)", len(self._outbounds))
        return q

    # ------------------------------------------------------------------#
    # Main loop
    # ------------------------------------------------------------------#
    def run(self) -> None:  # noqa: D401
        _log.info("Event-bus broker running (PID=%d)", self.pid)
        try:
            while not self._shutdown_evt.is_set():
                try:
                    evt: Event = self._inbound.get(timeout=0.1)
                except queue.Empty:
                    continue

                # Broadcast
                for q in self._outbounds:
                    try:
                        q.put_nowait(evt)
                    except Exception:  # noqa: BLE001
                        _log.exception("Failed to forward event to queue %s", q)
        finally:
            _log.info("Event-bus broker shutting down (PID=%d)", self.pid)


# -----------------------------------------------------------------------------
# Multiprocessing manager that exposes broker methods
# -----------------------------------------------------------------------------


class _BusManager(BaseManager):
    pass


# have to register after class definition
_BusManager.register("register_consumer", callable=None)  # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# EventBus (public)
# -----------------------------------------------------------------------------
class EventBus:
    """
    Public entry point used by every micro-front-end.

    Processes talk to a shared broker, threads inside the same process share
    exactly one :class:`EventBus` instance (thread-safe singleton).
    """

    _singleton: "EventBus" | None = None
    _singleton_lock = threading.Lock()

    # ------------------------------------------------------------------#
    # Construction helpers
    # ------------------------------------------------------------------#
    @classmethod
    def connect(cls) -> "EventBus":
        """
        Return a *singleton* instance of :class:`EventBus` for the current
        process.  Lazily starts the broker **once** per workstation.
        """
        with cls._singleton_lock:
            if cls._singleton is None:
                cls._singleton = cls._create()
        return cls._singleton

    # ------------------------------------------------------------------#
    # Instance-level lifecycle
    # ------------------------------------------------------------------#
    @classmethod
    def _create(cls) -> "EventBus":
        # 1. Spawn or attach to broker
        inbound: _InboundQueue = Queue()
        shutdown_evt: MpEvent = MpEvent()

        broker = _Broker(inbound, shutdown_evt)
        broker.start()

        # 2. Register via SyncManager so that we can obtain our *private* queue
        manager = _BusManager(
            address=("localhost", 0), authkey=uuid.uuid4().hex.encode("ascii")
        )
        # The manager itself runs in a sub-process—start it:
        manager.start()
        # Now we can register the broker method for remote access
        manager.register("register_consumer", broker.register_consumer)  # type: ignore[arg-type]

        consumer_q: _OutboundQueue = manager.register_consumer()  # type: ignore[attr-defined]

        return cls(
            inbound=inbound,
            outbound=consumer_q,
            shutdown_evt=shutdown_evt,
            broker=broker,
            manager=manager,
        )

    # ------------------------------------------------------------------#
    # dunder
    # ------------------------------------------------------------------#
    def __init__(
        self,
        *,
        inbound: _InboundQueue,
        outbound: _OutboundQueue,
        shutdown_evt: MpEvent,
        broker: _Broker,
        manager: _BusManager,
    ) -> None:
        self._inbound = inbound
        self._outbound = outbound
        self._broker = broker
        self._shutdown_evt = shutdown_evt
        self._manager = manager

        self._handlers: _HandlerMap = {}
        self._loop = asyncio.get_event_loop_policy().get_event_loop()
        self._dispatch_task: asyncio.Task[None] | None = None

        # Protect _handlers as multiple event-loop threads could touch it
        self._h_lock = asyncio.Lock()

        # Synchronize start
        self._ensure_dispatcher()

    # ------------------------------------------------------------------#
    # Public API
    # ------------------------------------------------------------------#
    def subscribe(self, topic: str, handler: Handler) -> _Subscription:
        """
        Register *handler* for the given *topic* pattern.

        Wildcards: Use ``'*'`` to match one segment, ``'**'`` to match
        anything recursively (see :pymod:`fnmatch`).

        Returns
        -------
        _Subscription
            A tiny handle that can be used to *unsubscribe* again.
        """
        if not callable(handler):
            raise TypeError("Handler must be callable")

        _log.debug("Subscribing %s to topic=%s", handler, topic)

        # Keep sync handler as is, wrap non-coroutine functions so that we can
        # `await` them uniformly.
        if not inspect.iscoroutinefunction(handler):

            async def _async_adapter(evt: Event, _h=handler) -> None:
                await self._loop.run_in_executor(None, _h, evt)

            adapted: Handler = _async_adapter
        else:
            adapted = handler  # type: ignore[assignment]

        # Insert
        async def _insert() -> None:
            async with self._h_lock:
                self._handlers.setdefault(topic, []).append(adapted)

        asyncio.run_coroutine_threadsafe(_insert(), self._loop).result()
        return _Subscription(topic, adapted, self)

    def publish(self, topic: str, payload: Any, headers: Optional[Mapping[str, Any]] = None) -> None:
        """
        Fire-and-forget publish.  Safe to call from **any** thread—will enqueue
        the event into the broker’s *inbound* queue.
        """
        evt = Event(topic=topic, payload=payload, headers=headers or {})
        try:
            self._inbound.put_nowait(evt)
        except Exception as exc:  # noqa: BLE001
            _log.exception("Failed to publish event %s: %s", evt, exc)

    async def request(
        self,
        topic: str,
        payload: Any,
        *,
        timeout: float = 5.0,
        headers: Optional[Mapping[str, Any]] = None,
    ) -> Event:
        """
        Send a *request* and await the first reply matching the
        ``correlation_id`` inside *timeout* seconds.

        The server side should look at the ``reply_to`` header and publish the
        answer to that topic including the ``correlation_id``.
        """
        correlation_id = uuid.uuid4().hex
        reply_topic = f"__reply__.{correlation_id}"

        fut: asyncio.Future[Event] = self._loop.create_future()

        # Local handler just completes the future
        async def _reply_handler(evt: Event) -> None:
            fut.set_result(evt)

        subscription = self.subscribe(reply_topic, _reply_handler)

        # Publish *request*
        hdrs: Dict[str, Any] = dict(headers or {})
        hdrs["reply_to"] = reply_topic
        hdrs["correlation_id"] = correlation_id
        self.publish(topic, payload, hdrs)

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise HandlerTimeout(f"Request timed out after {timeout}s") from exc
        finally:
            subscription.unsubscribe()

    # ------------------------------------------------------------------#
    # Shutdown
    # ------------------------------------------------------------------#
    def close(self) -> None:
        """
        Close the bus, stop the background tasks and terminate the broker.

        **Important:** This method should be called exactly *once* at
        application shutdown.
        """
        _log.info("Shutting down EventBus in process=%d", threading.get_native_id())

        self._shutdown_evt.set()

        if self._dispatch_task:
            self._dispatch_task.cancel()

        # Give the broker a moment to finish pending broadcasts
        if self._broker.is_alive():
            self._broker.join(timeout=1.0)
        self._manager.shutdown()

    # ------------------------------------------------------------------#
    # Internal helpers
    # ------------------------------------------------------------------#
    def _remove_handler(self, topic: str, handler: Handler) -> None:
        async def _remove() -> None:
            async with self._h_lock:
                lst = self._handlers.get(topic, [])
                if handler in lst:
                    lst.remove(handler)

        asyncio.run_coroutine_threadsafe(_remove(), self._loop).result()

    def _ensure_dispatcher(self) -> None:
        if self._dispatch_task is None or self._dispatch_task.done():
            self._dispatch_task = self._loop.create_task(self._dispatcher())

    async def _dispatcher(self) -> None:
        """
        Background coroutine that consumes events from the *outbound* queue and
        delivers them to pattern-matched handlers.
        """
        _log.debug("EventBus dispatcher started (thread=%s)", threading.current_thread().name)
        while not self._shutdown_evt.is_set():
            try:
                # Non-blocking read in *executor* because Queue.get is blocking but
                # not async aware.
                evt: Event = await self._loop.run_in_executor(None, self._outbound.get, True, 0.1)
            except queue.Empty:
                continue
            except Exception:  # noqa: BLE001
                _log.exception("Unhandled exception while reading outbound queue")
                continue

            await self._dispatch(evt)

    async def _dispatch(self, evt: Event) -> None:
        """Match patterns and execute handlers concurrently."""
        async with self._h_lock:
            # Flatten into (topic_pattern, handlers[])
            items: List[Tuple[str, List[Handler]]] = list(self._handlers.items())

        coros: List[Awaitable[None]] = []

        for pattern, handlers in items:
            if fnmatch.fnmatchcase(evt.topic, pattern):
                coros.extend(h(evt) for h in handlers)

        if not coros:
            return  # no listeners

        await asyncio.gather(*coros, return_exceptions=False)

    # ------------------------------------------------------------------#
    # Context manager sugar
    # ------------------------------------------------------------------#
    def __enter__(self) -> "EventBus":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()


# -----------------------------------------------------------------------------
# Convenience helpers for library-wide singleton access
# -----------------------------------------------------------------------------

_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """
    Return a process-global :class:`EventBus` instance, creating it on first use.
    """
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = EventBus.connect()
        return _bus


# -----------------------------------------------------------------------------
# Example usage (guarded)
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)

    async def main() -> None:
        bus = get_event_bus()

        # Example async handler
        async def on_presence(evt: Event) -> None:
            print("[async] received", evt.topic, evt.payload)

        # Example sync handler
        def on_any(evt: Event) -> None:
            print("[sync ] saw", evt.topic, evt.payload)

        bus.subscribe("presence.*", on_presence)
        bus.subscribe("**", on_any)

        # Publish from different thread
        def _publisher() -> None:
            b = get_event_bus()
            b.publish("presence.updated", {"user": "alice", "status": "online"})

        threading.Thread(target=_publisher, daemon=True).start()

        await asyncio.sleep(1.0)
        bus.close()

    asyncio.run(main())
```