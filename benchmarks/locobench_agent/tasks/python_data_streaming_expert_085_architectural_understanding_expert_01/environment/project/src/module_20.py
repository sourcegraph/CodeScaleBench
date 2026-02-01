```python
"""
PulseStream Nexus – src/module_20.py
===================================

This module provides a **production-ready, yet framework-agnostic** ingestion
orchestrator that demonstrates several of PulseStream Nexus’ architectural
pillars:

* Strategy Pattern – interchangeable source adapters & transformation strategies
* Observer Pattern  – Prometheus/Grafana-ready metrics publishing
* Data Validation   – Great Expectations integration (optional)
* Scheduling        – CRON or interval-based job execution via APScheduler
* Error Handling    – granular, typed exceptions and dead-letter hand-off

The code is intentionally self-contained so that it can be **unit-tested in
isolation** from the rest of the platform while still exposing extension points
for real backend integrations (Kafka, Flink, etc.).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple, Type

# --------------------------------------------------------------------------- #
# Optional 3rd-party dependencies                                             #
# --------------------------------------------------------------------------- #
with contextlib.suppress(ImportError):
    from prometheus_client import Counter, Histogram, start_http_server  # type: ignore
with contextlib.suppress(ImportError):
    import great_expectations as ge  # type: ignore
with contextlib.suppress(ImportError):
    from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #
LOG_LEVEL = os.getenv("PULSENEX_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(process)d] %(levelname)-8s "
    "%(name)s - %(threadName)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("pulse.module_20")

# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #


class IngestionError(RuntimeError):
    """Base class for ingestion-related exceptions."""


class ValidationError(IngestionError):
    """Raised when Great Expectations validation fails."""


class TransformationError(IngestionError):
    """Raised when a transformation strategy fails."""


class PublishError(IngestionError):
    """Raised when publishing to a sink fails."""


# --------------------------------------------------------------------------- #
# Protocols & Abstract Base Classes                                           #
# --------------------------------------------------------------------------- #


class SourceAdapter(Protocol):
    """
    A SourceAdapter is responsible for fetching raw records from an upstream
    provider (REST API, WebSocket, Kafka topic, etc.).
    """

    name: str

    @abstractmethod
    def fetch(self) -> Iterable[Dict[str, Any]]:
        """Fetch raw records. Expected to be lightweight and non-blocking."""

    @property
    def is_streaming(self) -> bool:
        """
        Return True if the adapter produces an **infinite stream** that should
        be consumed until cancelled (e.g., Kafka consumer); False for
        collection-based sources.
        """
        return False  # sensible default


class TransformStrategy(Protocol):
    """
    A TransformStrategy converts a raw record into PulseStream’s *canonical
    event* schema: validated, enriched, and ready for downstream analytics.
    """

    @abstractmethod
    def transform(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Transform a single record. Must never mutate the input."""

    @property
    def name(self) -> str:  # pragma: no cover
        return self.__class__.__name__


class Observer(Protocol):
    """Simple Observer interface for publishing events (e.g., metrics)."""

    def update(self, event_name: str, payload: Dict[str, Any]) -> None: ...


# --------------------------------------------------------------------------- #
# Default Implementations                                                     #
# --------------------------------------------------------------------------- #
_SENTIMENT_CLASSES = ("positive", "neutral", "negative")


class NaiveSentimentStrategy:
    """
    A *toy* sentiment classifier that tags messages purely on keyword matches.
    Replace with spaCy / Transformers pipeline in production.
    """

    POSITIVE = ("love", "great", "awesome", "good")
    NEGATIVE = ("hate", "terrible", "awful", "bad")

    def transform(self, record: Dict[str, Any]) -> Dict[str, Any]:  # noqa: C901
        text = record.get("text", "")
        lowered = text.lower()
        sentiment: str
        if any(x in lowered for x in self.POSITIVE):
            sentiment = "positive"
        elif any(x in lowered for x in self.NEGATIVE):
            sentiment = "negative"
        else:
            sentiment = "neutral"

        transformed = {
            "id": record.get("id"),
            "author": record.get("user"),
            "created_at": record.get("created_at"),
            "network": record.get("network"),
            "text": text,
            "sentiment": sentiment,
        }
        logger.debug("Transformed record %s -> %s", record.get("id"), sentiment)
        return transformed

    @property
    def name(self) -> str:
        return "NaiveSentimentStrategy"


class StdOutObserver:
    """Fallback metrics observer that prints to stdout when Prometheus is absent."""

    def update(self, event_name: str, payload: Dict[str, Any]) -> None:
        logger.info("Observer event=%s payload=%s", event_name, payload)


# --------------------------------------------------------------------------- #
# Prometheus Metrics Setup                                                    #
# --------------------------------------------------------------------------- #

_DEFAULT_METRIC_PORT = int(os.getenv("PULSENEX_METRIC_PORT", "9201"))

if "prometheus_client" in sys.modules:
    # Label set kept small for cardinality safety.
    _INGEST_COUNTER = Counter(
        "psn_ingested_records_total",
        "Number of raw records successfully ingested",
        ["source"],
    )
    _VALIDATION_COUNTER = Counter(
        "psn_validated_records_total",
        "Number of records that passed data-quality validation",
        ["source"],
    )
    _TRANSFORM_HIST = Histogram(
        "psn_transform_duration_seconds",
        "Time spent transforming individual records",
        ["strategy"],
    )

    def _start_metrics() -> None:
        start_http_server(_DEFAULT_METRIC_PORT)
        logger.info("Prometheus metrics exposed on :%d", _DEFAULT_METRIC_PORT)

    METRICS_ENABLED = True
else:

    def _start_metrics() -> None:
        logger.warning("prometheus_client missing – metrics disabled")

    METRICS_ENABLED = False


# --------------------------------------------------------------------------- #
# Great Expectations Validation Helper                                        #
# --------------------------------------------------------------------------- #

_EXPECTATION_SUITE = "pulse_event_suite"


class DataValidator:
    """
    Delegate to Great Expectations to run a lightweight validation step on each
    transformed record. If GE is unavailable, this becomes a no-op.
    """

    def __init__(self) -> None:
        if "great_expectations" in sys.modules:
            self._ctx = ge.get_context()
            self._suite = self._ensure_suite()
        else:
            self._ctx = None
            self._suite = None

    def _ensure_suite(self):  # type: ignore
        try:
            return self._ctx.get_expectation_suite(_EXPECTATION_SUITE)
        except Exception:  # suite does not exist
            logger.warning("GE suite %s not found – creating skeletal suite", _EXPECTATION_SUITE)
            suite = self._ctx.create_expectation_suite(
                expectation_suite_name=_EXPECTATION_SUITE, overwrite_existing=True
            )
            # Minimal constraint (id non-null) for demonstration
            suite.add_expectation(expectation_type="expect_column_values_to_not_be_null", kwargs={"column": "id"})
            self._ctx.save_expectation_suite(suite)
            return suite

    def validate(self, record: Dict[str, Any]) -> bool:
        if not self._ctx:
            logger.debug("Great Expectations not installed – skipping validation")
            return True
        try:
            # run on in-memory JSON (pandas validator would be quicker for bulks)
            batch_request = ge.dataset.PandasDataset([record])  # type: ignore
            validator = self._ctx.get_validator(
                batch=batch_request,
                expectation_suite_name=_EXPECTATION_SUITE,
            )
            res = validator.validate()
            return res.success  # type: ignore
        except Exception as exc:
            logger.exception("Data validation error: %s", exc)
            raise ValidationError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Ingestion Orchestrator                                                      #
# --------------------------------------------------------------------------- #


class IngestionOrchestrator:
    """
    Coordinates fetching, transformation, validation, and observer dispatch in
    a *single* end-to-end flow.  Thread-safe and back-pressure aware (bounded
    internal queue).
    """

    MAX_QUEUE_SIZE = 10_000

    def __init__(
        self,
        source: SourceAdapter,
        transformer: TransformStrategy,
        observers: Sequence[Observer] | None = None,
        validator: Optional[DataValidator] = None,
        max_retries: int = 5,
        retry_backoff: float = 1.5,
    ) -> None:
        self.source = source
        self.transformer = transformer
        self.observers: Tuple[Observer, ...] = tuple(observers or [StdOutObserver()])
        self.validator = validator or DataValidator()
        self._buffer: "queue.Queue[Dict[str, Any]]" = queue.Queue(self.MAX_QUEUE_SIZE)
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def start(self) -> None:
        """
        Kick off background threads: one producer fetching from source and
        one consumer handling transformation & validation.
        """
        logger.info("Starting orchestrator for %s w/ strategy %s", self.source.name, self.transformer.name)
        self._threads = [
            threading.Thread(target=self._produce, name=f"{self.source.name}-producer", daemon=True),
            threading.Thread(target=self._consume, name=f"{self.source.name}-consumer", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self, timeout: float = 10.0) -> None:
        logger.info("Graceful shutdown initiated (timeout=%.1fs)…", timeout)
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=timeout)
        logger.info("Orchestrator shut down successfully")

    # --------------------------------------------------------------------- #
    # Internal Worker Threads                                               #
    # --------------------------------------------------------------------- #

    def _produce(self) -> None:
        """Continuously fetch from the source adapter and put into buffer."""
        logger.debug("Producer thread started")
        retries = 0
        while not self._stop_event.is_set():
            try:
                for record in self.source.fetch():
                    self._buffer.put(record, block=True, timeout=1.0)
                    if METRICS_ENABLED:
                        _INGEST_COUNTER.labels(source=self.source.name).inc()
                retries = 0  # reset on success
            except Exception as exc:
                logger.exception("Producer error: %s", exc)
                retries += 1
                if retries > self.max_retries:
                    logger.critical("Producer exceeded max retries – terminating orchestrator")
                    self._stop_event.set()
                    break
                backoff = self.retry_backoff ** retries
                logger.warning("Retrying in %.1fs (attempt %d/%d)", backoff, retries, self.max_retries)
                time.sleep(backoff)

    def _consume(self) -> None:
        """Transform, validate, and notify observers."""
        logger.debug("Consumer thread started")
        while not self._stop_event.is_set() or not self._buffer.empty():
            try:
                record = self._buffer.get(block=True, timeout=1.0)
            except queue.Empty:
                continue

            start_time = time.perf_counter()
            try:
                transformed = self.transformer.transform(record)
            except Exception as exc:
                logger.exception("Transformation error for record=%s: %s", record.get("id"), exc)
                self._notify_observers("transformation_error", {"error": str(exc), "record": record})
                continue
            finally:
                duration = time.perf_counter() - start_time
                if METRICS_ENABLED:
                    _TRANSFORM_HIST.labels(strategy=self.transformer.name).observe(duration)

            # Validate
            try:
                if self.validator.validate(transformed):
                    if METRICS_ENABLED:
                        _VALIDATION_COUNTER.labels(source=self.source.name).inc()
                else:
                    raise ValidationError("Validation failed without explicit GE errors")
            except ValidationError as exc:
                logger.warning("Record failed validation: %s", exc)
                self._notify_observers("validation_failure", {"error": str(exc), "record": transformed})
                continue

            # Publish successful event
            self._notify_observers("record_processed", {"record": transformed})

    # --------------------------------------------------------------------- #
    # Observer Dispatch                                                     #
    # --------------------------------------------------------------------- #

    def _notify_observers(self, event_name: str, payload: Dict[str, Any]) -> None:
        for obs in self.observers:
            with contextlib.suppress(Exception):
                obs.update(event_name, payload)


# --------------------------------------------------------------------------- #
# Dummy Source Adapters (for demo & unit tests)                               #
# --------------------------------------------------------------------------- #


class StaticFileAdapter:
    """
    Reads a newline-separated JSON file containing social messages (one per
    line) and yields dictionaries.
    """

    name = "static_file"

    def __init__(self, path: str) -> None:
        self.path = path

    def fetch(self) -> Iterable[Dict[str, Any]]:
        logger.debug("Loading static file from %s", self.path)
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning("Skipping malformed JSON line: %s", exc)
        except FileNotFoundError as exc:
            logger.error("Static file not found: %s", exc)
            raise


class SyntheticStreamAdapter:
    """
    Generates an infinite stream of *fake* social events for load testing and
    local development.
    """

    name = "synthetic_stream"

    POS_MSGS = ("I love this!", "This is great", "Awesome work", "Good vibes only")
    NEG_MSGS = ("I hate this", "Terrible bug", "Awful experience", "Bad practice")

    def __init__(self, interval: float = 0.05) -> None:
        self.interval = interval
        self.counter = 0

    @property
    def is_streaming(self) -> bool:
        return True

    def fetch(self) -> Iterable[Dict[str, Any]]:
        import random
        while True:
            self.counter += 1
            msg_pool = self.POS_MSGS + self.NEG_MSGS
            text = random.choice(msg_pool)
            yield {
                "id": f"synth-{self.counter}",
                "user": f"user_{random.randint(1, 500)}",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "network": "synthetic",
                "text": text,
            }
            time.sleep(self.interval)


# --------------------------------------------------------------------------- #
# APScheduler Integration (optional)                                          #
# --------------------------------------------------------------------------- #

def _schedule_orchestrator(orch: IngestionOrchestrator, cron: str | None = None) -> None:
    """
    Helper to schedule the orchestrator start/stop cycle via APScheduler. When
    `cron` is None, starts the orchestrator immediately without scheduling.
    """
    if "apscheduler.schedulers.background" not in sys.modules:
        logger.warning("APScheduler not installed – running orchestrator immediately")
        orch.start()
        return

    scheduler = BackgroundScheduler(daemon=True)
    if cron:
        # Cron expression example: "0 * * * *"  (top of every hour)
        scheduler.add_job(lambda: orch.start(), trigger="cron", args=[], id="ingestion_start", **_cron_to_kwargs(cron))
        logger.info("Orchestrator scheduled via CRON='%s'", cron)
    else:
        scheduler.add_job(lambda: orch.start(), trigger="date", run_date=datetime.utcnow())
        logger.info("Orchestrator scheduled to run once now")

    # Ensure shutdown on process exit
    def _sigterm(_signo, _frame) -> None:  # noqa: D401
        logger.info("SIGTERM caught – shutting down scheduler & orchestrator")
        scheduler.shutdown(wait=False)
        orch.stop()

    signal.signal(signal.SIGTERM, _sigterm)
    scheduler.start()


def _cron_to_kwargs(cron_expr: str) -> Dict[str, str]:
    fields = cron_expr.split()
    if len(fields) != 5:
        raise ValueError("CRON expression must have 5 fields (min hour day month dow)")
    return dict(minute=fields[0], hour=fields[1], day=fields[2], month=fields[3], day_of_week=fields[4])


# --------------------------------------------------------------------------- #
# CLI Entrypoint                                                              #
# --------------------------------------------------------------------------- #

def _parse_argv(argv: List[str]) -> Dict[str, Any]:
    """Very small argparse replacement to keep dependencies light."""
    import argparse

    parser = argparse.ArgumentParser(description="PulseStream Nexus – Ingestion CLI")
    parser.add_argument("--source-file", help="Path to newline-delimited JSON file")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic stream source")
    parser.add_argument("--cron", help="CRON schedule for periodic ingestion job")
    parser.add_argument("--run-seconds", type=int, default=30, help="Run orchestrator for N seconds")
    parser.add_argument("--metrics", action="store_true", help="Expose Prometheus metrics on /metrics")
    return vars(parser.parse_args(argv))


def run_cli(argv: Optional[List[str]] = None) -> None:  # pragma: no cover
    argv = argv or sys.argv[1:]
    cfg = _parse_argv(argv)

    if cfg["metrics"]:
        _start_metrics()

    # Pick source adapter
    if cfg["source_file"]:
        source: SourceAdapter = StaticFileAdapter(cfg["source_file"])
    elif cfg["synthetic"]:
        source = SyntheticStreamAdapter()
    else:
        logger.error("You must specify either --source-file or --synthetic")
        sys.exit(1)

    # Build orchestrator
    orchestrator = IngestionOrchestrator(
        source=source,
        transformer=NaiveSentimentStrategy(),
        observers=[StdOutObserver()],
    )

    # Attach to scheduler or run immediately
    _schedule_orchestrator(orchestrator, cfg["cron"])

    # Run until keyboard interrupt or configured timeout
    end_time = datetime.utcnow() + timedelta(seconds=cfg["run_seconds"])
    try:
        while datetime.utcnow() < end_time:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received – shutting down")
    finally:
        orchestrator.stop()


if __name__ == "__main__":  # pragma: no cover
    run_cli()
```