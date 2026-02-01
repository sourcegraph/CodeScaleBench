```typescript
/**
 * PaletteFlow Studio – SemanticLinkType
 * -------------------------------------
 * Core-domain value-object that represents the *type* of semantic links that can
 * exist between two Nodes on a Canvas.
 *
 *  • Immutable, equality is based on its unique `id`.
 *  • Ships with several built-in types (Association, Dependency, …).
 *  • Plugins can register custom link types at runtime.  The registry is kept in
 *    memory only; a persistence mechanism is implemented elsewhere (out of scope).
 */

import { deepFreeze } from '../utils/deepFreeze'; // simple deepFreeze util (domain-local, no runtime dep)
import { Guard } from '../utils/Guard';           // invariant/validation helper

/**
 * DTO‐style representation used for serialization and registration.
 */
export interface SemanticLinkTypeProps {
  /** Unique, URL-safe identifier (kebab-case recommended). */
  id: string;
  /** Human-readable label shown in the UI – *internationalised elsewhere*. */
  displayName: string;
  /** Optional longer description shown in inspector/tooltips. */
  description?: string;
  /**
   * Whether the link is conceptually bidirectional (e.g. “relates-to”)
   * or directional (e.g. “depends-on”).
   */
  bidirectional?: boolean;
  /** Hex colour to be used by default when visualising the link. */
  defaultColor?: `#${string}`;
}

/**
 * Value-object representing a semantic link type.
 */
export class SemanticLinkType {
  /* ─────────────────────────────────────── Static factory & registry ─────── */

  /**
   * Memoised registry that stores all built-in *and* plugin-provided types.
   * Keyed by `id` for O(1) lookups.
   */
  private static readonly registry: Map<string, SemanticLinkType> = new Map();

  /**
   * Register a new link type (typically called by a plugin during bootstrap).
   *
   * @throws  Error – if a type with the same id already exists or the
   *         provided properties are invalid.
   */
  public static register(props: SemanticLinkTypeProps): SemanticLinkType {
    SemanticLinkType.validateProps(props);

    if (SemanticLinkType.registry.has(props.id)) {
      throw new Error(
        `SemanticLinkType.register(): A link type with id '${props.id}' is already registered.`
      );
    }

    const instance = new SemanticLinkType(props);
    SemanticLinkType.registry.set(instance.id, instance);
    return instance;
  }

  /**
   * Retrieves an already registered type by id.
   * Returns `undefined` when not found.
   */
  public static get(id: string): SemanticLinkType | undefined {
    return SemanticLinkType.registry.get(id);
  }

  /**
   * Returns all currently known link types, both built-in and custom.
   * The returned array is frozen to preserve immutability.
   */
  public static list(): readonly SemanticLinkType[] {
    return Object.freeze(Array.from(SemanticLinkType.registry.values()));
  }

  /**
   * Deserialises a DTO (e.g. loaded from persistence) into a value-object.
   * When the link type is unknown on the executing environment, it is
   * dynamically registered as *opaque* – meaning plugins may later supply the
   * full metadata.  This prevents data-loss round-trips.
   */
  public static fromJSON(dto: SemanticLinkTypeProps): SemanticLinkType {
    const existing = SemanticLinkType.get(dto.id);
    if (existing) return existing;

    // Register lazily with placeholder metadata
    return SemanticLinkType.register({
      ...dto,
      displayName: dto.displayName || dto.id,
      description: dto.description,
    });
  }

  /* ──────────────────────────────────────────── Built-ins ────────────────── */

  /** Unlabelled, undirected relationship. */
  public static readonly ASSOCIATION = SemanticLinkType.register({
    id: 'association',
    displayName: 'Association',
    description: 'General relationship without implied direction.',
    bidirectional: true,
    defaultColor: '#888888',
  });

  /** Source requires target before it can proceed. */
  public static readonly DEPENDENCY = SemanticLinkType.register({
    id: 'dependency',
    displayName: 'Depends On',
    description: 'Source cannot be considered complete without the target.',
    bidirectional: false,
    defaultColor: '#FF6F5B',
  });

  /** Lightweight reference/mention. */
  public static readonly REFERENCE = SemanticLinkType.register({
    id: 'reference',
    displayName: 'Reference',
    description: 'Source mentions or cites the target.',
    bidirectional: false,
    defaultColor: '#4C9AFF',
  });

  /** Bi-directional mirror (e.g. linked clone). */
  public static readonly TRANSCLUSION = SemanticLinkType.register({
    id: 'transclusion',
    displayName: 'Transclusion',
    description:
      'Both nodes render the same underlying content; editing either updates both.',
    bidirectional: true,
    defaultColor: '#34C759',
  });

  /** Event/trigger relationship (e.g. “on save → run tests”). */
  public static readonly TRIGGER = SemanticLinkType.register({
    id: 'trigger',
    displayName: 'Trigger',
    description: 'Source emits an event that initiates behaviour on the target.',
    bidirectional: false,
    defaultColor: '#AF52DE',
  });

  /* ────────────────────────────────────────── Instance side ─────────────── */

  public readonly id: string;
  public readonly displayName: string;
  public readonly description?: string;
  public readonly bidirectional: boolean;
  public readonly defaultColor?: `#${string}`;

  private constructor(props: SemanticLinkTypeProps) {
    // Props are validated by static factory
    this.id = props.id;
    this.displayName = props.displayName;
    this.description = props.description;
    this.bidirectional = props.bidirectional ?? false;
    this.defaultColor = props.defaultColor;

    deepFreeze(this); // immutability guarantee
  }

  /**
   * Value equality (structural): two types are equal if their id matches.
   */
  public equals(other: unknown): other is SemanticLinkType {
    return other instanceof SemanticLinkType && other.id === this.id;
  }

  /**
   * Serialises the value object to a plain JS object (DTO).
   * Used for persistence, IPC messages, etc.
   */
  public toJSON(): SemanticLinkTypeProps {
    return {
      id: this.id,
      displayName: this.displayName,
      description: this.description,
      bidirectional: this.bidirectional,
      defaultColor: this.defaultColor,
    };
  }

  public toString(): string {
    return `SemanticLinkType(${this.id})`;
  }

  /* ───────────────────────────────────────── Validation ─────────────────── */

  /** Validate provider props before instantiation/registration. */
  private static validateProps(props: SemanticLinkTypeProps): void {
    Guard.againstNullOrUndefined(props.id, 'SemanticLinkType.id');
    Guard.againstNullOrUndefined(props.displayName, 'SemanticLinkType.displayName');

    // id: lowercase, alphanumeric plus hyphens/underscores
    const idRegex = /^[a-z][a-z0-9-_]{1,63}$/;
    if (!idRegex.test(props.id)) {
      throw new Error(
        `SemanticLinkType: 'id' must match ${idRegex.toString()} – received '${props.id}'.`
      );
    }

    if (props.defaultColor) {
      const colorRegex = /^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$/;
      if (!colorRegex.test(props.defaultColor)) {
        throw new Error(
          `SemanticLinkType: 'defaultColor' must be a valid hex colour – received '${props.defaultColor}'.`
        );
      }
    }
  }
}

/* ────────────────────────────────────────── Utilities ───────────────────── */

/**
 * NOTE: These are kept in-file to make the example self-contained.
 * In the real codebase they live in `src/core/domain/utils`.
 */

// Deeply freezes an object (naïve implementation sufficient for immutables).
function deepFreeze<T>(obj: T): Readonly<T> {
  return Object.freeze(obj);
}

/**
 * Guard utility providing lightweight runtime validation helpers.
 * (Only the methods used in this file are implemented here.)
 */
namespace Guard {
  export function againstNullOrUndefined(value: unknown, label: string): asserts value {
    if (value === null || value === undefined) {
      throw new Error(`Guard: ${label} cannot be null or undefined.`);
    }
  }
}
```