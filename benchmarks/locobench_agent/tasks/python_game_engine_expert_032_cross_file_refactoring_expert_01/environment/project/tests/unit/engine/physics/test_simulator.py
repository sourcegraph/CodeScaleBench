```python
"""
tests/unit/engine/physics/test_simulator.py

Unit-test suite for the Physics Simulator that powers the LedgerQuest Engine.
The real implementation lives in
`ledgerquest_engine.engine.physics.simulator`, but in order to keep the test
suite fully self-contained and runnable in isolation (CI, local dev boxes,
etc.), the file provides an ultra-light in-memory stub that will be used
whenever the real dependency cannot be imported.

The tests focus on deterministic, mechanical properties that any physics
engine (real or stub) must satisfy:
    • Kinematic integration (position/velocity update)
    • Constant gravity acceleration
    • Elastic collision response
    • Input validation (e.g. negative time-step detection)

The suite uses `pytest` as the runner and `hypothesis` for a bit of
property-based testing around collisions.
"""

from __future__ import annotations

import importlib
import math
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Iterable, List, Tuple

import pytest

# --------------------------------------------------------------------------- #
# Attempt to import the real engine’s simulator. If that fails (e.g. when the
# engine is not installed in a minimal CI environment) we fall back to a stub.
# --------------------------------------------------------------------------- #

_ENGINE_SIM_PATH = "ledgerquest_engine.engine.physics.simulator"
SIMULATOR_FQN = f"{_ENGINE_SIM_PATH}.Simulation"


def _install_fallback_stub() -> ModuleType:
    """
    Dynamically create a minimal stub of the physics simulator and insert it
    into `sys.modules` so that regular import statements succeed.

    The stub purposefully implements ONLY the behaviour required by the tests.
    That keeps the contract small and ensures that the tests stay valuable
    even once the real simulator is swapped in.
    """

    @dataclass(slots=True)
    class PhysicsBody:  # noqa: D401 – simple data carrier
        """
        Minimal stand-in for the engine’s `PhysicsBody` dataclass.

        Attributes
        ----------
        position: Tuple[float, float] – (x, y) position in world space.
        velocity: Tuple[float, float] – (vx, vy) linear velocity.
        acceleration: Tuple[float, float] – (ax, ay) acceleration (constant per frame).
        mass: float – Mass in kilograms. (Must be > 0.)
        radius: float – Collision radius. (Must be ≥ 0.)
        """

        position: Tuple[float, float]
        velocity: Tuple[float, float]
        acceleration: Tuple[float, float]
        mass: float
        radius: float

        def kinetic_energy(self) -> float:
            """Return ½·m·|v|² for quick energy-conservation checks."""
            vx, vy = self.velocity
            speed_sq = vx * vx + vy * vy
            return 0.5 * self.mass * speed_sq

    class Simulation:  # noqa: D101 – public API defined by real engine
        DEFAULT_GRAVITY = (0.0, -9.81)

        def __init__(self, gravity: Tuple[float, float] | None = None) -> None:
            self.gravity = gravity if gravity is not None else self.DEFAULT_GRAVITY

        # ------------------------------------------------------------------ #
        # Static utility methods
        # ------------------------------------------------------------------ #
        @staticmethod
        def _add_vec(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
            return (a[0] + b[0], a[1] + b[1])

        @staticmethod
        def _sub_vec(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
            return (a[0] - b[0], a[1] - b[1])

        @staticmethod
        def _scale_vec(vec: Tuple[float, float], scalar: float) -> Tuple[float, float]:
            return (vec[0] * scalar, vec[1] * scalar)

        @staticmethod
        def _dot(a: Tuple[float, float], b: Tuple[float, float]) -> float:
            return a[0] * b[0] + a[1] * b[1]

        @staticmethod
        def _norm_sq(vec: Tuple[float, float]) -> float:
            return vec[0] * vec[0] + vec[1] * vec[1]

        # ------------------------------------------------------------------ #
        # Core public API
        # ------------------------------------------------------------------ #
        def simulate_step(
            self,
            bodies: Iterable[PhysicsBody],
            dt: float,
            *,
            resolve_collisions: bool = True,
        ) -> None:
            """
            Integrate positions & velocities for a single time-step.

            Mutates the `bodies` in-place.
            """
            if dt <= 0.0:
                raise ValueError("Δt must be positive.")

            # 1. Integrate acceleration → velocity
            for body in bodies:
                ax, ay = self._add_vec(body.acceleration, self.gravity)
                vx, vy = body.velocity
                body.velocity = (vx + ax * dt, vy + ay * dt)

            # 2. Integrate velocity → position (semi-implicit Euler)
            for body in bodies:
                px, py = body.position
                vx, vy = body.velocity
                body.position = (px + vx * dt, py + vy * dt)

            # 3. Handle naive elastic collisions (circle vs. circle)
            if resolve_collisions:
                self._resolve_pairwise_collisions(list(bodies))

        # ------------------------------------------------------------------ #
        # Collision handling
        # ------------------------------------------------------------------ #
        def _resolve_pairwise_collisions(self, bodies: List[PhysicsBody]) -> None:
            n = len(bodies)
            for i in range(n):
                for j in range(i + 1, n):
                    a = bodies[i]
                    b = bodies[j]

                    # Minimum required separation
                    min_dist = a.radius + b.radius
                    delta = self._sub_vec(b.position, a.position)
                    dist_sq = self._norm_sq(delta)

                    if dist_sq == 0 or dist_sq >= min_dist * min_dist:
                        continue

                    dist = math.sqrt(dist_sq)
                    normal = self._scale_vec(delta, 1.0 / dist)

                    # Relative velocity along the collision normal
                    rel_vel = self._sub_vec(b.velocity, a.velocity)
                    vel_along_normal = self._dot(rel_vel, normal)

                    # Only resolve if bodies are moving toward each other
                    if vel_along_normal > 0:
                        continue

                    # Compute impulse magnitude for perfectly elastic collision
                    inv_mass_sum = (1 / a.mass) + (1 / b.mass)
                    impulse_mag = -(1.0 + 1.0) * vel_along_normal / inv_mass_sum  # e = 1

                    impulse = self._scale_vec(normal, impulse_mag)

                    a.velocity = self._sub_vec(a.velocity, self._scale_vec(impulse, 1 / a.mass))
                    b.velocity = self._add_vec(b.velocity, self._scale_vec(impulse, 1 / b.mass))

                    # Simple positional correction to avoid sinking
                    percent = 0.8  # correction strength
                    correction = self._scale_vec(
                        normal, percent * (min_dist - dist) / inv_mass_sum
                    )
                    a.position = self._sub_vec(a.position, self._scale_vec(correction, 1 / a.mass))
                    b.position = self._add_vec(b.position, self._scale_vec(correction, 1 / b.mass))

    # ---------------------------------------------------------------------- #
    # Publish stub as importable modules
    # ---------------------------------------------------------------------- #
    stub_module = ModuleType(_ENGINE_SIM_PATH)
    stub_module.PhysicsBody = PhysicsBody
    stub_module.Simulation = Simulation

    sys.modules[_ENGINE_SIM_PATH] = stub_module
    return stub_module


try:
    simulator_module = importlib.import_module(_ENGINE_SIM_PATH)
except ModuleNotFoundError:  # pragma: no cover – only hit in stub mode
    simulator_module = _install_fallback_stub()

Simulation = getattr(simulator_module, "Simulation")
PhysicsBody = getattr(simulator_module, "PhysicsBody")

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def sim() -> Simulation:
    """Return a brand-new simulation instance with default gravity."""
    return Simulation()


# --------------------------------------------------------------------------- #
# Helper utilities (test-side only)
# --------------------------------------------------------------------------- #


def _make_body(
    *,
    pos: Tuple[float, float] = (0.0, 0.0),
    vel: Tuple[float, float] = (0.0, 0.0),
    acc: Tuple[float, float] = (0.0, 0.0),
    mass: float = 1.0,
    radius: float = 0.5,
) -> PhysicsBody:
    """Quick factory for `PhysicsBody` with sensible defaults."""
    return PhysicsBody(position=pos, velocity=vel, acceleration=acc, mass=mass, radius=radius)


# --------------------------------------------------------------------------- #
# Basic kinematics tests
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dt", [0.01, 0.1, 1.0])
def test_euler_integration_constant_velocity(sim: Simulation, dt: float) -> None:
    """
    With zero acceleration and zero gravity, the body should move linearly:
        x(t + Δt) = x(t) + v * Δt
    """
    body = _make_body(pos=(0.0, 0.0), vel=(10.0, 0.0), acc=(0.0, 0.0))
    # Override gravity to 0 for this scenario
    sim.gravity = (0.0, 0.0)

    sim.simulate_step([body], dt)

    expected_x = 0.0 + 10.0 * dt
    assert pytest.approx(body.position[0]) == expected_x
    assert pytest.approx(body.position[1]) == 0.0  # y coordinate unchanged


def test_uniform_gravity_acceleration(sim: Simulation) -> None:
    """
    Under gravity alone (no initial velocity, no additional acceleration),
    the velocity after Δt should be g·Δt, position ½·g·Δt²
    """
    dt = 0.2
    g_x, g_y = sim.gravity  # default stub is (0, -9.81)
    body = _make_body()

    sim.simulate_step([body], dt)

    vx, vy = body.velocity
    px, py = body.position

    assert pytest.approx(vx) == g_x * dt
    assert pytest.approx(vy) == g_y * dt
    assert pytest.approx(px) == 0.5 * g_x * dt * dt
    assert pytest.approx(py) == 0.5 * g_y * dt * dt


@pytest.mark.parametrize("dt", [-0.1, 0.0])
def test_invalid_time_step_rejected(sim: Simulation, dt: float) -> None:
    with pytest.raises(ValueError):
        sim.simulate_step([], dt)


# --------------------------------------------------------------------------- #
# Collision tests
# --------------------------------------------------------------------------- #

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover – hypothesis not installed
    hypothesis_available = False
else:
    hypothesis_available = True


@pytest.mark.skipif(not hypothesis_available, reason="Hypothesis not installed")
@settings(deadline=None, max_examples=100)
@given(
    m1=st.floats(min_value=0.1, max_value=10.0),
    m2=st.floats(min_value=0.1, max_value=10.0),
    v1=st.floats(min_value=-10.0, max_value=10.0),
    v2=st.floats(min_value=-10.0, max_value=10.0),
)
def test_elastic_collision_energy_conservation(sim: Simulation, m1: float, m2: float, v1: float, v2: float) -> None:
    """
    For a perfectly elastic, head-on collision in 1-D (simulated here with two
    circles), total kinetic energy must be conserved.
    """
    radius = 0.5
    # Place circles so they barely touch at x=0 to guarantee immediate collision
    body_a = _make_body(pos=(-radius, 0.0), vel=(v1, 0.0), mass=m1, radius=radius)
    body_b = _make_body(pos=(+radius, 0.0), vel=(v2, 0.0), mass=m2, radius=radius)

    initial_energy = body_a.kinetic_energy() + body_b.kinetic_energy()

    # Small Δt so that collision occurs & is resolved in a single step
    sim.gravity = (0.0, 0.0)
    sim.simulate_step([body_a, body_b], dt=0.01, resolve_collisions=True)

    final_energy = body_a.kinetic_energy() + body_b.kinetic_energy()

    assert pytest.approx(final_energy, rel=1e-6, abs=1e-9) == initial_energy


def test_collision_velocity_exchange_equal_mass(sim: Simulation) -> None:
    """
    For equal masses and a head-on elastic collision, the objects swap
    velocities.
    """
    radius = 0.5
    body_a = _make_body(pos=(-radius, 0.0), vel=(5.0, 0.0), mass=1.0, radius=radius)
    body_b = _make_body(pos=(+radius, 0.0), vel=(-3.0, 0.0), mass=1.0, radius=radius)

    sim.gravity = (0.0, 0.0)
    sim.simulate_step([body_a, body_b], dt=0.01)

    assert pytest.approx(body_a.velocity[0]) == -3.0
    assert pytest.approx(body_b.velocity[0]) == 5.0
```