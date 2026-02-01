```python
"""
ledgerquest.services.game_loop.physics_updater
=============================================

This Lambda-compatible module is responsible for applying physics
integration on dynamic entities inside a scene.  It is designed to
be triggered by an AWS Step-Functions `Task` state (or EventBridge
Scheduler), and persists the updated entity components back to
DynamoDB.  The routine is intentionally lightweight—only the minimal
math required for business-grade “serious games”.  Heavy GPU/CPU
workloads should still be off-loaded to dedicated workers (e.g.
Fargate).

Environment variables
---------------------
ENTITIES_TABLE_NAME   : DynamoDB table that stores entity component state
EVENT_BUS_NAME        : Optional ‑ EventBridge bus to publish collision events
LOG_LEVEL             : stdlib logging level (default=INFO)

Input event contract
--------------------
{
    "scene_id": "<uuid>",
    "delta_time": 0.016  # seconds since previous physics frame
}

Output contract (Step-Functions result)
---------------------------------------
{
    "scene_id": "<uuid>",
    "updated_entities": 42,
    "collisions": 3,
    "duration_ms": 12.34
}
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------#
# Logging setup
# ---------------------------------------------------------------------------#
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------#
# Constants & Config
# ---------------------------------------------------------------------------#
GRAVITY: float = 9.81  # m/s^2, positive downwards
MAX_BATCH_WRITE: int = 25  # DynamoDB service limit
DYNAMO_FLOAT_PRECISION = 8  # decimal places for serialization

_ENTITIES_TABLE_NAME = os.getenv("ENTITIES_TABLE_NAME")
if not _ENTITIES_TABLE_NAME:
    logger.error("Missing required env var ENTITIES_TABLE_NAME")
    raise RuntimeError("ENTITIES_TABLE_NAME environment variable not set")

_EVENT_BUS_NAME = os.getenv("EVENT_BUS_NAME")  # optional

_dynamo = boto3.resource("dynamodb")
_entities_table = _dynamo.Table(_ENTITIES_TABLE_NAME)

_events_client = boto3.client("events") if _EVENT_BUS_NAME else None


# ---------------------------------------------------------------------------#
# Helper datatypes
# ---------------------------------------------------------------------------#
@dataclass
class Vec2:
    """Simple 2-D vector for physics calculations."""
    x: float
    y: float

    def __add__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x + other.x, self.y + other.y)

    def __mul__(self, scalar: float) -> "Vec2":
        return Vec2(self.x * scalar, self.y * scalar)

    def copy(self) -> "Vec2":
        return Vec2(self.x, self.y)


@dataclass
class AABB:
    """Axis-Aligned Bounding Box used for naïve collision checks."""
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def intersects(self, other: "AABB") -> bool:
        return (
            self.max_x >= other.min_x
            and self.min_x <= other.max_x
            and self.max_y >= other.min_y
            and self.min_y <= other.max_y
        )


@dataclass
class EntityPhysicsState:
    """Subset of a full entity component specific to physics."""
    entity_id: str
    scene_id: str
    pos: Vec2
    vel: Vec2
    size: Vec2  # half-width / half-height (extents)
    mass: float
    is_static: bool = False
    version: int = 0  # optimistic-locking version

    # runtime-only computed field (not persisted)
    _aabb: AABB = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.compute_aabb()

    # ------------------------------------------------------------------#
    # Behaviour helpers
    # ------------------------------------------------------------------#
    def compute_aabb(self) -> None:
        self._aabb = AABB(
            self.pos.x - self.size.x,
            self.pos.y - self.size.y,
            self.pos.x + self.size.x,
            self.pos.y + self.size.y,
        )

    def apply_gravity(self, delta: float) -> None:
        if not self.is_static:
            self.vel.y += GRAVITY * delta

    def integrate(self, delta: float) -> None:
        if self.is_static:
            return
        self.pos = self.pos + self.vel * delta
        self.compute_aabb()

    def bounce(self, normal: Tuple[float, float]) -> None:
        """Very simple reflection model with full energy loss on normal axis."""
        nx, ny = normal
        if nx != 0:
            self.vel.x = -self.vel.x * 0.5  # some damping
        if ny != 0:
            self.vel.y = -self.vel.y * 0.5
        self.compute_aabb()

    # ------------------------------------------------------------------#
    # (De)serialization helpers
    # ------------------------------------------------------------------#
    def to_dynamo_item(self) -> Dict[str, Any]:
        """Serialize to a shape that can be put into DynamoDB."""
        return {
            "pk": f"scene#{self.scene_id}",
            "sk": f"ent#{self.entity_id}",
            "component": "physics",
            "pos": {
                "x": _to_dynamo_float(self.pos.x),
                "y": _to_dynamo_float(self.pos.y),
            },
            "vel": {
                "x": _to_dynamo_float(self.vel.x),
                "y": _to_dynamo_float(self.vel.y),
            },
            "size": {
                "x": _to_dynamo_float(self.size.x),
                "y": _to_dynamo_float(self.size.y),
            },
            "mass": _to_dynamo_float(self.mass),
            "is_static": self.is_static,
            "version": self.version + 1,  # increment
            "updated_at": int(time.time() * 1000),
        }

    @classmethod
    def from_dynamo_item(cls, item: Dict[str, Any]) -> "EntityPhysicsState":
        return cls(
            entity_id=item["sk"].split("#")[1],
            scene_id=item["pk"].split("#")[1],
            pos=Vec2(
                float(item["pos"]["x"]),
                float(item["pos"]["y"]),
            ),
            vel=Vec2(
                float(item["vel"]["x"]),
                float(item["vel"]["y"]),
            ),
            size=Vec2(
                float(item["size"]["x"]),
                float(item["size"]["y"]),
            ),
            mass=float(item["mass"]),
            is_static=item.get("is_static", False),
            version=int(item.get("version", 0)),
        )


# ---------------------------------------------------------------------------#
# Physics System
# ---------------------------------------------------------------------------#
class PhysicsUpdater:
    """Encapsulates physics simulation for a single time-step."""

    def __init__(self, scene_id: str, delta_time: float) -> None:
        self.scene_id = scene_id
        self.delta = max(delta_time, 0.001)  # clamp to avoid div-by-zero
        self.entities: List[EntityPhysicsState] = []
        self.collisions: List[Tuple[str, str]] = []

    # ------------------------------------------------------------------#
    # Public helpers
    # ------------------------------------------------------------------#
    def step(self) -> None:
        self._load_entities()
        logger.debug("Loaded %d physics entities", len(self.entities))
        self._apply_forces()
        self._integrate()
        self._detect_and_resolve_collisions()
        self._persist()
        self._emit_collision_events()

    # ------------------------------------------------------------------#
    # Internal helpers
    # ------------------------------------------------------------------#
    def _load_entities(self) -> None:
        try:
            response = _entities_table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={
                    ":pk": f"scene#{self.scene_id}",
                    ":sk": "ent#",
                },
                FilterExpression="component = :physics",
                ExpressionAttributeNames=None,
                ExpressionAttributeValues2={":physics": "physics"},
            )
        except TypeError:
            # boto3's query() unfortunately won't allow mixing FilterExpression
            # with ExpressionAttributeValues2; fall back to scan().  It's still
            # acceptable for small partitions (< ~100 items).
            logger.debug("Falling back to full scan for scene_id=%s", self.scene_id)
            response = _entities_table.scan(
                FilterExpression="pk = :pk AND component = :physics",
                ExpressionAttributeValues={
                    ":pk": f"scene#{self.scene_id}",
                    ":physics": "physics",
                }
            )

        items = response.get("Items", [])
        self.entities = [EntityPhysicsState.from_dynamo_item(i) for i in items]

    def _apply_forces(self) -> None:
        for ent in self.entities:
            ent.apply_gravity(self.delta)

    def _integrate(self) -> None:
        for ent in self.entities:
            ent.integrate(self.delta)

    def _detect_and_resolve_collisions(self) -> None:
        # Naïve O(N^2) for demo purposes; optimise using spatial hashing if needed
        count = len(self.entities)
        for i in range(count):
            a = self.entities[i]
            if a.is_static:
                continue
            for j in range(i + 1, count):
                b = self.entities[j]
                if a._aabb.intersects(b._aabb):
                    # Simple symmetric collision response
                    normal = self._compute_collision_normal(a, b)
                    a.bounce(normal)
                    if not b.is_static:
                        b.bounce((-normal[0], -normal[1]))
                    self.collisions.append((a.entity_id, b.entity_id))

    @staticmethod
    def _compute_collision_normal(a: EntityPhysicsState, b: EntityPhysicsState) -> Tuple[float, float]:
        # Determine which axis penetration is smaller
        dx = (b.pos.x - a.pos.x)
        dy = (b.pos.y - a.pos.y)
        abs_dx, abs_dy = abs(dx), abs(dy)
        if abs_dx > abs_dy:
            # collision comes from left or right
            return (1 if dx > 0 else -1, 0)
        else:
            return (0, 1 if dy > 0 else -1)

    def _persist(self) -> None:
        # Write in batches of 25
        batch: List[Dict[str, Any]] = []
        for ent in self.entities:
            batch.append({"PutRequest": {"Item": ent.to_dynamo_item()}})
            if len(batch) == MAX_BATCH_WRITE:
                self._flush_batch(batch)
                batch.clear()
        if batch:
            self._flush_batch(batch)

    @staticmethod
    def _flush_batch(batch: List[Dict[str, Any]]) -> None:
        try:
            response = _entities_table.meta.client.batch_write_item(
                RequestItems={_ENTITIES_TABLE_NAME: batch}
            )
            unprocessed = response.get("UnprocessedItems", {})
            if unprocessed:
                logger.warning("Retrying %d unprocessed items", len(unprocessed))
                # simple naive retry once
                _entities_table.meta.client.batch_write_item(
                    RequestItems=unprocessed
                )
        except ClientError as exc:
            logger.error("DynamoDB batch_write_item failed: %s", exc, exc_info=True)
            raise

    def _emit_collision_events(self) -> None:
        if not self.collisions or _events_client is None:
            return

        entries = []
        for a_id, b_id in self.collisions[:10]:  # limit to 10 per invocation
            entries.append(
                {
                    "Source": "ledgerquest.physics",
                    "DetailType": "COLLISION",
                    "EventBusName": _EVENT_BUS_NAME,
                    "Time": int(time.time() * 1000),
                    "Detail": json.dumps(
                        {
                            "scene_id": self.scene_id,
                            "a": a_id,
                            "b": b_id,
                        }
                    ),
                }
            )

        # EventBridge allows max 10 entries / put_events call
        try:
            _events_client.put_events(Entries=entries)
        except ClientError as exc:
            logger.error("Failed to publish collision events: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------#
# Lambda entrypoint
# ---------------------------------------------------------------------------#
def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler.  Expects a Step-Function / EventBridge payload.

    Parameter
    ---------
    event : dict
        {
            "scene_id": "<uuid>",
            "delta_time": 0.016
        }

    Returns
    -------
    dict  # same shape for downstream steps
    """
    t0 = time.perf_counter()
    try:
        scene_id = str(event["scene_id"])
        delta = float(event.get("delta_time", 0.016))
    except (KeyError, ValueError, TypeError) as exc:
        logger.error("Bad input event: %s", exc, exc_info=True)
        raise

    logger.info("Physics step start scene=%s  Δt=%.4fs", scene_id, delta)

    simulator = PhysicsUpdater(scene_id, delta)
    simulator.step()

    duration_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(
        "Physics step complete scene=%s entities=%d collisions=%d (%.2fms)",
        scene_id,
        len(simulator.entities),
        len(simulator.collisions),
        duration_ms,
    )

    return {
        "scene_id": scene_id,
        "updated_entities": len(simulator.entities),
        "collisions": len(simulator.collisions),
        "duration_ms": round(duration_ms, 2),
    }


# ---------------------------------------------------------------------------#
# Utility helpers
# ---------------------------------------------------------------------------#
def _to_dynamo_float(value: float) -> Decimal:
    """
    DynamoDB does not support IEEE-754 floats; we use `Decimal` with a fixed
    precision to maintain deterministic JSON hashing across our pipeline.
    """
    fmt = f"{{:.{DYNAMO_FLOAT_PRECISION}f}}"
    return Decimal(fmt.format(value))
