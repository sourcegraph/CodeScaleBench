```python
"""
crowdpay_connect/services/kyc_service/tests/test_verification_flow.py

End-to-end tests for the KYC verification component.  The tests focus on the
public behaviour of `KYCService.verify_user`, asserting that:

1.  A successful verification request:
        * persists a verified KYC record,
        * publishes a `UserVerificationSucceeded` event, and
        * returns the proper `VerificationResult` to the caller.

2.  A rejected verification request:
        * persists a rejected KYC record,
        * publishes a `UserVerificationFailed` event with the appropriate
          payload, and
        * surfaces a `VerificationResult` in the rejected state.

3.  The verification endpoint is idempotent when the same user attempts to
    verify twice with identical documents.

External dependencies (3rd-party KYC provider, event bus, persistence layer)
are replaced with in-memory fakes that record all interactions, allowing the
test-suite to make strong behavioural assertions without I/O.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass
from typing import List

import pytest
from pytest import MonkeyPatch

from crowdpay_connect.events import (
    BaseEvent,
    UserVerificationFailed,
    UserVerificationSucceeded,
)
from crowdpay_connect.services.kyc_service.enums import VerificationStatus
from crowdpay_connect.services.kyc_service.kyc_service import (
    DocumentPayload,
    KYCService,
    VerificationResult,
)
from crowdpay_connect.services.kyc_service.models import UserKYCRecord


# --------------------------------------------------------------------------- #
#                                Fake Fixtures                                #
# --------------------------------------------------------------------------- #
class FakeKYCProvider:
    """
    A trivial in-memory stub that pretends to be a 3rd-party KYC provider.
    The fake is deterministic, returning pre-configured results keyed by the
    SHA-256 hash of the submitted document bundle.
    """

    def __init__(self) -> None:
        self._responses: dict[str, VerificationResult] = {}
        self.calls: List[dict] = []

    # --------------------------------------------------------------------- #
    #                               API Surface                             #
    # --------------------------------------------------------------------- #
    def add_document_response(self, doc_hash: str, result: VerificationResult) -> None:
        """
        Pre-load the provider with a deterministic response.  Any document
        hash not explicitly registered will yield a `rejected` result.
        """
        self._responses[doc_hash] = result

    def verify(self, user_id: uuid.UUID, documents: List[DocumentPayload]) -> VerificationResult:
        """
        Emulates the synchronous verification endpoint that the production
        service would call over HTTP/REST or gRPC.  The fake is pure and
        side-effect free beyond recording input arguments.
        """
        self.calls.append({"user_id": user_id, "documents": documents})

        # Hash file names and sizes to produce a synthetic "content" hash.
        doc_hash = _stable_document_hash(documents)
        return self._responses.get(
            doc_hash,
            VerificationResult(
                status=VerificationStatus.REJECTED,
                provider_reference=f"fake-provider::reject::{uuid.uuid4()}",
                reason="document mismatch",
            ),
        )


class FakeEventBus:
    """
    Records all published domain events in a simple list so that the tests can
    make assertions on ordering and payload correctness.
    """

    def __init__(self) -> None:
        self.events: List[BaseEvent] = []

    def publish(self, event: BaseEvent) -> None:
        self.events.append(event)


class FakeUnitOfWork:
    """
    Minimal transactional wrapper around an in-memory set of `UserKYCRecord`s.
    """

    def __init__(self) -> None:
        self.records: dict[uuid.UUID, UserKYCRecord] = {}
        self.committed: bool = False

    # --------------------------------------------------------------------- #
    #                               API Surface                             #
    # --------------------------------------------------------------------- #
    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Any exception bubbles up; we only mark committed if all is well.
        if exc is None:
            self.committed = True

    # Domain-specific helpers
    def get_record(self, user_id: uuid.UUID) -> UserKYCRecord | None:
        return self.records.get(user_id)

    def save_record(self, record: UserKYCRecord) -> None:
        self.records[record.user_id] = record


# --------------------------------------------------------------------------- #
#                               Test Fixtures                                 #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="function")
def fake_provider() -> FakeKYCProvider:
    return FakeKYCProvider()


@pytest.fixture(scope="function")
def fake_event_bus() -> FakeEventBus:
    return FakeEventBus()


@pytest.fixture(scope="function")
def fake_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture(scope="function")
def kyc_service(fake_provider: FakeKYCProvider, fake_event_bus: FakeEventBus) -> KYCService:
    """
    Instantiate the service under test, wiring the fake provider *and*
    the fake event bus via constructor injection.  The production `KYCService`
    expects an abstract provider adapter and an event bus; our fakes conform
    to the required interfaces, so no further wrapping is needed.
    """
    return KYCService(provider=fake_provider, event_bus=fake_event_bus)


# --------------------------------------------------------------------------- #
#                               Helper Utils                                  #
# --------------------------------------------------------------------------- #
def _stable_document_hash(documents: List[DocumentPayload]) -> str:
    """
    Produces a deterministic hash solely from filenames and sizes so that the
    tests do not need to ship binary assets while still enjoying deterministic
    behaviour.
    """
    canonical = "|".join(sorted(f"{doc.filename}:{doc.byte_length}" for doc in documents))
    # Use UUID5 for deterministic hashing with a private namespace.
    return str(uuid.uuid5(uuid.NAMESPACE_OID, canonical))


def _make_document(name: str, size: int) -> DocumentPayload:
    """
    Shortcut factory because tests create many `DocumentPayload`s.
    """
    return DocumentPayload(filename=name, content=b"x" * size, mime_type="image/png")


# --------------------------------------------------------------------------- #
#                               Test Cases                                    #
# --------------------------------------------------------------------------- #
def test_successful_verification_flow(
    kyc_service: KYCService,
    fake_provider: FakeKYCProvider,
    fake_event_bus: FakeEventBus,
    fake_uow: FakeUnitOfWork,
) -> None:
    """
    GIVEN  a KYCService instance with a fake provider
    WHEN   verify_user is called with documents that the provider will approve
    THEN   the service should
           * return a successful VerificationResult
           * store a verified record in the Unit-of-Work
           * publish a UserVerificationSucceeded event
    """
    user_id = uuid.uuid4()
    documents = [_make_document("passport.png", 1234), _make_document("selfie.png", 2345)]

    expected_result = VerificationResult(
        status=VerificationStatus.VERIFIED,
        provider_reference="fake-provider::1234",
        reason=None,
    )

    # Tell the fake provider to approve this document bundle.
    doc_hash = _stable_document_hash(documents)
    fake_provider.add_document_response(doc_hash, expected_result)

    # Act
    result = kyc_service.verify_user(user_id=user_id, documents=documents, uow=fake_uow)

    # Assert result
    assert result == expected_result

    # Assert UnitOfWork persisted the record
    record = fake_uow.get_record(user_id)
    assert record is not None
    assert record.status == VerificationStatus.VERIFIED
    assert record.provider_reference == expected_result.provider_reference
    assert fake_uow.committed is True

    # Assert event bus
    assert len(fake_event_bus.events) == 1
    event = fake_event_bus.events[0]
    assert isinstance(event, UserVerificationSucceeded)
    assert event.user_id == user_id
    assert event.provider_reference == expected_result.provider_reference


def test_rejected_verification_flow(
    kyc_service: KYCService,
    fake_provider: FakeKYCProvider,
    fake_event_bus: FakeEventBus,
    fake_uow: FakeUnitOfWork,
) -> None:
    """
    GIVEN  documents not recognised by the provider
    WHEN   verify_user is called
    THEN   the service should return a rejected VerificationResult,
           persist the rejected state, and emit the correct domain event.
    """
    user_id = uuid.uuid4()
    documents = [_make_document("shady_passport.png", 666)]

    # No provider response registered → default branch returns REJECTED
    result = kyc_service.verify_user(user_id, documents, uow=fake_uow)

    # Result surface
    assert result.status == VerificationStatus.REJECTED
    assert "document mismatch" in result.reason.lower()

    # State persisted
    record = fake_uow.get_record(user_id)
    assert record.status == VerificationStatus.REJECTED
    assert fake_uow.committed

    # Event emitted
    assert len(fake_event_bus.events) == 1
    event = fake_event_bus.events[0]
    assert isinstance(event, UserVerificationFailed)
    assert event.user_id == user_id
    assert event.reason == result.reason


@pytest.mark.parametrize("repeat_count", [2, 3])
def test_idempotent_verifications(
    repeat_count: int,
    kyc_service: KYCService,
    fake_provider: FakeKYCProvider,
    fake_event_bus: FakeEventBus,
    fake_uow: FakeUnitOfWork,
) -> None:
    """
    KYC verification requests must be idempotent.  Calling the same input
    multiple times must not
       * create duplicate provider calls,
       * create multiple `UserKYCRecord`s, or
       * publish more than one event.
    """
    user_id = uuid.uuid4()
    documents = [_make_document("passport.png", 1024)]

    expected_result = VerificationResult(
        status=VerificationStatus.VERIFIED,
        provider_reference="fake-provider::unique-ref",
        reason=None,
    )

    doc_hash = _stable_document_hash(documents)
    fake_provider.add_document_response(doc_hash, expected_result)

    for _ in range(repeat_count):
        # Each call receives its own UoW for isolation
        uow = FakeUnitOfWork()
        result = kyc_service.verify_user(user_id, documents, uow=uow)
        assert result == expected_result
        assert uow.committed

    # Provider should only be called once due to internal deduplication
    assert len(fake_provider.calls) == 1

    # Only one event should have been emitted
    assert len(fake_event_bus.events) == 1
    assert isinstance(fake_event_bus.events[0], UserVerificationSucceeded)
```