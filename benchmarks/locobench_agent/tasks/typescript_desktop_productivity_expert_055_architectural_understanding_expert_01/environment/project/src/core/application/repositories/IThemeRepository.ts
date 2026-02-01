```typescript
/**
 * PaletteFlow Studio – Theme Repository Contract
 * ----------------------------------------------
 * This interface defines the abstraction through which application
 * use-cases interact with Theme persistence.  Implementations live in
 * the infrastructure layer (e.g. FileSystemThemeRepository,
 * SqliteThemeRepository, CloudSyncThemeRepository) and must satisfy the
 * invariants described below.
 *
 * Why an interface?
 * -----------------
 * • Enables Clean Architecture’s Dependency Inversion – the core does
 *   not depend on any specific storage or transport mechanism.
 * • Makes unit testing trivial by allowing in-memory or mocked
 *   repositories to be injected into use-cases.
 */

import { Observable } from 'rxjs';

import { Theme } from '../../domain/entities/Theme';
import { ThemeId } from '../../domain/value-objects/ThemeId';
import { Result } from '../common/Result';

/**
 * Strategy for handling conflicting writes when a Theme with the same
 * identifier already exists in the store.
 */
export enum WriteConflictStrategy {
  /**
   * Overwrite existing record unconditionally.
   */
  Overwrite = 'OVERWRITE',

  /**
   * Abort the operation and return an Err(Result) if a conflict
   * is detected.
   */
  Reject = 'REJECT',

  /**
   * Automatically create a new ThemeId (copy-on-write).
   */
  CreateDuplicate = 'CREATE_DUPLICATE',
}

/**
 * Options controlling repository `save` semantics.
 */
export interface SaveOptions {
  /**
   * Determines how the repository should behave when the Theme already exists.
   * Defaults to WriteConflictStrategy.Reject.
   */
  onConflict?: WriteConflictStrategy;

  /**
   * When true, the repository SHOULD persist changes immediately and flush
   * to the underlying medium.  When false, the repository MAY debounce or
   * batch writes for performance.
   */
  forceFlush?: boolean;
}

/**
 * Parameters for paginated Theme queries.
 * All fields are optional.  Implementations SHOULD apply reasonable
 * default pagination (e.g. 50 items) if both `limit` and `cursor` are undefined.
 */
export interface ThemeQuery {
  /**
   * Free-text search applied to name, description, tags, etc.
   */
  search?: string;

  /**
   * Filter Themes containing ALL of the specified tags.
   */
  tags?: string[];

  /**
   * Pagination cursor returned by a previous call.
   */
  cursor?: string;

  /**
   * Maximum number of items to return in this page.
   */
  limit?: number;
}

/**
 * Return‐type for paginated listing operations.
 */
export interface ThemePage {
  items: Theme[];
  /**
   * Opaque cursor for retrieving the next page.  Undefined when the
   * current page is the last one.
   */
  nextCursor?: string;
}

/**
 * Domain repository interface for Theme persistence.
 */
export interface IThemeRepository {
  /**
   * Retrieve a Theme aggregate by its identity.
   *
   * @param themeId – unique identifier for the Theme
   * @returns Theme when found, null otherwise.
   */
  getById(themeId: ThemeId): Promise<Theme | null>;

  /**
   * Persist or update a Theme aggregate.
   *
   * @param theme   – the Theme to be saved
   * @param options – conflict and flush behavior
   * @returns Ok(void) on success, Err(Error) when the operation fails
   *          (e.g. write permissions, conflict, corruption).
   */
  save(theme: Theme, options?: SaveOptions): Promise<Result<void>>;

  /**
   * Remove a Theme from the repository.  Implementations SHOULD execute
   * a soft-delete (tombstone) when remote synchronization or undo
   * history is enabled.
   *
   * @param themeId – identifier of the Theme to delete
   */
  delete(themeId: ThemeId): Promise<Result<void>>;

  /**
   * Determine whether a Theme exists in the repository.
   */
  exists(themeId: ThemeId): Promise<boolean>;

  /**
   * List or search Themes in a paginated manner.
   */
  list(query?: ThemeQuery): Promise<ThemePage>;

  /**
   * Returns an Observable that emits whenever the Theme with the given
   * identifier changes (local save, remote sync, etc.).  Useful for view
   * models that want real-time updates without polling.
   *
   * The Observable MUST emit the current value immediately after
   * subscription.
   *
   * @throws Error when reactive change tracking is not supported by the
   *               concrete implementation.
   */
  observe(themeId: ThemeId): Observable<Theme>;
}
```