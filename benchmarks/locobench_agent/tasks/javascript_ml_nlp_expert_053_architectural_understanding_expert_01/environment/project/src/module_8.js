```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: Sliding-Window Model Monitor
 *
 * File path: src/module_8.js
 * Language : JavaScript (Node.js >= 14)
 *
 * Responsibilities
 * • Consume “prediction-truth” pairs from Kafka (produced by model-serving layer)
 * • Aggregate them inside a sliding, time-based window using RxJS
 * • Compute online quality / fairness metrics
 * • Expose Prometheus metrics for dashboards & alerting
 * • Emit domain events to Kafka when any metric breaches configured thresholds
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* External Dependencies                                                     */
/* ────────────────────────────────────────────────────────────────────────── */
const { Kafka }               = require('kafkajs');         // Kafka client
const { Subject, timer }      = require('rxjs');            // Reactive core
const { bufferTime, filter }  = require('rxjs/operators');  // RxJS operators
const _                       = require('lodash');          // Utility helpers
const promClient              = require('prom-client');     // Prometheus client
const pino                    = require('pino');            // Fast logger
const { v4: uuidv4 }          = require('uuid');            // UUID generator

/* ────────────────────────────────────────────────────────────────────────── */
/* Config / Constants                                                        */
/* ────────────────────────────────────────────────────────────────────────── */
const DEFAULT_WINDOW_SEC   = 60; // Size of sliding window in seconds
const DEFAULT_EMIT_TOPIC   = 'model_monitoring_alerts';
const DEFAULT_SOURCE_TOPIC = 'model_predictions';

const METRIC_PREFIX = 'agorapulse_model_';

/* ────────────────────────────────────────────────────────────────────────── */
/* Logger                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */
const log = pino({
  name   : 'SlidingWindowMonitor',
  level  : process.env.LOG_LEVEL || 'info',
});

/* ────────────────────────────────────────────────────────────────────────── */
/* Custom Errors                                                             */
/* ────────────────────────────────────────────────────────────────────────── */
class MetricComputationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'MetricComputationError';
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Prometheus Metric Registry                                                */
/* ────────────────────────────────────────────────────────────────────────── */
const registry = new promClient.Registry();
promClient.collectDefaultMetrics({ register: registry });

/**
 * Factory helper to create or retrieve Prometheus Gauge
 * (prevents duplicate registrations in hot-reload environments)
 */
function getOrCreateGauge(name, help, labelNames = []) {
  const existing = registry.getSingleMetric(name);
  if (existing) return existing;
  const gauge = new promClient.Gauge({ name, help, labelNames, registers: [registry] });
  return gauge;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Core Class                                                                */
/* ────────────────────────────────────────────────────────────────────────── */
class SlidingWindowMonitor {
  /**
   * @param {Object} params
   * @param {Object} params.kafkaConfig      – kafkajs configuration object
   * @param {Array<string>} params.topics    – Kafka topics to consume from (default: model_predictions)
   * @param {number} params.windowSec        – Window size in seconds
   * @param {string} params.emitTopic        – Destination topic for alerts
   * @param {Object} params.thresholds       – Alert thresholds for metrics
   * @param {number} params.thresholds.maxFalseNegRate – Maximum tolerated false-negative rate
   * @param {number} params.thresholds.minAccuracy     – Minimum accepted accuracy
   */
  constructor({
    kafkaConfig           = {},
    topics                = [DEFAULT_SOURCE_TOPIC],
    windowSec             = DEFAULT_WINDOW_SEC,
    emitTopic             = DEFAULT_EMIT_TOPIC,
    thresholds            = {},
  } = {}) {
    this.id          = uuidv4();
    this.kafka       = new Kafka(kafkaConfig);
    this.topics      = topics;
    this.windowMs    = windowSec * 1000;
    this.emitTopic   = emitTopic;
    this.thresholds  = {
      maxFalseNegRate : thresholds.maxFalseNegRate ?? 0.05,
      minAccuracy     : thresholds.minAccuracy     ?? 0.90,
    };

    // RxJS subject acts as the ingestion bridge for Kafka messages
    this.subject     = new Subject();

    // Prometheus gauges (labeled by modelId + version)
    this.gAccuracy       = getOrCreateGauge(
      `${METRIC_PREFIX}accuracy`,
      'Online accuracy over sliding window',
      ['model_id', 'version'],
    );
    this.gFalseNeg       = getOrCreateGauge(
      `${METRIC_PREFIX}false_negative_rate`,
      'False-negative rate over sliding window',
      ['model_id', 'version'],
    );
  }

  /* ────────────────────────────────────────────────────────────────────── */
  /* Kafka Helpers                                                         */
  /* ────────────────────────────────────────────────────────────────────── */

  async _initKafka() {
    this.consumer = this.kafka.consumer({ groupId: `monitor-${this.id}` });
    this.producer = this.kafka.producer();

    await Promise.all([
      this.consumer.connect(),
      this.producer.connect(),
    ]);

    await Promise.all(
      this.topics.map((t) => this.consumer.subscribe({ topic: t, fromBeginning: false })),
    );

    this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          const payload = JSON.parse(message.value.toString());
          this.subject.next(payload);
        } catch (err) {
          log.warn({ err }, 'Invalid JSON message dropped');
        }
      },
    });

    log.info({ topics: this.topics }, 'Kafka consumer connected');
  }

  /* ────────────────────────────────────────────────────────────────────── */
  /* Metric Computation                                                    */
  /* ────────────────────────────────────────────────────────────────────── */

  /**
   * Compute accuracy & false-negative rate for a batch
   * @param {Array<Object>} batch – Array of prediction events
   * @returns {Object} metrics
   * @throws {MetricComputationError}
   */
  _computeMetrics(batch) {
    if (!batch.length) throw new MetricComputationError('Empty batch');

    const tp = batch.filter((e) => e.prediction === 1 && e.label === 1).length;
    const tn = batch.filter((e) => e.prediction === 0 && e.label === 0).length;
    const fp = batch.filter((e) => e.prediction === 1 && e.label === 0).length;
    const fn = batch.filter((e) => e.prediction === 0 && e.label === 1).length;

    const accuracy         = (tp + tn) / batch.length;
    const falseNegRate     = fn / (fn + tp || 1); // Avoid division by zero
    return { accuracy, falseNegRate };
  }

  /**
   * Push Prometheus metrics
   */
  _pushMetrics({ modelId, version, accuracy, falseNegRate }) {
    this.gAccuracy.set({ model_id: modelId, version }, accuracy);
    this.gFalseNeg.set({ model_id: modelId, version }, falseNegRate);
  }

  /**
   * Decide whether an alert should be emitted
   */
  _shouldAlert({ accuracy, falseNegRate }) {
    return (
      accuracy < this.thresholds.minAccuracy ||
      falseNegRate > this.thresholds.maxFalseNegRate
    );
  }

  /**
   * Emit alert to Kafka
   */
  async _emitAlert(event) {
    try {
      await this.producer.send({
        topic : this.emitTopic,
        messages: [{ key: event.modelId, value: JSON.stringify(event) }],
      });
      log.warn({ event }, 'Monitoring alert emitted');
    } catch (err) {
      log.error({ err }, 'Failed to emit alert event');
    }
  }

  /* ────────────────────────────────────────────────────────────────────── */
  /* RxJS Pipeline                                                         */
  /* ────────────────────────────────────────────────────────────────────── */

  _buildPipeline() {
    this.subject
      .pipe(
        // Windowed buffering
        bufferTime(this.windowMs),
        // Drop empty windows
        filter((batch) => batch.length > 0),
      )
      .subscribe({
        next  : (batch) => this._processBatch(batch),
        error : (err)   => log.error({ err }, 'Stream processing error'),
      });
  }

  async _processBatch(batch) {
    // Group by modelId + version to compute metrics per model
    const groups = _.groupBy(batch, (e) => `${e.modelId}::${e.version}`);

    await Promise.all(
      Object.entries(groups).map(async ([key, group]) => {
        const [modelId, version] = key.split('::');

        let metrics;
        try {
          metrics = this._computeMetrics(group);
        } catch (err) {
          if (err instanceof MetricComputationError) {
            log.warn({ err }, 'Skipping metric computation for batch');
            return;
          }
          throw err; // Unexpected error – propagate
        }

        this._pushMetrics({ modelId, version, ...metrics });

        if (this._shouldAlert(metrics)) {
          const alertEvt = {
            eventId      : uuidv4(),
            timestamp    : Date.now(),
            modelId,
            version,
            metrics,
            windowSec    : this.windowMs / 1000,
            thresholds   : this.thresholds,
            type         : 'MODEL_METRIC_THRESHOLD_BREACHED',
          };
          await this._emitAlert(alertEvt);
        } else {
          log.debug({ modelId, version, metrics }, 'Metrics within thresholds');
        }
      }),
    );
  }

  /* ────────────────────────────────────────────────────────────────────── */
  /* Public API                                                            */
  /* ────────────────────────────────────────────────────────────────────── */

  /**
   * Start monitoring
   */
  async start() {
    log.info('Starting SlidingWindowMonitor...');
    this._buildPipeline();
    await this._initKafka();
  }

  /**
   * Graceful shutdown
   */
  async stop() {
    log.info('Stopping SlidingWindowMonitor...');
    await Promise.all([
      this.consumer?.disconnect(),
      this.producer?.disconnect(),
    ]);
  }

  /**
   * Expose Prometheus metrics as text (for HTTP endpoint)
   * @returns {Promise<string>}
   */
  async metrics() {
    return registry.metrics();
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Module Export                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

module.exports = {
  SlidingWindowMonitor,
  MetricComputationError,
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Example Invocation (stand-alone node src/module_8.js)                     */
/* ────────────────────────────────────────────────────────────────────────── */
if (require.main === module) {
  (async () => {
    const monitor = new SlidingWindowMonitor({
      kafkaConfig : { brokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(',') },
      windowSec   : Number(process.env.WINDOW_SEC) || DEFAULT_WINDOW_SEC,
    });

    // Graceful SIGTERM/SIGINT
    const shutdown = async () => {
      await monitor.stop();
      process.exit(0);
    };

    process.on('SIGTERM', shutdown);
    process.on('SIGINT',  shutdown);

    try {
      await monitor.start();
      log.info('SlidingWindowMonitor is up');
    } catch (err) {
      log.fatal({ err }, 'Fatal error, shutting down');
      await shutdown();
    }
  })();
}
```