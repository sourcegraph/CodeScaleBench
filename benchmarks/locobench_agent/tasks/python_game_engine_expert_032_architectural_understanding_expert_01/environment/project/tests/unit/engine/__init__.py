```python
"""
tests.unit.engine
=================

Package‐wide fixtures and test helpers for the LedgerQuest Engine “engine”
sub‐package.  By colocating them in ``tests/unit/engine/__init__.py`` we avoid
the overhead of an additional conftest.py file yet grant *all* unit tests under
``tests/unit/engine`` transparent access to AWS mocks, common factories and
assertion helpers.

The fixtures are intentionally *serverless-centric*: they wire up moto’s
in-memory equivalents for DynamoDB, S3 and Step Functions so that the engine’s
repository, queue and state-machine layers can be exercised without touching a
real AWS account (or even LocalStack).  Credentials are stubbed via environment
variables to keep boto3 quiet.

Usage
-----

Simply ``import`` the helpers in individual test modules:

    def test_component_fetches_state(dynamodb_table, ecs_world):
        ...

No explicit ``pytest_plugins`` entry is required because the current module is
imported automatically when tests are collected.
"""

from __future__ import annotations

import json
import os
import pathlib
import random
import string
from contextlib import contextmanager
from typing import Any, Dict, Iterator

import boto3
import pytest
from moto import mock_dynamodb, mock_s3, mock_stepfunctions

# --------------------------------------------------------------------------- #
# Constants & global test configuration
# --------------------------------------------------------------------------- #

# Marker names used across the engine test-suite.
PYTEST_MARKERS = (
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "aws_integration: marks tests that hit real AWS resources",
)


def pytest_configure(config):  # pylint: disable=unused-argument
    """Register custom markers so that `pytest -m slow` doesn’t warn."""

    for marker in PYTEST_MARKERS:
        config.addinivalue_line("markers", marker)


# --------------------------------------------------------------------------- #
# Generic utility helpers
# --------------------------------------------------------------------------- #


def _random_suffix(length: int = 6) -> str:
    """Return a cryptographically *insecure* random string for resource names."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


@contextmanager
def _aws_env_vars() -> Iterator[None]:
    """
    Context-manager that temporarily supplies dummy AWS credentials.

    boto3 refuses to work if *either* access key or secret key are missing.
    """
    stubbed = {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }
    original = {k: os.environ.get(k) for k in stubbed}

    try:
        os.environ.update(stubbed)
        yield
    finally:
        # Restore original env-vars (or unset if they did not exist before)
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# --------------------------------------------------------------------------- #
# Pytest fixtures – AWS mocks
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def aws_credentials() -> Iterator[None]:
    """
    Provide *session-scoped* dummy credentials for all tests.

    Contrary to the name, this fixture does *not* spin up moto.  It only sets
    the env-vars used by boto3.  Use together with ``mock_dynamodb`` or other
    moto decorators/fixtures.
    """
    with _aws_env_vars():
        yield


@pytest.fixture
def dynamodb_table(aws_credentials) -> Iterator[boto3.resources.base.ServiceResource]:
    """
    Spin up an in-memory DynamoDB table configured like the production
    `ledgerquest-engine-state` table except that *pay-per-request* mode can’t be
    emulated by moto (ignored).

    The fixture yields a boto3 Table resource so that calling tests can
    query/scan/update it directly.
    """
    table_name = f"ledgerquest-engine-state-{_random_suffix()}"

    with mock_dynamodb():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = resource.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Wait until the table exists. (Moto resolves instantly but keep code realistic.)
        table.wait_until_exists()
        yield table


@pytest.fixture
def s3_bucket(aws_credentials) -> Iterator[str]:
    """
    Create a temporary S3 bucket for asset or save-game storage tests.

    Yields the bucket name (string), not the resource.  Using the string keeps
    test signatures clean while still letting the consumer build a boto3
    resource/client when needed.
    """
    bucket_name = f"lq-test-{_random_suffix()}"

    with mock_s3():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": "us-east-1"})
        yield bucket_name


@pytest.fixture
def stepfunctions_state_machine(aws_credentials) -> Iterator[str]:
    """
    Provision an *empty* Step Functions state machine (the definition is
    irrelevant for most unit tests – its ARN is enough to satisfy the engine’s
    repository code).
    """
    definition = json.dumps(
        {
            "Comment": "Dummy LedgerQuest Engine Test State Machine",
            "StartAt": "End",
            "States": {"End": {"Type": "Succeed"}},
        }
    )

    with mock_stepfunctions():
        sfn = boto3.client("stepfunctions", region_name="us-east-1")
        response = sfn.create_state_machine(
            name=f"LedgerQuestTest-{_random_suffix()}",
            definition=definition,
            roleArn="arn:aws:iam::123456789012:role/DummyRole",
            type="STANDARD",
        )
        yield response["stateMachineArn"]


# --------------------------------------------------------------------------- #
# Pytest fixtures – Domain objects
# --------------------------------------------------------------------------- #

@pytest.fixture
def ecs_world():
    """
    Return a *real* (not mocked) minimal ECS world instance from the
    ``game_engine`` package so that component-level unit tests have a shared
    context.  Import lazily to avoid the dependency for test modules that don’t
    touch ECS.
    """
    from game_engine.ecs import World  # Lazy import inside fixture
    return World()  # noqa: WPS331 – simple factory is OK here


# --------------------------------------------------------------------------- #
# Assertion helpers
# --------------------------------------------------------------------------- #

def assert_dicts_almost_equal(
    got: Dict[str, Any],
    expected: Dict[str, Any],
    *,
    rel_tol: float = 1e-9,
    abs_tol: float = 0.0,
) -> None:
    """
    Assert that two dictionaries match, allowing for *floating-point* tolerance.

    Non-numeric values must match exactly.  Missing keys or diverging value
    types raise immediately with a verbose diff.
    """
    missing = expected.keys() ^ got.keys()
    if missing:
        pytest.fail(f"Keys mismatch: {missing}")

    for key, expected_value in expected.items():
        actual_value = got[key]

        if isinstance(expected_value, (int, float)) and isinstance(actual_value, (int, float)):
            if not pytest.approx(expected_value, rel=rel_tol, abs=abs_tol) == actual_value:
                pytest.fail(f"Numeric values differ for key '{key}': {actual_value} != {expected_value}")
        else:
            if actual_value != expected_value:
                pytest.fail(f"Values differ for key '{key}': {actual_value!r} != {expected_value!r}")


# --------------------------------------------------------------------------- #
# Internal helpers – file system, config parsing, etc.
# --------------------------------------------------------------------------- #

_TEST_DATA_DIR = pathlib.Path(__file__).with_suffix("").parent / "data"


@pytest.fixture(scope="session")
def sample_level_config() -> Dict[str, Any]:
    """
    Load and parse a canonical sample level configuration shipped under
    ``tests/unit/engine/data/``.  This file is referenced by many test cases
    across different features (AI, physics, scripting) to ensure behavioural
    consistency.
    """
    level_path = _TEST_DATA_DIR / "sample_level.json"

    if not level_path.exists():
        pytest.skip("Sample level configuration not present – skipping dependent tests")

    with level_path.open(encoding="utf-8") as fp:
        return json.load(fp)
```