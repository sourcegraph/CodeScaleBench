/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * Module: src/module_74.js
 *
 * ToxicityMonitor:
 * Continuously watches toxicity–classification results coming back from the
 * model-serving layer.  Using KafkaJS and RxJS it consumes the stream,
 * aggregates a sliding-window metric, and raises an alert when the false-
 * negative rate breaches a configurable tolerance.  Alerts are published to a
 * dedicated Kafka topic and the active model is automatically flagged as
 * “under_review” in the Model Registry via REST.
 *
 * This module is intentionally self-contained: it can be imported and started
 * from a service-bootstrapper or an AWS Lambda handler with:
 *
 *   const { ToxicityMonitor } = require('./module_74');
 *   ToxicityMonitor.start();
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* External dependencies                                                     */
const { Kafka } = require('kafkajs');          // Apache Kafka client
const { timer, Subject } = require('rxjs');    // RxJS primitives
const {
  bufferTime,
  filter,
  map,
  share,
  tap,
} = require('rxjs/operators');
const axios = require('axios');                // HTTP client for Model Registry

/* ────────────────────────────────────────────────────────────────────────── */
/* Internal/shared dependencies                                              */
const logger = require('./utils/logger');      // Project-wide Winston logger
const cfg = require('./config');               // Typed configuration helper

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants                                                                 */
const INPUT_TOPIC = 'agorapulse.results.toxicity';
const ALERT_TOPIC = 'agorapulse.monitoring.alerts';
const WINDOW_MS = cfg.get('monitoring.toxicity.windowMs', 5 * 60 * 1000); // 5 min
const MAX_FN_RATE = cfg.get('monitoring.toxicity.maxFalseNegativeRate', 0.07);

/* ────────────────────────────────────────────────────────────────────────── */
/* Helper utilities                                                          */

/**
 * Parse a KafkaJS message value to JSON.
 * Swallows parsing errors and returns null instead.
 * @param {import('kafkajs').KafkaMessage} message
 * @returns {object|null}
 */
function safeJsonParse(message) {
  try {
    return JSON.parse(message.value.toString('utf8'));
  } catch (err) {
    logger.warn('Failed to JSON parse toxicity result', { error: err });
    return null;
  }
}

/**
 * Signal the Model Registry that the active toxicity model needs review.
 * Uses exponential back-off retries.
 * @param {string} modelVersion
 * @param {number} falseNegativeRate
 * @returns {Promise<void>}
 */
async function flagModelUnderReview(modelVersion, falseNegativeRate) {
  const url = `${cfg.get('registry.baseUrl')}/models/toxicity/${modelVersion}/status`;
  const payload = { status: 'under_review', metric: { falseNegativeRate } };

  for (let attempt = 1; attempt <= 5; attempt++) {
    try {
      await axios.post(url, payload, {
        timeout: 3500,
        headers: { 'X-API-Key': cfg.get('registry.apiKey') },
      });
      logger.info('Model Registry flagged model under review', {
        modelVersion,
        falseNegativeRate,
      });
      return;
    } catch (err) {
      const wait = Math.pow(2, attempt) * 250;
      logger.warn(`Registry call failed (attempt ${attempt})`, {
        wait,
        error: err.toString(),
      });
      await new Promise((r) => setTimeout(r, wait));
    }
  }
  logger.error('Could not flag model under review after max retries', {
    modelVersion,
  });
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Core class                                                                */

class ToxicityMonitor {
  constructor() {
    this._kafka = new Kafka(cfg.get('kafka.brokers'));
    this._consumer = this._kafka.consumer({
      groupId: cfg.get('kafka.groupId', 'agorapulse-toxic-monitor'),
    });
    this._producer = this._kafka.producer();
    this._shutdownRequested = false;

    // RxJS subject we push parsed messages into
    this._stream$ = new Subject();
  }

  /**
   * Connects the Kafka consumer/producer and starts the monitor.
   */
  async start() {
    await Promise.all([this._consumer.connect(), this._producer.connect()]);

    await this._consumer.subscribe({ topic: INPUT_TOPIC, fromBeginning: false });

    // Pipe Kafka messages into the RxJS Subject
    this._consumer.run({
      eachMessage: async ({ message }) => {
        const parsed = safeJsonParse(message);
        if (parsed) this._stream$.next(parsed);
      },
    });

    // Build the Observable pipeline
    this._buildPipeline();

    logger.info('ToxicityMonitor started ✅', {
      inputTopic: INPUT_TOPIC,
      windowMs: WINDOW_MS,
      threshold: MAX_FN_RATE,
    });

    // Handle graceful process shutdown
    process.once('SIGTERM', () => this.stop());
    process.once('SIGINT', () => this.stop());
  }

  /**
   * Creates a sliding-window false-negative metric over the toxicity results
   * stream and triggers side-effects when the threshold is exceeded.
   */
  _buildPipeline() {
    const shared$ = this._stream$.pipe(share());

    // Emits aggregated metric objects every WINDOW_MS
    const metric$ = shared$.pipe(
      bufferTime(WINDOW_MS),
      map((batch) => {
        if (!batch.length) return null;

        const total = batch.length;
        const falseNegatives = batch.filter((r) => r.is_toxic && !r.predicted_toxic)
          .length;
        return {
          windowStart: Date.now() - WINDOW_MS,
          windowEnd: Date.now(),
          total,
          falseNegatives,
          falseNegativeRate: falseNegatives / total,
          modelVersion: batch[0].model_version,
        };
      }),
      filter(Boolean),
    );

    metric$
      .pipe(
        tap((m) => {
          logger.debug('Toxicity metric', m);
        }),
        filter((m) => m.falseNegativeRate >= MAX_FN_RATE),
      )
      .subscribe({
        next: (m) => this._handleThresholdBreach(m),
        error: (err) => logger.error('Metric stream error', { error: err }),
      });
  }

  /**
   * Publishes an alert to Kafka and flags the model in the registry.  Runs both
   * tasks concurrently because neither depends on the other’s success.
   * @param {object} metric
   */
  async _handleThresholdBreach(metric) {
    logger.warn('Toxicity false negatives threshold breached', metric);

    const alertEvent = {
      type: 'TOXICITY_THRESHOLD_BREACH',
      timestamp: Date.now(),
      payload: metric,
    };

    // Fire & forget producer send (errors are logged)
    this._producer
      .send({
        topic: ALERT_TOPIC,
        messages: [{ value: JSON.stringify(alertEvent) }],
      })
      .catch((err) => logger.error('Failed to publish alert event', { err }));

    // Flag model in registry
    flagModelUnderReview(metric.modelVersion, metric.falseNegativeRate).catch(
      (e) => logger.error('Failed to flag model under review', { e }),
    );
  }

  /**
   * Gracefully stops the Kafka consumer/producer and completes the RxJS Subject
   */
  async stop() {
    if (this._shutdownRequested) return;
    this._shutdownRequested = true;

    logger.info('ToxicityMonitor shutting down…');

    try {
      await this._consumer.stop();
      await this._consumer.disconnect();
      await this._producer.disconnect();
      this._stream$.complete();
      logger.info('ToxicityMonitor stopped 🛑');
    } catch (err) {
      logger.error('Error during ToxicityMonitor shutdown', { error: err });
    } finally {
      process.exit(0);
    }
  }
}

/* ────────────────────────────────────────────────────────────────────────── */

module.exports = {
  ToxicityMonitor: new ToxicityMonitor(),
};
