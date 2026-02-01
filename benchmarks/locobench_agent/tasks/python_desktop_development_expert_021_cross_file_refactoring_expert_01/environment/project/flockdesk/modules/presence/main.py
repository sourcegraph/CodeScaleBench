```python
"""
flockdesk.modules.presence.main
================================

Real-time presence micro-frontend for the FlockDesk desktop suite.  The module
subscribes to user-status events coming from the internal event-bus, maintains
a reactive in-memory model and renders the data through a small Qt/PySide6 UI
implemented with an MVVM flavour.

The file can be started stand-alone (for local development) or imported by the
FlockDesk launcher which injects the shared ``EventBus`` implementation.

Copyright:
    (c) 2024 FlockDesk Contributors – MIT License
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import pkg_resources
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

LOG = logging.getLogger("flockdesk.presence")
LOG.setLevel(logging.INFO)


################################################################################
# Event-Bus Abstractions
################################################################################
class EventBus(Protocol):
    """Very small subset of the FlockDesk event-bus contract we care about."""

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None: ...

    def subscribe(
        self,
        topic: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]],
        *,
        buffered: bool = False,
    ) -> None: ...


class _InProcessBus:
    """
    Development fallback event-bus that works completely in-process and
    single-threaded. **Never** used in production where the concrete bus will
    be injected by the launcher (e.g., NATS, ZeroMQ, or AMQP).
    """

    def __init__(self) -> None:
        self._topics: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        LOG.debug("Publish: %s -> %s", topic, payload)
        for handler in self._topics.get(topic, []):
            try:
                await handler(payload)
            except Exception:  # pragma: no cover
                LOG.exception("Handler error for topic %s", topic)

    def subscribe(
        self,
        topic: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]],
        *,
        buffered: bool = False,
    ) -> None:
        self._topics.setdefault(topic, []).append(handler)
        LOG.debug("Subscribed %s to %s", handler, topic)


################################################################################
# Model
################################################################################
@dataclass(slots=True)
class UserPresence:
    """Immutable snapshot of a user's current presence."""

    user_id: str
    display_name: str
    status: str  # e.g. "online", "away", "dnd", "offline"
    last_active: datetime
    avatar_url: Optional[str] = None

    def is_online(self) -> bool:
        """Return ``True`` if the user is considered online."""
        if self.status in {"offline", "unknown"}:
            return False
        delta = datetime.utcnow() - self.last_active
        return delta < timedelta(minutes=5)


################################################################################
# View-Model
################################################################################
class PresenceViewModel(QObject):
    """
    Wraps the presence collection and notifies Qt when something changes.
    The VM lives on the Qt thread and receives signals forwarded from asyncio.
    """

    presence_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._users: Dict[str, UserPresence] = {}

    # --------------------------------------------------------------------- API
    def all_users(self) -> List[UserPresence]:
        return sorted(
            self._users.values(), key=lambda u: (not u.is_online(), u.display_name)
        )

    @Slot(dict)
    def on_presence_event(self, evt: Dict[str, Any]) -> None:
        """
        Slot invoked by the asyncio runner; marshals JSON into our dataclass and
        emits a notification to the UI controls.
        """
        user = UserPresence(
            user_id=evt["user_id"],
            display_name=evt.get("display_name", evt["user_id"]),
            status=evt.get("status", "unknown"),
            last_active=datetime.fromisoformat(evt["last_active"]),
            avatar_url=evt.get("avatar_url"),
        )
        LOG.debug("Presence updated: %s", user)
        self._users[user.user_id] = user
        self.presence_changed.emit()

    # ----------------------------------------------------------- Diagnostics
    def __repr__(self) -> str:  # pragma: no cover
        return f"<PresenceViewModel users={len(self._users)}>"


################################################################################
# Qt View
################################################################################
class PresenceListWidget(QWidget):
    """
    Very small widget that shows presence information in a vertical list.
    It is intentionally minimal – complex styling is handled by FlockDesk's
    global stylesheet that is applied by the shell.
    """

    def __init__(self, vm: PresenceViewModel, *, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._vm = vm
        self._setup_ui()
        vm.presence_changed.connect(self._refresh)

    # ---------------------------------------------------------------- UI
    def _setup_ui(self) -> None:
        self.setWindowTitle("Presence")
        layout = QVBoxLayout(self)
        self._list = QListWidget(self)
        self._list.setUniformItemSizes(True)
        layout.addWidget(self._list)

    @Slot()
    def _refresh(self) -> None:
        LOG.debug("Refresh UI")
        self._list.clear()
        for user in self._vm.all_users():
            item = QListWidgetItem()
            prefix = "🟢" if user.is_online() else "⚫"
            item.setText(f"{prefix}  {user.display_name}")
            if user.avatar_url:
                pixmap = QPixmap(user.avatar_url)
                if not pixmap.isNull():
                    item.setIcon(pixmap.scaled(24, 24, Qt.KeepAspectRatio))
            self._list.addItem(item)


################################################################################
# Presence Service (async)
################################################################################
class PresenceService:
    """
    Background asyncio component responsible for:

        • Subscribing to the presence topic
        • Forwarding updates into the Qt world (thread-safe)
    """

    _TOPIC = "users.presence"

    def __init__(self, bus: EventBus, vm: PresenceViewModel, qt_obj: QObject) -> None:
        self._bus = bus
        self._vm = vm
        self._qt_obj = qt_obj

    async def start(self) -> None:
        # Subscribe for push updates coming from remote users
        self._bus.subscribe(self._TOPIC, self._handle_presence)

        # Send an initial handshake for the local user (if desired)
        await self._publish_local_presence("online")

        # Emit a heartbeat every 30 s so others know we're still alive
        asyncio.create_task(self._heartbeat())

    # ---------------------------------------------------------------- internals
    async def _handle_presence(self, payload: Dict[str, Any]) -> None:
        """
        Receives JSON dictionaries from the bus and routes them into the Qt
        thread where the view-model lives.
        """
        # Qt objects must only be touched from their own thread, therefore we
        # use `QMetaObject.invokeMethod` to schedule the slot.
        LOG.debug("Event-bus -> Qt: %s", payload)
        QMetaObject.invokeMethod(
            self._qt_obj,
            lambda: self._vm.on_presence_event(payload),
            Qt.QueuedConnection,
        )

    async def _publish_local_presence(self, status: str) -> None:
        payload = {
            "user_id": self._local_user(),
            "display_name": self._local_user(),  # demo
            "status": status,
            "last_active": datetime.utcnow().isoformat(),
            "avatar_url": None,
        }
        await self._bus.publish(self._TOPIC, payload)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            await self._publish_local_presence("online")

    # ---------------------------------------------------------------- util
    @staticmethod
    def _local_user() -> str:
        # In real life we would ask the identity service
        return Path.home().name


################################################################################
# Plugin System (Providers, Rich-Presence, etc.)
################################################################################
class PresenceProvider(Protocol):
    """
    Extendable hook for vendors to feed additional presence information into
    the bus (think of Slack or Teams gateways).  Providers are optional Python
    packages that expose an ``flockdesk_presence_provider = mypkg:make_provider``
    entry-point.
    """

    async def start(self, bus: EventBus) -> None: ...


def _load_providers() -> List[PresenceProvider]:
    providers: List[PresenceProvider] = []
    for entry_point in pkg_resources.iter_entry_points("flockdesk_presence_provider"):
        try:
            factory = entry_point.load()
            providers.append(factory())  # type: ignore[call-arg]
            LOG.info("Loaded presence provider %s", entry_point.name)
        except Exception:  # pragma: no cover
            LOG.exception("Failed to load presence provider %s", entry_point.name)
    return providers


################################################################################
# Bootstrap
################################################################################
async def _async_main(bus: EventBus) -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    vm = PresenceViewModel()
    widget = PresenceListWidget(vm)
    widget.resize(240, 400)
    widget.show()

    # Async service & plugins
    service = PresenceService(bus, vm, widget)
    await service.start()

    for prov in _load_providers():
        asyncio.create_task(prov.start(bus))

    # ---------------------------------------------------------------- Run loop
    # Integrate Qt + asyncio.  We manually pump the event-loop every few ms so
    # we don't depend on *qasync* which would add an additional runtime dep.
    loop = asyncio.get_running_loop()
    qtimer = QTimer()
    qtimer.setInterval(5)  # ms
    qtimer.timeout.connect(lambda: None)  # NOOP, but keeps Qt awake
    qtimer.start()

    # Handle ^C gracefully on *nix
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, app.quit)

    await loop.run_in_executor(None, app.exec)


def main() -> None:  # pragma: no cover
    """
    Entry-point used by the micro-frontend launcher **or** when the file is
    executed directly.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s -> %(message)s",
    )
    bus: EventBus = _InProcessBus()  # dev fallback
    try:
        asyncio.run(_async_main(bus))
    except KeyboardInterrupt:
        LOG.info("Shutting down.")


if __name__ == "__main__":  # pragma: no cover
    main()
```