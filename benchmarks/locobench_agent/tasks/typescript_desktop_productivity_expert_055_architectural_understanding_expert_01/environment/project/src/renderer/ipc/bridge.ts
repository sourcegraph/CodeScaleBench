```typescript
/***********************************************************************************************************************
 * PaletteFlow Studio – IPC Bridge
 * --------------------------------------------------------------------------------------------------------------------
 * This module is the single, canonical place for the renderer-process to talk to the main-process. Having one
 * well-typed façade prevents “stringly-typed” channel names scattered throughout the codebase and gives us
 * compile-time safety plus centralised security hardening (e.g. channel allow-listing).
 *
 * NOTE: This file is imported by regular renderer bundles (React/Preact views, ViewModels, etc.) *and*
 * by the preload script in order to expose a safe API via Electron’s `contextBridge`.  Keep all Node-specific
 * imports behind conditional checks because preload runs with `contextIsolation: true` and
 * `nodeIntegration: false`.
 **********************************************************************************************************************/

import type { IpcRendererEvent } from 'electron';
import { ipcRenderer, contextBridge } from 'electron'; // Safe: imported in preload; will be tree-shaken in renderer

/* --------------------------------------------------------------------------------------------------------------------
 * 1. Channel catalog
 * ------------------------------------------------------------------------------------------------------------------ */
export enum RendererToMainChannel {
  /* Canvas / Node orchestration */
  CREATE_NODE           = 'canvas:create-node',
  APPLY_THEME           = 'canvas:apply-theme',
  EXPORT_WORKSPACE      = 'workspace:export',

  /* Application-level */
  OPEN_SETTINGS         = 'app:open-settings',
  REPORT_CRASH          = 'app:report-crash',
  REQUEST_PLUGIN_API    = 'plugin:request-api',

  /*  Internal debug / QA channels can be added below
      ...
  */
}

export enum MainToRendererChannel {
  NODE_CREATED          = 'event:node-created',
  THEME_APPLIED         = 'event:theme-applied',
  WORKSPACE_EXPORTED    = 'event:workspace-exported',

  UPDATE_AVAILABLE      = 'update:available',
  CRASH_ACK             = 'crash:ack',
  PLUGIN_API_RESPONSE   = 'plugin:api-response',
}

/* --------------------------------------------------------------------------------------------------------------------
 * 2. Payload typing
 * ------------------------------------------------------------------------------------------------------------------ */
export interface CreateNodePayload {
  workspaceId : string;
  nodeType    : string;
  position    : { x: number; y: number };
  initialData?: unknown;
}

export interface ApplyThemePayload {
  workspaceId : string;
  themeId     : string;
}

export interface ExportWorkspacePayload {
  workspaceId : string;
  format      : 'json' | 'pdf' | 'png';
  destination?: string;
}

export interface WorkspaceExportResult {
  success : boolean;
  path?   : string;
  error?  : string;
}

/**
 * Maps channels to their request payloads (arguments passed from renderer to main).
 * Use `void` for no payload.
 */
type InvokePayloadMap = {
  [RendererToMainChannel.CREATE_NODE]        : CreateNodePayload;
  [RendererToMainChannel.APPLY_THEME]        : ApplyThemePayload;
  [RendererToMainChannel.EXPORT_WORKSPACE]   : ExportWorkspacePayload;
  [RendererToMainChannel.OPEN_SETTINGS]      : void;
  [RendererToMainChannel.REPORT_CRASH]       : { reason: string; stack?: string };
  [RendererToMainChannel.REQUEST_PLUGIN_API] : { pluginId: string };
};

/**
 * Maps channels to their response values (data returned from main to renderer via `ipcRenderer.invoke`).
 */
type InvokeReturnMap = {
  [RendererToMainChannel.CREATE_NODE]        : { id: string }; // newly created node id
  [RendererToMainChannel.APPLY_THEME]        : boolean;        // ok?
  [RendererToMainChannel.EXPORT_WORKSPACE]   : WorkspaceExportResult;
  [RendererToMainChannel.OPEN_SETTINGS]      : void;
  [RendererToMainChannel.REPORT_CRASH]       : void;
  [RendererToMainChannel.REQUEST_PLUGIN_API] : unknown;        // will be cast by caller
};

/**
 * Maps event channels (push from main to renderer) to event payloads.
 */
type EventPayloadMap = {
  [MainToRendererChannel.NODE_CREATED]       : { id: string; workspaceId: string };
  [MainToRendererChannel.THEME_APPLIED]      : { workspaceId: string; themeId: string };
  [MainToRendererChannel.WORKSPACE_EXPORTED] : WorkspaceExportResult;
  [MainToRendererChannel.UPDATE_AVAILABLE]   : { version: string; releaseNotes?: string };
  [MainToRendererChannel.CRASH_ACK]          : void;
  [MainToRendererChannel.PLUGIN_API_RESPONSE]: { pluginId: string; api: unknown };
};

/* --------------------------------------------------------------------------------------------------------------------
 * 3. Runtime allow-lists for additional security
 * ------------------------------------------------------------------------------------------------------------------ */

const INVOKE_CHANNELS = new Set<string>(Object.values(RendererToMainChannel));
const EVENT_CHANNELS  = new Set<string>(Object.values(MainToRendererChannel));

/* --------------------------------------------------------------------------------------------------------------------
 * 4. Bridge implementation
 * ------------------------------------------------------------------------------------------------------------------ */
class IPCBridge {
  /* ------------------------------------------- invoke ------------------------------------------------------------- */
  private static async invoke<
    C extends RendererToMainChannel
  >(channel: C, payload: InvokePayloadMap[C]): Promise<InvokeReturnMap[C]> {
    if (!INVOKE_CHANNELS.has(channel)) {
      throw new Error(`[IPCBridge] Attempt to invoke unauthorized channel: ${channel}`);
    }

    // Electron strips prototypes, so we make sure payload is serializable.
    return ipcRenderer.invoke(channel, payload) as Promise<InvokeReturnMap[C]>;
  }

  /* ------------------------------------------- event subscription ------------------------------------------------- */
  private static on<
    C extends MainToRendererChannel
  >(channel: C, listener: (data: EventPayloadMap[C]) => void): () => void {
    if (!EVENT_CHANNELS.has(channel)) {
      throw new Error(`[IPCBridge] Attempt to listen to unauthorized channel: ${channel}`);
    }

    // We wrap the listener to drop the Electron event arg
    const wrapped = (_evt: IpcRendererEvent, data: EventPayloadMap[C]) => listener(data);
    ipcRenderer.on(channel, wrapped);

    // Return unsubscribe function
    return () => ipcRenderer.removeListener(channel, wrapped);
  }

  /* ------------------------------------------- public façade (type-safe) ----------------------------------------- */

  /* Canvas & Node */
  static async createNode(payload: CreateNodePayload) {
    return IPCBridge.invoke(RendererToMainChannel.CREATE_NODE, payload);
  }

  static onNodeCreated(
    listener: (data: EventPayloadMap[MainToRendererChannel.NODE_CREATED]) => void,
  ) {
    return IPCBridge.on(MainToRendererChannel.NODE_CREATED, listener);
  }

  /* Themes */
  static async applyTheme(payload: ApplyThemePayload) {
    return IPCBridge.invoke(RendererToMainChannel.APPLY_THEME, payload);
  }

  static onThemeApplied(
    listener: (data: EventPayloadMap[MainToRendererChannel.THEME_APPLIED]) => void,
  ) {
    return IPCBridge.on(MainToRendererChannel.THEME_APPLIED, listener);
  }

  /* Workspace export */
  static async exportWorkspace(payload: ExportWorkspacePayload) {
    return IPCBridge.invoke(RendererToMainChannel.EXPORT_WORKSPACE, payload);
  }

  static onWorkspaceExported(
    listener: (data: WorkspaceExportResult) => void,
  ) {
    return IPCBridge.on(MainToRendererChannel.WORKSPACE_EXPORTED, listener);
  }

  /* App-level helpers */
  static openSettings() {
    return IPCBridge.invoke(RendererToMainChannel.OPEN_SETTINGS, void 0);
  }

  static reportCrash(reason: string, stack?: string) {
    return IPCBridge.invoke(RendererToMainChannel.REPORT_CRASH, { reason, stack });
  }

  static onUpdateAvailable(listener: (info: EventPayloadMap[MainToRendererChannel.UPDATE_AVAILABLE]) => void) {
    return IPCBridge.on(MainToRendererChannel.UPDATE_AVAILABLE, listener);
  }

  /* Plugin system */
  static async getPluginApi<T = unknown>(pluginId: string): Promise<T> {
    return IPCBridge.invoke(RendererToMainChannel.REQUEST_PLUGIN_API, { pluginId }) as Promise<T>;
  }

  static onPluginApiResponse(
    listener: (data: EventPayloadMap[MainToRendererChannel.PLUGIN_API_RESPONSE]) => void,
  ) {
    return IPCBridge.on(MainToRendererChannel.PLUGIN_API_RESPONSE, listener);
  }
}

/* --------------------------------------------------------------------------------------------------------------------
 * 5. Expose to isolated world via contextBridge  (executed only when running inside Preload)
 * ------------------------------------------------------------------------------------------------------------------ */
try {
  // In renderer bundles `contextBridge` is undefined because we bundled for the DOM,
  // keep the runtime guard to prevent “contextBridge is not defined” errors.
  if (contextBridge && typeof contextBridge.exposeInMainWorld === 'function') {
    contextBridge.exposeInMainWorld('paletteflow', {
      canvas: {
        createNode           : IPCBridge.createNode,
        onNodeCreated        : IPCBridge.onNodeCreated,
        applyTheme           : IPCBridge.applyTheme,
        onThemeApplied       : IPCBridge.onThemeApplied,
      },
      workspace: {
        export               : IPCBridge.exportWorkspace,
        onExported           : IPCBridge.onWorkspaceExported,
      },
      app: {
        openSettings         : IPCBridge.openSettings,
        reportCrash          : IPCBridge.reportCrash,
        onUpdateAvailable    : IPCBridge.onUpdateAvailable,
      },
      plugins: {
        getApi               : IPCBridge.getPluginApi,
        onApiResponse        : IPCBridge.onPluginApiResponse,
      },
    });
  }
} catch (err) {
  // eslint-disable-next-line no-console
  console.error('[IPCBridge] Failed to expose bridge in main world:', err);
}

/* --------------------------------------------------------------------------------------------------------------------
 * 6. Export default for renderer code that imports this module directly
 * ------------------------------------------------------------------------------------------------------------------ */
export default IPCBridge;
```
