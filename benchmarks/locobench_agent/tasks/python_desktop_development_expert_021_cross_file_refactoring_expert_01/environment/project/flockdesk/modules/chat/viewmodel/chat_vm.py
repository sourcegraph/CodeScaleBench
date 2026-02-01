```python
"""
FlockDesk – Chat Module
View-Model (MVVM) for the Chat micro-front-end.

This module owns the presentation-ready state of a single chat channel.
It keeps the Qt View in sync with the domain layer through an internal
event-bus, handles optimistic UI updates, provides command objects for
the Controller, and persists transient UI data such as unsent drafts.

Author: FlockDesk Core Team
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6 import QtCore

# ---------------------------------------------------------------------------#
# External / Project-wide Dependencies
# ---------------------------------------------------------------------------#
try:
    from flockdesk.core.events import EventBus, Event  # type: ignore
    from flockdesk.core.settings import settings  # type: ignore
    from flockdesk.core.exceptions import ChatSendError  # type: ignore
except ModuleNotFoundError:  # Fallbacks for static type checkers / docs
    EventBus = Any  # pragma: no cover
    Event = Any  # pragma: no cover
    settings = {}  # pragma: no cover
    ChatSendError = Exception  # pragma: no cover


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------#
# Data Models
# ---------------------------------------------------------------------------#
@dataclass(slots=True, frozen=True)
class ChatMessage:
    """Immutably represents a message entity in the chat session."""

    msg_id: str
    channel_id: str
    sender_id: str
    sender_display: str
    content: str
    timestamp: datetime
    edited: bool = False
    is_outgoing: bool = False
    attachments: List[Path] = field(default_factory=list)

    def serialize(self) -> Dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "channel_id": self.channel_id,
            "sender_id": self.sender_id,
            "sender_display": self.sender_display,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "edited": self.edited,
            "is_outgoing": self.is_outgoing,
            "attachments": [str(p) for p in self.attachments],
        }


# ---------------------------------------------------------------------------#
# Chat View-Model
# ---------------------------------------------------------------------------#
class ChatViewModel(QtCore.QObject):
    """
    Acts as the View-Model for a single chat channel.

    Responsibilities
    ----------------
    • Keep a local in-memory list of ChatMessage objects
    • Subscribe to the domain event-bus for incoming/outgoing messages
    • Expose Qt signals so Views can bind via Qt’s signal/slot system
    • Persist unsent drafts & restore them on reboot
    """

    # -------- Qt Signals ----------------------------------------------------#
    messageAdded = QtCore.Signal(ChatMessage)  # new message appended
    messageReplaced = QtCore.Signal(ChatMessage)  # edited or updated
    typingStatusChanged = QtCore.Signal(str, bool)  # user_id, is_typing
    errorOccurred = QtCore.Signal(str)  # human-readable error string
    historyLoaded = QtCore.Signal(list)  # list[ChatMessage]

    # -----------------------------------------------------------------------#
    def __init__(self, channel_id: str, event_bus: EventBus, parent=None) -> None:
        super().__init__(parent)
        self._channel_id: str = channel_id
        self._event_bus: EventBus = event_bus
        self._messages: list[ChatMessage] = []

        # drafts/<user>/<channel>.json
        self._draft_path: Path = (
            Path(settings.get("user_data_dir", "~/.flockdesk")).expanduser()
            / "drafts"
            / f"{settings.get('user_id', 'anonymous')}"
            / f"{channel_id}.json"
        )

        self._typing_users: Dict[str, QtCore.QTimer] = {}
        self._lock = threading.RLock()

        self._register_event_subscriptions()
        self._restore_draft_async()

    # -----------------------------------------------------------------------#
    # API surface for Controllers
    # -----------------------------------------------------------------------#
    def history(self) -> list[ChatMessage]:
        """Return a copy of the current message history."""
        with self._lock:
            return list(self._messages)

    def send_message(self, content: str, attachments: Optional[List[Path]] = None) -> None:
        """
        Send a message to the current channel.

        The actual network interaction is delegated to the domain layer
        via the event-bus. We optimistically append the message locally
        and mark it as `is_outgoing=True`; once the server acknowledges
        (or rejects) the message we will replace/update it.
        """
        if not content and not attachments:
            _log.debug("Empty message suppressed")
            return

        msg_id = f"tmp-{datetime.now(tz=timezone.utc).timestamp()}"
        attachments = attachments or []
        outgoing = ChatMessage(
            msg_id=msg_id,
            channel_id=self._channel_id,
            sender_id=settings.get("user_id", "anonymous"),
            sender_display=settings.get("user_display", "Me"),
            content=content,
            timestamp=datetime.now(tz=timezone.utc),
            is_outgoing=True,
            attachments=attachments,
        )

        self._append_message(outgoing)

        # Publish to domain event-bus (fire-and-forget)
        _log.debug("Publishing OutgoingMessage event: %s", outgoing.msg_id)
        self._event_bus.publish(
            Event(
                topic="chat.outgoing",
                payload=outgoing.serialize(),
                replayable=False,
            )
        )

        # Clear persisted draft for this channel
        self._clear_draft_file()

    def start_typing(self) -> None:
        """Publish typing indicator event when user starts typing."""
        self._event_bus.publish(
            Event(
                topic="chat.typing",
                payload={"channel_id": self._channel_id, "user_id": settings.get("user_id")},
            )
        )

    def persist_draft(self, draft_text: str) -> None:
        """
        Persist unsent draft on disk.

        Called from the Controller on text-changed events.
        """
        if not draft_text.strip():
            self._clear_draft_file()
            return

        self._draft_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._draft_path.write_text(
                json.dumps({"draft": draft_text, "timestamp": datetime.now().isoformat()}),
                encoding="utf-8",
            )
            _log.debug("Draft persisted to %s", self._draft_path)
        except OSError as exc:
            _log.warning("Failed to write draft file: %s", exc)

    # -----------------------------------------------------------------------#
    # Internal helpers
    # -----------------------------------------------------------------------#
    def _register_event_subscriptions(self) -> None:
        """
        Subscribe to the global EventBus for chat-related events.

        We keep the subscription tokens so we can unsubscribe
        when the View-Model is deleted / the window is closed.
        """

        # Incoming messages
        self._event_bus.subscribe(
            "chat.incoming",
            self._on_incoming_message,
            group=f"vm_{self._channel_id}",
        )

        # Delivery acknowledgements for optimistic updates
        self._event_bus.subscribe(
            "chat.outgoing.confirmation",
            self._on_delivery_confirmation,
            group=f"vm_{self._channel_id}",
        )

        # Typing indicators
        self._event_bus.subscribe(
            "chat.typing",
            self._on_typing_indicator,
            group=f"vm_{self._channel_id}",
        )

        # Synchronised edits / deletions
        self._event_bus.subscribe(
            "chat.message.updated",
            self._on_remote_update,
            group=f"vm_{self._channel_id}",
        )

    # -----------------------------------------------------------------------#
    def _append_message(self, message: ChatMessage) -> None:
        with self._lock:
            self._messages.append(message)
        self.messageAdded.emit(message)

    # -----------------------------------------------------------------------#
    # Event-bus callback handlers
    # -----------------------------------------------------------------------#
    def _on_incoming_message(self, event: Event) -> None:
        """Handle new message events from other users."""
        payload = event.payload
        if payload["channel_id"] != self._channel_id:
            return

        msg = ChatMessage(
            msg_id=payload["msg_id"],
            channel_id=payload["channel_id"],
            sender_id=payload["sender_id"],
            sender_display=payload["sender_display"],
            content=payload["content"],
            timestamp=datetime.fromisoformat(payload["timestamp"]),
            attachments=[Path(p) for p in payload.get("attachments", [])],
        )
        self._append_message(msg)

    # -----------------------------------------------------------------------#
    def _on_delivery_confirmation(self, event: Event) -> None:
        """Replace optimistic message with definitive server copy."""
        payload = event.payload
        if payload["channel_id"] != self._channel_id:
            return

        tmp_id = payload["tmp_id"]
        real_id = payload["msg_id"]

        with self._lock:
            for idx, m in enumerate(self._messages):
                if m.msg_id == tmp_id:
                    updated = ChatMessage(
                        msg_id=real_id,
                        channel_id=m.channel_id,
                        sender_id=m.sender_id,
                        sender_display=m.sender_display,
                        content=m.content,
                        timestamp=datetime.fromisoformat(payload["timestamp"]),
                        is_outgoing=False,
                        attachments=m.attachments,
                    )
                    self._messages[idx] = updated
                    _log.debug("Optimistic message %s replaced by %s", tmp_id, real_id)
                    self.messageReplaced.emit(updated)
                    break

    # -----------------------------------------------------------------------#
    def _on_typing_indicator(self, event: Event) -> None:
        """Update typing indicator map & emit signal."""
        payload = event.payload
        if payload["channel_id"] != self._channel_id:
            return

        user_id = payload["user_id"]
        if user_id == settings.get("user_id"):
            return  # ignore self typing

        # Reset/Start debounce timer for this user
        timer = self._typing_users.get(user_id)
        if timer is None:
            timer = QtCore.QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda uid=user_id: self._emit_typing_end(uid))
            self._typing_users[user_id] = timer
            self.typingStatusChanged.emit(user_id, True)

        timer.start(3000)  # 3s window

    def _emit_typing_end(self, user_id: str) -> None:
        self.typingStatusChanged.emit(user_id, False)
        self._typing_users.pop(user_id, None)

    # -----------------------------------------------------------------------#
    def _on_remote_update(self, event: Event) -> None:
        """Handle remote edits or deletions."""
        payload = event.payload
        if payload["channel_id"] != self._channel_id:
            return

        with self._lock:
            for idx, m in enumerate(self._messages):
                if m.msg_id == payload["msg_id"]:
                    updated = ChatMessage(
                        msg_id=m.msg_id,
                        channel_id=m.channel_id,
                        sender_id=m.sender_id,
                        sender_display=m.sender_display,
                        content=payload.get("content", m.content),
                        timestamp=m.timestamp,
                        edited=True,
                        attachments=[Path(p) for p in payload.get("attachments", [])],
                    )
                    self._messages[idx] = updated
                    self.messageReplaced.emit(updated)
                    _log.debug("Message %s updated from remote", m.msg_id)
                    break

    # -----------------------------------------------------------------------#
    # Draft persistence
    # -----------------------------------------------------------------------#
    def _restore_draft_async(self) -> None:
        """Restore draft in a background thread to keep UI responsive."""

        def _worker(vm: "ChatViewModel") -> None:
            if vm._draft_path.exists():
                try:
                    data = json.loads(vm._draft_path.read_text(encoding="utf-8"))
                    draft = data.get("draft", "")
                    _log.debug("Draft restored for channel %s", vm._channel_id)
                    # Emit via Qt to avoid cross-thread issues
                    QtCore.QMetaObject.invokeMethod(
                        vm,
                        "_emit_draft_restored",
                        QtCore.Qt.QueuedConnection,
                        QtCore.Q_ARG(str, draft),
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    _log.warning("Failed to restore draft: %s", exc)

        threading.Thread(target=_worker, args=(self,), daemon=True).start()

    @QtCore.Slot(str)
    def _emit_draft_restored(self, text: str) -> None:
        self.historyLoaded.emit([])  # just to notify view to attach draft text

    def _clear_draft_file(self) -> None:
        try:
            if self._draft_path.exists():
                self._draft_path.unlink(missing_ok=True)
                _log.debug("Draft cleared for channel %s", self._channel_id)
        except OSError as exc:
            _log.warning("Failed to clear draft file: %s", exc)

    # -----------------------------------------------------------------------#
    # Qt Object Life-Cycle
    # -----------------------------------------------------------------------#
    def __del__(self) -> None:
        """Ensure we cleanly unsubscribe from the EventBus."""
        try:
            self._event_bus.unsubscribe_group(f"vm_{self._channel_id}")
        except Exception:  # pragma: no cover
            pass  # During interpreter shutdown objects may be gone


# ---------------------------------------------------------------------------#
# Factory (Dependency Injection ready)
# ---------------------------------------------------------------------------#
def create_chat_viewmodel(channel_id: str, event_bus: EventBus) -> ChatViewModel:
    """
    Factory helper so the app’s DI container can easily inject dependencies.

    Returns
    -------
    ChatViewModel
        Ready-to-use instance with subscriptions in place.
    """
    vm = ChatViewModel(channel_id=channel_id, event_bus=event_bus)
    return vm
```