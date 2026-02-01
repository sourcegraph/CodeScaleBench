```markdown
---
title: Nodes & Links
description: Learn how to create, edit, and super-charge Nodes and Links—the atomic building blocks of every PaletteFlow canvas.
sidebar_position: 3
---

# 03. Nodes & Links

PaletteFlow reimagines documents as living _flows_ of interconnected nodes.  
Where a traditional app gives you a single editor view, PaletteFlow gives you an **infinite canvas** where every idea is its own Node, and every relationship is a Link.

This chapter covers day-to-day usage as well as power-user techniques and plugin hooks.

---

## 1. Anatomy of a Node

| Part            | Description                                                                                  |
| --------------- | -------------------------------------------------------------------------------------------- |
| Header          | Displays the title, icon, status badge, and quick-action buttons (duplicate, branch, pin).   |
| Body            | Inline editor that switches automatically between Markdown, Vector, Code, Audio, etc.        |
| Ports           | Visual “sockets” on the left/right edge for drawing Links.                                   |
| Meta Panel      | Non-visual data such as tags, author, timestamps, and custom fields.                         |
| State Machine   | Hidden state graph (e.g. _Draft ↔ Review ↔ Done_) that can be customized or replaced.        |

A Node is more than a sticky note—it is an **embeddable mini-application**.  
Under the hood, each Node is backed by a domain entity:

```ts
// domain/canvas/Node.ts (simplified)
export interface Node {
  id: NodeId;
  kind: NodeKind;                      // 'markdown' | 'sketch' | 'audio' | ...
  title: string;
  body: unknown;                       // Editor-specific payload
  position: Vec2;                      // Canvas coordinates
  state: NodeState;                    // State machine value
  meta: Record<string, unknown>;       // Arbitrary plugin data
}
```

> 💡 Tip: Nodes are **framework-agnostic**. The same entity drives the Electron UI,
> CLI exporter, and the headless test runner.

### 1.1 Creating Nodes

Action                          | Shortcut                | Mouse / Touch
------------------------------- | ----------------------- | -------------
Quick Create Palette            | <kbd>Ctrl/Cmd</kbd>+<kbd>N</kbd> | Right-click canvas → “New Node”
Drag-Out (from existing Node)   | <kbd>Alt/Option</kbd> while dragging a port | —
Drop a file onto canvas         | — | Drag file(s) from OS

### 1.2 Editing Nodes

Inside a Node you enjoy _full-fat_ editors:

* Markdown → GitHub-flavored with live preview
* Code → Monaco with TypeScript IntelliSense
* Sketch → Bézier curves + boolean ops
* Audio → Waveform + basic trimming

Press <kbd>Esc</kbd> to toggle between **edit** and **navigate** mode.

---

## 2. Links — the semantic glue

A Link is a first-class citizen, not a mere arrow.  
It can carry metadata, state, and conditional styles.

```mermaid
flowchart LR
  A(["Feature Ideas"]) -- "blocks" --> B(["Spend Tracker\n(System)"])
  B -- "depends on" --> C["Budget API"]
  C -- "influences" -.-> A
```

### 2.1 Creating Links

1. Hover over a Node port until it glows.  
2. Drag to another Node (or empty canvas to create a new Node inline).  
3. Release → choose relationship type in the Link Palette.

Keyboard-first alternative:

1. Select source Node  
2. Press <kbd>L</kbd> → start link mode  
3. Type target Node title or `?` to open search  
4. Press <kbd>Enter</kbd>

### 2.2 Link Types

PaletteFlow ships with sane defaults:

Type          | Color | Semantics (Used by Task View, Exports, etc.)
------------- | ----- | ---------------------------------------------------------
`relates_to`  | Gray  | Weak association (non-blocking)
`blocks`      | Red   | Source must be completed **before** target
`depends_on`  | Blue  | Target provides capability used by source
`influences`  | Yellow| Soft directional influence (idea flow)

You can extend or override these via the **Link-Schema Plugin API** (see §4).

### 2.3 Styling & Routing

* Hold <kbd>Shift</kbd> while drawing to force an **orthogonal** path.
* Select one or more Links → press <kbd>.</kbd> to open the **Stroke Palette**  
  (line style, dash pattern, arrowheads).
* Double-click a Link label to edit rich-text annotations.

---

## 3. Queries & Smart Views

Links enable powerful graph queries:

Query                                    | How to run
--------------------------------------- | ------------
`outgoing:blocks from:"Deploy"`         | Command Palette → “Link Query…”
`path:"Design" to:"Launch"`             | Canvas context menu → “Highlight Path”
`cluster depends_on depth<=2`           | Sidebar → Smart Views → “+”

Query results manifest as **ad-hoc layers**—think Photoshop groups powered by graph logic.

---

## 4. Extending Nodes & Links via Plugins

PaletteFlow’s plugin architecture lets you ship new Node editors, state machines, and Link semantics without touching core code.

Below is a fully-working example that registers a _“Research Note”_ Node and a _“cites”_ Link type:

```ts
// plugins/research-note/index.ts
import {
  definePlugin,
  NodeKindRegistrar,
  LinkTypeRegistrar,
  css,
} from '@paletteflow/sdk';

export default definePlugin({
  id: 'com.acme.research-note',
  name: 'Research Note',

  onActivate({ api }) {
    /* ---------- Nodes ---------- */
    NodeKindRegistrar.register({
      kind: 'research-note',
      icon: 'flask',
      title: 'Research Note',
      initialState: () => ({
        markdown: '# Untitled Research\n\n> Start drafting…',
      }),
      editor: () => import('./ResearchNoteEditor'), // dynamic import
    });

    /* ---------- Links ---------- */
    LinkTypeRegistrar.register({
      type: 'cites',
      label: 'Cites',
      color: '#8e44ad',
      constraints: {
        // Only allow from research-note → research-note
        allowedPairs: [{ from: 'research-note', to: 'research-note' }],
      },
    });

    /* ---------- Theme ---------- */
    api.canvas.registerCss(
      css`
        .pf-link--cites {
          stroke-dasharray: 4 2;
          marker-end: url(#arrow-head);
        }
      `,
    );
  },
});
```

After placing the bundle in your `~/PaletteFlow/plugins` folder, restart the app and you’ll find:

* A new Node type in the Quick Create Palette.
* A purple, dashed **Cites** Link available in Link Palette.
* The Task View now hides **Cites** edges unless explicitly enabled.

> ⚠️ Remember to bump the plugin version on every change—PaletteFlow supports
> hot-reloading, but version conflicts will disable the plugin automatically.

---

## 5. Advanced: State Machines inside Nodes

Every Node carries a per-kind state machine (default: `Todo → Doing → Done`).  
Customize it:

1. Open Node Settings (<kbd>F3</kbd> or double-click icon).
2. Navigate to the “State Machine” tab.
3. Drag states/transitions or import a JSON schema.

Programmatically:

```ts
import { NodeKindRegistrar } from '@paletteflow/sdk';

NodeKindRegistrar.extend<'markdown'>('markdown', {
  stateMachine: {
    states: ['Draft', 'Review', 'Published'],
    transitions: {
      Draft: ['Review'],
      Review: ['Draft', 'Published'],
      Published: [],
    },
  },
});
```

The **Command Palette** automatically respects new states, giving you one-keystroke promotion/demotion.

---

## 6. Troubleshooting

Symptom                                   | Possible Cause & Fix
----------------------------------------- | ---------------------------------------------------------
Node won’t open in editor                 | Plugin conflict → run `Help ▸ Safe Mode`.  
Link can’t connect                        | Violates `allowedPairs` constraint → check Link type spec.  
Canvas feels sluggish with 1k+ Nodes      | Enable “Progressive Rendering” in Preferences → Performance.  
Links appear behind Nodes on export       | Export bug fixed in `v1.4.2` → update app.  

---

## 7. Cheatsheet

Shortcut / Action          | Description
---------------------------|------------
<kbd>Ctrl/Cmd</kbd>+<kbd>N</kbd> | Quick Create Node
<kbd>L</kbd>                | Start Link-draw mode (when a Node is selected)
<kbd>.</kbd>                | Stroke Palette (selected Link)
<kbd>Esc</kbd>              | Toggle edit ↔ navigate
<kbd>Space</kbd>+Drag       | Pan canvas
<kbd>Ctrl/Cmd</kbd>+Scroll  | Zoom

---

Ready to level up? Continue to [04-Command-Palette.md](./04-command-palette.md) to master PaletteFlow’s keyboard-first workflow.
```