```typescript
/**
 * PaletteFlow Studio – Renderer entry point
 * -----------------------------------------
 * This file bootstraps the React renderer that lives inside each Electron
 * BrowserWindow.  Responsibilities:
 *   • Wire global crash-reporting + error boundaries
 *   • Hydrate UI theme coming from persisted user settings
 *   • Dynamically discover & register renderer-side plugins
 *   • Forward high-level IPC messages as UI events (auto-update banner, etc.)
 *   • Expose a “command bus” to React components so they can execute
 *     domain use-cases without depending on Electron specifics.
 */

import React, {
  createContext,
  PropsWithChildren,
  ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { createRoot } from 'react-dom/client';
import * as Sentry from '@sentry/electron/renderer';
import { ipcRenderer, IpcRendererEvent } from 'electron';
import { ThemeProvider } from 'styled-components';
import { GlobalStyles } from './styles/GlobalStyles';
import { lightTheme, darkTheme } from './styles/themes';
import { executeUseCase } from '../shared/commandBus';
import type {
  Command,
  CommandResult,
} from '../shared/commandBus/types';
import {
  RendererPlugin,
  RendererPluginExports,
} from '../shared/pluginSystem/types';
import { notifications } from './ui/components/Notifications';
import { UpdateBanner } from './ui/components/UpdateBanner';

// ---------------------------
// Crash reporting & analytics
// ---------------------------
Sentry.init({
  dsn: 'https://public@sentry.io/123456',
  tracesSampleRate: 1.0,
});

// ---------------------------
// Theme context
// ---------------------------
type ThemeKind = 'light' | 'dark' | 'system';

interface ThemeContextValue {
  themeKind: ThemeKind;
  setThemeKind: (t: ThemeKind) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const ThemeProviderWithSystem: React.FC<PropsWithChildren> = ({
  children,
}) => {
  const getInitial = (): ThemeKind => {
    const stored = window.localStorage.getItem('pfs.theme');
    if (stored === 'light' || stored === 'dark' || stored === 'system')
      return stored;
    return 'system';
  };

  const [themeKind, setThemeKind] = useState<ThemeKind>(getInitial);

  // Persist to localStorage for next launch
  useEffect(() => {
    window.localStorage.setItem('pfs.theme', themeKind);
  }, [themeKind]);

  // Listen to OS theme changes if user chose “system”
  const [systemPrefersDark, setSystemPrefersDark] =
    useState<boolean>(window.matchMedia('(prefers-color-scheme: dark)').matches);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const listener = (e: MediaQueryListEvent) => setSystemPrefersDark(e.matches);
    mq.addEventListener('change', listener);
    return () => mq.removeEventListener('change', listener);
  }, []);

  const theme = useMemo(
    () =>
      themeKind === 'light'
        ? lightTheme
        : themeKind === 'dark'
        ? darkTheme
        : systemPrefersDark
        ? darkTheme
        : lightTheme,
    [themeKind, systemPrefersDark],
  );

  const value: ThemeContextValue = useMemo(
    () => ({ themeKind, setThemeKind }),
    [themeKind],
  );

  return (
    <ThemeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <GlobalStyles />
        {children}
      </ThemeProvider>
    </ThemeContext.Provider>
  );
};

// --------------------------------
// Command Bus (MVVM / Use-Case API)
// --------------------------------
interface CommandBusContextValue {
  dispatch<T = unknown, R = CommandResult>(
    command: Command<T>,
  ): Promise<R>;
}

const CommandBusContext =
  createContext<CommandBusContextValue | null>(null);

const CommandBusProvider: React.FC<PropsWithChildren> = ({
  children,
}) => {
  const dispatch = useCallback(
    async <T, R>(command: Command<T>): Promise<R> => {
      try {
        // Leverage shared implementation that proxies IPC or runs directly
        return (await executeUseCase(command)) as R;
      } catch (err) {
        Sentry.captureException(err);
        notifications.error(
          `Could not execute: ${command.type}`,
          (err as Error).message,
        );
        throw err;
      }
    },
    [],
  );

  const value = useMemo(() => ({ dispatch }), [dispatch]);

  return (
    <CommandBusContext.Provider value={value}>
      {children}
    </CommandBusContext.Provider>
  );
};

// ----------------------
// Plugin bootstrapping
// ----------------------
async function loadRendererPlugins(): Promise<RendererPluginExports[]> {
  // Renderer preloader passes discovered plugin paths through context-isolated
  // global wrapped in window.__pfsPreload
  const preload = (window as any).__pfsPreload;
  if (!preload || typeof preload.getRendererPlugins !== 'function')
    return [];
  const pluginMetas: RendererPlugin[] = preload.getRendererPlugins();

  const loaded: RendererPluginExports[] = [];

  for (const meta of pluginMetas) {
    try {
      // Dynamically import ES module; Webpack’s externals config keeps them
      // as files next to main bundle so they are resolved at runtime.
      const mod: RendererPluginExports = await import(/* @vite-ignore */ meta.entryPath);
      if (typeof mod.mount === 'function') {
        mod.mount();
      }
      loaded.push(mod);
    } catch (e) {
      console.error('Failed to load plugin', meta, e);
      Sentry.captureException(e, {
        tags: { subsystem: 'plugin-loader', pluginId: meta.id },
      });
      notifications.error(`Plugin “${meta.manifest.name}” failed to load`, e);
    }
  }

  return loaded;
}

// ------------------------
// Auto-update & IPC bridge
// ------------------------
function wireAutoUpdateBanners(setUpdateReady: (b: boolean) => void) {
  const onUpdateDownloaded = () => {
    setUpdateReady(true);
  };

  ipcRenderer.on('update-downloaded', onUpdateDownloaded);
  ipcRenderer.send('renderer-ready', { pid: process.pid });

  return () => {
    ipcRenderer.removeListener('update-downloaded', onUpdateDownloaded);
  };
}

// ----------------------
// Fatal Error Boundary
// ----------------------
class CrashBoundary extends React.Component<
  PropsWithChildren<{}>,
  { hasError: boolean; error?: Error }
> {
  constructor(props: PropsWithChildren<{}>) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(err: Error) {
    return { hasError: true, error: err };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    Sentry.captureException(error, {
      extra: { componentStack: info.componentStack },
    });
  }

  render(): ReactElement | null {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: 32,
            fontFamily: 'Inter, sans-serif',
            lineHeight: 1.6,
          }}
        >
          <h1>Something went wrong.</h1>
          <pre style={{ color: '#c00' }}>
            {this.state.error?.message ?? 'Unknown'}
          </pre>
          <p>
            The PaletteFlow team has been notified. You can safely restart the
            application, or{" "}
            <button onClick={() => ipcRenderer.invoke('app-relaunch')}>
              Relaunch now
            </button>
            .
          </p>
        </div>
      );
    }
    return this.props.children as ReactElement;
  }
}

// -------------------------
// Root Application Shell
// -------------------------
const App: React.FC = () => {
  const [pluginsReady, setPluginsReady] = useState(false);
  const [updateReady, setUpdateReady] = useState(false);

  useEffect(() => {
    // Kick off lazy plugin loading
    loadRendererPlugins().finally(() => setPluginsReady(true));

    // Setup IPC listeners
    const cleanup = wireAutoUpdateBanners(setUpdateReady);
    return cleanup;
  }, []);

  if (!pluginsReady) {
    return (
      <div style={{ padding: 24 }}>Loading plugins and workspace…</div>
    );
  }

  return (
    <>
      {/* Actual routed views live inside MainRouter */}
      <React.Suspense fallback={<div>Loading UI…</div>}>
        {/* Lazy-loaded to reduce TTI */}
        {React.createElement(
          React.lazy(() => import('./ui/MainRouter')),
        )}
      </React.Suspense>

      {/* Global notification portal */}
      {notifications.portal}

      {/* Auto-update banner */}
      <UpdateBanner visible={updateReady} />
    </>
  );
};

// ------------------------
// Render to the DOM
// ------------------------
function render() {
  const container = document.getElementById('root');
  if (!container) {
    throw new Error('#root element missing in index.html');
  }
  const root = createRoot(container);

  root.render(
    <CrashBoundary>
      <ThemeProviderWithSystem>
        <CommandBusProvider>
          <App />
        </CommandBusProvider>
      </ThemeProviderWithSystem>
    </CrashBoundary>,
  );
}

render();

// Hot-module replacement (Dev only)
if (module.hot) {
  module.hot.accept('./ui/MainRouter', () => {
    render();
  });
}

// ---------------
// Global typings
// ---------------

declare global {
  // Provided by preload script, defined in /electron/preload.ts
  interface Window {
    __pfsPreload?: {
      getRendererPlugins(): RendererPlugin[];
    };
  }
}
```