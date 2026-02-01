```javascript
/**
 * src/utils.js
 *
 * A curated set of general-purpose utilities shared by multiple services
 * inside the AgoraPulse monorepo. These helpers are intentionally dependency-
 * light and focus on the runtime characteristics required by distributed,
 * event-driven systems (retry, backoff, timeout, etc.).
 *
 * NOTE: This file is pure-E SM (uses `import`/`export`). Ensure `"type":"module"`
 * is set in the nearest package.json or transpile appropriately.
 */

import crypto from 'crypto';
import fs from 'fs/promises';
import path from 'path';
import process from 'process';
import { setTimeout as sleep } from 'timers/promises';

import pino from 'pino';
import debugFactory from 'debug';
import JSONbig from 'json-bigint';

// ---------------------------------------------------------------------------
// Logging helpers
// ---------------------------------------------------------------------------

/**
 * Shared pino logger instance.  Each consumer can create a child logger via
 * `logger.child({ module: 'xyz' })` to append contextual metadata.
 */
export const logger = pino({
  name: 'agorapulse-utils',
  level: process.env.LOG_LEVEL || 'info',
  redact: ['password', 'apiKey', 'token'],
});

/** Lightweight, low-overhead debug logs (`DEBUG=*` env flag required). */
export const debug = debugFactory('agorapulse:*');

// ---------------------------------------------------------------------------
// Environment variable helpers
// ---------------------------------------------------------------------------

/**
 * Fetch and coercively validate an environment variable.
 *
 * @template T
 * @param {string} key                - Name of the env var.
 * @param {Object} [opts]
 * @param {boolean} [opts.required]   - Throw if the variable is empty.
 * @param {'string'|'number'|'boolean'|'json'} [opts.type] - Desired coercion.
 * @param {T} [opts.default]          - Fallback value if env var is undefined.
 * @returns {T}
 */
export function getEnv(key, opts = {}) {
  const {
    required = false,
    type = 'string',
    default: defaultValue,
  } = opts;

  let raw = process.env[key];

  if (raw == null || raw === '') {
    if (required && defaultValue === undefined) {
      throw new Error(`Missing required environment variable ${key}`);
    }
    raw = defaultValue;
  }

  if (raw == null) return raw;

  try {
    switch (type) {
      case 'number': {
        const num = Number(raw);
        if (Number.isNaN(num)) throw new Error();
        return num;
      }
      case 'boolean':
        return raw === 'true' || raw === true;
      case 'json':
        return JSONbig.parse(raw);
      case 'string':
      default:
        return String(raw);
    }
  } catch {
    throw new Error(`Unable to coerce env var "${key}" to type "${type}"`);
  }
}

// ---------------------------------------------------------------------------
// Deterministic object/hash helpers
// ---------------------------------------------------------------------------

/**
 * Create a deterministic JSON string that is stable across key order.
 * Useful for hashing objects so that logically identical objects
 * produce identical digests.
 *
 * @param {unknown} obj
 * @returns {string}
 */
export function stableStringify(obj) {
  const seen = new WeakSet();
  const replacer = (_k, value) => {
    if (typeof value === 'object' && value !== null) {
      if (seen.has(value)) return '[Circular]';
      seen.add(value);

      // Sort object keys recursively.
      if (!Array.isArray(value)) {
        return Object.keys(value)
          .sort()
          .reduce((acc, key) => {
            acc[key] = value[key];
            return acc;
          }, {});
      }
    }
    return value;
  };

  return JSONbig.stringify(obj, replacer);
}

/**
 * Return a crypto hash (hex string) of any serializable object.
 *
 * @param {unknown} obj
 * @param {string} [algo='sha256']
 * @returns {string}
 */
export function hashObject(obj, algo = 'sha256') {
  const str = stableStringify(obj);
  return crypto.createHash(algo).update(str).digest('hex');
}

// ---------------------------------------------------------------------------
// Async control flow
// ---------------------------------------------------------------------------

/**
 * Sleep/delay helper that automatically converts seconds if a non-integer
 * is provided (e.g. `sleepSec(0.2)`).
 *
 * @param {number} ms Milliseconds to wait.
 */
export const delay = (ms) => sleep(ms);

/**
 * Promise wrapper that adds a timeout race.
 *
 * @template T
 * @param {Promise<T>} promise
 * @param {number} ms                     - Timeout in milliseconds.
 * @param {string} [message='Operation timed out']
 * @returns {Promise<T>}
 */
export function withTimeout(promise, ms, message = 'Operation timed out') {
  return Promise.race([
    promise,
    sleep(ms).then(() => {
      const err = new Error(message);
      err.code = 'ETIMEDOUT';
      throw err;
    }),
  ]);
}

/**
 * Generic async retry with exponential backoff & full jitter.
 *
 * @template T
 * @param {() => Promise<T>} fn
 * @param {Object} [opts]
 * @param {number} [opts.retries=5]        - Total attempts (includes first).
 * @param {number} [opts.min=100]          - Minimum delay (ms).
 * @param {number} [opts.factor=2]         - Exponential factor.
 * @param {number} [opts.max=15_000]       - Maximum delay (ms).
 * @param {(err: any) => boolean} [opts.shouldRetry] - Decide whether to retry.
 * @param {import('pino').Logger} [opts.logger]       - Logger for warnings.
 * @returns {Promise<T>}
 */
export async function retry(fn, opts = {}) {
  const {
    retries = 5,
    min = 100,
    factor = 2,
    max = 15_000,
    shouldRetry = () => true,
    logger: log = logger,
  } = opts;

  let attempt = 0;

  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      return await fn();
    } catch (err) {
      attempt += 1;
      if (attempt >= retries || !shouldRetry(err)) {
        throw err;
      }

      const backoff = Math.min(max, Math.round(min * factor ** attempt));
      // Full jitter (AWS-style)
      const delayMs = Math.random() * backoff;

      log.warn(
        {
          err,
          attempt,
          delay: Math.round(delayMs),
        },
        'Retrying operation',
      );

      await sleep(delayMs);
    }
  }
}

/**
 * Aggregate an array of promises but short-circuit early if any reject.
 *
 * This is similar to `Promise.all` but includes an optional bail-out
 * predicate, allowing the caller to cancel remaining work ASAP.
 *
 * @template T
 * @param {Array<() => Promise<T>>} promiseFactories
 * @param {(reason: any) => boolean} [shouldBail] - Return true to bail.
 * @returns {Promise<Array<T>>}
 */
export async function waterfallAll(promiseFactories, shouldBail = () => false) {
  const results = [];

  for (const factory of promiseFactories) {
    try {
      // eslint-disable-next-line no-await-in-loop
      results.push(await factory());
    } catch (err) {
      if (shouldBail(err)) {
        throw err;
      }
      results.push(err);
    }
  }

  return results;
}

// ---------------------------------------------------------------------------
// File system helpers
// ---------------------------------------------------------------------------

/**
 * Read JSON from disk using json-bigint so we don’t lose 64-bit ints.
 *
 * @param {string} filePath
 * @returns {Promise<any>}
 */
export async function readJson(filePath) {
  const data = await fs.readFile(filePath, 'utf8');
  return JSONbig.parse(data);
}

/**
 * Write pretty-printed JSON to disk atomically (via temp + rename).
 *
 * @param {string} filePath
 * @param {any} data
 * @param {number} [indent=2]
 * @returns {Promise<void>}
 */
export async function writeJson(filePath, data, indent = 2) {
  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmpPath, `${JSONbig.stringify(data, null, indent)}\n`);
  await fs.rename(tmpPath, filePath);
}

/**
 * Resolve the absolute path of a resource relative to the caller's directory.
 *
 * @param {string} importMetaUrl - Pass `import.meta.url`
 * @param {string[]} segments    - Path segments to join.
 * @returns {string}
 */
export function resolveRelative(importMetaUrl, ...segments) {
  const dirname = path.dirname(new URL(importMetaUrl).pathname);
  return path.join(dirname, ...segments);
}

// ---------------------------------------------------------------------------
// Miscellaneous
// ---------------------------------------------------------------------------

/**
 * Memoize a pure function with a simple in-memory cache (not LRU).
 *
 * @template Args
 * @template Ret
 * @param {(args: Args) => Ret} fn
 * @returns {(args: Args) => Ret}
 */
export function memoize(fn) {
  const cache = new Map();
  return function memoized(arg) {
    if (cache.has(arg)) return cache.get(arg);
    const res = fn(arg);
    cache.set(arg, res);
    return res;
  };
}

/**
 * Clamp a number between min & max (inclusive).
 *
 * @param {number} val
 * @param {number} min
 * @param {number} max
 * @returns {number}
 */
export const clamp = (val, min, max) => Math.min(max, Math.max(min, val));
```