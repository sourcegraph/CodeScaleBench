```python
"""
LedgerQuest Engine – Serverless Business-Grade Game Framework
=============================================================

This package initialises the LedgerQuest engine, exposes a concise public API
for host applications (be that a Lambda function, a local integration test,
or a Jupyter notebook) and boot-straps optional plug-ins discovered through
Python entry-points.

Because *everything* in LedgerQuest is ultimately executed inside a stateless
function (AWS Lambda, Step-Functions Task, API-GW WebSocket route, Fargate
task, etc.) most “long-lived” objects below are in fact light-weight singletons
that can be recreated at will.  The module therefore keeps *very little* global
state – just enough to cache expensive reflection / plug-in discovery results.

High-level responsibilities
---------------------------
1. Version, build meta-data and semantic logger initialisation
2. Runtime-environment inspection (local vs AWS Lambda vs container)
3. Declarative registration helpers (ECS components, systems, commands)
4. An `Engine` façade that:
   * Loads / validates `EngineConfig`
   * Provides a synchronous `start/stop` life-cycle for local tests
   * Exposes ``dispatch_command`` – the canonical, stateless invocation point
5. A convenience `lambda_handler` usable as the entry-point for Lambda
   functions created through AWS SAM / CDK / Serverless-Framework.

Note
----
This file purposefully avoids heavy, third-party dependencies.  Everything that
*must* be optional is lazily imported behind try/except blocks so the package
remains importable even in slim runtime environments.

Author  : LedgerQuest Core Team
Copyright © 2024
License : Apache-2.0
"""
from __future__ import annotations

import json
import logging
import os
import sys
import types
import uuid
from dataclasses import dataclass, field
from enum import Enum
from importlib import import_module
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

# --------------------------------------------------------------------------- #
# Package metadata                                                            #
# --------------------------------------------------------------------------- #

try:
    # When installed through pip the version is provided by package metadata
    __version__: str = importlib_metadata.version("ledgerquest")
except importlib_metadata.PackageNotFoundError:  # pragma: no cover
    # Development fallback – derive version from git or default to 0.0.0-dev
    __version__ = os.environ.get("LEDGERQUEST_VERSION", "0.0.0-dev")

__all__ = [
    "__version__",
    "EngineConfig",
    "Engine",
    "Runtime",
    "register_component",
    "register_system",
    "register_command",
    "lambda_handler",
]

# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #

_logger = logging.getLogger("ledgerquest")
if not _logger.handlers:  # Prevent double-handlers in AWS Lambda env.
    _handler = logging.StreamHandler(sys.stdout)
    _formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    _handler.setFormatter(_formatter)
    _logger.addHandler(_handler)

# Default to INFO unless overridden by env var
_logger.setLevel(os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO").upper())


# --------------------------------------------------------------------------- #
# Public data structures                                                      #
# --------------------------------------------------------------------------- #
class Runtime(str, Enum):
    """
    Supported execution environments for the engine.
    """

    LAMBDA = "lambda"
    LOCAL = "local"
    CONTAINER = "container"  # E.g. GPU worker inside Fargate


def _detect_runtime() -> Runtime:
    """
    Inspect environment variables / process attributes in order to guess where
    we are currently running.
    """
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return Runtime.LAMBDA
    if Path("/.dockerenv").exists() or os.getenv("CONTAINERIZED") == "true":
        return Runtime.CONTAINER
    return Runtime.LOCAL


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """
    Immutable engine configuration.  The config is typically produced
    from environment variables inside a Lambda function or read from a
    JSON/YAML manifest during local integration testing.
    """

    game_id: str = field(
        default_factory=lambda: os.getenv("LEDGERQUEST_GAME_ID", "default-game")
    )
    customer_id: str = field(
        default_factory=lambda: os.getenv("LEDGERQUEST_CUSTOMER_ID", "anonymous")
    )
    stage: str = field(
        default_factory=lambda: os.getenv("LEDGERQUEST_STAGE", "dev")
    )
    runtime: Runtime = field(default_factory=_detect_runtime)
    # Additional, dynamic settings
    extras: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "EngineConfig":
        """
        Create config by reading prefixed environment variables.

        All variables starting with `LEDGERQUEST_CFG_` are mapped into the
        `extras` dictionary for custom, user-defined configuration.
        """
        extras: Dict[str, Any] = {}
        prefix = "LEDGERQUEST_CFG_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                extras[key[len(prefix) :].lower()] = value
        return cls(extras=extras)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "EngineConfig":
        """
        Build configuration from an arbitrary mapping (e.g. loaded from JSON).
        """
        base_fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        std_kwargs = {k: mapping[k] for k in mapping if k in base_fields}
        extras = {k: mapping[k] for k in mapping if k not in base_fields}
        return cls(**std_kwargs, extras=extras)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Registration decorators for the ECS / Command Pattern                       #
# --------------------------------------------------------------------------- #
_ComponentRegistry: MutableMapping[str, type] = {}
_SystemRegistry: MutableMapping[str, Callable[..., Any]] = {}
_CommandRegistry: MutableMapping[str, Callable[..., Any]] = {}


def register_component(name: Optional[str] = None) -> Callable[[type], type]:
    """
    Decorator to register an ECS component class globally so it can be looked
    up across stateless function invocations.

    Example
    -------
    @register_component()
    class Position:
        x: float
        y: float
    """

    def decorator(cls: type) -> type:
        component_name = name or cls.__name__
        _logger.debug("Registering component '%s' -> %s", component_name, cls)
        if component_name in _ComponentRegistry:
            _logger.warning(
                "Component '%s' already registered. Overwriting.", component_name
            )
        _ComponentRegistry[component_name] = cls
        return cls

    return decorator


def register_system(name: Optional[str] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to register a system function that will be executed by the engine’s
    scheduler (local testing only – the production engine relies on Step Functions).
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        system_name = name or func.__name__
        _logger.debug("Registering system '%s' -> %s", system_name, func)
        if system_name in _SystemRegistry:
            _logger.warning("System '%s' already registered. Overwriting.", system_name)
        _SystemRegistry[system_name] = func
        return func

    return decorator


def register_command(name: Optional[str] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to register a stateless command (e.g. “move-unit”, “grant-xp”)
    that can be invoked through API-Gateway or Step-Functions Task states.

    The function must accept `payload: dict` and return `dict` with the result.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        command_name = name or func.__name__
        _logger.debug("Registering command '%s' -> %s", command_name, func)
        if command_name in _CommandRegistry:
            _logger.warning(
                "Command '%s' already registered. Overwriting.", command_name
            )
        _CommandRegistry[command_name] = func
        return func

    return decorator


def _load_plugins() -> None:
    """
    Discover and import optional LedgerQuest plug-ins.  Plug-ins advertise
    themselves by defining an entry-point of group ``ledgerquest.plugins``.
    """
    try:
        eps = importlib_metadata.entry_points(group="ledgerquest.plugins")
    except Exception:  # pragma: no cover
        _logger.debug("Cannot access entry_points() – possibly old importlib.")
        eps = []
    for ep in eps:
        try:
            _logger.info("Loading LedgerQuest plug-in: %s", ep.name)
            ep.load()  # Actual import happens here
        except Exception as exc:  # pragma: no cover
            _logger.exception("Failed to load plug-in %s: %s", ep.name, exc)


# --------------------------------------------------------------------------- #
# Engine façade                                                               #
# --------------------------------------------------------------------------- #
class Engine:
    """
    High-level façade that orchestrates component / system registration,
    command dispatching, plug-in loading and, in local mode, a *very trimmed*
    ECS game-loop for testability.

    The class is *not* used in Lambda production paths where handlers are
    directly invoked – but its stateless helpers (e.g. `dispatch_command`)
    remain valuable for controlling side-effects.
    """

    def __init__(self, config: Optional[EngineConfig] = None) -> None:
        self.config: EngineConfig = config or EngineConfig.from_env()
        self.runtime: Runtime = self.config.runtime
        self.session_id: str = uuid.uuid4().hex
        _logger.info(
            "Initialised LedgerQuest Engine v%s | runtime=%s | game=%s | customer=%s",
            __version__,
            self.runtime.value,
            self.config.game_id,
            self.config.customer_id,
        )
        _load_plugins()

        # Local cache; not persisted between Lambda cold starts
        self._world_state: Dict[str, Any] = {}

    # --------------------------------------------------------------------- #
    # Local testing utilities                                               #
    # --------------------------------------------------------------------- #
    def start(self) -> None:
        if self.runtime != Runtime.LOCAL:
            _logger.warning("Engine.start() called in non-local runtime – no-op.")
            return

        _logger.info("Starting local game loop with %d system(s)...", len(_SystemRegistry))
        for system_name, system_fn in _SystemRegistry.items():
            _logger.debug("Executing system: %s", system_name)
            try:
                system_fn(self._world_state, self.config)
            except Exception as exc:
                _logger.exception("System '%s' failed: %s", system_name, exc)
        _logger.info("Local game loop completed.")

    def stop(self) -> None:
        _logger.info("Engine stopped (session=%s).", self.session_id)

    # --------------------------------------------------------------------- #
    # Command dispatching                                                   #
    # --------------------------------------------------------------------- #
    def dispatch_command(self, command_name: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """
        Invoke a registered command in a stateless fashion, catching and logging
        exceptions so callers always receive a structured response.
        """
        payload = dict(payload or {})
        _logger.debug("Dispatching command '%s' with payload: %s", command_name, payload)

        handler = _CommandRegistry.get(command_name)
        if handler is None:
            error_msg = f"Unknown command: {command_name}"
            _logger.error(error_msg)
            return {"ok": False, "error": error_msg}

        try:
            result = handler(payload, self.config)  # type: ignore[arg-type]
            _logger.debug(
                "Command '%s' executed successfully – result: %s", command_name, result
            )
            return {"ok": True, "result": result}
        except Exception as exc:
            _logger.exception("Command '%s' failed: %s", command_name, exc)
            return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------- #
# AWS Lambda entry-point                                                      #
# --------------------------------------------------------------------------- #
_engine_singleton: Optional[Engine] = None


def lambda_handler(event: Dict[str, Any], context: types.SimpleNamespace) -> Dict[str, Any]:  # type: ignore[valid-type]
    """
    Serverless handler compatible with:
        * API-Gateway (REST / HTTP API)
        * API-Gateway WebSocket
        * Step-Functions Task states

    The input event MUST contain at a minimum:

    {
        "command": "move-unit",
        "payload": {...}
    }

    The handler keeps an in-memory singleton of `Engine` so that warmed Lambdas
    don’t pay the cold-start cost for plug-in discovery more than once.
    """
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = Engine()

    _logger.debug("Lambda event received: %s", json.dumps(event))

    command: str = event.get("command", "")
    payload: Mapping[str, Any] = event.get("payload", {})

    if not command:
        _logger.error("Request missing 'command' field.")
        return {"ok": False, "error": "Missing 'command' in request."}

    return _engine_singleton.dispatch_command(command, payload)
```