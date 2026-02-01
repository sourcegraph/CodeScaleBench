```markdown
---
title: LedgerQuest Engine
subtitle: A Serverless Business-Grade Game Framework
description: >
  LedgerQuest marries real-time game-engine primitives with enterprise-grade
  scalability, governance, and cost efficiency.  
  Build immersive, gamified business applications without ever touching a
  server.
toc: true
---

<div align="center">

![LedgerQuest Engine](./assets/ledgerquest_logo.svg)

</div>

# Welcome to LedgerQuest Engine 🏹🛡️

LedgerQuest Engine is an **expert-level Python game framework** purpose-built
for _business_ use-cases—think sales-force simulators, supply-chain strategy
games, or financial-literacy worlds.  
Behind the scenes, the entire runtime is **fully serverless**: every tick of the
game loop executes inside AWS Lambda, orchestration is handled by Step
Functions, and state is externalized to DynamoDB/S3 for infinite scale.

---

## Key Capabilities

| Feature                               | Business Value                                            |
|---------------------------------------|-----------------------------------------------------------|
| **GPU-accelerated Rendering**         | AAA visuals without owning GPUs                           |
| **Entity-Component-System**           | Rapid iteration on domain logic                           |
| **AI Behavior Trees**                 | Rich NPC & bot behaviors, configurable at runtime         |
| **Multi-Tenant Data Isolation**       | SOC 2 / ISO 27001 ready                                   |
| **Audit Logging & Usage Metering**    | Compliance & pay-per-use billing                          |
| **Event-Driven Asset Pipeline**       | Zero-idle cost for level-editor changes                   |
| **Step Function Orchestrated Ticks**  | Deterministic, debuggable, replayable game loops          |

---

## Serverless Architecture (Mermaid)

```mermaid
flowchart TD
    subgraph Game Tick [Every 50 ms (Tₙ)]
        A1[API Gateway<br>WebSocket] -->|Player Input| L1((Λ))
        style Game Tick fill:#f9f,stroke:#333,stroke-width:0px
    end

    subgraph Orchestration
        S1[Step Functions<br>State Machine]
        S1 --> L1((Λ))
        L1 --> DDB[(DynamoDB)]
        L1 --> EB>EventBridge]
    end

    subgraph Long-Lived State
        DDB -->|Persist Frame| S3[(S3 Checkpoints)]
    end

    EB --> GPU[Fargate GPU Fleet]
    EB --> Audit((CloudWatch Logs))
```

---

## Quick Start

```bash
# 1) Install the CLI
pip install ledgerquest-engine

# 2) Create a new game project
lq init my_first_game
cd my_first_game

# 3) Deploy to your AWS account (≈3 min)
lq deploy --profile my-org-sso
```

Once deployment succeeds, open the **Playground** URL printed in your terminal
to spawn a browser-based client connected via WebSocket.

---

## Hello, World 🏗️

Below is the minimal code required to spawn a rotating cube in a
multi-tenant-safe scene. Save it as `src/systems/hello_cube.py` and push it
with `lq sync`.

```python
"""
Demo system: Spawn & rotate a single cube entity.
Executed inside the stateless Lambda tick function.
"""
from __future__ import annotations

from decimal import Decimal
from ledgerquest.ecs import Component, System, ecs

class Transform(Component):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rot_y: float = 0.0  # Y-axis rotation in degrees

class Rotator(System):
    """Increment rot_y a tiny bit each frame."""
    ROT_SPEED = Decimal("1.5")  # degrees per tick

    def update(self, dt: float) -> None:
        for entity, tf in ecs.query(Transform):
            tf.rot_y = (tf.rot_y + float(self.ROT_SPEED)) % 360

# Register on module import
ecs.register_system(Rotator)
```

### What just happened?

1. `Rotator.update()` runs inside the ⁨`Λ-tick` Lambda.  
2. Each entity with a `Transform` component has its `rot_y` increased.  
3. The renderer (running on Fargate GPU) **streams only diffed transforms**
   back to connected clients—no over-the-wire physics spam.  
4. Because the system is **stateless**, it can **fan-out horizontally** for
   spikes in player activity.

---

## Design Philosophy

1. **Stateless Functions ≘ Game Loops**  
   Every Lambda invocation is a deterministic “frame” that pulls the previous
   world state from DynamoDB, mutates it, and commits the diff.

2. **Externalized State ≘ Infinite Scale**  
   Offloading persistence to DynamoDB/S3 allows hot-patching code without
   affecting sessions; cold starts are negligible (< 5 ms w/ provisioned
   concurrency).

3. **Event-Driven Everything**  
   Asset uploads, level-editor saves, and AI-script commits raise events that
   warm relevant object pools _only_ when needed—resulting in near-zero idle
   costs.

---

## Extending the Engine

### Custom Physics Integrations

While LedgerQuest ships with a deterministic, fixed-time-step physics module,
you can swap in a heterogeneous compute back-end (e.g., **Rust+WASM** or
**C++ MicroVM**) without touching the core engine:

```python
from ledgerquest.physics import register_physics_backend
from mycorp.superphysics import StepWorld, Body

register_physics_backend(StepWorld, body_cls=Body, deterministic=True)
```

### Scripting with Py-Sandbox

Business analysts can author narrative or financial scenarios in a restricted
Python subset that runs in a hardened **`py-sandbox`** Lambda layer:

```python
from ledgerquest.scripting import ScriptEngine, safe_imports

scenario = """
portfolio = {'cash': 100_000}
def on_tick(dt, market):
    if market['volatility'] < 0.2:
        portfolio['cash'] *= 1.01
"""
engine = ScriptEngine(safe_imports={"math", "random"})
engine.load_string(scenario).execute()
```

---

## Ops & Observability

| Concern           | Implementation                           |
|-------------------|------------------------------------------|
| **CI/CD**         | GitHub Actions + AWS CodeDeploy          |
| **Logging**       | Structured JSON via AWS Lambda Powertools|
| **Tracing**       | AWS X-Ray (automatic with Powertools)    |
| **Metrics**       | Embedded CloudWatch EMF                  |
| **Cost Analysis** | CloudWatch Usage Anomaly Detector        |

All infrastructure is codified in
[`cdk/app.py`](https://github.com/ledgerquest/engine/blob/main/cdk/app.py) and
deploys in under 4 minutes.

---

## Contributing 🤝

1. Fork ➡️ create feature branch
2. `pre-commit install` to run linters automatically
3. Ensure `pytest -q` passes & coverage ≥ 95 %
4. Submit PR — the core team responds within **2 business days**

---

## Further Reading

* [ECS design doc](./design/ECS.md)
* [AI behavior trees](./design/AI_Behavior.md)
* [Serverless checkpointing](./design/Checkpointing.md)
* [Cost-per-tick analysis](./design/Economics.md)

---

<div align="center">

Made with ❤️ & ☁️ by the LedgerQuest Community

</div>
```