```python
"""
ledgerquest.engine.ecs.component
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Core abstractions for the Entity-Component-System (ECS) layer.

LedgerQuest runs on a server-less, event-driven backbone.  Consequently,
component instances must be:

* Immutable in transit – serialisable to JSON/EventBridge.
* Persistable – convertible to/from DynamoDB attribute maps.
* Concurrency-safe – include optimistic‐locking metadata.
* Observable – raise internal events when state changes (dirty flag).

The module purposefully contains *no* game-specific data fields; concrete
components (Position, Inventory, Wallet, etc.) live in their own modules
and inherit from :class:`Component`.

Usage
-----

>>> from ledgerquest.engine.ecs.component import Component
>>> from dataclasses import dataclass
>>>
>>> @dataclass
... class Position(Component):
...     x: float = 0.0
...     y: float = 0.0
...
>>> pos = Position(entity_id="e-123")
>>> pos.x += 10
>>> pos.mark_dirty()
>>> pos.save(table_name="GameComponents")      # Persist to DynamoDB
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Optional, Type, TypeVar

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO"))

_T = TypeVar("_T", bound="Component")


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ComponentError(Exception):
    """Base‐class for all component related exceptions."""


class ComponentValidationError(ComponentError):
    """Raised when :pymeth:`Component.validate` fails."""


class ComponentPersistenceError(ComponentError):
    """Raised when a component cannot be stored or retrieved."""


# --------------------------------------------------------------------------- #
# Helper utils
# --------------------------------------------------------------------------- #


def _now_utc() -> datetime:
    """Returns current time (UTC, timezone aware)."""
    return datetime.now(timezone.utc)


def _datetime_to_iso(dt: datetime) -> str:
    """Converts a datetime to ISO-8601 string with milliseconds."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _iso_to_datetime(value: str) -> datetime:
    """Parses an ISO-8601 string back to a datetime instance."""
    return datetime.fromisoformat(value).astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


class _ComponentRegistry:
    """
    Global component registry used for dynamic deserialisation.

    Keyed by ``component_type`` (fully qualified class name).
    """

    _registry: Dict[str, Type["Component"]] = {}

    @classmethod
    def register(cls, component_cls: Type["Component"]) -> None:
        fqcn = component_cls.fqcn()
        if fqcn in cls._registry:
            # Multiple imports of the same module (e.g., in a Lambda warm/reload)
            # can re-register the exact same class; only warn when fingerprints
            # differ.
            if cls._registry[fqcn] is not component_cls:
                logger.warning(
                    "Component type re-registration collision: %s", fqcn
                )
        cls._registry[fqcn] = component_cls
        logger.debug("Registered component type: %s", fqcn)

    @classmethod
    def resolve(cls, fqcn: str) -> Type["Component"]:
        try:
            return cls._registry[fqcn]
        except KeyError as err:
            raise ComponentError(f"Unknown component type: {fqcn}") from err


# --------------------------------------------------------------------------- #
# Metaclass that auto-registers components
# --------------------------------------------------------------------------- #


class _ComponentMeta(type):
    """Metaclass to automatically register concrete component implementations."""

    def __init__(cls, name, bases, namespace, **kwargs):
        super().__init__(name, bases, namespace)
        # Skip registration for abstract base class itself
        if "Component" in [base.__name__ for base in bases]:
            _ComponentRegistry.register(cls)


# --------------------------------------------------------------------------- #
# Component base
# --------------------------------------------------------------------------- #


@dataclass(eq=False)
class Component(metaclass=_ComponentMeta):
    """
    Base Entity-Component class.

    Concrete subclasses *must* be :pymod:`dataclasses.dataclass`-decorated in
    order for (de)serialisation to work properly.
    """

    # --------------------------------------------------------------------- #
    # Core ECS metadata
    # --------------------------------------------------------------------- #

    entity_id: str
    component_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Optimistic locking & lifecycle
    created_at: datetime = field(default_factory=_now_utc, init=False)
    updated_at: datetime = field(default_factory=_now_utc, init=False)
    version: int = field(default=0, init=False)

    # Transient flags (not persisted)
    _dirty: bool = field(default=False, init=False, repr=False, compare=False)

    # --------------------------------------------------------------------- #
    # Class helpers
    # --------------------------------------------------------------------- #

    @classmethod
    def fqcn(cls) -> str:
        """Fully-qualified class name."""
        return f"{cls.__module__}.{cls.__qualname__}"

    # --------------------------------------------------------------------- #
    # Validation & dirty-tracking
    # --------------------------------------------------------------------- #

    def mark_dirty(self) -> None:
        """Marks the component as modified."""
        self._dirty = True
        self.updated_at = _now_utc()
        self.version += 1
        logger.debug(
            "Component %s marked dirty (version=%d)", self.component_id, self.version
        )

    def reset_dirty(self) -> None:
        """Reset the dirty flag after a successful persistence action."""
        self._dirty = False

    def validate(self) -> None:
        """
        Perform domain validation.

        Subclasses should override and raise
        :class:`ComponentValidationError` when failing.
        """

    # --------------------------------------------------------------------- #
    # Serialisation helpers
    # --------------------------------------------------------------------- #

    def _as_serialisable_dict(self) -> Dict[str, Any]:
        """
        Convert self to a JSON-serialisable ``dict``.
        Dataclasses' :func:`asdict` will deep-copy nested dataclasses, which
        is fine for our use case.
        """
        if not is_dataclass(self):
            raise ComponentError(
                "Component subclass must be a dataclass for serialisation"
            )

        payload: Dict[str, Any] = asdict(self)

        # Keep runtime only fields out of the serialised form
        payload.pop("_dirty", None)

        # Convert datetimes to ISO strings
        for key in ("created_at", "updated_at"):
            payload[key] = _datetime_to_iso(payload[key])

        # Inject component type for dynamic reconstruction
        payload["component_type"] = self.fqcn()

        return payload

    def to_json(self) -> str:
        """Serialise component to JSON (EventBridge friendly)."""
        return json.dumps(self._as_serialisable_dict(), separators=(",", ":"))

    def to_dynamo_item(self) -> Dict[str, Any]:
        """
        Convert to a DynamoDB attribute map.  Datetimes -> ISO strings.

        Note: DynamoDB distinguishes numbers and strings; version numbers are
        stored as numbers for efficient conditional updates.
        """
        item = self._as_serialisable_dict()
        item["version"] = self.version  # ensure int
        return item

    # --------------------------------------------------------------------- #
    # Deserialisation helpers
    # --------------------------------------------------------------------- #

    @classmethod
    def from_dict(cls: Type[_T], payload: Dict[str, Any]) -> _T:
        """
        Reconstruct a component *instance* from a plain dict.

        ``payload`` should include the ``component_type`` key used for dynamic
        resolution when called via :pymeth:`Component.loads`.
        """
        kwargs = payload.copy()
        for key in ("created_at", "updated_at"):
            if isinstance(kwargs.get(key), str):
                kwargs[key] = _iso_to_datetime(kwargs[key])

        # Transient flags
        kwargs["_dirty"] = False

        instance = cls(**{k: v for k, v in kwargs.items() if k in cls.field_names()})  # type: ignore
        instance.version = payload.get("version", 0)
        return instance

    @classmethod
    def loads(cls, raw: str | Dict[str, Any]) -> "Component":
        """
        Deserialize JSON string or dict into a concrete component instance.
        """
        if isinstance(raw, str):
            payload = json.loads(raw)
        else:
            payload = raw

        component_type = payload.get("component_type")
        if not component_type:
            raise ComponentError("Missing 'component_type' in payload")

        target_cls = _ComponentRegistry.resolve(component_type)
        return target_cls.from_dict(payload)

    # --------------------------------------------------------------------- #
    # Reflection helpers
    # --------------------------------------------------------------------- #

    @classmethod
    def field_names(cls) -> set[str]:
        """Return dataclass field names for the component."""
        return {f.name for f in fields(cls)}  # type: ignore[misc]

    # --------------------------------------------------------------------- #
    # Persistence helpers
    # --------------------------------------------------------------------- #

    def save(
        self,
        *,
        table_name: Optional[str] = None,
        aws_region: Optional[str] = None,
        dynamodb_resource=None,
    ) -> None:
        """
        Persist component to DynamoDB.

        Parameters
        ----------
        table_name:
            Target DynamoDB table name.  If ``None``, will look for
            ``LEDGERQUEST_DYNAMO_TABLE`` env var or fallback to
            ``LedgerQuestComponents``.
        aws_region:
            AWS region to use when initialising the ``boto3`` resource.
            Defaults to ``AWS_REGION`` env var or ``us-east-1``.
        dynamodb_resource:
            Injected :class:`boto3.resources.factory.dynamodb.ServiceResource`.
            Useful for unit testing / mocking.
        """
        if not self._dirty:
            logger.debug("Component %s not dirty – skipping save", self.component_id)
            return

        self.validate()

        try:
            # boto3 import is optional to keep local development dependency-free
            if dynamodb_resource is None:
                import boto3  # type: ignore

                dynamodb_resource = boto3.resource(
                    "dynamodb",
                    region_name=aws_region
                    or os.getenv("AWS_REGION")
                    or os.getenv("AWS_DEFAULT_REGION")
                    or "us-east-1",
                )

            table_name = table_name or os.getenv(
                "LEDGERQUEST_DYNAMO_TABLE", "LedgerQuestComponents"
            )
            table = dynamodb_resource.Table(table_name)

            logger.debug(
                "Persisting component %s to DynamoDB table %s (version=%d)",
                self.component_id,
                table_name,
                self.version,
            )

            # Conditional put for optimistic locking.
            condition_expr = (
                "attribute_not_exists(component_id) OR version = :expectedVersion"
            )

            table.put_item(
                Item=self.to_dynamo_item(),
                ConditionExpression=condition_expr,
                ExpressionAttributeValues={
                    ":expectedVersion": self.version - 1,
                },
            )
            self.reset_dirty()

        except Exception as exc:
            logger.exception("Failed to persist component: %s", exc)
            raise ComponentPersistenceError(str(exc)) from exc

    # --------------------------------------------------------------------- #
    # Representation helpers
    # --------------------------------------------------------------------- #

    def __hash__(self) -> int:
        # Hash by unique, immutable identifier
        return hash(self.component_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Component):
            return NotImplemented
        return self.component_id == other.component_id

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<{self.__class__.__name__} id={self.component_id} "
            f"entity={self.entity_id} version={self.version}>"
        )
```
