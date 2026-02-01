```python
"""
flockdesk.modules.chat.main
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Entry-point for the FlockDesk Chat micro-front-end.  Starts the Qt
application (if necessary), wires up the view-model, registers to the
internal event-bus, and coordinates send/receive message flows.

The code purposefully keeps GUI‐logic thin and delegates most of the
business rules to the ChatService so that it can be unit-tested without
spinning up a full Qt stack.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

# ---------------------------------------------------------------------------#
# 3rd-party / FlockDesk imports
# ---------------------------------------------------------------------------#
try:
    # FlockDesk core utilities
    from flockdesk.core.event_bus import EventBus, Event  # type: ignore
    from flockdesk.core.plugins import plugin  # decorator that registers plugin
except ImportError:  # ---- Fallback stubs for standalone execution ---------#
    class Event:  # noqa: D101 – minimal stub
        pass

    class EventBus:  # noqa: D101 – minimal stub
        def __init__(self) -> None:
            self._subscribers: dict[type, list[Callable]] = {}

        def publish(self, event: Event) -> None:
            for fn in self._subscribers.get(type(event), []):
                fn(event)

        def subscribe(self, event_type: type, handler: Callable) -> None:
            self._subscribers.setdefault(event_type, []).append(handler)

    def plugin(cls):  # noqa: D401 – simple decorator stub
        return cls

# Qt/PySide needs to be importable.  If unavailable, gracefully degrade so
# that non-GUI unit tests can still be executed.
try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    QtCore = QtGui = QtWidgets = None  # type: ignore

# ---------------------------------------------------------------------------#
# Logging configuration
# ---------------------------------------------------------------------------#
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------#
# Domain model
# ---------------------------------------------------------------------------#
@dataclass(slots=True, frozen=True)
class ChatMessage:
    """Immutable value-object representing a chat message."""
    msg_id: str
    sender_id: str
    body: str
    sent_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def __post_init__(self) -> None:  # noqa: D401
        if not self.body:
            raise ValueError("Message body must not be empty")


# ---------------------------------------------------------------------------#
# Event definitions
# ---------------------------------------------------------------------------#
class MessageReceived(Event):
    """Published when a message is delivered to the client."""

    def __init__(self, message: ChatMessage) -> None:
        self.message = message


class MessageSendRequest(Event):
    """Published when local user requests to send a message."""

    def __init__(self, message: ChatMessage) -> None:
        self.message = message


# ---------------------------------------------------------------------------#
# ChatService – business logic boundary
# ---------------------------------------------------------------------------#
class ChatService(QtCore.QObject if QtCore else object):  # type: ignore
    """
    Bridges the event-bus with the Qt layer, encapsulating all back-end
    behaviour so that the GUI remains declarative.
    """

    message_received = (
        QtCore.Signal(ChatMessage) if QtCore else lambda *_: None  # type: ignore
    )
    """
    Qt signal emitted when a new message was distributed through the
    event-bus (originating from self or remote users).
    """

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__()
        self._bus = event_bus

        # Register listeners
        self._bus.subscribe(MessageReceived, self._on_message_received)
        logger.debug("ChatService subscribed to MessageReceived events")

    # ---------------------------------------------------------------------#
    # Outgoing messages
    # ---------------------------------------------------------------------#
    def send_message(self, sender_id: str, body: str) -> None:
        """Validate & publish outgoing message."""
        body = body.strip()
        if not body:
            logger.warning("Attempt to send an empty message – ignored")
            return

        msg = ChatMessage(
            msg_id=str(uuid.uuid4()),
            sender_id=sender_id,
            body=body,
        )
        logger.debug("Publishing MessageSendRequest for %s", msg.msg_id)
        self._bus.publish(MessageSendRequest(msg))

        # Locally echo immediately for snappy UX
        self._bus.publish(MessageReceived(msg))

    # ---------------------------------------------------------------------#
    # Incoming messages
    # ---------------------------------------------------------------------#
    def _on_message_received(self, event: MessageReceived) -> None:
        logger.debug("ChatService received message %s", event.message.msg_id)
        if QtCore:
            self.message_received.emit(event.message)
        else:
            # Non-GUI context: we can log or route elsewhere
            logger.info("Received message (headless): %s", event.message.body)


# ---------------------------------------------------------------------------#
# View-Model (MVVM – QAbstractListModel)
# ---------------------------------------------------------------------------#
if QtCore:  # pragma: no branch – declared only when Qt available

    class ChatListModel(QtCore.QAbstractListModel):  # type: ignore
        """
        A very small view-model that exposes chat messages to a Qt view.
        """

        ROLE_MESSAGE = QtCore.Qt.UserRole + 1

        def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
            super().__init__(parent)
            self._messages: List[ChatMessage] = []

        # ----------------------------- Model API --------------------------#
        def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
            return len(self._messages)

        def data(
            self,
            index: QtCore.QModelIndex,
            role: int = QtCore.Qt.DisplayRole,
        ):
            if not index.isValid() or not 0 <= index.row() < len(self._messages):
                return None

            message = self._messages[index.row()]
            if role == QtCore.Qt.DisplayRole:
                return f"[{message.sender_id}] {message.body}"
            if role == self.ROLE_MESSAGE:
                return message
            return None

        # ---------------------------- Mutators ---------------------------#
        def add_message(self, message: ChatMessage) -> None:
            self.beginInsertRows(
                QtCore.QModelIndex(), self.rowCount(), self.rowCount()
            )
            self._messages.append(message)
            self.endInsertRows()

        # ------------------------- Role names ---------------------------#
        def roleNames(self):  # noqa: N802
            roles = super().roleNames()  # type: ignore[attr-defined]
            roles[self.ROLE_MESSAGE] = b"message"
            return roles


# ---------------------------------------------------------------------------#
# Qt Widget glue
# ---------------------------------------------------------------------------#
if QtWidgets:  # pragma: no branch — only define when Qt is importable

    class ChatWindow(QtWidgets.QWidget):
        """
        Quick messenger UI demonstrating MVVM.  Real production GUIs would
        be split into .ui Designer files and injected via QML/QtQuick.
        """

        def __init__(self, service: ChatService, *, my_user: str) -> None:
            super().__init__()
            self._service = service
            self._my_user = my_user

            # ------------------------- Widgets ---------------------------#
            self._view = QtWidgets.QListView()
            self._model = ChatListModel(self)
            self._view.setModel(self._model)

            self._input = QtWidgets.QLineEdit()
            self._input.setPlaceholderText("Type a message…")
            self._input.returnPressed.connect(self._on_return_pressed)

            # ----------------------- Layout ------------------------------#
            layout = QtWidgets.QVBoxLayout(self)
            layout.addWidget(self._view)
            layout.addWidget(self._input)

            # ------------------ Connect service signals ------------------#
            self._service.message_received.connect(self._model.add_message)

            # --------------- Quality-of-life window sizing ---------------#
            self.setWindowTitle("FlockDesk • Chat")
            self.resize(400, 600)

        # ----------------------------------------------------------------#
        # Slots
        # ----------------------------------------------------------------#
        def _on_return_pressed(self) -> None:
            body = self._input.text()
            self._input.clear()
            self._service.send_message(self._my_user, body)


# ---------------------------------------------------------------------------#
# Module entry-point / plugin registration
# ---------------------------------------------------------------------------#
@plugin
class ChatModule:
    """
    Plugin declaration for the FlockDesk runtime.  The host application
    discovers this class via entry points and executes `run()`.
    """

    NAME = "flockdesk.chat"

    def __init__(self, bus: Optional[EventBus] = None) -> None:
        # In production environment the bus is injected; when user double
        #-clicks chat.exe we lazily instantiate a local bus so that the UI
        # still works (offline/testing).
        self._bus = bus or EventBus()
        self._qt_created_locally = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------#
    # Public API
    # ------------------------------------------------------------------#
    def run(self, *, user_id: str) -> None:  # noqa: D401
        """
        Bootstrap Qt event loop and start the chat window.
        """
        logger.info("Starting ChatModule for user %s", user_id)

        # ------------------------- Qt setup ---------------------------#
        app = QtWidgets.QApplication.instance() if QtWidgets else None
        if app is None and QtWidgets:  # pragma: no branch
            self._qt_created_locally = True
            app = QtWidgets.QApplication(sys.argv)

        if QtWidgets:
            service = ChatService(self._bus)
            window = ChatWindow(service, my_user=user_id)
            window.show()

            # ------------------- Asyncio integration ------------------#
            # Needed if the broader FlockDesk runtime is using asyncio
            self._loop = asyncio.get_event_loop_policy().get_event_loop()
            if self._loop.is_running():
                # Interleave Qt & asyncio through QEventLoop / qasync
                from qasync import QEventLoop  # lazy import to avoid dep
                qt_loop = QEventLoop(app)  # type: ignore[arg-type]
                asyncio.set_event_loop(qt_loop)
                qt_loop.run_forever()
            else:
                sys.exit(app.exec())

        else:
            logger.error("PySide6 is not available – cannot start GUI.")

    # ------------------------------------------------------------------#
    # Convenience CLI launch (development)
    # ------------------------------------------------------------------#
    @staticmethod
    def cli() -> None:  # pragma: no cover
        """
        Quick way to launch the chat window directly:
            python -m flockdesk.modules.chat.main
        """
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        ChatModule().run(user_id="Me")


# ---------------------------------------------------------------------------#
# python -m flockdesk.modules.chat.main
# ---------------------------------------------------------------------------#
if __name__ == "__main__":  # pragma: no cover
    ChatModule.cli()
```