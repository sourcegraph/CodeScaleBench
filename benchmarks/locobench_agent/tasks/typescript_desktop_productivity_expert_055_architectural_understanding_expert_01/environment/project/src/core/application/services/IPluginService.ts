```typescript
/*********************************************************************************************************************
 * PaletteFlow Studio
 * File: src/core/application/services/IPluginService.ts
 *
 * Description:
 *   Public contract for the Plugin Service that lives in the application layer.
 *   Concrete implementations are provided by the infrastructure layer (e.g. an
 *   Electron-specific service that performs I/O, signature verification, hot-reloading,
 *   etc.).  Nothing in this file should import from a UI framework or Node-specific
 *   API—keep it platform-agnostic so the domain layer can consume it without
 *   additional dependencies.
 *
 *   The service is responsible for installing, loading, enabling, disabling, and
 *   uninstalling Palette Plugins at runtime.  It also exposes an event emitter so
 *   other application services (command palette, crash reporter, analytics) can
 *   react to changes in the plugin ecosystem.
 *
 * ---------------------------------------------------------------------------------------------------
 * NOTE:
 *   All complex types (PluginManifest, NodeRendererFactory, etc.) live under
 *   `src/core/domain` to ensure independence from implementation details.  They are
 *   re-exported here purely for developer ergonomics.
 *********************************************************************************************************************/

import { Readable } from 'stream';

import {
    PluginId,
    PluginManifest,
    PluginState,
    InstalledPlugin,
    PluginHookName,
    PluginHookArguments,
    PluginHookResult,
    NodeRendererFactory
} from '../../domain/plugins';

/* ------------------------------------------------------------------------------------------------
 * Error Types
 * ---------------------------------------------------------------------------------------------- */

/**
 * Base class for all plugin-related errors thrown by the service.
 * Keeping a distinct hierarchy allows callers to gracefully recover or present
 * actionable UI messages to the user.
 */
export abstract class PluginServiceError extends Error {
    constructor(message: string) {
        super(message);
        this.name = new.target.name;
    }
}

/** Thrown when the requested plugin does not exist in the registry. */
export class PluginNotFoundError extends PluginServiceError {}
/** Thrown when a plugin fails schema validation or contains a runtime error. */
export class PluginValidationError extends PluginServiceError {}
/** Thrown when two plugins attempt to register conflicting capabilities. */
export class PluginConflictError extends PluginServiceError {}
/** Thrown when signature or hash verification fails. */
export class PluginSecurityError extends PluginServiceError {}

/* ------------------------------------------------------------------------------------------------
 * Event System
 * ---------------------------------------------------------------------------------------------- */

/** Discriminated union of all event types emitted by the service. */
export type PluginEvent =
    | { type: 'installed';  plugin: InstalledPlugin }
    | { type: 'enabled';    plugin: InstalledPlugin }
    | { type: 'disabled';   plugin: InstalledPlugin }
    | { type: 'updated';    plugin: InstalledPlugin }
    | { type: 'uninstalled';plugin: InstalledPlugin }
    | { type: 'reloaded';   plugin: InstalledPlugin }
    | { type: 'error';      plugin: InstalledPlugin | null; error: Error };

/** Listener signature for subscribing to plugin events. */
export type PluginEventListener = (event: PluginEvent) => void;
/** Returned by `subscribe` to remove an existing listener. */
export type UnsubscribeFn = () => void;

/* ------------------------------------------------------------------------------------------------
 * Installation Options
 * ---------------------------------------------------------------------------------------------- */

/**
 * Options available when installing a plugin from a remote URL or local package.
 */
export interface InstallOptions {
    /**
     * Trust level for unsigned plugins.  If `false` (default), the service must
     * perform signature/hash validation and throw `PluginSecurityError` on failure.
     */
    readonly trustUnsigned?: boolean;

    /** Optional semantic version range; used when installing from a registry. */
    readonly versionRange?: string;

    /**
     * If provided, forces the plugin to be installed into the specified
     * workspace-scoped directory instead of the global registry.
     */
    readonly targetWorkspaceId?: string;
}

/* ------------------------------------------------------------------------------------------------
 * IPluginService
 * ---------------------------------------------------------------------------------------------- */

/**
 * Contract defining the capabilities exposed by the Plugin Service.
 *
 * Implementations SHOULD:
 *   • Be thread-safe (plugin operations may be invoked from multiple windows)
 *   • Guard against malicious code (signature checks, sandboxing, timeouts)
 *   • Gracefully degrade when auto-updates or network connectivity are unavailable
 *
 * Implementations MUST:
 *   • Never throw generic errors—always use the specialised error classes
 *   • Keep side effects out of the domain layer; only expose pure data structures
 */
export interface IPluginService {
    // -------------------------------------------------------------------------------------------
    // Lifecycle
    // -------------------------------------------------------------------------------------------

    /**
     * Scans the plugin registry folders (global + workspace) and loads any plugin
     * that is marked as `enabled`.  Should be called during application startup.
     */
    loadEnabledPlugins(): Promise<void>;

    /**
     * Reloads a single plugin in place without requiring an application restart.
     * Implementations should dispose of the previous execution context before
     * activating the new one.
     */
    reloadPlugin(pluginId: PluginId): Promise<void>;

    /**
     * Completely unloads all plugins and tears down their execution contexts.
     * Primarily used in unit tests or when changing global security settings.
     */
    unloadAll(): Promise<void>;

    // -------------------------------------------------------------------------------------------
    // Installation / Uninstallation
    // -------------------------------------------------------------------------------------------

    /**
     * Installs a plugin from a local .tgz/.zip package.
     *
     * @param packageStream A readable stream containing the plugin archive.
     * @param options       Optional installation parameters.
     * @throws PluginValidationError | PluginConflictError | PluginSecurityError
     */
    installFromStream(
        packageStream: Readable,
        options?: InstallOptions
    ): Promise<InstalledPlugin>;

    /**
     * Installs a plugin from a remote HTTP(S) URL.
     *
     * The implementation MAY retrieve additional metadata from PaletteFlow’s
     * official Plugin Registry API before downloading the asset.
     */
    installFromUrl(
        url: URL,
        options?: InstallOptions
    ): Promise<InstalledPlugin>;

    /**
     * Uninstalls a plugin completely.  If the plugin is currently enabled, the
     * service must disable and unload it first.
     *
     * @throws PluginNotFoundError
     */
    uninstall(pluginId: PluginId): Promise<void>;

    // -------------------------------------------------------------------------------------------
    // Enable / Disable
    // -------------------------------------------------------------------------------------------

    /**
     * Marks a plugin as enabled and activates it immediately.
     *
     * @throws PluginNotFoundError | PluginValidationError | PluginSecurityError
     */
    enable(pluginId: PluginId): Promise<void>;

    /**
     * Disables a plugin and unloads its execution context.
     *
     * @throws PluginNotFoundError
     */
    disable(pluginId: PluginId): Promise<void>;

    // -------------------------------------------------------------------------------------------
    // Queries
    // -------------------------------------------------------------------------------------------

    /** Returns all plugins currently installed (enabled + disabled). */
    getInstalledPlugins(): Promise<InstalledPlugin[]>;

    /** Returns only the plugins that are actively enabled and running. */
    getEnabledPlugins(): Promise<InstalledPlugin[]>;

    /** Convenience helper for fetching a single plugin by its id. */
    getPlugin(pluginId: PluginId): Promise<InstalledPlugin>;

    // -------------------------------------------------------------------------------------------
    // Hook Execution
    // -------------------------------------------------------------------------------------------

    /**
     * Executes a named hook across all enabled plugins and aggregates the results.
     *
     * Hooks are a type-safe mechanism for plugins to expose functionality to the
     * host application (e.g. “provideNodeRenderers”, “beforeWorkspaceExport”).
     *
     * @param hook   The well-known hook name to invoke.
     * @param args   The argument payload forwarded to the plugin.
     * @returns      An array of results; one entry per plugin that implemented the hook.
     *
     * @throws PluginServiceError (generic) if any plugin throws synchronously.
     */
    runHook<
        TName extends PluginHookName,
        TResult extends PluginHookResult<TName> = PluginHookResult<TName>
    >(
        hook: TName,
        args: PluginHookArguments<TName>
    ): Promise<TResult[]>;

    // -------------------------------------------------------------------------------------------
    // Node Renderer Resolution
    // -------------------------------------------------------------------------------------------

    /**
     * Determines the renderer factory responsible for a specific node type.
     *
     * @param nodeType The canonical node type identifier (e.g. "markdown", "audio").
     * @returns        The registered renderer factory or `null` if none exists.
     */
    resolveRendererFactory(nodeType: string): Promise<NodeRendererFactory | null>;

    // -------------------------------------------------------------------------------------------
    // Event Subscription
    // -------------------------------------------------------------------------------------------

    /**
     * Subscribes to plugin lifecycle events.
     *
     * @param listener A callback that will be invoked synchronously for each event.
     * @returns        A cleanup function for removing the listener.
     */
    subscribe(listener: PluginEventListener): UnsubscribeFn;
}
```