```typescript
/* PaletteFlow Studio
 * core/application/repositories/IWorkspaceRepository.ts
 *
 * Author: PaletteFlow Core Team
 *
 * Repository abstraction for Workspace aggregate roots.
 * -----------------------------------------------------
 * The interface purposely leaks no I/O or framework details, making it easy to
 * provide multiple interchangeable infrastructure adapters (Indexed-DB,
 * SQLite, cloud sync service, in-memory for unit tests, etc.).
 *
 * Every method that mutates state returns `Promise<void>` instead of the saved
 * entity to prevent accidental reliance on persistence-layer side effects.
 * Query methods that can be long-lived (e.g. `observeById`) use RxJS
 * Observables so that application services and UI presenters can reactively
 * stay in sync with external mutations (multi-window editing, live
 * collaboration, plugins, …).
 */

import { Observable } from 'rxjs';

import type { Workspace } from '../../domain/entities/Workspace';
import type { WorkspaceId } from '../../domain/value-objects/WorkspaceId';

/* --------------------------------------------------------------------- */
/* --------------------- Domain-level Helper Types --------------------- */
/* --------------------------------------------------------------------- */

/**
 * Common pagination options for repository queries.
 * A value of ‑1 means “no limit”.
 */
export interface PagingOptions {
  readonly limit?: number;    // max number of items to return
  readonly offset?: number;   // starting offset
}

/**
 * Search & filtering criteria for workspace listings.
 * Can be expanded over time without breaking callers.
 */
export interface WorkspaceFilter {
  readonly ownerId?: string;
  readonly hasTag?: string;
  readonly createdAfter?: Date;
  readonly createdBefore?: Date;
  readonly updatedAfter?: Date;
  readonly updatedBefore?: Date;
  readonly fullText?: string;
}

/**
 * Point-in-time snapshot of a Workspace.  Implementations can store these as
 * full binary blobs, event-streams, JSON diffs, etc.
 */
export interface WorkspaceSnapshot {
  readonly snapshotId: string;
  readonly workspaceId: WorkspaceId;
  readonly createdAt: Date;
  readonly metadata?: SnapshotMetadata;
}

/** Optional, user-defined information recorded together with a snapshot. */
export interface SnapshotMetadata {
  readonly label?: string;          // e.g. “Pre-presentation polish”
  readonly notes?: string;
  readonly createdBy?: string;      // user id
}

/**
 * Handle returned by `beginTransaction`.  Implementations may keep locks,
 * optimistic concurrency tokens, or open DB transactions behind this handle.
 * The handle is *opaque* to callers; they should only call commit/rollback.
 */
export interface WorkspaceTransactionHandle {
  readonly workspaceId: WorkspaceId;

  /** Persists the accumulated changes. */
  commit(): Promise<void>;

  /** Reverts the workspace to its previous persisted state. */
  rollback(): Promise<void>;
}

/* --------------------------------------------------------------------- */
/* -------------------------- Error Contracts -------------------------- */
/* --------------------------------------------------------------------- */

/** Base class for all repository-level errors.*/
export abstract class WorkspaceRepositoryError extends Error {
  public readonly workspaceId?: WorkspaceId;
  protected constructor(message: string, workspaceId?: WorkspaceId) {
    super(message);
    this.workspaceId = workspaceId;
  }
}

/** Thrown when a conflicting update is detected. */
export class WorkspaceConflictError extends WorkspaceRepositoryError {
  constructor(workspaceId: WorkspaceId) {
    super(`Workspace ${workspaceId} conflict – concurrent modification detected.`, workspaceId);
  }
}

/** Thrown when the requested workspace or snapshot does not exist. */
export class WorkspaceNotFoundError extends WorkspaceRepositoryError {
  constructor(workspaceId: WorkspaceId) {
    super(`Workspace ${workspaceId} was not found.`, workspaceId);
  }
}

/** Thrown when a snapshot cannot be found. */
export class WorkspaceSnapshotNotFoundError extends WorkspaceRepositoryError {
  constructor(snapshotId: string, workspaceId: WorkspaceId) {
    super(`Snapshot ${snapshotId} for workspace ${workspaceId} was not found.`, workspaceId);
  }
}

/* --------------------------------------------------------------------- */
/* --------------------------- Main Contract --------------------------- */
/* --------------------------------------------------------------------- */

/**
 * Workspace repository façade.
 *
 * All methods are `async` because even in a local-only scenario (e.g. SQLite),
 * I/O is involved.  Embracing asynchrony from the start allows the same
 * contract to be reused for cloud or sync backends later.
 */
export interface IWorkspaceRepository {
  /**
   * Load a workspace by id.
   * @returns the workspace or `null` when it doesn’t exist.
   */
  findById(id: WorkspaceId): Promise<Workspace | null>;

  /**
   * Persist or update a workspace.
   * Implementations must honour optimistic concurrency control.  If another
   * process/window has modified the workspace since the caller last fetched
   * it, `WorkspaceConflictError` **must** be thrown.
   */
  save(workspace: Workspace): Promise<void>;

  /**
   * Permanently remove a workspace and its snapshots.
   * Idempotent: deleting a non-existing workspace should resolve without
   * throwing — unless the backend specifically wishes to signal an error,
   * in which case `WorkspaceNotFoundError` must be used.
   */
  delete(id: WorkspaceId): Promise<void>;

  /**
   * Returns a list of workspaces matching the provided filter.
   */
  list(
    filter?: WorkspaceFilter,
    paging?: PagingOptions
  ): Promise<ReadonlyArray<Workspace>>;

  /**
   * Reactive updates for a single workspace.
   * The observable must:
   *   • Emit the current state immediately on subscription.
   *   • Complete when the workspace is deleted.
   *   • Error with `WorkspaceNotFoundError` when the workspace doesn’t exist.
   */
  observeById(id: WorkspaceId): Observable<Workspace>;

  /**
   * Creates an immutable snapshot.  The snapshot should represent the entire
   * workspace in a restorable form.
   */
  createSnapshot(
    id: WorkspaceId,
    metadata?: SnapshotMetadata
  ): Promise<WorkspaceSnapshot>;

  /**
   * Restores `snapshotId` and returns the revived workspace.
   * Throws `WorkspaceSnapshotNotFoundError` if the snapshot is unknown.
   */
  restoreSnapshot(snapshotId: string): Promise<Workspace>;

  /**
   * Begin a logical transaction on a workspace.  Guarantees that until commit
   * or rollback, no other writer can mutate the workspace.
   *
   * Implementations must ensure that a rolled-back transaction does **not**
   * leak partial state.
   */
  beginTransaction(id: WorkspaceId): Promise<WorkspaceTransactionHandle>;
}

/* --------------------------------------------------------------------- */
/* ------------------------- Type-Guard Utilities ---------------------- */
/* --------------------------------------------------------------------- */

/**
 * Returns `true` if the provided error is any of the repository-specific
 * contract errors.  Helpful for application services that need to handle
 * persistence concerns differently from domain/business constraints.
 */
export function isWorkspaceRepositoryError(
  err: unknown
): err is WorkspaceRepositoryError {
  return err instanceof WorkspaceRepositoryError;
}
```