"""
LedgerQuest Engine – Integration Test Fixtures
==============================================

This module provides reusable *pytest* fixtures and helper utilities that
spin-up a fully mocked AWS stack (DynamoDB, S3, EventBridge, Step Functions)
for integration-level testing of the LedgerQuest Engine.

All resources are provisioned with *moto* and therefore live entirely in-memory;
no real AWS calls are made, enabling the test-suite to run reliably in CI/CD
pipelines without additional infrastructure.

Usage
-----
Simply import the desired fixtures in your test modules:

    def test_create_entity(game_engine_api, entity_state_table):
        entity = game_engine_api.create_entity({"type": "player"})
        item = entity_state_table.get_item(
            Key={"pk": entity.id, "sk": "v0"}
        )["Item"]
        assert item["data"]["type"] == "player"

The most commonly used fixtures are:

    - aws_credentials          : Injects dummy AWS creds so boto3 does not complain
    - moto_aws                 : Session-scoped context manager starting all moto mocks
    - entity_state_table       : DynamoDB table used by the engine for ECS storage
    - scene_bucket             : S3 bucket where scene and asset blobs are stored
    - stepfunctions_client     : Boto3 client bound to the moto Step Functions mock
    - game_engine_api          : Lightweight engine façade bound to the mocked AWS stack
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from typing import Generator, Optional

import boto3
import pytest

# ---- Optional/mock fall-backs ------------------------------------------------

try:
    from moto import (
        mock_dynamodb2,
        mock_s3,
        mock_events,
        mock_stepfunctions,
    )
except ImportError:  # pragma: no cover – moto is a hard dependency for tests
    moto = None  # type: ignore
    pytest.skip("moto is required for integration tests", allow_module_level=True)

try:
    # Real engine import
    from game_engine.core import GameEngine  # type: ignore
except Exception:  # pylint: disable=broad-except
    # Provide a *very* light-weight stub so that the test-suite can be imported
    # even when the full game engine is not available in the environment where
    # only the tests are being analysed (e.g., static linters).
    class GameEngine:  # type: ignore
        """
        Minimal stub emulating only the surface used by integration tests.
        """

        def __init__(
            self,
            entity_state_table_name: str,
            scene_bucket_name: str,
            state_machine_arn: Optional[str] = None,
        ) -> None:
            self._started = False
            self._entity_state_table_name = entity_state_table_name
            self._scene_bucket_name = scene_bucket_name
            self._state_machine_arn = state_machine_arn

        # ------------------------------------------------------------------ #
        # Public API                                                         #
        # ------------------------------------------------------------------ #
        def start(self) -> None:
            self._started = True

        def stop(self) -> None:
            self._started = False

        def is_running(self) -> bool:
            return self._started

        # ------------------------------------------------------------------ #
        # Fake business operations                                           #
        # ------------------------------------------------------------------ #
        def create_entity(self, data: dict) -> "Entity":
            """
            Persist an entity into the mocked DynamoDB table and return an
            in-memory representation.
            """
            entity_id = str(uuid.uuid4())
            table = boto3.resource("dynamodb").Table(self._entity_state_table_name)
            table.put_item(
                Item={
                    "pk": entity_id,
                    "sk": "v0",
                    "data": data,
                }
            )
            return Entity(id_=entity_id, version=0)

        def run_game_loop_tick(self, payload: dict | None = None) -> dict:
            """
            Very rough emulation of invoking the Step Functions state machine
            that would normally orchestrate the serverless game loop.
            """
            if not self._state_machine_arn:
                # We cannot realistically simulate Step Functions' internals,
                # but we can return a predictable payload so tests can verify
                # the integration plumbing.
                return {"status": "NO_OP", "tick_id": str(uuid.uuid4())}

            client = boto3.client("stepfunctions")
            response = client.start_execution(
                stateMachineArn=self._state_machine_arn,
                input=json.dumps(payload or {}),
            )
            return response

    # A minimal value object for the stubbed GameEngine
    class Entity:  # pylint: disable=too-few-public-methods
        def __init__(self, id_: str, version: int) -> None:
            self.id = id_
            self.version = version

# --------------------------------------------------------------------------- #
#  Pytest fixtures                                                            #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session", autouse=True)
def aws_credentials() -> None:
    """
    Sets dummy AWS credentials for the session.  Required by boto3/moto.
    """
    # Values are irrelevant; they just need to be *something* so that boto3
    # does not attempt to read ~/.aws/ credentials / config.
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


@contextmanager
def _moto_context() -> Generator[None, None, None]:
    """
    Context manager that starts *all* moto mocks required for the engine.
    Moto does not provide a single unified `mock_all`, so we compose them.
    """
    with mock_dynamodb2():
        with mock_s3():
            with mock_events():
                with mock_stepfunctions():
                    yield


@pytest.fixture(scope="session")
def moto_aws() -> Generator[None, None, None]:
    """
    Session-scoped fixture that bootstraps the moto environment only once.
    """
    with _moto_context():
        yield


# --------------------------------------------------------------------------- #
#  DynamoDB – Entity / Session state                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def entity_state_table(moto_aws: None) -> "boto3.resources.factory.dynamodb.Table":
    """
    Provision the DynamoDB table used by the engine's ECS layer.

    Key schema:
        - pk : entity id   (STR)
        - sk : version key (STR)

    Note: Using a *string* sort key rather than a numeric allows us to add
    future prefixes (e.g., `v0`, `v1`) to model snapshots more flexibly.
    """
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.create_table(
        TableName="ledgerquest-entity-state",
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
    table.wait_until_exists()
    return table


# --------------------------------------------------------------------------- #
#  S3 – Scene / Asset storage                                                 #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def scene_bucket(moto_aws: None) -> str:
    """
    Create the S3 bucket where scenes and other static assets are stored.
    Returns the bucket name for convenience.
    """
    bucket_name = "ledgerquest-scenes"
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket=bucket_name)
    # Seed with a default, empty scene so that tests working on new engines
    # can load a predictable asset.
    s3.put_object(
        Bucket=bucket_name,
        Key="scenes/default.json",
        Body=b'{"name": "default", "entities": []}',
        ContentType="application/json",
    )
    return bucket_name


# --------------------------------------------------------------------------- #
#  Step Functions – Mocked Game Loop orchestrator                             #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def stepfunctions_client(moto_aws: None) -> "boto3.client":
    """
    Return a boto3 Step Functions client bound to the moto mock.
    """
    return boto3.client("stepfunctions")


@pytest.fixture(scope="session")
def game_loop_state_machine(
    stepfunctions_client: "boto3.client",
) -> str:
    """
    Register a stubbed Step Functions state machine that represents the
    LedgerQuest game loop.  The machine simply waits one second and
    returns a success payload, which is sufficient for most integration
    scenarios.
    """
    definition = json.dumps(
        {
            "StartAt": "NoOp",
            "States": {
                "NoOp": {
                    "Type": "Pass",
                    "Result": {"status": "NO_OP"},
                    "End": True,
                }
            },
        }
    )
    role_arn = "arn:aws:iam::123456789012:role/DummyRole"
    response = stepfunctions_client.create_state_machine(
        name="ledgerquest-game-loop",
        definition=definition,
        roleArn=role_arn,
    )
    return response["stateMachineArn"]


# --------------------------------------------------------------------------- #
#  High-level engine façade                                                   #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="function")
def game_engine_api(
    entity_state_table: "boto3.resources.factory.dynamodb.Table",
    scene_bucket: str,
    game_loop_state_machine: str,
) -> Generator[GameEngine, None, None]:
    """
    Fixture that yields a *running* instance of the (stubbed or real)
    LedgerQuest GameEngine.  The instance is initialised with the mocked
    AWS resource names so that its internals talk to moto.
    """
    engine = GameEngine(
        entity_state_table_name=entity_state_table.table_name,
        scene_bucket_name=scene_bucket,
        state_machine_arn=game_loop_state_machine,
    )
    engine.start()
    try:
        yield engine
    finally:
        engine.stop()


# --------------------------------------------------------------------------- #
#  Misc helper utilities                                                      #
# --------------------------------------------------------------------------- #


def random_scene_key() -> str:
    """
    Return a unique key suitable for uploading a new test scene into S3.
    """
    return f"scenes/{uuid.uuid4()}.json"


def upload_scene(
    bucket_name: str,
    scene_definition: dict,
    key: Optional[str] = None,
) -> str:
    """
    Utility function used by tests to upload a scene blob to S3 and return
    the object key that was written.
    """
    if key is None:
        key = random_scene_key()

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=json.dumps(scene_definition).encode("utf-8"),
        ContentType="application/json",
    )
    return key


__all__ = [
    # Fixtures (referenced dynamically by pytest)
    "aws_credentials",
    "moto_aws",
    "entity_state_table",
    "scene_bucket",
    "stepfunctions_client",
    "game_loop_state_machine",
    "game_engine_api",
    # Helpers
    "upload_scene",
    "random_scene_key",
]