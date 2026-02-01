```markdown
---
title: "Getting Started"
description: "A crash-course on installing PaletteFlow Studio, creating your first canvas, and extending the app with TypeScript plugins."
sidebar_position: 1
---

# 👋 Welcome to **PaletteFlow Studio**

PaletteFlow Studio is a next-generation creative productivity suite that lets you **think in shapes** instead of lines.  
This guide walks you through the essentials—from installation to authoring your first plugin—so you can start flowing in under **10 minutes**.

> **Prerequisites**  
> • macOS 11+, Windows 10+, or a modern Linux distribution  
> • Node.js ≥ 18 (for CLI tooling & plugin development)  
> • A GitHub account (optional, for auto-updates & crash reports)

---

## 1 / 3 Install the Desktop App 🚀

### Homebrew (macOS)

```shell
brew tap paletteflow/tap
brew install paletteflow-studio
```

### Winget (Windows)

```powershell
winget install PaletteFlow.Studio
```

### AppImage (Linux)

```shell
curl -L https://downloads.paletteflow.io/studio/latest/linux \
  -o PaletteFlowStudio.AppImage
chmod +x PaletteFlowStudio.AppImage && ./PaletteFlowStudio.AppImage
```

> ℹ️ The binary ships with **auto-updates** enabled (unless you disable it in *Settings → System*).

---

## 2 / 3 First Launch & Onboarding

1. **Open PaletteFlow Studio**.  
   A fresh *“Scratch Workspace”* is created automatically.
2. **Create a Node (`⌘/Ctrl + N`)**.  
   Choose between _Markdown_, _Sketch_, or _Audio_ editors.
3. **Link Nodes (`⌘/Ctrl + L`)**.  
   Drag from the right connector of one node onto another, or use the shortcut while two nodes are selected.  
   Links are *semantic*—they can be **tagged** (_“inspiration”_, _“blocked by”_, etc.) for richer queries.
4. **Explore the Command Palette (`⌘/Ctrl + K`)**.  
   Start typing “theme” to instantly switch visual styles or “export” to generate a PDF.

![Animated GIF showing node creation and linking](./assets/first-flow.gif)

---

## 3 / 3 Your First Plugin (5 Minutes)

PaletteFlow’s plugin system is built on **TypeScript decorators** and the **Command Pattern**.  
Below is a minimal plugin that adds a *“Countdown Node”* to your canvas.

```ts title="plugins/countdown-node/index.ts"
import {
  defineNode,
  NodeContext,
  registerRenderer,
  exposeCommand,
} from '@paletteflow/sdk';

@defineNode({
  type: 'countdown',
  title: '⏳ Countdown',
  icon: 'clock',
  // Default state
  state: { targetDate: new Date(Date.now() + 86_400_000) }, // +24h
})
export class CountdownNode {
  // Lifecycle hook: rendered in the right-hand inspector
  configure(ctx: NodeContext) {
    const { state, onUpdate } = ctx;

    // Render primitive inspector UI
    ctx.inspector.datePicker('Target Date', state.targetDate, (newDate) => {
      onUpdate({ targetDate: newDate });
    });
  }
}

// A lightweight renderer—uses the DOM API in Electron’s sandbox
registerRenderer('countdown', ({ state, mount }) => {
  const div = document.createElement('div');
  div.style.font = '600 18px/1.4 -apple-system, BlinkMacSystemFont, sans-serif';

  // Update loop
  const update = () => {
    const delta = state.targetDate.getTime() - Date.now();
    const hrs   = Math.max(0, Math.floor(delta / 36e5));
    const mins  = Math.max(0, Math.floor((delta % 36e5) / 6e4));
    const secs  = Math.max(0, Math.floor((delta % 6e4) / 1000));
    div.textContent = `${hrs}h ${mins}m ${secs}s`;
  };

  const timer = setInterval(update, 1000);
  update(); // initial paint

  mount(div);

  return () => clearInterval(timer); // renderer unmount
});

// Optional: add a command to spawn the node
exposeCommand({
  id: 'countdown.create',
  title: 'Insert Countdown Node',
  shortcut: '⌘⇧T',
  run: (api) => {
    api.canvas.createNode('countdown', { x: api.viewport.centerX, y: api.viewport.centerY });
  },
});
```

### Register the Plugin

1. Create a folder called `plugins` anywhere in your workspace.  
2. Add a `package.json`:

```json
{
  "name": "@acme/countdown-node",
  "version": "1.0.0",
  "main": "index.ts",
  "paletteflow": {
    "displayName": "Countdown Node",
    "minStudioVersion": ">=1.2.0"
  }
}
```

3. From the command palette, run **“Developer: Reload Plugins”**.  
   Your new node type will appear under **⌘/Ctrl + N → Custom**.

> 📖 More examples live in the [`examples/`](https://github.com/paletteflow/studio/tree/main/examples) directory.

---

## CLI Quick-Start

PaletteFlow ships with a companion CLI for automation and CI/CD workflows.

```bash
npx paletteflow workspace export ./my-workspace --format pdf --output report.pdf
```

CLI commands map 1-to-1 with use-cases like `CreateNode`, `ApplyTheme`, and `ExportWorkspace`.

---

## Configuration Reference

`paletterc.json` (dotfile at the workspace root):

```json5
{
  // Disable anonymous crash telemetry
  "telemetry": false,

  // Override update channel (alpha | beta | stable)
  "updates": "beta",

  // Default theme for new workspaces
  "theme": "dracula"
}
```

Changes are hot-reloaded across all open windows thanks to the **Observer Pattern** baked into the settings service.

---

## Troubleshooting & FAQ

| Issue | Fix |
| ----- | --- |
| **App doesn’t start on macOS Sonoma** | Run `xattr -dr com.apple.quarantine /Applications/PaletteFlow\ Studio.app` |
| **Plugins fail to compile** | Ensure `tsconfig.json` targets **ES2022** and enable `isolatedModules` |
| **Canvas feels laggy with 1000+ nodes** | Toggle *“Performance Mode”* in *View* → *Rendering* |

If you’re stuck, join our Discord (`#support`) or file a ticket on GitHub.  
Crash logs are automatically attached if **Telemetry** is enabled.

---

## Next Steps

1. Deep-dive into **Canvas Architecture** (_Docs → Core Concepts_).  
2. Learn advanced **Keyboard-Driven Workflows** (⌘/Ctrl + K & type `learn`).  
3. Explore **Palette Marketplace** for community-driven plugins and themes.

Happy flowing! 🌈
```