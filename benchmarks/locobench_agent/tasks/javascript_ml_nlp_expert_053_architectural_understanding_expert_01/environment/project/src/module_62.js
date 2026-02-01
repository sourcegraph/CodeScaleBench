```javascript
/**
 * src/module_62.js
 *
 * ToxicityMonitor
 * ---------------
 * Watches the `ml.toxicity.scores` Kafka topic for classification results,
 * aggregates them in a sliding time-window, and emits alerts whenever the
 * proportion of toxic messages breaches a configurable threshold.  The module
 * exposes an RxJS-based observable API so that product dashboards, automated
 * moderation bots, or incident-response pipelines can react in real-time.
 *
 * Patterns demonstrated:
 *  • Observer      – external callers subscribe() to alert$ observable
 *  • Pipeline      – Kafka → RxJS operators → aggregation → alert
 *  • Strategy      – AlertSink abstraction allows swapping delivery channels
 *
 * Dependencies:
 *  • kafkajs       – high-level Kafka client
 *  • rxjs          – reactive composition
 *  • prom-client   – runtime metrics
 *
 * NOTE: This file is JavaScript (ES2022) to keep the compilation pipeline
 * light-weight, but the codebase is otherwise fully-typed.  Type annotations
 * are expressed in JSDoc for IDEs / TS-check.
 */

/* eslint-disable no-console */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, timer, EMPTY } from 'rxjs';
import {
  bufferTime,
  catchError,
  filter,
  map,
  mergeMap,
  share,
} from 'rxjs/operators';
import { Counter, Gauge, collectDefaultMetrics, register } from 'prom-client';

// ───────────────────────────────────────────────────────────────────────────────
// Configuration Helpers
// ───────────────────────────────────────────────────────────────────────────────

/**
 * Reads configuration from environment variables with sane defaults and basic
 * validation.  Throws if required vars are missing.
 *
 * @returns {import('./types').ToxicityMonitorConfig}
 */
function loadConfig() {
  const required = ['KAFKA_BROKERS', 'KAFKA_TOXICITY_TOPIC'];
  const missing = required.filter((k) => !process.env[k]);
  if (missing.length) {
    throw new Error(`Missing required environment vars: ${missing.join(', ')}`);
  }

  return {
    kafkaBrokers: process.env.KAFKA_BROKERS.split(','),
    kafkaClientId: process.env.KAFKA_CLIENT_ID ?? 'agorapulse-toxicity-monitor',
    topic: process.env.KAFKA_TOXICITY_TOPIC,
    groupId: process.env.KAFKA_GROUP_ID ?? 'agorapulse-toxicity-monitor-group',
    slidingWindowMs: parseInt(process.env.SLIDING_WINDOW_MS ?? '60000', 10), // 1 min
    toxicityThreshold: parseFloat(process.env.TOXICITY_THRESHOLD ?? '0.2'), // 20%
    metrics: process.env.ENABLE_METRICS !== 'false',
  };
}

// ───────────────────────────────────────────────────────────────────────────────
// Metric Registry
// ───────────────────────────────────────────────────────────────────────────────

/**
 * Prometheus metric instances scoped to a monitor.
 * Lazy-initialized so that multiple monitors don’t overwrite each other.
 */
class MetricRegistry {
  /**
   * @param {boolean} enabled
   */
  constructor(enabled) {
    this.enabled = enabled;
    if (enabled) {
      collectDefaultMetrics({ register });
    }

    // message counters
    this.totalMsgs = new Counter({
      name: 'agp_toxicity_monitor_total_messages',
      help: 'Total number of messages processed by the toxicity monitor',
    });

    this.toxicMsgs = new Counter({
      name: 'agp_toxicity_monitor_toxic_messages',
      help: 'Total number of toxic messages detected',
    });

    // gauges
    this.toxicityRatio = new Gauge({
      name: 'agp_toxicity_monitor_toxicity_ratio',
      help: 'Toxic messages ratio in current sliding window',
    });
  }

  /**
   * Safely increment a counter.
   * @param {Counter} counter
   * @param {number} [value]
   */
  inc(counter, value = 1) {
    if (this.enabled) counter.inc(value);
  }

  /**
   * Safely set a gauge.
   * @param {Gauge} gauge
   * @param {number} value
   */
  set(gauge, value) {
    if (this.enabled) gauge.set(value);
  }
}

// ───────────────────────────────────────────────────────────────────────────────
// Alert Sink Strategy
// ───────────────────────────────────────────────────────────────────────────────

/**
 * Abstracts the actual delivery mechanism for alerts.
 * A concrete implementation must implement `send({ ratio, windowStart, windowEnd })`.
 */
class AlertSink {
  /* eslint-disable class-methods-use-this */
  /**
   * @param {import('./types').ToxicityAlert} alert
   * @returns {Promise<void>}
   */
  async send(alert) {
    throw new Error('send() must be implemented by subclass');
  }
  /* eslint-enable class-methods-use-this */
}

/**
 * Sends alerts to STDOUT – useful for local development.
 */
class ConsoleAlertSink extends AlertSink {
  async send(alert) {
    // eslint-disable-next-line no-console
    console.warn(
      `[ToxicityAlert] ratio=${alert.ratio.toFixed(2)} ` +
        `(${alert.toxicCount}/${alert.totalCount}) ` +
        `window=[${new Date(alert.windowStart).toISOString()} – ${new Date(
          alert.windowEnd
        ).toISOString()}]`
    );
  }
}

// Additional sinks – Slack, PagerDuty, etc. – can be registered here.

// ───────────────────────────────────────────────────────────────────────────────
// ToxicityMonitor – Core Implementation
// ───────────────────────────────────────────────────────────────────────────────

/**
 * @implements {import('./types').ToxicityMonitor}
 */
export class ToxicityMonitor {
  /**
   * @param {Partial<import('./types').ToxicityMonitorConfig>=} partialCfg
   * @param {AlertSink=} alertSink
   */
  constructor(partialCfg = {}, alertSink = new ConsoleAlertSink()) {
    // Merge config layers: env > ctor param > defaults
    const envCfg = loadConfig();
    /** @type {import('./types').ToxicityMonitorConfig} */
    this.cfg = { ...envCfg, ...partialCfg };
    this.alertSink = alertSink;
    this.metricRegistry = new MetricRegistry(this.cfg.metrics);

    // Kafka
    this.kafka = new Kafka({
      clientId: this.cfg.kafkaClientId,
      brokers: this.cfg.kafkaBrokers,
      logLevel: logLevel.ERROR,
    });
    this.consumer = this.kafka.consumer({ groupId: this.cfg.groupId });

    // Internal stream
    this.message$ = new Subject();

    // Public alert stream
    this.alert$ = this.message$.pipe(
      map((msg) => JSON.parse(msg.value.toString())),
      filter(
        /** @param {any} payload */ (payload) =>
          typeof payload.toxicity === 'number'
      ),
      tapPayloadMetrics(this.metricRegistry),
      bufferTime(this.cfg.slidingWindowMs),
      filter((batch) => batch.length > 0),
      map((batch) => aggregateToxicity(batch)),
      tapWindowMetrics(this.metricRegistry),
      filter(
        (stats) =>
          stats.ratio >= this.cfg.toxicityThreshold &&
          stats.toxicCount > 0 // avoid noisy zeros
      ),
      mergeMap((alert) =>
        this.alertSink
          .send(alert)
          .catch((err) =>
            /* eslint-disable no-console */
            console.error('[ToxicityMonitor] Failed to deliver alert', err)
            /* eslint-enable no-console */
          )
          .then(() => alert)
      ),
      share(), // multicast to all subscribers
      catchError((err, source) => {
        // Hot observable – log & resume
        console.error('[ToxicityMonitor] Stream error:', err);
        return source;
      })
    );

    // Handle shutdown
    process.once('SIGINT', () => void this.stop());
    process.once('SIGTERM', () => void this.stop());
  }

  /**
   * Starts Kafka consumption and score stream.
   */
  async start() {
    await this.consumer.connect();
    await this.consumer.subscribe({ topic: this.cfg.topic, fromBeginning: false });

    await this.consumer.run({
      autoCommit: true,
      eachMessage: async ({ message }) => {
        this.message$.next(message);
      },
    });

    // Periodic liveness log
    timer(0, 60_000).subscribe(() => {
      // eslint-disable-next-line no-console
      console.info(
        `[ToxicityMonitor] Alive. metrics: toxic=${this.metricRegistry.toxicMsgs.hashMap['']?.value ?? 0
        } / total=${this.metricRegistry.totalMsgs.hashMap['']?.value ?? 0}`
      );
    });
  }

  /**
   * Gracefully stops the monitor.
   */
  async stop() {
    try {
      await this.consumer.disconnect();
    } catch (err) {
      console.warn('[ToxicityMonitor] Error during shutdown', err);
    }
    process.exit(0); // eslint-disable-line no-process-exit
  }

  /**
   * External API: returns the cold observable of alerts.
   * @returns {import('rxjs').Observable<import('./types').ToxicityAlert>}
   */
  onAlert() {
    return this.alert$;
  }
}

// ───────────────────────────────────────────────────────────────────────────────
// Helper RxJS operators
// ───────────────────────────────────────────────────────────────────────────────

/**
 * @param {MetricRegistry} registry
 * @returns {import('rxjs').OperatorFunction<any, any>}
 */
function tapPayloadMetrics(registry) {
  return (src$) =>
    src$.pipe(
      map((payload) => {
        registry.inc(registry.totalMsgs);
        if (payload.toxicity >= 0.5) {
          registry.inc(registry.toxicMsgs);
        }
        return payload;
      })
    );
}

/**
 * @param {MetricRegistry} registry
 * @returns {import('rxjs').OperatorFunction<import('./types').ToxicityStats, import('./types').ToxicityStats>}
 */
function tapWindowMetrics(registry) {
  return (src$) =>
    src$.pipe(
      map((stats) => {
        registry.set(registry.toxicityRatio, stats.ratio);
        return stats;
      })
    );
}

/**
 * Aggregates toxicity stats for a batch.
 *
 * @param {Array<{toxicity:number, [k:string]:any}>} batch
 * @returns {import('./types').ToxicityStats}
 */
function aggregateToxicity(batch) {
  const totalCount = batch.length;
  const toxicCount = batch.filter((p) => p.toxicity >= 0.5).length;
  const ratio = toxicCount / totalCount;
  const now = Date.now();
  return {
    windowStart: now - batch[batch.length - 1]._ts ? batch[batch.length - 1]._ts : now, // optional timestamp from payload
    windowEnd: now,
    totalCount,
    toxicCount,
    ratio,
  };
}

// ───────────────────────────────────────────────────────────────────────────────
// JSDoc Type Declarations (keep co-located for ease of discovery)
// ───────────────────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} ToxicityStats
 * @property {number} windowStart – epoch ms
 * @property {number} windowEnd   – epoch ms
 * @property {number} totalCount  – # messages
 * @property {number} toxicCount  – # toxic messages
 * @property {number} ratio       – toxicCount / totalCount
 */

/**
 * @typedef {ToxicityStats} ToxicityAlert
 */

/**
 * @typedef {Object} ToxicityMonitorConfig
 * @property {string[]} kafkaBrokers
 * @property {string}   kafkaClientId
 * @property {string}   topic
 * @property {string}   groupId
 * @property {number}   slidingWindowMs
 * @property {number}   toxicityThreshold
 * @property {boolean}  metrics
 */

/**
 * @typedef {Object} ToxicityMonitor
 * @property {() => Promise<void>} start
 * @property {() => Promise<void>} stop
 * @property {() => import('rxjs').Observable<ToxicityAlert>} onAlert
 */

// Default export for convenience
export default ToxicityMonitor;
```
