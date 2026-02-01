```markdown
<!--
  File: docs/user-guide/05-using-plugins.md
  Project: PaletteFlow Studio
  Description: Comprehensive user-guide chapter that teaches end-users and plugin
               authors how to discover, install, and develop PaletteFlow plugins.
  -------------------------------------------------------------------------------
  NOTE: This document purposely embeds TypeScript code examples that compile
        against the public `@paletteflow/sdk` package exposed by the desktop
        application.  Copy & paste the snippets into your editor to bootstrap
        real plugins.
-->

# 05 &mdash; Using Plugins

PaletteFlow’s plugin system lets you bend the studio to your creative will:
drop in brand-new node types, wire custom state-machines, or import a file
format nobody has ever heard of.  
All without forking the core code-base.

This guide covers both **(A)** installing third-party plugins and **(B)**
authoring your own.

---

## A. Installing & Managing Plugins

### Installing from the Marketplace

1. Open `File ▸ Preferences ▸ Plugins`.
2. Search for the package name _or_ keyword.
3. Click **Install**.  
   Behind the scenes the Studio will fetch the signed `.pfp` bundle from the
   official registry, verify its signature, and place it in

   ```
   %AppData%/PaletteFlow/plugins   # Windows
   ~/.paletteflow/plugins          # macOS / Linux
   ```

### Installing a Local Bundle

Have a `.pfp` file on disk?

```bash
paletteflow plugins install ./my-awesome-plugin.pfp
```

### Enabling / Disabling & Hot-Reload

Toggle the switch in the **Plugins** pane or run:

```bash
paletteflow plugins enable  my-plugin-id
paletteflow plugins disable my-plugin-id
```

Changes take effect instantly; the runtime container will hot-reload the module
and broadcast the `plugin:reloaded` event to all observers.

### Upgrading

The auto-update engine checks for plugin updates every 4 hours.  
You can also trigger it manually:

```bash
paletteflow plugins upgrade --all
```

---

## B. Writing Your First Plugin

We ship an SDK that wraps the low-level IPC and event plumbing:

```bash
npm i --save-dev @paletteflow/sdk
```

Every plugin is just a regular **npm** package with a `paletteflow.json`
manifest at its root.

<details>
<summary>paletteflow.json</summary>

```jsonc
{
  // Unique reverse-DNS identifier
  "id": "dev.yourname.timer",
  "name": "Flow Timer",
  "version": "1.0.0",
  "main": "dist/index.js",
  "engines": {
    "paletteflow": ">=2.4.0"
  },
  // Minimum permissions required
  "permissions": ["node:fs", "ui:canvas", "clipboard"],
  // Node types contributed by the plugin
  "contributions": {
    "nodes": ["TimerNode"]
  }
}
```
</details>

### Project Layout

```
my-timer-plugin/
 ├─ src/
 │   ├─ TimerNode.ts
 │   ├─ TimerRenderer.tsx
 │   └─ index.ts           # entry point
 ├─ paletteflow.json
 ├─ tsconfig.json
 └─ README.md
```

---

### 1. Implementing a Node Type

```ts
// src/TimerNode.ts
import {
  AbstractNode,
  NodeContext,
  SerializableState,
  z // Zod for schema
} from '@paletteflow/sdk';

/**
 * The serializable state for a TimerNode.
 */
export interface TimerState extends SerializableState {
  startedAt: number | null;
  elapsedMs: number;
}

export const TimerSchema = z.object({
  startedAt: z.number().nullable(),
  elapsedMs: z.number().min(0)
});

/**
 * A stopwatch / pomodoro timer node.
 */
export class TimerNode extends AbstractNode<TimerState> {
  static type = 'dev.yourname.timer/TimerNode';

  constructor(initial?: Partial<TimerState>) {
    super({
      startedAt: null,
      elapsedMs: 0,
      ...initial
    });
  }

  override validate(state: unknown): asserts state is TimerState {
    TimerSchema.parse(state);
  }

  /* ------------------------- Domain Logic ------------------------- */

  start(now = Date.now()) {
    if (this.state.startedAt) return;
    this.patch({ startedAt: now });
  }

  stop(now = Date.now()) {
    if (!this.state.startedAt) return;
    const delta = now - this.state.startedAt;
    this.patch({
      startedAt: null,
      elapsedMs: this.state.elapsedMs + delta
    });
  }

  reset() {
    this.patch({ startedAt: null, elapsedMs: 0 });
  }

  /* ---------------------- Serialization Hooks --------------------- */

  // Called right before the workspace is persisted.
  override toJSON(): TimerState {
    return { ...this.state };
  }
}
```

---

### 2. Crafting a React Renderer

PaletteFlow ships a headless Canvas; renderers decide **how** a node looks.

```tsx
// src/TimerRenderer.tsx
import React, { useEffect, useState } from 'react';
import { RendererProps, useNode } from '@paletteflow/sdk/react';

export default function TimerRenderer({ nodeId }: RendererProps) {
  const node = useNode(nodeId);          // ► reactive hook (Observer Pattern)
  const [display, setDisplay] = useState('00:00');

  useEffect(() => {
    const { startedAt, elapsedMs } = node.state;
    const base = elapsedMs + (startedAt ? Date.now() - startedAt : 0);

    const interval = setInterval(() => {
      const sec = Math.floor(base / 1000) % 60;
      const min = Math.floor(base / 1000 / 60);
      setDisplay(`${min.toString().padStart(2, '0')}:${sec
        .toString()
        .padStart(2, '0')}`);
    }, 250);

    return () => clearInterval(interval);
  }, [node.state.startedAt, node.state.elapsedMs]);

  return (
    <div className="pf-node-body pf-flex pf-items-center pf-gap-2">
      <span className="pf-text-lg pf-font-mono">{display}</span>

      {node.state.startedAt ? (
        <button className="pf-btn" onClick={() => node.stop()}>
          Stop
        </button>
      ) : (
        <button className="pf-btn" onClick={() => node.start()}>
          Start
        </button>
      )}

      <button
        className="pf-btn pf-ml-auto pf-text-xs"
        onClick={() => node.reset()}
      >
        Reset
      </button>
    </div>
  );
}
```

---

### 3. The Plugin Entry Module

```ts
// src/index.ts
import { PluginContext } from '@paletteflow/sdk';
import { TimerNode } from './TimerNode';
import TimerRenderer from './TimerRenderer';

/**
 * Every plugin exports a default factory.
 * It receives a sandboxed context that exposes the
 * registries & event-bus the plugin may use.
 */
export default async function activate(ctx: PluginContext) {
  // 1️⃣ Register the node type with the core domain layer.
  ctx.nodes.register(TimerNode);

  // 2️⃣ Bind our React component to the new node.
  ctx.renderers.register(TimerNode.type, TimerRenderer);

  // 3️⃣ Add a command-palette entry.
  ctx.commands.register({
    id: 'timer.toggle',
    title: 'Toggle Timer Start/Stop',
    scope: 'node',
    shortcut: 'T',
    handler: ({ node }) => {
      const timer = node as unknown as TimerNode;
      timer.state.startedAt ? timer.stop() : timer.start();
    }
  });

  // 4️⃣ Clean-up when the plugin unloads (hot-reload support).
  return () => {
    ctx.nodes.unregister(TimerNode.type);
    ctx.renderers.unregister(TimerNode.type);
    ctx.commands.unregister('timer.toggle');
  };
}
```

Build it:

```bash
npm run build   # emits dist/index.js
```

Package it:

```bash
paletteflow plugins pack   # → my-awesome-timer-1.0.0.pfp
```

Distribute it to friends or upload to the Marketplace!

---

## Debugging & Troubleshooting

| Symptom                               | Fix                                                                 |
|---------------------------------------|---------------------------------------------------------------------|
| `PluginNotTrustedError`               | Your bundle isn’t signed. Add `--unsigned` flag to install locally. |
| Renderer throws `React is undefined`  | Remember to `import React` at top of each `.tsx` file.              |
| Hot-reload doesn’t update UI          | Ensure your `activate()` returns a disposer function.               |
| State fails to deserialize on reopen  | Update `TimerSchema` to match your latest interface changes.        |

Turn on verbose logging:

```bash
paletteflow --dev --log-level=debug
```

---

## API Surface Cheatsheet

| Namespace            | Description                           |
|----------------------|---------------------------------------|
| `ctx.nodes`          | Register / unregister domain nodes    |
| `ctx.renderers`      | Map node types → React/Vue/Svelte     |
| `ctx.commands`       | Contribute items to Cmd-Palette       |
| `ctx.settings`       | Expose custom settings UI & defaults  |
| `ctx.events`         | Event-bus (Observer Pattern)          |
| `ctx.storage`        | Sandboxed file-system access          |
| `ctx.http`           | Fetch with automatic CORS proxy       |
| `ctx.logger`         | Structured logging w/ crash reports   |

Complete typings live inside `node_modules/@paletteflow/sdk/dist/index.d.ts`.

---

## Security Model (TL;DR)

• Plugins execute in a hardened <webview> with **ContextIsolation**.  
• Only whitelisted **permissions** (declared in `paletteflow.json`) are
  proxied through the IPC bridge.  
• Native Node.js APIs are _not_ available unless explicitly requested and
  granted via `node:*` scopes.

---

## Next Steps

1. Read the full SDK reference (`Help ▸ API Docs`).
2. Study the bundled **Kanban** & **Whiteboard** plugins.
3. Publish your work—then brag on our Discord!

Happy hacking 💜
```