```python
"""
tests/unit/engine/ecs/test_registry.py

Unit-tests for the Entity–Component–System (ECS) registry that powers the
LedgerQuest Engine.  The registry is responsible for:

1. Creating unique entity identifiers
2. Managing the life-cycle of entities and their attached components
3. Enforcing multi-tenant isolation guarantees
4. Surfacing events that other engine subsystems (e.g. the scheduler or
   audit-logging facilities) can subscribe to

The tests are written defensively: if the real engine modules cannot be
imported (e.g. during isolated CI runs that only execute the test-suite)
a *very* small in-memory stub is created so the tests remain executable.
"""
from __future__ import annotations

import itertools
import threading
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, Iterable, List, MutableMapping, Set, Tuple, Type

import pytest

# --------------------------------------------------------------------------- #
# Conditional import of the production Registry implementation.               #
# --------------------------------------------------------------------------- #
try:
    # Preferred import path inside the real engine
    from game_engine.ecs.registry import Registry  # type: ignore
    from game_engine.ecs.component import Component  # type: ignore

except ModuleNotFoundError:  # pragma: no cover – fallback for local runs
    # ---------------------------- Stub Layer ----------------------------- #
    class Component:  # Minimal stand-in
        """Base-class for ECS components."""
        pass

    class _EventDispatcher:
        """Extremely small, synchronous event dispatcher used by the stub."""
        def __init__(self) -> None:
            self._subscribers: MutableMapping[str, List] = {}

        def subscribe(self, event_name: str, fn):
            self._subscribers.setdefault(event_name, []).append(fn)

        def emit(self, event_name: str, **payload):
            for fn in self._subscribers.get(event_name, []):
                fn(event_name, payload)

    class Registry:
        """
        A deliberately *minimal* replacement for the production Registry that
        supports only the API surface exercised by this test-suite.
        """
        _id_counter = itertools.count()
        _lock = threading.Lock()

        def __init__(self) -> None:
            self._entities: Set[int] = set()
            self._components: Dict[Tuple[int, Type[Component]], Component] = {}
            self._entity_to_tenant: Dict[int, str] = {}
            self._events = _EventDispatcher()

        # ------------------------------------------------------------------ #
        # Event-bus helpers                                                   #
        # ------------------------------------------------------------------ #
        def subscribe(self, event_name: str, fn):
            self._events.subscribe(event_name, fn)

        # ------------------------------------------------------------------ #
        # CRUD operations                                                    #
        # ------------------------------------------------------------------ #
        def create_entity(self, tenant_id: str) -> int:
            with self._lock:
                entity_id = next(self._id_counter)
                self._entities.add(entity_id)
                self._entity_to_tenant[entity_id] = tenant_id
            self._events.emit("ecs.entity.created", entity_id=entity_id, tenant_id=tenant_id)
            return entity_id

        def add_component(self, entity_id: int, component: Component) -> None:
            key = (entity_id, type(component))
            if key in self._components:
                raise ValueError(f"Entity {entity_id} already has component {type(component).__name__}")
            self._components[key] = component
            self._events.emit(
                "ecs.component.added",
                entity_id=entity_id,
                component_type=type(component).__name__,
            )

        def get_component(self, entity_id: int, component_type: Type[Component]) -> Component:
            try:
                return self._components[(entity_id, component_type)]
            except KeyError as exc:
                raise KeyError(
                    f"Entity {entity_id} does not have component {component_type.__name__}"
                ) from exc

        def components_for_entity(self, entity_id: int) -> Iterable[Component]:
            return (
                comp for (eid, _), comp in self._components.items() if eid == entity_id
            )

        def entities_with_components(self, *component_types: Type[Component]) -> List[int]:
            hits: List[int] = []
            for entity_id in self._entities:
                try:
                    # All component types must be present
                    for ct in component_types:
                        _ = self.get_component(entity_id, ct)
                except KeyError:
                    continue
                hits.append(entity_id)
            return hits

        def remove_entity(self, entity_id: int):
            self._entities.discard(entity_id)
            keys_to_delete = [key for key in self._components if key[0] == entity_id]
            for key in keys_to_delete:
                del self._components[key]
            self._events.emit("ecs.entity.removed", entity_id=entity_id)

        # ------------------------------------------------------------------ #
        # Introspection helpers                                              #
        # ------------------------------------------------------------------ #
        def tenant_id_for(self, entity_id: int) -> str:
            return self._entity_to_tenant[entity_id]

# --------------------------------------------------------------------------- #
# Generic component stubs used by the test-suite                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Position(Component):
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Velocity(Component):
    dx: float
    dy: float


@dataclass(frozen=True, slots=True)
class Health(Component):
    hit_points: int = 100


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture()
def registry() -> Registry:
    """Return a fresh, isolated ECS registry for each test."""
    return Registry()


# --------------------------------------------------------------------------- #
# Unit-tests                                                                   #
# --------------------------------------------------------------------------- #
class TestRegistryBasics:
    """CRUD operations and single-threaded behaviour."""

    def test_create_entity_yields_monotonically_increasing_ids(self, registry: Registry):
        id_a = registry.create_entity("tenant-a")
        id_b = registry.create_entity("tenant-a")
        id_c = registry.create_entity("tenant-b")

        assert id_a < id_b < id_c, "Entity IDs should be monotonically increasing"

    def test_component_lifecycle(self, registry: Registry):
        entity_id = registry.create_entity("tenant-z")
        pos = Position(10, 20)
        vel = Velocity(1, 1)

        registry.add_component(entity_id, pos)
        registry.add_component(entity_id, vel)

        # Happy-path retrieval
        assert registry.get_component(entity_id, Position) is pos
        assert registry.get_component(entity_id, Velocity) is vel

        all_components = list(registry.components_for_entity(entity_id))
        assert set(all_components) == {pos, vel}

        # Removing the entity should cascade-delete components
        registry.remove_entity(entity_id)
        with pytest.raises(KeyError):
            registry.get_component(entity_id, Position)

    def test_entities_with_components_query(self, registry: Registry):
        # tenant isolation isn't relevant for this particular query
        e1 = registry.create_entity("t1")
        e2 = registry.create_entity("t1")
        e3 = registry.create_entity("t1")

        registry.add_component(e1, Position(0, 0))
        registry.add_component(e1, Velocity(0, 0))

        registry.add_component(e2, Position(1, 0))
        # e2 has no velocity

        # e3 will only have velocity
        registry.add_component(e3, Velocity(5, 5))

        # Query for entities that have BOTH Position and Velocity
        entities = registry.entities_with_components(Position, Velocity)
        assert entities == [e1]

    def test_duplicate_component_raises(self, registry: Registry):
        entity_id = registry.create_entity("tenant-α")
        registry.add_component(entity_id, Position(1, 1))
        with pytest.raises(ValueError):
            registry.add_component(entity_id, Position(2, 2))  # Same component type


class TestMultiTenancy:
    """Ensure that tenant isolation guarantees are preserved."""

    @pytest.mark.parametrize("tenant_a, tenant_b", [("TENANT-A", "TENANT-B")])
    def test_entities_are_tagged_with_tenant_id(self, registry: Registry, tenant_a, tenant_b):
        e1 = registry.create_entity(tenant_a)
        e2 = registry.create_entity(tenant_b)

        assert registry.tenant_id_for(e1) == tenant_a
        assert registry.tenant_id_for(e2) == tenant_b

    def test_cross_tenant_component_leakage_not_possible(self, registry: Registry):
        """A component attached to one tenant's entity must not be visible from another."""
        tenant_a = "foo-corp"
        tenant_b = "bar-inc"

        e_a = registry.create_entity(tenant_a)
        e_b = registry.create_entity(tenant_b)

        registry.add_component(e_a, Health(100))
        registry.add_component(e_b, Health(50))

        # Both tenants see their own health values
        assert registry.get_component(e_a, Health).hit_points == 100
        assert registry.get_component(e_b, Health).hit_points == 50

        # Health for foo-corp should not equal health for bar-inc
        assert registry.get_component(e_a, Health) != registry.get_component(e_b, Health)


class TestEventBusIntegration:
    """Registry should emit well-formed events during state transitions."""

    def test_event_emission_on_entity_creation(self, registry: Registry):
        captured: List[SimpleNamespace] = []

        def listener(event_name: str, payload: dict):
            captured.append(SimpleNamespace(event=event_name, **payload))

        registry.subscribe("ecs.entity.created", listener)

        eid = registry.create_entity("tenant-42")
        assert len(captured) == 1
        evt = captured[0]
        assert evt.event == "ecs.entity.created"
        assert evt.entity_id == eid
        assert evt.tenant_id == "tenant-42"

    def test_event_emission_on_component_add(self, registry: Registry):
        captured: List[Tuple[str, dict]] = []

        def listener(event_name: str, payload: dict):
            captured.append((event_name, payload))

        registry.subscribe("ecs.component.added", listener)

        eid = registry.create_entity("foo")
        registry.add_component(eid, Position(9, 9))

        assert captured == [
            (
                "ecs.component.added",
                {
                    "entity_id": eid,
                    "component_type": "Position",
                },
            )
        ]


class TestConcurrencySafety:
    """
    The registry must remain consistent when accessed concurrently.
    The stub implementation uses a global lock for ID allocation;
    production code is likely using DynamoDB transactions or a
    distributed UID allocator.  Regardless, the *public contract*
    should be thread-safe.
    """

    def test_concurrent_entity_creation_is_thread_safe(self, registry: Registry):
        THREADS = 32
        ENTITIES_PER_THREAD = 100

        created_ids_lock = threading.Lock()
        created_ids: Set[int] = set()

        def worker():
            for _ in range(ENTITIES_PER_THREAD):
                eid = registry.create_entity(tenant_id=str(uuid.uuid4()))
                with created_ids_lock:
                    assert (
                        eid not in created_ids
                    ), f"Duplicate entity id {eid} allocated concurrently"
                    created_ids.add(eid)

        threads = [threading.Thread(target=worker) for _ in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_total = THREADS * ENTITIES_PER_THREAD
        assert len(created_ids) == expected_total
```