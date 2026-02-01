```typescript
/**************************************************************************************************
 * PaletteFlow Studio – IPC Channel Definitions (Main Process)
 * -----------------------------------------------------------------------------------------------
 * This module centralises every production-grade IPC channel that the main process exposes to
 * renderer windows and plugins.  All traffic is strongly typed and routed through a single
 * registry, enabling runtime auditing, hot-reloading of plugin handlers, granular permission
 * checks, and test-time mocking.
 *
 * NOTE:  Only code running in the Electron main context should import this file.
 *************************************************************************************************/

import {
  BrowserWindow,
  IpcMainInvokeEvent,
  IpcMainEvent,
  WebContents,
  ipcMain,
} from 'electron';
import { autoUpdater } from 'electron-updater';
import { v4 as uuidv4 } from 'uuid';

import { SettingsService } from '../services/settings-service';
import { CrashReporterService } from '../services/crash-reporter-service';
import { WorkspaceExportService } from '../services/workspace-export-service';
import { PluginService } from '../services/plugin-service';
import { WindowManager } from '../windows/window-manager';

/* -------------------------------------------------------------------------------------------------
 * Type-Safe Channel Map
 * -----------------------------------------------------------------------------------------------*/

export const Channels = {
  SETTINGS_GET: 'settings:get',
  SETTINGS_SET: 'settings:set',
  AUTOUPDATE_CHECK: 'autoupdate:check',
  CRASH_SUBMIT: 'crash:submit',
  WORKSPACE_EXPORT: 'workspace:export',
  WINDOW_NEW: 'window:new',
  PLUGIN_INVOKE: 'plugin:invoke',

  /* Broadcast-only events */
  AUTOUPDATE_STATE: 'autoupdate:state',
} as const;

type ValueOf<T> = T[keyof T];
export type Channel = ValueOf<typeof Channels>;

/* ---------------------------------- Payload Contracts -----------------------------------------*/

/* Settings ------------------------------------------------------------*/
export interface SettingsGetRequest {
  key?: string; // if omitted, return full settings object
}
export type SettingsGetResponse = unknown;

export interface SettingsSetRequest {
  key: string;
  value: unknown;
}
export type SettingsSetResponse = void;

/* Auto-Update ---------------------------------------------------------*/
export type AutoUpdateCheckResponse =
  | { status: 'up-to-date' }
  | { status: 'available'; version: string };

export type AutoUpdateStateEvent =
  | { phase: 'checking' }
  | { phase: 'downloading'; progress: number }
  | { phase: 'downloaded'; version: string }
  | { phase: 'error'; reason: string };

/* Crash Reporting -----------------------------------------------------*/
export interface CrashSubmitRequest {
  reason: string;
  details?: Record<string, unknown>;
}
export interface CrashSubmitResponse {
  reportId: string;
}

/* Workspace Export ----------------------------------------------------*/
export interface WorkspaceExportRequest {
  workspaceId: string;
  format: 'zip' | 'json';
}
export interface WorkspaceExportResponse {
  filePath: string;
}

/* Window Management ---------------------------------------------------*/
export interface WindowNewRequest {
  workspaceId?: string;
}
export interface WindowNewResponse {
  windowId: number;
}

/* Plugin Invocation ---------------------------------------------------*/
export interface PluginInvokeRequest {
  pluginId: string;
  command: string;
  args: unknown[];
}
export type PluginInvokeResponse = unknown;

/* Generic Invocation Handler ------------------------------------------*/
type Handler<Req, Res> = (
  event: IpcMainInvokeEvent,
  payload: Req,
) => Promise<Res> | Res;

/* -------------------------------------------------------------------------------------------------
 * IPC Registry
 * -----------------------------------------------------------------------------------------------*/

export class IpcRegistry {
  private registeredHandlers = new Map<Channel, (...args: any[]) => any>();

  constructor(
    private readonly settings: SettingsService,
    private readonly crashReporter: CrashReporterService,
    private readonly workspaceExporter: WorkspaceExportService,
    private readonly pluginService: PluginService,
    private readonly windowManager: WindowManager,
  ) {}

  /* ------------------------ Public life-cycle ------------------------*/

  initialise(): void {
    this.register(Channels.SETTINGS_GET, this.onSettingsGet);
    this.register(Channels.SETTINGS_SET, this.onSettingsSet);
    this.register(Channels.AUTOUPDATE_CHECK, this.onAutoupdateCheck);
    this.register(Channels.CRASH_SUBMIT, this.onCrashSubmit);
    this.register(Channels.WORKSPACE_EXPORT, this.onWorkspaceExport);
    this.register(Channels.WINDOW_NEW, this.onWindowNew);
    this.register(Channels.PLUGIN_INVOKE, this.onPluginInvoke);

    this.wireAutoupdateEvents();

    /* Expose registration for plugins */
    this.pluginService.onRegisterIpcHandler((channel, handler) => {
      this.dynamicRegister(channel, handler);
    });
  }

  dispose(): void {
    for (const [channel, handler] of this.registeredHandlers) {
      ipcMain.removeHandler(channel);
      ipcMain.removeAllListeners(channel);
      this.registeredHandlers.delete(channel);
    }
  }

  /* ---------------------------- Private ------------------------------*/

  private register<Req, Res>(
    channel: Channel,
    handler: Handler<Req, Res>,
  ): void {
    if (this.registeredHandlers.has(channel)) {
      throw new Error(`IPC handler already registered for ${channel}`);
    }

    const wrapped = async (event: IpcMainInvokeEvent, payload: Req) => {
      try {
        return await handler.call(this, event, payload);
      } catch (err) {
        console.error(`[IPC] Error in handler for ${channel}:`, err);
        // Throwing serialises the error to renderer
        throw err instanceof Error ? err : new Error(String(err));
      }
    };

    ipcMain.handle(channel, wrapped);
    this.registeredHandlers.set(channel, wrapped);
  }

  /** Register handlers contributed at runtime by plugins */
  private dynamicRegister(
    channel: string,
    handler: (event: IpcMainInvokeEvent, payload: any) => any,
  ): void {
    if (this.registeredHandlers.has(channel as Channel)) {
      throw new Error(`Channel ${channel} already taken`);
    }
    ipcMain.handle(channel, handler);
    this.registeredHandlers.set(channel as Channel, handler);
  }

  /* ---------------------------- Handlers -----------------------------*/

  private onSettingsGet: Handler<
    SettingsGetRequest,
    SettingsGetResponse
  > = async (_evt, payload) => {
    return payload.key
      ? this.settings.get(payload.key)
      : this.settings.getAll();
  };

  private onSettingsSet: Handler<
    SettingsSetRequest,
    SettingsSetResponse
  > = async (_evt, { key, value }) => {
    await this.settings.set(key, value);
  };

  private onAutoupdateCheck: Handler<undefined, AutoUpdateCheckResponse> =
    async () => {
      const update = await autoUpdater.checkForUpdates();
      return update?.updateInfo?.version
        ? { status: 'available', version: update.updateInfo.version }
        : { status: 'up-to-date' };
    };

  private onCrashSubmit: Handler<
    CrashSubmitRequest,
    CrashSubmitResponse
  > = async (_evt, { reason, details }) => {
    const reportId = await this.crashReporter.submit(reason, details);
    return { reportId };
  };

  private onWorkspaceExport: Handler<
    WorkspaceExportRequest,
    WorkspaceExportResponse
  > = async (_evt, { workspaceId, format }) => {
    const filePath = await this.workspaceExporter.export(workspaceId, format);
    return { filePath };
  };

  private onWindowNew: Handler<WindowNewRequest, WindowNewResponse> = async (
    _evt,
    { workspaceId },
  ) => {
    const win = await this.windowManager.createWindow({ workspaceId });
    return { windowId: win.id };
  };

  private onPluginInvoke: Handler<
    PluginInvokeRequest,
    PluginInvokeResponse
  > = async (_evt, { pluginId, command, args }) => {
    return await this.pluginService.invoke(pluginId, command, args);
  };

  /* ------------------------ Auto-update events -----------------------*/

  private wireAutoupdateEvents(): void {
    autoUpdater.on('checking-for-update', () => {
      this.broadcast<AutoUpdateStateEvent>(Channels.AUTOUPDATE_STATE, {
        phase: 'checking',
      });
    });

    autoUpdater.on('download-progress', (progressObj) => {
      this.broadcast<AutoUpdateStateEvent>(Channels.AUTOUPDATE_STATE, {
        phase: 'downloading',
        progress: progressObj.percent,
      });
    });

    autoUpdater.on('update-downloaded', (info) => {
      this.broadcast<AutoUpdateStateEvent>(Channels.AUTOUPDATE_STATE, {
        phase: 'downloaded',
        version: info.version,
      });
    });

    autoUpdater.on('error', (err) => {
      this.broadcast<AutoUpdateStateEvent>(Channels.AUTOUPDATE_STATE, {
        phase: 'error',
        reason: err.message,
      });
    });
  }

  /* --------------------------- Utilities -----------------------------*/

  /**
   * Broadcast an event to every open renderer.
   */
  private broadcast<T>(channel: Channel, payload: T): void {
    BrowserWindow.getAllWindows().forEach((w) =>
      w.webContents.send(channel, payload),
    );
  }

  /**
   * Send an event to a specific renderer WebContents if still alive.
   */
  private sendTo(webContents: WebContents, channel: Channel, payload: any): void {
    if (!webContents.isDestroyed()) {
      webContents.send(channel, payload);
    }
  }
}

/* -------------------------------------------------------------------------------------------------
 * Bootstrap Helper
 * -----------------------------------------------------------------------------------------------*/

let registry: IpcRegistry | undefined;

export function bootstrapIpcChannels(deps: {
  settings: SettingsService;
  crashReporter: CrashReporterService;
  workspaceExporter: WorkspaceExportService;
  pluginService: PluginService;
  windowManager: WindowManager;
}): void {
  if (registry) {
    throw new Error('IPC registry already initialised');
  }
  registry = new IpcRegistry(
    deps.settings,
    deps.crashReporter,
    deps.workspaceExporter,
    deps.pluginService,
    deps.windowManager,
  );
  registry.initialise();
}

export function disposeIpcChannels(): void {
  registry?.dispose();
  registry = undefined;
}
```