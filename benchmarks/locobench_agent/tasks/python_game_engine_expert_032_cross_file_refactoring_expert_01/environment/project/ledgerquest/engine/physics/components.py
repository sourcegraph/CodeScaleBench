```python
"""
ledgerquest.engine.physics.components
-------------------------------------

Entity-Component definitions used by the Physics subsystem of LedgerQuest Engine.
These components are designed to be *pure data* containers with minimum logic,
so they can be freely serialized and stored in external state stores such as
Amazon DynamoDB or S3, yet still contain utility helpers that make authoring
gameplay-code convenient.

Notes
-----
1. Only deterministic, side-effect-free helpers are implemented here. Heavy-duty
   numerical work (broad-phase collision queries, rigid-body solvers, etc.)
   is executed by specialised simulation Lambdas or GPU workers.
2. All components implement a common `serialise()` / `deserialise()` interface
   because Statemachines in LedgerQuest exchange payloads as JSON.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Type, TypeVar, Any, Optional, Mapping

__all__ = [
    "Vector3",
    "Quaternion",
    "BodyType",
    "TransformComponent",
    "RigidBodyComponent",
    "ColliderComponent",
    "BoxCollider",
    "SphereCollider",
]


class SerialisationError(RuntimeError):
    """Raised when component serialisation or deserialisation fails."""


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class Vector3:
    """
    Immutable 3-component vector with common operators overloaded. The class is
    intentionally minimal to keep the module dependency-free.

    Operations are safe for basic gameplay but *not* optimised for SIMD.
    """

    x: float
    y: float
    z: float

    # ------------------------------------------------------------------ magic

    def __add__(self, other: "Vector3") -> "Vector3":
        return Vector3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vector3") -> "Vector3":
        return Vector3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> "Vector3":  # type: ignore[override]
        return Vector3(self.x * scalar, self.y * scalar, self.z * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar: float) -> "Vector3":
        if scalar == 0.0:
            raise ZeroDivisionError("Division by zero in Vector3")
        return Vector3(self.x / scalar, self.y / scalar, self.z / scalar)

    # ------------------------------------------------------------- utilities

    @property
    def magnitude(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def normalised(self) -> "Vector3":
        mag = self.magnitude
        if mag == 0.0:
            return Vector3(0.0, 0.0, 0.0)
        return self / mag

    def lerp(self, other: "Vector3", t: float) -> "Vector3":
        """Linear interpolation between self and other."""
        return self * (1.0 - t) + other * t

    # ------------------------------------------------------------- mapping

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Vector3":
        try:
            return cls(float(data["x"]), float(data["y"]), float(data["z"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise SerialisationError("Invalid Vector3 data") from exc


@dataclass(frozen=True, slots=True)
class Quaternion:
    """
    Minimal quaternion representation for rotation. Only basic normalisation and
    slerp helpers are provided to avoid creeping complexity.
    """

    x: float
    y: float
    z: float
    w: float

    # --------------------------------------------------------------- helpers

    @property
    def normalised(self) -> "Quaternion":
        length = math.sqrt(self.x**2 + self.y**2 + self.z**2 + self.w**2)
        if length == 0.0:
            # Return identity quaternion to avoid NaNs
            return Quaternion(0.0, 0.0, 0.0, 1.0)
        inv = 1.0 / length
        return Quaternion(
            self.x * inv,
            self.y * inv,
            self.z * inv,
            self.w * inv,
        )

    def slerp(self, to: "Quaternion", t: float) -> "Quaternion":
        """
        Spherical linear interpolation with constant angular velocity.
        Implementation adapted from Ken Shoemake's algorithm.
        """
        # Compute the cosine of the angle
        cos_theta = (
            self.x * to.x + self.y * to.y + self.z * to.z + self.w * to.w
        )

        # If cos_theta < 0, the interpolation will take the long way around.
        # Fix by reversing one quaternion.
        if cos_theta < 0.0:
            to = Quaternion(-to.x, -to.y, -to.z, -to.w)
            cos_theta = -cos_theta

        # If the quaternions are very close, fall back to linear interpolation
        if cos_theta > 0.95:
            x = self.x + t * (to.x - self.x)
            y = self.y + t * (to.y - self.y)
            z = self.z + t * (to.z - self.z)
            w = self.w + t * (to.w - self.w)
            return Quaternion(x, y, z, w).normalised

        theta = math.acos(cos_theta)
        sin_theta = math.sqrt(1.0 - cos_theta * cos_theta)

        if abs(sin_theta) < 1e-5:
            return self

        ratio_a = math.sin((1.0 - t) * theta) / sin_theta
        ratio_b = math.sin(t * theta) / sin_theta

        return Quaternion(
            self.x * ratio_a + to.x * ratio_b,
            self.y * ratio_a + to.y * ratio_b,
            self.z * ratio_a + to.z * ratio_b,
            self.w * ratio_a + to.w * ratio_b,
        )

    # ------------------------------------------------------------- mapping
    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Quaternion":
        try:
            return cls(
                float(data["x"]),
                float(data["y"]),
                float(data["z"]),
                float(data["w"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise SerialisationError("Invalid Quaternion data") from exc


# --------------------------------------------------------------------------- #
# Core Components                                                             #
# --------------------------------------------------------------------------- #

class BodyType(str, Enum):
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"
    KINEMATIC = "KINEMATIC"


_COMPONENT_T = TypeVar("_COMPONENT_T", bound="BaseComponent")


class BaseComponent:
    """
    Base class for all physics components providing serialisation helpers and
    a common UUID identifier field allowing strongly-typed ECS storage.

    The UUID is generated only once at construction time so deterministic state
    can be maintained across simulation ticks.
    """

    __slots__ = ("_id",)

    def __init__(self, component_id: Optional[str] = None) -> None:
        self._id: str = component_id or str(uuid.uuid4())

    # --------------------------------------------------------------------- dunder

    def __repr__(self) -> str:  # pragma: no cover
        attrs = ", ".join(
            f"{k}={v!r}"
            for k, v in asdict(self).items()  # type: ignore[arg-type]
            if k != "_id"
        )
        return f"{self.__class__.__name__}({_id_short(self._id)}, {attrs})"

    # --------------------------------------------------------------------- serialisation

    def serialise(self) -> str:
        """
        Returns
        -------
        str
            Compact JSON representation suitable for Step Functions payloads.
        """
        payload = {"id": self._id, "type": self.__class__.__name__, "data": self._serialise_data()}
        return json.dumps(payload, separators=(",", ":"))

    @classmethod
    def deserialise(cls: Type[_COMPONENT_T], payload: str | bytes) -> _COMPONENT_T:
        """
        Restore component from JSON payload.

        Raises
        ------
        SerialisationError
            If the payload does not match the expected schema.
        """
        try:
            raw: Dict[str, Any] = json.loads(payload)
            if raw["type"] != cls.__name__:
                raise SerialisationError(
                    f"Incorrect component type: expected {cls.__name__}, got {raw['type']}"
                )
            component = cls._deserialise_data(raw["data"])  # type: ignore[arg-type]
            object.__setattr__(component, "_id", raw["id"])
            return component
        except (KeyError, TypeError, ValueError) as exc:
            raise SerialisationError("Failed to deserialise component") from exc

    # --------------------------------------------------------------------- internal

    def _serialise_data(self) -> Dict[str, Any]:  # noqa: D401
        raise NotImplementedError

    @classmethod
    def _deserialise_data(cls: Type[_COMPONENT_T], data: Dict[str, Any]) -> _COMPONENT_T:
        raise NotImplementedError

    # --------------------------------------------------------------------- api

    @property
    def id(self) -> str:
        """
        Globally unique identifier for the component instance. Used as the
        partition key when persisting to DynamoDB.
        """
        return self._id


# --------------------------------------------------------------------------- #
# Transform                                                                   #
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class TransformComponent(BaseComponent):
    """
    Spatial component that stores position, rotation, and scale.

    Transformations are always expressed in world space because the engine
    intentionally resolves parent/child hierarchies in a separate system in
    order to avoid circular dependencies between physics and rendering layers.
    """

    position: Vector3 = field(default_factory=lambda: Vector3(0.0, 0.0, 0.0))
    rotation: Quaternion = field(default_factory=lambda: Quaternion(0.0, 0.0, 0.0, 1.0))
    scale: Vector3 = field(default_factory=lambda: Vector3(1.0, 1.0, 1.0))

    # ------------------------------------------------------------------ helpers

    def translate(self, delta: Vector3) -> None:
        object.__setattr__(self, "position", self.position + delta)

    def rotate(self, delta: Quaternion) -> None:
        # Naïve quaternion multiplication (self.rotation = delta * self.rotation)
        r = self.rotation
        d = delta
        new_rotation = Quaternion(
            d.w * r.x + d.x * r.w + d.y * r.z - d.z * r.y,
            d.w * r.y - d.x * r.z + d.y * r.w + d.z * r.x,
            d.w * r.z + d.x * r.y - d.y * r.x + d.z * r.w,
            d.w * r.w - d.x * r.x - d.y * r.y - d.z * r.z,
        ).normalised
        object.__setattr__(self, "rotation", new_rotation)

    # ---------------------------------------------------------------- serialisation

    def _serialise_data(self) -> Dict[str, Any]:
        return {
            "pos": self.position.to_dict(),
            "rot": self.rotation.to_dict(),
            "scl": self.scale.to_dict(),
        }

    @classmethod
    def _deserialise_data(cls, data: Dict[str, Any]) -> "TransformComponent":
        return cls(
            position=Vector3.from_dict(data["pos"]),
            rotation=Quaternion.from_dict(data["rot"]),
            scale=Vector3.from_dict(data["scl"]),
        )


# --------------------------------------------------------------------------- #
# Rigid Body                                                                  #
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class RigidBodyComponent(BaseComponent):
    """
    Stores physical properties required by the rigid-body solver.

    The component is intentionally simple; advanced constraints (hinges, motors,
    etc.) live in their own dedicated components to keep things composable.
    """

    body_type: BodyType = BodyType.DYNAMIC
    mass: float = 1.0
    velocity: Vector3 = field(default_factory=lambda: Vector3(0.0, 0.0, 0.0))
    acceleration: Vector3 = field(default_factory=lambda: Vector3(0.0, 0.0, 0.0))
    linear_damping: float = 0.01      # simple exponential decay
    restitution: float = 0.2          # bounciness
    friction: float = 0.5

    # ------------------------------------------------------------------ helpers

    def apply_force(self, force: Vector3) -> None:
        """
        F = m * a  -> a = F / m
        Accumulate acceleration for the next integration step.
        """
        if self.body_type != BodyType.DYNAMIC:
            return
        incremental_acc = force / self.mass
        object.__setattr__(self, "acceleration", self.acceleration + incremental_acc)

    def integrate(self, transform: TransformComponent, dt: float) -> None:
        """
        Semi-implicit Euler integration step. Only executed in the simulation
        Lambda, never inside the API Gateway handler.

        Parameters
        ----------
        transform:
            TransformComponent of the owning entity. Updated in-place.
        dt:
            Delta-time in seconds.
        """
        if self.body_type != BodyType.DYNAMIC:
            return

        # Update velocity
        vel = (self.velocity + self.acceleration * dt) * (1.0 - self.linear_damping)
        object.__setattr__(self, "velocity", vel)

        # Update position
        transform.translate(vel * dt)

        # Reset acceleration for next frame
        object.__setattr__(self, "acceleration", Vector3(0.0, 0.0, 0.0))

    # ---------------------------------------------------------------- serialisation

    def _serialise_data(self) -> Dict[str, Any]:
        return {
            "type": self.body_type.value,
            "mass": self.mass,
            "vel": self.velocity.to_dict(),
            "acc": self.acceleration.to_dict(),
            "damping": self.linear_damping,
            "rest": self.restitution,
            "fric": self.friction,
        }

    @classmethod
    def _deserialise_data(cls, data: Dict[str, Any]) -> "RigidBodyComponent":
        return cls(
            body_type=BodyType(data["type"]),
            mass=float(data["mass"]),
            velocity=Vector3.from_dict(data["vel"]),
            acceleration=Vector3.from_dict(data["acc"]),
            linear_damping=float(data["damping"]),
            restitution=float(data["rest"]),
            friction=float(data["fric"]),
        )


# --------------------------------------------------------------------------- #
# Colliders                                                                   #
# --------------------------------------------------------------------------- #

class ColliderComponent(BaseComponent):
    """
    Abstract base class for collider shapes. Concrete shapes must implement the
    `bounding_radius` property so that broad-phase culling can be cheaply
    executed. Narrow-phase collision detection is handled elsewhere.
    """

    def __init__(
        self,
        is_trigger: bool = False,
        component_id: Optional[str] = None,
    ) -> None:
        super().__init__(component_id=component_id)
        self.is_trigger: bool = is_trigger

    # ------------------------------------------------------------- interface
    @property
    def bounding_radius(self) -> float:  # noqa: D401
        raise NotImplementedError

    # ------------------------------------------------------------- serialisation
    def _serialise_data(self) -> Dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def _deserialise_data(cls: Type[_COMPONENT_T], data: Dict[str, Any]) -> _COMPONENT_T:
        raise NotImplementedError

    # -------------------------------------------------------------------- helper
    def overlaps(self, other: "ColliderComponent", self_pos: Vector3, other_pos: Vector3) -> bool:
        """
        Quick sphere-radius overlap test. Concrete shapes override this method
        to provide precise checks if required.
        """
        combined_radius = self.bounding_radius + other.bounding_radius
        dist_sq = (self_pos.x - other_pos.x) ** 2 + (self_pos.y - other_pos.y) ** 2 + (self_pos.z - other_pos.z) ** 2
        return dist_sq <= combined_radius * combined_radius


@dataclass(slots=True)
class SphereCollider(ColliderComponent):
    """
    Sphere collider used for simple characters, projectiles, etc.
    """

    radius: float = 0.5

    # ---------------------------------------------------------------- serialisation
    def _serialise_data(self) -> Dict[str, Any]:
        return {"shape": "Sphere", "radius": self.radius, "trigger": self.is_trigger}

    @classmethod
    def _deserialise_data(cls, data: Dict[str, Any]) -> "SphereCollider":
        return cls(is_trigger=bool(data["trigger"]), radius=float(data["radius"]))

    # ---------------------------------------------------------------- properties
    @property
    def bounding_radius(self) -> float:
        return self.radius


@dataclass(slots=True)
class BoxCollider(ColliderComponent):
    """
    Axis-aligned bounding box (AABB) collider. For simplicity the box is stored
    in *local* space and always aligned to the world axes—rotation handling is
    delegated to a different component (e.g., `OBBComponent` for oriented boxes).
    """

    half_extents: Vector3 = field(
        default_factory=lambda: Vector3(0.5, 0.5, 0.5)
    )  # half-sizes along each axis

    # ---------------------------------------------------------------- serialisation
    def _serialise_data(self) -> Dict[str, Any]:
        return {
            "shape": "Box",
            "half_ext": self.half_extents.to_dict(),
            "trigger": self.is_trigger,
        }

    @classmethod
    def _deserialise_data(cls, data: Dict[str, Any]) -> "BoxCollider":
        return cls(
            is_trigger=bool(data["trigger"]),
            half_extents=Vector3.from_dict(data["half_ext"]),
        )

    # ---------------------------------------------------------------- properties
    @property
    def bounding_radius(self) -> float:
        # Sphere radius that encloses the box
        hx, hy, hz = self.half_extents.x, self.half_extents.y, self.half_extents.z
        return math.sqrt(hx * hx + hy * hy + hz * hz)

    # ---------------------------------------------------------------- narrow phase
    def overlaps(self, other: ColliderComponent, self_pos: Vector3, other_pos: Vector3) -> bool:
        """
        Box vs Sphere or Box vs Box intersection—fallback to the simple radius
        test for cross-shape combinations not implemented here.
        """
        if isinstance(other, BoxCollider):
            # AABB vs AABB
            min_a = Vector3(
                self_pos.x - self.half_extents.x,
                self_pos.y - self.half_extents.y,
                self_pos.z - self.half_extents.z,
            )
            max_a = Vector3(
                self_pos.x + self.half_extents.x,
                self_pos.y + self.half_extents.y,
                self_pos.z + self.half_extents.z,
            )
            min_b = Vector3(
                other_pos.x - other.half_extents.x,
                other_pos.y - other.half_extents.y,
                other_pos.z - other.half_extents.z,
            )
            max_b = Vector3(
                other_pos.x + other.half_extents.x,
                other_pos.y + other.half_extents.y,
                other_pos.z + other.half_extents.z,
            )
            return (
                min_a.x <= max_b.x
                and max_a.x >= min_b.x
                and min_a.y <= max_b.y
                and max_a.y >= min_b.y
                and min_a.z <= max_b.z
                and max_a.z >= min_b.z
            )
        else:
            # Fallback to sphere radius overlap
            return super().overlaps(other, self_pos, other_pos)


# --------------------------------------------------------------------------- #
# Utility                                                                     #
# --------------------------------------------------------------------------- #

def _id_short(full_id: str) -> str:
    """Return an abbreviated form of a UUID for debug strings."""
    return full_id.split("-")[0]
```