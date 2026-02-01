```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -----------------------------------------------
 * src/module_5.js
 *
 * This module implements real-time model-monitoring logic that listens to a
 * stream of prediction feedback events, computes quality / fairness metrics in
 * sliding windows, and emits a “MODEL_RETRAINING_NEEDED” domain event through
 * Kafka when user-configured thresholds are violated.
 *
 * Design notes:
 *  • RxJS is used for reactive windowing & aggregation.
 *  • kafkajs is used for broker communication (shared client across the app).
 *  • pino provides structured JSON logging compatible with the global logger.
 *  • Metric calculations are intentionally simple but easily swappable via DI
 *    (Strategy pattern) for more sophisticated estimators.
 *
 * The module can be required or ESM-imported:
 *    const { ModelMonitor } = require('./module_5');
 * or
 *    import { ModelMonitor } from './module_5.js';
 *
 * Copyright AgoraPulse ©
 */

"use strict";

// -------------------- Imports & Type Declarations ---------------------------

const { Kafka }              = require("kafkajs");
const { Subject, timer }     = require("rxjs");
const { bufferTime, filter } = require("rxjs/operators");
const pino                   = require("pino");
const _                      = require("lodash");

// ------------------------------ Constants -----------------------------------

/**
 * Default monitoring configuration. These can be overridden by providing a
 * custom config object to the ModelMonitor constructor.
 */
const DEFAULT_CONFIG = {
  // Sliding-window length in milliseconds (e.g. 5 min).
  windowMs: 5 * 60 * 1000,

  // How often we evaluate the buffered events (e.g. every 30 seconds).
  evaluationFrequencyMs: 30 * 1000,

  // Quality & fairness thresholds.
  thresholds: {
    accuracy:              0.87,
    toxicityFalseNegative: 0.03,   // ≤ 3 % false-negatives on toxic content.
    demographicParityDiff: 0.08,   // ≤ 8 % for demographic parity.
  },

  // Kafka topic to publish retraining requests.
  retrainingTopic: "ml.model.retraining_requests",

  // Lumped key so that all events for the same modelVersion end up
  // in the same partition (sticky-keyed by default).
  kafkaKeySelector: (event) => event.modelVersion,
};

// --------------------------------- Errors -----------------------------------

class MonitoringError extends Error {
  constructor(message, meta) {
    super(message);
    this.name  = "MonitoringError";
    this.meta  = meta;
    Error.captureStackTrace(this, this.constructor);
  }
}

// --------------------------- Helper / Utility Fns ---------------------------

/**
 * Calculates classic classification accuracy.
 */
function accuracy(events) {
  const valid = events.filter((e) => _.isBoolean(e.correct));
  if (valid.length === 0) return NaN;
  const correct = valid.filter((e) => e.correct === true).length;
  return correct / valid.length;
}

/**
 * Calculates toxicity false-negative rate.
 */
function toxicityFalseNegativeRate(events) {
  const toxicGroundTruth = events.filter(
    (e) => e.groundTruthLabel === "toxic"
  );
  if (toxicGroundTruth.length === 0) return NaN;
  const falseNegatives = toxicGroundTruth.filter(
    (e) => e.predictedLabel !== "toxic"
  ).length;
  return falseNegatives / toxicGroundTruth.length;
}

/**
 * Calculates simple demographic-parity difference:
 *     | P(pred=positive | subgroup=A) − P(pred=positive | subgroup=B) |
 * Supports binary sensitive attribute for simplicity.
 */
function demographicParityDiff(events) {
  const byGroup = _.groupBy(events, (e) => e.demographic);
  const groups  = Object.keys(byGroup);
  if (groups.length < 2) return 0; // trivially satisfied.

  const positiveRate = (arr) =>
    _.meanBy(arr, (e) => (e.predictedLabel === "positive" ? 1 : 0));

  const pairs = _.flatMap(groups, (g1, idx) =>
    groups.slice(idx + 1).map((g2) => Math.abs(
      positiveRate(byGroup[g1]) - positiveRate(byGroup[g2])
    ))
  );

  return _.max(pairs); // worst-case pairwise disparity.
}

// ------------------------------ Main Class ----------------------------------

class ModelMonitor {
  /**
   * @param {Object}   opts
   * @param {Object}   opts.kafka      – Pre-configured kafkajs client { brokers }.
   * @param {Object}   [opts.config]   – Monitoring config overrides.
   * @param {pino.Logger} [opts.logger]– Pino instance (child logger created if omitted).
   */
  constructor({ kafka, config = {}, logger = pino() }) {
    if (!kafka || !(kafka instanceof Kafka)) {
      throw new MonitoringError("A pre-configured kafkajs client must be provided.");
    }

    this.config  = _.merge({}, DEFAULT_CONFIG, config);
    this.logger  = logger.child({ module: "ModelMonitor" });
    this.kafka   = kafka;
    this.producer = this.kafka.producer({ allowAutoTopicCreation: false });

    // Subject for incoming events
    this._incoming$ = new Subject();

    // Ensure we only call connect once the user attaches.
    this._connected = false;

    // Bind internal methods
    this._handleWindow      = this._handleWindow.bind(this);
    this._emitRetrainEvent  = this._emitRetrainEvent.bind(this);
  }

  /**
   * Initialize the Kafka producer connection.
   */
  async _ensureProducer() {
    if (!this._connected) {
      await this.producer.connect();
      this._connected = true;
      this.logger.info("Kafka producer connected.");
    }
  }

  /**
   * Start monitoring.
   */
  start() {
    // Wire up windowed evaluation with RxJS.
    this._subscription = this._incoming$
      .pipe(
        bufferTime(this.config.windowMs, this.config.evaluationFrequencyMs),
        filter((events) => events.length > 0)
      )
      .subscribe(this._handleWindow);

    this.logger.info({
      msg:    "ModelMonitor started.",
      config: this.config,
    });
  }

  /**
   * Stop monitoring gracefully.
   */
  async stop() {
    if (this._subscription) {
      this._subscription.unsubscribe();
    }
    if (this._connected) {
      await this.producer.disconnect();
    }
    this.logger.info("ModelMonitor stopped.");
  }

  /**
   * Push a single feedback event onto the stream.
   * @param {Object} event – See README for exact schema.
   */
  ingest(event) {
    // Basic schema sanity check to avoid unexpected undefined access.
    if (!event || typeof event.modelVersion !== "string") {
      this.logger.warn({ event }, "Skipping invalid monitoring event.");
      return;
    }
    this._incoming$.next(event);
  }

  // ------------------------- Internal Handlers ------------------------------

  /**
   * Compute metrics & evaluate thresholds for a window of events.
   * @private
   */
  async _handleWindow(events) {
    const windowStats = {
      count:                 events.length,
      accuracy:              accuracy(events),
      toxicityFalseNegative: toxicityFalseNegativeRate(events),
      demographicParityDiff: demographicParityDiff(events),
      modelVersion:          _.get(_.head(events), "modelVersion", "unknown"),
      timeRange:             {
        start: _.first(events).timestamp,
        end:   _.last(events).timestamp,
      },
    };

    this.logger.debug({ windowStats }, "Evaluated monitoring window.");

    const breached = this._evaluateThresholds(windowStats);
    if (breached) {
      try {
        await this._ensureProducer();
        await this._emitRetrainEvent(windowStats);
      } catch (err) {
        // Logging but do not throw so that monitoring continues.
        this.logger.error({ err, windowStats }, "Failed to emit retraining event.");
      }
    }
  }

  /**
   * Check calculated metrics against configured thresholds.
   * @private
   * @returns {Boolean} Whether any threshold was violated.
   */
  _evaluateThresholds(stats) {
    const t = this.config.thresholds;

    const violations = {
      accuracy:              stats.accuracy < t.accuracy,
      toxicityFalseNegative: stats.toxicityFalseNegative > t.toxicityFalseNegative,
      demographicParityDiff: stats.demographicParityDiff > t.demographicParityDiff,
    };

    const breached = Object.values(violations).some(Boolean);
    if (breached) {
      this.logger.warn({ stats, violations }, "Thresholds breached.");
    }

    return breached;
  }

  /**
   * Publish a retraining request event to Kafka.
   * @private
   */
  async _emitRetrainEvent(stats) {
    const payload = {
      eventType:   "MODEL_RETRAINING_NEEDED",
      modelId:     stats.modelVersion,
      triggeredAt: new Date().toISOString(),
      reason:      "metric_threshold_breach",
      metrics:     _.pick(stats, [
        "accuracy",
        "toxicityFalseNegative",
        "demographicParityDiff",
      ]),
      window:      stats.timeRange,
    };

    await this.producer.send({
      topic: this.config.retrainingTopic,
      messages: [
        {
          key:   this.config.kafkaKeySelector(payload),
          value: JSON.stringify(payload),
          headers: {
            "content-type": "application/json",
            "x-event-id":   _.uniqueId("retrain_"),
          },
        },
      ],
    });

    this.logger.info({ payload }, "Retraining event emitted to Kafka.");
  }
}

// ---------------------------- Factory Helper --------------------------------

/**
 * Convenience helper that wires up a fully-configured ModelMonitor instance
 * based on a minimal set of environment variables. In larger contexts this
 * would live in a dedicated IoC container, but is kept here for portability.
 */
async function createDefaultModelMonitor() {
  const kafka = new Kafka({
    brokers: (process.env.KAFKA_BROKERS || "localhost:9092").split(","),
    clientId: process.env.KAFKA_CLIENT_ID || "agorapulse-model-monitor",
  });

  const monitor = new ModelMonitor({
    kafka,
    logger: pino({ level: process.env.LOG_LEVEL || "info" }),
  });

  monitor.start();
  await monitor._ensureProducer();

  return monitor;
}

// ------------------------------ Exports -------------------------------------

module.exports = {
  ModelMonitor,
  createDefaultModelMonitor,
  MonitoringError,
};
```