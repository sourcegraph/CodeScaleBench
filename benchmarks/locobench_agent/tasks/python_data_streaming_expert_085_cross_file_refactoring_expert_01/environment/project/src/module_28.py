from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterable, Callable, Dict, List, Optional

try:
    # Prometheus metrics are optional but highly recommended in production
    from prometheus_client import Counter, Summary  # type: ignore
except ImportError:  # pragma: no cover
    # Fallback to lightweight no-op metrics so that the code keeps working
    class _NoOpMetric:  # pylint: disable=too-few-public-methods
        def __init__(self, *_, **__):
            pass

        def labels(self, *_, **__):  # noqa: D401
            return self

        def inc(self, *_):  # noqa: D401
            pass

        def observe(self, *_):  # noqa: D401
            pass

        def time(self):  # noqa: D401
            class _DummyCtxMgr:  # pylint: disable=too-few-public-methods
                def __enter__(self, *_):  # noqa: D401
                    return self

                def __exit__(self, *_):  # noqa: D401
                    return False

            return _DummyCtxMgr()

    Counter = Summary = _NoOpMetric  # type: ignore

try:
    from pydantic import BaseModel, Field, ValidationError  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "`pydantic` is required for PulseStream Nexus, "
        "please install it with `pip install pydantic`."
    ) from exc

logger = logging.getLogger("pulsestream.module_28")
logger.setLevel(logging.INFO)

# ------------------------------------------------------------------------------
# Public exports
# ------------------------------------------------------------------------------

__all__ = [
    "SocialEvent",
    "SentimentWindowAggregator",
    "parse_event",
    "stream_processor",
]

# ------------------------------------------------------------------------------
# Pydantic model representing a single social-platform event
# ------------------------------------------------------------------------------


class SocialEvent(BaseModel):
    """
    Canonical representation of a social-network event after initial normalization.

    The model is intentionally concise—additional fields can be passed through
    the ``meta`` attribute to avoid breaking changes.
    """

    event_id: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="Event creation timestamp (UTC).",
    )
    user_id: str
    platform: str
    text: str
    sentiment_score: float
    toxicity_score: float
    topic: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------------------
# Aggregator implementation
# ------------------------------------------------------------------------------


class SentimentWindowAggregator:
    """
    Sliding/tumbling window aggregator that computes sentiment/toxicity statistics.

    The implementation is framework-agnostic and can be embedded in a FastAPI route,
    an async Kafka consumer, or any other asyncio-compatible context.

    Parameters
    ----------
    window_size:
        Duration of the tumbling window (e.g., ``timedelta(minutes=1)``).
    grace_period:
        Additional grace period added to the window end before data is flushed.
        This allows the aggregator to accept late-arriving events without
        duplicate emission.
    flush_cb:
        Callback invoked every time a window is flushed. The callable receives
        ``(window_start, events, aggregated_metrics)`` as positional arguments.
        The callback may be synchronous or async.
    loop:
        Event loop to use. Defaults to ``asyncio.get_event_loop()``.
    """

    def __init__(
        self,
        *,
        window_size: timedelta,
        grace_period: timedelta = timedelta(seconds=5),
        flush_cb: Optional[
            Callable[[datetime, List[SocialEvent], Dict[str, float]], Any]
        ] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        if window_size.total_seconds() <= 0:
            raise ValueError("window_size must be > 0")

        self._window_size = window_size
        self._grace_period = grace_period
        self._buckets: Dict[datetime, List[SocialEvent]] = defaultdict(list)
        self._flush_cb = flush_cb or self._noop_flush_cb
        self._loop = loop or asyncio.get_event_loop()
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

        # Prometheus instrumentation
        self._metric_ingested = Counter(
            "psn_ingested_events_total",
            "Total number of events ingested by SentimentWindowAggregator.",
        )
        self._metric_window_flush = Counter(
            "psn_window_flush_total",
            "Total number of windows flushed by SentimentWindowAggregator.",
        )
        self._metric_flush_latency = Summary(
            "psn_window_flush_latency_seconds",
            "Latency of window flush callbacks in seconds.",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the internal background flusher task.

        Must be invoked before ingesting events in a long-running process.
        """
        if self._task and not self._task.done():
            logger.debug("SentimentWindowAggregator already running.")
            return

        self._task = self._loop.create_task(self._flusher(), name="psn-flusher")
        logger.info("SentimentWindowAggregator started (window=%s).", self._window_size)

    async def stop(self) -> None:
        """
        Cancel the background flusher task and synchronously flush remaining data.
        """
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("Flusher task cancelled.")
        await self._force_flush_all()
        logger.info("SentimentWindowAggregator stopped.")

    async def ingest(self, event: SocialEvent) -> None:
        """
        Ingest a single, already validated ``SocialEvent`` into the appropriate window.
        """
        bucket_key = self._bucket_key(event.created_at)
        async with self._lock:
            self._buckets[bucket_key].append(event)
            self._metric_ingested.inc()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _bucket_key(self, dt: datetime) -> datetime:
        """
        Convert a timestamp into the canonical start time for its window.
        """
        epoch = int(dt.replace(tzinfo=timezone.utc).timestamp())
        window_sec = int(self._window_size.total_seconds())
        bucket_epoch = (epoch // window_sec) * window_sec
        return datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)

    async def _flusher(self) -> None:
        """
        Background coroutine periodically flushing expired windows.
        """
        try:
            # Flush at half-window intervals to reduce latency
            interval = max(self._window_size.total_seconds() / 2, 1.0)
            while True:
                await asyncio.sleep(interval)
                await self._flush_expired_windows()
        except asyncio.CancelledError:
            # Propagate cancellation so that stop() can manage final flush
            raise

    async def _flush_expired_windows(self) -> None:
        """
        Flush windows whose [window_end + grace_period] is in the past.
        """
        now = datetime.now(tz=timezone.utc)
        threshold = now - self._grace_period

        expired: List[datetime] = []

        async with self._lock:
            for window_start in list(self._buckets):
                window_end = window_start + self._window_size
                if window_end <= threshold:
                    expired.append(window_start)

            for key in expired:
                events = self._buckets.pop(key)
                metrics = self._aggregate(events)
                await self._execute_flush_cb(key, events, metrics)
                self._metric_window_flush.inc()

    async def _force_flush_all(self) -> None:
        """
        Flush all remaining windows irrespective of their completeness.
        """
        async with self._lock:
            keys = list(self._buckets)
            for key in keys:
                events = self._buckets.pop(key)
                metrics = self._aggregate(events)
                await self._execute_flush_cb(key, events, metrics)

    async def _execute_flush_cb(
        self,
        window_start: datetime,
        events: List[SocialEvent],
        metrics: Dict[str, float],
    ) -> None:
        """
        Safety wrapper around the user-provided callback.
        """
        try:
            with self._metric_flush_latency.time():
                result = self._flush_cb(window_start, events, metrics)
                if asyncio.iscoroutine(result):
                    await result
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Flush callback failed for window starting %s.", window_start.isoformat()
            )

    @staticmethod
    def _aggregate(events: List[SocialEvent]) -> Dict[str, float]:
        """
        Aggregate per-window metrics. Extend with additional KPIs as needed.
        """
        if not events:
            return {}

        total_sentiment = sum(e.sentiment_score for e in events)
        total_toxicity = sum(e.toxicity_score for e in events)
        count = len(events)

        return {
            "count": float(count),
            "avg_sentiment": total_sentiment / count,
            "avg_toxicity": total_toxicity / count,
            "sentiment_sum": total_sentiment,
            "toxicity_sum": total_toxicity,
        }

    @staticmethod
    def _noop_flush_cb(
        *_: Any, **__: Any
    ) -> None:  # noqa: D401  pylint: disable=unused-argument
        """
        Default callback used when no flush_cb is supplied.

        It is intentionally silent to avoid polluting stdout in test environments.
        """

# ------------------------------------------------------------------------------
# Convenience helpers
# ------------------------------------------------------------------------------


def parse_event(payload: Dict[str, Any]) -> Optional[SocialEvent]:
    """
    Convert an untrusted JSON/dict payload into a validated ``SocialEvent``.

    Returns ``None`` if validation fails—callers can decide whether to log/skip.
    """
    try:
        return SocialEvent.parse_obj(payload)
    except ValidationError as exc:
        logger.warning("Invalid event skipped: %s", exc)
        return None


async def stream_processor(
    stream: AsyncIterable[Dict[str, Any]],
    aggregator: SentimentWindowAggregator,
) -> None:
    """
    High-level helper: consume an async stream of raw payloads and push them into
    the supplied aggregator instance.

    Example
    -------
    >>> async def main():
    ...     async def fake_stream():
    ...         for i in range(10):
    ...             yield {
    ...                 "event_id": str(i),
    ...                 "user_id": "u42",
    ...                 "platform": "discord",
    ...                 "text": "hello",
    ...                 "sentiment_score": 0.5,
    ...                 "toxicity_score": 0.1,
    ...             }
    ...     aggregator = SentimentWindowAggregator(
    ...         window_size=timedelta(seconds=30)
    ...     )
    ...     aggregator.start()
    ...     await stream_processor(fake_stream(), aggregator)
    ...     await aggregator.stop()
    """
    async for raw_payload in stream:
        event = parse_event(raw_payload)
        if event:
            await aggregator.ingest(event)


# ------------------------------------------------------------------------------
# Self-test / Demo run (executed via `python -m src.module_28`)
# ------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(msg)s")

    async def _demo() -> None:
        """
        Minimal runnable demo that ingests randomly generated events.
        Acts as a sanity check without requiring external infra.
        """
        import random
        import string

        async def fake_event_stream() -> AsyncIterable[Dict[str, Any]]:
            for _ in range(200):
                await asyncio.sleep(random.uniform(0.01, 0.05))
                yield {
                    "event_id": "".join(random.choices(string.ascii_letters, k=8)),
                    "user_id": f"user-{random.randint(1,5)}",
                    "platform": random.choice(["twitter", "reddit", "mastodon"]),
                    "text": "lorem ipsum",
                    "sentiment_score": random.uniform(-1, 1),
                    "toxicity_score": random.uniform(0, 1),
                    "created_at": datetime.now(tz=timezone.utc).isoformat(),
                }

        # Configure window size via env var for quick experimentation
        window_sec = int(os.getenv("PSN_WINDOW_SEC", "10"))
        aggregator = SentimentWindowAggregator(
            window_size=timedelta(seconds=window_sec),
            flush_cb=lambda ws, evs, m: logger.info(  # type: ignore
                "FLUSH @ %s: %d events avg_sentiment=%.3f",
                ws.isoformat(timespec="seconds"),
                len(evs),
                m.get("avg_sentiment", 0.0),
            ),
        )

        aggregator.start()
        await stream_processor(fake_event_stream(), aggregator)
        await aggregator.stop()

    asyncio.run(_demo())