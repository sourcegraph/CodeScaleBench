```python
"""
ledgerquest.shared.utils
~~~~~~~~~~~~~~~~~~~~~~~~

A grab-bag of *battle-tested* helper utilities that are shared across the entire
LedgerQuest code-base.  Everything in this module is 100 % side-effect free and
safe to import from inside AWS Lambda’s global scope.

Highlights
----------
• Zero-dep structured logging that works both locally and in CloudWatch.
• Low-level AWS helpers (ARN parsing, boto3 client caching, stage detection).
• JSON helpers that understand `Decimal`, `datetime`, `UUID`, etc.
• Async + sync retry utilities with configurable, exponential back-off.
• Generic TTL cache & memoisation decorators to squeeze extra performance out
  of the  *“cold-start”* window.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import functools
import itertools
import json
import logging
import os
import re
import sys
import time
import types
import uuid
from decimal import Decimal
from threading import RLock
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)

try:
    import boto3  # Heavy-weight import ⇒ defer until runtime
    from botocore.client import BaseClient
except Exception:  # pragma: no cover
    boto3 = None  # type: ignore
    BaseClient = Any  # type: ignore


__all__ = [
    # Logging
    "get_logger",
    # JSON helpers
    "json_dumps",
    "json_loads",
    # AWS helpers
    "parse_arn",
    "get_boto3_client",
    "current_stage",
    "is_running_locally",
    # Generic utils
    "chunked",
    "timed",
    "retry",
    "async_retry",
    "ttl_cache",
]

####################################################################################
# Logging
####################################################################################

_LOG_LEVEL = os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO").upper()
_STRUCTURED = os.getenv("LEDGERQUEST_LOG_FORMAT", "auto").lower()
_LOCK = RLock()


def _detect_structured() -> bool:
    """
    Decide whether to enable JSON logging.

    * `LEDGERQUEST_LOG_FORMAT` can be `"json"`, `"plain"` or `"auto"`.
    * `"auto"` will output JSON **only** when running inside Lambda.
    """
    if _STRUCTURED in {"json", "plain"}:
        return _STRUCTURED == "json"

    # auto-detect: inside Lambda ⇒ prefer JSON
    return os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None


def get_logger(name: str | None = None, level: str = _LOG_LEVEL) -> logging.Logger:
    """
    Return a **singleton** logger configured for either structured JSON or plain text.

    The function is thread-safe and idempotent. Re-invoking it with the same
    arguments will always give you the same instance.

    Parameters
    ----------
    name:
        Name of the logger.  Defaults to the module name of the caller.
    level:
        Log-level (case-insensitive). Example: `"DEBUG"`, `"INFO"`, etc.
    """
    if name is None:
        # Walk the call-stack one frame up to get the caller’s module
        frame = sys._getframe(1)
        name = frame.f_globals.get("__name__", "ledgerquest")

    with _LOCK:
        logger = logging.getLogger(name)
        if logger.handlers:  # already configured
            return logger

        lvl = getattr(logging, str(level).upper(), logging.INFO)
        logger.setLevel(lvl)
        logger.propagate = False  # Don’t duplicate to root

        handler: logging.Handler
        if _detect_structured():
            handler = _JSONLogHandler()
        else:
            handler = logging.StreamHandler(sys.stdout)
            fmt = "[%(levelname)s] %(asctime)s %(name)s:%(lineno)d › %(message)s"
            handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))

        logger.addHandler(handler)
        return logger


class _JSONEncoder(json.JSONEncoder):
    """JSON encoder that gracefully serialises common non-default types."""

    def default(self, o: Any) -> Any:  # noqa: D401
        if isinstance(o, (Decimal,)):
            return float(o)
        if isinstance(o, (_dt.datetime, _dt.date)):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        # Fall back to default behaviour
        return super().default(o)


class _JSONLogHandler(logging.StreamHandler):
    """StreamHandler that outputs logs in structured JSON."""

    def __init__(self) -> None:
        super().__init__(stream=sys.stdout)
        self.encoder = _JSONEncoder()

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload = {
            "timestamp": _dt.datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "src": f"{record.pathname}:{record.lineno}",
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return self.encoder.encode(payload)


####################################################################################
# JSON helpers
####################################################################################

def json_dumps(obj: Any, *, sort_keys: bool = False, **kwargs: Any) -> str:
    """Dump *obj* to JSON using the shared encoder."""
    return json.dumps(obj, cls=_JSONEncoder, sort_keys=sort_keys, **kwargs)


def json_loads(s: str | bytes, **kwargs: Any) -> Any:
    """
    Thin wrapper around :pyfunc:`json.loads` with Decimal support
    (avoid float precision issues when dealing with financial data).
    """
    return json.loads(s, parse_float=Decimal, **kwargs)


####################################################################################
# AWS helpers
####################################################################################

_ARN_RE = re.compile(
    r"^arn:(?P<partition>aws[a-zA-Z-]*)?:"
    r"(?P<service>[a-z0-9-]+):"
    r"(?P<region>[a-z0-9-]*):"
    r"(?P<account_id>[0-9]*):"
    r"(?P<resource>.*)$"
)


def parse_arn(arn: str) -> Mapping[str, str]:
    """
    Parse an AWS ARN into its components.

    Returns a **read-only** mapping with keys:
    `partition`, `service`, `region`, `account_id`, `resource`.

    Raises ValueError on invalid ARN.
    """
    m = _ARN_RE.match(arn)
    if not m:
        raise ValueError(f"Invalid ARN: {arn!r}")
    return types.MappingProxyType(m.groupdict())


# Global client cache: {("service","region"): boto3_client}
_BOTO_CLIENTS: Dict[Tuple[str, Optional[str]], "BaseClient"] = {}
_BOTO_LOCK = RLock()


def get_boto3_client(
    service: str,
    *,
    region: str | None = None,
    fresh: bool = False,
    config: Any | None = None,
) -> "BaseClient":
    """
    Return a *cached* boto3 client.

    Parameters
    ----------
    service:
        AWS service name e.g. `"dynamodb"`, `"s3"`, etc.
    region:
        Explicit region, otherwise use Lambda’s default.
    fresh:
        Force creation of a new client (skip cache) – useful for tests.
    config:
        Optional botocore.config.Config to be forwarded.

    Notes
    -----
    The function takes a lock, making it thread-safe within Lambda’s single
    execution environment.
    """
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is not available in this environment")

    key = (service, region)
    with _BOTO_LOCK:
        if not fresh and key in _BOTO_CLIENTS:
            return _BOTO_CLIENTS[key]
        client = boto3.client(service, region_name=region, config=config)
        _BOTO_CLIENTS[key] = client
        return client


def current_stage() -> str:
    """
    Detect the active *deployment stage* (dev, staging, prod, …).

    The stage is determined in this order:

    1. `LEDGERQUEST_STAGE` env variable
    2. `AWS_LAMBDA_FUNCTION_NAME` suffix (`my-func-dev` ⇒ `dev`)
    3. Defaults to `"local"`
    """
    if stage := os.getenv("LEDGERQUEST_STAGE"):
        return stage.lower()

    fn = os.getenv("AWS_LAMBDA_FUNCTION_NAME", "")
    if m := re.match(r".+[-_]([a-zA-Z0-9]+)$", fn):
        return m.group(1).lower()
    return "local"


def is_running_locally() -> bool:
    """Return True when executed outside of AWS Lambda (e.g., pytest, local dev)."""
    return os.getenv("AWS_LAMBDA_FUNCTION_NAME") is None


####################################################################################
# Generic utilities
####################################################################################

T = TypeVar("T")
R = TypeVar("R")


def chunked(iterable: Iterable[T], n: int) -> Iterator[Tuple[T, ...]]:
    """
    Yield *n*-sized chunks from *iterable*.

    Example
    -------
    >>> list(chunked(range(5), 2))
    [(0, 1), (2, 3), (4,)]
    """
    if n <= 0:
        raise ValueError("Chunk size 'n' must be greater than 0")

    it = iter(iterable)
    while chunk := tuple(itertools.islice(it, n)):
        yield chunk


@contextlib.contextmanager
def timed(label: str, *, logger: logging.Logger | None = None) -> Generator[None, None, None]:
    """
    Context manager that logs the execution time of the wrapped block.

    Example
    -------
    >>> with timed("heavy_task"):
    ...     do_heavy_stuff()
    """
    _logger = logger or get_logger(__name__)
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1_000
        _logger.debug("%s took %.2f ms", label, duration_ms)


def retry(
    attempts: int = 3,
    *,
    backoff: float = 0.25,
    exceptions: Tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """
    Decorator that retries the wrapped function with exponential back-off.

    Parameters
    ----------
    attempts:
        Total attempts (initial call + retries).
    backoff:
        Base back-off in seconds; grows exponentially.
    exceptions:
        Tuple of exception classes that should trigger a retry.
    """
    def decorator(fn: Callable[..., R]) -> Callable[..., R]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> R:
            delay = backoff
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt >= attempts:
                        raise
                    logger = get_logger(fn.__module__)
                    logger.warning(
                        "%s failed (%s) – retry %d/%d in %.2f s",
                        fn.__name__,
                        exc,
                        attempt,
                        attempts,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
        return wrapper
    return decorator


def async_retry(
    attempts: int = 3,
    *,
    backoff: float = 0.25,
    exceptions: Tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """
    Async equivalent of :func:`retry`.
    """
    def decorator(fn: Callable[..., R]) -> Callable[..., R]:
        if not asyncio.iscoroutinefunction(fn):
            raise ValueError("async_retry can only wrap 'async def' functions")

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> R:
            delay = backoff
            for attempt in range(1, attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt >= attempts:
                        raise
                    logger = get_logger(fn.__module__)
                    logger.warning(
                        "%s failed (%s) – retry %d/%d in %.2f s",
                        fn.__name__,
                        exc,
                        attempt,
                        attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
        return wrapper
    return decorator


def ttl_cache(seconds: int = 60):
    """
    Decorator that caches the function’s result for a given TTL.

    Thread-safe and works for both sync & async functions.
    """
    def decorator(fn: Callable[..., R]) -> Callable[..., R]:
        lock = RLock()
        cached_at: float | None = None
        value: R | None = None

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> R:  # type: ignore[override]
                nonlocal cached_at, value
                with lock:
                    now = time.time()
                    if cached_at is None or (now - cached_at) > seconds:
                        value = None  # expire
                if value is not None:
                    return value
                result = await fn(*args, **kwargs)
                with lock:
                    cached_at, value = time.time(), result
                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> R:  # type: ignore[override]
            nonlocal cached_at, value
            with lock:
                now = time.time()
                if cached_at is None or (now - cached_at) > seconds:
                    value = None  # expire
                    cached_at = None
                if value is not None:
                    return value
            result = fn(*args, **kwargs)
            with lock:
                cached_at, value = time.time(), result
            return result

        return wrapper  # type: ignore[return-value]
    return decorator


####################################################################################
# End of file
####################################################################################
```