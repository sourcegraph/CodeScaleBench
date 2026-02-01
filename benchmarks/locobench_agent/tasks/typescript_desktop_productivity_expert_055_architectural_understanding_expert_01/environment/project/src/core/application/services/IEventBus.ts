```typescript
/**
 * PaletteFlow Studio – Event Bus Contract & Reference Implementation
 * ---------------------------------------------------------------
 * The core application layer communicates exclusively through
 * domain events.  To stay framework-agnostic, we define our own
 * minimal contract here, together with a robust in-memory
 * implementation that is good enough for unit tests and
 * low-throughput production scenarios (e.g. CLI adapters).
 *
 * NOTE:   UI adapters (Electron windows, plugin host, etc.) swap
 *         this implementation for an RxJS / IPC hybrid, but that
 *         lives in the infrastructure layer and must not be
 *         imported by core code.
 */

import { v4 as uuid } from 'uuid';

/* ------------------------------------------------------------------
 * Domain primitives
 * ------------------------------------------------------------------ */

/**
 * A domain event is an immutable fact that something business-relevant
 * happened at a specific time.  The `type` field SHOULD be a unique
 * reverse-DNS string (e.g. "studio.node.created") so that plugins can
 * safely filter/extend without name collisions.
 */
export interface DomainEvent<TPayload = unknown> {
  /** Unique, reverse-DNS event name (e.g. "studio.node.created") */
  readonly type: string;

  /** ISO timestamp of when the event occurred */
  readonly occurredAt: string;

  /** Opaque correlation ID that ties events with the same cause */
  readonly correlationId?: string;

  /** Business-specific payload */
  readonly payload: TPayload;
}

/**
 * Convenience factory for ad-hoc events without adding ceremony.
 * (Useful for tests or infrastructure adapters.)
 */
export function createEvent<TPayload = unknown>(
  type: string,
  payload: TPayload,
  correlationId?: string,
): DomainEvent<TPayload> {
  return {
    type,
    payload,
    correlationId,
    occurredAt: new Date().toISOString(),
  };
}

/* ------------------------------------------------------------------
 * Event Bus contract
 * ------------------------------------------------------------------ */

/**
 * Signature for event handlers.  Handlers MAY return a promise;
 * failures will be captured and forwarded to the bus logger.
 */
export type EventHandler<E extends DomainEvent = DomainEvent> = (
  event: E,
) => void | Promise<void>;

export interface Subscription {
  /** Opaque ID that can be used to unsubscribe programmatically */
  readonly id: string;

  /** Cancels the underlying handler */
  unsubscribe(): void;
}

/**
 * Options that influence how an event is dispatched.
 */
export interface PublishOptions {
  /**
   * If `true`, events will be delivered synchronously in the caller’s
   * call stack.  This is handy for tests but **must** be `false` in any
   * user-facing UI thread to avoid jank / re-entrance bugs.
   *
   * Defaults to `false`.
   */
  readonly sync?: boolean;
}

/**
 * Clean-Architecture friendly abstraction that decouples all layers
 * from any specific eventing library (EventEmitter, RxJS, etc.).
 */
export interface IEventBus {
  /**
   * Broadcast a single event to all interested handlers.
   */
  publish<E extends DomainEvent>(
    event: E,
    options?: PublishOptions,
  ): Promise<void>;

  /**
   * Publish multiple events atomically.  An implementation MAY ensure
   * transactional guarantees (e.g. either all or none are dispatched),
   * but the default in-memory variant does **not**.
   */
  publishAll(events: ReadonlyArray<DomainEvent>, options?: PublishOptions): Promise<void>;

  /**
   * Register a new handler for the given event type.
   *
   * eventType may be:
   *   • a concrete string
   *   • the wildcard "*" for all events
   */
  subscribe<E extends DomainEvent>(
    eventType: string,
    handler: EventHandler<E>,
  ): Subscription;

  /**
   * Convenience helper to run a handler only once.  The subscription
   * self-destructs after the first invocation.
   */
  once<E extends DomainEvent>(
    eventType: string,
    handler: EventHandler<E>,
  ): Subscription;

  /**
   * Remove a previously registered subscription.
   */
  unsubscribe(subscriptionId: string): void;

  /**
   * Removes all handlers – handy for test tear-down or hot-module reloads.
   */
  drain(): void;
}

/* ------------------------------------------------------------------
 * Reference implementation – In-Memory, Single-Process
 * ------------------------------------------------------------------ */

export class InMemoryEventBus implements IEventBus {
  private readonly handlers: Map<
    string, // eventType
    Map<string, EventHandler> // subscriptionId -> handler
  > = new Map();

  private readonly logger: Pick<Console, 'debug' | 'error'>;

  constructor(logger: Pick<Console, 'debug' | 'error'> = console) {
    this.logger = logger;
  }

  /* ---------------------------------- publish ---------------------------------- */

  async publish<E extends DomainEvent>(
    event: E,
    options: PublishOptions = {},
  ): Promise<void> {
    await this.dispatch([event], options);
  }

  async publishAll(
    events: ReadonlyArray<DomainEvent>,
    options: PublishOptions = {},
  ): Promise<void> {
    await this.dispatch(events, options);
  }

  /* -------------------------------- subscribe --------------------------------- */

  subscribe<E extends DomainEvent>(
    eventType: string,
    handler: EventHandler<E>,
  ): Subscription {
    if (!eventType) {
      throw new Error('eventType must be a non-empty string');
    }
    if (typeof handler !== 'function') {
      throw new Error('handler must be a function');
    }

    const subscriptionId = uuid();

    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Map());
    }
    this.handlers.get(eventType)!.set(subscriptionId, handler);

    return {
      id: subscriptionId,
      unsubscribe: () => this.unsubscribe(subscriptionId),
    };
  }

  once<E extends DomainEvent>(
    eventType: string,
    handler: EventHandler<E>,
  ): Subscription {
    const wrapper: EventHandler<E> = async (event: E) => {
      try {
        await handler(event);
      } finally {
        sub.unsubscribe();
      }
    };

    const sub = this.subscribe(eventType, wrapper);
    return sub;
  }

  /* ------------------------------ unsubscribe ---------------------------------- */

  unsubscribe(subscriptionId: string): void {
    for (const [, subs] of this.handlers) {
      if (subs.delete(subscriptionId)) {
        return;
      }
    }
  }

  drain(): void {
    this.handlers.clear();
  }

  /* ------------------------------------------------------------------ helpers */

  private async dispatch(
    events: ReadonlyArray<DomainEvent>,
    { sync = false }: PublishOptions,
  ) {
    const deliveries: Promise<void>[] = [];

    for (const event of events) {
      this.logger.debug('[EventBus] Dispatching', event.type, event);
      const matchedHandlers = [
        ...(this.handlers.get('*')?.values() ?? []),
        ...(this.handlers.get(event.type)?.values() ?? []),
      ];

      for (const handler of matchedHandlers) {
        const invoke = () =>
          Promise.resolve()
            .then(() => handler(event))
            .catch((err) => {
              this.logger.error(
                `[EventBus] Handler threw for event "${event.type}"`,
                err,
              );
            });

        if (sync) {
          // Execute immediately (still async to allow error capturing)
          deliveries.push(invoke());
        } else {
          // Defer so we never block the caller
          deliveries.push(queueMicrotaskPolyfill(invoke));
        }
      }
    }

    await Promise.all(deliveries);
  }
}

/**
 * queueMicrotask is not available in all Node versions that our
 * CLI adapters support.  We polyfill with setTimeout(…, 0) while
 * preserving the Promise-based contract.
 */
function queueMicrotaskPolyfill(fn: () => void): Promise<void> {
  return new Promise<void>((resolve) =>
    // eslint-disable-next-line prefer-arrow-callback
    (typeof queueMicrotask === 'function'
      ? queueMicrotask
      : (cb: () => void) => setTimeout(cb, 0))(async () => {
        try {
          await fn();
        } finally {
          resolve();
        }
      }),
  );
}
```