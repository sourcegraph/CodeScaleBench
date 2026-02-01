```python
"""
ledgerquest_engine/ecs/dynamodb_repository.py

A production-grade DynamoDB–backed implementation of the Entity–Component–System
persistence layer used by LedgerQuest Engine.

This repository persists entities and their associated components into a
single DynamoDB table using a composite primary key:

    PK  = "ENTITY#{tenant_id}#{entity_id}"
    SK  = "COMPONENT#{component_name}"

The design satisfies the following requirements:

    • Multi-tenant isolation                (tenant_id included in the PK)
    • Strongly-typed component marshaling   (dataclasses + Pydantic models)
    • Auditable change history              (ConditionExpression + EventBridge)
    • Optimistic concurrency control        (entity_version attribute)
    • Incremental component loading         (query on PK, filter on SK)

The module is intentionally self-contained so that it can be imported by both
Lambda functions (per-request ECS mutations) and long-running game-loop
simulations scheduled in Fargate tasks.

Functions are synchronous for readability, but boto3 client calls are executed
using a ThreadPool so the interface remains non-blocking when used from
async/await code.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from functools import partial
from typing import Any, Dict, Iterable, List, Mapping, Optional, Type, TypeVar

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, ValidationError

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

_LOGGER = logging.getLogger("ledgerquest.ecs.dynamodb_repository")
_LOGGER.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ECSRepositoryError(RuntimeError):
    """Base class for repository related failures."""


class EntityNotFound(ECSRepositoryError):
    """Raised when an entity cannot be found in the database."""


class ComponentValidationError(ECSRepositoryError):
    """Raised when a component payload fails validation."""


class OptimisticLockError(ECSRepositoryError):
    """Raised when the entity_version no longer matches."""


# --------------------------------------------------------------------------- #
# Utility / Typing
# --------------------------------------------------------------------------- #

_T = TypeVar("_T", bound="ComponentModel")


class ComponentModel(BaseModel):
    """Base class for any ECS Component stored in DynamoDB."""

    # Every component inherits tenant_id / entity_id so it can be reconstructed
    tenant_id: str
    entity_id: str

    def pk(self) -> str:
        return f"ENTITY#{self.tenant_id}#{self.entity_id}"

    @property
    def sk(self) -> str:
        return f"COMPONENT#{self.__class__.__name__}"

    class Config:
        extra = "forbid"


@dataclass(frozen=True)
class EntityKey:
    tenant_id: str
    entity_id: str

    def pk(self) -> str:
        return f"ENTITY#{self.tenant_id}#{self.entity_id}"


# --------------------------------------------------------------------------- #
# Repository
# --------------------------------------------------------------------------- #


class DynamoDBECSRepository:
    """
    Reads / writes ECS entities into a DynamoDB table.

    A single instance is safe for concurrent use between threads *provided* that
    the AWS SDK client is not mutated at runtime.
    """

    _DEFAULT_CONCURRENCY = int(os.getenv("LEDGERQUEST_ECS_MAX_THREADS", "8"))

    def __init__(
        self,
        table_name: str,
        boto3_resource: Optional[Any] = None,
        eventbridge_bus: Optional[str] = None,
        executor: Optional[ThreadPoolExecutor] = None,
    ) -> None:
        self._dynamodb = boto3_resource or boto3.resource("dynamodb")
        self._table = self._dynamodb.Table(table_name)
        self._bus_name = eventbridge_bus
        self._event_client = boto3.client("events") if eventbridge_bus else None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=self._DEFAULT_CONCURRENCY
        )
        _LOGGER.debug(
            "DynamoDBECSRepository initialised for table=%s, bus=%s",
            table_name,
            eventbridge_bus,
        )

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def create_entity(
        self, key: EntityKey, components: Iterable[ComponentModel]
    ) -> None:
        """
        Insert a new entity; fails if the entity_id already exists for the
        tenant. All components are stored in a single TransactWrite.

        Raises:
            ECSRepositoryError – on any DynamoDB failure
            ComponentValidationError – if component fails validation
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        transact_items: List[Dict[str, Any]] = []

        for component in components:
            component_dict = _serialise_component(component, timestamp)
            transact_items.append(
                {
                    "Put": {
                        "TableName": self._table.name,
                        "Item": component_dict,
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                }
            )

        # entity_version item
        entity_meta = {
            "PK": key.pk(),
            "SK": "META",
            "entity_version": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        transact_items.append(
            {
                "Put": {
                    "TableName": self._table.name,
                    "Item": entity_meta,
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            }
        )

        _LOGGER.debug("Creating entity %s with %d components", key, len(components))
        self._execute_transact_write(transact_items)
        self._publish_event(
            "EntityCreated", {"tenantId": key.tenant_id, "entityId": key.entity_id}
        )

    def get_components(
        self,
        key: EntityKey,
        component_types: Optional[Iterable[Type[_T]]] = None,
    ) -> Dict[str, _T]:
        """
        Load components for an entity. If `component_types` is provided the query
        will filter accordingly (client-side).

        Raises:
            EntityNotFound
        """
        response = self._table.query(KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": key.pk()})
        if not response.get("Items"):
            raise EntityNotFound(f"Entity {key} not found")

        components: Dict[str, _T] = {}
        allowed_names = {c.__name__ for c in component_types} if component_types else None

        for item in response["Items"]:
            if item["SK"] == "META":
                continue  # skip meta row
            comp_name = item["SK"].split("#", 1)[1]
            if allowed_names is None or comp_name in allowed_names:
                comp_cls = _component_registry().get(comp_name)
                if not comp_cls:
                    _LOGGER.warning("Component class %s not registered", comp_name)
                    continue
                components[comp_name] = comp_cls.parse_obj(item["data"])  # type: ignore

        return components

    def put_component(
        self,
        component: ComponentModel,
        expected_entity_version: Optional[int] = None,
    ) -> None:
        """
        Inserts or replaces a single component.

        Args:
            component: ComponentModel – the component data.
            expected_entity_version: int | None – optional optimistic lock.

        Raises:
            OptimisticLockError – entity version mismatch.
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        transact_items: List[Dict[str, Any]] = []

        # Upsert component
        component_dict = _serialise_component(component, timestamp)
        transact_items.append(
            {
                "Put": {
                    "TableName": self._table.name,
                    "Item": component_dict,
                }
            }
        )

        # Bump entity version
        update_expression = "SET entity_version = entity_version + :inc, updated_at = :ts"
        expression_values = {":inc": 1, ":ts": timestamp}
        condition_expression = None
        if expected_entity_version is not None:
            condition_expression = "entity_version = :expected"
            expression_values[":expected"] = expected_entity_version

        transact_items.append(
            {
                "Update": {
                    "TableName": self._table.name,
                    "Key": {"PK": component.pk(), "SK": "META"},
                    "UpdateExpression": update_expression,
                    "ExpressionAttributeValues": expression_values,
                    **(
                        {"ConditionExpression": condition_expression}
                        if condition_expression
                        else {}
                    ),
                }
            }
        )

        try:
            self._execute_transact_write(transact_items)
        except ClientError as exc:
            if _is_conditional_failed(exc):
                raise OptimisticLockError(
                    f"Entity version mismatch for {component.entity_id}"
                ) from exc
            raise

        self._publish_event(
            "ComponentUpserted",
            {
                "tenantId": component.tenant_id,
                "entityId": component.entity_id,
                "component": component.__class__.__name__,
            },
        )

    def delete_entity(self, key: EntityKey) -> None:
        """
        Delete an entity and all its components using a PartiQL statement.

        Raises:
            EntityNotFound – if the entity does not exist.
        """
        # Verify entity exists
        try:
            self._table.get_item(Key={"PK": key.pk(), "SK": "META"})["Item"]
        except KeyError:
            raise EntityNotFound(f"Entity {key} not found")

        _LOGGER.debug("Deleting entity %s", key)
        statement = f"DELETE FROM \"{self._table.name}\" WHERE PK=?"
        self._table.meta.client.execute_statement(Statement=statement, Parameters=[{"S": key.pk()}])
        self._publish_event(
            "EntityDeleted", {"tenantId": key.tenant_id, "entityId": key.entity_id}
        )

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _execute_transact_write(self, items: List[Dict[str, Any]]) -> None:
        try:
            future = self._executor.submit(
                self._table.meta.client.transact_write_items, TransactItems=items
            )
            future.result()
        except ClientError as exc:
            _LOGGER.exception("DynamoDB TransactWrite failed: %s", exc)
            raise ECSRepositoryError("DynamoDB transact write failed") from exc

    def _publish_event(self, event_type: str, detail: Mapping[str, Any]) -> None:
        if not self._event_client:
            return  # EventBridge not configured
        try:
            self._event_client.put_events(
                Entries=[
                    {
                        "Source": "ledgerquest.ecs",
                        "DetailType": event_type,
                        "Detail": json.dumps(detail),
                        "EventBusName": self._bus_name,
                        "Time": datetime.now(tz=timezone.utc),
                    }
                ]
            )
        except ClientError as exc:
            # Fail silently – publishing is best-effort
            _LOGGER.warning("EventBridge publish failed: %s", exc)


# --------------------------------------------------------------------------- #
# Component (De)Serialisation
# --------------------------------------------------------------------------- #


def _serialise_component(component: ComponentModel, timestamp: str) -> Dict[str, Any]:
    if not isinstance(component, ComponentModel):
        raise TypeError("component must inherit from ComponentModel")
    try:
        payload = component.dict(by_alias=True)
    except ValidationError as exc:
        raise ComponentValidationError(str(exc)) from exc
    return {
        "PK": component.pk(),
        "SK": component.sk,
        "data": payload,
        "updated_at": timestamp,
    }


# --------------------------------------------------------------------------- #
# Component Registry
# --------------------------------------------------------------------------- #

_registry: Dict[str, Type[ComponentModel]] = {}


def register_component(cls: Type[_T]) -> Type[_T]:
    """
    Class decorator registering a ComponentModel subclass for automatic
    deserialisation. The decorated class *must* inherit from ComponentModel.
    """
    if not issubclass(cls, ComponentModel):
        raise TypeError("Only ComponentModel subclasses can be registered")
    _registry[cls.__name__] = cls
    return cls


def _component_registry() -> Mapping[str, Type[ComponentModel]]:
    return _registry


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _is_conditional_failed(exc: ClientError) -> bool:
    return (
        exc.response.get("Error", {}).get("Code") == "TransactionCanceledException"
        and any(
            reason.get("Code") == "ConditionalCheckFailed"
            for reason in exc.response.get("CancellationReasons", [])
        )
    )


# --------------------------------------------------------------------------- #
# Example Component Definitions
# --------------------------------------------------------------------------- #

# The following component classes *serve as usage examples* and *may* be moved
# into their own modules by consumers of this repository.


@register_component
class Position(ComponentModel):
    x: float
    y: float
    z: float = 0.0


@register_component
class Health(ComponentModel):
    max_hp: int = 100
    current_hp: int = 100
    last_damage_source: Optional[str] = None


# --------------------------------------------------------------------------- #
# Convenience – quick smoke test
# --------------------------------------------------------------------------- #

if __name__ == "__main__" and os.getenv("LEDGERQUEST_ECS_SMOKE_TEST"):
    import uuid
    from pprint import pprint

    logging.basicConfig(level=logging.DEBUG)

    repo = DynamoDBECSRepository(
        table_name=os.getenv("LEDGERQUEST_ECS_TABLE", "LedgerQuestECS"),
        eventbridge_bus=os.getenv("LEDGERQUEST_ECS_BUS", None),
    )

    tenant = "demo"
    eid = str(uuid.uuid4())[:8]
    key = EntityKey(tenant_id=tenant, entity_id=eid)

    _LOGGER.info("Creating entity %s", key)
    repo.create_entity(
        key,
        components=[
            Position(tenant_id=tenant, entity_id=eid, x=1.0, y=1.0),
            Health(tenant_id=tenant, entity_id=eid),
        ],
    )

    _LOGGER.info("Fetching components")
    comps = repo.get_components(key)
    pprint(comps)

    _LOGGER.info("Updating position")
    repo.put_component(
        Position(tenant_id=tenant, entity_id=eid, x=5.0, y=7.5, z=1.2),
        expected_entity_version=1,
    )

    _LOGGER.info("Deleting entity")
    repo.delete_entity(key)
```