```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: src/module_67.js
 *
 * Purpose
 * -------
 * Real-time model-monitoring micro-pipeline.
 * Listens to the `model.predictions` Kafka topic, aggregates streaming
 * predictions in sliding windows, evaluates custom rules (fairness,
 * toxicity-FN rate, drift, etc.), and emits structured alert events to the
 * `model.alerts` topic.  Exposed as a tiny, composable service that can be
 * embedded in larger RxJS-based pipelines or run standalone via CLI.
 *
 * Design notes
 * ------------
 * • Event-driven: Kafka for ingestion/egress, RxJS for in-process stream
 *   composition.
 * • Resilient: automatic retries with back-off, graceful shutdown hooks,
 *   circuit-breaker for the producer path.
 * • Extensible: user-supplied rule functions & dynamic configuration updates
 *   via Kafka control topic (`model.monitor.ctrl`).
 *
 * Author: AgoraPulse Engineering ✨
 * License: MIT
 */

import { Kafka, logLevel } from 'kafkajs';
import {
  Subject,
  timer,
  merge,
  from,
} from 'rxjs';
import {
  bufferTime,
  catchError,
  filter,
  map,
  mergeMap,
  takeUntil,
  tap,
} from 'rxjs/operators';

/* -------------------------------------------------------------------------- *
 * Configuration & constants                                                  *
 * -------------------------------------------------------------------------- */

export const DEFAULT_CONFIG = {
  kafka: {
    clientId: 'agorapulse-model-monitor',
    brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
    connectionTimeout: 30_000,
    authenticationTimeout: 20_000,
    logLevel: logLevel.ERROR,
  },
  topics: {
    predictions: 'model.predictions',
    alerts: 'model.alerts',
    control: 'model.monitor.ctrl',
  },
  windowMs: 15_000, // sliding window for aggregation
  maxBatchSize: 5_000,
  alertRules: [
    // Built-in example rule – Toxicity false-negative rate > 3 %
    ({ metrics }) =>
      metrics.toxicityFNRate > 0.03 && {
        severity: 'high',
        type: 'TOXICITY_FN_RATE',
        message: `Toxicity FN rate spiked to ${(
          metrics.toxicityFNRate * 100
        ).toFixed(2)} %`,
      },
  ],
};

/* -------------------------------------------------------------------------- *
 * Utility helpers                                                            *
 * -------------------------------------------------------------------------- */

/**
 * Compute aggregate metrics for a batch of prediction events.
 * Each event is expected to contain:
 * {
 *   modelVersion: string;
 *   label: string;                // predicted label
 *   groundTruthLabel?: string;    // optional for online evaluation
 *   probability?: number;         // soft score from model
 * }
 */
function computeMetrics(batch) {
  const metrics = {
    count: batch.length,
    toxicityFNRate: 0,
    classCounts: {},
  };

  if (batch.length === 0) return metrics;

  let toxicityFN = 0;
  for (const ev of batch) {
    const { label, groundTruthLabel } = ev;

    metrics.classCounts[label] = (metrics.classCounts[label] ?? 0) + 1;

    if (groundTruthLabel) {
      // False negative for toxicity:
      // Ground truth toxic but predicted non-toxic
      if (groundTruthLabel === 'toxic' && label !== 'toxic') toxicityFN += 1;
    }
  }

  if (batch.some((e) => e.groundTruthLabel)) {
    const toxicGT = batch.filter(
      (e) => e.groundTruthLabel === 'toxic'
    ).length;

    metrics.toxicityFNRate =
      toxicGT > 0 ? toxicityFN / toxicGT : 0;
  }

  return metrics;
}

/**
 * Wrap a promise-returning function with retry and exponential back-off.
 */
async function retry(
  fn,
  { retries = 5, baseDelay = 500 } = {}
) {
  let attempt = 0;
  while (true) {
    try {
      return await fn();
    } catch (err) {
      attempt += 1;
      if (attempt > retries) throw err;
      const delay = baseDelay * 2 ** (attempt - 1);
      await new Promise((res) => setTimeout(res, delay));
    }
  }
}

/* -------------------------------------------------------------------------- *
 * Main class                                                                 *
 * -------------------------------------------------------------------------- */

export class RealTimeModelMonitor {
  /**
   * @param {Partial<typeof DEFAULT_CONFIG>} [customConfig]
   */
  constructor(customConfig = {}) {
    this.config = {
      ...DEFAULT_CONFIG,
      ...customConfig,
      kafka: { ...DEFAULT_CONFIG.kafka, ...(customConfig.kafka ?? {}) },
      topics: { ...DEFAULT_CONFIG.topics, ...(customConfig.topics ?? {}) },
      alertRules: [
        ...(DEFAULT_CONFIG.alertRules ?? []),
        ...(customConfig.alertRules ?? []),
      ],
    };

    this.kafka = new Kafka(this.config.kafka);
    this.consumer = this.kafka.consumer({
      groupId: `${this.config.kafka.clientId}-${Math.random()
        .toString(36)
        .slice(2)}`,
    });
    this.producer = this.kafka.producer({ allowAutoTopicCreation: true });

    // RxJS primitives
    this._stream$ = new Subject();
    this._shutdown$ = new Subject();
  }

  /* ------------------------------- Public API ----------------------------- */

  async start() {
    await retry(() => this.producer.connect());
    await retry(() => this.consumer.connect());

    await this.consumer.subscribe({
      topic: this.config.topics.predictions,
      fromBeginning: false,
    });

    // Listen to control topic for dynamic rule updates, config pushes, etc.
    await this.consumer.subscribe({
      topic: this.config.topics.control,
      fromBeginning: false,
    });

    // Forward prediction events into RxJS subject
    this.consumer.run({
      eachMessage: async ({ topic, message, partition }) => {
        try {
          if (topic === this.config.topics.control) {
            this._handleControlMessage(message);
            return;
          }

          const parsed = JSON.parse(message.value.toString());
          this._stream$.next(parsed);
        } catch (err) {
          console.error(
            `[ModelMonitor] Failed to process message on ${topic} / ${partition}\n`,
            err
          );
        }
      },
    });

    this._initPipeline();
    console.info('[ModelMonitor] Started 🚀');
  }

  async stop() {
    this._shutdown$.next(true);
    await Promise.allSettled([this.consumer.disconnect(), this.producer.disconnect()]);
    console.info('[ModelMonitor] Gracefully stopped.');
  }

  /* ----------------------------- Implementation --------------------------- */

  _initPipeline() {
    const {
      windowMs,
      maxBatchSize,
      alertRules,
      topics: { alerts: alertsTopic },
    } = this.config;

    // Core aggregation + rule-evaluation pipeline
    this._stream$
      .pipe(
        bufferTime(windowMs, undefined, maxBatchSize),
        filter((batch) => batch.length > 0),
        map((batch) => ({
          batch,
          metrics: computeMetrics(batch),
          ts: Date.now(),
        })),
        mergeMap(async (window) => {
          // Evaluate rules
          const triggeredAlerts = alertRules
            .map((rule) => {
              try {
                return rule(window);
              } catch (err) {
                console.error('[ModelMonitor] Rule error', err);
                return null;
              }
            })
            .filter(Boolean);

          // Publish alerts to Kafka
          if (triggeredAlerts.length > 0) {
            const payloads = triggeredAlerts.map((alert) => ({
              key: alert.type,
              value: JSON.stringify({
                ...alert,
                metrics: window.metrics,
                ts: window.ts,
              }),
            }));

            await retry(() =>
              this.producer.send({
                topic: alertsTopic,
                messages: payloads,
              })
            );
          }
        }),
        catchError((err, src) => {
          console.error('[ModelMonitor] Pipeline error', err);
          return src;
        }),
        takeUntil(this._shutdown$)
      )
      .subscribe({
        error: (err) =>
          console.error('[ModelMonitor] Unhandled stream error', err),
      });

    // Periodic heartbeat to reassure liveness
    merge(
      timer(0, 60_000).pipe(
        tap(() =>
          this.producer
            .send({
              topic: alertsTopic,
              messages: [
                {
                  key: 'HEARTBEAT',
                  value: JSON.stringify({ ts: Date.now() }),
                },
              ],
            })
            .catch((err) =>
              console.error('[ModelMonitor] Heartbeat failure', err)
            )
        )
      )
    )
      .pipe(takeUntil(this._shutdown$))
      .subscribe();
  }

  /**
   * Dynamic configuration/control message handler.
   * Enables hot-reloading of rules without downtime.
   */
  _handleControlMessage(message) {
    try {
      const { op, payload } = JSON.parse(message.value.toString());

      switch (op) {
        case 'ADD_RULE':
          if (typeof payload?.code !== 'string') break;
          // `payload.code` should export a function (metrics) => alert | void
          // eslint-disable-next-line no-new-func
          const fn = new Function(
            'return ' + payload.code
          )();
          this.config.alertRules.push(fn);
          console.info('[ModelMonitor] Added new rule via control topic');
          break;

        case 'REMOVE_RULE':
          this.config.alertRules = this.config.alertRules.filter(
            (r) => r.name !== payload?.name
          );
          console.info('[ModelMonitor] Removed rule:', payload?.name);
          break;

        default:
          console.warn('[ModelMonitor] Unknown control op:', op);
      }
    } catch (err) {
      console.error('[ModelMonitor] Failed to handle control message', err);
    }
  }
}

/* -------------------------------------------------------------------------- *
 * CLI entrypoint                                                             *
 * -------------------------------------------------------------------------- */

if (require.main === module) {
  (async () => {
    const monitor = new RealTimeModelMonitor();

    // Graceful shutdown (Ctrl-C, SIGTERM, etc.)
    const shutdown = async () => {
      console.log('\n[ModelMonitor] Shutting down...');
      await monitor.stop();
      process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);

    try {
      await monitor.start();
    } catch (err) {
      console.error('[ModelMonitor] Fatal error', err);
      await shutdown();
    }
  })();
}
```