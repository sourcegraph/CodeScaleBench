```python
"""
ledgerquest.engine.ai.blackboard
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A thread-safe, hierarchical AI “blackboard” implementation inspired by
game-AI behaviour-tree patterns, but extended for LedgerQuest’s
serverless, multi-tenant runtime.

Key features
------------
• Hierarchical paths  –  `enemy/target/pos.x`
• Change listeners    –  Observer pattern hooks (for BT re-evaluation)
• Namespacing         –  Tenant / entity isolation
• Persistence hooks   –  Pluggable async storage adapters (e.g. DynamoDB)
• Versioning & TTL    –  Optimistic-locking + auto-expiry helpers
• Debug snapshotting  –  JSON serialisable state for audit logs

The module is intentionally self-contained so it can run inside Lambda¹
or local unit tests without additional infrastructure.  If boto3 is
installed and the environment variable LEDGERQUEST_BLACKBOARD_TABLE is
set, a DynamoDB adapter is auto-created.

¹ Lambda’s “frozen global” model means process-level variables may
  survive warm invocations; `Blackboard` is therefore thread-safe.

"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError  # pragma: no cover
except ImportError:  # boto3 is optional for local mode / unit tests
    boto3 = None  # type: ignore
    ClientError = Exception  # type: ignore


__all__ = [
    "Blackboard",
    "BlackboardError",
    "ScopedBlackboard",
    "BlackboardStorageAdapter",
    "DynamoDBStorageAdapter",
]


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #
class BlackboardError(RuntimeError):
    """Base class for Blackboard related exceptions."""


# --------------------------------------------------------------------------- #
# Data classes & helpers                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Scope:
    """Uniquely identifies a tenant / entity / session tuple."""
    tenant_id: str
    entity_id: str
    session_id: str | None = None

    def as_key(self) -> str:
        # Compound key for DynamoDB (PK)
        sid = self.session_id or "global"
        return f"{self.tenant_id}#{self.entity_id}#{sid}"


# --------------------------------------------------------------------------- #
# Storage adapters                                                            #
# --------------------------------------------------------------------------- #
class BlackboardStorageAdapter(ABC):
    """
    Strategy interface for persisting a blackboard’s state.

    Implementations must be *thread-safe* because the Blackboard keeps a
    single instance per Lambda execution environment.
    """

    @abstractmethod
    def load(self, scope: Scope) -> Mapping[str, Any]:
        """Retrieve a snapshot from storage.  Must return a *plain* Mapping."""

    @abstractmethod
    def save(
        self, scope: Scope, delta: Mapping[str, Any], ttl_seconds: int | None = None
    ) -> None:
        """
        Persist a *partial* update (delta).  Implementations should use
        compare-and-set semantics if a version field is present.
        """


class DynamoDBStorageAdapter(BlackboardStorageAdapter):
    """
    Concrete adapter that stores blackboard state in a DynamoDB table.

    Table schema
    ------------
    PK              : HASH   (scope.as_key())
    sk              : RANGE  literal '#' (single item model)
    data            : MAP    ≤ 400 KB
    updated_at      : Number (unix epoch)
    ttl             : Number (optional – unix epoch)
    """

    def __init__(
        self,
        table_name: str,
        region_name: Optional[str] = None,
        client_kwargs: Optional[dict] = None,
    ) -> None:
        if boto3 is None:  # pragma: no cover
            raise RuntimeError("boto3 is required for DynamoDBStorageAdapter")
        self._dynamodb = boto3.resource("dynamodb", region_name=region_name, **(client_kwargs or {}))
        self._table = self._dynamodb.Table(table_name)

    def load(self, scope: Scope) -> Mapping[str, Any]:
        try:
            resp = self._table.get_item(Key={"PK": scope.as_key(), "sk": "#"})
            return resp.get("Item", {}).get("data", {})
        except ClientError as exc:  # pragma: no cover
            raise BlackboardError(f"DynamoDB load failed: {exc}")

    def save(self, scope: Scope, delta: Mapping[str, Any], ttl_seconds: int | None = None) -> None:
        update_expr_parts: List[str] = []
        expr_attr_vals: Dict[str, Any] = {":u": int(time.time())}
        expr_attr_names: Dict[str, str] = {}
        for i, (k, v) in enumerate(delta.items(), start=1):
            placeholder = f"#k{i}"
            value_holder = f":v{i}"
            expr_attr_names[placeholder] = k
            expr_attr_vals[value_holder] = v
            update_expr_parts.append(f"data.{placeholder} = {value_holder}")

        update_expr = "SET updated_at = :u"
        if update_expr_parts:
            update_expr += ", " + ", ".join(update_expr_parts)
        if ttl_seconds:
            expr_attr_vals[":ttl"] = int(time.time()) + ttl_seconds
            update_expr += ", ttl = :ttl"

        try:
            self._table.update_item(
                Key={"PK": scope.as_key(), "sk": "#"},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_attr_vals,
                ExpressionAttributeNames=expr_attr_names or None,
            )
        except ClientError as exc:  # pragma: no cover
            raise BlackboardError(f"DynamoDB save failed: {exc}")


# --------------------------------------------------------------------------- #
# Blackboard core                                                             #
# --------------------------------------------------------------------------- #
Listener = Callable[[str, Any, Any], None]  # path, old, new

_SENTINEL = object()  # unique sentinel for “unset”


class Blackboard:
    """
    A hierarchical, observable key/value store.

    Example
    -------
    >>> bb = Blackboard()
    >>> bb.set("enemy.target.pos.x", 10)
    >>> bb.get("enemy.target.pos")   # {'x': 10}
    >>> bb.push("inventory.potions", "health")
    >>> with bb.override("difficulty", "HARD"):
    ...     run_AI()
    """

    # One process-wide storage adapter (Lambdas reuse execution envs)
    _adapter: Optional[BlackboardStorageAdapter] = None
    _adapter_lock = threading.RLock()

    # --------------------------------------------------------------------- #
    def __init__(
        self,
        scope: Scope | None = None,
        *,
        auto_persist: bool = True,
        ttl_seconds: int | None = 60 * 60 * 6,
    ) -> None:
        self._data: Dict[str, Any] = {}
        self._listeners: Dict[str, List[Listener]] = {}
        self._lock = threading.RLock()
        self._scope = scope or Scope("default", "global")
        self._auto_persist = auto_persist
        self._ttl = ttl_seconds

        # Lazy-load persisted state
        adapter = self._get_adapter()
        if self._auto_persist and adapter:
            self._data.update(adapter.load(self._scope))

    # --------------------------------------------------------------------- #
    # Adapter helpers                                                       #
    # --------------------------------------------------------------------- #
    @classmethod
    def _get_adapter(cls) -> Optional[BlackboardStorageAdapter]:
        with cls._adapter_lock:
            if cls._adapter is not None:
                return cls._adapter

            # Auto-configure a Dynamo adapter if env-vars available.
            table_name = os.getenv("LEDGERQUEST_BLACKBOARD_TABLE")
            if boto3 and table_name:
                cls._adapter = DynamoDBStorageAdapter(table_name)
            return cls._adapter

    @classmethod
    def configure_adapter(cls, adapter: BlackboardStorageAdapter) -> None:
        """Manually set a process-level storage adapter (for tests)."""
        with cls._adapter_lock:
            cls._adapter = adapter

    # --------------------------------------------------------------------- #
    # Core accessors                                                        #
    # --------------------------------------------------------------------- #
    def get(self, path: str, default: Any = None) -> Any:
        with self._lock:
            value = self._traverse(path, create=False)
            return value if value is not _SENTINEL else default

    def set(self, path: str, value: Any) -> None:
        old = _SENTINEL
        with self._lock:
            node, key = self._parent_node(path, create=True)
            old = node.get(key, _SENTINEL)
            node[key] = value
            self._notify(path, old, value)

        if self._auto_persist:
            self._persist({path: value})

    def delete(self, path: str) -> None:
        with self._lock:
            node, key = self._parent_node(path, create=False)
            if key not in node:
                return
            old = node.pop(key)
            self._notify(path, old, _SENTINEL)

        if self._auto_persist:
            self._persist({path: None})

    def push(self, path: str, *values: Any, maxlen: int | None = None) -> None:
        with self._lock:
            lst: List[Any] = self.get(path, [])
            if not isinstance(lst, list):
                raise BlackboardError(f"Value at {path!r} is not a list")
            old = list(lst)
            lst.extend(values)
            if maxlen is not None:
                del lst[:-maxlen]
            self.set(path, lst)
            self._notify(path, old, lst)

    # --------------------------------------------------------------------- #
    # Listener API                                                          #
    # --------------------------------------------------------------------- #
    def add_listener(self, path: str, listener: Listener) -> None:
        with self._lock:
            self._listeners.setdefault(path, []).append(listener)

    def remove_listener(self, path: str, listener: Listener) -> None:
        with self._lock:
            listeners = self._listeners.get(path)
            if listeners and listener in listeners:
                listeners.remove(listener)

    def _notify(self, path: str, old: Any, new: Any) -> None:
        # Fire listeners for exact path and wildcard '*'
        listeners = self._listeners.get(path, []) + self._listeners.get("*", [])
        for cb in listeners:
            try:
                cb(path, old if old is not _SENTINEL else None, new if new is not _SENTINEL else None)
            except Exception as exc:  # pragma: no cover
                # Listener failures must not break BB logic
                print(f"[Blackboard] listener {cb} for path {path!r} raised: {exc}")

    # --------------------------------------------------------------------- #
    # Utility / internals                                                   #
    # --------------------------------------------------------------------- #
    def _persist(self, delta: Mapping[str, Any]) -> None:
        adapter = self._get_adapter()
        if not adapter:
            return
        try:
            adapter.save(self._scope, delta, self._ttl)
        except BlackboardError:
            raise
        except Exception as exc:  # pragma: no cover
            raise BlackboardError(f"Persist failed: {exc}") from exc

    # Traversal helpers
    def _parent_node(self, path: str, *, create: bool) -> Tuple[MutableMapping[str, Any], str]:
        parts = path.split(".")
        node = self._data
        for part in parts[:-1]:
            next_node = node.get(part, _SENTINEL)
            if next_node is _SENTINEL:
                if not create:
                    raise BlackboardError(f"Path {path!r} does not exist")
                next_node = {}
                node[part] = next_node
            if not isinstance(next_node, dict):
                raise BlackboardError(f"Path {'/'.join(parts[:-1])!r} is not a namespace")
            node = next_node
        return node, parts[-1]

    def _traverse(self, path: str, *, create: bool) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict):
                return _SENTINEL
            if part not in node:
                if create:
                    node[part] = {}
                else:
                    return _SENTINEL
            node = node[part]
        return node

    # --------------------------------------------------------------------- #
    # Context manager                                                       #
    # --------------------------------------------------------------------- #
    @contextlib.contextmanager
    def override(self, path: str, value: Any):
        """Temporarily override a value inside a `with` block."""
        old = self.get(path, _SENTINEL)
        self.set(path, value)
        try:
            yield
        finally:
            if old is _SENTINEL:
                self.delete(path)
            else:
                self.set(path, old)

    # --------------------------------------------------------------------- #
    # Debugging / inspection                                                #
    # --------------------------------------------------------------------- #
    def snapshot(self) -> Dict[str, Any]:
        """Return a deep copy suitable for JSON serialisation."""
        with self._lock:
            return json.loads(json.dumps(self._data, default=str))

    # --------------------------------------------------------------------- #
    # Dunder methods for niceness                                           #
    # --------------------------------------------------------------------- #
    def __getitem__(self, path: str) -> Any:
        val = self.get(path, _SENTINEL)
        if val is _SENTINEL:
            raise KeyError(path)
        return val

    def __setitem__(self, path: str, value: Any) -> None:
        self.set(path, value)

    def __delitem__(self, path: str) -> None:
        self.delete(path)

    def __contains__(self, path: str) -> bool:
        return self.get(path, _SENTINEL) is not _SENTINEL

    # --------------------------------------------------------------------- #
    # Convenience factory                                                   #
    # --------------------------------------------------------------------- #
    @classmethod
    def for_entity(
        cls,
        tenant_id: str,
        entity_id: str,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> "Blackboard":
        return cls(scope=Scope(tenant_id, entity_id, session_id), **kwargs)


# --------------------------------------------------------------------------- #
# Scoped (read-only) facade                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ScopedBlackboard:
    """
    Lightweight, *read-only* projection that wraps a Blackboard and
    exposes a subtree, preventing accidental writes to other branches.

    Example
    -------
    npc_bb = ScopedBlackboard(root_bb, "npc_42")
    mood = npc_bb.get("state.mood")
    """

    _origin: Blackboard
    _prefix: str

    # ------------------------------------------------------------------ #
    def get(self, path: str = "", default: Any = None) -> Any:
        sanitized = self._join(path)
        return self._origin.get(sanitized, default)

    def __contains__(self, path: str) -> bool:
        return self._origin.__contains__(self._join(path))

    # Internal helpers
    def _join(self, path: str) -> str:
        return f"{self._prefix}.{path}" if path else self._prefix

    # Block mutation attempts
    def __setattr__(self, *_) -> None:  # pragma: no cover
        if _.0 in {"_origin", "_prefix"}:
            object.__setattr__(self, *_)
        else:
            raise AttributeError("ScopedBlackboard is read-only")

    __setitem__ = __delitem__ = set = delete = push = __setattr__  # type: ignore
```