```python
"""
LedgerQuest Engine – State Management Sub-Package
=================================================

This module contains the canonical implementation of state persistence for
LedgerQuest Engine.  State in LedgerQuest is:

    • Multi-tenant aware                  (tenant_id)
    • Optimistically concurrent           (version)
    • Persisted in a serverless backend   (DynamoDB, S3, etc.)
    • Serializable to JSON               (for transport & snapshots)

The public surface is intentionally small:

    ┌───────────────────────────────────────────────────────────────┐
    │ GameState            – Data-class representing a game state  │
    │ StateRepository       – Abstract repository interface        │
    │ DynamoDBRepository    – Production impl. (uses boto3)        │
    │ InMemoryRepository    – Testing / local fallback             │
    │ StateTransaction      – Context-manager with OCC semantics   │
    │ get_default_repository() – Factory using env. configuration  │
    └───────────────────────────────────────────────────────────────┘

Example
-------

>>> from ledgerquest.engine.state import StateTransaction
>>> with StateTransaction(game_id="g-123", tenant_id="acme") as state:
...     state.data["score"] += 250
...     # state is automatically persisted on __exit__

Notes
-----
• DynamoDB exceptions are wrapped in StatePersistenceError to avoid leaking
  provider-specific details to calling code.
• The implementation purposefully avoids any game-specific logic; GameState is
  a generic envelope that engine subsystems (physics, AI, etc.) may enrich via
  their own Component serialisation.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

# --------------------------------------------------------------------------- #
# Optional AWS imports – LedgerQuest runs in pure-python mode during local dev
# --------------------------------------------------------------------------- #
try:
    import boto3
    from botocore.exceptions import ClientError
except ModuleNotFoundError:  # pragma: no cover – AWS deps absent locally
    boto3 = None
    ClientError = Exception  # type: ignore

__all__ = [
    "GameState",
    "StateRepository",
    "DynamoDBRepository",
    "InMemoryRepository",
    "StateTransaction",
    "StateError",
    "StateConcurrencyError",
    "StatePersistenceError",
    "get_default_repository",
]

_LOG = logging.getLogger("ledgerquest.engine.state")
_LOG.setLevel(logging.INFO)


# =========================================================================== #
# Exceptions
# =========================================================================== #
class StateError(RuntimeError):
    """Base class for all state-related exceptions."""


class StateConcurrencyError(StateError):
    """Raised when optimistic-locking detects a stale version."""


class StatePersistenceError(StateError):
    """Raised when we fail to read or write to the persistence backend."""


# =========================================================================== #
# GameState dataclass
# =========================================================================== #
@dataclass
class GameState:
    """
    A serialisable envelope for all game state.

    Attributes
    ----------
    game_id:     Unique identifier for the game / match / session.
    tenant_id:   SaaS tenant owner; guarantees isolation.
    data:        Arbitrary JSON-serialisable dict with engine data.
    version:     Monotonically increasing integer for OCC.
    updated_at:  UTC timestamp of last modification.
    """

    game_id: str
    tenant_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    version: int = 0
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # -------------------------- Serialisation helpers ---------------------- #
    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict suitable for storage."""
        return {
            "game_id": self.game_id,
            "tenant_id": self.tenant_id,
            "version": self.version,
            "updated_at": self.updated_at.isoformat(),
            # Store game payload as a *string* to guarantee DynamoDB sizing
            "payload": json.dumps(self.data, separators=(",", ":")),
        }

    @classmethod
    def from_dict(cls, item: Dict[str, Any]) -> "GameState":
        """Reconstitute a GameState from storage representation."""
        try:
            payload = json.loads(item.get("payload") or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise StatePersistenceError("Corrupted state payload") from exc

        return cls(
            game_id=item["game_id"],
            tenant_id=item["tenant_id"],
            version=int(item.get("version", 0)),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            data=payload,
        )

    # ----------------------------- Convenience ----------------------------- #
    def bump_version(self) -> None:
        """Increment version & timestamp locally."""
        self.version += 1
        self.updated_at = datetime.now(timezone.utc)


# =========================================================================== #
# Repository Protocol
# =========================================================================== #
class StateRepository(Protocol):
    """Pluggable persistence backend."""

    def load(self, *, tenant_id: str, game_id: str) -> GameState: ...

    def save(
        self,
        state: GameState,
        *,
        expected_version: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GameState: ...


# =========================================================================== #
# DynamoDB implementation
# =========================================================================== #
class DynamoDBRepository:
    """
    Production repository storing game state in a single DynamoDB table.

    Schema
    ------
    PK  : tenant_id
    SK  : game_id
    Additional fields: version (N), updated_at (S), payload (S)
    """

    _DEFAULT_TABLE_ENV = "LEDGERQUEST_STATE_TABLE"

    def __init__(
        self,
        table_name: Optional[str] = None,
        dynamodb_resource=None,
    ) -> None:
        if boto3 is None:
            raise RuntimeError(
                "boto3 is not available; cannot use DynamoDBRepository."
            )
        self.table_name: str = table_name or os.getenv(
            self._DEFAULT_TABLE_ENV, "ledgerquest_game_state"
        )
        self.dynamodb = dynamodb_resource or boto3.resource("dynamodb")
        self._table = self.dynamodb.Table(self.table_name)
        _LOG.debug("DynamoDBRepository initialised [table=%s]", self.table_name)

    # --------------------------------------------------------------------- #
    # StateRepository interface
    # --------------------------------------------------------------------- #
    def load(self, *, tenant_id: str, game_id: str) -> GameState:
        try:
            response = self._table.get_item(
                Key={"tenant_id": tenant_id, "game_id": game_id},
                ConsistentRead=True,
            )
        except ClientError as exc:
            _LOG.exception("Failed to load state from DynamoDB: %s", exc)
            raise StatePersistenceError("DynamoDB read error") from exc

        item = response.get("Item")
        if not item:
            _LOG.info(
                "No state found – returning new GameState [tenant=%s, game=%s]",
                tenant_id,
                game_id,
            )
            return GameState(game_id=game_id, tenant_id=tenant_id)

        return GameState.from_dict(item)

    def save(
        self,
        state: GameState,
        *,
        expected_version: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GameState:
        """Persist state ensuring optimistic concurrency if expected_version."""
        state.bump_version()  # locally increment

        item = state.to_dict()
        item["pk"] = item["tenant_id"]  # optional GSIs / append for ops

        condition = None
        expression_values = None
        expression_names = None

        if expected_version is not None:
            # Only update if version matches expected_version
            condition = "version = :v"
            expression_values = {":v": expected_version}
            expression_names = None

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=condition,
                ExpressionAttributeValues=expression_values,
                ExpressionAttributeNames=expression_names,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                _LOG.warning(
                    "Version mismatch during save [tenant=%s, game=%s]",
                    state.tenant_id,
                    state.game_id,
                )
                raise StateConcurrencyError(
                    f"Stale state detected for {state.tenant_id}/{state.game_id}"
                ) from exc
            _LOG.exception("Failed to save state to DynamoDB: %s", exc)
            raise StatePersistenceError("DynamoDB write error") from exc

        if metadata:
            _LOG.debug("State saved with metadata: %s", metadata)

        return state


# =========================================================================== #
# In-memory implementation (for local tests / dry-runs)
# =========================================================================== #
class InMemoryRepository:
    """Thread-safe in-memory repository useful for unit tests."""

    _STORE: Dict[str, GameState] = {}
    _LOCK = threading.Lock()

    # StateRepository API
    # ------------------- #
    def load(self, *, tenant_id: str, game_id: str) -> GameState:
        key = self._key(tenant_id, game_id)
        with self._LOCK:
            # return a *copy* to protect against mutation outside txn
            state = self._STORE.get(key)
            if state:
                return GameState(
                    game_id=state.game_id,
                    tenant_id=state.tenant_id,
                    data=dict(state.data),
                    version=state.version,
                    updated_at=state.updated_at,
                )
            return GameState(game_id=game_id, tenant_id=tenant_id)

    def save(
        self,
        state: GameState,
        *,
        expected_version: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GameState:
        key = self._key(state.tenant_id, state.game_id)
        with self._LOCK:
            current = self._STORE.get(key)
            if expected_version is not None and current:
                if current.version != expected_version:
                    raise StateConcurrencyError(
                        f"Stale state detected for {state.tenant_id}/{state.game_id}"
                    )
            state.bump_version()
            self._STORE[key] = GameState(
                game_id=state.game_id,
                tenant_id=state.tenant_id,
                data=dict(state.data),
                version=state.version,
                updated_at=state.updated_at,
            )
        return state

    @staticmethod
    def _key(tenant_id: str, game_id: str) -> str:
        return f"{tenant_id}#{game_id}"


# =========================================================================== #
# Transaction context manager
# =========================================================================== #
class StateTransaction(AbstractContextManager):
    """
    Context manager handling the classic load-modify-save pattern.

    It guarantees:
        • Consistent read before modifications.
        • Optimistic concurrency control on save.
    """

    def __init__(
        self,
        game_id: str,
        tenant_id: str,
        repository: Optional[StateRepository] = None,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.repository = repository or get_default_repository()
        self.game_id = game_id
        self.tenant_id = tenant_id
        self.metadata = metadata or {}
        self._state: Optional[GameState] = None

    # --------------------------------------------------------------------- #
    # Enter / Exit
    # --------------------------------------------------------------------- #
    def __enter__(self) -> GameState:
        _LOG.debug(
            "Entering StateTransaction [tenant=%s, game=%s]",
            self.tenant_id,
            self.game_id,
        )
        self._state = self.repository.load(
            tenant_id=self.tenant_id, game_id=self.game_id
        )
        return self._state

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            _LOG.info(
                "StateTransaction rolled back due to exception: %s", exc_type
            )
            return False  # propagate exception

        assert self._state is not None  # for mypy
        try:
            self.repository.save(
                self._state,
                expected_version=self._state.version,
                metadata=self.metadata,
            )
            _LOG.debug(
                "StateTransaction committed [tenant=%s, game=%s, v=%s]",
                self.tenant_id,
                self.game_id,
                self._state.version,
            )
        except StateConcurrencyError as err:
            _LOG.error("Failed to commit StateTransaction: %s", err)
            raise
        return False  # do not swallow any exception deliberately


# =========================================================================== #
# Repository factory
# =========================================================================== #
_DEFAULT_REPOSITORY: Optional[StateRepository] = None
_REPOSITORY_LOCK = threading.Lock()


def get_default_repository() -> StateRepository:
    """
    Return a lazily-initialised repository.

    Precedence:
        1. If AWS_LAMBDA_FUNCTION_NAME env var is present -> DynamoDBRepository.
        2. Explicit LEDGERQUEST_STATE_BACKEND env overrides:
            • "dynamodb"
            • "memory"
        3. Fallback to InMemoryRepository.
    """
    global _DEFAULT_REPOSITORY

    if _DEFAULT_REPOSITORY is not None:
        return _DEFAULT_REPOSITORY

    with _REPOSITORY_LOCK:
        if _DEFAULT_REPOSITORY is not None:
            return _DEFAULT_REPOSITORY

        backend = os.getenv("LEDGERQUEST_STATE_BACKEND")
        if backend == "memory":
            _DEFAULT_REPOSITORY = InMemoryRepository()
        elif backend == "dynamodb" or (
            backend is None and os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        ):
            # In AWS by default, assume DDB
            _DEFAULT_REPOSITORY = DynamoDBRepository()
        else:
            _DEFAULT_REPOSITORY = InMemoryRepository()

        _LOG.info(
            "Default StateRepository initialised: %s",
            type(_DEFAULT_REPOSITORY).__name__,
        )
        return _DEFAULT_REPOSITORY


# =========================================================================== #
# Step-Functions / Lambda Helpers
# =========================================================================== #
def load_state_from_event(
    event: Dict[str, Any],
    repository: Optional[StateRepository] = None,
) -> GameState:
    """
    Convenience helper for Lambda handlers triggered by EventBridge / StepFn.

    The `event` must carry `tenantId` and `gameId` fields either at the top
    level or nested under `detail`.
    """
    tenant_id = (
        event.get("tenantId")
        or event.get("tenant_id")
        or event.get("detail", {}).get("tenantId")
    )
    game_id = (
        event.get("gameId")
        or event.get("game_id")
        or event.get("detail", {}).get("gameId")
    )

    if not tenant_id or not game_id:
        raise ValueError(
            "Event is missing tenantId and/or gameId fields required to "
            "load game state."
        )

    repo = repository or get_default_repository()
    _LOG.debug("Loading state from event [tenant=%s, game=%s]", tenant_id, game_id)
    return repo.load(tenant_id=tenant_id, game_id=game_id)


# =========================================================================== #
# Minimal Event Recorder (Append-only) – S3
# =========================================================================== #
class EventRecorder:
    """
    Append-only event log for audit / replay.

    An S3 object (one per game_id) is used as immutable log storage.  Each
    `record()` call appends a line of compact JSON to the object.
    """

    _DEFAULT_BUCKET_ENV = "LEDGERQUEST_EVENT_BUCKET"

    def __init__(
        self,
        bucket: Optional[str] = None,
        s3_client=None,
    ) -> None:
        if boto3 is None:
            raise RuntimeError("boto3 is required for S3 EventRecorder.")
        self.bucket = bucket or os.getenv(self._DEFAULT_BUCKET_ENV)
        if not self.bucket:
            raise RuntimeError(
                "EventRecorder bucket not provided and environment variable "
                f"{self._DEFAULT_BUCKET_ENV} absent."
            )
        self.s3 = s3_client or boto3.client("s3")

    def record(
        self,
        *,
        tenant_id: str,
        game_id: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        """Append event JSON line to S3 object."""
        line = json.dumps(
            {
                "id": str(uuid.uuid4()),
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "tenant": tenant_id,
                "game": game_id,
                "payload": payload,
            },
            separators=(",", ":"),
        )
        key = f"{tenant_id}/{game_id}.log"

        # Use multipart upload with append semantics (Get existing, append)
        try:
            previous = ""
            try:
                resp = self.s3.get_object(Bucket=self.bucket, Key=key)
                previous = resp["Body"].read().decode("utf-8")
            except self.s3.exceptions.NoSuchKey:
                pass

            body = f"{previous}{line}\n"
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/x-ndjson",
            )
            _LOG.debug("Event recorded to S3 [%s/%s]", self.bucket, key)
        except ClientError as exc:
            _LOG.exception("Failed to record event: %s", exc)
            raise StatePersistenceError("S3 write error") from exc
```