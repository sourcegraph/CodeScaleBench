```python
"""
flockdesk.core.shell.layout_manager
-----------------------------------

A high-level service that orchestrates the life-cycle of user-defined window
layouts.  The manager is responsible for:

• Serialising / deserialising Qt-level geometry & state blobs
• Persisting layouts to disk under the active user’s profile directory
• Publishing event-bus notifications so that micro-front-ends can attach
  additional metadata to the currently applied layout
• Receiving and executing commands coming from plugins (Command Pattern)
• Performing defensive validation / version checks before restoring layouts

The public API is intentionally narrow—callers can *request* layout changes but
the manager owns all side-effects so that the overall desktop remains
consistent.

This implementation is Qt-aware but has no direct dependency on QWidget /
QMainWindow et al; those details are injected via call-backs to keep the module
unit-testable.

Author: FlockDesk Core Team
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QSettings, QTimer, Signal, Slot

try:
    # Optional dependency – at runtime the actual event-bus implementation will
    # be injected via the plugin system. This keeps the module importable during
    # headless unit tests.
    from flockdesk.common.event_bus import EventBus, ScopedSubscription
except ModuleNotFoundError:  # pragma: no cover – unit-test fallback
    class EventBus:  # type: ignore
        def publish(self, *_: object, **__: object) -> None: ...
        def subscribe(self, *_: object, **__: object) -> "ScopedSubscription": ...
        def unsubscribe(self, sub: "ScopedSubscription") -> None: ...

    class ScopedSubscription:  # type: ignore
        pass


__all__ = ["LayoutManager", "LayoutSnapshot"]

_LOG = logging.getLogger(__name__)

_LAYOUT_VERSION = 2  # increment whenever the serialization format changes


@dataclass(slots=True)
class LayoutSnapshot:
    """
    A pure-data representation of a FlockDesk desktop layout.

    geometry_blob:    str – base-64 or Qt binary data encoded as string
    dock_state_blob:  str – same, but for dock widgets
    plugin_payload:   arbitrary JSON-serialisable dict supplied by plugins
    timestamp:        ISO-8601 time of creation
    """
    geometry_blob: str
    dock_state_blob: str
    plugin_payload: Dict[str, dict] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    version: int = field(default=_LAYOUT_VERSION)

    @classmethod
    def from_json(cls, raw: str) -> "LayoutSnapshot":
        """Reconstitute from a JSON string, performing minimal validation."""
        data = json.loads(raw)
        if data.get("version") != _LAYOUT_VERSION:
            _LOG.warning(
                "Layout version mismatch – expected %s, got %s. "
                "Attempting best-effort restore.",
                _LAYOUT_VERSION,
                data.get("version"),
            )
        return cls(
            geometry_blob=data["geometry_blob"],
            dock_state_blob=data["dock_state_blob"],
            plugin_payload=data.get("plugin_payload", {}),
            timestamp=data.get("timestamp", datetime.utcnow().isoformat()),
            version=data.get("version", 0),
        )

    def to_json(self, pretty: bool = False) -> str:
        opts = {"indent": 2, "sort_keys": True} if pretty else {}
        return json.dumps(asdict(self), **opts)


class LayoutPersistenceError(RuntimeError):
    """Raised when a layout file cannot be read or written."""


class LayoutManager(QObject):
    """
    The *single* instance responsible for persisting and restoring desktop
    layouts.  Thread-safe and re-entrant by design—UI calls happen in the Qt
    main-thread whilst disk I/O occurs in a background worker.
    """

    # Emitted *after* a layout has been applied to Qt widgets
    layout_applied: Signal = Signal(LayoutSnapshot)

    # Emitted when a new layout is persisted to disk
    layout_saved: Signal = Signal(str)  # path

    #: Event-bus topics
    EVT_PLUGIN_ATTACH = "layout.plugin_attach_request"
    EVT_SHELL_APPLY = "shell.apply_layout"

    def __init__(
        self,
        *,
        settings: Optional[QSettings] = None,
        event_bus: Optional[EventBus] = None,
        user_profile_dir: Optional[Path] = None,
        geometry_provider: Callable[[], bytes],
        geometry_consumer: Callable[[bytes], None],
        dock_state_provider: Callable[[], bytes],
        dock_state_consumer: Callable[[bytes], None],
        parent: Optional[QObject] = None,
    ) -> None:
        """
        geometry_provider      returns Qt saveGeometry() bytes
        geometry_consumer      takes bytes and restores via restoreGeometry()
        dock_state_provider    returns Qt saveState() bytes
        dock_state_consumer    takes bytes and restores via restoreState()
        """
        super().__init__(parent)

        self._settings = settings or QSettings()
        self._event_bus = event_bus or EventBus()
        self._profile_dir = user_profile_dir or Path(
            self._settings.value("general/userProfileDir", Path.home() / ".flockdesk")
        )
        self._profile_dir.mkdir(exist_ok=True, parents=True)

        self._geometry_provider = geometry_provider
        self._geometry_consumer = dock_state_consumer  # type: ignore
        self._dock_state_provider = dock_state_provider
        self._dock_state_consumer = dock_state_consumer

        self._io_lock = threading.RLock()
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._sync_debounced)

        # Wire up the event bus
        self._subscriptions: List[ScopedSubscription] = [
            self._event_bus.subscribe(self.EVT_PLUGIN_ATTACH, self._on_plugin_attach),
            self._event_bus.subscribe(self.EVT_SHELL_APPLY, self._on_external_apply),
        ]

    # --------------------------------------------------------------------- I/O

    def _layout_file(self, name: str) -> Path:
        return self._profile_dir / f"{name}.layout.json"

    def _write_snapshot(self, name: str, snap: LayoutSnapshot) -> None:
        """Thread-safe persistence helper."""
        with self._io_lock:
            target = self._layout_file(name)
            try:
                target.write_text(snap.to_json(pretty=True), encoding="utf-8")
            except OSError as exc:
                raise LayoutPersistenceError(
                    f"Cannot write layout '{name}' → {target}: {exc}"
                ) from exc
            _LOG.debug("Saved layout '%s' to %s", name, target)
            self.layout_saved.emit(str(target))

    def _read_snapshot(self, name: str) -> Optional[LayoutSnapshot]:
        with self._io_lock:
            target = self._layout_file(name)
            if not target.exists():
                _LOG.debug("No layout file at %s", target)
                return None
            try:
                return LayoutSnapshot.from_json(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LayoutPersistenceError(
                    f"Cannot read layout '{name}' from {target}: {exc}"
                ) from exc

    # ------------------------------------------------------------ Public API

    def save_layout(self, name: str, debounce_ms: int = 500) -> None:
        """
        Capture the current Qt layout and persist it under *name*.

        The operation is debounced because widgets may emit a burst of geometry
        events while the user is dragging panes around.
        """
        self._pending_save_name = name
        self._debounce_timer.start(debounce_ms)

    def apply_layout(self, name: str) -> None:
        """
        Restore widgets to the geometry recorded under *name*.

        The call returns immediately but the actual restore will occur in the
        Qt main-thread to avoid cross-thread event dispatch.
        """
        snap = self._read_snapshot(name)
        if not snap:
            _LOG.warning("Requested layout '%s' does not exist – ignoring", name)
            return

        _LOG.info("Applying layout '%s' captured on %s", name, snap.timestamp)
        self._restore_snapshot(snap)

    def list_available_layouts(self) -> List[str]:
        """Return layout names found in the active profile directory."""
        return sorted(p.stem for p in self._profile_dir.glob("*.layout.json"))

    # ---------------------------------------------------------------- Events

    def _on_plugin_attach(self, event: dict) -> None:
        """
        Plugins may ask the shell to attach extra data to the *next* snapshot
        that will be saved.  The event payload:

        {
            "layout_name": "default",
            "plugin_id": "whiteboard",
            "payload": { ... arbitrary json ... }
        }
        """
        _LOG.debug("Plugin attach request received: %s", event)
        layout_name = event.get("layout_name")
        plugin_id = event.get("plugin_id")
        payload = event.get("payload", {})

        snap = self._read_snapshot(layout_name)
        if not snap:
            _LOG.warning("Trying to attach to non-existing layout '%s'", layout_name)
            return

        snap.plugin_payload[plugin_id] = payload
        _LOG.info("Attaching plugin payload for '%s' to layout '%s'", plugin_id, layout_name)
        self._write_snapshot(layout_name, snap)

    def _on_external_apply(self, event: dict) -> None:
        """
        Another component (e.g. settings dialog) requested to apply a layout.
        """
        layout_name = event.get("layout_name")
        if layout_name:
            self.apply_layout(layout_name)

    # ----------------------------------------------------------- Internals

    def _sync_debounced(self) -> None:
        """Actual write to disk after debounce interval."""
        name = getattr(self, "_pending_save_name", None)
        if not name:
            return

        snap = LayoutSnapshot(
            geometry_blob=self._geometry_provider().hex(),
            dock_state_blob=self._dock_state_provider().hex(),
        )
        _LOG.debug("Captured snapshot for layout '%s': %s", name, snap)
        self._write_snapshot(name, snap)

        # Broadcast so plugins can attach their own payload asynchronously
        self._event_bus.publish(
            "layout.snapshot_captured",
            {"layout_name": name, "timestamp": snap.timestamp},
        )

    def _restore_snapshot(self, snap: LayoutSnapshot) -> None:
        """
        Perform the Qt restore calls and notify interested parties.
        This function **must** execute in the Qt main-thread.
        """
        # Defensive checks – blobs may be corrupt
        try:
            self._geometry_consumer(bytes.fromhex(snap.geometry_blob))
            self._dock_state_consumer(bytes.fromhex(snap.dock_state_blob))
        except Exception as exc:  # pragma: no cover
            _LOG.exception("Failed to restore layout: %s", exc)
            return

        # Let plugins know so they can re-hydrate their state
        self._event_bus.publish(
            "layout.applied",
            {
                "timestamp": snap.timestamp,
                "plugin_payload": snap.plugin_payload,
            },
        )
        self.layout_applied.emit(snap)

    # -------------------------------------------------------------- Cleanup

    def dispose(self) -> None:
        """Gracefully unsubscribe from the event-bus (idempotent)."""
        for sub in self._subscriptions:
            self._event_bus.unsubscribe(sub)
        self._subscriptions.clear()

    def __del__(self) -> None:  # noqa: D401
        # QObject.__del__ might be called *after* QApplication is gone; guard
        # against delayed finalisation issues.
        try:
            self.dispose()
        except Exception:  # pragma: no cover
            pass
```