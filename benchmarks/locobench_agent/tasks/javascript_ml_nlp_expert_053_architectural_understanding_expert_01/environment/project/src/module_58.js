```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 *
 * Module: ModelDriftMonitor
 * File  : src/module_58.js
 *
 * Listens to real-time inference and feedback events, aggregates metrics over a
 * sliding time-window, and emits “retraining-trigger” events to Kafka whenever
 * online performance breaches configurable thresholds (e.g., toxicity false-
 * negative rate, p95 latency).
 *
 * The module is completely self-contained; simply instantiate
 * `new ModelDriftMonitor().start()` inside your boot-strapper.
 */

import { Kafka, logLevel } from 'kafkajs';
import {
  Subject,
  merge,
  timer,
  takeUntil,
  bufferTime,
  filter,
  map,
  from,
} from 'rxjs';
import pino from 'pino';
import { isNil } from 'lodash';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/**
 * Environment-driven config ensures 12-Factor compliance.
 * All thresholds are intentionally conservative; tune as needed.
 */
const CONFIG = {
  kafka: {
    clientId: process.env.KAFKA_CLIENT_ID ?? 'agorapulse-drift-monitor',
    brokers: (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
    groupId: process.env.KAFKA_GROUP_ID ?? 'drift-monitor-group',
  },
  topics: {
    inference: process.env.KAFKA_TOPIC_INFERENCE ?? 'model-inference',
    feedback: process.env.KAFKA_TOPIC_FEEDBACK ?? 'user-feedback',
    retrain: process.env.KAFKA_TOPIC_RETRAIN ?? 'model-retrain',
  },
  monitoring: {
    windowSeconds: Number(process.env.MONITOR_WINDOW_SEC) || 60,
    minSamples: Number(process.env.MONITOR_MIN_SAMPLES) || 500,
    maxToxicityFNRate: Number(process.env.MONITOR_MAX_FN) || 0.02,
    maxP95LatencyMs: Number(process.env.MONITOR_MAX_P95_LATENCY_MS) || 250,
  },
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} InferenceEvent
 * @property {string} id            – Correlation identifier, shared with feedback.
 * @property {string} modelVersion  – Model version (sem-ver).
 * @property {number} timestamp     – Client-side epoch millis.
 * @property {number} latencyMs     – Serving latency.
 * @property {Object} result
 * @property {string} result.label  – Predicted label (e.g. "toxic" / "clean").
 * @property {number} result.score  – Soft-probability.
 */

/**
 * @typedef {Object} FeedbackEvent
 * @property {string} id             – Correlation identifier.
 * @property {number} timestamp      – When feedback was produced.
 * @property {string} truthLabel     – Ground-truth label.
 */

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

const logger = pino({
  name: 'ModelDriftMonitor',
  level: process.env.LOG_LEVEL ?? 'info',
  base: undefined, // remove pid/hostname noise from structured logs
});

export class ModelDriftMonitor {
  #kafka;
  #producer;
  #inferenceConsumer;
  #feedbackConsumer;

  // RxJS subjects to bridge Kafka → reactive operators
  #inference$ = new Subject(); // emits InferenceEvent
  #feedback$ = new Subject();  // emits FeedbackEvent
  #shutdown$ = new Subject();  // emits void   (stop signal)

  // Correlation buffer – keeps incomplete pairs for a bounded horizon
  // (pruned via periodic cleanup to avoid unbounded memory growth).
  #pending = new Map();

  constructor(customConfig = {}) {
    this.config = {
      ...CONFIG,
      ...customConfig,
      kafka: { ...CONFIG.kafka, ...customConfig.kafka },
      topics: { ...CONFIG.topics, ...customConfig.topics },
      monitoring: { ...CONFIG.monitoring, ...customConfig.monitoring },
    };

    this.#kafka = new Kafka({
      clientId: this.config.kafka.clientId,
      brokers: this.config.kafka.brokers,
      logLevel: logLevel.NOTHING, // suppress kafkajs internal logs; rely on pino
    });
  }

  // --------------------------------------------------------
  // Lifecycle management
  // --------------------------------------------------------

  async start() {
    logger.info('Starting ModelDriftMonitor…');
    await this.#initKafka();
    this.#initRxPipeline();
    this.#scheduleStalePairSweep();
    logger.info('ModelDriftMonitor started.');
  }

  async stop() {
    logger.info('Stopping ModelDriftMonitor…');
    this.#shutdown$.next();
    await Promise.allSettled([
      this.#inferenceConsumer?.disconnect(),
      this.#feedbackConsumer?.disconnect(),
      this.#producer?.disconnect(),
    ]);
    logger.info('ModelDriftMonitor stopped.');
  }

  // --------------------------------------------------------
  // Kafka wiring
  // --------------------------------------------------------

  async #initKafka() {
    this.#producer = this.#kafka.producer();
    this.#inferenceConsumer = this.#kafka.consumer({
      groupId: `${this.config.kafka.groupId}-inference`,
    });
    this.#feedbackConsumer = this.#kafka.consumer({
      groupId: `${this.config.kafka.groupId}-feedback`,
    });

    await Promise.all([
      this.#producer.connect(),

      this.#inferenceConsumer.connect(),
      this.#inferenceConsumer.subscribe({
        topic: this.config.topics.inference,
        fromBeginning: false,
      }),
      this.#inferenceConsumer.run({
        eachMessage: async ({ message }) => {
          try {
            const ev = JSON.parse(message.value.toString());
            if (this.#validateInference(ev)) this.#inference$.next(ev);
          } catch (err) {
            logger.warn({ err }, 'Bad inference message – skipped.');
          }
        },
      }),

      this.#feedbackConsumer.connect(),
      this.#feedbackConsumer.subscribe({
        topic: this.config.topics.feedback,
        fromBeginning: false,
      }),
      this.#feedbackConsumer.run({
        eachMessage: async ({ message }) => {
          try {
            const ev = JSON.parse(message.value.toString());
            if (this.#validateFeedback(ev)) this.#feedback$.next(ev);
          } catch (err) {
            logger.warn({ err }, 'Bad feedback message – skipped.');
          }
        },
      }),
    ]);
  }

  // --------------------------------------------------------
  // RxJS pipeline (metrics & alerts)
  // --------------------------------------------------------

  #initRxPipeline() {
    const {
      windowSeconds,
      minSamples,
      maxToxicityFNRate,
      maxP95LatencyMs,
    } = this.config.monitoring;

    // -------- Pair inference ↔ feedback --------
    merge(this.#inference$, this.#feedback$)
      .pipe(takeUntil(this.#shutdown$))
      .subscribe((ev) => this.#correlatePair(ev));

    // -------- Sliding-window aggregation --------
    from(this.#inference$) // "from" ensures multicast semantics
      .pipe(
        takeUntil(this.#shutdown$),
        bufferTime(windowSeconds * 1000, undefined, Number.POSITIVE_INFINITY),
        filter((batch) => batch.length >= minSamples)
      )
      .subscribe(async (batch) => {
        const metrics = this.#computeMetrics(batch);
        logger.debug({ metrics }, 'Computed metrics for window');

        if (this.#breach(metrics, maxToxicityFNRate, maxP95LatencyMs)) {
          logger.warn({ metrics }, 'Performance breach detected – emitting retrain event');
          await this.#emitRetrainEvent(metrics);
        }
      });
  }

  // --------------------------------------------------------
  // Event correlation
  // --------------------------------------------------------

  /**
   * Maintains a correlation buffer so that whenever an inference and its
   * feedback arrive (order-agnostic) we can enrich the inference with ground-
   * truth information necessary for online metrics.
   */
  #correlatePair(ev) {
    const { id } = ev;
    if (!id) return;

    const existing = this.#pending.get(id) ?? {};
    const merged = { ...existing, ...ev, receivedAt: Date.now() };

    // if we have both result.label and truthLabel we can push to inference$ for metrics
    if (!isNil(merged.truthLabel) && !isNil(merged.result?.label)) {
      this.#inference$.next(merged);
      this.#pending.delete(id);
    } else {
      this.#pending.set(id, merged);
    }
  }

  /**
   * Periodically remove zombie entries (ids that never received their pair).
   * This avoids runaway memory growth.
   */
  #scheduleStalePairSweep() {
    const STALE_MS = this.config.monitoring.windowSeconds * 5 * 1000; // 5x window
    timer(STALE_MS, STALE_MS)
      .pipe(takeUntil(this.#shutdown$))
      .subscribe(() => {
        const now = Date.now();
        let purged = 0;
        for (const [id, obj] of this.#pending.entries()) {
          if (now - obj.receivedAt > STALE_MS) {
            this.#pending.delete(id);
            purged += 1;
          }
        }
        if (purged) logger.debug({ purged }, 'Stale correlation pairs purged');
      });
  }

  // --------------------------------------------------------
  // Metrics & thresholds
  // --------------------------------------------------------

  /**
   * Compute window metrics.
   * We only track:
   *  – toxicity false-negative rate: fraction of (truth="toxic", pred="clean")
   *  – p95 latency
   *
   * @param {Array<InferenceEvent & FeedbackEvent>} batch
   */
  #computeMetrics(batch) {
    let toxicTruth = 0;
    let toxicFN = 0;
    const latencies = [];

    for (const msg of batch) {
      if (msg.truthLabel === 'toxic') {
        toxicTruth++;
        if (msg.result.label !== 'toxic') toxicFN++;
      }
      if (!isNil(msg.latencyMs)) latencies.push(msg.latencyMs);
    }

    latencies.sort((a, b) => a - b);
    const idx = Math.floor(0.95 * (latencies.length - 1));
    const p95Latency = latencies[idx] ?? 0;

    return {
      cnt: batch.length,
      toxicTruth,
      toxicFN,
      fnRate: toxicTruth ? toxicFN / toxicTruth : 0,
      p95Latency,
    };
  }

  /**
   * Does the window breach any configured thresholds?
   */
  #breach(metrics, maxFNRate, maxP95Latency) {
    return (
      metrics.fnRate > maxFNRate || metrics.p95Latency > maxP95Latency
    );
  }

  /**
   * Send a retraining trigger event to Kafka with contextual metadata.
   */
  async #emitRetrainEvent(metrics) {
    try {
      await this.#producer.send({
        topic: this.config.topics.retrain,
        messages: [
          {
            key: 'model-drift',
            value: JSON.stringify({
              type: 'MODEL_PERFORMANCE_BREACH',
              detectedAt: Date.now(),
              metrics,
            }),
          },
        ],
      });
    } catch (err) {
      logger.error({ err }, 'Failed to publish retrain event');
    }
  }

  // --------------------------------------------------------
  // Validation helpers
  // --------------------------------------------------------

  #validateInference(ev) {
    return (
      ev &&
      typeof ev.id === 'string' &&
      ev.result &&
      typeof ev.result.label === 'string'
    );
  }

  #validateFeedback(ev) {
    return (
      ev &&
      typeof ev.id === 'string' &&
      typeof ev.truthLabel === 'string'
    );
  }
}

// ---------------------------------------------------------------------------
// Auto-start if launched directly (e.g. `node src/module_58.js`)
// ---------------------------------------------------------------------------
if (require.main === module) {
  const monitor = new ModelDriftMonitor();
  monitor.start();

  // Graceful shutdown
  ['SIGINT', 'SIGTERM'].forEach((signal) =>
    process.on(signal, async () => {
      logger.info(`Received ${signal} – shutting down…`);
      await monitor.stop();
      process.exit(0);
    })
  );
}
```