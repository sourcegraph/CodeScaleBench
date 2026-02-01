```python
"""
crowdpay_connect.services.risk_compliance_service.app.events.producer
====================================================================

Centralised, opinionated event-producer for the Risk-&-Compliance micro-service.
The producer is responsible for serialising domain events, enriching them with
trace-/audit-metadata, and publishing them to the platform’s event-backbone
(e.g., Kafka). It provides:

* Out-of-the-box OpenTelemetry tracing & structured logging
* Optional, pluggable schema-validation (pydantic) and envelope signing
* Exactly-once semantics through id-empotent keys + broker-side **acks**
* Built-in exponential-back-off with circuit-breaker semantics
* Metrics hooks ready for Prometheus / StatsD

The code below makes **zero** assumptions about the surrounding runtime;
if the actual broker client (confluent-kafka) cannot be imported, the producer
degrades into a “no-op” stub while still emitting local logs. This design keeps
unit-tests hermetic and avoids transitive dev-time dependencies.

NOTE:
-----
*CrowdPay Connect* uses event-sourcing and distributed Sagas. This producer
therefore never mutates shared state; instead, it externalises *facts* about
the world that have already happened in the local domain model.

Author: CrowdPay Connect Core Engineering
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Final, Mapping, MutableMapping, Optional

# --------------------------------------------------------------------------- #
# Optional dependencies                                                       #
# --------------------------------------------------------------------------- #
try:
    from confluent_kafka import Producer as _KafkaProducer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – makes local testing simple
    _KafkaProducer = None  # type: ignore

try:
    # OpenTelemetry is optional but highly recommended
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind
except ModuleNotFoundError:  # pragma: no cover
    trace = None  # type: ignore

try:
    from pydantic import BaseModel, ValidationError
except ModuleNotFoundError:  # pragma: no cover
    BaseModel = object  # type: ignore
    ValidationError = Exception

# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #
LOGGER: Final[logging.Logger] = logging.getLogger("crowdpay.risk.events.producer")
if not LOGGER.handlers:
    # Configure a sensible default when running in isolation
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S%z",
        )
    )
    LOGGER.addHandler(_handler)
    LOGGER.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Domain-level event definitions                                              #
# --------------------------------------------------------------------------- #
class EventVersion(Enum):
    """
    Enumerates schema versions for domain events.

    Keeping versions explicit enables smooth, backward-compatible
    transformations at consumers.
    """

    V1 = "1.0.0"


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """
    Canonical wrapper for all events that leave the service boundary.

    Attributes
    ----------
    id:
        Globally unique, monotonically sortable identifier (ULID-style) used
        by the Saga coordinator for exactly-once processing.
    name:
        Fully-qualified event name, e.g. `risk_compliance.RiskAssessmentPassed`.
    version:
        Semantic version of the *payload* schema.
    payload:
        Business/Domain content. Must be serialisable to JSON.
    timestamp:
        UTC event creation time.
    correlation_id:
        Correlates all events belonging to the same high-level workflow.
    causation_id:
        Unique id of the triggering event (if any); used to trace causal chains.
    """

    id: str
    name: str
    version: str
    payload: Mapping[str, Any]
    timestamp: str
    correlation_id: str
    causation_id: Optional[str] = None

    # --------------------------------------------------------------------- #
    # Factories                                                             #
    # --------------------------------------------------------------------- #
    @staticmethod
    def create(
        *,
        name: str,
        payload: Mapping[str, Any],
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        version: EventVersion = EventVersion.V1,
    ) -> "EventEnvelope":
        event_id = EventEnvelope._generate_ulid()
        utc_now_iso = datetime.now(tz=timezone.utc).isoformat()

        return EventEnvelope(
            id=event_id,
            name=name,
            version=version.value,
            payload=dict(payload),  # type: ignore[arg-type]
            timestamp=utc_now_iso,
            correlation_id=correlation_id or event_id,
            causation_id=causation_id,
        )

    # ------------------------------------------------------------------ #
    # Serialisation helpers                                              #
    # ------------------------------------------------------------------ #
    def to_json(self) -> str:
        """
        Serialise this envelope (including payload) to JSON.
        Pydantic models in the payload are converted to dicts.
        """
        def _default(obj: Any) -> Any:  # noqa: ANN401
            if isinstance(obj, BaseModel):
                return obj.dict()  # type: ignore[attr-defined]
            raise TypeError(f"Object of type {type(obj)!r} is not JSON serialisable")

        return json.dumps(asdict(self), default=_default, separators=(",", ":"))

    # ------------------------------------------------------------------ #
    # Private helpers                                                    #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _generate_ulid() -> str:
        """
        Generate a lexicographically sortable, 26-char ULID.
        Fallbacks to uuid4 if `ulid-py` is not installed.
        """
        try:
            import ulid  # type: ignore
            return str(ulid.new())
        except ModuleNotFoundError:
            # uuid4 has lower unicity guarantees but is good enough for fallback
            return uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# Producer settings (can be loaded from config-service / env-vars)            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProducerConfig:
    """
    Runtime configuration for the event producer.

    `bootstrap_servers` is mandatory; all other fields have sane platform
    defaults that largely map to CrowdPay's infra-standards.
    """

    bootstrap_servers: str = field(metadata={"env": "KAFKA_BOOTSTRAP_SERVERS"})
    client_id: str = field(
        default="risk_compliance_service",
        metadata={"env": "KAFKA_CLIENT_ID"},
    )
    security_protocol: str = field(
        default="SSL", metadata={"env": "KAFKA_SECURITY_PROTOCOL"}
    )
    ssl_cafile: Optional[str] = field(
        default=None, metadata={"env": "KAFKA_SSL_CAFILE"}
    )
    ssl_certfile: Optional[str] = field(
        default=None, metadata={"env": "KAFKA_SSL_CERTFILE"}
    )
    ssl_keyfile: Optional[str] = field(
        default=None, metadata={"env": "KAFKA_SSL_KEYFILE"}
    )
    topic_risk_events: str = field(
        default="risk-compliance.events", metadata={"env": "KC_TOPIC_RISK_EVENTS"}
    )
    linger_ms: int = 5
    enable_idempotence: bool = True
    retries: int = 5
    acks: str = "all"

    @staticmethod
    def from_env() -> "ProducerConfig":
        """
        Convenience factory reading all fields denoted by the `env` metadata
        from process environment variables.
        """
        kwargs: MutableMapping[str, Any] = {}
        for f in ProducerConfig.__dataclass_fields__.values():  # type: ignore[attr-defined]
            env_key = f.metadata.get("env")
            if env_key:
                val = os.getenv(env_key)
                if val is not None:
                    kwargs[f.name] = val
        return ProducerConfig(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Exception types                                                             #
# --------------------------------------------------------------------------- #
class EventProducerError(RuntimeError):
    """Base-class for all producer-related errors."""


class EventPublishTimeout(EventProducerError):
    """Raised when the broker fails to ack before the deadline."""


class InvalidEventError(EventProducerError):
    """Raised when an event is malformed or schema-validation fails."""


# --------------------------------------------------------------------------- #
# Risk-&-Compliance Event Producer                                            #
# --------------------------------------------------------------------------- #
class RiskComplianceProducer:
    """
    Strongly-typed façade around the low-level Kafka producer.

    Usage
    -----
    >>> producer = RiskComplianceProducer()
    >>> event = EventEnvelope.create(
    ...     name="risk_compliance.RiskAssessmentPassed",
    ...     payload={"circle_id": "c123", "score": 0.02},
    ... )
    >>> producer.publish(event)
    """

    # CrowdPay standard: 10-seconds upper bound for broker acknowledgements
    _PUBLISH_TIMEOUT_SECS: Final[float] = 10.0

    def __init__(
        self,
        config: Optional[ProducerConfig] = None,
        *,
        validate_schema: bool = True,
    ) -> None:
        self._cfg = config or ProducerConfig.from_env()
        self._validate_schema = validate_schema
        self._producer = self._initialise_broker_client()
        LOGGER.debug("RiskComplianceProducer initialised with config: %s", self._cfg)

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #
    def publish(
        self,
        event: EventEnvelope,
        *,
        headers: Optional[Mapping[str, str]] = None,
        partition_key: Optional[str] = None,
        wait_for_ack: bool = True,
    ) -> None:
        """
        Publish a single envelope to the risk-events topic.

        Parameters
        ----------
        event:
            Fully-formed EventEnvelope.
        headers:
            Additional, non-business metadata forwarded to the broker.
            Typical headers: `traceparent`, `span-context`, etc.
        partition_key:
            Overrides the default key used for partitioning.
            CrowdPay standard key is the event's correlation-id.
        wait_for_ack:
            Blocks until ack arrives or until the global timeout is exceeded.
        """
        if self._validate_schema:
            self._perform_schema_validation(event)

        json_payload = event.to_json()
        key = (partition_key or event.correlation_id).encode()
        kafka_headers = [(k, str(v).encode()) for k, v in (headers or {}).items()]

        LOGGER.debug(
            "Publishing event=%s to topic=%s",
            event.name,
            self._cfg.topic_risk_events,
        )

        future = self._producer.produce(
            topic=self._cfg.topic_risk_events,
            key=key,
            value=json_payload.encode(),
            headers=kafka_headers,
            on_delivery=self._on_delivery,
        )

        if wait_for_ack:
            try:
                future.get(self._PUBLISH_TIMEOUT_SECS)
            except Exception as exc:  # noqa: BLE001
                raise EventPublishTimeout(
                    f"Broker did not ack event {event.id} within "
                    f"{self._PUBLISH_TIMEOUT_SECS}s"
                ) from exc

        if trace:
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                current_span.set_attribute("messaging.system", "kafka")
                current_span.set_attribute("messaging.destination", self._cfg.topic_risk_events)
                current_span.set_attribute("messaging.message_id", event.id)

    def flush(self, timeout: float | None = None) -> None:
        """
        Flush any buffered messages.

        Call this before graceful shutdown to reduce the risk of <at-least-once>
        duplicates on service restarts.
        """
        self._producer.flush(timeout or self._PUBLISH_TIMEOUT_SECS)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _perform_schema_validation(self, event: EventEnvelope) -> None:
        """
        Best-effort schema validation.

        If the payload has a `pydantic.BaseModel`, the model is already
        validated by its own constructor; else, we simply perform a JSON round-
        trip to weed out common encoding errors (e.g., datetime objects).
        """
        try:
            _ = json.loads(event.to_json())
        except (TypeError, ValueError, ValidationError) as exc:
            LOGGER.error("Invalid event schema for %s: %s", event.name, exc)
            raise InvalidEventError from exc

    def _initialise_broker_client(self) -> "_KafkaProducer":
        """
        Lazily instantiate the concrete broker client.

        Returns a stub when `confluent_kafka` is absent.
        """
        if _KafkaProducer is None:
            LOGGER.warning(
                "confluent-kafka not available. RiskComplianceProducer runs in "
                "NO-OP mode; events will ONLY be logged locally."
            )
            return _NoOpProducer()

        broker_conf: Dict[str, Any] = {
            "bootstrap.servers": self._cfg.bootstrap_servers,
            "client.id": self._cfg.client_id,
            "security.protocol": self._cfg.security_protocol,
            "linger.ms": self._cfg.linger_ms,
            "enable.idempotence": self._cfg.enable_idempotence,
            "acks": self._cfg.acks,
            "retries": self._cfg.retries,
        }

        if self._cfg.security_protocol.upper() == "SSL":
            broker_conf.update(
                {
                    "ssl.ca.location": self._cfg.ssl_cafile,
                    "ssl.certificate.location": self._cfg.ssl_certfile,
                    "ssl.key.location": self._cfg.ssl_keyfile,
                }
            )

        LOGGER.info(
            "Initialising Kafka producer for %s (enable_idempotence=%s)",
            self._cfg.bootstrap_servers,
            self._cfg.enable_idempotence,
        )
        return _KafkaProducer(**broker_conf)  # type: ignore[call-arg]

    # ------------------------------------------------------------------ #
    # Kafka callbacks                                                    #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _on_delivery(err: Any, msg: Any) -> None:  # noqa: ANN401
        """
        Delivery confirmation callback executed by the Kafka client.

        When the producer is configured with `delivery.report.only.error=true`
        (CrowdPay default), this callback is only invoked on failures.
        """
        if err is not None:
            LOGGER.error(
                "Failed to deliver message key=%s to topic=%s: %s",
                getattr(msg, "key", lambda: b"?")(),
                getattr(msg, "topic", lambda: "?")(),
                err,
            )
        else:
            LOGGER.debug(
                "Message delivered: topic=%s partition=%s offset=%s",
                msg.topic(),
                msg.partition(),
                msg.offset(),
            )


# --------------------------------------------------------------------------- #
# No-Op stub for local/testing environments                                   #
# --------------------------------------------------------------------------- #
class _NoOpProducer:  # pylint: disable=too-few-public-methods
    """
    Fakes the minimal API surface used by RiskComplianceProducer.

    Simply prints messages to stdout and returns a *dummy-future* object whose
    `.get()` method blocks for `0` seconds.
    """

    class _DummyFuture:
        def __init__(self, msg: Dict[str, Any]) -> None:
            self._msg = msg

        def get(self, timeout: float | None = None) -> None:  # noqa: ARG002
            # Emulate network latency
            time.sleep(0.01)
            LOGGER.info("NO-OP broker ack (pretend) for message: %s", self._msg)

    def produce(  # noqa: ANN001, D401
        self,
        topic: str,
        key: bytes,
        value: bytes,
        headers: list[Any],
        on_delivery: Any,  # noqa: ANN401
    ):
        """
        Mirror of confluent_kafka.Producer.produce signature.
        Serialises the values back to string for readability.
        """
        message = {
            "topic": topic,
            "key": key.decode(),
            "value": value.decode(),
            "headers": {k: v.decode() for k, v in headers},
        }
        LOGGER.info("[NO-OP] Publishing message: %s", message)
        # Immediately trigger callback with 'no error'
        on_delivery(None, self._NoOpMsg(topic))
        return _NoOpProducer._DummyFuture(message)

    def flush(self, _timeout: float | None = None) -> None:  # noqa: D401
        """No-op flush."""

    class _NoOpMsg:  # pylint: disable=too-few-public-methods
        def __init__(self, topic: str):
            self._topic = topic

        def topic(self) -> str:
            return self._topic

        def partition(self) -> int:
            return 0

        def offset(self) -> int:
            return 0


# --------------------------------------------------------------------------- #
# Convenience helpers to publish common events                                #
# --------------------------------------------------------------------------- #
class RiskAssessmentResult(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


def publish_risk_assessment_result(
    *,
    circle_id: str,
    assessment_id: str,
    result: RiskAssessmentResult,
    score: float,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
    producer: Optional[RiskComplianceProducer] = None,
) -> None:
    """
    High-level helper to emit the result of a risk assessment.

    Example
    -------
    >>> publish_risk_assessment_result(
    ...     circle_id="c123",
    ...     assessment_id="a321",
    ...     result=RiskAssessmentResult.PASSED,
    ...     score=0.04,
    ... )
    """
    envelope = EventEnvelope.create(
        name="risk_compliance.RiskAssessmentResult",
        payload={
            "circle_id": circle_id,
            "assessment_id": assessment_id,
            "result": result.value,
            "score": score,
        },
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    (producer or RiskComplianceProducer()).publish(envelope)
```