```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence – Sentiment Drift Monitor
 * ------------------------------------------------------------------------
 * File:        src/module_56.js
 * Description: Monitors real-time sentiment scores produced by downstream
 *              model-serving pipelines.  When the rolling average sentiment
 *              drifts beyond a configurable threshold, an alert domain event
 *              is emitted to Kafka – which in turn can trigger automated
 *              retraining or human review workflows.
 *
 * Author:      AgoraPulse Engineering
 * Copyright:   (c) 2024 AgoraPulse
 * License:     MIT
 */

'use strict';

/* ──────────────────────────────────────────────────────────────────────────
 * External Dependencies
 * ──────────────────────────────────────────────────────────────────────── */
const { Kafka, logLevel } = require('kafkajs');   // Kafka client
const { Subject, timer }  = require('rxjs');      // Reactive stream
const { bufferTime, map, filter } = require('rxjs/operators');
const _ = require('lodash');                      // Utilities
const winston = require('winston');               // Logging

/* ──────────────────────────────────────────────────────────────────────────
 * Configuration Defaults
 * ──────────────────────────────────────────────────────────────────────── */
const DEFAULT_CONFIG = {
  kafka: {
    brokers: ['localhost:9092'],
    clientId: 'agorapulse-sentiment-drift-monitor',
    groupId:  'ap-sent-drift-monitor-group',
    maxRetries: 5,
    connectionTimeout: 5000,
  },

  topics: {
    input:  'model.sentiment.output', // Incoming sentiment classifications
    alerts: 'model.monitoring.alert'  // Generated alert events
  },

  monitoring: {
    windowMs:        60_000,     // Size of rolling window (in ms)
    emitEveryMs:     15_000,     // How often to evaluate / emit (in ms)
    driftThreshold:  0.20,       // Allowed deviation from baseline (absolute)
    minSamples:      50,         // Require at least X samples in window
    baselineRefresh: 3600_000    // Refresh baseline every 1h
  }
};

/* ──────────────────────────────────────────────────────────────────────────
 * Logger
 * ──────────────────────────────────────────────────────────────────────── */
const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    winston.format.timestamp({ format: 'YYYY-MM-DDTHH:mm:ss.SSSZ' }),
    winston.format.printf(
      ({ level, message, timestamp }) => `${timestamp} [${level.toUpperCase()}] ${message}`
    )
  ),
  transports: [new winston.transports.Console()]
});

/* ──────────────────────────────────────────────────────────────────────────
 * Helper: Jittered Backoff
 * ──────────────────────────────────────────────────────────────────────── */
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function withRetry(fn, retries, baseDelayMs = 500) {
  let attempt = 0;
  /* eslint-disable no-await-in-loop */
  while (attempt <= retries) {
    try {
      return await fn();
    } catch (err) {
      attempt += 1;
      if (attempt > retries) throw err;
      const jitter = _.random(0, baseDelayMs);
      const delay  = baseDelayMs * 2 ** attempt + jitter;
      logger.warn(`Retrying after error (${attempt}/${retries}) – waiting ${delay}ms: ${err.message}`);
      await sleep(delay);
    }
  }
  /* eslint-enable no-await-in-loop */
}

/* ──────────────────────────────────────────────────────────────────────────
 * Core Class: SentimentDriftMonitor
 * ──────────────────────────────────────────────────────────────────────── */
class SentimentDriftMonitor {
  /**
   * @param {Partial<typeof DEFAULT_CONFIG>} [configOverride]
   */
  constructor(configOverride = {}) {
    this.config = _.merge({}, DEFAULT_CONFIG, configOverride);

    this._kafka   = new Kafka({
      brokers: this.config.kafka.brokers,
      clientId: this.config.kafka.clientId,
      logLevel: logLevel.NOTHING // suppress internal logs; we use winston
    });

    // RxJS Subject acts as a bridge between Kafka consumer and reactive pipeline
    this._eventSubject = new Subject();

    // State
    this._baselineMean = 0;
    this._baselineLastRefresh = Date.now();
    this._consumer = null;
    this._producer = null;
    this._isRunning = false;
  }

  /* ────────── Public API ────────── */

  /**
   * Bootstraps Kafka connections and starts monitoring pipeline.
   */
  async start() {
    if (this._isRunning) return;
    logger.info('Starting SentimentDriftMonitor …');

    // Connect Kafka consumer & producer with retries
    this._consumer = this._kafka.consumer({ 
      groupId: this.config.kafka.groupId,
      allowAutoTopicCreation: false
    });
    this._producer = this._kafka.producer();

    await withRetry(() => this._producer.connect(), this.config.kafka.maxRetries);
    await withRetry(() => this._consumer.connect(), this.config.kafka.maxRetries);

    // Subscribe to input topic
    await this._consumer.subscribe({ topic: this.config.topics.input, fromBeginning: false });

    // Hook Kafka consumer to RxJS Subject
    this._consumer.run({
      eachMessage: async ({ message }) => {
        try {
          const payload = JSON.parse(message.value.toString());
          // payload: { sentimentScore: -1..1, timestamp: number }
          if (_.isNumber(payload.sentimentScore)) {
            this._eventSubject.next(payload);
          }
        } catch (err) {
          logger.error(`Failed to process incoming message: ${err.stack || err}`);
        }
      }
    });

    // Initialize reactive pipeline
    this._initializePipeline();

    this._isRunning = true;
    logger.info('SentimentDriftMonitor online.');
  }

  /**
   * Gracefully shuts down monitoring (closes Kafka connections, completes streams).
   */
  async stop() {
    if (!this._isRunning) return;
    logger.info('Stopping SentimentDriftMonitor …');

    this._isRunning = false;
    this._eventSubject.complete();

    await Promise.allSettled([
      this._consumer && this._consumer.disconnect(),
      this._producer && this._producer.disconnect()
    ]);

    logger.info('SentimentDriftMonitor stopped.');
  }

  /* ────────── Internal Methods ────────── */

  /**
   * Build RxJS pipeline that:
   *   – Buffers events in sliding window
   *   – Calculates mean sentiment
   *   – Compares with baseline and emits alert if drift is detected
   */
  _initializePipeline() {
    const {
      windowMs,
      emitEveryMs,
      driftThreshold,
      minSamples,
      baselineRefresh
    } = this.config.monitoring;

    this._eventSubject.pipe(
      bufferTime(windowMs, emitEveryMs),     // Rolling window
      filter((buffer) => buffer.length >= minSamples),
      map((buffer) => {
        const mean = _.meanBy(buffer, 'sentimentScore');
        return { mean, sampleSize: buffer.length, windowStart: buffer[0].timestamp, windowEnd: _.last(buffer).timestamp };
      })
    ).subscribe({
      next: async (stats) => {
        try {
          await this._evaluateWindow(stats, driftThreshold);
          await this._maybeRefreshBaseline(stats, baselineRefresh);
        } catch (err) {
          logger.error(`Pipeline evaluation error: ${err.stack || err}`);
        }
      },
      error: (err) => {
        logger.error(`RX pipeline error: ${err.stack || err}`);
      },
      complete: () => {
        logger.info('RX pipeline completed.');
      }
    });
  }

  /**
   * Compare current window mean against baseline and publish alert when drifted.
   * @private
   * @param {{ mean: number, sampleSize: number, windowStart: number, windowEnd: number }} stats
   * @param {number} threshold
   */
  async _evaluateWindow(stats, threshold) {
    const deviation = Math.abs(stats.mean - this._baselineMean);

    logger.info(
      `Window [${new Date(stats.windowStart).toISOString()} – ` +
      `${new Date(stats.windowEnd).toISOString()}] ` +
      `mean=${stats.mean.toFixed(3)} baseline=${this._baselineMean.toFixed(3)} ` +
      `dev=${deviation.toFixed(3)} (n=${stats.sampleSize})`
    );

    if (deviation >= threshold) {
      logger.warn(`Sentiment drift detected! Deviation ${deviation.toFixed(3)} ≥ threshold ${threshold}`);

      const alertEvent = {
        eventType:   'SENTIMENT_DRIFT_ALERT',
        detectedAt:  Date.now(),
        deviation,
        currentMean: stats.mean,
        baseline:    this._baselineMean,
        window:      { start: stats.windowStart, end: stats.windowEnd, sampleSize: stats.sampleSize }
      };

      await this._publishAlert(alertEvent);
    }
  }

  /**
   * Publishes alert events to Kafka "model.monitoring.alert".
   * @private
   * @param {Object} alertEvent
   */
  async _publishAlert(alertEvent) {
    const message = { key: 'sentiment-drift', value: JSON.stringify(alertEvent) };

    await withRetry(
      () => this._producer.send({ topic: this.config.topics.alerts, messages: [message] }),
      this.config.kafka.maxRetries
    );

    logger.info('Alert event published to Kafka.');
  }

  /**
   * Refresh baseline periodically using exponential moving average (EMA).
   * @private
   * @param {{ mean: number }} stats
   * @param {number} refreshIntervalMs
   */
  async _maybeRefreshBaseline(stats, refreshIntervalMs) {
    const now = Date.now();
    if (now - this._baselineLastRefresh >= refreshIntervalMs) {
      const alpha = 0.2; // EMA smoothing factor
      this._baselineMean = alpha * stats.mean + (1 - alpha) * this._baselineMean;
      this._baselineLastRefresh = now;
      logger.info(`Baseline updated via EMA → ${this._baselineMean.toFixed(3)}`);
    }
  }
}

/* ──────────────────────────────────────────────────────────────────────────
 * Module Exports
 * ──────────────────────────────────────────────────────────────────────── */
module.exports = {
  SentimentDriftMonitor,
  DEFAULT_CONFIG
};

/* ──────────────────────────────────────────────────────────────────────────
 * Self-Execute if Invoked Directly
 * ──────────────────────────────────────────────────────────────────────── */
if (require.main === module) {
  // Stand-alone run: node src/module_56.js
  (async () => {
    const monitor = new SentimentDriftMonitor();

    // Handle graceful shutdown (SIGINT / SIGTERM)
    const shutdown = async () => {
      await monitor.stop();
      process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);

    try {
      await monitor.start();
      logger.info('SentimentDriftMonitor is running. Press Ctrl+C to exit.');
    } catch (err) {
      logger.error(`Fatal error during startup: ${err.stack || err}`);
      process.exit(1);
    }
  })();
}
```