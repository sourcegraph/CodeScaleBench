```typescript
/********************************************************************************************************************
 *  PaletteFlow Studio
 *  File: src/main/services/IpcMainManager.ts
 *
 *  The IpcMainManager wires Electron’s ipcMain to the rest of the application core in a
 *  cohesive, safe-by-default way.  All main-process <-> renderer traffic MUST pass through
 *  this class so that:
 *    •  Every message is typed, validated, and logged
 *    •  Domain-layer use-cases stay framework-agnostic
 *    •  We retain a single place to harden against malformed/hostile renderer input
 *
 *  NOTE: Never invoke ipcMain.on / ipcMain.handle outside of this file.
 ********************************************************************************************************************/

import { BrowserWindow, IpcMainEvent, IpcMainInvokeEvent, ipcMain } from 'electron';
import { autoUpdater } from 'electron-updater';

import { ILogger } from '../logging/ILogger';
import { CrashReporter } from '../crash/CrashReporter';
import { SettingsService } from '../settings/SettingsService';
import { WindowRegistry } from '../windows/WindowRegistry';
import { PluginBridge } from '../plugins/PluginBridge';

// Domain use-cases (thin proxies to the application core)
import { CreateNode } from '../../core/usecases/CreateNode';
import { ApplyTheme } from '../../core/usecases/ApplyTheme';
import { ExportWorkspace } from '../../core/usecases/ExportWorkspace';

/**
 * IPC channels are stringly typed; to reduce error-proneness we maintain a strongly-typed
 * map of well-known channels here.  Plugin channels are dynamically added at runtime.
 */
export const IPC_CHANNELS = {
    // Renderer lifecycle
    RENDERER_READY: 'renderer:ready',
    // Workspace
    CREATE_NODE: 'workspace:create-node',
    EXPORT_WORKSPACE: 'workspace:export',
    APPLY_THEME: 'workspace:apply-theme',
    // Settings
    SETTINGS_GET: 'settings:get',
    SETTINGS_SET: 'settings:set',
    // Auto-updates
    CHECK_FOR_UPDATES: 'app:check-for-updates',
    // Crash / analytics
    TRACK_EVENT: 'analytics:track-event',
    // Plugin passthrough
    PLUGIN_MESSAGE: 'plugin:message',
} as const;

export type IpcChannel = typeof IPC_CHANNELS[keyof typeof IPC_CHANNELS];

/**
 *  Utility: coerces an unknown renderer payload into a given runtime guard.
 */
function assert<T>(
    guard: (value: unknown) => value is T,
    value: unknown,
    errMessage: string,
): T {
    if (!guard(value)) {
        throw new Error(errMessage);
    }
    return value;
}

export interface IpcMainManagerDependencies {
    logger: ILogger;
    windowRegistry: WindowRegistry;
    settings: SettingsService;
    crashReporter: CrashReporter;
    pluginBridge: PluginBridge;
    createNode: CreateNode;
    applyTheme: ApplyTheme;
    exportWorkspace: ExportWorkspace;
}

/**
 *  Central registry for all ipcMain listeners.
 */
export class IpcMainManager {
    private readonly log: ILogger;
    private readonly deps: IpcMainManagerDependencies;

    /** Keep track of added listeners for clean shutdown / hot reload */
    private readonly registeredListeners: Array<{
        channel: IpcChannel | string;
        type: 'on' | 'handle';
        listener: (...args: any[]) => void | Promise<void>;
    }> = [];

    constructor(deps: IpcMainManagerDependencies) {
        this.deps = deps;
        this.log = deps.logger.child({ scope: 'IpcMainManager' });
    }

    /**
     *  Initializes all core IPC handlers and wires plugin-contributed ones.
     */
    public initialize(): void {
        this.log.info('Initializing IPC main listeners …');

        /* -------------------------------------------------------------
         *  Renderer lifecycle
         * ----------------------------------------------------------- */
        this.on(IPC_CHANNELS.RENDERER_READY, this.handleRendererReady.bind(this));

        /* -------------------------------------------------------------
         *  Workspace / domain use-cases
         * ----------------------------------------------------------- */
        this.handle(IPC_CHANNELS.CREATE_NODE, this.handleCreateNode.bind(this));
        this.handle(IPC_CHANNELS.EXPORT_WORKSPACE, this.handleExportWorkspace.bind(this));
        this.handle(IPC_CHANNELS.APPLY_THEME, this.handleApplyTheme.bind(this));

        /* -------------------------------------------------------------
         *  Settings
         * ----------------------------------------------------------- */
        this.handle(IPC_CHANNELS.SETTINGS_GET, this.handleSettingsGet.bind(this));
        this.handle(IPC_CHANNELS.SETTINGS_SET, this.handleSettingsSet.bind(this));

        /* -------------------------------------------------------------
         *  Auto-updates
         * ----------------------------------------------------------- */
        this.handle(IPC_CHANNELS.CHECK_FOR_UPDATES, this.handleCheckForUpdates.bind(this));

        /* -------------------------------------------------------------
         *  Crash analytics
         * ----------------------------------------------------------- */
        this.on(IPC_CHANNELS.TRACK_EVENT, this.handleTrackEvent.bind(this));

        /* -------------------------------------------------------------
         *  Plugin passthrough
         * ----------------------------------------------------------- */
        this.on(IPC_CHANNELS.PLUGIN_MESSAGE, this.handlePluginMessage.bind(this));

        this.log.info(`IPC initialization complete. Registered ${this.registeredListeners.length} listener(s).`);
    }

    /**
     *  Cleanly removes all listeners.  Useful during hot-reload or when running tests.
     */
    public dispose(): void {
        for (const { channel, type, listener } of this.registeredListeners) {
            try {
                if (type === 'on') {
                    ipcMain.removeListener(channel, listener);
                } else {
                    // ipcMain.handle wraps a listener on the internal map; .removeHandler is idempotent
                    ipcMain.removeHandler(channel);
                }
                this.log.debug(`Unregistered IPC listener '${channel}'.`);
            } catch (err) {
                this.log.error(err, `Failed to unregister listener '${channel}'.`);
            }
        }
        this.registeredListeners.length = 0;
    }

    /* ****************************************************************************************************************
     *  Helper registration methods
     **************************************************************************************************************** */

    private on(channel: IpcChannel | string, listener: (event: IpcMainEvent, ...args: any[]) => void) {
        ipcMain.on(channel, listener);
        this.registeredListeners.push({ channel, listener, type: 'on' });
    }

    private handle(
        channel: IpcChannel | string,
        listener: (event: IpcMainInvokeEvent, ...args: any[]) => Promise<unknown>,
    ) {
        ipcMain.handle(channel, listener);
        this.registeredListeners.push({ channel, listener, type: 'handle' });
    }

    /* ****************************************************************************************************************
     *  IPC Handlers
     **************************************************************************************************************** */

    // --------------------------------- Renderer lifecycle ----------------------------------------------------------

    private handleRendererReady(event: IpcMainEvent): void {
        const window = BrowserWindow.fromWebContents(event.sender);
        this.log.info({ id: window?.id }, 'Renderer signaled readiness.');
    }

    // --------------------------------- Workspace use-cases --------------------------------------------------------

    private async handleCreateNode(event: IpcMainInvokeEvent, payload: unknown): Promise<string> {
        try {
            const { workspaceId, type, initialContent } = assert<
                { workspaceId: string; type: string; initialContent?: unknown }
            >(
                (v): v is { workspaceId: string; type: string; initialContent?: unknown } =>
                    typeof v === 'object' &&
                    v !== null &&
                    typeof (v as any).workspaceId === 'string' &&
                    typeof (v as any).type === 'string',
                payload,
                'Invalid payload for CREATE_NODE',
            );

            const nodeId = await this.deps.createNode.execute({
                workspaceId,
                nodeType: type,
                initialContent,
            });

            this.log.info({ nodeId, workspaceId }, 'Node created via IPC.');
            return nodeId;
        } catch (err) {
            this.handleError(event, err, 'Failed to create node');
            throw err; // rethrow so renderer gets rejection
        }
    }

    private async handleExportWorkspace(event: IpcMainInvokeEvent, payload: unknown): Promise<string> {
        try {
            const { workspaceId, format } = assert<{ workspaceId: string; format: string }>(
                (v): v is { workspaceId: string; format: string } =>
                    typeof v === 'object' &&
                    v !== null &&
                    typeof (v as any).workspaceId === 'string' &&
                    typeof (v as any).format === 'string',
                payload,
                'Invalid payload for EXPORT_WORKSPACE',
            );

            const filePath = await this.deps.exportWorkspace.execute({ workspaceId, format });
            this.log.info({ workspaceId, filePath }, 'Workspace exported via IPC.');

            return filePath;
        } catch (err) {
            this.handleError(event, err, 'Failed to export workspace');
            throw err;
        }
    }

    private async handleApplyTheme(event: IpcMainInvokeEvent, payload: unknown): Promise<void> {
        try {
            const { themeId } = assert<{ themeId: string }>(
                (v): v is { themeId: string } =>
                    typeof v === 'object' && v !== null && typeof (v as any).themeId === 'string',
                payload,
                'Invalid payload for APPLY_THEME',
            );

            await this.deps.applyTheme.execute({ themeId });
            this.log.info({ themeId }, 'Theme applied via IPC.');
        } catch (err) {
            this.handleError(event, err, 'Failed to apply theme');
            throw err;
        }
    }

    // --------------------------------- Settings --------------------------------------------------------------------

    private async handleSettingsGet(): Promise<Record<string, unknown>> {
        try {
            return this.deps.settings.getAll();
        } catch (err) {
            this.log.error(err, 'Failed to retrieve settings');
            throw err;
        }
    }

    private async handleSettingsSet(
        _event: IpcMainInvokeEvent,
        kv: unknown,
    ): Promise<Record<string, unknown>> {
        try {
            const data = assert<Record<string, unknown>>(
                (v): v is Record<string, unknown> => typeof v === 'object' && v !== null,
                kv,
                'Invalid payload for SETTINGS_SET',
            );

            const updated = await this.deps.settings.setMany(data);
            this.log.info({ updatedKeys: Object.keys(data) }, 'Settings updated via IPC.');
            return updated;
        } catch (err) {
            this.log.error(err, 'Failed to update settings via IPC.');
            throw err;
        }
    }

    // --------------------------------- Auto-updates ----------------------------------------------------------------

    private async handleCheckForUpdates(): Promise<void> {
        try {
            await autoUpdater.checkForUpdates();
            this.log.info('Manual update check triggered via IPC.');
        } catch (err) {
            this.log.error(err, 'Failed to check for updates via IPC.');
            throw err;
        }
    }

    // --------------------------------- Crash / analytics -----------------------------------------------------------

    private handleTrackEvent(_event: IpcMainEvent, payload: unknown): void {
        try {
            const { category, action, label, value } = assert<
                { category: string; action: string; label?: string; value?: number }
            >(
                (v): v is { category: string; action: string; label?: string; value?: number } =>
                    typeof v === 'object' &&
                    v !== null &&
                    typeof (v as any).category === 'string' &&
                    typeof (v as any).action === 'string',
                payload,
                'Invalid payload for TRACK_EVENT',
            );

            this.deps.crashReporter.captureBreadcrumb({
                category,
                message: `${action}${label ? ` (${label})` : ''}`,
                data: { value },
            });
        } catch (err) {
            this.log.warn(err, 'Malformed analytics event ignored.');
        }
    }

    // --------------------------------- Plugin messages -------------------------------------------------------------

    private handlePluginMessage(event: IpcMainEvent, payload: unknown): void {
        try {
            const msg = assert<
                {
                    pluginId: string;
                    event: string;
                    data?: unknown;
                }
            >(
                (v): v is { pluginId: string; event: string; data?: unknown } =>
                    typeof v === 'object' &&
                    v !== null &&
                    typeof (v as any).pluginId === 'string' &&
                    typeof (v as any).event === 'string',
                payload,
                'Invalid payload for PLUGIN_MESSAGE',
            );

            this.deps.pluginBridge.emitToPlugin(msg.pluginId, msg.event, msg.data);
            this.log.debug({ pluginId: msg.pluginId, event: msg.event }, 'Routed plugin IPC message.');
        } catch (err) {
            this.handleError(event, err, 'Failed to route plugin message');
        }
    }

    /* ****************************************************************************************************************
     *  Helpers
     **************************************************************************************************************** */

    private handleError(event: IpcMainEvent | IpcMainInvokeEvent, err: unknown, userMessage: string) {
        this.log.error(err, userMessage);

        const window = BrowserWindow.fromWebContents(event.sender);
        if (!window?.isDestroyed()) {
            // Send a safe, non-technical message back to renderer so it can surface a toast
            window.webContents.send('app:error', { message: userMessage });
        }

        // Enrich crash reporter
        this.deps.crashReporter.captureException(err as Error, { hint: userMessage });
    }
}
```