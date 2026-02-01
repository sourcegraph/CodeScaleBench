```markdown
# FlockDesk Plugin Development Guide
> File: `docs/guides/03_plugin_development.md`  
> Version: 1.1 • Last updated: 2024-03-31

Welcome to the **FlockDesk Plugin Development Guide**.  
This document walks you through everything you need to build, test, and distribute
a first-class plugin that integrates cleanly with the desktop client, respects
our sandboxing guarantees, and ships over the auto-update pipeline.

---

## 1. Architectural Primer

FlockDesk follows a **plugin-first** architecture:

* Each plugin is an *independently deployable* Python package.
* Plugins communicate with the **Event Bus** (an in-proc [pydispatch]-style hub).
* The **Plugin Manager** handles discovery, isolation, hot-loading, updates,
  crash-containment, and dependency resolution.
* UI widgets are rendered in a dedicated Qt `QWindow` and wired to the main
  docking system via *extension points*.

> **Important**  
> A malformed plugin can never crash the host.  
> All plugin code executes in a green-thread sandbox
> (via [`trio`]) with per-plugin exception fences.

---

## 2. Directory Layout

Every plugin lives in its own directory and must be a *proper* Python package:

```
pomodoro_timer/
└─ flockdesk_plugin.py      # Entry-point file (required)
└─ requirements.txt         # Optional runtime deps
└─ README.md                # Optional long description
└─ ui/                      # .ui or .qml files (optional)
└─ assets/                  # Icons, audio, etc.
```

---

## 3. Minimal Skeleton

Below is a **fully functional** skeleton that you can copy-paste and run.
The code purposefully demonstrates best practices—type hints, docstrings,
structured logging, context management, and graceful degradation.

```python
# flockdesk_plugin.py
"""
Pomodoro Timer — Example FlockDesk plugin.

Implements a simple 25/5 Pomodoro timer with a progress ring and desktop
notifications.  Demonstrates:
  • Event-Bus pub/sub
  • MVVM Qt widget
  • Keyboard shortcut registration
  • Settings persistence (Plugin KV-store)
"""

from __future__ import annotations

import logging
import pathlib
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from PySide6 import QtCore, QtGui, QtWidgets

# -- FlockDesk SDK -------------------------------------------------------------
# NOTE: These are provided by the host at runtime. Do *not* vendor-copy them.
from flockdesk.sdk.plugin import (
    BasePlugin,
    PluginContext,
    PluginInfo,
    Setting,
    SettingType,
)
from flockdesk.sdk.events import EventBus, Subscribe
from flockdesk.sdk.gui import DockPosition, register_panel
from flockdesk.sdk.shortcuts import shortcut
from flockdesk.sdk.exceptions import PluginValidationError

# -----------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _Constants:
    """Hard-coded constants for the Pomodoro cycle."""
    WORK_DURATION: Final[int] = 25  # minutes
    BREAK_DURATION: Final[int] = 5  # minutes
    TICK_INTERVAL_MS: Final[int] = 1_000  # 1 second


class PomodoroPlugin(BasePlugin):
    """
    Main plugin class.

    Life cycle:
        • __init__  – construction (no heavy work)
        • activate  – host loaded the plugin (allocate resources/UI)
        • deactivate– host unloading (release everything)
    """

    # --------------------------------------------------------------------- #
    # Metadata — mandatory attributes parsed by the Plugin Manager.         #
    # --------------------------------------------------------------------- #
    PLUGIN_INFO = PluginInfo(
        id="com.flockdesk.plugins.pomodoro_timer",
        name="Pomodoro Timer",
        description="A minimalist Pomodoro timer with progress ring and stats.",
        version="1.0.0",
        author="FlockDesk Community",
        homepage="https://flockdesk.app/plugins/pomodoro",
        license="MIT",
        min_host_version="0.9.0",
    )

    # Example settings surfaced in FlockDesk’s settings UI.
    SETTINGS = [
        Setting(
            key="work_duration",
            label="Work interval (minutes)",
            setting_type=SettingType.INTEGER,
            default=_Constants.WORK_DURATION,
            min_value=5,
            max_value=120,
        ),
        Setting(
            key="break_duration",
            label="Break interval (minutes)",
            setting_type=SettingType.INTEGER,
            default=_Constants.BREAK_DURATION,
            min_value=1,
            max_value=60,
        ),
        Setting(
            key="auto_start_next",
            label="Automatically start next interval",
            setting_type=SettingType.BOOLEAN,
            default=True,
        ),
    ]

    # --------------------------------------------------------------------- #
    # Init / Activate / Deactivate                                          #
    # --------------------------------------------------------------------- #
    def __init__(self, ctx: PluginContext) -> None:
        super().__init__(ctx)
        self._logger = logging.getLogger(self.PLUGIN_INFO.id)
        self._event_bus: EventBus = ctx.event_bus
        self._timer = QtCore.QTimer()
        self._elapsed_seconds = 0
        self._in_break = False
        self._ui: PomodoroWidget | None = None

        # Connect QTimer to tick handler.
        self._timer.timeout.connect(self._on_tick)

    # ­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­ #
    def activate(self) -> None:
        """Allocate UI and register event subscribers."""
        self._logger.debug("Activating Pomodoro Timer plugin")

        # Build the widget.
        self._ui = PomodoroWidget(self)
        register_panel(
            widget=self._ui,
            title="Pomodoro",
            dock_position=DockPosition.RIGHT,
            icon_path=str(_asset("tomato.svg")),
        )

        # Subscribe to global events.
        self._event_bus.subscribe("ui.theme.changed", self._on_theme_changed)
        self._logger.info("Pomodoro Timer plugin activated")

    # ­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­­ #
    def deactivate(self) -> None:
        """Clean up."""
        self._logger.debug("Deactivating Pomodoro Timer plugin")
        self._timer.stop()

        # Disconnect to avoid leaking handlers.
        self._event_bus.unsubscribe("ui.theme.changed", self._on_theme_changed)

        if self._ui:
            self._ui.deleteLater()
            self._ui = None

        self._logger.info("Pomodoro Timer plugin deactivated")

    # --------------------------------------------------------------------- #
    # UI Actions / Commands                                                 #
    # --------------------------------------------------------------------- #
    @shortcut("Ctrl+Alt+Shift+T", description="Start / Pause Pomodoro")
    def toggle_timer(self) -> None:
        """Start or pause the timer."""
        if self._timer.isActive():
            self._logger.debug("Pausing timer")
            self._timer.stop()
        else:
            self._logger.debug("Starting timer")
            self._timer.start(_Constants.TICK_INTERVAL_MS)

        if self._ui:
            self._ui.update_play_state(self._timer.isActive())

    def reset_timer(self) -> None:
        """Reset cycle to the beginning."""
        self._logger.debug("Resetting timer")
        self._timer.stop()
        self._elapsed_seconds = 0
        self._in_break = False
        if self._ui:
            self._ui.update_time_left(self._current_target())
            self._ui.update_cycle_state(self._in_break)

    # --------------------------------------------------------------------- #
    # Internal event handlers                                               #
    # --------------------------------------------------------------------- #
    def _on_tick(self) -> None:
        self._elapsed_seconds += 1
        remaining = self._current_target() - timedelta(seconds=self._elapsed_seconds)

        if self._ui:
            self._ui.update_time_left(remaining)

        if remaining.total_seconds() <= 0:
            self._logger.info(
                "Cycle finished (%s)",
                "break" if self._in_break else "work",
            )
            self._notify_cycle_complete()
            self._elapsed_seconds = 0
            self._in_break = not self._in_break
            if self._ui:
                self._ui.update_cycle_state(self._in_break)

            if self._context.settings.get_bool("auto_start_next"):
                self._logger.debug("Auto-starting next cycle")
                self._timer.start()
            else:
                self._timer.stop()

    @Subscribe(topic="ui.theme.changed")
    def _on_theme_changed(self, payload: dict) -> None:
        """Handle theme switch to re-tint our widget."""
        self._logger.debug("Theme changed: %s", payload)
        if self._ui:
            self._ui.refresh_theme(payload["name"])

    # --------------------------------------------------------------------- #
    # Utilities                                                             #
    # --------------------------------------------------------------------- #
    def _current_target(self) -> timedelta:
        minutes = (
            self._context.settings.get_int("break_duration")
            if self._in_break
            else self._context.settings.get_int("work_duration")
        )
        return timedelta(minutes=minutes)

    def _notify_cycle_complete(self) -> None:
        self._event_bus.publish(
            "notification.show",
            {
                "title": "Pomodoro",
                "message": "Break time!" if not self._in_break else "Back to work!",
                "icon": str(_asset("tomato.svg")),
            },
        )


# -----------------------------------------------------------------------------#
# Qt Widget — MVVM                                                             #
# -----------------------------------------------------------------------------#
class PomodoroWidget(QtWidgets.QFrame):
    """Simple Qt UI for the Pomodoro timer."""

    def __init__(self, plugin: PomodoroPlugin) -> None:
        super().__init__()
        self._plugin = plugin
        self._build_ui()
        self.setObjectName("PomodoroWidget")
        self.update_time_left(self._plugin._current_target())

    # ..................................................................... #
    def _build_ui(self) -> None:
        self.setLayout(QtWidgets.QVBoxLayout())

        # Remaining time label
        self._time_lbl = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        font = QtGui.QFont()
        font.setPointSize(32)
        self._time_lbl.setFont(font)
        self.layout().addWidget(self._time_lbl)

        # Buttons
        btn_row = QtWidgets.QHBoxLayout()
        self.layout().addLayout(btn_row)

        self._play_btn = QtWidgets.QPushButton("▶")
        self._play_btn.clicked.connect(self._plugin.toggle_timer)
        btn_row.addWidget(self._play_btn)

        reset_btn = QtWidgets.QPushButton("⟲")
        reset_btn.clicked.connect(self._plugin.reset_timer)
        btn_row.addWidget(reset_btn)

        self.layout().addStretch()

    # ..................................................................... #
    def update_time_left(self, remaining: timedelta) -> None:
        minutes, seconds = divmod(int(remaining.total_seconds()), 60)
        self._time_lbl.setText(f"{minutes:02d}:{seconds:02d}")

    def update_play_state(self, running: bool) -> None:
        self._play_btn.setText("⏸" if running else "▶")

    def update_cycle_state(self, in_break: bool) -> None:
        # Tint background depending on state
        palette = self.palette()
        role = QtGui.QPalette.Window
        color = QtGui.QColor("#2ecc71" if in_break else "#e74c3c")
        palette.setColor(role, color)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

    def refresh_theme(self, theme_name: str) -> None:
        # In this example we don’t do per-theme customization,
        # but here’s where you would re-load a .qss or adjust palette.
        pass


# -----------------------------------------------------------------------------#
# Helper utilities                                                             #
# -----------------------------------------------------------------------------#
def _asset(name: str) -> pathlib.Path:
    """Resolve asset path relative to this file."""
    return pathlib.Path(__file__).with_name("assets") / name


# -----------------------------------------------------------------------------#
# Entry-point check (optional)                                                 #
# -----------------------------------------------------------------------------#
if __name__ == "__main__":  # pragma: no cover
    # Allow launching plugin standalone for quick manual testing.
    import sys

    app = QtWidgets.QApplication(sys.argv)
    ctx = PluginContext.dummy()  # Provided by SDK for local debugging.
    plugin = PomodoroPlugin(ctx)
    plugin.activate()

    window = QtWidgets.QMainWindow()
    window.setCentralWidget(plugin._ui)  # type: ignore[arg-type]
    window.resize(300, 200)
    window.show()

    sys.exit(app.exec())
```

---

## 4. Packaging & Distribution

1. Create a `flockdesk_plugin.py` *or* expose a `flockdesk_plugin:Plugin` entry
   point in `pyproject.toml`:

   ```toml
   [project.entry-points."flockdesk.plugins"]
   pomodoro_timer = "pomodoro_timer.flockdesk_plugin:PomodoroPlugin"
   ```

2. Run `flockdesk plugin build .` to bundle your plugin.
3. Upload `%dist%/pomodoro_timer-1.0.0.fdesk` to the FlockDesk Plugin Portal.

---

## 5. Advanced Topics

* **Async bus** — For high-frequency data, rely on the async bus variant:
  `from flockdesk.sdk.events import AsyncEventBus`.
* **WebRTC** — Plugins can create peer-to-peer channels via `ctx.webrtc`.
* **IPC** — Long-running subprocesses must communicate through the
  [Zero-MQ]-backed IPC helper to keep the main UI responsive.

---

## 6. Testing

We recommend `pytest` + `pytest-qt`:

```python
def test_timer_starts(qtbot):
    ctx = PluginContext.dummy()
    plugin = PomodoroPlugin(ctx)
    plugin.activate()

    qtbot.mouseClick(plugin._ui._play_btn, QtCore.Qt.LeftButton)
    assert plugin._timer.isActive()
```

Use `flockdesk plugin test .` to run your suite inside the sandbox the same
way the marketplace CI does.

---

## 7. Versioning & API Stability

The public **SDK** follows semantic versioning (`MAJOR.MINOR.PATCH`).  
Breaking changes only occur on `MAJOR` bumps and are announced 60 days ahead
of time. Pin your dependency as:

```
flockdesk-sdk >=1.2,<2.0
```

---

## 8. Support

Stuck? Ping us in `#plugin-dev` on the FlockDesk Community Slack or open an
issue on <https://github.com/flockdesk/sdk/issues>.

---

## 9. Appendix: Common Pitfalls

1. **Spawning threads** without using the SDK’s `ThreadPool` leads to undefined
   behavior.  
2. **Heavy blocking** in the UI thread will freeze the entire workspace—always
   offload to the background runner.  
3. Always call `QTimer.stop()` in `deactivate()`.

Happy hacking! 🍅
```