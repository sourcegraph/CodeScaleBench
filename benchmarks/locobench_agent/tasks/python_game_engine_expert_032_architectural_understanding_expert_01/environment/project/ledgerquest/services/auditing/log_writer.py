```python
"""
ledgerquest.services.auditing.log_writer
---------------------------------------

A thin yet robust audit trail writer that fulfils the multi-tenant compliance
requirements of LedgerQuest Engine.  The writer batches audit log records and
persists them to a DynamoDB table while also emitting them to the Python
logging subsystem for CloudWatch log shipping.

Design goals
============

1.  **Low-latency hot path** – game logic must not block on I/O.
2.  **Serverless constraints** – executions may be frozen or force-ended at any
    time.  Provide an explicit `flush()` so Lambda handlers can persist
    buffered events right before returning.
3.  **Cost-optimised** – leverage `batch_write_item` (25 items) to minimise API
    calls.
4.  **Defensive** – retries with decorrelated jitter and partial-failure
    detection.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from itertools import islice
from typing import Any, Dict, Iterable, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

__all__ = ["AuditLogRecord", "LogWriter"]

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

_DEFAULT_TABLE_NAME = os.getenv("LQ_ENGINE_AUDIT_TABLE", "ledgerquest-audit")
_MAX_BATCH_SIZE = 25  # DynamoDB limit
_MAX_RETRIES = 5
_BASE_BACKOFF = 0.1  # seconds
_LOGGER = logging.getLogger("ledgerquest.audit")

# --------------------------------------------------------------------------------------
# Data Model
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuditLogRecord:
    """
    A single immutable audit-trail entry.

    NOTE:
        Keep the footprint small – this struct may be instantiated thousands of
        times per second during peak multiplayer sessions.
    """

    tenant_id: str
    user_id: str
    session_id: str
    action: str
    entity_type: str
    entity_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def to_ddb_item(self) -> Dict[str, Dict[str, Any]]:
        """
        Convert this record into the DynamoDB attribute-value map format.

        Partition / sort key schema:
            PK = TENANT#<tenant_id>
            SK = <ts_iso>#<session_id>#<action>

        Secondary index on `entity_id` enables look-ups by domain object.
        """
        iso_ts = self.timestamp.isoformat()

        return {
            "PK": {"S": f"TENANT#{self.tenant_id}"},
            "SK": {"S": f"{iso_ts}#{self.session_id}#{self.action}"},
            "entity_type": {"S": self.entity_type},
            "entity_id": {"S": self.entity_id},
            "user_id": {"S": self.user_id},
            "session_id": {"S": self.session_id},
            "action": {"S": self.action},
            "timestamp": {"S": iso_ts},
            # Serialise metadata as JSON string.  DDB 'M' types must have
            # homogeneous value types, which cannot be guaranteed here.
            "metadata": {"S": json.dumps(self.metadata, default=_json_fallback)},
        }

    def to_json(self) -> str:
        """Human-readable JSON representation used in CloudWatch logs."""
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        return json.dumps(payload, default=_json_fallback)


def _json_fallback(o: Any) -> str:
    """Best-effort JSON serialiser for otherwise unsupported objects."""
    try:
        return str(o)
    except Exception:  # pragma: no cover
        return "<unserialisable>"


# --------------------------------------------------------------------------------------
# Helper utilities
# --------------------------------------------------------------------------------------


def _chunks(iterable: Iterable[Any], size: int) -> Iterable[List[Any]]:
    """Yield successive *size* chunks from *iterable*."""
    iterator = iter(iterable)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _sleep_with_jitter(attempt: int) -> None:
    """
    Exponential back-off with full jitter, as per AWS architecture guidelines.

    delay = random_between(0, base * 2**attempt)
    """
    delay = random.uniform(0, _BASE_BACKOFF * (2**attempt))
    time.sleep(delay)


# --------------------------------------------------------------------------------------
# LogWriter
# --------------------------------------------------------------------------------------


class LogWriter:
    """
    Thread-safe, batching audit log writer.

    Basic usage inside a Lambda handler::

        log_writer = LogWriter()
        # ... game loop / business logic ...
        log_writer.write(
            tenant_id=ctx.tenant,
            user_id=ctx.user,
            session_id=ctx.session,
            action="PLAYER_MOVED",
            entity_type="avatar",
            entity_id=player_id,
            metadata={"x": 42, "y": 21},
        )
        # ensure we persisted all buffered events
        log_writer.flush()
    """

    _lock: threading.Lock
    _buffer: List[AuditLogRecord]
    _client: "boto3.client"

    def __init__(
        self,
        dynamodb_table: str | None = None,
        aws_region: str | None = None,
        boto3_client: Optional["boto3.client"] = None,
    ) -> None:
        self._table_name = dynamodb_table or _DEFAULT_TABLE_NAME
        self._client = boto3_client or boto3.client(
            "dynamodb", region_name=aws_region
        )
        self._buffer = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ Public API

    def write(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Buffer an audit event.

        Non-blocking; performs minimal work and returns immediately.
        """
        record = AuditLogRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata or {},
            timestamp=timestamp or datetime.now(tz=timezone.utc),
        )

        with self._lock:
            self._buffer.append(record)
            buffer_len = len(self._buffer)

        _LOGGER.debug(
            "Buffered audit record (%s). Current buffer size=%d",
            record.action,
            buffer_len,
        )

        if buffer_len >= _MAX_BATCH_SIZE:
            self.flush()

    def flush(self) -> None:
        """
        Write all buffered records to DynamoDB.

        Retries transient errors automatically.  On unrecoverable failure the
        records are *not* dropped – they remain in the buffer so that the caller
        can retry or persist them elsewhere (e.g. S3 DLQ).
        """
        with self._lock:
            if not self._buffer:
                _LOGGER.debug("No audit records to flush.")
                return

            records = self._buffer
            self._buffer = []

        _LOGGER.debug("Flushing %d audit records ...", len(records))

        for chunk in _chunks(records, _MAX_BATCH_SIZE):
            # Translate to DynamoDB format once to avoid repeated costs in retry loop
            request_items = [
                {"PutRequest": {"Item": rec.to_ddb_item()}} for rec in chunk
            ]
            self._batch_put_with_retry(request_items)

            # Even if the write fails, we still log the record in CloudWatch
            for rec in chunk:
                _LOGGER.info(rec.to_json())

    # ------------------------------------------------------------------ Internals

    def _batch_put_with_retry(self, items: List[Dict[str, Any]]) -> None:
        """
        `batch_write_item` with partial unprocessed handling and retries.

        Adopt the pattern recommended in
        https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/example-python-write-batch.html
        """
        attempt = 0
        unprocessed = items

        while unprocessed and attempt < _MAX_RETRIES:
            try:
                response = self._client.batch_write_item(
                    RequestItems={self._table_name: unprocessed},
                    ReturnConsumedCapacity="NONE",
                )
                unprocessed = response.get("UnprocessedItems", {}).get(
                    self._table_name, []
                )
            except (ClientError, BotoCoreError) as exc:
                _LOGGER.warning(
                    "DynamoDB batch_write_item failed on attempt %d/%d: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    exc_info=_LOGGER.isEnabledFor(logging.DEBUG),
                )
                _sleep_with_jitter(attempt)
            else:
                if unprocessed:
                    _LOGGER.debug(
                        "%d items unprocessed, retrying ...", len(unprocessed)
                    )
                    _sleep_with_jitter(attempt)
            attempt += 1

        if unprocessed:
            # Re-enqueue unprocessed items back to buffer for caller to decide.
            with self._lock:
                self._buffer.extend(
                    AuditLogRecord(
                        tenant_id=item["PutRequest"]["Item"]["PK"]["S"].split(
                            "#", maxsplit=1
                        )[1],
                        user_id=item["PutRequest"]["Item"]["user_id"]["S"],
                        session_id=item["PutRequest"]["Item"]["session_id"]["S"],
                        action=item["PutRequest"]["Item"]["action"]["S"],
                        entity_type=item["PutRequest"]["Item"]["entity_type"][
                            "S"
                        ],
                        entity_id=item["PutRequest"]["Item"]["entity_id"]["S"],
                        metadata=json.loads(
                            item["PutRequest"]["Item"]["metadata"]["S"]
                        ),
                        timestamp=datetime.fromisoformat(
                            item["PutRequest"]["Item"]["timestamp"]["S"]
                        ),
                    )
                    for item in unprocessed
                )
            raise RuntimeError(
                f"Failed to write {len(unprocessed)} audit records after "
                f"{_MAX_RETRIES} attempts; re-queued for later flush."
            )
```