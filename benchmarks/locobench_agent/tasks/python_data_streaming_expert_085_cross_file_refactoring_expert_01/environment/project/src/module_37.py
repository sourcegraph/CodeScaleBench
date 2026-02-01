```python
"""
PulseStream Nexus – Data Quality & Validation Component
=======================================================

src/module_37.py

This module encapsulates an **Observable** validation pipeline that inspects
social-event records in near-real-time, applies pluggable validation strategies
(e.g., Great Expectations schema checks, domain-specific guardrails), and emits
Prometheus metrics while forwarding errors to Sentry.  It demonstrates multiple
architectural patterns used across PulseStream Nexus:

• Pipe-and-Filter / ETL Pipeline
• Strategy Pattern (swappable validation engines)
• Observer Pattern (metrics & alert side-effects)
• Clean-Architecture boundary isolation (no I/O concerns here)

External dependencies (import-time optional):

    pip install "pydantic>=2" "prometheus-client" "sentry-sdk" "great_expectations"

The module is 100 % self-contained and testable via an in-memory stream.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from types import TracebackType
from typing import Generator, Iterable, List, Optional, Sequence, Tuple, Type

try:
    from prometheus_client import Counter, Gauge
except ImportError:  # pragma: no cover – metrics exporting is optional
    Counter = Gauge = None  # type: ignore  # fallback stubs


try:
    import sentry_sdk
except ImportError:  # pragma: no cover – Sentry usage is optional
    sentry_sdk = None  # type: ignore


# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #

logger = logging.getLogger("pulse_stream.data_quality")
log_level = os.environ.get("PULSE_LOG_LEVEL", "INFO").upper()
logger.setLevel(log_level)
handler = logging.StreamHandler(stream=sys.stdout)
handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)s – %(name)s – %(message)s")
)
logger.addHandler(handler)

# --------------------------------------------------------------------------- #
# Pydantic data-model
# --------------------------------------------------------------------------- #

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "pydantic is required for module_37; please install with `pip install pydantic`"
    ) from exc


class EventRecord(BaseModel):
    """
    Canonical internal representation of a social-event document.

    The schema is intentionally minimal; additional dynamic
    attributes are allowed to future-proof against upstream changes.
    """

    event_id: str = Field(..., min_length=3, description="ULID or UUID")
    network: str = Field(..., description="Social network identifier, e.g., twitter")
    author_id: str = Field(..., min_length=1)
    text: str = Field(..., description="Raw post content")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    # Enriched fields --------------------------------------------------------
    sentiment: Optional[float] = Field(
        default=None, ge=-1.0, le=1.0, description="Polarity score"
    )
    toxicity: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Perspective API toxicity probability",
    )

    model_config = dict(extra="allow")  # Allow dynamic attributes


# --------------------------------------------------------------------------- #
# Validation Strategy Pattern
# --------------------------------------------------------------------------- #


class ValidationResult(BaseModel):
    """Aggregate outcome for a single record and strategy."""

    strategy_name: str
    ok: bool
    errors: List[str] = []
    duration_ms: int = 0


class BaseValidationStrategy(ABC):
    """Abstract Strategy interface."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def validate(self, record: EventRecord) -> ValidationResult: ...


# -- Strategy 1: Great Expectations ---------------------------------------- #


class GreatExpectationsStrategy(BaseValidationStrategy):
    """
    Record-level validation by delegating to Great Expectations.

    In production, Great Expectations suites live in `gx/` data docs, but
    here we define an in-memory expectation for illustration purposes
    (date not in future, toxicity bounds, non-empty text, etc.).
    """

    def __init__(self) -> None:
        try:
            import great_expectations as gx  # local import to avoid hard dep
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "great_expectations is required for GreatExpectationsStrategy; "
                "install via `pip install great_expectations`."
            ) from exc

        self._gx = gx
        self._expectation_suite = self._build_suite()

    # NOTE: Building suite once keeps runtime hot-path minimal.
    def _build_suite(self):
        from great_expectations.core.expectation_suite import ExpectationSuite

        suite = ExpectationSuite(expectation_suite_name="event_record_suite")

        # Lint few fields; for brevity we validate a subset.
        suite.add_expectation(
            {
                "expectation_type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "event_id"},
            }
        )
        suite.add_expectation(
            {
                "expectation_type": "expect_column_min_to_be_between",
                "kwargs": {
                    "column": "sentiment",
                    "min_value": -1.0,
                    "max_value": -1.0,
                    "mostly": 0.05,  # allow 95 % missing
                },
            }
        )
        suite.add_expectation(
            {
                "expectation_type": "expect_column_values_to_be_between",
                "kwargs": {
                    "column": "toxicity",
                    "min_value": 0.0,
                    "max_value": 1.0,
                    "ignore_row_if": "all_values_are_missing",
                },
            }
        )
        return suite

    # --------------------------------------------------------------------- #

    @property
    def name(self) -> str:  # noqa: D401 – concise property doc
        return "great_expectations"

    def validate(self, record: EventRecord) -> ValidationResult:  # noqa: D401
        start = time.perf_counter()

        # Coerce record to Pandas row for GE.
        import pandas as pd

        df = pd.DataFrame([record.model_dump()])
        from great_expectations.core.batch import BatchRequest
        from great_expectations.validator.validator import Validator
        from great_expectations.data_context import get_context

        context = get_context()
        batch_request = BatchRequest(
            datasource_name="pandas_datasource",
            data_connector_name="default_runtime_data_connector_name",
            data_asset_name="event_dataframe",
            runtime_parameters={"batch_data": df},
            batch_identifiers={"default_identifier_name": "event_validation"},
        )

        validator: Validator = context.get_validator(
            batch_request=batch_request, expectation_suite=self._expectation_suite
        )
        res = validator.validate()

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ValidationResult(
            strategy_name=self.name,
            ok=res.success,
            errors=[str(d) for d in res.results if not d.success],
            duration_ms=duration_ms,
        )


# -- Strategy 2: Domain-specific rulebook ---------------------------------- #


class ToxicityBoundsStrategy(BaseValidationStrategy):
    """
    Lightweight built-in strategy verifying toxicity <= policy threshold.

    Allows rapid **fail-fast** without incurring GE overhead.
    """

    def __init__(self, max_toxicity: float = 0.92) -> None:
        if not 0 <= max_toxicity <= 1:
            raise ValueError("max_toxicity must be within [0, 1]")
        self._max_toxicity = max_toxicity

    # --------------------------------------------------------------------- #
    @property
    def name(self) -> str:
        return "toxicity_bounds"

    def validate(self, record: EventRecord) -> ValidationResult:
        start = time.perf_counter()
        ok = True
        errors: List[str] = []

        if record.toxicity is not None and record.toxicity > self._max_toxicity:
            ok = False
            errors.append(
                f"Toxicity {record.toxicity:.2%} exceeds policy limit "
                f"{self._max_toxicity:.2%}"
            )

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ValidationResult(
            strategy_name=self.name, ok=ok, errors=errors, duration_ms=duration_ms
        )


# --------------------------------------------------------------------------- #
# Observer Pattern – side-effect subscribers
# --------------------------------------------------------------------------- #


class ValidationEvent(BaseModel):
    """Observable payload fired after each strategy run."""

    record: EventRecord
    result: ValidationResult


class EventObserver(ABC):
    """Subscriber interface."""

    @abstractmethod
    def notify(self, event: ValidationEvent) -> None: ...


class PrometheusObserver(EventObserver):
    """
    Publishes validation outcomes to Prometheus Counters/Gauges.

    Metrics exported:
        • pulse_validation_success_total{strategy="…"}
        • pulse_validation_failure_total{strategy="…"}
        • pulse_validation_latency_ms{strategy="…"}
    """

    _success: Counter
    _failure: Counter
    _latency: Gauge

    def __init__(self) -> None:
        if Counter is None:  # pragma: no cover
            raise RuntimeError(
                "prometheus_client not installed. "
                "Install via `pip install prometheus-client` to enable metrics."
            )

        self._success = Counter(
            "pulse_validation_success_total",
            "Successful validation results",
            ["strategy"],
        )
        self._failure = Counter(
            "pulse_validation_failure_total",
            "Failed validation results",
            ["strategy"],
        )
        self._latency = Gauge(
            "pulse_validation_latency_ms",
            "Validation latency (ms)",
            ["strategy"],
        )

    def notify(self, event: ValidationEvent) -> None:
        strat = event.result.strategy_name
        if event.result.ok:
            self._success.labels(strategy=strat).inc()
        else:
            self._failure.labels(strategy=strat).inc()
        self._latency.labels(strategy=strat).set(event.result.duration_ms)


class LoggingObserver(EventObserver):
    """Simple observer that logs failed validations."""

    def notify(self, event: ValidationEvent) -> None:
        if event.result.ok:
            logger.debug(
                "Validated record %s via %s in %d ms",
                event.record.event_id,
                event.result.strategy_name,
                event.result.duration_ms,
            )
            return

        logger.warning(
            "Validation failed for %s via %s (%s)",
            event.record.event_id,
            event.result.strategy_name,
            "; ".join(event.result.errors),
        )


class SentryObserver(EventObserver):
    """
    Ships validation failures to Sentry as breadcrumb + exception.

    The observer is enabled only when sentry_sdk has been initialised.
    """

    def __init__(self) -> None:
        if sentry_sdk is None:  # pragma: no cover
            raise RuntimeError(
                "sentry-sdk not installed. Install via `pip install sentry-sdk`."
            )

    def notify(self, event: ValidationEvent) -> None:
        if event.result.ok:
            return

        sentry_sdk.add_breadcrumb(
            category="data_validation",
            message=f"Validation errors: {event.result.errors}",
            level="warning",
            data={"strategy": event.result.strategy_name},
        )
        sentry_sdk.capture_message(
            f"[PulseStream] Validation failed for record {event.record.event_id}",
            level="warning",
        )


# --------------------------------------------------------------------------- #
# DataQualityMonitor (Observable)                                            #
# --------------------------------------------------------------------------- #


class DataQualityMonitor:
    """
    Drives validation strategy execution and publishes `ValidationEvent`s.

    Typical lifecycle:

        monitor = DataQualityMonitor(
            strategies=[GreatExpectationsStrategy(), ToxicityBoundsStrategy()],
            observers=[PrometheusObserver(), LoggingObserver()]
        )
        monitor.process(record)  # Returns aggregated success bool
    """

    def __init__(
        self,
        strategies: Sequence[BaseValidationStrategy] | None = None,
        observers: Sequence[EventObserver] | None = None,
    ) -> None:
        self._strategies: Tuple[BaseValidationStrategy, ...] = (
            tuple(strategies) if strategies else (ToxicityBoundsStrategy(),)
        )
        self._observers: Tuple[EventObserver, ...] = (
            tuple(observers) if observers else (LoggingObserver(),)
        )

    # --------------------------------------------------------------------- #
    def process(self, record: EventRecord) -> bool:
        """
        Validate a single record using the configured strategies.

        Returns
        -------
        bool
            True if the record passes *all* strategies; False otherwise.
        """
        all_ok = True
        for strat in self._strategies:
            result = strat.validate(record)
            event = ValidationEvent(record=record, result=result)

            # Notify subscribers
            for observer in self._observers:
                try:
                    observer.notify(event)
                except Exception:  # pragma: no cover – isolating failures
                    logger.exception("Observer %s crashed", observer.__class__.__name__)

            if not result.ok:
                all_ok = False

        return all_ok


# --------------------------------------------------------------------------- #
# Convenience helpers
# --------------------------------------------------------------------------- #


def json_stream_reader(
    source: Iterable[str] | Generator[str, None, None],
) -> Generator[EventRecord, None, None]:
    """
    Lazily parse an iterable/stream of JSON lines into validated EventRecord objects.

    Invalid rows are skipped but logged; backpressure is delegated to caller.
    """
    for raw in source:
        raw = raw.strip()
        if not raw:
            continue

        try:
            payload = json.loads(raw)
            yield EventRecord.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.error("Skipping invalid message: %s – %r", exc, raw)


def process_event_stream(
    raw_stream: Iterable[str] | Generator[str, None, None],
    monitor: Optional[DataQualityMonitor] = None,
) -> Generator[Tuple[EventRecord, bool], None, None]:
    """
    High-level generator that (1) parses JSON, (2) validates, (3) yields verdict.

    This function represents the Clean-Architecture *interface adapter*; it is
    agnostic to message bus / socket / kafka consumer.
    """
    monitor = monitor or DataQualityMonitor()
    for record in json_stream_reader(raw_stream):
        result = monitor.process(record)
        yield record, result


# --------------------------------------------------------------------------- #
# Context Manager – benchmark & graceful teardown
# --------------------------------------------------------------------------- #


class _StreamTimer:
    """Private context manager used by `__main__` demonstration."""

    def __enter__(self):  # noqa: D401
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ):
        took_ms = (time.perf_counter() - self._start) * 1000
        logger.info("Processed stream in %.2f ms", took_ms)


# --------------------------------------------------------------------------- #
# Inline usage example                                                       #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    # Initialize Sentry only when DSN provided
    if sentry_sdk and (dsn := os.getenv("SENTRY_DSN")):
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.05)

    # Synthetic JSONL dataset
    sample_stream = (
        json.dumps(  # noqa: WPS316
            {
                "event_id": f"id_{i}",
                "network": "twitter",
                "author_id": f"user_{i}",
                "text": "Hello world!",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
                "toxicity": 0.1 * (i % 4),
            }
        )
        for i in range(1, 11)
    )

    # Instantiate monitor with default strategies + observers
    dq_monitor = DataQualityMonitor(
        strategies=[ToxicityBoundsStrategy(max_toxicity=0.3)],
        observers=[LoggingObserver()],
    )

    # Run pipeline
    with _StreamTimer():
        for rec, verdict in process_event_stream(sample_stream, dq_monitor):
            logger.info(
                "Record %s -> %s", rec.event_id, "ACCEPT" if verdict else "REJECT"
            )
```