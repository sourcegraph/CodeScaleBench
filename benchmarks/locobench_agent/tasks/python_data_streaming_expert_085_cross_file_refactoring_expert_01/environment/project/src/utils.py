```python
"""
PulseStream Nexus – Utility helpers.

This module intentionally contains *zero* domain-specific logic.  Instead it
bundles together small, well-tested helpers that are widely re-used across the
entire code-base (from micro-services to batch jobs).  The goal is to centralise
generic concerns—configuration handling, retries, serialization, metrics,
etc.—so that higher layers can focus exclusively on business rules.

All functions/classes are pure or side-effect-free unless explicitly stated.
They are designed to run in both sync and async contexts, and degrade
gracefully when optional third-party dependencies (e.g. prometheus_client,
sentry_sdk) are not available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import sys
import time
import types
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from functools import wraps
from hashlib import blake2b
from inspect import signature
from itertools import islice
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    MutableMapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

logger = logging.getLogger("pulstream.utils")
logger.addHandler(logging.NullHandler())

# --------------------------------------------------------------------------- #
# Optional dependencies
# --------------------------------------------------------------------------- #
try:
    from prometheus_client import Counter, Histogram

    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover
    _HAS_PROMETHEUS = False
    Counter = Histogram = None  # type: ignore

try:
    import sentry_sdk

    _HAS_SENTRY = True
except ImportError:  # pragma: no cover
    _HAS_SENTRY = False

try:
    from pydantic import BaseSettings, Field, ValidationError  # type: ignore

    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False

# --------------------------------------------------------------------------- #
# Generic Types
# --------------------------------------------------------------------------- #
T = TypeVar("T")
R = TypeVar("R")
Func = TypeVar("Func", bound=Callable[..., Any])

# --------------------------------------------------------------------------- #
# Configuration Handling
# --------------------------------------------------------------------------- #


class _BaseSettings:
    """
    Fallback implementation when Pydantic is unavailable.

    Only implements a tiny subset of pydantic.BaseSettings behaviour that we use
    in the project (env var override + type coercion).
    """

    def __init_subclass__(cls, **kwargs):  # noqa: D401
        super().__init_subclass__(**kwargs)
        cls.__fields__: Dict[str, Any] = {
            key: value for key, value in cls.__dict__.items() if not key.startswith("_")
        }

    def __init__(self, **kwargs: Any) -> None:  # noqa: D401
        for field, default in self.__class__.__fields__.items():
            env_val = os.getenv(field.upper())
            value = kwargs.get(field, env_val if env_val is not None else default)
            try:
                # Naïve coercion
                if isinstance(default, bool):
                    value = str(value).lower() in {"1", "true", "yes", "on"}
                elif isinstance(default, int):
                    value = int(value)
                elif isinstance(default, float):
                    value = float(value)
            except Exception as exc:  # pragma: no cover
                raise ValueError(f"Invalid env var for {field}: {value}") from exc
            setattr(self, field, value)

    def dict(self) -> Dict[str, Any]:  # noqa: D401
        return {field: getattr(self, field) for field in self.__fields__}


if _HAS_PYDANTIC:

    class Settings(BaseSettings):  # type: ignore
        """
        Application-wide configuration model (pydantic powered).
        """

        LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")
        SENTRY_DSN: Optional[str] = Field(None, env="SENTRY_DSN")
        PROMETHEUS_ENABLED: bool = Field(True, env="PROMETHEUS_ENABLED")
        RETRY_MAX_ATTEMPTS: int = Field(5, env="RETRY_MAX_ATTEMPTS")
        RETRY_BASE_DELAY: float = Field(0.2, env="RETRY_BASE_DELAY")  # seconds
        class Config:  # noqa: D401
            env_prefix = ""  # we rely on explicit Field(env=...)

else:

    class Settings(_BaseSettings):  # type: ignore
        LOG_LEVEL: str = "INFO"
        SENTRY_DSN: Optional[str] = None
        PROMETHEUS_ENABLED: bool = True
        RETRY_MAX_ATTEMPTS: int = 5
        RETRY_BASE_DELAY: float = 0.2


settings = Settings()  # global immutable instance
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

# --------------------------------------------------------------------------- #
# Serialization Helpers
# --------------------------------------------------------------------------- #


class _PulseJSONEncoder(json.JSONEncoder):
    """
    Custom JSONEncoder that understands `datetime` objects and UUIDs.

    All datetimes are normalised to UTC ISO-8601 (`xxxxxZ`) to ensure
    consistent downstream parsing (e.g. BigQuery, Spark).
    """

    def default(self, obj: Any) -> Any:  # noqa: D401
        if isinstance(obj, (datetime, date)):
            # Always convert date to ISO; for Naïve dt -> assume UTC
            if isinstance(obj, datetime) and obj.tzinfo is None:
                obj = obj.replace(tzinfo=timezone.utc)
            iso = obj.astimezone(timezone.utc).isoformat()
            if iso.endswith("+00:00"):
                iso = iso[:-6] + "Z"
            return iso
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if hasattr(obj, "dict"):  # pydantic model or dataclass
            return obj.dict()  # type: ignore
        return super().default(obj)


def dumps(obj: Any, **kwargs: Any) -> str:  # noqa: D401
    """
    Serialize *obj* to JSON string using the project-wide encoder.
    """
    return json.dumps(obj, cls=_PulseJSONEncoder, **kwargs)


def loads(data: str | bytes, **kwargs: Any) -> Any:  # noqa: D401
    """
    Deserialize JSON (thin wrapper in case we need custom hook later).
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data, **kwargs)


# --------------------------------------------------------------------------- #
# Retry utilities
# --------------------------------------------------------------------------- #


class ExponentialBackoff:
    """
    Exponential back-off timer with full jitter (per AWS recommendations).

    Example
    -------
        backoff = ExponentialBackoff(base=0.25, factor=2, max_attempts=5)
        for attempt, delay in backoff:
            try:
                do_work()
                break
            except SomeError:
                logger.warning("Attempt %s failed; retrying in %.2fs", attempt, delay)
                await asyncio.sleep(delay)

    References
    ----------
    - https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter
    """

    def __init__(
        self,
        *,
        base: float = 0.25,
        factor: float = 2.0,
        max_attempts: int = 5,
        max_delay: float = 10.0,
    ) -> None:
        self.base = base
        self.factor = factor
        self.max_attempts = max_attempts
        self.max_delay = max_delay

    def __iter__(self) -> Iterator[Tuple[int, float]]:  # noqa: D401
        delay = self.base
        for attempt in range(1, self.max_attempts + 1):
            yield attempt, delay if delay < self.max_delay else self.max_delay
            delay = min(delay * self.factor, self.max_delay)

    # Async helper --------------------------------------------------------- #
    async def run_async(
        self,
        func: Callable[..., "Any"],
        *args: Any,
        fatal_exceptions: tuple[Type[BaseException], ...] = (),
        **kwargs: Any,
    ) -> Any:
        """
        Run *func* with retry and back-off.  Works for sync or async callables.
        """
        for attempt, delay in self:
            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except fatal_exceptions as fatal:  # pragma: no cover
                logger.error("Fatal error encountered: %s", fatal, exc_info=True)
                raise
            except Exception as exc:  # noqa: BLE001
                if attempt == self.max_attempts:
                    logger.error("Max attempts exceeded - raising error.")
                    raise
                jitter = random.uniform(0, delay)
                logger.warning(
                    "Retryable error (%s) on attempt %s/%s; sleeping %.3fs",
                    exc,
                    attempt,
                    self.max_attempts,
                    jitter,
                )
                await asyncio.sleep(jitter)


def _get_backoff_kwargs(kwargs: MutableMapping[str, Any]) -> Dict[str, Any]:
    """
    Extract back-off tunables from decorator arguments or fallback to settings.
    """
    return {
        "max_attempts": int(kwargs.pop("max_attempts", settings.RETRY_MAX_ATTEMPTS)),
        "base": float(kwargs.pop("base", settings.RETRY_BASE_DELAY)),
        **kwargs,
    }


def retry(  # noqa: D401
    **backoff_kwargs: Any,
) -> Callable[[Func], Func]:
    """
    Decorator to retry synchronous functions with exponential back-off.

    Example
    -------
        @retry(max_attempts=3)
        def flaky_io():
            if random.random() < 0.8:
                raise RuntimeError("Boom!")
            return 42
    """

    def decorator(fn: Func) -> Func:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):  # type: ignore[override]
            backoff = ExponentialBackoff(**_get_backoff_kwargs(backoff_kwargs))
            last_exc: Optional[Exception] = None
            for attempt, delay in backoff:
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == backoff.max_attempts:
                        break
                    jitter = random.uniform(0, delay)
                    logger.debug(
                        "Attempt %s/%s failed: %s. Retrying in %.3fs",
                        attempt,
                        backoff.max_attempts,
                        exc,
                        jitter,
                    )
                    time.sleep(jitter)
            # If we reached here, all retries exhausted
            raise last_exc if last_exc else RuntimeError("Retry failed without exception")

        return wrapper  # type: ignore[return-value]

    return decorator


def async_retry(  # noqa: D401
    **backoff_kwargs: Any,
) -> Callable[[Func], Func]:
    """
    Decorator for *async* functions supporting exponential back-off.
    """

    def decorator(fn: Func) -> Func:
        if not asyncio.iscoroutinefunction(fn):
            raise TypeError("@async_retry can only be applied to async functions")

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any):  # type: ignore[override]
            backoff = ExponentialBackoff(**_get_backoff_kwargs(backoff_kwargs))
            last_exc: Optional[Exception] = None
            for attempt, delay in backoff:
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == backoff.max_attempts:
                        break
                    jitter = random.uniform(0, delay)
                    logger.debug(
                        "[async_retry] Attempt %s/%s failed: %s. Retrying in %.3fs",
                        attempt,
                        backoff.max_attempts,
                        exc,
                        jitter,
                    )
                    await asyncio.sleep(jitter)
            raise last_exc if last_exc else RuntimeError("Async retry failed w/out exception")

        return wrapper  # type: ignore[return-value]

    return decorator


# --------------------------------------------------------------------------- #
# Metrics helpers
# --------------------------------------------------------------------------- #

if _HAS_PROMETHEUS and settings.PROMETHEUS_ENABLED:

    _REQUEST_LATENCY: Histogram = Histogram(  # type: ignore[call-arg]
        "pulse_request_latency_seconds",
        "Latency of service requests.",
        ["service", "method"],
        buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
    )
    _REQUEST_COUNT: Counter = Counter(  # type: ignore[call-arg]
        "pulse_request_total",
        "Count of service requests.",
        ["service", "method", "status"],
    )
else:
    _REQUEST_LATENCY = None
    _REQUEST_COUNT = None


@contextmanager
def record_metrics(service: str, method: str) -> Generator[None, None, None]:
    """
    Context-manager to measure execution time and count success/failure.

    Example
    -------
        with record_metrics("user-service", "fetch_user"):
            call_expensive_io()
    """
    start = time.perf_counter()
    exc: Optional[BaseException] = None
    try:
        yield
    except BaseException as err:  # noqa: BLE001
        exc = err
        raise
    finally:
        duration = time.perf_counter() - start
        if _REQUEST_LATENCY:
            _REQUEST_LATENCY.labels(service, method).observe(duration)
        if _REQUEST_COUNT:
            status = "error" if exc else "success"
            _REQUEST_COUNT.labels(service, method, status).inc()
        logger.debug(
            "Metrics[%s.%s] duration=%.4fs status=%s",
            service,
            method,
            duration,
            "error" if exc else "success",
        )


# --------------------------------------------------------------------------- #
# Miscellaneous helpers
# --------------------------------------------------------------------------- #


def chunked(iterable: Iterable[T], size: int) -> Iterator[List[T]]:  # noqa: D401
    """
    Break *iterable* into fixed-size lists.

    Example
    -------
        for page in chunked(users, 100):
            process(page)
    """
    if size <= 0:
        raise ValueError("size must be > 0")
    it = iter(iterable)
    while chunk := list(islice(it, size)):
        yield chunk


def stable_hash(value: Any, *, salt: str = "") -> str:  # noqa: D401
    """
    Compute a stable, short BLAKE2b hash for *value* (used for idempotency keys).
    """
    h = blake2b(digest_size=16, person=salt.encode("utf-8"))
    h.update(json.dumps(value, cls=_PulseJSONEncoder, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def signal_safe_shutdown(loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    """
    Register SIGINT/SIGTERM handlers so that *asyncio* applications can shut
    down gracefully.
    """

    async def _shutdown(sig: signal.Signals) -> None:  # noqa: D401
        logger.info("Received signal: %s. Cancelling outstanding tasks...", sig.name)
        tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
        [task.cancel() for task in tasks]
        await asyncio.gather(*tasks, return_exceptions=True)
        loop.stop()

    loop = loop or asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(_shutdown(s)),  # noqa: B023
        )


def setup_sentry(dsn: Optional[str] = None) -> None:
    """
    Initialize Sentry (if available) with the current release + python version.
    """
    if not _HAS_SENTRY:
        logger.debug("Sentry SDK not installed; skipping initialization.")
        return

    dsn = dsn or settings.SENTRY_DSN
    if not dsn:
        logger.debug("No SENTRY_DSN configured; skipping Sentry startup.")
        return

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.05,
        environment=os.getenv("ENVIRONMENT", "dev"),
        release=f"PulseStream@{os.getenv('GIT_COMMIT', 'local')}",
    )
    logger.info("Sentry initialized.")


def validate_callable_signature(fn: Callable[..., Any], expected: int | None = None) -> None:
    """
    Ensure a callable's signature matches *expected* number of parameters.

    Raises ValueError if the expectation isn't met.  Useful for pluggable
    strategy validation where duck-typing isn't obvious.
    """
    params = signature(fn).parameters
    if expected is not None and len(params) != expected:
        raise ValueError(
            f"Callable {fn.__name__} must accept {expected} parameters "
            f"but has {len(params)} ({list(params)})"
        )


# --------------------------------------------------------------------------- #
# __all__
# --------------------------------------------------------------------------- #

__all__ = [
    # config
    "settings",
    "Settings",
    # json
    "dumps",
    "loads",
    # retry
    "retry",
    "async_retry",
    "ExponentialBackoff",
    # metrics
    "record_metrics",
    # misc
    "chunked",
    "stable_hash",
    "signal_safe_shutdown",
    "setup_sentry",
    "validate_callable_signature",
]
```