```typescript
/**
 * tests/test_utils.ts
 *
 * A shared test-helper library for the PulseSphere SocialOps code-base.
 * -------------------------------------------------------------------
 * All Jest/Vitest test-suites should import from this module instead of
 * re-implementing ad-hoc mocks or helpers.  The utilities below are
 * crafted to cover a wide range of common testing scenarios inside
 * a large, event-driven, micro-service landscape:
 *
 *  1.  Synthetic telemetry & social-signal generators
 *  2.  An in-memory event-bus that mimics Kafka / NATS semantics
 *  3.  Async “eventually” expectations (handy for polling-based tests)
 *  4.  Console spies & environment isolation helpers
 *
 * The goal is to keep individual test-files lean and focused on domain
 * behaviour while centralising repetitive scaffolding concerns.
 */

import { EventEmitter } from 'events';
import { randomUUID } from 'crypto';
import { Mock, vi } from 'vitest'; // Works for Jest as well when using `jest` instead of `vi`
import ms from 'ms';

/* ------------------------------------------------------------------ */
/*                         Domain-level fixtures                       */
/* ------------------------------------------------------------------ */

export type UserInteractionType =
  | 'like'
  | 'comment'
  | 'share'
  | 'view'
  | 'reaction'
  | 'follow';

export interface TelemetryEvent {
  id: string;                // UUID v4
  timestamp: number;         // epoch ms
  service: string;           // “feed-api”, “timeline-svc”, …
  host: string;              // “ip-10-0-0-12”
  metric: string;            // “cpu_usage”, “latency_p50”
  value: number;             // numeric value
  tags: Record<string, string>;
  userInteraction?: {
    type: UserInteractionType;
    delta: number;           // how many interactions happened in this frame
  };
}

/**
 * Generate a realistic, deterministic (if seed passed) TelemetryEvent.
 */
export function createMockTelemetryEvent(
  overrides: Partial<TelemetryEvent> = {},
): TelemetryEvent {
  const defaults: TelemetryEvent = {
    id: randomUUID(),
    timestamp: Date.now(),
    service: `svc-${Math.floor(Math.random() * 10)}`,
    host: `ip-10-0-0-${Math.floor(Math.random() * 255)}`,
    metric: 'latency_p95',
    value: Number((Math.random() * 800).toFixed(2)),
    tags: {
      env: 'test',
      region: 'us-east-1',
    },
  };

  // Randomly sprinkle a social interaction unless explicitly disabled
  if (
    overrides.userInteraction === undefined &&
    Math.random() > 0.5
  ) {
    defaults.userInteraction = {
      type: pickRandom<UserInteractionType>([
        'like',
        'comment',
        'share',
        'view',
        'reaction',
        'follow',
      ]),
      delta: Math.floor(Math.random() * 200),
    };
  }

  return { ...defaults, ...overrides };
}

/* ------------------------------------------------------------------ */
/*                         Event-Bus test-double                       */
/* ------------------------------------------------------------------ */

/**
 * Lightweight in-memory pub/sub implementation that imitates the most
 * essential semantics of Kafka/NATS used throughout PulseSphere.
 *
 *  - Topics are plain strings
 *  - Messages are delivered in-order (sync inside the same tick)
 *  - Back-pressure & re-delivery are *not* simulated
 */
export class InMemoryEventBus {
  private emitter = new EventEmitter();

  public publish<T>(topic: string, payload: T): void {
    this.emitter.emit(topic, payload);
  }

  public subscribe<T>(
    topic: string,
    handler: (payload: T) => void | Promise<void>,
  ): () => void {
    this.emitter.on(topic, handler as any);

    // Return unsubscribe fn
    return () => this.emitter.off(topic, handler as any);
  }

  /**
   * For tests that need to wait until *all* listeners processed the
   * published message (when handlers are async).
   */
  public async publishAndDrain<T>(
    topic: string,
    payload: T,
  ): Promise<void> {
    const listeners = this.emitter.listeners(topic);

    const results = listeners.map(async (listener) => listener(payload));
    this.emitter.emit(topic, payload);
    // Wait until every handler has been awaited
    await Promise.allSettled(results);
  }

  public clearAll(): void {
    this.emitter.removeAllListeners();
  }
}

/* ------------------------------------------------------------------ */
/*                       Asynchronous expect helper                   */
/* ------------------------------------------------------------------ */

/**
 * Waits until the supplied expectation callback stops throwing or the
 * timeout is reached. Helpful for eventual-consistency scenarios,
 * especially with message queues or retry loops.
 *
 * Example:
 *   await expectEventually(() => {
 *     expect(storage.get('myKey')).toBeDefined();
 *   });
 */
export async function expectEventually(
  assertion: () => void | Promise<void>,
  opts: {
    timeout?: number | string;   // integer ms or “1s”, “500ms”
    interval?: number | string;  // polling interval
  } = {},
): Promise<void> {
  const timeout =
    typeof opts.timeout === 'string'
      ? ms(opts.timeout)
      : opts.timeout ?? 2_000;
  const interval =
    typeof opts.interval === 'string'
      ? ms(opts.interval)
      : opts.interval ?? 50;

  const startedAt = Date.now();
  let lastErr: unknown;

  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      await assertion();
      return; // success 🎉
    } catch (err) {
      lastErr = err;
      const elapsed = Date.now() - startedAt;
      if (elapsed >= timeout) {
        throw lastErr;
      }
      await wait(interval);
    }
  }
}

const wait = (t: number) => new Promise((res) => setTimeout(res, t));

/* ------------------------------------------------------------------ */
/*                     Console & env isolation helpers                */
/* ------------------------------------------------------------------ */

type ConsoleMethod = 'log' | 'info' | 'warn' | 'error' | 'debug';

interface ConsoleSpies {
  log: Mock;
  info: Mock;
  warn: Mock;
  error: Mock;
  debug: Mock;
}

/**
 * Silence console output for noisy tests *and* give you access to the
 * captured calls (returned mocks Reset via `restoreConsole`).
 */
export function mockConsole(): ConsoleSpies {
  const original: Record<ConsoleMethod, (...args: any[]) => void> = {
    log: console.log,
    info: console.info,
    warn: console.warn,
    error: console.error,
    debug: console.debug,
  };

  const spies = {} as ConsoleSpies;

  (Object.keys(original) as ConsoleMethod[]).forEach((method) => {
    // @ts-ignore – dynamic assignment is fine here
    spies[method] = vi.fn();
    console[method] = spies[method] as unknown as typeof console.log;
  });

  // Provide a restore hook on the spy object set
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore
  spies.restore = () => {
    (Object.keys(original) as ConsoleMethod[]).forEach((method) => {
      console[method] = original[method];
    });
  };

  return spies;
}

/**
 * Temporarily override process.env keys for the duration of the test.
 *
 * Usage:
 *   const restoreEnv = withEnv({ NODE_ENV: 'production' });
 *   // ... run code
 *   restoreEnv(); // resets previous values
 */
export function withEnv(
  envOverrides: NodeJS.ProcessEnv,
): () => void {
  const previous = { ...process.env };

  Object.entries(envOverrides).forEach(([key, val]) => {
    process.env[key] = val;
  });

  return () => {
    process.env = previous;
  };
}

/* ------------------------------------------------------------------ */
/*                             Test data pools                        */
/* ------------------------------------------------------------------ */

/** A curated list of real-world endpoints we can reuse in tests */
export const SERVICE_NAMES = [
  'user-svc',
  'feed-api',
  'search-edge',
  'notification-worker',
  'media-transcoder',
  'analytics-ingestor',
] as const;

/** Some helper pick-random functions */
export function pickRandom<T>(array: ReadonlyArray<T>): T {
  return array[Math.floor(Math.random() * array.length)];
}

export function pickRandomService(): typeof SERVICE_NAMES[number] {
  return pickRandom(SERVICE_NAMES);
}

/** Deep clone helper – useful when you want to ensure immutability */
export function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj));
}

/* ------------------------------------------------------------------ */
/* Default export – convenient aggregate                              */
/* ------------------------------------------------------------------ */

export default {
  createMockTelemetryEvent,
  InMemoryEventBus,
  expectEventually,
  mockConsole,
  withEnv,
  pickRandom,
  pickRandomService,
  deepClone,
};
```
