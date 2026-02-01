```typescript
/***********************************************************************************************************************
 * PaletteFlow Studio — Core Domain Layer
 * File: PaletteFlow Studio/src/core/domain/entities/Workspace.ts
 *
 * Description:
 *   Domain entity that represents a single “Workspace” in PaletteFlow Studio. A workspace is the root aggregate that
 *   owns one-or-more canvases and associated metadata, allowing users to branch, remix, theme, and persist their work
 *   across editing sessions.  The class is deliberately free of framework-specific concerns so that it can be reused
 *   in any delivery mechanism (Electron, CLI, headless server tests, etc.).
 *
 * NOTE:
 *   This file lives in the domain layer and must not import UI / infrastructure code.  It may, however, reference
 *   other domain primitives (e.g. Canvas) and tiny, dependency-free utility libs such as `uuid`.
 **********************************************************************************************************************/

import { v4 as uuidv4 } from 'uuid';

/* -------------------------------------------------------------------------------------------------
 * Auxiliary Domain Primitives
 * -----------------------------------------------------------------------------------------------*/

/**
 * Simple, serializable value object that encapsulates a unique workspace identifier.
 */
export class WorkspaceId {
  private readonly _value: string;

  private constructor(value?: string) {
    this._value = value ?? uuidv4();
  }

  public static create(value?: string): WorkspaceId {
    return new WorkspaceId(value);
  }

  public equals(other: WorkspaceId): boolean {
    return this._value === other._value;
  }

  public toString(): string {
    return this._value;
  }

  public toJSON(): string {
    return this._value;
  }
}

/**
 * Very small abstract representation of a Canvas so this file can compile in isolation.
 * The full Canvas aggregate is declared elsewhere (`./Canvas.ts`), but we only need ID & name
 * for workspace-level operations here.
 */
export interface CanvasSnapshot {
  id: string;
  name: string;
}

export type CanvasId = string;

/**
 * A minimal placeholder for the Canvas aggregate to satisfy TypeScript compilation.
 * In a real build, this would be imported from the Canvas entity module.
 */
export interface Canvas {
  readonly id: CanvasId;
  readonly name: string;
  toSnapshot(): CanvasSnapshot;
}

/**
 * Domain event base contract.  Concrete events implement this interface; they will later be
 * published by an outbox or event-bus in the infrastructure layer.
 */
export interface DomainEvent {
  readonly name: string;
  readonly occurredOn: Date;
  readonly payload: Record<string, unknown>;
}

/* -------------------------------------------------------------------------------------------------
 * Workspace Aggregate Root
 * -----------------------------------------------------------------------------------------------*/

/**
 * Possible lifecycle states for a workspace.
 */
export enum WorkspaceState {
  ACTIVE = 'ACTIVE',
  ARCHIVED = 'ARCHIVED',
  DELETED = 'DELETED',
}

/**
 * Serializable interface for persisting / hydrating a workspace.
 */
export interface WorkspaceSnapshot {
  id: string;
  name: string;
  createdAt: string;     // ISO string
  updatedAt: string;     // ISO string
  state: WorkspaceState;
  metadata: Record<string, unknown>;
  canvases: CanvasSnapshot[];
  version: number;
}

/**
 * Custom domain-level error used by workspace behaviours.
 */
export class WorkspaceError extends Error {
  public readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    Object.setPrototypeOf(this, WorkspaceError.prototype);
  }
}

/**
 * Workspace aggregate root.
 */
export class Workspace {
  // --------------------------------------------------------------------- //
  // Static factory                                                         //
  // --------------------------------------------------------------------- //

  public static create(
    props: {
      name: string;
      metadata?: Record<string, unknown>;
      initialCanvases?: Canvas[];
    },
    id?: WorkspaceId,
  ): Workspace {
    if (!props.name?.trim()) {
      throw new WorkspaceError('INVALID_NAME', 'Workspace name must be a non-empty string.');
    }

    const now = new Date();

    return new Workspace({
      id: id ?? WorkspaceId.create(),
      name: props.name.trim(),
      createdAt: now,
      updatedAt: now,
      state: WorkspaceState.ACTIVE,
      metadata: props.metadata ?? {},
      canvases: new Map(
        (props.initialCanvases ?? []).map((c) => [c.id, c]),
      ),
      version: 1,
    });
  }

  public static fromSnapshot(snapshot: WorkspaceSnapshot, canvasResolver: (snap: CanvasSnapshot) => Canvas): Workspace {
    const canvases = new Map<CanvasId, Canvas>(
      snapshot.canvases.map((snap) => {
        const canvas = canvasResolver(snap);
        return [canvas.id, canvas];
      }),
    );

    return new Workspace({
      id: WorkspaceId.create(snapshot.id),
      name: snapshot.name,
      createdAt: new Date(snapshot.createdAt),
      updatedAt: new Date(snapshot.updatedAt),
      state: snapshot.state,
      metadata: snapshot.metadata,
      canvases,
      version: snapshot.version,
    });
  }

  // --------------------------------------------------------------------- //
  // Instance                                                               //
  // --------------------------------------------------------------------- //

  private _id: WorkspaceId;
  private _name: string;
  private _createdAt: Date;
  private _updatedAt: Date;
  private _state: WorkspaceState;
  private _metadata: Record<string, unknown>;
  private _canvases: Map<CanvasId, Canvas>;
  private _version: number;

  private _domainEvents: DomainEvent[] = [];

  /**
   * Private constructor enforces use of the factory above.
   */
  private constructor(props: {
    id: WorkspaceId;
    name: string;
    createdAt: Date;
    updatedAt: Date;
    state: WorkspaceState;
    metadata: Record<string, unknown>;
    canvases: Map<CanvasId, Canvas>;
    version: number;
  }) {
    this._id = props.id;
    this._name = props.name;
    this._createdAt = props.createdAt;
    this._updatedAt = props.updatedAt;
    this._state = props.state;
    this._metadata = { ...props.metadata };
    this._canvases = props.canvases;
    this._version = props.version;
  }

  /* ------------------------------------------------------------------
   * Domain getters
   * --------------------------------------------------------------- */

  public get id(): WorkspaceId {
    return this._id;
  }

  public get name(): string {
    return this._name;
  }

  public get createdAt(): Date {
    return this._createdAt;
  }

  public get updatedAt(): Date {
    return this._updatedAt;
  }

  public get state(): WorkspaceState {
    return this._state;
  }

  public get metadata(): Readonly<Record<string, unknown>> {
    return { ...this._metadata };
  }

  public get version(): number {
    return this._version;
  }

  public get canvases(): ReadonlyArray<Canvas> {
    return Array.from(this._canvases.values());
  }

  /* ------------------------------------------------------------------
   * Behaviour
   * --------------------------------------------------------------- */

  /**
   * Rename the workspace.
   */
  public rename(newName: string): void {
    const clean = newName.trim();
    if (!clean) {
      throw new WorkspaceError('INVALID_NAME', 'Workspace name must be a non-empty string.');
    }
    if (clean === this._name) return;

    this._name = clean;
    this.touch();
    this.addDomainEvent({
      name: 'WorkspaceRenamed',
      occurredOn: new Date(),
      payload: { workspaceId: this._id.toString(), newName: clean },
    });
  }

  /**
   * Archive the workspace (soft hide from primary UI).
   */
  public archive(): void {
    if (this._state === WorkspaceState.DELETED) {
      throw new WorkspaceError('INVALID_STATE', 'Cannot archive a deleted workspace.');
    }
    if (this._state === WorkspaceState.ARCHIVED) return;

    this._state = WorkspaceState.ARCHIVED;
    this.touch();
    this.addDomainEvent({
      name: 'WorkspaceArchived',
      occurredOn: new Date(),
      payload: { workspaceId: this._id.toString() },
    });
  }

  /**
   * Restore an archived workspace back to active.
   */
  public restore(): void {
    if (this._state !== WorkspaceState.ARCHIVED) {
      throw new WorkspaceError('INVALID_STATE', 'Only archived workspaces can be restored.');
    }
    this._state = WorkspaceState.ACTIVE;
    this.touch();
    this.addDomainEvent({
      name: 'WorkspaceRestored',
      occurredOn: new Date(),
      payload: { workspaceId: this._id.toString() },
    });
  }

  /**
   * Mark workspace as deleted.  It is up to the application layer to decide whether
   * “deleted” means immediate purge or a soft-delete kept in the database.
   */
  public delete(): void {
    if (this._state === WorkspaceState.DELETED) return;

    this._state = WorkspaceState.DELETED;
    this.touch();
    this.addDomainEvent({
      name: 'WorkspaceDeleted',
      occurredOn: new Date(),
      payload: { workspaceId: this._id.toString() },
    });
  }

  /**
   * Add a canvas to this workspace.
   */
  public addCanvas(canvas: Canvas): void {
    if (this._state === WorkspaceState.DELETED) {
      throw new WorkspaceError('INVALID_STATE', 'Cannot modify a deleted workspace.');
    }
    if (this._canvases.has(canvas.id)) {
      throw new WorkspaceError(
        'DUPLICATE_CANVAS',
        `A canvas with id ${canvas.id} already exists in this workspace.`,
      );
    }

    this._canvases.set(canvas.id, canvas);
    this.touch();
    this.addDomainEvent({
      name: 'CanvasAddedToWorkspace',
      occurredOn: new Date(),
      payload: { workspaceId: this._id.toString(), canvasId: canvas.id },
    });
  }

  /**
   * Remove a canvas from the workspace.
   */
  public removeCanvas(canvasId: CanvasId): void {
    if (!this._canvases.has(canvasId)) {
      throw new WorkspaceError('CANVAS_NOT_FOUND', `Canvas ${canvasId} does not exist in this workspace.`);
    }
    this._canvases.delete(canvasId);
    this.touch();
    this.addDomainEvent({
      name: 'CanvasRemovedFromWorkspace',
      occurredOn: new Date(),
      payload: { workspaceId: this._id.toString(), canvasId },
    });
  }

  /**
   * Update or merge arbitrary metadata attached to the workspace.
   */
  public updateMetadata(patch: Record<string, unknown>): void {
    this._metadata = { ...this._metadata, ...patch };
    this.touch();
    this.addDomainEvent({
      name: 'WorkspaceMetadataUpdated',
      occurredOn: new Date(),
      payload: { workspaceId: this._id.toString(), patch },
    });
  }

  /* ------------------------------------------------------------------
   * Persistence helpers
   * --------------------------------------------------------------- */

  /**
   * Convert the aggregate to a serializable snapshot for JSON persistence.
   */
  public toSnapshot(): WorkspaceSnapshot {
    return {
      id: this._id.toString(),
      name: this._name,
      createdAt: this._createdAt.toISOString(),
      updatedAt: this._updatedAt.toISOString(),
      state: this._state,
      metadata: { ...this._metadata },
      canvases: this.canvases.map((c) => c.toSnapshot()),
      version: this._version,
    };
  }

  /**
   * Increment version & timestamp for safe optimistic concurrency control.
   */
  private touch(): void {
    this._updatedAt = new Date();
    this._version += 1;
  }

  /* ------------------------------------------------------------------
   * Domain-event handling (simple in-memory collection)
   * --------------------------------------------------------------- */

  private addDomainEvent(event: DomainEvent): void {
    this._domainEvents.push(event);
  }

  /**
   * Expose and clear domain events.  The Infrastructure outbox pattern will persist
   * and publish them after a successful transaction commit.
   */
  public pullDomainEvents(): DomainEvent[] {
    const events = [...this._domainEvents];
    this._domainEvents.length = 0;
    return events;
  }
}
```
