```python
"""
LedgerQuestEngine.tests.fixtures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Fixtures that are shared across the LedgerQuest Engine test-suite.

The majority of the engine is deeply integrated with AWS’ serverless stack,
so spinning up local mocks is required for deterministic, side-effect-free
tests.  Pytest is used as the test-runner, while the excellent *moto* library
is leveraged for AWS service emulation.

Every fixture defined in this module is automatically discovered by pytest
because the file lives in a *tests/fixtures* package and exposes functions
decorated with :pyfunc:`pytest.fixture`.

Usage
=====

Simply add the fixture name as an argument to your test function, e.g. ::

    def test_session_persistence(mock_dynamodb_table, sample_game_manifest):
        ...
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import string
import textwrap
from contextlib import contextmanager
from typing import Any, Dict, Generator, Iterator, List, Mapping

import boto3
import pytest
import yaml
from botocore.client import BaseClient
from moto import (
    mock_dynamodb2,
    mock_eventbridge,
    mock_s3,
    mock_stepfunctions,
)

# --------------------------------------------------------------------------- #
# Utility helpers                                                             #
# --------------------------------------------------------------------------- #


def _random_suffix(length: int = 8) -> str:
    """
    Generate a random lower-case alpha string that can be appended to resource
    names to avoid collisions in parallel test runs.
    """
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _assets_dir() -> pathlib.Path:
    """
    Returns the absolute path to the local *tests/assets* directory.
    """
    # ``__file__`` points to LedgerQuestEngine/tests/fixtures/__init__.py
    return pathlib.Path(__file__).parent.parent / "assets"


@contextmanager
def _aws_credentials() -> Iterator[None]:
    """
    Context-manager that ensures dummy AWS credentials exist for moto to work
    without requiring real AWS keys in a developer’s environment.
    """
    # Only override if the developer hasn’t configured credentials.
    overrides = {
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_SECURITY_TOKEN": "test",
        "AWS_SESSION_TOKEN": "test",
    }
    old_environ: Dict[str, str] = {}
    try:
        for key, value in overrides.items():
            old_environ[key] = os.environ.get(key, "")  # keep original
            os.environ[key] = value
        yield
    finally:
        # Restore environment to previous state to avoid side-effects when
        # developers do *pytest* while they are also logged into AWS CLI.
        for key, original_value in old_environ.items():
            if original_value:
                os.environ[key] = original_value
            else:
                os.environ.pop(key, None)


# --------------------------------------------------------------------------- #
# Pytest fixtures                                                             #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def faker() -> "faker.Faker":  # type: ignore[name-defined]
    """
    Session-scoped *Faker* instance shared across tests to cheaply generate
    fake names, addresses, company data, etc.
    """
    # Lazy-import because *faker* pulls in locale data that is slow to load.
    from faker import Faker  # pylint: disable=import-error

    return Faker()


@pytest.fixture(scope="session")
def sample_game_manifest() -> Mapping[str, Any]:
    """
    Returns a dictionary representation of a minimal game manifest used in the
    majority of engine tests.

    The manifest is loaded once per test session for performance reasons and
    then reused by reference (it is considered immutable in test scenarios).
    """
    manifest_file = _assets_dir() / "sample_manifest.yml"
    if not manifest_file.exists():
        raise FileNotFoundError(
            f"Expected test asset at {manifest_file} but it does not exist."
        )

    with manifest_file.open("r", encoding="utf-8") as fp:
        try:
            return yaml.safe_load(fp)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"Unable to parse YAML sample manifest ({manifest_file})"
            ) from exc


# --------------------------------------------------------------------------- #
# AWS mocks                                                                   #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def aws_credentials() -> Iterator[None]:
    """
    Session-scoped fixture that ensures every test has fake credentials so that
    boto3 does not attempt to look up real profiles or hit the metadata
    service.
    """
    with _aws_credentials():
        yield


@pytest.fixture(scope="function")
def mock_s3_bucket(aws_credentials) -> Iterator[BaseClient]:
    """
    Function-scoped S3 bucket mock.

    The bucket is unique per test -> *ledgerquest-assets-<random>* to ensure
    there is no cross-test leakage.  The fixture yields a boto3 S3 client that
    is already pointed at the right region and bucket.
    """
    bucket_name = f"ledgerquest-assets-{_random_suffix()}"
    with mock_s3():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": "us-east-1"},
        )
        yield s3

        # moto tears down resources automatically on exit—no cleanup needed.


@pytest.fixture(scope="function")
def mock_dynamodb_table(aws_credentials) -> Iterator[BaseClient]:
    """
    Mocks the DynamoDB *GameSessions* table that LedgerQuest uses to store
    current player state.

    The schema is minimal and tailored for unit/integration testing only.
    """
    with mock_dynamodb2():
        dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        table_name = "GameSessions"

        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "session_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Seed with a dummy record so tests that simply *query* work out-of-box
        dynamodb.put_item(
            TableName=table_name,
            Item={
                "session_id": {"S": "demo-session-id"},
                "payload": {"S": json.dumps({"level": 1, "score": 0})},
            },
        )

        yield dynamodb


@pytest.fixture(scope="function")
def mock_eventbridge_bus(aws_credentials) -> Iterator[BaseClient]:
    """
    Fixture that spins up a mocked EventBridge bus used for asset update events
    in the engine.
    """
    with mock_eventbridge():
        eb = boto3.client("events", region_name="us-east-1")
        bus_name = f"ledgerquest-bus-{_random_suffix()}"
        eb.create_event_bus(Name=bus_name)
        yield eb


@pytest.fixture(scope="function")
def mock_step_function(aws_credentials) -> Iterator[BaseClient]:
    """
    Mocked AWS Step Functions client.

    While moto currently provides limited support for Step Functions, being
    able to *create_state_machine* and *start_execution* is more than enough
    for the engine’s unit tests.
    """
    with mock_stepfunctions():
        sfn = boto3.client("stepfunctions", region_name="us-east-1")
        yield sfn


# --------------------------------------------------------------------------- #
# Engine-specific helpers                                                     #
# --------------------------------------------------------------------------- #


class DummyWorld:
    """
    A *very* stripped-down ECS world that is “good enough” for testing pure
    systems that do not rely on the full engine runtime.

    It purposefully mimics just a subset of the public API exposed by the
    in-production world object so that tests remain somewhat realistic.
    """

    def __init__(self) -> None:
        self._entities: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def spawn(self, components: Mapping[str, Dict[str, Any]] | None = None) -> str:
        """
        Create a new entity.

        Parameters
        ----------
        components:
            Optional mapping of component names -> component data to attach
            immediately.

        Returns
        -------
        str
            The new entity’s unique identifier.
        """
        eid = _random_suffix(12)
        self._entities[eid] = {}
        if components:
            for comp_name, comp_data in components.items():
                self.add_component(eid, comp_name, comp_data)  # reuse method
        return eid

    def add_component(self, entity_id: str, name: str, data: Dict[str, Any]) -> None:
        """
        Add or overwrite a component for a given entity.
        """
        if entity_id not in self._entities:
            raise KeyError(f"Entity '{entity_id}' does not exist.")
        self._entities[entity_id][name] = data

    def remove_entity(self, entity_id: str) -> None:
        """
        Remove an entity and all of its components from the world.
        """
        try:
            del self._entities[entity_id]
        except KeyError as exc:
            raise KeyError(f"Cannot remove: entity '{entity_id}' missing.") from exc

    def query(self, component: str) -> Dict[str, Dict[str, Any]]:
        """
        Retrieve all entities that have a given component attached.
        """
        return {
            eid: comp[component]
            for eid, comp in self._entities.items()
            if component in comp
        }

    def to_json(self) -> str:
        """
        Serialise the entire world state to JSON, useful for snapshot testing.
        """
        return json.dumps(self._entities, indent=2, sort_keys=True)

    # --------------------------------------------------------------------- #
    # Debug/Dev helpers                                                     #
    # --------------------------------------------------------------------- #

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DummyWorld ({len(self._entities)} entities)>"

    def __iter__(self) -> Iterator[str]:
        """
        Allows iterating over the entity IDs directly, e.g. ::

            for eid in world:
                ...
        """
        return iter(self._entities)


@pytest.fixture(scope="function")
def dummy_world() -> DummyWorld:
    """
    Provides tests with an in-memory ECS world that behaves similarly to the
    production *ledgerquest.game_engine.world.World* but without any external
    dependencies or async scheduling primitives.
    """
    return DummyWorld()


# --------------------------------------------------------------------------- #
# Integration helpers                                                         #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="function")
def populated_dummy_world(
    dummy_world: DummyWorld, faker  # bring in previous fixtures
) -> DummyWorld:
    """
    A *DummyWorld* pre-populated with a few entities + components so that
    downstream tests do not have to repeat boilerplate setup code.
    """
    # Player entity
    dummy_world.spawn(
        {
            "Transform": {"x": 0, "y": 0, "z": 0},
            "Profile": {
                "player_name": faker.user_name(),
                "avatar_url": faker.image_url(),
            },
        }
    )

    # NPC entity
    dummy_world.spawn(
        {
            "Transform": {"x": 10, "y": 0, "z": 5},
            "AIState": {"behaviour": "idle"},
        }
    )

    # Prop entity
    dummy_world.spawn(
        {
            "Transform": {"x": -3, "y": 0, "z": 12},
            "Collider": {"radius": 1.25},
        }
    )

    return dummy_world


# --------------------------------------------------------------------------- #
# Quality-of-life fixtures                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="function")
def snapshot_json(request, tmp_path) -> Iterator[pathlib.Path]:
    """
    A tiny helper that writes the JSON serialisation of an object to a temp
    file to make *snapshot* style assertions pleasant.

    Usage
    -----
    ````python
    def test_world_serialisation(populated_dummy_world, snapshot_json):
        snapshot_path = snapshot_json(populated_dummy_world)
        assert snapshot_path.read_text() == expected_json
    ````
    """

    def _snapshot(obj: Any) -> pathlib.Path:
        file_name = f"{request.node.name}.json"
        file_path = tmp_path / file_name
        if hasattr(obj, "to_json"):
            payload = obj.to_json()
        else:
            payload = json.dumps(obj, indent=2, sort_keys=True)
        file_path.write_text(payload)
        return file_path

    # Yield the helper so the test can call *snapshot_json(obj)*
    yield _snapshot


# --------------------------------------------------------------------------- #
# End of fixtures module                                                      #
# --------------------------------------------------------------------------- #
```