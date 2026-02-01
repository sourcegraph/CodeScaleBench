```python
"""
ledgerquest.engine.physics
==========================

A *stateless* physics simulation kernel optimised for AWS Lambda execution.

The module purposefully avoids global state.  Callers are expected to supply the
entire world-state as an event payload (e.g. via Step Functions).  After the
physics step is complete we return the mutated copy, ready to be stored back to
DynamoDB or forwarded to the game-logic branch of the state-machine.

Key Characteristics
-------------------
• Deterministic 2-D rigid-body dynamics (semi-implicit Euler)  
• Minimal, allocation-free hot path suitable for cold-start constrained Lambdas  
• Pure-Python reference implementation; heavy workloads are expected to be
  delegated to the GPU-accelerated `physics-worker` Fargate task but this module
  is sufficient for turn-based or low-tick-rate simulations.  
• JSON-serialisable entities for effortless inter-service transport

Exported Symbols
----------------
PhysicsWorld   – Container object holding global simulation parameters  
Body           – Dataclass representing a rigid body  
PhysicsError   – Root exception for all physics-related failures  
step_simulation(event, /) – Functional façade used by Step Functions  
lambda_handler – Convenience AWS Lambda handler  

The implementation purposefully lives in `__init__.py` to keep import-times low
on cold starts while presenting a single, concise import path:
`from ledgerquest.engine.physics import step_simulation`.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, getcontext
from typing import Iterable, List, MutableSequence, Tuple

__all__ = [
    "PhysicsError",
    "Body",
    "PhysicsWorld",
    "step_simulation",
    "lambda_handler",
]

###############################################################################
# Logging & Numeric Precision
###############################################################################

logger = logging.getLogger("ledgerquest.physics")
_LOG_LEVEL = os.environ.get("LQ_PHYSICS_LOG_LEVEL", "INFO").upper()
logger.setLevel(_LOG_LEVEL)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter(
        "[%(levelname)s] %(asctime)s — %(name)s:%(lineno)d — %(message)s"
    )
)
if not logger.handlers:
    logger.addHandler(handler)

# Increase decimal precision for deterministic math if requested
_DECIMAL_PRECISION = int(os.environ.get("LQ_PHYSICS_DEC_PRECISION", 10))
getcontext().prec = _DECIMAL_PRECISION


###############################################################################
# Exceptions
###############################################################################


class PhysicsError(RuntimeError):
    """Base-class for physics-layer exceptions."""


###############################################################################
# Data Models
###############################################################################


@dataclass
class Body:
    """
    Serializable 2-D rigid body.

    Attributes
    ----------
    id : str
        Unique identifier referencing the ECS entity ID.
    mass : float
        Non-zero mass (kg).  Infinite mass ≅ locked object ⇒ use `float("inf")`.
    position : Tuple[float, float]
        Current world coordinates in metres.
    velocity : Tuple[float, float]
        Current velocity vector (m/s).
    size : Tuple[float, float]
        AABB half-extents in metres (for cheap collision detection).
    force_accum : Tuple[float, float]
        Force accumulator used within the integration step; not persisted.
    restitution : float
        Coefficient of restitution for collision response (0 – 1).
    """

    id: str
    mass: float
    position: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))
    velocity: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))
    size: Tuple[float, float] = field(default_factory=lambda: (0.5, 0.5))
    force_accum: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))
    restitution: float = 0.2

    # ---------------------------- Runtime Helpers ---------------------------- #

    @property
    def inv_mass(self) -> float:
        """Pre-computed inverse mass for integration; 0 for immovable bodies."""
        if math.isinf(self.mass) or self.mass == 0.0:
            return 0.0
        return 1.0 / self.mass

    def apply_force(self, fx: float, fy: float) -> None:
        """Accumulate force until the next integration tick."""
        ax, ay = self.force_accum
        self.force_accum = (ax + fx, ay + fy)

    # ---------------------------- Serialisation ----------------------------- #

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def from_json(raw: str | bytes) -> "Body":
        try:
            data = json.loads(raw)
            return Body(**data)
        except (TypeError, ValueError) as exc:
            raise PhysicsError("Failed to deserialize Body") from exc


@dataclass
class PhysicsWorld:
    """
    Container for immutable per-step parameters.

    Parameters
    ----------
    gravity : Tuple[float, float]  – Gravity vector in m/s²
    dt      : float                – Simulation time-step in seconds
    """

    gravity: Tuple[float, float] = (0.0, -9.81)
    dt: float = 1.0 / 60.0  # 60 Hz

    # ----------------------- Configuration Validation ----------------------- #

    def __post_init__(self) -> None:
        if self.dt <= 0:
            raise PhysicsError("`dt` must be positive")


###############################################################################
# Internal Utilities
###############################################################################


def _vector_add(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
    return a[0] + b[0], a[1] + b[1]


def _vector_mul(a: Tuple[float, float], scalar: float) -> Tuple[float, float]:
    return a[0] * scalar, a[1] * scalar


###############################################################################
# Core Integration & Collision
###############################################################################


def _integrate_bodies(world: PhysicsWorld, bodies: MutableSequence[Body]) -> None:
    """
    Semi-implicit Euler integration.

    Mutates the supplied list *in place* (minimal allocations for Lambda).
    """
    gx, gy = world.gravity
    dt = world.dt

    for body in bodies:
        inv_mass = body.inv_mass
        if inv_mass == 0.0:
            # Static body
            continue

        # Acceleration = (gravity * mass) + ΣF / m
        fx, fy = body.force_accum
        ax = gx + fx * inv_mass
        ay = gy + fy * inv_mass

        # v  ← v + a·dt
        vx, vy = body.velocity
        vx += ax * dt
        vy += ay * dt

        # p ← p + v·dt
        px, py = body.position
        px += vx * dt
        py += vy * dt

        # Commit
        body.velocity = (vx, vy)
        body.position = (px, py)

        # Reset accumulator
        body.force_accum = (0.0, 0.0)


def _aabb_overlap(a: Body, b: Body) -> bool:
    ax, ay = a.position
    bx, by = b.position
    aw, ah = a.size
    bw, bh = b.size

    return (
        abs(ax - bx) <= (aw + bw)
        and abs(ay - by) <= (ah + bh)
    )


def _resolve_collision(a: Body, b: Body) -> None:
    """
    Elastic collision resolution using impulse scalar.

    The function assumes an overlap already occurred; penetration fixing is
    omitted for brevity—it should be handled by a positional correction pass in
    production systems.
    """
    # Relative velocity
    rv_x = b.velocity[0] - a.velocity[0]
    rv_y = b.velocity[1] - a.velocity[1]

    # Collision normal (approx.)
    nx = 1.0 if a.position[0] < b.position[0] else -1.0
    ny = 1.0 if a.position[1] < b.position[1] else -1.0

    # Relative velocity along the normal
    vel_along_normal = rv_x * nx + rv_y * ny
    if vel_along_normal > 0:
        # Objects are moving apart
        return

    # Calculate restitution
    e = min(a.restitution, b.restitution)

    # Calculate impulse scalar
    inv_mass_sum = a.inv_mass + b.inv_mass
    if inv_mass_sum == 0:
        return  # Both objects immovable

    j = -(1 + e) * vel_along_normal
    j /= inv_mass_sum

    impulse_x = j * nx
    impulse_y = j * ny

    # Apply impulses
    if a.inv_mass != 0.0:
        ax, ay = a.velocity
        a.velocity = (ax - impulse_x * a.inv_mass, ay - impulse_y * a.inv_mass)

    if b.inv_mass != 0.0:
        bx, by = b.velocity
        b.velocity = (bx + impulse_x * b.inv_mass, by + impulse_y * b.inv_mass)


def _broad_phase_collisions(bodies: List[Body]) -> List[Tuple[int, int]]:
    """
    Naïve N² broad phase suitable for ≤100 bodies.  Production deployments
    should leverage spatial partitioning (BVH, uniform grid, etc.).

    Returns a list of (index_i, index_j) pairs referencing colliding bodies.
    """
    collisions: List[Tuple[int, int]] = []
    count = len(bodies)
    for i in range(count):
        for j in range(i + 1, count):
            if _aabb_overlap(bodies[i], bodies[j]):
                collisions.append((i, j))
    return collisions


###############################################################################
# Public API
###############################################################################


def step_simulation(event: dict | str) -> dict:
    """
    Pure function that executes a single physics step.

    Parameters
    ----------
    event : dict | str
        JSON string or object with keys:
        • "world": { "gravity": [gx, gy], "dt": 0.016 }
        • "bodies": [ {Body JSON… }, … ]

    Returns
    -------
    dict
        Same schema as input with mutated body state
    """
    started_at = time.perf_counter()

    # ------------------------- Decode and Validate -------------------------- #
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except (TypeError, ValueError) as exc:
            logger.error("Malformed event JSON")
            raise PhysicsError("step_simulation: invalid JSON payload") from exc

    try:
        world_cfg = event["world"]
        bodies_cfg = event["bodies"]
    except KeyError as exc:
        raise PhysicsError("Missing required keys in physics payload") from exc

    world = PhysicsWorld(
        gravity=tuple(world_cfg.get("gravity", (0.0, -9.81))),
        dt=float(world_cfg.get("dt", 1.0 / 60.0)),
    )

    bodies: List[Body] = []
    for blob in bodies_cfg:
        bodies.append(Body(**blob))

    if not bodies:
        logger.debug("No bodies supplied; skipping integration.")
        return event  # Nothing to simulate

    # ---------------------------- Integrate Step ---------------------------- #
    _integrate_bodies(world, bodies)

    # ------------------------ Collision Detection --------------------------- #
    pairs = _broad_phase_collisions(bodies)
    for i, j in pairs:
        _resolve_collision(bodies[i], bodies[j])

    # ----------------------------- Encode ----------------------------------- #
    event["bodies"] = [asdict(b) for b in bodies]

    duration_ms = (time.perf_counter() - started_at) * 1000
    logger.debug("Physics step completed in %.2f ms", duration_ms)
    return event


# ------------------------------------------------------------------------------
# AWS Lambda entry-point
# ------------------------------------------------------------------------------


def lambda_handler(event, context):  # noqa: D401
    """
    AWS Lambda handler delegating to :pyfunc:`step_simulation`.

    The handler is intentionally thin to minimise cold-start overhead.

    Notes
    -----
    • `context` is ignored but kept for AWS interface compatibility.  
    • Any uncaught :class:`PhysicsError` will translate into a 500 response when
      executed behind API Gateway.  Consider trapping and mapping to structured
      error JSON if exposing directly to clients.
    """
    try:
        return step_simulation(event)
    except PhysicsError as exc:
        logger.exception("Physics simulation failed")
        # Bubble up the error to Step Functions – it will be handled by the saga
        raise exc
```