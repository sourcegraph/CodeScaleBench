```python
"""
module_29.py

PulseStream Nexus – Batch & Streaming Orchestrator
==================================================

This module is responsible for registering, scheduling, and monitoring ETL/ELT
jobs executed inside the PulseStream Nexus platform.  Although the surrounding
project follows a Clean Architecture, this module lives in the _infrastructure_
layer because it coordinates frameworks (APScheduler, asyncio, Prometheus,
logging, etc.) in order to execute domain-level use-case interactors.

Key Features
------------
1. Dynamic job discovery via configuration files or imperative API.
2. Async-friendly scheduler based on APScheduler’s `AsyncIOScheduler`.
3. First-class observability: structured logging + optional Prometheus metrics.
4. Graceful shutdown & error handling through context management helpers.
5. Minimal dependencies—optional fallbacks when third-party libraries are
   unavailable (e.g., in unit-test mode).

Typical Usage
-------------
>>> from src.module_29 import SchedulerService, JobRegistry
>>> registry = JobRegistry()
>>> registry.register_job(name="hourly_backfill",
...                       cron="0 * * * *",
...                       coroutine=backfill_hourly_data)
>>> service = SchedulerService(registry)
>>> service.run_forever()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Dict, Final, List, Optional

# --------------------------------------------------------------------------- #
# Optional third-party imports
# --------------------------------------------------------------------------- #
_APSCHED_AVAILABLE: Final[bool]
_PROM_AVAILABLE: Final[bool]
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    _APSCHED_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    _APSCHED_AVAILABLE = False

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    _PROM_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    _PROM_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Configuration dataclasses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class JobConfig:
    """Configuration container for a single ETL/ELT job."""

    name: str
    cron: str
    coroutine: Callable[[], Awaitable[None]]
    description: str = ""
    retries: int = 3
    retry_backoff_seconds: int = 30
    timeout_seconds: Optional[int] = None

    def as_dict(self) -> Dict[str, str]:
        """Return a JSON-serialisable representation."""
        return {
            "name": self.name,
            "cron": self.cron,
            "description": self.description,
            "retries": str(self.retries),
            "retry_backoff_seconds": str(self.retry_backoff_seconds),
            "timeout_seconds": str(self.timeout_seconds or ""),
        }


# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #
_LOG_FORMAT: Final[str] = (
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)  # RFC 3339 compliant

logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
logger: Final = logging.getLogger("pulse.scheduler")


# --------------------------------------------------------------------------- #
# Prometheus metrics (initialized dynamically if possible)
# --------------------------------------------------------------------------- #
if _PROM_AVAILABLE:  # pragma: no cover
    JOB_EXECUTION_COUNT = Counter(
        "pulse_job_execution_total",
        "Total number of job executions.",
        ["job_name", "status"],
    )
    JOB_DURATION = Histogram(
        "pulse_job_duration_seconds",
        "Runtime of jobs in seconds.",
        ["job_name"],
        buckets=(
            0.1,
            0.5,
            1,
            2.5,
            5,
            10,
            30,
            60,
            120,
            300,
            600,
            1800,
            float("inf"),
        ),
    )
else:  # fallback no-op implementations
    class _NoOp:
        def labels(self, *_, **__):
            return self

        def inc(self, *_):
            pass

        def observe(self, *_):
            pass

    JOB_EXECUTION_COUNT = JOB_DURATION = _NoOp()  # type: ignore


# --------------------------------------------------------------------------- #
# Job Registry – keeps track of configured jobs
# --------------------------------------------------------------------------- #
class JobRegistry:
    """A registry that stores job configurations and offers discovery helpers."""

    def __init__(self) -> None:
        self._jobs: Dict[str, JobConfig] = {}

    # Public API ----------------------------------------------------------------
    def register_job(
        self,
        *,
        name: str,
        cron: str,
        coroutine: Callable[[], Awaitable[None]],
        description: str = "",
        retries: int = 3,
        retry_backoff_seconds: int = 30,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        """Register a coroutine as a scheduled job."""
        if name in self._jobs:
            raise ValueError(f"Job '{name}' already registered")

        self._jobs[name] = JobConfig(
            name=name,
            cron=cron,
            coroutine=coroutine,
            description=description,
            retries=retries,
            retry_backoff_seconds=retry_backoff_seconds,
            timeout_seconds=timeout_seconds,
        )
        logger.debug("Registered job: %s", name)

    def jobs(self) -> List[JobConfig]:
        """Return all registered jobs."""
        return list(self._jobs.values())

    def get(self, name: str) -> JobConfig:
        """Return a job config; raises KeyError if not found."""
        return self._jobs[name]

    # Convenience ----------------------------------------------------------------
    @classmethod
    def from_json(cls, file_path: str | os.PathLike[str]) -> "JobRegistry":
        """
        Build registry contents from a JSON file.

        Expected schema:::

            [
                {
                    "name": "hourly_foo",
                    "cron": "0 * * * *",
                    "module": "mod.path",
                    "callable": "main",
                    "description": "...",
                    "retries": 3
                },
                ...
            ]
        """
        registry = cls()
        with open(file_path, "r", encoding="utf-8") as fp:
            spec = json.load(fp)

        for job_spec in spec:
            module_name = job_spec["module"]
            callable_name = job_spec["callable"]
            try:
                module = __import__(module_name, fromlist=[callable_name])
                coroutine = getattr(module, callable_name)
            except (ImportError, AttributeError) as exc:
                logger.error(
                    "Failed importing %s.%s for job '%s': %s",
                    module_name,
                    callable_name,
                    job_spec["name"],
                    exc,
                )
                continue

            registry.register_job(
                name=job_spec["name"],
                cron=job_spec["cron"],
                coroutine=coroutine,
                description=job_spec.get("description", ""),
                retries=job_spec.get("retries", 3),
                retry_backoff_seconds=job_spec.get("retry_backoff_seconds", 30),
                timeout_seconds=job_spec.get("timeout_seconds"),
            )
        return registry


# --------------------------------------------------------------------------- #
# Helper decorators / utilities
# --------------------------------------------------------------------------- #
def _retry(
    retries: int, backoff_seconds: int
) -> Callable[[Callable[..., Awaitable[None]]], Callable[..., Awaitable[None]]]:
    """
    Decorator that retries a coroutine when an exception is raised.

    Metrics are emitted based on success or error outcome.
    """

    def decorator(
        coro: Callable[..., Awaitable[None]]
    ) -> Callable[..., Awaitable[None]]:
        @wraps(coro)
        async def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    start_time = datetime.now().timestamp()
                    result = await coro(*args, **kwargs)
                    JOB_EXECUTION_COUNT.labels(
                        job_name=coro.__name__, status="success"
                    ).inc()
                    JOB_DURATION.labels(job_name=coro.__name__).observe(
                        datetime.now().timestamp() - start_time
                    )
                    return result
                except Exception as exc:  # pylint: disable=broad-except
                    attempt += 1
                    JOB_EXECUTION_COUNT.labels(
                        job_name=coro.__name__, status="failure"
                    ).inc()
                    logger.exception(
                        "Job '%s' failed (attempt %d/%d): %s",
                        coro.__name__,
                        attempt,
                        retries,
                        exc,
                    )
                    if attempt >= retries:
                        logger.error(
                            "Job '%s' exhausted retry budget (%d)", coro.__name__, retries
                        )
                        raise
                    await asyncio.sleep(backoff_seconds)

        return wrapper

    return decorator


@asynccontextmanager
async def _timeout(
    seconds: Optional[int], job_name: str
):  # pragma: no cover – tested by behaviour
    """Async context that cancels if runtime exceeds `seconds`."""
    if seconds is None:
        yield
        return

    task = asyncio.current_task()
    if task is None:  # pragma: no cover
        yield
        return

    def _canceller():
        logger.warning("Job '%s' exceeded timeout (%ds)", job_name, seconds)
        task.cancel()

    loop = asyncio.get_event_loop()
    handle = loop.call_later(seconds, _canceller)
    try:
        yield
    finally:
        handle.cancel()


# --------------------------------------------------------------------------- #
# Scheduler Service
# --------------------------------------------------------------------------- #
class SchedulerService:
    """Manages lifecycle of the APScheduler instance and graceful shutdown."""

    def __init__(
        self,
        registry: JobRegistry,
        *,
        prom_port: int | None = 8001,
    ) -> None:
        if not _APSCHED_AVAILABLE:  # pragma: no cover
            raise RuntimeError(
                "APScheduler not installed; install `apscheduler[asyncio]`."
            )

        self._registry = registry
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._loop = asyncio.get_event_loop()

        if _PROM_AVAILABLE and prom_port:
            start_http_server(prom_port)
            logger.info("Prometheus metrics available at :%d", prom_port)

        self._register_signal_handlers()

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def start(self) -> None:
        """Start scheduler and register all jobs."""
        self._scheduler.start(paused=True)  # delay until after registration

        for job in self._registry.jobs():
            wrapped = _retry(job.retries, job.retry_backoff_seconds)(job.coroutine)

            async def _runner(job_cfg: JobConfig = job, func=wrapped):
                async with _timeout(job_cfg.timeout_seconds, job_cfg.name):
                    logger.info("→ Starting job '%s'", job_cfg.name)
                    await func()
                    logger.info("✓ Completed job '%s'", job_cfg.name)

            trigger = CronTrigger.from_crontab(job.cron)
            self._scheduler.add_job(
                _runner, trigger=trigger, id=job.name, name=job.description
            )
            logger.debug("Scheduled job '%s' with cron '%s'", job.name, job.cron)

        self._scheduler.resume()
        logger.info("Scheduler started with %d job(s)", len(self._registry.jobs()))

    def run_forever(self) -> None:
        """
        Convenience wrapper that starts the service and keeps the event loop
        alive until interruption.
        """
        self.start()
        logger.info("Press CTRL+C to exit.")
        self._loop.run_forever()

    def shutdown(self) -> None:
        """Shut down APScheduler and the underlying event loop gracefully."""
        async def _shutdown():
            logger.info("Shutdown initiated …")
            self._scheduler.shutdown(wait=False)
            tasks = [
                t
                for t in asyncio.all_tasks(loop=self._loop)
                if t is not asyncio.current_task(loop=self._loop)
            ]
            logger.debug("Cancelling %d pending tasks", len(tasks))
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._loop.stop()
            logger.info("Shutdown complete.")

        asyncio.run_coroutine_threadsafe(_shutdown(), loop=self._loop)

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #
    def _register_signal_handlers(self) -> None:
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                self._loop.add_signal_handler(sig, self.shutdown)
        except NotImplementedError:  # pragma: no cover – Windows / restricted env
            logger.warning("Signal handlers not supported on this platform.")


# --------------------------------------------------------------------------- #
# Example: When the module is executed directly, start scheduler with demo job
# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover
    async def _demo_job():
        await asyncio.sleep(1)
        logger.info("Hello from demo job: current time is %s", datetime.utcnow())

    registry = JobRegistry()
    registry.register_job(
        name="demo_minutely",
        cron="*/1 * * * *",
        coroutine=_demo_job,
        description="A demo job that runs every minute.",
        retries=2,
        retry_backoff_seconds=5,
        timeout_seconds=10,
    )
    service = SchedulerService(registry)
    service.run_forever()
```