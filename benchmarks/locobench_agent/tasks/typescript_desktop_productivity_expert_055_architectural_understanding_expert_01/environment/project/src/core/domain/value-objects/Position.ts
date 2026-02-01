```typescript
/**
 * PaletteFlow Studio
 * ------------------
 * Value Object: Position
 *
 * A small yet non-trivial geometry utility that represents an immutable
 * (x, y) coordinate on the infinite canvas.  It lives in the core domain
 * layer and therefore has ZERO runtime dependencies on UI/tooling
 * libraries.  All calculations are IEEE-754 double precision and guard
 * against NaN/Infinity so we don’t poison the graph with invalid numbers.
 *
 * The object offers a handful of convenience helpers that are useful in
 * many business rules, e.g. snapping to a grid, distance calculations and
 * boundary clamping.
 */

export type SerializedPosition = Readonly<{
  x: number;
  y: number;
}>;

/**
 * Domain-level error thrown whenever an invalid coordinate is supplied.
 * Being explicit about the error type allows the application layer to
 * distinguish between geometry validation issues and other faults.
 */
export class InvalidPositionError extends Error {
  public readonly x: unknown;
  public readonly y: unknown;

  public constructor(x: unknown, y: unknown) {
    super(`Invalid Position coordinates (x: ${x}, y: ${y}). Coordinates must be finite numbers.`);
    this.name = 'InvalidPositionError';
    this.x = x;
    this.y = y;
  }
}

/**
 * Immutably represents a two-dimensional point.
 */
export class Position {
  private readonly _x: number;
  private readonly _y: number;

  /* ------------------------------------------------------------------ */
  /*                Construction & Serialization Helpers                */
  /* ------------------------------------------------------------------ */

  /**
   * Domain factory.  Ensures invariants are validated before an instance
   * ever sees the light of day.
   */
  public static of(x: number, y: number): Position {
    Position.ensureIsFinite(x, y);
    return new Position(x, y);
  }

  /**
   * Reconstructs an instance from a serialized representation (e.g.
   * values loaded from disk, network or plugin message bus).
   */
  public static fromJSON(payload: SerializedPosition): Position {
    return Position.of(payload.x, payload.y);
  }

  /**
   * The constructor is intentionally private so that all creation flows
   * through the validation logic in `of`.
   */
  private constructor(x: number, y: number) {
    this._x = x;
    this._y = y;

    // Freeze to guarantee immutability at runtime—even in devtools.
    Object.freeze(this);
  }

  /* ------------------------------------------------------------------ */
  /*                               Getters                              */
  /* ------------------------------------------------------------------ */

  public get x(): number {
    return this._x;
  }

  public get y(): number {
    return this._y;
  }

  /* ------------------------------------------------------------------ */
  /*                             Operations                             */
  /* ------------------------------------------------------------------ */

  /**
   * Translate by dx, dy.  Does not mutate the current instance.
   */
  public translate(dx: number, dy: number): Position {
    return Position.of(this._x + dx, this._y + dy);
  }

  /**
   * Add another Position (vector addition).
   */
  public add(other: Position): Position {
    return Position.of(this._x + other._x, this._y + other._y);
  }

  /**
   * Subtract another Position (vector subtraction).
   */
  public subtract(other: Position): Position {
    return Position.of(this._x - other._x, this._y - other._y);
  }

  /**
   * Euclidean distance to another point.
   */
  public distanceTo(other: Position): number {
    const dx = this._x - other._x;
    const dy = this._y - other._y;
    return Math.hypot(dx, dy);
  }

  /**
   * Manhattan distance to another point—useful for keyboard nudge
   * operations and simple heuristics where diagonals aren’t important.
   */
  public manhattanDistanceTo(other: Position): number {
    return Math.abs(this._x - other._x) + Math.abs(this._y - other._y);
  }

  /**
   * Snap this position to a grid of the provided size.
   *
   * Example:
   *   (23.4, 41.2) with gridSize=10  ==>  (20, 40)
   */
  public snapToGrid(gridSize: number): Position {
    if (!Number.isFinite(gridSize) || gridSize <= 0) {
      throw new InvalidPositionError(gridSize, gridSize);
    }
    const snappedX = Math.round(this._x / gridSize) * gridSize;
    const snappedY = Math.round(this._y / gridSize) * gridSize;
    return Position.of(snappedX, snappedY);
  }

  /**
   * Returns a new Position that lies within the provided rectangular
   * bounds.  The rectangle itself is defined by its minimum and maximum
   * inclusive edges.
   *
   * Example: useful when auto-scrolling or constraining drags to viewport.
   */
  public clamp(
    xMin: number,
    yMin: number,
    xMax: number,
    yMax: number
  ): Position {
    Position.ensureIsFinite(xMin, yMin);
    Position.ensureIsFinite(xMax, yMax);

    const clampedX = Math.min(Math.max(this._x, xMin), xMax);
    const clampedY = Math.min(Math.max(this._y, yMin), yMax);

    return Position.of(clampedX, clampedY);
  }

  /**
   * Determines logical equality.  Because the value object is immutable,
   * referential equality would work in many cases, but we also want
   * semantic equality for reconstructed objects.
   */
  public equals(other: unknown): other is Position {
    return (
      other instanceof Position &&
      Object.is(this._x, other._x) &&
      Object.is(this._y, other._y)
    );
  }

  /* ------------------------------------------------------------------ */
  /*                 Serialization / Debugging Convenience              */
  /* ------------------------------------------------------------------ */

  public toJSON(): SerializedPosition {
    return { x: this._x, y: this._y };
  }

  public toString(): string {
    return `(${this._x.toFixed(2)}, ${this._y.toFixed(2)})`;
  }

  /* ------------------------------------------------------------------ */
  /*                           Helper Methods                           */
  /* ------------------------------------------------------------------ */

  private static ensureIsFinite(x: unknown, y: unknown): asserts x is number & y is number {
    if (
      typeof x !== 'number' ||
      typeof y !== 'number' ||
      !Number.isFinite(x) ||
      !Number.isFinite(y)
    ) {
      throw new InvalidPositionError(x, y);
    }
  }
}

```