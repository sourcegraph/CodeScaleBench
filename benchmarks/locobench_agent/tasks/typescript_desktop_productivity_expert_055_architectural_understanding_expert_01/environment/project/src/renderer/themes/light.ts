```typescript
/**
 * PaletteFlow Studio – Light Theme
 *
 * This file defines and registers the canonical “light” theme used by the
 * renderer process.  The object is immutable and exposed through the global
 * ThemeRegistry so that it can be swapped at runtime by the ApplyTheme
 * use-case and queried by palette plugins.
 */

import { systemPreferences, nativeTheme } from 'electron';
import tinycolor from 'tinycolor2';
import { ThemeRegistry } from '../themeRegistry';

/* ────────────────────────────────────────────────────────────────────────── */
/* Types                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

/** Primitive colors referenced in the design system. */
export interface Palette {
  background: string;        // Main application background
  surface: string;           // Cards, panels, nodes
  elevatedSurface: string;   // Pop-ups, dialogs
  stroke: string;            // Non-interactive borders
  divider: string;           // Hairline separators

  /** Accent-driven system colors. */
  primary: string;
  primaryHover: string;
  primaryActive: string;

  success: string;
  warning: string;
  error: string;

  /** Typography colors. */
  textPrimary: string;
  textSecondary: string;
  textDisabled: string;
  textInverted: string;
}

/** Scalable typography tokens. */
export interface TypographyScale {
  fontFamily: string;
  fontSizeBase: number;
  scale: Record<'xs' | 'sm' | 'md' | 'lg' | 'xl', number>;
  weight: Record<'light' | 'regular' | 'medium' | 'bold', number>;
}

/** Tokens that drive the infinite canvas renderer. */
export interface CanvasTokens {
  node: {
    background: string;
    border: string;
    headerBackground: string;
    headerText: string;
    shadow: string;
  };
  link: {
    stroke: string;
    hovered: string;
    selected: string;
  };
}

export interface ThemeTokens {
  name: string;
  palette: Palette;
  typography: TypographyScale;
  canvas: CanvasTokens;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Helpers                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Safely retrieves the OS accent color, if available.
 * Returns undefined on unsupported platforms or when the call fails.
 */
function getSystemAccentColor(): string | undefined {
  try {
    if (process.platform === 'win32' && systemPreferences?.getAccentColor) {
      // Returns a hex string without the leading '#'
      return `#${systemPreferences.getAccentColor()}`;
    }

    if (nativeTheme?.accentColor) {
      return nativeTheme.accentColor; // Already includes '#'
    }
  } catch {
    /* ignore */
  }

  return undefined;
}

/** Deep-freeze to avoid accidental runtime mutations by plugins. */
function deepFreeze<T extends Record<string, any>>(obj: T): Readonly<T> {
  Object.keys(obj).forEach((key) => {
    const value = obj[key];
    if (value && typeof value === 'object') deepFreeze(value);
  });
  return Object.freeze(obj);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Theme construction                                                       */
/* ────────────────────────────────────────────────────────────────────────── */

const DEFAULT_ACCENT = '#3D7CFF'; // PaletteFlow brand blue
const accent = tinycolor(getSystemAccentColor() ?? DEFAULT_ACCENT).toHexString();

const palette: Palette = {
  background: '#F5F5F7',
  surface: '#FFFFFF',
  elevatedSurface: '#FFFFFF',
  stroke: '#D0D0D5',
  divider: 'rgba(60, 60, 67, 0.12)',

  primary: accent,
  primaryHover: tinycolor(accent).lighten(12).toHexString(),
  primaryActive: tinycolor(accent).darken(8).toHexString(),

  success: '#27C93F',
  warning: '#FFB020',
  error: '#FF453A',

  textPrimary: '#1C1C1E',
  textSecondary: '#3A3A3C',
  textDisabled: '#8E8E93',
  textInverted: '#FFFFFF',
};

const typography: TypographyScale = {
  fontFamily: `'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif`,
  fontSizeBase: 14,
  scale: { xs: 0.75, sm: 0.875, md: 1, lg: 1.25, xl: 1.5 },
  weight: { light: 300, regular: 400, medium: 500, bold: 700 },
};

const canvas: CanvasTokens = {
  node: {
    background: palette.surface,
    border: palette.stroke,
    headerBackground: palette.primaryHover,
    headerText: palette.textPrimary,
    shadow: '0 2px 6px rgba(0, 0, 0, 0.06)',
  },
  link: {
    stroke: palette.primary,
    hovered: palette.primaryHover,
    selected: palette.primaryActive,
  },
};

const lightTheme: ThemeTokens = deepFreeze({
  name: 'light',
  palette,
  typography,
  canvas,
});

/* ────────────────────────────────────────────────────────────────────────── */
/* Registration                                                             */
/* ────────────────────────────────────────────────────────────────────────── */

try {
  ThemeRegistry.register(lightTheme);
} catch (err) {
  // Registration errors are non-fatal.  We log once for diagnostics.
  // eslint-disable-next-line no-console
  console.error('[PaletteFlow] Failed to register Light theme:', err);
}

export default lightTheme;
```