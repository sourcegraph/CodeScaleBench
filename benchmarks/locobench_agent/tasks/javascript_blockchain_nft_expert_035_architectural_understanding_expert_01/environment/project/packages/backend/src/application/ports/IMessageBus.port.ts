```typescript
/* eslint-disable @typescript-eslint/no-explicit-any */
/* --------------------------------------------------------------------------
 *  StellarStage Carnival – Message Bus Port
 *  File: packages/backend/src/application/ports/IMessageBus.port.ts
 *
 *  A Clean-Architecture “port” that defines the contract for our event /
 *  message bus.  Infrastructure adapters (RabbitMQ, NATS, Redis-Streams,
 *  WalletConnect, in-proc EventEmitter, etc.) implement this interface
 *  while application services depend on it exclusively.
 *
 *  Core responsibilities:
 *  • Publish domain events & commands
 *  • Subscribe / unsubscribe with back-pressure & at-least-once guarantees
 *  • Support request-/-response (“RPC over the bus”) with correlation IDs
 *  • Provide typed envelopes with traceable metadata
 * ----------------------------------------------------------------------- */

import { z } from 'zod'; // Runtime schema validation (implementation optional)

/* -------------------------------------------------------------------------
 *  Message Envelopes
 * ---------------------------------------------------------------------- */

/**
 * ISO-8601 timestamp string (UTC).
 */
export type ISODateTimeString = string;

/**
 * A base envelope for all bus messages.  Keeps metadata outside the
 * domain payload so we can re-serialize with different codecs
 * (JSON, MsgPack, Protobuf) without touching core schemas.
 */
export interface MessageEnvelope<TPayload = unknown> {
  /** Fully-qualified message type, e.g. "show.pass.minted.v1" */
  readonly type: string;

  /** RFC 4122 v4 correlation ID for traceability across micro-services */
  readonly correlationId: string;

  /** Causation ID that triggered this message (if any) */
  readonly causationId?: string;

  /** Milliseconds since Unix epoch */
  readonly timestamp: number;

  /** Actor / wallet / service that emitted the message */
  readonly issuer: string;

  /** Business payload.  SHOULD be immutable / pure data. */
  readonly data: TPayload;

  /** Custom headers for routing, multi-tenancy, sharding, etc. */
  readonly headers?: Record<string, string | number | boolean>;
}

/**
 * Compile-time helper for message constructors:
 *
 * interface Foo { bar: string }
 * type FooMessage = MessageEnvelope<Foo>
 */
export type Message<TPayload = unknown> = MessageEnvelope<TPayload>;

/* -------------------------------------------------------------------------
 *  Validation & Serialization Contracts
 * ---------------------------------------------------------------------- */

/**
 * Contract used by adapters to validate & hydrate payloads.  We use `zod`
 * here because it’s lightweight and works in both node & browser runtimes,
 * but any runtime codec (io-ts, runtypes, superstruct) may be swapped in.
 */
export interface SerializationCodec<TPayload = any> {
  /** Human-readable ID for debugging (e.g. "json", "msgpack") */
  readonly format: string;

  /** Encode payload → Buffer / Uint8Array */
  encode(payload: TPayload): Uint8Array;

  /** Decode Buffer → payload (throws on failure) */
  decode(buffer: Uint8Array): TPayload;

  /** Optional runtime validator (zod schema, JSON-Schema, etc.) */
  readonly schema?: z.ZodTypeAny;
}

/* -------------------------------------------------------------------------
 *  Subscription Handling
 * ---------------------------------------------------------------------- */

/**
 * A token returned by `subscribe` that allows idempotent teardown
 * of the underlying bus listener.
 */
export interface Subscription {
  /** Unsubscribe from the bus.  MUST be idempotent. */
  unsubscribe(): Promise<void>;
}

/**
 * Options for a subscription — scope, parallelism, queue-group etc.
 */
export interface SubscribeOptions {
  /** Durable consumer ID so messages survive restarts */
  durableName?: string;

  /** Named queue / group for fan-out or work-queue semantics */
  queueGroup?: string;

  /** Max in-flight messages before back-pressure kicks in */
  maxInFlight?: number;

  /** Abort controller for graceful shutdown */
  signal?: AbortSignal;
}

/* -------------------------------------------------------------------------
 *  Request / Response Handling
 * ---------------------------------------------------------------------- */

export interface RequestOptions {
  /** Milliseconds before the request times out (default: 15 000) */
  timeoutMs?: number;

  /** Abort controller to cancel the request early */
  signal?: AbortSignal;
}

/* -------------------------------------------------------------------------
 *  Core Message Bus Port
 * ---------------------------------------------------------------------- */

export interface IMessageBus {
  /* ---------------------------------------------------------------------
   *  Fire-and-forget Events & Commands
   * ------------------------------------------------------------------ */

  /**
   * Publish a single message to the bus.
   *
   * Implementations MUST guarantee:
   * • At-least-once delivery
   * • Message ordering per subject / stream
   * • Configurable durability (e.g. persistent when possible)
   */
  publish<TPayload = unknown>(
    message: Message<TPayload>,
    codec?: SerializationCodec<TPayload>,
    abortSignal?: AbortSignal
  ): Promise<void>;

  /**
   * Publish multiple messages atomically.  Adapters should attempt to batch
   * them in a single transaction where supported (e.g. NATS JetStream).
   */
  publishBatch(
    messages: Message[],
    codec?: SerializationCodec,
    abortSignal?: AbortSignal
  ): Promise<void>;

  /* ---------------------------------------------------------------------
   *  Subscribe
   * ------------------------------------------------------------------ */

  /**
   * Subscribe to one or many message types.  Handler receives fully-decoded
   * envelopes + an ack callback.  Implementations MUST NOT auto-ack before
   * the handler says so; otherwise we risk message loss on crashes.
   */
  subscribe<TPayload = unknown>(
    messageTypes: string | string[],
    handler: (
      message: Message<TPayload>,
      ack: () => Promise<void>,
      nack: (err: Error, requeue?: boolean) => Promise<void>
    ) => Promise<void> | void,
    options?: SubscribeOptions
  ): Promise<Subscription>;

  /* ---------------------------------------------------------------------
   *  Request / Response
   * ------------------------------------------------------------------ */

  /**
   * Send a request message and wait for its correlated response.
   *
   * BEWARE: Use sparingly — request/response re-introduces temporal
   * coupling into an otherwise event-driven architecture.  Prefer
   * eventual consistency when possible.
   */
  request<TRequest = unknown, TResponse = unknown>(
    request: Message<TRequest>,
    expectedResponseType: string,
    options?: RequestOptions
  ): Promise<Message<TResponse>>;
}

/* -------------------------------------------------------------------------
 *  In-Memory No-Op Bus (Useful for Unit Tests)
 *  NOTE: Normally this would live in a separate `test` utility module, but
 *  we place it here for convenience as a reference implementation.
 * ---------------------------------------------------------------------- */

export class InMemoryMessageBus implements IMessageBus {
  private readonly listeners: Map<
    string,
    Set<
      (
        msg: Message,
        ack: () => Promise<void>,
        nack: (err: Error) => Promise<void>
      ) => void
    >
  > = new Map();

  async publish<TPayload>(
    message: Message<TPayload>,
    _codec?: SerializationCodec<TPayload>
  ): Promise<void> {
    await this.dispatch(message);
  }

  async publishBatch(messages: Message[]): Promise<void> {
    for (const msg of messages) {
      await this.dispatch(msg);
    }
  }

  async subscribe<TPayload>(
    messageTypes: string | string[],
    handler: (
      message: Message<TPayload>,
      ack: () => Promise<void>,
      nack: (err: Error) => Promise<void>
    ) => void,
    options?: SubscribeOptions
  ): Promise<Subscription> {
    const types = Array.isArray(messageTypes) ? messageTypes : [messageTypes];

    types.forEach((type) => {
      if (!this.listeners.has(type)) this.listeners.set(type, new Set());
      this.listeners.get(type)!.add(handler as any);
    });

    // Basic abort handling
    options?.signal?.addEventListener('abort', () => {
      void sub.unsubscribe();
    });

    const sub: Subscription = {
      unsubscribe: async () => {
        types.forEach((type) => {
          this.listeners.get(type)?.delete(handler as any);
        });
      }
    };

    return sub;
  }

  async request<TRequest, TResponse>(
    request: Message<TRequest>,
    expectedResponseType: string,
    options?: RequestOptions
  ): Promise<Message<TResponse>> {
    const controller = new AbortController();
    const signal = options?.signal ?? controller.signal;

    const timeout = setTimeout(() => controller.abort(), options?.timeoutMs ?? 15_000);

    return new Promise<Message<TResponse>>((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timeout);
        void sub.unsubscribe();
      };

      this.subscribe(
        expectedResponseType,
        (msg, ack) => {
          if (msg.correlationId === request.correlationId) {
            cleanup();
            void ack();
            resolve(msg as Message<TResponse>);
          }
        },
        { signal }
      )
        .then((s) => (sub = s))
        .catch(reject);

      let sub: Subscription;

      this.publish(request).catch((err) => {
        cleanup();
        reject(err);
      });

      signal.addEventListener('abort', () => {
        cleanup();
        reject(new Error('Request aborted or timed out'));
      });
    });
  }

  /* -------------------------------------------------------------------
   *  Internals
   * ------------------------------------------------------------------ */

  private async dispatch(message: Message): Promise<void> {
    const handlers = this.listeners.get(message.type);
    if (!handlers?.size) return;

    for (const handler of handlers) {
      try {
        await handler(
          message,
          async () => {
            /* no-op ack for in-memory implementation */
          },
          async () => {
            /* no-op nack */
          }
        );
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error('[InMemoryMessageBus] Handler error', err);
      }
    }
  }
}
```