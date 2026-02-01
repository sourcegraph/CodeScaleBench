```typescript
/* eslint-disable prefer-destructuring */

/**
 * PaletteFlow Studio
 * File: WindowManager.ts
 * Description:
 * Singleton-style service that owns the life-cycle of all primary Electron
 * BrowserWindows belonging to the desktop application.  It ensures that:
 *   • windows are restored after an unclean shutdown
 *   • windows remember their last size/position
 *   • only one Settings window can exist at a time
 *   • themes, updates, crash-reporting and plugin preload scripts are applied
 *   • renderer processes can request new windows via IPC
 *
 * The manager lives in the Electron *main* process.
 */

import path from 'node:path';
import { URL } from 'node:url';
import {
  app,
  BrowserWindow,
  BrowserWindowConstructorOptions,
  Event as ElectronEvent,
  ipcMain,
  shell,
} from 'electron';
import { EventEmitter } from 'node:events';
import log from 'electron-log';
import Store from 'electron-store';

import { UpdateService } from '../modules/update/UpdateService';
import { CrashReporterService } from '../modules/crash/CrashReporterService';
import { ThemeService } from '../modules/theme/ThemeService';
import { PluginRegistry } from '../plugins/PluginRegistry';
import { WorkspaceDTO } from '../../shared/dto/WorkspaceDTO';

/* -------------------------------------------------------------------------- */
/*                                  Typings                                   */
/* -------------------------------------------------------------------------- */

type WindowKind = 'workspace' | 'settings' | 'plugin';

interface WindowMeta {
  id: number;
  kind: WindowKind;
  workspaceId?: string; // only for workspace windows
}

/**
 * Structure persisted to disk for every window id
 * so we can restore them later.
 */
interface WindowState {
  bounds: Electron.Rectangle;
  isMaximized: boolean;
  keyword?: string; // e.g. workspaceId
}

interface ManagedWindow {
  win: BrowserWindow;
  meta: WindowMeta;
}

interface CreateWindowOptions {
  kind: WindowKind;
  preload: string;
  /**
   * URL or file loaded into the BrowserWindow.
   * If undefined, it is resolved from renderer/index.html fallback.
   */
  loadUrl?: string;
  workspace?: WorkspaceDTO;
  extraPreferences?: Record<string, unknown>;
}

/* -------------------------------------------------------------------------- */
/*                            Implementation Class                            */
/* -------------------------------------------------------------------------- */

export class WindowManager extends EventEmitter {
  private static instance: WindowManager;

  /** Map<windowId, ManagedWindow> */
  private windows: Map<number, ManagedWindow> = new Map();

  private readonly store: Store<Record<string, WindowState>>;

  private readonly updateService = UpdateService.getInstance();
  private readonly crashReporterService = CrashReporterService.getInstance();
  private readonly themeService = ThemeService.getInstance();
  private readonly pluginRegistry = PluginRegistry.getInstance();

  private constructor() {
    super();

    // Electron-store acts like a persistent KV database in the userData dir.
    this.store = new Store<Record<string, WindowState>>({
      name: 'window-state',
    });

    this.registerIpcHandlers();
  }

  /* ------------------------------ Life-Cycle ------------------------------ */

  /**
   * Must be called once after the `app.whenReady()` promise resolves.
   * Restores existing windows (if any) or creates a fresh workspace window.
   */
  public async init(): Promise<void> {
    try {
      await this.restorePreviousWindows();
    } catch (err) /* istanbul ignore next */ {
      log.error('[WindowManager] Failed to restore windows:', err);
      // Fallback: at least open a single workspace window
      this.createWorkspaceWindow();
    }
  }

  /* ---------------------------------------------------------------------- */
  /*                           Public API - Windows                         */
  /* ---------------------------------------------------------------------- */

  /**
   * Create a new workspace window.
   * If the argument is omitted, an empty workspace is bootstrapped
   * by the renderer.
   */
  public createWorkspaceWindow(workspace?: WorkspaceDTO): BrowserWindow {
    const preload = path.join(__dirname, '../preload/workspacePreload.js');
    const loadUrl = this.resolveRendererUrl('workspace.html');
    return this.createWindow({ kind: 'workspace', preload, loadUrl, workspace });
  }

  /** Open (or focus) the singleton Settings window. */
  public openSettingsWindow(): BrowserWindow {
    // Reuse existing settings window if one exists
    const existing = [...this.windows.values()].find(
      (mw) => mw.meta.kind === 'settings',
    );
    if (existing) {
      existing.win.focus();
      return existing.win;
    }

    const preload = path.join(__dirname, '../preload/settingsPreload.js');
    const loadUrl = this.resolveRendererUrl('settings.html');
    return this.createWindow({ kind: 'settings', preload, loadUrl });
  }

  /** Generic broadcast to all renderer processes. */
  public broadcast(channel: string, ...args: unknown[]): void {
    this.windows.forEach(({ win }) => {
      if (!win.isDestroyed()) {
        win.webContents.send(channel, ...args);
      }
    });
  }

  /**
   * Send to a specific window id. Returns `false` if the window cannot be found.
   */
  public sendTo(windowId: number, channel: string, ...args: unknown[]): boolean {
    const target = this.windows.get(windowId);
    if (!target || target.win.isDestroyed()) {
      return false;
    }
    target.win.webContents.send(channel, ...args);
    return true;
  }

  public getWindowMeta(windowId: number): WindowMeta | undefined {
    return this.windows.get(windowId)?.meta;
  }

  /* ---------------------------- Private helpers --------------------------- */

  /**
   * Restores all BrowserWindows that were opened when the app quit last time.
   */
  private async restorePreviousWindows(): Promise<void> {
    if (app.commandLine.hasSwitch('no-restore')) {
      log.info('[WindowManager] Skipping window restoration (arg: --no-restore)');
      this.createWorkspaceWindow();
      return;
    }

    const allStates = this.store.store;
    const stateEntries = Object.entries(allStates);
    if (stateEntries.length === 0) {
      this.createWorkspaceWindow();
      return;
    }

    // Ensure the plugin registry is hydrated before we ask renders to load
    await this.pluginRegistry.waitUntilReady();

    stateEntries.forEach(([key, value]) => {
      const kind = key.startsWith('settings') ? 'settings' : 'workspace';
      const preload =
        kind === 'settings'
          ? path.join(__dirname, '../preload/settingsPreload.js')
          : path.join(__dirname, '../preload/workspacePreload.js');
      this.createWindow({
        kind,
        preload,
        workspace: kind === 'workspace' ? { id: value.keyword ?? '' } as WorkspaceDTO : undefined,
      });
    });
  }

  /**
   * Low-level window factory.  Every BrowserWindow flows through here so
   * we can attach common listeners and do bookkeeping.
   */
  private createWindow({
    kind,
    preload,
    loadUrl,
    workspace,
    extraPreferences,
  }: CreateWindowOptions): BrowserWindow {
    const savedState = this.loadWindowState(kind, workspace?.id);
    const windowOptions: BrowserWindowConstructorOptions = {
      show: false, // we show once the content is ready
      webPreferences: {
        preload,
        sandbox: false,
        nodeIntegration: false,
        contextIsolation: true,
        additionalArguments: workspace ? [`--workspaceId=${workspace.id}`] : undefined,
        ...extraPreferences,
      },
      ...savedState.bounds,
    };

    const win = new BrowserWindow(windowOptions);

    const meta: WindowMeta = {
      id: win.id,
      kind,
      workspaceId: workspace?.id,
    };

    this.windows.set(win.id, { win, meta });

    /* ------------------------ BrowserWindow events ----------------------- */

    win.once('ready-to-show', () => {
      if (savedState.isMaximized) win.maximize();
      win.show();
    });

    win.on('close', () => {
      this.saveWindowState(win, meta);
    });

    win.on('closed', () => {
      this.windows.delete(win.id);
      this.emit('window-closed', meta);
    });

    win.webContents.on('new-window', (e: ElectronEvent, url) => {
      // Open external links in the system browser
      e.preventDefault();
      shell.openExternal(url).catch((err) => log.error(err));
    });

    /* ------------------------- Misc integrations ------------------------ */

    // CrashReporter attaches to every new webContents
    this.crashReporterService.attachToWebContents(win.webContents);

    // Theming
    win.webContents.on('did-finish-load', () => {
      const css = this.themeService.getActiveThemeCss();
      if (css) {
        win.webContents.insertCSS(css).catch((err) =>
          log.warn('[WindowManager] Failed to insert theme CSS', err),
        );
      }
    });

    /* --------------------------- Load content --------------------------- */

    if (loadUrl) {
      win.loadURL(loadUrl).catch((err) => {
        log.error('[WindowManager] Failed to load window URL', err);
      });
    } else {
      // Fallback to default renderer page
      win
        .loadFile(path.join(app.getAppPath(), 'renderer', 'index.html'))
        .catch((err) => log.error(err));
    }

    return win;
  }

  /* ---------------------------------------------------------------------- */
  /*                         IPC from Renderer Process                       */
  /* ---------------------------------------------------------------------- */

  private registerIpcHandlers(): void {
    /**
     * Renderer processes may request a new window by sending:
     *   ipcRenderer.invoke('window-manager:create-workspace', workspaceDto)
     */
    ipcMain.handle(
      'window-manager:create-workspace',
      (_event, workspace: WorkspaceDTO | undefined) => {
        const newWin = this.createWorkspaceWindow(workspace);
        return newWin.id;
      },
    );

    ipcMain.handle('window-manager:open-settings', () => {
      const win = this.openSettingsWindow();
      return win.id;
    });

    ipcMain.handle(
      'window-manager:apply-theme',
      async (_e, themeId: string) => {
        await this.themeService.setActiveTheme(themeId);
        const css = this.themeService.getActiveThemeCss();
        if (!css) return;
        this.broadcast('theme:css', css);
      },
    );
  }

  /* ---------------------------------------------------------------------- */
  /*                          Window State Persistence                      */
  /* ---------------------------------------------------------------------- */

  private makeStateKey(kind: WindowKind, workspaceId?: string): string {
    return kind === 'workspace'
      ? `workspace:${workspaceId ?? 'untitled'}`
      : 'settings';
  }

  private loadWindowState(
    kind: WindowKind,
    workspaceId?: string,
  ): WindowState & { bounds: Electron.Rectangle } {
    const key = this.makeStateKey(kind, workspaceId);
    const saved = this.store.get(key) as WindowState | undefined;
    const defaultBounds: Electron.Rectangle = { width: 1280, height: 800, x: undefined as any, y: undefined as any };

    if (!saved) return { bounds: defaultBounds, isMaximized: false };
    return { bounds: saved.bounds ?? defaultBounds, isMaximized: saved.isMaximized };
  }

  private saveWindowState(win: BrowserWindow, meta: WindowMeta): void {
    if (win.isDestroyed()) return;

    const isMaximized = win.isMaximized();
    const bounds = isMaximized ? win.getNormalBounds() : win.getBounds();

    const key = this.makeStateKey(meta.kind, meta.workspaceId);
    const state: WindowState = {
      bounds,
      isMaximized,
      keyword: meta.workspaceId,
    };

    this.store.set(key, state);
  }

  /* ---------------------------------------------------------------------- */
  /*                           Helper / Utilities                            */
  /* ---------------------------------------------------------------------- */

  /**
   * Resolves a relative renderer HTML file to a URL that the BrowserWindow
   * can consume.  In development we point to the Vite/webpack dev server;
   * in production we use a file:// protocol.
   */
  // eslint-disable-next-line class-methods-use-this
  private resolveRendererUrl(htmlFile: string): string {
    if (app.isPackaged) {
      return new URL(
        `file://${path.join(app.getAppPath(), 'renderer', htmlFile)}`,
      ).toString();
    }

    const devServerUrl = process.env['PALETTEFLOW_DEV_SERVER_URL'];
    if (!devServerUrl) {
      throw new Error(
        'Missing dev server URL - did you start the renderer bundler?',
      );
    }
    return `${devServerUrl}/${htmlFile}`;
  }

  /* ---------------------------------------------------------------------- */
  /*                              Static entry                               */
  /* ---------------------------------------------------------------------- */

  public static getInstance(): WindowManager {
    if (!WindowManager.instance) {
      WindowManager.instance = new WindowManager();
    }
    return WindowManager.instance;
  }
}

/* -------------------------------------------------------------------------- */
/*                              Initialization                                */
/* -------------------------------------------------------------------------- */

/**
 * The main process entry file should import `WindowManager` and call
 * `WindowManager.getInstance().init()` after `app.whenReady()`.
 *
 * Example:
 *   const wm = WindowManager.getInstance();
 *   app.whenReady().then(() => wm.init());
 *
 * This side-effect import ensures the singleton is created even if someone
 * forgets to call getInstance() manually elsewhere in the codebase.
 */
export const windowManager = WindowManager.getInstance();
```