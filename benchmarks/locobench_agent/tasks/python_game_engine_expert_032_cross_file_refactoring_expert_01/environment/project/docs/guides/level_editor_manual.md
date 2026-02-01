```markdown
<!--
  LedgerQuest Engine – Level-Editor Manual
  =======================================
  File: docs/guides/level_editor_manual.md
  Last-Updated: 2024-05-06
  ---------------------------------------------------------------------------
  This document ships with the LedgerQuest Engine and is intended for
  designers, developers, and DevOps engineers who need to create, test, and
  ship interactive business levels (e.g. sales simulations, supply-chain
  games, financial-literacy quests) without touching infrastructure.

  All examples assume:
    • Python ≥ 3.10
    • LedgerQuest Engine ≥ 2.1
    • AWS CLI with a default profile bound to the correct account
    • Node ≥ 18, if you plan to extend the React-based UI shell

  Tip: To report a typo or request clarifications, create a GitHub issue with
  the `docs/level-editor` label. We release documentation patches weekly.
-->

# Table of Contents
1. [What Is the LedgerQuest Level Editor?](#what-is-the-ledgerquest-level-editor)
2. [Installation](#installation)
3. [Launching the Editor](#launching-the-editor)
4. [Anatomy of the UI](#anatomy-of-the-ui)
5. [Creating Your First Scene](#creating-your-first-scene)
6. [Python Scripting 101](#python-scripting-101)
7. [Serverless Persistence](#serverless-persistence)
8. [Testing & Continuous Integration](#testing--continuous-integration)
9. [Advanced Topics](#advanced-topics)
10. [Troubleshooting](#troubleshooting)
11. [Glossary](#glossary)
12. [Changelog](#changelog)

---

## What Is the LedgerQuest Level Editor?
The Level Editor is a thin desktop and web hybrid that lets you author scenes,
entities, and game‐logic without running a monolithic server.  
Under the hood, each editor action *dispatches an immutable event* to AWS
EventBridge, which in turn fires Lambda functions that mutate DynamoDB or warm
Fargate-based GPU containers.  
Because every change is event-sourced, you get **auditability**
and **time-travel debugging** out of the box.

Key capabilities:

| Feature | Description                           |
|---------|---------------------------------------|
| ECS Graph | Visual drag-and-drop entity/component system |
| StepFn Preview | Render the Step Functions flow behind your scene |
| Multi-Tenant | All editor calls are namespaced by an `OrganisationId` |
| Hot-Reload | Zero-downtime Lambda + WebSocket push updates |
| Git-Like Branching | Branch/merge scenes via the `ledgerquest-scm` command |

---

## Installation
### Via `pip` (recommended)
```bash
python -m venv .venv
source .venv/bin/activate         # On Windows: .venv\Scripts\activate
pip install ledgerquest-engine[editor]
```

### Build from source
```bash
git clone https://github.com/ledgerquest/engine.git
cd engine
make init && make editor
```

### Verify
```bash
lq-editor --version
# LedgerQuest Level Editor v2.1.0 (build abc1234)
```

---

## Launching the Editor
You can run the editor as a standalone **Electron** app or open the
server-rendered web edition in the browser.

### Electron (desktop)
```bash
lq-editor
```

### Web (serverless)
```bash
lq-editor serve --port 5173
open http://localhost:5173
```

> Note: The web version proxies asset uploads directly to S3 via
> pre-signed URLs, so your IAM user must have `s3:PutObject` permissions.

Environment Variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `LEDGERQUEST_STAGE` | `dev` | Which AWS stack to talk to |
| `LEDGERQUEST_ORG_ID` | `demo` | Tenant ID, used for row-level security |

---

## Anatomy of the UI
```
┌──────────────────────────────────────────────────────────────┐
│ Toolbar  ▸  File  Edit  View  Tools  Play  AWS (✓)  Help     │
├──────┬───────────────────────────┬───────────────────────────┤
│Hierarchy│   Scene View (WebGL)   │     Property Inspector    │
│ (Tree) │                         │  (JSON + Form Overlay)    │
├──────┴───────────────────────────┴───────────────────────────┤
│                   Console (WebSocket)                        │
└──────────────────────────────────────────────────────────────┘
```

1. **Hierarchy Panel**  
   Lists every entity by `EntityId`, grouped by Unity-style tags but
   powered by an ECS filter query (`ComponentMask`).

2. **Scene View**  
   Live GPU canvas rendered by a headless Fargate batch when
   *Hardware Acceleration* is enabled, else by browser WebGL.

3. **Property Inspector**  
   Auto-generated forms using [pydantic] models declared in your
   Python components.

4. **Console**  
   Aggregated logs from CloudWatch + local editor runtime, searchable
   with regex and OmegaQL.

---

## Creating Your First Scene
> Estimated time: 5 min

1. Click **File ▸ New Scene** → choose *Blank Template*  
   This sends `SceneCreated` to EventBridge.

2. In the **Hierarchy**, press ⌘N (Ctrl+N on Windows) to *spawn* an
   entity. Name it `PlayerAvatar`.

3. Attach built-in components:
   * `Transform3D`
   * `NetworkReplicator`
   * `Health` *(domain-specific, provided by the Sales-Trainer template)*

4. Press **Play ▶**  
   The editor spins up a *sandbox* Step Function run called
   `dev-PlayerAvatar-preview`, executes a deterministic loop, then
   streams the frames back over WebSocket.

5. Click **Save** (⌘S). A versioned object named
   `s3://ledgerquest-assets/dev/scenes/MyFirstScene.v1.0.0.json` is
   created. The DynamoDB `SceneMetadata` table is also updated.

---

## Python Scripting 101
Every LedgerQuest system is a *stateless* function that receives and
returns pure data. You can write those systems in Python and hot-swap
them into the sandbox without redeploying.

### Example: Custom Scoring System
```python
# file: systems/scoring.py

from __future__ import annotations

from ledgerquest.core import System
from ledgerquest.events import ScoreIncremented, DamageTaken
from ledgerquest.logger import get_logger

log = get_logger(__name__)


class ScoringSystem(System):
    """
    Awards 10 points for each successful 'OutboundCall' action,
    but deducts if the user triggers 'ComplianceStrike'.
    """

    def process(self, frame):
        # `frame.events` is a list of domain events emitted this tick.
        for event in frame.events:
            match event:
                case ScoreIncremented(user_id=user, amount=amount):
                    self._update_score(user, +amount)
                case DamageTaken(user_id=user, damage=damage):
                    self._update_score(user, -damage * 2)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _update_score(self, user: str, delta: int) -> None:
        before = self.world.components["Score"][user].value
        self.world.components["Score"][user].value += delta
        after = self.world.components["Score"][user].value

        log.debug(
            "Score updated for %s: %d → %d (Δ=%+d)", user, before, after, delta
        )
```

Hot-reload into the editor:

```bash
lq-editor watch systems/scoring.py
# Editor will prompt: "Reload ScoringSystem? (y/n)"
```

### Unit testing with PyTest
```python
# tests/test_scoring.py
import pytest
from ledgerquest.testing import MockWorld
from systems.scoring import ScoringSystem
from ledgerquest.events import ScoreIncremented

@pytest.fixture()
def world():
    return MockWorld(components=["Score"])

def test_score_increments(world):
    sys = ScoringSystem(world)
    user = "alice"
    world.components["Score"][user].value = 0

    frame = world.fake_frame(events=[ScoreIncremented(user, 5)])
    sys.process(frame)

    assert world.components["Score"][user].value == 5
```

---

## Serverless Persistence
Whenever you click **Save**, these actions happen:

1. The scene JSON is compressed with `zstd` (~65 % smaller than gzip).
2. A `PutObject` to an S3 bucket partitioned by `OrganisationId`.
3. A `SceneVersioned` event triggers:
   • A Lambda that updates the **Search Index** (OpenSearch)  
   • A Lambda that computes **cost-to-run** analytics  
   • A Lambda that warms the **GPU object pool** if render demand spikes

Because assets live in S3, you can use standard lifecycle rules,
Glacier, or S3 Intelligent-Tiering to keep costs low.

---

## Testing & Continuous Integration
We ship a GitHub Action workflow located at
`.github/workflows/editor-ci.yml`. It will:

1. Install Python + Node matrix
2. `pip install ledgerquest-engine[all]`
3. Lint with `ruff`, type-check with `mypy`
4. Run `pytest --cov=ledgerquest`
5. Upload coverage to Codecov
6. Build the Electron app for macOS, Linux, Windows
7. Publish artifacts back to the PR

To run locally:

```bash
make lint test build
```

---

## Advanced Topics
### Multi-Region Replication
Set `LEDGERQUEST_REGION=us-east-1,eu-west-1,ap-southeast-1` and the
editor will **fan-out** save events across active-active DynamoDB,
ensuring sub-200 ms latency world-wide. Conflict resolution follows
*last-writer-wins* with a monotonic timestamp from AWS X-Ray.

### Branching & Merging Scenes
```bash
ledgerquest-scm branch create feature/revenue-dashboard
lq-editor --branch feature/revenue-dashboard
# Do edits...
ledgerquest-scm branch merge feature/revenue-dashboard main --squash
ledgerquest-scm publish                 # Push to remote (ECR + S3)
```

### Programmatic Editor API
All UI actions are thin wrappers over the `ledgerquest.editor.api`
module. You can automate tasks, e.g. baking lightmaps or anonymising
tenant-data before a demo.

```python
from ledgerquest.editor.api import Scene, open_project

project = open_project("s3://ledgerquest-assets/dev")
with project.checkout("MyFirstScene") as scene:      # type: Scene
    player = scene.get_entity("PlayerAvatar")
    player.add_component("AchievementTracker", threshold=100)
    scene.save(message="Add achievements to player")
```

---

## Troubleshooting

| Symptom | Possible Cause | Fix |
|---------|----------------|-----|
| “AWS Signature expired” | System clock skew | `sudo ntpdate -u pool.ntp.org` |
| Missing textures in Scene View | S3 CORS misconfiguration | `aws s3 cp cors.json s3://…/ --region us-east-1 --profile admin` |
| Editor crashes on Play ▶ | Lambda timed-out | `lq logs tail --filter <SceneRunId>` and bump `TIMEOUT` env |
| GPU preview blank | No Fargate capacity | Request limit-increase: `aws support create-limit-request …` |

If all else fails, join the **#ledgerquest-editor** Slack channel and
attach your `~/Library/Logs/ledgerquest/editor.log`.

---

## Glossary
* **ECS** – Entity Component System  
* **Step Function** – AWS serverless state machine orchestrating your loop  
* **EventBridge** – Event bus used for audit and side-effects  
* **System** – Pure Python function mutating world state  
* **Scene** – A serialisable collection of entities & components  

---

## Changelog
| Version | Date | Notes |
|---------|------|-------|
| 2.1.0 | 2024-05-06 | Added multi-region replication and live ECM preview |
| 2.0.0 | 2024-02-12 | Re-wrote editor in Tauri, switched to pydantic v2 |
| 1.3.5 | 2023-11-18 | Initial public release |

---

© 2024 LedgerQuest Inc. All rights reserved.
```