```python
"""
LedgerQuest Engine – Unit-Test Bootstrap Package
================================================

This module is imported automatically by *pytest* because it sits inside the
`tests/unit` package and contains a number of *session-wide* fixtures and
utilities that are reused by all unit tests.

The goals of this bootstrap are:

1. Provide hermetic AWS mocks (via `moto`) so we never reach the real cloud.
2. Normalise environment variables so Lambda-style handlers behave the same
   inside and outside CI.
3. Offer small helper APIs—e.g., `load_asset`, `capture_invocations`—that cut
   down on boiler-plate inside individual test modules.
4. Fail fast if any test leaks resources (open files, background threads, etc.).

Because this file is imported before any tests run, keep imports light-weight
and defer heavier libraries (e.g., NumPy, PyGame) to individual test modules.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import pathlib
import queue
import threading
import time
from typing import Any, Callable, Dict, Generator, Iterable, List, Tuple

import boto3
import pytest
from _pytest.monkeypatch import MonkeyPatch
from botocore.exceptions import ClientError
from moto import (
    mock_dynamodb,
    mock_s3,
    mock_sfn,
)

__all__: List[str] = [
    # Public pytest fixtures
    "aws_env",
    "dynamodb_table",
    "s3_bucket",
    "step_functions_client",
    "iso_timestamp",
    "load_asset",
    "capture_invocations",
]

# ------------------------------------------------------------------------------
# Logging configuration
# ------------------------------------------------------------------------------

# Emit DEBUG logs during tests so we can assert on log output if needed.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
)

_LOG = logging.getLogger("ledgerquest.tests.bootstrap")

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------

# Where sample JSON assets used by tests live (relative to repository root).
_ASSET_ROOT = pathlib.Path(__file__).resolve().parents[1] / "fixtures"

# Fake AWS account/region used by moto.
_FAKE_AWS_REGION = "us-east-1"
_FAKE_AWS_ACCOUNT_ID = "123456789012"

# ------------------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------------------


def _fake_arn(service: str, resource_id: str) -> str:
    """Return a deterministic fake AWS ARN for use in assertions."""
    return f"arn:aws:{service}:{_FAKE_AWS_REGION}:{_FAKE_AWS_ACCOUNT_ID}:{resource_id}"


def iso_timestamp(offset_seconds: int = 0) -> str:
    """
    Return an ISO-8601 timestamp suitable for DynamoDB/S3 keys.

    Parameters
    ----------
    offset_seconds:
        Optional offset applied to *now*. Useful for creating
        before/after ordering scenarios in tests.
    """
    return time.strftime(
        "%Y-%m-%dT%H:%M:%S",
        time.gmtime(time.time() + offset_seconds),
    )


def load_asset(name: str) -> Dict[str, Any]:
    """
    Load a JSON test asset from `tests/fixtures/<name>.json`.

    Raises if the file cannot be found or parsed.
    """
    path = _ASSET_ROOT / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Test asset not found: {path}")
    _LOG.debug("Loading asset %s", path)
    return json.loads(path.read_text(encoding="utf-8"))


class InvocationRecorder:
    """
    Thread-safe collector used to capture function calls during a test.

    Example
    -------
    >>> recorder = InvocationRecorder()
    >>> @recorder
    ... def foo(x): return x * 2
    >>> foo(5)
    10
    >>> recorder.invocations  # doctest: +ELLIPSIS
    [(('x', 5), ...)]
    """

    def __init__(self) -> None:
        self._queue: "queue.Queue[Tuple[Tuple[Any, ...], Dict[str, Any]]]" = (
            queue.Queue()
        )

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator that records each invocation of *func*."""

        def wrapper(*args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
            _LOG.debug("Captured invocation: %s args=%s kwargs=%s", func, args, kwargs)
            self._queue.put((args, kwargs))
            return func(*args, **kwargs)

        wrapper.__signature__ = inspect.signature(func)  # type: ignore[attr-defined]
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    # ------------------------------------------------------------------ public

    @property
    def invocations(self) -> List[Tuple[Tuple[Any, ...], Dict[str, Any]]]:
        """Return a *snapshot* of all recorded invocations."""
        items: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items


# ------------------------------------------------------------------------------
# Pytest fixtures
# ------------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def aws_env(monkeysession: MonkeyPatch) -> None:  # type: ignore[name-defined]
    """
    Establish fake AWS credentials/region for moto.

    The fixture is applied *automatically* (autouse=True) for the entire test
    session, guaranteeing no test ever touches real AWS resources.
    """
    monkeysession.setenv("AWS_ACCESS_KEY_ID", "fake")
    monkeysession.setenv("AWS_SECRET_ACCESS_KEY", "fake")
    monkeysession.setenv("AWS_SECURITY_TOKEN", "fake")
    monkeysession.setenv("AWS_SESSION_TOKEN", "fake")
    monkeysession.setenv("AWS_DEFAULT_REGION", _FAKE_AWS_REGION)
    _LOG.info("Set fake AWS env")


@pytest.fixture(scope="function")
def dynamodb_table(aws_env: None) -> Generator[Any, None, None]:
    """
    Spin up a moto-mocked DynamoDB table and yield the *boto3* resource object.

    The table schema mirrors the one used by the production engine:
    *PK* (HASH)  – composite of tenant+entity
    *SK* (RANGE) – ISO timestamp or sub-entity identifier
    """
    with mock_dynamodb():
        dynamodb = boto3.resource("dynamodb", region_name=_FAKE_AWS_REGION)
        table = dynamodb.create_table(
            TableName="ledgerquest-unit-tests",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        # Wait until the table exists.
        table.meta.client.get_waiter("table_exists").wait(TableName=table.name)
        _LOG.debug("Created mock DynamoDB table %s", table.name)
        yield table


@pytest.fixture(scope="function")
def s3_bucket(aws_env: None) -> Generator[Any, None, None]:
    """
    Provide a moto-mocked S3 bucket pre-created for convenience.
    """
    with mock_s3():
        s3 = boto3.resource("s3", region_name=_FAKE_AWS_REGION)
        bucket = s3.Bucket("ledgerquest-unit-tests")
        bucket.create(
            CreateBucketConfiguration={"LocationConstraint": _FAKE_AWS_REGION}
        )
        _LOG.debug("Created mock S3 bucket %s", bucket.name)
        yield bucket


@pytest.fixture(scope="function")
def step_functions_client(aws_env: None) -> Generator[Any, None, None]:
    """
    Provide a moto-mocked Step Functions client.
    """
    with mock_sfn():
        client = boto3.client("stepfunctions", region_name=_FAKE_AWS_REGION)
        yield client


@pytest.fixture()
def capture_invocations() -> InvocationRecorder:
    """
    Return an :pyclass:`InvocationRecorder` that can be used to assert on
    side-effecting function invocations.

    Example
    -------
    >>> def do_work(cb): ...
    >>> recorder = capture_invocations
    >>> do_work(recorder(some_callback))
    >>> assert recorder.invocations  # ensure callback executed
    """
    return InvocationRecorder()


# ------------------------------------------------------------------------------
# Sanity checks – Fail fast if mocks leak resources
# ------------------------------------------------------------------------------


@pytest.hookimpl(trylast=True)  # noqa: D401
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """
    After the whole test suite finishes, ensure moto has not left any threads
    hanging around which would otherwise cause stochastic failures on CI
    runners due to resource leakage.
    """
    live_threads: List[threading.Thread] = [
        t for t in threading.enumerate() if t is not threading.main_thread()
    ]
    # Exclude threads started by pytest itself (e.g., --numprocesses).
    offenders: List[threading.Thread] = [
        t for t in live_threads if "moto" in t.name.lower()
    ]
    if offenders:
        _LOG.error("Dangling threads detected: %s", offenders)
        session.exitstatus = 1  # override overall status to FAILURE

    _LOG.info("Pytest session completed with status %s", exitstatus)
```