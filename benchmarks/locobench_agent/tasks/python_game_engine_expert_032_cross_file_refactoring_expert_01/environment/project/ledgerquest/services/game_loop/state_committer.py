```python
"""
ledgerquest.services.game_loop.state_committer
---------------------------------------------

The *state_committer* is the final step in a single game-loop iteration
orchestrated by AWS Step Functions.  It receives a collection of entity /
component deltas that were produced by the simulation worker and attempts to
commit them to the authoritative data-store while enforcing:

* Multi-tenant isolation (tenant_id partition key)
* Optimistic concurrency (per-session frame counters)
* Size limits of DynamoDB items (≈ 400 KB)
* Audit, metering, and diagnostic logging

If the payload is too large for DynamoDB, it is transparently off-loaded to
Amazon S3 and only a pointer is stored in the main table.

Because every Lambda invocation must be stateless, **StateCommitter** receives
its dependencies (boto3 clients, loggers, …) via *constructor injection* to make
the code testable and to enable local / on-prem adapters.

Typical usage
~~~~~~~~~~~~~

    committer = StateCommitter(
        ddb_table_name=os.environ["GAME_STATE_TABLE"],
        s3_bucket_name=os.environ["GAME_STATE_BUCKET"],
        s3_prefix="session-frames/",
    )

    result = committer.commit_state(
        tenant_id=event["tenant_id"],
        session_id=event["session_id"],
        frame_id=event["frame_id"],
        expected_previous_frame_id=event["expected_previous_frame_id"],
        entity_changes=event["changes"],
    )

"""
from __future__ import annotations

import gzip
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

__all__ = [
    "StateCommitter",
    "EntityChange",
    "StateCommitError",
    "ConcurrencyConflictError",
    "StorageError",
]

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

MAX_DDB_ITEM_SIZE = 400 * 1024  # Hard DynamoDB limit (400 KB)
GZIP_COMPRESSION_LEVEL = 6       # Reasonable trade-off speed vs. ratio
DEFAULT_S3_STORAGE_CLASS = "STANDARD_IA"  # Cheaper but still fast access


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class StateCommitError(RuntimeError):
    """Base-class for commit failures."""


class ConcurrencyConflictError(StateCommitError):
    """Raised when optimistic concurrency protection fails."""


class StorageError(StateCommitError):
    """Raised when S3 or DynamoDB operations fail for non-concurrency reasons."""


# --------------------------------------------------------------------------- #
# Data Model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EntityChange:  # noqa: D401
    """Represents a single entity/component mutation.

    Attributes
    ----------
    entity_id
        The canonical UUID of the entity.
    component
        The component name (e.g., 'Transform', 'Health', 'AccountBalance').
    operation
        'PUT', 'DELETE', or 'UPDATE'.
    payload
        Arbitrary JSON-serialisable structure containing the component data.
    version
        Client-supplied optimistic version of the component (optional).
    """

    entity_id: str
    component: str
    operation: str
    payload: Mapping[str, Any]
    version: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _utc_now_rfc3339() -> str:
    """Return the current UTC timestamp in RFC 3339 format."""
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _estimate_item_size(item: Mapping[str, Any]) -> int:
    """Approximate size of a DynamoDB item after JSON serialisation."""
    # NOTE: DynamoDB binary encoding is different, but JSON is a good proxy.
    return len(json.dumps(item, separators=(",", ":")).encode("utf-8"))


def _gzip_compress(data: bytes, level: int = GZIP_COMPRESSION_LEVEL) -> bytes:
    """Compress *data* using GZIP."""
    buffer = BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=level) as gz:
        gz.write(data)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Core Service
# --------------------------------------------------------------------------- #


class StateCommitter:  # noqa: D401
    """Persist simulation results whilst enforcing concurrency & compliance."""

    def __init__(
        self,
        *,
        ddb_table_name: str,
        s3_bucket_name: str,
        s3_prefix: str = "",
        dynamodb_client: Optional[BaseClient] = None,
        s3_client: Optional[BaseClient] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._table = ddb_table_name
        self._bucket = s3_bucket_name
        self._prefix = s3_prefix.lstrip("/")
        self._ddb = dynamodb_client or boto3.client("dynamodb")
        self._s3 = s3_client or boto3.client("s3")
        self._log = logger or LOGGER

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def commit_state(
        self,
        *,
        tenant_id: str,
        session_id: str,
        frame_id: int,
        expected_previous_frame_id: int,
        entity_changes: Sequence[EntityChange] | Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Commit simulation deltas to DynamoDB (+ S3 for over-flow payloads).

        Parameters
        ----------
        tenant_id
            Multi-tenant partition key.
        session_id
            Current game session identifier.
        frame_id
            Monotonically incremental frame counter generated by the orchestrator.
        expected_previous_frame_id
            Optimistic concurrency token – the *last* frame the caller believes
            was successfully committed.  If it mismatches, the commit fails.
        entity_changes
            Iterable of :class:`~ledgerquest.services.game_loop.state_committer.EntityChange`.

        Returns
        -------
        dict
            Metadata about the commit (timings, S3-pointer, etc.).

        Raises
        ------
        ConcurrencyConflictError
            When the server-side frame pointer differs from `expected_previous_frame_id`.
        StorageError
            For any other storage-layer failure.
        """
        start_ts = time.time()

        # Serialise entity changes
        if not entity_changes:
            raise ValueError("entity_changes cannot be empty")

        changes_serialised: List[Dict[str, Any]] = [
            change.to_dict() if isinstance(change, EntityChange) else dict(change)
            for change in entity_changes
        ]
        commit_payload = {
            "tenantId": tenant_id,
            "sessionId": session_id,
            "frameId": frame_id,
            "changes": changes_serialised,
            "committedAt": _utc_now_rfc3339(),
        }

        # Decide whether to inline payload or off-load to S3
        ddb_item: Dict[str, Any] = self._build_ddb_item(
            payload=commit_payload,
            tenant_id=tenant_id,
            session_id=session_id,
            frame_id=frame_id,
            previous_frame_id=expected_previous_frame_id,
        )

        try:
            self._execute_transaction(ddb_item)
            elapsed = time.time() - start_ts
            self._emit_metrics(
                tenant_id=tenant_id,
                session_id=session_id,
                payload_size_bytes=_estimate_item_size(ddb_item),
                duration_ms=elapsed * 1000,
            )
            return {
                "status": "OK",
                "payloadInlined": "s3Pointer" not in ddb_item,
                "elapsedMs": round(elapsed * 1000, 2),
            }
        except ConcurrencyConflictError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.exception("Unexpected error while committing state")
            raise StorageError("Failed to commit state") from exc

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _build_ddb_item(
        self,
        *,
        payload: MutableMapping[str, Any],
        tenant_id: str,
        session_id: str,
        frame_id: int,
        previous_frame_id: int,
    ) -> Dict[str, Any]:
        """Create a DynamoDB item, deciding if payload must be off-loaded to S3."""
        partition_key = f"TENANT#{tenant_id}"
        sort_key = f"SESSION#{session_id}#FRAME#{frame_id:012d}"

        item: Dict[str, Any] = {
            "pk": {"S": partition_key},
            "sk": {"S": sort_key},
            "prevFrameId": {"N": str(previous_frame_id)},
            "committedAt": {"S": payload["committedAt"]},
            # The frame counter is duplicated outside of the payload for queries
            "frameId": {"N": str(frame_id)},
        }

        serialized_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        est_size = _estimate_item_size(item) + len(serialized_payload)

        if est_size < MAX_DDB_ITEM_SIZE - 2048:  # keep some buffer
            item["payload"] = {"S": serialized_payload.decode("utf-8")}
            return item

        # Payload too large – off-load to S3
        pointer = self._offload_to_s3(
            data=serialized_payload,
            tenant_id=tenant_id,
            session_id=session_id,
            frame_id=frame_id,
        )
        item["s3Pointer"] = {"S": pointer}
        item["payloadSize"] = {"N": str(len(serialized_payload))}
        return item

    def _offload_to_s3(
        self,
        *,
        data: bytes,
        tenant_id: str,
        session_id: str,
        frame_id: int,
    ) -> str:
        """Upload compressed payload to S3 and return the URI."""
        key = (
            f"{self._prefix.rstrip('/')}/"
            f"{tenant_id}/{session_id}/frame-{frame_id:012d}.json.gz"
        ).lstrip("/")
        compressed = _gzip_compress(data)

        self._log.debug(
            "Uploading %s bytes (compressed to %s) to s3://%s/%s",
            len(data),
            len(compressed),
            self._bucket,
            key,
        )
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=compressed,
                ContentType="application/json",
                ContentEncoding="gzip",
                StorageClass=DEFAULT_S3_STORAGE_CLASS,
            )
        except (BotoCoreError, ClientError) as exc:  # noqa: PERF203
            raise StorageError("Failed to off-load payload to S3") from exc
        return f"s3://{self._bucket}/{key}"

    # --------------------------------------------------------------------- #
    # DynamoDB transaction
    # --------------------------------------------------------------------- #

    def _execute_transaction(self, item: Dict[str, Any]) -> None:
        """Perform the conditional write that makes the commit atomic."""
        partition_key: str = item["pk"]["S"]
        frame_id: int = int(item["frameId"]["N"])
        previous_frame_id: int = int(item["prevFrameId"]["N"])

        # Primary session pointer item – one per session, updated every frame
        session_pointer_key = {
            "pk": {"S": partition_key},
            "sk": {"S": "SESSION_POINTER"},
        }

        # Expression ensures that the pointer currently equals *previous_frame_id*.
        update_expression = (
            "SET lastFrameId = :frameId, modifiedAt = :ts "
            "REMOVE staleSince"
        )
        condition_expression = "attribute_not_exists(lastFrameId) OR lastFrameId = :expected"

        transact_items = [
            {
                "Put": {
                    "TableName": self._table,
                    "Item": item,
                    "ConditionExpression": "attribute_not_exists(pk) AND attribute_not_exists(sk)",
                }
            },
            {
                "Update": {
                    "TableName": self._table,
                    "Key": session_pointer_key,
                    "UpdateExpression": update_expression,
                    "ConditionExpression": condition_expression,
                    "ExpressionAttributeValues": {
                        ":frameId": {"N": str(frame_id)},
                        ":expected": {"N": str(previous_frame_id)},
                        ":ts": {"S": _utc_now_rfc3339()},
                    },
                }
            },
        ]

        try:
            self._ddb.transact_write_items(TransactItems=transact_items)
        except self._ddb.exceptions.TransactionCanceledException as exc:
            # Inspect cancellation reasons for concurrency error
            cancellation_errors = getattr(exc, "response", {}).get(
                "CancellationReasons", []
            )
            for reason in cancellation_errors:
                if reason.get("Code") == "ConditionalCheckFailed":
                    raise ConcurrencyConflictError(
                        "Session pointer mismatch – concurrent update detected."
                    ) from exc
            raise StorageError("DynamoDB transaction failed") from exc
        except (BotoCoreError, ClientError) as exc:  # noqa: PERF203
            raise StorageError("DynamoDB transaction failed") from exc

    # --------------------------------------------------------------------- #
    # Metrics
    # --------------------------------------------------------------------- #

    def _emit_metrics(
        self,
        *,
        tenant_id: str,
        session_id: str,
        payload_size_bytes: int,
        duration_ms: float,
    ) -> None:
        """Log commit metrics to stdout for CloudWatch EMF pipeline.

        EMF schema:
            {
              "_aws": {
                  "Timestamp": 1670000000000,
                  "CloudWatchMetrics": [
                    {
                      "Namespace": "LedgerQuest/StateCommitter",
                      "Dimensions": [["tenantId", "sessionId"]],
                      "Metrics": [
                        {"Name": "PayloadSize", "Unit": "Bytes"},
                        {"Name": "Latency", "Unit": "Milliseconds"}
                      ]
                    }
                  ]
              },
              "tenantId": "t-123",
              "sessionId": "s-123",
              "PayloadSize": 12345,
              "Latency": 10.3
            }
        """
        try:
            ts = int(time.time() * 1000)
            metric_doc = {
                "_aws": {
                    "Timestamp": ts,
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "LedgerQuest/StateCommitter",
                            "Dimensions": [["tenantId", "sessionId"]],
                            "Metrics": [
                                {"Name": "PayloadSize", "Unit": "Bytes"},
                                {"Name": "Latency", "Unit": "Milliseconds"},
                            ],
                        }
                    ],
                },
                "tenantId": tenant_id,
                "sessionId": session_id,
                "PayloadSize": payload_size_bytes,
                "Latency": duration_ms,
            }
            print(json.dumps(metric_doc))  # CloudWatch agent will detect EMF
        except Exception:  # noqa: BLE001
            # Metrics are non-critical; ensure they don't break main flow.
            self._log.debug("Failed to emit EMF metrics", exc_info=True)
```