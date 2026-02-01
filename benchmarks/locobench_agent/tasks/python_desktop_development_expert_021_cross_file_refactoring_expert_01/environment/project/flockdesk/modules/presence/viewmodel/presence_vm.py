```python
"""
FlockDesk – Presence Module: View-Model Layer
============================================

This file holds the *view-model* that mediates between the presence
backend-service (listening on the internal event-bus) and the Qt views /
QML components that render the roster.

The module is 100 % standalone and can be imported by tests without the
full desktop runtime.  It exposes one public symbol:

    PresenceViewModel  – A Qt QObject that wraps a
                         QAbstractListModel with presence data and
                         exposes commands for the UI.

Author  : FlockDesk Core Team
License : MIT (see project root)
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import types
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional

from PySide6 import QtCore

# ---------------------------------------------------------------------------#
# 3rd-party / infrastructure stubs
# ---------------------------------------------------------------------------#
# NOTE:
# The real application injects an actual event-bus implementation that
# resembles the minimal API below.  We ship a tiny duck-type fallback so
# the module does not crash when imported in isolation.
# ---------------------------------------------------------------------------#


class _DummySubscription:  # pragma: no cover – testing helper
    def __init__(self, topic: str, cb):
        self._topic, self._cb = topic, cb

    def dispose(self):
        """Mimic an un-subscribe operation."""
        logging.getLogger(__name__).debug("Unsubscribed from topic %s", self._topic)


class EventBus:  # pragma: no cover – placeholder
    """Very small subset of the real bus used in production."""

    def __init__(self):
        self._topics: Dict[str, List] = {}

    def publish(self, topic: str, payload: object) -> None:
        for cb in self._topics.get(topic, []):
            try:
                cb(payload)  # noqa: B023 – sync callback in fake bus
            except Exception:  # pylint: disable=broad-except
                logging.exception("Unhandled error in bus subscriber for topic %s", topic)

    def subscribe(self, topic: str, cb) -> _DummySubscription:
        self._topics.setdefault(topic, []).append(cb)
        return _DummySubscription(topic, cb)


# When FlockDesk boots, the DI-container injects a **shared** bus
# instance.  Until then, we fall back to a local private one.
_default_bus = EventBus()

# ---------------------------------------------------------------------------#
# Domain model
# ---------------------------------------------------------------------------#


class PresenceStatus(Enum):
    """Canonical presence states understood by the desktop suite."""

    ONLINE = auto()
    AWAY = auto()
    BUSY = auto()
    OFFLINE = auto()

    def __str__(self) -> str:  # Readable for QML
        return self.name.lower()


@dataclass(slots=True)
class PresenceEntry:
    user_id: str
    display_name: str
    status: PresenceStatus = PresenceStatus.OFFLINE
    last_active: _dt.datetime = field(default_factory=_dt.datetime.utcnow)

    def to_qvariant_map(self) -> Dict[str, object]:
        """Return values convertible by Qt for use in QML/JS."""
        return {
            "userId": self.user_id,
            "displayName": self.display_name,
            "status": str(self.status),
            "lastActive": self.last_active.isoformat(),
        }


# ---------------------------------------------------------------------------#
# QAbstractListModel representing the roster
# ---------------------------------------------------------------------------#


class PresenceListModel(QtCore.QAbstractListModel):
    """
    Thin wrapper between a list[PresenceEntry] and Qt's model/view API.
    Emits the usual model signals, hence updates appear instantaneously
    on bound QML ListViews or QtWidgets views.
    """

    # Qt Role numeric IDs
    USER_ID_ROLE = QtCore.Qt.UserRole + 1
    DISPLAY_NAME_ROLE = USER_ID_ROLE + 1
    STATUS_ROLE = DISPLAY_NAME_ROLE + 1
    LAST_ACTIVE_ROLE = STATUS_ROLE + 1

    _ROLE_NAMES = {
        USER_ID_ROLE: b"userId",
        DISPLAY_NAME_ROLE: b"displayName",
        STATUS_ROLE: b"status",
        LAST_ACTIVE_ROLE: b"lastActive",
    }

    # ---------------------------------------------------------------------#
    # Qt mandatory overrides
    # ---------------------------------------------------------------------#

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._roster: List[PresenceEntry] = []

    # Qt interface – meta
    def roleNames(self) -> Dict[int, bytes]:  # noqa: N802 – Qt API
        return self._ROLE_NAMES

    # Qt interface – data
    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._roster)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole):  # noqa: N802
        if not index.isValid() or not (0 <= index.row() < len(self._roster)):
            return None

        entry = self._roster[index.row()]

        if role == self.USER_ID_ROLE:
            return entry.user_id
        if role == self.DISPLAY_NAME_ROLE:
            return entry.display_name
        if role == self.STATUS_ROLE:
            return str(entry.status)
        if role == self.LAST_ACTIVE_ROLE:
            return entry.last_active.isoformat()

        return None

    # ------------------------------------------------------------------#
    # Mutating helpers exposed to the VM
    # ------------------------------------------------------------------#

    def upsert_entries(self, entries: List[PresenceEntry]) -> None:
        """
        Insert or update one or many presence rows.

        The algorithm is O(N*M) but roster lists are typically short
        (max ~200 members).  Optimise later if needed.
        """
        for entry in entries:
            try:
                idx = next(i for i, e in enumerate(self._roster) if e.user_id == entry.user_id)
                if self._roster[idx] != entry:
                    self._roster[idx] = entry
                    top_left = self.index(idx, 0)
                    self.dataChanged.emit(top_left, top_left, self._ROLE_NAMES.keys())
            except StopIteration:
                # New participant – append
                self.beginInsertRows(QtCore.QModelIndex(), len(self._roster), len(self._roster))
                self._roster.append(entry)
                self.endInsertRows()

    def remove_user(self, user_id: str) -> None:
        try:
            idx = next(i for i, e in enumerate(self._roster) if e.user_id == user_id)
        except StopIteration:
            return  # nothing to do
        self.beginRemoveRows(QtCore.QModelIndex(), idx, idx)
        del self._roster[idx]
        self.endRemoveRows()

    # convenience for QML
    @QtCore.Slot(str, result=int)
    def row_for_user(self, user_id: str) -> int:  # noqa: D401
        """Return row index for a given user or ‑1."""
        try:
            return next(i for i, entry in enumerate(self._roster) if entry.user_id == user_id)
        except StopIteration:
            return -1


# ---------------------------------------------------------------------------#
# Presence View-Model
# ---------------------------------------------------------------------------#


class PresenceViewModel(QtCore.QObject):
    """
    Qt QObject acting as the binding layer between presence model
    changes and the GUI.  It subscribes to an *EventBus*, receives
    events like ``presence.updated`` or ``presence.left``, and updates
    an internal QAbstractListModel exposed to QML.
    """

    presenceListChanged = QtCore.Signal()  # emitted when the model pointer itself changes
    errorOccurred = QtCore.Signal(str)

    # ------------------------------------------------------------------#
    # Construction / DI
    # ------------------------------------------------------------------#

    def __init__(
        self,
        bus: EventBus | None = None,
        *,
        current_user_id: Optional[str] = None,
        parent: Optional[QtCore.QObject] = None,
    ):
        super().__init__(parent)

        self._log = logging.getLogger(self.__class__.__name__)
        self._bus: EventBus = bus or _default_bus
        self._current_user_id = current_user_id

        # Our roster list-model
        self._model = PresenceListModel(self)

        # Keep references to bus subscriptions so we can dispose later.
        self._subscriptions: List[_DummySubscription] = []

        # Async tasks we spawn (cancel on destruction)
        self._tasks: List[asyncio.Task] = []

        self._wire_bus()
        self._bootstrap_roster()

    # ------------------------------------------------------------------#
    # Qt property for QML
    # ------------------------------------------------------------------#

    @QtCore.Property(QtCore.QObject, notify=presenceListChanged)
    def presenceModel(self) -> PresenceListModel:  # noqa: D401
        """Return the QAbstractListModel consumed by the view."""
        return self._model

    # ------------------------------------------------------------------#
    # Public API
    # ------------------------------------------------------------------#

    @QtCore.Slot(result=str)
    def currentUserId(self) -> str:  # noqa: D401, N802 – match Qt naming
        """Expose the logged-in user's ID to the view."""
        return self._current_user_id or ""

    @QtCore.Slot(str, str)
    def setStatus(self, user_id: str, raw_status: str) -> None:  # noqa: N802
        """
        Command from the UI to update somebody's presence manually.
        Usually only called for *self*.  Publishes an event so the
        backend broadcasts to everybody else.
        """
        try:
            status = PresenceStatus[raw_status.upper()]
        except KeyError as exc:
            self.errorOccurred.emit(f"Invalid status: {raw_status}")
            self._log.warning("Rejected invalid presence status %s", raw_status)
            return

        payload = {
            "user_id": user_id,
            "status": status.name,
            "timestamp": _dt.datetime.utcnow().isoformat(),
        }
        self._bus.publish("presence.set_status", payload)

    # ------------------------------------------------------------------#
    # Private helpers – bus / async
    # ------------------------------------------------------------------#

    def _wire_bus(self) -> None:
        """Subscribe to presence events on the internal event-bus."""
        self._subscriptions.append(self._bus.subscribe("presence.snapshot", self._on_snapshot))
        self._subscriptions.append(self._bus.subscribe("presence.updated", self._on_presence_updated))
        self._subscriptions.append(self._bus.subscribe("presence.left", self._on_presence_left))

    def _bootstrap_roster(self) -> None:
        """
        Ask the backend for the initial roster list via RPC-style
        request/response.  We use asyncio so as not to block the Qt loop.
        """

        async def request_snapshot():
            try:
                # fire-and-wait pattern: publish request, listen for snapshot
                # The backend replies on the same `presence.snapshot` topic
                self._bus.publish("presence.request_snapshot", {"requester": self._current_user_id})
                # DONE: nothing, listener will receive snapshot asynchronously
            except Exception:  # pylint: disable=broad-except
                self._log.exception("Failed to request presence snapshot")
                self.errorOccurred.emit("Presence initialisation failed")

        task = asyncio.create_task(request_snapshot(), name="presence.bootstrap")
        self._tasks.append(task)

    # ------------------------------------------------------------------#
    # Bus event callbacks – sync context (fake bus).
    # In production they run on a background thread; we therefore use
    # Qt's `invokeMethod` to marshal into the main thread.
    # ------------------------------------------------------------------#

    # The real bus dispatches events on worker threads.  Qt objects are
    # not thread-safe; we hop back to the main thread via single-shot
    # queued connections.  `QtCore.QMetaObject.invokeMethod` is used
    # instead of Signals for performance / testability.
    def _sync_to_qt(self, fn: types.FunctionType, /, *args):
        QtCore.QMetaObject.invokeMethod(
            self,
            lambda: fn(*args),  # type: ignore[arg-type]  # pyqt signature magic
            QtCore.Qt.QueuedConnection,
        )

    # Snapshot – full presence list
    def _on_snapshot(self, payload):
        self._log.debug("Received presence.snapshot %s", payload)
        entries = [
            PresenceEntry(
                user_id=e["user_id"],
                display_name=e["display_name"],
                status=PresenceStatus[e["status"].upper()],
                last_active=_dt.datetime.fromisoformat(e["last_active"]),
            )
            for e in payload.get("members", [])
            if "user_id" in e
        ]
        self._sync_to_qt(self._model.upsert_entries, entries)

    # Incremental updates
    def _on_presence_updated(self, payload):
        self._log.debug("presence.updated %s", payload)
        entry = PresenceEntry(
            user_id=payload["user_id"],
            display_name=payload.get("display_name", payload["user_id"]),
            status=PresenceStatus[payload["status"].upper()],
            last_active=_dt.datetime.utcnow(),
        )
        self._sync_to_qt(self._model.upsert_entries, [entry])

    # User left – remove from list
    def _on_presence_left(self, payload):
        self._log.debug("presence.left %s", payload)
        self._sync_to_qt(self._model.remove_user, payload["user_id"])

    # ------------------------------------------------------------------#
    # Cleanup
    # ------------------------------------------------------------------#

    def __del__(self):
        for sub in self._subscriptions:
            try:
                sub.dispose()
            except Exception:  # pragma: no cover
                self._log.warning("Failed to dispose subscription %s", sub, exc_info=True)
        for task in self._tasks:
            task.cancel()
```