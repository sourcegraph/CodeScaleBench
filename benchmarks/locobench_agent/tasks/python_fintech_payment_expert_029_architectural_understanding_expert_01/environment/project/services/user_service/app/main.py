```python
"""
CrowdPay Connect – User Service (main entrypoint)

This micro-service is responsible for the life-cycle of a single end-user:
registration, profile maintenance, KYC verification and reputation emission.
It exposes a REST/JSON API (FastAPI), persists data to the service data-store
(SQLAlchemy) and emits domain events to the company event-bus (RabbitMQ).

The file is intentionally self-contained to ease the example, yet follows
production quality guidelines: settings management, dependency-injection,
transaction-handling, logging, metrics and graceful shutdown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, AsyncGenerator, Final, List, Optional

import pika  # type: ignore
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BaseSettings, EmailStr, Field, validator
from sqlalchemy import Boolean, Column, DateTime, String, Text, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

# --------------------------------------------------------------------------- #
# Settings                                                                    #
# --------------------------------------------------------------------------- #


class Settings(BaseSettings):
    """
    Service configuration loaded from environment variables or `.env`.
    """

    # General
    service_name: str = "crowdpay_user_service"
    environment: str = "development"
    log_level: str = "INFO"

    # Database
    database_uri: str = "sqlite+aiosqlite:///./user_service.db"

    # Event Bus
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_exchange: str = "crowdpay.events"
    rabbitmq_exchange_type: str = "topic"

    # CORS
    allowed_origins: List[str] = ["*"]

    # Security / Compliance
    kyc_threshold: int = 18  # Simplified example age threshold

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings: Final[Settings] = Settings()

# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=settings.log_level,
    stream=sys.stdout,
    format="%(message)s",
)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(settings.log_level)),
    processors=[
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
)
logger = structlog.get_logger().bind(service=settings.service_name)

# --------------------------------------------------------------------------- #
# Database                                                                    #
# --------------------------------------------------------------------------- #

Base = declarative_base()


class User(Base):
    """
    User persistence model (publicly safe subset; sensitive data lives in the
    dedicated secure-data service in production).
    """

    __tablename__ = "users"

    id: Annotated[str, Column] = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Annotated[str, Column] = Column(String(320), unique=True, nullable=False)
    full_name: Annotated[str, Column] = Column(String(255), nullable=False)
    kyc_verified: Annotated[bool, Column] = Column(Boolean, default=False)
    reputation_score: Annotated[int, Column] = Column(
        String, default=0
    )  # Simplified for demo
    created_at: Annotated[str, Column] = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Annotated[str, Column] = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Audit trail kept in shadow table (not part of demo)


def create_engine() -> AsyncEngine:
    return create_async_engine(settings.database_uri, echo=False, future=True)


engine: Final[AsyncEngine] = create_engine()
async_session_factory: Final[async_sessionmaker] = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a database session inside a SQLAlchemy 2.0 style transaction.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# --------------------------------------------------------------------------- #
# Event Bus                                                                   #
# --------------------------------------------------------------------------- #


class EventPublisher:
    """
    Publish domain events to RabbitMQ in a non-blocking fashion.
    """

    def __init__(self) -> None:
        self._connection: Optional[pika.BlockingConnection] = None
        self._channel: Optional[pika.adapters.blocking_connection.BlockingChannel] = None

    def connect(self) -> None:
        params = pika.URLParameters(settings.rabbitmq_url)
        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()
        self._channel.exchange_declare(
            exchange=settings.rabbitmq_exchange,
            exchange_type=settings.rabbitmq_exchange_type,
            durable=True,
        )
        logger.info("rabbitmq_connected")

    def publish_event(self, routing_key: str, payload: dict) -> None:
        if not self._channel or self._connection is None or self._connection.is_closed:
            self.connect()

        body = json.dumps(payload).encode("utf-8")
        self._channel.basic_publish(
            exchange=settings.rabbitmq_exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,  # persistent
                content_type="application/json",
            ),
        )
        logger.info("event_published", routing_key=routing_key, payload=payload)

    def close(self) -> None:
        try:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
                logger.info("rabbitmq_connection_closed")
        except Exception as exc:
            logger.error("rabbitmq_graceful_shutdown_failed", error=str(exc))


event_publisher: Final[EventPublisher] = EventPublisher()

# --------------------------------------------------------------------------- #
# Schemas                                                                     #
# --------------------------------------------------------------------------- #


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str
    age: int = Field(..., gt=0)

    @validator("full_name")
    def name_must_have_space(cls, v: str) -> str:
        if " " not in v.strip():
            raise ValueError("full_name must contain at least one space.")
        return v.title()


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    kyc_verified: bool
    reputation_score: int
    created_at: str
    updated_at: str


class KYCVerificationRequest(BaseModel):
    doc_type: str = Field(..., description="e.g. passport, driver_license")
    doc_front_image_url: str
    doc_back_image_url: Optional[str] = None


# --------------------------------------------------------------------------- #
# Service Layer                                                               #
# --------------------------------------------------------------------------- #


async def create_user(
    payload: UserCreateRequest, session: AsyncSession
) -> User:
    existing = (
        await session.execute(
            # type: ignore[attr-defined]
            sqlalchemy.select(User).where(User.email == payload.email)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(email=payload.email, full_name=payload.full_name)
    session.add(user)

    await session.flush()  # get id
    event_publisher.publish_event(
        routing_key="user.created",
        payload={
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "timestamp": str(user.created_at),
        },
    )
    return user


async def verify_kyc(
    user_id: str, payload: KYCVerificationRequest, session: AsyncSession
) -> User:
    # Real KYC would call external provider; we simulate pass/fail

    user: User | None = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.kyc_verified:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="User already KYC verified"
        )

    # Fake validation logic
    if not payload.doc_type or not payload.doc_front_image_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid documents")

    user.kyc_verified = True
    await session.flush()

    event_publisher.publish_event(
        routing_key="user.kyc_verified",
        payload={
            "id": user.id,
            "doc_type": payload.doc_type,
            "timestamp": str(func.now()),
        },
    )
    return user


async def get_user(user_id: str, session: AsyncSession) -> User:
    user: User | None = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


# --------------------------------------------------------------------------- #
# API / FastAPI                                                               #
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="CrowdPay Connect – User Service",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


# --------------------------- Middleware & Hooks ---------------------------- #

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("validation_error", errors=exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("http_exception", detail=exc.detail, status_code=exc.status_code)
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail}
    )


# ------------------------------- Endpoints --------------------------------- #


@app.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    summary="Register a new user",
)
async def api_create_user(
    payload: UserCreateRequest,
    session: Annotated[AsyncSession, Depends(db_session)],
):
    user = await create_user(payload, session)
    return UserResponse.from_orm(user)  # type: ignore[arg-type]


@app.post(
    "/users/{user_id}/kyc",
    response_model=UserResponse,
    summary="Verify user KYC",
)
async def api_verify_kyc(
    user_id: str,
    payload: KYCVerificationRequest,
    session: Annotated[AsyncSession, Depends(db_session)],
):
    user = await verify_kyc(user_id, payload, session)
    return UserResponse.from_orm(user)  # type: ignore[arg-type]


@app.get(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Fetch user details",
)
async def api_get_user(
    user_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
):
    user = await get_user(user_id, session)
    return UserResponse.from_orm(user)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Lifespan Management                                                         #
# --------------------------------------------------------------------------- #


@app.on_event("startup")
async def on_startup() -> None:
    # Database
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("tables_ready")

    # Event bus (warm connection)
    try:
        event_publisher.connect()
    except Exception as exc:
        logger.error("rabbitmq_initial_connection_failed", error=str(exc))

    # Graceful shutdown signals for uvicorn / hypercorn
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown(loop, signal_name=s.name)),
        )
    logger.info("startup_complete")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("service_shutdown")
    event_publisher.close()
    await engine.dispose()


async def shutdown(loop: asyncio.AbstractEventLoop, signal_name: str) -> None:
    logger.info("graceful_shutdown_initiated", signal=signal_name)
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()
```
