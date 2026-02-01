```python
"""
CrowdPay Connect – Risk & Compliance Service
============================================

Entry-point module that exposes a small HTTP surface (FastAPI) for health-checks
and on-demand risk look-ups, while running an asynchronous event-consumer that
performs real-time risk assessments, KYC verification and compliance checks
whenever a payment-related domain event is published to Kafka.

The micro-service follows the following high-level workflow:

    Kafka Event  ─┐
                  ├──▶ EventConsumer ──▶  EventRouter  ─┐
                  │                                     │
                  │                                     ▼
                  │                          +-------------------+
                  │                          |  RiskEngine       |
                  │                          +-------------------+
                  │                                     │
                  │                                     ▼
                  │                          +-------------------+
                  │                          |  ComplianceSuite  |
                  │                          +-------------------+
                  │                                     │
                  │                                     ▼
                  └──────────────────────────────────▶ SagaReply
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BaseSettings, Field, ValidationError
from starlette.requests import Request

# --------------------------------------------------------------------------- #
#  External message queue (Kafka) – imported lazily to keep test-deps light.  #
# --------------------------------------------------------------------------- #
try:  # pragma: no cover
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
except ModuleNotFoundError:  # gracefully degrade for unit-tests
    AIOKafkaConsumer = None  # type: ignore
    AIOKafkaProducer = None  # type: ignore


###############################################################################
#                              Configuration                                  #
###############################################################################
class Settings(BaseSettings):
    """Service configuration loaded from environment variables."""

    # Basic
    APP_NAME: str = "crowdpay-risk-compliance-service"
    ENV: str = Field("dev", regex="^(dev|staging|prod)$")
    LOG_LEVEL: str = Field("INFO", regex="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    EVENTS_TOPIC: str = "crowdpay.payments.events"
    SAGA_REPLY_TOPIC: str = "crowdpay.saga.replies"
    CONSUMER_GROUP_ID: str = "risk_compliance_service"

    # Risk engine
    FRAUD_THRESHOLD: float = 0.75  # 0-1 risk score
    MODEL_PATH: Optional[str] = None

    # Time-outs
    KAFKA_CONN_TIMEOUT_S: int = 10
    RISK_ASSESSMENT_TIMEOUT_S: int = 3

    class Config:
        env_prefix = "CROWDPAY_"
        case_sensitive = False


settings = Settings()  # will raise early if env vars invalid


###############################################################################
#                              Logging                                        #
###############################################################################
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(settings.APP_NAME)

###############################################################################
#                Domain Models (simplified for demonstration)                 #
###############################################################################
class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class PaymentEvent(BaseModel):
    """Inbound event emitted by the Payment Service."""

    event_id: str
    type: str  # e.g., PAYMENT_INITIATED, CROWD_POD_CREATED
    payload: Dict[str, Any]
    timestamp: float


class RiskAssessment(BaseModel):
    """Internal representation of a risk-assessment result."""

    event_id: str
    user_id: str
    crowdpod_id: str
    score: float
    flagged: bool
    reason: str


class SagaReply(BaseModel):
    """Reply to the Saga orchestrator for accept/compensate."""

    correlation_id: str
    status: str  # COMMIT/ROLLBACK
    detail: Dict[str, Any]


###############################################################################
#                       Risk, KYC & Compliance Engines                        #
###############################################################################
class KYCService:
    """
    Simplified KYC verification service.
    In production, this would integrate with vendors such as Trulioo, Onfido, etc.
    """

    async def verify_user(self, user_id: str) -> bool:
        logger.debug("Performing KYC verification for user '%s'", user_id)
        await asyncio.sleep(0.1)  # simulate latency
        # Composite heuristic: odd ids fail KYC (demo only)
        passed = int(user_id[-1]) % 2 == 0
        logger.debug("KYC result for user '%s': %s", user_id, passed)
        return passed


class RiskEngine:
    """A toy risk-scoring engine."""

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = model_path
        # In real life, a ML model would be loaded here.
        logger.info("RiskEngine initialised (model=%s)", model_path)

    async def score_payment(self, event: PaymentEvent) -> float:
        logger.debug("Scoring event '%s'", event.event_id)
        await asyncio.sleep(0.05)  # pretend work

        payment_amount: float = float(event.payload.get("amount", 0))
        currency: Currency = Currency(event.payload.get("currency", "USD"))
        user_id: str = event.payload.get("user_id", "unknown")
        crowd_pod_size = int(event.payload.get("crowd_pod_size", 1))

        # Heuristics (demo only, NOT for production)
        base_score = min(1.0, payment_amount / 1_000)
        currency_factor = 0.1 if currency == Currency.USD else 0.2
        crowd_factor = 0.05 * crowd_pod_size
        user_factor = 0.3 if user_id.startswith("sus") else 0.0

        score = base_score + currency_factor + crowd_factor + user_factor
        score = min(score, 1.0)
        logger.debug(
            "Risk score computed for event '%s': %.2f (amount=%.2f, crowd=%d)",
            event.event_id,
            score,
            payment_amount,
            crowd_pod_size,
        )
        return score


###############################################################################
#                           Event Processing Logic                            #
###############################################################################
class EventProcessor:
    """Coordinates KYC, risk-scoring and compliance decisions."""

    def __init__(
        self,
        risk_engine: RiskEngine,
        kyc_service: KYCService,
        producer: Optional["AIOKafkaProducer"],
    ) -> None:
        self._risk_engine = risk_engine
        self._kyc_service = kyc_service
        self._producer = producer

    async def process(self, raw: bytes) -> None:
        """Process a single raw Kafka message."""
        try:
            event = PaymentEvent.parse_raw(raw)
        except ValidationError as e:
            logger.error("Failed to parse PaymentEvent: %s", e)
            return

        logger.info("Processing event '%s' (%s)", event.event_id, event.type)

        try:
            # Parallelise KYC and risk scoring
            kyc_task = asyncio.create_task(
                self._kyc_service.verify_user(event.payload.get("user_id", ""))
            )
            risk_task = asyncio.create_task(self._risk_engine.score_payment(event))

            done, pending = await asyncio.wait(
                {kyc_task, risk_task},
                timeout=settings.RISK_ASSESSMENT_TIMEOUT_S,
                return_when=asyncio.ALL_COMPLETED,
            )
            for task in pending:
                task.cancel()

            kyc_passed: bool = kyc_task.result()
            score: float = risk_task.result()

        except Exception as exc:
            logger.exception("Error during assessment: %s", exc)
            await self._saga_reply(
                correlation_id=event.event_id,
                status="ROLLBACK",
                detail={"reason": "internal_error"},
            )
            return

        flagged = not kyc_passed or score >= settings.FRAUD_THRESHOLD
        if flagged:
            reason = []
            if not kyc_passed:
                reason.append("kyc_failed")
            if score >= settings.FRAUD_THRESHOLD:
                reason.append("high_risk_score")
            await self._handle_block(event, reason)
        else:
            await self._handle_approve(event)

    # --------------------------------------------------------------------- #
    #                            Private helpers                            #
    # --------------------------------------------------------------------- #
    async def _handle_block(self, event: PaymentEvent, reasons: list[str]) -> None:
        logger.warning(
            "Payment '%s' blocked – reasons=%s", event.event_id, ",".join(reasons)
        )
        await self._publish_risk_assessment(event, blocked=True, reason=",".join(reasons))
        await self._saga_reply(
            correlation_id=event.event_id,
            status="ROLLBACK",
            detail={"reasons": reasons},
        )

    async def _handle_approve(self, event: PaymentEvent) -> None:
        logger.info("Payment '%s' approved", event.event_id)
        await self._publish_risk_assessment(event, blocked=False, reason="approved")
        await self._saga_reply(
            correlation_id=event.event_id,
            status="COMMIT",
            detail={"risk": "approved"},
        )

    async def _publish_risk_assessment(
        self, event: PaymentEvent, blocked: bool, reason: str
    ) -> None:
        if not self._producer:
            logger.debug("No Kafka producer available – skipping publish")
            return

        assessment = RiskAssessment(
            event_id=event.event_id,
            user_id=event.payload.get("user_id", "unknown"),
            crowdpod_id=event.payload.get("crowd_pod_id", "unknown"),
            score=await self._risk_engine.score_payment(event),
            flagged=blocked,
            reason=reason,
        )
        await self._producer.send_and_wait(
            topic=settings.SAGA_REPLY_TOPIC,
            value=assessment.json().encode(),
        )
        logger.debug("Published RiskAssessment for event '%s'", event.event_id)

    async def _saga_reply(
        self, correlation_id: str, status: str, detail: Dict[str, Any]
    ) -> None:
        if not self._producer:
            logger.debug("No Kafka producer available – skipping saga reply")
            return

        reply = SagaReply(correlation_id=correlation_id, status=status, detail=detail)
        await self._producer.send_and_wait(
            topic=settings.SAGA_REPLY_TOPIC, value=reply.json().encode()
        )
        logger.debug("Saga reply sent for '%s' – status=%s", correlation_id, status)


###############################################################################
#                       Kafka Consumer Lifecycle                              #
###############################################################################
@asynccontextmanager
async def kafka_resources() -> AsyncGenerator[
    tuple[Optional["AIOKafkaConsumer"], Optional["AIOKafkaProducer"]], None
]:
    """
    Context manager that lazily instantiates Kafka consumer & producer
    (if aiokafka is installed). When the context exits, the connections
    are closed gracefully.
    """
    if AIOKafkaConsumer is None:  # pragma: no cover
        logger.warning("aiokafka not installed – running without Kafka")
        yield None, None
        return

    loop = asyncio.get_running_loop()
    consumer = AIOKafkaConsumer(
        settings.EVENTS_TOPIC,
        loop=loop,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.CONSUMER_GROUP_ID,
        enable_auto_commit=True,
    )
    producer = AIOKafkaProducer(
        loop=loop, bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
    )

    await consumer.start()
    await producer.start()
    logger.info("Kafka consumer & producer started")
    try:
        yield consumer, producer
    finally:
        logger.info("Stopping Kafka consumer & producer")
        await consumer.stop()
        await producer.stop()


async def _consumer_loop(consumer: "AIOKafkaConsumer", processor: EventProcessor) -> None:
    """Continuously poll Kafka for new events."""
    try:
        async for msg in consumer:
            await processor.process(msg.value)
    except asyncio.CancelledError:  # graceful shutdown
        logger.info("Kafka consumer loop cancelled")
    except Exception as exc:  # pragma: no cover
        logger.exception("Unhandled exception in consumer loop: %s", exc)


###############################################################################
#                                FastAPI                                      #
###############################################################################
app = FastAPI(
    title="CrowdPay – Risk & Compliance Service",
    version="1.0.0",
    description="Performs real-time risk assessments, KYC and AML checks",
    contact={"name": "CrowdPay Compliance Team", "url": "https://crowdpay.io"},
)


class RiskRequest(BaseModel):
    event: PaymentEvent


class RiskResponse(BaseModel):
    score: float
    flagged: bool


def get_risk_engine() -> RiskEngine:
    return app.state.risk_engine  # type: ignore


@app.on_event("startup")
async def _startup() -> None:
    """Initialise shared components & background tasks."""
    risk_engine = RiskEngine(model_path=settings.MODEL_PATH)
    kyc_service = KYCService()
    app.state.risk_engine = risk_engine
    app.state.kyc_service = kyc_service

    # Kafka – start only if dependency available
    if AIOKafkaConsumer is None:
        logger.warning("Kafka not available – event consumer disabled")
        return

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Inject resources into lifespan context
        async with kafka_resources() as (consumer, producer):
            if consumer and producer:
                processor = EventProcessor(risk_engine, kyc_service, producer)
                consumer_task = asyncio.create_task(_consumer_loop(consumer, processor))
                app.state.consumer_task = consumer_task
            yield
            # Clean-up happens in kafka_resources & FastAPI handles task cancellations

    # Override default lifespan only if aiokafka available
    app.router.lifespan_context = lifespan  # type: ignore


@app.on_event("shutdown")
async def _shutdown() -> None:
    # Cancel consumer task if running
    task: Optional[asyncio.Task] = getattr(app.state, "consumer_task", None)
    if task and not task.done():
        logger.info("Cancelling Kafka consumer task...")
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.get("/health", tags=["system"])
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": settings.APP_NAME, "env": settings.ENV}


@app.post("/risk/score", response_model=RiskResponse, tags=["risk"])
async def risk_score(
    req: RiskRequest, risk_engine: RiskEngine = Depends(get_risk_engine)
) -> RiskResponse:
    """Compute a risk score on-demand."""
    score = await risk_engine.score_payment(req.event)
    flagged = score >= settings.FRAUD_THRESHOLD
    return RiskResponse(score=score, flagged=flagged)


###############################################################################
#                       Entrypoint (CLI / uvicorn)                            #
###############################################################################
def _configure_uvicorn_loggers() -> None:
    """Apply consistent logging settings to uvicorn access/error loggers."""
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = logging.getLogger().handlers
        logging.getLogger(name).setLevel(settings.LOG_LEVEL)


def run() -> None:  # pragma: no cover
    """
    Minimal CLI entry-point.
    Example:
        python -m crowdpay_connect.services.risk_compliance_service.app.main
    """
    import uvicorn

    _configure_uvicorn_loggers()

    uvicorn.run(
        "crowdpay_connect.services.risk_compliance_service.app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level=settings.LOG_LEVEL.lower(),
        reload=settings.ENV == "dev",
    )


# Allow `python main.py` execution for local development
if __name__ == "__main__":  # pragma: no cover
    # Forward SIGTERM to asyncio loop for graceful docker shutdown
    def _handle_sigterm(*_: Any) -> None:
        logger.info("Received SIGTERM signal – initiating shutdown")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    run()
```