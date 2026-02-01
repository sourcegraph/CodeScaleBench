```python
"""
ledgerquest.services.game_loop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Orchestration utilities that bridge the synchronous “engine style” game-loop
with LedgerQuest’s serverless, event-driven runtime.

When the engine is deployed on AWS the actual frame-steps are executed by
Step Functions states, however this module provides a thin façade that:

1. Starts new Step-Function executions (production).
2. Allows an in-process ‘local’ tick (unit-tests / local tooling).
3. Persists & loads world-state deltas to DynamoDB.
4. Emits structured CloudWatch logs and EventBridge events so that other
   services (metering, audit, multi-tenant observability…) can subscribe.

Nothing in here is game-specific; all concrete behaviour (AI updates,
physics, scripting, etc.) lives in the respective sub-services that the state
machine invokes.  This file purely coordinates those services.

The module is intentionally free of heavy dependencies to keep cold-starts
low; anything compute-intensive is delegated to Lambda Layers or container
tasks.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

_LOGGER = logging.getLogger(__name__)
_LOG_LEVEL = os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=_LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# ------------------------------------------------------------------------------
# Constants / Env Vars
# ------------------------------------------------------------------------------

_ENV = os.getenv("LEDGERQUEST_ENV", "dev")
_STATE_MACHINE_ARN = os.getenv("LEDGERQUEST_GAMELOOP_SFN_ARN")
_DDB_TABLE_NAME = os.getenv("LEDGERQUEST_WORLDSTATE_TABLE", "ledgerquest_worldstate")
_EVENT_BUS_NAME = os.getenv("LEDGERQUEST_EVENT_BUS", "ledgerquest-events")

# ------------------------------------------------------------------------------
# Data Models
# ------------------------------------------------------------------------------


@dataclass(frozen=True)
class GameLoopContext:
    """
    Context object passed around the different parts of a frame-tick.
    Immutable by design; any mutation should be done on copies to keep the
    functional / stateless paradigm.
    """

    game_id: str
    frame_number: int
    delta_time: float  # Seconds since last frame.
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ------------------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------------------


class GameLoopError(RuntimeError):
    """Base class for any Game-Loop specific exception."""


class StateMachineMissing(GameLoopError):
    """Raised when the Step-Function ARN is not configured."""


class WorldStateError(GameLoopError):
    """Raised when DynamoDB world-state operations fail."""


# ------------------------------------------------------------------------------
# Service
# ------------------------------------------------------------------------------


class GameLoopService:
    """
    Facade in front of the Game-Loop Step Function.

    Typical usage:

        svc = GameLoopService()
        execution_arn = svc.tick(game_id="demo", frame_number=42)
    """

    _ddb = boto3.resource("dynamodb")
    _step_functions = boto3.client("stepfunctions")
    _events = boto3.client("events")

    def __init__(self, state_machine_arn: Optional[str] = None) -> None:
        self._state_machine_arn = state_machine_arn or _STATE_MACHINE_ARN
        if not self._state_machine_arn:
            raise StateMachineMissing(
                "Missing Step-Function ARN – configure LEDGERQUEST_GAMELOOP_SFN_ARN."
            )
        self._world_table = self._ddb.Table(_DDB_TABLE_NAME)

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def tick(
        self,
        game_id: str,
        frame_number: int,
        *,
        override_payload: Optional[Dict[str, Any]] = None,
        async_execution: bool = True,
    ) -> str | Dict[str, Any]:
        """
        Start a new ‘frame’ by invoking the Step Function.

        When ``async_execution`` is True (default) we simply kick off the
        execution and return its ARN.  When False, we run a best-effort
        *local* tick for test purposes – this never touches AWS Step
        Functions and therefore should not be used in production.
        """
        _LOGGER.debug("tick called with game_id=%s frame=%s async=%s", game_id, frame_number, async_execution)

        if async_execution:
            return self._start_remote_execution(game_id, frame_number, override_payload)
        return self._run_local(game_id, frame_number, override_payload)

    # ----------------------------------------------------------------------
    # Private – Remote Execution
    # ----------------------------------------------------------------------

    def _start_remote_execution(
        self, game_id: str, frame_number: int, override_payload: Optional[Dict[str, Any]]
    ) -> str:
        """Spin up a new Step-Functions execution."""
        payload = override_payload or self._build_payload(game_id, frame_number)
        execution_name = f"{game_id}-{frame_number}-{uuid.uuid4().hex[:8]}"

        _LOGGER.info(
            "Starting remote GameLoop execution %s (frame=%s game=%s)",
            execution_name,
            frame_number,
            game_id,
        )
        try:
            resp = self._step_functions.start_execution(
                stateMachineArn=self._state_machine_arn,
                name=execution_name,
                input=json.dumps(payload),
                traceHeader=payload["context"]["trace_id"],
            )
        except ClientError as exc:  # pragma: no cover
            _LOGGER.exception("Unable to start Step-Function execution")
            raise GameLoopError("Failed to start game-loop execution") from exc

        # Fire & forget event for observability
        self._emit_event(
            detail_type="GameLoop.ExecutionStarted",
            detail={
                "gameId": game_id,
                "frameNumber": frame_number,
                "executionArn": resp["executionArn"],
                "env": _ENV,
            },
        )
        return resp["executionArn"]

    # ----------------------------------------------------------------------
    # Private – Local Execution
    # ----------------------------------------------------------------------

    def _run_local(
        self, game_id: str, frame_number: int, override_payload: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Execute the frame in-process.  This method stitches together the same
        *logical* steps the Step Function would invoke (physics → AI →
        scripting …) but without any network calls.

        Only lightweight logic lives here; real heavy-lifting code lives in
        their own modules so that production Lambdas can reuse them.
        """
        _LOGGER.warning("Running LOCAL game-loop tick – NOT SUITABLE FOR PRODUCTION")
        payload = override_payload or self._build_payload(game_id, frame_number)

        ctx = GameLoopContext(
            game_id=game_id,
            frame_number=frame_number,
            delta_time=payload["context"]["delta_time"],
            trace_id=payload["context"]["trace_id"],
        )
        world_state = payload["world_state"]
        # Example sub-step calls (would be separate packages in real life)
        world_state = self._apply_physics(world_state, ctx)
        world_state = self._apply_ai(world_state, ctx)
        world_state = self._run_scripts(world_state, ctx)

        # Persist & return result
        self._save_world_state(game_id, frame_number, world_state)
        return {
            "context": ctx.__dict__,
            "world_state": world_state,
            "metadata": {"executedLocally": True, "env": _ENV},
        }

    # ----------------------------------------------------------------------
    # World-State helpers
    # ----------------------------------------------------------------------

    def _load_previous_state(self, game_id: str) -> Dict[str, Any]:
        """
        Load the last committed world-state for a game.

        DynamoDB schema (simplified):
            PK  =  "GAME#{game_id}"
            SK  =  "FRAME#{frame_number:016d}"
        """
        _LOGGER.debug("Loading previous world-state for game %s", game_id)
        try:
            resp = self._world_table.query(
                KeyConditionExpression="PK = :pk",
                ExpressionAttributeValues={":pk": f"GAME#{game_id}"},
                Limit=1,
                ScanIndexForward=False,  # DESC by SK
            )
            items = resp.get("Items", [])
            if not items:
                _LOGGER.info("No existing world-state found – starting fresh")
                return {}
            return items[0]["payload"]
        except ClientError as exc:
            _LOGGER.exception("Failed to read world-state from DynamoDB")
            raise WorldStateError from exc

    def _save_world_state(
        self, game_id: str, frame_number: int, world_state: Dict[str, Any]
    ) -> None:
        """Persist the new world-state snapshot."""
        pk = f"GAME#{game_id}"
        sk = f"FRAME#{frame_number:016d}"
        try:
            self._world_table.put_item(
                Item={
                    "PK": pk,
                    "SK": sk,
                    "payload": world_state,
                    "createdAt": int(time.time() * 1000),
                },
                ConditionExpression="attribute_not_exists(SK)",
            )
            _LOGGER.debug("World-state for frame %s saved", frame_number)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                _LOGGER.exception("Failed to save world-state to DynamoDB")
                raise WorldStateError from exc
            _LOGGER.warning("World-state for frame %s already exists – skipping save", frame_number)

    # ----------------------------------------------------------------------
    # AWS EventBridge
    # ----------------------------------------------------------------------

    def _emit_event(self, detail_type: str, detail: Dict[str, Any]) -> None:
        """Send a single event to the shared event bus."""
        try:
            self._events.put_events(
                Entries=[
                    {
                        "EventBusName": _EVENT_BUS_NAME,
                        "Source": "ledgerquest.gameloop",
                        "DetailType": detail_type,
                        "Detail": json.dumps(detail),
                        "Time": datetime.now(timezone.utc),
                    }
                ]
            )
            _LOGGER.debug("Event %s emitted", detail_type)
        except ClientError:  # pragma: no cover
            _LOGGER.exception("Failed to push event %s", detail_type)

    # ----------------------------------------------------------------------
    # Payload Construction
    # ----------------------------------------------------------------------

    def _build_payload(self, game_id: str, frame_number: int) -> Dict[str, Any]:
        """Generate the JSON payload the state machine expects."""
        previous_state = self._load_previous_state(game_id)
        delta_time = self._compute_delta(previous_state)
        ctx = GameLoopContext(game_id=game_id, frame_number=frame_number, delta_time=delta_time)

        payload = {
            "context": ctx.__dict__,
            "world_state": previous_state or self._initial_world_state(game_id),
        }
        _LOGGER.debug("Payload built for game %s frame %s", game_id, frame_number)
        return payload

    @staticmethod
    def _compute_delta(previous_state: Dict[str, Any]) -> float:
        """Calculate Δt since last frame, falling back to 1/60s."""
        if not previous_state:
            return 1.0 / 60.0
        last_ts = previous_state.get("meta", {}).get("timestamp")
        if not last_ts:
            return 1.0 / 60.0
        try:
            last_dt = datetime.fromisoformat(last_ts)
        except ValueError:
            return 1.0 / 60.0
        now = datetime.now(timezone.utc)
        return max((now - last_dt).total_seconds(), 1.0 / 1000.0)

    # ----------------------------------------------------------------------
    # Example Sub-Steps (stub implementations)
    # ----------------------------------------------------------------------

    @staticmethod
    def _apply_physics(world_state: Dict[str, Any], ctx: GameLoopContext) -> Dict[str, Any]:
        """
        Apply a very naive physics step that updates entity positions based
        on velocity. Real engines would delegate to C++ or GPU compute.
        """
        entities = world_state.get("entities", {})
        for ent_id, ent in entities.items():
            vel = ent.get("velocity")
            pos = ent.get("position")
            if vel and pos:
                ent["position"] = [
                    pos[0] + vel[0] * ctx.delta_time,
                    pos[1] + vel[1] * ctx.delta_time,
                ]
        world_state["entities"] = entities
        return world_state

    @staticmethod
    def _apply_ai(world_state: Dict[str, Any], ctx: GameLoopContext) -> Dict[str, Any]:
        """Placeholder AI tick – toggles a boolean flag."""
        for ent in world_state.get("entities", {}).values():
            if ent.get("type") == "npc":
                ent["aiAwake"] = not ent.get("aiAwake", False)
        return world_state

    @staticmethod
    def _run_scripts(world_state: Dict[str, Any], ctx: GameLoopContext) -> Dict[str, Any]:
        """Run per-frame scripts (simplified to counter increment)."""
        counters = world_state.setdefault("scriptCounters", {})
        counters["frame"] = counters.get("frame", 0) + 1
        return world_state

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    @staticmethod
    def _initial_world_state(game_id: str) -> Dict[str, Any]:
        """Generate an initial world-state for a new game."""
        _LOGGER.info("Generating initial world-state for game %s", game_id)
        return {
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
            "entities": {
                "player": {
                    "type": "avatar",
                    "position": [0.0, 0.0],
                    "velocity": [0.0, 0.0],
                }
            },
        }


# ------------------------------------------------------------------------------
# Convenience – module level instance
# ------------------------------------------------------------------------------

_default_service: Optional[GameLoopService] = None


def _get_default_service() -> GameLoopService:
    global _default_service
    if _default_service is None:
        _default_service = GameLoopService()
    return _default_service


# Re-export a shorthand tick function so that callers can simply:
#    from ledgerquest.services.game_loop import tick
def tick(
    game_id: str,
    frame_number: int,
    *,
    override_payload: Optional[Dict[str, Any]] = None,
    async_execution: bool = True,
) -> str | Dict[str, Any]:
    """
    Proxy to ``GameLoopService.tick`` using a singleton service instance.
    Useful for Lambda handlers or quick scripts.
    """
    return _get_default_service().tick(
        game_id,
        frame_number,
        override_payload=override_payload,
        async_execution=async_execution,
    )
```