```markdown
# PaletteFlow Studio — Plugin SDK Documentation  
_Revision: v2.1 • Status: Stable • Minimum Studio Version: `>= 0.9.0`_

Welcome to the official documentation for the **PaletteFlow Studio Plugin SDK**.  
This guide covers everything you need to build, test, and publish palette plugins that extend the core application with _new node types, renderers, commands, file-importers, themes,_ and more.

> All examples are written in **TypeScript 5+** and assume that the plugin is being developed outside of the Studio repository using the published NPM package `@paletteflow/sdk`.

---

## Table of Contents
1. Motivation & Design Goals  
2. Quick Start (Hello-World Plugin)  
3. The Plugin Manifest (`paletteflow.plugin.json`)  
4. Runtime Lifecycle & API Surface  
5. Creating Custom Node Types  
6. Providing Custom Renderers  
7. Adding Palette Commands  
8. Listening to & Emitting Events  
9. Settings & Configuration Flow  
10. Error Handling & Logging  
11. Testing & Debugging Plugins  
12. Packaging & Publishing  
13. Advanced Topics  
14. Appendix: Complete Type Declarations  

---

## 1. Motivation & Design Goals

PaletteFlow is built on a _Clean Architecture_ foundation. The plugin system respects these boundaries by only exposing _application-level_ ports while keeping domain entities immutable and framework-agnostic.  
This design:

* Keeps the core safe from accidental mutations
* Guarantees forward compatibility via semantic-versioned contracts
* Encourages functional, side-effect-free patterns

---

## 2. Quick Start: “Hello Shapes” Plugin

A minimal plugin that registers a new node called **HelloShape** and draws a rectangle.

```bash
$ mkdir palette-hello-shapes && cd palette-hello-shapes
$ npm init -y
$ npm i @paletteflow/sdk
$ touch paletteflow.plugin.json src/index.ts
```

`paletteflow.plugin.json`
```jsonc
{
  "name": "@my-company/hello-shapes",
  "displayName": "Hello Shapes",
  "version": "1.0.0",
  "main": "dist/index.js",
  "minStudioVersion": "0.9.0",
  "permissions": ["canvas:read", "canvas:write"],
  "contributes": {
    "nodes": ["HelloShape"]
  }
}
```

`src/index.ts`
```ts
import {
  definePlugin,
  NodeContext,
  NodeShape,
  RendererAPI,
  log
} from '@paletteflow/sdk';

export default definePlugin({
  id: '@my-company/hello-shapes',
  init({ nodes, renderers, commands }) {
    // 1. Register a new Node schema
    nodes.register<NodeShape<HelloShapeData>>({
      type: 'HelloShape',
      version: 1,
      defaults: { text: 'Hello World!', color: '#60A5FA' }
    });

    // 2. Provide a renderer for the node
    renderers.register('HelloShape', (ctx: NodeContext<HelloShapeData>, api: RendererAPI) => {
      const { canvas } = api;
      const { text, color } = ctx.data;

      return (
        <g>
          <rect width={200} height={100} rx={8} fill={color} />
          <text
            x={100}
            y={55}
            font-size={16}
            font-family="Inter, sans-serif"
            text-anchor="middle"
            fill="white"
          >
            {text}
          </text>
        </g>
      );
    });

    // 3. Add a command for quick-insertion via the command palette
    commands.register({
      id: 'insert-hello-shape',
      title: 'Insert: Hello Shape',
      icon: '🎨',
      run: async ({ canvas }) => {
        const pos = await canvas.getViewportCenter();
        await canvas.nodes.create({ type: 'HelloShape', position: pos });
        log.info('HelloShape node created!');
      }
    });
  }
});

interface HelloShapeData {
  text: string;
  color: string;
}
```

Build with your favorite bundler (`tsup`, `esbuild`, `vite`, …) and drop the generated directory into **Studio → Preferences → Plugins → “Add from Folder”**.

---

## 3. The Plugin Manifest (`paletteflow.plugin.json`)

Key fields:

| Field              | Required | Description                                                         |
|--------------------|----------|---------------------------------------------------------------------|
| `name`             | ✔        | Scoped npm-style identifier.                                        |
| `displayName`      | —        | Human-friendly name (defaults to `name`).                           |
| `version`          | ✔        | Semantic version; validated by Studio.                              |
| `main`             | ✔        | Compiled entry point.                                               |
| `minStudioVersion` | ✔        | Range matching `app.getVersion()`. Prevents ABI mismatch.           |
| `permissions`      | —        | Granular capabilities (e.g. `fs`, `network`, `canvas:write`).       |
| `contributes`      | —        | Declarative hints (nodes, commands, settings) used for auto-docs.   |

Complete schema is exported as `ManifestSchema` in `@paletteflow/sdk/schema`.

---

## 4. Runtime Lifecycle & API Surface

```mermaid
graph TD
  A[Plugin Loaded] --> B(validateManifest)
  B --> C(import main)
  C --> D(call init(ctx))
  D --> E[PluginActive]
  E -->|hot-reload| D
  E --> F(unload)
```

The entry-point must export a `default` of `definePlugin(config)`.  
`init(ctx)` receives a **sandboxed API**, split into sub-namespaces:

* `nodes` – CRUD + schema validation
* `renderers` – React-like vnode returns via [Preact 10]
* `workspace` – Workspace-level actions
* `commands` – Register/deregister palette commands
* `events` – Observer bus (strong-typed via generics)
* `settings` – Persist user-configurable values
* `log` – Structured logger (levels: trace→fatal)

All cross-boundary calls are proxied through an _IPC bridge_ to keep Studio’s core process isolated.

---

## 5. Creating Custom Node Types

```ts
type KanbanCardData = {
  title: string;
  description: string;
  status: 'todo' | 'doing' | 'done';
};

nodes.register<NodeShape<KanbanCardData>>({
  type: 'KanbanCard',
  version: 2,
  migrate: (prev) => ({ ...prev, description: prev.description ?? '' }),
  defaults: { title: 'Untitled Card', description: '', status: 'todo' },
  validate(data, utils) {
    if (!utils.isNonEmptyString(data.title)) throw new Error('Title is required');
  }
});
```

### Hooks
* `onCreate`, `onUpdate`, `onDelete`
* `onDropExternalFile` – Allow drag’n’drop mapping

---

## 6. Providing Custom Renderers

Renderers run inside a WebWorker-driven _scene engine_, safe from DOM side-effects.  
They should be _pure functions_ that return **SVG VNodes**.

Performance Guidelines:
1. Avoid global state mutations.
2. Memoize expensive calculations via `ctx.memo`.
3. Keep re-render diff Δ < _1 ms_ per node for 60 fps smoothness.

---

## 7. Adding Palette Commands

Commands are globally searchable via **⌘ K**:

```ts
commands.register({
  id: 'workspace.export.png',
  title: 'Export Canvas as PNG',
  tags: ['export', 'image'],
  run: async ({ canvas, ui }) => {
    const file = await ui.showSaveDialog({ filters: [{ name: 'PNG', extensions: ['png'] }] });
    if (!file) return;
    await canvas.export.png(file);
    ui.toast.success('Canvas exported successfully 🎉');
  }
});
```

---

## 8. Listening to & Emitting Events

```ts
events.on('node:moved', ({ nodeId, newPosition }) => {
  log.debug(`Node ${nodeId} moved to`, newPosition);
});

// Custom events
events.emit<'my-plugin:focus-mode'>({ enabled: true });
```

Event types are centrally declared in `@paletteflow/sdk/events.d.ts`—augment them via [declaration merging](https://www.typescriptlang.org/docs/handbook/declaration-merging.html) for auto-complete.

---

## 9. Settings & Configuration Flow

```ts
const themeColor = settings.register<string>({
  key: 'themeColor',
  default: '#FFB703',
  scope: 'workspace', // 'global' | 'workspace'
  ui: {
    label: 'Theme Accent Color',
    component: 'color-picker'
  }
});

// Use reactive accessor
themeColor.onChange((v) => {
  workspace.setAccentColor(v);
});
```

Settings are persisted in JSON; Studio syncs _workspace-scoped_ values when exporting/importing `.pflow` archives.

---

## 10. Error Handling & Logging

The SDK exposes `tryCatch` helpers and [`zod`](https://zod.dev) for runtime validation.

```ts
import { guard } from '@paletteflow/sdk/utils';

commands.register({
  id: 'fetch-quote',
  title: 'Fetch Random Quote',
  run: guard(async ({ ui }) => {
    const res = await fetch('https://api.quotable.io/random').then(r => r.json());

    // Validate with Zod
    const Quote = z.object({ content: z.string() });
    const { content } = Quote.parse(res);

    ui.toast.info(`💡 "${content}"`);
  })
);
```

All uncaught exceptions are reported through the built-in crash reporter with automatic symbolication.

---

## 11. Testing & Debugging Plugins

1. `pnpm dlx studio-plugin-test` bundles ◦ launches a disposable Studio instance ◦ loads your plugin.
2. Enable **Developer Tools** in the menu for Chromium-based debugging.
3. Use `log.trace()`; messages appear under **Studio → Help → Logs**.

---

## 12. Packaging & Publishing

```jsonc
// package.json snippet
{
  "scripts": {
    "build": "tsup src/index.ts --dts --format cjs,esm",
    "prepublishOnly": "npm run build && npm test"
  }
}
```

Run:

```bash
$ npm publish --access public
```

Consumers can install via **Studio Marketplace** or by dragging the `.tgz` into the plugin pane.

---

## 13. Advanced Topics

• Embedding WASM modules  
• Incremental DOM diffing strategies  
• Off-main-thread audio analysis  
• Multi-canvas synchronization via WebRTC  

See the dedicated chapters at `/docs/plugin-api/advanced/*`.

---

## 14. Appendix: Condensed Type Declarations

```ts
// @paletteflow/sdk/index.d.ts (excerpt)

export interface PluginContext {
  version: string;
  nodes: NodeRegistry;
  renderers: RendererRegistry;
  commands: CommandRegistry;
  events: EventBus;
  settings: SettingsRegistry;
  workspace: WorkspaceAPI;
  log: Logger;
}

export declare function definePlugin(
  factory: (ctx: PluginContext) => void | Promise<void>
): void;

/** Generic JSON-serializable record. */
export type Plain = string | number | boolean | null | Plain[] | { [k: string]: Plain };

export interface NodeShape<D extends Plain = Plain> {
  type: string;
  version: number;
  defaults: D;
  validate?: (data: D, utils: ValidationUtils) => void;
  migrate?: (prev: unknown) => D;
}
```

---

Happy hacking! 💜  
Need help? Ping us on **Discord #plugins** or open an issue at  
`https://github.com/paletteflow/studio-plugin-sdk`.
```