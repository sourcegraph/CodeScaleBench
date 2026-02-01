```python
"""
ledgerquest.engine.ecs.entity
=============================

Core Entity/Component abstractions for the LedgerQuest Engine.

The ECS (Entity–Component–System) design used by LedgerQuest decouples
behaviour (systems) from state (components) and identity (entities).  This
module focuses on the first two pieces, providing a production-ready:

* `Component`            – light-weight data holders with (de)serialisation
* `ComponentRegistry`    – string <-> type mapping for persistence
* `Entity`               – runtime container with optimistic-locking revision
                           counter, delta tracking and helpful ergonomics

NOTE:
    No cloud-specific code is present here; persistence back-ends such as
    DynamoDB or S3 and event buses (EventBridge) are handled in dedicated
    repository layers.  Keeping this module pure Python makes unit testing and
    local simulation straightforward.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from dataclasses import asdict, is_dataclass
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Set,
    Type,
    TypeVar,
)

__all__ = [
    "Component",
    "ComponentRegistry",
    "DEFAULT_COMPONENT_REGISTRY",
    "register_component",
    "Entity",
]

_LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Component                                                                  #
# --------------------------------------------------------------------------- #
C = TypeVar("C", bound="Component")


class Component:
    """
    Base-class for ECS components.

    Sub-classes are expected to be *mostly* plain data containers.  If the
    subclass is a `@dataclass`, (de)serialisation is automatically provided; for
    anything more exotic, simply override `serialise`/`deserialise`.

    A component MUST be fully serialisable to a JSON compatible structure – the
    engine routinely persists entities to DynamoDB for long-lived state.
    """

    # Slotting prevents accidental attribute creation and saves memory.
    __slots__: Iterable[str] = ()

    # --------------------------------------------------------------------- #
    #  (De)Serialisation helpers                                             #
    # --------------------------------------------------------------------- #
    def serialise(self) -> Dict[str, Any]:
        """Return a JSON-safe dict of the component."""
        if is_dataclass(self):
            return asdict(self)
        raise NotImplementedError(
            f"{self.__class__.__name__}.serialise() must be implemented or "
            "use @dataclass for automatic support."
        )

    @classmethod
    def deserialise(cls: Type[C], payload: Mapping[str, Any]) -> C:
        """Recreate a component from JSON-safe data."""
        if is_dataclass(cls):
            # type: ignore[return-value] – dataclass ctor matches fields.
            return cls(**payload)  # pyright: ignore
        raise NotImplementedError(
            f"{cls.__name__}.deserialise() must be implemented or "
            "use @dataclass for automatic support."
        )

    # --------------------------------------------------------------------- #
    #  Hooks                                                                 #
    # --------------------------------------------------------------------- #
    # The following hooks are meant for Systems that need to react to high
    #-level component lifecycle events (e.g. AI blackboard cache invalidation).
    # Implement wisely – they run synchronously in the same process.
    def on_added_to_entity(self, entity_id: str) -> None:  # noqa: D401
        """Called immediately after the component has been attached."""
        _LOGGER.debug(
            "Component %s added to Entity(%s)", self.__class__.__name__, entity_id
        )

    def on_removed_from_entity(self, entity_id: str) -> None:  # noqa: D401
        """Called immediately after the component has been detached."""
        _LOGGER.debug(
            "Component %s removed from Entity(%s)", self.__class__.__name__, entity_id
        )


# --------------------------------------------------------------------------- #
#  Component Registry                                                         #
# --------------------------------------------------------------------------- #
class ComponentRegistry:
    """
    Maps component classes to *wire-names* and vice-versa.

    Using a registry decouples storage formats (human friendly strings) from
    implementation details (fully qualified Python paths).  It also allows us
    to perform run-time validation when deserialising untrusted payloads.
    """

    def __init__(self) -> None:
        self._type_to_name: Dict[Type[Component], str] = {}
        self._name_to_type: Dict[str, Type[Component]] = {}

    # --------------------------------------------------------------------- #
    #  Registration                                                          #
    # --------------------------------------------------------------------- #
    def register(self, component_cls: Type[C], *, name: Optional[str] = None) -> None:
        if not issubclass(component_cls, Component):
            raise TypeError("Only subclasses of Component can be registered")

        _name = name or component_cls.__name__
        if (
            _name in self._name_to_type
            and self._name_to_type[_name] is not component_cls
        ):
            raise ValueError(f"Component name '{_name}' already registered")

        self._type_to_name[component_cls] = _name
        self._name_to_type[_name] = component_cls
        _LOGGER.debug("Registered component: %s → '%s'", component_cls, _name)

    # --------------------------------------------------------------------- #
    #  Lookup                                                                #
    # --------------------------------------------------------------------- #
    def name_for(self, component_cls: Type[Component]) -> str:
        try:
            return self._type_to_name[component_cls]
        except KeyError as exc:
            raise KeyError(
                f"Component class {component_cls!r} has not been registered"
            ) from exc

    def type_for(self, name: str) -> Type[Component]:
        try:
            return self._name_to_type[name]
        except KeyError as exc:
            raise KeyError(f"Unknown component name '{name}'") from exc

    # --------------------------------------------------------------------- #
    #  Utilities                                                             #
    # --------------------------------------------------------------------- #
    def ensure_registered(self, component: Component) -> None:
        """
        Raise a helpful error early if the caller attempts to use an unregistered
        component.
        """
        if component.__class__ not in self._type_to_name:
            raise ValueError(
                f"Component {component.__class__.__qualname__} is not registered "
                "– use @register_component or ComponentRegistry.register first."
            )


DEFAULT_COMPONENT_REGISTRY = ComponentRegistry()


def register_component(name: Optional[str] = None):
    """
    Decorator – sugar around `DEFAULT_COMPONENT_REGISTRY.register`.

    Example:
        >>> @register_component()
        ... @dataclass
        ... class Position(Component):
        ...     x: float
        ...     y: float
    """

    def _decorator(cls: Type[C]) -> Type[C]:
        DEFAULT_COMPONENT_REGISTRY.register(cls, name=name)
        return cls

    return _decorator


# --------------------------------------------------------------------------- #
#  Entity                                                                     #
# --------------------------------------------------------------------------- #
T = TypeVar("T", bound=Component)


class Entity:
    """
    An *Entity* is little more than a unique identifier plus a bag of
    components.  The actual game logic lives in Systems that operate on
    entities possessing specific component subsets.

    Attributes
    ----------
    entity_id:
        Globally unique identifier.  ULIDs would be even nicer, but uuid4 is
        still the best-supported built-in solution.
    revision:
        Monotonically increasing optimistic-locking counter.  External
        repositories (e.g. the DynamoDB adapter) compare this value to detect
        write conflicts.
    tags:
        Arbitrary user-defined labels useful for queries or editor tooling.
    """

    __slots__ = (
        "_components",
        "entity_id",
        "revision",
        "tags",
        "_dirty_components",
        "_dirty",
        "_registry",
    )

    # --------------------------------------------------------------------- #
    #  Construction                                                          #
    # --------------------------------------------------------------------- #
    def __init__(
        self,
        *,
        entity_id: Optional[str] = None,
        components: Optional[Iterable[Component]] = None,
        tags: Optional[Iterable[str]] = None,
        registry: ComponentRegistry = DEFAULT_COMPONENT_REGISTRY,
        revision: int = 0,
    ) -> None:
        self.entity_id: str = entity_id or str(uuid.uuid4())
        self.revision: int = revision  # optimistic-locking counter
        self.tags: Set[str] = set(tags or [])

        self._components: Dict[Type[Component], Component] = {}
        self._dirty_components: Set[Type[Component]] = set()
        self._dirty: bool = False

        self._registry: ComponentRegistry = registry

        if components:
            for component in components:
                self.add_component(component, replace=True, mark_dirty=False)

        _LOGGER.debug(
            "Created Entity(%s) with %d components",
            self.entity_id,
            len(self._components),
        )

    # --------------------------------------------------------------------- #
    #  Component CRUD                                                        #
    # --------------------------------------------------------------------- #
    def add_component(
        self,
        component: Component,
        *,
        replace: bool = False,
        mark_dirty: bool = True,
    ) -> None:
        """
        Attach a component.  If 'replace' is True, an existing component of the
        same type will be silently overwritten; otherwise a `ValueError` is
        raised.
        """
        self._registry.ensure_registered(component)
        comp_type = type(component)

        if comp_type in self._components and not replace:
            raise ValueError(
                f"Entity({self.entity_id}) already has a component of "
                f"type {comp_type.__name__!r}"
            )

        self._components[comp_type] = component
        component.on_added_to_entity(self.entity_id)

        if mark_dirty:
            self._mark_dirty(comp_type)

    def remove_component(self, component_cls: Type[T]) -> T:
        """
        Detach component and return it.  Raises `KeyError` if not present.
        """
        if component_cls not in self._components:
            raise KeyError(
                f"Entity({self.entity_id}) has no component "
                f"of type {component_cls.__name__!r}"
            )

        component: T = self._components.pop(component_cls)  # type: ignore[assignment]
        component.on_removed_from_entity(self.entity_id)

        self._mark_dirty(component_cls)
        return component

    def get_component(self, component_cls: Type[T]) -> T:
        """Return component or raise `KeyError`."""
        try:
            return self._components[component_cls]  # type: ignore[return-value]
        except KeyError as exc:
            raise KeyError(
                f"Entity({self.entity_id}) has no component "
                f"of type {component_cls.__name__}"
            ) from exc

    def try_get_component(self, component_cls: Type[T]) -> Optional[T]:
        """Return component if present, otherwise `None`."""
        return self._components.get(component_cls)  # type: ignore[return-value]

    def has_component(self, component_cls: Type[Component]) -> bool:
        """Shorthand for `component_cls in entity` style checks."""
        return component_cls in self._components

    # --------------------------------------------------------------------- #
    #  Component iteration                                                   #
    # --------------------------------------------------------------------- #
    def components(self) -> Iterator[Component]:
        """Yield all attached components."""
        return iter(self._components.values())

    def component_types(self) -> Iterator[Type[Component]]:
        """Yield the *types* of attached components."""
        return iter(self._components.keys())

    # --------------------------------------------------------------------- #
    #  Dirty tracking                                                        #
    # --------------------------------------------------------------------- #
    def _mark_dirty(self, component_cls: Optional[Type[Component]] = None) -> None:
        self._dirty = True
        if component_cls:
            self._dirty_components.add(component_cls)

    def clear_dirty(self) -> None:
        """Reset dirty flags after persistence."""
        self._dirty = False
        self._dirty_components.clear()

    @property
    def is_dirty(self) -> bool:
        """Return True if any modification has occurred since `clear_dirty`."""
        return self._dirty

    @property
    def dirty_components(self) -> Set[Type[Component]]:
        return set(self._dirty_components)

    # --------------------------------------------------------------------- #
    #  Serialisation                                                         #
    # --------------------------------------------------------------------- #
    def serialise(
        self,
        *,
        include_revision: bool = True,
        only_dirty: bool = False,
    ) -> Dict[str, Any]:
        """
        Convert entity into a JSON-safe dict suitable for storage or wire
        transfer.

        Args
        ----
        include_revision:
            The revision number is needed by repositories implementing
            optimistic locking.
        only_dirty:
            When True, only components that have been changed since the last
            persistence will be included.  This can drastically reduce payload
            size for large entities.
        """
        payload: Dict[str, Any] = {
            "id": self.entity_id,
            "tags": list(self.tags),
        }
        if include_revision:
            payload["revision"] = self.revision

        components_dict: Dict[str, Dict[str, Any]] = {}
        for comp_type, component in self._components.items():
            if only_dirty and comp_type not in self._dirty_components:
                continue
            name = self._registry.name_for(comp_type)
            components_dict[name] = component.serialise()

        payload["components"] = components_dict
        return payload

    @classmethod
    def deserialise(
        cls,
        payload: Mapping[str, Any],
        *,
        registry: ComponentRegistry = DEFAULT_COMPONENT_REGISTRY,
    ) -> "Entity":
        """
        Reconstruct an `Entity` from its serialised representation.

        Unknown component names raise `KeyError` – this is an intentional guard
        against stale client payloads or tampering.
        """
        entity = cls(
            entity_id=str(payload["id"]),
            tags=payload.get("tags", []),
            revision=payload.get("revision", 0),
            registry=registry,
        )

        components_blob: Mapping[str, Dict[str, Any]] = payload.get("components", {})
        for name, component_data in components_blob.items():
            comp_cls = registry.type_for(name)
            component = comp_cls.deserialise(component_data)
            entity.add_component(component, replace=False, mark_dirty=False)

        entity.clear_dirty()  # pristine after fresh load
        return entity

    # --------------------------------------------------------------------- #
    #  Cloning                                                               #
    # --------------------------------------------------------------------- #
    def clone(self, *, deep: bool = True) -> "Entity":
        """
        Create a copy of the entity.  The new entity receives a fresh UUID and
        starts with revision 0.  Components are deep-copied by default so that
        mutating the clone does not affect the original.
        """
        components = (
            (copy.deepcopy(comp) if deep else comp)
            for comp in self._components.values()
        )
        clone_entity = Entity(components=components, tags=self.tags.copy())
        return clone_entity

    # --------------------------------------------------------------------- #
    #  String helpers                                                        #
    # --------------------------------------------------------------------- #
    def __contains__(self, component_cls: Type[Component]) -> bool:  # noqa: Dunder
        return self.has_component(component_cls)

    def __iter__(self) -> Iterator[Component]:  # noqa: Dunder
        return self.components()

    def __repr__(self) -> str:  # noqa: Dunder
        comps = ", ".join(c.__class__.__name__ for c in self._components.values())
        return f"<Entity id={self.entity_id} comps=[{comps}] rev={self.revision}>"

    # --------------------------------------------------------------------- #
    #  Debugging                                                             #
    # --------------------------------------------------------------------- #
    def to_json(self, *, indent: int = 2, **kwargs: Any) -> str:
        """Pretty-print the serialised entity – handy during development."""
        return json.dumps(self.serialise(), indent=indent, **kwargs)
```