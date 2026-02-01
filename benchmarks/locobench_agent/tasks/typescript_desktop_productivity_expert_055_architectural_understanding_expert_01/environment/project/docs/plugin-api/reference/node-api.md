```markdown
<!--
  File: docs/plugin-api/reference/node-api.md
  Project: PaletteFlow Studio
  Description: Comprehensive reference for authoring custom Canvas Nodes through the PaletteFlow
               Plugin API.  The page is intentionally exhaustive—every public symbol exposed to
               plugin authors is documented with rich TypeScript examples, design-guidelines,
               lifecycle diagrams, and gotchas harvested from real-world usage inside the
               first-party “PaletteFlow Essentials” plugin bundle.
-->

# 🎨 PaletteFlow Plugin API — Node API Reference

A *Node* is the foundational building block of a PaletteFlow canvas.  
Plugins can register entirely new Node types—Markdown snippets, code run-books, custom
vector editors, IoT dashboards, … you name it.

This document teaches you how to:

1. Declare a custom Node type with rich metadata.  
2. Implement a **ViewModel-driven Renderer** that plays nicely with PaletteFlow’s MVVM shell.  
3. Wire up a declarative **State Machine** so your Nodes behave predictably and are
   serializable across workspaces.  
4. Expose **Command Palette** actions, a **contextual toolbar**, and participate in global
   **undo/redo** via the Command pattern.  
5. Subscribe to low-level **canvas events** while remaining sandboxed by the plugin host.

All public interfaces shown here are imported from the top-level package

```ts
import {
  CanvasNodeFactory,
  CanvasNodeRenderer,
  CanvasNodeContext,
  registerNodeType,
  useNodeEvent,
  CommandRegistrar,
  NodeStateMachine,
  NodeLifecycleHooks,
  Theme,
} from '@paletteflow/sdk';        // Installed automatically alongside PaletteFlow Studio
```

---

## 1  Node Metadata

Metadata is a plain object that describes how your Node manifests inside the UX (palette
search, toolbar icon, import/export, etc.).  It must satisfy the
`CanvasNodeFactory['meta']` contract:

```ts
export interface NodeMeta {
  type: string;                    // Unique machine-friendly identifier
  displayName: string;             // Shown in the Command Palette & UI
  version: string;                 // Semver (should mirror your plugin version)
  icon?: string | IconComponent;   // 16 × 16 SVG or React/Vue/Svelte component
  defaultWidth?: number;           // Initial bounding-box (CSS pixels)
  defaultHeight?: number;
  categories?: string[];           // e.g., ['Productivity', 'Visualization']
  tags?: string[];                 // Free-form search keywords
  docsUrl?: string;                // Deep-link to your own documentation
}
```

### Example

```ts
const meta: NodeMeta = {
  type:          'com.acme.stopwatch',
  displayName:   '⏱️ Stopwatch',
  version:       '1.2.3',
  icon:          '<svg …/>',
  defaultWidth:  320,
  defaultHeight: 160,
  categories:    ['Utilities'],
  tags:          ['time', 'tracking', 'pomodoro'],
  docsUrl:       'https://acme.dev/paletteflow/stopwatch',
};
```

---

## 2  Renderer

PaletteFlow is UI-framework agnostic—your plugin chooses *one* of the officially
supported renderer runtimes:

• React 18  
• Vue 3  
• Svelte 4  
• Lit (WebComponents)  
• Solid JS  

Renderers must be *purely presentational*. Business logic lives inside the **ViewModel**
exposed by `CanvasNodeContext.vm`.

Below is a fully-fledged *Stopwatch* Node implemented in React and TypeScript.

```tsx
import React, { useEffect } from 'react';
import { CanvasNodeRenderer, useNodeEvent } from '@paletteflow/sdk/react';

interface StopwatchVm {
  elapsedMs: number;
  running: boolean;
  start: () => void;
  stop: () => void;
  reset: () => void;
}

export const StopwatchRenderer: CanvasNodeRenderer<StopwatchVm> = ({
  ctx,                 // CanvasNodeContext<StopwatchVm>
  theme,               // Resolved Theme object (colors, fonts, etc.)
}) => {
  const { vm } = ctx;

  /* Hot-reloader friendly event subscription */
  useNodeEvent(ctx, 'themeChanged', (newTheme: Theme) => {
    console.debug('[Stopwatch] Theme updated →', newTheme.name);
  });

  // Auto-tick every 100 ms **while** running
  useEffect(() => {
    if (!vm.running) return;

    const id = window.setInterval(() => vm.tick?.(), 100);
    return () => window.clearInterval(id);
  }, [vm.running]);

  /* 🎨 Dumb component with ZERO business logic */
  return (
    <div
      style={{
        fontFamily: theme.fontMono,
        background: theme.surface2,
        color:      theme.textPrimary,
        padding:    12,
        borderRadius: 8,
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <span>{(vm.elapsedMs / 1000).toFixed(1)} s</span>
      {vm.running ? (
        <button onClick={vm.stop}>Stop</button>
      ) : (
        <button onClick={vm.start}>Start</button>
      )}
      <button onClick={vm.reset} disabled={vm.elapsedMs === 0}>
        Reset
      </button>
    </div>
  );
};
```

---

## 3  State Machine

Nodes are long-lived and must be serializable.  PaletteFlow relies on XState-inspired
state machines so your logic is deterministic, testable, and persists cleanly to JSON.

```ts
import { NodeStateMachine } from '@paletteflow/sdk';

interface StopwatchState {
  elapsedMs: number;
}

interface StopwatchContext {
  running: boolean;
}

export const stopwatchMachine: NodeStateMachine<
  StopwatchState,
  StopwatchContext
> = {
  id: 'stopwatch',
  context: { running: false },
  initial: 'idle',
  states: {
    idle: {
      on: {
        START: { target: 'running', actions: ['startTimer'] },
      },
    },
    running: {
      on: {
        STOP: { target: 'idle', actions: ['stopTimer'] },
        TICK: { actions: ['increment'] },
      },
    },
  },
  actions: {
    startTimer: ({ ctx }) => { ctx.running = true; },
    stopTimer:  ({ ctx }) => { ctx.running = false; },
    increment:  ({ state }, { ms }) => { state.elapsedMs += ms; },
  },
  guards: {
    hasElapsed: ({ state }) => state.elapsedMs > 0,
  },
};
```

Action/guard callbacks receive a strongly-typed bag:

```ts
type ActionFn<S, C, E extends { type: string }> = (payload: {
  state: S;          // Mutable clone
  ctx: C;            // Machine context             (mutable)
  event: E;          // Raw triggering event
}) => void;
```

---

## 4  Canvas Node Factory

Finally, glue the pieces together with `registerNodeType`.

```ts
import { registerNodeType, CanvasNodeFactory } from '@paletteflow/sdk';
import { StopwatchRenderer } from './StopwatchRenderer';
import { stopwatchMachine }  from './stopwatch.machine';
import meta                  from './meta.json';

type StopwatchNode = CanvasNodeFactory<
  typeof stopwatchMachine,
  StopwatchRenderer
>;

const stopwatchFactory: StopwatchNode = {
  meta,
  machine: stopwatchMachine,
  renderer: StopwatchRenderer,

  /* Optional lifecycle hooks */
  hooks: {
    onCreate(ctx) {
      ctx.log.debug('Stopwatch created');
    },
    onDestroy(ctx) {
      ctx.log.debug('Stopwatch destroyed');
    },
  },
};

/* Plugin entrypoint — executed by the host once at load-time */
export function activate() {
  registerNodeType(stopwatchFactory);
}
```

> ⚠️ The factory itself is **pure metadata**—make sure *none* of the properties capture
> request-scoped variables (DOM, timers, WebSocket handles, etc.) or you’ll leak memory
> on hot-reload.

---

## 5  Command Palette & Toolbar

PaletteFlow’s global Command Palette (⇧⌘P) can invoke Node-scoped commands declared via
`CommandRegistrar`.

```ts
import { CommandRegistrar } from '@paletteflow/sdk';

export const stopwatchCommands: CommandRegistrar = (ctx) => ({
  'stopwatch.start': {
    label: 'Start Stopwatch',
    when: () => !ctx.vm.running,
    execute: ctx.vm.start,
  },
  'stopwatch.stop': {
    label: 'Stop Stopwatch',
    when: () =>  ctx.vm.running,
    execute: ctx.vm.stop,
  },
  'stopwatch.reset': {
    label: 'Reset Stopwatch',
    when: () => ctx.vm.elapsedMs > 0,
    execute: ctx.vm.reset,
    shortcuts: ['R'],
  },
});
```

### Contextual Toolbar

```ts
export const toolbar = [
  {
    id: 'startStop',
    icon: '▶️/⏸️',
    tooltip: (ctx: CanvasNodeContext) => ctx.vm.running ? 'Stop' : 'Start',
    onClick: (ctx) => ctx.vm.running ? ctx.vm.stop() : ctx.vm.start(),
  },
  {
    id: 'reset',
    icon: '⟲',
    tooltip: 'Reset (R)',
    disabled: (ctx) => ctx.vm.elapsedMs === 0,
    onClick: (ctx) => ctx.vm.reset(),
  },
];
```

Register both alongside the Node factory:

```ts
registerNodeType({
  ...stopwatchFactory,
  commands: stopwatchCommands,
  toolbar,
});
```

---

## 6  Lifecycle Hooks

Hook                   | Timing                                                | Args
---------------------- | ------------------------------------------------------ | ----
`onCreate`             | Right after Node JSON is instantiated (workspace load) | `ctx`
`onMount`              | Renderer attached to DOM                               | `ctx`
`onUpdate`             | Renderer re-render; diff contains changed props        | `ctx`, `diff`
`onDestroy`            | Node removed from canvas or workspace closed           | `ctx`

All hooks receive a **hot-scoped** `CanvasNodeContext`:

```ts
interface CanvasNodeContext<VM = any> {
  readonly id: string;
  readonly meta: NodeMeta;
  readonly vm: VM;                       // ViewModel derived from your machine
  readonly log: Logger;                  // Per-Node logger w/ scoping
  readonly clipboard: ClipboardAdapter;  // File, text, Node payloads
  emit<E extends NodeEvent>(event: E): void;
  on<E extends NodeEvent>(type: E['type'], cb: (event: E) => void): Unsubscribe;
}
```

---

## 7  Inter-Node Communication

PaletteFlow ships with *strict* plug-in isolation.  Direct references between Nodes
inside different plugin sandboxes are forbidden to guarantee hot-reload integrity and
security.  Instead, use the **Event Bus**:

```ts
// sender
ctx.emit({ type: 'stopwatch/elapsed', ms: ctx.vm.elapsedMs });

// receiver
useNodeEvent(ctx, 'stopwatch/elapsed', ({ ms }) => {
  if (ms > 25_000) alert('Take a quick break! 🚶‍♂️');
});
```

Event names are namespaced (`<domain>/<event>`).  Third-party plugins should document
their contracts in README files.

---

## 8  Error Handling

All uncaught exceptions thrown inside Renderers, state-machine actions, commands, or
lifecycle hooks are wrapped in a plugin-specific boundary and reported through
PaletteFlow’s crash analytics center.  You can *optionally* attach additional context:

```ts
try {
  riskyOperation();
} catch (err) {
  ctx.log.error('Stopwatch tick failed', err, {
    elapsedMs: ctx.vm.elapsedMs,
    running:   ctx.vm.running,
  });
  throw err;           // Rethrow so host picks it up
}
```

---

## 9  Testing & CI

Because Node logic is decoupled from the renderer, you can run fast, headless
unit-tests with your favorite framework:

```ts
// stopwatch.spec.ts
import { interpretMachine } from '@paletteflow/sdk/testing';
import { stopwatchMachine } from './stopwatch.machine';

describe('Stopwatch Machine', () => {
  it('increments elapsedMs while running', () => {
    const service = interpretMachine(stopwatchMachine).start();

    service.send('START');
    service.send({ type: 'TICK', ms: 500 });
    service.send('STOP');

    expect(service.snapshot.state.elapsedMs).toBe(500);
    expect(service.snapshot.ctx.running).toBe(false);
  });
});
```

CI pipelines should run `pf validate` to lint meta-schemas and ensure your plugin stays
forward-compatible with upcoming PaletteFlow Studio releases.

---

## 10  Publishing

1. Add `"paletteflow-plugin": "^1"` to your `package.json` keywords.  
2. Run `npm publish --access public`.  
3. Submit your plugin URL at <https://paletteflow.io/plugins/submit>.  
4. Congrats!  Your Node will appear in users’ in-app discovery feed after automated
   security scanning (typical SLA ≤ 15 min).

---

## 11  API Changelog

Version | Breaking? | Notes
------- | --------- | -----
v2.0    | ✅        | Renderer props renamed `hostTheme` → `theme`
v1.7    |           | Added `toolbar` dynamic disable predicate
v1.5    |           | Machine guards now access full `canvas` snapshot
v1.0    |           | Initial GA

Stay tuned via the #plugin-dev Discord channel for release candidates and RFCs.

---

## 12  Further Reading

• [Theme API Reference](./theme-api.md)  
• [Plugin Manifest Schema](../manifest-schema.md)  
• [PaletteFlow Core Architecture](../../design/architecture.md)

*Happy hacking, and may your canvases flow with infinite creativity!* 🚀
```