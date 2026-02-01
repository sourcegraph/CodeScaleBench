```typescript
/***************************************************************************************************
 * SettingsService.ts
 *
 * Centralised configuration manager for PaletteFlow Studio.
 * Handles:
 *  • Loading / persisting strongly-typed settings to the userData folder
 *  • Runtime change notifications (EventEmitter)
 *  • Schema validation & implicit migrations
 *  • Plugin-level default overrides / extensions
 *
 * The service is framework-agnostic; Electron specifics are kept to minimal `app.getPath`.
 *
 * NOTE:  This service must only be instantiated once per process.  Import the default instance.
 ***************************************************************************************************/

import { app } from 'electron';
import fs from 'fs/promises';
import { existsSync } from 'fs';
import path from 'path';
import { EventEmitter } from 'events';
import { z } from 'zod';
import deepmerge from 'deepmerge';
import debounce from 'lodash.debounce';

/* -------------------------------------------------------------------------------------------------
 * Types & Schemas
 * -----------------------------------------------------------------------------------------------*/

export const CURRENT_SETTINGS_VERSION = 2;

/**
 * Core application settings schema. Plugins can extend this at runtime by using
 * `SettingsService.registerPluginDefaults()`, which deep-merges the defaults
 * without touching this core schema.
 */
const CoreSettingsSchema = z.object({
  version: z.number().default(CURRENT_SETTINGS_VERSION),

  /* App-wide behaviour ----------------------------------------------------*/
  theme: z.enum(['light', 'dark', 'system']).default('system'),
  language: z.string().default('en-US'),
  enableAutoUpdates: z.boolean().default(true),
  enableCrashReporting: z.boolean().default(true),

  /* Window & session ------------------------------------------------------*/
  window: z
    .object({
      width: z.number().min(640).default(1280),
      height: z.number().min(480).default(800),
      isMaximized: z.boolean().default(false),
      lastOpenedWorkspace: z.string().nullable().default(null),
    })
    .default({}),

  /* Recent files, MRU lists ----------------------------------------------*/
  recentWorkspaces: z.string().array().default([]),

  /* Plugin namespace placeholder (filled dynamically) ---------------------*/
  plugins: z.record(z.any()).default({}),
});

export type CoreSettings = z.infer<typeof CoreSettingsSchema>;

/* -------------------------------------------------------------------------------------------------
 * Helper utilities
 * -----------------------------------------------------------------------------------------------*/

/** Safely ensure that a folder exists, creating it recursively if missing. */
async function ensureDir(dirPath: string) {
  if (!existsSync(dirPath)) {
    await fs.mkdir(dirPath, { recursive: true });
  }
}

/** Small wrapper to do `await` on fs.writeFile with proper JSON formatting. */
async function writeJSON(file: string, data: unknown) {
  const json = JSON.stringify(data, null, 2);
  await fs.writeFile(file, json, { encoding: 'utf-8' });
}

/* -------------------------------------------------------------------------------------------------
 * SettingsService
 * -----------------------------------------------------------------------------------------------*/

class SettingsService extends EventEmitter {
  private readonly settingsPath: string;
  private settings: CoreSettings;
  private isReady = false;

  /** Debounced disk persist to avoid excessive writes during rapid updates. */
  private readonly persistDebounced = debounce(() => this.persist().catch(console.error), 500);

  constructor() {
    super();
    const userData = app.getPath('userData');
    this.settingsPath = path.join(userData, 'settings.json');
    this.settings = CoreSettingsSchema.parse({});
  }

  /* -----------------------------------------------------------------------*
   * Public API
   * ----------------------------------------------------------------------*/

  /**
   * Bootstraps the service. Must be called once during app start-up before
   * interacting with any getters / setters.
   */
  async init(): Promise<void> {
    await ensureDir(path.dirname(this.settingsPath));

    if (existsSync(this.settingsPath)) {
      try {
        const raw = await fs.readFile(this.settingsPath, { encoding: 'utf-8' });
        const parsed = JSON.parse(raw);
        this.settings = await this.applyMigrations(parsed);
      } catch (err) {
        console.error('[SettingsService] Failed to load settings; falling back to defaults.', err);
        this.settings = CoreSettingsSchema.parse({});
      }
    } else {
      /* Fresh install: write file so that later edits have a base */
      this.settings = CoreSettingsSchema.parse({});
      await this.persist();
    }

    this.isReady = true;
    this.emit('ready', this.settings);
  }

  /**
   * Reads a settings value via dot-notation, e.g. `get('window.width')`.
   * Returns `undefined` if key path does not exist.
   */
  get<T = unknown>(keyPath: string): T | undefined {
    this.assertReady();
    return keyPath.split('.').reduce<any>((obj, key) => obj?.[key], this.settings);
  }

  /**
   * Updates a settings value via dot-notation; persists automatically.
   * Emits `change` event with args `(keyPath, newValue, oldValue)`.
   */
  async set<T = unknown>(keyPath: string, value: T): Promise<void> {
    this.assertReady();

    const keys = keyPath.split('.');
    const lastKey = keys.pop() as string;
    let cursor: any = this.settings;

    for (const key of keys) {
      if (cursor[key] == null || typeof cursor[key] !== 'object') cursor[key] = {};
      cursor = cursor[key];
    }

    const oldValue = cursor[lastKey];
    if (oldValue === value) return; // no-op

    cursor[lastKey] = value;

    this.emit('change', keyPath, value, oldValue);
    this.persistDebounced();
  }

  /**
   * Register default settings for a plugin namespace. The provided defaults
   * are deep-merged with existing settings; user overrides remain intact.
   */
  registerPluginDefaults(pluginId: string, defaults: Record<string, unknown>) {
    this.assertReady();
    const existing = this.settings.plugins[pluginId] ?? {};
    this.settings.plugins[pluginId] = deepmerge(defaults, existing);
    // Immediately flush to disk; plugin registration usually happens once.
    this.persistDebounced();
  }

  /**
   * Subscribe to change events for reactive consumption.
   * Returns an unsubscribe function.
   */
  onChange(
    listener: (keyPath: string, newValue: unknown, oldValue: unknown) => void,
  ): () => void {
    this.on('change', listener);
    return () => this.off('change', listener);
  }

  /**
   * Returns the in-memory immutable snapshot of the full settings object.
   * Do not mutate this object directly!
   */
  snapshot(): Readonly<CoreSettings> {
    this.assertReady();
    return Object.freeze({ ...this.settings });
  }

  /* -----------------------------------------------------------------------*
   * Internals
   * ----------------------------------------------------------------------*/

  /** Writes current state to disk.  Debounced by `persistDebounced`. */
  private async persist(): Promise<void> {
    try {
      await writeJSON(this.settingsPath, this.settings);
    } catch (err) {
      // Persist errors are non-fatal but worth logging.
      console.error('[SettingsService] Failed to persist settings:', err);
    }
  }

  /** Ensures .init() has run before any interaction */
  private assertReady() {
    if (!this.isReady) {
      throw new Error(
        'SettingsService has not been initialised. Call await Settings.init() first.',
      );
    }
  }

  /** Apply migrations between schema versions. */
  private async applyMigrations(raw: any): Promise<CoreSettings> {
    let workingCopy = { ...raw };

    const fromVersion: number = workingCopy.version ?? 0;

    if (fromVersion < 1) {
      // v0 ➜ v1 migration:
      // • rename `auto_updates` ➜ `enableAutoUpdates`
      // • rename `crash_reporting` ➜ `enableCrashReporting`
      if (Object.prototype.hasOwnProperty.call(workingCopy, 'auto_updates')) {
        workingCopy.enableAutoUpdates = workingCopy.auto_updates;
        delete workingCopy.auto_updates;
      }
      if (Object.prototype.hasOwnProperty.call(workingCopy, 'crash_reporting')) {
        workingCopy.enableCrashReporting = workingCopy.crash_reporting;
        delete workingCopy.crash_reporting;
      }
    }

    if (fromVersion < 2) {
      // v1 ➜ v2 migration:
      // • Add `plugins` root namespace if missing
      if (!workingCopy.plugins) workingCopy.plugins = {};
    }

    workingCopy.version = CURRENT_SETTINGS_VERSION;

    // Validate against latest schema; throws if invalid
    return CoreSettingsSchema.parse(workingCopy);
  }
}

/* -------------------------------------------------------------------------------------------------
 * Export singleton instance
 * -----------------------------------------------------------------------------------------------*/

const instance = new SettingsService();
export default instance;

/* -------------------------------------------------------------------------------------------------
 * Ambient type augmentation for Plugin authors
 * -----------------------------------------------------------------------------------------------*/

/**
 * To make plugin defaults type-safe, plugin authors can augment the SettingsMap
 * using TypeScript's module augmentation:
 *
 * declare module '@palette-flow/settings' {
 *   interface PluginSettings {
 *     myPlugin: {
 *       enabled: boolean;
 *       customPalette: string[];
 *     };
 *   }
 * }
 */

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace PaletteFlow {
    interface PluginSettings {} // extended by plugins
  }
}
```