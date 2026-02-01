```typescript
/***********************************************************************************************************************
 * PaletteFlow Studio – Core Domain Layer
 * File: src/core/domain/entities/content/BaseContent.ts
 *
 * Description:
 * -------------
 * The BaseContent entity represents immutable, serialisable content living inside a Canvas Node.
 * Concrete content types (Markdown, Vector shapes, VoiceNotes, etc.) extend this class to inherit
 * foundational behaviour such as identity, metadata tracking, optimistic–concurrency versioning,
 * serialisation helpers, and a simple domain-event dispatch facility.
 *
 * This file is 100 % framework-agnostic and may be shared between the main Electron process,
 * renderer processes, the CLI, and plugin sandbox environments.
 *
 * --------------------------------------------------------------------------------------------------------------------
 * © PaletteFlow Inc. 2023-present. All rights reserved.
 **********************************************************************************************************************/

// NOTE: The core layer purposefully avoids heavy runtime dependencies.
// The ‘uuid’ package would normally be used, but we rely on the built-in
// crypto implementation (available in modern browsers & Node ≥ v16) to
// eliminate external coupling.

import { randomUUID } from 'crypto';

/* -------------------------------------------------------------------------------------------------
 * Value-objects & Helper Types
 * ---------------------------------------------------------------------------------------------- */

/**
 * A unique identifier for any domain entity.
 * Implemented as an opaque string to prevent accidental mixing with raw strings.
 */
export type EntityId = string & { readonly __brand: unique symbol };

/**
 * Common metadata attached to all content types.
 */
export interface ContentMetadata {
  readonly createdAt: Date;
  readonly updatedAt: Date;
  readonly author?: string;          // e.g., userId or pluginId that created the content
  readonly version: number;          // Optimistic concurrency control
  readonly readonly?: boolean;       // Mark content as read-only (e.g., imported assets)
  readonly tags?: ReadonlyArray<string>;
}

/**
 * The minimal shape expected from all concrete Content entities when they are serialised.
 * Generic param `TData` represents the specific payload of each content type.
 */
export interface SerializedContent<TData = unknown> {
  readonly id: EntityId;
  readonly type: string;
  readonly data: TData;
  readonly metadata: ContentMetadata;
}

/**
 * Domain events emitted by Content entities.  Plugins, use-cases, or
 * application services may subscribe to these to trigger side-effects.
 */
export interface DomainEvent<TPayload = unknown> {
  readonly name: string;
  readonly occurredAt: Date;
  readonly payload: TPayload;
}

/* -------------------------------------------------------------------------------------------------
 * Helper Functions
 * ---------------------------------------------------------------------------------------------- */

/**
 * Generates a strongly-typed EntityId without leaking implementation details.
 */
function generateEntityId(): EntityId {
  // `randomUUID` is supported in Node ≥ 16.7 and modern browsers.
  // Fallback to quick implementation if unavailable (should never happen in supported targets).
  // We brand the string so TypeScript won’t mistake it for an arbitrary string.
  const uuid = typeof randomUUID === 'function'
    ? randomUUID()
    : `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;

  return uuid as EntityId;
}

/* -------------------------------------------------------------------------------------------------
 * The BaseContent Abstract Class
 * ---------------------------------------------------------------------------------------------- */

/**
 * BaseContent<TData>
 * ------------------
 * Abstract root entity for all content nodes.  Concrete subclasses *must*
 * implement the `protected validate()` method to ensure their internal data
 * is always in a valid state.
 *
 * TData – Concrete, immutable payload specific to the content type.
 */
export abstract class BaseContent<TData = unknown> {
  /* ---------------------------------------------------------------------------
   * Properties
   * ------------------------------------------------------------------------ */

  /**
   * Stable identifier across the life-time of the entity.
   */
  public readonly id: EntityId;

  /**
   * Fully qualified, unique type-id for the content.
   * Examples: “core.markdown”, “vector.shape”, “my-plugin.soundWave”
   */
  public abstract readonly type: string;

  /**
   * Mutable metadata object, versioned on every modification.
   */
  private _metadata: ContentMetadata;

  /**
   * Internal data payload (immutable outside the class boundary).
   */
  private _data: TData;

  /**
   * Queue of domain events that occurred on this aggregate root
   * since it was loaded from the repository.
   */
  private readonly _domainEvents: DomainEvent[] = [];

  /* ---------------------------------------------------------------------------
   * Ctor
   * ------------------------------------------------------------------------ */

  protected constructor(initial: {
    id?: EntityId;
    data: TData;
    metadata?: Partial<Omit<ContentMetadata, 'version' | 'createdAt' | 'updatedAt'>>;
  }) {
    this.id = initial.id ?? generateEntityId();
    this._data = Object.freeze({ ...initial.data }) as TData;

    const now = new Date();
    this._metadata = {
      createdAt: now,
      updatedAt: now,
      version: 1,
      ...initial.metadata,
    };

    // Validate upon construction to ensure invariants.
    this.validate(this._data);
  }

  /* ---------------------------------------------------------------------------
   * Public Getters
   * ------------------------------------------------------------------------ */

  /** Retrieve a (deep frozen) copy of the current content payload */
  public get data(): TData {
    // NOTE: For performance we assume that data is already
    // immutable (Object.freeze in constructor) therefore we can
    // safely return it directly.
    return this._data;
  }

  /** Clone of metadata to preserve encapsulation */
  public get metadata(): ContentMetadata {
    return { ...this._metadata };
  }

  /** Domain events generated by the entity (read-only to external callers) */
  public get domainEvents(): ReadonlyArray<DomainEvent> {
    return this._domainEvents;
  }

  /* ---------------------------------------------------------------------------
   * Behavioural Methods
   * ------------------------------------------------------------------------ */

  /**
   * Replace the entire data payload atomically.
   * Emits a ‘ContentUpdated’ domain event.
   */
  public replaceData(nextData: TData, actor?: string): void {
    // Prevent updates on read-only content
    if (this._metadata.readonly) {
      throw new Error(`Content ${this.id} is read-only and cannot be modified.`);
    }

    this.validate(nextData);

    this._data = Object.freeze({ ...nextData }) as TData;
    this.bumpVersion(actor);

    this.addDomainEvent({
      name: 'ContentUpdated',
      occurredAt: new Date(),
      payload: { contentId: this.id, actor },
    });
  }

  /**
   * Applies a partial patch to the data payload.  The default implementation
   * only works for plain object payloads.  Sub-classes may override to add
   * smarter diff-merge logic (e.g., OT for text documents).
   */
  // biome-ignore lint/suspicious/noExplicitAny: patch shape needs to be flexible
  public patchData(patch: Partial<any>, actor?: string): void {
    if (typeof this._data !== 'object' || this._data === null) {
      throw new Error(
        `patchData() is not supported for non-object payloads of content type ‘${this.type}’.`
      );
    }

    // Simple shallow merge
    const next = { ...(this._data as Record<string, unknown>), ...patch } as TData;
    this.replaceData(next, actor);
  }

  /**
   * Serialises the entity to a plain JSON-serialisable object.
   */
  public toJSON(): SerializedContent<TData> {
    return {
      id: this.id,
      type: this.type,
      data: this._data,
      metadata: this._metadata,
    };
  }

  /**
   * Clear previously captured domain events.
   * Called by the Repository after persisting and by the EventDispatcher
   * after publishing.
   */
  public clearDomainEvents(): void {
    this._domainEvents.length = 0;
  }

  /* ---------------------------------------------------------------------------
   * Internal Helpers
   * ------------------------------------------------------------------------ */

  /**
   * Concrete entities must implement their own validation logic to
   * guarantee domain invariants at all times.
   */
  protected abstract validate(data: TData): void;

  /**
   * Updates metadata book-keeping.
   */
  private bumpVersion(actor?: string): void {
    this._metadata = {
      ...this._metadata,
      updatedAt: new Date(),
      version: this._metadata.version + 1,
      author: actor ?? this._metadata.author,
    };
  }

  private addDomainEvent<TPayload = unknown>(event: DomainEvent<TPayload>): void {
    this._domainEvents.push(event);
  }
}

/* -------------------------------------------------------------------------------------------------
 * Type-guard Utilities
 * ---------------------------------------------------------------------------------------------- */

/**
 * Runtime type-guard to detect BaseContent instances regardless of their generic parameter.
 */
export function isBaseContent(value: unknown): value is BaseContent<unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    'type' in value &&
    'toJSON' in value &&
    typeof (value as BaseContent<unknown>).toJSON === 'function'
  );
}
```