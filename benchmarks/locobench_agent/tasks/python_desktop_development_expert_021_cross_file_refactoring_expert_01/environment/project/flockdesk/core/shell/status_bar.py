from __future__ import annotations

"""
flockdesk.core.shell.status_bar
--------------------------------

Production-quality implementation of the FlockDesk status-bar component.

Responsibilities
================
• Provide a Qt/QStatusBar based widget that can be embedded in the shell window.
• Act as the *View* in MVVM. Business logic lives in `StatusBarViewModel`.
• Listen to the internal event-bus and surface relevant information (network,
  presence, plugin updates, etc.) to the user.
• Offer a public plugin API (`StatusIndicatorPlugin`) so extensions can add
  their own widgets or indicators at runtime.
• Handle message lifecycles (automatic expiration, severity colouring, …).
"""

import importlib.metadata
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QStatusBar, QWidget

# --------------------------------------------------------------------------- #
# Fallback / development stubs
# --------------------------------------------------------------------------- #
_log = logging.getLogger(__name__)


try:
    # The real event-bus shipped with FlockDesk
    from flockdesk.core.event_bus import EventBus  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – local dev environment
    class EventBus:  # pylint: disable=too-few-public-methods
        """
        Extremely small, in-memory event-bus used when FlockDesk is not fully
        installed (unit-tests, docs, CI). The interface mimics the production
        bus closely enough for this module’s needs.
        """

        _subscribers: Dict[str, List[Callable[[Any], None]]] = {}

        @classmethod
        def subscribe(cls, topic: str, callback: Callable[[Any], None]) -> None:
            cls._subscribers.setdefault(topic, []).append(callback)
            _log.debug("Subscribed %s to topic '%s'", callback, topic)

        @classmethod
        def publish(cls, topic: str, payload: Any) -> None:
            _log.debug("Publishing event %s with payload %s", topic, payload)
            for cb in cls._subscribers.get(topic, []):
                try:
                    cb(payload)
                except Exception:  # pragma: no cover
                    _log.exception("Uncaught error in event-bus subscriber")


# --------------------------------------------------------------------------- #
# Data-model
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class StatusMessage:
    """
    Container with semantics for a message rendered in the status-bar.

    Attributes
    ----------
    severity:
        One of ``info``, ``warning`` or ``error``.
    text:
        Localised, human readable string.
    ttl:
        Time-to-live in seconds. Optional ``None`` means the message stays
        until explicitly cleared.
    timestamp:
        UNIX epoch when the message was created. Automatically supplied.
    """

    severity: str
    text: str
    ttl: Optional[float] = 5.0
    timestamp: float = field(default_factory=lambda: time.time())

    # Convenience factory helpers
    @classmethod
    def info(cls, text: str, ttl: float = 5.0) -> "StatusMessage":
        return cls("info", text, ttl)

    @classmethod
    def warning(cls, text: str, ttl: float = 7.0) -> "StatusMessage":
        return cls("warning", text, ttl)

    @classmethod
    def error(cls, text: str, ttl: Optional[float] = None) -> "StatusMessage":
        return cls("error", text, ttl)


# --------------------------------------------------------------------------- #
# View-Model (MVVM)
# --------------------------------------------------------------------------- #
class StatusBarViewModel(QObject):
    """
    Glue between backend events and the *View* (`StatusBarWidget`).

    Thread-safety: All public methods must be called from the Qt GUI thread
    or use `QMetaObject.invokeMethod`. For now we assume EventBus already
    dispatches on the main thread.
    """

    message_added = Signal(StatusMessage)
    message_removed = Signal(StatusMessage)
    plugin_added = Signal(QObject)  # Emits `StatusIndicatorPlugin`

    #: Maps severity → Qt colour
    SEVERITY_COLORS: Dict[str, QColor] = {
        "info": QColor("#32a852"),
        "warning": QColor("#e0a800"),
        "error": QColor("#dc3545"),
    }

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._messages: List[StatusMessage] = []

        # Periodic cleanup for expired messages
        self._timer = QTimer(self)
        self._timer.setInterval(1_000)
        self._timer.timeout.connect(self._clear_expired)
        self._timer.start()

        # Wire up to internal bus
        self._register_event_handlers()

        # Auto-discover status-bar plugins via setuptools entry-points
        self._load_external_plugins()

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    @Slot(StatusMessage)
    def add_message(self, message: StatusMessage) -> None:
        """
        Add a new message and notify views.
        """
        self._messages.append(message)
        self.message_added.emit(message)
        _log.debug("Added status-message: %s", message)

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #
    def _register_event_handlers(self) -> None:
        """
        Subscribe to core topics and convert them into UI messages.
        """
        EventBus.subscribe("network.connection", self._on_network_event)
        EventBus.subscribe("plugins.updates", self._on_plugin_updates)
        EventBus.subscribe("user.presence", self._on_presence_update)

    def _load_external_plugins(self) -> None:
        """
        Enumerate and instantiate all `flockdesk_status_plugins` entry-points.
        External packages can ship their own status indicators without touching
        the core.
        """
        try:
            eps = importlib.metadata.entry_points(group="flockdesk_status_plugins")
        except Exception:  # pragma: no cover
            _log.exception("Unable to resolve plugin entry-points")
            eps = ()

        for ep in eps:
            try:
                plugin_cls = ep.load()
                plugin = plugin_cls(self)  # type: ignore[call-arg]
                _log.info("Loaded status-bar plugin %s from %s", plugin, ep.module)
                self.plugin_added.emit(plugin)
            except Exception:  # pragma: no cover
                _log.exception("Failed loading plugin entry-point '%s'", ep)

    # --------------------------------------------------------------------- #
    # Event handlers
    # --------------------------------------------------------------------- #
    def _on_network_event(self, data: Dict[str, Any]) -> None:
        """
        'network.connection' event schema::

            {
                'state': 'online' | 'offline' | 'degraded',
                'latency_ms': int,
            }
        """
        state = data.get("state", "unknown")
        latency = data.get("latency_ms", "–")
        text = f"Network {state.upper()} (latency: {latency} ms)"

        severity = {
            "online": "info",
            "degraded": "warning",
            "offline": "error",
        }.get(state, "warning")

        self.add_message(StatusMessage(severity, text, ttl=4.0))

    def _on_plugin_updates(self, data: Dict[str, Any]) -> None:
        """
        'plugins.updates' event schema::

            {
                'plugin_id': str,
                'version': str,
                'action': 'installed' | 'updated' | 'failed',
            }
        """
        action = data.get("action", "updated")
        plugin_id = data.get("plugin_id", "unknown")
        version = data.get("version", "")
        text = f"Plugin {plugin_id} {action} {version}".strip()
        severity = "info" if action in ("installed", "updated") else "error"
        self.add_message(StatusMessage(severity, text))

    def _on_presence_update(self, data: Dict[str, Any]) -> None:
        """
        'user.presence' event schema::

            {
                'user': str,
                'status': 'online' | 'away' | 'dnd' | 'offline',
            }
        """
        user = data.get("user", "Unknown user")
        status = data.get("status", "offline")
        text = f"{user} is now {status.upper()}"
        self.add_message(StatusMessage.info(text, ttl=2.5))

    # --------------------------------------------------------------------- #
    # House-keeping
    # --------------------------------------------------------------------- #
    def _clear_expired(self) -> None:
        """
        Remove any messages whose TTL expired and notify views.
        """
        now = time.time()
        expired: List[StatusMessage] = [
            m for m in self._messages
            if m.ttl is not None and m.timestamp + m.ttl < now
        ]
        for msg in expired:
            self._messages.remove(msg)
            self.message_removed.emit(msg)
            _log.debug("Expired status-message removed: %s", msg)


# --------------------------------------------------------------------------- #
# Plugin API
# --------------------------------------------------------------------------- #
class StatusIndicatorPlugin(QObject):
    """
    Baseclass for custom widgets that appear permanently in the status-bar.

    To expose a plugin via setuptools, declare an entry-point:

    [project.entry-points."flockdesk_status_plugins"]
    my_plugin = "my_package.status_plugin:MyStatusPlugin"
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    def widget(self) -> QWidget:
        """
        Return a *new* widget instance to be inserted into the QStatusBar.
        Subclasses **must** implement.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# View (Qt Widget)
# --------------------------------------------------------------------------- #
class StatusBarWidget(QStatusBar):
    """
    QStatusBar implementation that binds itself to a `StatusBarViewModel`
    instance. The same bar can be used in multiple windows by sharing the
    view-model.
    """

    def __init__(self, view_model: StatusBarViewModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("flockdesk-status-bar")

        self._view_model = view_model
        self._message_label = QLabel(self)
        self._message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.addPermanentWidget(self._message_label, 1)
        self._message_label.hide()

        # Connect signals
        view_model.message_added.connect(self._on_message_added)
        view_model.message_removed.connect(self._on_message_removed)
        view_model.plugin_added.connect(self._on_plugin_added)

        # Keep at most one active message visible
        self._active_message: Optional[StatusMessage] = None

    # --------------------------------------------------------------------- #
    # Slots
    # --------------------------------------------------------------------- #
    @Slot(StatusMessage)
    def _on_message_added(self, msg: StatusMessage) -> None:
        """
        Render the message with colour matching its severity.
        """
        self._active_message = msg
        color = self._view_model.SEVERITY_COLORS.get(msg.severity, QColor("black"))
        self._message_label.setStyleSheet(f"color: {color.name()};")
        self._message_label.setText(msg.text)
        self._message_label.show()
        _log.debug("Displayed status message: %s", msg)

        # If the message is temporary, ensure it's cleared via timer as well
        if msg.ttl:
            QTimer.singleShot(int(msg.ttl * 1000), lambda: self._check_auto_clear(msg))

    @Slot(StatusMessage)
    def _on_message_removed(self, msg: StatusMessage) -> None:
        """
        Hide the message if it's the current one.
        """
        if self._active_message == msg:
            self._message_label.clear()
            self._message_label.hide()
            self._active_message = None
            _log.debug("Hid status message: %s", msg)

    @Slot(QObject)
    def _on_plugin_added(self, plugin: QObject) -> None:
        """
        Position permanent widgets for newly loaded plugins.
        """
        if not isinstance(plugin, StatusIndicatorPlugin):
            _log.warning("Ignoring invalid status plugin: %s", plugin)
            return
        try:
            widget = plugin.widget()
            self.addPermanentWidget(widget)
            _log.info("Added plugin-widget to status-bar: %s", plugin)
        except Exception:  # pragma: no cover
            _log.exception("Plugin '%s' failed to provide widget()", plugin)

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #
    def _check_auto_clear(self, msg: StatusMessage) -> None:
        """
        Clear the message if it's still active. This can happen if TTL expired
        but the message hasn't been explicitly removed yet.
        """
        if self._active_message == msg:
            self._message_label.clear()
            self._message_label.hide()
            self._active_message = None
            _log.debug("Auto-cleared status message: %s", msg)


# --------------------------------------------------------------------------- #
# Sample plugin (demonstration only)
# --------------------------------------------------------------------------- #
class _ClockPlugin(StatusIndicatorPlugin):
    """
    Tiny plugin showing the current local time. Primarily for demonstration
    and unit-testing of the plugin interface. Not registered through an
    entry-point but instantiated manually when this module is executed
    stand-alone.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._label = QLabel()
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)

        self._timer = QTimer(self)
        self._timer.setInterval(1_000)
        self._timer.timeout.connect(self._update)
        self._timer.start()

        self._update()

    def _update(self) -> None:
        self._label.setText(time.strftime("%H:%M:%S"))

    def widget(self) -> QWidget:  # noqa: D401
        return self._label


# --------------------------------------------------------------------------- #
# Stand-alone manual test
# --------------------------------------------------------------------------- #
def _demo() -> None:  # pragma: no cover
    """
    Quickly run this module to visually inspect behaviour.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    app = QApplication(sys.argv)

    vm = StatusBarViewModel()
    bar = StatusBarWidget(vm)
    bar.resize(640, 24)
    bar.show()

    # Publish dummy events every few seconds
    def spam_events() -> None:
        EventBus.publish("network.connection", {"state": "online", "latency_ms": 42})
        EventBus.publish("plugins.updates", {
            "plugin_id": "spellchecker",
            "version": "1.2.3",
            "action": "updated",
        })
        EventBus.publish("user.presence", {"user": "Alice", "status": "away"})
        QTimer.singleShot(9_000, spam_events)

    spam_events()

    # Inject clock plugin
    vm.plugin_added.emit(_ClockPlugin(vm))

    sys.exit(app.exec())


if __name__ == "__main__":  # pragma: no cover
    _demo()
