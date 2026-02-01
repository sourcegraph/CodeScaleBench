"""
Shared fixtures and utilities for Service-layer unit tests.

This module is imported automatically by pytest thanks to the
standard Python package discovery rules.  All fixtures declared
here are therefore available to every test module located under
tests/unit/services/.

The intent is to provide:

* A completely self-contained, in-memory AWS environment powered
  by ``moto`` so that service tests can run offline and deterministically.
* Common helpers for generating predictable identifiers, test payloads,
  and environment variables that mirror Production defaults.
* Event-loop management for async code paths.

NOTE:
    We purposely keep the surface area small; only fixtures that are
    truly required by *multiple* test modules belong here.  One-off
    helpers should live next to the test that needs them.
"""

from __future__ import annotations

import os
import random
import string
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterator

import boto3
import pytest
from moto import mock_dynamodb2, mock_s3, mock_stepfunctions

# --------------------------------------------------------------------------- #
# ------------------------------  Constants  -------------------------------- #
# --------------------------------------------------------------------------- #

_DDB_TABLE_NAME = "LedgerQuest_GameState"
_S3_BUCKET_NAME = "ledgerquest-artifacts"
_SFN_STATE_MACHINE_NAME = "LedgerQuest-Orchestration-StateMachine"
_REGION_NAME = "us-east-1"

# --------------------------------------------------------------------------- #
# ---------------------------  Helper Functions  --------------------------- #
# --------------------------------------------------------------------------- #


def _random_suffix(length: int = 8) -> str:
    """
    Generate a short random string for resource suffixing.

    Args:
        length: How many characters the suffix should contain.

    Returns:
        A cryptographically-unsafe random string consisting of uppercase
        letters and digits.
    """
    population = string.ascii_uppercase + string.digits
    return "".join(random.SystemRandom().choice(population) for _ in range(length))


def iso_utc_now() -> str:
    """
    Returns the current UTC time as an ISO-8601 string with millisecond precision.
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def _aws_credentials() -> Iterator[None]:
    """
    Context manager that injects fake AWS credentials into the environment.
    Moto requires them to exist, even though it never validates the values.
    """
    env = {
        "AWS_ACCESS_KEY_ID":     "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN":    "testing",
        "AWS_SESSION_TOKEN":     "testing",
        "AWS_DEFAULT_REGION":    _REGION_NAME,
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield
    finally:
        # Restore original environment
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# --------------------------------------------------------------------------- #
# -----------------------------  Pytest Hooks  ------------------------------ #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def event_loop():
    """
    A session-wide asyncio event loop.

    This fixture overrides the default ``function`` scope of the built-in
    ``pytest-asyncio`` event loop so we can reuse the loop across tests,
    reducing startup overhead.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# --------------------------------------------------------------------------- #
# ----------------------------  AWS  Fixtures  ------------------------------ #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def aws_env() -> None:
    """
    Provide dummy AWS credentials for the entire test session.

    Tests that need to patch environment variables *must* declare a dependency
    on this fixture **before** monkeypatching to ensure ordering.
    """
    with _aws_credentials():
        yield


@pytest.fixture(scope="function")
def ddb_table(aws_env) -> boto3.resources.base.ServiceResource:
    """
    A fresh DynamoDB table for every test function.

    The schema matches the Production table used by LedgerQuest's GameState
    repository so that queries in service code remain valid.
    """
    with mock_dynamodb2():
        dynamodb = boto3.resource("dynamodb", region_name=_REGION_NAME)
        table = dynamodb.create_table(
            TableName=_DDB_TABLE_NAME + "-" + _random_suffix(),
            KeySchema=[
                {"AttributeName": "tenant_id", "KeyType": "HASH"},
                {"AttributeName": "entity_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "tenant_id", "AttributeType": "S"},
                {"AttributeName": "entity_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield table


@pytest.fixture(scope="function")
def s3_bucket(aws_env) -> boto3.resources.base.ServiceResource:
    """
    Creates a mock S3 bucket and yields the boto3 ``Bucket`` resource.
    """
    with mock_s3():
        s3 = boto3.resource("s3", region_name=_REGION_NAME)
        bucket = s3.Bucket(_S3_BUCKET_NAME + "-" + _random_suffix())
        bucket.create()
        yield bucket


@pytest.fixture(scope="function")
def stepfunctions_client(aws_env) -> boto3.client:
    """
    Provides a mock Step Functions client with a minimal State Machine registered.

    The created State Machine is a basic pass-through, but it's enough for
    service code that only needs to start executions and poll for status.
    """
    with mock_stepfunctions():
        client = boto3.client("stepfunctions", region_name=_REGION_NAME)

        definition = {
            "Comment": "LedgerQuest Game Loop (Mock)",
            "StartAt": "Pass",
            "States": {
                "Pass": {
                    "Type": "Pass",
                    "End": True,
                }
            },
        }

        role_arn = f"arn:aws:iam::123456789012:role/{_SFN_STATE_MACHINE_NAME}-Role"
        response = client.create_state_machine(
            name=_SFN_STATE_MACHINE_NAME + "-" + _random_suffix(),
            definition=str(definition),
            roleArn=role_arn,
        )
        state_machine_arn = response["stateMachineArn"]
        yield client, state_machine_arn


# --------------------------------------------------------------------------- #
# --------------------------  Domain Test Helpers  -------------------------- #
# --------------------------------------------------------------------------- #

@pytest.fixture
def sample_game_session_payload() -> Dict[str, str]:
    """
    Build a minimal Game Session payload similar to what the real API
    gateway would submit to our service layer.

    The payload is intentionally lightweight; individual tests can augment
    or override any fields they care about.
    """
    tenant_id = f"tenant-{_random_suffix(4).lower()}"
    session_id = f"session-{_random_suffix(6).lower()}"
    return {
        "tenant_id": tenant_id,
        "session_id": session_id,
        "started_at": iso_utc_now(),
        "metadata": {
            "platform": "pytest",
            "version": "unit-test",
        },
    }


def insert_dummy_game_state(
    table: boto3.resources.base.ServiceResource,
    tenant_id: str,
    entity_id: str,
    state: Dict[str, str] | None = None,
) -> None:
    """
    Convenience function to seed an item into the (mock) DynamoDB table.

    Args:
        table: The DynamoDB Table fixture returned from ``ddb_table``.
        tenant_id: Partition key for the item.
        entity_id: Sort key for the item.
        state: Additional attributes to persist with the item – defaults to
               an empty dict.
    """
    state = state or {}
    item = {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "payload": state,
        "updated_at": iso_utc_now(),
    }
    table.put_item(Item=item)
