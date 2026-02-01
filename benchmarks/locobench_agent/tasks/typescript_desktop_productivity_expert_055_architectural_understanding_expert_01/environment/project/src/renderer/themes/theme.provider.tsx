```tsx
/**************************************************************************
 *  PaletteFlow Studio – ThemeProvider
 *  File: renderer/themes/theme.provider.tsx
 *
 *  A React provider that exposes theming capabilities to the renderer
 *  process.  Themes come from three sources:
 *
 *    1. Built-in palettes shipped with the application
 *    2. User-installed plugins (via the palette-plugin system)
 *    3. OS / system settings (prefers-color-scheme, Electron nativeTheme)
 *
 *  Responsibilities:
 *    • Keep the active Theme in React state
 *    • Persist user selection in the SettingsRepository
 *    • React to system / IPC events to update the UI in real-time
 *    • Expose helper utilities (toggleDarkMode, registerTheme, etc.)
 *
 *  NOTE:
 *    – This provider purposefully does not depend on any specific UI
 *      library – it wraps around styled-components’ ThemeProvider if the
 *      latter is present.  This prevents tight-coupling to a single UI
 *      stack and allows legacy class-based components to consume the
 *      ThemeContext as well.
 **************************************************************************/

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  PropsWithChildren,
} from 'react';
import { ThemeProvider as StyledComponentsThemeProvider } from 'styled-components';
import { Theme } from '@core/domain/entities/Theme';
import { ApplyTheme } from '@core/use-cases/theme/ApplyTheme';
import { SettingsRepository } from '@core/domain/repositories/SettingsRepository';
import { useEventBus } from '../hooks/useEventBus';
import { pluginRegistry } from '../plugins/registry';
import logger from '../logger';

// ---------------------------------------------------------------------------
// Types & Interfaces
// ---------------------------------------------------------------------------

export interface ThemeContextValue {
  theme: Theme;
  availableThemes: ReadonlyArray<Theme>;
  applyTheme: (id: string) => Promise<void>;
  toggleDarkMode: () => Promise<void>;
  registerTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// ---------------------------------------------------------------------------
// Constants & Defaults
// ---------------------------------------------------------------------------

const FALLBACK_THEME_ID = 'paletteflow.default.light';
const BUILTIN_THEMES: Theme[] = [
  {
    id: FALLBACK_THEME_ID,
    name: 'Light',
    kind: 'light',
    palette: {
      background: '#ffffff',
      surface: '#f9f9f9',
      text: '#1a1a1a',
      primary: '#4a90e2',
      secondary: '#50e3c2',
      error: '#d0021b',
    },
  },
  {
    id: 'paletteflow.default.dark',
    name: 'Dark',
    kind: 'dark',
    palette: {
      background: '#18191c',
      surface: '#23262e',
      text: '#eef1f8',
      primary: '#4a90e2',
      secondary: '#50e3c2',
      error: '#ff5555',
    },
  },
];

// ---------------------------------------------------------------------------
// Helper hooks
// ---------------------------------------------------------------------------

/**
 * Returns the effective system theme (light | dark).
 */
const useSystemThemeKind = (): 'light' | 'dark' => {
  const [kind, setKind] = useState<'light' | 'dark'>(() => {
    if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return 'light';
  });

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (ev: MediaQueryListEvent) => setKind(ev.matches ? 'dark' : 'light');

    if (mq.addEventListener) {
      mq.addEventListener('change', handler);
    } else {
      // Safari & older versions
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      mq.addListener(handler);
    }
    return () => {
      if (mq.removeEventListener) {
        mq.removeEventListener('change', handler);
      } else {
        // eslint-disable-next-line @typescript-eslint/ban-ts-comment
        // @ts-ignore
        mq.removeListener(handler);
      }
    };
  }, []);

  return kind;
};

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export const ThemeProvider = ({ children }: PropsWithChildren<{}>): JSX.Element => {
  const settingsRepo = useMemo(() => new SettingsRepository(), []);
  const applyThemeUC = useMemo(() => new ApplyTheme(settingsRepo), [settingsRepo]);

  const [themes, setThemes] = useState<Theme[]>(() => [...BUILTIN_THEMES]);
  const [activeTheme, setActiveTheme] = useState<Theme>(() => {
    // attempt to restore persisted theme
    const storedId = settingsRepo.get<string>('appearance.themeId');
    const found = storedId && BUILTIN_THEMES.find((t) => t.id === storedId);
    return found ?? BUILTIN_THEMES[0];
  });

  const systemKind = useSystemThemeKind();
  const eventBus = useEventBus();

  // -----------------------------------------------------------------------
  // Dynamic theme registration (from plugins, experiments, etc.)
  // -----------------------------------------------------------------------
  const registerTheme = useCallback((theme: Theme): void => {
    setThemes((prev) => {
      if (prev.find((t) => t.id === theme.id)) return prev; // Already registered
      logger.debug(`[ThemeProvider] Registered new theme: ${theme.name} (${theme.id})`);
      return [...prev, theme];
    });
  }, []);

  // -----------------------------------------------------------------------
  // Apply theme
  // -----------------------------------------------------------------------
  const applyTheme = useCallback(
    async (id: string): Promise<void> => {
      const target = themes.find((t) => t.id === id);
      if (!target) {
        logger.warn(`[ThemeProvider] Attempted to apply unknown theme id ${id}`);
        return;
      }
      try {
        await applyThemeUC.execute(target); // Domain/business logic (updates workspace, nodes, etc.)
        settingsRepo.set('appearance.themeId', id);
        setActiveTheme(target);
        eventBus.emit('theme.changed', target);
        logger.debug(`[ThemeProvider] Applied theme: ${target.name}`);
      } catch (err) {
        logger.error('[ThemeProvider] Failed to apply theme', err);
      }
    },
    [applyThemeUC, settingsRepo, eventBus, themes],
  );

  // -----------------------------------------------------------------------
  // Toggle dark / light within same flavor if available
  // -----------------------------------------------------------------------
  const toggleDarkMode = useCallback(async (): Promise<void> => {
    const nextKind = activeTheme.kind === 'dark' ? 'light' : 'dark';
    const candidate =
      themes.find((t) => t.kind === nextKind && t.name === activeTheme.name) ??
      themes.find((t) => t.kind === nextKind);

    if (!candidate) {
      logger.warn('[ThemeProvider] No alternative theme available for toggleDarkMode.');
      return;
    }
    await applyTheme(candidate.id);
  }, [activeTheme, themes, applyTheme]);

  // -----------------------------------------------------------------------
  // Plugin integration – subscribe for theme registrations
  // -----------------------------------------------------------------------
  useEffect(() => {
    // Immediate registration for already-loaded plugins
    pluginRegistry.getThemes().forEach(registerTheme);

    // Live registration
    const dispose = pluginRegistry.onThemeRegistered(registerTheme);
    return dispose;
  }, [registerTheme]);

  // -----------------------------------------------------------------------
  // Automatic alignment to system preference (opt-in via settings)
  // -----------------------------------------------------------------------
  useEffect(() => {
    const alignWithSystem = settingsRepo.get<boolean>('appearance.followSystemTheme') ?? true;

    if (!alignWithSystem) return;

    const candidate = themes.find((t) => t.kind === systemKind);
    if (candidate && candidate.id !== activeTheme.id) {
      applyTheme(candidate.id).catch((err) =>
        logger.error('[ThemeProvider] Failed to auto-switch theme', err),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [systemKind]);

  // -----------------------------------------------------------------------
  // IPC bridge - listen to nativeTheme updates from main process
  // -----------------------------------------------------------------------
  useEffect(() => {
    const electron = (window as any).electron;
    if (!electron?.ipcRenderer) return;

    const handler = (_: unknown, payload: { kind: 'light' | 'dark' }) => {
      const alignWithSystem = settingsRepo.get<boolean>('appearance.followSystemTheme') ?? true;
      if (!alignWithSystem) return;

      const candidate = themes.find((t) => t.kind === payload.kind);
      if (candidate && candidate.id !== activeTheme.id) {
        applyTheme(candidate.id).catch((err) =>
          logger.error('[ThemeProvider] Failed to respond to nativeTheme update', err),
        );
      }
    };

    electron.ipcRenderer.on('nativeTheme.updated', handler);
    return () => {
      electron.ipcRenderer.removeListener('nativeTheme.updated', handler);
    };
  }, [activeTheme, themes, applyTheme, settingsRepo]);

  // -----------------------------------------------------------------------
  // Memoized context value
  // -----------------------------------------------------------------------
  const ctx: ThemeContextValue = useMemo(
    () => ({
      theme: activeTheme,
      availableThemes: themes,
      applyTheme,
      toggleDarkMode,
      registerTheme,
    }),
    [activeTheme, themes, applyTheme, toggleDarkMode, registerTheme],
  );

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  const MaybeSCThemeProvider = ({ children: inner }: PropsWithChildren<{}>) => {
    // Do not crash if styled-components is not used by the consumer
    if (!StyledComponentsThemeProvider) return <>{inner}</>;
    return <StyledComponentsThemeProvider theme={activeTheme}>{inner}</StyledComponentsThemeProvider>;
  };

  return (
    <ThemeContext.Provider value={ctx}>
      <MaybeSCThemeProvider>{children}</MaybeSCThemeProvider>
    </ThemeContext.Provider>
  );
};

// ---------------------------------------------------------------------------
// Hook helper
// ---------------------------------------------------------------------------

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme() must be used within a <ThemeProvider>');
  }
  return ctx;
}
```