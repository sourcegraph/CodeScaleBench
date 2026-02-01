```typescript
/**
 * PaletteFlow Studio
 * core/domain/errors/DomainError.ts
 *
 * A framework-agnostic base error class used throughout the domain layer.
 * All domain-level exceptions should extend from, or be created via,
 * DomainError so that they can be serialised across IPC boundaries,
 * logged uniformly, and correctly mapped to UI notifications.
 */

 /* eslint-disable @typescript-eslint/ban-types */

//////////////////////////////
// Public Typings & Helpers //
//////////////////////////////

/**
 * A classification that helps callers decide how to react to an error
 * (e.g. show validation hints vs. fatal crash dialog).
 */
export enum DomainErrorKind {
  Validation   = 'Validation',
  NotFound     = 'NotFound',
  Conflict     = 'Conflict',
  Unauthorized = 'Unauthorized',
  System       = 'System',
  Unknown      = 'Unknown',
}

/**
 * Shape returned when DomainError instances travel across process / thread
 * boundaries (Electron ↔ worker ↔ renderer, etc.).
 */
export interface DomainErrorPayload {
  name: string;
  kind: DomainErrorKind;
  message: string;
  metadata?: Readonly<Record<string, unknown>>;
  cause?: DomainErrorPayload | { name: string; message: string };
  stack?: string;
}

/**
 * Construction options mimicking the upcoming TC39 `ErrorOptions` while
 * remaining backward-compatible with Node <18 / Electron 20.
 */
export interface DomainErrorOptions {
  cause?: Error;
  metadata?: Readonly<Record<string, unknown>>;
  /**
   * When re-hydrating an error received from a remote process we inject the
   * original stack so that debugging in the main process still makes sense.
   */
  stack?: string;
}

/////////////////////////
// Concrete Error Type //
/////////////////////////

export class DomainError extends Error {
  /** Marker used in type-guards and IPC marshalling */
  public readonly isDomainError = true;

  /** High-level category describing *what* went wrong in business terms */
  public readonly kind: DomainErrorKind;

  /** Optional arbitrary data that does not belong in the message */
  public readonly metadata?: Readonly<Record<string, unknown>>;

  /** Root cause that triggered this exception. */
  public override readonly cause?: Error;

  constructor(kind: DomainErrorKind, message: string, options?: DomainErrorOptions) {
    // Pass message + cause (ES2022) when supported, else just message.
    // Node 16 (Electron 19) ignores the second param.
    super(message, 'cause' in Error.prototype ? { cause: options?.cause } as unknown as ErrorOptions : undefined);

    // Restore prototype chain as per TypeScript's recommended pattern.
    Object.setPrototypeOf(this, new.target.prototype);

    this.kind     = kind;
    this.cause    = options?.cause;
    this.metadata = options?.metadata;

    // Use V8 stack capturing so that we get correct file/line numbers.
    if (!options?.stack && Error.captureStackTrace) {
      Error.captureStackTrace(this, this.constructor);
    } else if (options?.stack) {
      this.stack = options.stack;
    }
  }

  ////////////////////
  // Static Helpers //
  ////////////////////

  /**
   * Type-guard that checks whether an arbitrary value is a DomainError.
   */
  public static isDomainError(error: unknown): error is DomainError {
    return Boolean(error) && typeof error === 'object' && (error as DomainError).isDomainError === true;
  }

  /**
   * Converts unknown/foreign exceptions into a DomainError so that
   * upstream layers are shielded from framework-specific error types.
   */
  public static fromUnknown(error: unknown): DomainError {
    if (DomainError.isDomainError(error)) {
      return error;
    }
    if (error instanceof Error) {
      return new DomainError(DomainErrorKind.Unknown, error.message, { cause: error, stack: error.stack });
    }
    return new DomainError(DomainErrorKind.Unknown, 'An unexpected error occurred.', {
      metadata: { originalValue: error },
    });
  }

  ////////////////////////////
  // Serialization / IPCing //
  ////////////////////////////

  /**
   * Serialise the error into a plain object that can cross JSON boundaries.
   */
  public toJSON(): DomainErrorPayload {
    return {
      name:    this.name,
      kind:    this.kind,
      message: this.message,
      metadata: this.metadata,
      cause: this.cause
        ? DomainError.isDomainError(this.cause)
          ? this.cause.toJSON()
          : { name: this.cause.name, message: this.cause.message }
        : undefined,
      stack: this.stack,
    };
  }

  /**
   * De-serialise an object back into a DomainError instance.
   * Useful when receiving errors from worker threads or the plugin host.
   */
  public static hydrate(payload: DomainErrorPayload): DomainError {
    const cause = payload.cause && 'kind' in payload.cause
      ? DomainError.hydrate(payload.cause as DomainErrorPayload)
      : payload.cause
        ? new Error(payload.cause.message)
        : undefined;

    return new DomainError(payload.kind, payload.message, {
      cause,
      metadata: payload.metadata,
      stack: payload.stack,
    });
  }

  ////////////////////
  // String Helpers //
  ////////////////////

  /**
   * A terser representation used by logging sinks.
   */
  public toString(): string {
    return `[${this.kind}] ${this.message}${this.metadata ? ` | metadata: ${JSON.stringify(this.metadata)}` : ''}`;
  }
}

/////////////////////////
// Convenience Classes //
/////////////////////////

/**
 * Although optional, declaring specific subclasses helps with `instanceof`
 * checks in calling code and improves IntelliSense by pre-setting the kind.
 */

export class ValidationError extends DomainError {
  constructor(message: string, options?: Omit<DomainErrorOptions, 'stack'>) {
    super(DomainErrorKind.Validation, message, options);
    this.name = 'ValidationError';
  }
}

export class NotFoundError extends DomainError {
  constructor(message: string, options?: Omit<DomainErrorOptions, 'stack'>) {
    super(DomainErrorKind.NotFound, message, options);
    this.name = 'NotFoundError';
  }
}

export class ConflictError extends DomainError {
  constructor(message: string, options?: Omit<DomainErrorOptions, 'stack'>) {
    super(DomainErrorKind.Conflict, message, options);
    this.name = 'ConflictError';
  }
}

export class UnauthorizedError extends DomainError {
  constructor(message: string, options?: Omit<DomainErrorOptions, 'stack'>) {
    super(DomainErrorKind.Unauthorized, message, options);
    this.name = 'UnauthorizedError';
  }
}

export class SystemError extends DomainError {
  constructor(message: string, options?: Omit<DomainErrorOptions, 'stack'>) {
    super(DomainErrorKind.System, message, options);
    this.name = 'SystemError';
  }
}
```