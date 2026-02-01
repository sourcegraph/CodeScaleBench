```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * =================================================
 * Module: SentimentDriftMonitor
 * File:   src/module_70.js
 *
 * Purpose:
 * --------
 *  Watches the real-time sentiment-analysis topic, maintains a rolling
 *  baseline sentiment distribution, and continuously compares the most
 *  recent statistics against that baseline.  When a statistically
 *  significant divergence is detected, it:
 *
 *    • Emits a local EventEmitter event ("drift")
 *    • Produces an event to a Kafka topic for downstream services
 *    • Notifies the Model-Registry/Monitoring API
 *    • Publishes Prometheus metrics
 *
 *  This module demonstrates 100% event-driven operation, tight Kafka/RxJS
 *  integration, defensive error-handling, and production-grade observability.
 *
 * Dependencies:
 *  • kafkajs        – Kafka client
 *  • rxjs           – Reactive stream composition
 *  • lodash         – Utility helpers
 *  • prom-client    – Prometheus instrumentation
 *  • axios          – HTTP calls to external services
 */

'use strict';

const { Kafka } = require('kafkajs');
const { Subject, timer } = require('rxjs');
const { bufferTime, filter } = require('rxjs/operators');
const _ = require('lodash');
const axios = require('axios');
const EventEmitter = require('events');
const promClient = require('prom-client');

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

/**
 * Compute discrete probability distribution for an array of categorical labels.
 * @param {string[]} labels
 * @return {Record<string, number>} Probabilities summing to 1.0
 */
function makeDistribution(labels) {
  const counts = _.countBy(labels);
  const total = labels.length || 1;
  return _.mapValues(counts, c => c / total);
}

/**
 * Jensen–Shannon divergence (symmetric, smoothed) for two discrete
 * probability distributions expressed as objects of the same keys.
 * Returned value in [0, 1]. 0 => identical, 1 => maximally different.
 *
 * @param {Record<string, number>} p
 * @param {Record<string, number>} q
 * @returns {number}
 */
function jsDivergence(p, q) {
  const keys = _.union(Object.keys(p), Object.keys(q));
  const m = {};
  keys.forEach(k => {
    m[k] = 0.5 * ((p[k] || 0) + (q[k] || 0));
  });

  const kl = (a, b) =>
    _.sum(
      keys.map(k => {
        const ak = a[k] || 0;
        const bk = b[k] || 0;
        return ak === 0 ? 0 : ak * Math.log2(ak / bk);
      }),
    );

  const js = 0.5 * (kl(p, m) + kl(q, m));

  // Normalise against log2(2) to bound within [0, 1].
  return Math.min(1, js);
}

// ---------------------------------------------------------------------------
// Prometheus instrumentation
// ---------------------------------------------------------------------------

const divergenceGauge = new promClient.Gauge({
  name: 'agorapulse_sentiment_drift_divergence',
  help: 'Latest Jensen-Shannon divergence between rolling window and baseline',
});

const driftCounter = new promClient.Counter({
  name: 'agorapulse_sentiment_drift_events_total',
  help: 'Total number of drift events emitted',
});

const messageCounter = new promClient.Counter({
  name: 'agorapulse_sentiment_messages_consumed_total',
  help: 'Total sentiment messages consumed',
});

// ---------------------------------------------------------------------------
// Core class
// ---------------------------------------------------------------------------

class SentimentDriftMonitor extends EventEmitter {
  /**
   * @param {Object} options
   * @param {string[]} options.brokers Kafka brokers
   * @param {string}   options.inputTopic Topic that carries sentiment results
   * @param {string}   options.driftTopic Topic to publish drift events to
   * @param {number}   [options.baselineWindow=60000] Baseline window (ms)
   * @param {number}   [options.detectionWindow=10000] Detection window (ms)
   * @param {number}   [options.driftThreshold=0.15] JS-Divergence threshold
   * @param {string}   [options.registryEndpoint] HTTP endpoint for alerts
   * @param {number}   [options.httpTimeout=3000] Timeout for external calls (ms)
   */
  constructor(options) {
    super();

    this.config = Object.freeze({
      baselineWindow: 60_000,
      detectionWindow: 10_000,
      driftThreshold: 0.15,
      httpTimeout: 3_000,
      ...options,
    });

    this.kafka = new Kafka({ clientId: 'sentiment-drift-monitor', brokers: this.config.brokers });
    this.consumer = this.kafka.consumer({ groupId: 'sentiment-drift-consumer' });
    this.producer = this.kafka.producer();

    this._stream$ = new Subject();
    this._baselineDist = null;
    this._isRunning = false;

    // Bind this for callback safety
    this._handleKafkaMessage = this._handleKafkaMessage.bind(this);
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  /**
   * Start consuming Kafka messages & monitoring drift.
   */
  async start() {
    if (this._isRunning) return;
    this._isRunning = true;

    await Promise.all([this.consumer.connect(), this.producer.connect()]);
    await this.consumer.subscribe({ topic: this.config.inputTopic, fromBeginning: false });

    await this.consumer.run({
      eachMessage: async ({ message }) => {
        try {
          this._handleKafkaMessage(message);
        } catch (err) {
          // Surface errors but continue processing
          this.emit('error', err);
        }
      },
    });

    // Kick off RxJS window pipelines
    this._setupWindows();
  }

  /**
   * Stop consuming and disconnect from Kafka.
   */
  async stop() {
    if (!this._isRunning) return;
    this._isRunning = false;

    await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
    this._stream$.complete();
  }

  // -------------------------------------------------------------------------
  // Internal helpers
  // -------------------------------------------------------------------------

  /**
   * Forward Kafka messages into RxJS stream with minimal parsing.
   * @param {import('kafkajs').KafkaMessage} message
   * @private
   */
  _handleKafkaMessage(message) {
    messageCounter.inc();

    const payload = JSON.parse(message.value.toString('utf8'));
    // Expect the analyser to emit { sentiment: "positive"|"negative"|"neutral", ... }
    const label = _.get(payload, 'sentiment');
    if (!label) return;

    this._stream$.next(label);
  }

  /**
   * Wire up two overlapping RxJS buffers:
   * 1. Baseline – large window used as reference distribution
   * 2. Detection – small window compared against baseline
   *
   * Emits drift events whenever JS divergence exceeds configured threshold.
   * @private
   */
  _setupWindows() {
    const {
      baselineWindow,
      detectionWindow,
      driftThreshold,
      driftTopic,
      registryEndpoint,
      httpTimeout,
    } = this.config;

    // Baseline window: emits only the latest distribution
    this._stream$
      .pipe(bufferTime(baselineWindow))
      .pipe(filter(batch => batch.length > 0))
      .subscribe({
        next: batch => {
          this._baselineDist = makeDistribution(batch);
        },
        error: err => this.emit('error', err),
      });

    // Detection window: compare against current baseline
    this._stream$
      .pipe(bufferTime(detectionWindow))
      .pipe(filter(batch => batch.length > 0))
      .subscribe({
        next: async batch => {
          if (!this._baselineDist) {
            // Not enough data to build baseline yet
            return;
          }

          const dist = makeDistribution(batch);
          const divergence = jsDivergence(this._baselineDist, dist);
          divergenceGauge.set(divergence);

          if (divergence >= driftThreshold) {
            // Record metrics first for reliability
            driftCounter.inc();

            const driftEvent = {
              id: _.uniqueId('drift_'),
              timestamp: Date.now(),
              divergence,
              baselineWindowMs: baselineWindow,
              detectionWindowMs: detectionWindow,
              baselineDistribution: this._baselineDist,
              currentDistribution: dist,
            };

            // Fire local event (e.g., UI dashboard or other in-process subscribers)
            this.emit('drift', driftEvent);

            // Kafka: non-blocking fire-and-forget
            this.producer
              .send({
                topic: driftTopic,
                messages: [{ key: driftEvent.id, value: JSON.stringify(driftEvent) }],
              })
              .catch(err => {
                // Log but swallow to avoid cascading failures
                this.emit('error', err);
              });

            // Hit monitoring/registry endpoint (optional, best-effort)
            if (registryEndpoint) {
              axios
                .post(registryEndpoint, driftEvent, { timeout: httpTimeout })
                .catch(err => {
                  this.emit('error', new Error(`Registry call failed: ${err.message}`));
                });
            }
          }
        },
        error: err => this.emit('error', err),
      });

    // Health-check: emit heartbeat for observability
    timer(0, 30_000).subscribe(() => this.emit('heartbeat', { ts: Date.now() }));
  }
}

// ---------------------------------------------------------------------------
// Factory helper (Factory Pattern) – returns a ready-to-use monitor instance.
// ---------------------------------------------------------------------------

/**
 * Create and start a SentimentDriftMonitor with sane defaults.
 * Usage:
 *   const monitor = await createSentimentDriftMonitor({...});
 *   monitor.on('drift', evt => console.log('Drift detected!', evt));
 *
 * @param {Partial<ConstructorParameters<typeof SentimentDriftMonitor>[0]>} cfg
 * @return {Promise<SentimentDriftMonitor>}
 */
async function createSentimentDriftMonitor(cfg) {
  const defaults = {
    brokers: ['localhost:9092'],
    inputTopic: 'agorapulse.sentiment.raw',
    driftTopic: 'agorapulse.drift.events',
    registryEndpoint: process.env.REGISTRY_ENDPOINT,
  };

  const monitor = new SentimentDriftMonitor({ ...defaults, ...cfg });
  await monitor.start();
  return monitor;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

module.exports = {
  SentimentDriftMonitor,
  createSentimentDriftMonitor,
  // Utilities exported for unit testing
  _private: { jsDivergence, makeDistribution },
};
```