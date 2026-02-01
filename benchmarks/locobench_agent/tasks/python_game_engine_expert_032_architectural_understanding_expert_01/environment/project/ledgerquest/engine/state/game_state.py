```python
"""
ledgerquest.engine.state.game_state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

High-level state-persistence façade used by the LedgerQuest Engine runtime
and authoring tools.  The module provides an opinionated wrapper around
DynamoDB for low-latency, per-tick mutations (optimistic-locking included)
plus a snapshotter that durably archives every committed revision to S3.

Both services are discovered via environment variables so that the same code
runs unmodified in local development (e.g. with `localstack`) and AWS Lambda.

Environment variables
---------------------
LEDGERQUEST_GAMESTATE_DDB_TABLE   DynamoDB table storing the latest document
LEDGERQUEST_GAMESTATE_S3_BUCKET   S3 bucket used for *immutable* snapshots
LEDGERQUEST_AWS_REGION            If absent, falls back to AWS_DEFAULT_REGION

The document schema stored in DynamoDB looks like this:

    PK              :  <TENANT>#<GAME_ID>
    SK              :  "STATE"
    version         :  int  (monotonically increasing, starts at 1)
    updated_at      :  int  (unix epoch millis)
    payload         :  map (arbitrary JSON–serialisable object)

The table should have `PK` as the partition key and `SK` as the sort key.
`version` is used for conditional writes to implement optimistic locking.

Snapshot objects in S3 are written to:

    s3://{bucket}/{tenant_id}/{game_id}/{version}.json

…where the file contents are the exact `payload` document plus a small
metadata header (see :pyfunc:`_build_snapshot_blob`).

Note
----
This module intentionally avoids any notion of “transient / in-memory”
game-loop data.  The engine’s deterministic simulation pipeline is executed
inside Step Functions and Lambda layers; every function receives the latest
authoritative state at invocation time, mutates it, and calls
:pyfunc:`GameState.save` when finished.

Author
------
LedgerQuest Engine Team <engineering@ledgerquest.io>
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

__all__ = [
    "GameState",
    "GameStateError",
    "ConcurrentModificationError",
    "GameStateNotFound",
]

_LOG = logging.getLogger(__name__)
_LOG.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
#  Exceptions                                                                 #
# --------------------------------------------------------------------------- #


class GameStateError(RuntimeError):
    """Base-class for *all* GameState-related errors."""


class ConcurrentModificationError(GameStateError):
    """
    Raised by :pyfunc:`GameState.save` if the underlying DynamoDB record has
    been updated between `load()` and `save()`.
    """


class GameStateNotFound(GameStateError):
    """
    Thrown by :pyfunc:`GameState.load` when the requested record does not
    exist in DynamoDB *and* `create_if_absent` was *False*.
    """


# --------------------------------------------------------------------------- #
#  Helpers                                                                    #
# --------------------------------------------------------------------------- #


def _env(var: str, *, default: Optional[str] = None) -> str:
    """Fetch required environment variables and raise loudly if missing."""
    try:
        return os.environ[var]
    except KeyError as exc:
        if default is not None:
            return default
        raise RuntimeError(
            f"Environment variable '{var}' not set ‑- required by GameState"
        ) from exc


def _now_millis() -> int:
    return int(time.time() * 1000)


class _DecimalEncoder(json.JSONEncoder):
    """
    JSON encoder that converts `Decimal` into float, needed because
    `boto3` automatically unmarshals Dynamo `N` attributes into `Decimal`s.
    """

    def default(self, o):  # noqa: D401  # pylint: disable=method-hidden
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _build_snapshot_blob(state: "GameState") -> bytes:
    """
    Marshals the GameState payload into a pretty-printed JSON file that
    contains some header metadata for auditing purposes.
    """
    blob = {
        "__ledgerquest_metadata__": {
            "tenant_id": state.tenant_id,
            "game_id": state.game_id,
            "version": state.version,
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds")
            + "Z",
        },
        "payload": state.payload,
    }
    return json.dumps(blob, indent=2, cls=_DecimalEncoder).encode("utf-8")


# --------------------------------------------------------------------------- #
#  GameState                                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class GameState:
    """
    Immutable data-class representing *one* document from the GameState
    table.  Mutation helpers (`patch`, `set`) return **new** instances.
    Persist changes via :pyfunc:`save` which also snapshots to S3.
    """

    tenant_id: str
    game_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    version: int = 0  # version == 0 means “not yet persisted”
    updated_at: int = field(default_factory=_now_millis)

    # BOTO3 clients are expensive to create, keep them at module level.
    _ddb = boto3.resource(
        "dynamodb",
        region_name=_env("LEDGERQUEST_AWS_REGION", default=os.getenv("AWS_DEFAULT_REGION")),
    )
    _s3 = boto3.client(
        "s3",
        region_name=_env("LEDGERQUEST_AWS_REGION", default=os.getenv("AWS_DEFAULT_REGION")),
    )
    _table_name = _env("LEDGERQUEST_GAMESTATE_DDB_TABLE")
    _s3_bucket = _env("LEDGERQUEST_GAMESTATE_S3_BUCKET")

    # DynamoDB table handle (lazy property so that moto/localstack patches work)
    @property
    def _table(self):
        return self.__class__._ddb.Table(self.__class__._table_name)

    # --------------------------------------------------------------------- #
    #  Factory / IO                                                         #
    # --------------------------------------------------------------------- #

    @classmethod
    def load(
        cls,
        tenant_id: str,
        game_id: str,
        *,
        create_if_absent: bool = False,
        default_payload: Optional[Dict[str, Any]] = None,
    ) -> "GameState":
        """
        Retrieve the latest state from DynamoDB.

        Parameters
        ----------
        tenant_id
            Multi-tenant isolation identifier
        game_id
            Primary key of the game session
        create_if_absent
            When *True*, missing records will be created on-the-fly.
        default_payload
            Initial payload when `create_if_absent` kicks in.

        Returns
        -------
        GameState

        Raises
        ------
        GameStateNotFound
            When the record is missing and `create_if_absent` is *False*.
        """
        pk = f"{tenant_id}#{game_id}"
        try:
            resp = cls._ddb.Table(cls._table_name).get_item(
                Key={"PK": pk, "SK": "STATE"}, ConsistentRead=True
            )
            item = resp.get("Item")
            if item is None:
                if not create_if_absent:
                    raise GameStateNotFound(f"Game state for {pk} not found")
                # create a brand new record
                state = cls(
                    tenant_id=tenant_id,
                    game_id=game_id,
                    payload=default_payload or {},
                    version=0,
                )
                state.save()  # will write as version 1
                _LOG.info("Created new GameState record PK=%s", pk)
                return state

            _LOG.debug("Loaded GameState from DDB: %s", item)
            return cls(
                tenant_id=tenant_id,
                game_id=game_id,
                payload=item["payload"],
                version=int(item["version"]),
                updated_at=int(item["updated_at"]),
            )
        except ClientError as err:  # pragma: no cover
            _LOG.exception("DynamoDB get_item failed: %s", err.response["Error"])
            raise GameStateError("Unable to load GameState") from err

    # --------------------------------------------------------------------- #
    #  Mutations                                                            #
    # --------------------------------------------------------------------- #

    def patch(self, changes: Dict[str, Any]) -> "GameState":
        """
        Return a *new* GameState with `changes` shallow-merged into the
        existing payload.

        Nested keys are NOT deep-merged — caller must read/modify/write
        sub-structures by itself if deep behaviour is desired.
        """
        new_payload = {**self.payload, **changes}
        return self._clone(payload=new_payload)

    def set(self, key: str, value: Any) -> "GameState":
        """Shortcut for `patch({key: value})`."""
        return self.patch({key: value})

    # --------------------------------------------------------------------- #
    #  Persistence                                                          #
    # --------------------------------------------------------------------- #

    def save(self, *, snapshot: bool = True) -> "GameState":
        """
        Persist the GameState atomically.

        The method employs DynamoDB’s `ConditionExpression` to guard against
        concurrent writes — if another runtime saved a newer version in the
        meantime, :class:`ConcurrentModificationError` is raised.

        On successful commit the object’s `version` is incremented and (by
        default) an immutable snapshot is copied to S3.

        Returns a **new** GameState instance representing the committed row
        so that callers can safely discard their previous (dirty) object.
        """
        pk = f"{self.tenant_id}#{self.game_id}"
        new_version = self.version + 1
        now = _now_millis()

        item = {
            "PK": pk,
            "SK": "STATE",
            "version": new_version,
            "updated_at": now,
            "payload": self.payload,
        }

        condition = (
            "attribute_not_exists(version)" if self.version == 0 else "#v = :v"
        )  # first write vs update

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=condition,
                ExpressionAttributeNames={"#v": "version"} if self.version else None,
                ExpressionAttributeValues={":v": self.version} if self.version else None,
            )
            _LOG.info(
                "Saved GameState PK=%s version=%d (prev=%d)", pk, new_version, self.version
            )
        except ClientError as err:  # pragma: no cover
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConcurrentModificationError(
                    f"GameState {pk} modified concurrently (expected version "
                    f"{self.version})"
                ) from err
            _LOG.exception("DynamoDB put_item failed: %s", err.response["Error"])
            raise GameStateError("Unable to save GameState") from err

        # Snapshot *after* successful commit; any failure here should not
        # rollback the DDB write, we only log the error.
        if snapshot:
            try:
                self._snapshot_to_s3(new_version)
            except Exception:  # pragma: no cover
                _LOG.exception("Non-fatal: failed to snapshot GameState to S3")

        return self._clone(version=new_version, updated_at=now)

    # --------------------------------------------------------------------- #
    #  Internal helpers                                                     #
    # --------------------------------------------------------------------- #

    def _snapshot_to_s3(self, version: int) -> None:
        key = f"{self.tenant_id}/{self.game_id}/{version}.json"
        blob = _build_snapshot_blob(self)
        self._s3.put_object(
            Bucket=self._s3_bucket,
            Key=key,
            Body=blob,
            ContentType="application/json",
            Metadata={
                "tenant_id": self.tenant_id,
                "game_id": self.game_id,
                "version": str(version),
            },
        )
        _LOG.debug("Snapshot written to s3://%s/%s", self._s3_bucket, key)

    def _clone(self, **overrides) -> "GameState":
        """
        Return a new GameState with the provided attribute overrides.
        Private helper for functional-style mutation.
        """
        data = asdict(self)
        data.update(overrides)
        return GameState(**data)

    # --------------------------------------------------------------------- #
    #  Utility                                                              #
    # --------------------------------------------------------------------- #

    def to_dict(self, *, include_internal: bool = False) -> Dict[str, Any]:
        """
        Convert the GameState into a plain‐old Python dictionary, suitable for
        JSON serialisation or logging.  Internal bookkeeping fields (PK/SK)
        are excluded unless `include_internal` is *True*.
        """
        doc = {
            "tenant_id": self.tenant_id,
            "game_id": self.game_id,
            "version": self.version,
            "updated_at": self.updated_at,
            "payload": self.payload,
        }
        if include_internal:
            doc["pk"] = f"{self.tenant_id}#{self.game_id}"
            doc["sk"] = "STATE"
        return doc

    # --------------------------------------------------------------------- #
    #  Dunder stuff                                                          #
    # --------------------------------------------------------------------- #

    def __repr__(self) -> str:  # pragma: no cover
        # Only show first 120 chars of payload to keep logs readable
        payload_preview = json.dumps(self.payload, cls=_DecimalEncoder)[:120]
        return (
            f"GameState<{self.tenant_id}/{self.game_id} v{self.version} "
            f"updated_at={self.updated_at} payload={payload_preview}...>"
        )
```