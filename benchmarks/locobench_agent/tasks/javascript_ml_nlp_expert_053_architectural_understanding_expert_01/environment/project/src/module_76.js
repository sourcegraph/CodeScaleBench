```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: src/module_76.js
 *
 * Description:
 *  Real-Time Model Monitoring service that listens to inference-outcome events
 *  from Kafka, aggregates them in sliding time windows using RxJS, detects
 *  fairness / performance regressions, and emits structured alert events.
 *
 *  This module is meant to be embedded in a long-running Node.js worker (e.g.,
 *  inside a Kubernetes pod) and can be controlled programmatically or via
 *  process signals.
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* Dependencies                                                              */
/* ────────────────────────────────────────────────────────────────────────── */
const { Kafka, logLevel } = require('kafkajs');
const { Subject, timer } = require('rxjs');
const { bufferTime, filter, map } = require('rxjs/operators');
const EventEmitter = require('events');
const _ = require('lodash');
const Pino = require('pino');
const Ajv = require('ajv');

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants                                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

const DEFAULT_WINDOW_MS = 30_000;           // 30-second sliding window
const DEFAULT_GRACE_MS  = 5_000;            // wait before shutdown EXIT
const DEFAULT_THRESHOLDS = {
  falseNegativeRate: 0.20,                  // 20 %
  fairnessDiff:      0.10                   // 10 % absolute diff between groups
};

const OUTCOME_MESSAGE_SCHEMA = {
  $id:          'agorapulse.outcome.message',
  type:         'object',
  required:     [ 'modelId', 'version', 'prediction', 'label', 'group', 'timestamp' ],
  additionalProperties: false,
  properties: {
    modelId:     { type: 'string' },
    version:     { type: 'string' },
    prediction:  { type: 'integer', enum: [ 0, 1 ] },  // 1 = toxic
    label:       { type: 'integer', enum: [ 0, 1 ] },  // 1 = toxic
    group:       { type: 'string' },                   // protected group (e.g., locale/language)
    timestamp:   { type: 'integer' }                   // epoch ms
  }
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Logger                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

const logger = Pino({
  name: 'ModelMonitoringService',
  level: process.env.LOG_LEVEL || 'info',
  mixin() {
    return { service: 'model-monitoring' };
  }
});

/* ────────────────────────────────────────────────────────────────────────── */
/* Helper utilities                                                          */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Compute false-negative rate (FNR) for a set of outcome records.
 * FNR = FN / (FN + TP) where:
 *   FN – toxic comments predicted as non-toxic
 *   TP – toxic comments predicted correctly
 *
 * @param {Object[]} rows
 * @returns {number} rate between 0-1
 */
function computeFalseNegativeRate(rows) {
  const fn = rows.filter(r => r.label === 1 && r.prediction === 0).length;
  const tp = rows.filter(r => r.label === 1 && r.prediction === 1).length;
  const denom = fn + tp;
  return denom === 0 ? 0 : fn / denom;
}

/**
 * Compute per-group rates and compare against global rate.
 * Returns absolute difference between worst group and global.
 *
 * @param {Object[]} rows
 * @param {Function} metricFn
 * @returns {number} absolute diff
 */
function computeFairnessDiff(rows, metricFn) {
  if (rows.length === 0) return 0;
  const globalRate = metricFn(rows);
  const groups = _.groupBy(rows, 'group');
  const worstGroupRate = _.max(_.map(groups, metricFn));
  return Math.abs(worstGroupRate - globalRate);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* ModelMonitoringService                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Real-time Model Monitoring with windowed aggregation and drift detection.
 * Emits events:
 *   - 'metrics' -> { modelId, version, windowStart, windowEnd, metrics }
 *   - 'alert'   -> { modelId, version, metric, value, threshold, windowEnd }
 */
class ModelMonitoringService extends EventEmitter {

  /**
   * @param {Object} options
   * @param {Object} options.kafka                 Kafka connection options
   * @param {string} options.inferenceTopic        Kafka topic with outcomes
   * @param {string} [options.alertTopic]          Optional topic for alerts
   * @param {Object} [options.thresholds]          Alert thresholds
   * @param {number} [options.windowMs]            Aggregation window in ms
   * @param {Object} [options.logger]              Pino-style logger
   */
  constructor(options) {
    super();
    this._assertOptions(options);

    this.kafkaConfig      = options.kafka;
    this.inferenceTopic   = options.inferenceTopic;
    this.alertTopic       = options.alertTopic || null;
    this.thresholds       = _.defaults(options.thresholds, DEFAULT_THRESHOLDS);
    this.windowMs         = options.windowMs || DEFAULT_WINDOW_MS;
    this.logger           = options.logger || logger;

    this._ajv        = new Ajv({ useDefaults: true });
    this._validateFn = this._ajv.compile(OUTCOME_MESSAGE_SCHEMA);

    this._consumer   = null;
    this._producer   = null;
    this._msg$       = new Subject();
    this._subscriptions = [];
  }

  /* ─────────────────────── Public API ─────────────────────── */

  /**
   * Bootstrap Kafka connections and start streaming.
   */
  async start() {
    if (this._consumer) {
      this.logger.warn('Monitoring service already started');
      return;
    }

    const kafka = new Kafka({
      clientId:  'agorapulse-monitor',
      brokers:   this.kafkaConfig.brokers,
      ssl:       this.kafkaConfig.ssl,
      sasl:      this.kafkaConfig.sasl,
      logLevel:  logLevel.ERROR
    });

    this._consumer = kafka.consumer({ groupId: `monitor-${Date.now()}` });
    this._producer = kafka.producer();

    await Promise.all([
      this._consumer.connect(),
      this._producer.connect()
    ]);

    await this._consumer.subscribe({ topic: this.inferenceTopic, fromBeginning: false });

    this._consumer.run({
      autoCommit: true,
      eachMessage: async ({ topic, partition, message }) => {
        try {
          const payload = JSON.parse(message.value.toString());
          if (!this._validateFn(payload)) {
            this.logger.warn(
              { errors: this._validateFn.errors, payload },
              'Dropped malformed message'
            );
            return;
          }
          this._msg$.next(payload);
        } catch (err) {
          this.logger.error(err, 'Failed to process Kafka message');
        }
      }
    });

    this._initAggregation();

    this.logger.info('ModelMonitoringService started');
  }

  /**
   * Flush and close all resources.
   */
  async stop() {
    if (!this._consumer) return;

    this._subscriptions.forEach(sub => sub.unsubscribe());
    this._subscriptions.length = 0;

    await Promise.allSettled([
      this._consumer.disconnect(),
      this._producer.disconnect()
    ]);

    // Give any in-flight timer/IO a chance to settle
    await new Promise(res => setTimeout(res, DEFAULT_GRACE_MS));

    this._consumer = null;
    this._producer = null;

    this.logger.info('ModelMonitoringService stopped');
  }

  /* ─────────────────────── Internals ─────────────────────── */

  _initAggregation() {
    // Buffer incoming messages in a time-based window
    const sub = this._msg$
      .pipe(
        bufferTime(this.windowMs),
        filter(buffer => buffer.length > 0),
        map(buffer => _.groupBy(buffer, r => `${r.modelId}::${r.version}`))
      )
      .subscribe(grouped => {
        const windowEnd = Date.now();
        const windowStart = windowEnd - this.windowMs;

        _.forEach(grouped, (rows, key) => {
          const [modelId, version] = key.split('::');

          const fnr   = computeFalseNegativeRate(rows);
          const diff  = computeFairnessDiff(rows, computeFalseNegativeRate);

          const metrics = {
            falseNegativeRate: fnr,
            fairnessDiff:      diff,
            sampleSize:        rows.length
          };

          this.emit('metrics', { modelId, version, windowStart, windowEnd, metrics });

          // Evaluate thresholds
          this._maybeAlert({ modelId, version, windowEnd, metrics });
        });
      });

    this._subscriptions.push(sub);
  }

  /**
   * Check metrics against thresholds and emit/produce alerts.
   *
   * @param {Object} ctx
   * @private
   */
  async _maybeAlert({ modelId, version, windowEnd, metrics }) {
    const alerts = [];

    if (metrics.falseNegativeRate > this.thresholds.falseNegativeRate) {
      alerts.push({
        metric:     'falseNegativeRate',
        value:      metrics.falseNegativeRate,
        threshold:  this.thresholds.falseNegativeRate
      });
    }

    if (metrics.fairnessDiff > this.thresholds.fairnessDiff) {
      alerts.push({
        metric:     'fairnessDiff',
        value:      metrics.fairnessDiff,
        threshold:  this.thresholds.fairnessDiff
      });
    }

    for (const alert of alerts) {
      const alertEvent = {
        modelId,
        version,
        windowEnd,
        ...alert
      };

      this.emit('alert', alertEvent);

      if (this.alertTopic) {
        try {
          await this._producer.send({
            topic: this.alertTopic,
            messages: [
              {
                key: `${modelId}-${version}-${alert.metric}`,
                value: JSON.stringify(alertEvent)
              }
            ]
          });
        } catch (err) {
          this.logger.error(err, 'Failed to publish alert to Kafka');
        }
      }
    }
  }

  /**
   * Validate constructor options.
   * @param {Object} opts
   * @private
   */
  _assertOptions(opts) {
    if (!opts || typeof opts !== 'object') {
      throw new TypeError('Options must be an object');
    }
    if (!opts.kafka || !Array.isArray(opts.kafka.brokers)) {
      throw new Error('Kafka configuration with "brokers" array is required');
    }
    if (!opts.inferenceTopic) {
      throw new Error('"inferenceTopic" is required');
    }
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Exported factory                                                          */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Factory function that returns a started MonitoringService.
 *
 * @param {Object} options   – see ModelMonitoringService constructor
 * @returns {Promise<ModelMonitoringService>}
 */
async function createMonitoringService(options) {
  const svc = new ModelMonitoringService(options);
  await svc.start();
  return svc;
}

module.exports = {
  ModelMonitoringService,
  createMonitoringService
};
```