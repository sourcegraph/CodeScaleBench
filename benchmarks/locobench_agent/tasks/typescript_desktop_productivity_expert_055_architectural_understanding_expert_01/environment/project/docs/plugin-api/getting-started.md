```markdown
# PaletteFlow Studio – Plugin API: Getting Started
Welcome to the **PaletteFlow Studio Plugin SDK**!  
This guide walks you through creating, running, and distributing your first PaletteFlow
plugin with production-grade TypeScript, strong typing, and clean-architecture
principles.

> Minimum Studio version: **v1.8.0**  
> Minimum Node version: **18.16.0 LTS** (ESM enabled)  
> Tested on macOS 13+, Windows 11, and Ubuntu 22.04

---

## 1. Why plugins?

PaletteFlow’s core is intentionally minimal.  
Everything “extra”—from CSV importers to
Kanban renderers—is delivered as a plugin so that:

* You ship features decoupled from the core upgrade cycle
* Designers remix functionality without forking
* Enterprise teams keep sensitive code private

---

## 2. Prerequisites

1. Install the **PaletteFlow CLI** (ships with the desktop bundle):

   ```bash
   $ pf --version
   PaletteFlow CLI v1.8.3
   ```

2. Globally enable **TypeScript** and **ESBuild** (optional but recommended):

   ```bash
   npm i -g typescript esbuild
   ```

3. Configure an editor with `tsconfig.json` path-mapping
   (see “Type safety” below).

---

## 3. Scaffold a plugin

Run the generator:

```bash
pf plugin init my-first-plugin
```

This creates:

```
my-first-plugin/
├─ paletteflow.plugin.json   # Manifest
├─ src/
│  ├─ index.ts               # Entry point
│  ├─ MyRainbowNode.ts       # Domain node object
│  └─ RainbowRenderer.tsx    # React renderer (optional)
├─ test/
│  └─ integration.spec.ts
├─ tsconfig.json
└─ README.md
```

---

## 4. The manifest – `paletteflow.plugin.json`

```jsonc
{
  // Unique, reverse-DNS identifier
  "id": "studio.example.rainbow",
  "name": "🌈 Rainbow Nodes",
  "version": "0.1.0",
  "author": "Jane Dev",
  "main": "dist/index.js",
  // Studio compatibility, semver range
  "engines": {
    "paletteflow": ">=1.8.0 <2.0.0"
  },
  // Optional: npm deps automatically bundled
  "dependencies": {
    "chroma-js": "^2.4.2"
  }
}
```

---

## 5. Implement the entry point – `src/index.ts`

```ts
import type {
  PalettePlugin,
  PluginContext,
  NodeRegistrar,
  CommandRegistrar,
  Logger
} from '@paletteflow/sdk';

/**
 * Entry function called by the host during plugin loading.
 *
 * DO NOT execute side-effects at file top-level. Studio loads
 * plugins in a sandbox; deferred execution is required so that
 * plugin unloading works correctly in hot-reload mode.
 */
const plugin: PalettePlugin = async (ctx: PluginContext): Promise<void> => {
  const log = ctx.logger.createScope('rainbow');

  // 1️⃣ Register a new node type
  await registerRainbowNode(ctx.nodes, log);

  // 2️⃣ Attach custom renderer (optional – only if you need bespoke UI)
  await attachRainbowRenderer(ctx.renderers, log);

  // 3️⃣ Expose command palette actions
  await registerCommands(ctx.commands, log);

  log.info('Rainbow plugin initialised ✅');
};

export default plugin;

// ---------------------------------------------------------------------------
// Implementation details
// ---------------------------------------------------------------------------

async function registerRainbowNode(reg: NodeRegistrar, log: Logger) {
  const definition = await import('./MyRainbowNode.js');
  reg.registerType(definition.RainbowNode);
  log.debug('Node type "RainbowNode" registered');
}

async function attachRainbowRenderer(reg: any, log: Logger) {
  // Renderers live in optional peerDep `@paletteflow/react-sdk`
  const { RainbowRenderer } = await import('./RainbowRenderer.js');
  reg.registerRenderer('studio.example.rainbow.node', RainbowRenderer);
  log.debug('Renderer attached');
}

async function registerCommands(reg: CommandRegistrar, log: Logger) {
  reg.add({
    id: 'rainbow.toggle-mode',
    title: 'Rainbow: Toggle Disco Mode 🪩',
    icon: 'mdi-party-popper',
    run: async ({ studio }) => {
      const current = studio.settings.get('rainbow.disco', false);
      await studio.settings.set('rainbow.disco', !current);
      studio.toast.success(`Disco mode ${!current ? 'enabled' : 'disabled'}!`);
    }
  });

  log.debug('Command registered');
}
```

Key takeaways:

* Prefer **async imports** to avoid eager dependency loading.
* Always log through `ctx.logger`; never `console.log` in production!
* The plugin function **must default-export** an
  `async (ctx) => void` signature.

---

## 6. Creating a domain node – `src/MyRainbowNode.ts`

```ts
import { z } from 'zod';
import {
  BaseNode,
  NodeFactory,
  EditableField,
  Color,
  NodeSchema
} from '@paletteflow/sdk';

/**
 * Runtime schema validates persisted JSON.
 * Version it so migrations can happen automatically.
 */
export const RainbowNodeSchema: NodeSchema = {
  version: 1,
  shape: z.object({
    label: z.string().default('New Rainbow 🌈'),
    hue: z.number().min(0).max(360).default(180)
  })
};

/**
 * Domain entity – zero UI assumptions.
 */
export class RainbowNode extends BaseNode<typeof RainbowNodeSchema> {
  static readonly type = 'studio.example.rainbow.node';

  protected readonly schema = RainbowNodeSchema;

  // Visual affordances for the built-in editor sidebar
  static editable: EditableField[] = [
    { key: 'label', label: 'Label', type: 'text' },
    { key: 'hue', label: 'Hue', type: 'slider', min: 0, max: 360 }
  ];

  get colors(): Color[] {
    const { hue } = this.state;
    // Converts HSL wheel to pleasing pastel palette
    return [...Array(5)].map((_, i) => ({
      h: (hue + i * 30) % 360,
      s: 0.5,
      l: 0.6
    }));
  }
}

/**
 * NodeFactory required so that the host can lazily instantiate
 * nodes from JSON blobs fetched from storage.
 */
export const factory: NodeFactory = {
  type: RainbowNode.type,
  schema: RainbowNodeSchema,
  create: (initial) => new RainbowNode(initial)
};
```

---

## 7. (Optional) A custom renderer – `src/RainbowRenderer.tsx`

```tsx
import React from 'react';
import { NodeRendererProps } from '@paletteflow/react-sdk';
import chroma from 'chroma-js';

export const RainbowRenderer: React.FC<NodeRendererProps> = ({ node }) => {
  const colors = (node as any).colors ?? [];
  return (
    <div
      style={{
        width: 160,
        height: 120,
        borderRadius: 8,
        display: 'flex',
        overflow: 'hidden',
        boxShadow: '0 1px 4px rgba(0,0,0,.2)'
      }}
    >
      {colors.map((c: any, i: number) => (
        <div
          key={i}
          style={{
            flex: 1,
            background: chroma.hsl(c.h, c.s, c.l).hex()
          }}
        />
      ))}
    </div>
  );
};
```

---

## 8. Build & run

1. Inside the plugin root:

   ```bash
   npm install
   npm run build           # tsc + esbuild
   ```

2. Link the plugin into your local Studio:

   ```bash
   pf plugin link .
   ```

3. Start PaletteFlow Studio; open **Plugins → Reload & Restart**.  
   Open the command palette (`⌘ ⇧ P` / `Ctrl ⇧ P`) and type “Rainbow”.

---

## 9. Hot-reloading (dev mode)

`pf plugin dev` spins up a file watcher with
instant HMR (requires Studio ≥ v1.9):

```bash
pf plugin dev --open
```

_edits compile → Studio reloads only the affected plugin._
Logs stream in a docked console.

---

## 10. Type safety & versioning tips

* Pin `@paletteflow/sdk` in **both** plugin `package.json` and `devDependencies`
  to the same exact version; mismatches cause schema drift.
* Use `@tsconfig/strictest` base configs.
* Prefer **Zod** schemas (already peer-dependenced) for validation.

---

## 11. Distribution

1. Create a ZIP of the compiled `dist/` plus `paletteflow.plugin.json`.
2. Publish to the **PaletteFlow Registry**:

   ```bash
   pf plugin publish --token $PF_REGISTRY_TOKEN
   ```

   The CLI validates, lints, scans for vulnerabilities, then signs the bundle.
3. Alternatively, hand people the ZIP; they can `pf plugin install file.zip`.

---

## 12. Security model

Plugins run in a hardened Electron sandbox:

* No `nodeIntegration` – you must use the exposed API bridge.
* File-system access requires explicit user grant per-path.
* Network calls are proxied through a CORS safelist.

Request additional permissions in `paletteflow.plugin.json`:

```jsonc
{
  "permissions": {
    "fs": ["read", "write"],
    "net": ["https://api.example.com"]
  }
}
```

---

## 13. Troubleshooting

| Symptom                                  | Fix                                                         |
| ---------------------------------------- | ----------------------------------------------------------- |
| “Plugin loaded but nothing happens”      | Verify `default export` is **async function** not `object`. |
| `ERR_PLUGIN_VERSION_MISMATCH`            | Align `engines.paletteflow` with your Studio version.       |
| `401 Registry auth` on publish           | Check `PF_REGISTRY_TOKEN` env variable.                     |
| Blank renderer in canvas                 | Ensure `renderer.registerRenderer` type matches node type.  |

---

## 14. Next steps

* Read the **Complete API Reference** (`docs/plugin-api/reference.md`)
* Explore advanced topics:  
  ‑ Node-to-node **state machines**,  
  ‑ **Custom toolbars** & inspectors,  
  ‑ Embedding **WebAssembly** workers.
* Join the #plugins channel on Discord for community help.

Happy flowing! 🎨
```