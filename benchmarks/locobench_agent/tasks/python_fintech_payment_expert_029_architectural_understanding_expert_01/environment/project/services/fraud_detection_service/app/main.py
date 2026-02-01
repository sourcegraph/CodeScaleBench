```python
"""
CrowdPay Connect – Fraud-Detection Service (main.py)
====================================================

This micro-service performs real-time fraud analysis for every monetary
operation that flows through CrowdPay Connect.  The service exposes:

1.  A synchronous HTTP endpoint used by API-Gateway / gRPC edge to obtain
    an immediate fraud verdict on a pending transaction.

2.  An asynchronous Kafka consumer that continuously ingests “Transaction*
    events from the global event bus, enriches them with fraud signals and
    re-publishes “FraudVerdict* events to downstream services (settlements,
    notifications, reputation-engine, etc.).

Design principles
-----------------
• FastAPI ‑ high-performance HTTP layer.  
• Pydantic ‑ strong runtime validation.  
• asyncio  ‑ non-blocking IO for Kafka + HTTP calls to KYC/Risk-score
  micro-services.  
• Security-by-design ‑ no sensitive data logged, strict exception handling.  
• Saga-/Event-Sourcing-ready – emits idempotent domain events.  
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from enum import Enum
from functools import lru_cache
from typing import Optional

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BaseSettings, Field, validator

try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
except ImportError as exc:  # Soft-dependency (unit tests / local dev)
    AIOKafkaConsumer = AIOKafkaProducer = None  # type: ignore
    logging.warning("aiokafka not installed – event bus disabled: %s", exc)

###############################################################################
# Configuration
###############################################################################


class Settings(BaseSettings):
    """Service configuration pulled from ENV variables."""

    # --- HTTP ---------------------------------------------------------------
    project_name: str = "CrowdPay Fraud-Detection"
    api_prefix: str = "/api/v1/fraud"

    # --- Service Ports ------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8085

    # --- External Services --------------------------------------------------
    kyc_service_url: str = "http://kyc_service:8081/api/v1/users"
    rules_service_url: str = "http://rules_engine:8082/api/v1/rules"

    # --- Kafka --------------------------------------------------------------
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_tx_topic: str = "transaction.events"
    kafka_fraud_topic: str = "fraud.events"
    kafka_group_id: str = "fraud_detection_service"

    # --- Risk scoring -------------------------------------------------------
    high_risk_threshold: float = 0.8
    medium_risk_threshold: float = 0.5

    # --- Misc ---------------------------------------------------------------
    log_level: str = Field("INFO", env="LOG_LEVEL")

    class Config:
        env_prefix = "CROWD_FRAUD_"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    """Resolve configuration once (FastAPI dependency)."""
    return Settings()


###############################################################################
# Models
###############################################################################


class RiskVerdict(str, Enum):
    """Possible fraud verdicts."""

    APPROVED = "approved"
    REVIEW = "review"
    DECLINED = "declined"


class TransactionEvent(BaseModel):
    """Incoming transaction payload (event-sourcing & API)."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tx_id: uuid.UUID
    from_user_id: uuid.UUID
    crowd_pod_id: uuid.UUID
    amount: float
    currency: str
    ip_address: str
    device_id: str
    timestamp: int  # epoch-milliseconds
    # Additional optional metadata
    location: Optional[str] = None
    user_agent: Optional[str] = None

    @validator("amount")
    def amount_must_be_positive(cls, v):  # noqa: N805
        if v <= 0:
            raise ValueError("amount must be > 0")
        return v


class FraudVerdictEvent(BaseModel):
    """Event emitted after fraud analysis."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tx_id: uuid.UUID
    risk_score: float
    verdict: RiskVerdict
    created_at: int  # epoch-milliseconds


###############################################################################
# Risk / Fraud logic
###############################################################################


class FraudEngine:
    """
    Stateless fraud engine.

    Combines:
    1. Simple heuristic rules (e.g. amount caps, geo-ip mismatch).
    2. External KYC / Risk-score micro-service.
    """

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient):
        self.settings = settings
        self.client = http_client

    async def _kyc_status(self, user_id: uuid.UUID) -> bool:
        """
        Ask KYC service if user is verified.
        Returns True if verified, False otherwise. Network errors default False.
        """
        try:
            url = f"{self.settings.kyc_service_url}/{user_id}/status"
            resp = await self.client.get(url, timeout=3.0)
            resp.raise_for_status()
            data = resp.json()
            return bool(data.get("verified", False))
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logging.error("KYC service error for %s: %s", user_id, exc)
            # Conservative default: not verified => higher risk
            return False

    async def _external_rule_score(self, tx: TransactionEvent) -> float:
        """
        Ask rules-engine for advanced ML score. Returns 0-1 float.
        Fallback to 0.5 (neutral) on failure.
        """
        try:
            resp = await self.client.post(
                f"{self.settings.rules_service_url}/score",
                json=tx.dict(),
                timeout=2.5,
            )
            resp.raise_for_status()
            return float(resp.json().get("score", 0.5))
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logging.error("Rules-engine unavailable: %s", exc)
            return 0.5

    async def compute_risk(self, tx: TransactionEvent) -> float:
        """
        Compute an aggregated fraud risk score between 0 and 1.
        Higher is riskier.
        """
        kyc_verified = await self._kyc_status(tx.from_user_id)
        ml_score = await self._external_rule_score(tx)

        # Simple heuristics
        heuristics_score = 0.0
        if tx.amount > 10_000:  # Large amount
            heuristics_score += 0.3
        if tx.location and tx.location.lower() not in {"us", "ca", "uk"}:
            heuristics_score += 0.2
        if not kyc_verified:
            heuristics_score += 0.25

        # Weighted aggregation
        final_score = min(1.0, 0.6 * ml_score + heuristics_score)
        return round(final_score, 4)

    def derive_verdict(self, score: float) -> RiskVerdict:
        """
        Map risk score to human verdict using configured thresholds.
        """
        if score >= self.settings.high_risk_threshold:
            return RiskVerdict.DECLINED
        if score >= self.settings.medium_risk_threshold:
            return RiskVerdict.REVIEW
        return RiskVerdict.APPROVED


###############################################################################
# FastAPI application & dependency wiring
###############################################################################

app = FastAPI(
    title="CrowdPay Fraud Detection",
    description="Real-time fraud evaluation micro-service.",
    version="1.1.0",
)


async def get_http_client() -> httpx.AsyncClient:
    """
    Shared async HTTP client (FastAPI dependency). Closes on application shutdown.
    """
    async with httpx.AsyncClient() as client:
        yield client


async def get_engine(
    settings: Settings = Depends(get_settings),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> FraudEngine:
    yield FraudEngine(settings, http_client)


@app.post(
    "/evaluate",
    response_model=FraudVerdictEvent,
    status_code=status.HTTP_200_OK,
    tags=["sync"],
)
async def evaluate_transaction(
    tx: TransactionEvent,
    bg_tasks: BackgroundTasks,
    engine: FraudEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    """
    Synchronous risk evaluation endpoint used by API-Gateway
    to decide whether to continue the payment workflow.
    """
    risk_score = await engine.compute_risk(tx)
    verdict = engine.derive_verdict(risk_score)
    verdict_event = FraudVerdictEvent(
        tx_id=tx.tx_id, risk_score=risk_score, verdict=verdict, created_at=tx.timestamp
    )

    # Publish the verdict asynchronously to Kafka (do not block request)
    if AIOKafkaProducer is not None:
        bg_tasks.add_task(_publish_verdict_event, verdict_event, settings)

    return verdict_event


###############################################################################
# Kafka background loop
###############################################################################


async def _publish_verdict_event(event: FraudVerdictEvent, settings: Settings) -> None:
    """Publish FraudVerdictEvent to Kafka topic."""
    if AIOKafkaProducer is None:
        logging.debug("Kafka producer disabled – event not published.")
        return

    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        await producer.send_and_wait(
            settings.kafka_fraud_topic, json.dumps(event.dict()).encode()
        )
    except Exception as exc:  # pylint: disable=broad-except
        logging.error("Failed to publish fraud event: %s", exc)
    finally:
        await producer.stop()


async def _consume_transaction_events(
    settings: Settings, engine: FraudEngine
) -> None:
    """Long-running task: consume transaction events from Kafka."""
    if AIOKafkaConsumer is None:
        logging.warning("Kafka consumer disabled – no event ingestion.")
        return

    consumer = AIOKafkaConsumer(
        settings.kafka_tx_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_group_id,
        enable_auto_commit=True,
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    await consumer.start()
    producer: Optional[AIOKafkaProducer] = None

    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers
        )
        await producer.start()

        async for msg in consumer:
            try:
                tx_event = TransactionEvent(**msg.value)
            except Exception as exc:  # invalid schema
                logging.error("Invalid transaction event skipped: %s", exc)
                continue

            risk_score = await engine.compute_risk(tx_event)
            verdict = engine.derive_verdict(risk_score)
            verdict_event = FraudVerdictEvent(
                tx_id=tx_event.tx_id,
                risk_score=risk_score,
                verdict=verdict,
                created_at=tx_event.timestamp,
            )
            try:
                await producer.send(
                    settings.kafka_fraud_topic, json.dumps(verdict_event.dict()).encode()
                )
            except Exception as exc:  # pylint: disable=broad-except
                logging.error("Failed to send verdict event: %s", exc)
    finally:
        await consumer.stop()
        if producer:
            await producer.stop()


###############################################################################
# Lifespan handling
###############################################################################

@app.on_event("startup")
async def _startup_event() -> None:
    """Initialize logging & background consumer."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    if AIOKafkaConsumer is None:
        return  # Kafka not available

    # Spin background consumer
    engine = FraudEngine(settings, httpx.AsyncClient())
    loop = asyncio.get_running_loop()
    loop.create_task(_consume_transaction_events(settings, engine))
    logging.info("Fraud-detection service started.")


@app.on_event("shutdown")
async def _shutdown_event() -> None:
    logging.info("Fraud-detection service shutting down.")


###############################################################################
# Entrypoint (for `python main.py` local testing)
###############################################################################

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8085")),
        reload=bool(os.getenv("DEBUG", "0")) or "--reload" in sys.argv,
    )
```