```python
"""
FlockDesk – Poll Plugin
=======================

A hot-swappable plugin that allows participants inside a live
FlockDesk session to create, share and vote on multiple-choice polls.

The plugin adheres to FlockDesk’s event-driven, MVVM-centric plugin
contract:

    ┌─────────────┐      bus.publish("poll/vote", {...})
    │  PollWidget │  ─────────────────────────────────────▶  Event-Bus
    └─────────────┘
          ▲                                         │
          │  Qt signals / slots                     │
          │                                         ▼
    ┌──────────────┐   model.change_state(...)   ┌─────────────┐
    │ PollViewModel│  ──────────────────────────▶│  PollModel  │
    └──────────────┘                             └─────────────┘

Only *this* file is required for the assignment, but it purposefully
illustrates how a real-world plugin would be structured.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Optional imports – gracefully degrade if host environment is missing Qt
# ──────────────────────────────────────────────────────────────────────────────
try:
    from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer
    from PySide6.QtWidgets import (
        QWidget,
        QVBoxLayout,
        QLabel,
        QButtonGroup,
        QRadioButton,
        QPushButton,
        QMessageBox,
    )
except ModuleNotFoundError:  # pragma: no cover – type check / headless CI
    # Provide stub classes so *importing* does not fail during headless tests.
    class _Stub:  # pylint: disable=too-few-public-methods
        def __init__(self, *_, **__):
            pass

    QObject = _Stub  # type: ignore
    Signal = lambda *_, **__: None  # type: ignore
    Slot = lambda *_, **__: None  # type: ignore
    Qt = _Stub  # type: ignore
    QTimer = _Stub  # type: ignore
    QWidget = _Stub  # type: ignore
    QVBoxLayout = _Stub  # type: ignore
    QLabel = _Stub  # type: ignore
    QButtonGroup = _Stub  # type: ignore
    QRadioButton = _Stub  # type: ignore
    QPushButton = _Stub  # type: ignore
    QMessageBox = _Stub  # type: ignore

# ──────────────────────────────────────────────────────────────────────────────
# FlockDesk public APIs – provide safe fallbacks during unit tests
# ──────────────────────────────────────────────────────────────────────────────
try:
    from flockdesk.core.plugin import BasePlugin
    from flockdesk.core.event_bus import EventBus
    from flockdesk.core.settings import Settings
except ModuleNotFoundError:  # pragma: no cover
    class BasePlugin:  # pylint: disable=too-few-public-methods
        """Very small shim standing in for the real BasePlugin."""

        def __init__(self, name: str):
            self.name = name

        def start(self) -> None:  # noqa: D401
            """Start plugin (stub)."""

        def stop(self) -> None:  # noqa: D401
            """Stop plugin (stub)."""

    class EventBus:  # pylint: disable=too-few-public-methods
        """Naïve, thread-safe event bus used for local development."""

        _subscribers: Dict[str, List] = {}
        _lock = threading.Lock()

        @classmethod
        def subscribe(cls, topic: str, handler):
            with cls._lock:
                cls._subscribers.setdefault(topic, []).append(handler)

        @classmethod
        def publish(cls, topic: str, payload):
            with cls._lock:
                for handler in cls._subscribers.get(topic, []):
                    handler(topic, payload)

    class Settings(dict):  # type: ignore
        """Stub replacement for flockdesk.core.settings.Settings."""


# ──────────────────────────────────────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("flockdesk.poll_plugin")
if not logger.handlers:
    # Avoid duplicate handlers when reloading in development
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(levelname)5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────────────────────────────────────
# Domain Model
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PollOption:
    """Single option inside a poll."""

    id: str
    text: str
    votes: int = 0


@dataclass
class Poll:
    """A poll object with multiple choices."""

    id: str
    question: str
    options: List[PollOption]
    creator: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    closed: bool = False
    voted_users: List[str] = field(default_factory=list)

    # High-level business logic methods
    # --------------------------------------------------------------------- #
    def vote(self, user_id: str, option_id: str) -> None:
        if self.closed:
            raise RuntimeError("Poll is closed.")
        if user_id in self.voted_users:
            raise RuntimeError("User has already voted.")
        for option in self.options:
            if option.id == option_id:
                option.votes += 1
                self.voted_users.append(user_id)
                logger.debug("Vote registered: %s -> %s", user_id, option_id)
                return
        raise ValueError("Option not found.")

    def close(self) -> None:
        self.closed = True
        logger.debug("Poll '%s' closed.", self.id)


# ──────────────────────────────────────────────────────────────────────────────
# Storage / Model
# ──────────────────────────────────────────────────────────────────────────────


class PollModel:
    """
    Thread-safe in-memory storage for active polls.
    In a real implementation this could be a DB or synced state.
    """

    _lock = threading.RLock()

    def __init__(self, settings: Settings):
        self._polls: Dict[str, Poll] = {}
        self._settings = settings

    # Poll CRUD
    # ------------------------------------------------------------------ #
    def create_poll(
        self, question: str, options: List[str], creator: str
    ) -> Poll:
        poll_id = str(uuid.uuid4())
        poll = Poll(
            id=poll_id,
            question=question,
            options=[PollOption(id=str(uuid.uuid4()), text=opt) for opt in options],
            creator=creator,
        )
        with self._lock:
            self._polls[poll_id] = poll
        logger.info("Poll created: %s", poll_id)
        return poll

    def get_poll(self, poll_id: str) -> Optional[Poll]:
        with self._lock:
            return self._polls.get(poll_id)

    def close_poll(self, poll_id: str) -> None:
        poll = self.get_poll(poll_id)
        if poll:
            poll.close()

    def iterate(self):
        """Return a snapshot list of polls (copy)."""
        with self._lock:
            return list(self._polls.values())


# ──────────────────────────────────────────────────────────────────────────────
# ViewModel (MVVM)
# ──────────────────────────────────────────────────────────────────────────────


class PollViewModel(QObject):
    """
    ViewModel connecting PollModel <--> Qt view with signals/slots.

    All model mutations are forwarded onto the event bus so other
    micro-front-ends are kept in sync.
    """

    poll_created = Signal(dict)  # emitted when a new poll is created
    vote_registered = Signal(dict)
    poll_closed = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, model: PollModel, event_bus: EventBus, user_id: str):
        super().__init__()
        self._model = model
        self._bus = event_bus
        self._user_id = user_id

        # Subscribe to external bus events
        self._bus.subscribe("poll/create", self._on_external_poll_create)
        self._bus.subscribe("poll/vote", self._on_external_vote)
        self._bus.subscribe("poll/close", self._on_external_close)

    # Public API – called by the Qt view
    # ------------------------------------------------------------------ #
    def create_poll(self, question: str, options: List[str]) -> None:
        try:
            poll = self._model.create_poll(question, options, self._user_id)
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to create poll.")
            self.error_occurred.emit(str(exc))
            return

        # Propagate to rest of workspace
        payload = self._serialize_poll(poll)
        self._bus.publish("poll/create", payload)
        self.poll_created.emit(payload)

    def vote(self, poll_id: str, option_id: str) -> None:
        try:
            poll = self._model.get_poll(poll_id)
            if not poll:
                raise RuntimeError("Poll not found.")
            poll.vote(self._user_id, option_id)
        except Exception as exc:
            logger.warning("Vote rejected: %s", exc)
            self.error_occurred.emit(str(exc))
            return

        payload = {
            "poll_id": poll_id,
            "option_id": option_id,
            "user_id": self._user_id,
        }
        self._bus.publish("poll/vote", payload)
        self.vote_registered.emit(payload)

    def close_poll(self, poll_id: str) -> None:
        self._model.close_poll(poll_id)
        payload = {"poll_id": poll_id, "closed_by": self._user_id}
        self._bus.publish("poll/close", payload)
        self.poll_closed.emit(payload)

    # Private helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _serialize_poll(poll: Poll) -> dict:
        return {
            "id": poll.id,
            "question": poll.question,
            "options": [
                {"id": opt.id, "text": opt.text, "votes": opt.votes}
                for opt in poll.options
            ],
            "creator": poll.creator,
            "created_at": poll.created_at.isoformat(),
            "closed": poll.closed,
            "voted_users": poll.voted_users,
        }

    # Event-bus inbound handlers
    # ------------------------------------------------------------------ #
    def _on_external_poll_create(self, topic: str, payload: dict) -> None:
        if payload["creator"] == self._user_id:
            # Ignore echo of our own publication
            return
        logger.debug("Received external poll create payload: %s", payload)
        # Re-hydrate into local store
        poll = Poll(
            id=payload["id"],
            question=payload["question"],
            options=[
                PollOption(
                    id=opt["id"],
                    text=opt["text"],
                    votes=opt.get("votes", 0),
                )
                for opt in payload["options"]
            ],
            creator=payload["creator"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            closed=payload["closed"],
            voted_users=payload["voted_users"],
        )
        with self._model._lock:
            self._model._polls[payload["id"]] = poll
        self.poll_created.emit(payload)

    def _on_external_vote(self, topic: str, payload: dict) -> None:
        if payload["user_id"] == self._user_id:
            return  # ignore own vote echo
        poll = self._model.get_poll(payload["poll_id"])
        if not poll:
            logger.warning("Vote received for unknown poll '%s'.", payload["poll_id"])
            return
        try:
            poll.vote(payload["user_id"], payload["option_id"])
        except RuntimeError:
            # Already voted – this can happen when event ordering differs
            pass
        self.vote_registered.emit(payload)

    def _on_external_close(self, topic: str, payload: dict) -> None:
        self._model.close_poll(payload["poll_id"])
        self.poll_closed.emit(payload)


# ──────────────────────────────────────────────────────────────────────────────
# View (Qt)
# ──────────────────────────────────────────────────────────────────────────────


class PollWidget(QWidget):
    """
    Basic UI showcasing integration. In real FlockDesk, a designer-authored
    .ui file would be loaded and bound by an MVVM framework.
    """

    def __init__(self, vm: PollViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm

        # Layout
        self._root = QVBoxLayout(self)
        self._question_label = QLabel("", self)
        self._root.addWidget(self._question_label)

        self._options_group = QButtonGroup(self)
        self._vote_buttons: Dict[str, QRadioButton] = {}

        self._vote_action = QPushButton("Vote", self)
        self._vote_action.clicked.connect(self._on_vote_clicked)
        self._root.addWidget(self._vote_action)

        self._close_action = QPushButton("Close Poll (creator)", self)
        self._close_action.clicked.connect(self._on_close_clicked)
        self._root.addWidget(self._close_action)

        # Connect ViewModel signals
        self._vm.poll_created.connect(self._display_poll)
        self._vm.vote_registered.connect(self._update_votes)
        self._vm.poll_closed.connect(self._handle_close)
        self._vm.error_occurred.connect(self._show_error)

        # Debounce UI updates
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(300)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render)

        self._active_poll: Optional[Poll] = None

    # ViewModel signal handlers
    # ------------------------------------------------------------------ #
    @Slot(dict)
    def _display_poll(self, data: dict):
        logger.debug("Displaying poll in widget: %s", data)
        with self._vm._model._lock:
            self._active_poll = self._vm._model._polls[data["id"]]
        self._render_timer.start()

    @Slot(dict)
    def _update_votes(self, _):
        self._render_timer.start()

    @Slot(dict)
    def _handle_close(self, _):
        self._render_timer.start()

    @Slot(str)
    def _show_error(self, message: str):
        QMessageBox.warning(self, "Poll Error", message)

    # UI event handlers
    # ------------------------------------------------------------------ #
    def _on_vote_clicked(self):
        if not self._active_poll or self._active_poll.closed:
            return
        selected_id = next(
            (oid for oid, btn in self._vote_buttons.items() if btn.isChecked()), None
        )
        if selected_id:
            self._vm.vote(self._active_poll.id, selected_id)

    def _on_close_clicked(self):
        if self._active_poll:
            self._vm.close_poll(self._active_poll.id)

    # Internal render
    # ------------------------------------------------------------------ #
    def _render(self):
        if not self._active_poll:
            return
        poll = self._active_poll
        self._question_label.setText(poll.question)

        # Wipe existing option widgets
        for btn in self._vote_buttons.values():
            self._options_group.removeButton(btn)
            self._root.removeWidget(btn)
            btn.deleteLater()
        self._vote_buttons.clear()

        for opt in poll.options:
            label = f"{opt.text} ({opt.votes})"
            btn = QRadioButton(label, self)
            self._options_group.addButton(btn)
            self._root.insertWidget(self._root.indexOf(self._vote_action), btn)
            self._vote_buttons[opt.id] = btn

        self._vote_action.setEnabled(not poll.closed)
        self._close_action.setEnabled(
            not poll.closed and poll.creator == self._vm._user_id
        )
        self.update()


# ──────────────────────────────────────────────────────────────────────────────
# Plugin implementation
# ──────────────────────────────────────────────────────────────────────────────


class PollPlugin(BasePlugin):
    """
    Entrypoint consumed by FlockDesk’s plugin loader.
    """

    PLUGIN_NAME = "poll_plugin"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, event_bus: EventBus, settings: Settings, user_id: str):
        super().__init__(self.PLUGIN_NAME)
        self._bus = event_bus
        self._settings = settings
        self._user_id = user_id

        self._model = PollModel(settings)
        self._vm = PollViewModel(self._model, self._bus, user_id)

        # The widget can be queried by the host to embed into its docking area
        self._widget = PollWidget(self._vm)
        logger.info("PollPlugin initialised.")

    # BasePlugin overrides
    # ------------------------------------------------------------------ #
    def start(self):
        logger.info("PollPlugin started, ready for polls.")

    def stop(self):
        logger.info("PollPlugin stopped.")

    # Public API consumed by host
    # ------------------------------------------------------------------ #
    @property
    def widget(self) -> QWidget:
        """Return root QWidget for embedding in the UI."""
        return self._widget

    def serialize_state(self) -> str:
        """
        Serialize plugin state so it can be restored in another session.
        """
        snapshot = [PollViewModel._serialize_poll(p) for p in self._model.iterate()]
        return json.dumps(snapshot)

    def restore_state(self, raw: str):
        """
        Restore previously saved state. Called by workspace loader.
        """
        try:
            dataset = json.loads(raw)
        except json.JSONDecodeError:  # pragma: no cover
            logger.error("Failed to decode saved poll state: %s", raw)
            return

        for payload in dataset:
            self._vm._on_external_poll_create("poll/create", payload)


# ──────────────────────────────────────────────────────────────────────────────
# Plugin entrypoint required by FlockDesk
# ──────────────────────────────────────────────────────────────────────────────


def plugin_entry(event_bus: EventBus, settings: Settings, user_id: str) -> PollPlugin:
    """
    Mandatory factory that FlockDesk calls when loading a plugin.

    Parameters
    ----------
    event_bus
        Shared event bus supplied by FlockDesk core.
    settings
        User-/workspace-level settings dict.
    user_id
        Identifier of the current user.

    Returns
    -------
    PollPlugin
        A fully initialised plugin instance.
    """
    return PollPlugin(event_bus, settings, user_id)
```