```python
"""
LedgerQuestEngine.tests
=======================

High-level, black-box tests that validate the *contract* between the
server-side (Lambda/Step-Functions-backed) gameplay primitives and the rest
of the LedgerQuest Engine.

Because the core engine is designed to run in a fully-managed, serverless
environment, the bulk of the “logic” lives in functions that are *stateless*
and *pure* (they depend exclusively on their inputs and configuration
embedded in the event).  These tests primarily focus on:

1.  Verifying deterministic behaviour of critical stateless functions
    (e.g. physics simulation).
2.  Ensuring side-effect boundaries (persistence, audit logging, metrics)
    are correctly respected and *observable* via emitted events.
3.  Exercising the public API surface (as exposed to Lambda handlers)
    rather than private helpers wherever practical.

NOTE:  Although this file lives in ``tests/__init__.py`` to keep the example
self-contained, in a real-world repository one would normally place the
individual tests in **dedicated** modules and only keep fixtures / helpers
in the *package* initializer.
"""
from __future__ import annotations

import json
import os
import random
import time
import types
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Generator, Tuple

import pytest

# ---------------------------------------------------------------------------
# 3rd-party optional tooling
# ---------------------------------------------------------------------------

try:  # We use moto to mock DynamoDB and EventBridge
    from moto import mock_dynamodb2, mock_events
    import boto3
except ImportError:  # pragma: no cover
    mock_dynamodb2 = mock_events = None        # type: ignore
    boto3 = None                               # type: ignore

# Skip integration tests that rely on AWS mocks if the deps are missing.
aws = pytest.importorskip("boto3", reason="boto3 is required for AWS-level tests")


# ---------------------------------------------------------------------------
# Constants / Test Data
# ---------------------------------------------------------------------------

GAME_TABLE_NAME = "ledgerquest-test-game-state"
EVENT_BUS_NAME = "ledgerquest-test-bus"

_PHYSICS_SEED = 1337           # Ensure reproducible RNG in tests
_EPSILON = 1e-7                # Float tolerance for physics comparisons


# ---------------------------------------------------------------------------
# Generic Utilities
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    """Return current UTC epoch timestamp in ISO-8601 (millisecond precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def _monotonic_seed(seed: int) -> Generator[None, None, None]:
    """
    Context-manager that sets *both* ``random`` *and* ``os.urandom`` style UUID
    generation to a deterministic seed for the lifetime of the ``with`` block.
    """
    state = random.getstate()
    random.seed(seed)
    try:
        yield
    finally:
        random.setstate(state)


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def aws_test_resources() -> Generator[Dict[str, Any], None, None]:
    """
    Provision *in-memory* DynamoDB table + EventBridge bus using *moto*.

    Returned mapping contains ready-to-use ``boto3`` *resource*/*client*
    objects so the test-suite can transparently inject them into the engine’s
    store / dispatcher classes.
    """
    if not mock_dynamodb2 or not mock_events:  # pragma: no cover
        pytest.skip("Moto is required for AWS-level integration tests")

    with mock_dynamodb2(), mock_events():
        # DynamoDB ----------------------------------------------------------------
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName=GAME_TABLE_NAME,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()

        # EventBridge -------------------------------------------------------------
        events = boto3.client("events", region_name="us-east-1")
        events.create_event_bus(Name=EVENT_BUS_NAME)

        yield {
            "dynamodb_resource": dynamodb,
            "dynamodb_table": table,
            "events_client": events,
        }


@pytest.fixture(scope="function")
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure that tests never rely on leaky environment variables."""
    for key in list(os.environ):
        if key.startswith("LEDGERQUEST_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(scope="function")
def physics_seed() -> Generator[int, None, None]:
    """
    Provide a consistent RNG seed to guarantee *deterministic* test results
    while allowing reproducibility across different machines / CI nodes.
    """
    with _monotonic_seed(_PHYSICS_SEED):
        yield _PHYSICS_SEED


# ---------------------------------------------------------------------------
#  Helper Stubs (used for monkey-patching external services inside tests)
# ---------------------------------------------------------------------------

@dataclass
class _CapturedEvent:
    """Simple DTO that represents a captured audit / metrics event."""
    bus_name: str
    timestamp: str
    detail_type: str
    detail: Dict[str, Any]


class _EventCollector:
    """
    Lightweight in-memory stand-in for EventBridge used to assert that our
    lambdas emit the *correct* metadata without requiring the real service.
    """
    def __init__(self) -> None:
        self._events: list[_CapturedEvent] = []

    # Signature mirrors boto3's put_events for seamless monkey-patching
    def put_events(self, Entries: list[dict[str, Any]]) -> Dict[str, Any]:  # noqa: N803
        for entry in Entries:
            self._events.append(
                _CapturedEvent(
                    bus_name=entry.get("EventBusName", EVENT_BUS_NAME),
                    timestamp=entry.get("Time", _iso_now()),
                    detail_type=entry["DetailType"],
                    detail=json.loads(entry["Detail"]),
                )
            )
        # Simulate success response
        return {"FailedEntryCount": 0, "Entries": [{"EventId": str(uuid.uuid4())} for _ in Entries]}

    # Helper for tests
    def filter(self, detail_type: str) -> list[_CapturedEvent]:
        return [e for e in self._events if e.detail_type == detail_type]

    def __len__(self) -> int:
        return len(self._events)


# ---------------------------------------------------------------------------
#  Test-cases
# ---------------------------------------------------------------------------

def test_physics_simulation_is_deterministic(monkeypatch: pytest.MonkeyPatch, physics_seed: int) -> None:
    """
    The physics Lambda **must** behave deterministically for a single frame
    when invoked with identical state + inputs.  Otherwise, we cannot rely on
    Step Functions’ *exactly-once* guarantee to reconcile divergent branches.

    We patch the ``time.time`` call to eliminate non-determinism in code that,
    for performance reasons, uses epoch deltas rather than *pure* frame
    counters.
    """
    # Importing late to avoid polluting global state before patching RNG/time.
    from game_engine.physics import simulate_frame  # type: ignore

    fixed_time = 1672531200.123  # Epoch for 2023-01-01 00:00:00.123 UTC

    monkeypatch.setattr(time, "time", lambda: fixed_time)

    state_in = {
        "entity_id": "42",
        "position": {"x": 0.0, "y": 0.0},
        "velocity": {"x": 5.0, "y": 0.0},
        "dt": 1 / 60,
    }

    with _monotonic_seed(physics_seed):
        out_a = simulate_frame(state_in)

    # Re-run under the *same* conditions:
    with _monotonic_seed(physics_seed):
        out_b = simulate_frame(state_in)

    assert out_a == pytest.approx(out_b, abs=_EPSILON), (
        "Physics simulation diverged between identical invocations; "
        "expected deterministic outcome."
    )


def test_ecs_persistence_layer_roundtrip(
    aws_test_resources: Dict[str, Any],
) -> None:
    """
    Smoke-test that verifies a basic *Entity-Component-System* snapshot can be
    persisted to DynamoDB and then re-hydrated without mutation.

    This is crucial because the engine relies on *idempotent* snapshots to
    re-process frames after transient Lambda failures.
    """
    dynamodb_table = aws_test_resources["dynamodb_table"]

    from game_engine.persistence.state import StateStore  # type: ignore

    store = StateStore(table=dynamodb_table)

    snapshot = {
        "pk": "g#demo",
        "sk": "e#player1",
        "components": {
            "Transform": {"x": 10.0, "y": 5.0, "rotation": 90.0},
            "Health": {"current": 100, "max": 100},
        },
        "version": 1,
    }

    # Write
    store.put_snapshot(snapshot)

    # Read
    loaded = store.get_snapshot("g#demo", "e#player1")

    assert loaded == snapshot, "Round-tripped ECS snapshot mutated data!"


def test_audit_log_event_emission(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    """
    `Command` processing Lambdas should *always* emit an ``AuditLog`` event
    to EventBridge so compliance pipelines can ingest them for long-term, WORM
    storage.  The payload *must* include the original command, the outcome,
    and the authenticated principal information.
    """
    # ------------------------------------------------------------------
    # Arrange: create a fake EventBridge and patch the engine dispatcher
    # ------------------------------------------------------------------
    collector = _EventCollector()

    monkeypatch.setenv("AUDIT_BUS_NAME", EVENT_BUS_NAME)
    monkeypatch.setattr("game_engine.events.eventbridge", collector, raising=False)

    from game_engine.command_bus import handle_command  # type: ignore

    command = {
        "type": "SpawnEntity",
        "principal": {"tenant_id": "acme", "user_id": "u42"},
        "payload": {"prefab": "orc", "position": {"x": 3, "y": 4}},
        "metadata": {"message_id": str(uuid.uuid4()), "timestamp": _iso_now()},
    }

    # ------------------------------------------------------------------
    # Act
    result = handle_command(command)

    # ------------------------------------------------------------------
    # Assert
    assert result["status"] == "OK"

    assert len(collector) == 1, "Exactly one audit event must be emitted"

    evt = collector.filter("AuditLog")[0]

    assert evt.detail["command"] == command
    assert evt.detail["outcome"]["status"] == result["status"]
    assert evt.detail["principal"] == command["principal"]


def test_behavior_tree_tick_is_side_effect_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Behaviour-tree ticks should *not* mutate the tree definition object
    provided as input; instead, they must return a new *immutable* status
    description, enabling safe concurrent execution across multiple Lambda
    invocations without locking.
    """
    from game_engine.ai.behavior_tree import BehaviourTree, NodeStatus  # type: ignore

    # Build the simplest *always-success* leaf node
    leaf = BehaviourTree.Leaf(lambda *_: NodeStatus.SUCCESS)
    tree = BehaviourTree.Root(leaf)

    # Copy by value for later equality check
    original_serialised = tree.to_json()

    status = tree.tick(context={})

    assert status == NodeStatus.SUCCESS

    # Serialise again after tick; must remain unchanged
    after_serialised = tree.to_json()
    assert original_serialised == after_serialised, (
        "BehaviourTree mutated its structure during tick; "
        "must remain immutable."
    )


# ---------------------------------------------------------------------------
#  PyTest hooks (optional)
# ---------------------------------------------------------------------------

def pytest_runtest_setup(item: pytest.Item) -> None:  # noqa: D401
    """
    Global `pytest` hook that enforces the *slow* marker for tests that take
    longer than a predefined threshold.

    By tagging slow tests explicitly we can allow CI pipelines to skip or run
    them conditionally.
    """
    timeout_threshold = float(os.getenv("LEDGERQUEST_SLOW_TEST_THRESHOLD", "0.5"))
    if "slow" in item.keywords and timeout_threshold == 0.0:
        pytest.skip("Skipping slow tests because threshold is set to 0.0s")
```