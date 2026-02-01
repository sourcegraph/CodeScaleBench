```python
"""
flockdesk.core.shortcuts.commands
=================================

Central shortcut/command registry used by the entire FlockDesk desktop
suite.  The registry provides a unified way for core components *and*
external plugins to register keyboard-driven commands that can later be
re-mapped by the user via the settings UI.

The implementation is intentionally *headless* – it does not create
`QShortcut` objects itself.  Instead it focuses on keeping an in-memory
catalogue of available commands, persisting user overrides, and
dispatching “command-invoked” events onto the global event-bus.

The UI layer (or view-models in MVVM terminology) can materialise that
information to visually represent the bindings and to install actual
`QShortcut`s on top-level windows.

Key features
------------
• Thread-safe, re-entrant registration/deregistration  
• First-class plugin support – plugins simply call `register()`  
• Hot-reloading – key-binding changes are applied at runtime  
• Built-in persistence – delegates to the global Settings store  
• Event-driven – command executions are emitted on the event-bus

"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QShortcut, QWidget
from PySide6.QtCore import Qt, QObject, Signal

# ---------------------------------------------------------------------------
# Global logger for this module
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event-bus integration
# ---------------------------------------------------------------------------
try:
    # Real implementation, available in production.
    from flockdesk.core.event_bus import EventBus

    _bus: EventBus = EventBus.get_global_instance()
except Exception:  # pragma: no cover – used while running tests in isolation
    class _FallbackBus:  # pylint: disable=too-few-public-methods
        """A *very* small, synchronous fallback event-bus implementation."""

        def emit(self, topic: str, **payload):
            logger.debug("FallbackBus.emit(%s, %s)", topic, payload)

    _bus = _FallbackBus()  # type: ignore


# ---------------------------------------------------------------------------
# User settings (persistent key-binding overrides)
# ---------------------------------------------------------------------------
try:
    from flockdesk.core.settings import settings  # Production settings store
except Exception:  # pragma: no cover – fallback for unit tests
    class _EphemeralSettings(dict):  # type: ignore
        """An in-memory stub to satisfy unit-tests."""

        def get_nested(self, *path, default=None):
            ref = self
            for key in path:
                ref = ref.get(key, {})
            return ref or default

        def set_nested(self, *path, value):
            ref = self
            for key in path[:-1]:
                ref = ref.setdefault(key, {})
            ref[path[-1]] = value
            logger.debug("Settings updated at %s = %s", ".".join(path), value)

    settings = _EphemeralSettings()  # type: ignore


# ---------------------------------------------------------------------------
# Exceptions specific to this module
# ---------------------------------------------------------------------------
class ShortcutCommandError(RuntimeError):
    """Base exception for all shortcut command related errors."""


class DuplicateCommandError(ShortcutCommandError):
    """Raised when someone attempts to register a command twice."""


class UnknownCommandError(ShortcutCommandError):
    """Raised when a command cannot be found within the registry."""


# ---------------------------------------------------------------------------
# Data-class representing a single command entry
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ShortcutCommand:
    """
    Represents a single keyboard-triggerable command.

    Attributes
    ----------
    id:
        Unique, namespaced identifier (e.g. ``"chat.send_message"``).
    description:
        Human-readable description shown in shortcut config UIs.
    default_sequence:
        The factory default :class:`QKeySequence`.
    handler:
        Callable executed when the command is invoked.
    enabled:
        Optional callable returning ``True`` if the command is currently
        available (for example, “Paste” may be disabled if the clipboard
        is empty).
    owner:
        Optional string that indicates the plugin/component that owns this
        command.  Purely informational.
    """

    id: str
    description: str
    default_sequence: QKeySequence
    handler: Callable[[], None]
    enabled: Callable[[], bool] = lambda: True
    owner: Optional[str] = None

    # Runtime fields – do *not* include in constructor
    current_sequence: QKeySequence = field(init=False)

    def __post_init__(self):
        # Load override from persistent settings, if any
        seq_str: Optional[str] = settings.get_nested(
            "shortcuts", self.id, default=None
        )
        if seq_str:
            self.current_sequence = QKeySequence(seq_str)
            logger.debug(
                "Command %s – loaded user override: %s",
                self.id,
                self.current_sequence.toString(),
            )
        else:
            self.current_sequence = self.default_sequence

    # ---------------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------------
    def is_enabled(self) -> bool:
        try:
            return bool(self.enabled())
        except Exception:  # pylint: disable=broad-except
            logger.exception("Error while checking enabled() for %s", self.id)
            return False

    def trigger(self) -> None:
        """
        Execute the command if enabled.  Errors are caught and logged.
        """
        if not self.is_enabled():
            logger.debug("Command %s is disabled – skipping trigger()", self.id)
            return

        logger.debug("Triggering command %s", self.id)
        try:
            self.handler()
            _bus.emit("shortcut.triggered", command=self.id)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unhandled exception while executing %s", self.id)
            _bus.emit("shortcut.error", command=self.id, exc_info=True)


# ---------------------------------------------------------------------------
# Registry – the public surface of this module
# ---------------------------------------------------------------------------
class ShortcutCommandRegistry(QObject):
    """
    Thread-safe registry storing :class:`ShortcutCommand` instances.

    All write operations are protected by an RLock so that plugins may
    register/unregister commands in background threads while the UI
    thread is traversing the registry to build shortcut menus.
    """

    command_registered = Signal(str)     # Arguments: command-id
    command_unregistered = Signal(str)   # Arguments: command-id
    command_triggered = Signal(str)      # Arguments: command-id

    _instance: "ShortcutCommandRegistry" | None = None
    _lock: threading.RLock

    # ---------------------------------------------------------------------
    # Singleton boiler-plate
    # ---------------------------------------------------------------------
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_singleton()
        return cls._instance

    def _init_singleton(self):
        super().__init__()
        self._commands: Dict[str, ShortcutCommand] = {}
        self._lock = threading.RLock()
        _bus.emit("registry.created", name="shortcut")

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def register(
        self,
        *,
        id: str,
        description: str,
        sequence: str | QKeySequence,
        handler: Callable[[], None],
        enabled: Callable[[], bool] = lambda: True,
        owner: Optional[str] = None,
    ) -> ShortcutCommand:
        """
        Registers a new command or raises :class:`DuplicateCommandError`.

        Parameters
        ----------
        id:
            Must be unique across the entire application.
        sequence:
            Either a :class:`QKeySequence` or any string accepted by
            ``QKeySequence(sequence)`` (e.g. ``"Ctrl+Shift+P"``).
        """
        if isinstance(sequence, str):
            sequence = QKeySequence(sequence)

        with self._lock:
            if id in self._commands:
                raise DuplicateCommandError(f"Command already registered: {id}")

            cmd = ShortcutCommand(
                id=id,
                description=description,
                default_sequence=sequence,
                handler=handler,
                enabled=enabled,
                owner=owner,
            )
            self._commands[id] = cmd
            logger.info("Registered command %s (%s)", id, sequence.toString())

        self.command_registered.emit(id)
        _bus.emit("shortcut.registered", id=id)
        return cmd

    def unregister(self, id_: str) -> None:
        with self._lock:
            if id_ not in self._commands:
                raise UnknownCommandError(id_)
            del self._commands[id_]
            logger.info("Unregistered command %s", id_)

        self.command_unregistered.emit(id_)
        _bus.emit("shortcut.unregistered", id=id_)

    def get(self, id_: str) -> ShortcutCommand:
        with self._lock:
            if id_ not in self._commands:
                raise UnknownCommandError(id_)
            return self._commands[id_]

    # Iterable protocol – convenient when building menus
    def __iter__(self) -> Iterable[ShortcutCommand]:
        with self._lock:
            return iter(list(self._commands.values()))

    # ---------------------------------------------------------------------
    # Triggering helpers
    # ---------------------------------------------------------------------
    def trigger(self, id_: str) -> None:
        cmd = self.get(id_)
        logger.debug("Registry.trigger(%s)", id_)
        cmd.trigger()
        self.command_triggered.emit(id_)

    # ---------------------------------------------------------------------
    # Key-binding management
    # ---------------------------------------------------------------------
    def update_binding(self, id_: str, sequence: str | QKeySequence) -> None:
        """
        Updates the user-visible key-sequence *and* persists the change.

        The new binding is written to the global settings store at::

            shortcuts.<command-id> = "<KeySequence>"

        A “shortcut.rebound” event will be emitted.
        """
        if isinstance(sequence, str):
            sequence = QKeySequence(sequence)

        cmd = self.get(id_)
        old = cmd.current_sequence

        if old.matches(sequence) == QKeySequence.ExactMatch:
            return  # no-op

        cmd.current_sequence = sequence
        settings.set_nested("shortcuts", id_, value=sequence.toString())
        logger.info(
            "Key-binding for %s changed: %s -> %s",
            id_,
            old.toString(),
            sequence.toString(),
        )

        _bus.emit(
            "shortcut.rebound",
            id=id_,
            old=old.toString(),
            new=sequence.toString(),
        )

    # ---------------------------------------------------------------------
    # Convenience – create actual QShortcut objects
    # ---------------------------------------------------------------------
    def materialise_for_widget(
        self, widget: QWidget, context: Qt.ShortcutContext = Qt.WidgetWithChildrenShortcut
    ) -> List[QShortcut]:
        """
        Install :class:`QShortcut` objects for *all* registered commands on
        the given ``widget``.

        Returns the list of created `QShortcut`s so that the caller can
        keep them alive as long as necessary (Qt requires that).
        """

        shortcuts: List[QShortcut] = []

        def _make_callback(command_id: str) -> Callable[[], None]:
            return lambda: self.trigger(command_id)

        with self._lock:
            for cmd in self._commands.values():
                sc = QShortcut(cmd.current_sequence, widget, context=context)
                sc.activated.connect(_make_callback(cmd.id))  # type: ignore[arg-type]
                shortcuts.append(sc)

                logger.debug(
                    "Installed QShortcut for %s on %s (%s)",
                    cmd.id,
                    widget,
                    cmd.current_sequence.toString(),
                )

        return shortcuts


# ---------------------------------------------------------------------------
# Public, singleton accessor
# ---------------------------------------------------------------------------
registry: ShortcutCommandRegistry = ShortcutCommandRegistry()


# ---------------------------------------------------------------------------
# Self-registration of *core* commands – executed on import
# ---------------------------------------------------------------------------
def _register_core_commands():
    # Examples only – real implementations will reside in their modules.
    from PySide6.QtWidgets import QApplication

    def _quit():
        QApplication.quit()

    registry.register(
        id="core.quit",
        description="Quit FlockDesk",
        sequence="Ctrl+Q",
        handler=_quit,
        owner="flockdesk.core",
    )

    def _show_settings():
        _bus.emit("ui.settings.opened")

    registry.register(
        id="core.open_settings",
        description="Open Settings",
        sequence="Ctrl+,",
        handler=_show_settings,
        owner="flockdesk.core",
    )

    logger.debug("Core shortcut commands registered.")


_register_core_commands()
```