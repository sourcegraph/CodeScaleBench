```python
"""
PulseStream Nexus – Data-Streaming Platform
-------------------------------------------

src/module_5.py
~~~~~~~~~~~~~~~

This module houses a self-contained, production-grade implementation of a
stream-side transformation pipeline that demonstrates several of the guiding
principles behind PulseStream Nexus:

    • Strict domain / infrastructure segregation
    • Strategy Pattern for runtime-selectable transformations
    • Clean error handling and validation
    • Observability hooks (Prometheus compatible)
    • Extensibility via clearly defined interfaces

The code purposefully avoids tight coupling with other project files so it can
run stand-alone for demonstration and unit-testing purposes.  Replace the
simplified implementations (e.g. word-list sentiment) with real ML models or
micro-service calls as needed.

Author: PulseStream Engineering
License: MIT
"""

from __future__ import annotations

import json
import logging
import queue
import signal
import sys
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional

try:
    # Pydantic v1 for broad compatibility; swap to v2 if desired
    from pydantic import BaseModel, Field, ValidationError, validator
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Pydantic is required for this module. Install with `pip install pydantic`."
    ) from exc

try:
    # Prometheus instrumentation is optional
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
except ImportError:
    Counter = Gauge = Histogram = None  # type: ignore

# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #

LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"
)
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("pulse.module_5")

# --------------------------------------------------------------------------- #
# Domain model
# --------------------------------------------------------------------------- #


class SocialEvent(BaseModel):
    """
    A normalized in-memory representation of a social network event
    flowing through the PulseStream pipelines.
    """

    id: str
    network: str
    user_id: str = Field(..., alias="userId")
    timestamp: datetime
    content: str
    metadata: Dict[str, Any] = {}
    sentiment: Optional[float] = None  # –1 (neg) .. 1 (pos)
    toxicity: Optional[float] = None  # 0 (clean) .. 1 (toxic)
    virality: Optional[float] = None  # 0 .. 1 relative scale

    # --------------------------------------------------------------------- #
    # Validators
    # --------------------------------------------------------------------- #

    @validator("network")
    def _supported_networks(cls, value: str) -> str:  # noqa: D401, N805
        supported = {"twitter", "reddit", "mastodon", "discord"}
        if value.lower() not in supported:
            raise ValueError(f"Unsupported network '{value}'.")
        return value.lower()

    @validator("content")
    def _non_empty_content(cls, value: str) -> str:  # noqa: D401, N805
        if not value.strip():
            raise ValueError("Content must not be empty.")
        return value

    class Config:
        allow_population_by_field_name = True
        frozen = True  # make model immutable for easier reasoning


# --------------------------------------------------------------------------- #
# Transformation Strategies
# --------------------------------------------------------------------------- #


class TransformationStrategy(ABC):
    """
    Abstract base class for transformation strategies.
    """

    @abstractmethod
    def apply(self, event: SocialEvent) -> SocialEvent:
        """
        Apply the transformation and return a *new* event instance.
        """
        raise NotImplementedError


class SentimentStrategy(TransformationStrategy):
    """
    Naïve word-list sentiment analysis.

    Replace with a full-fledged transformer model in production, but keep the
    interface intact to avoid ripple effects.
    """

    POSITIVE_WORDS = frozenset(
        [
            "good",
            "great",
            "excellent",
            "awesome",
            "happy",
            "love",
            "fantastic",
            "superb",
            "amazing",
            "wonderful",
        ]
    )
    NEGATIVE_WORDS = frozenset(
        [
            "bad",
            "awful",
            "terrible",
            "hate",
            "sad",
            "horrible",
            "worst",
            "angry",
            "disappointing",
            "nasty",
        ]
    )

    def apply(self, event: SocialEvent) -> SocialEvent:
        words = set(event.content.lower().split())
        pos_hits = len(words & self.POSITIVE_WORDS)
        neg_hits = len(words & self.NEGATIVE_WORDS)

        # Simple scoring: positive – negative, normalized to [-1, 1]
        score = (pos_hits - neg_hits) / max(pos_hits + neg_hits, 1)

        logger.debug(
            "SentimentStrategy: pos=%d neg=%d score=%.3f id=%s",
            pos_hits,
            neg_hits,
            score,
            event.id,
        )
        return event.copy(update={"sentiment": score})


class ToxicityStrategy(TransformationStrategy):
    """
    Detects presence of toxic language using a block-list approach.
    """

    TOXIC_WORDS = frozenset(
        [
            "idiot",
            "stupid",
            "dumb",
            "fool",
            "moron",
            "loser",
            "trash",
            "garbage",
            "shut up",
            "kill",
        ]
    )

    def apply(self, event: SocialEvent) -> SocialEvent:
        lowered = event.content.lower()
        hits = sum(word in lowered for word in self.TOXIC_WORDS)
        score = min(hits * 0.1, 1.0)  # each hit adds 0.1 up to 1.0

        logger.debug(
            "ToxicityStrategy: hits=%d score=%.3f id=%s",
            hits,
            score,
            event.id,
        )
        return event.copy(update={"toxicity": score})


class ViralityStrategy(TransformationStrategy):
    """
    Estimates virality based on metadata features such as retweets, likes,
    and replies.  Uses a simple logistic-like scoring function.
    """

    COEFFICIENTS = {
        "retweets": 0.6,
        "likes": 0.3,
        "replies": 0.1,
    }

    def apply(self, event: SocialEvent) -> SocialEvent:
        meta = event.metadata or {}
        raw_score = 0.0
        for feature, weight in self.COEFFICIENTS.items():
            raw_score += weight * float(meta.get(feature, 0))

        # Logistic normalization to (0, 1)
        virality = 1.0 / (1.0 + pow(2.71828, -0.01 * raw_score))

        logger.debug(
            "ViralityStrategy: raw=%.1f virality=%.3f id=%s",
            raw_score,
            virality,
            event.id,
        )
        return event.copy(update={"virality": virality})


# --------------------------------------------------------------------------- #
# Pipeline Orchestrator
# --------------------------------------------------------------------------- #


class TransformationPipeline:
    """
    Executes an ordered set of transformations on incoming events and yields
    the results downstream.
    """

    def __init__(
        self, strategies: Iterable[TransformationStrategy], *,
        raise_on_error: bool = False
    ) -> None:
        self._strategies: List[TransformationStrategy] = list(strategies)
        self._raise_on_error = raise_on_error

        # Optional Prometheus metrics
        self._metrics_enabled = Counter is not None
        if self._metrics_enabled:
            self._events_total = Counter(  # type: ignore
                "psn_events_total",
                "Total number of events processed by module_5",
            )
            self._events_failed = Counter(  # type: ignore
                "psn_events_failed_total",
                "Number of events that failed during processing",
            )
            self._latency = Histogram(  # type: ignore
                "psn_event_latency_seconds",
                "Event processing latency in seconds",
            )

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def process(
        self, events: Iterable[SocialEvent]
    ) -> Generator[SocialEvent, None, None]:
        """
        Lazily process a stream of `SocialEvent`s.

        Yields a new `SocialEvent` instance for each incoming event.
        Errors are either raised (default off) or logged and skipped.
        """

        for event in events:
            start_time = time.time()
            try:
                for strategy in self._strategies:
                    event = strategy.apply(event)
                if self._metrics_enabled:
                    self._events_total.inc()  # type: ignore[attr-defined]
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Failed to process event id=%s: %s", event.id, exc)
                if self._metrics_enabled:
                    self._events_failed.inc()  # type: ignore[attr-defined]
                if self._raise_on_error:
                    raise
                continue
            finally:
                if self._metrics_enabled:
                    elapsed = time.time() - start_time
                    self._latency.observe(elapsed)  # type: ignore[attr-defined]
            yield event


# --------------------------------------------------------------------------- #
# Infrastructure: Minimal I/O Facade
# --------------------------------------------------------------------------- #


class FileEventSource:
    """
    Reads JSON-encoded events from a newline-delimited file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def stream(self) -> Generator[SocialEvent, None, None]:
        with self._path.open("r", encoding="utf-8") as fp:
            for line_no, raw in enumerate(fp, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    yield SocialEvent.parse_obj(data)
                except (json.JSONDecodeError, ValidationError) as exc:
                    logger.warning(
                        "Malformed event line %d in %s: %s", line_no, self._path, exc
                    )
                    continue


class StdoutSink:
    """
    Writes processed events as JSON lines to stdout (flushed).
    """

    @staticmethod
    def emit(events: Iterable[SocialEvent]) -> None:
        for event in events:
            json_event = event.json(by_alias=True, separators=(",", ":"))
            print(json_event, flush=True)


# --------------------------------------------------------------------------- #
# Graceful shutdown utility
# --------------------------------------------------------------------------- #


class StoppableWorker(threading.Thread):
    """
    Runs a target callable in a thread until stop() is called.
    Useful for illustrating how pipelines would run inside long-lived micro
    services while still supporting SIGTERM/SIGINT for K8s.
    """

    def __init__(self, target, *args, **kwargs) -> None:  # noqa: D401
        super().__init__(daemon=True)
        self._target = target
        self._args = args
        self._kwargs = kwargs
        self._stop_event = threading.Event()

    def run(self) -> None:  # noqa: D401
        try:
            logger.info("Worker %s started.", self.name)
            self._target(*self._args, **self._kwargs, stop_event=self._stop_event)
        finally:
            logger.info("Worker %s exited.", self.name)

    def stop(self) -> None:  # noqa: D401
        self._stop_event.set()


def register_signal_handlers(worker: StoppableWorker) -> None:
    def _handler(signum, _frame):  # noqa: D401, N801
        logger.info("Received signal %s, shutting down worker…", signum)
        worker.stop()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


# --------------------------------------------------------------------------- #
# CLI entry-point
# --------------------------------------------------------------------------- #


def _run_pipeline_loop(
    source: FileEventSource,
    pipeline: TransformationPipeline,
    *,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        for event in pipeline.process(source.stream()):
            StdoutSink.emit([event])
        # Sleep to avoid busy-looping in demo mode
        stop_event.wait(timeout=1.0)


def main(argv: Optional[List[str]] = None) -> None:  # noqa: D401
    """
    Example CLI:

        python -m src.module_5 path/to/events.ndjson --prometheus 8002
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="psn-transform",
        description="PulseStream Nexus transformation pipeline demo",
    )
    parser.add_argument("events_file", type=Path, help="Path to ND-JSON events file.")
    parser.add_argument(
        "--prometheus",
        type=int,
        default=None,
        metavar="PORT",
        help="Expose Prometheus metrics on the given port.",
    )
    parser.add_argument(
        "--verbose", "-v", action="count", default=0, help="Increase log verbosity."
    )
    args = parser.parse_args(argv)

    # Adjust log level
    if args.verbose == 1:
        logger.setLevel(logging.DEBUG)
    elif args.verbose >= 2:
        logger.setLevel(logging.NOTSET)

    if args.prometheus is not None:
        if Counter is None:
            parser.error(
                "Prometheus client not available. "
                "Install with `pip install prometheus_client`."
            )
        else:
            logger.info("Starting Prometheus metrics server on port %d…", args.prometheus)
            start_http_server(args.prometheus)  # type: ignore [call-arg]

    # Build pipeline
    strategies = [SentimentStrategy(), ToxicityStrategy(), ViralityStrategy()]
    pipeline = TransformationPipeline(strategies)

    # Launch worker thread
    source = FileEventSource(args.events_file)
    worker = StoppableWorker(_run_pipeline_loop, source, pipeline)
    register_signal_handlers(worker)
    worker.start()
    worker.join()  # wait indefinitely


# --------------------------------------------------------------------------- #
# Module execution
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
```