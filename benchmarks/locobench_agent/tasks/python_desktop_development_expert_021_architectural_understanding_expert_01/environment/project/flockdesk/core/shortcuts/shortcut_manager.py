```python
"""
FlockDesk – Social Workspace Orchestrator
Shortcut Manager Core Module

This module centralises the registration, (re-)mapping, persistence and
activation of keyboard shortcuts across the entire desktop suite.  It supports
dynamic plugins, multi-window contexts, real-time conflict detection and emits
events over the internal event bus so that interested micro-front-ends can keep
their UI in sync.

The manager purposely avoids any direct dependency on concrete Qt widgets to
keep the core headless and unit-test friendly.  UI layers interact with the
manager through thin adapter helpers that translate high-level “command”
objects into QShortcut instances in their own window hierarchy.

Author  : FlockDesk Core Team
License : MIT
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Set

# --------------------------------------------------------------------------- #
# Optional Qt dependency                                                      #
# --------------------------------------------------------------------------- #
try:
    from PySide6.QtGui import QKeySequence  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – unit tests may run headless
    class QKeySequence:  # minimal stub
        """Fallback stub so the core can run without Qt available."""

        def __init__(self, seq: str | "QKeySequence") -> None:
            self._seq = str(seq)

        def toString(self) -> str:  # noqa: N802 – Qt style
            return self._seq

        def __str__(self) -> str:
            return self._seq

        # Qt API surface that we rely on
        def __eq__(self, other: object) -> bool:  # noqa: D401
            if isinstance(other, QKeySequence):
                return self._seq == other._seq
            return NotImplemented

        def __hash__(self) -> int:
            return hash(self._seq)


# --------------------------------------------------------------------------- #
# Internal event bus (fallback)                                               #
# --------------------------------------------------------------------------- #
try:
    from flockdesk.core.eventbus import EventBus  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    class EventBus:  # minimal safe fallback
        def __init__(self) -> None:
            self._subs: Dict[str, Set[Callable[..., None]]] = {}

        def emit(self, event: str, **payload) -> None:
            for cb in self._subs.get(event, set()):
                try:
                    cb(**payload)
                except Exception:  # pragma: no cover
                    logging.exception("Unhandled error in event bus subscriber")

        def subscribe(self, event: str, callback: Callable[..., None]) -> None:
            self._subs.setdefault(event, set()).add(callback)

        def unsubscribe(self, event: str, callback: Callable[..., None]) -> None:
            self._subs.get(event, set()).discard(callback)


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #
class ShortcutError(RuntimeError):
    """Base class for shortcut related problems."""


class ShortcutConflictError(ShortcutError):
    """Raised when attempting to assign a key sequence that is already in use."""


class UnknownCommandError(ShortcutError):
    """Raised when a command identifier is not known to the manager."""


# --------------------------------------------------------------------------- #
# Dataclasses                                                                 #
# --------------------------------------------------------------------------- #
@dataclass(slots=True, frozen=True)
class CommandMetadata:
    """Human-readable command description required for UI layers."""

    description: str
    category: str  # e.g. “chat”, “editor”, “navigation”


@dataclass(slots=True)
class CommandShortcut:
    """Container that holds the default & active key sequence for a command."""

    command_id: str
    default: QKeySequence
    meta: CommandMetadata
    active: QKeySequence | None = field(default=None)

    # -------- computed helpers --------------------------------------------- #
    def effective(self) -> QKeySequence:
        """Return active if set, otherwise the default value."""
        return self.active or self.default


# --------------------------------------------------------------------------- #
# Shortcut Manager                                                            #
# --------------------------------------------------------------------------- #
class ShortcutManager:
    """
    Thread-safe singleton responsible for managing keyboard shortcuts.

    Usage
    -----
    >>> mgr = ShortcutManager.instance()
    >>> mgr.register_command(
    ...     command_id="chat.send_message",
    ...     default="Ctrl+Return",
    ...     description="Send current chat message",
    ...     category="chat",
    ... )
    >>> mgr.assign_shortcut("chat.send_message", "Ctrl+Enter")
    """

    _instance: Optional["ShortcutManager"] = None
    _instance_lock = threading.Lock()

    # ------------------------------ singleton ------------------------------ #
    @classmethod
    def instance(cls) -> "ShortcutManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------- construction / state ------------------------ #
    def __init__(self) -> None:
        if ShortcutManager._instance is not None:  # pragma: no cover
            raise RuntimeError("ShortcutManager is a singleton. "
                               "Use ShortcutManager.instance()")

        self._commands: Dict[str, CommandShortcut] = {}
        self._lock = threading.RLock()
        self._bus = EventBus()
        self._settings_path = (
            Path.home()
            / ".config"
            / "flockdesk"
            / "shortcuts.json"
        )
        self._log = logging.getLogger("flockdesk.shortcuts")
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    # --------------------------- command API ------------------------------- #
    def register_command(
        self,
        command_id: str,
        default: str | QKeySequence,
        description: str,
        category: str,
        override_existing: bool = False,
    ) -> None:
        """
        Register a new command & its default shortcut.

        Plugins should call this during their ``on_load`` hook.  If the command
        already exists and *override_existing* is False, a warning is logged and
        the call is ignored.
        """
        with self._lock:
            if command_id in self._commands and not override_existing:
                self._log.warning("Command '%s' already registered – ignored.",
                                  command_id)
                return

            cs = CommandShortcut(
                command_id=command_id,
                default=self._coerce_sequence(default),
                meta=CommandMetadata(description=description, category=category),
            )
            self._commands[command_id] = cs
            self._bus.emit("shortcut.command-registered", command=cs)
            self._log.debug("Registered command '%s' with default '%s'",
                            command_id, cs.default)

    def unregister_command(self, command_id: str) -> None:
        """Remove a command from the manager (usually when a plugin unloads)."""
        with self._lock:
            if self._commands.pop(command_id, None) is not None:
                self._bus.emit("shortcut.command-unregistered",
                               command_id=command_id)
                self._log.debug("Unregistered command '%s'", command_id)

    def assign_shortcut(
        self,
        command_id: str,
        new_sequence: str | QKeySequence,
        force: bool = False,
    ) -> None:
        """
        Assign *new_sequence* to *command_id*.

        When *force* is False (default), a ``ShortcutConflictError`` is raised
        if the key sequence is already taken by another command.
        """
        seq = self._coerce_sequence(new_sequence)
        with self._lock:
            cmd = self._require_command(command_id)

            # conflict detection
            conflicting_cmd_id = self._find_command_by_sequence(seq)
            if conflicting_cmd_id and conflicting_cmd_id != command_id:
                if not force:
                    raise ShortcutConflictError(
                        f"'{seq}' already assigned "
                        f"to '{conflicting_cmd_id}'."
                    )
                # override conflicting command
                self._commands[conflicting_cmd_id].active = None
                self._log.info("Removed shortcut from command '%s' "
                               "due to force override.", conflicting_cmd_id)

            cmd.active = seq
            self._bus.emit("shortcut.updated", command=cmd)
            self._log.info("Assigned '%s' to command '%s'", seq, command_id)
            self._persist_to_disk()

    def clear_shortcut(self, command_id: str) -> None:
        """Remove any user override and fall back to default."""
        with self._lock:
            cmd = self._require_command(command_id)
            cmd.active = None
            self._bus.emit("shortcut.updated", command=cmd)
            self._log.debug("Cleared custom shortcut for '%s'", command_id)
            self._persist_to_disk()

    def restore_defaults(self) -> None:
        """Reset all commands to their default key sequence."""
        with self._lock:
            for cmd in self._commands.values():
                cmd.active = None
            self._bus.emit("shortcut.defaults-restored")
            self._persist_to_disk()
            self._log.info("Restored default shortcuts for all commands")

    # ------------------------------ query API ------------------------------ #
    def get_shortcut(self, command_id: str) -> QKeySequence:
        """Return the effective key sequence for *command_id*."""
        with self._lock:
            cmd = self._require_command(command_id)
            return cmd.effective()

    def all_commands(self) -> Iterable[CommandShortcut]:
        """Return a snapshot list of all command descriptors."""
        with self._lock:
            return list(self._commands.values())

    def commands_by_category(self) -> Dict[str, Iterable[CommandShortcut]]:
        """
        Convenience wrapper that returns commands grouped by their *category*
        (e.g. for preferences UI).
        """
        grouped: Dict[str, list[CommandShortcut]] = {}
        with self._lock:
            for cmd in self._commands.values():
                grouped.setdefault(cmd.meta.category, []).append(cmd)
        return grouped

    # ------------------------- persistence helpers ------------------------- #
    def _coerce_sequence(self, seq: str | QKeySequence) -> QKeySequence:
        """Ensure *seq* is a QKeySequence instance."""
        return seq if isinstance(seq, QKeySequence) else QKeySequence(seq)

    def _find_command_by_sequence(
        self, seq: QKeySequence
    ) -> Optional[str]:
        """Return command_id that owns *seq* or None."""
        for cmd_id, cmd in self._commands.items():
            if cmd.effective() == seq:
                return cmd_id
        return None

    def _require_command(self, command_id: str) -> CommandShortcut:
        if command_id not in self._commands:
            raise UnknownCommandError(command_id)
        return self._commands[command_id]

    # ------------------------------ settings ------------------------------- #
    def _load_from_disk(self) -> None:
        """Load user mapped shortcuts (if any) from disk."""
        if not self._settings_path.exists():
            return

        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover
            self._log.error("Failed to parse shortcut settings – %s", exc)
            return

        with self._lock:
            for command_id, seq_str in data.items():
                if command_id in self._commands:
                    self._commands[command_id].active = QKeySequence(seq_str)
            self._log.debug("Loaded %d custom shortcuts from disk", len(data))

    def _persist_to_disk(self) -> None:
        """Persist user overrides to the settings file atomically."""
        to_dump: Dict[str, str] = {}
        with self._lock:
            for cmd in self._commands.values():
                if cmd.active is not None:
                    to_dump[cmd.command_id] = cmd.active.toString()

        tmp = self._settings_path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(to_dump, indent=2), encoding="utf-8")
            tmp.replace(self._settings_path)
            self._log.debug("Persisted %d custom shortcuts to disk",
                            len(to_dump))
        except OSError:  # pragma: no cover
            self._log.exception("Unable to write shortcut settings to %s",
                                self._settings_path)

    # ----------------------------- event bus ------------------------------- #
    def bus(self) -> EventBus:
        """Expose the internal event bus to subscribers."""
        return self._bus


# --------------------------------------------------------------------------- #
# Convenience function for external imports                                   #
# --------------------------------------------------------------------------- #
def shortcuts() -> ShortcutManager:
    """Shorthand access wrapper (`from flockdesk.shortcuts import shortcuts`)."""
    return ShortcutManager.instance()
```