```typescript
/**************************************************************************************************
 * PaletteFlow Studio
 * File: core/domain/entities/content/TextContent.ts
 *
 * A domain-level entity that represents any textual payload held by a Canvas Node.  It is a
 * framework-agnostic object that encapsulates both the raw text and domain logic such as
 * validation, immutable updates, diffing, and semantic equality.  Nothing in this file should
 * import UI-specific or persistence-specific code.
 *************************************************************************************************/

import { v4 as uuid } from 'uuid';

/* -------------------------------------------------------------------------- */
/*                                Value Objects                               */
/* -------------------------------------------------------------------------- */

/**
 * Simple opaque identifier that can be shared across bounded contexts without
 * leaking the underlying implementation (currently `uuid v4`).
 */
export class ContentId {
  private readonly _value: string;

  private constructor(value: string) {
    this._value = value;
    Object.freeze(this); // immutability guarantee
  }

  public static create(id?: string): ContentId {
    if (id && !ContentId.isValid(id)) {
      throw new InvalidContentIdError(`Invalid ContentId: "${id}"`);
    }
    return new ContentId(id ?? uuid());
  }

  public static isValid(value: string): boolean {
    // Additional validation rules can be applied here if needed.
    return /^[0-9a-fA-F-]{36}$/.test(value);
  }

  public toString(): string {
    return this._value;
  }

  public equals(other: ContentId): boolean {
    return this._value === other._value;
  }
}

/**
 * Supported textual formats.  Each format can later be associated with its own
 * renderer plugin without changing core code.
 */
export enum TextContentKind {
  PlainText  = 'plain_text',
  Markdown   = 'markdown',
  RichText   = 'rich_text',
  TodoList   = 'todo_list', // e.g., `- [ ] Task`
}

/* -------------------------------------------------------------------------- */
/*                                   Errors                                   */
/* -------------------------------------------------------------------------- */

export class InvalidContentIdError extends Error                      { name = 'InvalidContentIdError'; }
export class InvalidTextPayloadError extends Error                    { name = 'InvalidTextPayloadError'; }
export class UnsupportedTextKindError extends Error                   { name = 'UnsupportedTextKindError'; }
export class ContentMergeConflictError extends Error                  { name = 'ContentMergeConflictError'; }

/* -------------------------------------------------------------------------- */
/*                             Helper / Utility API                           */
/* -------------------------------------------------------------------------- */

/** @internal Recursively freezes an object graph to enforce immutability at runtime. */
function deepFreeze<T extends object>(obj: T): Readonly<T> {
  Object.freeze(obj);
  Object.getOwnPropertyNames(obj).forEach((prop) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const value: any = (obj as any)[prop];
    if (
      !!value &&
      (typeof value === 'object' || typeof value === 'function') &&
      !Object.isFrozen(value)
    ) {
      deepFreeze(value);
    }
  });
  return obj;
}

/**
 * Very small diff result capturing lines added & removed.
 * More sophisticated diffing should live in a dedicated package, but this is
 * enough for domain-level merge/provenance decisions.
 */
export interface TextDiff {
  added   : string[];
  removed : string[];
  unchanged: string[];
}

/**
 * Naïve line-based diffing algorithm.  Optimized diffing is beyond the scope of
 * the core domain layer; we avoid external dependencies for portability.
 */
function diffLines(a: string, b: string): TextDiff {
  const aLines = a.split(/\r?\n/);
  const bLines = b.split(/\r?\n/);

  const added: string[]    = [];
  const removed: string[]  = [];
  const unchanged: string[] = [];

  const max = Math.max(aLines.length, bLines.length);

  for (let i = 0; i < max; i++) {
    const left  = aLines[i];
    const right = bLines[i];

    if (left === undefined) {
      added.push(right);
    } else if (right === undefined) {
      removed.push(left);
    } else if (left !== right) {
      removed.push(left);
      added.push(right);
    } else {
      unchanged.push(left);
    }
  }

  return { added, removed, unchanged };
}

/* -------------------------------------------------------------------------- */
/*                               Entity: TextContent                          */
/* -------------------------------------------------------------------------- */

export interface TextContentProps {
  id         : ContentId;
  kind       : TextContentKind;
  text       : string;          // ALWAYS stored as UTF-8
  createdAt  : Date;
  updatedAt  : Date;
}

export class TextContent {
  private readonly props: TextContentProps;

  /* ---------------------------------------------------------------------- */
  /*                             Creation Helpers                           */
  /* ---------------------------------------------------------------------- */

  /**
   * Factory method that performs validation & canonicalization.
   *
   * @throws InvalidTextPayloadError        if payload is not a valid UTF-8 string
   * @throws UnsupportedTextKindError       if `kind` is not whitelisted
   */
  public static create(
    text: string,
    kind: TextContentKind = TextContentKind.Markdown,
    id  : ContentId = ContentId.create(),
    createdAt: Date = new Date(),
  ): TextContent {

    TextContent.validatePayload(text);
    TextContent.assertSupportedKind(kind);

    const props: TextContentProps = {
      id,
      kind,
      text,
      createdAt,
      updatedAt: createdAt,
    };

    return new TextContent(props);
  }

  /**
   * Rehydrates a TextContent from persistence (e.g., file system or DB).
   * All validation checks still run to protect invariants.
   */
  public static restore(props: TextContentProps): TextContent {
    // Defensive copies to prevent external mutation
    const safeProps: TextContentProps = {
      ...props,
      id: ContentId.create(props.id.toString()), // ensure valid
      createdAt: new Date(props.createdAt),
      updatedAt: new Date(props.updatedAt),
      text: props.text.slice(),                  // copy string
    };

    TextContent.validatePayload(safeProps.text);
    TextContent.assertSupportedKind(safeProps.kind);

    return new TextContent(safeProps);
  }

  private constructor(props: TextContentProps) {
    this.props = deepFreeze(props);
  }

  /* ---------------------------------------------------------------------- */
  /*                               Getters                                  */
  /* ---------------------------------------------------------------------- */

  public get id(): ContentId               { return this.props.id; }
  public get kind(): TextContentKind       { return this.props.kind; }
  public get text(): string                { return this.props.text; }
  public get createdAt(): Date             { return this.props.createdAt; }
  public get updatedAt(): Date             { return this.props.updatedAt; }

  /* ---------------------------------------------------------------------- */
  /*                       Immutability-preserving updates                   */
  /* ---------------------------------------------------------------------- */

  /**
   * Returns a NEW `TextContent` with updated textual payload and timestamp.
   */
  public updateText(newText: string): TextContent {
    TextContent.validatePayload(newText);

    if (newText === this.props.text) {
      return this; // no change, preserve identity
    }

    return new TextContent({
      ...this.props,
      text: newText,
      updatedAt: new Date(),
    });
  }

  /**
   * Derives a NEW `TextContent` after changing the text kind (e.g., from
   * Markdown to RichText).  Format conversion itself is the responsibility of
   * caller (plugins, use-cases, etc.).
   */
  public changeKind(newKind: TextContentKind): TextContent {
    TextContent.assertSupportedKind(newKind);

    if (newKind === this.props.kind) {
      return this;
    }

    return new TextContent({
      ...this.props,
      kind: newKind,
      updatedAt: new Date(),
    });
  }

  /* ---------------------------------------------------------------------- */
  /*                                Equality                                */
  /* ---------------------------------------------------------------------- */

  /**
   * Semantic equality ignoring `updatedAt`.  Useful for set operations and
   * memoization in state stores.
   */
  public equals(other: TextContent): boolean {
    return (
      this.id.equals(other.id) &&
      this.kind === other.kind &&
      this.text === other.text &&
      this.createdAt.getTime() === other.createdAt.getTime()
    );
  }

  /* ---------------------------------------------------------------------- */
  /*                                Diff / Merge                            */
  /* ---------------------------------------------------------------------- */

  /**
   * Produces a line-based diff between two versions.  Caller can decide how to
   * visualize the result.
   */
  public diff(other: TextContent): TextDiff {
    if (!this.id.equals(other.id)) {
      throw new ContentMergeConflictError(
        'Cannot diff content with different IDs',
      );
    }
    return diffLines(this.text, other.text);
  }

  /**
   * Attempts to merge two divergent copies.  Right-bias strategy: if both
   * versions edited the same line differently, a conflict is raised.
   */
  public mergeWith(incoming: TextContent): TextContent {
    if (!this.id.equals(incoming.id)) {
      throw new ContentMergeConflictError(
        'Cannot merge content with different IDs',
      );
    }

    if (this.text === incoming.text) {
      // No divergence — keep the more recent updateAt
      return this.updatedAt > incoming.updatedAt ? this : incoming;
    }

    // Naïve implementation: conflict if both changed
    throw new ContentMergeConflictError(
      'Automatic merge failed due to concurrent edits. Manual resolution required.',
    );
  }

  /* ---------------------------------------------------------------------- */
  /*                           Serialization utils                          */
  /* ---------------------------------------------------------------------- */

  public toJSON(): TextContentProps {
    // Dates are serialized as ISO strings by JSON.stringify automatically
    return {
      ...this.props,
    };
  }

  public clone(): TextContent {
    return TextContent.restore(this.toJSON());
  }

  /* ---------------------------------------------------------------------- */
  /*                             Static Helpers                             */
  /* ---------------------------------------------------------------------- */

  private static validatePayload(text: string): void {
    if (typeof text !== 'string' || text.length === 0) {
      throw new InvalidTextPayloadError('Text payload cannot be empty');
    }

    // Arbitrary safeguard against runaway payloads in memory-constrained envs.
    const MAX_BYTES = 1_000_000; // 1 MB
    if (Buffer.byteLength(text, 'utf8') > MAX_BYTES) {
      throw new InvalidTextPayloadError(
        `Text payload exceeds ${MAX_BYTES} bytes`,
      );
    }
  }

  private static assertSupportedKind(kind: TextContentKind): void {
    if (!(kind in TextContentKind)) {
      throw new UnsupportedTextKindError(
        `Unsupported TextContent kind: "${kind}"`,
      );
    }
  }
}
```