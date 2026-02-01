```typescript
/**
 * PaletteFlow Studio – Theme Hook
 * =================================
 * This hook is responsible for:
 *  • Keeping track of the currently–selected UI theme (light / dark / custom)
 *  • Sync-ing changes across multiple Electron windows via IPC
 *  • Reacting to system “prefers-color-scheme” while respecting user overrides
 *  • Registering / de-registering plugin-provided themes at runtime
 *  • Persisting the user preference through the SettingsService
 *
 * The hook exposes both a React Context provider (ThemeProvider) and a
 * convenience hook (useTheme) that returns the current theme alongside a set
 * of imperative helper methods.
 */

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { ipcRenderer } from 'electron';
import mitt, { Emitter } from 'mitt';

import { Theme } from '@core/domain/Theme';
import { applyTheme } from '@core/use-cases/ApplyTheme';

import settingsService from '../services/settingsService';
import { getPluginThemes } from '../plugins/themeRegistry';

const BUILTIN_LIGHT: Theme = {
  id: 'builtin-light',
  name: 'Light',
  variables: {
    '--pf-background': '#ffffff',
    '--pf-on-background': '#1c1c1c',
    '--pf-primary': '#3662ff',
  },
  isDark: false,
  source: 'builtin',
};

const BUILTIN_DARK: Theme = {
  id: 'builtin-dark',
  name: 'Dark',
  variables: {
    '--pf-background': '#181a1b',
    '--pf-on-background': '#f7f7f7',
    '--pf-primary': '#5b7dff',
  },
  isDark: true,
  source: 'builtin',
};

type ThemeEventMap = {
  'theme:changed': Theme;
  'theme:registered': Theme;
  'theme:unregistered': string; // themeId
};

const emitter: Emitter<ThemeEventMap> = mitt<ThemeEventMap>();

/* -------------------------------------------------------------------------- */
/* 🎨 React Context                                                           */
/* -------------------------------------------------------------------------- */

interface ThemeContextValue {
  theme: Theme;
  availableThemes: Theme[];
  setTheme: (themeId: string) => void;
  toggleDarkMode: () => void;
  registerTheme: (theme: Theme) => void;
  unregisterTheme: (themeId: string) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/* -------------------------------------------------------------------------- */
/* 🪝 Hook Implementation                                                     */
/* -------------------------------------------------------------------------- */

interface Props {
  children: ReactNode;
}

export const ThemeProvider = ({ children }: Props) => {
  /* ------------------------ Gather Available Themes ----------------------- */
  const [registry, setRegistry] = useState<Record<string, Theme>>(() => {
    const pluginThemes = getPluginThemes().reduce<Record<string, Theme>>(
      (acc, theme) => {
        acc[theme.id] = theme;
        return acc;
      },
      {},
    );

    return {
      [BUILTIN_LIGHT.id]: BUILTIN_LIGHT,
      [BUILTIN_DARK.id]: BUILTIN_DARK,
      ...pluginThemes,
    };
  });

  /* --------------------------- Current Theme ------------------------------ */
  const [theme, setThemeState] = useState<Theme>(() => {
    // 1. User-saved preference
    const savedId = settingsService.get<string>('ui.theme');
    if (savedId && registry[savedId]) return registry[savedId];

    // 2. Follow system
    const prefersDark =
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches;

    return prefersDark ? BUILTIN_DARK : BUILTIN_LIGHT;
  });

  /* ------------------------ Persist + Apply Theme ------------------------- */
  const persistAndApply = useCallback(
    async (t: Theme) => {
      try {
        await settingsService.set('ui.theme', t.id);
      } catch (err) {
        // Non-fatal, silently fail (settings service might be unavailable in
        // sandboxed renderer processes).
        console.error('SettingsService: failed to persist theme', err);
      }

      // Apply css-vars through the domain use-case
      try {
        await applyTheme(t);
      } catch (err) {
        console.error('Failed to apply theme', err);
      }

      // Broadcast to sibling windows
      ipcRenderer.send('theme:changed', t.id);
      emitter.emit('theme:changed', t);
    },
    [],
  );

  /* ------------------------------ Set Theme ------------------------------- */
  const setTheme = useCallback(
    (themeId: string) => {
      const next = registry[themeId];
      if (!next) {
        console.warn(`Attempted to select unknown theme: ${themeId}`);
        return;
      }
      setThemeState(next);
      persistAndApply(next).catch(console.error);
    },
    [registry, persistAndApply],
  );

  /* ------------------------- Toggle Light / Dark -------------------------- */
  const toggleDarkMode = useCallback(() => {
    const fallback = theme.isDark ? BUILTIN_LIGHT : BUILTIN_DARK;
    const next =
      Object.values(registry).find(
        (t) => t.isDark !== undefined && t.isDark !== theme.isDark,
      ) || fallback;
    setTheme(next.id);
  }, [theme, registry, setTheme]);

  /* ---------------------- (Un)Register Plugin Themes ---------------------- */
  const registerTheme = useCallback((t: Theme) => {
    setRegistry((prev) => {
      if (prev[t.id]) return prev; // already registered
      const next = { ...prev, [t.id]: t };
      emitter.emit('theme:registered', t);
      return next;
    });
  }, []);

  const unregisterTheme = useCallback((themeId: string) => {
    setRegistry((prev) => {
      if (!prev[themeId]) return prev;
      const { [themeId]: _, ...next } = prev;
      emitter.emit('theme:unregistered', themeId);
      return next;
    });
  }, []);

  /* ----------------------- React to System Theme -------------------------- */
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (ev: MediaQueryListEvent) => {
      // Respect user override: only auto-switch if preference is built-in light/dark
      const isUserDefault =
        theme.id === BUILTIN_LIGHT.id || theme.id === BUILTIN_DARK.id;
      if (!isUserDefault) return;

      const next = ev.matches ? BUILTIN_DARK : BUILTIN_LIGHT;
      setTheme(next.id);
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [theme, setTheme]);

  /* --------------- Listen to IPC (multi-window synchronization) ----------- */
  useEffect(() => {
    const listener = (_: unknown, themeId: string) => {
      if (registry[themeId]) {
        setThemeState(registry[themeId]);
      }
    };
    ipcRenderer.on('theme:changed', listener);
    return () => {
      ipcRenderer.removeListener('theme:changed', listener);
    };
  }, [registry]);

  /* ----------------- Apply theme once when provider mounts ---------------- */
  useEffect(() => {
    persistAndApply(theme).catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* --------------------- Derived Memoized Values -------------------------- */
  const contextValue = useMemo<ThemeContextValue>(
    () => ({
      theme,
      availableThemes: Object.values(registry),
      setTheme,
      toggleDarkMode,
      registerTheme,
      unregisterTheme,
    }),
    [
      theme,
      registry,
      setTheme,
      toggleDarkMode,
      registerTheme,
      unregisterTheme,
    ],
  );

  return (
    <ThemeContext.Provider value={contextValue}>
      {children}
    </ThemeContext.Provider>
  );
};

/* -------------------------------------------------------------------------- */
/* 📌 Consumer Hook                                                           */
/* -------------------------------------------------------------------------- */

export const useTheme = (): ThemeContextValue => {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error(
      'useTheme must be used inside a <ThemeProvider>. Make sure your component is wrapped correctly.',
    );
  }
  return ctx;
};

/* -------------------------------------------------------------------------- */
/* 🛠  Non-React Utility (for imperative callers / plugins)                   */
/* -------------------------------------------------------------------------- */

/**
 * Allows non-React code (e.g. command palette, plugin scripts) to subscribe to
 * theme changes without having to import React.
 *
 * Example:
 *    themeEvents.on('theme:changed', (theme) => console.log(theme.name));
 */
export const themeEvents = emitter;
```