```python
"""
ledgerquest.services.game_loop.ai_updater
========================================

AWS Lambda entry-point responsible for advancing AI behaviour for a single
game tick.  The function is invoked by an AWS Step-Functions state machine
that orchestrates the stateless “game-loop” for LedgerQuest Engine.

The AI updater performs the following high-level steps:

1.  Input validation & context bootstrap (tenant, session, tick, etc.)
2.  Pull the set of ECS entities that own an ``AIComponent`` and require an
    update this tick.
3.  Evaluate each entity’s Behaviour-Tree (BT) against the current world
    state, producing one or more commands.
4.  Persist the updated component state and publish resulting commands to an
    EventBridge bus so that downstream state mutators (e.g., physics
    simulator) can consume them.

The module purposefully keeps all objects in memory during execution to
honour the Lambda “stateless but warm container” paradigm—no globals are
written to. Behaviour-Tree definitions are cached across invocations via the
*execution context* (module-level) to minimise S3 latency.

Author: LedgerQuest Team
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
LOG_LEVEL = os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO").upper()
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)

# --------------------------------------------------------------------------- #
# AWS Clients (re-use across warm invocations)
# --------------------------------------------------------------------------- #
_BOTO_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})
_dynamodb = boto3.resource("dynamodb", config=_BOTO_CONFIG)
_s3 = boto3.client("s3", config=_BOTO_CONFIG)
_eventbridge = boto3.client("events", config=_BOTO_CONFIG)

# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #
DDB_ENTITY_TABLE = os.getenv("LEDGERQUEST_ENTITY_TABLE", "ledgerquest_entities")
DDB_COMPONENT_GSI = os.getenv("LEDGERQUEST_COMPONENT_GSI", "components-index")
BT_S3_BUCKET = os.getenv("LEDGERQUEST_BT_BUCKET", "ledgerquest-behaviour-trees")
EVENT_BUS = os.getenv("LEDGERQUEST_EVENT_BUS", "ledgerquest-game-events")
MAX_BATCH_WRITE = 25  # DynamoDB maximum for batch_write_item


# --------------------------------------------------------------------------- #
# ECS & Behaviour-Tree Models
# --------------------------------------------------------------------------- #
@dataclass
class EntityState:
    """Simplified ECS entity snapshot required for AI evaluation."""
    entity_id: str
    session_id: str
    tenant_id: str
    position: Dict[str, float]
    ai_state: Dict[str, Any]  # arbitrary per-entity scratch-pad


class Blackboard(dict):
    """Shared memory for BT nodes during a single tick."""


class BTNode(Protocol):
    """Behaviour-Tree node protocol."""

    def tick(self, state: EntityState, blackboard: Blackboard) -> bool: ...


class Selector:
    """Returns `True` when the first child returns `True`."""

    def __init__(self, *children: BTNode) -> None:
        self._children = children

    def tick(self, state: EntityState, blackboard: Blackboard) -> bool:
        for child in self._children:
            if child.tick(state, blackboard):
                return True
        return False


class Sequence:
    """Returns `True` when *all* children return `True`."""

    def __init__(self, *children: BTNode) -> None:
        self._children = children

    def tick(self, state: EntityState, blackboard: Blackboard) -> bool:
        for child in self._children:
            if not child.tick(state, blackboard):
                return False
        return True


class ConditionNode:
    """Evaluates a predicate stored in BT specification."""

    def __init__(self, predicate: str) -> None:
        self._predicate = predicate

    def tick(self, state: EntityState, blackboard: Blackboard) -> bool:
        # In real world, predicate would be compiled Python or DSL.
        # For demo, support a few hard-coded predicates.
        if self._predicate == "is_player_nearby":
            # Randomised example
            is_near = random.random() < 0.3
            logger.debug("Predicate is_player_nearby -> %s", is_near)
            return is_near
        if self._predicate == "low_health":
            # Suppose health sits on blackboard
            low = blackboard.get("health", 100) < 25
            logger.debug("Predicate low_health -> %s", low)
            return low
        logger.warning("Unknown predicate %s, defaulting to False", self._predicate)
        return False


class ActionNode:
    """Produces commands for the entity; always returns `True`."""

    def __init__(self, command_type: str, **params: Any) -> None:
        self._command_type = command_type
        self._params = params

    def tick(self, state: EntityState, blackboard: Blackboard) -> bool:
        # Store commands on the blackboard; they will be flushed later.
        commands: List[Dict[str, Any]] = blackboard.setdefault("commands", [])
        commands.append(
            {
                "type": self._command_type,
                "entity_id": state.entity_id,
                "params": self._params,
            }
        )
        logger.debug(
            "Queued command %s for entity %s", self._command_type, state.entity_id
        )
        return True


# --------------------------------------------------------------------------- #
# Behaviour-Tree Registry
# --------------------------------------------------------------------------- #
_BT_CACHE: Dict[str, BTNode] = {}


def _load_bt_from_s3(key: str) -> BTNode:
    """Load & parse BT JSON from S3, then cache the compiled tree."""
    if key in _BT_CACHE:
        return _BT_CACHE[key]

    try:
        response = _s3.get_object(Bucket=BT_S3_BUCKET, Key=key)
        definition = json.loads(response["Body"].read())
        root = _compile_bt(definition)
        _BT_CACHE[key] = root
        logger.info("Behaviour-Tree %s loaded and cached", key)
        return root
    except ClientError as exc:
        logger.error("Failed to load BT %s from S3: %s", key, exc)
        raise


def _compile_bt(spec: Dict[str, Any]) -> BTNode:
    """Recursively compile a JSON BT specification into runtime objects."""
    n_type = spec["type"]
    if n_type == "selector":
        return Selector(*[_compile_bt(child) for child in spec["children"]])
    if n_type == "sequence":
        return Sequence(*[_compile_bt(child) for child in spec["children"]])
    if n_type == "condition":
        return ConditionNode(spec["predicate"])
    if n_type == "action":
        return ActionNode(spec["command"], **spec.get("params", {}))
    raise ValueError(f"Unknown BT node type: {n_type}")


# --------------------------------------------------------------------------- #
# DynamoDB Helpers
# --------------------------------------------------------------------------- #
def _paginated_scan_entities(
    tenant_id: str, session_id: str, limit: int = 1000
) -> List[Dict[str, Any]]:
    """Scan the entity table for AI components, respecting GSIs for efficiency."""
    table = _dynamodb.Table(DDB_ENTITY_TABLE)
    start_key = None
    items: List[Dict[str, Any]] = []

    key_expr = "tenant_id = :tenant AND session_id = :sess"
    filter_expr = "contains(components, :ai)"
    expr_attr_values = {
        ":tenant": tenant_id,
        ":sess": session_id,
        ":ai": "AIComponent",
    }

    while True:
        resp = table.scan(
            IndexName=DDB_COMPONENT_GSI,
            ExclusiveStartKey=start_key,
            FilterExpression=filter_expr,
            KeyConditionExpression=key_expr,  # type: ignore[arg-type]
            ExpressionAttributeValues=expr_attr_values,
            Limit=limit,
        )
        items.extend(resp.get("Items", []))
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            break
    logger.info(
        "Fetched %s AI-enabled entities for tenant=%s session=%s",
        len(items),
        tenant_id,
        session_id,
    )
    return items


def _batch_write_with_retries(
    table_name: str, requests: List[Dict[str, Any]], retries: int = 3
) -> None:
    """Write items to DynamoDB with exponential backoff."""
    client = boto3.client("dynamodb", config=_BOTO_CONFIG)
    for attempt in range(1, retries + 1):
        try:
            resp = client.batch_write_item(RequestItems={table_name: requests})
            unprocessed = resp.get("UnprocessedItems", {}).get(table_name, [])
            if unprocessed:
                logger.warning(
                    "Attempt %d: %d items unprocessed, retrying",
                    attempt,
                    len(unprocessed),
                )
                requests = unprocessed
                time.sleep(2 ** attempt)
                continue
            return
        except ClientError as exc:
            logger.error(
                "Error writing to DynamoDB (attempt %d/%d): %s", attempt, retries, exc
            )
            time.sleep(2 ** attempt)
    if requests:
        logger.error("Failed to write some items to DynamoDB after retries: %s", requests)
        raise RuntimeError("DynamoDB batch write failed")


# --------------------------------------------------------------------------- #
# Lambda Handler
# --------------------------------------------------------------------------- #
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda entry-point.

    Expected ``event`` shape:
    {
        "tenant_id": "corp-foo",
        "session_id": "sess-uuid",
        "tick": 1024
    }
    """
    tenant_id = event.get("tenant_id")
    session_id = event.get("session_id")
    tick = event.get("tick")

    if not (tenant_id and session_id and isinstance(tick, int)):
        logger.error("Invalid invocation parameters: %s", event)
        raise ValueError("Missing required parameters")

    entities_raw = _paginated_scan_entities(tenant_id, session_id)
    entities: List[EntityState] = [
        EntityState(
            entity_id=e["entity_id"],
            session_id=session_id,
            tenant_id=tenant_id,
            position=e.get("position", {"x": 0, "y": 0}),
            ai_state=e.get("components", {}).get("AIComponent", {}),
        )
        for e in entities_raw
    ]

    ddb_updates: List[Dict[str, Any]] = []
    event_entries: List[Dict[str, Any]] = []

    for entity in entities:
        try:
            bt_key = entity.ai_state.get("behaviour_tree_key")
            if not bt_key:
                logger.warning("Entity %s missing behaviour_tree_key", entity.entity_id)
                continue

            blackboard = Blackboard()

            # Populate blackboard with dynamic values (simplified)
            blackboard["health"] = entity.ai_state.get("health", 100)

            bt_root = _load_bt_from_s3(bt_key)
            bt_root.tick(entity, blackboard)

            commands = blackboard.get("commands", [])
            logger.debug(
                "Entity %s produced %d commands", entity.entity_id, len(commands)
            )

            # Prepare DynamoDB update for the AI scratch-pad
            ddb_updates.append(
                {
                    "Update": {
                        "Key": {"entity_id": {"S": entity.entity_id}},
                        "TableName": DDB_ENTITY_TABLE,
                        "UpdateExpression": "SET components.#ai = :val",
                        "ExpressionAttributeNames": {"#ai": "AIComponent"},
                        "ExpressionAttributeValues": {
                            ":val": {"S": json.dumps(entity.ai_state)}
                        },
                    }
                }
            )

            # Prepare EventBridge entries
            for cmd in commands:
                event_entries.append(
                    {
                        "Source": "ledgerquest.ai",
                        "DetailType": cmd["type"],
                        "EventBusName": EVENT_BUS,
                        "Detail": json.dumps(
                            {
                                "tenant_id": tenant_id,
                                "session_id": session_id,
                                "tick": tick,
                                **cmd,
                            }
                        ),
                    }
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed processing entity %s: %s", entity.entity_id, exc)

    # Commit updates
    if ddb_updates:
        # DynamoDB batch_write_item requires <=25 items
        for i in range(0, len(ddb_updates), MAX_BATCH_WRITE):
            _batch_write_with_retries(
                DDB_ENTITY_TABLE, ddb_updates[i : i + MAX_BATCH_WRITE]
            )

    if event_entries:
        # EventBridge put_events allows up to 10 entries
        for i in range(0, len(event_entries), 10):
            batch = event_entries[i : i + 10]
            try:
                response = _eventbridge.put_events(Entries=batch)
                failed = response.get("FailedEntryCount", 0)
                if failed:
                    logger.error("%d EventBridge entries failed: %s", failed, response)
            except ClientError as exc:
                logger.error("Error publishing to EventBridge: %s", exc)

    return {
        "status": "ok",
        "processed_entities": len(entities),
        "commands_emitted": len(event_entries),
        "tick": tick,
    }
```