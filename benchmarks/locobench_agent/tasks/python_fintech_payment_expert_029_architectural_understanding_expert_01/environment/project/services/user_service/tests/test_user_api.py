```python
"""
Integration-style tests for the User Service public HTTP API.

These tests spin up the real FastAPI application (but with selected
dependencies monkey-patched) and exercise the most important scenarios
around the User domain:

    • On-boarding / sign-up
    • Data retrieval & updates
    • KYC workflow bootstrap
    • Contract validation / error handling

The tests purposefully avoid touching the real persistence layer
or third-party integrations by replacing them with in-memory fakes.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional

import pytest
from faker import Faker
from fastapi import status
from httpx import AsyncClient

# Application entry-point (creates FastAPI instance with all routes/DI wired)
from crowdpay_connect.services.user_service.main import create_app
from crowdpay_connect.services.user_service.schemas import (
    KYCRequest,
    UserCreate,
    UserOut,
    UserUpdate,
)
from crowdpay_connect.services.user_service.repositories.user_repository import (
    UserRepository,
)
from crowdpay_connect.services.user_service.clients.kyc_client import KYCClient

###############################################################################
#                               Pytest fixtures                               #
###############################################################################


@pytest.fixture(scope="session")
def faker() -> Faker:
    """Return a shared Faker generator instance."""
    return Faker("en_US")


@pytest.fixture(scope="session")
def anyio_backend() -> str:  # let pytest-asyncio use asyncio
    return "asyncio"


@pytest.fixture()
async def http_client():
    """
    Provide a running FastAPI test-client with the application boot-strapped.
    """
    app = create_app()

    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture()
def fake_user_repo(monkeypatch: pytest.MonkeyPatch, faker: Faker) -> UserRepository:
    """
    Inject an in-memory stand-in for `UserRepository`. Everything is stored
    in a local dict and removed when the fixture goes out of scope.
    """

    class _InMemUserRepo(UserRepository):  # type: ignore[misc]
        _db: Dict[str, UserOut] = {}

        async def get_by_email(self, email: str) -> Optional[UserOut]:
            return next((u for u in self._db.values() if u.email == email), None)

        async def get_by_id(self, user_id: str) -> Optional[UserOut]:
            return self._db.get(user_id)

        async def create_user(self, payload: UserCreate) -> UserOut:
            # Enforce uniqueness similar to a real DB
            if await self.get_by_email(payload.email):
                raise ValueError("duplicate email")

            new_user = UserOut(
                id=str(uuid.uuid4()),
                email=payload.email,
                first_name=payload.first_name,
                last_name=payload.last_name,
                country_code=payload.country_code,
                is_kyc_verified=False,
            )
            self._db[new_user.id] = new_user
            return new_user

        async def update_user(self, user_id: str, payload: UserUpdate) -> UserOut:
            if user_id not in self._db:
                raise KeyError(user_id)
            updated = self._db[user_id].copy(update=payload.dict(exclude_unset=True))
            self._db[user_id] = updated
            return updated

    repo_instance = _InMemUserRepo()

    # Monkey-patch the factory used by the application’s dependency-injection
    monkeypatch.setattr(
        "crowdpay_connect.services.user_service.dependencies.get_user_repo",
        lambda: repo_instance,
    )
    return repo_instance


@pytest.fixture()
def fake_kyc_client(monkeypatch: pytest.MonkeyPatch):
    """Swap-in a fake KYC client that responds instantly."""

    class _FakeKYCClient(KYCClient):  # type: ignore[misc]
        async def submit_application(self, user_id: str, req: KYCRequest) -> str:
            # Immediately approve for test purposes
            return "APPROVED"

    monkeypatch.setattr(
        "crowdpay_connect.services.user_service.dependencies.get_kyc_client",
        lambda: _FakeKYCClient(),
    )
    return _FakeKYCClient()


###############################################################################
#                                   Test-cases                                #
###############################################################################


@pytest.mark.anyio
async def test_user_signup_happy_path(
    http_client: AsyncClient, fake_user_repo: UserRepository, faker: Faker
):
    """
    GIVEN valid registration data
    WHEN  the /v1/users endpoint is called
    THEN  the service returns 201 with the newly created user record
    """
    payload = {
        "email": faker.unique.email(),
        "first_name": faker.first_name(),
        "last_name": faker.last_name(),
        "country_code": "US",
    }

    response = await http_client.post("/v1/users", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    body = response.json()
    assert body["email"] == payload["email"]
    assert body["country_code"] == "US"
    assert uuid.UUID(body["id"])  # valid UUID?

    # Verify that it actually hit our repo
    assert await fake_user_repo.get_by_id(body["id"]) is not None


@pytest.mark.anyio
async def test_user_signup_duplicate_email_returns_409(
    http_client: AsyncClient, faker: Faker
):
    """
    Attempting to create the same user twice must fail with 409 Conflict.
    """
    first_payload = {
        "email": faker.unique.email(),
        "first_name": faker.first_name(),
        "last_name": faker.last_name(),
        "country_code": "GB",
    }

    # First attempt succeeds
    assert (await http_client.post("/v1/users", json=first_payload)).status_code == 201

    # Second attempt with identical email → 409
    second_payload = {
        **first_payload,
        "first_name": "Changed",
    }
    dup_resp = await http_client.post("/v1/users", json=second_payload)
    assert dup_resp.status_code == status.HTTP_409_CONFLICT
    assert dup_resp.json()["detail"] == "email_already_exists"


@pytest.mark.anyio
async def test_get_user_by_id(
    http_client: AsyncClient, fake_user_repo: UserRepository, faker: Faker
):
    """
    The GET endpoint should retrieve previously created users.
    """
    # Arrange: manually insert a user into fake repo
    new_user = await fake_user_repo.create_user(
        UserCreate(
            email=faker.unique.email(),
            first_name=faker.first_name(),
            last_name=faker.last_name(),
            country_code="DE",
        )
    )

    # Act
    resp = await http_client.get(f"/v1/users/{new_user.id}")
    assert resp.status_code == 200
    assert resp.json()["email"] == new_user.email


@pytest.mark.anyio
async def test_patch_user_profile(
    http_client: AsyncClient, fake_user_repo: UserRepository, faker: Faker
):
    """
    Users should be able to modify non-critical profile attributes.
    """
    # Arrange
    existing = await fake_user_repo.create_user(
        UserCreate(
            email=faker.unique.email(),
            first_name="Alice",
            last_name="Tester",
            country_code="FR",
        )
    )
    # Act
    patch_payload = {"first_name": "Alicia"}
    resp = await http_client.patch(f"/v1/users/{existing.id}", json=patch_payload)

    # Assert
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Alicia"
    assert (await fake_user_repo.get_by_id(existing.id)).first_name == "Alicia"


@pytest.mark.anyio
async def test_kyc_bootstrap_returns_202_and_emits_event(
    http_client: AsyncClient,
    fake_user_repo: UserRepository,
    fake_kyc_client: KYCClient,
    faker: Faker,
):
    """
    Starting the KYC process should:
        • Return 202 Accepted
        • Set the 'is_kyc_verified' flag once the fake KYC immediately approves
    """
    # Arrange
    user = await fake_user_repo.create_user(
        UserCreate(
            email=faker.unique.email(),
            first_name=faker.first_name(),
            last_name=faker.last_name(),
            country_code="CA",
        )
    )

    # Act
    kyc_req = {"document_type": "PASSPORT", "document_number": "X12345"}
    resp = await http_client.post(f"/v1/users/{user.id}/kyc", json=kyc_req)

    # Assert response contract
    assert resp.status_code == status.HTTP_202_ACCEPTED
    body = resp.json()
    assert body["status"] == "APPROVED"

    # Assert repository state has been updated by domain event handler
    updated = await fake_user_repo.get_by_id(user.id)
    assert updated.is_kyc_verified is True


@pytest.mark.anyio
async def test_payload_validation_error_returns_422(http_client: AsyncClient):
    """
    Missing mandatory field → 422 Unprocessable Entity with detail.
    """
    bad_payload = {"email": "invalid@example.com"}  # missing first/last name
    resp = await http_client.post("/v1/users", json=bad_payload)

    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    err_fields = {err["loc"][-1] for err in resp.json()["detail"]}
    assert {"first_name", "last_name", "country_code"}.issubset(err_fields)
```
