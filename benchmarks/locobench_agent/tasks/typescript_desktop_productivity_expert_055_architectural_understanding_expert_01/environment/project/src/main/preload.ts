```typescript
/******************************************************************************
 *  PaletteFlow Studio — Pre-load Script
 *  ------------------------------------
 *  This script runs in Electron’s isolated “preload” context. It exposes a
 *  tightly-scoped, type-safe API surface to renderer processes through
 *  `contextBridge`, preventing direct use of Node.js primitives while still
 *  enabling rich communication with the main process.
 *
 *  Responsibilities
 *  • Forward strongly-typed IPC calls to/from main.
 *  • Guard against channel spoofing by white-listing valid IPC topics.
 *  • Provide convenience wrappers for common desktop operations (clipboard,
 *    shell, drag-and-drop, crash reporting, auto-updates, etc.).
 *
 *  NOTE: All channels **must** be declared in `ValidInvokeChannels` or
 *  `ValidOnChannels`. Any addition should be mirrored in the main process
 *  handler map to preserve type-safety and security.
 ******************************************************************************/

import {
  contextBridge,
  ipcRenderer,
  IpcRendererEvent,
  clipboard,
  shell,
  CrashReporterStartOptions,
} from 'electron';

/* -------------------------------------------------------------------------- */
/*                              Type Declarations                             */
/* -------------------------------------------------------------------------- */

type Unsubscribe = () => void;

export interface AppPreferences {
  /* These should stay in sync with `/domain/settings.ts` */
  theme: 'light' | 'dark' | 'system';
  autoUpdate: boolean;
  crashReporting: boolean;
  telemetry: boolean;
  recentWorkspaces: string[];
}

export interface PluginMeta {
  id: string;
  name: string;
  version: string;
  author: string;
  description?: string;
  enabled: boolean;
  entry: string; // absolute file URI
}

export interface WindowOpenOptions {
  workspacePath?: string;
  readonly?: boolean;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
}

/* -------------------------------------------------------------------------- */
/*                            IPC Channel Whitelist                           */
/* -------------------------------------------------------------------------- */

const ValidInvokeChannels = {
  // settings
  GetSettings: 'settings:get',
  SetSettings: 'settings:set',
  // plugins
  ListPlugins: 'plugins:list',
  InstallPlugin: 'plugins:install',
  TogglePlugin: 'plugins:toggle',
  // windows
  CreateWindow: 'window:create',
  // utility
  CheckForUpdates: 'autoUpdate:check',
  DownloadUpdate: 'autoUpdate:download',
  QuitAndInstall: 'autoUpdate:install',
  // crash reporter
  StartCrashReporter: 'crash:start',
} as const;

const ValidOnChannels = {
  SettingsChanged: 'settings:changed',
  UpdateDownloadProgress: 'autoUpdate:progress',
  UpdateAvailable: 'autoUpdate:available',
  UpdateDownloaded: 'autoUpdate:downloaded',
  PluginInstalled: 'plugins:installed',
  PluginErrored: 'plugins:error',
} as const;

type InvokeChannel = typeof ValidInvokeChannels[keyof typeof ValidInvokeChannels];
type OnChannel = typeof ValidOnChannels[keyof typeof ValidOnChannels];

/* -------------------------------------------------------------------------- */
/*                           IPC Helper — Type-Safe                           */
/* -------------------------------------------------------------------------- */

function invoke<TResponse = unknown, TArgs = unknown>(
  channel: InvokeChannel,
  args?: TArgs,
): Promise<TResponse> {
  return ipcRenderer.invoke(channel, args);
}

function on<TPayload>(
  channel: OnChannel,
  listener: (payload: TPayload) => void,
): Unsubscribe {
  const wrapped = (_ev: IpcRendererEvent, payload: TPayload) => listener(payload);
  ipcRenderer.on(channel, wrapped);
  return () => {
    ipcRenderer.removeListener(channel, wrapped);
  };
}

/* -------------------------------------------------------------------------- */
/*                            Exposed Renderer API                            */
/* -------------------------------------------------------------------------- */

const paletteflowBridge = {
  version: process.env.npm_package_version,

  /**********************
   *  Application Menu  *
   **********************/
  menu: {
    /* Example: Trigger the main process’ command palette */
    executeCommand(commandId: string, args?: unknown[]) {
      ipcRenderer.send('command:execute', { commandId, args });
    },
  },

  /*******************
   *  User Settings  *
   *******************/
  settings: {
    async get(): Promise<AppPreferences> {
      return invoke<AppPreferences>(ValidInvokeChannels.GetSettings);
    },
    async set(partial: Partial<AppPreferences>): Promise<void> {
      await invoke<void, Partial<AppPreferences>>(ValidInvokeChannels.SetSettings, partial);
    },
    /* Real-time updates pushed from main process */
    onChange(listener: (prefs: AppPreferences) => void): Unsubscribe {
      return on<AppPreferences>(ValidOnChannels.SettingsChanged, listener);
    },
  },

  /****************
   *  Crash/Logs  *
   ****************/
  crashReporter: {
    start(options?: CrashReporterStartOptions) {
      invoke<void, CrashReporterStartOptions>(
        ValidInvokeChannels.StartCrashReporter,
        options,
      ).catch(console.error);
    },
  },

  /****************
   *  Auto Update *
   ****************/
  autoUpdate: {
    check() {
      invoke<void>(ValidInvokeChannels.CheckForUpdates).catch(console.error);
    },
    onAvailable(cb: () => void): Unsubscribe {
      return on<void>(ValidOnChannels.UpdateAvailable, cb);
    },
    onDownloadProgress(cb: (percent: number) => void): Unsubscribe {
      return on<number>(ValidOnChannels.UpdateDownloadProgress, cb);
    },
    onDownloaded(cb: () => void): Unsubscribe {
      return on<void>(ValidOnChannels.UpdateDownloaded, cb);
    },
    download() {
      invoke<void>(ValidInvokeChannels.DownloadUpdate).catch(console.error);
    },
    quitAndInstall() {
      invoke<void>(ValidInvokeChannels.QuitAndInstall).catch(console.error);
    },
  },

  /****************
   *   Plugins    *
   ****************/
  plugins: {
    async list(): Promise<PluginMeta[]> {
      return invoke<PluginMeta[]>(ValidInvokeChannels.ListPlugins);
    },
    async install(packagePath: string): Promise<void> {
      return invoke<void, string>(ValidInvokeChannels.InstallPlugin, packagePath);
    },
    /* Enable/Disable without uninstalling */
    async toggle(pluginId: string, enable: boolean): Promise<void> {
      return invoke<void, { id: string; enable: boolean }>(ValidInvokeChannels.TogglePlugin, {
        id: pluginId,
        enable,
      });
    },
    onInstalled(
      cb: (plugin: PluginMeta) => void,
    ): Unsubscribe {
      return on<PluginMeta>(ValidOnChannels.PluginInstalled, cb);
    },
    onError(cb: (msg: string) => void): Unsubscribe {
      return on<string>(ValidOnChannels.PluginErrored, cb);
    },
  },

  /****************
   *   Windows    *
   ****************/
  windows: {
    async create(opts?: WindowOpenOptions): Promise<void> {
      await invoke<void, WindowOpenOptions>(ValidInvokeChannels.CreateWindow, opts);
    },
  },

  /*****************
   * Clipboard API *
   *****************/
  clipboard: {
    readText: () => clipboard.readText(),
    writeText: (text: string) => clipboard.writeText(text),
  },

  /****************
   *  External    *
   ****************/
  shell: {
    openExternal: (url: string, activate = true) => {
      shell.openExternal(url, { activate });
    },
  },

  /******************
   *  Event Relay   *
   ******************/
  once<TPayload>(
    channel: OnChannel,
    listener: (payload: TPayload) => void,
  ): void {
    ipcRenderer.once(channel, (_ev, payload: TPayload) => listener(payload));
  },
};

/* -------------------------------------------------------------------------- */
/*                  Expose API — `window.paletteflow` (renderer)              */
/* -------------------------------------------------------------------------- */

declare global {
  interface Window {
    paletteflow: typeof paletteflowBridge;
  }
}

/* Security: expose only the whitelisted bridge */
contextBridge.exposeInMainWorld('paletteflow', paletteflowBridge);

/* -------------------------------------------------------------------------- */
/*                             Process Event Hooks                            */
/* -------------------------------------------------------------------------- */

/**
 * Notify the main process when the renderer throws an uncaught error so that
 * we can surface it in crash analytics or show an in-app notification. We keep
 * the payload minimal to avoid leaking PII.
 */
window.addEventListener('error', (ev) => {
  const errorSummary = {
    message: ev.message,
    source: ev.filename,
    line: ev.lineno,
    column: ev.colno,
  };

  ipcRenderer.send('renderer:error', errorSummary);
});

/**
 * Forward unhandled Promise rejections as well.
 */
window.addEventListener('unhandledrejection', (ev) => {
  ipcRenderer.send('renderer:unhandledRejection', {
    reason: (ev.reason && ev.reason.message) || 'Unknown',
  });
});
```