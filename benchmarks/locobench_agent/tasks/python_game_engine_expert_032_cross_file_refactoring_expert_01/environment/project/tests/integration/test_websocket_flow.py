```python
"""
LedgerQuest Engine – Integration tests for the WebSocket command flow.

These tests exercise the “real” WebSocket entry-point exposed by the LedgerQuest
Engine’s API-Gateway integration (or the sam-local / localstack equivalent that
is spun-up during CI).  The goal is to verify that:

1.  A client can perform the initial CONNECT / AUTHORISE handshake.
2.  Game-loop commands (e.g., MOVE, ATTACK, BUY, SELL) are acknowledged
    and recorded in the authoritative state-store (DynamoDB).
3.  Multi-tenant isolation is respected – messages are never leaked across
    tenant boundaries.
4.  Room / session broadcasts reach all participants in the same “shard”.
5.  The contract stays stable as we iterate on Lambdas behind the socket route.

The file purposefully sticks to the public WebSocket contract and *never*
imports implementation details such as handler Lambdas; this ensures we catch
regressions introduced by infra changes that unit-tests might miss.

To execute locally:

$ LEDGERQUEST_WS_URL="ws://127.0.0.1:9001" \
  AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  pytest -m websocket tests/integration/test_websocket_flow.py

AWS creds are required only because LocalStack/SAM will short-circuit to the
default boto3 credential chain even in fully local mode.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Tuple

import pytest
import websockets
from websockets.client import WebSocketClientProtocol

try:
    import async_timeout  # nicer cancellation semantics than asyncio.wait_for
except ImportError:  # pragma: no cover
    async_timeout = None  # mypy: ignore [assignment]


###############################################################################
# Constants & helpers
###############################################################################

WS_URL: str = os.getenv("LEDGERQUEST_WS_URL", "ws://localhost:9001/socket")
# On CI we usually point to the SAM/LocalStack endpoint.  If the URL is
# unreachable we soft-skip the entire module below.


PING_TIMEOUT_SEC: float = 30.0  # generous as CI can be slow


def _rand_tenant() -> str:
    """Return a cryptographically random tenant id."""
    return f"tenant-{secrets.token_hex(4)}"


def _rand_player() -> str:
    """Return a cryptographically random player id."""
    return f"player-{uuid.uuid4().hex[:8]}"


async def _recv_json(ws: WebSocketClientProtocol) -> Dict[str, Any]:
    """
    Convenience helper: wait for a JSON frame and parse it.

    Raises
    ------
    asyncio.TimeoutError
        If no frame is received within `PING_TIMEOUT_SEC`
    json.JSONDecodeError
        If payload is not valid JSON
    """
    if async_timeout:
        cm = async_timeout.timeout(PING_TIMEOUT_SEC)
    else:  # fallback
        cm = asyncio.timeout(PING_TIMEOUT_SEC)  # Python 3.11+
    async with cm:
        raw = await ws.recv()
        return json.loads(raw)


###############################################################################
# Fixturing – we do NOT want to re-open a socket for every test case; instead
# we use a scoped fixture that yields connections which the tests can borrow.
###############################################################################


@asynccontextmanager
async def _connected_socket(
    tenant_id: str, player_id: str, *,
    auth_token: str | None = None,
) -> AsyncGenerator[WebSocketClientProtocol, None]:
    """
    Context manager that opens an authenticated socket connection and yields it.

    The initial AUTHORISE message is project-specific, but usually contains:
        { "action": "AUTHORISE", "tenant_id": ..., "player_id": ..., "token": ... }
    """
    headers: List[Tuple[str, str]] = []
    if auth_token:
        headers.append(("X-LedgerQuest-Auth", auth_token))

    async with websockets.connect(WS_URL, extra_headers=headers) as ws:
        # Perform the AUTHORISE handshake.
        handshake: Dict[str, Any] = {
            "action": "AUTHORISE",
            "tenant_id": tenant_id,
            "player_id": player_id,
            # The token field is optional in local environments.
            "token": auth_token or "dev-token",
        }
        await ws.send(json.dumps(handshake))

        # Expect either an ACK or an ERR message
        reply = await _recv_json(ws)
        assert reply["type"] in {"ACK", "ERR"}, f"Unexpected handshake reply: {reply}"
        if reply["type"] == "ERR":
            raise RuntimeError(f"Authorisation failed: {reply}")

        yield ws
        # Teardown – best-effort CLOSE (async-context will finally close anyway)
        try:
            await ws.close()
        except Exception:  # pragma: no cover
            pass


@pytest.fixture(scope="function")
async def socket_fixture() -> AsyncGenerator[
    Tuple[str, str, WebSocketClientProtocol], None
]:
    """
    Provide a *fresh* (<tenant_id, player_id, ws>) tuple per test case.

    The fixture guarantees isolation by using random identifiers.
    """
    tenant_id, player_id = _rand_tenant(), _rand_player()
    async with _connected_socket(tenant_id, player_id) as ws:
        yield tenant_id, player_id, ws


###############################################################################
# Dynamic skip if WebSocket server isn't reachable
###############################################################################

async def _probe_ws(url: str) -> bool:
    """Return True if the WebSocket handshake succeeds, else False."""
    try:
        async with websockets.connect(url):
            return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """
    Module-level hook that soft-skips all tests if the WS_URL is dead.

    We perform a single short connection probe to avoid waiting for every
    individual test's connection timeout, which can easily add 10+ seconds per
    test on CI.
    """
    if not items:
        return

    loop = asyncio.get_event_loop()
    is_alive = loop.run_until_complete(_probe_ws(WS_URL))
    if not is_alive:
        skip_marker = pytest.mark.skip(
            reason=f"WebSocket endpoint {WS_URL!r} not reachable."
        )
        for item in items:
            item.add_marker(skip_marker)


###############################################################################
# Tests
###############################################################################


@pytest.mark.websocket
@pytest.mark.asyncio
async def test_command_acknowledged(socket_fixture):
    """
    Sanity check: send a MOVE command and expect a deterministic ACK.

    The ACK must contain:
        - identical correlation_id
        - the applied game tick
        - the canonical server timestamp
    """
    tenant_id, player_id, ws = socket_fixture

    command: Dict[str, Any] = {
        "action": "COMMAND",
        "tenant_id": tenant_id,
        "player_id": player_id,
        "correlation_id": uuid.uuid4().hex,
        "payload": {
            "type": "MOVE",
            "vector": [1, 0, 0],  # move +X
            "speed": 5.5,
        },
    }

    await ws.send(json.dumps(command))
    reply = await _recv_json(ws)

    assert reply["type"] == "ACK", reply
    assert reply["correlation_id"] == command["correlation_id"]
    assert isinstance(reply["tick"], int) and reply["tick"] >= 0
    assert "timestamp" in reply and isinstance(reply["timestamp"], str)


@pytest.mark.websocket
@pytest.mark.asyncio
async def test_tenant_isolation():
    """
    Verify that no messages flow across tenant boundaries.

    We open two sockets under distinct tenants and send a PRIVATE_UPDATE message
    that should only be echoed back to the sender's connection.
    """

    tenant_a, player_a = _rand_tenant(), _rand_player()
    tenant_b, player_b = _rand_tenant(), _rand_player()

    async with _connected_socket(tenant_a, player_a) as ws_a, \
            _connected_socket(tenant_b, player_b) as ws_b:

        msg: Dict[str, Any] = {
            "action": "PRIVATE_UPDATE",
            "tenant_id": tenant_a,
            "player_id": player_a,
            "payload": {"secret": "alpha-only"},
            "correlation_id": uuid.uuid4().hex,
        }
        await ws_a.send(json.dumps(msg))

        # ws_a *must* receive an ACK
        ack = await _recv_json(ws_a)
        assert ack["type"] == "ACK", ack

        # ws_b should remain silent.  We listen for a short timeout window.
        try:
            if async_timeout:
                cm = async_timeout.timeout(2)  # seconds
            else:
                cm = asyncio.timeout(2)  # py3.11+

            async with cm:
                leaked = await ws_b.recv()
                pytest.fail(f"Tenant leakage detected: {leaked}")
        except asyncio.TimeoutError:
            # expected – no leakage
            pass


@pytest.mark.websocket
@pytest.mark.asyncio
async def test_room_broadcast_reaches_all_members():
    """
    Scenario:

    1.  Create a shared game-room under the same tenant.
    2.  Connect N clients and JOIN the same room.
    3.  Have one client publish a CHAT message.
    4.  All clients (including sender) must receive the broadcast *exactly once*.
    """
    tenant_id = _rand_tenant()
    room_id = f"room-{secrets.token_hex(3)}"
    num_clients = 3

    clients: List[Tuple[str, WebSocketClientProtocol]] = []
    # step 1+2: connect all players
    async with asyncio.TaskGroup() as tg:
        for _ in range(num_clients):
            player_id = _rand_player()

            async def _join_room(p_id: str):
                async with _connected_socket(tenant_id, p_id) as ws:
                    await ws.send(json.dumps({
                        "action": "JOIN_ROOM",
                        "tenant_id": tenant_id,
                        "room_id": room_id,
                        "player_id": p_id,
                        "correlation_id": uuid.uuid4().hex,
                    }))
                    # consume ACK
                    await _recv_json(ws)
                    clients.append((p_id, ws))
                    # keep the WS open for rest of TaskGroup lifetime

            tg.create_task(_join_room(player_id))

    # At this point all sockets are open and joined.
    # Pick the first client as sender
    sender_id, sender_ws = clients[0]

    chat_payload = {
        "action": "CHAT",
        "tenant_id": tenant_id,
        "room_id": room_id,
        "player_id": sender_id,
        "correlation_id": uuid.uuid4().hex,
        "payload": {
            "text": "Hello Room!"
        },
    }
    await sender_ws.send(json.dumps(chat_payload))

    # Collect messages from all clients in parallel
    async def _expect_broadcast(_ws: WebSocketClientProtocol) -> Dict[str, Any]:
        msg = await _recv_json(_ws)
        assert msg["type"] == "BROADCAST", msg
        assert msg["payload"]["text"] == "Hello Room!"
        return msg

    results = await asyncio.gather(*[_expect_broadcast(ws) for _, ws in clients])

    # There should be exactly `num_clients` unique delivery IDs
    delivery_ids = {m["delivery_id"] for m in results}
    assert len(delivery_ids) == num_clients


"""
EOF – keep the test self-contained and import-free where possible.  All
assertions are explicit so that failures are obvious when scanning CI logs.
"""
```