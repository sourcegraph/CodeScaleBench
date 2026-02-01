```markdown
<!--
    FlockDesk – Social Workspace Orchestrator
    docs/guides/01_setup_guide.md
    ──────────────────────────────────────────────────────────────────────────
    Copyright © 2023-present
    SPDX-License-Identifier: MIT
-->

# FlockDesk Desktop – Setup Guide

Welcome to FlockDesk, the modular desktop suite that transforms ordinary
workstations into real-time social hubs.  
This guide walks you through installing **FlockDesk Desktop** from source,
bootstrapping the development environment, and verifying that each
micro-front-end service can be launched in isolation or orchestrated from the
core shell.

> NOTE: The instructions below target macOS, Windows 10/11, and modern Linux
> distributions (Fedora 37+, Ubuntu 22.04+, Arch). If you run into platform-
> specific issues, please file an issue or reach out in the `#setup-support`
> channel on the community Discord.

---

## 1 Prerequisites

| Requirement              | Version (min) | Check command            |
| ------------------------ | ------------- | ------------------------ |
| Git                      | 2.34          | `git --version`          |
| Python (CPython)         | 3.11.x        | `python3 --version`      |
| Poetry                   | 1.6           | `poetry --version`       |
| Node.js (for UI assets)  | 18 LTS        | `node --version`         |
| C/C++ build toolchain    | n/a           | see platform specifics   |

### 1.1 Platform specifics

macOS:
```shell
brew install cmake pkg-config openssl@3 sdl2
xcode-select --install   # if not already installed
```

Ubuntu:
```shell
sudo apt update && sudo apt install -y \
    build-essential cmake pkg-config libssl-dev \
    libsdl2-dev libgl1-mesa-dev libxcb-keysyms1-dev
```

Windows 10/11:  
Install *Visual Studio 2022 Community* with the “Desktop development with C++”
workload. Ensure `choco install cmake openssl` is in `PATH`.

---

## 2 Clone the repository

```shell
git clone --recurse-submodules https://github.com/flockdesk/desktop.git
cd desktop
```

> The **`--recurse-submodules`** flag is critical—FlockDesk pins sub-projects
> (plugins, the event bus, and UI component libraries) as Git submodules.

---

## 3 Bootstrapping with Poetry

1. Ensure the local Python is 3.11:  
   ```shell
   pyenv install 3.11.4        # or use your platform’s installer
   pyenv local 3.11.4
   ```
2. Install dependencies (this will also compile native extensions such as our
   high-performance diff/merge engine written in Rust):

   ```shell
   poetry install --with dev
   ```

3. Activate the virtual environment:

   ```shell
   poetry shell
   ```

All CLI snippets that follow assume the environment is activated. To exit, use
`exit` or `Ctrl-D`.

---

## 4 Building Qt resources & JavaScript bundles

FlockDesk uses the MVVM pattern on top of **Qt 6** (`PySide6`).  
JavaScript/TypeScript bundles (emoji picker, Monaco editor, etc.) live in
`ui/asset_pipeline`.

```shell
# Compile TS/SCSS → dist/
npm ci --prefix ui/asset_pipeline
npm run build --prefix ui/asset_pipeline

# Embed resources into a Qt .rcc file
python scripts/build_qt_resources.py
```

> Re-run the script whenever **SVGs**, **QSS**, or **JSON** localization files
> change. The resource compiler watches for mtime deltas to skip redundant work.

---

## 5 Running FlockDesk Desktop

### 5.1 Launch the orchestrator

```shell
python -m flockdesk
```

The orchestrator boots the event bus, discovers micro-front-ends via the plugin
registry (see [`flockdesk/plugins.yml`](../../flockdesk/plugins.yml)), and
spawns each service in its own Qt `QProcess`.

### 5.2 Hot-reloading a single micro-front-end

```shell
python -m flockdesk.chat --dev --reload
```

The `--reload` flag wires filesystem watchers to auto-restart the process on
source changes—handy for TDD loops.

---

## 6 Configuration & Profiles

Settings are persisted as **roaming profiles** backed by SQLite, syncable via
cloud providers (OneDrive, iCloud Drive, Dropbox). File layout:

```
~/FlockDesk/
└─ profiles/
   └─ <uuid4>/
      ├─ settings.sqlite3
      ├─ shortcuts.json
      └─ plugins/
```

Environment variable overrides:

| Variable                      | Purpose                                      | Example                    |
| ----------------------------- | -------------------------------------------- | -------------------------- |
| `FLOCKDESK_PROFILE`           | Force profile path                           | `/tmp/fd_profile`          |
| `FLOCKDESK_EVENTBUS_BACKEND`  | Pick bus backend (`ipc`, `zmq`, `nats`)      | `nats://localhost:4222`    |
| `FLOCKDESK_PLUGINS_DIR`       | Extra directory for side-loaded plugins      | `/opt/flockdesk/plugins`   |
| `SENTRY_DSN`                  | Crash reporting endpoint                     | _secret_                   |

---

## 7 Developing a Plugin

FlockDesk adopts a **Plugin-First** architecture. Each plugin is a standard
Python package that exposes an `entrypoints` hook:

```toml
# pyproject.toml (of your plugin)
[project.entry-points."flockdesk.plugins"]
music_room = "flockdesk_music_room:Plugin"
```

Minimal scaffold:

```python
# flockdesk_music_room/plugin.py
from __future__ import annotations

from flockdesk.api import BasePlugin, BusEvent

class Plugin(BasePlugin):
    """A jukebox where teammates can queue songs."""

    name = "Music Room 🎶"
    version = "0.1.0"
    author = "You"

    def on_load(self) -> None:
        # Subscribe to play/pause events
        self.bus.subscribe("music.toggle", self._on_toggle)

    def on_unload(self) -> None:
        # Persist queue to profile storage
        self.storage.save_json("queue.json", self._queue)

    def _on_toggle(self, event: BusEvent) -> None:
        self.player.toggle()
```

Install the plugin **editable** into the current env:

```shell
cd plugins/flockdesk_music_room
poetry install -n
flockdesk plugin reload   # or restart orchestrator
```

---

## 8 Testing

```shell
# Run unit tests and generate coverage HTML
pytest -q --cov=flockdesk --cov-report=html
python -m webbrowser htmlcov/index.html
```

Integration and contract tests live under `tests/integration`.  
They spin up a **headless** orchestrator using `pytest-qt` plus an
in-memory event bus stub to verify cross-service messaging.

---

## 9 Code Quality Gates

```shell
ruff check .
mypy --strict flockdesk/
pytest -q
```

CI (GitHub Actions) enforces:

* Ruff
* MyPy (strict)
* PyTest
* `poetry export --without-hashes` for deployable lockfiles

---

## 10 Distribution & Auto-Update

Local packaging uses **Briefcase** to produce signed installers for macOS
(.dmg), Windows (.msi), and AppImage on Linux.

```shell
briefcase create macOS
briefcase build macOS
briefcase run macOS
```

The **Auto-Update Pipeline** consumes the artifacts and publishes release
metadata to the CDN bucket referenced by `flockdesk.yml`.  
Clients poll the endpoint in the background and perform staged rollouts:

```yaml
update:
  channel: stable
  rollout:
    percentage: 10            # gradually increase to 100
    stagger_hours: 4
```

---

## 11 Troubleshooting

| Symptom                          | Resolution                                                          |
| -------------------------------- | ------------------------------------------------------------------- |
| Qt plugin “xcb” missing (Linux)  | `sudo apt install libxcb-* libxkbcommon-x11-0`                      |
| `ModuleNotFoundError: pyside6`   | Verify Poetry venv activated and `poetry install` succeeded         |
| Black screen after update        | Run with `--safe-mode` to disable third-party plugins               |
| Event bus port already in use    | Set `FLOCKDESK_EVENTBUS_PORT=0` to auto-allocate                    |

Generate a diagnostics bundle with:

```shell
flockdesk diagnostics --output ./diag.zip
```

Upload the bundle on the issue tracker or share it privately with a maintainer.

---

## 12 Next Steps

* Read the **Architecture Deep Dive** (`docs/architecture/overview.md`)
* Browse the **Command Pattern** implementations under `flockdesk/core/commands`
* Contribute to the **design system** at `ui/design_system`

Happy hacking, and welcome to the Flock! 🪶
```