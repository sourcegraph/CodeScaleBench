"""src/constants.py

PulseStream Nexus — central constants module
============================================

This module gathers together *immutable* configuration values, enumerations and
regex patterns that are referenced throughout the PulseStream Nexus code-base.
Keeping them colocated prevents circular imports, aids discoverability and
simplifies environment bootstrap logic.

The module is intentionally light-weight: **no third-party libraries** are
imported so that it can be imported by any package at any layer (including
domain entities and infra bootstrap scripts) without introducing heavy
dependencies.

Whenever possible, configuration is pulled from environment variables.  A small
helper function (`_get_env`) performs robust type-casting and validation so that
call-sites do not have to repeat boiler-plate parsing logic.

NOTE:
    • Constants are *read-only* by convention.  Any attempt to mutate them will
      raise a ``TypeError`` once `freeze()` has been invoked during start-up.
"""

from __future__ import annotations

import os
import re
import sys
from enum import Enum, unique
from pathlib import Path
from typing import Callable, Final, Iterable, Mapping, Sequence, Tuple, TypeVar

__all__ = [
    # Enums
    "SocialPlatform",
    "EventType",
    "ProcessingMode",
    # Regex patterns
    "MENTION_REGEX",
    "HASHTAG_REGEX",
    "URL_REGEX",
    # Runtime environment
    "ROOT_DIR",
    "ENV",
    "IS_PROD",
    "VERSION",
    # Infrastructure
    "KAFKA_BROKERS",
    "KAFKA_TOPICS",
    "SCHEMA_REGISTRY_URL",
    "SENTRY_DSN",
    "PROMETHEUS_PORT",
    # Misc
    "DEFAULT_TIME_WINDOWS",
    "RETRY_BACKOFF",
    # Sentinel & helpers
    "UNSET",
    "freeze",
]

T = TypeVar("T")

# ------------------------------------------------------------------------------
# Helper utilities
# ------------------------------------------------------------------------------


class _ConstantMutationError(TypeError):
    """Raised when an attempt is made to mutate a frozen constant."""


def _get_env(
    name: str,
    default: T | None = None,
    cast: Callable[[str], T] | None = None,
    *,
    choices: Iterable[T] | None = None,
) -> T:
    """Retrieve an environment variable with optional casting and validation.

    Args:
        name: Name of the environment variable.
        default: Value used if the variable is not set.  If *None* and the
                 variable is missing, ``KeyError`` is raised.
        cast: Function that converts the raw string into a target type.
        choices: Sequence of allowed values.  Only checked **after** casting.

    Returns:
        The converted value (or the raw string if *cast* is ``None``).

    Raises:
        KeyError:       When the env var is missing *and* no default is given.
        ValueError:     If casting fails or *choices* validation fails.
    """
    try:
        raw: str = os.environ[name]
    except KeyError as exc:
        if default is None:
            raise
        return default  # type: ignore[return-value]

    try:
        value: T = cast(raw) if cast else raw  # type: ignore[assignment]
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"Unable to cast environment variable {name!r} with value {raw!r}"
        ) from exc

    if choices is not None and value not in choices:
        raise ValueError(
            f"Environment variable {name!r} has invalid value {value!r}. "
            f"Allowed values: {sorted(choices)!r}"
        )
    return value


def _csv(value: str) -> Tuple[str, ...]:
    """Cast comma-separated string into a tuple of trimmed segments."""
    return tuple(part.strip() for part in value.split(",") if part.strip())


# ------------------------------------------------------------------------------
# Enumerations
# ------------------------------------------------------------------------------


@unique
class SocialPlatform(str, Enum):
    """Supported social networks."""

    TWITTER = "twitter"
    REDDIT = "reddit"
    MASTODON = "mastodon"
    DISCORD = "discord"
    BLUESKY = "bluesky"


@unique
class EventType(str, Enum):
    """Categorisation of incoming social events."""

    POST = "post"
    COMMENT = "comment"
    REPLY = "reply"
    RETWEET = "retweet"
    QUOTE = "quote"
    LIKE = "like"


@unique
class ProcessingMode(str, Enum):
    """Execution strategy used by the pipeline."""

    STREAMING = "streaming"
    BATCH = "batch"
    INTERACTIVE = "interactive"


# ------------------------------------------------------------------------------
# Regex patterns
# ------------------------------------------------------------------------------

MENTION_REGEX: Final[re.Pattern[str]] = re.compile(r"@([A-Za-z0-9_]{1,15})")
HASHTAG_REGEX: Final[re.Pattern[str]] = re.compile(r"#(\w{1,100})")
URL_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(https?://[^\s/$.?#].[^\s]*)", flags=re.IGNORECASE
)

# ------------------------------------------------------------------------------
# Runtime / Environment
# ------------------------------------------------------------------------------

ROOT_DIR: Final[Path] = Path(__file__).resolve().parents[1]
VERSION: Final[str] = "0.3.0"

ENV: Final[str] = _get_env(
    "PULSENEX_ENV",
    default="development",
    choices=("development", "staging", "production"),
)
IS_PROD: Final[bool] = ENV == "production"

# ------------------------------------------------------------------------------
# Infrastructure defaults
# ------------------------------------------------------------------------------

# Kafka
KAFKA_BROKERS: Final[Tuple[str, ...]] = _get_env(
    "KAFKA_BROKERS", default=("localhost:9092",), cast=_csv
)
KAFKA_TOPICS: Final[Mapping[str, str]] = {
    "RAW_EVENTS": "psn.raw.social_events.v1",
    "ENRICHED_EVENTS": "psn.enriched.social_events.v1",
    "AGGREGATES": "psn.analytics.aggregates.v1",
}

# Schema registry
SCHEMA_REGISTRY_URL: Final[str] = _get_env(
    "SCHEMA_REGISTRY_URL", default="http://localhost:8081"
)

# Monitoring / Observability
PROMETHEUS_PORT: Final[int] = _get_env("PROMETHEUS_PORT", default=8007, cast=int)
SENTRY_DSN: Final[str] = _get_env("SENTRY_DSN", default="")  # Empty string disables

# ------------------------------------------------------------------------------
# Business-logic related constants
# ------------------------------------------------------------------------------

# Rolling time windows (in seconds) commonly used throughout analytics jobs.
DEFAULT_TIME_WINDOWS: Final[Tuple[int, ...]] = (60, 300, 900, 3_600)

# Exponential backoff defaults for transient retry logic.
RETRY_BACKOFF: Final[dict[str, float]] = {
    "base": 0.25,  # initial delay in seconds
    "factor": 2.0,  # multiplier
    "max": 30.0,  # upper bound
    "jitter": 0.1,  # +- random jitter
}

# ------------------------------------------------------------------------------
# Sentinel values
# ------------------------------------------------------------------------------

class _UnsetType:
    """Sentinel singleton used to detect *explicitly* missing parameters."""

    __slots__ = ()

    def __bool__(self) -> bool:  # pragma: no cover
        return False

    def __repr__(self) -> str:  # pragma: no cover
        return "UNSET"


UNSET: Final = _UnsetType()

# ------------------------------------------------------------------------------
# Immutability enforcement
# ------------------------------------------------------------------------------

_frozen: bool = False


def __setattr__(name: str, value) -> None:  # type: ignore[override]
    if _frozen:
        raise _ConstantMutationError(
            f"Attempt to mutate constant {name!r}. Constants are frozen."
        )
    return super(__class__, globals()["__builtins__"]["object"]).__setattr__(name, value)  # type: ignore[attr-defined]


def freeze() -> None:
    """Prevent any further mutation of module-level variables.

    Should be invoked once during the application's bootstrap phase **after**
    all environment variables have been evaluated.
    """
    global _frozen
    _frozen = True


# Freeze automatically in production to catch accidental mutation early.
if IS_PROD:
    freeze()

# ------------------------------------------------------------------------------
# Developer Quality-of-Life helpers
# ------------------------------------------------------------------------------

def _debug_dump() -> None:  # pragma: no cover
    """Emit a helpful diagnostic dump of key runtime constants."""
    import json

    payload = {
        "version": VERSION,
        "env": ENV,
        "root_dir": str(ROOT_DIR),
        "kafka_brokers": KAFKA_BROKERS,
        "schema_registry": SCHEMA_REGISTRY_URL,
        "prometheus_port": PROMETHEUS_PORT,
        "sentry_enabled": bool(SENTRY_DSN),
        "frozen": _frozen,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":  # pragma: no cover
    _debug_dump()
