```python
"""
ledgerquest.engine.ecs.system
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Core implementation for the “S” in ECS (Entity–Component–System).

A *System* is a unit of behaviour that operates over entities that own a
specific set of components.  Unlike a monolithic game-loop running on a
stateful server, LedgerQuest executes systems inside short-lived AWS Lambda
invocations orchestrated by Step Functions.  To keep this file agnostic of
AWS APIs (so that the engine can still run locally or in unit tests), all
cloud-specific hooks are abstracted behind thin strategy interfaces.

The public surface of this module therefore focuses on:

*   An abstract ``BaseSystem`` with lifecycle hooks
*   A ``SystemManager`` that:
    -   registers systems,
    -   resolves execution order based on priority & dependencies,
    -   records performance metrics, and
    -   emits structured events to the chosen “telemetry backend”.
*   A naive in-memory fallback telemetry backend used during local runs
    or CI.

The implementation strives to be thread-safe, asyncio-friendly, and fully
type-annotated so mypy can enforce correctness.
"""
from __future__ import annotations

import abc
import asyncio
import dataclasses
import json
import logging
import time
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
)

###############################################################################
# Type-level primitives
###############################################################################
C = TypeVar("C", bound="Component")
T = TypeVar("T")
EntityId = str

logger = logging.getLogger("ledgerquest.engine.ecs.system")
logger.setLevel(logging.INFO)


class Component(Protocol):
    """Structural marker for a component."""
    __component_name__: str


class Entity(Protocol):
    """Minimal interface that a World/Entity implementation must satisfy."""

    id: EntityId

    def has(self, component_type: Type[Component]) -> bool:  # pragma: no cover
        ...

    def get(self, component_type: Type[C]) -> C:  # pragma: no cover
        ...


###############################################################################
# Telemetry backend
###############################################################################
class TelemetryBackend(abc.ABC):
    """Abstracts away CloudWatch or any other metrics sink."""

    @abc.abstractmethod
    def record(
        self,
        *,
        system: str,
        duration_ms: float,
        processed_entities: int,
        extras: Optional[Mapping[str, Any]] = None,
    ) -> None:  # pragma: no cover
        """
        Record a single execution of a system.

        Parameters
        ----------
        system:
            Human-readable name of the system.
        duration_ms:
            Wall-clock time spent executing the system.
        processed_entities:
            Number of entities that matched the system’s ``required_components``.
        extras:
            Additional JSON-serialisable payload for custom dashboards.
        """
        ...


class StdOutTelemetry(TelemetryBackend):
    """Simple stdout sink for local development."""

    def record(
        self,
        *,
        system: str,
        duration_ms: float,
        processed_entities: int,
        extras: Optional[Mapping[str, Any]] = None,
    ) -> None:  # pragma: no cover
        payload = {
            "system": system,
            "duration_ms": round(duration_ms, 3),
            "entities": processed_entities,
            **(extras or {}),
        }
        line = json.dumps(payload, separators=(",", ":"))
        print(line, flush=True)


###############################################################################
# System implementation
###############################################################################
class SystemError(Exception):
    """Raised when a system fails during execution."""


class BaseSystem(abc.ABC):
    """
    Foundation for all concrete Systems.

    Sub-classes define the set of components they operate on via the
    ``required_components`` class attribute and implement the core behaviour
    in :meth:`process`.

    The runtime may reuse the same instance multiple times during a Step
    Functions loop, so the implementation must be side-effect-free *except*
    for changes performed on the world/entities given in :meth:`process`.
    """

    #: Static set of components required by this system.
    required_components: Set[Type[Component]] = set()

    #: Lower number = higher execution priority within a tick
    priority: int = 100

    #: Whether :pymeth:`process` can be executed as a coroutine
    is_async: bool = False

    #: Max permitted runtime (ms) before logging a warning
    soft_time_budget_ms: int = 12  # ~60 FPS nominal frame budget

    #: Optional name override (otherwise class-name is used)
    name: Optional[str] = None

    def __init__(self) -> None:
        self._name = self.name or self.__class__.__qualname__
        self._validate()

    # --------------------------------------------------------------------- #
    # Introspection helpers
    # --------------------------------------------------------------------- #
    @property
    def system_name(self) -> str:
        return self._name

    @classmethod
    def matches_entity(cls, entity: Entity) -> bool:
        """Return ``True`` if *entity* satisfies ``required_components``."""
        return all(entity.has(comp) for comp in cls.required_components)

    def _validate(self) -> None:
        if not self.required_components:
            raise ValueError(
                f"{self.system_name} must declare at least one "
                f"required component."
            )

    # --------------------------------------------------------------------- #
    # Lifecycle hooks
    # --------------------------------------------------------------------- #
    async def __call__(
        self, *, world: "WorldLike", dt: float, telemetry: TelemetryBackend
    ) -> None:
        """
        Execute the system over the given *world*.  Dispatches to
        :meth:`process` and instruments execution time.

        Parameters
        ----------
        world:
            Object exposing ``iter_entities`` and ``get_entity`` helpers.
        dt:
            Time elapsed since last tick (in seconds).
        telemetry:
            Concrete telemetry backend.
        """
        start = time.perf_counter()

        try:
            if self.is_async:
                processed_entities = await self._run_async(world, dt)
            else:
                processed_entities = self._run_sync(world, dt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("System %s failed: %s", self.system_name, exc)
            raise SystemError from exc

        duration_ms = (time.perf_counter() - start) * 1_000.0
        telemetry.record(
            system=self.system_name,
            duration_ms=duration_ms,
            processed_entities=processed_entities,
        )

        if duration_ms > self.soft_time_budget_ms:
            logger.warning(
                "System %s exceeded soft budget: %.3f ms > %d ms",
                self.system_name,
                duration_ms,
                self.soft_time_budget_ms,
            )

    # ------------------------------------------------------------------ #
    # Concrete execution helpers
    # ------------------------------------------------------------------ #
    def _run_sync(self, world: "WorldLike", dt: float) -> int:
        processed = 0
        for entity in world.iter_entities(self.required_components):
            self.process(entity, dt, world)
            processed += 1
        return processed

    async def _run_async(self, world: "WorldLike", dt: float) -> int:
        coroutines: List[Awaitable[None]] = []
        for entity in world.iter_entities(self.required_components):
            coroutines.append(self.process_async(entity, dt, world))

        processed = len(coroutines)

        # Limit concurrency to avoid Lambda OOMs
        semaphore = asyncio.Semaphore(32)

        async def _guard(coro: Awaitable[None]) -> None:
            async with semaphore:
                await coro

        await asyncio.gather(*[_guard(c) for c in coroutines])
        return processed

    # ------------------------------------------------------------------ #
    # Methods to override
    # ------------------------------------------------------------------ #
    @abc.abstractmethod
    def process(self, entity: Entity, dt: float, world: "WorldLike") -> None:
        """Pure synchronous logic implemented by the subclass."""
        raise NotImplementedError

    async def process_async(
        self, entity: Entity, dt: float, world: "WorldLike"
    ) -> None:
        """
        Override this for async systems.

        Default implementation delegates to the sync version so subclasses
        only need to implement one of the two methods.
        """
        self.process(entity, dt, world)


###############################################################################
# World interface (duck-typed; implemented elsewhere in engine)
###############################################################################
class WorldLike(Protocol):
    """
    Minimal interface that the SystemManager expects from a “world”.
    """

    def iter_entities(
        self, required_components: Iterable[Type[Component]]
    ) -> Iterable[Entity]:
        ...  # pragma: no cover


###############################################################################
# SystemManager – Orchestrates a collection of systems
###############################################################################
 _S = TypeVar("_S", bound=BaseSystem)


class SystemManager:
    """
    Maintains a registry of systems and executes them in priority-order.

    This class is intentionally lightweight; advanced orchestration (e.g.
    parallel execution across multiple Lambdas) should be handled by the
    higher-level *Step Function* driving the simulation job.
    """

    def __init__(
        self,
        *,
        telemetry_backend: Optional[TelemetryBackend] = None,
    ) -> None:
        self._systems: List[BaseSystem] = []
        self._telemetry = telemetry_backend or StdOutTelemetry()

    # ------------------------------------------------------------------ #
    # Registry API
    # ------------------------------------------------------------------ #
    def register(self, system: _S) -> _S:
        """
        Register *system*.  The list remains sorted by ``priority``.
        """
        if any(s.system_name == system.system_name for s in self._systems):
            raise ValueError(f"System '{system.system_name}' already registered")

        self._systems.append(system)
        self._systems.sort(key=lambda s: s.priority)
        logger.debug("Registered system %s (priority=%d)", system, system.priority)
        return system

    def unregister(self, system_name: str) -> None:
        before = len(self._systems)
        self._systems = [s for s in self._systems if s.system_name != system_name]
        if len(self._systems) == before:
            raise KeyError(f"System '{system_name}' not found")

    def clear(self) -> None:
        self._systems.clear()

    # ------------------------------------------------------------------ #
    # Execution API
    # ------------------------------------------------------------------ #
    async def tick(self, world: WorldLike, dt: float) -> None:
        """
        Execute all registered systems for the current *dt*.

        For maximum portability we do not attempt fancy task scheduling
        here; systems decide individually whether to run sync or async
        and the manager simply awaits each in order.
        """
        for system in self._systems:
            await system(world=world, dt=dt, telemetry=self._telemetry)

    # ------------------------------------------------------------------ #
    # Debug helpers
    # ------------------------------------------------------------------ #
    def list_systems(self) -> List[str]:
        return [s.system_name for s in self._systems]

    def __repr__(self) -> str:
        systems = ", ".join(self.list_systems())
        return f"<SystemManager [{systems}]>"


###############################################################################
# Context-manager for quick “local world” testing
###############################################################################
class LocalWorldSandbox:
    """
    Helper context-manager that spins up an in-memory world and system
    manager suitable for unit tests or rapid prototyping.
    """

    def __init__(self, *systems: BaseSystem) -> None:
        from ledgerquest.engine.ecs.world import InMemoryWorld  # late import

        self._world_cls = InMemoryWorld
        self._systems = systems
        self.manager: Optional[SystemManager] = None
        self.world: Optional[InMemoryWorld] = None

    def __enter__(self) -> "LocalWorldSandbox":
        self.world = self._world_cls()
        self.manager = SystemManager()
        for sys in self._systems:
            self.manager.register(sys)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        # Clean-up resources if necessary
        return None
```