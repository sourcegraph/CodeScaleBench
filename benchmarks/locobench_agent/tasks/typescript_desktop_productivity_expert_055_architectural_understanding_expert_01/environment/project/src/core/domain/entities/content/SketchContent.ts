```typescript
/**
 * PaletteFlow Studio – Core Domain
 * --------------------------------
 * Entity: SketchContent
 *
 * A SketchContent object represents the vector-based drawing data that lives
 * inside a “Sketch Node” on the infinite canvas.  Because we are in the core
 * domain layer, the class is completely framework-agnostic—no Electron, no
 * React, no Canvas-API.  We merely describe “what” the sketch is, not “how”
 * it’s rendered.
 *
 * Business rules encapsulated here:
 *   • A sketch is composed of strokes (lines, shapes, splines, etc.)
 *   • A stroke carries points in local-space and rendering properties
 *   • Strokes can be added, updated, removed
 *   • Mutations update an internal revision counter, aiding CRDT/OT logic
 *
 * NOTE: The implementation purposefully avoids heavy-handed immutability.
 *       Entities inside aggregates are allowed to mutate as long as the
 *       aggregate boundary is respected.  Immutability is enforced at the
 *       persistence/serialization boundary instead.
 */

import { v4 as uuidv4 } from 'uuid';

/* ------------------------------------------------------------------ */
/* Value Objects                                                      */
/* ------------------------------------------------------------------ */

/**
 * A simple 2-D cartesian point.  Immutable by design.
 */
export class Point {
  public readonly x: number;
  public readonly y: number;

  public constructor(x: number, y: number) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      throw new Error('Point coordinates must be finite numbers.');
    }
    this.x = x;
    this.y = y;
    Object.freeze(this); // Deep freeze not needed; numbers are primitives
  }
}

/**
 * All supported blend modes for a sketch stroke.  Kept minimal
 * to reduce domain surface; renderers can expand if needed.
 */
export enum BlendMode {
  Normal = 'normal',
  Multiply = 'multiply',
  Screen = 'screen',
  Overlay = 'overlay',
  Darken = 'darken',
  Lighten = 'lighten',
}

/* ------------------------------------------------------------------ */
/* Entities & Interfaces                                              */
/* ------------------------------------------------------------------ */

/**
 * Shape of an individual stroke within the sketch.
 * This qualifies as an *entity* because it carries identity (id).
 */
export interface SketchStroke {
  /** Globally unique identifier (uuid v4) */
  readonly id: string;

  /** The ordered list of points that make up this stroke (local-space) */
  readonly points: ReadonlyArray<Point>;

  /** 0xRRGGBBAA or named CSS color (renderers decide) */
  readonly color: string;

  /** Stroke width in device-independent pixels */
  readonly width: number;

  /** 0–1, where 1 is fully opaque */
  readonly opacity: number;

  /** How the stroke blends with the canvas */
  readonly blendMode: BlendMode;
}

/**
 * Serialized wire format.  We purposefully keep this shallow to decouple the
 * entity from how it’s persisted (DB, JSON file, network, etc.).
 */
export type SketchContentDTO = {
  id: string;
  revision: number;
  strokes: Array<{
    id: string;
    points: Array<{ x: number; y: number }>;
    color: string;
    width: number;
    opacity: number;
    blendMode: BlendMode;
  }>;
};

/* ------------------------------------------------------------------ */
/* Aggregate Root: SketchContent                                      */
/* ------------------------------------------------------------------ */

export class SketchContent {
  /** Entity id—stable across saves/loads */
  public readonly id: string;

  /** Monotonically increasing with each mutation; aids in OT / syncing */
  public get revision(): number {
    return this._revision;
  }

  private _revision: number = 0;

  /** Primary storage for strokes (identity -> entity) */
  private readonly strokes: Map<string, SketchStroke> = new Map();

  /* -------------------- Construction ----------------------------- */

  private constructor(id?: string) {
    this.id = id ?? uuidv4();
  }

  /**
   * Factory: creates an empty, brand-new SketchContent.
   */
  public static createEmpty(): SketchContent {
    return new SketchContent();
  }

  /**
   * Factory: rebuilds a SketchContent entity from its DTO representation.
   * Throws on malformed data—since we’re in the domain layer, failing fast
   * is acceptable and even preferable.
   */
  public static fromDTO(dto: SketchContentDTO): SketchContent {
    if (!dto || typeof dto !== 'object') {
      throw new Error('Cannot hydrate SketchContent: DTO is not an object.');
    }

    const sketch = new SketchContent(dto.id);
    sketch._revision = dto.revision;

    for (const s of dto.strokes) {
      // Defensive validations
      if (!Array.isArray(s.points) || s.points.length === 0) {
        throw new Error(`Stroke ${s.id} has no points.`);
      }
      sketch.strokes.set(s.id, {
        id: s.id,
        points: s.points.map(({ x, y }) => new Point(x, y)),
        color: s.color,
        width: s.width,
        opacity: s.opacity,
        blendMode: s.blendMode,
      });
    }

    return sketch;
  }

  /* -------------------- Query Methods ---------------------------- */

  /**
   * Returns a copy of all strokes for read-only consumption.
   */
  public getAllStrokes(): ReadonlyArray<SketchStroke> {
    return Array.from(this.strokes.values(), s => ({ ...s }));
  }

  /**
   * Returns a stroke by id, or `undefined` if NOT found.
   */
  public getStroke(id: string): SketchStroke | undefined {
    const stroke = this.strokes.get(id);
    return stroke ? { ...stroke } : undefined;
  }

  /* -------------------- Command Methods -------------------------- */

  /**
   * Adds a new stroke to the sketch.  Returns the generated id so callers can
   * keep references if desired.
   */
  public addStroke(props: Omit<SketchStroke, 'id'> & { id?: string }): string {
    const id = props.id ?? uuidv4();

    if (this.strokes.has(id)) {
      throw new Error(`Stroke with id ${id} already exists in sketch ${this.id}.`);
    }

    if (!Array.isArray(props.points) || props.points.length === 0) {
      throw new Error('A stroke must contain at least one point.');
    }

    // Freeze the points array so no one mutates the value object
    const points = Object.freeze(props.points.map(p => new Point(p.x, p.y)));

    const stroke: SketchStroke = Object.freeze({
      id,
      points,
      color: props.color,
      width: props.width,
      opacity: props.opacity,
      blendMode: props.blendMode,
    });

    this.strokes.set(id, stroke);
    this.bumpRevision();

    return id;
  }

  /**
   * Updates an existing stroke with partial data.
   * Returns `true` when the stroke was found and updated, `false` otherwise.
   */
  public updateStroke(
    id: string,
    patch: Partial<Omit<SketchStroke, 'id' | 'points'>> & { points?: ReadonlyArray<Point> }
  ): boolean {
    const current = this.strokes.get(id);
    if (!current) {
      return false;
    }

    const nextStroke: SketchStroke = Object.freeze({
      id: current.id,
      points: patch.points ? Object.freeze(patch.points.map(p => new Point(p.x, p.y))) : current.points,
      color: patch.color ?? current.color,
      width: patch.width ?? current.width,
      opacity: patch.opacity ?? current.opacity,
      blendMode: patch.blendMode ?? current.blendMode,
    });

    // Early exit if nothing changed (cheap reference equality check)
    if (current === nextStroke) {
      return true;
    }

    this.strokes.set(id, nextStroke);
    this.bumpRevision();

    return true;
  }

  /**
   * Removes a stroke, returning `true` if the stroke existed, `false` otherwise.
   */
  public removeStroke(id: string): boolean {
    const removed = this.strokes.delete(id);
    if (removed) {
      this.bumpRevision();
    }
    return removed;
  }

  /* -------------------- Persistence & Serialization -------------- */

  /**
   * Serializes the entity into a DTO.  The DTO purposefully contains raw
   * literals to make it JSON-serializable without custom replacers.
   */
  public toDTO(): SketchContentDTO {
    return {
      id: this.id,
      revision: this._revision,
      strokes: Array.from(this.strokes.values()).map(s => ({
        id: s.id,
        points: s.points.map(p => ({ x: p.x, y: p.y })), // unwrap value object
        color: s.color,
        width: s.width,
        opacity: s.opacity,
        blendMode: s.blendMode,
      })),
    };
  }

  /* -------------------- Private Helpers -------------------------- */

  /**
   * Increments the revision counter.  This is the *only* place we mutate
   * `_revision` to keep side-effects discoverable.
   */
  private bumpRevision(): void {
    this._revision++;
  }
}
```
