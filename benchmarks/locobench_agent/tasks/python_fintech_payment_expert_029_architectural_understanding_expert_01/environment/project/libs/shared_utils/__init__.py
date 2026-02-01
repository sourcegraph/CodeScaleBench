```python
"""
crowdpay_connect.libs.shared_utils
=================================

Shared utilities that can be imported throughout the CrowdPay Connect
code-base.  The goal is to provide a *single*, well-tested surface area
for common functionality such as:

• Structured logging
• Environment/secret management
• Retry / back-off helpers (useful for distributed Sagas)
• Lightweight runtime settings
• Currency helpers
• Misc. convenience functions

Every public symbol is intentionally re-exported via ``__all__`` so that
type checkers (mypy, pyright, etc.) and IDEs can offer auto-completion
from a single import path:

    from crowdpay_connect.libs.shared_utils import (
        get_logger,
        settings,
        retry,
        saga_step,
        to_bool,
        to_int,
        format_currency,
        AuditEvent,
    )

This module must *not* import any project-internal application code to
avoid cyclic-dependencies.  Only third-party or standard-library imports
are permitted.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache, wraps
from typing import Any, Callable, Dict, Generator, Iterable, Optional, TypeVar, overload

# --------------------------------------------------------------------------- #
# Third-party imports (kept optional to avoid hard requirements during CI)    #
# --------------------------------------------------------------------------- #

try:
    from pydantic import BaseSettings, Field, ValidationError  # type: ignore
except ImportError:  # pragma: no cover
    BaseSettings = object  # type: ignore
    Field = lambda default=None, **_: Any  # type: ignore
    ValidationError = RuntimeError

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, RetryError  # type: ignore
except ImportError:  # pragma: no cover
    # A *very* small subset of tenacity’s interface, only what we need.
    T = TypeVar("T")

    def retry(
        *,
        stop: Callable[..., bool] | None = None,
        wait: Callable[..., float] | None = None,
        reraise: bool = True,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """
        Fallback retry decorator that retries a function up to three times with
        exponential back-off (1, 2, 4 seconds).  This is **not** feature-parity
        with tenacity—only a safety-net for environments where tenacity is
        unavailable.
        """

        stop_after = stop or (lambda attempt: attempt >= 3)
        wait_fn = wait or (lambda attempt: 2 ** (attempt - 1))

        def decorator(fn: Callable[..., T]) -> Callable[..., T]:
            @wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        return fn(*args, **kwargs)
                    except Exception:  # pragma: no cover
                        if stop_after(attempt):
                            if reraise:
                                raise
                            return None  # type: ignore
                        time.sleep(wait_fn(attempt))

            return wrapper

        return decorator

    class RetryError(RuntimeError):  # noqa: D401
        """Retry operation failed"""


# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #

_DEFAULT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_JSON_LOG_FORMAT = os.getenv("LOG_JSON", "false").lower() in {"1", "true", "yes"}


class _JsonFormatter(logging.Formatter):
    """
    Very small JSON log formatter.  Avoids adding heavyweight dependencies
    (e.g., python-json-logger) for a single feature.
    """

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        message = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "event": record.getMessage(),
        }
        if record.exc_info:
            message["exception"] = self.formatException(record.exc_info)
        return json.dumps(message, separators=(",", ":"))


@lru_cache(maxsize=None)
def _configure_root_logger() -> None:
    """
    Configure root logger exactly once (thread-safe thanks to `lru_cache`).

    This method installs either a colored console formatter or a JSON formatter
    depending on the ``LOG_JSON`` environment variable.
    """
    root = logging.getLogger()
    root.setLevel(_DEFAULT_LOG_LEVEL)

    if root.handlers:
        # Avoid duplicate handlers when running in environments that pre-configure logging
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    if _JSON_LOG_FORMAT:
        formatter: logging.Formatter = _JsonFormatter()
    else:
        fmt = "[%(asctime)s] %(levelname)s in %(name)s: %(message)s"
        formatter = logging.Formatter(fmt=fmt, datefmt="%Y-%m-%d %H:%M:%S%z")
    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Returns a module-level logger with shared configuration applied.

    Example
    -------
    >>> logger = get_logger(__name__)
    >>> logger.info("Hallo Welt")
    """
    _configure_root_logger()
    return logging.getLogger(name)


# --------------------------------------------------------------------------- #
# Environment helpers                                                         #
# --------------------------------------------------------------------------- #

def to_bool(value: str | int | bool | None, *, default: bool = False) -> bool:
    """
    Convert various truthy/falsey strings/ints to boolean.

    >>> to_bool("yes")
    True
    >>> to_bool("0")
    False
    """
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    value = value.strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def to_int(value: str | int | None, *, default: int | None = None) -> int | None:
    """
    Convert environment variable string to int with fallback.

    Raises
    ------
    ValueError if the conversion fails and no default is provided.
    """
    if value is None:
        if default is None:
            raise ValueError("Value cannot be None")
        return default

    if isinstance(value, int):
        return value

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        if default is not None:
            return default
        raise ValueError(f"Cannot parse int from {value!r}") from exc


# --------------------------------------------------------------------------- #
# Runtime settings (loaded once, cached)                                      #
# --------------------------------------------------------------------------- #

class _ServiceSettings(BaseSettings):  # type: ignore[misc]
    """
    Typed runtime configuration using Pydantic (if available).  All settings
    are sourced from environment variables, making it trivial to inject values
    via Docker/K8s secrets or CI pipelines.
    """

    # Application
    app_name: str = Field("crowdpay_connect")
    environment: str = Field("local", env="ENVIRONMENT")

    # Infrastructure
    redis_url: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    postgres_dsn: str = Field("postgresql://postgres@localhost:5432/crowdpay", env="POSTGRES_DSN")

    # Security / Compliance
    kyc_provider_api_key: str = Field("replace-me", env="KYC_PROVIDER_API_KEY")
    risk_threshold: float = Field(0.75, env="RISK_THRESHOLD")

    # Logging
    log_level: str = Field(_DEFAULT_LOG_LEVEL, env="LOG_LEVEL")
    log_json: bool = Field(_JSON_LOG_FORMAT, env="LOG_JSON")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def _load_settings() -> _ServiceSettings:
    """
    Load application settings only once for the lifetime of the process.
    If Pydantic is unavailable, fall back to a naive object.
    """
    try:
        return _ServiceSettings()  # type: ignore[call-arg]
    except ValidationError as err:  # pragma: no cover
        logger = get_logger(__name__)
        logger.error("Invalid configuration: %s", err)
        raise SystemExit(1) from err


settings = _load_settings()

# --------------------------------------------------------------------------- #
# Retry helper (wraps tenacity’s default config)                              #
# --------------------------------------------------------------------------- #

def retryable(
    *, tries: int = 5, min_seconds: float = 0.5, max_seconds: float = 10.0
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Generic retry decorator using `tenacity` if available or the internal
    fallback.  Synonymous to:

    @retryable(tries=3)
    def call_payment_service():
        ...
    """

    stop_strategy = stop_after_attempt(tries)  # type: ignore[name-defined]
    wait_strategy = wait_exponential(min=min_seconds, max=max_seconds)  # type: ignore[name-defined]

    return retry(stop=stop_strategy, wait=wait_strategy, reraise=True)  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Saga pattern instrumentation                                                #
# --------------------------------------------------------------------------- #

@contextmanager
def saga_step(name: str, *, logger: Optional[logging.Logger] = None) -> Generator[None, None, None]:
    """
    Context-manager that logs the start/end (success/failure) of a distributed
    Saga step.  It automatically attaches a correlation ID to each log record
    so that a complete end-to-end trail can be reconstructed across services.
    """

    _log = logger or get_logger(f"saga.{name}")
    correlation_id = uuid.uuid4().hex

    _log.debug(
        "Saga-step %s started ‑ correlation_id=%s",
        name,
        correlation_id,
        extra={"correlation_id": correlation_id},
    )
    try:
        yield
    except Exception as exc:
        _log.exception(
            "Saga-step %s failed ‑ correlation_id=%s ‑ %s: %s",
            name,
            correlation_id,
            exc.__class__.__name__,
            exc,
            extra={"correlation_id": correlation_id},
        )
        raise
    else:
        _log.debug(
            "Saga-step %s complete ‑ correlation_id=%s",
            name,
            correlation_id,
            extra={"correlation_id": correlation_id},
        )


# --------------------------------------------------------------------------- #
# Audit events (event sourcing baseline schema)                               #
# --------------------------------------------------------------------------- #

@dataclass(slots=True, frozen=True)
class AuditEvent:
    """
    Canonical audit event emitted by micro-components.  While an *immutable*
    dataclass is sufficient here, events are eventually persisted in the event
    store via Kafka / Pulsar in production.
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    type: str = "generic"
    actor_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": self.event_id,
                "type": self.type,
                "actor_id": self.actor_id,
                "timestamp": self.timestamp.isoformat(),
                "payload": self.payload,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, data: str | bytes | bytearray) -> "AuditEvent":
        obj = json.loads(data)
        return cls(
            event_id=obj["event_id"],
            type=obj["type"],
            actor_id=obj["actor_id"],
            timestamp=datetime.fromisoformat(obj["timestamp"]),
            payload=obj.get("payload", {}),
        )


# --------------------------------------------------------------------------- #
# Currency helpers                                                            #
# --------------------------------------------------------------------------- #

_CURRENCY_SYMBOLS: Dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "NGN": "₦",
    "JPY": "¥",
    "AUD": "A$",
}


@overload
def format_currency(amount: float | int, currency: str = "USD", /) -> str:
    ...


def format_currency(amount: float | int, currency: str = "USD", /) -> str:
    """
    Very lightweight currency formatter used for UI-facing notifications.
    Does *not* attempt to localize decimal separators or symbol placement.

    >>> format_currency(12.5, "EUR")
    '€12.50'
    """
    symbol = _CURRENCY_SYMBOLS.get(currency.upper(), currency.upper() + " ")
    return f"{symbol}{amount:,.2f}"


# --------------------------------------------------------------------------- #
# Public interface                                                            #
# --------------------------------------------------------------------------- #

__all__: Iterable[str] = (
    "get_logger",
    "settings",
    "retryable",
    "saga_step",
    "to_bool",
    "to_int",
    "format_currency",
    "AuditEvent",
    "RetryError",
)
```