```javascript
/**
 * AgoraPulse — Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: src/module_57.js
 *
 * Component: Real-Time Drift Monitor
 * Purpose:  Observes a stream of model inference events, detects
 *           distributional drift in predictions, and publishes a
 *           domain event to Kafka when the divergence exceeds a
 *           configurable threshold.  This enables fully-automated
 *           retraining triggers and closed-loop model governance.
 *
 * Author:   AgoraPulse Engineering
 * License:  Apache-2.0
 */

'use strict';

/* ────────────────────────────────────────────────────────── Imports ───── */
const { bufferTime, filter, map } = require('rxjs/operators');
const { Subject } = require('rxjs');

const fs = require('fs').promises;
const path = require('path');

const { Kafka, CompressionTypes, logLevel } = require('kafkajs');
const pino = require('pino');
const _ = require('lodash');

/* ──────────────────────────────────────────────────────── Constants ───── */
const DEFAULT_WINDOW_MS = 60_000;           // 1-minute sliding window
const DEFAULT_ALERT_THRESHOLD = 0.12;       // JSD threshold to flag drift
const RETRAIN_EVENT_TOPIC = 'ml.retrain.requested';

const logger = pino({
  name: 'RealTimeDriftMonitor',
  level: process.env.LOG_LEVEL || 'info',
});

/* ─────────────────────────────────────────────────────────── Utils ────── */
/**
 * Numerically safe division.
 */
const safeDiv = (a, b) => (b === 0 ? 0 : a / b);

/**
 * Normalize an object of counts to probability distribution.
 *
 * @param {Object<string, number>} counts
 * @returns {Object<string, number>} distribution
 */
function normalize(counts) {
  const total = _.sum(Object.values(counts));
  return _.mapValues(counts, v => safeDiv(v, total));
}

/**
 * Kullback-Leibler divergence D(P‖Q).
 *
 * @param {number} p
 * @param {number} q
 * @returns {number}
 */
function kl(p, q) {
  if (p === 0) return 0;
  if (q === 0) return Infinity;
  return p * Math.log2(p / q);
}

/**
 * Jensen-Shannon Divergence between two discrete distributions.
 *
 * @param {Object<string, number>} p
 * @param {Object<string, number>} q
 * @returns {number}
 */
function jensenShannonDivergence(p, q) {
  const keys = _.union(Object.keys(p), Object.keys(q));
  const m = {};

  for (const key of keys) {
    m[key] = 0.5 * ((p[key] || 0) + (q[key] || 0));
  }

  let divergence = 0;
  for (const key of keys) {
    divergence += 0.5 * kl(p[key] || 0, m[key]) + 0.5 * kl(q[key] || 0, m[key]);
  }
  return divergence;
}

/* ───────────────────────────────────────────────────── Core Component ─── */
/**
 * Real-Time Drift Monitor
 */
class RealTimeDriftMonitor {
  /**
   * @param {Object}       opts
   * @param {Subject}      opts.inference$          RxJS stream of inference events
   * @param {string}       [opts.baselineFile]     Path to baseline distribution JSON
   * @param {number}       [opts.windowMs]         Sliding buffer window in ms
   * @param {number}       [opts.alertThreshold]   Divergence threshold
   * @param {Kafka}        [opts.kafkaClient]      Optional pre-configured KafkaJS client
   * @param {string}       [opts.kafkaBrokers]     Broker list (comma-separated) if no client
   * @param {string}       [opts.retrainTopic]     Kafka topic to emit retrain events
   */
  constructor(opts = {}) {
    this.inference$ = opts.inference$ ?? new Subject();
    this.windowMs = opts.windowMs ?? DEFAULT_WINDOW_MS;
    this.alertThreshold = opts.alertThreshold ?? DEFAULT_ALERT_THRESHOLD;
    this.retrainTopic = opts.retrainTopic ?? RETRAIN_EVENT_TOPIC;
    this.baselineFile = opts.baselineFile;

    this.kafka =
      opts.kafkaClient ??
      new Kafka({
        clientId: 'agorapulse-drift-monitor',
        brokers: (opts.kafkaBrokers ?? process.env.KAFKA_BROKERS ?? '')
          .split(',')
          .map(b => b.trim())
          .filter(Boolean),
        logLevel: logLevel.NOTHING,
      });

    this.producer = this.kafka.producer({
      allowAutoTopicCreation: false,
    });

    this._baselineDist = null; // will load async
    this._subscription = null;
  }

  /* ───────────────────────────────────────────────────── public API ──── */

  /**
   * Initialize resources (load baseline, connect producer, etc.).
   */
  async init() {
    await Promise.all([this._loadBaseline(), this.producer.connect()]);
    logger.info('RealTimeDriftMonitor initialized');
  }

  /**
   * Start observing the stream; idempotent.
   */
  start() {
    if (this._subscription) {
      logger.warn('Attempted to start monitor twice; ignoring.');
      return;
    }

    this._subscription = this.inference$
      .pipe(
        bufferTime(this.windowMs),
        filter(buffer => buffer.length > 0),
        map(events => this._processWindow(events)),
        filter(Boolean) // only when processWindow returns a drift result
      )
      .subscribe({
        next: driftEvent => this._emitRetrainEvent(driftEvent),
        error: err => logger.error({ err }, 'Drift monitor stream error'),
      });

    logger.info({ windowMs: this.windowMs }, 'Drift monitoring started');
  }

  /**
   * Graceful shutdown.
   */
  async stop() {
    if (this._subscription) {
      this._subscription.unsubscribe();
      this._subscription = null;
    }
    await this.producer.disconnect();
    logger.info('Drift monitor stopped');
  }

  /* ─────────────────────────────────────────────────── internal ────── */

  /**
   * Per-window processing: compute divergence, decide on alert.
   *
   * @param {Array<Object>} events
   * @returns {Object|undefined}   drift result if threshold crossed
   *          { divergence, windowSize, timestamp, currDist }
   */
  _processWindow(events) {
    const currDist = this._distributionFromEvents(events);
    if (!currDist) {
      logger.debug('Insufficient class data in current window');
      return;
    }

    const divergence = jensenShannonDivergence(
      this._baselineDist,
      currDist
    );

    logger.debug(
      { divergence: divergence.toFixed(4), size: events.length },
      'Window evaluated'
    );

    if (divergence >= this.alertThreshold) {
      logger.warn(
        { divergence: divergence.toFixed(4) },
        'Drift threshold exceeded'
      );
      return {
        divergence,
        windowSize: events.length,
        timestamp: Date.now(),
        currDist,
      };
    }
  }

  /**
   * Convert list of events to a normalized class distribution.
   *
   * @param {Array<Object>} events
   * @returns {Object<string,number>}
   */
  _distributionFromEvents(events) {
    const counts = {};
    for (const evt of events) {
      // Prediction can be a class label or array of proba; we simplify.
      const cls = _.isString(evt.prediction)
        ? evt.prediction
        : _.isArray(evt.prediction)
        ? _.maxBy(evt.prediction, 'prob')?.label
        : undefined;
      if (!cls) continue;
      counts[cls] = (counts[cls] || 0) + 1;
    }

    if (_.isEmpty(counts)) return null;
    return normalize(counts);
  }

  /**
   * Publish a drift (retraining) event to Kafka.
   *
   * @param {Object} driftEvent
   */
  async _emitRetrainEvent(driftEvent) {
    const payload = {
      key: `model-drift-${Date.now()}`,
      value: JSON.stringify({
        type: 'MODEL_DRIFT_DETECTED',
        data: {
          divergence: driftEvent.divergence,
          distribution: driftEvent.currDist,
          windowSize: driftEvent.windowSize,
          detectedAt: new Date(driftEvent.timestamp).toISOString(),
        },
      }),
      headers: {
        'content-type': 'application/json',
      },
    };

    try {
      await this.producer.send({
        topic: this.retrainTopic,
        messages: [payload],
        compression: CompressionTypes.GZIP,
      });
      logger.info(
        {
          divergence: driftEvent.divergence.toFixed(4),
          topic: this.retrainTopic,
        },
        'Retrain event emitted'
      );
    } catch (err) {
      logger.error({ err }, 'Failed to emit retrain event');
    }
  }

  /**
   * Load baseline distribution from JSON file.
   */
  async _loadBaseline() {
    if (!this.baselineFile) {
      throw new Error(
        'Baseline distribution file path must be specified for drift monitoring'
      );
    }
    try {
      const raw = await fs.readFile(path.resolve(this.baselineFile), 'utf8');
      const json = JSON.parse(raw);
      this._baselineDist = normalize(json);
      logger.info(
        { baselineFile: this.baselineFile },
        'Baseline distribution loaded'
      );
    } catch (err) {
      logger.error({ err, file: this.baselineFile }, 'Failed to load baseline');
      throw err;
    }
  }
}

/* ───────────────────────────────────────────────────────── Exports ───── */
module.exports = {
  RealTimeDriftMonitor,
  jensenShannonDivergence,
  normalize,
};
```