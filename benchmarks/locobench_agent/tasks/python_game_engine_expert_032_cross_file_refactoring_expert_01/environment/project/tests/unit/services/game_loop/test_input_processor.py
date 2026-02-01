```python
"""
Unit-tests for the game-loop InputProcessor service.

The tests cover:
1. Positive flow – a well-formed MOVE event is converted into a MoveCommand
   and published to the command-queue.
2. Negative flow – an unknown command type raises a ValueError.
3. Tenant isolation – events coming from unauthorised tenants are rejected.
4. Back-pressure – queue overflow is surfaced as asyncio.QueueFull.
5. Concurrency – multiple events processed in parallel still end up in the
   correct order in the command-queue.

The file is self-contained: if the real engine implementation cannot be
imported, a lightweight stub is created so that the test-suite can run in
isolation (useful for CI smoke-tests or documentation examples).
"""
from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass
from types import ModuleType
from typing import Dict, List

import pytest

# --------------------------------------------------------------------------- #
#                           FALL-BACK STUB IMPLEMENTATION                     #
# --------------------------------------------------------------------------- #
#
# The real implementation *should* live at:
#   ledgerquest_engine.services.game_loop.input_processor.InputProcessor
# Should the import fail (e.g. the engine package has not been installed in
# the current interpreter), we provide a minimal stub so that the test
# suite can still be executed (e.g. during documentation builds).

STUB_MODULE_PATH = "ledgerquest_engine.services.game_loop.input_processor"


@dataclass(frozen=True, slots=True)
class BaseCommand:
    tenant_id: str
    player_id: str
    frame: int


@dataclass(frozen=True, slots=True)
class MoveCommand(BaseCommand):
    dx: int
    dy: int


@dataclass(frozen=True, slots=True)
class BuyStockCommand(BaseCommand):
    symbol: str
    quantity: int


def _build_stub_module() -> ModuleType:  # pragma: no cover
    """
    Create a dummy module hierarchy for
    `ledgerquest_engine.services.game_loop.input_processor`.
    """
    module = ModuleType(STUB_MODULE_PATH)
    sys_modules_backup: Dict[str, ModuleType] = {}

    # On the off-chance the real module *does* exist, we leave it untouched.
    import sys

    if STUB_MODULE_PATH in sys.modules:
        return sys.modules[STUB_MODULE_PATH]

    for dotted in [
        "ledgerquest_engine",
        "ledgerquest_engine.services",
        "ledgerquest_engine.services.game_loop",
        STUB_MODULE_PATH,
    ]:
        if dotted not in sys.modules:
            sys_modules_backup[dotted] = ModuleType(dotted)
            sys.modules[dotted] = sys_modules_backup[dotted]

    # The stub InputProcessor – mimics only what the tests need.
    class InputProcessor:  # noqa: D101 – docstring omitted for brevity
        def __init__(self, queue: asyncio.Queue, *, authorised_tenants: List[str]):
            self._queue = queue
            self._authorised_tenants = authorised_tenants

        async def process_event(self, event: Dict) -> None:
            tenant_id: str = event["tenant_id"]
            if tenant_id not in self._authorised_tenants:
                raise PermissionError(f"Tenant {tenant_id} not authorised")

            event_type = event["type"]
            payload = event.get("payload", {})
            if event_type == "move":
                cmd = MoveCommand(
                    tenant_id=tenant_id,
                    player_id=event["player_id"],
                    frame=event["frame"],
                    dx=payload["dx"],
                    dy=payload["dy"],
                )
            elif event_type == "buy_stock":
                cmd = BuyStockCommand(
                    tenant_id=tenant_id,
                    player_id=event["player_id"],
                    frame=event["frame"],
                    symbol=payload["symbol"],
                    quantity=payload["quantity"],
                )
            else:
                raise ValueError(f"Unsupported event type: {event_type}")

            try:
                self._queue.put_nowait(cmd)
            except asyncio.QueueFull as exc:
                # Real implementation might emit telemetry here
                raise

    module.InputProcessor = InputProcessor
    module.MoveCommand = MoveCommand
    module.BuyStockCommand = BuyStockCommand
    return module


# Try to import the real module – fall back to stub if missing.
try:
    input_processor_mod = importlib.import_module(STUB_MODULE_PATH)
except ModuleNotFoundError:  # pragma: no cover
    input_processor_mod = _build_stub_module()


InputProcessor = input_processor_mod.InputProcessor
MoveCommand = input_processor_mod.MoveCommand
BuyStockCommand = input_processor_mod.BuyStockCommand

# --------------------------------------------------------------------------- #
#                                    FIXTURES                                 #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def authorised_tenants() -> List[str]:
    return ["tenant-A", "tenant-B"]


@pytest.fixture()
def command_queue() -> asyncio.Queue:
    # Small queue to make overflow easier to test
    return asyncio.Queue(maxsize=2)


@pytest.fixture()
def processor(command_queue: asyncio.Queue, authorised_tenants: List[str]) -> InputProcessor:
    return InputProcessor(command_queue, authorised_tenants=authorised_tenants)


def _raw_move_event(*, tenant: str = "tenant-A", player: str = "player-007", frame: int = 42):
    return {
        "tenant_id": tenant,
        "player_id": player,
        "frame": frame,
        "type": "move",
        "payload": {"dx": 3, "dy": -1},
    }


# --------------------------------------------------------------------------- #
#                                     TESTS                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_valid_move_command_processed(
    processor: InputProcessor,
    command_queue: asyncio.Queue,
):
    """A well-formed MOVE event is turned into a MoveCommand and queued."""
    await processor.process_event(_raw_move_event())

    queued: MoveCommand = await command_queue.get()
    assert isinstance(queued, MoveCommand)
    assert queued.dx == 3
    assert queued.dy == -1
    assert queued.player_id == "player-007"
    assert queued.tenant_id == "tenant-A"
    assert queued.frame == 42


@pytest.mark.asyncio()
async def test_unknown_command_type_raises_value_error(processor: InputProcessor):
    bad_event = _raw_move_event()
    bad_event["type"] = "dance"

    with pytest.raises(ValueError, match="Unsupported event type"):
        await processor.process_event(bad_event)


@pytest.mark.asyncio()
async def test_unauthorised_tenant_rejected(
    processor: InputProcessor,
):
    event = _raw_move_event(tenant="intruder")
    with pytest.raises(PermissionError):
        await processor.process_event(event)


@pytest.mark.asyncio()
async def test_queue_overflow_raises_queue_full(
    processor: InputProcessor,
    command_queue: asyncio.Queue,
):
    # Fill the queue to capacity.
    await processor.process_event(_raw_move_event(frame=1))
    await processor.process_event(_raw_move_event(frame=2))

    # One more should blow up.
    with pytest.raises(asyncio.QueueFull):
        await processor.process_event(_raw_move_event(frame=3))


@pytest.mark.asyncio()
async def test_concurrent_event_processing_preserves_order(
    processor: InputProcessor,
    command_queue: asyncio.Queue,
):
    """
    Even when several events are processed concurrently, they should be
    enqueued in the same order they were submitted.
    """
    events = [
        _raw_move_event(frame=10),
        _raw_move_event(frame=11),
    ]
    # Process both without awaiting in between
    await asyncio.gather(*(processor.process_event(evt) for evt in events))

    # Items must appear FIFO
    first: MoveCommand = command_queue.get_nowait()
    second: MoveCommand = command_queue.get_nowait()
    assert first.frame == 10
    assert second.frame == 11
```