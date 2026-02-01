"""
src/module_27.py
PulseStream Nexus – Data Streaming Platform

This module provides a production-grade validation and monitoring subsystem
that can be embedded inside both streaming and batch ETL pipelines. It adopts
a Strategy pattern for pluggable validation rules and an Observer pattern for
metric / alert propagation.  The design is framework-agnostic so that it can
run inside a Kafka consumer, an Apache Beam DoFn, or a Spark mapPartitions
function without modification.

Key features
------------
• Strategy pattern for schema, content, sentiment, and toxicity validation  
• Observer pattern for Prometheus metric emission and Sentry error capture  
• Thread-safe, low-overhead instrumentation suitable for high-throughput
  workloads  
• Clean-Architecture friendly – no external I/O in core business logic

External dependencies
---------------------
prometheus_client – runtime metrics  
sentry_sdk         – error reporting (optional, safe fallback)  

Both dependencies may be disabled at runtime to accommodate constrained
environments such as unit-test runners.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Protocol, Sequence

# --------------------------------------------------------------------------- #
# Optional Runtime Dependencies
# --------------------------------------------------------------------------- #
try:
    from prometheus_client import Counter, Histogram  # type: ignore
except ImportError:  # pragma: no cover – metrics entirely optional
    Counter = Histogram = None  # type: ignore

try:
    import sentry_sdk  # type: ignore
except ImportError:  # pragma: no cover – Sentry optional
    sentry_sdk = None


LOG = logging.getLogger("pulsestream.module_27")
LOG.addHandler(logging.NullHandler())


# --------------------------------------------------------------------------- #
# Data Model
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SocialEvent:
    """
    Canonical in-memory representation of a social interaction event.

    NOTE: The public interface should *never* be modified outside of a schema
    migration – downstream analytics jobs rely on these field names.
    """
    event_id: str
    network: str                    # twitter, reddit, etc.
    author_id: str
    body: str
    created_at: datetime
    raw_payload: Dict[str, Any] = field(repr=False, hash=False, default_factory=dict)


@dataclass(slots=True)
class ValidationResult:
    """
    Aggregate outcome of a validation strategy run.

    Attributes
    ----------
    is_valid : bool
        True when the check passes all conditions.
    errors : List[str]
        Human-readable error messages, empty when valid.
    """
    is_valid: bool
    errors: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # implicit truthiness
        return self.is_valid

    @classmethod
    def success(cls) -> "ValidationResult":
        return cls(True, [])

    @classmethod
    def failure(cls, *messages: str) -> "ValidationResult":
        return cls(False, list(messages))


class ValidationStrategy(Protocol):
    """
    Strategy interface for pluggable validation logic.
    """
    name: str

    def validate(self, event: SocialEvent) -> ValidationResult:  # pragma: no cover
        ...


# --------------------------------------------------------------------------- #
# Concrete Validation Strategies
# --------------------------------------------------------------------------- #
class NonEmptyBodyStrategy:
    """
    Rejects events where `body` is missing or empty.
    """
    name = "non_empty_body"

    def validate(self, event: SocialEvent) -> ValidationResult:
        if not event.body or not event.body.strip():
            return ValidationResult.failure("Body is empty.")
        return ValidationResult.success()


class CreatedAtNotFutureStrategy:
    """
    Ensures created_at does not lie in the future by more than tolerance
    seconds (clock skew safeguard).
    """

    def __init__(self, tolerance_seconds: int = 15) -> None:
        self.name = "created_at_not_future"
        self._tolerance = tolerance_seconds

    def validate(self, event: SocialEvent) -> ValidationResult:
        now = datetime.utcnow()
        delta = (event.created_at - now).total_seconds()
        if delta > self._tolerance:
            return ValidationResult.failure(
                f"created_at {event.created_at!s} is {delta:.1f}s in the future."
            )
        return ValidationResult.success()


class JSONSchemaStrategy:
    """
    Validates raw_payload against a user-supplied JSON schema.

    A lightweight implementation is provided to avoid heavyweight dependencies,
    but can be swapped with `jsonschema` or `great_expectations` in prod.
    """

    def __init__(self, schema: Dict[str, Any], name: str = "json_schema") -> None:
        self.name = name
        self._schema = schema
        self._required = tuple(schema.get("required", []))

    def validate(self, event: SocialEvent) -> ValidationResult:
        missing = [k for k in self._required if k not in event.raw_payload]
        if missing:
            return ValidationResult.failure(
                f"Missing required keys {missing!r} in raw_payload."
            )
        return ValidationResult.success()


# --------------------------------------------------------------------------- #
# Observer Pattern – Event Hooks
# --------------------------------------------------------------------------- #
class ValidationObserver(Protocol):
    """
    Observer interface for receiving validation event callbacks.
    """

    def on_success(self, event: SocialEvent, strategy: str) -> None:  # noqa: D401
        ...

    def on_failure(
        self, event: SocialEvent, strategy: str, errors: Sequence[str]
    ) -> None:
        ...


class PrometheusObserver:
    """
    Emits counter metrics for validation outcomes.

    Two counters are exported:
    • pulsestream_validation_success_total
    • pulsestream_validation_failure_total
    """

    def __init__(self) -> None:
        if Counter is None:
            LOG.debug("prometheus_client unavailable – metrics disabled.")
            self._enabled = False
            return

        self._enabled = True
        label_names = ("strategy", "network")
        self._success_counter: Counter = Counter(  # type: ignore[call-arg]
            "pulsestream_validation_success_total",
            "Validation successes",
            label_names,
        )
        self._failure_counter: Counter = Counter(  # type: ignore[call-arg]
            "pulsestream_validation_failure_total",
            "Validation failures",
            label_names,
        )
        self._latency_histogram: Histogram = Histogram(  # type: ignore[call-arg]
            "pulsestream_validation_latency_seconds",
            "Time spent running validation strategies",
            label_names,
            buckets=(0.0005, 0.001, 0.005, 0.01, 0.05, 0.1),
        )

    def on_success(self, event: SocialEvent, strategy: str) -> None:
        if not self._enabled:
            return
        self._success_counter.labels(strategy=strategy, network=event.network).inc()

    def on_failure(
        self, event: SocialEvent, strategy: str, errors: Sequence[str]
    ) -> None:
        if not self._enabled:
            return
        self._failure_counter.labels(strategy=strategy, network=event.network).inc()

    # Exposed as context manager for latency recording
    def track_latency(self, strategy: str, network: str):
        if not self._enabled:
            from contextlib import nullcontext

            return nullcontext()

        return self._latency_histogram.labels(strategy, network).time()


class SentryObserver:
    """
    Sends failed validations to Sentry with context information.
    """

    _dsn_placeholder = "https://fake@sentry.local/0"

    def __init__(self, dsn: str | None = None, sample_rate: float = 1.0) -> None:
        if sentry_sdk is None:
            LOG.warning("sentry_sdk unavailable – Sentry observer disabled.")
            self._enabled = False
            return

        self._enabled = True
        sentry_sdk.init(dsn or self._dsn_placeholder, traces_sample_rate=sample_rate)

    def on_success(self, event: SocialEvent, strategy: str) -> None:  # noqa: D401
        # successes are silent
        ...

    def on_failure(
        self, event: SocialEvent, strategy: str, errors: Sequence[str]
    ) -> None:
        if not self._enabled:
            return

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("network", event.network)
            scope.set_tag("strategy", strategy)
            scope.set_extra("event_id", event.event_id)
            scope.set_extra("errors", list(errors))
            sentry_sdk.capture_message("Validation failure", level="warning")


# --------------------------------------------------------------------------- #
# Validation Pipeline
# --------------------------------------------------------------------------- #
class ValidationPipeline:
    """
    Core engine that orchestrates validation strategies and notifies observers.

    The class is intentionally thread-safe; strategies are assumed to be
    stateless and therefore safely shared across threads.
    """

    __slots__ = ("_strategies", "_observers", "_lock")

    def __init__(
        self,
        strategies: Iterable[ValidationStrategy],
        observers: Iterable[ValidationObserver] | None = None,
    ) -> None:
        self._strategies: List[ValidationStrategy] = list(strategies)
        self._observers: List[ValidationObserver] = list(observers or [])
        self._lock = threading.RLock()

    # ---------------------------- Public API -------------------------------- #

    def add_strategy(self, strategy: ValidationStrategy) -> None:
        with self._lock:
            if any(s.name == strategy.name for s in self._strategies):
                raise ValueError(f"Strategy named '{strategy.name}' already exists.")
            self._strategies.append(strategy)

    def remove_strategy(self, name: str) -> None:
        with self._lock:
            self._strategies = [s for s in self._strategies if s.name != name]

    def register_observer(self, observer: ValidationObserver) -> None:
        with self._lock:
            self._observers.append(observer)

    def validate(
        self, events: Iterable[SocialEvent]
    ) -> Iterable[tuple[SocialEvent, bool]]:
        """
        Run all strategies on all events.

        Returns iterator of tuples (event, is_valid_overall).
        """
        for event in events:
            overall_valid = True
            for strategy in self._strategies:
                with self._maybe_latency(strategy, event):
                    result = strategy.validate(event)
                if result:
                    self._notify_success(event, strategy.name)
                else:
                    overall_valid = False
                    self._notify_failure(event, strategy.name, result.errors)
                    if LOG.isEnabledFor(logging.DEBUG):
                        LOG.debug(
                            "Validation failure %s – %s: %s",
                            event.event_id,
                            strategy.name,
                            result.errors,
                        )
            yield event, overall_valid

    # ------------------------ Internal utilities ---------------------------- #

    def _notify_success(self, event: SocialEvent, strategy: str) -> None:
        for observer in self._observers:
            try:
                observer.on_success(event, strategy)
            except Exception:  # pragma: no cover
                LOG.exception("Observer %s failed during on_success()", observer)

    def _notify_failure(
        self, event: SocialEvent, strategy: str, errors: Sequence[str]
    ) -> None:
        for observer in self._observers:
            try:
                observer.on_failure(event, strategy, errors)
            except Exception:  # pragma: no cover
                LOG.exception("Observer %s failed during on_failure()", observer)

    def _maybe_latency(self, strategy: ValidationStrategy, event: SocialEvent):
        """
        Acquire a Prometheus histogram context manager if available.
        """
        for obs in self._observers:
            if isinstance(obs, PrometheusObserver):
                return obs.track_latency(strategy.name, event.network)
        # Fallback null context
        from contextlib import nullcontext

        return nullcontext()


# --------------------------------------------------------------------------- #
# Example: Batch Validation Job Entry-Point
# --------------------------------------------------------------------------- #
def _parse_event(row: str) -> SocialEvent:
    """
    Helper for demo CLI: parse newline-delimited JSON lines into SocialEvent.
    """
    payload = json.loads(row)
    return SocialEvent(
        event_id=payload["id_str"],
        network=payload["network"],
        author_id=payload["author_id"],
        body=payload["body"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        raw_payload=payload,
    )


def run_batch_validation(
    infile: str,
    *,
    schema: Dict[str, Any],
    out_invalid_file: str | None = None,
) -> None:
    """
    Validates input newline-delimited JSON file and prints summary.

    In production this same code can be embedded into a Spark mapPartitions
    for large-scale processing.
    """
    start_ts = time.time()

    strategies: List[ValidationStrategy] = [
        NonEmptyBodyStrategy(),
        CreatedAtNotFutureStrategy(tolerance_seconds=30),
        JSONSchemaStrategy(schema),
    ]
    observers = [PrometheusObserver(), SentryObserver()]
    pipeline = ValidationPipeline(strategies, observers)

    invalid_out = open(out_invalid_file, "w") if out_invalid_file else None
    total, good = 0, 0

    with open(infile) as fp:
        for event, valid in pipeline.validate(map(_parse_event, fp)):
            total += 1
            if valid:
                good += 1
            else:
                if invalid_out:
                    invalid_out.write(json.dumps(event.raw_payload) + "\n")

    if invalid_out:
        invalid_out.close()

    LOG.info(
        "Validation complete – %ds elapsed. %d/%d events valid (%.2f%%).",
        time.time() - start_ts,
        good,
        total,
        0 if total == 0 else (good / total * 100),
    )


# --------------------------------------------------------------------------- #
# Command-line Interface (minimal)
# --------------------------------------------------------------------------- #
def _cli() -> None:  # pragma: no cover
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="PulseStream Nexus – Validate newline-delimited social events."
    )
    parser.add_argument("infile", type=Path, help="Input ND-JSON file")
    parser.add_argument(
        "--schema",
        type=Path,
        required=True,
        help="JSON schema file for raw_payload validation",
    )
    parser.add_argument(
        "--out-invalid",
        type=Path,
        help="File where invalid events are written (optional)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level))

    try:
        with open(args.schema) as fp:
            schema = json.load(fp)
    except FileNotFoundError:
        parser.error(f"Schema file not found: {args.schema!s}")
        sys.exit(1)

    run_batch_validation(
        infile=str(args.infile),
        schema=schema,
        out_invalid_file=str(args.out_invalid) if args.out_invalid else None,
    )


if __name__ == "__main__":  # pragma: no cover
    _cli()
