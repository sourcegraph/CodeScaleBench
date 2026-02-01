```python
"""
ledgerquest.engine.ecs
~~~~~~~~~~~~~~~~~~~~~~

A minimal yet production-ready Entity-Component-System (ECS) runtime that is
compatible with LedgerQuest’s fully-serverless execution model.  The goal of
this module is to provide an in-memory façade that *feels* like a traditional
game-loop driven ECS while remaining stateless between Lambda invocations.
Long-lived state can be (optionally) off-loaded to DynamoDB via the
`DynamoDBSnapshotAdapter`.

The API is intentionally compact:

    >>> world = World()
    >>> world.add_system(PhysicsSystem())
    >>> eid = world.create_entity()
    >>> world.add_component(eid, Transform(x=10, y=20))
    >>> world.update(dt=0.016)  # 60 FPS delta-time

The implementation keeps zero global state and is thus completely safe for
Lambda’s execution context reuse.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, fields, is_dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Generic,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

# Optional AWS import—engine still works when boto3 is not available.
try:
    import boto3  # pragma: no cover
    from botocore.exceptions import BotoCoreError, ClientError  # pragma: no cover
except ModuleNotFoundError:  # pragma: no cover
    boto3 = None  # type: ignore

__all__ = [
    "Component",
    "System",
    "World",
    "EventBus",
    "DynamoDBSnapshotAdapter",
]


################################################################################
# Logging setup
################################################################################
_logger = logging.getLogger("ledgerquest.ecs")
# In library code we *never* configure the root logger; we only set a noop
# handler to avoid "No handler found" warnings for casual users.
_logger.addHandler(logging.NullHandler())


################################################################################
# Component
################################################################################
T_co = TypeVar("T_co", bound="Component", covariant=True)


class Component:
    """
    Base-class for all components.  Concrete components **should** be declared
    as dataclasses:

        @dataclass
        class Transform(Component):
            x: float = 0.0
            y: float = 0.0
            rotation: float = 0.0
    """

    # --------------------------------------------------------------------- #
    # Serialization helpers                                                 #
    # --------------------------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the dataclass fields into a plain dict suitable for storage.

        Sub-classes that are *not* dataclasses may override this.
        """
        if is_dataclass(self):
            return asdict(self)
        # Fallback for non-dataclass components
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls: Type[T_co], data: Dict[str, Any]) -> T_co:  # noqa: D401
        """
        Reconstruct a component from the dictionary produced by :py:meth:`to_dict`.
        """
        try:
            return cls(**data)  # type: ignore[arg-type]
        except TypeError as exc:  # pragma: no cover
            raise ValueError(
                f"Failed to hydrate component {cls.__name__} "
                f"from data {json.dumps(data)}"
            ) from exc

    # --------------------------------------------------------------------- #
    # Convenience                                                           #
    # --------------------------------------------------------------------- #
    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} {self.to_dict()}>"


################################################################################
# System
################################################################################
class System:
    """
    Abstract base-class for systems.  Subclasses must implement :py:meth:`update`.

    A system *must not* hold internal mutable state between invocations if it
    will be executed in a serverless context.  Persist state externally or
    leverage :pyclass:`DynamoDBSnapshotAdapter`.
    """

    priority: int = 0  # Lower values execute *first*.

    def update(self, world: "World", dt: float) -> None:  # pragma: no cover
        """
        Perform one update tick.

        Parameters
        ----------
        world:
            The :class:`World` instance executing the system.
        dt:
            Delta-time in seconds.
        """
        raise NotImplementedError()


################################################################################
# Event Bus
################################################################################
EventCallback = Callable[[str, Dict[str, Any]], None]


class EventBus:
    """
    Extremely light-weight synchronous event bus used inside a single Lambda
    invocation.  If you need cross-invocation delivery use EventBridge.
    """

    __slots__ = ("_subscribers", "_lock")

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventCallback]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Subscription                                                       #
    # ------------------------------------------------------------------ #
    def subscribe(self, event_type: str, handler: EventCallback) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)
            _logger.debug("Subscribed %s to '%s'", handler, event_type)

    def unsubscribe(self, event_type: str, handler: EventCallback) -> None:
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)
                _logger.debug("Unsubscribed %s from '%s'", handler, event_type)

    # ------------------------------------------------------------------ #
    # Publishing                                                         #
    # ------------------------------------------------------------------ #
    def emit(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        payload = payload or {}
        handlers = self._subscribers.get(event_type, []).copy()

        _logger.debug("Emitting event '%s' to %d handler(s)", event_type, len(handlers))
        for handler in handlers:
            try:
                handler(event_type, payload)
            except Exception as exc:  # pragma: no cover
                _logger.exception("Event handler %s failed: %s", handler, exc)


################################################################################
# World
################################################################################
EntityId = str
C = TypeVar("C", bound=Component)


class World:
    """
    The central registry maintaining *entities*, *components* and *systems*.

    Note: A World instance is intentionally *not* a singleton.  Multiple worlds
    can coexist during unit tests or within a single Lambda invocation.
    """

    __slots__ = (
        "_components",
        "_systems",
        "_entities",
        "_event_bus",
        "_lock",
    )

    def __init__(self, *, event_bus: Optional[EventBus] = None) -> None:
        self._components: Dict[Type[Component], Dict[EntityId, Component]] = {}
        self._systems: List[System] = []
        self._entities: set[EntityId] = set()
        self._event_bus = event_bus or EventBus()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Entity management                                                  #
    # ------------------------------------------------------------------ #
    def create_entity(self, *, entity_id: Optional[EntityId] = None) -> EntityId:
        with self._lock:
            eid = entity_id or str(uuid.uuid4())
            if eid in self._entities:  # pragma: no cover
                raise ValueError(f"Entity {eid} already exists")
            self._entities.add(eid)

            _logger.debug("Created entity %s", eid)
            self._event_bus.emit("ecs.entity_created", {"entity_id": eid})
            return eid

    def destroy_entity(self, entity_id: EntityId, *, cascade: bool = True) -> None:
        with self._lock:
            if entity_id not in self._entities:
                raise KeyError(f"Entity {entity_id} does not exist")

            if cascade:
                for comp_map in self._components.values():
                    comp_map.pop(entity_id, None)
            self._entities.remove(entity_id)

            _logger.debug("Destroyed entity %s", entity_id)
            self._event_bus.emit("ecs.entity_destroyed", {"entity_id": entity_id})

    # ------------------------------------------------------------------ #
    # Component management                                               #
    # ------------------------------------------------------------------ #
    def add_component(self, entity_id: EntityId, component: Component) -> None:
        if entity_id not in self._entities:
            raise KeyError(f"Entity {entity_id} does not exist")

        with self._lock:
            comp_map = self._components.setdefault(type(component), {})
            if entity_id in comp_map:
                raise ValueError(
                    f"Entity {entity_id} already has component {type(component).__name__}"
                )
            comp_map[entity_id] = component

            _logger.debug(
                "Added component %s to entity %s", type(component).__name__, entity_id
            )
            self._event_bus.emit(
                "ecs.component_added",
                {
                    "entity_id": entity_id,
                    "component_type": component.__class__.__name__,
                },
            )

    def remove_component(self, entity_id: EntityId, component_type: Type[C]) -> None:
        with self._lock:
            comp_map = self._components.get(component_type)
            if not comp_map or entity_id not in comp_map:
                raise KeyError(
                    f"Entity {entity_id} does not have component {component_type}"
                )
            del comp_map[entity_id]

            _logger.debug(
                "Removed component %s from entity %s", component_type.__name__, entity_id
            )
            self._event_bus.emit(
                "ecs.component_removed",
                {
                    "entity_id": entity_id,
                    "component_type": component_type.__name__,
                },
            )

    def get_component(self, entity_id: EntityId, component_type: Type[C]) -> C:
        comp_map = self._components.get(component_type, {})
        try:
            return comp_map[entity_id]  # type: ignore[return-value]
        except KeyError as exc:  # pragma: no cover
            raise KeyError(
                f"Entity {entity_id} does not have component {component_type}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Queries                                                            #
    # ------------------------------------------------------------------ #
    def query(
        self, *component_types: Type[Component]
    ) -> Generator[Tuple[EntityId, Tuple[Component, ...]], None, None]:
        """
        Yield entities that have **all** of the specified component types.

        Example
        -------
        >>> for eid, (trans, vel) in world.query(Transform, Velocity):
        ...     ...
        """
        if not component_types:
            return

        # Short-circuit for 1-component query (fast-path).
        first_map = self._components.get(component_types[0], {})
        entity_ids = set(first_map.keys())

        for comp_type in component_types[1:]:
            entity_ids &= set(self._components.get(comp_type, {}).keys())

        for eid in entity_ids:
            yield eid, tuple(
                self._components[comp_type][eid] for comp_type in component_types
            )

    # ------------------------------------------------------------------ #
    # System management & update                                         #
    # ------------------------------------------------------------------ #
    def add_system(self, system: System) -> None:
        with self._lock:
            self._systems.append(system)
            self._systems.sort(key=lambda s: s.priority)
            _logger.debug("Added system %s (priority=%d)", system, system.priority)

    def remove_system(self, system: System) -> None:
        with self._lock:
            self._systems.remove(system)
            _logger.debug("Removed system %s", system)

    def update(self, dt: float) -> None:
        """
        Execute one ECS tick.

        The call order is:
            1. Systems are executed in ascending order of :pyattr:`System.priority`.
            2. All event bus processing is synchronous.
        """
        # Capture a *snapshot* of systems because they may mutate the list.
        systems = self._systems.copy()
        _logger.debug("World update started with %d system(s)", len(systems))

        for system in systems:
            try:
                system.update(self, dt)
            except Exception:  # pragma: no cover
                _logger.exception("System %s failed during update", system)
                # Do not propagate to avoid cascading Lambda failures.

        _logger.debug("World update finished")


################################################################################
# Persistence
################################################################################
class DynamoDBSnapshotAdapter:
    """
    Optional persistence layer for Worlds using DynamoDB.

    The adapter serializes component data as JSON strings, storing one item per
    component instance.  The schema is intentionally simple:

        PK = world_id#<WORLD>
        SK = entity_id#component#<COMPONENT_TYPE>

    Only world-scale games should use this directly; turn-based business games
    usually require less frequent, macro-level snapshots (e.g., at the end of a
    financial quarter), but the adapter is provided for convenience.

    This class is *lazy*—it will no-op if boto3 is not available or no table
    name is configured.
    """

    _TABLE_ENV = "LEDGERQUEST_DDB_TABLE"

    def __init__(self, table_name: Optional[str] = None) -> None:
        if boto3 is None:
            raise RuntimeError(
                "boto3 is required for DynamoDBSnapshotAdapter but is not installed"
            )

        self.table_name = table_name or os.getenv(self._TABLE_ENV)
        if not self.table_name:
            raise ValueError(
                "DynamoDB table name must be provided or set via "
                f"${self._TABLE_ENV}"
            )

        self._table = boto3.resource("dynamodb").Table(self.table_name)
        _logger.debug("DynamoDBSnapshotAdapter bound to table %s", self.table_name)

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #
    def save_world(self, world_id: str, world: World) -> None:
        """
        Persist the entire world to DynamoDB in a *best effort* fashion.  This
        method is **not** transactional—partial writes may occur if a Lambda
        times out midway.
        """
        with world._lock:  # pylint: disable=protected-access
            for comp_type, comp_map in world._components.items():
                comp_name = comp_type.__name__

                for entity_id, component in comp_map.items():
                    item = {
                        "pk": f"world#{world_id}",
                        "sk": f"entity#{entity_id}#component#{comp_name}",
                        "component_data": json.dumps(component.to_dict()),
                    }
                    try:
                        self._table.put_item(Item=item)
                    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
                        _logger.error(
                            "Failed to save component %s of entity %s: %s",
                            comp_name,
                            entity_id,
                            exc,
                        )

    def load_world(self, world_id: str) -> World:
        """
        Reconstruct a :class:`World` instance previously stored by
        :py:meth:`save_world`.  Unknown component classes are skipped with a
        warning (e.g., when code has been refactored).
        """
        world = World()

        try:
            response = self._table.query(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": f"world#{world_id}"},
            )
        except (BotoCoreError, ClientError) as exc:  # pragma: no cover
            _logger.error("Failed to load world %s: %s", world_id, exc)
            return world

        for item in response.get("Items", []):
            _, entity_token, _, comp_name = item["sk"].split("#", 3)
            entity_id = entity_token

            # Dynamically resolve component class.
            comp_cls = self._resolve_component_class(comp_name)
            if comp_cls is None:
                _logger.warning(
                    "Component class %s no longer exists; skipping.", comp_name
                )
                continue

            comp_data = json.loads(item["component_data"])
            component = comp_cls.from_dict(comp_data)  # type: ignore[arg-type]

            if entity_id not in world._entities:  # pylint: disable=protected-access
                world.create_entity(entity_id=entity_id)
            world.add_component(entity_id, component)

        return world

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_component_class(name: str) -> Optional[Type[Component]]:
        """
        Resolve a component class by name, assuming it has been imported into
        the current interpreter session.
        """
        for cls in Component.__subclasses__():
            if cls.__name__ == name:
                return cls
        return None
```