```typescript
/* PaletteFlow Studio
 * src/core/domain/value-objects/EntityId.ts
 *
 * A strongly-typed, immutable wrapper around a UUID v4 string that is used to
 * uniquely identify any domain entity (Canvas, Node, Link, Theme, Workspace, …)
 * across the entire PaletteFlow ecosystem.  Keeping the identifier logic
 * encapsulated in a single Value Object helps us:
 *
 *  • Avoid leaking raw strings all over the domain layer
 *  • Provide centralized validation & parsing
 *  • Enable richer comparison semantics
 *  • Offer utility helpers (e.g. NIL, type-guards) in one place
 */

import { v4 as uuidV4, validate as uuidValidate, version as uuidVersion, NIL as NIL_UUID } from 'uuid';

/**
 * Under the hood we keep the UUID as an opaque branded string so that
 * TypeScript’s structural typing won’t accidentally let us mix up identifiers.
 */
type UuidString = string & { readonly __brand: unique symbol };

/**
 * EntityId represents a globally unique identifier for any Aggregate Root or
 * Entity defined inside the core domain layer.  It purposefully hides the
 * UUID implementation details and exposes a small surface area that satisfies
 * our domain requirements while remaining persistence-agnostic.
 */
export class EntityId {
  /** A constant nil/empty identifier (all zeros).  Useful for default states. */
  public static readonly NIL = new EntityId(NIL_UUID as UuidString, true);

  /** Internal raw UUID string. Never expose publicly—use .value()/toString(). */
  private readonly _value: UuidString;

  /**
   * PRIVATE constructor; consumers should go through the factory methods so we
   * can guarantee the invariants (non-empty, valid UUID v4, etc.).
   */
  private constructor(uuid: UuidString, unsafeSkipValidation = false) {
    if (!unsafeSkipValidation) {
      EntityId.assertIsValid(uuid);
    }
    this._value = uuid;
    Object.freeze(this); // Immutable at runtime
  }

  /* --------------------------------------------------------------------- *
   *  Static Factory Methods
   * --------------------------------------------------------------------- */

  /**
   * Creates a brand-new, randomly generated v4 identifier.
   */
  public static next(): EntityId {
    return new EntityId(uuidV4() as UuidString, true); // uuid library already guarantees validity
  }

  /**
   * Creates an EntityId from an existing string, e.g. when mapping from the
   * database or deserialising from IPC.  Throws an Error if the string is not
   * a valid UUID v4.
   */
  public static fromString(id: string): EntityId {
    return new EntityId(id as UuidString);
  }

  /**
   * Type-guard for safer runtime checks, especially handy in plugin land where
   * unknown input may come from un-typed JavaScript.
   */
  /* eslint-disable @typescript-eslint/explicit-module-boundary-types */
  // (We allow unknown here because this is explicitly a type-guard)
  public static isEntityId(maybe: any): maybe is EntityId {
    return maybe instanceof EntityId;
  }
  /* eslint-enable @typescript-eslint/explicit-module-boundary-types */

  /* --------------------------------------------------------------------- *
   *  Instance Methods
   * --------------------------------------------------------------------- */

  /**
   * Returns the raw UUID string (still branded).  Prefer toString() when
   * serialising outside of the domain layer.
   */
  public value(): string {
    return this._value as unknown as string;
  }

  /**
   * Comparison—two EntityIds are equal iff their underlying UUID strings match
   * exactly (case-sensitive).
   */
  public equals(other?: EntityId | null): boolean {
    if (!other) return false;
    return this._value === other._value;
  }

  /**
   * String representation—called implicitly by JSON.stringify, concatenation,
   * template strings, etc.
   */
  public toString(): string {
    return this.value();
  }

  /**
   * Custom JSON serialiser so that we don’t end up with `{ _value: ... }`.
   */
  public toJSON(): string {
    return this.toString();
  }

  /* --------------------------------------------------------------------- *
   *  Helpers & Validation
   * --------------------------------------------------------------------- */

  private static assertIsValid(uuid: string): void {
    // Fast fail for falsy/empty strings
    if (!uuid || typeof uuid !== 'string') {
      throw new InvalidEntityIdError('Identifier must be a non-empty string');
    }

    if (!uuidValidate(uuid) || uuidVersion(uuid) !== 4) {
      // Only v4 is allowed for now (NIL is a special case handled earlier)
      throw new InvalidEntityIdError(
        `Invalid UUID v4: "${uuid}".  Make sure you are passing a version-4 UUID string.`,
      );
    }
  }
}

/**
 * Domain-level error for invalid identifier creation attempts.  We keep it in
 * the core layer so that infrastructure/presentation tiers can react
 * generically to Value Object validation failures.
 */
export class InvalidEntityIdError extends Error {
  public readonly name = 'InvalidEntityIdError';

  public constructor(message: string) {
    super(message);
    // Maintains proper stack trace for where the error was thrown (V8 only).
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, InvalidEntityIdError);
    }
  }
}

/* ------------------------------------------------------------------------- *
 *  Module-level convenience exports
 * ------------------------------------------------------------------------- */

/**
 * Short alias to generate a new UUID v4 wrapped in an EntityId.  This is
 * intentionally *not* the default export; explicitness wins.
 *
 * Example:
 *   import { newId } from '@/core/domain/value-objects/EntityId';
 *   const nodeId = newId();
 */
export const newId = (): EntityId => EntityId.next();
```