```typescript
/**************************************************************************************************
 * PaletteFlow Studio – Electron Main Process Entry Point
 *
 * This file bootstraps the desktop application, wiring together:
 *   • Electron lifecycle
 *   • Multi-window management
 *   • Auto-update & crash-reporting
 *   • Dynamic plugin discovery
 *   • IPC channels that expose clean-architecture use-cases to renderer processes
 *
 * NOTE: Do not place business-rule code here.  Keep this file focused on process orchestration and
 * adapter wiring.  All domain logic lives in the /core or /use-case layers.
 *************************************************************************************************/

import { app, BrowserWindow, ipcMain, dialog, shell, CrashReporter, nativeTheme } from 'electron';
import { autoUpdater } from 'electron-updater';
import path from 'node:path';
import url from 'node:url';
import { once } from 'node:events';
import { readFile } from 'node:fs/promises';

import { AppConfig } from '../common/config/AppConfig';                 // Shared config access
import { PluginManager } from './plugins/PluginManager';                // Runtime plugin loader
import { MenuBuilder } from './ui/MenuBuilder';                         // Application menu
import { WindowStateKeeper } from './ui/WindowStateKeeper';             // Persists per-window size
import { registerIpcHandlers } from './ipc/IpcRegistry';                // Expose backend services
import { logger } from './logging/logger';                              // Unified logger

/**************************************************************************************************
 * Globals
 *************************************************************************************************/
let mainWindow: BrowserWindow | null;
const openWindows: Set<BrowserWindow> = new Set();
const plugins = new PluginManager();

/**************************************************************************************************
 * Helper: Resolve index.html (or webpack dev server) depending on environment
 *************************************************************************************************/
function resolveRendererUrl(): string {
  if (process.env.NODE_ENV === 'development' && process.env.VITE_DEV_SERVER_URL) {
    return process.env.VITE_DEV_SERVER_URL;
  }

  return url.format({
    protocol: 'file',
    slashes: true,
    pathname: path.join(__dirname, 'renderer', 'index.html'),
  });
}

/**************************************************************************************************
 * Window Factory
 *************************************************************************************************/
async function createWindow(startupFile?: string): Promise<BrowserWindow> {
  const windowState = new WindowStateKeeper('main', { width: 1440, height: 900 });

  const win = new BrowserWindow({
    x: windowState.x,
    y: windowState.y,
    width: windowState.width,
    height: windowState.height,
    minWidth: 960,
    minHeight: 640,
    show: false,
    title: 'PaletteFlow Studio',
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#1e1e1e' : '#ffffff',
    webPreferences: {
      // Security best-practices: disable Node.js integration and enable context isolation
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      sandbox: true,
    },
  });

  /********* Load UI *********/
  win.loadURL(resolveRendererUrl());

  // Open dev tools automatically if launched via `npm run dev`
  if (process.env.NODE_ENV === 'development') {
    win.webContents.openDevTools({ mode: 'detach' }).catch(() => /* ignore */ undefined);
  }

  /********* Restore + persist window position *********/
  windowState.watch(win);

  /********* Window Event Wiring *********/
  win.once('ready-to-show', () => win.show());
  win.on('focus', () => logger.debug('Window focus gained'));
  win.on('close', (e) => {
    // Ask renderer if it's safe to close (e.g. unsaved changes)
    e.preventDefault();
    win.webContents.send('window:query-close');
  });

  ipcMain.once(`window:${win.id}:allow-close`, () => {
    win.removeAllListeners('close');
    win.close();
  });

  win.on('closed', () => {
    openWindows.delete(win);
    if (win === mainWindow) {
      mainWindow = null;
    }
  });

  openWindows.add(win);

  /********* Open specified workspace file *********/
  if (startupFile) {
    win.webContents.once('did-finish-load', () => {
      win.webContents.send('workspace:open', startupFile);
    });
  }

  return win;
}

/**************************************************************************************************
 * Crash Reporter
 *************************************************************************************************/
function initCrashReporter(): CrashReporter {
  return CrashReporter.start({
    productName: 'PaletteFlow Studio',
    companyName: 'PaletteFlow Inc.',
    submitURL: 'https://crash.paletteflow.com/report',
    uploadToServer: true,
    compress: true,
    extra: {
      version: app.getVersion(),
      platform: process.platform,
    },
  });
}

/**************************************************************************************************
 * Auto-Updater
 *************************************************************************************************/
function initAutoUpdates(): void {
  autoUpdater.logger = logger;
  autoUpdater.autoDownload = false;

  autoUpdater.on('update-available', async () => {
    const { response } = await dialog.showMessageBox({
      type: 'info',
      message: 'A new version of PaletteFlow Studio is available.',
      detail: 'Would you like to download it now?',
      buttons: ['Download', 'Later'],
      cancelId: 1,
    });
    if (response === 0) {
      autoUpdater.downloadUpdate().catch(logger.error);
    }
  });

  autoUpdater.on('update-downloaded', async () => {
    const { response } = await dialog.showMessageBox({
      type: 'info',
      message: 'Update ready to install',
      detail: 'PaletteFlow Studio needs to restart to apply updates.',
      buttons: ['Restart', 'Later'],
      cancelId: 1,
    });
    if (response === 0) {
      setImmediate(() => autoUpdater.quitAndInstall());
    }
  });

  autoUpdater.checkForUpdates().catch(logger.warn);
}

/**************************************************************************************************
 * Single Instance Lock
 *************************************************************************************************/
function ensureSingleInstance(): boolean {
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
    app.quit();
    return false;
  }

  // Handle second-instance: focus existing window or create a new one
  app.on('second-instance', async (_event, argv) => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    } else {
      mainWindow = await createWindow();
    }

    // If user double-clicked a workspace file (*.pflow), open it
    const workspaceArg = argv.find((arg) => arg.endsWith('.pflow'));
    if (workspaceArg) {
      mainWindow?.webContents.send('workspace:open', workspaceArg);
    }
  });

  return true;
}

/**************************************************************************************************
 * Plugin Loading
 *************************************************************************************************/
async function loadPlugins(): Promise<void> {
  const pluginDir = AppConfig.get('plugins.directory');
  await plugins.discover(pluginDir);
  await plugins.activateAll();
  logger.info(`Loaded ${plugins.count} plugins from ${pluginDir}`);
}

/**************************************************************************************************
 * Application Bootstrap
 *************************************************************************************************/
async function bootstrap(): Promise<void> {
  logger.profile('startup');

  initCrashReporter();
  initAutoUpdates();

  await loadPlugins();

  registerIpcHandlers(ipcMain, plugins); // Dynamically registers handlers based on plugins

  // Open an initial window
  mainWindow = await createWindow();

  new MenuBuilder(app, shell, plugins).build();

  logger.profile('startup');
}

/**************************************************************************************************
 * Application Event Lifecycle
 *************************************************************************************************/
if (ensureSingleInstance()) {
  app.on('ready', () => {
    bootstrap().catch((err) => {
      logger.fatal('Failed to bootstrap application', err);
      dialog.showErrorBox('PaletteFlow Start-Up Error', String(err));
      app.exit(1);
    });
  });

  app.on('window-all-closed', () => {
    // On macOS, apps commonly stay open until the user quits explicitly with Cmd + Q
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });

  app.on('activate', async () => {
    if (openWindows.size === 0) {
      mainWindow = await createWindow();
    }
  });

  /************************************************************************************************
   * Graceful Shutdown Handling
   ************************************************************************************************/
  app.on('before-quit', async (event) => {
    event.preventDefault(); // We'll quit manually after cleanup

    try {
      // Allow plugins to flush any pending data
      await Promise.race([plugins.deactivateAll(), once(setTimeout, 3000)]);
    } catch (err) {
      logger.warn('Plugin deactivation timeout', err);
    } finally {
      app.exit(0);
    }
  });
}

/**************************************************************************************************
 * Dev-Only: Watch for unhandled rejections so they surface in devtools console
 *************************************************************************************************/
process.on('unhandledRejection', (reason: unknown) => {
  logger.error('Unhandled Promise rejection', reason);
});

process.on('uncaughtException', (err) => {
  logger.fatal('Uncaught Exception', err);
});
```