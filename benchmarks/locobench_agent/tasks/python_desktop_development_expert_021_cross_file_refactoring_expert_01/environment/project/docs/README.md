```markdown
# FlockDesk – Social Workspace Orchestrator  
_Desktop micro-front-ends for next-level collaboration_

[![Build Status](https://github.com/flockdesk/flockdesk/actions/workflows/ci.yaml/badge.svg)](https://github.com/flockdesk/flockdesk/actions)  
[![Code Style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)  
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)  
[![PyPI version](https://img.shields.io/pypi/v/flockdesk.svg)](https://pypi.org/project/flockdesk)  

> FlockDesk turns everyday workstations into collaborative social hubs by composing independent desktop micro-front-ends—chat, whiteboard, co-editing, presence, dashboards—into a unified, event-driven workspace.

---

## ⭐ Key Capabilities
- **Plugin-first architecture** enabling drag-and-drop extensions at runtime  
- **Isolated micro-UIs** (services) sandboxed into individual processes  
- **Event-bus messaging** for fault-tolerant inter-service communication  
- **Qt/PySide6 MVVM GUI** with multi-window docking, theme toggling, & state roaming  
- **Hot-swappable updates** delivered via auto-update pipelines  
- **Crash-reporting core** funneling diagnostics to Sentry without killing the session  

---

## 🌐 Architecture at a Glance

```text
┌──────────┐     IPC/Event Bus     ┌──────────────┐
│ Chat MFE │ ◀────────┬──────────► │ Whiteboard   │
└──────────┘          │            │   MFE        │
                      │            └──────────────┘
                      │
                 ┌────▼─────┐
                 │  Core    │
                 │ Orchestr │
                 │  ator    │
                 └────┬─────┘
                      │
           ┌──────────▼─────────┐
           │ Plugin Supervisor  │
           └──────────┬─────────┘
                      │
          ┌───────────▼────────────┐
          │  3rd-Party Extensions   │
          └─────────────────────────┘
```

*Each Micro-Front-End (MFE) is a separate Python entry-point that boots a Qt window. The **Core Orchestrator** maintains user sessions, settings, and service discovery while forwarding domain events across the **IPC Event Bus** (ZeroMQ). Plugins register capabilities, UI panes, and domain commands through a declarative manifest.*

---

## 🚀 Quick Start

1. **Install with pip (system Python ≥ 3.10)**  
   ```bash
   pip install flockdesk
   ```

2. **Launch the orchestrator**  
   ```bash
   flockdesk
   ```

3. **Hot-load a plugin**  
   Drag `music-room.flockplug` onto any FlockDesk window or run:  
   ```bash
   flockdesk plugin install music-room.flockplug
   ```

---

## 🛠️ Building From Source

```bash
git clone https://github.com/flockdesk/flockdesk.git
cd flockdesk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,qt]"
pre-commit install              # enforce code style
invoke build                    # run linters, mypy, tests
invoke run                      # start orchestrator in dev-mode
```

`invoke` tasks are defined in `tasks.py` for CI parity. `invoke dev` launches the orchestrator with live-reload for MFEs.

---

## 🧩 Writing Your First Plugin

```python
# music_room/plugin.py
from flockdesk.sdk import (
    PluginBase,
    pane,
    command,
    event_handler,
    bus,
)

class MusicRoom(PluginBase):
    name = "Music Room"
    version = "0.1.0"
    description = "Co-listen to tracks together"
    author = "You <you@example.com>"

    @pane(title="Music Room", icon="🎵")
    def main_pane(self):
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
        root = QWidget()
        layout = QVBoxLayout(root)
        play_btn = QPushButton("Play")
        layout.addWidget(play_btn)
        return root

    @command("music.play")
    def play_song(self, song_id: str) -> None:
        bus.emit("music.started", song_id=song_id)

    @event_handler("presence.joined")
    def greet(self, *, user_id: str):
        self.toast(f"👋 {user_id} joined the Music Room")
```

Package it:  
```bash
flockdesk plugin pack music_room --output music-room.flockplug
```

Drag-and-drop the resulting file into FlockDesk or install via CLI.

---

## 🧭 Command-Line Interface

```bash
flockdesk --help
Usage: flockdesk [OPTIONS] COMMAND [ARGS]...

Commands:
  run              Start FlockDesk orchestrator
  plugin           Manage plugins (install/list/remove/pack)
  settings         Inspect or modify user settings
  doctor           Diagnostic utility
```

---

## 🧪 Testing & Quality

- **Unit tests** – `pytest`, coverage enforced at 90 %  
- **Static typing** – `mypy`, `pydantic` models for configs  
- **Linting** – `black`, `ruff`, `isort`, `flake8-comprehensions`  
- **CI/CD** – GitHub Actions (`.github/workflows/ci.yml`) triggers on push & PR  

Run locally:  
```bash
pytest -q
```

---

## 📝 Configuration

Files are stored in `${XDG_CONFIG_HOME:-~/.config}/flockdesk` and synced to the cloud via optional OAuth login.

```toml
[ui]
theme = "auto"
docked_panels = ["chat", "presence", "whiteboard"]

[keyboard]
"Ctrl+Shift+P" = "open-command-palette"
```

---

## 🤝 Contributing

1. Fork → feature branch → PR  
2. Ensure `invoke build` passes  
3. Add unit tests & docstrings  
4. Adhere to [Conventional Commits](https://www.conventionalcommits.org)

Join the discussion in `#flockdesk-dev` on Matrix!

---

## 📅 Roadmap

- [ ] End-to-end encryption for private chats  
- [ ] Native Wayland rendering backend  
- [ ] ARM64 Windows cross-builds  
- [ ] Collaborative code review plugin (PR sync)

---

## 📜 License

FlockDesk is released under the MIT License (see [`LICENSE`](../LICENSE)).  
© 2023–Present FlockDesk Contributors
```