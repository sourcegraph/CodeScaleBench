```python
"""
FlockDesk – Social Workspace Orchestrator
----------------------------------------

View base implementation for the MVVM layer.

Every micro–front-end view in FlockDesk should inherit from ``ViewBase`` to get:

    * Strongly-typed ViewModel wiring
    * Centralised event-bus subscription management
    * Automatic Qt shortcut handling
    * Persisted window geometry / arbitrary state via QSettings
    * Live theme switching
    * Safe teardown & diagnostic logging

The class purposefully avoids caring about *what* widgets are created; concrete
sub-classes implement ``_construct_ui`` and ``_bind_view_model`` while the base
takes care of all plumbing code.

Author: FlockDesk Core Team
"""

from __future__ import annotations

import json
import logging
import sys
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import (QByteArray, QEvent, QObject, QPoint, QRect, QSize,
                            Qt, QSettings, Signal, Slot)
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QShortcut, QWidget

# --------------------------------------------------------------------------- #
# Optional dependency – the in-house event bus. For 3rd-party tooling or unit
# tests the import may not be available, therefore a light-weight stub helps
# to keep the module importable even if the real bus is missing.
# --------------------------------------------------------------------------- #
try:  # pragma: no-cover – real bus exists only in production runtime
    from flockdesk.shared.event_bus import EventBus  # type: ignore
except ModuleNotFoundError:  # pragma: no-cover
    class _StubEventBus(QObject):  # pylint: disable=too-few-public-methods
        """Simple in-memory event bus stub used when real bus is absent."""

        _instance: t.ClassVar[_StubEventBus] | None = None
        event_emitted = Signal(str, dict)

        def __new__(cls, *args: t.Any, **kwargs: t.Any):  # noqa: D401
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

        # Public API parity with real bus
        def subscribe(self, topic: str, callback: t.Callable[[dict], None]) -> None:
            self.event_emitted.connect(lambda tpc, payload: callback(payload)
                                       if tpc == topic else None)

        def unsubscribe(self, topic: str, callback: t.Callable[[dict], None]) -> None:
            self.event_emitted.disconnect(callback)  # type: ignore[arg-type]

        def publish(self, topic: str, payload: dict) -> None:
            self.event_emitted.emit(topic, payload)

    EventBus = _StubEventBus  # type: ignore[assignment]

# --------------------------------------------------------------------------- #
# Logging config – can be overridden by root logger configuration at startup
# --------------------------------------------------------------------------- #
LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s :: %(message)s")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Typing helpers
# --------------------------------------------------------------------------- #
ViewModelT = t.TypeVar("ViewModelT", bound="ViewModelBase")


class ViewModelBase(QObject):
    """
    Minimal ViewModel contract to satisfy type checking.  The real implementation
    lives in ``flockdesk.shared.mvvm.viewmodel_base``.
    """

    data_changed = Signal()

    def dispose(self) -> None:  # noqa: D401 – convenience API
        """Free resources before the ViewModel goes out of scope."""
        LOGGER.debug("%s::dispose called – override in subclass", self.__class__.__name__)


# --------------------------------------------------------------------------- #
# Persisted state ADT
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ViewState:
    """Container persisted by :class:`QSettings`."""

    geometry: QByteArray | None = None
    custom: dict[str, t.Any] = field(default_factory=dict)

    def to_json(self) -> str:
        serialisable = {
            "geometry": bytes(self.geometry).hex() if self.geometry else None,
            "custom": self.custom,
        }
        return json.dumps(serialisable)

    @classmethod
    def from_json(cls, raw: str | None) -> "ViewState":
        if not raw:
            return cls()
        try:
            parsed = json.loads(raw)
            geometry = QByteArray.fromHex(
                parsed["geometry"].encode()) if parsed.get("geometry") else None
            return cls(geometry=geometry, custom=parsed.get("custom", {}))
        except Exception:  # pragma: no-cover – corrupted settings should not crash
            LOGGER.warning("Failed to parse persisted view state – resetting", exc_info=True)
            return cls()


# --------------------------------------------------------------------------- #
# Core ViewBase implementation
# --------------------------------------------------------------------------- #
class ViewBase(QWidget, t.Generic[ViewModelT]):
    """
    Base class for every Qt view in the MVVM layer.

    Responsibilities
    ----------------
        * Instantiate and own a ViewModel instance
        * Provide hook methods for UI composition & DM-binding
        * Manage event-bus registration / tear-down
        * Expose safe public API for plug-ins to attach behaviour
    """

    # Emitted right after UI has been constructed but before ViewModel is bound.
    ready = Signal()

    __settings_root = "FlockDesk"  # QSettings organisation identifier
    __settings_app = "Desktop"     # QSettings application identifier

    def __init__(
        self,
        view_id: str,
        view_model: ViewModelT,
        *,
        save_state: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """
        Parameters
        ----------
        view_id:
            Unique name used as key for persisted layout & user preferences.
        view_model:
            Concrete :class:`ViewModelBase` instance driving this view.
        save_state:
            Set *False* to opt-out of automatic QSettings persistence.
        """
        super().__init__(parent)
        self.setObjectName(view_id)
        self._vm: ViewModelT = view_model
        self._event_bus: EventBus = EventBus()
        self._save_state = save_state
        self._shortcuts: list[QShortcut] = []
        self._subscriptions: list[tuple[str, t.Callable[[dict], None]]] = []

        LOGGER.debug("Creating %s (id=%s)", self.__class__.__name__, view_id)

        # Phase 1 – Build the UI synchronously (must be implemented by subclass)
        self._construct_ui()

        # Phase 2 – Connect theme switcher & window state restore
        self._register_core_shortcuts()
        self._restore_state()

        # Phase 3 – Bind ViewModel & allow subclass to hook in
        self._bind_view_model(self._vm)

        # Phase 4 – All done – let the world know
        self.ready.emit()

    # --------------------------------------------------------------------- #
    #                      Abstract glaze for subclasses                    #
    # --------------------------------------------------------------------- #
    def _construct_ui(self) -> None:  # noqa: D401 – internal
        """Sub-classes must create widgets & layouts inside this method."""
        raise NotImplementedError

    def _bind_view_model(self, vm: ViewModelT) -> None:  # noqa: D401 – internal
        """Connect ViewModel signals to widgets. To be overriden."""
        raise NotImplementedError

    # --------------------------------------------------------------------- #
    #                       Persisted layout / settings                     #
    # --------------------------------------------------------------------- #
    @property
    def _settings(self) -> QSettings:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        return QSettings(self.__settings_root, self.__settings_app)

    def _setting_key(self) -> str:
        return f"views/{self.objectName()}"

    def _restore_state(self) -> None:
        """Restore geometry & custom state from QSettings."""
        if not self._save_state:
            LOGGER.debug("%s – state persistence disabled", self.objectName())
            return

        state = ViewState.from_json(self._settings.value(self._setting_key()))
        if state.geometry:
            LOGGER.debug("%s – restoring geometry", self.objectName())
            self.restoreGeometry(state.geometry)

        if custom := state.custom:
            LOGGER.debug("%s – restoring %d custom keys", self.objectName(), len(custom))
            self._on_state_restored(custom)

    def _save_state_to_settings(self) -> None:
        """Serialise current state back to QSettings."""
        if not self._save_state:
            return
        state = ViewState(
            geometry=self.saveGeometry(),
            custom=self._gather_custom_state(),
        )
        self._settings.setValue(self._setting_key(), state.to_json())
        self._settings.sync()
        LOGGER.debug("%s – state persisted", self.objectName())

    # Hooks for subclasses
    def _gather_custom_state(self) -> dict[str, t.Any]:  # noqa: D401
        """Return custom key/values to save in addition to window geometry."""
        return {}

    def _on_state_restored(self, custom_state: dict[str, t.Any]) -> None:  # noqa: D401
        """Called after window state has been restored."""
        # Default implementation does nothing; override in subclass if needed.

    # --------------------------------------------------------------------- #
    #                              Event Bus                                #
    # --------------------------------------------------------------------- #
    def subscribe(
        self,
        topic: str,
        callback: t.Callable[[dict], None],
        *,
        auto_dispose: bool = True,
    ) -> None:
        """
        Subscribe to global event bus topic.

        Setting ``auto_dispose`` ensures the subscription is revoked when the
        view is closed, preventing memory leaks.
        """
        self._event_bus.subscribe(topic, callback)
        if auto_dispose:
            self._subscriptions.append((topic, callback))
        LOGGER.debug("%s – subscribed to '%s'", self.objectName(), topic)

    def publish(self, topic: str, payload: dict | None = None) -> None:
        """Publish a message via the global event bus."""
        self._event_bus.publish(topic, payload or {})
        LOGGER.debug("%s – published event '%s'", self.objectName(), topic)

    # --------------------------------------------------------------------- #
    #                              Shortcuts                                #
    # --------------------------------------------------------------------- #
    def _register_core_shortcuts(self) -> None:
        """Adds universal shortcuts (theme toggle, inspector, …)."""
        # Toggle dark/light theme
        sc_theme = QShortcut(QKeySequence("Ctrl+`"), self, context=Qt.ApplicationShortcut)
        sc_theme.activated.connect(self._toggle_theme)  # type: ignore[arg-type]
        self._shortcuts.append(sc_theme)

    def register_shortcut(self, key_seq: str | QKeySequence, slot: t.Callable[[], None]) -> None:
        """
        Register additional keyboard shortcut that auto-cleans on view dispose.

        Example:
            self.register_shortcut("Ctrl+S", self._vm.save_current_document)
        """
        shortcut = QShortcut(QKeySequence(key_seq), self)
        shortcut.setContext(Qt.ApplicationShortcut)
        shortcut.activated.connect(slot)  # type: ignore[arg-type]
        self._shortcuts.append(shortcut)
        LOGGER.debug("%s – shortcut '%s' registered", self.objectName(), key_seq)

    @Slot()
    def _toggle_theme(self) -> None:
        """Flip between the configured dark/light theme."""
        self.publish("ui.theme.toggle")

    # --------------------------------------------------------------------- #
    #                       QWidget lifecycle overrides                      #
    # --------------------------------------------------------------------- #
    def closeEvent(self, event: QEvent) -> None:  # pylint: disable=signature-differs
        """Persist state & unsubscribe when window is closing."""
        try:
            self._save_state_to_settings()
        except Exception:  # pragma: no-cover – persistence errors are non-critical
            LOGGER.exception("Failed to persist state")

        # Clean-up shortcuts
        for sc in self._shortcuts:
            sc.deleteLater()

        # Unsubscribe from event bus
        for topic, cb in self._subscriptions:
            self._event_bus.unsubscribe(topic, cb)
            LOGGER.debug("%s – unsubscribed from '%s'", self.objectName(), topic)
        self._subscriptions.clear()

        # Dispose ViewModel
        try:
            self._vm.dispose()
        except Exception:  # pragma: no-cover
            LOGGER.exception("ViewModel dispose raised")

        super().closeEvent(event)

    # --------------------------------------------------------------------- #
    #                         Diagnostic helper API                         #
    # --------------------------------------------------------------------- #
    def dump_hierarchy(self, file: str | Path | None = None) -> None:
        """
        Writes Qt widget tree to *file* (or stdout) for debugging issues like
        focus handling, stylesheet propagation, etc.
        """
        dump = self._walk_tree(self)
        output = "\n".join(dump)
        if file:
            Path(file).expanduser().write_text(output, encoding="utf-8")
            LOGGER.info("Widget tree dumped to %s", file)
        else:
            print(output)  # noqa: T201

    @staticmethod
    def _walk_tree(root: QWidget, _depth: int = 0) -> list[str]:
        indent = " " * 2 * _depth
        info = f"{indent}{root.__class__.__name__}('{root.objectName()}')"
        out = [info]
        for child in root.children():
            if isinstance(child, QWidget):
                out.extend(ViewBase._walk_tree(child, _depth + 1))
        return out
```