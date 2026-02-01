```python
"""
PulseStream Nexus – Data Quality Monitor
========================================
src/module_10.py

This module implements an asynchronous, streaming, data–quality monitor that
validates each inbound social‐event message coming from a Kafka topic.  The
logic embraces a Clean Architecture layering:

    ┌──────────────────────────┐
    │  Interfaces / I/O (CLI)  │  -> `main`, Kafka consumer
    ├──────────────────────────┤
    │        Observer          │  -> Prometheus metrics + logging
    ├──────────────────────────┤
    │       Use-Case(s)        │  -> `ValidateEventUseCase`
    ├──────────────────────────┤
    │        Entities          │  -> pydantic `SocialEvent`
    └──────────────────────────┘

Key Features
------------
• Pydantic schema validation for fast, runtime type enforcement  
• Great Expectations suite (optional) for semantic checks  
• Tenacity retry decorator for transient GE errors  
• Prometheus client metrics with an embedded HTTP server (/metrics)  
• Pluggable Strategy for deserialisation (raw Kafka -> Dict)  
• Graceful degradation when optional third-party libs are missing  
• Thorough logging and error handling suitable for production

The component can be executed as a stand-alone process:

    $ python -m src.module_10 \
        --bootstrap-servers localhost:9092 \
        --topic social-events \
        --expectation-suite expectations/social_event.json

It will expose Prometheus metrics on :9123/metrics by default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterable, Dict, List, Optional

import pydantic
from pydantic import BaseModel, Field, ValidationError

# --------------------------------------------------------------------------- #
# Optional / Soft Deps – gracefully degrade when missing                      #
# --------------------------------------------------------------------------- #
try:
    # Great Expectations adds ~300 ms import overhead, so only import when present
    import great_expectations as ge
    from great_expectations.checkpoint import LegacyCheckpoint
    GE_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    ge = None
    LegacyCheckpoint = None
    GE_AVAILABLE = False

try:
    from prometheus_client import Counter, Summary, start_http_server
    PROM_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    # Fallback stubs keep the remainder of the code unchanged
    PROM_AVAILABLE = False

    class _NoopMetric:  # noqa: D401
        """A dummy metric placeholder when Prometheus is unavailable."""

        def labels(self, *_, **__) -> "._NoopMetric":  # type: ignore
            return self

        def observe(self, *_: Any, **__: Any) -> None:
            pass

        def inc(self, *_: Any, **__: Any) -> None:
            pass

    Counter = Summary = _NoopMetric  # type: ignore


try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ModuleNotFoundError:  # pragma: no cover
    # Simple shim; we lose fancy retries but continue execution
    def retry(*_dargs, **_dkwargs):  # type: ignore
        def _decor(fn):  # noqa: D401
            return fn

        return _decor

    def stop_after_attempt(*_a, **_k):  # noqa: D401
        pass

    def wait_exponential(*_a, **_k):  # noqa: D401
        pass

# aiokafka might be optional in non-Kafka test environments.
try:
    from aiokafka import AIOKafkaConsumer
    AIOKAFKA_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    AIOKAFKA_AVAILABLE = False
# --------------------------------------------------------------------------- #
# Logging Configuration                                                       #
# --------------------------------------------------------------------------- #
LOG_LEVEL = os.getenv("PSN_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)-8s] %(name)s – %(message)s",  # noqa: WPS323
)
logger = logging.getLogger("pulse_stream_nexus.module_10")

# --------------------------------------------------------------------------- #
# Prometheus Metrics                                                          #
# --------------------------------------------------------------------------- #
if PROM_AVAILABLE:
    METRIC_VALID_EVENTS = Counter(
        "psn_valid_events_total",
        "Number of events that passed validation",
        labelnames=["platform"],
    )
    METRIC_INVALID_EVENTS = Counter(
        "psn_invalid_events_total",
        "Number of events that failed validation",
        labelnames=["platform", "reason"],
    )
    METRIC_LATENCY = Summary(  # noqa: WPS316
        "psn_event_validation_seconds",
        "Time spent validating an event",
    )
else:  # pragma: no cover
    METRIC_VALID_EVENTS = Counter()
    METRIC_INVALID_EVENTS = Counter()
    METRIC_LATENCY = Summary()

# --------------------------------------------------------------------------- #
# Domain Model (Entity)                                                       #
# --------------------------------------------------------------------------- #
class SocialEvent(BaseModel):
    """
    Immutable domain entity representing a single social event.

    Attributes
    ----------
    id: str
        Unique event identifier (social-network generated UUID or Snowflake).
    platform: str
        Source platform (`twitter`, `reddit`, `mastodon`, `discord`, …).
    user_id: str
        Normalised user identifier.
    content: str
        Raw textual content (before any NLP transforms).
    timestamp: float
        Epoch time in seconds (UTC).
    lang: Optional[str]
        Language code (ISO-639-1) detected by the emitter.
    sentiment_score: Optional[float]
        Optional pre-computed sentiment ‑1..1.
    """

    id: str
    platform: str
    user_id: str
    content: str
    timestamp: float
    lang: Optional[str] = Field(None, min_length=2, max_length=8)
    sentiment_score: Optional[float] = Field(None, ge=-1.0, le=1.0)

    # Domain invariants / validators
    @pydantic.validator("platform")
    def _platform_whitelist(cls, value: str) -> str:  # noqa: N805
        allowed = {"twitter", "reddit", "mastodon", "discord"}
        if value not in allowed:
            raise ValueError(f"Unsupported platform '{value}'")
        return value

    @pydantic.validator("timestamp")
    def _timestamp_past_not_future(cls, value: float) -> float:  # noqa: N805
        if value > time.time() + 60:  # 60 s clock-skew tolerance
            raise ValueError("timestamp is in the future")
        return value


# --------------------------------------------------------------------------- #
# Strategy: Deserialiser                                                      #
# --------------------------------------------------------------------------- #
class DeserialiserStrategy:
    """Strategy base class for decoding raw message bytes into dicts."""

    async def decode(self, raw_msg: bytes) -> Dict[str, Any]:
        """Decode raw bytes into a Python dictionary."""
        raise NotImplementedError


class JsonDeserialiser(DeserialiserStrategy):
    """Default JSON deserialisation strategy."""

    async def decode(self, raw_msg: bytes) -> Dict[str, Any]:
        try:
            # Assume UTF-8 encoded JSON document.
            return json.loads(raw_msg.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON payload") from exc


# --------------------------------------------------------------------------- #
# Validation Service (Great Expectations wrapper)                            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EventValidator:
    """
    Wrapper for Great Expectations checkpoint execution.

    Parameters
    ----------
    expectation_suite: Path
        Path to a .json/.yaml GE expectation suite. Optional; when omitted
        only pydantic validation is applied.
    """

    expectation_suite: Optional[Path] = None

    def _load_checkpoint(self) -> LegacyCheckpoint:  # pragma: no cover
        """(Lazy) build a checkpoint object for the given suite."""
        if not GE_AVAILABLE:
            raise RuntimeError("Great Expectations is not installed")

        context = ge.get_context()
        suite_name = self.expectation_suite.stem
        checkpoint_name = f"psn_{suite_name}_checkpoint"
        # Reuse or create a minimal checkpoint
        if checkpoint_name not in context.list_checkpoints():
            checkpoint_config = {
                "name": checkpoint_name,
                "class_name": "Checkpoint",
                "expectation_suite_name": suite_name,
                "run_name_template": "psn_dq_{run_time}",
            }
            context.add_checkpoint(**checkpoint_config)  # type: ignore[arg-type]
        return context.get_checkpoint(checkpoint_name)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    def validate_with_ge(self, payload: Dict[str, Any]) -> None:
        """
        Execute the Great Expectations checkpoint against a *single* payload.

        Raises
        ------
        ValueError
            When the checkpoint run does not succeed.
        """
        if not self.expectation_suite:
            return  # No semantic validation requested
        checkpoint = self._load_checkpoint()
        # GE expects batch data; wrap in list
        result = checkpoint.run(validations=[{"batch_data": [payload]}])
        if not result.success:
            raise ValueError("Great Expectations validation failed")

    def validate(self, payload: Dict[str, Any]) -> SocialEvent:
        """
        Perform pydantic + optional GE validation and return a SocialEvent.

        Parameters
        ----------
        payload: Dict[str, Any]
            Raw JSON-serialisable data.

        Returns
        -------
        SocialEvent
            A validated, domain entity.
        """
        # 1. Pydantic structural validation
        event = SocialEvent.parse_obj(payload)  # May raise ValidationError
        # 2. Great Expectations semantic validation
        self.validate_with_ge(payload)
        return event


# --------------------------------------------------------------------------- #
# Use-Case                                                                     #
# --------------------------------------------------------------------------- #
class ValidateEventUseCase:
    """
    Orchestrates validation, metric recording, and error handling for events.
    """

    def __init__(
        self,
        validator: EventValidator,
        deserialiser: DeserialiserStrategy | None = None,
    ) -> None:
        self._validator = validator
        self._deserialiser = deserialiser or JsonDeserialiser()

    async def execute(self, raw_msg: bytes) -> None:
        """
        Execute the validation flow for a single raw event message.

        This routine is intentionally small so that it remains synchronous after
        the initial await for deserialisation.  Any I/O within validation
        (Great Expectations file reads) runs in a thread-pool via GE.

        Errors are trapped and mapped to Prometheus counters.
        """
        start_ts = time.perf_counter()
        try:
            payload = await self._deserialiser.decode(raw_msg)
            event = self._validator.validate(payload)
        except (ValidationError, ValueError) as exc:
            platform = payload.get("platform", "unknown") if isinstance(payload, dict) else "unknown"
            reason = exc.__class__.__name__
            logger.debug("Event invalid (%s): %s", reason, exc, exc_info=LOG_LEVEL == "DEBUG")
            METRIC_INVALID_EVENTS.labels(platform=platform, reason=reason).inc()
        else:
            # Successful validation
            METRIC_VALID_EVENTS.labels(platform=event.platform).inc()
            logger.debug("Event %s validated successfully", event.id)
        finally:
            METRIC_LATENCY.observe(time.perf_counter() - start_ts)


# --------------------------------------------------------------------------- #
# Async Infrastructure / Adapter                                              #
# --------------------------------------------------------------------------- #
async def _consume_kafka(
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    loop: asyncio.AbstractEventLoop,
) -> AsyncIterable[bytes]:
    """
    Consume forever from Kafka, yielding raw bytes.

    This is separated for testability; in unit tests it can be monkey-patched
    with an async generator that yields demo data.
    """
    if not AIOKAFKA_AVAILABLE:  # pragma: no cover
        raise RuntimeError("aiokafka is required for Kafka consumption")

    consumer = AIOKafkaConsumer(
        topic,
        loop=loop,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            yield msg.value
    finally:
        await consumer.stop()


@asynccontextmanager
async def _graceful_shutdown(
    tasks: List[asyncio.Task[Any]],
) -> AsyncIterable[None]:
    """
    Async context manager that cancels running tasks on SIGINT/SIGTERM.
    """
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handler(_: signal.Signals) -> None:  # noqa: D401
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handler, sig)

    try:
        yield
    finally:
        await shutdown_event.wait()
        logger.info("Cancellation requested – shutting down tasks")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# --------------------------------------------------------------------------- #
# Bootstrap                                                                   #
# --------------------------------------------------------------------------- #
async def _worker(
    stream: AsyncIterable[bytes],
    use_case: ValidateEventUseCase,
) -> None:
    """
    Core worker that drives the consumer & validation pipeline.
    """
    async for raw_msg in stream:
        await use_case.execute(raw_msg)


async def _run_async(args: argparse.Namespace) -> None:  # noqa: WPS231
    # 1. Metrics server
    if PROM_AVAILABLE:
        logger.info("Starting Prometheus metrics server on port %d", args.prometheus_port)
        start_http_server(addr="0.0.0.0", port=args.prometheus_port)  # type: ignore[arg-type]

    # 2. Build components
    validator = EventValidator(Path(args.expectation_suite) if args.expectation_suite else None)
    use_case = ValidateEventUseCase(validator=validator)

    loop = asyncio.get_running_loop()
    stream: AsyncIterable[bytes]

    # Fallback: If Kafka unavailable we read from stdin (tests / local dev)
    if AIOKAFKA_AVAILABLE:
        logger.info("Consuming Kafka topic '%s' at %s", args.topic, args.bootstrap_servers)
        stream = _consume_kafka(
            bootstrap_servers=args.bootstrap_servers,
            topic=args.topic,
            group_id=args.group_id,
            loop=loop,
        )
    else:
        logger.warning("aiokafka not available; falling back to STDIN line reader")
        stream = (line.encode() async for line in _stdin_async_gen())

    worker_task = asyncio.create_task(_worker(stream, use_case), name="dq_worker")

    async with _graceful_shutdown([worker_task]):
        await worker_task


async def _stdin_async_gen() -> AsyncIterable[str]:
    """
    Async generator that yields lines from stdin without blocking the loop.
    """
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()

    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)  # type: ignore[arg-type]

    while True:
        line = await reader.readline()
        if not line:
            break
        yield line.decode()


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for the monitor process."""
    parser = argparse.ArgumentParser(description="PulseStream Nexus Data-Quality Monitor")
    parser.add_argument("--bootstrap-servers", default="localhost:9092", help="Kafka bootstrap servers")
    parser.add_argument("--topic", default="social-events", help="Kafka topic name")
    parser.add_argument("--group-id", default="psn_dq_monitor", help="Kafka consumer group")
    parser.add_argument("--expectation-suite", help="Path to GE expectation suite (.json/.yml)")
    parser.add_argument("--prometheus-port", type=int, default=9123, help="Prometheus metrics HTTP port")

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    """Synchronously run the async application entrypoint."""
    args = _parse_args(argv)
    try:
        asyncio.run(_run_async(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user – exiting")


if __name__ == "__main__":  # pragma: no cover
    main()

```