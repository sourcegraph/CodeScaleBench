"""
LedgerQuest Engine
==================

Top-level package initialization for the LedgerQuest Engine.  This module is
responsible for

1.  Boot-strapping logging and configuration.
2.  Creating an application-wide EngineContext that exposes AWS resources
    (DynamoDB, S3, EventBridge, Step Functions, …) and helper utilities
    often required inside stateless Lambda functions.
3.  Discovering and loading plug-ins declared via Python entry-points
    (``ledgerquest_engine.plugins``) so that feature teams can extend the core
    engine without touching this repository.
4.  Surfacing a minimal public API so downstream code can access the current
    EngineContext *safely* without relying on global variables sprinkled
    across the code-base.

The file is intentionally placed in ``ledgerquest/engine/__init__.py`` rather
than buried inside a sub-module, as Lambda cold-starts benefit from having
as little indirection as possible.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import logging
import os
import sys
import types
import uuid
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional

# --------------------------------------------------------------------------- #
# 3rd-party imports — soft-dependencies                                       #
# --------------------------------------------------------------------------- #
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ModuleNotFoundError:  # Graceful degradation when running in local mode
    boto3 = None  # type: ignore
    ClientError = BotoCoreError = Exception  # type: ignore


__all__ = [
    "VERSION",
    "EngineContext",
    "init",
    "context",
    "require_initialized",
    "ConfigurationError",
    "EngineNotInitializedError",
]

VERSION: str = "0.9.3"  # Updated by CI pipeline


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #
class ConfigurationError(RuntimeError):
    """Raised when the configuration file cannot be parsed or is invalid."""


class EngineNotInitializedError(RuntimeError):
    """Raised when code attempts to access the global context before init()."""


# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #
def _bootstrap_logging() -> logging.Logger:
    """
    Create a root logger with sane defaults. The formatting and levels can later
    be overridden by the user's configuration file or environment variables.

    Returns
    -------
    logging.Logger
        The root logger instance.
    """
    log_level_str = os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("ledgerquest.engine")


_LOG = _bootstrap_logging()

# --------------------------------------------------------------------------- #
# Engine Context                                                              #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class EngineContext:
    """
    A *thin* dependency-injection container that bundles all networking and I/O
    clients required across the engine code-base.  Designed to be:

    1. Pickle-able (important for multiprocessing / batching tasks).
    2. Immutable after initialisation except explicitly whitelisted fields.
    """

    config: Mapping[str, Any]
    """Loaded JSON/YAML configuration as a read-only mapping."""

    # AWS resources – optional for non-AWS environments
    boto_session: Optional["boto3.Session"] = field(repr=False, default=None)
    dynamodb: Optional[Any] = field(repr=False, default=None)
    s3: Optional[Any] = field(repr=False, default=None)
    event_bridge: Optional[Any] = field(repr=False, default=None)
    step_functions: Optional[Any] = field(repr=False, default=None)

    # Run-time meta information
    logger: logging.Logger = field(repr=False, default_factory=lambda: _LOG.getChild("context"))
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex, init=False)

    # Plug-in registry
    plugins: Dict[str, types.ModuleType] = field(default_factory=dict, repr=False)

    # --------------------------------------------------------------------- #
    # Helper utilities                                                      #
    # --------------------------------------------------------------------- #
    def publish_event(
        self,
        *,
        detail_type: str,
        detail: Mapping[str, Any],
        source: str = "ledgerquest.engine",
        event_bus_name: Optional[str] = None,
    ) -> None:
        """
        Dispatch an event to Amazon EventBridge (or noop locally).

        Parameters
        ----------
        detail_type:
            The *detail-type* attribute used by Rule filters.
        detail:
            JSON-serialisable Python mapping.
        source:
            The *source* attribute of the EventBridge event.
        event_bus_name:
            Custom event bus ARN/name. Defaults to the account's default bus.
        """
        if not self.event_bridge:  # Local dev or stubs
            self.logger.debug("EventBridge client missing; skipping publish_event.")
            return

        event = {
            "Time": None,  # Let AWS assign server-side timestamp
            "Source": source,
            "Resources": [],
            "DetailType": detail_type,
            "Detail": json.dumps(detail),
        }

        if event_bus_name:
            event["EventBusName"] = event_bus_name  # type: ignore[typeddict-item]

        self.logger.debug("Publishing EventBridge event: %s", event)

        try:
            self.event_bridge.put_events(Entries=[event])
        except ClientError as exc:
            self.logger.error("Failed to put EventBridge event: %s", exc, exc_info=True)

    # --------------------------------------------------------------------- #
    # DynamoDB helpers                                                      #
    # --------------------------------------------------------------------- #
    def put_state(self, table_name: str, item: Mapping[str, Any]) -> None:
        """Write a game entity state‐record to DynamoDB."""
        if not self.dynamodb:
            self.logger.debug("DynamoDB resource missing; skipping put_state.")
            return
        try:
            table = self.dynamodb.Table(table_name)
            table.put_item(Item=dict(item))
        except ClientError as exc:
            self.logger.error("put_state(%s) failed: %s", table_name, exc, exc_info=True)

    def get_state(self, table_name: str, key: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """Retrieve a game entity state‐record from DynamoDB."""
        if not self.dynamodb:
            self.logger.debug("DynamoDB resource missing; skipping get_state.")
            return None
        try:
            table = self.dynamodb.Table(table_name)
            resp = table.get_item(Key=dict(key))
            return resp.get("Item")
        except ClientError as exc:
            self.logger.error("get_state(%s) failed: %s", table_name, exc, exc_info=True)
            return None

    # --------------------------------------------------------------------- #
    # Step Functions helpers                                                #
    # --------------------------------------------------------------------- #
    def start_state_machine(self, state_machine_arn: str, *, input_: Mapping[str, Any] | None = None) -> None:
        """Invoke an AWS Step Functions state machine."""
        if not self.step_functions:
            self.logger.debug("StepFunctions client missing; skipping start_state_machine.")
            return
        try:
            self.step_functions.start_execution(
                stateMachineArn=state_machine_arn,
                input=json.dumps(input_ or {}),
            )
        except ClientError as exc:
            self.logger.error("Failed to start state machine %s: %s", state_machine_arn, exc, exc_info=True)

    # --------------------------------------------------------------------- #
    # Plug-ins                                                              #
    # --------------------------------------------------------------------- #
    def register_plugin(self, name: str, module: types.ModuleType) -> None:
        """Register a plugin inside the global registry (idempotent)."""
        if name in self.plugins:
            self.logger.debug("Plugin %s already registered; ignoring.", name)
            return
        self.plugins[name] = module
        self.logger.info("Registered LedgerQuest plugin: %s", name)


# --------------------------------------------------------------------------- #
# Global runtime                                                               #
# --------------------------------------------------------------------------- #
_CONTEXT: Optional[EngineContext] = None


def require_initialized(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that raises EngineNotInitializedError when the global context has
    not been boot-strapped yet.  Prevents *implicit* lazy initialisation, which
    can break during Lambda parallel invocations.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any):  # noqa: ANN401
        if _CONTEXT is None:
            raise EngineNotInitializedError("LedgerQuest Engine has not been initialised yet. Call init() first.")
        return func(*args, **kwargs)

    return wrapper


@require_initialized
def context() -> EngineContext:
    """Return the currently active EngineContext."""
    # mypy: the decorator guarantees _CONTEXT is not None
    return _CONTEXT  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Initialization                                                              #
# --------------------------------------------------------------------------- #
def init(  # noqa: C901  — complexity acceptable for bootstrap
    *,
    config_path: str | Path | None = None,
    boto_session: Optional["boto3.Session"] = None,
    discover_plugins: bool = True,
) -> EngineContext:
    """
    Initialise the LedgerQuest Engine.

    This function is *idempotent*; calling it more than once will return the
    previously created EngineContext to avoid hidden state.

    Parameters
    ----------
    config_path:
        Absolute or relative path to a JSON/YAML configuration file.  When
        omitted, the function looks for ``$LEDGERQUEST_CONFIG`` environment
        variable and eventually falls back to an empty dict.
    boto_session:
        Pre-constructed ``boto3.Session``.  Useful when re-using credentials
        between multiple AWS clients in the same Lambda.
    discover_plugins:
        Whether to auto-discover Python entry-points (``ledgerquest_engine.plugins``).
    """
    global _CONTEXT  # noqa: PLW0603

    if _CONTEXT is not None:
        _LOG.debug("LedgerQuest Engine already initialised; reusing existing context.")
        return _CONTEXT

    # --------------------------------------------------------------------- #
    # Configuration                                                         #
    # --------------------------------------------------------------------- #
    cfg_path = (
        Path(config_path).expanduser()
        if config_path
        else Path(os.getenv("LEDGERQUEST_CONFIG", "")).expanduser()
        if os.getenv("LEDGERQUEST_CONFIG")
        else None
    )

    configuration: Dict[str, Any] = {}
    if cfg_path:
        if not cfg_path.exists():
            raise ConfigurationError(f"Configuration file not found: {cfg_path}")
        try:
            if cfg_path.suffix in {".yaml", ".yml"}:
                import yaml  # Lazy import to avoid hard dependency
                configuration = yaml.safe_load(cfg_path.read_text()) or {}
            else:
                configuration = json.loads(cfg_path.read_text())
        except Exception as exc:  # noqa: BLE001
            raise ConfigurationError(f"Failed to parse configuration file {cfg_path}: {exc}") from exc

    _LOG.debug("Loaded configuration: %s", configuration)

    # --------------------------------------------------------------------- #
    # AWS Session + clients                                                 #
    # --------------------------------------------------------------------- #
    session = boto_session
    if boto3 is None:
        _LOG.warning("boto3 not available; running in no-AWS mode.")
    else:
        session = session or boto3.Session()  # type: ignore[misc]
    if session:
        dynamodb = session.resource("dynamodb")
        s3 = session.client("s3")
        event_bridge = session.client("events")
        step_functions = session.client("stepfunctions")
    else:
        dynamodb = s3 = event_bridge = step_functions = None

    # --------------------------------------------------------------------- #
    # Construct context                                                     #
    # --------------------------------------------------------------------- #
    _CONTEXT = EngineContext(
        config=types.MappingProxyType(configuration),
        boto_session=session,
        dynamodb=dynamodb,
        s3=s3,
        event_bridge=event_bridge,
        step_functions=step_functions,
    )

    _LOG.info("LedgerQuest Engine initialised (request_id=%s)", _CONTEXT.request_id)

    # --------------------------------------------------------------------- #
    # Plug-in discovery                                                     #
    # --------------------------------------------------------------------- #
    if discover_plugins:
        _discover_and_register_plugins(_CONTEXT)

    return _CONTEXT


def _discover_and_register_plugins(ctx: EngineContext) -> None:  # noqa: D401
    """Search ``ledgerquest_engine.plugins`` entry-points and import them."""
    try:
        # importlib.metadata is stdlib in 3.10+, else fallback
        try:
            from importlib.metadata import entry_points, EntryPoint  # type: ignore
        except ImportError:  # pragma: no cover  — Python < 3.10
            from importlib_metadata import entry_points, EntryPoint  # type: ignore

        eps: Iterable["EntryPoint"] = entry_points(group="ledgerquest_engine.plugins")  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        ctx.logger.warning("Plugin discovery failed: %s", exc, exc_info=True)
        return

    for ep in eps:
        try:
            module = ep.load()
            if hasattr(module, "register") and callable(module.register):
                module.register(ctx)  # type: ignore[attr-defined]
            ctx.register_plugin(ep.name, module)
        except Exception as exc:  # noqa: BLE001
            ctx.logger.error("Failed to load plugin %s: %s", ep.name, exc, exc_info=True)


# --------------------------------------------------------------------------- #
# Convenience: automatic initialisation in AWS Lambda flex-mode               #
# --------------------------------------------------------------------------- #
#
# When running inside AWS Lambda the *preferred* pattern is still to call
# ledgerquest.engine.init() explicitly at top of the handler.  However, to
# reduce friction for quick-start tutorials we attempt a best-effort implicit
# bootstrap by inspecting environment variables commonly present in Lambda.
#
if (
    os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    and os.getenv("LEDGERQUEST_AUTO_INIT", "true").lower() in {"1", "true", "yes"}
):
    with contextlib.suppress(Exception):
        init()  # pragma: no cover


# EOF 🏴‍☠️