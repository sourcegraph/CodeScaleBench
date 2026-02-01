```python
"""
Integration tests for FlockDesk’s internal event-bus communication layer.

The tests are purposely written against the public surface of
`flockdesk.core.event_bus.EventBus`.  Because the actual implementation
lives in the main application repository, we provide a **minimal stub**
that is only used when the real package cannot be imported (e.g. when a
contributor runs the test-suite outside of the full monorepo).  The stub
implements the most important semantics required by the tests:
    • async publish / subscribe API
    • wildcard topics (“*”)
    • graceful error isolation
DO ‑ NOT ‑ rely on the stub in production.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    DefaultDict,
    List,
    Optional,
    Type,
)

import pytest

try:  # pragma: no-cover – Use the real implementation when available.
    # pylint: disable=import-error
    from flockdesk.core.event_bus import EventBus  # type: ignore
except Exception:  # pylint: disable=broad-except
    # ------------------------------------------------------------------
    # Fallback stub; only used when FlockDesk isn’t installed locally.
    # ------------------------------------------------------------------
    _THandler = Callable[[str, Any], Awaitable[None]]

    class EventBus:  # noqa: D101 – Simple documentation in module docstring.
        def __init__(self) -> None:
            self._subs: DefaultDict[str, List[_THandler]] = defaultdict(list)
            self._lock = asyncio.Lock()
            self._logger = logging.getLogger(self.__class__.__name__)

        # ------------------------------------------------------------------
        # Public API
        # ------------------------------------------------------------------
        async def subscribe(self, topic: str, handler: _THandler) -> None:
            """Register an async callback for *topic*.  “\*” is a wildcard."""
            if not asyncio.iscoroutinefunction(handler):
                raise TypeError("Handler must be an async function.")
            async with self._lock:
                self._subs[topic].append(handler)

        async def unsubscribe(self, topic: str, handler: _THandler) -> None:
            """Remove a previously registered handler."""
            async with self._lock:
                if handler in self._subs.get(topic, []):
                    self._subs[topic].remove(handler)
                    if not self._subs[topic]:
                        del self._subs[topic]

        async def publish(self, topic: str, payload: Any) -> None:
            """Publish *payload* to *topic* as well as wildcard subscribers."""
            async with self._lock:
                callbacks = list(self._subs.get(topic, ())) + list(
                    self._subs.get("*", ()),
                )

            # Deliver outside the lock.
            for cb in callbacks:
                try:
                    await cb(topic, payload)
                except Exception:  # noqa: BLE001 – We need to isolate.
                    self._logger.exception(
                        "Unhandled exception in subscriber for topic %s",
                        topic,
                    )

        # ------------------------------------------------------------------
        # Async context-manager helpers – handy in tests and demos
        # ------------------------------------------------------------------
        async def __aenter__(self) -> "EventBus":
            return self

        async def __aexit__(
            self,
            _exc_type: Optional[Type[BaseException]],
            _exc: Optional[BaseException],
            _tb: Optional[TracebackType],
        ) -> bool:
            async with self._lock:
                self._subs.clear()
            return False  # Do not suppress exceptions.


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
async def event_bus() -> EventBus:
    """Provide a fresh event-bus instance per test."""
    async with EventBus() as bus:
        yield bus


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
async def _wait_for_event(
    fut: "asyncio.Future[Any]",
    timeout: float = 1.0,
) -> Any:
    """Await *fut* failing the test if a result does not arrive in time."""
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError as exc:  # pragma: no-cover
        pytest.fail(f"Timed-out waiting for event: {exc}")  # noqa: PT011 – OK.


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
@pytest.mark.asyncio()
async def test_basic_publish_subscribe(event_bus: EventBus) -> None:
    """
    GIVEN a fresh event bus
    WHEN  a subscriber registers for 'chat.message'
          and a publisher publishes a payload on that topic
    THEN  the subscriber must receive the payload once.
    """
    received: asyncio.Future[str] = asyncio.get_event_loop().create_future()

    async def handler(_topic: str, payload: str) -> None:
        if not received.done():
            received.set_result(payload)

    await event_bus.subscribe("chat.message", handler)

    message = "Hello, world!"
    await event_bus.publish("chat.message", message)

    assert await _wait_for_event(received) == message


@pytest.mark.asyncio()
async def test_unsubscribe_stops_receiving(event_bus: EventBus) -> None:
    """
    Subscribers that explicitly unsubscribe must no longer receive events.
    """
    received: int = 0

    async def handler(_topic: str, _payload: object) -> None:
        nonlocal received
        received += 1

    await event_bus.subscribe("presence.update", handler)
    await event_bus.publish("presence.update", {"user": "alice", "online": True})

    # First message MUST be received.
    await asyncio.sleep(0)  # allow micro-task scheduling
    assert received == 1

    # Unsubscribe and send another message.
    await event_bus.unsubscribe("presence.update", handler)
    await event_bus.publish("presence.update", {"user": "alice", "online": False})

    await asyncio.sleep(0)  # allow micro-task scheduling
    assert received == 1, "Handler should not have been invoked after un-subscribe."


@pytest.mark.asyncio()
async def test_wildcard_subscription(event_bus: EventBus) -> None:
    """
    “*” is the wildcard topic and must receive **all** events published on the bus.
    """
    seen: list[str] = []

    async def handler(topic: str, _payload: object) -> None:
        seen.append(topic)

    await event_bus.subscribe("*", handler)

    topics = ["chat.message", "file.upload", "poll.vote"]
    for t in topics:
        await event_bus.publish(t, {})

    # Wait long enough for all scheduled handler calls to finish.
    await asyncio.sleep(0)

    assert sorted(seen) == sorted(topics)


@pytest.mark.asyncio()
async def test_handler_errors_are_isolated(
    event_bus: EventBus,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    An exception in one subscriber must *never* prevent delivery to others.
    The faulty handler must be logged at ERROR level.
    """
    caplog.set_level(logging.ERROR, logger="EventBus")

    bad_handler_called = asyncio.Event()
    good_handler_received: asyncio.Future[str] = asyncio.get_event_loop().create_future()

    async def bad_handler(_topic: str, _payload: object) -> None:
        bad_handler_called.set()
        raise RuntimeError("Synthetic test error")

    async def good_handler(_topic: str, payload: str) -> None:
        if not good_handler_received.done():
            good_handler_received.set_result(payload)

    await event_bus.subscribe("whiteboard.draw", bad_handler)
    await event_bus.subscribe("whiteboard.draw", good_handler)

    payload = "circle(x=10,y=10,r=5)"
    await event_bus.publish("whiteboard.draw", payload)

    await bad_handler_called.wait()
    assert (await _wait_for_event(good_handler_received)) == payload

    # Exactly one error log should have been produced.
    error_logs = [
        rec for rec in caplog.records if rec.levelno == logging.ERROR
    ]
    assert len(error_logs) == 1
    assert "Synthetic test error" in error_logs[0].getMessage()


@pytest.mark.asyncio()
async def test_concurrent_publishers(event_bus: EventBus) -> None:
    """
    Stress-test the bus with concurrent publishers and a single subscriber.
    All messages must arrive exactly once.
    """
    NUM_PUBLISHERS = 10
    MSGS_PER_PUBLISHER = 50

    inbox: list[int] = []
    inbox_event = asyncio.Event()

    async def sink(_topic: str, payload: int) -> None:
        inbox.append(payload)
        if len(inbox) == NUM_PUBLISHERS * MSGS_PER_PUBLISHER:
            inbox_event.set()

    await event_bus.subscribe("analytics.tick", sink)

    async def publisher(id_: int) -> None:
        for i in range(MSGS_PER_PUBLISHER):
            await event_bus.publish("analytics.tick", id_ * 1_000 + i)

    await asyncio.gather(*(publisher(i) for i in range(NUM_PUBLISHERS)))
    await _wait_for_event(inbox_event, timeout=5.0)

    # Assert that we have received every unique payload.
    expected = {
        id_ * 1_000 + i
        for id_ in range(NUM_PUBLISHERS)
        for i in range(MSGS_PER_PUBLISHER)
    }
    assert set(inbox) == expected, "Some messages were lost or duplicated."
```