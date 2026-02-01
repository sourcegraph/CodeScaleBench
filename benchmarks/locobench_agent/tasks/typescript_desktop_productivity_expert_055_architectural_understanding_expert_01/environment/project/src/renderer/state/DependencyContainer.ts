```typescript
/**
 * PaletteFlow Studio – DependencyContainer
 *
 * This file wires together the dependency-injection graph that is used by the
 * renderer process.  We build on top of `tsyringe`, a lightweight, reflection-
 * free container that plays nicely with tree-shaking and supports Electron
 * hot-reload scenarios out of the box.
 *
 * NOTE:
 *   Every service or state store that needs to be shared across React/Preact
 *   components, view-models or IPC handlers should be registered here.  Keep
 *   this file lean—**never** import heavy domain logic directly; instead import
 *   thin façade classes (use-cases, stores, helpers) so that we don’t bloat the
 *   renderer bundle.
 */

import {
  container as rootContainer,
  DependencyContainer as TsyringeContainer,
  InjectionToken,
  Lifecycle,
  delay,
} from 'tsyringe';
import { ipcRenderer, IpcRendererEvent } from 'electron';

// We purposefully import *types* only here (they’ll be erased at compile time)
import type { CanvasStore } from '../view-model/CanvasStore';
import type { WorkspaceStore } from '../view-model/WorkspaceStore';
import type { ThemeStore } from '../view-model/ThemeStore';
import type { CommandRegistry } from '../../shared/commands/CommandRegistry';
import type { PluginRegistry } from '../../shared/plugins/PluginRegistry';
import type { SettingsService } from '../../shared/settings/SettingsService';
import type { AnalyticsService } from '../../shared/analytics/AnalyticsService';

/* -------------------------------------------------------------------------- */
/*                             Injection Tokens                               */
/* -------------------------------------------------------------------------- */

/**
 * Using Symbols instead of strings prevents clashes when plugins register their
 * own services.
 */
export const TOKENS = {
  CanvasStore: Symbol.for('CanvasStore'),
  WorkspaceStore: Symbol.for('WorkspaceStore'),
  ThemeStore: Symbol.for('ThemeStore'),
  CommandRegistry: Symbol.for('CommandRegistry'),
  PluginRegistry: Symbol.for('PluginRegistry'),
  SettingsService: Symbol.for('SettingsService'),
  AnalyticsService: Symbol.for('AnalyticsService'),
} as const;

/* -------------------------------------------------------------------------- */
/*                      Conditional (lazy) dependency load                    */
/* -------------------------------------------------------------------------- */

/**
 * Because some services are dynamically imported (to cut initial bundle size),
 * we expose helper factories.  They return promises so that consumers can
 * `await container.resolveAsync(TOKENS.X)`.
 */
const factories = {
  async CanvasStore(): Promise<CanvasStore> {
    const { CanvasStoreImpl } = await import('../view-model/CanvasStore');
    return new CanvasStoreImpl();
  },
  async WorkspaceStore(): Promise<WorkspaceStore> {
    const { WorkspaceStoreImpl } = await import('../view-model/WorkspaceStore');
    return new WorkspaceStoreImpl();
  },
  async ThemeStore(): Promise<ThemeStore> {
    const { ThemeStoreImpl } = await import('../view-model/ThemeStore');
    return new ThemeStoreImpl();
  },
  async CommandRegistry(): Promise<CommandRegistry> {
    const { CommandRegistryImpl } = await import('../../shared/commands/CommandRegistry');
    return new CommandRegistryImpl();
  },
  async PluginRegistry(): Promise<PluginRegistry> {
    const { PluginRegistryImpl } = await import('../../shared/plugins/PluginRegistry');
    return new PluginRegistryImpl();
  },
  async SettingsService(): Promise<SettingsService> {
    const { SettingsServiceImpl } = await import('../../shared/settings/SettingsService');
    return new SettingsServiceImpl();
  },
  async AnalyticsService(): Promise<AnalyticsService> {
    const { AnalyticsServiceImpl } = await import('../../shared/analytics/AnalyticsService');
    return new AnalyticsServiceImpl();
  },
};

/* -------------------------------------------------------------------------- */
/*                         DependencyContainer façade                         */
/* -------------------------------------------------------------------------- */

export class DependencyContainer {
  /**
   * We keep the underlying tsyringe container private so we can swap or reset
   * it during hot reload without leaking references.
   */
  private static _container: TsyringeContainer | null = null;

  /**
   * Call once, ideally at application start.  Subsequent calls are ignored
   * unless the container has been explicitly `reset()`.
   */
  public static init(): void {
    if (this._container) {
      return;
    }

    // Re-use container across hot-reload cycles (only in dev).
    const globalKey = '__pfStudioDIContainer';
    if (import.meta.env?.DEV && (globalThis as any)[globalKey]) {
      this._container = (globalThis as any)[globalKey] as TsyringeContainer;
      return;
    }

    this._container = rootContainer.createChildContainer();

    // Register synchronous/lite dependencies here…
    this._container.register(TOKENS.SettingsService, {
      useFactory: delay(() => factories.SettingsService()),
    });
    this._container.register(TOKENS.AnalyticsService, {
      useFactory: delay(() => factories.AnalyticsService()),
    });

    // Stores (they depend on settings/analytics, but we register them
    // un-instantiated so tsyringe resolves deps lazily).
    this._container.register(TOKENS.CanvasStore, {
      useFactory: delay(() => factories.CanvasStore()),
      lifecycle: Lifecycle.Singleton,
    });
    this._container.register(TOKENS.WorkspaceStore, {
      useFactory: delay(() => factories.WorkspaceStore()),
      lifecycle: Lifecycle.Singleton,
    });
    this._container.register(TOKENS.ThemeStore, {
      useFactory: delay(() => factories.ThemeStore()),
      lifecycle: Lifecycle.Singleton,
    });

    // Command & Plugin registries
    this._container.register(TOKENS.CommandRegistry, {
      useFactory: delay(() => factories.CommandRegistry()),
      lifecycle: Lifecycle.Singleton,
    });
    this._container.register(TOKENS.PluginRegistry, {
      useFactory: delay(() => factories.PluginRegistry()),
      lifecycle: Lifecycle.Singleton,
    });

    // Listen for IPC events that require DI look-ups (e.g., issued by main process)
    this.installIpcBridge();

    if (import.meta.env?.DEV) {
      (globalThis as any)[globalKey] = this._container;
    }
  }

  /**
   * Resolve a dependency synchronously.  Throws if the container has not been
   * initialised or if the token is async-only.
   */
  public static resolve<T>(token: InjectionToken<T>): T {
    if (!this._container) {
      throw new Error('DependencyContainer not initialised – call init() first.');
    }
    return this._container.resolve(token);
  }

  /**
   * Resolve an async factory-registered dependency.
   */
  public static async resolveAsync<T>(token: InjectionToken<T>): Promise<T> {
    if (!this._container) {
      throw new Error('DependencyContainer not initialised – call init() first.');
    }
    return await this._container.resolve<Promise<T>>(token);
  }

  /**
   * Allows plugins to register their own services at runtime.
   */
  public static registerSingleton<T>(
    token: InjectionToken<T>,
    ctor: new (...args: never[]) => T,
  ): void {
    if (!this._container) {
      throw new Error('DependencyContainer not initialised – call init() first.');
    }

    if (this._container.isRegistered(token)) {
      console.warn(
        `[DI] Token ${token.toString()} already registered – plugin override ignored.`,
      );
      return;
    }

    this._container.registerSingleton<T>(token, ctor);
  }

  /**
   * For testing & hot-reload only – wipes the current container.
   */
  public static reset(): void {
    this._container = null;
  }

  /* ------------------------------------------------------------------------ */
  /*                              IPC Integration                             */
  /* ------------------------------------------------------------------------ */

  /**
   * Expose a minimal IPC bridge so that the main process can request
   * information held only in the renderer (e.g., unsaved changes indicator).
   */
  private static installIpcBridge(): void {
    ipcRenderer.on('pfstudio:get-state', async (event: IpcRendererEvent, token: string) => {
      try {
        // eslint-disable-next-line @typescript-eslint/await-thenable
        const instance = await this.resolveAsync<any>(Symbol.for(token));
        event.reply(`pfstudio:get-state:response:${token}`, { ok: true, payload: instance });
      } catch (err) {
        console.error('[IPC Bridge] Failed to resolve token', token, err);
        event.reply(`pfstudio:get-state:response:${token}`, {
          ok: false,
          error: (err as Error).message,
        });
      }
    });
  }
}
```