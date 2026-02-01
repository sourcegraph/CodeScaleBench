```python
"""
PulseStream Nexus – Core Stream Dispatcher & Validation Utilities
================================================================

This module provides three production-ready building blocks that are reused
across multiple micro-services inside the PulseStream Nexus ecosystem:

1. SchemaValidator
   ----------------
   A lightweight wrapper around Great Expectations that performs runtime
   validation of incoming social-network events.  The validator is completely
   optional at runtime – if Great Expectations is not available the system
   will gracefully degrade to *pass-through* mode, emitting a structured
   warning so that operators are aware of the lack of validation guarantees.

2. MetricCollector
   ---------------
   Prometheus metrics suitable for high-volume event streaming use-cases.
   All metrics are automatically namespaced and can be disabled if the
   `prometheus_client` package is missing or the environment variable
   `PSN_DISABLE_METRICS` is set to `"1"`.

3. StreamDispatcher
   ----------------
   A thread-safe Observer/Publisher implementation that fans out validated
   events to registered observers.  Observers are *weakly referenced* in
   order to prevent accidental memory leaks in long-lived JVM-style services.
   The dispatcher is intentionally framework-agnostic and can be embedded in
   asyncio, Trio or plain threading deployments.

The implementation follows the PulseStream Nexus Clean Architecture
guidelines – core business rules live in this module, completely independent
from specific IO frameworks (Kafka, HTTP, gRPC, etc.).

Author: PulseStream Nexus core team
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import weakref
from dataclasses import dataclass
from queue import Queue, Empty
from typing import Any, Dict, Iterable, List, Protocol, Union

# --------------------------------------------------------------------------- #
# Optional Dependencies – best-effort import
# --------------------------------------------------------------------------- #

try:  # Great Expectations is optional at runtime
    import great_expectations as gx
    from great_expectations.core import ExpectationSuite
except ModuleNotFoundError:  # pragma: no cover
    gx = None
    ExpectationSuite = None  # type: ignore

try:  # Prometheus instrumentation is also optional
    from prometheus_client import Counter, Histogram
except ModuleNotFoundError:  # pragma: no cover
    Counter = Histogram = None  # type: ignore


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# --------------------------------------------------------------------------- #
# Public Protocols
# --------------------------------------------------------------------------- #


class EventObserver(Protocol):
    """
    Minimalistic Observer contract for event consumers.

    The interface purposefully maps 1-to-1 with the canonical Kafka message
    structure: a single dict **event** plus optional **metadata** (partition,
    topic, etc.) so that thin adapters can bridge between infrastructure and
    application code.
    """

    def handle_event(self, event: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> None:
        ...


# --------------------------------------------------------------------------- #
# Schema Validation
# --------------------------------------------------------------------------- #


class SchemaValidationError(RuntimeError):
    """Raised when an event fails validation."""

    def __init__(self, *, errors: List[str], event: Dict[str, Any]):
        super().__init__("Schema validation failed.")
        self.errors = errors
        self.event = event

    def __str__(self) -> str:
        return f"SchemaValidationError(errors={self.errors}, event={self.event})"


@dataclass(slots=True, frozen=True)
class SchemaValidator:
    """
    Runtime event validator backed by Great Expectations.

    Parameters
    ----------
    expectation_suite_path:
        Path to an on-disk `.json` or `.yml` Great Expectations
        ExpectationSuite.
    strict:
        If *True* (default) raise `SchemaValidationError` on any failure.
        If *False* validation errors will be logged and the event will be
        passed unchanged to downstream consumers.
    """

    expectation_suite_path: str
    strict: bool = True

    _suite: Union[ExpectationSuite, None] = None

    # The `__post_init__` is needed because we are using frozen dataclass with
    # pre-computed fields – we mutate via `object.__setattr__`.
    def __post_init__(self) -> None:
        if gx is None:  # Great Expectations not installed – skip validation
            logger.warning(
                "Great Expectations not available. All events will bypass schema validation."
            )
            return

        try:
            suite = gx.core.ExpectationSuite(expectation_suite_name="runtime_suite")
            suite = gx.core.ExpectationSuite(
                **gx.core.ExpectationSuite.load(expectation_suite_name="tmp").to_json_dict()
            )
        except Exception:  # pragma: no cover
            # Fallback to reading from file (json/yaml)
            suite = gx.core.ExpectationSuite(
                **gx.core.ExpectationSuite.load_from_json(self.expectation_suite_path)
            )

        object.__setattr__(self, "_suite", suite)
        logger.debug("Loaded expectation suite at '%s'.", self.expectation_suite_path)

    # --------------------------------------------------------------------- #
    # Business logic
    # --------------------------------------------------------------------- #

    def validate(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate *event* against the configured ExpectationSuite.

        Returns the original event if validation passes or validation is
        disabled. If validation fails and `strict=True`, a
        SchemaValidationError is raised; otherwise the error is logged and the
        event is returned unchanged.
        """
        if gx is None or self._suite is None:
            return event  # graceful pass-through

        batch = gx.core.Batch(
            data=[event],  # type: ignore[arg-type]
            expectation_suite=self._suite,
        )

        # Execute validations
        result = batch.validate()
        if not result["success"]:
            errors = [r["expectation_config"]["kwargs"] for r in result["results"] if not r["success"]]
            msg = f"Event failed validation: {errors}"
            if self.strict:
                raise SchemaValidationError(errors=[json.dumps(e) for e in errors], event=event)
            logger.warning(msg)
        return event


# --------------------------------------------------------------------------- #
# Prometheus Instrumentation
# --------------------------------------------------------------------------- #


class MetricCollector:
    """
    Lazily initialized Prometheus metrics.

    The class hides the Prometheus dependency behind a simple façade so that
    calling code can remain oblivious if the `prometheus_client` package is
    missing or metrics have been disabled through environment variable.
    """

    def __init__(self, namespace: str = "pulsestream_nexus"):
        self._enabled = (
            os.getenv("PSN_DISABLE_METRICS", "0") != "1" and Counter is not None
        )
        self._namespace = namespace
        if self._enabled:
            # Use rich cardinality labels only where necessary to keep TSDB
            # load manageable.
            self._events_counter = Counter(
                name="events_total",
                documentation="Total number of processed social events",
                namespace=namespace,
                labelnames=("status",),
            )
            self._latency_histogram = Histogram(
                name="event_latency_seconds",
                documentation="Latency between event ingestion and processing",
                namespace=namespace,
                buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 10),
            )
            logger.debug("Prometheus metrics enabled under namespace '%s'.", namespace)
        else:
            logger.info("Prometheus metrics disabled.")

    # --------------------------------------------------------------------- #
    # Public helpers
    # --------------------------------------------------------------------- #

    def inc_events(self, status: str) -> None:
        if self._enabled:
            self._events_counter.labels(status=status).inc()

    def observe_latency(self, latency_s: float) -> None:
        if self._enabled:
            self._latency_histogram.observe(latency_s)


# --------------------------------------------------------------------------- #
# Dispatcher (Observer Pattern)
# --------------------------------------------------------------------------- #


class StreamDispatcher:
    """
    Thread-safe dispatcher that validates events and notifies observers.

    Usage
    -----
    >>> dispatcher = StreamDispatcher(validator, metrics)
    >>> dispatcher.register(MyObserver())

    # Somewhere in your consumer loop:
    >>> for raw_event in kafka_consumer:
    ...     dispatcher.enqueue(raw_event.value, metadata=raw_event.headers)
    """

    def __init__(
        self,
        validator: SchemaValidator | None = None,
        metrics: MetricCollector | None = None,
        *,
        max_queue_size: int = 10_000,
        worker_threads: int = 2,
    ) -> None:
        self._validator = validator
        self._metrics = metrics or MetricCollector()
        self._event_queue: Queue[tuple[Dict[str, Any], Dict[str, Any] | None]] = Queue(max_queue_size)
        self._observers: "weakref.WeakSet[EventObserver]" = weakref.WeakSet()
        self._shutdown_event = threading.Event()
        self._threads: List[threading.Thread] = []

        for idx in range(worker_threads):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"psn-dispatcher-{idx}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
        logger.debug("StreamDispatcher initialized with %d worker threads.", worker_threads)

    # --------------------------------------------------------------------- #
    # Observer management
    # --------------------------------------------------------------------- #

    def register(self, observer: EventObserver) -> None:
        self._observers.add(observer)
        logger.debug("Observer %s registered. Total=%d", observer, len(self._observers))

    def unregister(self, observer: EventObserver) -> None:
        self._observers.discard(observer)
        logger.debug("Observer %s unregistered. Total=%d", observer, len(self._observers))

    # --------------------------------------------------------------------- #
    # Event ingestion
    # --------------------------------------------------------------------- #

    def enqueue(self, event: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> None:
        """
        Non-blocking enqueue. If the internal queue is full the oldest event
        will be dropped (in order to preserve near-real-time semantics).
        """
        try:
            self._event_queue.put_nowait((event, metadata))
            logger.debug("Event enqueued. Queue size=%d", self._event_queue.qsize())
        except Exception:  # pragma: no cover
            # Queue is full – drop oldest to make space
            try:
                _ = self._event_queue.get_nowait()
            except Empty:
                pass  # should not happen
            self._event_queue.put_nowait((event, metadata))
            logger.warning("Event queue full. Oldest event dropped.")

    # --------------------------------------------------------------------- #
    # Graceful shutdown
    # --------------------------------------------------------------------- #

    def stop(self, timeout: float | None = None) -> None:
        """
        Signal worker threads to terminate and wait (optional) until they have
        actually shut down.
        """
        logger.info("Stopping StreamDispatcher...")
        self._shutdown_event.set()
        for _ in self._threads:
            self._event_queue.put_nowait((None, None))  # type: ignore[arg-type]
        for t in self._threads:
            t.join(timeout=timeout)
        logger.info("StreamDispatcher stopped.")

    # --------------------------------------------------------------------- #
    # Internal – worker thread
    # --------------------------------------------------------------------- #

    def _worker_loop(self) -> None:  # pragma: no cover – difficult to unit-test
        while not self._shutdown_event.is_set():
            try:
                evt, metadata = self._event_queue.get(timeout=0.1)
            except Empty:
                continue

            if evt is None:  # Poison pill
                break

            start_ts = time.time()
            status = "ok"
            try:
                if self._validator is not None:
                    evt = self._validator.validate(evt)
                for obs in list(self._observers):
                    try:
                        obs.handle_event(evt, metadata)
                    except Exception:
                        status = "observer_error"
                        logger.exception("Observer raised an exception.")
                elapsed = time.time() - start_ts
                self._metrics.observe_latency(elapsed)
            except SchemaValidationError:
                status = "validation_failed"
                logger.exception("Event schema invalid.")
            except Exception:  # pragma: no cover
                status = "internal_error"
                logger.exception("Unhandled exception in dispatcher loop.")
            finally:
                self._metrics.inc_events(status=status)
                self._event_queue.task_done()


# --------------------------------------------------------------------------- #
# Convenience bootstrap helper
# --------------------------------------------------------------------------- #

def build_default_dispatcher(
    expectation_suite_path: str | None = None,
    *,
    strict_validation: bool = True,
) -> StreamDispatcher:
    """
    Factory helper used by most micro-services to obtain a fully configured
    dispatcher with sensible defaults.
    """
    validator = (
        SchemaValidator(expectation_suite_path, strict=strict_validation)
        if expectation_suite_path
        else None
    )
    metrics = MetricCollector()
    return StreamDispatcher(validator=validator, metrics=metrics)
```