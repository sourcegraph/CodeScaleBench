```python
"""
module_49.py
PulseStream Nexus – Data Streaming Platform
-------------------------------------------

This module delivers a resilient, real-time event-dispatch component that
validates, rate-limits, and forwards social interaction events (e.g., tweets,
posts, messages) to downstream sinks such as Kafka topics or in-memory
subscribers.  The implementation purposefully avoids direct framework
dependencies (e.g., FastAPI, Spark) so it can be imported by pure domain/use-
case layers without violating Clean-Architecture boundaries.

Key Features
============
1. Data-validation via pydantic schema registry
2. Token-bucket rate-limiting (configurable)
3. Retry w/ exponential back-off (tenacity)
4. Optional Prometheus metrics export
5. Pluggable sink strategy (Kafka, stdout, custom observers)

Typical Usage
=============
>>> dispatcher = StreamDispatcher(settings=DispatcherSettings())
>>> dispatcher.subscribe(KafkaProducerSink("social_events"))
>>> asyncio.run(
...     dispatcher.enqueue(
...         {
...             "event_id": "abc123",
...             "network": "twitter",
...             "payload": {"text": "hello world"},
...             "user_id": "u42",
...             "timestamp": 1688751234.2,
...         }
...     )
... )

Author:  PulseStream Nexus engineering team
"""

from __future__ import annotations

import asyncio
import logging
import random
import string
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Protocol, Union

try:
    from prometheus_client import Counter, Gauge, Histogram
except ImportError:  # pragma: no cover
    # Gracefully degrade if prometheus_client is unavailable.
    Counter = Gauge = Histogram = lambda *_, **__: None  # type: ignore

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("pydantic must be installed: pip install pydantic") from exc

try:
    from tenacity import RetryError, retry, stop_after_attempt, wait_exponential_jitter
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("tenacity must be installed: pip install tenacity") from exc

# --------------------------------------------------------------------------- #
# Logging Configuration                                                       #
# --------------------------------------------------------------------------- #

logger = logging.getLogger("pulstream.module_49")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
    )
)
logger.addHandler(_handler)


# --------------------------------------------------------------------------- #
# Domain Model & Validation                                                   #
# --------------------------------------------------------------------------- #

class SocialEventModel(BaseModel):
    """
    Canonical schema for social interaction events.

    All fields are required unless explicitly marked optional.
    """
    event_id: str = Field(..., regex=r"^[a-zA-Z0-9_\-]{3,64}$")
    network: str = Field(..., regex=r"^(twitter|reddit|mastodon|discord)$")
    user_id: str
    payload: Dict[str, Any]
    timestamp: float  # Unix epoch (seconds)

    # Optional metadata
    ingestion_ts: Optional[float] = Field(
        default_factory=lambda: time.time(),
        description="Populated automatically by the ingestion layer.",
    )


# --------------------------------------------------------------------------- #
# Rate Limiter (Token Bucket)                                                 #
# --------------------------------------------------------------------------- #

class TokenBucket:
    """
    Thread-safe token-bucket rate limiter.

    Parameters
    ----------
    rate : float
        Tokens (events) per second added to the bucket.
    capacity : int
        Maximum token capacity.
    """

    __slots__ = ("_rate", "_capacity", "_tokens", "_last_refill", "_lock")

    def __init__(self, rate: float, capacity: int) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")

        self._rate: float = rate
        self._capacity: int = capacity
        self._tokens: float = capacity  # Start full for burst allowance
        self._last_refill: float = time.monotonic()
        self._lock: Lock = Lock()

    def consume(self, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens. Returns True on success, False otherwise.
        """
        if tokens <= 0:
            raise ValueError("tokens must be positive")

        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill = elapsed * self._rate
            self._tokens = min(self._capacity, self._tokens + refill)
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"TokenBucket(rate={self._rate}, capacity={self._capacity}, "
            f"tokens={self._tokens:.2f})"
        )


# --------------------------------------------------------------------------- #
# Metrics                                                                     #
# --------------------------------------------------------------------------- #

# Provide no-op metrics if prometheus_client is missing
if callable(Counter):
    METRIC_EVENTS_VALID = Counter(
        "psn_events_validated_total",
        "Total number of events that passed schema validation.",
    )
    METRIC_EVENTS_INVALID = Counter(
        "psn_events_invalid_total",
        "Total number of events that failed schema validation.",
    )
    METRIC_RATE_LIMITED = Counter(
        "psn_events_rate_limited_total",
        "Total number of events rejected due to rate limiting.",
    )
    METRIC_DISPATCH_TIME = Histogram(
        "psn_dispatch_latency_seconds",
        "Time spent dispatching events.",
        buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5),
    )
else:  # pragma: no cover
    METRIC_EVENTS_VALID = METRIC_EVENTS_INVALID = METRIC_RATE_LIMITED = (
        METRIC_DISPATCH_TIME
    ) = None  # type: ignore


# --------------------------------------------------------------------------- #
# Sink Protocol & Implementations                                             #
# --------------------------------------------------------------------------- #

class Sink(Protocol):
    """
    Destination for validated social events.
    """

    async def send(self, event: SocialEventModel) -> None:  # pragma: no cover
        ...


class StdoutSink:
    """
    Simple sink that prints events to stdout (useful for local debugging).
    """

    __slots__ = ()

    async def send(self, event: SocialEventModel) -> None:
        print(event.json())


class KafkaProducerSink:
    """
    Non-blocking Kafka producer sink.

    Requires confluent-kafka to be installed.  If unavailable or mis-configured,
    the sink gracefully degrades to StdoutSink.
    """

    __slots__ = ("_topic", "_producer", "_fallback")

    def __init__(self, topic: str, config: Optional[Dict[str, Any]] = None) -> None:
        self._topic = topic
        self._fallback = StdoutSink()

        try:
            from confluent_kafka import Producer  # type: ignore
        except ImportError:  # pragma: no cover
            logger.warning("confluent-kafka not installed; falling back to StdoutSink")
            self._producer = None
            return

        # Minimal sane defaults; caller can pass arbitrary overrides
        default_config = {
            "bootstrap.servers": "localhost:9092",
            "queue.buffering.max.messages": 100_000,
            "queue.buffering.max.kbytes": 10240,
            "queue.buffering.max.ms": 20,
            "batch.num.messages": 10_000,
            "compression.type": "lz4",
        }
        merged_config = {**default_config, **(config or {})}

        try:
            self._producer = Producer(merged_config)
            logger.info("KafkaProducerSink connected to %s", merged_config["bootstrap.servers"])
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to create Kafka producer [%s]; using fallback: %s", exc, topic)
            self._producer = None

    async def send(self, event: SocialEventModel) -> None:
        if not self._producer:
            await self._fallback.send(event)
            return

        payload = event.json().encode("utf-8")
        loop = asyncio.get_running_loop()
        # Execute produce() in a thread to avoid blocking the event loop
        await loop.run_in_executor(
            None, lambda: self._producer.produce(self._topic, payload)
        )
        # Fire-and-forget flush in the background
        loop.run_in_executor(None, self._producer.poll, 0)  # type: ignore


# --------------------------------------------------------------------------- #
# Dispatcher                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class DispatcherSettings:
    """
    Configuration knobs for `StreamDispatcher`.
    """
    max_queue_size: int = 50_000
    rate_limit_per_sec: float = 5_000  # tokens/sec
    rate_limit_capacity: int = 10_000
    validation_enabled: bool = True
    retries: int = 3
    jitter: bool = True


class StreamDispatcher:
    """
    Asynchronous dispatcher orchestrating validation, rate-limiting, and sink
    fan-out.  Designed to run in a long-lived asyncio event loop.

    Example
    -------
    >>> dispatcher = StreamDispatcher(settings=DispatcherSettings())
    >>> dispatcher.subscribe(StdoutSink())
    >>> await dispatcher.enqueue({...})
    """

    def __init__(self, settings: DispatcherSettings) -> None:
        self._settings = settings
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(settings.max_queue_size)
        self._subscribers: List[Sink] = []
        self._rate_limiter = TokenBucket(
            rate=settings.rate_limit_per_sec,
            capacity=settings.rate_limit_capacity,
        )
        self._stop_event = asyncio.Event()
        self._worker_task: Optional["asyncio.Task[None]"] = None

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def subscribe(self, sink: Sink) -> None:
        self._subscribers.append(sink)
        logger.info("StreamDispatcher subscribed: %s", sink.__class__.__name__)

    async def enqueue(self, raw_event: Dict[str, Any]) -> None:
        """
        Validate and buffer an incoming event dict for async processing.

        Raises
        ------
        asyncio.QueueFull
            If the internal queue is at capacity.
        """
        await self._queue.put(raw_event)

    async def start(self) -> None:
        """
        Launch background worker.  Safe to call multiple times.
        """
        if self._worker_task and not self._worker_task.done():
            logger.debug("StreamDispatcher already running.")
            return

        self._stop_event.clear()
        self._worker_task = asyncio.create_task(self._run_worker(), name="stream-worker")
        logger.info("StreamDispatcher started.")

    async def stop(self) -> None:
        """
        Signal worker shutdown and wait for graceful completion.
        """
        self._stop_event.set()
        if self._worker_task:
            await self._worker_task
            logger.info("StreamDispatcher stopped.")

    # --------------------------------------------------------------------- #
    # Internal worker                                                       #
    # --------------------------------------------------------------------- #

    async def _run_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                raw_event = await asyncio.wait_for(self._queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue  # blank tick

            # Rate-limit first; cheapest operation
            if not self._rate_limiter.consume():
                if METRIC_RATE_LIMITED:
                    METRIC_RATE_LIMITED.inc()
                logger.debug("Event rate-limited. Queue length=%d", self._queue.qsize())
                continue  # Skip event

            try:
                validated = self._validate(raw_event) if self._settings.validation_enabled else raw_event
            except ValidationError as ve:
                if METRIC_EVENTS_INVALID:
                    METRIC_EVENTS_INVALID.inc()
                logger.warning("Invalid event dropped: %s", ve)
                continue

            # Fan-out
            await self._dispatch(validated)

    def _validate(self, raw_event: Dict[str, Any]) -> SocialEventModel:
        model = SocialEventModel(**raw_event)
        if METRIC_EVENTS_VALID:
            METRIC_EVENTS_VALID.inc()
        return model

    async def _dispatch(self, event: SocialEventModel) -> None:
        if not self._subscribers:
            logger.warning("No sinks registered; dropping event %s", event.event_id)
            return

        start_ts = time.perf_counter()
        # Send concurrently to all sinks
        await asyncio.gather(*(self._send_with_retry(s, event) for s in self._subscribers))
        elapsed = time.perf_counter() - start_ts
        if METRIC_DISPATCH_TIME:
            METRIC_DISPATCH_TIME.observe(elapsed)

    # --------------------------------------------------------------------- #
    # Retry handling                                                        #
    # --------------------------------------------------------------------- #

    def _retry_decorator(self):
        """
        Build tenacity retry decorator based on settings.
        """
        wait = wait_exponential_jitter(multiplier=0.2) if self._settings.jitter else wait_exponential_jitter(
            multiplier=0.2, exp_base=2, max_delay=1
        )
        return retry(
            stop=stop_after_attempt(self._settings.retries),
            wait=wait,
            reraise=True,
        )

    async def _send_with_retry(self, sink: Sink, event: SocialEventModel) -> None:
        dec = self._retry_decorator()

        @dec
        async def _send() -> None:
            await sink.send(event)

        try:
            await _send()
        except RetryError as exc:  # pragma: no cover
            logger.error(
                "Exhausted retries sending event=%s to sink=%s | last_error=%s",
                event.event_id,
                sink.__class__.__name__,
                exc.last_attempt.exception(),
            )

    # --------------------------------------------------------------------- #
    # Util                                                                   #
    # --------------------------------------------------------------------- #

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"StreamDispatcher(queue={self._queue.qsize()}, "
            f"sinks={len(self._subscribers)})"
        )


# --------------------------------------------------------------------------- #
# Demo CLI (python -m src.module_49)                                          #
# --------------------------------------------------------------------------- #

async def _demo() -> None:  # pragma: no cover
    settings = DispatcherSettings(rate_limit_per_sec=1000)
    dispatcher = StreamDispatcher(settings)
    dispatcher.subscribe(StdoutSink())
    dispatcher.subscribe(KafkaProducerSink("social_stream"))

    await dispatcher.start()

    # Generate fake events
    for _ in range(50):
        evt = {
            "event_id": "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
            "network": random.choice(["twitter", "reddit", "mastodon", "discord"]),
            "user_id": f"user_{random.randint(1, 1000)}",
            "payload": {"text": "Lorem ipsum dolor sit amet."},
            "timestamp": datetime.now(tz=timezone.utc).timestamp(),
        }
        await dispatcher.enqueue(evt)

    # Give the worker time to flush
    await asyncio.sleep(2)
    await dispatcher.stop()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_demo())
```