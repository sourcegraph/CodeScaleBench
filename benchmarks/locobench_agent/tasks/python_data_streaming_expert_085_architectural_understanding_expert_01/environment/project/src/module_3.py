```python
"""
src/module_3.py

Adaptive Sentiment Transformation layer for PulseStream Nexus.
----------------------------------------------------------------
This module implements a Strategy–Observer hybrid that performs
context-aware sentiment / toxicity analysis on social-media
events while remaining agnostic of concrete I/O—conforming to
the platform’s Clean-Architecture service boundary.

Key responsibilities
--------------------
1. Provide multiple interchangeable sentiment strategies
   (Strategy Pattern) that downstream interactors can select
   at runtime (e.g., polarity, toxicity, or subjectivity).
2. Expose a thread-safe SentimentEngine façade that:
      • picks the appropriate strategy,
      • records structured SentimentResult objects,
      • broadcasts results to any registered observers
        (Observer Pattern) such as metrics reporters or
        asynchronous sinks.
3. Remain defensive with graceful degradation when optional
   NLP libraries (TextBlob, Detoxify) are missing.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, MutableMapping, Optional, Protocol, runtime_checkable, Union

# --------------------------------------------------------------------------- #
# Optional heavy dependencies – the import guard keeps core runtime light.
# --------------------------------------------------------------------------- #
try:
    from textblob import TextBlob  # pylint: disable=import-error
except ModuleNotFoundError:  # pragma: no cover
    TextBlob = None  # type: ignore

try:
    from detoxify import Detoxify  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    Detoxify = None  # type: ignore

# --------------------------------------------------------------------------- #
# Logging configuration (module-local; real projects would centralize this).
# --------------------------------------------------------------------------- #
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# --------------------------------------------------------------------------- #
# Domain primitives
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Event:
    """
    Immutable representation of an incoming social-stream message.

    The object is deliberately minimal; large, platform-specific
    payloads live in the adapter layer to preserve separation of
    concerns in Clean Architecture.
    """

    event_id: str
    platform: str
    text: str
    authored_at: datetime
    author_id: str
    metadata: Dict[str, Union[str, int, float]] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the event for observability/debugging."""
        return json.dumps(
            {
                "event_id": self.event_id,
                "platform": self.platform,
                "text": self.text,
                "authored_at": self.authored_at.isoformat(),
                "author_id": self.author_id,
                "metadata": self.metadata,
            },
            ensure_ascii=False,
        )


@dataclass
class SentimentResult:
    """
    Normalized sentiment output that downstream use-cases can rely on.
    """

    event_id: str
    platform: str
    strategy_name: str
    score: float
    magnitude: float
    label: str
    computed_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def to_json(self) -> str:
        """Serialize the result for transport/storage."""
        return json.dumps(
            {
                "event_id": self.event_id,
                "platform": self.platform,
                "strategy_name": self.strategy_name,
                "score": self.score,
                "magnitude": self.magnitude,
                "label": self.label,
                "computed_at": self.computed_at.isoformat(),
            },
            ensure_ascii=False,
        )


# --------------------------------------------------------------------------- #
# Sentiment Strategy abstractions
# --------------------------------------------------------------------------- #


class SentimentStrategy(ABC):
    """
    Base class for all sentiment analysis algorithms.
    """

    name: str = "base"

    @abstractmethod
    def analyze(self, event: Event) -> SentimentResult:
        """
        Derive sentiment metrics from an Event.

        Must return a SentimentResult with consistent semantics:
        • score      – signed value in range [-1, 1]
        • magnitude  – absolute intensity (≥ 0)
        • label      – discrete representation (e.g., 'POS', 'NEG')
        """
        raise NotImplementedError


class FallbackNeutralStrategy(SentimentStrategy):
    """
    Strategy used when a requested strategy is unavailable
    or external sentiment libraries are missing.
    """

    name = "neutral_fallback"

    def analyze(self, event: Event) -> SentimentResult:
        logger.debug("Using FallbackNeutralStrategy for event %s", event.event_id)
        return SentimentResult(
            event_id=event.event_id,
            platform=event.platform,
            strategy_name=self.name,
            score=0.0,
            magnitude=0.0,
            label="NEUTRAL",
        )


class PolarityStrategy(SentimentStrategy):
    """
    Sentiment polarity via TextBlob.
    """

    name = "polarity"

    def __init__(self) -> None:
        if TextBlob is None:  # pylint: disable=using-constant-test
            raise RuntimeError(
                "TextBlob is required for PolarityStrategy but is not installed."
            )

    def analyze(self, event: Event) -> SentimentResult:
        logger.debug("Running PolarityStrategy for event %s", event.event_id)
        blob = TextBlob(event.text)
        score = round(blob.sentiment.polarity, 4)
        magnitude = round(abs(score), 4)
        label = (
            "POS"
            if score > 0.1
            else "NEG"
            if score < -0.1
            else "NEUTRAL"
        )

        return SentimentResult(
            event_id=event.event_id,
            platform=event.platform,
            strategy_name=self.name,
            score=score,
            magnitude=magnitude,
            label=label,
        )


class SubjectivityStrategy(SentimentStrategy):
    """
    Subjectivity analysis using TextBlob’s subjectivity measure.
    """

    name = "subjectivity"

    def __init__(self) -> None:
        if TextBlob is None:  # pragma: no cover
            raise RuntimeError(
                "TextBlob is required for SubjectivityStrategy but is not installed."
            )

    def analyze(self, event: Event) -> SentimentResult:
        logger.debug("Running SubjectivityStrategy for event %s", event.event_id)
        blob = TextBlob(event.text)
        score = round(blob.sentiment.subjectivity, 4)
        magnitude = round(score, 4)  # For subjectivity, score == magnitude.
        label = (
            "SUBJECTIVE"
            if score >= 0.5
            else "OBJECTIVE"
            if score <= 0.2
            else "MIXED"
        )

        return SentimentResult(
            event_id=event.event_id,
            platform=event.platform,
            strategy_name=self.name,
            score=score,
            magnitude=magnitude,
            label=label,
        )


class ToxicityStrategy(SentimentStrategy):
    """
    Toxicity detection via Detoxify (Transformer model).
    """

    name = "toxicity"

    _model: Optional["Detoxify"] = None
    _model_lock = threading.Lock()

    def __init__(self) -> None:
        if Detoxify is None:
            raise RuntimeError(
                "Detoxify is required for ToxicityStrategy but is not installed."
            )
        # Lazy load the model only once
        with ToxicityStrategy._model_lock:
            if ToxicityStrategy._model is None:
                logger.info("Loading Detoxify model – may take a while…")
                ToxicityStrategy._model = Detoxify("original-small")

    def analyze(self, event: Event) -> SentimentResult:
        assert ToxicityStrategy._model is not None  # nosec
        logger.debug("Running ToxicityStrategy for event %s", event.event_id)
        prediction: MutableMapping[str, float] = ToxicityStrategy._model.predict(
            event.text
        )
        # The 'toxicity' field is common; we fall back to max otherwise.
        if "toxicity" in prediction:
            score = prediction["toxicity"]
        else:
            score = max(prediction.values())

        score = round(score, 4)
        magnitude = score
        label = "TOXIC" if score >= 0.5 else "NON_TOXIC"

        return SentimentResult(
            event_id=event.event_id,
            platform=event.platform,
            strategy_name=self.name,
            score=score,
            magnitude=magnitude,
            label=label,
        )


# --------------------------------------------------------------------------- #
# Observer protocol for downstream consumers
# --------------------------------------------------------------------------- #

@runtime_checkable
class SentimentObserver(Protocol):
    """
    Minimal observer interface for push-based consumption.
    """

    def update(self, result: SentimentResult) -> None: ...


class PrintObserver:
    """
    Toy implementation that prints to stdout (useful for demo/testing).
    """

    def update(self, result: SentimentResult) -> None:
        print(f"[{result.computed_at.isoformat()}] {result.to_json()}")


# --------------------------------------------------------------------------- #
# Engine façade
# --------------------------------------------------------------------------- #


class SentimentEngine:
    """
    Thread-safe façade that orchestrates strategy selection,
    error recovery, and observer notifications.
    """

    def __init__(self) -> None:
        self._strategies: Dict[str, SentimentStrategy] = {}
        self._observers: List[SentimentObserver] = []
        self._rw_lock = threading.RLock()

        # Built-in default fallback
        self.register_strategy(FallbackNeutralStrategy())

    # --------------------------------------------------
    # Strategy management
    # --------------------------------------------------

    def register_strategy(self, strategy: SentimentStrategy) -> None:
        with self._rw_lock:
            logger.debug("Registering strategy '%s'", strategy.name)
            self._strategies[strategy.name] = strategy

    def unregister_strategy(self, name: str) -> None:
        with self._rw_lock:
            logger.debug("Unregistering strategy '%s'", name)
            self._strategies.pop(name, None)

    def list_strategies(self) -> List[str]:
        with self._rw_lock:
            return list(self._strategies.keys())

    def _resolve_strategy(self, name: Optional[str]) -> SentimentStrategy:
        with self._rw_lock:
            if name and name in self._strategies:
                return self._strategies[name]
            # Attempt heuristic selection—example based on name patterns
            if name is None:
                return self._strategies.get("polarity") or next(
                    iter(self._strategies.values())
                )
            logger.warning("Unknown strategy '%s'; using fallback.", name)
            return self._strategies["neutral_fallback"]

    # --------------------------------------------------
    # Observer management
    # --------------------------------------------------

    def add_observer(self, observer: SentimentObserver) -> None:
        with self._rw_lock:
            self._observers.append(observer)

    def remove_observer(self, observer: SentimentObserver) -> None:
        with self._rw_lock:
            self._observers.remove(observer)

    def _notify_observers(self, result: SentimentResult) -> None:
        with self._rw_lock:
            for obs in list(self._observers):
                try:
                    obs.update(result)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.exception(
                        "SentimentObserver %s failed: %s", obs.__class__.__name__, exc
                    )

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    def analyze(
        self,
        event: Event,
        strategy_name: Optional[str] = None,
        notify: bool = True,
    ) -> SentimentResult:
        """
        Analyze an Event using the specified strategy (or automatic selection).

        Parameters
        ----------
        event:
            Domain Event to enrich with sentiment.
        strategy_name:
            Name of the registered strategy. If None, engine chooses.
        notify:
            If True, broadcast SentimentResult to observers.

        Returns
        -------
        SentimentResult
        """
        start_ts = time.perf_counter()
        strategy = self._resolve_strategy(strategy_name)
        logger.debug(
            "Selected strategy '%s' for event %s", strategy.name, event.event_id
        )

        try:
            result = strategy.analyze(event)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(
                "Strategy '%s' failed on event %s: %s",
                strategy.name,
                event.event_id,
                exc,
            )
            # Fallback to neutral if any error occurs.
            fallback = self._strategies.get("neutral_fallback", FallbackNeutralStrategy())
            result = fallback.analyze(event)

        duration_ms = round((time.perf_counter() - start_ts) * 1000, 2)
        logger.info(
            "Sentiment computed in %s ms using '%s' for event %s",
            duration_ms,
            result.strategy_name,
            event.event_id,
        )

        if notify:
            self._notify_observers(result)

        return result


# --------------------------------------------------------------------------- #
# Convenience factory for default engine instance
# --------------------------------------------------------------------------- #

def default_sentiment_engine() -> SentimentEngine:
    """
    Build a SentimentEngine with all built-in strategies that are
    available in the current runtime environment.
    """
    engine = SentimentEngine()

    # Register optional strategies guarded by availability.
    for strategy_cls in (PolarityStrategy, SubjectivityStrategy, ToxicityStrategy):
        try:
            strategy = strategy_cls()  # type: ignore[call-arg]
            engine.register_strategy(strategy)
        except RuntimeError as err:
            logger.warning("Skipping %s: %s", strategy_cls.__name__, err)

    # Attach stdout observer by default for demo envs.
    engine.add_observer(PrintObserver())
    return engine


# --------------------------------------------------------------------------- #
# Self-test / demo
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    demo_engine = default_sentiment_engine()

    # Example events
    samples = [
        Event(
            event_id="evt_001",
            platform="twitter",
            text="I absolutely love the new features!",
            authored_at=datetime.now(tz=timezone.utc),
            author_id="user_42",
        ),
        Event(
            event_id="evt_002",
            platform="reddit",
            text="This is the worst update ever. Totally unusable.",
            authored_at=datetime.now(tz=timezone.utc),
            author_id="user_17",
        ),
        Event(
            event_id="evt_003",
            platform="discord",
            text="Meh.",
            authored_at=datetime.now(tz=timezone.utc),
            author_id="user_99",
        ),
    ]

    for evt in samples:
        demo_engine.analyze(evt)
```