```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: src/module_49.js
 *
 * Responsibility:
 *   Real-time monitoring of model-serving quality.  The monitor listens to the
 *   `ml.inference.outcome` Kafka topic where online predictions are enriched
 *   with their ground-truth label once it becomes available (usually minutes
 *   later after a moderation decision or user feedback).  Sliding-window
 *   metrics are computed with RxJS and exported via Prometheus as well as
 *   domain events to downstream services (alerting, retraining pipeline, etc.).
 *
 * Patterns used:
 *   • Observer / Reactive (RxJS stream)
 *   • Pipeline (Kafka → RxJS → Metrics → Kafka)
 *   • Strategy (custom threshold evaluators)
 *
 * NOTE: This file is plain JavaScript (ES2020) with JSDoc type annotations so
 *       that both TS tooling and plain node runtimes work out-of-the-box.
 */

/* ────────────────────────────────────────────────────────────────────────── */
/* External dependencies                                                     */
/* ────────────────────────────────────────────────────────────────────────── */
import { Kafka, logLevel, CompressionTypes } from 'kafkajs';
import pino from 'pino';
import { Subject } from 'rxjs';
import {
  bufferTime,
  filter as rxFilter,
  map as rxMap,
  mergeMap,
} from 'rxjs/operators';
import Ajv from 'ajv';
import {
  Counter,
  Gauge,
  Histogram,
  Registry,
  collectDefaultMetrics,
} from 'prom-client';

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants & configuration                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Sliding-window size (ms) for metrics.  Must balance reactivity vs variance.
 * 60 000 ms = 1 minute.
 * @type {number}
 */
const DEFAULT_WINDOW_MS = 60_000;

/**
 * How often to push Prometheus histograms to gateway (ms).
 * Kept short for demo purposes, could be ≥ 15 s in prod.
 * @type {number}
 */
const DEFAULT_PROM_PUSH_MS = 5_000;

/** @type {import('ajv').JSONSchemaType<object>} */
const INFERENCE_SCHEMA = {
  type: 'object',
  properties: {
    inferenceId: { type: 'string' },
    modelVersion: { type: 'string' },
    predictedLabel: { type: 'string' },
    groundTruthLabel: { type: 'string', nullable: true },
    timestamp: { type: 'number' },
  },
  required: ['inferenceId', 'modelVersion', 'predictedLabel', 'timestamp'],
  additionalProperties: true,
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Helper classes                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Accumulates confusion-matrix counts for binary classification during a window.
 *
 * @class
 */
class MetricAccumulator {
  /** @private */
  #tp = 0;
  /** @private */
  #tn = 0;
  /** @private */
  #fp = 0;
  /** @private */
  #fn = 0;

  /**
   * Update confusion-matrix counts for a single example.
   * @param {string} predicted
   * @param {string} truth
   */
  update(predicted, truth) {
    const positive = 'positive'; // domain-specific positive class
    const negative = 'negative';

    if (![positive, negative].includes(predicted) ||
        ![positive, negative].includes(truth)) {
      // Unknown classes → skip
      return;
    }

    if (predicted === positive && truth === positive) this.#tp++;
    else if (predicted === positive && truth === negative) this.#fp++;
    else if (predicted === negative && truth === positive) this.#fn++;
    else if (predicted === negative && truth === negative) this.#tn++;
  }

  /**
   * Convert counts to easily consumable metrics.
   * @returns {{tp:number,tn:number,fp:number,fn:number,accuracy:number,fnr:number}}
   */
  metrics() {
    const { #tp: tp, #tn: tn, #fp: fp, #fn: fn } = this;
    const total = tp + tn + fp + fn;
    const accuracy = total ? (tp + tn) / total : 0;
    const fnr = tp + fn ? fn / (tp + fn) : 0; // False Negative Rate
    return { tp, tn, fp, fn, accuracy, fnr };
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Main monitoring class                                                     */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * @typedef {Object} MonitorOptions
 * @property {string[]} brokers                – Kafka broker list
 * @property {string}  topicInferences         – Incoming topic w/ outcomes
 * @property {string}  topicAlerts             – Outgoing topic for alerts
 * @property {number}  [windowMs]              – Metrics sliding window
 * @property {{accuracy:number,fnr:number}} thresholds – Alert thresholds
 * @property {Registry} [registry]             – Prom. registry, optional
 */

export class ModelPerformanceMonitor {
  /** @private */
  #kafka;
  /** @private */
  #consumer;
  /** @private */
  #producer;
  /** @private */
  #subject = new Subject();
  /** @private */
  #logger;
  /** @private */
  #ajvValidate;
  /** @private */
  #windowMs;
  /** @type {{accuracy:number,fnr:number}} */
  #thresholds;

  // Prometheus metrics
  /** @private */
  #mAccuracy;
  /** @private */
  #mFnr;
  /** @private */
  #mThroughput;

  /**
   * @param {MonitorOptions} opts
   */
  constructor(opts) {
    this.#logger = pino({
      name: 'model-perf-monitor',
      level: process.env.LOG_LEVEL || 'info',
    });

    this.#windowMs = opts.windowMs ?? DEFAULT_WINDOW_MS;
    this.#thresholds = opts.thresholds;
    this.#kafka = new Kafka({
      brokers: opts.brokers,
      logLevel: logLevel.ERROR,
    });

    this.#consumer = this.#kafka.consumer({ groupId: 'perf-monitor' });
    this.#producer = this.#kafka.producer({
      allowAutoTopicCreation: false,
      idempotent: true,
    });

    const ajv = new Ajv({ allErrors: true });
    this.#ajvValidate = ajv.compile(INFERENCE_SCHEMA);

    // Prometheus metrics
    const registry = opts.registry ?? new Registry();
    collectDefaultMetrics({ register: registry });

    this.#mAccuracy = new Gauge({
      name: 'agorapulse_model_accuracy',
      help: 'Sliding window accuracy by modelVersion',
      labelNames: ['modelVersion'],
      registers: [registry],
    });
    this.#mFnr = new Gauge({
      name: 'agorapulse_model_fnr',
      help: 'Sliding window false negative rate by modelVersion',
      labelNames: ['modelVersion'],
      registers: [registry],
    });
    this.#mThroughput = new Histogram({
      name: 'agorapulse_monitor_throughput',
      help: 'Messages per window',
      labelNames: ['modelVersion'],
      registers: [registry],
      buckets: [10, 50, 100, 500, 1000, 5000],
    });

    // RxJS pipeline
    this.#setupStream(opts.topicAlerts);
  }

  /* ──────────────── Public API ──────────────── */

  async start(topic) {
    await Promise.all([this.#consumer.connect(), this.#producer.connect()]);
    await this.#consumer.subscribe({ topic, fromBeginning: false });

    this.#logger.info({ topic }, 'performance monitor started');

    await this.#consumer.run({
      eachMessage: async ({ message }) => this.#ingest(message),
    });
  }

  async shutdown() {
    await Promise.all([this.#consumer.disconnect(), this.#producer.disconnect()]);
    await this.#subject.complete();
    this.#logger.info('performance monitor shut down');
  }

  /* ──────────────── Stream wiring ──────────────── */

  /**
   * Set up the reactive stream once, when instance is created.
   * @param {string} topicAlerts
   * @private
   */
  #setupStream(topicAlerts) {
    this.#subject
      .pipe(
        rxFilter((msg) => msg.groundTruthLabel !== undefined),
        bufferTime(this.#windowMs),
        rxFilter((batch) => batch.length > 0),
        rxMap(this.#aggregate.bind(this)),
        mergeMap((alertEvents) =>
          // Emit 0-n alert events per batch
          alertEvents.length
            ? this.#producer.send({
                topic: topicAlerts,
                compression: CompressionTypes.GZIP,
                messages: alertEvents.map((ev) => ({
                  key: ev.modelVersion,
                  value: JSON.stringify(ev),
                  timestamp: String(Date.now()),
                })),
              })
            : Promise.resolve()
        )
      )
      .subscribe({
        error: (err) => {
          this.#logger.error({ err }, 'stream error');
        },
      });
  }

  /* ──────────────── Kafka ingestion ──────────────── */

  /**
   * Validate & push single Kafka message into RxJS pipeline.
   * @param {import('kafkajs').KafkaMessage} message
   * @private
   */
  #ingest(message) {
    let parsed;
    try {
      parsed = JSON.parse(message.value.toString());
    } catch (err) {
      this.#logger.warn({ err, value: message.value }, 'invalid JSON');
      return;
    }

    if (!this.#ajvValidate(parsed)) {
      this.#logger.warn(
        { errors: this.#ajvValidate.errors, value: parsed },
        'schema validation failed'
      );
      return;
    }

    this.#subject.next(parsed);
  }

  /* ──────────────── Aggregation & alerting ──────────────── */

  /**
   * Aggregate a window of messages by model version, update Prom metrics,
   * and return alert events.
   *
   * @param {Array<Object>} window
   * @returns {Array<Object>} – alert events
   * @private
   */
  #aggregate(window) {
    /** @type {Map<string, MetricAccumulator>} */
    const perModel = new Map();

    for (const msg of window) {
      const acc =
        perModel.get(msg.modelVersion) ?? perModel.set(msg.modelVersion, new MetricAccumulator()).get(msg.modelVersion);
      acc.update(msg.predictedLabel, msg.groundTruthLabel);
    }

    const alerts = [];
    const windowStart = Date.now() - this.#windowMs;
    const windowEnd = Date.now();

    perModel.forEach((acc, modelVersion) => {
      const { accuracy, fnr, tp, tn, fp, fn } = acc.metrics();

      // Prometheus export
      this.#mAccuracy.labels(modelVersion).set(accuracy);
      this.#mFnr.labels(modelVersion).set(fnr);
      this.#mThroughput
        .labels(modelVersion)
        .observe(tp + tn + fp + fn);

      // Threshold evaluation
      if (accuracy < this.#thresholds.accuracy) {
        alerts.push(
          this.#buildAlert(
            modelVersion,
            'accuracy',
            accuracy,
            this.#thresholds.accuracy,
            windowStart,
            windowEnd
          )
        );
      }
      if (fnr > this.#thresholds.fnr) {
        alerts.push(
          this.#buildAlert(
            modelVersion,
            'fnr',
            fnr,
            this.#thresholds.fnr,
            windowStart,
            windowEnd
          )
        );
      }
    });

    return alerts;
  }

  /**
   * Construct alert payload.
   * @private
   */
  #buildAlert(modelVersion, metric, value, threshold, start, end) {
    this.#logger.warn(
      { modelVersion, metric, value, threshold },
      'performance degradation detected'
    );
    return {
      eventType: 'MODEL_PERFORMANCE_ALERT',
      modelVersion,
      metric,
      value,
      threshold,
      windowStart: start,
      windowEnd: end,
      emittedAt: Date.now(),
    };
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Bootstrap – run if executed directly                                      */
/* ────────────────────────────────────────────────────────────────────────── */
if (require.main === module) {
  // Basic CLI usage:
  //   node src/module_49.js KAFKA_BROKER[:PORT] [,KAFKA2] [...]
  const brokers = process.argv.slice(2);
  if (!brokers.length) {
    // eslint-disable-next-line no-console
    console.error('Usage: node src/module_49.js <broker1,broker2,...>');
    process.exit(1);
  }

  const monitor = new ModelPerformanceMonitor({
    brokers,
    topicInferences: 'ml.inference.outcome',
    topicAlerts: 'ml.monitoring.alerts',
    thresholds: { accuracy: 0.85, fnr: 0.15 },
  });

  monitor
    .start('ml.inference.outcome')
    .catch((err) => {
      // eslint-disable-next-line no-console
      console.error('Fatal error starting monitor', err);
      process.exit(1);
    });

  // Graceful shutdown on SIGINT / SIGTERM
  process.on('SIGINT', async () => {
    await monitor.shutdown();
    process.exit(0);
  });
  process.on('SIGTERM', async () => {
    await monitor.shutdown();
    process.exit(0);
  });
}
```