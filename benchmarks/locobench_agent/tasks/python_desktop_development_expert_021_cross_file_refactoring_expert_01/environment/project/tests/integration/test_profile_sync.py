```python
"""
tests/integration/test_profile_sync.py

End-to-end integration tests covering the profile-synchronisation layer that keeps
user preferences in-sync between micro-front-ends and the cloud profile service.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import pytest


# --------------------------------------------------------------------------- #
#                             ––– Test Doubles –––                            #
# --------------------------------------------------------------------------- #
class NetworkError(ConnectionError):
    """Raised when the remote profile gateway is unreachable."""


class FakeEventBus:
    """
    *Extremely* lightweight pub/sub bus for integration testing.

    It behaves like the in-process event bus the real application would use,
    but is limited to fan-out broadcasts with no routing / filtering logic.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}

    def publish(self, topic: str, payload: Any) -> None:
        """
        Dispatch an event to all current subscribers.  Publishing is synchronous
        but the individual consumers receive the events asynchronously via the
        returned queue from :py:meth:`listen`.
        """
        if topic not in self._subscribers:  # pragma: no cover
            return  # No one cares.

        for queue in self._subscribers[topic]:
            # Use put_nowait so a slow consumer does *not* block the publisher.
            queue.put_nowait(payload)

    def listen(self, topic: str) -> "asyncio.Queue[Any]":
        """
        Subscribe to a topic and receive a dedicated queue that will carry all
        future events for that topic.
        """
        q: "asyncio.Queue[Any]" = asyncio.Queue()
        self._subscribers.setdefault(topic, []).append(q)
        return q


class FakeRemoteGateway:
    """
    In-memory substitute of the cloud-backed profile service.

    It emulates three main responsibilities:
      1. Keeping the canonical *remote* profile for each user.
      2. Detecting network availability and raising :class:`NetworkError`
         accordingly.
      3. Broadcasting updates from *any* client to *all* clients subscribed for
         that user.
    """

    def __init__(self) -> None:
        self._remote_profiles: Dict[str, Dict[str, Any]] = {}
        self._channels: Dict[str, List[asyncio.Queue]] = {}
        self.offline: bool = False

    # --------------------------------------------------------------------- #
    #                        ––– Public API (client) –––                    #
    # --------------------------------------------------------------------- #
    async def push_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        """Persist the profile to the 'cloud' and broadcast the change."""
        self._ensure_online()

        # Use a *monotonic* timestamp as a version indicator (LWW conflict
        # resolution).
        merged = dict(profile)
        merged["_last_modified"] = time.monotonic()
        self._remote_profiles[user_id] = merged

        # Fan-out to listeners (non-blocking).
        for q in self._channels.get(user_id, []):
            q.put_nowait(merged)

    def subscribe(self, user_id: str) -> "asyncio.Queue[Dict[str, Any]]":
        """
        Subscribe to server-side changes for *user_id* and receive a queue that
        is fed whenever **another** client pushes a change.
        """
        q: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self._channels.setdefault(user_id, []).append(q)
        return q

    def snapshot(self, user_id: str) -> Dict[str, Any]:
        """Return the server-side profile for assertions."""
        return self._remote_profiles.get(user_id, {}).copy()

    # ------------------------------------------------------------------ #
    #                           ––– Internals –––                        #
    # ------------------------------------------------------------------ #
    def _ensure_online(self) -> None:
        if self.offline:
            raise NetworkError("Remote gateway is offline")


# --------------------------------------------------------------------------- #
#                       ––– System-Under-Test: Sync Service –––               #
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ProfileSyncService:
    """
    Minimal, yet realistic, profile-synchronisation service.

    A real implementation would be heavily event-driven, but for the purpose of
    integration testing we drive the important mechanics manually.
    """

    user_id: str
    event_bus: FakeEventBus
    gateway: FakeRemoteGateway

    local_profile: Dict[str, Any] = field(default_factory=dict)

    # Internal run-state
    _unsynced_changes: bool = field(default=False, init=False)
    _running: bool = field(default=False, init=False)
    _remote_listener_task: Optional[asyncio.Task] = field(default=None, init=False)

    # ------------------------------- Life-Cycle ----------------------------- #
    async def start(self) -> None:
        """Kick-off background tasks (remote listener)."""
        if self._running:  # pragma: no cover
            return
        self._running = True
        self._remote_listener_task = asyncio.create_task(self._listen_remote())

    async def stop(self) -> None:
        """Gracefully shut down the background listener."""
        if not self._running:  # pragma: no cover
            return

        self._running = False
        if self._remote_listener_task:
            self._remote_listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._remote_listener_task

    # ---------------------------- Public Interface ------------------------- #
    def update_local(self, changes: Dict[str, Any]) -> None:
        """
        Called by the UI layer whenever the user modifies their preferences.
        """
        self.local_profile.update(changes)
        self._unsynced_changes = True

        # Immediately broadcast to local components.
        self.event_bus.publish(
            f"profile.{self.user_id}.updated", dict(self.local_profile)
        )

        # Fire-and-forget the sync attempt.
        asyncio.create_task(self._attempt_sync())

    async def on_network_restored(self) -> None:
        """
        The connectivity monitor can poke this method once the network becomes
        available again, so we can flush pending writes.
        """
        await self._attempt_sync()

    # ------------------------------- Internals ----------------------------- #
    async def _attempt_sync(self) -> None:
        """Try to push local changes to the remote gateway."""
        if not self._unsynced_changes:
            return

        try:
            await self.gateway.push_profile(self.user_id, dict(self.local_profile))
            self._unsynced_changes = False
        except NetworkError:
            # Silently keep the dirty flag so we know to retry later.
            pass

    async def _listen_remote(self) -> None:
        """
        Background coroutine that receives server-side updates that originated
        from *other* clients.
        """
        q = self.gateway.subscribe(self.user_id)

        while self._running:
            remote_profile = await q.get()

            # We only care when the incoming update carries a newer timestamp.
            local_ts = self.local_profile.get("_last_modified", -1)
            remote_ts = remote_profile["_last_modified"]
            if remote_ts <= local_ts:
                continue  # Local copy is newer or identical.

            self.local_profile = dict(remote_profile)
            self.event_bus.publish(
                f"profile.{self.user_id}.updated", dict(self.local_profile)
            )


# --------------------------------------------------------------------------- #
#                                ––– Helpers –––                              #
# --------------------------------------------------------------------------- #
async def wait_for(
    queue: "asyncio.Queue[Any]",
    *,
    predicate: Callable[[Any], bool] | None = None,
    timeout: float = 2.0,
) -> Any:
    """
    Utility that awaits until `predicate(item)` is *True* for an element read
    from *queue*.  If *predicate* is :pydata:`None`, the call returns the first
    element received.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    predicate = predicate or (lambda _x: True)

    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("Timeout while waiting for queue event")

        item = await asyncio.wait_for(queue.get(), timeout=remaining)
        if predicate(item):
            return item


# --------------------------------------------------------------------------- #
#                            ––– Integration Tests –––                        #
# --------------------------------------------------------------------------- #
@pytest.fixture()
def event_bus() -> FakeEventBus:
    return FakeEventBus()


@pytest.fixture()
def remote_gateway() -> FakeRemoteGateway:
    return FakeRemoteGateway()


@pytest.fixture()
async def services(event_bus: FakeEventBus, remote_gateway: FakeRemoteGateway):
    """
    Spin-up *two* sync services to simulate two independent micro-front-ends
    running in different processes.
    """
    svc_a = ProfileSyncService("alice", event_bus, remote_gateway)
    svc_b = ProfileSyncService("alice", event_bus, remote_gateway)

    await asyncio.gather(svc_a.start(), svc_b.start())
    yield svc_a, svc_b

    await asyncio.gather(svc_a.stop(), svc_b.stop())


@pytest.mark.asyncio
async def test_local_update_propagates_to_remote_and_peers(
    services, event_bus: FakeEventBus, remote_gateway: FakeRemoteGateway
):
    """
    When one service updates the local profile, the change should:

      1. Appear on the remote gateway.
      2. Be broadcast on the local event bus.
      3. Update *other* micro-front-ends listening for that user.
    """
    svc_a, svc_b = services
    bus_q = event_bus.listen("profile.alice.updated")

    # Act – change a preference on service A.
    svc_a.update_local({"theme": "dark"})

    # 1) Wait for the bus broadcast and verify the payload.
    msg = await wait_for(bus_q, predicate=lambda m: m.get("theme") == "dark")
    assert msg["theme"] == "dark"

    # 2) Eventually, remote profile should be in sync.
    await asyncio.sleep(0.1)  # Allow async push to complete.
    assert remote_gateway.snapshot("alice")["theme"] == "dark"

    # 3) The peer (service B) must have updated its local copy.
    assert svc_b.local_profile["theme"] == "dark"


@pytest.mark.asyncio
async def test_last_write_wins_conflict_resolution(
    services, remote_gateway: FakeRemoteGateway
):
    """
    When concurrent updates occur, the service implementing a *later* change
    (higher `_last_modified`) must win the conflict.
    """
    svc_a, svc_b = services

    # Simulate near-simultaneous changes.
    svc_a.update_local({"language": "en"})
    await asyncio.sleep(0.05)
    svc_b.update_local({"language": "fr"})  # <- later write wins.

    # Give the sync loop a moment to converge.
    await asyncio.sleep(0.2)

    snap = remote_gateway.snapshot("alice")
    assert snap["language"] == "fr"
    assert svc_a.local_profile["language"] == svc_b.local_profile["language"] == "fr"


@pytest.mark.asyncio
async def test_offline_changes_are_synced_when_network_recovers(
    services, remote_gateway: FakeRemoteGateway
):
    """
    Offline edits must be queued locally and flushed to the server once
    connectivity is restored.
    """
    svc_a, _ = services

    # Simulate loss of connectivity *before* the update.
    remote_gateway.offline = True
    svc_a.update_local({"showAvatars": False})

    # Wait briefly to ensure the failed attempt has happened.
    await asyncio.sleep(0.1)
    assert remote_gateway.snapshot("alice") == {}  # Nothing on the server.

    # Bring the network back and trigger a retry.
    remote_gateway.offline = False
    await svc_a.on_network_restored()

    # The push should succeed shortly after.
    await asyncio.sleep(0.1)
    assert remote_gateway.snapshot("alice")["showAvatars"] is False
    assert svc_a._unsynced_changes is False
```