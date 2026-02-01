```python
"""
ledgerquest.engine.core.command
================================

Infrastructure layer for LedgerQuest’s Command pattern.

The module provides:

1. Command – an immutable, serialisable value-object representing an
   intent to change game state.
2. CommandHandler – an abstract base for classes that *execute* a
   Command against the external ECS/DynamoDB/S3 back-end.
3. CommandRegistry – a lightweight service-locator that maps Command
   types to their respective handlers.  Registration happens
   automatically through decorators.
4. CommandBus – a thin façade that receives a Command instance,
   resolves the correct handler, and calls `handle()` with robust
   error-handling and audit logging.

These building blocks are intentionally framework-agnostic so they can
be used inside AWS Lambda functions, Step-Functions state machines, or
local unit tests with equal ease.
"""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Generic, Mapping, MutableMapping, Optional, Type, TypeVar, Union

__all__ = [
    "Command",
    "CommandHandler",
    "CommandRegistry",
    "CommandBus",
    "CommandError",
    "CommandValidationError",
    "CommandHandlerNotFound",
    "ECSGateway",
]

log = logging.getLogger("ledgerquest.engine.command")

# --------------------------------------------------------------------------- #
#                                Exceptions                                   #
# --------------------------------------------------------------------------- #


class CommandError(RuntimeError):
    """Base-class for all Command-related exceptions."""


class CommandValidationError(CommandError):
    """Raised when a Command fails semantic or structural validation."""


class CommandHandlerNotFound(CommandError):
    """Raised when the CommandBus cannot locate a handler for the given Command."""


# --------------------------------------------------------------------------- #
#                   Core Domain – Command & Handler                           #
# --------------------------------------------------------------------------- #

T_Command = TypeVar("T_Command", bound="Command")


@dataclass(frozen=True, kw_only=True)
class Command(ABC):
    """
    An immutable value-object that represents a request to mutate game
    state.  Concrete command classes should inherit from this base
    class and declare their own business fields:

        @command
        @dataclass(frozen=True, kw_only=True)
        class SpawnNPC(Command):
            npc_type: str
            position: Vec3
            tenant_id: str
            user_id: str
    """

    tenant_id: str
    user_id: str
    correlation_id: Optional[str] = None

    # Metadata automatically injected for traceability.
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=lambda: time.time())

    # ------------------------- Convenience helpers ------------------------ #

    def iso_timestamp(self) -> str:
        return (
            datetime.fromtimestamp(self.created_at, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), default=str, separators=(",", ":"))


class ECSGateway(ABC):
    """
    Very thin Repository/DAO abstraction for the ECS back-end
    (DynamoDB, S3, Redis, etc.).  A concrete implementation is
    provided elsewhere – here we only need the interface.
    """

    @abstractmethod
    def apply_component_patch(
        self,
        entity_id: str,
        component_name: str,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        user_id: str,
    ) -> None:
        """
        Apply a **partial** component update, recording audit metadata.
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_component(
        self,
        entity_id: str,
        component_name: str,
        *,
        tenant_id: str,
    ) -> Mapping[str, Any]:
        raise NotImplementedError


T_Handler = TypeVar("T_Handler", bound="CommandHandler")


class CommandHandler(Generic[T_Command], ABC):
    """
    Abstract super-class for all Command handlers.  Handlers must be
    stateless and thread-safe; any shared dependencies (ECS gateway,
    loggers, etc.) are injected at construction time.
    """

    # Derived classes should set this to the *Command* subclass handled.
    command_cls: Type[T_Command]

    def __init__(self, *, ecs_gateway: ECSGateway, logger: Optional[logging.Logger] = None) -> None:
        self._ecs_gateway = ecs_gateway
        self._logger = logger or logging.getLogger(self.__class__.__name__)
        # Defensive: ensure subclass configured command_cls.
        if not hasattr(self, "command_cls") or not inspect.isclass(self.command_cls):
            raise TypeError(
                f"{self.__class__.__name__} must set `command_cls` attribute "
                "pointing to the Command it handles."
            )

    # pylint: disable=unused-argument
    def validate(self, command: T_Command) -> None:
        """
        Optional validation hook.  Sub-classes should raise
        CommandValidationError for invalid payloads.
        """

    @abstractmethod
    def handle(self, command: T_Command) -> Any:  # noqa: D401
        """
        Execute the given Command.  Should return a serialisable result
        (dict, list, str, etc.) that can be included in Lambda/HTTP
        responses or Step-Functions state outputs.
        """


# --------------------------------------------------------------------------- #
#               Service-Locator – Register & Discover handlers                #
# --------------------------------------------------------------------------- #


class CommandRegistry:
    """
    A global registry mapping Command subclasses to their respective
    *handler* classes.  The registry is intentionally simple and
    depends on explicit code-based registration to avoid import-time
    magic that can misbehave in Lambda’s frozen environments.
    """

    _command_to_handler: MutableMapping[Type[Command], Type[CommandHandler]] = {}

    # ------------------------------ API ----------------------------------- #

    @classmethod
    def register(
        cls, *, command_cls: Type[Command], handler_cls: Type[CommandHandler]
    ) -> None:
        log.debug(
            "Registering Command handler – %s -> %s",
            command_cls.__qualname__,
            handler_cls.__qualname__,
        )
        if command_cls in cls._command_to_handler:
            existing = cls._command_to_handler[command_cls]
            raise RuntimeError(
                f"Duplicate handler for {command_cls}: "
                f"{existing.__qualname__} vs {handler_cls.__qualname__}"
            )
        cls._command_to_handler[command_cls] = handler_cls

    @classmethod
    def handler_for(cls, command_cls: Type[T_Command]) -> Optional[Type[CommandHandler[T_Command]]]:
        return cls._command_to_handler.get(command_cls)

    # --------------------------- Decorators ------------------------------- #

    @classmethod
    def command_handler(
        cls, command_cls: Type[T_Command]
    ):  # noqa: D401  # non-standard decorator signature
        """
        Decorator for registering a CommandHandler.

            @CommandRegistry.command_handler(MyCommand)
            class MyCommandHandler(CommandHandler[MyCommand]):
                ...
        """

        def _decorator(handler_cls: Type[CommandHandler[T_Command]]) -> Type[CommandHandler]:
            cls.register(command_cls=command_cls, handler_cls=handler_cls)
            return handler_cls

        return _decorator

    # --------------------------- Discovery -------------------------------- #

    @classmethod
    def auto_discover(cls, module_paths: Optional[list[str]] = None) -> None:
        """
        Optionally discover handlers by importing modules listed in
        `module_paths`.  This is useful for Lambda cold-starts where
        handlers live in separate files and have to be imported (and
        thus executed) before their decorators register.
        """
        if not module_paths:
            return
        for mod_path in module_paths:
            try:
                importlib.import_module(mod_path)
            except Exception:  # pylint: disable=broad-except
                log.exception("Could not auto-import module %s during discovery", mod_path)


# --------------------------------------------------------------------------- #
#                               Command Bus                                   #
# --------------------------------------------------------------------------- #


class CommandBus:
    """
    Thin orchestrator that locates the appropriate handler for an
    incoming Command instance (via CommandRegistry) and executes it.
    """

    def __init__(
        self,
        *,
        ecs_gateway: ECSGateway,
        discovery_modules: Optional[list[str]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._ecs_gateway = ecs_gateway
        self._logger = logger or log.getChild("bus")
        # Ensure registry contains all handlers.
        CommandRegistry.auto_discover(discovery_modules)

    # --------------------------------------------------------------------- #

    def dispatch(self, command: Command) -> Any:
        """
        Execute *command* synchronously.  The function will:

        1. Resolve a registered handler.
        2. Perform optional validation.
        3. Run `handler.handle()`.
        4. Record structured audit in the log.

        Any exception propagates unless it is a known *CommandError*,
        in which case a clean log statement is emitted first.
        """

        start_ts = time.time_ns()

        handler_cls = CommandRegistry.handler_for(type(command))
        if handler_cls is None:
            raise CommandHandlerNotFound(f"No handler registered for {type(command).__name__}")

        handler = handler_cls(ecs_gateway=self._ecs_gateway, logger=self._logger)

        try:
            if hasattr(handler, "validate"):
                handler.validate(command)  # type: ignore[arg-type]
            result = handler.handle(command)  # type: ignore[arg-type]
            duration_ms = (time.time_ns() - start_ts) / 1_000_000
            self._logger.info(
                "Command executed: cmd=%s tenant=%s user=%s handler=%s duration=%.2fms",
                type(command).__name__,
                command.tenant_id,
                command.user_id,
                handler_cls.__qualname__,
                duration_ms,
            )
            return result
        except CommandValidationError as exc:
            self._logger.warning(
                "Command validation failed: cmd=%s id=%s reason=%s",
                type(command).__name__,
                command.command_id,
                exc,
            )
            raise
        except Exception:
            # Serious errors – log as ERROR and propagate.
            self._logger.exception(
                "Command execution failed: cmd=%s id=%s", type(command).__name__, command.command_id
            )
            raise


# --------------------------------------------------------------------------- #
#                       Sugar – user-friendly decorator                       #
# --------------------------------------------------------------------------- #


def command_handler(
    command_cls: Type[T_Command],
) -> "Callable[[Type[CommandHandler[T_Command]]], Type[CommandHandler[T_Command]]]":
    """
    Shorthand decorator, so users can write:

        @command_handler(SpawnNPC)
        class SpawnNPCHandler(CommandHandler[SpawnNPC]):
            ...

    instead of using `CommandRegistry.command_handler`.
    """
    return CommandRegistry.command_handler(command_cls)


# --------------------------------------------------------------------------- #
#                     Example Concrete Command & Handler                      #
#               (kept here for documentation and unit testing)                #
# --------------------------------------------------------------------------- #

# To avoid circular dependencies in type-checking / import, we
# explicitly place demo code under a `__name__ == "__main__"` guard so
# it is ignored by production runtime but used by `pytest -m example`.

if __name__.endswith(".command.__main__"):
    # Only executed during `python -m ledgerquest.engine.core.command`.
    from typing import Mapping

    class InMemoryECS(ECSGateway):
        """Simple in-memory ECS for smoke-tests."""

        def __init__(self) -> None:
            self._store: Dict[str, Dict[str, Mapping[str, Any]]] = {}

        def apply_component_patch(
            self,
            entity_id: str,
            component_name: str,
            payload: Mapping[str, Any],
            *,
            tenant_id: str,
            user_id: str,
        ) -> None:
            entity = self._store.setdefault(entity_id, {})
            comp = dict(entity.get(component_name, {}))
            comp.update(payload)
            entity[component_name] = comp
            log.debug(
                "[TEST] %s/%s – Patched %s: %s", tenant_id, entity_id, component_name, payload
            )

        def fetch_component(
            self, entity_id: str, component_name: str, *, tenant_id: str
        ) -> Mapping[str, Any]:
            return self._store.get(entity_id, {}).get(component_name, {})

    # --------------------------------------------------------------------- #
    #                  Example domain-specific Command                       #
    # --------------------------------------------------------------------- #

    @dataclass(frozen=True, kw_only=True)
    class SetHealth(Command):
        entity_id: str
        new_hp: int

    @command_handler(SetHealth)
    class SetHealthHandler(CommandHandler[SetHealth]):
        command_cls = SetHealth

        def validate(self, command: SetHealth) -> None:  # noqa: D401
            if command.new_hp < 0:
                raise CommandValidationError("new_hp must be >= 0")

        def handle(self, command: SetHealth) -> Dict[str, Any]:  # noqa: D401
            self._ecs_gateway.apply_component_patch(
                command.entity_id,
                component_name="Health",
                payload={"hp": command.new_hp},
                tenant_id=command.tenant_id,
                user_id=command.user_id,
            )
            return {"status": "ok", "hp": command.new_hp}

    # --------------------------------------------------------------------- #
    #                         Quick manual smoke-test                       #
    # --------------------------------------------------------------------- #

    ecs = InMemoryECS()
    bus = CommandBus(ecs_gateway=ecs)

    result = bus.dispatch(
        SetHealth(
            entity_id="player-123",
            tenant_id="acme-corp",
            user_id="gm-1",
            new_hp=95,
        )
    )
    print("RESULT:", result)
```