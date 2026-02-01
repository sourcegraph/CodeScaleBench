```python
"""
Integration tests for the LedgerQuest Engine asset-ingest pipeline.

These tests spin up fully-featured, in-memory AWS services (via `moto`) and
exercise the Lambda entry-point that reacts to fresh scene-asset uploads:

    1.  The scene is uploaded to an S3 bucket.
    2.  A Lambda function (`game_engine.asset_pipeline.processor.lambda_handler`)
        calculates metadata, stores it in DynamoDB, and kicks off a
        Step-Functions workflow that renders GPU thumbnails, generates LODs,
        etc.

Because we do not want to hit real AWS services in CI we:
    • Use `moto` for S3 and DynamoDB.
    • Monkey-patch the Step-Functions client to a local spy.
"""
from __future__ import annotations

import base64
import json
import hashlib
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Dict, Generator, List, Tuple

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_dynamodb, mock_s3

pytest.importorskip("boto3")  # Hard requirement for these tests

# Try to import the Lambda under test.  If the target module is unavailable the
# test-run should fail early rather than silently passing.
try:
    from game_engine.asset_pipeline import processor  # type: ignore
except ImportError as exc:  # pragma: no cover — failing early is important here
    raise RuntimeError(
        "Unable to import game_engine.asset_pipeline.processor; "
        "ensure the LedgerQuest Engine source is on PYTHONPATH.",
    ) from exc


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
ASSET_BUCKET = "lq-assets"
ASSET_TABLE = "AssetIndex"


@pytest.fixture(scope="function")
def aws_env() -> Generator[Tuple[boto3.resource, boto3.client], None, None]:
    """
    Spin up in-memory S3 and DynamoDB backends for the lifetime of a single
    test function.
    """
    with mock_s3(), mock_dynamodb():
        # Setup resources
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=ASSET_BUCKET)

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName=ASSET_TABLE,
            KeySchema=[{"AttributeName": "asset_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "asset_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        yield dynamodb, s3


@pytest.fixture(scope="function")
def stepfunctions_spy(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """
    Monkey-patch the Step-Functions client with a stub that records invocations
    for later inspection.
    """
    calls: List[Dict[str, Any]] = []

    class _FakeSFNClient:  # pylint: disable=too-few-public-methods
        def start_execution(self, **kwargs: Any) -> Dict[str, Any]:
            calls.append(kwargs)
            # Return shape must match AWS's response contract
            return {
                "executionArn": f"arn:aws:states:us-east-1:123456789012:execution:AssetPipeline:{uuid.uuid4()}",
                "startDate": datetime.now(tz=timezone.utc),
                "ResponseMetadata": {
                    "HTTPStatusCode": 200,
                    "RequestId": str(uuid.uuid4()),
                    "RetryAttempts": 0,
                },
            }

    # Patch the `boto3.client("stepfunctions")` call inside the processor module
    monkeypatch.setattr(processor.boto3, "client", lambda service, **_: _FakeSFNClient() if service == "stepfunctions" else boto3.client(service, **_))  # type: ignore[attr-defined]

    return calls


# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #
def _make_s3_event(bucket: str, key: str) -> Dict[str, Any]:
    """
    Create a pseudo-S3 event that looks like the one emitted by AWS when
    users upload a file through the console/API.
    """
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventTime": datetime.utcnow().isoformat() + "Z",
                "requestParameters": {"sourceIPAddress": "127.0.0.1"},
                "s3": {
                    "bucket": {"name": bucket, "arn": f"arn:aws:s3:::{bucket}", "ownerIdentity": {"principalId": "EXAMPLE"}},
                    "object": {"key": key, "size": 0, "sequencer": "0A1B2C3D4E5F678901"},
                },
            }
        ]
    }


def _upload_random_asset(s3_client: boto3.client, key: str) -> Tuple[bytes, str]:
    """
    Upload a random 'scene' file to the bucket and return the (bytes, sha256)
    so that downstream assertions can confirm integrity.
    """
    # LedgerQuest scenes are GLB under the hood; we can get away with dummy bytes
    payload = uuid.uuid4().bytes * 4  # 64 bytes of entropy
    checksum = hashlib.sha256(payload).hexdigest()

    s3_client.put_object(Bucket=ASSET_BUCKET, Key=key, Body=payload)

    return payload, checksum


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_scene_asset_upload_triggers_pipeline(
    aws_env: Tuple[boto3.resource, boto3.client],
    stepfunctions_spy: List[Dict[str, Any]],
) -> None:
    """Happy path: uploading a new asset should persist metadata and launch the Step-Functions workflow."""
    dynamodb, s3 = aws_env

    key = "uploads/scene_001.glb"
    payload, checksum = _upload_random_asset(s3, key)
    event = _make_s3_event(ASSET_BUCKET, key)

    # Act
    result = processor.lambda_handler(event, context={})  # type: ignore[arg-type]
    assert result is None or result.get("status") == "OK"

    # Assert: Dynamo record
    table = dynamodb.Table(ASSET_TABLE)
    items = table.scan()["Items"]
    assert len(items) == 1, "Exactly one record should be written to AssetIndex"

    rec = items[0]
    assert rec["s3_key"] == key
    assert rec["checksum_sha256"] == checksum
    assert rec["file_size_bytes"] == len(payload)

    # Assert: Step-Functions was invoked with correct payload
    assert len(stepfunctions_spy) == 1, "A single Step-Functions execution should be started"
    started = stepfunctions_spy[0]
    input_payload = json.loads(started["input"])
    assert input_payload["assetId"] == rec["asset_id"]
    assert input_payload["s3Uri"].endswith(key)


def test_duplicate_upload_is_idempotent(
    aws_env: Tuple[boto3.resource, boto3.client],
    stepfunctions_spy: List[Dict[str, Any]],
) -> None:
    """
    The Lambda should be safe to invoke multiple times with the same asset;
    it must not create duplicate DynamoDB entries or trigger duplicate renders.
    """
    dynamodb, s3 = aws_env
    key = "uploads/double_tap.glb"

    _upload_random_asset(s3, key)
    first_event = _make_s3_event(ASSET_BUCKET, key)
    processor.lambda_handler(first_event, context={})  # type: ignore[arg-type]

    # Upload the exact same payload again to simulate accidental re-upload
    _upload_random_asset(s3, key)
    second_event = _make_s3_event(ASSET_BUCKET, key)
    processor.lambda_handler(second_event, context={})  # type: ignore[arg-type]

    # Only one DynamoDB item expected
    table = dynamodb.Table(ASSET_TABLE)
    items = table.scan()["Items"]
    assert len(items) == 1

    # Likewise Step-Functions: only one workflow should be started
    assert len(stepfunctions_spy) == 1
```