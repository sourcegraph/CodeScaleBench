```python
"""
Unit-tests for the AuditLogWriter class that lives in
`game_engine.services.auditing.log_writer`.

The writer’s responsibilities are to
    1. Buffer audit events in memory and flush them to DynamoDB in batches.
    2. Respect a configurable max-batch size.
    3. Attach a correlation-id to every event.
    4. Retry on retryable DynamoDB errors (e.g. ProvisionedThroughputExceededException).

These tests rely on `botocore.stub.Stubber` to prevent any real AWS calls from
occurring.  Where timing is involved we monkey-patch `time.sleep` so tests run
quickly.

NOTE:
If you refactor the AuditLogWriter API please update the helper functions
(`_build_event`, `_expect_batch_write`) so the assertions match your new schema.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Any
from uuid import uuid4

import boto3
import pytest
from botocore.stub import Stubber, ANY

# --------------------------------------------------------------------------- #
#                                Test helpers                                 #
# --------------------------------------------------------------------------- #


def _build_event(action: str = "create", entity: str = "player") -> Dict[str, Any]:
    """Return a minimal, schema-valid audit event."""
    return {
        "action": action,
        "entity": entity,
        "performed_by": "unit-tester",
        "performed_at": datetime.now(timezone.utc).isoformat(),
    }


def _expect_batch_write(stubber: Stubber, table_name: str, batch_len: int) -> None:
    """
    Register a stubbed DynamoDB `batch_write_item` call that matches
    `batch_len` items and succeeds without unprocessed items.
    """
    stubber.add_response(
        "batch_write_item",
        expected_params={
            "RequestItems": ANY,  # We don’t want brittle tests ‑ just validate the call shape
            "ReturnConsumedCapacity": "TOTAL",
            "ReturnItemCollectionMetrics": "SIZE",
        },
        service_response={"UnprocessedItems": {}},
    )


# --------------------------------------------------------------------------- #
#                                  Fixtures                                   #
# --------------------------------------------------------------------------- #


@pytest.fixture(name="aws_session")
def fx_aws_session() -> boto3.Session:
    """A real boto3 session that talks to a stubbed client only."""
    return boto3.Session(region_name="us-east-1")


@pytest.fixture(name="dynamodb_stub")
def fx_dynamodb_stub(monkeypatch: pytest.MonkeyPatch, aws_session: boto3.Session) -> Stubber:
    """
    Supply a Stubber hooked into the DynamoDB client that
    `AuditLogWriter` will end up using.
    """
    client = aws_session.client("dynamodb")
    stubber = Stubber(client)

    # Ensure whatever code calls `session.client('dynamodb')`
    # gets our stubbed client back.
    monkeypatch.setattr(aws_session, "client", lambda *_args, **_kw: client)
    return stubber


@pytest.fixture(name="no_sleep")
def fx_no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force `time.sleep` to return immediately so retries are instant."""
    monkeypatch.setattr(time, "sleep", lambda _secs: None)


@pytest.fixture(name="log_writer")
def fx_log_writer(dynamodb_stub: Stubber, aws_session: boto3.Session):
    """
    Instantiate the writer under test *after* the stub has been installed so
    the writer grabs the stubbed DynamoDB client.
    """
    from game_engine.services.auditing.log_writer import AuditLogWriter

    writer = AuditLogWriter(
        table_name="audit_events",
        boto3_session=aws_session,
        max_batch=2,  # Keep batches tiny so tests run quick.
    )
    return writer


# --------------------------------------------------------------------------- #
#                                    Tests                                    #
# --------------------------------------------------------------------------- #


def test_write_single_event_flushes(monkeypatch, dynamodb_stub: Stubber, log_writer):
    """
    GIVEN an AuditLogWriter with max_batch = 2
    WHEN a caller writes a single event and flush() is invoked
    THEN a single DynamoDB batch_write_item call is issued.
    """
    _expect_batch_write(dynamodb_stub, "audit_events", 1)
    dynamodb_stub.activate()

    log_writer.write(_build_event(), correlation_id=str(uuid4()))
    log_writer.flush()  # force the flush for deterministic behaviour

    dynamodb_stub.assert_no_pending_responses()
    dynamodb_stub.deactivate()


def test_batching_respects_max_batch_size(dynamodb_stub: Stubber, log_writer):
    """
    GIVEN max_batch = 2
    WHEN three events are queued
    THEN the writer should flush twice:
         – first flush at 2 items (auto-flush),
         – second flush for the remaining single item at explicit flush().
    """
    # First auto-flush will contain 2 events, second explicit flush 1 event.
    _expect_batch_write(dynamodb_stub, "audit_events", 2)
    _expect_batch_write(dynamodb_stub, "audit_events", 1)
    dynamodb_stub.activate()

    # These two should auto-flush on the second write (batch size met).
    log_writer.write(_build_event("create"), correlation_id="corr-1")
    log_writer.write(_build_event("update"), correlation_id="corr-2")

    # Third event sits in buffer until explicit flush.
    log_writer.write(_build_event("delete"), correlation_id="corr-3")
    log_writer.flush()

    dynamodb_stub.assert_no_pending_responses()
    dynamodb_stub.deactivate()


def test_missing_required_field_raises_validation_error(log_writer):
    """
    The writer is expected to validate incoming payloads.
    An event missing a critical field (e.g. 'action') should raise ValueError.
    """
    bad_event = {"entity": "player"}  # missing 'action'
    with pytest.raises(ValueError):
        log_writer.write(bad_event, correlation_id="bad-corr-id")


def test_retry_on_throughput_exceeded(
    dynamodb_stub: Stubber, log_writer, no_sleep
):
    """
    GIVEN DynamoDB repeatedly throws ProvisionedThroughputExceededException
    WHEN flush() is executed
    THEN AuditLogWriter should retry automatically and finally succeed.
    """

    # First attempt raises a throughput error; second attempt succeeds.
    dynamodb_stub.add_client_error(
        "batch_write_item",
        service_error_code="ProvisionedThroughputExceededException",
        service_message="Simulated capacity error",
    )
    _expect_batch_write(dynamodb_stub, "audit_events", 1)
    dynamodb_stub.activate()

    log_writer.write(_build_event(), correlation_id="retry-test-1")
    log_writer.flush()

    dynamodb_stub.assert_no_pending_responses()
    dynamodb_stub.deactivate()
```