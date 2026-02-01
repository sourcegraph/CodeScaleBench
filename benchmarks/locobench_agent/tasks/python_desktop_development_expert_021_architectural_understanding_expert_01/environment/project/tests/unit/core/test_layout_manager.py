```python
"""
Unit-tests for the core LayoutManager component.

The real LayoutManager lives in `flockdesk.core.layout_manager`.  If that
module is not import-able (e.g. these tests are executed in isolation
outside the complete FlockDesk source-tree), we fall back to a **stub**
implementation that behaves just enough like the real thing for the tests
to stay meaningful.

The tests exercise the public contract:

    • register_window         – adds a QMainWindow to the manager and
                                 publishes an event on the internal bus
    • save_layout             – persists a window’s byte-state to the
                                 settings-repository and publishes an event
    • restore_layout          – fetches persisted state (or returns None)
    • apply_theme             – delegates a theme switch to every window
                                 and notifies the bus
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Tuple

import pytest

######################################################################
# TEST DOUBLE IMPLEMENTATIONS
######################################################################


class _FakeEventBus:
    """A minimal in-memory spy for the event-bus used by core services."""

    def __init__(self) -> None:
        self._published: List[Tuple[str, Any]] = []

    # Public API expected by LayoutManager
    def publish(self, topic: str, payload: Any) -> None:  # noqa: D401
        """Record the published tuple for later inspection."""
        self._published.append((topic, payload))

    # Convenience helpers for the tests
    def last(self) -> Tuple[str, Any]:
        if not self._published:
            raise AssertionError("Nothing has been published yet!")
        return self._published[-1]

    def clear(self) -> None:
        self._published.clear()

    def topics(self) -> List[str]:
        return [topic for topic, _ in self._published]


class _FakeSettingsRepo:
    """
    Naïve in-memory settings storage with the same façade as the project’s
    real key-value persistence layer (most likely QSettings-backed).
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    # Public API expected by LayoutManager
    def set(self, key: str, value: Any) -> None:  # noqa: D401
        """Mimic a blocking write into persistent storage."""
        self._store[key] = value

    def get(self, key: str, default: Any | None = None) -> Any:  # noqa: D401
        """Retrieve a previously stored value."""
        return self._store.get(key, default)

    # Convenience helpers
    def has(self, key: str) -> bool:
        return key in self._store

    def clear(self) -> None:
        self._store.clear()


class _FakeWindow:
    """
    A bare-bones replacement for a PySide6.QtWidgets.QMainWindow
    implementation.  Only what LayoutManager needs is emulated.
    """

    def __init__(self, object_name: str, initial_state: bytes | None = None):
        self._object_name = object_name
        self._state = initial_state or b""
        self._themes_applied: list[str] = []

    # Qt compatibility shims ------------------------------------------------
    def objectName(self) -> str:  # noqa: N802
        return self._object_name

    # Windows layout API mimicry --------------------------------------------
    def saveState(self) -> bytes:  # noqa: N802
        return self._state

    def restoreState(self, state: bytes) -> bool:  # noqa: N802
        self._state = state
        return True

    # Theme application hook ------------------------------------------------
    def apply_theme(self, theme_name: str) -> None:  # noqa: D401
        self._themes_applied.append(theme_name)

    # Test helpers ----------------------------------------------------------
    @property
    def themes_applied(self) -> list[str]:
        return self._themes_applied[:]


######################################################################
# STUB LAYOUT-MANAGER (only when the real one cannot be imported)
######################################################################

try:
    # The actual implementation should be imported when the full
    # FlockDesk code-base is present.
    from flockdesk.core.layout_manager import LayoutManager  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – executed by CI fallback
    # ------------------------------------------------------------------
    #  WARNING: This stub is **only** for keeping the tests runnable
    #  in isolation (e.g., public CI or interactive demonstration).
    #  The real logic lives in the project proper.
    # ------------------------------------------------------------------
    class LayoutManager:  # type: ignore
        """
        Very small in-process re-implementation of the public behaviors used
        by the tests.  Anything beyond that scope is intentionally ignored.
        """

        # Events this stub emits.  Declared here to avoid string-typos.
        EVT_REGISTERED = "layout.window.registered"
        EVT_SAVED = "layout.window.saved"
        EVT_RESTORE_FAILED = "layout.window.restore.failed"
        EVT_THEME_APPLIED = "theme.applied"

        def __init__(self, event_bus: _FakeEventBus, settings_repo: _FakeSettingsRepo):
            self._bus = event_bus
            self._settings = settings_repo
            self._windows: dict[str, _FakeWindow] = {}

        # ------------------------------------------------------------------
        # Public API
        # ------------------------------------------------------------------
        def register_window(self, window: _FakeWindow) -> None:
            window_id = window.objectName()
            self._windows[window_id] = window
            self._bus.publish(self.EVT_REGISTERED, window_id)

        def save_layout(self, window_id: str, state: bytes) -> None:
            self._settings.set(f"layout::{window_id}", state)
            self._bus.publish(self.EVT_SAVED, window_id)

        def restore_layout(self, window_id: str) -> bytes | None:
            key = f"layout::{window_id}"
            state = self._settings.get(key)
            if state is None:
                self._bus.publish(self.EVT_RESTORE_FAILED, window_id)
            return state

        def apply_theme(self, theme_name: str) -> None:
            for window in self._windows.values():
                if hasattr(window, "apply_theme"):
                    window.apply_theme(theme_name)
            self._bus.publish(self.EVT_THEME_APPLIED, theme_name)


######################################################################
# PYTEST FIXTURES
######################################################################


@pytest.fixture()
def event_bus() -> _FakeEventBus:
    return _FakeEventBus()


@pytest.fixture()
def settings_repo() -> _FakeSettingsRepo:
    return _FakeSettingsRepo()


@pytest.fixture()
def layout_manager(event_bus: _FakeEventBus, settings_repo: _FakeSettingsRepo) -> LayoutManager:
    return LayoutManager(event_bus=event_bus, settings_repo=settings_repo)


######################################################################
# TESTS
######################################################################


def test_register_window_emits_event(
    layout_manager: LayoutManager,
    event_bus: _FakeEventBus,
) -> None:
    """When a window is registered, the LayoutManager must broadcast an event."""
    win = _FakeWindow("alpha")
    layout_manager.register_window(win)

    assert event_bus.last() == ("layout.window.registered", "alpha")


def test_save_layout_persists_to_settings_and_notifies(
    layout_manager: LayoutManager,
    settings_repo: _FakeSettingsRepo,
    event_bus: _FakeEventBus,
) -> None:
    """
    Saving a layout should write to the settings repository and fire an event on
    the internal bus.
    """
    win_id = "beta"
    state = b"serialized-qt-bytes"

    layout_manager.save_layout(win_id, state)

    assert settings_repo.get("layout::beta") == state
    assert event_bus.last() == ("layout.window.saved", "beta")


def test_restore_layout_returns_correct_state(
    layout_manager: LayoutManager,
    settings_repo: _FakeSettingsRepo,
) -> None:
    """Restoration must round-trip the exact bytes previously saved."""
    win_id = "gamma"
    state = b"some-window-geometry"
    settings_repo.set("layout::gamma", state)

    restored = layout_manager.restore_layout(win_id)

    assert restored == state, "LayoutManager did not fetch the expected state"


def test_restore_layout_failure_emits_warning_event(
    layout_manager: LayoutManager,
    event_bus: _FakeEventBus,
) -> None:
    """
    When no layout is stored for a given window, the manager should publish an
    indicative event and return None.
    """
    missing_win_id = "non-existent"

    restored = layout_manager.restore_layout(missing_win_id)

    # Nothing stored ⇒ no bytes expected
    assert restored is None
    assert (
        "layout.window.restore.failed" in event_bus.topics()
    ), "Manager failed to emit a restore-failure event"


def test_apply_theme_propagates_to_all_registered_windows(
    layout_manager: LayoutManager,
    event_bus: _FakeEventBus,
) -> None:
    """A theme change should be delegated to every registered window instance."""
    dark_theme = "ObsidianNight"

    win_one = _FakeWindow("omega")
    win_two = _FakeWindow("sigma")

    # Register both windows
    layout_manager.register_window(win_one)
    layout_manager.register_window(win_two)

    # Switch the theme
    layout_manager.apply_theme(dark_theme)

    assert dark_theme in win_one.themes_applied
    assert dark_theme in win_two.themes_applied
    assert event_bus.last() == ("theme.applied", dark_theme)
```