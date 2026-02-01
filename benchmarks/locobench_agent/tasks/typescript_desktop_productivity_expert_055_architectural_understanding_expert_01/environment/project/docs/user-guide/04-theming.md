```markdown
---
id: user-guide-theming
title: 🎨 Theming Your Workspaces
sidebar_label: 04 · Theming
description: Learn how to apply, create, and distribute custom themes in PaletteFlow Studio.
---

> “Design is not just what it looks like and feels like. Design is how it **flows**.”  
> — *Unknown Flowonaut*

PaletteFlow Studio ships with an industrial–strength theming system that lets you recolor and restyle virtually every pixel—without forking the code-base.  
Whether you’re a dark-mode purist, running a brand-sponsored color scheme, or shipping a plugin that needs bespoke node skins, this guide has you covered.

---

## 1. Theme Fundamentals

A **Theme** in PaletteFlow Studio is a serializable object that contains:

| Key             | Type                         | Purpose                                  |
| --------------- | ---------------------------- | ---------------------------------------- |
| `meta`          | `ThemeMeta`                  | Identifies author, version, license, etc.|
| `tokens`        | `ThemeTokenRegistry`         | Raw design tokens (colors, sizes, fonts) |
| `components`    | `Partial<ComponentStyles>`   | Optional overrides per UI component      |
| `nodeSkins`     | `Record<NodeType, SkinDef>`  | Optional skins for custom node types     |
| `extends`       | `string \| string[]`         | Name(s) of base themes to inherit from   |

The **domain layer** treats a theme purely as data (`Theme` entity).  
At runtime, the **MVVM presentation layer** combines active themes into a computed `ResolvedTheme` and exposes it via the reactive `theme$` observable.

> ℹ️  Multiple themes can be stacked (think CSS cascade). User-selected theme sits on top, followed by workspace theme, then plugin contributions, and finally the *Base Light* / *Base Dark* defaults.

---

## 2. Applying a Theme

### 2.1 Via Command Palette (Recommended)

1. Press **⌘/Ctrl + K** to open the Command Palette.  
2. Type **“Switch Theme”** and hit **Enter**.  
3. Browse the live preview list ↑ ↓ and press **Enter** again to apply.

> The change is instantaneous and applies to all open windows that share the same workspace profile.

### 2.2 Per-Workspace Auto-Load

Every workspace folder can include an optional `.paletteflow/theme.json`.  
When the workspace is opened, the file is resolved relative to the workspace root and applied automatically.

### 2.3 Programmatically — Use-Case API

If you are authoring an **Electron adapter**, **CLI script**, or **headless test runner**, call the `ApplyTheme` use-case:

```ts
import { ApplyTheme } from '@paletteflow/core/use-cases/appearance/ApplyTheme'
import { ThemeJsonLoader } from '@paletteflow/infrastructure/io/ThemeJsonLoader'

async function bootstrap(): Promise<void> {
  const themePath = '/path/to/dracula.json'
  const theme = await ThemeJsonLoader.load(themePath)

  await ApplyTheme.execute({
    theme,
    scope: 'global',          // "global" | "workspace" | "window"
    persist: true,            // Save to ~/.paletteflow/settings.json
  })
}
```

Error handling follows the standard `Result<T, E>` pattern used across the code-base, so failed themes never crash the UI.

---

## 3. Authoring Custom Themes

### 3.1 Quick-Start With the Theme Builder

1. Open the **Settings → Appearance** panel.  
2. Click **“Create New Theme”** → “Duplicate Current Theme”.  
3. Tweak your color tokens, preview in real-time.  
4. Hit **Export** to save as `.json`—ready to share or publish.

### 3.2 DIY JSON Schema

All themes conform to the `ThemeSchema` JSON schema, so you get auto-completion in most editors.

```jsonc
{
  "$schema": "https://paletteflow.dev/schema/theme.v2.json",
  "meta": {
    "name": "Dracula PRO",
    "author": "Jane Doe",
    "version": "2.1.0",
    "license": "MIT"
  },
  "tokens": {
    "color.background.canvas": "#282a36",
    "color.foreground.text-primary": "#f8f8f2",
    "color.accent.primary": "#ff79c6",
    "radius.node": 6,
    "font.family.monospace": "Fira Code"
  },
  "components": {
    "Button": {
      "borderRadius": "{radius.node}",
      "background": "{color.accent.primary}",
      "foreground": "{color.foreground.text-primary}"
    }
  }
}
```

Tokens can **reference each other** using `{…}` placeholders, which are resolved lazily for maximum flexibility.

### 3.3 Advanced: Supplying a JavaScript Theme Module

When you need dynamic logic (e.g., auto-switch based on system clock), export a `ThemeProvider`:

```ts
// nocturnal-theme.ts
import { Theme } from '@paletteflow/core/entities/Theme'

export default function provide(): Theme {
  const isNight = new Date().getHours() >= 18
  return isNight ? nightTheme : dayTheme
}
```

Place the file inside any folder listed in **Settings → Paths → Custom Theme Folders**.

> ⚠️  Keep heavy, synchronous operations out of `ThemeProvider`—it runs on the renderer thread.

---

## 4. Theming in Plugins

Plugins can bundle private themes or expose tokens to host themes.

1. Add a `theme` folder in your plugin package.
2. Reference themes in your `manifest.json`:

```jsonc
{
  "id": "com.acme.graphviz",
  "version": "3.0.0",
  "themes": [
    "theme/graphviz-light.json",
    "theme/graphviz-dark.json"
  ],
  "contributes": {
    "nodeTypes": ["graphviz.diagram"]
  }
}
```

3. In your renderer code, pull current theme tokens via the **observer pattern**:

```ts
/** Renderer (ViewModel) **/
import { theme$ } from '@paletteflow/core/state/theme'

theme$.subscribe(resolved => {
  const accent = resolved.tokens['color.accent.primary']
  updateSVGStroke(accent)
})
```

> The `theme$` stream emits debounced updates, so feel free to subscribe liberally.

---

## 5. Frequently Asked Questions

**Q:** “Why didn’t my custom font apply?”  
**A:** Make sure you list the font in both `font.family.*` tokens *and* install it system-wide (or bundle via plugin).

**Q:** “How can I reset to defaults?”  
**A:** Run **`Preferences: Reset Theme`** from the Command Palette, or delete `~/.paletteflow/settings.json → appearance.theme`.

**Q:** “Can I override just the canvas background?”  
**A:** Yes—create a minimal theme containing only `tokens.color.background.canvas` and apply it at the *workspace* scope.

---

## 6. Troubleshooting

| Symptom                                               | Remedy                                                       |
| ----------------------------------------------------- | ------------------------------------------------------------ |
| Theme JSON fails validation                           | Run `pnpx ajv validate -s schema/theme.v2.json -d your.json` |
| Unknown token reference `{foo.bar}`                   | Ensure `foo.bar` exists *and* matches the correct casing.    |
| UI flickers when switching rapidly                    | File an issue—repaint batching should prevent this.          |
| Node skin not applied after plugin install            | Restart PaletteFlow Studio (plugin assets hot-reload WIP).   |

---

## 7. Next Steps

• Continue to **05 · Keyboard Shortcuts** for maximizing efficiency.  
• Explore the **Theme Marketplace** inside the app to discover community creations.  
• Contribute to theming docs by editing this very file—PRs welcome!

Happy Flow-ming! 🖌️
```