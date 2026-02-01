```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module 66: RealtimeDriftMonitor
 *
 * This module listens to a Kafka topic that contains model-serving
 * inference events (prediction + ground-truth once available) and
 * detects potential model performance or fairness regressions in
 * real-time.  When drift is detected, it emits a domain event that
 * triggers automated retraining workflows downstream.
 *
 * The implementation is intentionally self-contained—no business logic
 * is hard-coded—so thresholds and fairness metrics can be adapted
 * dynamically through the configuration topic.
 */

import { Kafka } from 'kafkajs';
import EventEmitter from 'events';
import { Subject, from, of } from 'rxjs';
import {
  bufferTime,
  catchError,
  filter,
  map,
  mergeMap,
  tap,
} from 'rxjs/operators';
import * as promClient from 'prom-client';
import merge from 'lodash/merge';
import createLogger from './utils/logger.js'; // project-local Winston wrapper

/* ------------------------------------------------------------------ *
 * Constants & Types
 * ------------------------------------------------------------------ */

/**
 * @typedef {Object} DriftMonitorOptions
 * @property {string} kafkaBrokers          – Comma-separated address list
 * @property {string} inferenceTopic        – Kafka topic with inference events
 * @property {number} slidingWindow         – Window size in milliseconds
 * @property {number} minSamples            – Min # of samples before checking
 * @property {number} accuracyDropThreshold – Accuracy % drop vs. baseline
 * @property {number} fairnessThreshold     – Allowed Δ between group accuracies
 * @property {Object} baselineMetrics       – { accuracy: number, groupAccuracies: Object<string, number> }
 */

const DEFAULT_OPTIONS = /** @type {DriftMonitorOptions} */ ({
  kafkaBrokers: process.env.KAFKA_BROKERS || 'localhost:9092',
  inferenceTopic: process.env.INFERENCE_TOPIC || 'agorapulse.inference',
  slidingWindow: 60_000, // 1 minute
  minSamples: 500,
  accuracyDropThreshold: 0.05, // 5 % absolute drop
  fairnessThreshold: 0.07, // max allowed gap
  baselineMetrics: {
    accuracy: 0.9,
    groupAccuracies: {}, // e.g., { "en": 0.92, "es": 0.88 }
  },
});

/* ------------------------------------------------------------------ *
 * Utility helpers
 * ------------------------------------------------------------------ */

/**
 * Incrementally updates numeric aggregate.
 */
function updateRunningMetric(metric, value) {
  metric.count += 1;
  metric.sum += value;
  return metric;
}

/* ------------------------------------------------------------------ *
 * RealtimeDriftMonitor
 * ------------------------------------------------------------------ */

export default class RealtimeDriftMonitor extends EventEmitter {
  /**
   * @param {Partial<DriftMonitorOptions>} [userOptions]
   */
  constructor(userOptions = {}) {
    super();

    /** @type {DriftMonitorOptions} */
    this.options = merge({}, DEFAULT_OPTIONS, userOptions);

    // Winston logger – level derived from ENV
    this.log = createLogger('RealtimeDriftMonitor');

    // Kafka client
    this.kafka = new Kafka({
      brokers: this.options.kafkaBrokers.split(','),
      clientId: 'agorapulse.drift-monitor',
      connectionTimeout: 3_000,
      logLevel: 0,
    });

    this.consumer = this.kafka.consumer({
      groupId: 'agorapulse.drift-monitor-group',
    });

    // RxJS subject that will stream incoming messages
    this.event$ = new Subject();

    // Prometheus metrics
    this.metrics = {
      accuracy: new promClient.Gauge({
        name: 'agorapulse_serving_accuracy',
        help: 'Rolling accuracy over last window',
      }),
      fairnessGap: new promClient.Gauge({
        name: 'agorapulse_serving_fairness_gap',
        help: 'Max Δ accuracy between protected groups',
      }),
      driftFlag: new promClient.Gauge({
        name: 'agorapulse_drift_flag',
        help: '1 when drift detected in last evaluation window',
      }),
    };

    // Internal state
    this.running = false;
  }

  /**
   * Connects to Kafka and starts the RxJS pipeline.
   */
  async start() {
    if (this.running) return;
    this.running = true;

    await this.consumer.connect();
    await this.consumer.subscribe({ topic: this.options.inferenceTopic });

    // Forward each Kafka message to RxJS stream
    this.consumer.run({
      eachMessage: async ({ message }) => {
        try {
          // Robust JSON parse
          const payload = JSON.parse(message.value.toString('utf8'));
          this.event$.next(payload);
        } catch (err) {
          this.log.warn('Malformed message skipped', { err });
        }
      },
    });

    // Build processing pipeline
    this.#buildPipeline();

    this.log.info('Drift monitor started', { topic: this.options.inferenceTopic });
  }

  /**
   * Gracefully stops consumption and cleans up resources.
   */
  async stop() {
    if (!this.running) return;
    this.running = false;

    await this.consumer.disconnect();
    this.event$.complete();

    this.log.info('Drift monitor stopped');
  }

  /* ------------------------------------------------------------------ *
   * Internal
   * ------------------------------------------------------------------ */

  /**
   * Constructs the RxJS pipeline that computes metrics in sliding windows.
   */
  #buildPipeline() {
    const {
      slidingWindow,
      minSamples,
      accuracyDropThreshold,
      fairnessThreshold,
      baselineMetrics,
    } = this.options;

    this.event$
      .pipe(
        // Pre-transform event
        map((evt) => ({
          // expected shape: { id, y_pred, y_true, protected_attr }
          // Missing ground_truth until human moderation arrives;
          ...evt,
          valid: typeof evt.y_true !== 'undefined',
        })),
        filter((evt) => evt.valid),
        bufferTime(slidingWindow),
        filter((batch) => batch.length >= minSamples),
        mergeMap((batch) =>
          from(this.#computeMetrics(batch)).pipe(
            tap((metrics) => this.#updatePrometheus(metrics)),
            tap((metrics) => this.#maybeEmitDrift(metrics, baselineMetrics, accuracyDropThreshold, fairnessThreshold)),
            catchError((err) => {
              this.log.error('Error computing drift metrics', { err });
              this.emit('error', err);
              return of(null);
            }),
          ),
        ),
      )
      .subscribe(); // side-effects only
  }

  /**
   * Computes windowed accuracy & group accuracies.
   *
   * @param {Array<any>} batch
   * @returns {Promise<{ accuracy: number, groupAccuracies: Object<string, number> }>}
   */
  async #computeMetrics(batch) {
    const stats = {
      accuracyMetric: { count: 0, sum: 0 },
      // per protected attribute
      group: /** @type {Record<string, { count: number, sum: number }>} */ ({}),
    };

    batch.forEach((evt) => {
      const correct = evt.y_pred === evt.y_true ? 1 : 0;

      updateRunningMetric(stats.accuracyMetric, correct);

      const groupKey = evt.protected_attr || 'unknown';
      if (!stats.group[groupKey]) {
        stats.group[groupKey] = { count: 0, sum: 0 };
      }
      updateRunningMetric(stats.group[groupKey], correct);
    });

    const accuracy = stats.accuracyMetric.sum / stats.accuracyMetric.count;

    /** @type {Record<string, number>} */
    const groupAccuracies = {};
    Object.entries(stats.group).forEach(([k, v]) => {
      groupAccuracies[k] = v.sum / v.count;
    });

    return { accuracy, groupAccuracies };
  }

  /**
   * Publishes metrics to Prometheus registry.
   * @param {{ accuracy: number, groupAccuracies: Object<string, number> }} metrics
   */
  #updatePrometheus(metrics) {
    this.metrics.accuracy.set(metrics.accuracy);

    // compute fairness gap
    const accValues = Object.values(metrics.groupAccuracies);
    const max = Math.max(...accValues);
    const min = Math.min(...accValues);
    const gap = max - min;

    this.metrics.fairnessGap.set(gap);
  }

  /**
   * Emits ‘driftDetected’ domain event when thresholds breached.
   *
   * @param {{ accuracy: number, groupAccuracies: Object<string, number> }} current
   * @param {{ accuracy: number, groupAccuracies: Object<string, number> }} baseline
   * @param {number} accThreshold
   * @param {number} fairnessThreshold
   */
  #maybeEmitDrift(current, baseline, accThreshold, fairnessThreshold) {
    const accDrop = baseline.accuracy - current.accuracy;

    const accAlert = accDrop > accThreshold;

    // fairness gap comparison
    const currentGap =
      Math.max(...Object.values(current.groupAccuracies)) -
      Math.min(...Object.values(current.groupAccuracies));

    const fairnessAlert = currentGap > fairnessThreshold;

    const driftDetected = accAlert || fairnessAlert;

    this.metrics.driftFlag.set(driftDetected ? 1 : 0);

    if (driftDetected) {
      const payload = {
        timestamp: Date.now(),
        current,
        baseline,
        accDrop,
        currentGap,
        fairnessThreshold,
      };
      this.log.warn('⚠️  Model drift detected', payload);
      this.emit('driftDetected', payload);
    } else {
      // still emit metrics update for dashboards
      this.emit('metricsUpdate', current);
    }
  }
}

/* ------------------------------------------------------------------ *
 * Auto-start in stand-alone mode
 * ------------------------------------------------------------------ */

// Allow the module to be executed directly for local debugging
if (require.main === module) {
  (async () => {
    const monitor = new RealtimeDriftMonitor();
    await monitor.start();

    // Shutdown gracefully on SIGINT / SIGTERM
    const shutdown = async () => {
      await monitor.stop();
      process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
  })().catch((err) => {
    console.error('Fatal error starting RealtimeDriftMonitor', err);
    process.exit(1);
  });
}
```