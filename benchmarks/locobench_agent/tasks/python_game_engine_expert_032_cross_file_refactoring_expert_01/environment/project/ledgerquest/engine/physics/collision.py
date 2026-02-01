```python
"""
ledgerquest.engine.physics.collision
====================================

Pure-python, dependency-free collision detection & resolution helpers
used by the serverless physics simulation Lambda.  All functions are
pure (side-effect free) so that they can be invoked concurrently in a
stateless environment and their results serialised back to DynamoDB or
Step-Functions with no hidden globals.

The module purposefully limits itself to 2-D collisions—most
LedgerQuest business simulations render on a 2-D canvas even when they
display an isometric, pseudo-3-D perspective in the client.

If you need 3-D or GPU-accelerated collisions, spin up a Fargate worker
and use the engine’s C++ / CUDA back-end instead.
"""
from __future__ import annotations

import math
import itertools
from enum import Enum
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple


__all__ = [
    "Vector2",
    "ShapeType",
    "Collider",
    "AABBCollider",
    "CircleCollider",
    "CollisionManifold",
    "detect_collisions",
    "resolve_collision",
    "broad_phase_quadtree",
]


# ------------------------------------------------------------------------------
# Vector helpers
# ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Vector2:
    """
    Minimal 2-D vector to avoid pulling in numpy for Lambda size limits.
    Operations always return NEW objects to keep functional purity.
    """

    x: float
    y: float

    # ------------------------------------------------------------------
    # Basic arithmetic
    # ------------------------------------------------------------------

    def __add__(self, other: "Vector2") -> "Vector2":
        return Vector2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vector2") -> "Vector2":
        return Vector2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vector2":
        return Vector2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def dot(self, other: "Vector2") -> float:
        return self.x * other.x + self.y * other.y

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y

    def length(self) -> float:
        return math.sqrt(self.length_sq())

    def normalized(self) -> "Vector2":
        l = self.length()
        if l == 0.0:
            # Return a zero vector instead of raising to keep algorithms simple.
            return Vector2(0.0, 0.0)
        return Vector2(self.x / l, self.y / l)

    def perp(self) -> "Vector2":
        """Return a vector perpendicular to this one."""
        return Vector2(-self.y, self.x)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __iter__(self):
        yield self.x
        yield self.y

    def __repr__(self) -> str:  # pragma: no cover
        return f"Vector2({self.x:.4f}, {self.y:.4f})"


# ------------------------------------------------------------------------------
# Collider types
# ------------------------------------------------------------------------------

class ShapeType(str, Enum):
    CIRCLE = "circle"
    AABB = "aabb"


@dataclass(slots=True)
class Collider:
    """
    Base collider representation used in pure data form in the Lambda
    simulation.  It can be serialised to JSON directly because it only
    contains primitives.
    """

    shape: ShapeType
    position: Vector2
    # Additional user metadata (e.g. entity id) to correlate back on the client.
    user_data: Optional[str] = field(default=None)

    # API to satisfy static checkers—implemented by subclasses
    def bounding_radius(self) -> float:  # pragma: no cover
        raise NotImplementedError


@dataclass(slots=True)
class AABBCollider(Collider):
    half_extents: Vector2  # Positive half-widths

    def __init__(
        self,
        position: Vector2,
        half_extents: Vector2,
        user_data: Optional[str] = None,
    ) -> None:
        super().__init__(ShapeType.AABB, position, user_data)
        object.__setattr__(self, "half_extents", half_extents)

    @property
    def min(self) -> Vector2:
        return Vector2(self.position.x - self.half_extents.x, self.position.y - self.half_extents.y)

    @property
    def max(self) -> Vector2:
        return Vector2(self.position.x + self.half_extents.x, self.position.y + self.half_extents.y)

    # For broad-phase pruning
    def bounding_radius(self) -> float:
        return math.hypot(self.half_extents.x, self.half_extents.y)


@dataclass(slots=True)
class CircleCollider(Collider):
    radius: float

    def __init__(self, position: Vector2, radius: float, user_data: Optional[str] = None) -> None:
        super().__init__(ShapeType.CIRCLE, position, user_data)
        object.__setattr__(self, "radius", radius)

    def bounding_radius(self) -> float:
        return self.radius


# ------------------------------------------------------------------------------
# Collision manifold
# ------------------------------------------------------------------------------

@dataclass(slots=True)
class CollisionManifold:
    """
    Result of a narrow-phase collision test.
    """

    collided: bool
    normal: Vector2 = Vector2(0.0, 0.0)  # From A → B
    penetration: float = 0.0
    # Optional point(s) of contact—unused in this simplified implementation
    contacts: Tuple[Vector2, ...] = field(default_factory=tuple)

    # Entities participating so the caller knows what to resolve
    collider_a: Optional[Collider] = None
    collider_b: Optional[Collider] = None


# ------------------------------------------------------------------------------
# Narrow-phase detection
# ------------------------------------------------------------------------------

def _intersect_aabb_aabb(a: AABBCollider, b: AABBCollider) -> CollisionManifold:
    # Vector from A to B
    d = b.position - a.position

    overlap_x = a.half_extents.x + b.half_extents.x - abs(d.x)
    if overlap_x <= 0:
        return CollisionManifold(False, collider_a=a, collider_b=b)

    overlap_y = a.half_extents.y + b.half_extents.y - abs(d.y)
    if overlap_y <= 0:
        return CollisionManifold(False, collider_a=a, collider_b=b)

    # Penetration is minimal overlap
    if overlap_x < overlap_y:
        normal = Vector2(1.0, 0.0) if d.x > 0 else Vector2(-1.0, 0.0)
        penetration = overlap_x
    else:
        normal = Vector2(0.0, 1.0) if d.y > 0 else Vector2(0.0, -1.0)
        penetration = overlap_y

    return CollisionManifold(True, normal, penetration, collider_a=a, collider_b=b)


def _intersect_circle_circle(a: CircleCollider, b: CircleCollider) -> CollisionManifold:
    # Vector from A to B
    d = b.position - a.position
    dist_sq = d.length_sq()
    radius_sum = a.radius + b.radius

    if dist_sq >= radius_sum * radius_sum:
        return CollisionManifold(False, collider_a=a, collider_b=b)

    distance = math.sqrt(dist_sq) if dist_sq != 0 else 1e-8
    normal = Vector2(d.x / distance, d.y / distance)
    penetration = radius_sum - distance
    return CollisionManifold(True, normal, penetration, collider_a=a, collider_b=b)


def _closest_point_on_aabb(aabb: AABBCollider, point: Vector2) -> Vector2:
    # Clamp point to AABB bounds
    clamped_x = max(aabb.min.x, min(point.x, aabb.max.x))
    clamped_y = max(aabb.min.y, min(point.y, aabb.max.y))
    return Vector2(clamped_x, clamped_y)


def _intersect_aabb_circle(aabb: AABBCollider, circle: CircleCollider, invert: bool = False) -> CollisionManifold:
    # invert == True means we were called as Circle vs AABB: swap normal later
    closest = _closest_point_on_aabb(aabb, circle.position)
    d = circle.position - closest
    dist_sq = d.length_sq()

    if dist_sq >= circle.radius * circle.radius:
        return CollisionManifold(False, collider_a=aabb, collider_b=circle)

    distance = math.sqrt(dist_sq) if dist_sq != 0 else 1e-8
    normal = d * (1.0 / distance)
    penetration = circle.radius - distance

    # Orientation: normal must always point from A → B (aabb → circle)
    if invert:
        normal = normal * -1.0

    return CollisionManifold(True, normal, penetration, collider_a=aabb, collider_b=circle)


# ------------------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------------------

_NARROW_PHASE_DISPATCH = {
    (ShapeType.AABB, ShapeType.AABB): _intersect_aabb_aabb,
    (ShapeType.CIRCLE, ShapeType.CIRCLE): _intersect_circle_circle,
    (ShapeType.AABB, ShapeType.CIRCLE): _intersect_aabb_circle,
    # For Circle vs AABB, we call the same function but tell it to invert normals
    (ShapeType.CIRCLE, ShapeType.AABB): lambda a, b: _intersect_aabb_circle(b, a, invert=True),
}


def detect_collisions(colliders: Iterable[Collider]) -> List[CollisionManifold]:
    """
    Given an iterable of colliders, run pair-wise collision detection.
    A super simple uniform n² algorithm is used after an optional broad-phase
    pruning step.  In production scale, call `broad_phase_quadtree` first.

    Parameters
    ----------
    colliders:
        Iterable of Collider instances.

    Returns
    -------
    List[CollisionManifold]
        All detected collision manifolds.
    """
    manifolds: List[CollisionManifold] = []

    # Convert to list so we can index
    colliders = list(colliders)
    for i, j in itertools.combinations(range(len(colliders)), 2):
        c1, c2 = colliders[i], colliders[j]
        key = (c1.shape, c2.shape)
        narrow = _NARROW_PHASE_DISPATCH.get(key)
        if narrow is None:  # Should not happen: indicates a missing algorithm
            # We avoid exceptions inside the loop for performance; skip instead.
            continue

        manifold = narrow(c1, c2)
        if manifold.collided:
            manifolds.append(manifold)

    return manifolds


# ------------------------------------------------------------------------------
# Resolution (impulse-based)
# ------------------------------------------------------------------------------

@dataclass(slots=True)
class RigidBody:
    """
    Pure-data rigid body representation, kept independent from gameplay
    ECS to simplify Lambda payloads / JSON serialisation.
    """

    position: Vector2
    velocity: Vector2
    mass: float
    restitution: float  # bounciness [0..1]

    def __post_init__(self) -> None:
        if self.mass <= 0:
            # Treat as immovable object
            object.__setattr__(self, "inverse_mass", 0.0)
        else:
            object.__setattr__(self, "inverse_mass", 1.0 / self.mass)

    inverse_mass: float = field(init=False)


def resolve_collision(
    manifold: CollisionManifold,
    body_a: RigidBody,
    body_b: RigidBody,
    positional_correction: bool = True,
) -> Tuple[RigidBody, RigidBody]:
    """
    Resolve the collision between two bodies using an impulse approach.

    Parameters
    ----------
    manifold:
        Narrow-phase collision info (normal points from A → B).
    body_a, body_b:
        The rigid bodies associated with the collider objects.
    positional_correction:
        When True, performs a post-impulse penetration slop correction
        (Baumgarte stabilisation) to avoid sinking over time.

    Returns
    -------
    Tuple[RigidBody, RigidBody]
        New immutable bodies with updated position & velocity.
    """
    if not manifold.collided:
        return body_a, body_b

    n = manifold.normal
    rv = body_b.velocity - body_a.velocity
    vel_along_normal = rv.dot(n)

    # Bodies are separating
    if vel_along_normal > 0:
        return body_a, body_b

    # Calculate restitution (bounciness)
    e = min(body_a.restitution, body_b.restitution)

    # Calculate impulse scalar
    j = -(1 + e) * vel_along_normal
    inv_mass_sum = body_a.inverse_mass + body_b.inverse_mass
    if inv_mass_sum == 0:
        return body_a, body_b  # Both infinite mass

    j /= inv_mass_sum
    impulse = n * j

    # Apply impulse
    va = body_a.velocity - impulse * body_a.inverse_mass
    vb = body_b.velocity + impulse * body_b.inverse_mass
    body_a = RigidBody(body_a.position, va, body_a.mass, body_a.restitution)
    body_b = RigidBody(body_b.position, vb, body_b.mass, body_b.restitution)

    # Positional correction to avoid sinking
    if positional_correction:
        percent = 0.2  # 20% of penetration
        slop = 0.01    # Allowable penetration
        correction_mag = max(manifold.penetration - slop, 0.0) / inv_mass_sum * percent
        correction = n * correction_mag
        pa = body_a.position - correction * body_a.inverse_mass
        pb = body_b.position + correction * body_b.inverse_mass
        body_a = RigidBody(pa, body_a.velocity, body_a.mass, body_a.restitution)
        body_b = RigidBody(pb, body_b.velocity, body_b.mass, body_b.restitution)

    return body_a, body_b


# ------------------------------------------------------------------------------
# Naive Quadtree broad phase (optional)
# ------------------------------------------------------------------------------

@dataclass
class _Quad:
    """Internal node for the Quadtree."""
    center: Vector2
    half_size: float
    items: List[Collider] = field(default_factory=list)
    children: Tuple[Optional["_Quad"], Optional["_Quad"], Optional["_Quad"], Optional["_Quad"]] = (
        None,
        None,
        None,
        None,
    )
    capacity: int = 4
    level: int = 0
    max_level: int = 6  # Limit recursion to avoid pathologic splits

    def _index(self, pos: Vector2) -> int:
        """Return the child index for the given position."""
        idx = 0
        if pos.x > self.center.x:
            idx |= 1
        if pos.y > self.center.y:
            idx |= 2
        return idx

    def subdivide(self) -> None:
        if self.level >= self.max_level or self.children[0] is not None:
            return

        quarter = self.half_size / 2
        for i in range(4):
            offset = Vector2(
                quarter if i & 1 else -quarter,
                quarter if i & 2 else -quarter,
            )
            child_center = self.center + offset
            self.children = tuple(
                _Quad(
                    child_center if j == i else self.children[j - 1],
                    quarter,
                    level=self.level + 1,
                    max_level=self.max_level,
                )
                if j == i
                else self.children[j - 1]
                for j in range(4)
            )

    def insert(self, collider: Collider) -> None:
        if self.children[0] is not None:
            idx = self._index(collider.position)
            self.children[idx].insert(collider)  # type: ignore[index]
            return

        self.items.append(collider)

        if len(self.items) > self.capacity and self.level < self.max_level:
            self.subdivide()
            for item in self.items:
                idx = self._index(item.position)
                self.children[idx].insert(item)  # type: ignore[index]
            self.items.clear()

    def query(self, region_center: Vector2, region_half_size: float, found: Optional[List[Collider]] = None):
        if found is None:
            found = []

        # AABB vs AABB overlap test between region and this node
        dx = abs(region_center.x - self.center.x)
        dy = abs(region_center.y - self.center.y)
        if dx > (region_half_size + self.half_size) or dy > (region_half_size + self.half_size):
            return found  # No overlap

        # Add items
        found.extend(self.items)

        # Recurse
        if self.children[0] is not None:
            for child in self.children:  # type: ignore[assignment]
                child.query(region_center, region_half_size, found)

        return found


def broad_phase_quadtree(colliders: Iterable[Collider]) -> List[Tuple[Collider, Collider]]:
    """
    Return potentially colliding pairs using a Quadtree for pruning.
    This is not a full SAP (sweep and prune) but performs well when
    colliders are distributed in 2-D space.

    The coordinate system must be roughly within ±10,000 units; higher
    magnitudes may require adjusting the root half size.

    Returns
    -------
    List[Tuple[Collider, Collider]]
        Pairs likely to collide (false positives possible).
    """
    root = _Quad(center=Vector2(0.0, 0.0), half_size=10000.0)

    colliders = list(colliders)
    for col in colliders:
        root.insert(col)

    pairs = set()

    for col in colliders:
        search_radius = col.bounding_radius()
        candidates = root.query(col.position, search_radius)
        for other in candidates:
            if other is col:
                continue
            # Deterministic ordering for set uniqueness
            pair = tuple(sorted((col, other), key=id))
            pairs.add(pair)

    # Convert back to list of tuples
    return [p for p in pairs]
```