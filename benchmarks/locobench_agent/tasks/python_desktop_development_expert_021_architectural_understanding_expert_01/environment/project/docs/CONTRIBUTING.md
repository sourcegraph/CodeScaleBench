```markdown
<!--
  FlockDesk – Social Workspace Orchestrator
  docs/CONTRIBUTING.md

  Thank you for considering a contribution to FlockDesk!  
  This document contains everything you need to know to propose a change,
  from opening an issue to merging a pull-request.

  TL;DR
  -----
  1. Fork → branch → commit (conventional) → PR.
  2. Run `make pre-commit` before pushing.
  3. Add/update tests and docs.
  4. Keep UI work in sync with the Event-Bus contract.
-->

# Contributing to FlockDesk

FlockDesk thrives because of people like **you**.  
Whether you are fixing a one-character typo or designing an entirely new micro-UI, we welcome and value your contribution.

* [Code of Conduct](#code-of-conduct)
* [Quick Start](#quick-start)
* [Project Architecture](#project-architecture)
* [Development Workflow](#development-workflow)
* [Coding Guidelines](#coding-guidelines)
* [Commit Message Convention](#commit-message-convention)
* [Testing](#testing)
* [Plugin & Extension Guidelines](#plugin--extension-guidelines)
* [Event-Bus Contract](#event-bus-contract)
* [Documentation](#documentation)
* [Security & Responsible Disclosure](#security--responsible-disclosure)
* [Getting Help](#getting-help)

---

## Code of Conduct

We pledge to foster an open and inclusive environment.  
By participating in this project you agree to abide by the
[Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

---

## Quick Start

```bash
# 1. Fork the repository on GitHub
# 2. Clone your fork
git clone https://github.com/<your-user>/flockdesk.git
cd flockdesk

# 3. Bootstrap your development environment
make bootstrap       # installs Python toolchain, Qt dependencies, pre-commit, etc.

# 4. Activate the virtual environment
source .venv/bin/activate   # or `pipenv shell` if you prefer Pipenv

# 5. Run the desktop client in dev-mode
make run

# 6. Start writing code!
```

---

## Project Architecture

FlockDesk uses a **plugin-first**, **event-driven** design and is split into
independently deployable _micro front-ends_:

```
desktop_client/
├── core/            # Bootstrapper, update-manager, crash-guard
├── event_bus/       # ZeroMQ wrapper around internal protobuf schema
├── services/        # Presence, Storage, Telemetry, etc.
└── plugins/         # Chat, Whiteboard, Polls, etc. (dynamically loaded)
```

Each micro-UI runs in its own process, communicates _only_ via the
event bus, follows MVVM, and ships its own tests and docs.

---

## Development Workflow

1. **Open an issue** – Discuss your idea before investing time.
2. **Create a branch** – Use the pattern `feat/<scope>`, `fix/<scope>`, etc.
3. **Write code** – Keep commits small and focused.
4. **Run `make pre-commit`** – Auto-format, lint, type-check, unit-test.
5. **Push and open a PR** – Reference the issue and request reviewers.
6. **Respond to reviews** – Be patient, we’re all volunteers.
7. **Merge** – CI must be green; at least one approval required.

### Local Tooling

Target Python `3.11+`.

Tool        | Purpose                | Invocation
------------|------------------------|------------
Black       | Formatter              | `make fmt`
isort       | Import sorter          | part of `make fmt`
flake8      | Linting                | `make lint`
mypy        | Static typing          | `make type-check`
pytest      | Unit/integration tests | `make test`
tox         | Multi-env test matrix  | `make tox`
sphinx      | Docs generation        | `make docs`
pre-commit  | Git hooks bundle       | `make pre-commit`

---

## Coding Guidelines

* Follow **PEP 8** (Black keeps us compliant).
* Type-annotate all new functions (`mypy --strict` passes).
* One public class/function per file **unless** they are tightly coupled.
* Avoid cyclic imports; use the event-bus for cross-service messaging.
* Prefer composition over inheritance for UI view-models.
* Public APIs must raise domain-specific exceptions located in
  `flockdesk.exceptions`.
* Keep GUI code free of business logic—view-models own state & actions.
* For async tasks, prefer `asyncio` + `qasync` bridge instead of raw threads.
* All new or modified code paths require tests with ≥ 90 % coverage.

---

## Commit Message Convention

FlockDesk follows **Conventional Commits** + semantic versioning.

Format:
```
<type>(<scope>): <subject>

<body> (optional)
```

Type          | Meaning
--------------|------------------------------------------------
feat          | New user-facing functionality
fix           | Bug fix
perf          | Performance improvement
refactor      | Code change that neither fixes a bug nor adds a feature
docs          | Documentation only
test          | Adding or updating tests
build         | Changes to build, CI, or tooling
chore         | Other changes (maintenance, bump deps, etc.)
revert        | Revert to a previous commit

Examples:
```
feat(chat): add threaded replies
fix(presence): handle websocket reconnect loop
docs(plugins): clarify view-model lifecycle
```

---

## Testing

We use **pytest**; tests live next to the code under `tests/` siblings.

Guidelines:
* Prefer `pytest-qt`’s `qtbot` for GUI interactions.
* Mock network and file-system calls.
* Integration tests spin up an **in-memory** ZeroMQ bus via fixtures.
* End-to-end smoke tests live in `e2e/` and run nightly in the CI.
* Add regression tests for every bug you fix.

Run:

```bash
make test        # fast unit tests
make test-all    # full suite including GUI + e2e (≈ 5 min)
```

---

## Plugin & Extension Guidelines

Plugins are distributed as wheels that expose an
`flockdesk_plugin` entry-point:

```python
# setup.cfg
[options.entry_points]
flockdesk_plugin =
    polls = flockdesk_polls.plugin:PollsPlugin
```

Rules of thumb:

1. No side-effects on import.
2. Register **only** with the bus; never call other plugins directly.
3. Bundle migrations & default config under `resources/`.
4. Keep UI assets in `qrc` files for theme switching.
5. Use semantic versioning; FlockDesk’s update manager relies on it.

A sample template is located at `examples/polls-plugin/`.

---

## Event-Bus Contract

All inter-process communication flows through `event_bus/`:

* Protocol: **ZeroMQ PUB/SUB** with **Protocol Buffers** schema.
* Topics are case-kebab: `chat.posted`, `presence.updated`.
* Payloads MUST be defined in `*.proto` and compiled via `make protobuf`.
* Never break backward compatibility—introduce new fields with `optional`.
* Large blobs (e.g., file-transfers) go to object-storage; pass only IDs.

For contract changes, update:

1. `.proto` schema (additive).
2. Bus integration tests.
3. Changelog entry.

---

## Documentation

FlockDesk uses **reStructuredText** + **MyST-Markdown**.  
Docs auto-deploy to https://flockdesk.io/docs via GitHub Pages.

```bash
make docs            # build
make docs-live       # autoreload on change
```

Document **why**, not only **what**.  
Public functions/classes need doctrings in NumPy format.

---

## Security & Responsible Disclosure

If you discover a vulnerability:

1. **Do not open a public issue.**
2. Email security@flockdesk.io with the details.
3. We’ll respond within 48 hours and work with you on a fix.

We follow [disclosure best practices](https://github.com/ossf/oss-vulnerability-guide).

---

## Getting Help

Stuck? Have questions?

* Slack #contributors – quick feedback
* GitHub Discussions – design proposals
* Weekly open-source call – Thursdays 15:00 UTC

We are excited to collaborate.  
Happy hacking! 🐦
```