```typescript
/* eslint-disable @typescript-eslint/no-explicit-any */
/*
 * File: src/utils.ts
 * Project: PulseSphere SocialOps (system_monitoring)
 *
 * Purpose:
 * Centralised utility helpers that are shared across the 88 micro-services
 * powering PulseSphere.  The functions below focus on resiliency, observability
 * and configuration hygiene—core attributes for a real-time, socially-aware
 * monitoring platform.
 *
 * NOTE:  Do NOT import application-layer or domain-specific code here; keep
 *        this file dependency-free (except for very small 3rd-party libs) so
 *        it can be published as an internal NPM package and consumed by every
 *        service without causing circular-dependency hell.
 */

import crypto from 'crypto';
import { setTimeout as sleepTimer } from 'timers/promises';
import pino, { Logger, LoggerOptions } from 'pino';
import { ZodError, ZodSchema } from 'zod';

/* -------------------------------------------------------------------------- */
/*                                ⚙️  Logging                                 */
/* -------------------------------------------------------------------------- */

export interface CreateLoggerOptions extends LoggerOptions {
  /**
   * Attach an always-present correlation id to each log line.
   * Useful when logs are piped to Loki/Grafana and queried by trace id.
   */
  correlationId?: string;
}

/**
 * Returns a pre-configured Pino logger instance with sensible defaults
 * for distributed tracing, timestamping and redaction of secrets.
 *
 * Each service can create child loggers per module file to keep context.
 *
 * Example:
 *   const log = createLogger({ name: 'metrics-ingestor' });
 *   const child = log.child({ component: 'kafka-consumer' });
 */
export function createLogger(
  opts: CreateLoggerOptions = {},
): Logger {
  const {
    correlationId,
    level = process.env.LOG_LEVEL || 'info',
    ...rest
  } = opts;

  const base = {
    pid: process.pid,
    hostname: process.env.HOSTNAME,
    correlationId: correlationId ?? undefined,
  };

  return pino(
    {
      level,
      base,
      timestamp: pino.stdTimeFunctions.isoTime, // 2023-05-12T08:01:55.953Z
      redact: ['password', 'secret', '*.apiKey', '*.token'],
      ...rest,
    },
    pino.destination(1), // 1 == stdout
  );
}

/* -------------------------------------------------------------------------- */
/*                                  🛌 Sleep                                  */
/* -------------------------------------------------------------------------- */

/**
 * Sleeps for the specified range of milliseconds.
 * Supports cancellation via AbortSignal.
 *
 * @param ms           Milliseconds to wait
 * @param abortSignal  Optional AbortSignal to cancel wait
 */
export function sleep(ms: number, abortSignal?: AbortSignal): Promise<void> {
  if (ms <= 0) return Promise.resolve();

  // timers/promises#setTimeout supports AbortSignal out of the box.
  return sleepTimer(ms, undefined, { signal: abortSignal });
}

/* -------------------------------------------------------------------------- */
/*                           🔁 Exponential Backoff                           */
/* -------------------------------------------------------------------------- */

export interface RetryOptions {
  retries: number;            // Total retry attempts (excluding the initial try)
  factor?: number;            // Exponential factor (default = 2)
  minTimeout?: number;        // Initial delay in ms
  maxTimeout?: number;        // Max cap delay in ms
  jitter?: boolean;           // Add random jitter to each delay
  abortSignal?: AbortSignal;  // Allows external cancellation
  onRetry?: (
    attempt: number,
    error: unknown,
    delay: number,
  ) => void | Promise<void>;  // Hook executed before each retry sleep
}

const DEFAULT_RETRY_OPTS: Omit<RetryOptions, 'retries'> = {
  factor: 2,
  minTimeout: 250,
  maxTimeout: 15_000,
  jitter: true,
};

/**
 * Retries an async task with (optional) exponential backoff and jitter.
 *
 * @example
 *   const json = await retryWithBackoff(() => fetchJson(url), { retries: 5 });
 */
export async function retryWithBackoff<T>(
  task: () => Promise<T>,
  {
    retries,
    factor,
    minTimeout,
    maxTimeout,
    jitter,
    abortSignal,
    onRetry,
  }: RetryOptions,
): Promise<T> {
  // merge defaults
  factor = factor ?? DEFAULT_RETRY_OPTS.factor;
  minTimeout = minTimeout ?? DEFAULT_RETRY_OPTS.minTimeout;
  maxTimeout = maxTimeout ?? DEFAULT_RETRY_OPTS.maxTimeout;
  jitter = jitter ?? DEFAULT_RETRY_OPTS.jitter;

  let attempt = 0;
  let lastErr: unknown;

  // Use for-loop for more explicitness
  for (; attempt <= retries; attempt++) {
    if (abortSignal?.aborted) {
      throw new Error('Retry aborted by AbortSignal.');
    }

    try {
      return await task();
    } catch (err) {
      lastErr = err;

      if (attempt === retries) break; // Exhausted
      const exp = minTimeout! * Math.pow(factor!, attempt);
      let delay = Math.min(exp, maxTimeout!);

      // Full jitter (AWS style) => random between 0 and delay
      if (jitter) {
        delay = Math.random() * delay;
      }

      // eslint-disable-next-line no-await-in-loop
      await onRetry?.(attempt + 1, err, delay);
      // eslint-disable-next-line no-await-in-loop
      await sleep(delay, abortSignal);
    }
  }

  throw lastErr!;
}

/* -------------------------------------------------------------------------- */
/*                            🧹  Safe JSON Parsing                           */
/* -------------------------------------------------------------------------- */

/**
 * Parse JSON without throwing for malformed input.
 *
 * Returns undefined if the input is empty or unparsable.
 * Errors are logged with a small digest and truncated input so that
 * extremely large bodies do not swamp the logs.
 */
export function safeJsonParse<T = any>(
  raw: string | Buffer | null | undefined,
  log?: Logger,
): T | undefined {
  if (raw == null || raw.length === 0) {
    return undefined;
  }

  try {
    const str = raw instanceof Buffer ? raw.toString('utf-8') : raw;
    return JSON.parse(str) as T;
  } catch (err) {
    log?.warn(
      {
        err,
        sample: (raw as string).toString().slice(0, 256),
      },
      'safeJsonParse(): Malformed JSON input.',
    );
    return undefined;
  }
}

/* -------------------------------------------------------------------------- */
/*                           📄 Environment Loader                            */
/* -------------------------------------------------------------------------- */

/**
 * Loads and validates configuration from process.env (or a supplied object)
 * using a Zod schema.  Throws if validation fails so that the container
 * crashes fast and observability can alert SREs.
 *
 * @example
 *   const schema = z.object({
 *     REDIS_URL: z.string().url(),
 *     KAFKA_BROKERS: z.string(),
 *   });
 *   const cfg = loadConfig(schema); // => { REDIS_URL: 'redis://…', … }
 */
export function loadConfig<T>(
  schema: ZodSchema<T>,
  env: Record<string, unknown> = process.env,
): T {
  const parsing = schema.safeParse(env);
  if (!parsing.success) {
    // Prettify zod errors & show only first 5 issues to avoid noisy logs
    const issueSummary = parsing.error.issues
      .slice(0, 5)
      .map((i) => `${i.path.join('.')}: ${i.message}`)
      .join('; ');

    throw new ZodError(parsing.error.issues);
  }
  return parsing.data;
}

/* -------------------------------------------------------------------------- */
/*                           🗑️  Expiry-Aware Cache                           */
/* -------------------------------------------------------------------------- */

/**
 * A minimal in-memory cache with TTL semantics.
 *
 * NOT suitable for cross-process caching but works well for holding
 * ephemeral lookups such as recently seen message IDs or feature flags.
 */
export class TTLCache<K, V> {
  private readonly store = new Map<K, { value: V; expires: number }>();

  constructor(private readonly defaultTtlMs = 60_000) {}

  /**
   * Get value if not expired.
   */
  get(key: K): V | undefined {
    const entry = this.store.get(key);
    if (!entry) return undefined;

    if (Date.now() > entry.expires) {
      this.store.delete(key);
      return undefined;
    }
    return entry.value;
  }

  /**
   * Insert or update.
   */
  set(key: K, value: V, ttlMs = this.defaultTtlMs): void {
    const expires = Date.now() + ttlMs;
    this.store.set(key, { value, expires });
  }

  /**
   * Delete entry.
   */
  delete(key: K): boolean {
    return this.store.delete(key);
  }

  /**
   * Remove all expired items.  Can be called periodically via setInterval.
   */
  sweep(): void {
    const now = Date.now();
    for (const [k, { expires }] of this.store) {
      if (now > expires) this.store.delete(k);
    }
  }

  /**
   * Number of items (both expired and active).  Expired items are removed first.
   */
  size(): number {
    this.sweep();
    return this.store.size;
  }
}

/* -------------------------------------------------------------------------- */
/*                     🔗 Correlation / Trace Id Utilities                    */
/* -------------------------------------------------------------------------- */

/**
 * Returns an RFC 4122 v4 UUID in base64url form which is shorter than the
 * canonical representation yet collision-safe enough for distributed tracing.
 */
export function generateCorrelationId(): string {
  // Node 14.17+ supports crypto.randomUUID()
  const uuid = crypto.randomUUID();

  // Convert canonical UUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
  // to raw bytes, then to base64url.
  const bytes = Buffer.from(uuid.replace(/-/g, ''), 'hex');
  return bytes
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');
}

/* -------------------------------------------------------------------------- */
/*                                 🧯  Guard                                  */
/* -------------------------------------------------------------------------- */

/**
 * Asserts a condition at runtime, otherwise throws an error.
 * Reduces boilerplate for parameter validation.
 */
export function assert(
  condition: unknown,
  message = 'Assertion failed',
): asserts condition {
  if (!condition) {
    // Include caller line for easier debugging.
    const err = new Error(message);
    if (Error.captureStackTrace) {
      Error.captureStackTrace(err, assert);
    }
    throw err;
  }
}
```