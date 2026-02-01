```markdown
# PaletteFlow Studio – Plugin SDK

Welcome to the **PaletteFlow Studio Plugin SDK** – your gateway to extending PaletteFlow’s
infinite-canvas productivity platform with your own node types, renderers, import/export
pipelines, state-machine behaviours, and bespoke UI panels.

This document is the authoritative, production-grade reference for building,
testing, packaging, and publishing third-party plugins.  
All examples are written in **TypeScript** and assume basic familiarity with the
language as well as Node ≥ 16 LTS.

---

## 0. Quick Start

```bash
# 1 · Generate a new plugin skeleton (uses the official scaffolder)
npx @paletteflow/create-plugin my-cool-plugin
cd my-cool-plugin

# 2 · Run the local dev server (hot-reload into a live PaletteFlow window)
npm start

# 3 · Package & submit to the registry
npm run build
npm publish --access public
```

Once the dev server is running, PaletteFlow will detect the plugin via the local
WebSocket bridge and load it instantly – no restarts required.

---

## 1. Anatomy of a Plugin

```
my-cool-plugin/
├─ dist/                         # Compiled JS (auto-generated)
├─ src/
│  ├─ nodes/MarkdownCallout.ts   # Example custom node
│  ├─ panels/SettingsPanel.tsx   # Optional React panel
│  └─ index.ts                   # ✨  Entrypoint
├─ pfs-plugin.json               # ✍️  Manifest (see §3)
├─ tsconfig.json
└─ package.json
```

The convention is simple:

* `src/index.ts` exports a function called `activate`, which is invoked exactly
  once when the plugin is loaded.
* Anything returned by `activate` that implements the `Disposable` interface
  will be disposed when the plugin is unloaded.
* The manifest (`pfs-plugin.json`) declares metadata and extension points.

---

## 2. Hello World (Full Example)

Create `src/index.ts`:

```ts
import {
  PluginContext,
  registerNodeType,
  Disposable,
  CanvasNode,
  html
} from 'paletteflow-sdk';

/**
 * Minimal Hello-World node that echoes user text.
 */
class HelloWorldNode implements CanvasNode {
  static type = 'hello.world';

  // Node schema – persisted in workspace JSON
  state = { message: 'Hello PaletteFlow 🎨' };

  render() {
    return html`<h1>${this.state.message}</h1>`;
  }
}

export function activate(ctx: PluginContext): Disposable {
  // 1. Register a new node type
  const unregister = registerNodeType(HelloWorldNode);

  // 2. Log to the global command palette
  ctx.logger.info('HelloWorld plugin activated 🚀');

  // 3. Return a disposer so PaletteFlow can clean up hot-reloaded plugins
  return {
    dispose() {
      unregister();
      ctx.logger.info('HelloWorld plugin deactivated 🛑');
    }
  };
}
```

Add a _manifest_ in the project root:

```jsonc
{
  "id": "dev.yourname.hello-world",
  "displayName": "Hello World",
  "version": "0.1.0",
  "publisher": "yourname",
  "engines": {
    "paletteflow": "^1.8.0"
  },
  "icon": "assets/icon.svg",
  "main": "dist/index.js",
  "contributes": {
    "nodes": ["hello.world"]
  }
}
```

Compile & run:

```bash
npm run build
```

PaletteFlow should pick up the plugin immediately; type “_Hello World_” in the
command palette to spawn a new node.

---

## 3. Manifest Reference (`pfs-plugin.json`)

| Field                    | Type            | Required | Description                                                         |
|--------------------------|-----------------|----------|---------------------------------------------------------------------|
| `id`                     | string (scoped) | ✔        | Unique reverse-DNS identifier (`com.acme.markdown`)                 |
| `displayName`            | string          | ✔        | Human-readable name                                                 |
| `version`                | semver          | ✔        | Must follow semantic-versioning                                     |
| `publisher`              | string          | ✔        | Your registry publisher/org                                         |
| `main`                   | path            | ✔        | Relative path to compiled JS entry                                  |
| `icon`                   | path            | —        | 128×128 SVG/PNG shown in the marketplace                            |
| `description`            | string          | —        | Markdown short description                                          |
| `engines.paletteflow`    | semver range    | ✔        | Target PaletteFlow engine constraint                                |
| `contributes.nodes`      | string[]        | —        | Node types implemented (used for search)                            |
| `contributes.panels`     | string[]        | —        | Custom sidebar panels                                               |
| `activationEvents`       | string[]        | —        | Eager vs lazy loading (see below)                                   |
| `permissions`            | string[]        | —        | (`fs`, `clipboard`, `net`, etc.) prompts user on install            |

### Activation Events

By default, plugins load **on startup**. To reduce boot time you can defer
activation until a condition is met:

```json
"activationEvents": [
  "onCommand:workspace.export",
  "onNodeType:markdown.*",
  "onStartupFinished"
]
```

---

## 4. API Surface

The full type declarations live inside
`node_modules/paletteflow-sdk/dist/index.d.ts`; a quick overview:

```ts
interface PluginContext {
  subscriptions: Disposable[];
  workspace: WorkspaceGateway;
  logger: Logger;
  settings: SettingsStore;
  events: EventBus;           // 🔔 pub/sub
  ui: UIPortal;               // React render targets
}

export function registerNodeType<T extends CanvasNode>(
  ctor: NodeConstructor<T>
): () => void;

export function registerFileImporter(
  options: FileImporterDescriptor
): Disposable;

/* …plus dozens more (command palette, theme manager, telemetry) */
```

All APIs follow **Clean Architecture** principles: your plugin talks only to the
SDK, never to internal Electron or database layers.

---

## 5. Advanced Topics

### 5.1 State Machines

Plugins can attach a `StateMachine` to any node to drive animations,
long-running tasks, or multiplayer presence.

```ts
import { createMachine, assign } from 'xstate';
import { attachStateMachine } from 'paletteflow-sdk';

const timerMachine = createMachine({
  id: 'pomodoro',
  initial: 'idle',
  context: { seconds: 0 },
  states: {
    idle: {
      on: { START: 'running' }
    },
    running: {
      entry: assign({ seconds: 1500 }),
      on: {
        TICK: { actions: assign({ seconds: ctx => ctx.seconds - 1 }) },
        RESET: 'idle'
      },
      always: [{ target: 'idle', cond: ctx => ctx.seconds <= 0 }]
    }
  }
});

attachStateMachine('hello.world', timerMachine);
```

### 5.2 IPC & Background Workers

Long-running or privileged tasks (e.g. Git, network, AI inference) should be
moved to a **dedicated worker process** to keep the renderer snappy.

```ts
// main.ts ‑ Electron side
ipcMain.handle('git:status', async (_, repoPath) => {
  return await git.status(repoPath);
});

// renderer plugin
export async function getGitStatus(path: string) {
  return await ctx.ipc.invoke<string[]>('git:status', path);
}
```

---

## 6. Testing

PaletteFlow uses **Vitest** + **Jest-DOM**.  
Scaffolded plugins include a ready-made setup:

```bash
npm test                # unit tests
npm run test:integration # launches headless PaletteFlow
```

Example test:

```ts
import { renderNode } from 'paletteflow-sdk/test-utils';
import { HelloWorldNode } from '../src/nodes/HelloWorld';

test('renders default message', () => {
  const view = renderNode(HelloWorldNode);
  expect(view.getByText('Hello PaletteFlow 🎨')).toBeInTheDocument();
});
```

---

## 7. Publishing

1. Bump version in `pfs-plugin.json` & `package.json`.
2. `npm run build` – produce a clean `dist/` bundle.
3. `npm publish --access public`
4. Submit the resulting `tgz` in the **PaletteFlow Marketplace** dashboard.

Marketplace reviews automated security scans (dependency CVEs, static analysis,
sandboxing) before listing.

---

## 8. Security Guidelines

• Never ship obfuscated or minified sources – the CLI does that for you.  
• All network requests must respect the user’s proxy settings.  
• Do not write outside `ctx.paths.storage` unless `fs` permission is granted.  
• Use the provided `@paletteflow/crypto` utilities for encryption.

---

## 9. Troubleshooting

| Symptom                               | Likely Cause / Fix                              |
|---------------------------------------|-------------------------------------------------|
| Plugin never activates                | Check `activationEvents`; verify version range |
| `Cannot find module 'paletteflow-sdk'`| Run `npm install`; ensure peer dep satisfies   |
| Renderer freezes / high CPU           | Offload work to a worker thread                |
| “Permission denied” dialogs           | Declare `permissions` in `pfs-plugin.json`     |

---

## 10. Further Reading

* API Docs: <https://sdk.paletteflow.dev>
* Community Forum: <https://community.paletteflow.dev/plugins>
* Clean Architecture in PaletteFlow – internal whitepaper

Happy hacking – we can’t wait to see what you’ll create!  
_— The PaletteFlow Studio Team_ 🎨🚀
```