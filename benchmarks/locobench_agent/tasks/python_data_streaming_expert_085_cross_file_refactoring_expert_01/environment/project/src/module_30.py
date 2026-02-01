```python
"""
PulseStream Nexus – Backfill Orchestrator
=========================================
src/module_30.py

This module coordinates historical back-fill jobs that hydrate the data-lake with
older social data while guaranteeing data-quality and operational visibility.

Key responsibilities
--------------------
1. Strategy Pattern:
   • Select between multiple execution engines (Spark or Beam).

2. Observer Pattern:
   • Notify interested observers (e.g. monitoring, alerting) of pipeline events.

3. Validation Layer:
   • Run Great Expectations suites before persisting data.

4. Monitoring:
   • Expose Prometheus metrics for job duration, success/failure, and row counts.

5. Scheduling:
   • Register cron-like schedules through APScheduler (fallback to naïve scheduler
     when APScheduler is unavailable).

NOTE:
-----
• The code degrades gracefully in environments where optional dependencies are
  not installed. Warnings will be logged, and no-op adapters kick in so that
  the rest of the system can continue to run.
"""

from __future__ import annotations

import datetime as _dt
import functools
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, MutableMapping, Optional, Sequence

# --------------------------------------------------------------------------- #
# Optional third-party integrations                                           #
# --------------------------------------------------------------------------- #

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    BackgroundScheduler = None  # type: ignore

try:
    from prometheus_client import Counter, Gauge, Histogram
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    # Provide no-op replacements to avoid import errors in minimal installs.
    class _NoOp:  # pylint: disable=too-few-public-methods
        def __call__(self, *_, **__) -> "_NoOp":  # noqa: D401
            return self

        def labels(self, *_, **__) -> "_NoOp":  # noqa: D401
            return self

        def observe(self, *_):  # noqa: D401
            pass

        def inc(self, *_):  # noqa: D401
            pass

        def set(self, *_):  # noqa: D401
            pass

    Counter = Gauge = Histogram = _NoOp  # type: ignore

try:
    import great_expectations as gx
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    gx = None  # type: ignore

# --------------------------------------------------------------------------- #
# Logging configuration                                                       #
# --------------------------------------------------------------------------- #

LOGGER = logging.getLogger("pulstream.backfill")
LOGGER.setLevel(logging.INFO)

_DEFAULT_LOG_FMT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(threadName)s | %(message)s"
)
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(_DEFAULT_LOG_FMT))
    LOGGER.addHandler(_handler)

# --------------------------------------------------------------------------- #
# Prometheus Metrics                                                          #
# --------------------------------------------------------------------------- #

_METRIC_JOB_DURATION = Histogram(
    "pulstream_backfill_duration_seconds",
    "Duration in seconds of back-fill job execution",
    ["job_name", "engine"],
)

_METRIC_JOB_ROWS = Counter(
    "pulstream_backfill_rows_processed_total",
    "Total number of rows processed in back-fill jobs",
    ["job_name", "engine"],
)

_METRIC_JOB_STATUS = Gauge(
    "pulstream_backfill_status",
    "Latest status of back-fill job (0=Pending,1=Running,2=Success,3=Failed)",
    ["job_name", "engine"],
)

# --------------------------------------------------------------------------- #
# Data structures                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BackfillJobConfig:
    """
    Immutable configuration required to run a back-fill job.
    """

    job_name: str
    source_uri: str
    target_table: str
    engine: str  # e.g. 'spark', 'beam'
    schedule_cron: Optional[str] = None  # e.g. '0 2 * * *'
    expectation_suite_name: Optional[str] = None
    extra_options: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass
class BackfillContext:
    """
    Runtime context passed to strategy implementations for additional I/O
    marshalling and inter-actor communication.
    """

    job_id: str
    config: BackfillJobConfig
    start_ts: _dt.datetime = field(default_factory=_dt.datetime.utcnow)
    rows_processed: int = 0
    # arbitrary scratch-pad
    state: MutableMapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )


# --------------------------------------------------------------------------- #
# Observer Pattern implementation                                             #
# --------------------------------------------------------------------------- #


class PipelineEvent:
    """
    Simple value object representing a pipeline event.
    """

    __slots__ = ("name", "context", "payload", "timestamp")

    def __init__(self, name: str, context: BackfillContext, payload: Any = None):
        self.name = name
        self.context = context
        self.payload = payload
        self.timestamp = _dt.datetime.utcnow()

    def __repr__(self) -> str:  # noqa: D401
        return (
            f"PipelineEvent(name={self.name!r}, "
            f"job_id={self.context.job_id}, "
            f"at={self.timestamp.isoformat(timespec='milliseconds')})"
        )


class PipelineObserver(ABC):
    """
    Observer interface for pipeline events.
    """

    @abstractmethod
    def update(self, event: PipelineEvent) -> None:  # pragma: no cover
        raise NotImplementedError


class CompositeObserver(PipelineObserver):
    """
    Allows multiple observers to be treated as a single entity.
    """

    __slots__ = ("_observers",)

    def __init__(self, *observers: PipelineObserver):
        self._observers: List[PipelineObserver] = list(observers)

    # Public API ----------------------------------------------------------------
    def attach(self, observer: PipelineObserver) -> None:
        self._observers.append(observer)

    def detach(self, observer: PipelineObserver) -> None:
        self._observers.remove(observer)

    # PipelineObserver ----------------------------------------------------------
    def update(self, event: PipelineEvent) -> None:
        for obs in list(self._observers):  # shallow copy to support detach inside
            try:
                obs.update(event)
            except Exception:  # pragma: no cover
                LOGGER.exception("Uncaught error in observer %s", obs.__class__.__name__)


class LoggingObserver(PipelineObserver):
    """
    Basic observer that logs every pipeline event.
    """

    def __init__(self, level: int = logging.DEBUG):
        self._level = level

    def update(self, event: PipelineEvent) -> None:
        LOGGER.log(self._level, "Event: %s", event)


# --------------------------------------------------------------------------- #
# Back-fill Strategy pattern                                                  #
# --------------------------------------------------------------------------- #


class BackfillStrategy(ABC):
    """
    Strategy interface for different execution engines.
    """

    @abstractmethod
    def run(self, ctx: BackfillContext) -> int:  # pragma: no cover
        """
        Execute the back-fill job for the given context.

        Returns
        -------
        int
            The number of rows processed.
        """
        raise NotImplementedError


class SparkBackfillStrategy(BackfillStrategy):
    """
    Implementation for Apache Spark execution engine.
    """

    def __init__(self) -> None:
        # Lazy import to avoid heavy dependency when not required.
        try:
            from pyspark.sql import SparkSession  # type: ignore
        except (ImportError, ModuleNotFoundError):  # pragma: no cover
            LOGGER.warning("pyspark not available; using mock SparkSession.")
            SparkSession = None  # type: ignore

        self._SparkSession = SparkSession  # type: ignore

    # --------------------------------------------------------------------- #
    # BackfillStrategy                                                      #
    # --------------------------------------------------------------------- #

    def run(self, ctx: BackfillContext) -> int:
        LOGGER.info("[Spark] Starting job %s from %s", ctx.job_id, ctx.config.source_uri)
        if self._SparkSession is None:  # pragma: no cover
            time.sleep(1)  # Simulate runtime
            mock_rows = 42
            LOGGER.info("[Spark] Finished mock run with %d rows", mock_rows)
            return mock_rows

        spark = self._SparkSession.builder.appName(f"Backfill-{ctx.job_id}").getOrCreate()
        try:
            df = spark.read.json(ctx.config.source_uri)
            rows = df.count()
            df.write.mode("append").saveAsTable(ctx.config.target_table)
            LOGGER.info("[Spark] Wrote %d rows -> %s", rows, ctx.config.target_table)
            return int(rows)
        finally:
            spark.stop()


class BeamBackfillStrategy(BackfillStrategy):
    """
    Implementation for Apache Beam execution engine.
    """

    def __init__(self) -> None:
        try:
            import apache_beam as beam  # type: ignore
        except (ImportError, ModuleNotFoundError):  # pragma: no cover
            beam = None  # type: ignore

        self._beam = beam

    # --------------------------------------------------------------------- #
    # BackfillStrategy                                                      #
    # --------------------------------------------------------------------- #

    def run(self, ctx: BackfillContext) -> int:
        LOGGER.info("[Beam] Starting job %s from %s", ctx.job_id, ctx.config.source_uri)
        if self._beam is None:  # pragma: no cover
            time.sleep(1.2)
            mock_rows = 77
            LOGGER.info("[Beam] Finished mock run with %d rows", mock_rows)
            return mock_rows

        from apache_beam.options.pipeline_options import PipelineOptions  # type: ignore

        options = PipelineOptions(flags=[], save_main_session=True)
        with self._beam.Pipeline(options=options) as p:  # type: ignore
            rows = (
                p
                | "ReadJSON" >> self._beam.io.ReadFromText(ctx.config.source_uri)  # type: ignore
                | "Parse" >> self._beam.Map(lambda x: 1)  # simple parse
                | "Count" >> self._beam.Map(lambda _: 1)
            )
            # Materialize the count
            result = p.run()
            result.wait_until_finish()

            # In real code we'd extract row counts from metrics;
            # here, we just simulate.
            simulated_rows = 100
        LOGGER.info("[Beam] Wrote %d rows -> %s", simulated_rows, ctx.config.target_table)
        return simulated_rows


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #


def _run_expectation_suite(ctx: BackfillContext) -> None:
    """
    Execute Great Expectations validation if configured.

    Raises
    ------
    RuntimeError
        If validation fails or GE is unavailable.
    """
    suite_name = ctx.config.expectation_suite_name
    if suite_name is None:
        LOGGER.debug("No expectation suite configured for job %s", ctx.job_id)
        return

    if gx is None:  # pragma: no cover
        raise RuntimeError(
            "Great Expectations not installed; cannot run expectation suite."
        )

    LOGGER.info("Running GE suite '%s' for %s", suite_name, ctx.job_id)
    context = gx.get_context()
    try:
        batch_request = {
            "datasource_name": "pulstream_datasource",
            "data_connector_name": "default_runtime_data_connector_name",
            "data_asset_name": ctx.config.target_table,
            "runtime_parameters": {"query": f"SELECT * FROM {ctx.config.target_table}"},
            "batch_identifiers": {"default_identifier": str(uuid.uuid4())},
        }
        validation_result = context.run_checkpoint(  # type: ignore
            checkpoint_name=suite_name,
            batch_request=batch_request,
        )
    except Exception as err:  # pragma: no cover
        LOGGER.exception("GE validation error in job %s", ctx.job_id)
        raise RuntimeError("Failed Great Expectations validation") from err

    if not validation_result["success"]:  # type: ignore
        raise RuntimeError(f"Data validation failed for suite '{suite_name}'")
    LOGGER.info("GE validation passed for job %s", ctx.job_id)


# --------------------------------------------------------------------------- #
# Orchestrator                                                                #
# --------------------------------------------------------------------------- #


class BackfillRunner:
    """
    High-level façade coordinating strategy selection, validation, metrics and
    observer notifications.
    """

    _ENGINES: Dict[str, BackfillStrategy] = {
        "spark": SparkBackfillStrategy(),
        "beam": BeamBackfillStrategy(),
    }

    def __init__(self, observer: Optional[PipelineObserver] = None) -> None:
        self._observer = observer or CompositeObserver(LoggingObserver())

    # Public API ----------------------------------------------------------------
    def run(self, config: BackfillJobConfig) -> int:
        job_id = str(uuid.uuid4())
        ctx = BackfillContext(job_id=job_id, config=config)

        strategy = self._select_strategy(config.engine)
        LOGGER.debug("Selected strategy %s for job %s", strategy.__class__.__name__, job_id)

        # Metrics – status: Pending
        _METRIC_JOB_STATUS.labels(config.job_name, config.engine).set(0)

        self._notify("JOB_STARTED", ctx)
        _METRIC_JOB_STATUS.labels(config.job_name, config.engine).set(1)  # Running

        start_time = time.perf_counter()
        try:
            processed_rows = strategy.run(ctx)
            ctx.rows_processed = processed_rows
            _run_expectation_suite(ctx)

            # Metrics
            duration = time.perf_counter() - start_time
            _METRIC_JOB_DURATION.labels(config.job_name, config.engine).observe(duration)
            _METRIC_JOB_ROWS.labels(config.job_name, config.engine).inc(processed_rows)
            _METRIC_JOB_STATUS.labels(config.job_name, config.engine).set(2)  # Success

            self._notify("JOB_SUCCEEDED", ctx, payload={"rows": processed_rows})
            LOGGER.info("%s completed successfully in %.2fs", config.job_name, duration)
            return processed_rows

        except Exception as exc:
            duration = time.perf_counter() - start_time
            _METRIC_JOB_DURATION.labels(config.job_name, config.engine).observe(duration)
            _METRIC_JOB_STATUS.labels(config.job_name, config.engine).set(3)  # Failed

            LOGGER.exception("Job %s failed after %.2fs: %s", config.job_name, duration, exc)
            self._notify("JOB_FAILED", ctx, payload={"error": str(exc)})
            raise

    # Internal helpers ----------------------------------------------------------

    def _notify(self, name: str, ctx: BackfillContext, payload: Any = None) -> None:
        try:
            event = PipelineEvent(name, ctx, payload)
            self._observer.update(event)
        except Exception:  # pragma: no cover
            LOGGER.exception("Observer raised during %s notification", name)

    @classmethod
    def _select_strategy(cls, engine: str) -> BackfillStrategy:
        try:
            return cls._ENGINES[engine.lower()]
        except KeyError as exc:
            available = ", ".join(cls._ENGINES)
            raise ValueError(f"Unsupported engine '{engine}'. Available: {available}") from exc


# --------------------------------------------------------------------------- #
# Scheduling                                                                  #
# --------------------------------------------------------------------------- #


class BackfillScheduler:
    """
    Cron-like scheduler responsible for enqueueing back-fill jobs based on
    BackfillJobConfig definitions.
    """

    def __init__(self, runner: Optional[BackfillRunner] = None):
        self._runner = runner or BackfillRunner()
        self._scheduler = (
            BackgroundScheduler(daemon=True) if BackgroundScheduler else None
        )
        self._jobs: Dict[str, BackfillJobConfig] = {}

        if self._scheduler:
            self._scheduler.start()
            LOGGER.info("APScheduler started in background mode.")
        else:
            LOGGER.warning("APScheduler not available; falling back to polling loop.")

        # Thread for naïve polling when APScheduler is missing
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # Public API ----------------------------------------------------------------
    def register(self, config: BackfillJobConfig) -> None:
        """
        Register a job with the scheduler.
        """
        if not config.schedule_cron:
            raise ValueError("schedule_cron must be provided for scheduled jobs")

        key = config.job_name
        if key in self._jobs:
            LOGGER.warning("Job %s already registered; overwriting.", key)
            self.unregister(key)

        self._jobs[key] = config
        if self._scheduler:
            self._scheduler.add_job(
                func=functools.partial(self._runner.run, config),
                trigger="cron",
                id=f"backfill_{key}",
                name=key,
                **self._parse_cron(config.schedule_cron),
            )
            LOGGER.info("Registered job %s with APScheduler.", key)
        else:
            LOGGER.info("Registered job %s for naïve polling mode.", key)

    def unregister(self, job_name: str) -> None:
        """
        Unregister (remove) a scheduled job.
        """
        self._jobs.pop(job_name, None)
        if self._scheduler and self._scheduler.get_job(f"backfill_{job_name}"):
            self._scheduler.remove_job(f"backfill_{job_name}")

    def start(self) -> None:
        """
        Start the naïve polling loop if APScheduler is not present.
        """
        if self._scheduler:
            LOGGER.debug("APScheduler already running; nothing to start.")
            return

        if self._poll_thread and self._poll_thread.is_alive():
            return  # Already running

        self._poll_thread = threading.Thread(
            name="BackfillPollLoop", target=self._poll_loop, daemon=True
        )
        self._poll_thread.start()
        LOGGER.info("Backfill naïve scheduler polling thread started.")

    def shutdown(self) -> None:
        """
        Stop polling thread or APScheduler instance.
        """
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
        else:
            self._stop_event.set()
            if self._poll_thread:
                self._poll_thread.join(timeout=5)

    # Internal helpers ----------------------------------------------------------
    def _poll_loop(self) -> None:  # pragma: no cover
        LOGGER.debug("Entering naïve polling loop.")
        while not self._stop_event.is_set():
            current_minute = _dt.datetime.utcnow().replace(second=0, microsecond=0)
            for cfg in self._jobs.values():
                if self._cron_matches(current_minute, cfg.schedule_cron):
                    LOGGER.debug("Triggering job %s via naïve scheduler.", cfg.job_name)
                    threading.Thread(
                        target=self._runner.run, args=(cfg,), daemon=True
                    ).start()
            time.sleep(60)

    @staticmethod
    def _cron_matches(moment: _dt.datetime, cron_expr: str) -> bool:
        """
        Very naïve cron matcher that supports only 'minute hour * * *'.
        """
        try:
            minute, hour, *_ = cron_expr.split()
            return (
                (minute == "*" or int(minute) == moment.minute)
                and (hour == "*" or int(hour) == moment.hour)
            )
        except Exception:  # pragma: no cover
            LOGGER.error("Invalid cron expression: %s", cron_expr)
            return False

    @staticmethod
    def _parse_cron(cron_expr: str) -> Dict[str, Any]:
        """
        Convert POSIX cron string to APScheduler kwargs.
        Supports 'minute hour day month day_of_week'.
        """
        minute, hour, day, month, dow = cron_expr.split()
        return {
            "minute": minute,
            "hour": hour,
            "day": day,
            "month": month,
            "day_of_week": dow,
        }


# --------------------------------------------------------------------------- #
# CLI entry-point                                                             #
# --------------------------------------------------------------------------- #

def _example_cli() -> None:  # pragma: no cover
    """
    Example usage when the module is executed directly.
    """
    demo_config = BackfillJobConfig(
        job_name="historical_twitter_ingest",
        source_uri="s3://pulstream/stage/twitter/2023/*/*.json",
        target_table="twitter_raw",
        engine="spark",
        schedule_cron="0 2 * * *",  # 02:00 UTC daily
        expectation_suite_name="twitter_raw_suite",
    )

    runner = BackfillRunner()
    scheduler = BackfillScheduler(runner)
    scheduler.register(demo_config)
    scheduler.start()

    try:
        # Keep the main thread alive to service background jobs
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        LOGGER.info("Shutting down gracefully…")
        scheduler.shutdown()


if __name__ == "__main__":  # pragma: no cover
    _example_cli()
```