```tsx
/**
 * PaletteFlow Studio — Renderer Root
 * ----------------------------------
 * This file bootstraps the React renderer that powers every window in the
 * desktop-application.  Responsibilities handled here:
 *
 *   1.  Configure top-level providers (theme, preferences, plugins, command palette)
 *   2.  Wire IPC channels for auto-update & crash reporting
 *   3.  Expose a robust error boundary that funnels uncaught errors into the
 *       domain-level CrashAnalytics use-case
 *   4.  Mount window routes (canvas, settings, crash reporter, …)
 *
 * The renderer is completely framework-agnostic beyond React itself—i.e. no
 * domain logic leaks into this layer.  Instead, all business rules live in the
 * core domain and are reached via IPC calls to the main process or through the
 * in-memory message bus exposed by the plugin host.
 */

import React, {
  FC,
  Suspense,
  ReactNode,
  useEffect,
  PropsWithChildren,
} from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ipcRenderer, IpcRendererEvent } from 'electron';
import { ThemeProvider } from 'styled-components';

import GlobalStyles from './styles/GlobalStyles';
import { lightTheme, darkTheme } from './styles/themes';

import {
  PreferencesProvider,
  usePreferences,
} from './providers/PreferencesProvider';
import {
  PluginProvider,
  PluginHostRuntime as PluginHost,
} from './providers/PluginProvider';
import { CommandPaletteProvider } from './providers/CommandPaletteProvider';
import { NotificationCenter, notify } from './components/NotificationCenter';
import { Spinner } from './components/Spinner';
import { ErrorBoundary } from './components/ErrorBoundary';

/* ------------------------------------------------
 *  Code-split heavy windows
 * ------------------------------------------------ */
const CanvasWindow    = React.lazy(() => import('./windows/CanvasWindow'));
const SettingsWindow  = React.lazy(() => import('./windows/SettingsWindow'));
const CrashReporter   = React.lazy(() => import('./windows/CrashReporter'));

/* ------------------------------------------------
 *  Hooks
 * ------------------------------------------------ */

/**
 * useAutoUpdater
 * Listen for auto-update events coming from the main process and surface them
 * through the in-app notification system.
 */
const useAutoUpdater = (): void => {
  const { preferences } = usePreferences();

  useEffect(() => {
    if (!preferences.autoUpdates) return;

    const handleUpdateAvailable = (
      _evt: IpcRendererEvent,
      meta: { version: string },
    ) => {
      notify({
        id: 'update-available',
        title: 'Update available',
        message: `PaletteFlow ${meta.version} is now downloading in the background…`,
        variant: 'info',
      });
    };

    const handleUpdateDownloaded = (
      _evt: IpcRendererEvent,
      meta: { version: string },
    ) => {
      notify({
        id: 'update-downloaded',
        title: 'Update ready',
        message: `Restart to install PaletteFlow ${meta.version}.`,
        variant: 'success',
        actions: [
          {
            label: 'Restart now',
            onClick: () => ipcRenderer.send('app/restart-to-update'),
          },
        ],
      });
    };

    ipcRenderer.on('auto-update:available', handleUpdateAvailable);
    ipcRenderer.on('auto-update:downloaded', handleUpdateDownloaded);

    return () => {
      ipcRenderer.removeListener('auto-update:available', handleUpdateAvailable);
      ipcRenderer.removeListener('auto-update:downloaded', handleUpdateDownloaded);
    };
  }, [preferences.autoUpdates]);
};

/* ------------------------------------------------
 *  Helpers
 * ------------------------------------------------ */

interface ThemedProps extends PropsWithChildren<unknown> {}

/**
 * Themed – injects styled-components theme based on user preferences.
 */
const Themed: FC<ThemedProps> = ({ children }) => {
  const {
    preferences: { theme },
  } = usePreferences();

  return (
    <ThemeProvider theme={theme === 'dark' ? darkTheme : lightTheme}>
      {children}
    </ThemeProvider>
  );
};

/* ------------------------------------------------
 *  Application Shell
 * ------------------------------------------------ */

const AppRoutes: FC = () => (
  <Suspense fallback={<Spinner />}>
    <Routes>
      <Route path="/" element={<CanvasWindow />} />
      <Route path="/settings/*" element={<SettingsWindow />} />
      <Route path="/crash" element={<CrashReporter />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </Suspense>
);

const AppShell: FC = () => {
  useAutoUpdater();

  return (
    <>
      <Router>
        <AppRoutes />
      </Router>
      <NotificationCenter />
      {/* PluginHost runs headlessly to service background tasks */}
      <PluginHost />
    </>
  );
};

/* ------------------------------------------------
 *  Root Component
 * ------------------------------------------------ */

/**
 * App
 * Wraps the entire renderer hierarchy with global providers and error boundary.
 */
export const App: FC = () => (
  <ErrorBoundary>
    <PreferencesProvider>
      <Themed>
        <PluginProvider>
          <CommandPaletteProvider>
            <GlobalStyles />
            <AppShell />
          </CommandPaletteProvider>
        </PluginProvider>
      </Themed>
    </PreferencesProvider>
  </ErrorBoundary>
);

/* ------------------------------------------------
 *  Bootstrap
 * ------------------------------------------------ */

document.addEventListener('DOMContentLoaded', () => {
  const rootElem = document.getElementById('root');

  if (!rootElem) {
    // If the root container is missing, there is nothing we can do—fail fast.
    // eslint-disable-next-line no-console
    console.error(
      '[Renderer] Could not find #root element—renderer failed to mount.',
    );
    return;
  }

  const root = createRoot(rootElem);
  root.render(<App />);
});
```