```typescript
// PaletteFlow Studio
// File: src/core/domain/entities/Theme.ts

/* eslint-disable @typescript-eslint/no-explicit-any */

import { v4 as uuidv4, validate as validateUuid } from 'uuid';

/**
 * A DomainEvent base interface so that entities can
 * raise events without knowledge of the infrastructure layer.
 */
export interface DomainEvent {
  readonly name: string;
  readonly payload: unknown;
  readonly occurredAt: Date;
}

/**
 * Colors are represented as CSS-compatible strings.
 * Examples: `#FF00FF`, `rgba(0,0,0,0.5)`, `hsl(120, 100%, 50%)`.
 */
export type ColorToken = string;

/**
 * A token that describes a block of typography styles.
 * Kept intentionally minimal and framework-agnostic.
 */
export interface TypographyToken {
  fontFamily: string;
  fontSize: number; // in px
  fontWeight?: number; // 100–900
  lineHeight?: number; // unit-less multiplier
  letterSpacing?: number; // in em
}

/**
 * A spacing token that can be multiplied by 4 px (industry convention)
 * or any other unit chosen by the rendering adapter.
 */
export interface SpacingToken {
  multiplier: number; // e.g. 1 => 4 px, 2 => 8 px, etc.
}

/**
 * Core token namespaces understood by the desktop client.
 * Plugin authors can extend this shape by piggy-backing on the
 * index signature.
 */
export interface ThemeTokens {
  colors: Record<string, ColorToken>;
  typography?: Record<string, TypographyToken>;
  spacing?: Record<string, SpacingToken>;
  // eslint-disable-next-line @typescript-eslint/ban-types
  [namespace: string]: unknown; // allow arbitrary namespaces (e.g. animations, shadows, etc.)
}

/**
 * Minimal info representing an author of a theme.
 */
export interface ThemeAuthor {
  name: string;
  email?: string;
  url?: string;
}

/**
 * Native JS representation that can cross a JSON boundary.
 */
export interface SerializedTheme {
  id: string;
  name: string;
  author?: ThemeAuthor;
  version: string;
  tokens: ThemeTokens;
  createdAt: string;
  updatedAt: string;
}

/**
 * Errors that can be thrown by Theme operations.
 */
export class ThemeError extends Error {
  constructor(message: string) {
    super(`[Theme] ${message}`);
  }
}

/**
 * Domain entity that encapsulates palette and style information
 * for PaletteFlow canvases.
 *
 * NOTE: The entity is kept immutable after construction; any method
 * that alters state returns a new Theme instance.
 */
export class Theme {
  // --------------------------------------------------------------------- //
  // Static factory helpers
  // --------------------------------------------------------------------- //

  /**
   * Build a Theme from user-supplied raw data.
   * Performs validation and assigns default values where needed.
   */
  public static create(partial: Omit<Partial<SerializedTheme>, 'createdAt' | 'updatedAt'>): Theme {
    return new Theme({
      id: partial.id ?? uuidv4(),
      name: partial.name ?? 'Untitled Theme',
      author: partial.author,
      version: partial.version ?? '1.0.0',
      tokens: partial.tokens ?? { colors: {} },
      createdAt: new Date(),
      updatedAt: new Date(),
    }).assertValid();
  }

  /**
   * Rehydrates a Theme that has been serialized (e.g. loaded from disk).
   * All timestamps are converted back into Date objects.
   */
  public static fromJSON(json: SerializedTheme): Theme {
    if (!json) throw new ThemeError('Cannot hydrate Theme from undefined JSON.');
    return new Theme({
      ...json,
      createdAt: new Date(json.createdAt),
      updatedAt: new Date(json.updatedAt),
    }).assertValid();
  }

  // --------------------------------------------------------------------- //
  // Constructor & private state
  // --------------------------------------------------------------------- //

  private constructor(props: {
    id: string;
    name: string;
    author?: ThemeAuthor;
    version: string;
    tokens: ThemeTokens;
    createdAt: Date;
    updatedAt: Date;
  }) {
    this._id = props.id;
    this._name = props.name;
    this._author = props.author;
    this._version = props.version;
    this._tokens = deepFreeze(clone(props.tokens)); // immutable defensive copy
    this._createdAt = props.createdAt;
    this._updatedAt = props.updatedAt;
  }

  // Backing fields
  private readonly _id: string;
  private readonly _name: string;
  private readonly _author?: ThemeAuthor;
  private readonly _version: string;
  private readonly _tokens: ThemeTokens;
  private readonly _createdAt: Date;
  private readonly _updatedAt: Date;

  // Raised domain events (collected synchronously; to be published by the
  // use-case or unit-of-work layer).
  private readonly _events: DomainEvent[] = [];

  // --------------------------------------------------------------------- //
  // Public read-only accessors
  // --------------------------------------------------------------------- //

  get id(): string {
    return this._id;
  }
  get name(): string {
    return this._name;
  }
  get author(): ThemeAuthor | undefined {
    return this._author;
  }
  get version(): string {
    return this._version;
  }
  get tokens(): ThemeTokens {
    return this._tokens;
  }
  get createdAt(): Date {
    return this._createdAt;
  }
  get updatedAt(): Date {
    return this._updatedAt;
  }

  /**
   * Domain events raised by this entity since it was loaded/instantiated.
   * Consumers should clear this array after publishing.
   */
  get events(): readonly DomainEvent[] {
    return this._events;
  }

  // --------------------------------------------------------------------- //
  // Business logic
  // --------------------------------------------------------------------- //

  /**
   * Retrieve a color token by name.
   * Throws when it cannot be found unless `fallback` is provided.
   */
  public getColor(name: string, fallback?: ColorToken): ColorToken {
    const color = this._tokens.colors[name];
    if (!color) {
      if (fallback) return fallback;
      throw new ThemeError(`Color token "${name}" does not exist in theme "${this._name}".`);
    }
    return color;
  }

  /**
   * Retrieve a typography token by name. Returns undefined when not found.
   */
  public getTypography(name: string): TypographyToken | undefined {
    return this._tokens.typography?.[name];
  }

  /**
   * Retrieve a spacing token by name. Returns undefined when not found.
   */
  public getSpacing(name: string): SpacingToken | undefined {
    return this._tokens.spacing?.[name];
  }

  /**
   * Merge another theme into this one, with the other theme taking precedence
   * on collisions. Plugins can rely on this to layer custom tokens.
   */
  public mergeWith(other: Theme): Theme {
    const mergedTokens: ThemeTokens = {
      ...this._tokens,
      ...other._tokens,
      colors: { ...this._tokens.colors, ...other._tokens.colors },
      typography: { ...this._tokens.typography, ...other._tokens.typography },
      spacing: { ...this._tokens.spacing, ...other._tokens.spacing },
    };

    const merged = new Theme({
      id: this._id,
      name: `${this._name} + ${other._name}`,
      author: this._author,
      version: bumpPatchVersion(this._version),
      tokens: mergedTokens,
      createdAt: this._createdAt,
      updatedAt: new Date(),
    });

    merged.raiseEvent({
      name: 'ThemeMerged',
      occurredAt: new Date(),
      payload: { base: this._id, incoming: other._id, result: merged._id },
    });

    return merged.assertValid();
  }

  /**
   * Export the theme into a plain object suitable for serialization.
   */
  public toJSON(): SerializedTheme {
    return {
      id: this._id,
      name: this._name,
      author: this._author,
      version: this._version,
      tokens: clone(this._tokens),
      createdAt: this._createdAt.toISOString(),
      updatedAt: this._updatedAt.toISOString(),
    };
  }

  /**
   * Equality check based on the unique identifier.
   */
  public equals(other: Theme): boolean {
    return this._id === other._id;
  }

  // --------------------------------------------------------------------- //
  // Internal helpers
  // --------------------------------------------------------------------- //

  /**
   * Ensure the Theme’s invariants hold. Throws ThemeError otherwise.
   */
  // eslint-disable-next-line class-methods-use-this
  private validate(): void {
    // UUID validity
    if (!validateUuid(this._id)) {
      throw new ThemeError(`Invalid UUID: "${this._id}".`);
    }

    // Name constraints
    if (!this._name || typeof this._name !== 'string' || this._name.trim().length === 0) {
      throw new ThemeError('Theme name must be a non-empty string.');
    }

    // Tokens must contain at least one color
    if (!this._tokens.colors || Object.keys(this._tokens.colors).length === 0) {
      throw new ThemeError('Theme must define at least one color token.');
    }
  }

  /**
   * Calls `validate()` and returns `this` for fluent APIs.
   */
  private assertValid(): this {
    this.validate();
    return this;
  }

  /**
   * Collect a domain event.
   */
  private raiseEvent(event: DomainEvent): void {
    this._events.push(Object.freeze(event));
  }
}

// ----------------------------------------------------------------------- //
// Utility helpers (kept local to avoid extra files in this snippet)
// ----------------------------------------------------------------------- //

/**
 * Deep freeze an object in a best-effort fashion.
 * For performance reasons, only freezes plain objects & arrays.
 */
function deepFreeze<T extends object>(obj: T): T {
  Object.freeze(obj);
  Object.getOwnPropertyNames(obj).forEach((prop) => {
    const value: any = (obj as any)[prop];
    if (
      value &&
      (typeof value === 'object' || typeof value === 'function') &&
      !Object.isFrozen(value)
    ) {
      deepFreeze(value);
    }
  });
  return obj;
}

/** Cheap clone that is good enough for POJOs. */
function clone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj));
}

/**
 * Bumps the patch component of a semver string.
 * Fails gracefully if the string is not semver compliant.
 */
function bumpPatchVersion(version: string): string {
  const parts = version.split('.');
  if (parts.length !== 3) return version;
  const [major, minor, patch] = parts.map((p) => Number.parseInt(p, 10));
  if (Number.isNaN(major) || Number.isNaN(minor) || Number.isNaN(patch)) return version;
  return [major, minor, patch + 1].join('.');
}
```