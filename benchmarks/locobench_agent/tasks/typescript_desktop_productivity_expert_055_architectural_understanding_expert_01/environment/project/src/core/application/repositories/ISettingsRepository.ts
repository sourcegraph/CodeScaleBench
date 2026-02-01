```typescript
/**
 * PaletteFlow Studio
 * ------------------
 * Core › Application › Repositories
 *
 * This interface defines the contract that any persistence
 * adapter must satisfy in order to provide application and
 * plugin settings to the rest of the system.  Concrete
 * implementations live in the *infrastructure* layer
 * (Electron-store, SQLite, cloud sync, etc.) and are wired
 * through IoC at runtime.
 */

import { Observable } from 'rxjs';

import { AppSettings } from '../../domain/entities/AppSettings';
import {
  PluginSettings,
  PluginIdentifier,
} from '../../domain/entities/plugins';

/**
 * Repository for application-wide and plugin-scoped settings.
 *
 * All methods return *immutable* objects to discourage accidental
 * object-graph mutation.  Callers work with snapshots and then
 * explicitly persist their changes through `save`, `update`, or
 * plugin-specific counterparts.
 */
export interface ISettingsRepository {
  /* ────────────────────────────────────────────────────────────
   * Application-wide settings
   * ──────────────────────────────────────────────────────────── */

  /**
   * Retrieve the current snapshot of application settings.
   */
  get(): Promise<Readonly<AppSettings>>;

  /**
   * Persist a fresh snapshot of settings.  The implementation is
   * expected to perform validation, migration, and sanitisation
   * before writing to storage.
   *
   * Resolves with the persisted (and possibly transformed) snapshot.
   */
  save(settings: AppSettings): Promise<Readonly<AppSettings>>;

  /**
   * Merge a partial update into the existing settings snapshot
   * and persist the result atomically.
   */
  update(
    partial: Partial<AppSettings>,
  ): Promise<Readonly<AppSettings>>;

  /**
   * Reactively observe settings changes originating from any
   * source (UI, plugins, auto-sync, etc.).  The observable must
   * multicast the **same** snapshot instance to all subscribers
   * (e.g. `shareReplay(1)`), guaranteeing referential equality.
   */
  observe(): Observable<Readonly<AppSettings>>;

  /**
   * Restore factory defaults and return the clean snapshot.
   * Implementations should keep an internal history so that
   * a caller could implement "Undo reset" if desired.
   */
  resetToDefaults(): Promise<Readonly<AppSettings>>;

  /* ────────────────────────────────────────────────────────────
   * Plugin-scoped settings
   * ──────────────────────────────────────────────────────────── */

  /**
   * Retrieve settings belonging to a single plugin.
   * When the plugin has never stored any settings, an
   * empty object is returned instead of `null`.
   */
  getPluginSettings<T extends PluginSettings = PluginSettings>(
    pluginId: PluginIdentifier,
  ): Promise<Readonly<T>>;

  /**
   * Atomically merge and persist plugin settings.
   * Implementations **must** isolate each plugin’s data so that
   * malicious code cannot tamper with others.
   */
  updatePluginSettings<T extends PluginSettings = PluginSettings>(
    pluginId: PluginIdentifier,
    partial: Partial<T>,
  ): Promise<Readonly<T>>;

  /**
   * Remove *all* settings belonging to a plugin.  No-ops when the
   * plugin had no persisted data.
   */
  resetPluginSettings(pluginId: PluginIdentifier): Promise<void>;
}

/**
 * Injection token used by the IoC container.  Consumers should
 * reference the symbol instead of hard-coding class names.
 */
export const ISettingsRepositoryToken = Symbol.for('pf.core.ISettingsRepository');
```