```python
"""
flockdesk.core.theming.theme_manager
------------------------------------

Centralised run-time theme management for the FlockDesk desktop client.
The ThemeManager is responsible for

1. Discovering themes shipped with the client or provided by plugins.
2. Persisting the user’s preferred theme in QSettings.
3. Broadcasting a “theme.changed” event via the internal event-bus.
4. Applying QPalettes / QStylesheets to the running QApplication.
5. Hot-reloading theme files when they change on disk (optional).

The implementation purposely has zero hard dependencies on the rest of
FlockDesk apart from the (very small) event-bus contract, keeping the
module portable and easy to unit-test in isolation.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, MutableMapping, Optional, Protocol

from PySide6.QtCore import QObject, QSettings, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer as FSObserver

    WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover
    WATCHDOG_AVAILABLE = False

# ------------------------------------------------------------------------------
# Event-bus fallback stub
# ------------------------------------------------------------------------------

try:
    from flockdesk.core.events import Event, event_bus  # type: ignore
except Exception:  # pragma: no cover
    class Event:  # pylint: disable=too-few-public-methods
        """Tiny placeholder event."""

        def __init__(self, name: str, payload: Optional[dict] = None) -> None:
            self.name: str = name
            self.payload: dict = payload or {}

    class _DummyBus:  # pylint: disable=too-few-public-methods
        def publish(self, event: Event) -> None:  # noqa: D401
            logging.getLogger(__name__).debug("Event published: %s – %s", event.name, event.payload)

        def subscribe(self, *_a, **_kw) -> None:  # pragma: no cover
            pass

    event_bus = _DummyBus()  # type: ignore  # pylint: disable=invalid-name

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

_log = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Public Data-Structures
# ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Theme:
    """
    Immutable runtime representation of a desktop theme.
    """

    name: str
    palette: QPalette
    stylesheet: str = ""
    metadata: Dict[str, str] = None

    def __post_init__(self) -> None:  # pylint: disable=unused-private-member
        object.__setattr__(self, "metadata", self.metadata or {})


class ThemeProvider(Protocol):
    """
    Interface that any third-party theme provider must implement to
    integrate with the ThemeManager.
    """

    def themes(self) -> List[Theme]:  # noqa: D401
        """
        Return a list of Theme instances.
        """


# ------------------------------------------------------------------------------
# File-System based provider
# ------------------------------------------------------------------------------


class FileSystemThemeProvider(ThemeProvider):
    """
    Scans a directory for “*.qss” files to build Theme objects.

    Each theme may optionally ship a “<theme_name>.json” file sitting
    next to the QSS file which may contain additional metadata like:

        {
            "display_name": "Ocean Breeze",
            "author": "FlockDesk Design",
            "description": "Lightweight blue look & feel."
        }
    """

    def __init__(self, folder: os.PathLike, watch_changes: bool = True) -> None:
        self._path = Path(folder).expanduser().resolve()
        self._watch_changes = watch_changes and WATCHDOG_AVAILABLE
        self._themes: List[Theme] = []
        self._lock = threading.RLock()

        if not self._path.exists():
            _log.warning("Theme directory '%s' does not exist – creating.", self._path)
            self._path.mkdir(parents=True, exist_ok=True)

        self._scan()

        if self._watch_changes:
            self._start_watchdog()

    # ------------------------------------------------------------------ private

    def _scan(self) -> None:
        with self._lock:
            _log.debug("Scanning theme directory: %s", self._path)
            self._themes.clear()

            for qss_file in self._path.glob("*.qss"):
                try:
                    theme = self._build_theme_from_files(qss_file)
                    self._themes.append(theme)
                    _log.debug("Loaded theme '%s' from '%s'", theme.name, qss_file.name)
                except Exception as exc:  # pragma: no cover
                    _log.error("Failed to load theme file %s – %s", qss_file, exc, exc_info=True)

    def _build_theme_from_files(self, qss_path: Path) -> Theme:
        name = qss_path.stem
        stylesheet = qss_path.read_text(encoding="utf-8")

        metadata_path = qss_path.with_suffix(".json")
        metadata: MutableMapping[str, str] = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:  # pragma: no cover
                _log.warning("Malformed metadata file '%s': %s", metadata_path, exc)

        palette = self._infer_palette_from_metadata(metadata)

        return Theme(name=name, palette=palette, stylesheet=stylesheet, metadata=dict(metadata))

    @staticmethod
    def _infer_palette_from_metadata(metadata: MutableMapping[str, str]) -> QPalette:
        """
        Convert the user-provided metadata colour keys into a QPalette.
        Falls back to the QApplication’s current palette.
        """
        base_palette = QApplication.instance().palette()  # type: ignore[call-arg]

        # Graceful degradation if we’re running outside of a QApplication
        if base_palette is None:  # pragma: no cover
            base_palette = QPalette()

        # Simple mapping
        mapping = {
            "window": QPalette.Window,
            "window_text": QPalette.WindowText,
            "base": QPalette.Base,
            "text": QPalette.Text,
            "button": QPalette.Button,
            "button_text": QPalette.ButtonText,
            "highlight": QPalette.Highlight,
            "highlight_text": QPalette.HighlightedText,
        }

        for key, role in mapping.items():
            if (value := metadata.get(key)) is not None:
                base_palette.setColor(role, QColor(value))

        return base_palette

    def _start_watchdog(self) -> None:
        class _Watch(FileSystemEventHandler):  # pylint: disable=too-few-public-methods
            def __init__(self, outer: FileSystemThemeProvider) -> None:
                self._outer = outer

            def on_any_event(self, _event) -> None:  # noqa: D401
                _log.debug("Filesystem change detected in theme folder – refreshing.")
                self._outer._scan()  # pylint: disable=protected-access

        observer = FSObserver()
        observer.schedule(_Watch(self), str(self._path), recursive=False)
        observer.daemon = True
        observer.start()

    # ------------------------------------------------------------------ public

    def themes(self) -> List[Theme]:  # noqa: D401
        with self._lock:
            return list(self._themes)


# ------------------------------------------------------------------------------
# Theme Manager (Singleton via Borg pattern – easier unit tests)
# ------------------------------------------------------------------------------


class _ThemeManagerSignals(QObject):  # pylint: disable=too-few-public-methods
    theme_changed: Signal = Signal(str)  # emits theme-name


class ThemeManager:
    """
    Central theme registry + controller. Use `ThemeManager.instance()`
    to obtain the shared manager.

    Example
    -------
    >>> tm = ThemeManager.instance()
    >>> tm.apply_theme("DarkFusion")
    """

    _shared_state: dict = {}

    _SETTINGS_KEY = "ui/theme/name"
    _ORG_DOMAIN = "FlockDesk"
    _ORG_APP = "FlockDeskDesktop"

    # ----------------------------- construction / singleton --------------

    def __init__(self) -> None:
        self.__dict__ = self._shared_state  # Borg pattern
        if not hasattr(self, "_initialised"):  # first initialisation?
            self._providers: List[ThemeProvider] = []
            self._themes: Dict[str, Theme] = {}
            self._lock = threading.RLock()
            self._signals = _ThemeManagerSignals()
            self._current: Optional[Theme] = None

            self._settings = QSettings(self._ORG_DOMAIN, self._ORG_APP)
            self._initialised = True  # type: ignore[attr-defined]

    # ---------------------------------------------------------------- public

    @staticmethod
    def instance() -> "ThemeManager":  # noqa: D401
        return ThemeManager()

    # ---------------------------------------------------------------- signals

    def signals(self) -> _ThemeManagerSignals:
        return self._signals

    # ---------------------------------------------------------------- providers

    def register_provider(self, provider: ThemeProvider) -> None:
        _log.debug("Registering theme provider: %s", provider)
        with self._lock:
            self._providers.append(provider)
        self._refresh_themes()

    # ---------------------------------------------------------------- themes

    def available_themes(self) -> List[str]:  # noqa: D401
        with self._lock:
            return sorted(self._themes.keys())

    def current(self) -> Optional[str]:  # noqa: D401
        return self._current.name if self._current else None

    def theme(self, name: str) -> Optional[Theme]:  # noqa: D401
        with self._lock:
            return self._themes.get(name)

    # ---------------------------------------------------------------- io

    def apply_theme(self, name: str) -> None:
        """
        Apply the given theme to the QApplication and broadcast an event.

        Parameters
        ----------
        name:
            Symbolic theme name.
        """
        with self._lock:
            theme = self._themes.get(name)
            if theme is None:
                raise KeyError(f"Unknown theme: {name!r}")

            _log.info("Applying theme '%s'", name)
            self._do_apply(theme)
            self._current = theme

            # Persist selection
            self._settings.setValue(self._SETTINGS_KEY, name)

        # Notify listeners
        self._signals.theme_changed.emit(name)
        event_bus.publish(Event("ui.theme.changed", payload={"name": name}))

    # ---------------------------------------------------------------- internals

    def _do_apply(self, theme: Theme) -> None:
        app = QApplication.instance()  # type: ignore[call-arg]
        if app is None:
            _log.error("Cannot apply theme outside of a QApplication context.")
            return

        app.setPalette(theme.palette)
        app.setStyleSheet(theme.stylesheet)

    def _refresh_themes(self) -> None:
        _log.debug("Refreshing themes from %d providers", len(self._providers))
        with self._lock:
            self._themes.clear()
            for provider in self._providers:
                for theme in provider.themes():
                    if theme.name in self._themes:
                        _log.warning("Theme name collision: '%s' – provider %s", theme.name, provider)
                        continue
                    self._themes[theme.name] = theme

            _log.info("Registered %d themes: %s", len(self._themes), ", ".join(self._themes.keys()))

        # First run after startup?  Apply stored theme (falling back to default)
        if self._current is None:
            self._auto_apply_from_settings()

    def _auto_apply_from_settings(self) -> None:
        desired = self._settings.value(self._SETTINGS_KEY, type=str)
        if desired and desired in self._themes:
            try:
                self.apply_theme(desired)
            except Exception as exc:  # pragma: no cover
                _log.warning("Failed to apply stored theme '%s': %s", desired, exc, exc_info=True)
        elif self._themes:
            # Apply the first available theme as default
            first = next(iter(self._themes))
            self.apply_theme(first)

    # ---------------------------------------------------------------- context manager helpers (unit tests)

    def __enter__(self):  # noqa: D401, ANN001
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):  # noqa: D401, ANN001
        # Nothing to tear down for now
        return False


# ------------------------------------------------------------------------------
# Convenience API
# ------------------------------------------------------------------------------

def init_default_theme_provider() -> None:
    """
    Initialises a provider that looks into the default “themes” directory
    sitting next to the running Python file (../resources/themes).

    Should be called once during client bootstrap.
    """
    module_dir = Path(__file__).parent
    default_theme_dir = (module_dir / ".." / "resources" / "themes").resolve()

    provider = FileSystemThemeProvider(default_theme_dir, watch_changes=True)
    ThemeManager.instance().register_provider(provider)


# Automatically bootstrap when running inside a QApplication
if QApplication.instance() is not None:  # type: ignore[call-arg]
    init_default_theme_provider()
```