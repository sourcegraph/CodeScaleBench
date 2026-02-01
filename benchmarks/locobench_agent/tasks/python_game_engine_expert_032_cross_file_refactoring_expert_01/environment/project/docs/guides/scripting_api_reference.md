```markdown
# LedgerQuest Engine • Scripting API Reference  
**Version:** 1.4.x   **Runtime:** Python ≥ 3.11   **Last updated:** 2024-05-08  

Welcome to the official reference for the LedgerQuest Engine scripting layer (`lq.script`).  
All examples below are production-ready and are known to run **unchanged** inside the managed
server-side runtime (AWS Lambda) as well as the local simulator (`lq-cli sim run`).

---

## Table of Contents
1. [Quick-Start](#quick-start)  
2. [Execution Model](#execution-model)  
3. [Lifecycle Hooks](#lifecycle-hooks)  
4. [Core API](#core-api)  
   1. [`GameObject`](#gameobject)  
   2. [`Component`](#component)  
   3. [`Behavior`](#behavior)  
   4. [`PhysicsBody`](#physicsbody)  
   5. [`Animator`](#animator)  
   6. [`DataStore`](#datastore)  
5. [Networking & Messaging](#networking--messaging)  
6. [Data Persistence](#data-persistence)  
7. [Complete Samples](#complete-samples)  
8. [Best Practices & Gotchas](#best-practices--gotchas)  
9. [Changelog](#changelog)  

---

## Quick-Start

```bash
# Install the SDK locally
pip install ledgerquest-engine==1.4.*

# Scaffold a new script
lq-cli script new my_first_script
```

```python
# my_first_script.py
from lq.script import GameObject, Behavior, Logger

class Greeter(Behavior):
    """
    A minimal behavior that greets players once at spawn and
    tracks how long the GameObject has been alive.
    """

    # Called once when the enclosing GameObject is spawned
    def on_spawn(self) -> None:
        Logger.info(f"👋 Hello from: {self.game_object.name}")

    # Called every engine tick (≈ 60 Hz by default)
    def on_update(self, delta_time: float) -> None:
        self.game_object.meta['elapsed'] = (
            self.game_object.meta.get('elapsed', 0.0) + delta_time
        )

    # Called when the GameObject is destroyed
    def on_destroy(self) -> None:
        Logger.info(
            f"{self.game_object.name} lived for "
            f"{self.game_object.meta.get('elapsed', 0):.2f}s"
        )
```

Deploy the function with:

```bash
lq-cli deploy --scripts my_first_script.py
```

---

## Execution Model

• **Stateless**: Each script runs inside an AWS Lambda container.
  Persistent data must be externalized (see [`DataStore`](#datastore)).  
• **Event-Driven**: Triggers come from the real-time game loop,
  player WebSocket events, or external system webhooks  
• **Soft Realtime**: A single Lambda invocation must finish within
  16 ms (`≈ 60 FPS`) to avoid dropping frames in multiplayer sessions.  
• **Long-Running Tasks**: For jobs exceeding the 16 ms budget,
  off-load to Fargate GPU workers via `lq.jobs.enqueue()`.

---

## Lifecycle Hooks

| Hook           | Signature                          | Guaranteed Order | Typical Use-Case                       |
|----------------|------------------------------------|------------------|----------------------------------------|
| `on_spawn`     | `() -> None`                       | 1 st            | Allocate timers, register observers    |
| `on_update`    | `(delta_time: float) -> None`      | 2 nd (loops)    | Per-frame logic, animations            |
| `on_message`   | `(msg: dict, sender_id: str)`      | async           | Inter-entity comms, chat, RPC          |
| `on_collision` | `(other: GameObject) -> None`      | async           | Gameplay physics                       |
| `on_destroy`   | `() -> None`                       | final           | Cleanup, statistics, achievements      |

> Hooks are *optional*—only implement what you need.

---

## Core API

### `GameObject`

Represents an entity inside the **Entity-Component-System** (ECS).

```python
class GameObject:
    id: str
    name: str
    tags: set[str]
    transform: Transform
    meta: dict[str, Any]

    def add_component(self, component: Component) -> None: ...
    def get_component(self, cls: type[T]) -> T | None: ...
    def destroy(self) -> None: ...
    def send_message(self, target_id: str, payload: dict) -> None: ...
```

### `Component`

Base-class for data only (no logic).

```python
class Component:
    game_object: GameObject
```

### `Behavior`

The work-horse—attach logic to a `GameObject`.

```python
class Behavior(Component):
    # Override any of the lifecycle hooks
    def on_spawn(self) -> None: ...
    def on_update(self, delta_time: float) -> None: ...
    def on_message(self, msg: dict, sender_id: str) -> None: ...
    def on_collision(self, other: GameObject) -> None: ...
    def on_destroy(self) -> None: ...
```

### `PhysicsBody`

```python
class PhysicsBody(Component):
    velocity: Vector3
    angular_velocity: Vector3
    mass: float

    def apply_force(self, force: Vector3) -> None: ...
    def apply_impulse(self, impulse: Vector3) -> None: ...
```

### `Animator`

```python
class Animator(Component):
    def play(self, clip: str, loop: bool = False) -> None: ...
    def cross_fade(self, from_clip: str, to_clip: str, duration: float) -> None: ...
```

### `DataStore`

A zero-config wrapper around DynamoDB and S3, automatically
namespaced per tenant and game session.

```python
from lq.script import DataStore

store = DataStore(table="player_stats")

# Typed reads & writes
await store.put("player_42", {"xp": 1337, "last_login": "2024-05-08"})
stats: dict = await store.get("player_42")
```

> Reads inside the same Lambda invocation are strongly-consistent
> by default; cross-invocation reads are eventually consistent
> (≈ 100 ms).

---

## Networking & Messaging

```python
from lq.script import NetEntity, Logger

class ChatRelay(NetEntity):
    """Forward chat messages to all players in the same room."""

    async def on_message(self, payload: dict, sender_id: str) -> None:
        text = payload.get("text", "")
        Logger.debug(f"Chat: {sender_id}: {text}")

        # Broadcast to everyone (O(n) fan-out handled by the runtime)
        await self.broadcast({"text": text, "from": sender_id})
```

---

## Data Persistence

Two patterns are provided:

1. **High-frequency, Low-latency** → `DataStore` (DynamoDB + DAX cache)  
2. **Bulk / Binary** → `DataStore.bucket` (S3 + S3 Object Lambda)  

```python
avatar_png = await store.bucket.get_bytes("avatars/player_42.png")
await store.bucket.put_bytes("snapshots/level-1.bin", level_bytes, content_type="application/octet-stream")
```

---

## Complete Samples

### 1. Collectible Item

```python
# collectible.py
from lq.script import Behavior, PhysicsBody, DataStore, Logger

class Coin(Behavior):
    """
    Rotates slowly, detects player collision, awards currency,
    and then self-destructs with a particle effect.
    """

    def on_spawn(self) -> None:
        self.body: PhysicsBody = self.game_object.get_component(PhysicsBody)
        self.tilt_speed = 45.0  # degrees/s

    def on_update(self, dt: float) -> None:
        # Rotate around Y-axis
        self.game_object.transform.rotate_y(self.tilt_speed * dt)

    async def on_collision(self, other) -> None:
        if "player" not in other.tags:
            return

        player_id = other.id
        store = DataStore(table="wallet")
        await store.inc(player_id, "gold", by=1)

        Logger.info(f"Player {player_id} collected a coin.")
        self.spawn_effect()
        self.game_object.destroy()

    def spawn_effect(self) -> None:
        self.game_object.scene.spawn_prefab("VFX/CoinPickup", self.game_object.transform.position)
```

### 2. AI Behavior Tree Node

```python
# guard_bt.py
from lq.script import Behavior, Logger
from lq.ai import Blackboard, Condition, Action

class IsPlayerVisible(Condition):
    def tick(self) -> bool:
        player = self.context.get("player")
        visible = self.context['vision'].can_see(player)
        Logger.debug(f"Visibility check: {visible}")
        return visible

class ChasePlayer(Action):
    def tick(self) -> bool:
        nav = self.context['nav_agent']
        nav.set_destination(self.context['player'].transform.position)
        return nav.reached_destination()
```

Register nodes in the editor under *AI Library ➜ Guards*.

---

## Best Practices & Gotchas

✔ Keep Lambda payloads < 6 MB—large JSON blobs incur latency  
✔ Minimize cold starts via `lq.cli warm --script my_script.py`  
✔ Use `async`/`await` for I/O; never block the event loop  
✘ Don’t assume local wall-clock continuity between invocations  
✘ Don’t store secrets in script source—use AWS Secrets Manager  

---

## Changelog

2024-05-08 • Added `Animator.cross_fade` & `DataStore.inc` convenience  
2024-04-12 • Scripting runtime bumped to Python 3.11  
2024-03-01 • Initial public release  

---

© 2024 LedgerQuest Inc. All rights reserved.
```