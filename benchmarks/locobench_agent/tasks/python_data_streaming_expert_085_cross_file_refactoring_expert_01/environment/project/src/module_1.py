```python
"""
PulseStream Nexus – Ingestion Module
====================================

This module implements the real–time ingestion layer for PulseStream Nexus.
It demonstrates (1) Strategy Pattern for pluggable social-network specific
consumers, (2) Observer Pattern for cross-cutting concerns such as monitoring
and error tracking, and (3) basic schema validation via Pydantic.

The code purposefully limits direct external I/O while keeping the structure
required for production deployment.  Third-party integrations (Kafka,
Prometheus, Sentry, etc.) are optional and safely degrade when the dependency
is absent, allowing the package to remain importable in constrained
environments (e.g., CI unit tests).

Author: PulseStream Nexus Engineering
"""
from __future__ import annotations

import json
import logging
import signal
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol, Type

try:
    # Confluent Kafka offers the best performance in production,
    # but `kafka-python` can be used as a fallback during testing.
    from confluent_kafka import Consumer, KafkaException, KafkaError  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    Consumer = None  # type: ignore
    KafkaException = Exception  # type: ignore
    KafkaError = Exception  # type: ignore

try:
    from prometheus_client import Counter, Gauge  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Minimal stubs for environments without prometheus_client
    class _Stub:  # noqa: D401
        def __init__(self, *_, **__) -> None:
            pass

        def labels(self, *_, **__) -> "_Stub":
            return self

        def inc(self, *_: Any, **__: Any) -> None:  # noqa: D401
            pass

    Counter = Gauge = _Stub  # type: ignore

try:
    import sentry_sdk  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    sentry_sdk = None  # type: ignore

from pydantic import BaseModel, ValidationError, Field

# --------------------------------------------------------------------------- #
# Logging Configuration
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
)
logger = logging.getLogger("pulstream.ingestion")

# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
INGESTED_EVENTS = Counter(
    "pulstream_ingested_events_total",
    "Total number of events successfully ingested",
    ["source"],
)
FAILED_EVENTS = Counter(
    "pulstream_failed_events_total",
    "Number of events that failed validation or processing",
    ["source", "reason"],
)
CURRENT_LAG = Gauge(
    "pulstream_ingestion_kafka_lag",
    "Current Kafka consumer lag in messages",
    ["source"],
)

# --------------------------------------------------------------------------- #
# Domain Model
# --------------------------------------------------------------------------- #
class SocialEvent(BaseModel):
    """
    Canonical social event model used across the platform.
    """

    id: str = Field(..., description="Unique event ID provided by the platform")
    user_id: str = Field(..., description="Actor that triggered the event")
    username: Optional[str] = Field(None, description="Human readable user name")
    platform: str = Field(..., description="Name of the social platform (e.g. Twitter)")
    content: str = Field(..., description="Raw content or message text")
    timestamp: float = Field(..., description="Unix time of creation")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional info")

    class Config:
        allow_mutation = False
        frozen = True


# --------------------------------------------------------------------------- #
# Observer Pattern – Pluggable Event Hooks
# --------------------------------------------------------------------------- #
class EventObserver(Protocol):  # pylint: disable=too-few-public-methods
    """
    Minimal observer protocol. Observers register side-effects triggered by
    incoming events (e.g., metrics, audit logging, error tracking).
    """

    def on_success(self, event: SocialEvent) -> None: ...

    def on_failure(self, raw_event: str, error: Exception) -> None: ...


class PrometheusObserver:
    """
    Observer that publishes per-network metrics to Prometheus.
    """

    def on_success(self, event: SocialEvent) -> None:
        INGESTED_EVENTS.labels(source=event.platform).inc()

    def on_failure(self, raw_event: str, error: Exception) -> None:
        # The caller is responsible for catching validation errors first.
        platform_hint = "unknown"
        if isinstance(error, ValidationError):
            try:
                platform_hint = json.loads(raw_event).get("platform", "unknown")
            except Exception:  # pylint: disable=broad-except
                pass
        FAILED_EVENTS.labels(source=platform_hint, reason=type(error).__name__).inc()


class SentryObserver:
    """
    Observer that relays errors to Sentry.
    """

    def __init__(self) -> None:
        if sentry_sdk is None:
            logger.warning("sentry-sdk not installed; SentryObserver disabled.")

    def on_success(self, event: SocialEvent) -> None:  # noqa: D401
        # No-op for success path
        pass

    def on_failure(self, raw_event: str, error: Exception) -> None:  # noqa: D401
        if sentry_sdk is None:
            return
        sentry_sdk.capture_exception(error, scope=None)


# --------------------------------------------------------------------------- #
# Strategy Pattern – Network Specific Ingestion
# --------------------------------------------------------------------------- #
class IngestionStrategy(ABC):
    """
    Abstract base class for network-specific ingestion strategies.
    """

    def __init__(self, observers: Iterable[EventObserver] | None = None) -> None:
        self._observers: List[EventObserver] = list(observers or [])
        self._stop_event = threading.Event()
        self._consumer = self._build_consumer()

    # --------------------------------------------------------------------- #
    # Framework Integration
    # --------------------------------------------------------------------- #
    @staticmethod
    def _build_consumer() -> Optional["Consumer"]:
        """
        Factory for Kafka consumer. May return None if Kafka packages are
        unavailable (allowing unit tests to mock consumption).
        """
        if Consumer is None:
            logger.warning("Kafka library not available; Consumer disabled.")
            return None

        # Note: In production, credentials and env-specific configs should be
        # fetched from a secret store or service registry.
        conf = {
            "bootstrap.servers": "localhost:9092",
            "group.id": "pulstream-ingestion",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
        return Consumer(conf)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def start(self) -> None:
        """
        Start the ingestion loop on the calling thread. This call blocks until
        `stop()` is invoked (e.g., via SIGTERM) or an unrecoverable Kafka error
        bubbles up.
        """
        logger.info("Starting %s ...", self.__class__.__name__)
        try:
            self._subscribe()
            while not self._stop_event.is_set():
                self._poll_and_process()
        finally:
            self._shutdown()

    def stop(self) -> None:
        """
        Gracefully shut down the ingestion loop (non-blocking).
        """
        logger.info("Stopping %s ...", self.__class__.__name__)
        self._stop_event.set()

    # --------------------------------------------------------------------- #
    # Event Loop Helpers
    # --------------------------------------------------------------------- #
    def _poll_and_process(self) -> None:
        """
        Poll one message from Kafka and process it through validation,
        observers, and domain hand-off.
        """
        if self._consumer is None:
            # In tests: call a no-op sleep to avoid hot loop
            time.sleep(1)
            return

        msg = self._consumer.poll(1.0)
        if msg is None:
            return
        if msg.error():
            self._handle_kafka_error(msg.error())
            return

        raw_event = msg.value().decode("utf-8")
        try:
            event = SocialEvent.parse_raw(raw_event)
            self.handle_event(event)
            self._notify_success(event)
            self._consumer.commit(msg)
        except ValidationError as err:
            logger.warning("Event validation failed: %s", err)
            self._notify_failure(raw_event, err)
        except Exception as err:  # pylint: disable=broad-except
            logger.exception("Unhandled error during processing")
            self._notify_failure(raw_event, err)

    def _handle_kafka_error(self, error: "KafkaError") -> None:
        """
        Handle recoverable / fatal Kafka errors according to best practices,
        raising only if necessary so the daemon can restart.
        """
        if error.retriable():
            logger.warning("Retriable Kafka error: %s", error)
            return
        logger.error("Fatal Kafka error encountered: %s", error)
        raise KafkaException(error)

    def _notify_success(self, event: SocialEvent) -> None:
        for obs in self._observers:
            try:
                obs.on_success(event)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Observer %s crashed during success callback", obs)

    def _notify_failure(self, raw_event: str, error: Exception) -> None:
        for obs in self._observers:
            try:
                obs.on_failure(raw_event, error)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Observer %s crashed during failure callback", obs)

    # --------------------------------------------------------------------- #
    # Strategy Specific Hooks
    # --------------------------------------------------------------------- #
    @abstractmethod
    def _subscribe(self) -> None:
        """
        Subscribe the consumer to one or more Kafka topics. Implementations may
        apply bespoke partitioning or pattern‐based subscription.
        """

    @abstractmethod
    def handle_event(self, event: SocialEvent) -> None:
        """
        Handle a fully validated event. Implementations can perform ETL,
        enrichment, or fan-out to downstream processors.
        """

    # --------------------------------------------------------------------- #
    # Cleanup
    # --------------------------------------------------------------------- #
    def _shutdown(self) -> None:
        if self._consumer:
            logger.info("Closing Kafka consumer ...")
            self._consumer.close()


# --------------------------------------------------------------------------- #
# Concrete Strategies
# --------------------------------------------------------------------------- #
class TwitterIngestionStrategy(IngestionStrategy):
    """
    Ingestion implementation for Twitter events. Additional business-specific
    logic such as tweet hydration, user profile enrichment, or partial
    redaction can be placed here.
    """

    TOPIC = "psn.twitter.raw"

    def _subscribe(self) -> None:
        if self._consumer:
            self._consumer.subscribe([self.TOPIC])
            logger.info("Subscribed to topic %s", self.TOPIC)

    def handle_event(self, event: SocialEvent) -> None:
        # Place domain-specific processing here
        logger.debug("Processing Twitter event %s", event.id)
        # Example placeholder for downstream pipeline hand-off
        # downstream_queue.put(event)


class RedditIngestionStrategy(IngestionStrategy):
    """
    Ingestion implementation for Reddit events.
    """

    TOPIC = "psn.reddit.raw"

    def _subscribe(self) -> None:
        if self._consumer:
            self._consumer.subscribe([self.TOPIC])
            logger.info("Subscribed to topic %s", self.TOPIC)

    def handle_event(self, event: SocialEvent) -> None:
        logger.debug("Processing Reddit event %s", event.id)
        # Domain business logic would be implemented here.


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
STRATEGY_REGISTRY: Dict[str, Type[IngestionStrategy]] = {
    "twitter": TwitterIngestionStrategy,
    "reddit": RedditIngestionStrategy,
    # Add more strategies here (e.g., MastodonIngestionStrategy)
}


def build_strategy(
    platform: str,
    observers: Iterable[EventObserver] | None = None,
) -> IngestionStrategy:
    """
    Factory that instantiates a strategy by name, defaulting to a no-op
    placeholder when the platform is unsupported.
    """
    if platform not in STRATEGY_REGISTRY:
        raise ValueError(f"Unsupported platform: {platform}")
    return STRATEGY_REGISTRY[platform](observers)


# --------------------------------------------------------------------------- #
# Graceful Shutdown Helper
# --------------------------------------------------------------------------- #
@dataclass
class _SignalHandleContext:
    """
    Internal dataclass to manage signal handler state.
    """

    strategy: IngestionStrategy
    original_sigint: Any
    original_sigterm: Any


@contextmanager
def graceful_shutdown(strategy: IngestionStrategy):
    """
    Context manager that installs SIGINT / SIGTERM handlers to gracefully stop
    an ingestion strategy inside a `with` block.

        with graceful_shutdown(strategy):
            strategy.start()
    """

    def _signal_handler(*_args):  # noqa: D401
        logger.info("Shutdown signal received (%s)", _args[0])
        strategy.stop()

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.debug("Signal handlers installed for strategy %s", strategy)
    try:
        yield
    finally:
        # Restore previous handlers
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)
        logger.debug("Signal handlers restored")


# --------------------------------------------------------------------------- #
# Main Entrypoint (when run as CLI)
# --------------------------------------------------------------------------- #
def _main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="PulseStream Nexus – Real-Time Ingestion Daemon"
    )
    parser.add_argument(
        "--platform",
        choices=list(STRATEGY_REGISTRY.keys()),
        required=True,
        help="Which social platform ingestion strategy to run",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging verbosity",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    observers: List[EventObserver] = [
        PrometheusObserver(),
        SentryObserver(),
    ]

    strategy = build_strategy(args.platform, observers)

    # Use the context manager so `Ctrl-C` terminates cleanly.
    with graceful_shutdown(strategy):
        strategy.start()


if __name__ == "__main__":
    _main()
```