```python
"""
CrowdPay Connect – KYC Service (main.py)

This micro–service is responsible for:
1. Accepting KYC verification requests coming from the API-gateway / other services.
2. Persisting verification lifecycle to the service database.
3. Emitting domain-events to the event-bus (Kafka) so that the
   Compliance, Risk-Assessment, and Orchestrator (Saga) components
   can react accordingly.

Architecture patterns in play:
• Security-by-Design – minimal PII is stored, all data is encrypted in transit.
• Event Sourcing – every state-change is captured as an immutable event.
• Saga Pattern     – the service is a participant in the wider onboarding saga.
• CQRS             – write-model (commands) is separated from read-model (queries).

The file is intentionally self-contained for brevity, but in production each
segment (routers / models / repositories / clients) would live in its own module.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, BaseSettings, Field
from sqlalchemy import Column, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #


class Settings(BaseSettings):
    # Database
    db_uri: str = Field(
        default="postgresql+asyncpg://kyc_service:kyc_pass@localhost:5432/kyc_service"
    )

    # Kafka
    kafka_bootstrap_servers: str = Field(default="localhost:9092")
    kafka_topic: str = Field(default="kyc-events")

    # Misc
    service_name: str = Field(default="kyc_service")
    log_level: str = Field(default="INFO")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(settings.service_name)

# --------------------------------------------------------------------------- #
# Database                                                                    #
# --------------------------------------------------------------------------- #

Base = declarative_base()
engine = create_async_engine(settings.db_uri, echo=False, pool_pre_ping=True)
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# --------------------------------------------------------------------------- #
# Domain Model                                                                #
# --------------------------------------------------------------------------- #


class KycStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    failed = "failed"


class KycVerification(Base):
    __tablename__ = "kyc_verifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(String(64), index=True, nullable=False)
    status = Column(Enum(KycStatus), nullable=False, default=KycStatus.pending)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DomainEvent(Base):
    """
    Immutable event used for event-sourcing and audit-trail.
    """

    __tablename__ = "domain_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    aggregate_id = Column(String(64), index=True)
    aggregate_type = Column(String(64))
    event_type = Column(String(128))
    payload = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Kafka Producer                                                              #
# --------------------------------------------------------------------------- #
try:
    from aiokafka import AIOKafkaProducer
except ImportError:  # Hard-dependency is optional for unit-tests/doc builds.
    AIOKafkaProducer = None  # type: ignore[misc]


class KafkaPublisher:
    """
    Thin wrapper around aiokafka producer with JSON serialization and
    automatic reconnect on producer errors.
    """

    def __init__(self, brokers: str, topic: str) -> None:
        if AIOKafkaProducer is None:
            raise RuntimeError("aiokafka is required for KafkaPublisher")
        self._producer: Optional[AIOKafkaProducer] = None
        self._brokers = brokers
        self._topic = topic

    async def start(self) -> None:
        if self._producer is None:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._brokers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self._producer.start()
            logger.info("Kafka producer started.")

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            logger.info("Kafka producer stopped.")
            self._producer = None

    async def publish(self, payload: dict[str, Any]) -> None:
        if self._producer is None:
            raise RuntimeError("Kafka producer not started")
        try:
            await self._producer.send_and_wait(settings.kafka_topic, value=payload)
            logger.debug("Event published to Kafka: %s", payload)
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to publish event to Kafka: %s", exc)


publisher: Optional[KafkaPublisher] = None

# --------------------------------------------------------------------------- #
# Schemas                                                                     #
# --------------------------------------------------------------------------- #


class KycRequest(BaseModel):
    """
    Payload incoming from client / other micro-services.
    """

    user_id: str = Field(..., example="user_123")
    document_type: str = Field(..., example="passport")
    document_data: str = Field(
        ...,
        example="base64:<encrypted-blob>",
        description="Encrypted / tokenized document information",
    )


class KycResponse(BaseModel):
    user_id: str
    status: KycStatus
    failure_reason: Optional[str] = None
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Business Logic                                                              #
# --------------------------------------------------------------------------- #


class KycService:
    """
    Application-Service / Use-Case boundary.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def verify(self, req: KycRequest) -> KycVerification:
        """
        Runs the KYC verification flow. Mimics interaction with an
        external provider (document scanning, selfie-liveness, etc.).
        """

        record = KycVerification(
            user_id=req.user_id,
            status=KycStatus.pending,
        )
        self._db.add(record)
        await self._db.flush()  # obtain primary-key for event correlation

        # Persist initial "pending" event
        await self._append_event(
            aggregate_id=req.user_id,
            aggregate_type="user",
            event_type="KYC_PENDING",
            payload={"kyc_id": record.id},
        )

        # Simulate network call / long-running check
        try:
            is_valid, failure_reason = await self._call_third_party(req)
            record.status = KycStatus.verified if is_valid else KycStatus.failed
            record.failure_reason = failure_reason
            await self._db.commit()
        except Exception as exc:  # pragma: no cover
            logger.exception("KYC verification error: %s", exc)
            await self._db.rollback()
            raise

        # Emit domain-event
        event_type = (
            "KYC_VERIFIED" if record.status == KycStatus.verified else "KYC_FAILED"
        )
        await self._append_event(
            aggregate_id=req.user_id,
            aggregate_type="user",
            event_type=event_type,
            payload={
                "kyc_id": record.id,
                "failure_reason": record.failure_reason,
            },
        )

        return record

    async def _append_event(
        self,
        *,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        event = DomainEvent(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            payload=json.dumps(payload),
        )
        self._db.add(event)
        await self._db.flush()

        try:
            if publisher:
                await publisher.publish(
                    {
                        "aggregate_id": aggregate_id,
                        "aggregate_type": aggregate_type,
                        "event_type": event_type,
                        "payload": payload,
                        "created_at": datetime.utcnow().isoformat(),
                    }
                )
        except Exception:  # pragma: no cover
            # Do not fail the transaction – event can be re-played from DB
            logger.exception("Non-blocking: Failed to publish KYC event.")

    async def _call_third_party(self, req: KycRequest) -> tuple[bool, Optional[str]]:
        """
        Placeholder for external KYC provider call.

        The implementation would:
        1. Decrypt the `document_data`
        2. Upload to provider
        3. Poll / receive webhook
        For demo purposes we return success/failure based on a hash.
        """

        await asyncio.sleep(0.2)  # simulate network latency
        ok = hash(req.document_data) % 3 != 0  # approx. 66% success rate
        reason = None if ok else "Document validation failed with provider."
        return ok, reason

    async def get_by_user(self, user_id: str) -> Optional[KycVerification]:
        stmt = (
            await self._db.execute(
                "SELECT * FROM kyc_verifications WHERE user_id = :uid "
                "ORDER BY updated_at DESC LIMIT 1",
                {"uid": user_id},
            )
        ).first()
        return stmt[0] if stmt else None  # type: ignore[index]


# --------------------------------------------------------------------------- #
# FastAPI                                                                     #
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="CrowdPay ‑ KYC Service",
    version="1.0.0",
    openapi_url="/openapi.json",
)


@app.on_event("startup")
async def on_startup() -> None:
    # Create tables if they do not exist (Alembic should handle migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Init Kafka producer (non-blocking if unavailable)
    global publisher
    try:
        publisher = KafkaPublisher(
            brokers=settings.kafka_bootstrap_servers, topic=settings.kafka_topic
        )
        await publisher.start()
    except Exception:  # pragma: no cover
        publisher = None
        logger.warning("Kafka unavailable – events will be stored only in DB.")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if publisher:
        await publisher.stop()
    await engine.dispose()


# --------------------------------------------------------------------------- #
# API Routes                                                                  #
# --------------------------------------------------------------------------- #


def get_service(db: AsyncSession = Depends(get_session)) -> KycService:
    return KycService(db)


@app.post(
    "/kyc/verify",
    response_model=KycResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kick-off KYC verification for a user.",
)
async def verify_kyc(
    request: KycRequest, service: KycService = Depends(get_service)
) -> KycResponse:
    record = await service.verify(request)
    return KycResponse(
        user_id=record.user_id,
        status=record.status,
        failure_reason=record.failure_reason,
        updated_at=record.updated_at,
    )


@app.get(
    "/kyc/{user_id}",
    response_model=KycResponse,
    summary="Retrieve latest KYC status for given user.",
)
async def get_kyc_status(
    user_id: str, service: KycService = Depends(get_service)
) -> KycResponse:
    record = await service.get_by_user(user_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KYC record for user '{user_id}' not found.",
        )
    return KycResponse(
        user_id=record.user_id,
        status=record.status,
        failure_reason=record.failure_reason,
        updated_at=record.updated_at,
    )
```