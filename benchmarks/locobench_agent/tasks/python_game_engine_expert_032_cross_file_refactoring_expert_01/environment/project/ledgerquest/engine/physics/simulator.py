```python
"""
LedgerQuest Engine – Physics Simulator
======================================

This module contains a stateless physics simulator that is intended to be
invoked as an AWS Lambda (or any FaaS runtime).  The simulator receives a
serialized “world-slice” describing entities that contain physics components,
advances the simulation by `delta_time`, and returns the new state.

Unlike traditional long-running simulations, LedgerQuest keeps no in-memory
state between invocations—making the update routine *purely functional* and
therefore horizontally scalable.  Long-lived state is externalised to
DynamoDB/S3 by higher-level orchestration layers.

Key Features
------------
• 2-D rigid-body integration with semi-implicit Euler
• Broad-phase AABB collision culling
• Narrow-phase contact resolution (elastic impulse)
• Deterministic float math w/ configurable tolerance
• Structured logging for audit/trace pipelines
• Graceful error handling with typed exceptions

Notes
-----
This implementation purposely avoids heavyweight, C-accelerated libraries
(e.g. PyBox2D, Pymunk) so that it can run inside Lambda’s execution limits
without native extensions.  If you deploy this in a container with those
libraries available, simply replace the math backend while keeping the
function signatures stable.
"""
from __future__ import annotations

import json
import logging
import math
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Tuple

# -----------------------------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------------------------

LOG_LEVEL = os.getenv("LEDGERQUEST_PHYSICS_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ledgerquest.engine.physics.simulator")


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------

class PhysicsError(RuntimeError):
    """Base-class for physics-simulation errors."""


class DeserializationError(PhysicsError):
    """Invalid or malformed input payload raised during deserialization."""


class SimulationInvariantViolation(PhysicsError):
    """Raised when the simulation produces a non-finite or invalid result."""


# -----------------------------------------------------------------------------
# Math Primitives
# -----------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class Vec2:
    """Immutable 2-D vector with basic operations—fast enough for small N."""
    x: float
    y: float

    # ------------------------------------------------------------------
    # Vector arithmetic
    # ------------------------------------------------------------------
    def __add__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vec2":
        return Vec2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def dot(self, other: "Vec2") -> float:
        return (self.x * other.x) + (self.y * other.y)

    def magnitude(self) -> float:
        return math.hypot(self.x, self.y)

    def normalize(self) -> "Vec2":
        mag = self.magnitude() or 1.0
        return Vec2(self.x / mag, self.y / mag)

    def perpendicular(self) -> "Vec2":
        """Right-handed perpendicular vector (rotated 90°)."""
        return Vec2(-self.y, self.x)

    # ------------------------------------------------------------------
    # Built-ins helpers
    # ------------------------------------------------------------------
    def __iter__(self):
        yield self.x
        yield self.y

    def to_json(self) -> Tuple[float, float]:
        return self.x, self.y

    @staticmethod
    def from_iterable(it: Iterable[float]) -> "Vec2":
        x, y, *_ = it
        return Vec2(float(x), float(y))


# -----------------------------------------------------------------------------
# Physics Data Structures
# -----------------------------------------------------------------------------

@dataclass(slots=True)
class AABB:
    """Axis-Aligned Bounding Box used for broad-phase collision tests."""
    min: Vec2
    max: Vec2

    def overlaps(self, other: "AABB") -> bool:
        return (
            self.max.x >= other.min.x
            and self.min.x <= other.max.x
            and self.max.y >= other.min.y
            and self.min.y <= other.max.y
        )

    @classmethod
    def from_center(cls, center: Vec2, half_extents: Vec2) -> "AABB":
        return cls(
            min=center - half_extents,
            max=center + half_extents,
        )


@dataclass(slots=True)
class RigidBody:
    """
    Minimal rigid-body representation.

    Only rectangle shapes are supported in this reference implementation, but
    the component data model can be extended without changing the simulator’s
    public interface.
    """
    id: str
    position: Vec2
    velocity: Vec2
    half_extents: Vec2  # half-width/height (meters)
    mass: float = 1.0
    restitution: float = 0.5
    static: bool = False
    # Non-serialized runtime fields
    force_acc: Vec2 = field(default_factory=lambda: Vec2(0.0, 0.0), repr=False)

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------
    @property
    def inv_mass(self) -> float:
        """Inverse mass—0 for static or infinite-mass bodies."""
        return 0.0 if self.static else 1.0 / self.mass

    @property
    def aabb(self) -> AABB:
        return AABB.from_center(self.position, self.half_extents)

    def apply_force(self, force: Vec2):
        """Accumulate force for the current frame (F = m * a)."""
        if not self.static:
            self.force_acc = self.force_acc + force


# -----------------------------------------------------------------------------
# Physics Simulator
# -----------------------------------------------------------------------------

class PhysicsSimulator:
    """
    Stateless 2-D physics simulator.

    Usage (inside Lambda):
    ----------------------
    def handler(event, context):
        return PhysicsSimulator.lambda_handler(event, context)
    """

    # Gravity can be overridden at runtime via env-var for gameplay tuning.
    GRAVITY = Vec2(
        float(os.getenv("LEDGERQUEST_GRAVITY_X", "0")),
        float(os.getenv("LEDGERQUEST_GRAVITY_Y", "-9.81")),
    )

    # Velocity threshold below which bodies will be considered “sleeping”.
    SLEEP_TOLERANCE = float(os.getenv("LEDGERQUEST_SLEEP_TOLERANCE", "0.01"))

    # Safe-guard to avoid unbounded compute for huge payloads.
    MAX_BODIES_PER_INVOCATION = int(os.getenv("LEDGERQUEST_MAX_BODIES", "512"))

    # ------------------------------------------------------------------
    # Lambda Entrypoint
    # ------------------------------------------------------------------
    @classmethod
    def lambda_handler(cls, event, _context):
        """
        AWS Lambda handler. Receives JSON payload:
        {
          "delta_time": 0.016,
          "bodies": [
              {
                  "id": "entity-uuid",
                  "position": [x, y],
                  "velocity": [vx, vy],
                  "half_extents": [hx, hy],
                  "mass": 1.0,
                  "restitution": 0.5,
                  "static": false
              },
              ...
          ]
        }
        """
        try:
            world_state = cls._deserialize_event(event)
        except DeserializationError as exc:
            logger.exception("Invalid input payload.")
            raise

        logger.debug("Simulating %d bodies (dt=%.6f)",
                     len(world_state), event["delta_time"])

        cls._validate_payload_size(len(world_state))

        cls._integrate(world_state, event["delta_time"])
        cls._broad_and_narrow_phase(world_state)

        # Prepare JSON-serialisable response
        response = {
            "bodies": [
                {
                    "id": body.id,
                    "position": body.position.to_json(),
                    "velocity": body.velocity.to_json(),
                }
                for body in world_state
            ]
        }
        return json.dumps(response)

    # ------------------------------------------------------------------
    # Public helper for unit tests or in-process calls
    # ------------------------------------------------------------------
    @classmethod
    def step(
        cls,
        bodies: List[RigidBody],
        delta_time: float,
        *,
        apply_gravity: bool = True,
    ) -> List[RigidBody]:
        """
        Advance simulation by `delta_time` and return *mutated* bodies list.

        The method is kept pure: no network, no I/O, no global state mutation,
        which makes it deterministic and easy to unit-test.
        """
        if apply_gravity:
            for body in bodies:
                if not body.static:
                    body.apply_force(cls.GRAVITY * body.mass)

        cls._integrate(bodies, delta_time)
        cls._broad_and_narrow_phase(bodies)
        return bodies

    # ------------------------------------------------------------------
    # Internal – Payload (de)serialization
    # ------------------------------------------------------------------
    @staticmethod
    def _deserialize_event(event: Dict) -> List[RigidBody]:
        """
        Convert the inbound JSON event into a list of `RigidBody` instances.
        Raises `DeserializationError` when invalid.
        """
        try:
            bodies_payload = event["bodies"]
            delta_time = float(event["delta_time"])
            if delta_time <= 0.0 or not math.isfinite(delta_time):
                raise ValueError("delta_time must be positive and finite.")
        except (KeyError, TypeError, ValueError) as exc:
            raise DeserializationError(str(exc)) from exc

        bodies = []
        for raw in bodies_payload:
            try:
                body = RigidBody(
                    id=raw.get("id") or str(uuid.uuid4()),
                    position=Vec2.from_iterable(raw["position"]),
                    velocity=Vec2.from_iterable(raw["velocity"]),
                    half_extents=Vec2.from_iterable(raw["half_extents"]),
                    mass=float(raw.get("mass", 1.0)),
                    restitution=float(raw.get("restitution", 0.5)),
                    static=bool(raw.get("static", False)),
                )
                bodies.append(body)
            except Exception as exc:
                raise DeserializationError(
                    f"Malformed body entry: {raw}"
                ) from exc

        return bodies

    @classmethod
    def _validate_payload_size(cls, n: int):
        if n > cls.MAX_BODIES_PER_INVOCATION:
            raise PhysicsError(
                f"Too many bodies for a single invocation "
                f"({n} > {cls.MAX_BODIES_PER_INVOCATION})."
            )

    # ------------------------------------------------------------------
    # Internal – Integration
    # ------------------------------------------------------------------
    @staticmethod
    def _integrate(bodies: Iterable[RigidBody], dt: float):
        """Semi-implicit Euler integration."""
        for body in bodies:
            if body.static:
                continue

            # a = F * inv_mass
            acceleration = body.force_acc * body.inv_mass
            body.velocity = body.velocity + acceleration * dt
            body.position = body.position + body.velocity * dt

            # Clear forces for next frame
            body.force_acc = Vec2(0.0, 0.0)

            # Sleep optimisation
            if body.velocity.magnitude() < PhysicsSimulator.SLEEP_TOLERANCE:
                body.velocity = Vec2(0.0, 0.0)

            # Post-integration invariant check
            if (
                not math.isfinite(body.position.x)
                or not math.isfinite(body.position.y)
            ):
                raise SimulationInvariantViolation(
                    f"Non-finite position for body {body.id}"
                )

    # ------------------------------------------------------------------
    # Internal – Collision Phases
    # ------------------------------------------------------------------
    @staticmethod
    def _broad_and_narrow_phase(bodies: List[RigidBody]):
        """
        Perform broad-phase AABB checks followed by narrow-phase impulse
        resolution for overlapping pairs.
        """
        # Simple N^2 broadphase due to low `MAX_BODIES_PER_INVOCATION`.
        for i, a in enumerate(bodies):
            if a.static:
                continue
            for b in bodies[i + 1 :]:
                # Skip pairs with two static bodies
                if a.static and b.static:
                    continue

                if not a.aabb.overlaps(b.aabb):
                    continue  # broad-phase cull

                PhysicsSimulator._resolve_collision(a, b)

    # ------------------------------------------------------------------
    # Internal – Narrow-phase Resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_collision(a: RigidBody, b: RigidBody):
        """
        Very small subset of SAT—for axis-aligned rectangles only.
        Calculates penetration depth along each axis and resolves along the
        axis of least penetration.
        """
        # Relative vector
        n = b.position - a.position

        # Overlap on x axis
        x_overlap = (a.half_extents.x + b.half_extents.x) - abs(n.x)
        if x_overlap <= 0:
            return  # no collision

        # Overlap on y axis
        y_overlap = (a.half_extents.y + b.half_extents.y) - abs(n.y)
        if y_overlap <= 0:
            return  # no collision

        # Find axis of least penetration
        if x_overlap < y_overlap:
            mtv = Vec2(x_overlap if n.x > 0 else -x_overlap, 0)
        else:
            mtv = Vec2(0, y_overlap if n.y > 0 else -y_overlap)

        # Positional correction (minimum translation vector)
        PhysicsSimulator._positional_correction(a, b, mtv)

        # Relative velocity
        rv = b.velocity - a.velocity
        # Normal is direction of MTV
        normal = mtv.normalize()

        vel_along_normal = rv.dot(normal)
        if vel_along_normal > 0:
            return  # bodies separating

        restitution = min(a.restitution, b.restitution)

        # Impulse scalar
        j = -(1 + restitution) * vel_along_normal
        inv_mass_sum = a.inv_mass + b.inv_mass
        if inv_mass_sum == 0:
            return

        j /= inv_mass_sum

        # Apply impulse
        impulse = normal * j
        if not a.static:
            a.velocity = a.velocity - impulse * a.inv_mass
        if not b.static:
            b.velocity = b.velocity + impulse * b.inv_mass

    # ------------------------------------------------------------------
    # Internal – Positional Correction
    # ------------------------------------------------------------------
    @staticmethod
    def _positional_correction(a: RigidBody, b: RigidBody, mtv: Vec2):
        """
        Positional correction to avoid sinking due to numerical errors.
        """
        percent = 0.8  # higher percentage = more correction
        slop = 0.01    # penetration allowance
        correction_magnitude = max(mtv.magnitude() - slop, 0.0) * percent
        correction = mtv.normalize() * correction_magnitude

        total_inv_mass = a.inv_mass + b.inv_mass
        if total_inv_mass == 0:
            return

        if not a.static:
            a.position = a.position - correction * (a.inv_mass / total_inv_mass)
        if not b.static:
            b.position = b.position + correction * (b.inv_mass / total_inv_mass)


# -----------------------------------------------------------------------------
# Module test hook (executed only when run locally)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Quick sanity test – two boxes falling onto the floor.
    ground = RigidBody(
        id="ground",
        position=Vec2(0.0, -1.0),
        velocity=Vec2(0.0, 0.0),
        half_extents=Vec2(5.0, 0.5),
        static=True,
    )

    box = RigidBody(
        id="box",
        position=Vec2(0.0, 2.0),
        velocity=Vec2(0.0, 0.0),
        half_extents=Vec2(0.5, 0.5),
        mass=1.0,
        restitution=0.3,
    )

    bodies = [ground, box]
    dt = 1.0 / 60.0

    for frame in range(240):  # 4 seconds
        PhysicsSimulator.step(bodies, dt)
        logger.info(
            "Frame %03d | pos=%.3f, %.3f vel=%.3f, %.3f",
            frame,
            box.position.x,
            box.position.y,
            box.velocity.x,
            box.velocity.y,
        )
```