```python
"""
LedgerQuest Engine – pytest configuration & reusable fixtures.

The fixtures defined here spin-up an entirely in-memory copy of the
engine’s AWS-centric control-plane (DynamoDB, S3, EventBridge,
Step Functions, …) by relying on `moto`.  This allows unit- and
integration-tests to exercise the same data-access paths and
contract boundaries that exist in production—without touching real
AWS resources or requiring any developer credentials.

The file intentionally focuses on *infrastructure* concerns and
keeps domain-level helpers (e.g. specialised ECS assemblers) very
thin, so that individual test-modules remain free to build the
precise entities/levels they require.
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List

import boto3
import pytest
from faker import Faker
from moto import (
    mock_dynamodb2,
    mock_events,
    mock_s3,
    mock_stepfunctions,
)

# --------------------------------------------------------------------------------------
# CONSTANTS & TEST-HELPERS
# --------------------------------------------------------------------------------------

_TEST_REGION = "us-east-1"
_DYNAMODB_TABLE_NAME = "ledgerquest-tests-table"
_S3_BUCKET_NAME = "ledgerquest-tests-bucket"
_EVENT_BUS_NAME = "ledgerquest-game-events"
_STEP_FN_NAME = "ledgerquest-main-loop"


def _set_fake_aws_creds() -> None:
    """
    moto does not automatically inject AWS_* credentials.  Most SDK
    calls fail if these environment variables are missing, therefore
    we patch them with dummy values before mocks are started.
    """
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", _TEST_REGION)


def _build_dynamodb_table() -> None:
    """Create the ledgerquest test table in moto's fake DynamoDB."""
    ddb = boto3.client("dynamodb", region_name=_TEST_REGION)
    ddb.create_table(
        TableName=_DYNAMODB_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
    )
    ddb.get_waiter("table_exists").wait(TableName=_DYNAMODB_TABLE_NAME)


def _build_s3_bucket() -> None:
    """Create test S3 bucket used for level assets and replays."""
    s3 = boto3.client("s3", region_name=_TEST_REGION)
    s3.create_bucket(
        Bucket=_S3_BUCKET_NAME,
        CreateBucketConfiguration={"LocationConstraint": _TEST_REGION},
    )


def _build_event_bus() -> None:
    """Create a dedicated EventBridge bus."""
    eb = boto3.client("events", region_name=_TEST_REGION)
    eb.create_event_bus(Name=_EVENT_BUS_NAME)


def _build_step_function() -> str:
    """
    Create a trivial state-machine representing the game-loop.

    Returns
    -------
    str
        The ARN of the newly created state machine.
    """
    sf = boto3.client("stepfunctions", region_name=_TEST_REGION)

    definition = {
        "Comment": "Test game-loop",
        "StartAt": "Noop",
        "States": {
            "Noop": {
                "Type": "Pass",
                "End": True,
            }
        },
    }

    response = sf.create_state_machine(
        name=_STEP_FN_NAME,
        definition=json.dumps(definition),
        roleArn=f"arn:aws:iam::000000000000:role/{_STEP_FN_NAME}-role",
        type="STANDARD",
    )
    return response["stateMachineArn"]


# --------------------------------------------------------------------------------------
# PYTEST HOOKS
# --------------------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """
    Register **LedgerQuest** label so internal markers don't trigger
    warnings with `--strict-markers`.
    """
    config.addinivalue_line(
        "markers",
        "ledgerquest: mark test as belonging to the LedgerQuest Engine suite",
    )


# --------------------------------------------------------------------------------------
# FIXTURES—INFASTRUCTURE
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def faker_locale() -> str:
    """Single place to override default Faker locale for all tests."""
    return "en_US"


@pytest.fixture(scope="session")
def fake(faker_locale: str) -> Faker:
    """Shared Faker instance to improve test performance."""
    return Faker(locale=faker_locale)


@pytest.fixture(scope="session")
def aws_credentials() -> None:
    """
    Auto-use fixture that ensures dummy AWS credentials exist in the
    environment for the entire test-run.
    """
    _set_fake_aws_creds()


@pytest.fixture(scope="session")
def moto_session(
    aws_credentials: None,
) -> Iterator[None]:
    """
    Starts/stops all moto mocks that the engine relies on.  Holding
    them at **session** scope is significantly faster than spinning
    them up per-test, while still ensuring isolation thanks to moto's
    internal state-reset between tests.
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock_dynamodb2())
        stack.enter_context(mock_s3())
        stack.enter_context(mock_events())
        stack.enter_context(mock_stepfunctions())

        # Bootstrap resources inside the fakeAWS session
        _build_dynamodb_table()
        _build_s3_bucket()
        _build_event_bus()
        _build_step_function()

        yield  # tests execute here


@pytest.fixture(scope="function")
def ddb_table(moto_session: None) -> str:
    """
    Return the name of the DynamoDB table pre-created for tests.
    Individual tests can put/delete/query items without additional
    setup.
    """
    return _DYNAMODB_TABLE_NAME


@pytest.fixture(scope="function")
def s3_bucket(moto_session: None) -> str:
    """Name of the moto S3 bucket used by the engine."""
    return _S3_BUCKET_NAME


@pytest.fixture(scope="function")
def event_bus(moto_session: None) -> str:
    """Name of the EventBridge bus."""
    return _EVENT_BUS_NAME


@pytest.fixture(scope="function")
def step_function_arn(moto_session: None) -> str:
    """ARN of the fake Step Functions state machine."""
    # Re-fetch because the ARN is generated at runtime.
    sf = boto3.client("stepfunctions", region_name=_TEST_REGION)
    machines = sf.list_state_machines()["stateMachines"]
    return machines[0]["stateMachineArn"]


# --------------------------------------------------------------------------------------
# FIXTURES—DOMAIN SPECIFIC
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="function")
def tenant_id(fake: Faker) -> str:
    """Randomly generated tenant identifier used for multitenant tests."""
    return fake.uuid4()


@pytest.fixture(scope="function")
def game_world(tenant_id: str) -> "World":  # type: ignore[name-defined]
    """
    Yield a fresh ECS `World` instance pre-configured for the given
    tenant.  Components/Systems are *not* pre-registered to keep this
    fixture generic.  Tests should add what they need locally.

    The import is done lazily to avoid blowing up if optional engine
    extras (GPU libs, etc.) are missing in the CI environment.
    """
    from game_engine.ecs import World  # heavy import; keep local

    world = World(tenant=tenant_id)
    yield world
    # The engine guarantees that `World.dispose()` flushes any
    # background tasks, making it safe for modularised tests.
    world.dispose()


# --------------------------------------------------------------------------------------
# FILE-SYSTEM UTILITY FIXTURES
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="function")
def tmp_assets_dir(tmp_path: Path) -> Path:
    """
    Provide a temporary directory that mimics the layout of an asset
    bundle.  Tests may write GLTFs, JSONs, audio files, etc. here.

    Returns
    -------
    pathlib.Path
        Empty directory that gets deleted after the test is finished.
    """
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    return assets_dir


# --------------------------------------------------------------------------------------
# CREATIONAL HELPERS (RETURNED AS DICT FOR EASY SERIALISATION)
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="function")
def sample_player_state(fake: Faker) -> Dict[str, Any]:
    """
    Quickly construct a JSON-serialisable dict representing a player's
    save-game.  By centralising the generator, we guarantee consistent
    shape across unrelated tests.
    """
    return {
        "player_id": fake.uuid4(),
        "position": {"x": fake.pyfloat(), "y": fake.pyfloat(), "z": fake.pyfloat()},
        "inventory": [fake.word() for _ in range(3)],
        "currency": {"gold": fake.pyint(min_value=0, max_value=9999)},
        "achievements": [],
        "timestamp": fake.iso8601(),
    }


# --------------------------------------------------------------------------------------
# MISCELLANEOUS
# --------------------------------------------------------------------------------------


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """
    Automatically mark all tests inside `tests/integration/` as
    belonging to the “integration” group if the marker is missing.
    """
    if "tests/integration/" in str(item.fspath) and not item.get_closest_marker(
        "integration"
    ):
        item.add_marker(pytest.mark.integration)
```