```python
"""
ledgerquest.shared
==================

Shared, engine-wide utilities that are reused throughout LedgerQuest Engine.
Nothing in this module should have a hard dependency on *game* domain code;
keep it generic so it can be imported by Lambda functions, container tasks,
and local tooling alike.

The intent is to provide a single, canonical place for:

1. Runtime configuration (env var parsing & defaults)
2. Structured logging initialisation
3. Lightweight metrics emission
4. Re-usable AWS SDK helpers
5. Base exception hierarchy

All helpers are written to be *import side-effect free*; expensive/remote
operations are performed lazily only when first needed.

This file doubles as the package’s public surface.  Any symbol added to
__all__ is considered part of the public API and should follow SemVer rules.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache, wraps
from types import TracebackType
from typing import Any, Callable, Generator, Iterable, Mapping, MutableMapping, Type, TypeVar

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

try:
    # Optional dependency for prettier, structured logs
    import structlog  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    structlog = None  # type: ignore


__all__ = [
    # Configuration / env
    "Settings",
    "get_settings",
    "Environment",
    # Logging
    "get_logger",
    # Metrics + timing helpers
    "put_metric",
    "metrics_timer",
    "timed",
    # AWS helpers
    "aws_client",
    # Exceptions
    "LedgerQuestError",
    "DataValidationError",
    "AWSServiceError",
    # Misc utils
    "json_dumps",
    "iso_now",
]

###############################################################################
# Configuration / Environment
###############################################################################

class Environment(str):
    """
    Enumerates the high-level deployment environment the engine is running in.
    """

    LOCAL = "local"
    DEV = "dev"
    STAGE = "stage"
    PROD = "prod"

    @classmethod
    def from_str(cls, value: str | None) -> "Environment":
        mapping = {
            "local": cls.LOCAL,
            "development": cls.DEV,
            "dev": cls.DEV,
            "staging": cls.STAGE,
            "stage": cls.STAGE,
            "prod": cls.PROD,
            "production": cls.PROD,
        }
        return mapping.get((value or "").lower(), cls.LOCAL)  # default to local


@dataclass(frozen=True, slots=True)
class Settings:
    """
    Runtime settings loaded primarily from environment variables.

    Use `get_settings()` instead of instantiating directly.
    """

    # Core
    service_name: str
    stage: Environment
    aws_region: str
    log_level: int

    # Feature flags
    enable_metrics: bool = True

    # Versioning / build
    build_sha: str | None = None

    # Misc
    _raw: Mapping[str, str | None] | None = None  # for troubleshooting

    # --------------------------------------------------------------------- #
    # Derived helpers
    # --------------------------------------------------------------------- #

    @property
    def is_local(self) -> bool:
        return self.stage == Environment.LOCAL

    @property
    def is_debug(self) -> bool:
        return self.log_level <= logging.DEBUG

    # --------------------------------------------------------------------- #
    # Factory
    # --------------------------------------------------------------------- #

    @classmethod
    def load(cls) -> "Settings":  # noqa: C901  (slightly longer, ok for config)
        """
        Load settings from environment variables.

        The method attempts to be Lambda-aware: when ``AWS_LAMBDA_FUNCTION_NAME``
        is present, default stage is considered *dev* unless explicitly set.
        """
        env = os.environ

        stage = Environment.from_str(env.get("STAGE") or env.get("ENV") or None)
        if stage == Environment.LOCAL and env.get("AWS_LAMBDA_FUNCTION_NAME"):
            # Running in Lambda but stage not explicitly provided
            stage = Environment.DEV

        try:
            log_level_name = (env.get("LOG_LEVEL") or "INFO").upper()
            log_level = getattr(logging, log_level_name)
        except AttributeError:
            log_level = logging.INFO

        settings = cls(
            service_name=env.get("SERVICE_NAME", "ledgerquest-engine"),
            stage=stage,
            aws_region=env.get("AWS_REGION", "us-east-1"),
            log_level=log_level,
            enable_metrics=env.get("ENABLE_METRICS", "true").lower() != "false",
            build_sha=env.get("BUILD_SHA"),
            _raw=dict(env),  # capture snapshot for debugging
        )
        return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Retrieve a cached, singleton instance of Settings.

    Unlike most frameworks, we avoid module-level instantiation to ensure
    deterministic behaviour during unit tests (settings can be patched before
    first call).
    """
    return Settings.load()


###############################################################################
# Logging
###############################################################################

def _configure_root_logger(level: int) -> logging.Logger:
    """
    Configure *root* logger.

    Using a separate function ensures idempotent configuration; multiple calls
    with different log levels will upgrade the level if needed but never lower
    it.
    """
    root = logging.getLogger()
    if not root.handlers:
        # First time initialisation
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)-8s] %(name)s - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(level)
    elif level < root.level:
        # Increase verbosity (lower numeric level)
        root.setLevel(level)
    return root


@lru_cache(maxsize=None)
def get_logger(name: str | None = None) -> logging.Logger:
    """
    Return a structured or classic logger depending on availability.

    The logger is cached per *name* using LRU, so repeated calls are cheap.
    """

    settings = get_settings()
    _configure_root_logger(settings.log_level)

    if structlog:
        # Ensure structlog is configured only once globally
        if not structlog.is_configured():
            structlog.configure(
                wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
                processors=[
                    structlog.processors.TimeStamper(fmt="iso", utc=True),
                    structlog.processors.add_log_level,
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer(),
                ],
            )
        return structlog.get_logger(name or settings.service_name)
    else:  # Fallback to stdlib logger
        return logging.getLogger(name or settings.service_name)


###############################################################################
# Metrics
###############################################################################

_METRIC_NAMESPACE = "LedgerQuest"


def _namespaced_metric(metric_name: str) -> tuple[str, list[dict[str, int | float]]]:
    """
    Prepare CloudWatch metric payload (namespace, data) for a *single* datum.
    """
    return (
        _METRIC_NAMESPACE,
        [
            {
                "MetricName": metric_name,
                "Value": 1,
                "Unit": "Count",
            }
        ],
    )


def put_metric(
    metric_name: str,
    value: float | int = 1,
    unit: str = "Count",
    dimensions: Mapping[str, str] | None = None,
) -> None:
    """
    Emit a custom CloudWatch metric using `boto3`'s `PutMetricData`.

    The function is intentionally *fire-and-forget*; failures are logged but
    never raised to calling code, preserving primary execution path.
    """
    settings = get_settings()
    if not settings.enable_metrics:
        return

    namespace, base_data = _namespaced_metric(metric_name)
    data: MutableMapping[str, Any] = base_data[0]  # we only send one datum
    data["Value"] = value
    data["Unit"] = unit
    if dimensions:
        data["Dimensions"] = [{"Name": k, "Value": v} for k, v in dimensions.items()]

    try:
        cw = aws_client("cloudwatch")
        cw.put_metric_data(Namespace=namespace, MetricData=[data])  # type: ignore[arg-type]
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
        logger = get_logger(__name__)
        logger.debug("Failed to publish metric", metric=metric_name, err=str(exc))


TFunc = TypeVar("TFunc", bound=Callable[..., Any])


def metrics_timer(metric_name: str | None = None) -> Callable[[TFunc], TFunc]:
    """
    Decorator to time a function and emit a CloudWatch metric of type *Milliseconds*.

    Example
    -------
        @metrics_timer("db_query_latency")
        def query_db(...):
            ...
    """

    def decorator(func: TFunc) -> TFunc:
        nonlocal metric_name
        metric_name = metric_name or f"{func.__module__}.{func.__name__}"

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):  # type: ignore[override]
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                put_metric(
                    metric_name, value=elapsed_ms, unit="Milliseconds"
                )

        return wrapper  # type: ignore[return-value]

    return decorator


@contextmanager
def timed(metric_name: str) -> Generator[None, None, None]:
    """
    Context manager variant of `metrics_timer`.

    Example
    -------
        with timed("frame_build"):
            build_frame()
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        put_metric(metric_name, value=elapsed_ms, unit="Milliseconds")


###############################################################################
# AWS helpers
###############################################################################

@lru_cache(maxsize=None)
def aws_client(service_name: str, **kwargs: Any) -> BaseClient:
    """
    Return a cached boto3 client for the given service.

    The cache avoids Lambda cold-start penalties where multiple modules import
    different helpers but ultimately require the same AWS client.
    """
    settings = get_settings()
    # Do **NOT** hardcode credentials here; rely on instance/Lambda roles.
    return boto3.client(
        service_name,
        region_name=settings.aws_region,
        **kwargs,
    )


###############################################################################
# Exception hierarchy
###############################################################################

class LedgerQuestError(Exception):
    """
    Base class for **all** custom LedgerQuest exceptions.
    """


class DataValidationError(LedgerQuestError):
    """
    Raised when incoming payload or state fails schema validation.
    """


class AWSServiceError(LedgerQuestError):
    """
    Raised when an AWS SDK call fails in an unrecoverable way.
    """


###############################################################################
# Misc utilities
###############################################################################

def json_dumps(obj: Any, **kwargs: Any) -> str:
    """
    A json.dumps wrapper that defaults to ``separators=(",", ":")`` and
    ``default=str`` to keep payloads compact yet robust.
    """
    return json.dumps(
        obj,
        separators=(",", ":"),
        default=str,
        **kwargs,
    )


def iso_now() -> str:
    """
    Return current UTC timestamp in ISO-8601 format (millisecond precision).
    """
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
