```python
"""
flockdesk.modules.chat.service
------------------------------

High-level chat domain service used by the “Chat” micro-front-end.  It exposes an
asynchronous API for sending / receiving messages, integrates with the internal
event-bus, handles plugin dispatch, command parsing, and on-disk persistence of
message history.

The module is deliberately self-contained: if the real FlockDesk event-bus is
not importable (e.g. running unit-tests in isolation) a very small fallback
implementation is provided so the service still works end-to-end.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import TracebackType
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Type,
    TypeVar,
)

__all__ = ["ChatService", "BaseChatPlugin", "ChatMessageEvent", "ChatTypingEvent"]

_log = logging.getLogger(__name__)

###############################################################################
# Fallback Event-Bus (only used when the real implementation is unavailable)  #
###############################################################################

try:
    from flockdesk.core.eventbus import EventBus  # pylint: disable=import-error
except ModuleNotFoundError:  # pragma: no cover – unit-tests / IDE
    T_Event = TypeVar("T_Event")

    class EventBus:
        """
        Very small, asyncio-based in-process event-bus substitute.  It is *not*
        feature-complete – it only supports the subset required by ChatService.
        """

        def __init__(self) -> None:
            self._subscribers: Dict[type, List[Callable[[Any], Awaitable[None]]]] = {}

        def subscribe(
            self,
            event_type: Type[T_Event],
            callback: Callable[[T_Event], Awaitable[None]],
        ) -> None:
            self._subscribers.setdefault(event_type, []).append(callback)
            _log.debug("Subscribed %s to %s", callback, event_type)

        def unsubscribe(
            self,
            event_type: Type[T_Event],
            callback: Callable[[T_Event], Awaitable[None]],
        ) -> None:
            with suppress(ValueError, KeyError):
                self._subscribers[event_type].remove(callback)
            _log.debug("Unsubscribed %s from %s", callback, event_type)

        async def publish(self, event: Any) -> None:
            for evt_type, callbacks in self._subscribers.items():
                if isinstance(event, evt_type):
                    for cb in list(callbacks):
                        try:
                            await cb(event)
                        except Exception:  # noqa: BLE001 pragma: no cover
                            _log.exception(
                                "Error while delivering %s to %s", event, cb
                            )


###############################################################################
# Domain Events                                                               #
###############################################################################


@dataclass(slots=True)
class _BaseEvent:
    channel: str
    timestamp: _dt.datetime = field(
        default_factory=lambda: _dt.datetime.now(tz=_dt.timezone.utc)
    )


@dataclass(slots=True)
class ChatMessageEvent(_BaseEvent):
    user_id: str
    content: str


@dataclass(slots=True)
class ChatTypingEvent(_BaseEvent):
    user_id: str
    is_typing: bool = True


###############################################################################
# Plugin System                                                               #
###############################################################################


class BaseChatPlugin(Protocol):
    """
    Interface every chat plugin has to fulfil.

    Implementations are discovered / loaded elsewhere, the service only handles
    lifecycle callbacks.
    """

    name: str

    # --------------------------------------------------------------------- #
    # Lifecycle                                                             #
    # --------------------------------------------------------------------- #

    async def on_start(self, service: "ChatService") -> None:  # noqa: D401
        """Called once the hosting ChatService has started."""

    async def on_stop(self) -> None:
        """Called before the service shuts down."""

    # --------------------------------------------------------------------- #
    # Event hooks                                                           #
    # --------------------------------------------------------------------- #

    async def on_message(self, event: ChatMessageEvent) -> None:
        """Allows the plugin to read / transform / react to an incoming chat
        message *before* it is persisted or forwarded to the GUI."""
        # Example: implement `@giphy` support or language-filtering

    async def on_typing(self, event: ChatTypingEvent) -> None:
        """Hook executed whenever a Typing event reaches the service."""


###############################################################################
# Chat Service                                                                #
###############################################################################


class ChatService:
    """
    Orchestrates chat messaging, plugin dispatch, command execution, and
    persistence.  The class is intentionally lightweight and can be instantiated
    multiple times (e.g. for different workspaces) as long as a *separate*
    EventBus is provided for each instance.
    """

    # --------------------------------------------------------------------- #
    # Construction / Context-Manager                                        #
    # --------------------------------------------------------------------- #

    def __init__(
        self,
        *,
        user_id: str,
        storage_dir: Path,
        event_bus: EventBus | None = None,
        plugins: Iterable[BaseChatPlugin] | None = None,
    ) -> None:
        self.user_id = user_id
        self._storage_dir: Path = storage_dir.expanduser().absolute()
        self._bus: EventBus = event_bus or EventBus()
        self._plugins: Dict[str, BaseChatPlugin] = {
            p.name: p for p in (plugins or [])
        }
        self._history_cache: Dict[str, List[ChatMessageEvent]] = {}
        self._command_handlers: Dict[str, Callable[[Sequence[str]], Awaitable[str]]] = {}

        self._lock = asyncio.Lock()
        self._running = False

    async def __aenter__(self) -> "ChatService":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    async def start(self) -> None:
        """
        Bootstraps the service, loads history from disk, subscribes to events
        and calls plugin lifecycle hooks.
        """
        if self._running:
            return

        _log.info("Starting ChatService for user %s", self.user_id)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # Subscribe to bus events before we call plugin.on_start so plugins can
        # publish messages during startup if desired.
        self._bus.subscribe(ChatMessageEvent, self._handle_incoming_message)
        self._bus.subscribe(ChatTypingEvent, self._handle_typing)

        # Register builtin command
        self.register_command("/help", self._cmd_help)

        for plugin in self._plugins.values():
            with suppress(Exception):
                await plugin.on_start(self)

        self._running = True
        _log.info("ChatService started (%s plugins)", len(self._plugins))

    async def stop(self) -> None:
        """Gracefully tear down the service."""
        if not self._running:
            return

        _log.info("Stopping ChatService...")

        self._bus.unsubscribe(ChatMessageEvent, self._handle_incoming_message)
        self._bus.unsubscribe(ChatTypingEvent, self._handle_typing)

        for plugin in self._plugins.values():
            with suppress(Exception):
                await plugin.on_stop()

        self._history_cache.clear()
        self._running = False

    # ------------------------------------------------------------------ #

    async def send_message(self, channel: str, content: str) -> None:
        """
        Creates a ChatMessageEvent and publishes it to the bus so every
        interested party receives it – including *this* service (symmetry).
        """
        if not self._running:
            raise RuntimeError("ChatService is not running")

        event = ChatMessageEvent(
            channel=channel,
            user_id=self.user_id,
            content=content,
        )
        await self._bus.publish(event)

    async def set_typing(self, channel: str, is_typing: bool = True) -> None:
        """Emit a typing indicator for the local user."""
        event = ChatTypingEvent(channel=channel, user_id=self.user_id, is_typing=is_typing)
        await self._bus.publish(event)

    def register_command(
        self, command: str, handler: Callable[[Sequence[str]], Awaitable[str]]
    ) -> None:
        if not command.startswith("/"):
            raise ValueError("Commands have to start with '/'")
        self._command_handlers[command] = handler
        _log.debug("Registered command %s -> %s", command, handler)

    def register_plugin(self, plugin: BaseChatPlugin) -> None:
        if self._running:
            raise RuntimeError("Cannot register plugins after service.start()")
        if plugin.name in self._plugins:
            raise KeyError(f"Plugin with name '{plugin.name}' already registered")
        self._plugins[plugin.name] = plugin

    async def history(
        self, channel: str, limit: int | None = 50
    ) -> List[ChatMessageEvent]:
        """
        Retrieve chat history for given channel – will be loaded from disk the
        first time and cached afterwards.
        """
        if channel not in self._history_cache:
            await self._load_history(channel)

        messages = self._history_cache[channel]
        return messages[-limit:] if limit else list(messages)

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    async def _handle_incoming_message(self, event: ChatMessageEvent) -> None:
        _log.debug("ChatService received message: %s", event)

        # 1) Plugin pipeline
        for plugin in self._plugins.values():
            try:
                await plugin.on_message(event)
            except Exception:  # noqa: BLE001
                _log.exception("Plugin %s failed during on_message()", plugin.name)

        # 2) Command handling (only if originating from self, we don't want to
        #    parse others' messages).
        if event.user_id == self.user_id and event.content.startswith("/"):
            if await self._try_process_command(event):
                # Command was consumed – do *not* persist or forward to GUI.
                return

        # 3) Persistence
        await self._persist_message(event)

    async def _handle_typing(self, event: ChatTypingEvent) -> None:
        for plugin in self._plugins.values():
            try:
                await plugin.on_typing(event)
            except Exception:  # noqa: BLE001
                _log.exception("Plugin %s failed during on_typing()", plugin.name)

    # ------------------------------------------------------------------ #

    async def _try_process_command(self, event: ChatMessageEvent) -> bool:
        """Returns True if the message was handled as a command."""
        parts = event.content.strip().split()
        command, args = parts[0], parts[1:]

        if command not in self._command_handlers:
            return False

        handler = self._command_handlers[command]
        try:
            response = await handler(args)
            await self.send_message(event.channel, response)
        except Exception:  # noqa: BLE001
            _log.exception("Command %s failed", command)
            await self.send_message(event.channel, f"Error executing {command}")
        return True

    # ------------------------------------------------------------------ #
    # Command Implementations                                            #
    # ------------------------------------------------------------------ #

    async def _cmd_help(self, _args: Sequence[str]) -> str:  # noqa: D401
        return (
            "Available commands:\n"
            + "\n".join(
                f" {cmd.ljust(10)} – {func.__doc__ or 'undocumented'}"
                for cmd, func in self._command_handlers.items()
            )
        )

    # ------------------------------------------------------------------ #
    # Persistence                                                        #
    # ------------------------------------------------------------------ #

    async def _persist_message(self, event: ChatMessageEvent) -> None:
        path = self._storage_dir / f"{event.channel}.log.jsonl"

        async with self._lock:
            # Append to cache
            self._history_cache.setdefault(event.channel, []).append(event)

            # Append to file
            loop = asyncio.get_running_loop()
            line = json.dumps(asdict(event), default=str)

            await loop.run_in_executor(
                None,  # default executor
                _append_line,
                path,
                line,
            )

    async def _load_history(self, channel: str) -> None:
        path = self._storage_dir / f"{channel}.log.jsonl"
        if not path.exists():
            self._history_cache[channel] = []
            return

        loop = asyncio.get_running_loop()

        raw_lines: List[str] = await loop.run_in_executor(None, path.read_text)
        events: List[ChatMessageEvent] = []
        for line in raw_lines.splitlines():
            with suppress(json.JSONDecodeError, KeyError):
                payload = json.loads(line)
                events.append(
                    ChatMessageEvent(
                        channel=payload["channel"],
                        timestamp=_dt.datetime.fromisoformat(
                            payload["timestamp"]
                        ),
                        user_id=payload["user_id"],
                        content=payload["content"],
                    )
                )
        self._history_cache[channel] = events


###############################################################################
# Helpers                                                                     #
###############################################################################


def _append_line(path: Path, line: str) -> None:
    """
    Synchronous helper for writing to the history log.  Run inside the default
    executor so we do not block the asyncio loop.
    """
    with path.open("a", encoding="utf-8") as fp:
        fp.write(line + "\n")


###############################################################################
# Example entry-point for manual testing                                      #
###############################################################################

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    async def main() -> None:
        async with ChatService(
            user_id="alice",
            storage_dir=Path("~/.flockdesk/chat").expanduser(),
        ) as chat:
            await chat.send_message("general", "Hello, world!")
            await chat.set_typing("general", False)
            history = await chat.history("general")
            for msg in history:
                print(msg)

    asyncio.run(main())
```