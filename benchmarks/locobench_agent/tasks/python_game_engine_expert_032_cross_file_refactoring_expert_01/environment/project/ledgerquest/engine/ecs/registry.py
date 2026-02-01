```python
"""
ledgerquest.engine.ecs.registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Central registry and façade for the Entity-Component-System (ECS) runtime
inside LedgerQuest Engine.

The registry coordinates the life-cycle of entities, components, and systems,
while delegating low-level storage operations to a pluggable backend.  In
production the backend can be backed by DynamoDB (for a fully-serverless,
multi-tenant deployment), whereas unit-tests and local simulations can rely on
an in-memory implementation.

Key responsibilities
--------------------
• Unique ID generation and entity bookkeeping
• Consistent component CRUD operations
• Reactive events for audit-logging / streaming updates
• System orchestration (update loop, dependency sorting, etc.)

NOTE:
-----
This module purposefully avoids tight coupling with AWS SDK so that the
core ECS logic can run in any environment.  Cloud-specific integration is
encapsulated behind the backend and event_sink abstractions.
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    MutableMapping,
    MutableSet,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
)

__all__ = [
    "ECSRegistry",
    "EntityId",
    "Component",
    "System",
    "EntityNotFoundError",
    "ComponentNotFoundError",
    "RegistryBackendError",
]

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class RegistryBackendError(RuntimeError):
    """Fatal error raised by an ECS backend implementation."""

    pass


class EntityNotFoundError(KeyError):
    """Raised when an entity cannot be found."""

    pass


class ComponentNotFoundError(KeyError):
    """Raised when a requested component is not present on an entity."""

    pass


# --------------------------------------------------------------------------- #
# Typing helpers
# --------------------------------------------------------------------------- #

EntityId = str
C = TypeVar("C", bound="Component")


class Component(Protocol):
    """
    Protocol that all components must comply with.

    Concrete components can be dataclasses, attrs classes, or custom objects
    – as long as they expose a `.type` attribute (used for indexing) and can be
    passed by reference or serialised by the backend.
    """

    @property
    def type(self) -> str:  # noqa: D401
        """Unique identifier for the component class."""
        ...


class System(Protocol):
    """
    Protocol for systems executed by the ECS update loop.
    """

    name: str
    order: int  # lower = executed earlier

    def update(self, registry: "ECSRegistry", dt: float) -> None:  # noqa: D401
        """
        Perform one tick/update on the registry.

        Arguments
        ---------
        registry
            The central ECS registry instance.
        dt
            Time delta (in seconds) since the previous update call.
        """
        ...


# --------------------------------------------------------------------------- #
# Backend / Storage Abstraction
# --------------------------------------------------------------------------- #


class BaseBackend(ABC):
    """
    Abstract storage layer for the ECS.

    Implementations *must* be thread-safe as registry operations may be invoked
    concurrently from WebSocket handlers, Lambda warmers, or physics workers.
    """

    @abstractmethod
    def create_entity(self, entity_id: EntityId) -> None:
        ...

    @abstractmethod
    def delete_entity(self, entity_id: EntityId) -> None:
        ...

    @abstractmethod
    def list_entities(self) -> Iterable[EntityId]:
        ...

    @abstractmethod
    def add_component(self, entity_id: EntityId, component: Component) -> None:
        ...

    @abstractmethod
    def remove_component(
        self, entity_id: EntityId, component_type: str
    ) -> Component:
        ...

    @abstractmethod
    def get_component(self, entity_id: EntityId, component_type: str) -> Component:
        ...

    @abstractmethod
    def get_components(
        self, entity_id: EntityId, *component_types: str
    ) -> List[Component]:
        ...

    @abstractmethod
    def query_entities(self, component_types: Sequence[str]) -> Set[EntityId]:
        ...


class InMemoryBackend(BaseBackend):
    """
    Simple dictionary-based backend.

    Intended for local development, unit-tests, and single-process worker
    containers.
    """

    def __init__(self) -> None:
        self._entities: MutableSet[EntityId] = set()
        # entity_id -> component_type -> component
        self._components: Dict[EntityId, Dict[str, Component]] = defaultdict(dict)
        # Index: component_type -> set(entity_ids)
        self._component_index: Dict[str, Set[EntityId]] = defaultdict(set)

        # Thread safety
        self._lock = threading.RLock()

    # BaseBackend implementation -------------------------------------------------

    def create_entity(self, entity_id: EntityId) -> None:
        with self._lock:
            if entity_id in self._entities:
                log.debug("Entity %s already exists in backend", entity_id)
                return
            self._entities.add(entity_id)

    def delete_entity(self, entity_id: EntityId) -> None:
        with self._lock:
            if entity_id not in self._entities:
                raise EntityNotFoundError(entity_id)

            # Remove from indices first
            for c_type in list(self._components[entity_id].keys()):
                self._component_index[c_type].discard(entity_id)

            del self._components[entity_id]
            self._entities.discard(entity_id)

    def list_entities(self) -> Iterable[EntityId]:
        with self._lock:
            return tuple(self._entities)

    def add_component(self, entity_id: EntityId, component: Component) -> None:
        with self._lock:
            if entity_id not in self._entities:
                raise EntityNotFoundError(entity_id)

            c_type = component.type
            self._components[entity_id][c_type] = component
            self._component_index[c_type].add(entity_id)

    def remove_component(
        self, entity_id: EntityId, component_type: str
    ) -> Component:
        with self._lock:
            if entity_id not in self._entities:
                raise EntityNotFoundError(entity_id)
            try:
                removed = self._components[entity_id].pop(component_type)
            except KeyError as exc:
                raise ComponentNotFoundError(component_type) from exc

            self._component_index[component_type].discard(entity_id)
            return removed

    def get_component(self, entity_id: EntityId, component_type: str) -> Component:
        with self._lock:
            try:
                return self._components[entity_id][component_type]
            except KeyError as exc:
                raise ComponentNotFoundError(component_type) from exc

    def get_components(
        self, entity_id: EntityId, *component_types: str
    ) -> List[Component]:
        with self._lock:
            if entity_id not in self._entities:
                raise EntityNotFoundError(entity_id)

            storage = self._components[entity_id]
            if not component_types:  # all components
                return list(storage.values())

            missing = [c for c in component_types if c not in storage]
            if missing:
                raise ComponentNotFoundError(
                    f"Entity {entity_id} lacks components {', '.join(missing)}"
                )
            return [storage[c] for c in component_types]

    def query_entities(self, component_types: Sequence[str]) -> Set[EntityId]:
        """
        Return the set of entity IDs that have at least *all* the given
        component types.
        """
        if not component_types:
            raise ValueError("At least one component type must be specified")

        with self._lock:
            # Start with entities having the first component_type.
            result: Set[EntityId] = set(
                self._component_index.get(component_types[0], set())
            )
            # Intersect successively to ensure entity has *all* components.
            for c_type in component_types[1:]:
                result &= self._component_index.get(c_type, set())
                if not result:  # Early abort – no entity can match anymore.
                    break
            return result


# --------------------------------------------------------------------------- #
# Event sink abstraction
# --------------------------------------------------------------------------- #


@dataclass
class Event:
    """
    Internal ECS event emitted on structural changes.

    Examples
    --------
    Event("ENTITY_CREATED", {"entity_id": ...})
    Event("COMPONENT_ADDED", {"entity_id": ..., "component_type": ...})
    """

    name: str
    payload: Dict[str, Any]
    ts: _dt.datetime = _dt.datetime.utcnow()


class EventSink(Protocol):
    """
    Represents a destination for ECS events (e.g. EventBridge, Kinesis, Redis).
    """

    def publish(self, event: Event) -> None:  # noqa: D401
        ...


class _NullEventSink(EventSink):
    """
    Default sink that discards all events (used if caller does not supply one).
    """

    def publish(self, event: Event) -> None:  # noqa: D401
        pass


# --------------------------------------------------------------------------- #
# The main registry façade
# --------------------------------------------------------------------------- #


class ECSRegistry:
    """
    Production-ready ECS registry with pluggable storage.

    Usage
    -----
    >>> registry = ECSRegistry(InMemoryBackend())
    >>> player = registry.create_entity()
    >>> registry.add_component(player, Position(x=10, y=20))
    >>> registry.update(1 / 60)

    Thread safety
    -------------
    All mutating operations are delegated to the backend, which must guarantee
    atomicity.  Read-only convenience methods obtain a shared lock to guard
    against concurrent mutation.
    """

    _DEFAULT_BACKEND_CLS: Type[BaseBackend] = InMemoryBackend

    def __init__(
        self,
        backend: Optional[BaseBackend] = None,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        self._backend = backend or self._DEFAULT_BACKEND_CLS()
        self._event_sink = event_sink or _NullEventSink()

        self._systems: List[System] = []
        self._state_lock = threading.RLock()

        log.debug("ECSRegistry initialised with backend %s", type(self._backend).__name__)

    # --------------------------------------------------------------------- #
    # Entity management
    # --------------------------------------------------------------------- #

    def create_entity(
        self, entity_id: Optional[EntityId] = None, *, publish_event: bool = True
    ) -> EntityId:
        """
        Create a new entity and return its unique identifier.
        """
        entity_id = entity_id or str(uuid.uuid4())
        log.debug("Creating entity %s", entity_id)

        try:
            self._backend.create_entity(entity_id)
        except Exception as exc:  # pylint: disable=broad-except
            msg = f"Backend failed to create entity {entity_id}: {exc}"
            log.exception(msg)
            raise RegistryBackendError(msg) from exc

        if publish_event:
            self._event_sink.publish(Event("ENTITY_CREATED", {"entity_id": entity_id}))

        return entity_id

    def delete_entity(self, entity_id: EntityId, *, publish_event: bool = True) -> None:
        log.debug("Deleting entity %s", entity_id)
        self._backend.delete_entity(entity_id)
        if publish_event:
            self._event_sink.publish(Event("ENTITY_DELETED", {"entity_id": entity_id}))

    def list_entities(self) -> Tuple[EntityId, ...]:
        entities = tuple(self._backend.list_entities())
        log.debug("Listing entities – count: %d", len(entities))
        return entities

    # --------------------------------------------------------------------- #
    # Component CRUD
    # --------------------------------------------------------------------- #

    def add_component(
        self,
        entity_id: EntityId,
        component: Component,
        *,
        publish_event: bool = True,
    ) -> None:
        log.debug("Adding component %s to entity %s", component.type, entity_id)
        self._backend.add_component(entity_id, component)
        if publish_event:
            self._event_sink.publish(
                Event(
                    "COMPONENT_ADDED",
                    {"entity_id": entity_id, "component_type": component.type},
                )
            )

    def remove_component(
        self,
        entity_id: EntityId,
        component_type: str,
        *,
        publish_event: bool = True,
    ) -> Component:
        log.debug("Removing component %s from entity %s", component_type, entity_id)
        component = self._backend.remove_component(entity_id, component_type)
        if publish_event:
            self._event_sink.publish(
                Event(
                    "COMPONENT_REMOVED",
                    {"entity_id": entity_id, "component_type": component_type},
                )
            )
        return component

    def get_component(self, entity_id: EntityId, component_type: str) -> Component:
        component = self._backend.get_component(entity_id, component_type)
        log.debug("Fetched component %s for entity %s", component_type, entity_id)
        return component

    def get_components(
        self, entity_id: EntityId, *component_types: str
    ) -> List[Component]:
        comps = self._backend.get_components(entity_id, *component_types)
        log.debug(
            "Fetched %d components for entity %s (requested: %s)",
            len(comps),
            entity_id,
            component_types or "ALL",
        )
        return comps

    # --------------------------------------------------------------------- #
    # Query helpers
    # --------------------------------------------------------------------- #

    def query(self, *component_types: str) -> Iterator[Tuple[EntityId, List[Component]]]:
        """
        Yield (entity_id, [components]) tuples for all entities that have the
        requested set of component types.
        """
        entity_ids = self._backend.query_entities(component_types)
        log.debug(
            "Query for %s returned %d entities",
            component_types,
            len(entity_ids),
        )
        for eid in entity_ids:
            comps = self.get_components(eid, *component_types)
            yield eid, comps

    # --------------------------------------------------------------------- #
    # System management
    # --------------------------------------------------------------------- #

    def register_system(self, system: System) -> None:
        """
        Register a system instance.

        Systems are kept ordered by their specified `order` attribute, allowing
        callers to control update sequences (e.g. physics before AI).
        """
        if any(s.name == system.name for s in self._systems):
            log.warning("System %s already registered – ignoring", system.name)
            return
        self._systems.append(system)
        self._systems.sort(key=lambda s: (s.order, s.name))
        log.info("Registered system '%s' (order=%s)", system.name, system.order)

    # --------------------------------------------------------------------- #
    # Update loop
    # --------------------------------------------------------------------- #

    def update(self, dt: float) -> None:
        """
        Invoke `update(dt)` on all registered systems.

        This method is intentionally lightweight; in production the step-function
        orchestrator will call individual Lambda functions per system to stay
        aligned with the serverless design.  For local simulations (e.g. unit
        tests or authoritative server for matchmaking) this naïve loop is fine.
        """
        errors: List[Tuple[str, Exception]] = []
        for system in self._systems:
            try:
                log.debug("Updating system %s (dt=%.4f)", system.name, dt)
                system.update(self, dt)
            except Exception as exc:  # pylint: disable=broad-except
                log.exception("System %s raised during update: %s", system.name, exc)
                errors.append((system.name, exc))

        if errors:
            # Bubble up aggregated errors as a single exception to stop the loop
            first_system, first_exc = errors[0]
            raise RuntimeError(
                f"{len(errors)} system(s) failed during update. "
                f"First failure: {first_system} -> {first_exc}"
            ) from first_exc

    # --------------------------------------------------------------------- #
    # Context manager helpers
    # --------------------------------------------------------------------- #

    class _ScopedMutation:  # noqa: D401
        """
        Context manager that batches event emission for mass updates.

        Example
        -------
        >>> with registry.batch_events():
        ...     for _ in range(100):
        ...         eid = registry.create_entity(publish_event=False)
        ...         registry.add_component(eid, Position(0, 0), publish_event=False)
        """
        def __init__(self, registry: "ECSRegistry") -> None:
            self._registry = registry
            self._events: List[Event] = []

        def __enter__(self) -> "ECSRegistry._ScopedMutation":
            self._orig_sink = self._registry._event_sink
            # Replace sink with ourselves; we just accumulate.
            self._registry._event_sink = self  # type: ignore[assignment]
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: D401
            # Restore original sink regardless of exceptions
            self._registry._event_sink = self._orig_sink
            if exc is None:
                for evt in self._events:
                    self._orig_sink.publish(evt)
            # If an exception happened inside the with-block, we suppress
            # nothing and let it propagate.
            return False

        # Implement EventSink protocol
        def publish(self, event: Event) -> None:  # noqa: D401
            self._events.append(event)

    def batch_events(self) -> "_ScopedMutation":
        """
        Return a context manager that defers event publication until exit.
        """
        return ECSRegistry._ScopedMutation(self)

    # --------------------------------------------------------------------- #
    # Diagnostics / Introspection
    # --------------------------------------------------------------------- #

    def dump(self) -> Dict[str, Any]:
        """
        Dump a serialisable snapshot of the registry for debugging.

        Returns
        -------
        dict
            {
                "entities": ["uuid-1", "uuid-2", ...],
                "components": {
                    "uuid-1": {"Position": {"x": 10, "y": 20}, ...},
                    ...
                },
                "systems": ["PhysicsSystem", "AISystem"]
            }
        """
        entities = list(self._backend.list_entities())
        components: Dict[str, Dict[str, Any]] = {}
        for e in entities:
            comps: Dict[str, Any] = {}
            for comp in self._backend.get_components(e):
                # Best-effort serialisation – assumes component has __dict__
                try:
                    comps[comp.type] = comp.__dict__
                except Exception:  # noqa: BLE001
                    comps[comp.type] = str(comp)
            components[e] = comps

        return {
            "entities": entities,
            "components": components,
            "systems": [s.name for s in self._systems],
        }
```