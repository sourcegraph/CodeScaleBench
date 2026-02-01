```python
"""
LedgerQuest Engine – Core Runtime Bootstrap
===========================================

This package initialises the runtime environment for every LedgerQuest
execution context—whether inside an AWS Lambda function, a Fargate GPU
container, or a local integration-test run.  Importing *ledgerquest.engine.core*
automatically:

1. Detects the runtime environment and configures a structured logger
   (plain-text for consoles, JSON for cloud logs).
2. Exposes a *bootstrap()* helper that loads configuration from
   environment variables / parameter stores / S3 (mocked here).
3. Discovers and registers engine plugins published through the
   ``ledgerquest.plugins`` entry-point group (see *setup.cfg*).
4. Provides a ``@stateless_function`` decorator used by gameplay-logic
   authors to annotate Lambda-compatible pure functions with metadata
   that the deployment tool-chain can pick up on.
5. Offers a thin abstraction over the event bus so that calling code can
   simply invoke ``dispatch_event(payload, detail_type=...)`` and let
   the implementation decide if the target is AWS EventBridge, a local
   async queue, or a mock object.

The goal is to keep this file *import-side-effect-free* except for safe
initialisation steps.  No network calls are made during import so that
cold-start latency remains negligible.

Usage Example
-------------

    from ledgerquest.engine.core import bootstrap, dispatch_event

    ctx = bootstrap(profile="integration-test")
    dispatch_event({"message": "hello"})

"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import os
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Mapping, MutableMapping, Optional, Protocol

try:
    # boto3 is optional; the engine can run in a fully mocked local mode.
    import boto3  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    boto3 = None  # type: ignore

# ---------------------------------------------------------------------------#
# Versioning
# ---------------------------------------------------------------------------#

__all__ = [
    "EngineContext",
    "bootstrap",
    "stateless_function",
    "dispatch_event",
    "register_plugin",
    "get_plugin",
    "PLUGIN_REGISTRY",
    "__version__",
]

__version__: str = "0.1.0"

# ---------------------------------------------------------------------------#
# Structured Logging Helpers
# ---------------------------------------------------------------------------#


class _JsonFormatter(logging.Formatter):
    """A minimal JSON log formatter that remains dependency-free."""

    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, separators=(",", ":"))


def _configure_logger() -> logging.Logger:
    logger = logging.getLogger("ledgerquest")
    if logger.handlers:
        # Avoid duplicate handlers on repeated imports (Lambda cold/warm).
        return logger

    logger.setLevel(os.getenv("LQ_LOG_LEVEL", "INFO").upper())

    handler: logging.Handler
    if sys.stderr.isatty():
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("[%(levelname)s] %(name)s - %(message)s")
        )
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())

    logger.addHandler(handler)
    logger.debug("LedgerQuest logger configured (isatty=%s)", sys.stderr.isatty())
    return logger


_LOG = _configure_logger()

# ---------------------------------------------------------------------------#
# Engine Context & Configuration
# ---------------------------------------------------------------------------#


@dataclass(slots=True)
class EngineContext:
    """
    Immutable runtime context object injected throughout the engine.
    """

    profile: str
    region: str
    account_id: str
    stage: str
    config: Mapping[str, Any] = field(default_factory=dict)
    plugins: Mapping[str, Any] = field(default_factory=dict)

    # Convenience look-ups
    @property
    def is_local(self) -> bool:
        return self.stage == "local"


def _load_remote_config(profile: str) -> Dict[str, Any]:
    """
    Placeholder for loading layered configuration from SSM, S3, or Parameter
    Store.  For unit-tests, this can be monkey-patched.
    """
    _LOG.debug("Loading remote configuration for profile=%s", profile)
    # A real implementation could use boto3 to fetch configuration here.
    return {"max_connections": 512, "feature_flags": {"new_physics": True}}


def bootstrap(
    *,
    profile: str = "default",
    stage: Optional[str] = None,
    force_reload: bool = False,
) -> EngineContext:
    """
    Bootstraps the runtime and returns a singleton *EngineContext*.

    Re-invoking *bootstrap()* with the same arguments re-uses the cached
    context unless *force_reload=True* is provided.
    """
    global _BOOTSTRAPPED_CTX

    if "_BOOTSTRAPPED_CTX" in globals() and not force_reload:
        return _BOOTSTRAPPED_CTX  # type: ignore[return-value]

    resolved_stage = stage or os.getenv("LQ_STAGE", "local")
    resolved_region = os.getenv("AWS_REGION", "us-east-1")
    resolved_account = os.getenv("AWS_ACCOUNT_ID", "000000000000")

    config_blob = _load_remote_config(profile) if resolved_stage != "local" else {}

    plugins = _discover_plugins()

    _BOOTSTRAPPED_CTX = EngineContext(
        profile=profile,
        region=resolved_region,
        account_id=resolved_account,
        stage=resolved_stage,
        config=config_blob,
        plugins=plugins,
    )

    _LOG.info(
        "LedgerQuest engine bootstrapped (stage=%s, region=%s, plugins=%d)",
        resolved_stage,
        resolved_region,
        len(plugins),
    )
    return _BOOTSTRAPPED_CTX


_BOOTSTRAPPED_CTX: Optional[EngineContext] = None

# ---------------------------------------------------------------------------#
# Plugin Registry (Entry-Point Discovery)
# ---------------------------------------------------------------------------#


class _PluginProtocol(Protocol):
    """
    Minimal protocol that every plugin should adhere to.

    Plugins can expose additional attributes; only *name* is required for
    registry bookkeeping.
    """

    name: str


PLUGIN_REGISTRY: Dict[str, _PluginProtocol] = {}


def register_plugin(plugin: _PluginProtocol) -> None:
    """Called by third-party code to imperatively register a plugin."""
    if plugin.name in PLUGIN_REGISTRY:
        raise ValueError(f"Plugin '{plugin.name}' is already registered")
    PLUGIN_REGISTRY[plugin.name] = plugin
    _LOG.debug("Plugin '%s' registered via register_plugin(..)", plugin.name)


def get_plugin(name: str) -> _PluginProtocol:
    """Fetches a plugin or raises KeyError if missing."""
    return PLUGIN_REGISTRY[name]


def _discover_plugins() -> Dict[str, _PluginProtocol]:
    """
    Discovers plugins via importlib.metadata entry points.  Uses a lazy import
    to avoid paying the cost when running in an AWS Lambda cold-start path
    where entry-point scanning can be expensive.
    """
    try:
        import importlib.metadata as importlib_metadata  # Py>=3.8
    except ImportError:  # pragma: no cover
        import importlib_metadata  # type: ignore

    discovered: Dict[str, _PluginProtocol] = {}

    with contextlib.suppress(Exception):
        eps = importlib_metadata.entry_points(group="ledgerquest.plugins")  # type: ignore[arg-type]
        for ep in eps:
            try:
                plugin: _PluginProtocol = ep.load()
                discovered[plugin.name] = plugin
                _LOG.debug("Discovered plugin '%s' via entry point", plugin.name)
            except Exception as exc:  # pragma: no cover
                _LOG.warning("Failed to load plugin '%s': %s", ep.name, exc)

    # Merge with any already-registered plugins (imperative takes precedence).
    discovered.update(PLUGIN_REGISTRY)
    PLUGIN_REGISTRY.update(discovered)
    return discovered


# ---------------------------------------------------------------------------#
# Stateless Function Decorator
# ---------------------------------------------------------------------------#


class StatelessFunctionMetadata(Protocol):
    """Metadata exposed on decorated callables."""

    lq_timeout_seconds: int
    lq_idempotent: bool
    lq_version: str


def stateless_function(
    *,
    timeout_seconds: int = 30,
    idempotent: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator for pure, deterministic functions that *could* be deployed as
    AWS Lambda steps inside a Step-Functions state machine.

    The decorator itself is runtime-no-op (it merely annotates attributes),
    allowing regular synchronous AND async callables.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, "lq_timeout_seconds", timeout_seconds)
        setattr(fn, "lq_idempotent", idempotent)
        setattr(fn, "lq_version", __version__)
        _LOG.debug(
            "Applied @stateless_function to %s (timeout=%ss, idempotent=%s)",
            fn.__qualname__,
            timeout_seconds,
            idempotent,
        )
        return fn

    return _decorator


# ---------------------------------------------------------------------------#
# Event Bus Abstraction
# ---------------------------------------------------------------------------#


class _EventDispatcher(Protocol):
    def __call__(self, event: Mapping[str, Any], *, detail_type: str) -> Awaitable[None]:
        ...


async def _aws_eventbridge_dispatch(
    event: Mapping[str, Any],
    *,
    detail_type: str,
) -> None:  # pragma: no cover
    """Sends the event to AWS EventBridge.  Requires *boto3*."""
    if boto3 is None:
        raise RuntimeError("boto3 is required for AWS dispatch but is not installed")

    client = boto3.client("events")
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.put_events(
            Entries=[
                {
                    "Source": "ledgerquest.engine",
                    "DetailType": detail_type,
                    "Detail": json.dumps(event, default=str),
                }
            ]
        ),
    )
    _LOG.debug("Event dispatched to AWS EventBridge (detail_type=%s)", detail_type)


async def _in_memory_dispatch(
    event: Mapping[str, Any],
    *,
    detail_type: str,
) -> None:
    """
    Local fallback that queues events in an asyncio.Queue(), enabling unit tests
    and local dev to observe side-effects without AWS.
    """
    if "_IN_MEMORY_QUEUE" not in globals():
        globals()["_IN_MEMORY_QUEUE"] = asyncio.Queue()  # type: ignore[attr-defined]
    queue: "asyncio.Queue[tuple[str, Mapping[str, Any]]]" = globals()["_IN_MEMORY_QUEUE"]  # type: ignore[assignment]
    await queue.put((detail_type, dict(event)))
    _LOG.debug("Event enqueued locally (detail_type=%s)", detail_type)


def _get_dispatcher(ctx: EngineContext) -> _EventDispatcher:
    if ctx.is_local:
        return _in_memory_dispatch
    return _aws_eventbridge_dispatch


def dispatch_event(
    event: Mapping[str, Any],
    *,
    detail_type: str,
    ctx: Optional[EngineContext] = None,
) -> None:
    """
    Fire-and-forget helper that proxies to the concrete dispatcher based on the
    runtime context.  This non-blocking wrapper is safe to call from sync code
    because it schedules the coroutine on the current event loop or spins up a
    new one if necessary.
    """
    _ctx = ctx or _BOOTSTRAPPED_CTX or bootstrap()

    dispatcher = _get_dispatcher(_ctx)

    coro = dispatcher(event, detail_type=detail_type)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # No running loop
        asyncio.run(coro)
    else:
        asyncio.create_task(coro)


# ---------------------------------------------------------------------------#
# Sentinel: auto-bootstrap in AWS Lambda runtime for convenience
# ---------------------------------------------------------------------------#

if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    # When executed as part of a Lambda invocation, auto-bootstrap using
    # environment variables.  Developers can still perform explicit bootstrap()
    # for local testing or customise by importing earlier in the cold-start path.
    bootstrap(profile=os.getenv("LQ_PROFILE", "lambda"))
```