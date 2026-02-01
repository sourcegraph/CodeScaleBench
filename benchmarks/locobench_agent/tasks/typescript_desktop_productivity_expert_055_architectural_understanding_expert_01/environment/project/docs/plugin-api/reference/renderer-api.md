```markdown
# PaletteFlow Studio Plugin SDK  
## Renderer API Reference

> Version: `@paletteflow/sdk ^0.5.0`

The **Renderer API** lets your plugin draw custom visuals for nodes and links at run-time.  
Renderers run **inside the renderer-process** of an Electron window and have no direct
access to NodeJS or OS primitives — everything goes through the strongly-typed SDK.

---

## At a Glance

```ts
import { definePlugin } from '@paletteflow/sdk';
import type {
  RendererFactory,
  RendererContext,
  PaletteRenderer,
} from '@paletteflow/sdk/renderer';

export default definePlugin(({ register }) => {
  // 1️⃣ Declare which domain objects you want to render
  register.renderer<NodePayload>('my-company/counter-node', counterRenderer);
});

/* ------------------------------------------------------------------ */
/*  counterRenderer.ts                                                */
/* ------------------------------------------------------------------ */

const counterRenderer: RendererFactory<NodePayload> = ctx => {
  // `ctx` is a RendererContext (see below)
  let count = 0;
  let root: HTMLDivElement;

  return {
    mount(container) {
      root = document.createElement('div');
      root.className = 'pf-counter-node';
      container.appendChild(root);
      render();
    },
    update(payload) {
      count = payload.value;
      render();
    },
    unmount() {
      root.remove();
    },
  };

  function render() {
    root.textContent = `🔢 ${count}`;
  }
};
```

---

## Import Paths

| Layer                 | Package                         | Path                                  |
| --------------------- | ------------------------------- | ------------------------------------- |
| Top-level re-export   | `@paletteflow/sdk`              | `import { … } from "@paletteflow/sdk"`|
| Renderer-only helpers | `@paletteflow/sdk/renderer`     | `import { … } from "@paletteflow/sdk/renderer"` |

All types documented below originate from `@paletteflow/sdk/renderer`.

---

## `RendererFactory<TPayload>`

```ts
export type RendererFactory<TPayload = unknown> =
  (ctx: RendererContext<TPayload>) => PaletteRenderer<TPayload>;
```

A **factory** that receives a `RendererContext` on first construction and must
return an object implementing the `PaletteRenderer` contract.

| Type parameter | Description                              |
|----------------|------------------------------------------|
| `TPayload`     | The shape of `.payload` for the node or link you render. |

---

## `RendererContext<TPayload>`

```ts
export interface RendererContext<TPayload = unknown> {
  /* ⚓️ Identification */
  readonly id: string;               // Unique per renderer instance
  readonly kind: 'node' | 'link';    // What you are rendering

  /* 📐 Layout & Viewport  */
  readonly bounds: Readonly<Rect>;   // In canvas coordinates
  getZoom(): number;                 // 1.0 = 100 %

  /* 🎨 Theming */
  readonly theme: Readonly<Theme>;   // Reactive (proxied) theme object
  onThemeChange(cb: (theme: Theme) => void): Disposer;

  /* 🎯 Selection & Hover */
  isSelected(): boolean;
  isHovered(): boolean;
  onSelectionChange(cb: (state: boolean) => void): Disposer;
  onHoverChange(cb: (state: boolean) => void): Disposer;

  /* 🔄 Reactivity helpers  */
  observe<T extends object>(value: T): DeepReadonly<T>;
  autorun(effect: () => void): Disposer;

  /* 💬 Command bus */
  dispatch(cmd: Command): Promise<CommandResult>;

  /* 🗂️ Raw domain data */
  readonly payload: Readonly<TPayload>;

  /* 📚 Utilities */
  openExternal(url: string): void;   // Opens in system browser
  t(key: string, params?: Record<string, any>): string; // i18n helper
}
```

All observer callbacks must return a **`Disposer`** (alias for `() => void`).

---

## `PaletteRenderer<TPayload>`

```ts
export interface PaletteRenderer<TPayload = unknown> {
  /**
   * Called exactly once. You should create DOM / Pixi / React roots here.
   */
  mount(target: HTMLElement): void | Promise<void>;

  /**
   * Called whenever the node’s payload or selection/hover state changed.
   * It receives the most recent `TPayload`.
   */
  update?(nextPayload: Readonly<TPayload>): void;

  /**
   * Called when the node disappears from the canvas (deleted, hidden,
   * tab switched, file closed, etc.). Clean up any listeners here.
   */
  unmount?(): void | Promise<void>;
}
```

If `update` is missing, PaletteFlow assumes the renderer is **static**.

---

## Lifecycle Diagram

```
 ┌──────────┐   mount()    ┌────────────┐   update()   ┌──────────────┐
 │  Factory │────────────►│  Renderer   │────────────►│  Renderer     │
 └──────────┘              │ (Mounted)  │◄────────────┤ (Still Active)│
                           └────────────┘              └─────┬────────┘
                                      ▲   unmount()          │
                                      └──────────────────────┘
```

---

## Example: React-based Renderer

The SDK ships with a very thin React 18 shim that handles mount/unmount
plumbing for you.

```ts
// src/renderers/NoteRenderer.tsx
import React from 'react';
import { createReactRenderer } from '@paletteflow/sdk/renderer/react';

interface NotePayload {
  text: string;
  color: string;
}

export default createReactRenderer<NotePayload>((ctx) => {
  // Hooks are allowed! The shim internally wraps you in <StrictMode>.
  const { payload, theme, isSelected } = ctx.useReactiveParams();

  return (
    <article
      style={{
        background: payload.color ?? theme.surface.primary,
        border: isSelected() ? `2px solid ${theme.accent}` : 'none',
        padding: '8px 12px',
        borderRadius: 6,
        fontFamily: theme.font.monospace,
      }}
    >
      <pre>{payload.text}</pre>
    </article>
  );
});
```

Register it in your plugin entrypoint:

```ts
register.renderer<NotePayload>('my-plugin/note', NoteRenderer);
```

---

## Error Handling

Renderers operate on an **isolate** event bus.  
Uncaught errors are sandboxed and shown to the user without crashing the
entire window.

Recommendations:

1. Wrap async work in `try/catch`.
2. Throw **typed** errors (`PaletteError`) so the host can deliver context.
3. Always guard DOM look-ups (`root && root.remove()`).

Example:

```ts
update(payload) {
  try {
    expensiveDiffAndPatch(root, payload);
  } catch (e) {
    ctx.dispatch({
      type: 'logger/error',
      message: `[CounterRenderer] Failed to patch DOM: ${(e as Error).message}`,
      scope: 'renderer',
    });
  }
}
```

---

## Performance Tips

• Prefer **update** over re-mounting to avoid animation flicker.  
• Subscribe to **only** the reactive signals you need (`observe`, `autorun`).  
• Dispose event listeners in `unmount` — leaking 1 listener per render can
  snowball in multi-window sessions.  
• Virtualize large DOM trees (e.g., use [`react-window`](https://react-window.vercel.app/))
  when rendering lists.

---

## Security Checklist

☑ Never eval user script.  
☑ Do not trust `payload` — validate before insertion to DOM (XSS).  
☑ Sanitize URLs passed into `<img>` or media tags.  
☑ Never hard-code absolute file paths; use `ctx.openExternal()`.

---

## Type Declarations

Below are the authoritative `d.ts` snippets generated from the latest SDK
build — useful if your editor fails to resolve types.

```ts
declare module '@paletteflow/sdk/renderer' {
  export interface Rect { x: number; y: number; width: number; height: number }
  export interface Theme { /* …snip… */ }
  export interface Command { type: string; [k: string]: any }
  export type CommandResult = { ok: true } | { ok: false; error: string };

  export interface RendererContext<T = unknown> { /* see above */ }
  export interface PaletteRenderer<T = unknown> { /* see above */ }
  export type RendererFactory<T = unknown> =
    (ctx: RendererContext<T>) => PaletteRenderer<T>;
  
  export const createReactRenderer:
    <T = unknown>(fn: (ctx: RendererContext<T>) => React.ReactElement)
      => RendererFactory<T>;
}
```

---

## Migration Guide

• **0.4 → 0.5**: `boundsChanged` signal was renamed to `onViewportChange`.  
• **0.3 → 0.4**: `dispatchCommand` → `dispatch`.  
• **0.2 → 0.3**: Renderers now receive `theme` proxy instead of raw JSON.  

Refer to `CHANGELOG.md` for a full diff.

---

## Contributing to the Renderer API

We ❤️ pull requests! If the API is missing a hook you need:

1. Open an issue titled **"[Renderer] Feature Request: X"**.  
2. Outline your use-case and a minimal interface sketch.  
3. The core team will triage within 3 business days.

---

© 2024 PaletteFlow Studio — Licensed under the Apache 2.0 License
```