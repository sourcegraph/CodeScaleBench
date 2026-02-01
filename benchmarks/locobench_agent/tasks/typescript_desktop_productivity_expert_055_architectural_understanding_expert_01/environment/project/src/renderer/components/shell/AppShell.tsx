```tsx
/* PaletteFlow Studio
 * src/renderer/components/shell/AppShell.tsx
 *
 * Application-level shell that boots the renderer process, wires global
 * concerns (IPC, settings, themes, plugin boot-strapping, auto-updates, …)
 * and renders the top-level UI scaffold (sidebar, canvas viewport, status
 * bar).  All feature screens are children of this component.
 */

import React, {
  FC,
  ReactNode,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { ipcRenderer, IpcRendererEvent } from 'electron';
import { ThemeProvider, createTheme, StyledEngineProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Snackbar from '@mui/material/Snackbar';
import MuiAlert, { AlertColor } from '@mui/material/Alert';
import { useHotkeys } from 'react-hotkeys-hook';

import { PluginManager } from '../../infra/plugins/PluginManager';
import { SettingsService } from '../../infra/settings/SettingsService';
import { ApplyTheme } from '../../../core/useCases/ApplyTheme';
import { PaletteFlowErrorBoundary } from '../shared/PaletteFlowErrorBoundary';

import { Sidebar } from './Sidebar';
import { CanvasViewport } from './CanvasViewport';
import { StatusBar } from './StatusBar';

////////////////////////////////////////////////////////////////////////////////
// Type declarations
////////////////////////////////////////////////////////////////////////////////

interface UpdateState {
  available: boolean;
  progress?: number;
  downloaded?: boolean;
}

interface SnackbarState {
  open: boolean;
  severity: AlertColor;
  message: string;
  autoHide?: number;
}

////////////////////////////////////////////////////////////////////////////////
// Constants
////////////////////////////////////////////////////////////////////////////////

const DEFAULT_SNACKBAR_STATE: SnackbarState = {
  open: false,
  severity: 'info',
  message: '',
  autoHide: 5000,
};

////////////////////////////////////////////////////////////////////////////////
// Component
////////////////////////////////////////////////////////////////////////////////

export const AppShell: FC = () => {
  /**************************************************************************
   * Local state
   *************************************************************************/
  const [muiTheme, setMuiTheme] = useState(() =>
    createTheme({
      palette: { mode: 'dark' },
    })
  );
  const [updateState, setUpdateState] = useState<UpdateState>({ available: false });
  const [snack, setSnack] = useState<SnackbarState>(DEFAULT_SNACKBAR_STATE);
  const [pluginsReady, setPluginsReady] = useState(false);

  /**************************************************************************
   * Handlers
   *************************************************************************/

  /** Raised by auto-updater IPC events */
  const handleUpdateAvailable = useCallback(() => {
    setUpdateState({ available: true });
    setSnack({
      open: true,
      severity: 'info',
      message: 'Update available — downloading in the background…',
    });
  }, []);

  const handleUpdateProgress = useCallback((_e: IpcRendererEvent, progress: number) => {
    setUpdateState((prev) => ({ ...prev, progress }));
  }, []);

  const handleUpdateDownloaded = useCallback(() => {
    setUpdateState({ available: true, downloaded: true });
    setSnack({
      open: true,
      severity: 'success',
      message: 'Update ready — restart PaletteFlow Studio to apply.',
      autoHide: 10000,
    });
  }, []);

  /** Crash reports from main process */
  const handleCrashReport = useCallback(
    (_e: IpcRendererEvent, error: { message: string }) => {
      setSnack({
        open: true,
        severity: 'error',
        message: `Renderer crash captured: ${error.message}`,
      });
    },
    []
  );

  /** Global error snackbar close */
  const handleSnackClose = useCallback(() => {
    setSnack((prev) => ({ ...prev, open: false }));
  }, []);

  /**************************************************************************
   * Effects
   *************************************************************************/

  /* IPC wiring */
  useEffect(() => {
    ipcRenderer.on('autoUpdate:available', handleUpdateAvailable);
    ipcRenderer.on('autoUpdate:download-progress', handleUpdateProgress);
    ipcRenderer.on('autoUpdate:downloaded', handleUpdateDownloaded);
    ipcRenderer.on('crash:report', handleCrashReport);

    return () => {
      ipcRenderer.removeListener('autoUpdate:available', handleUpdateAvailable);
      ipcRenderer.removeListener('autoUpdate:download-progress', handleUpdateProgress);
      ipcRenderer.removeListener('autoUpdate:downloaded', handleUpdateDownloaded);
      ipcRenderer.removeListener('crash:report', handleCrashReport);
    };
  }, [handleUpdateAvailable, handleUpdateDownloaded, handleUpdateProgress, handleCrashReport]);

  /* Load settings + theme on boot */
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const settings = await SettingsService.instance.getRendererSettings();
        const appTheme = await ApplyTheme.run(settings.theme as any); // domain use-case
        setMuiTheme(
          createTheme({
            palette: {
              mode: appTheme.mode,
              primary: { main: appTheme.primaryColor },
              secondary: { main: appTheme.accentColor },
            },
            typography: appTheme.typography,
          })
        );
      } catch (err) {
        console.error('Failed to load user settings:', err);
        setSnack({
          open: true,
          severity: 'error',
          message: 'Failed to load user settings — falling back to defaults.',
        });
      }
    };
    loadSettings();
  }, []);

  /* Boot plugins (async to avoid blocking first paint) */
  useEffect(() => {
    let cancelled = false;
    const bootPlugins = async () => {
      try {
        await PluginManager.instance.initializeRendererBridge();
        if (!cancelled) setPluginsReady(true);
      } catch (err) {
        console.error('Plugin system failed to initialize', err);
        setSnack({
          open: true,
          severity: 'error',
          message: '⚠️ Plugin system failed to initialize.',
        });
      }
    };
    bootPlugins();
    return () => {
      cancelled = true;
    };
  }, []);

  /**************************************************************************
   * Global keyboard shortcuts
   *************************************************************************/

  // Command Palette
  useHotkeys(
    'cmd+k,ctrl+k',
    () => {
      ipcRenderer.invoke('commandPalette:open');
    },
    { enableOnTags: ['INPUT', 'TEXTAREA'] },
    []
  );

  // Quick save
  useHotkeys('cmd+s,ctrl+s', () => ipcRenderer.invoke('workspace:save'), [], {
    enableOnTags: ['INPUT', 'TEXTAREA'],
  });

  /**************************************************************************
   * Memoized UI
   *************************************************************************/

  const LoadingSplash: ReactNode = useMemo(
    () => (
      <Box
        sx={{
          height: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'background.default',
        }}
      >
        <CircularProgress size={64} />
      </Box>
    ),
    []
  );

  if (!pluginsReady) {
    // Wait until plugins have been initialized before rendering the workspace;
    // otherwise plugin-provided node renderers would be missing.
    return LoadingSplash;
  }

  /**************************************************************************
   * Render
   *************************************************************************/

  return (
    <StyledEngineProvider injectFirst>
      <ThemeProvider theme={muiTheme}>
        <CssBaseline />
        {/* Top-level runtime error boundary */}
        <PaletteFlowErrorBoundary>
          <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
            {/* Static sidebar */}
            <Sidebar updateState={updateState} />

            {/* Main canvas viewport */}
            <Box component="main" sx={{ flexGrow: 1, position: 'relative' }}>
              {/* Lazy-load expensive editor modules */}
              <Suspense fallback={LoadingSplash}>
                <CanvasViewport />
              </Suspense>
            </Box>

            {/* Always-visible status bar */}
            <StatusBar />
          </Box>
        </PaletteFlowErrorBoundary>

        {/* Global snackbar for human-readable notifications */}
        <Snackbar
          open={snack.open}
          autoHideDuration={snack.autoHide ?? 5000}
          onClose={handleSnackClose}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <MuiAlert
            variant="filled"
            severity={snack.severity}
            onClose={handleSnackClose}
            elevation={6}
          >
            {snack.message}
          </MuiAlert>
        </Snackbar>
      </ThemeProvider>
    </StyledEngineProvider>
  );
};

////////////////////////////////////////////////////////////////////////////////
// Default export
////////////////////////////////////////////////////////////////////////////////

export default AppShell;
```
