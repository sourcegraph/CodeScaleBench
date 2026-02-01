```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: src/module_55.js
 *
 * Purpose:
 *   Online model-performance & fairness monitor that consumes streaming
 *   prediction events, computes windowed metrics (accuracy, FNR, demographic
 *   parity, etc.), and emits alert events whenever configurable thresholds
 *   are violated.  The module is fully reactive—built on RxJS—and integrates
 *   with Kafka for cross-service notification as well as Prometheus for
 *   observability.
 *
 * Usage:
 *   const monitor = new ModelMonitor(config);
 *   monitor.start();                         // start consuming & evaluating
 *   monitor.ingest(predictionEvent);         // push events from other code
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

'use strict';

/* ────────────────────────────────── Imports ───────────────────────────────── */
const { Subject, timer } = require('rxjs');
const {
  bufferTime,
  filter,
  map,
  mergeMap,
  takeUntil,
  tap,
} = require('rxjs/operators');
const _ = require('lodash');
const { Kafka } = require('kafkajs');
const promClient = require('prom-client');
const winston = require('winston');

/* ──────────────────────────────── Constants ──────────────────────────────── */
const DEFAULT_WINDOW_MS = 60_000;      // 1-minute sliding window
const DEFAULT_MAX_LATENCY_MS = 10_000; // Acceptable event time skew
const DEFAULT_THRESHOLDS = {
  accuracy: 0.85,
  demographicParityDiff: 0.05,
  falseNegativeRateDiff: 0.05,
};

/* ───────────────────────────── Helper Functions ─────────────────────────── */

/**
 * Builds a confusion matrix keyed by demographic group.
 * @param {Array<object>} events - Buffered prediction events.
 * @return {Object<string, ConfusionMatrix>}
 */
function buildConfusionByGroup(events) {
  const groups = _.groupBy(events, (e) => e.attributes.demographic || 'unknown');
  const matrices = {};

  for (const [group, groupEvents] of Object.entries(groups)) {
    const cm = { TP: 0, TN: 0, FP: 0, FN: 0 };
    for (const ev of groupEvents) {
      const { predicted, actual } = ev;
      if (predicted === 1 && actual === 1) cm.TP += 1;
      else if (predicted === 0 && actual === 0) cm.TN += 1;
      else if (predicted === 1 && actual === 0) cm.FP += 1;
      else if (predicted === 0 && actual === 1) cm.FN += 1;
    }
    matrices[group] = cm;
  }

  return matrices;
}

/**
 * Computes accuracy from a confusion matrix.
 * @param {ConfusionMatrix} cm
 */
function accuracy(cm) {
  const total = cm.TP + cm.TN + cm.FP + cm.FN;
  return total === 0 ? 0 : (cm.TP + cm.TN) / total;
}

/**
 * Computes false negative rate from confusion matrix.
 * @param {ConfusionMatrix} cm
 */
function fnr(cm) {
  const positives = cm.TP + cm.FN;
  return positives === 0 ? 0 : cm.FN / positives;
}

/* ───────────────────────────── ModelMonitor ─────────────────────────────── */

/**
 * @typedef {object} MonitorConfig
 * @property {number} [windowMs]                 – Sliding window duration.
 * @property {number} [maxEventLatencyMs]        – Allowed event skew.
 * @property {object} [thresholds]               – Alert thresholds.
 * @property {Array<string>} kafka.brokers       – Kafka brokers list.
 * @property {string} kafka.alertTopic           – Kafka topic for alerts.
 * @property {object} logger                    – Winston logger instance.
 */

/**
 * Realtime model monitoring engine.
 */
class ModelMonitor {
  /**
   * @param {MonitorConfig} userConfig
   */
  constructor(userConfig = {}) {
    /* Merge defaults */
    const {
      windowMs = DEFAULT_WINDOW_MS,
      maxEventLatencyMs = DEFAULT_MAX_LATENCY_MS,
      thresholds = DEFAULT_THRESHOLDS,
      kafka = { brokers: ['kafka:9092'], alertTopic: 'MODEL_MONITORING_ALERT' },
      logger,
    } = userConfig;

    this.config = { windowMs, maxEventLatencyMs, thresholds, kafka };
    this.logger =
      logger ||
      winston.createLogger({
        level: 'info',
        format: winston.format.combine(
          winston.format.timestamp(),
          winston.format.json()
        ),
        transports: [new winston.transports.Console()],
      });

    /* Internal subjects & subscriptions */
    this._ingest$ = new Subject();
    this._stop$ = new Subject();

    /* Kafka producer */
    this.kafka = new Kafka({ brokers: kafka.brokers });
    this.producer = this.kafka.producer({ allowAutoTopicCreation: true });

    /* Prometheus metrics */
    this.metricAccuracy = new promClient.Gauge({
      name: 'agora_model_accuracy',
      help: 'Overall model accuracy (sliding window).',
    });
    this.metricParity = new promClient.Gauge({
      name: 'agora_model_demographic_parity_diff',
      help: 'Absolute difference in accuracy between demographics.',
    });
    this.metricFNRDiff = new promClient.Gauge({
      name: 'agora_model_fnr_diff',
      help: 'Absolute difference in false negative rate between demographics.',
    });
  }

  /**
   * Boots up the reactive pipeline and the Kafka producer.
   */
  async start() {
    await this.producer.connect();
    this.logger.info('ModelMonitor: Kafka producer connected');

    /* Set up processing pipeline */
    this._ingest$
      .pipe(
        /* Filter out events that are too old */
        filter(
          (ev) =>
            Date.now() - ev.timestamp <= this.config.maxEventLatencyMs
        ),
        bufferTime(this.config.windowMs), // sliding window
        filter((batch) => batch.length > 0), // ignore empty windows
        takeUntil(this._stop$),
        mergeMap((batch) => this._evaluateWindow(batch))
      )
      .subscribe({
        next: () => {
          /* noop – handled in _evaluateWindow */
        },
        error: (err) => this.logger.error('Pipeline error', { err }),
        complete: () => this.logger.info('ModelMonitor pipeline stopped'),
      });

    this.logger.info('ModelMonitor started');
  }

  /**
   * Clean shutdown.
   */
  async stop() {
    this._stop$.next(true);
    await this.producer.disconnect();
    this.logger.info('ModelMonitor stopped');
  }

  /**
   * Pushes a single prediction event into the monitor.
   *
   * @param {object} event
   * @param {number} event.timestamp          – Unix epoch millis.
   * @param {number} event.predicted          – Model prediction (1/0).
   * @param {number} event.actual             – Ground truth label (1/0).
   * @param {object} event.attributes         – Arbitrary metadata (e.g. demographic group).
   */
  ingest(event) {
    if (
      !event ||
      typeof event.timestamp !== 'number' ||
      ![0, 1].includes(event.predicted) ||
      ![0, 1].includes(event.actual)
    ) {
      this.logger.warn('Invalid event dropped', { event });
      return;
    }
    this._ingest$.next(event);
  }

  /* ─────────────────────────── Internal Logic ─────────────────────────── */

  /**
   * Evaluate a single window of events, emit metrics & alerts if necessary.
   * @param {Array<object>} batch
   * @private
   */
  async _evaluateWindow(batch) {
    const confusionByGroup = buildConfusionByGroup(batch);
    const groups = Object.keys(confusionByGroup);

    /* Compute overall metrics */
    const overallCM = batch.reduce(
      (agg, ev) => {
        if (ev.predicted === 1 && ev.actual === 1) agg.TP += 1;
        else if (ev.predicted === 0 && ev.actual === 0) agg.TN += 1;
        else if (ev.predicted === 1 && ev.actual === 0) agg.FP += 1;
        else if (ev.predicted === 0 && ev.actual === 1) agg.FN += 1;
        return agg;
      },
      { TP: 0, TN: 0, FP: 0, FN: 0 }
    );

    const overallAccuracy = accuracy(overallCM);

    /* Compute parity & FNR differences  */
    const accuracies = groups.map((g) => accuracy(confusionByGroup[g]));
    const fnrs = groups.map((g) => fnr(confusionByGroup[g]));

    const demographicParityDiff =
      accuracies.length > 0 ? _.max(accuracies) - _.min(accuracies) : 0;

    const fnrDiff = fnrs.length > 0 ? _.max(fnrs) - _.min(fnrs) : 0;

    /* Record metrics */
    this.metricAccuracy.set(overallAccuracy);
    this.metricParity.set(demographicParityDiff);
    this.metricFNRDiff.set(fnrDiff);

    /* Log window summary */
    this.logger.info('ModelMonitor window evaluated', {
      counts: batch.length,
      overallAccuracy,
      demographicParityDiff,
      fnrDiff,
    });

    /* Check & emit alerts */
    const alertPayload = {
      timestamp: Date.now(),
      overallAccuracy,
      demographicParityDiff,
      fnrDiff,
      thresholds: this.config.thresholds,
      violated: {},
    };

    if (overallAccuracy < this.config.thresholds.accuracy) {
      alertPayload.violated.accuracy = overallAccuracy;
    }
    if (demographicParityDiff > this.config.thresholds.demographicParityDiff) {
      alertPayload.violated.demographicParityDiff = demographicParityDiff;
    }
    if (fnrDiff > this.config.thresholds.falseNegativeRateDiff) {
      alertPayload.violated.falseNegativeRateDiff = fnrDiff;
    }

    if (Object.keys(alertPayload.violated).length > 0) {
      await this._emitAlert(alertPayload);
    }
  }

  /**
   * Emit alert both to Kafka and to logs.
   * @param {object} payload
   * @private
   */
  async _emitAlert(payload) {
    this.logger.warn('ModelMonitor threshold violation', payload);

    try {
      await this.producer.send({
        topic: this.config.kafka.alertTopic,
        messages: [{ key: 'ALERT', value: JSON.stringify(payload) }],
      });
    } catch (err) {
      this.logger.error('Failed to publish alert to Kafka', { err, payload });
    }
  }
}

/* ────────────────────────── Export Factory Function ───────────────────────── */

/**
 * Factory utility that returns a ready-to-run instance for convenience.
 * Users can call:
 *     const monitor = require('./module_55').createDefault();
 *     monitor.ingest(...);
 */
function createDefault() {
  const monitor = new ModelMonitor({});
  monitor.start().catch((err) => {
    monitor.logger.error('Failed to start ModelMonitor', { err });
  });
  return monitor;
}

module.exports = {
  ModelMonitor,
  createDefault,
};
```
