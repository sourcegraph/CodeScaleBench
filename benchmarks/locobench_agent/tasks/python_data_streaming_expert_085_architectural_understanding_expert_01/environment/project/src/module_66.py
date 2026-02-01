```python
"""
src/module_66.py

This module hosts a generic—but production-ready—Streaming ETL pipeline
implementation that follows PulseStream Nexus’ Clean Architecture mandates.
It combines the Pipeline, Strategy, and Observer patterns to give callers
a fully-extensible building block that can be reused by ingestion or
back-fill micro-services alike.

Key features
------------
1.  Asynchronous event streaming (asyncio, back-pressure aware).
2.  Pluggable Extract / Transform / Load / Validate / Custom steps.
3.  Built-in JSON-Schema validation strategy (optional ‑ gracefully degrades
    if `jsonschema` is not installed).
4.  Observer hooks for out-of-band side-effects (metrics, logging, alerts).
5.  Prometheus counters & histograms (optional, dependency-free fallback).
6.  Resilient error handling with per-step failure isolation.

Usage example
-------------
>>> async def source():
...     for i in range(10):
...         yield {"id": i, "payload": "hello world"}
...
>>> async def sink(item: dict):
...     print("SINK:", item)
...
>>> from src.module_66 import StreamingETLPipeline, StepType, PipelineStep
>>>
>>> pipeline = StreamingETLPipeline(
...     steps=[
...         PipelineStep(
...             name="no_op_transform",
...             step_type=StepType.TRANSFORM,
...             coroutine=lambda evt: evt  # pass-through
...         )
...     ]
... )
>>> asyncio.run(pipeline.run(source(), sink))
SINK: {'id': 0, 'payload': 'hello world'}
...

NOTE:
-----
The pipeline does not own the event loop; that responsibility belongs to
the caller—typically a FastAPI, Faust, or plain asyncio service.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Deque,
    List,
    Optional,
    Protocol,
)

_LOGGER = logging.getLogger("pulsestream.pipeline")
logging.basicConfig(level=logging.INFO)

###############################################################################
# Optional third-party integrations                                            #
###############################################################################
with contextlib.suppress(ImportError):
    import prometheus_client  # type: ignore

    PROM_COUNTER = prometheus_client.Counter(
        "pulsestream_events_total",
        "Total events processed by the Streaming ETL pipeline",
        ["step", "status"],
    )
    PROM_DURATION = prometheus_client.Histogram(
        "pulsestream_step_duration_seconds",
        "Step execution time in seconds",
        ["step"],
        buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
    )
with contextlib.suppress(ImportError):
    import jsonschema  # type: ignore


###############################################################################
# Public API                                                                   #
###############################################################################
class Observer(Protocol):
    """
    Observer interface used to decouple side-effects (metrics, logging, etc.)
    from the core business logic.
    """

    async def update(self, event: dict, *, step: str) -> None:  # pragma: no cover
        ...


class StepType(str, Enum):
    """
    Logical step categories. While the pipeline treats every step the same,
    semantic tags help with metrics, introspection, and docs.
    """

    EXTRACT = "extract"
    VALIDATE = "validate"
    TRANSFORM = "transform"
    LOAD = "load"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class PipelineStep:
    """
    Immutable descriptor for a single ETL step.
    """

    name: str
    step_type: StepType
    coroutine: Callable[[dict], Awaitable[dict]]  # each step must be awaitable


class PipelineError(RuntimeError):
    """
    Wrapper exception so callers can catch *all* pipeline-related errors with a
    single `except`.
    """

    def __init__(self, message: str, *, step: str, original: Exception) -> None:
        super().__init__(message)
        self.step = step
        self.original = original


class CircularBuffer:
    """
    Thread-safe async circular buffer implementing basic back-pressure.

    The buffer leverages `asyncio.Condition` for coordination, ensuring that
    producers pause when the buffer is full and consumers pause when it is
    empty.
    """

    def __init__(self, max_size: int = 2048) -> None:
        self._buffer: Deque[dict] = deque(maxlen=max_size)
        self._condition = asyncio.Condition()

    async def put(self, item: dict) -> None:
        async with self._condition:
            while len(self._buffer) >= self._buffer.maxlen:  # pragma: no cover
                await self._condition.wait()
            self._buffer.append(item)
            self._condition.notify()

    async def get(self) -> dict:
        async with self._condition:
            while not self._buffer:
                await self._condition.wait()
            item = self._buffer.popleft()
            self._condition.notify()
            return item

    async def drain(self) -> None:
        async with self._condition:
            self._buffer.clear()
            self._condition.notify_all()


class StreamingETLPipeline:
    """
    Core orchestrator for near-real-time ETL. Steps execute sequentially for
    every event, but the pipeline itself can process multiple events
    concurrently depending on `concurrency`.

    Attributes
    ----------
    steps: List[PipelineStep]
        Ordered list of ETL steps.
    observers: List[Observer]
        Observer instances notified after each successful step.
    concurrency: int
        Amount of worker coroutines concurrently processing events.
    """

    def __init__(
        self,
        steps: List[PipelineStep],
        observers: Optional[List[Observer]] = None,
        *,
        concurrency: int = 5,
        queue_max_size: int = 4096,
    ) -> None:
        if not steps:
            raise ValueError("Pipeline must declare at least one step")
        self._steps = steps
        self._observers = observers or []
        self._concurrency = max(1, concurrency)
        self._queue: CircularBuffer = CircularBuffer(max_size=queue_max_size)
        _LOGGER.debug(
            "Pipeline created with %d steps & %d workers", len(steps), concurrency
        )

    # ---------------------------------------------------------------------#
    #                            Public methods                            #
    # ---------------------------------------------------------------------#

    async def run(
        self,
        source: AsyncIterator[dict],
        sink: Callable[[dict], Awaitable[None]],
        *,
        graceful_shutdown_secs: int = 3,
    ) -> None:
        """
        Entry-point for streaming execution.

        Parameters
        ----------
        source: AsyncIterator[dict]
            Upstream event source.
        sink: Callable[[dict], Awaitable[None]]
            Downstream consumer. Usually a Kafka or Pulsar producer.
        graceful_shutdown_secs: int, default=3
            Time allowed for workers to finish processing buffered events once
            the source is exhausted.
        """
        producer_task = asyncio.create_task(self._producer(source))
        worker_tasks = [
            asyncio.create_task(self._worker(sink)) for _ in range(self._concurrency)
        ]

        await producer_task  # blocks until the source iterator is exhausted

        # Drain phase
        _LOGGER.info("Source exhausted. Waiting up to %d sec for workers to finish.", graceful_shutdown_secs)
        try:
            await asyncio.wait_for(
                asyncio.gather(*worker_tasks), timeout=graceful_shutdown_secs
            )
        except asyncio.TimeoutError:
            _LOGGER.warning("Graceful shutdown timed-out; cancelling workers.")
            for task in worker_tasks:
                task.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
        finally:
            await self._queue.drain()

    # ------------------------------------------------------------------#
    #                        Pipeline composition                        #
    # ------------------------------------------------------------------#

    @staticmethod
    def make_json_schema_step(
        *, name: str, schema: dict, raise_on_error: bool = True
    ) -> PipelineStep:
        """
        Helper factory for JSON-Schema validation. Uses `jsonschema` if present,
        otherwise raises `RuntimeError` when called.

        Returns
        -------
        PipelineStep
            A ready-to-use validation step.
        """
        if "jsonschema" not in globals():
            raise RuntimeError(
                "jsonschema not available. Install with `pip install jsonschema`."
            )

        async def _validator(event: dict) -> dict:
            jsonschema.validate(event, schema)  # type: ignore
            return event

        return PipelineStep(
            name=name,
            step_type=StepType.VALIDATE,
            coroutine=_validator if raise_on_error else _safe_wrapper(_validator),
        )

    # ------------------------------------------------------------------#
    #                           Private methods                         #
    # ------------------------------------------------------------------#

    async def _producer(self, source: AsyncIterator[dict]) -> None:
        async for event in source:
            await self._queue.put(event)
        _LOGGER.debug("Producer finished streaming events.")

    async def _worker(self, sink: Callable[[dict], Awaitable[None]]) -> None:
        while True:
            try:
                event = await self._queue.get()
            except asyncio.CancelledError:  # pragma: no cover
                break

            try:
                processed_event = await self._run_steps(event)
                await sink(processed_event)
            except Exception as exc:  # broad exception boundary is intentional
                _LOGGER.exception("Pipeline failed for event %s: %s", event, exc)

    async def _run_steps(self, event: dict) -> dict:
        """
        Execute all steps for the given event in series.
        """
        current = event
        for step in self._steps:
            start = time.perf_counter()
            try:
                current = await step.coroutine(current)
                status = "ok"
            except Exception as exc:
                status = "error"
                wrapped = PipelineError(
                    f"Step '{step.name}' failed. See `original` for root cause.",
                    step=step.name,
                    original=exc,
                )
                _LOGGER.debug("Error captured in step %s: %s", step.name, exc)
                raise wrapped from exc
            finally:
                duration = time.perf_counter() - start
                self._record_metrics(step.name, status, duration)

            # Notify observers only when step succeed
            if status == "ok":
                await self._dispatch_observers(current, step=step.name)
        return current

    # ------------------------------------------------------------------#
    #                          Observer helpers                         #
    # ------------------------------------------------------------------#

    async def _dispatch_observers(self, event: dict, *, step: str) -> None:
        if not self._observers:
            return

        await asyncio.gather(
            *[_safe_wrapper(obs.update)(event, step=step) for obs in self._observers],
            return_exceptions=True,
        )

    # ------------------------------------------------------------------#
    #                          Metrics helpers                          #
    # ------------------------------------------------------------------#

    @staticmethod
    def _record_metrics(step: str, status: str, duration: float) -> None:
        if "PROM_COUNTER" in globals():
            PROM_COUNTER.labels(step=step, status=status).inc()
            PROM_DURATION.labels(step=step).observe(duration)

        _LOGGER.debug("Step %s finished with %s in %.4fs", step, status, duration)


###############################################################################
# Utility helpers                                                             #
###############################################################################
def _safe_wrapper(
    func: Callable[..., Awaitable[Any]]
) -> Callable[..., Coroutine[Any, Any, Any]]:
    """
    Wrap coroutines so they swallow *unexpected* errors, log, and return the
    original payload—useful for non-critical validation or enrichment steps.
    """

    async def _inner(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("Non-critical step error: %s", exc, exc_info=exc)
            # Do *not* re-raise; just forward the original payload
            return args[0] if args else None

    return _inner


###############################################################################
# Example Observer Implementation                                             #
###############################################################################
class LoggingObserver:
    """
    Minimalistic observer that logs the current event id at INFO level.
    """

    def __init__(self, id_field: str = "id") -> None:
        self._id_field = id_field

    async def update(self, event: dict, *, step: str) -> None:
        _LOGGER.info("Observer[%s]: processed id=%s", step, event.get(self._id_field))
```