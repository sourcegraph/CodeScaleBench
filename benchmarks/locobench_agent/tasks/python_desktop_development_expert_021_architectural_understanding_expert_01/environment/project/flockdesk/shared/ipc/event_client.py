```python
"""
flockdesk.shared.ipc.event_client
=================================

As part of FlockDesk’s event-driven architecture, every micro-frontend talks
to the internal event-bus.  The `EventClient` below is a **thin, resilient,
and high-level** wrapper around a websocket connection that supports:

    • Publish / Subscribe topics (fan-out semantics)  
    • Fire-and-forget events as well as request / response (RPC-style)  
    • Automatic exponential back-off + jitter reconnects  
    • Thread-safe, synchronous API for non-async callers  
    • JSON framing with basic validation & schema versioning  
    • Graceful shutdown & cancellation propagation  

The implementation purposefully avoids leaking the underlying networking
stack and can be swapped for a different transport (e.g., ZeroMQ, gRPC)
by replacing `_BaseTransport`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from threading import Event as ThreadEvent, Thread
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
)

# External dependency.  Keep import local to raise helpful error if absent.
try:
    import websockets
    from websockets.exceptions import ConnectionClosed  # noqa: WPS433
except ModuleNotFoundError as exc:  # pragma: no cover
    raise RuntimeError(
        "EventClient requires the 'websockets' library. "
        "Install via `pip install websockets`."
    ) from exc


log = logging.getLogger(__name__)
SCHEMA_VERSION = 1
DEFAULT_ENDPOINT = "ws://127.0.0.1:8765/events"

JsonPayload = Mapping[str, Any]
Callback = Callable[[JsonPayload], Awaitable[None]]


###############################################################################
# Utility helpers
###############################################################################
def _json_dumps(obj: JsonPayload) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _json_loads(data: str) -> JsonPayload:
    return json.loads(data)


def _gen_msg_id() -> str:
    return uuid.uuid4().hex


###############################################################################
# Transport Abstraction
###############################################################################


class _BaseTransport:  # pragma: no cover – acts as an interface
    """
    Abstract websocket-like transport used by EventClient.
    """

    async def connect(self) -> None: ...  # noqa: D401, WPS428

    async def disconnect(self) -> None: ...  # noqa: D401, WPS428

    async def send(self, data: str) -> None: ...  # noqa: D401, WPS428

    async def recv(self) -> str: ...  # noqa: D401, WPS428


class _WebSocketTransport(_BaseTransport):
    """
    Concrete transport implemented via the `websockets` package.
    """

    def __init__(self, uri: str, ssl: Optional[Any] = None) -> None:
        self._uri = uri
        self._ssl = ssl
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def connect(self) -> None:
        log.debug("Connecting to %s", self._uri)
        self._ws = await websockets.connect(self._uri, ssl=self._ssl)

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            log.debug("Disconnected from %s", self._uri)

    async def send(self, data: str) -> None:
        if not self._ws or self._ws.closed:
            raise ConnectionClosed(1006, "socket not connected")
        await self._ws.send(data)

    async def recv(self) -> str:
        if not self._ws or self._ws.closed:
            raise ConnectionClosed(1006, "socket not connected")
        return await self._ws.recv()


###############################################################################
# Public API
###############################################################################


@dataclass
class Event:
    """
    Wrapper around an incoming event message.
    """

    id: str
    topic: str
    payload: JsonPayload
    sender: str
    timestamp: float
    reply_to: Optional[str] = None
    schema: int = SCHEMA_VERSION

    @classmethod
    def from_raw(cls, data: str) -> "Event":
        msg: MutableMapping[str, Any] = _json_loads(data)
        return cls(
            id=msg["id"],
            topic=msg["topic"],
            payload=msg["payload"],
            sender=msg["sender"],
            timestamp=msg["ts"],
            reply_to=msg.get("reply_to"),
            schema=msg.get("schema", 1),
        )

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    def is_request(self) -> bool:
        return self.reply_to is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "payload": self.payload,
            "sender": self.sender,
            "ts": self.timestamp,
            "reply_to": self.reply_to,
            "schema": self.schema,
        }


class EventClient:
    """
    High-level, asyncio-first EventBus client.

    Typical usage
    -------------
    >>> async with EventClient("ws://127.0.0.1:8765/events") as bus:
    ...     await bus.subscribe("chat.message", lambda e: print(e.payload))
    ...     await bus.publish("chat.message", {"text": "hello world"})
    """

    # Default jitter/back-off: 0.5s -> 16s.
    _RETRY_BACKOFF: Sequence[float] = (0.5, 1, 2, 4, 8, 16)

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        sender_id: Optional[str] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._transport: _BaseTransport = _WebSocketTransport(endpoint)
        self._sender = sender_id or uuid.uuid4().hex[:8]  # shorten for GUI overlay
        self._stop_event = asyncio.Event()
        self._callbacks: Dict[str, Tuple[Callback, bool]] = {}
        self._pending_rpcs: Dict[str, asyncio.Future[Any]] = {}
        self._runner_task: Optional["asyncio.Task[None]"] = None

    # --------------------------------------------------------------------- #
    # Context-manager helpers
    # --------------------------------------------------------------------- #
    async def __aenter__(self) -> "EventClient":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        await self.stop()
        # Propagate exception (if any) to caller.
        return None

    # --------------------------------------------------------------------- #
    # Lifecycle
    # --------------------------------------------------------------------- #
    async def start(self) -> None:
        """
        Open the connection and spawn the listener task.

        Safe to call multiple times.
        """
        if self._runner_task:
            return

        await self._connect_with_retry()
        self._runner_task = self._loop.create_task(self._listener(), name="eventbus-listener")
        log.info("EventClient %s connected", self._sender)

    async def stop(self) -> None:
        """
        Gracefully terminate the connection.
        """
        self._stop_event.set()
        if self._runner_task:
            await self._runner_task
        with contextlib.suppress(Exception):
            await self._transport.disconnect()
        log.info("EventClient %s stopped", self._sender)

    # --------------------------------------------------------------------- #
    # Publish / Subscribe
    # --------------------------------------------------------------------- #
    async def publish(self, topic: str, payload: JsonPayload, *, reply_to: Optional[str] = None) -> str:
        """
        Fire-and-forget event.

        Returns the autogenerated message id.
        """
        msg_id = _gen_msg_id()
        envelope = {
            "id": msg_id,
            "topic": topic,
            "payload": payload,
            "sender": self._sender,
            "ts": time.time(),
            "reply_to": reply_to,
            "schema": SCHEMA_VERSION,
        }
        await self._transport.send(_json_dumps(envelope))
        log.debug("Published %s -> %s", topic, msg_id)
        return msg_id

    async def request(
        self,
        topic: str,
        payload: JsonPayload,
        *,
        timeout: float = 10.0,
    ) -> JsonPayload:
        """
        RPC-style request that waits for a reply.

        Returns the reply payload or raises `TimeoutError`.
        """
        future: "asyncio.Future[JsonPayload]" = self._loop.create_future()
        correlation_id = self._gen_correlation_id()
        self._pending_rpcs[correlation_id] = future

        await self.publish(topic, payload, reply_to=correlation_id)

        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            # Clean up in all cases.
            self._pending_rpcs.pop(correlation_id, None)

    async def subscribe(
        self,
        topic: str,
        callback: Callback,
        *,
        once: bool = False,
    ) -> None:
        """
        Register a coroutine callback for a specific topic.

        Args:
            topic:     The topic / routing-key
            callback:  Coroutine taking a `Event` instance.
            once:      If True, callback is removed after first invocation.
        """
        if not asyncio.iscoroutinefunction(callback):
            raise TypeError("callback must be an async function")

        if topic in self._callbacks:
            log.warning("Overwriting existing subscription for %s", topic)
        self._callbacks[topic] = (callback, once)
        log.debug("Subscribed to %s (once=%s)", topic, once)

    async def unsubscribe(self, topic: str) -> None:
        """
        Remove previously registered subscription.
        """
        self._callbacks.pop(topic, None)
        log.debug("Unsubscribed from %s", topic)

    # --------------------------------------------------------------------- #
    # Internal
    # --------------------------------------------------------------------- #
    @staticmethod
    def _gen_correlation_id() -> str:
        return f"rpc-{_gen_msg_id()}"

    async def _connect_with_retry(self) -> None:
        """
        Attempt to connect with exponential back-off.
        """
        for idx, delay in enumerate(self._RETRY_BACKOFF):
            try:
                await self._transport.connect()
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("Connection attempt %d failed: %s", idx + 1, exc, exc_info=exc)
                jitter = random.uniform(0, delay)
                await asyncio.sleep(delay + jitter)
        raise ConnectionError("Failed to connect to event-bus after multiple attempts.")

    async def _listener(self) -> None:
        """
        Background coroutine that receives messages and dispatches them.
        """
        while not self._stop_event.is_set():
            try:
                raw = await self._transport.recv()
                event = Event.from_raw(raw)
            except ConnectionClosed:
                log.warning("Connection lost. Trying to reconnect…")
                await self._connect_with_retry()
                continue
            except Exception:  # noqa: BLE001
                log.exception("Failed to parse incoming message")
                continue

            # Handle RPC responses.
            if event.topic == "_rpc.reply" and event.reply_to:
                future = self._pending_rpcs.get(event.reply_to)
                if future and not future.done():
                    future.set_result(event.payload)
                continue

            # Dispatch to subscribers.
            cb_tuple = self._callbacks.get(event.topic)
            if cb_tuple:
                callback, once = cb_tuple
                try:
                    await callback(event)
                except Exception:  # noqa: BLE001
                    log.exception("Subscriber callback raised")
                if once:
                    self._callbacks.pop(event.topic, None)

    # --------------------------------------------------------------------- #
    # Convenience synchronous wrapper
    # --------------------------------------------------------------------- #
    def sync(self, *, shutdown_timeout: float = 5.0) -> "SyncEventClient":
        """
        Return a thread-based, synchronous proxy around this EventClient.

        Useful from Qt slots or other blocking contexts.
        """
        return SyncEventClient(self, shutdown_timeout=shutdown_timeout)


###############################################################################
# Synchronous wrapper
###############################################################################


class SyncEventClient:
    """
    Thread-safe, blocking facade around :class:`EventClient`.

    Example
    -------
    >>> bus = EventClient().sync()
    >>> bus.start()
    >>> bus.publish("presence.ping", {"user": "alice"})
    >>> bus.stop()
    """

    def __init__(self, async_client: EventClient, *, shutdown_timeout: float = 5.0) -> None:
        self._client = async_client
        self._shutdown_timeout = shutdown_timeout
        self._thread: Optional[Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = ThreadEvent()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = Thread(target=self._run_loop, name="eventbus-sync", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)

    def stop(self) -> None:
        if not self._loop:
            return
        fut = asyncio.run_coroutine_threadsafe(self._client.stop(), self._loop)
        fut.result(timeout=self._shutdown_timeout)

    def publish(self, topic: str, payload: JsonPayload) -> str:
        self._ensure_running()
        fut = asyncio.run_coroutine_threadsafe(self._client.publish(topic, payload), self._loop)
        return fut.result()

    def request(self, topic: str, payload: JsonPayload, *, timeout: float = 10.0) -> JsonPayload:
        self._ensure_running()
        fut = asyncio.run_coroutine_threadsafe(self._client.request(topic, payload, timeout=timeout), self._loop)
        return fut.result(timeout=timeout + 1)

    def subscribe(
        self,
        topic: str,
        callback: Callable[[JsonPayload], None],
        *,
        once: bool = False,
    ) -> None:
        """
        Register a blocking callback; executed in the I/O thread.

        Note: callback should be lightweight — heavy-weight work can be pushed
        back to another executor to avoid stalling the event loop.
        """

        async def _async_wrapper(event: Event) -> None:
            try:
                callback(event.payload)
            except Exception:  # noqa: BLE001
                log.exception("Synchronous subscriber raised")

        self._ensure_running()
        asyncio.run_coroutine_threadsafe(
            self._client.subscribe(topic, _async_wrapper, once=once),
            self._loop,
        ).result()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._client.start())
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def _ensure_running(self) -> None:
        if not self._thread or not self._thread.is_alive():
            raise RuntimeError("SyncEventClient has not been started.")


###############################################################################
# CLI test driver (optional)
###############################################################################
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    async def _main() -> None:
        async with EventClient() as bus:

            async def _printer(event: Event) -> None:  # simple subscriber
                log.info("RECV %s %s", event.topic, event.payload)

            await bus.subscribe("test.ping", _printer)

            # Fire & forget
            await bus.publish("test.ping", {"hello": "world"})

            # RPC example
            try:
                response = await bus.request("echo", {"msg": "Please reply!"})
                log.info("RPC response: %s", response)
            except TimeoutError:
                log.warning("RPC timed out")

            await asyncio.sleep(2)  # give some time for messages to flow

    asyncio.run(_main())
```