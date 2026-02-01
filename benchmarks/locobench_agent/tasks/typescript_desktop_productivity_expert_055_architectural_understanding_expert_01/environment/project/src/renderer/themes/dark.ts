```typescript
/**
 * PaletteFlow Studio — Dark Theme
 * --------------------------------
 * This file lives in the renderer-layer because it ultimately mutates the
 * browser DOM and therefore must not leak into the domain layer.  All the
 * values below should be treated as *presentation* details only.
 */

import { ipcRenderer } from 'electron';
import tinycolor from 'tinycolor2';
import { ThemeRegistry } from '../services/theme-registry';
import { deepFreeze } from '../utils/object';

/* -------------------------------------------------------------------------- */
/*                                 Contracts                                  */
/* -------------------------------------------------------------------------- */

/**
 * A minimal subset of design-tokens required by the renderer.  The exact same
 * interface is also implemented by user-defined palette plugins and therefore
 * MUST stay backwards-compatible.
 */
export interface RendererTheme {
  /** Unique key (e.g. `"dark"`).  Must match the folder name in `/themes`. */
  id: string;
  /** Translatable name shown in the UI (Command Palette, Settings, …). */
  displayName: string;

  tokens: {
    /* ------------------------------ Base tokens --------------------------- */
    background: string;
    surface: string;
    surfaceAlt: string;
    text: string;
    textSubtle: string;
    accent: string;
    accentHover: string;
    border: string;
    focusOutline: string;

    /* ------------------------------ State tokens -------------------------- */
    success: string;
    warning: string;
    error: string;
  };

  /**
   * Optional code-syntax coloring.  Keys intentionally match PrismJS token
   * names so that we can apply them straight to the highlighted markup.
   */
  syntax?: Record<string, string>;
}

/* -------------------------------------------------------------------------- */
/*                             Helper utilities                               */
/* -------------------------------------------------------------------------- */

/**
 * Inject the provided tokens as CSS variables on the `<html>` element.  This
 * makes them accessible from plain CSS, Web-Components, Monaco, etc.
 */
function injectCssVariables(theme: RendererTheme): void {
  const root = document.documentElement;

  const flatten = (
    obj: Record<string, any>,
    prefix: string[] = [],
    result: Record<string, string> = {},
  ) => {
    Object.entries(obj).forEach(([k, v]) => {
      if (typeof v === 'object') {
        flatten(v, [...prefix, k], result);
      } else {
        const cssVar = `--pf-${[...prefix, k].join('-')}`;
        result[cssVar] = String(v);
      }
    });
    return result;
  };

  const cssVars = flatten(theme.tokens);

  Object.entries(cssVars).forEach(([name, value]) => {
    root.style.setProperty(name, value);
  });

  if (theme.syntax) {
    Object.entries(theme.syntax).forEach(([token, color]) => {
      root.style.setProperty(`--pf-syntax-${token}`, color);
    });
  }
}

/**
 * Automatically create a hover color by lightening the given base color.  We
 * stick to HSL manipulation because end-users tend to perceive it as more
 * “natural” compared to RGB tweaks.
 */
function createHoverColor(base: string, amount = 6): string {
  return tinycolor(base).lighten(amount).toHexString();
}

/* -------------------------------------------------------------------------- */
/*                            Theme ‑- Definition                             */
/* -------------------------------------------------------------------------- */

const dark: RendererTheme = deepFreeze({
  id: 'dark',
  displayName: 'Dark',

  tokens: {
    background: '#181A1F',
    surface: '#202329',
    surfaceAlt: '#2B2F36',
    text: '#F5F7FA',
    textSubtle: '#A8AEBA',
    accent: '#46A0FC',
    accentHover: createHoverColor('#46A0FC'),
    border: '#3B4048',
    focusOutline: '#5F9BFF',

    success: '#27C46A',
    warning: '#F6C744',
    error: '#E55757',
  },

  syntax: {
    comment: '#5C6370',
    string: '#98C379',
    keyword: '#C678DD',
    number: '#D19A66',
    function: '#61AFEF',
    boolean: '#56B6C2',
    operator: '#ABB2BF',
  },
});

/* -------------------------------------------------------------------------- */
/*                            Theme ‑- Lifecycle                              */
/* -------------------------------------------------------------------------- */

ThemeRegistry.register(dark);

/**
 * Expose a small imperative helper for scenarios where theming must happen
 * outside of the usual MVVM-binding cycle (e.g. right after the `<webview>`
 * tag swaps documents, before React renders again).
 */
export function applyDarkTheme(): void {
  injectCssVariables(dark);

  // Notify other renderer-process windows so they keep in sync.
  // We intentionally broadcast inside the renderer because PaletteFlow allows
  // *multiple* workspaces to be open in different windows, each with its own
  // theme context.
  ipcRenderer.send('theme:changed', dark.id);
}

/* -------------------------------------------------------------------------- */
/*                            Auto-apply on import                            */
/* -------------------------------------------------------------------------- */

/**
 * Immediately apply when the module is imported.  This is mostly convenient
 * for tests and storybook, but end-users may override the theme later via the
 * Settings screen.
 */
if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', () => applyDarkTheme());
} else {
  applyDarkTheme();
}

/* -------------------------------------------------------------------------- */
/*                                 Re-exports                                 */
/* -------------------------------------------------------------------------- */

export { dark as DarkTheme };
export default dark;
```