```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * SentimentDriftMonitor
 *
 * This module listens to the stream of sentiment-analysis model outputs,
 * computes online statistics over a sliding window, and detects sentiment
 * distribution drifts in real time.  When a statistically significant drift
 * is observed it:
 *
 *   1. Emits a domain-level “model.drift.detected” Kafka event.
 *   2. Exposes Prometheus metrics for alerting.
 *   3. Emits an in-process EventEmitter notification to interested
 *      collaborators (e.g. ModelRegistry, ExperimentTracker).
 *
 * The implementation purposefully avoids heavyweight dependencies so that it
 * can run inside a side-car container adjacent to the model-serving pod.
 *
 * Pattern references:
 *   • Observer Pattern (RxJS + EventEmitter)
 *   • Pipeline Pattern  (RxJS operator chain)
 *   • Factory Pattern   (createSentimentDriftMonitor)
 *
 * Author: AgoraPulse Engineering
 */
'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* External dependencies                                                     */
/* ────────────────────────────────────────────────────────────────────────── */
const { Kafka }           = require('kafkajs');
const { Subject }         = require('rxjs');
const {
  bufferTime,
  filter,
  map,
}                          = require('rxjs/operators');
const {
  Counter,
  Gauge,
  register: promRegister,
}                          = require('prom-client');
const { EventEmitter }     = require('events');
const { mean, std }        = require('lodash');
const debug                = require('debug')('agorapulse:drift-monitor');

/* ────────────────────────────────────────────────────────────────────────── */
/* Configuration                                                             */
/* ────────────────────────────────────────────────────────────────────────── */

const DEFAULT_WINDOW_MS          = 60_000; // 1 minute sliding window
const DEFAULT_THRESHOLD_Z        = 3;      // 3 σ rule
const DEFAULT_MIN_SAMPLES        = 250;    // Minimum messages before testing
const PREDICTION_TOPIC           = process.env.AGORA_PREDICTION_TOPIC || 'model.sentiment.out';
const DRIFT_DETECTED_TOPIC       = process.env.AGORA_DRIFT_TOPIC      || 'model.drift.detected';
const KAFKA_BROKERS              = (process.env.KAFKA_BROKERS || 'localhost:9092').split(',');

/* ────────────────────────────────────────────────────────────────────────── */
/* Prometheus metrics                                                        */
/* ────────────────────────────────────────────────────────────────────────── */
const driftCounter = new Counter({
  name: 'agora_drift_detections_total',
  help: 'Total number of drift events detected.',
  labelNames: ['modelId'],
});

const windowGauge = new Gauge({
  name : 'agora_sentiment_window_size',
  help : 'Number of samples in the current sliding window.',
  labelNames: ['modelId'],
});

/* ----------------------------------------------------------------------------
 * BaselineStore
 * ------------------------------------------------------------------------- */
/**
 * Keeps baseline statistics for each model version in memory.
 */
class BaselineStore {
  constructor() {
    this._store = new Map();
  }

  /**
   * Retrieve baseline statistics for a given modelId. If absent, initializes.
   * @param {string} modelId
   * @returns {{mean:number, std:number}}
   */
  getStats(modelId) {
    if (!this._store.has(modelId)) {
      // Cold start baseline – until enough samples accumulate.
      this._store.set(modelId, { mean: 0, std: 1 });
    }
    return this._store.get(modelId);
  }

  /**
   * Updates baseline with new window statistics using exponential smoothing.
   * @param {string} modelId
   * @param {number} newMean
   * @param {number} newStd
   */
  updateStats(modelId, newMean, newStd) {
    const ALPHA = 0.1; // smoothing factor
    const current = this.getStats(modelId);
    const updated = {
      mean: ALPHA * newMean + (1 - ALPHA) * current.mean,
      std : ALPHA * newStd  + (1 - ALPHA) * current.std,
    };
    this._store.set(modelId, updated);
  }
}

/* ----------------------------------------------------------------------------
 * SentimentDriftMonitor
 * ------------------------------------------------------------------------- */
class SentimentDriftMonitor extends EventEmitter {

  /**
   * @param {object} [options]
   * @param {number} [options.windowMs=60000] – Sliding window size in ms.
   * @param {number} [options.thresholdZ=3]  – Z-score threshold to flag drift.
   * @param {number} [options.minSamples=250] – Minimum window samples required.
   * @param {object} [options.kafkaConfig] – Optional kafkajs client config.
   */
  constructor(options = {}) {
    super();
    this.options        = {
      windowMs    : options.windowMs    || DEFAULT_WINDOW_MS,
      thresholdZ  : options.thresholdZ || DEFAULT_THRESHOLD_Z,
      minSamples  : options.minSamples || DEFAULT_MIN_SAMPLES,
      kafkaConfig : options.kafkaConfig || { brokers: KAFKA_BROKERS },
    };

    this._baselineStore = new BaselineStore();
    this._kafka         = new Kafka(this.options.kafkaConfig);
    this._producer      = this._kafka.producer();
    this._consumer      = this._kafka.consumer({ groupId: 'sentiment-drift-monitor' });

    // The incoming prediction stream
    this._predictions$  = new Subject();

    this._subscriptions = []; // keep track for teardown.
  }

  /* ──────────────────────────────────────────────────────────────────────── */
  /* Public lifecycle methods                                                */
  /* ──────────────────────────────────────────────────────────────────────── */

  /**
   * Connects to Kafka, starts consuming prediction messages, and sets up the
   * RxJS pipeline for drift detection.
   */
  async start() {
    debug('Starting SentimentDriftMonitor...');
    await Promise.all([
      this._producer.connect(),
      this._consumer.connect(),
    ]);

    await this._consumer.subscribe({ topic: PREDICTION_TOPIC, fromBeginning: false });

    this._streamKafkaMessages();
    this._buildPipeline();

    debug(
      'SentimentDriftMonitor ready; consuming %s and emitting drifts to %s',
      PREDICTION_TOPIC,
      DRIFT_DETECTED_TOPIC,
    );
  }

  /**
   * Gracefully shuts down Kafka connections and RxJS subscriptions.
   */
  async stop() {
    debug('Stopping SentimentDriftMonitor...');
    await Promise.allSettled([
      this._consumer.disconnect(),
      this._producer.disconnect(),
    ]);
    this._subscriptions.forEach((sub) => sub.unsubscribe());
    this._predictions$.complete();
  }

  /* ──────────────────────────────────────────────────────────────────────── */
  /* Private helpers                                                         */
  /* ──────────────────────────────────────────────────────────────────────── */

  _streamKafkaMessages() {
    // Forward Kafka messages into the RxJS Subject
    this._consumer.run({
      eachMessage: async ({ message }) => {
        try {
          const payload = JSON.parse(message.value.toString());
          /**
           * Expected payload:
           *   { modelId: string, timestamp: number, score: number }
           */
          if (
            typeof payload.score === 'number' &&
            typeof payload.modelId === 'string'
          ) {
            this._predictions$.next(payload);
          }
        } catch (err) {
          debug('Non-fatal: Failed to parse message – %O', err);
        }
      },
    })
    .catch((err) => {
      // Fatal connection error – bubble up
      this.emit('error', err);
    });
  }

  /**
   * Builds the reactive pipeline responsible for buffering, computing
   * statistics, and signaling drift events.
   */
  _buildPipeline() {
    const sub = this._predictions$
      .pipe(
        // group predictions in sliding time windows
        bufferTime(this.options.windowMs),
        // discard empty buffers
        filter((batch) => batch.length > 0),
        // compute stats per model
        map((batch) => {
          const byModel = batch.reduce((acc, cur) => {
            (acc[cur.modelId] = acc[cur.modelId] || []).push(cur);
            return acc;
          }, {});

          return Object.entries(byModel).map(([modelId, samples]) => ({
            modelId,
            samples,
            meanScore: mean(samples.map((s) => s.score)),
            stdDev   : std(samples.map((s) => s.score)) || 0.0001, // prevent division by zero
          }));
        }),
        // flatten arrays
        map((arr) => arr.flat()),
      )
      .subscribe({
        next  : (modelStatsArray) => {
          modelStatsArray.forEach((stats) => this._evaluateDrift(stats));
        },
        error : (err) => this.emit('error', err),
      });

    this._subscriptions.push(sub);
  }

  /**
   * Evaluates a single model's statistics versus its baseline.
   * @param {{modelId:string, samples:object[], meanScore:number, stdDev:number}} stats
   * @private
   */
  async _evaluateDrift(stats) {
    const { modelId, meanScore, stdDev, samples } = stats;
    const windowSize = samples.length;

    windowGauge.labels(modelId).set(windowSize);

    // Require minimum sample count
    if (windowSize < this.options.minSamples) {
      debug('Insufficient samples for %s – need %d, have %d',
        modelId, this.options.minSamples, windowSize);
      return;
    }

    const baseline = this._baselineStore.getStats(modelId);
    const zScore   = Math.abs((meanScore - baseline.mean) / (baseline.std || 1));

    debug('Model %s – µ %.3f (baseline %.3f) σ %.3f, z=%.2f',
      modelId, meanScore, baseline.mean, baseline.std, zScore);

    if (zScore >= this.options.thresholdZ) {
      // Drift detected!
      await this._handleDrift(modelId, { meanScore, stdDev, windowSize, zScore });
    } else {
      // Update rolling baseline.
      this._baselineStore.updateStats(modelId, meanScore, stdDev);
    }
  }

  /**
   * Handles drift detection side-effects.
   * @param {string} modelId
   * @param {object} details
   * @private
   */
  async _handleDrift(modelId, details) {
    driftCounter.labels(modelId).inc();

    const eventPayload = {
      eventType : 'model.drift.detected',
      modelId,
      timestamp : Date.now(),
      details,
    };

    debug('Drift detected for %s – publishing event %O', modelId, details);

    // Fire Kafka event
    await this._producer.send({
      topic: DRIFT_DETECTED_TOPIC,
      messages: [
        { key: modelId, value: JSON.stringify(eventPayload) },
      ],
    }).catch((err) => {
      debug('Failed to publish drift event – %O', err);
    });

    // Notify in-process subscribers
    this.emit('drift', eventPayload);
  }

  /* ──────────────────────────────────────────────────────────────────────── */
  /* Introspection                                                            */
  /* ──────────────────────────────────────────────────────────────────────── */

  /**
   * Returns current Prometheus metrics as a formatted string.
   * Useful for shipping via /metrics HTTP endpoint.
   */
  async metrics() {
    return promRegister.metrics();
  }
}

/* ----------------------------------------------------------------------------
 * Factory
 * ------------------------------------------------------------------------- */
/**
 * Factory function so callers need not know the constructor signature.
 * @param {object} [config]
 * @returns {SentimentDriftMonitor}
 */
function createSentimentDriftMonitor(config) {
  return new SentimentDriftMonitor(config);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Exports                                                                   */
/* ────────────────────────────────────────────────────────────────────────── */
module.exports = {
  createSentimentDriftMonitor,
  SentimentDriftMonitor,
};
```