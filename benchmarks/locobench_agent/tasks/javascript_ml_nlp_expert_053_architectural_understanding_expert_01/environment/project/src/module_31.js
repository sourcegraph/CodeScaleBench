```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: SentimentShiftMonitor
 * File:   src/module_31.js
 *
 * Description:
 * Real-time model-monitoring component that watches the stream of
 * sentiment-analysis results coming off a Kafka topic, computes
 * rolling aggregates with RxJS, applies online statistics
 * (Welford’s algorithm) to learn a baseline, and fires an alert
 * when the aggregate sentiment drifts beyond a configurable
 * z-score threshold.
 *
 * This module is intended for server-side Node.js runtimes.
 *
 * -------------------------------------------------
 * Author: AgoraPulse Engineering
 * License: MIT
 */

'use strict';

/* eslint-disable no-console */

// ───────────────────────────────────────────────────────────────────────────────
// Dependencies
// ───────────────────────────────────────────────────────────────────────────────
const { Kafka, logLevel: KafkaLogLevel } = require('kafkajs');
const pino = require('pino');
const {
    Subject,
    timer,
    EMPTY,
} = require('rxjs');
const {
    bufferTime,
    filter,
    map,
    mergeMap,
    tap,
    catchError,
} = require('rxjs/operators');

// ───────────────────────────────────────────────────────────────────────────────
// Constants & Defaults
// ───────────────────────────────────────────────────────────────────────────────
const DEFAULT_WINDOW_SIZE_SEC = 60;      // aggregation window size
const DEFAULT_MIN_MESSAGES    = 100;     // min msgs per window
const DEFAULT_Z_SCORE_THRESH  = 2.5;     // alert if |z| > thresh

const EVENT_TYPES = Object.freeze({
    ALERT_SENTIMENT_SHIFT: 'ALERT_SENTIMENT_SHIFT',
});

// ───────────────────────────────────────────────────────────────────────────────
// Utility – OnlineMeanStd (Welford)
// ───────────────────────────────────────────────────────────────────────────────
class OnlineMeanStd {
    constructor() {
        this.n    = 0;
        this.mean = 0;
        this.M2   = 0; // sum of squares of differences from the current mean
    }

    add(x) {
        this.n += 1;
        const delta = x - this.mean;
        this.mean  += delta / this.n;
        const delta2 = x - this.mean;
        this.M2 += delta * delta2;
    }

    get variance() {
        return this.n > 1 ? this.M2 / (this.n - 1) : 0;
    }

    get std() {
        return Math.sqrt(this.variance);
    }

    toJSON() {
        return { n: this.n, mean: this.mean, std: this.std };
    }
}

// ───────────────────────────────────────────────────────────────────────────────
// SentimentShiftMonitor
// ───────────────────────────────────────────────────────────────────────────────
class SentimentShiftMonitor {
    /**
     * @param {Object} opts
     * @param {Object} opts.kafka         - KafkaJS configuration object
     * @param {string} opts.inputTopic    - Kafka topic to consume sentiment results from
     * @param {string} opts.alertTopic    - Kafka topic to emit alerts to
     * @param {number} [opts.windowSizeSec=60]
     * @param {number} [opts.minMessages=100]
     * @param {number} [opts.zScoreThreshold=2.5]
     * @param {pino.Logger} [opts.logger]
     */
    constructor({
        kafka,
        inputTopic,
        alertTopic,
        windowSizeSec    = DEFAULT_WINDOW_SIZE_SEC,
        minMessages      = DEFAULT_MIN_MESSAGES,
        zScoreThreshold  = DEFAULT_Z_SCORE_THRESH,
        logger           = pino({ name: 'SentimentShiftMonitor' }),
    }) {
        if (!kafka || !inputTopic || !alertTopic) {
            throw new Error('kafka, inputTopic and alertTopic are required');
        }

        this._kafkaCfg        = kafka;
        this._inputTopic      = inputTopic;
        this._alertTopic      = alertTopic;
        this._windowSizeSec   = windowSizeSec;
        this._minMessages     = minMessages;
        this._zScoreThreshold = zScoreThreshold;
        this._logger          = logger;

        // RxJS Subject that represents the sentiment stream
        this._stream$ = new Subject();

        // Online baseline statistics
        this._baselineStats = new OnlineMeanStd();

        // Kafka objects
        this._kafka    = new Kafka({ ...this._kafkaCfg, logLevel: KafkaLogLevel.NOTHING });
        this._consumer = this._kafka.consumer({ groupId: `sentiment-monitor-${Date.now()}` });
        this._producer = this._kafka.producer();

        // Internal state
        this._isRunning = false;
    }

    /**
     * Initialize Kafka connections and start processing loop.
     */
    async start() {
        if (this._isRunning) {
            this._logger.warn('Monitor already running.');
            return;
        }
        this._isRunning = true;

        await Promise.all([this._consumer.connect(), this._producer.connect()]);
        await this._consumer.subscribe({ topic: this._inputTopic, fromBeginning: false });

        // Forward Kafka messages into RxJS subject
        this._consumer.run({
            eachMessage: async ({ message }) => {
                try {
                    const payload = JSON.parse(message.value.toString('utf8'));
                    if (typeof payload.sentiment_score !== 'number') return;
                    this._stream$.next({ ...payload, ts: Date.now() });
                } catch (err) {
                    this._logger.error({ err }, 'Failed to parse sentiment message');
                }
            },
        }).catch(err => this._logger.error({ err }, 'Kafka consumer failure'));

        // Start RxJS pipeline
        this._subscription = this._stream$
            .pipe(
                bufferTime(this._windowSizeSec * 1_000),
                filter(batch => batch.length >= this._minMessages),
                map(batch => this._computeWindowStats(batch)),
                mergeMap(stats => this._handleWindowStats(stats)),
                catchError(err => {
                    this._logger.error({ err }, 'Pipeline error — continuing');
                    return EMPTY; // swallow & continue
                }),
            )
            .subscribe({
                complete: () => this._logger.info('Stream completed'),
            });

        this._logger.info('SentimentShiftMonitor started');
    }

    /**
     * Gracefully shuts down consumer/producer and RxJS pipeline.
     */
    async stop() {
        if (!this._isRunning) return;
        this._isRunning = false;

        if (this._subscription) this._subscription.unsubscribe();

        await Promise.allSettled([
            this._consumer.disconnect(),
            this._producer.disconnect(),
        ]);

        this._logger.info('SentimentShiftMonitor stopped');
    }

    // ────────────────────────────────────────────────────────────────────────
    // Internals
    // ────────────────────────────────────────────────────────────────────────

    /**
     * Compute statistics for the current window.
     * @param {Array<Object>} batch
     * @returns {Object} { mean, std, count, windowStart, windowEnd }
     * @private
     */
    _computeWindowStats(batch) {
        const scores = batch.map(x => x.sentiment_score);
        const sum    = scores.reduce((a, b) => a + b, 0);
        const mean   = sum / scores.length;
        const variance = scores.reduce((acc, x) => acc + (x - mean) ** 2, 0) / scores.length;
        const std    = Math.sqrt(variance);

        const windowStart = batch[0].ts;
        const windowEnd   = batch[batch.length - 1].ts;

        return { mean, std, count: batch.length, windowStart, windowEnd };
    }

    /**
     * Handle window statistics: update baseline and decide on alerts.
     * @param {Object} stats
     * @returns {Promise<void>}
     * @private
     */
    async _handleWindowStats(stats) {
        const { mean, std, count, windowStart, windowEnd } = stats;

        // update baseline incrementally
        this._baselineStats.add(mean);

        const baselineMean = this._baselineStats.mean;
        const baselineStd  = this._baselineStats.std || 1e-9; // avoid divide by zero
        const zScore = (mean - baselineMean) / baselineStd;

        this._logger.debug({
            window: { start: windowStart, end: windowEnd, count },
            mean, std,
            baseline: this._baselineStats.toJSON(),
            zScore,
        }, 'Window statistics');

        if (Math.abs(zScore) >= this._zScoreThreshold) {
            await this._emitAlert({
                type: EVENT_TYPES.ALERT_SENTIMENT_SHIFT,
                payload: {
                    zScore,
                    mean,
                    baselineMean,
                    baselineStd,
                    window: { start: windowStart, end: windowEnd, count },
                    timestamp: Date.now(),
                },
            });
        }
    }

    /**
     * Produce alert to Kafka and log it.
     * @param {Object} alert
     * @private
     */
    async _emitAlert(alert) {
        this._logger.warn({ alert }, 'Sentiment shift detected, emitting alert');

        try {
            await this._producer.send({
                topic: this._alertTopic,
                messages: [
                    { key: alert.type, value: JSON.stringify(alert) },
                ],
            });
        } catch (err) {
            this._logger.error({ err }, 'Failed to send alert message');
        }
    }
}

// ───────────────────────────────────────────────────────────────────────────────
// Factory
// ───────────────────────────────────────────────────────────────────────────────
/**
 * Factory helper that instantiates SentimentShiftMonitor with sensible defaults,
 * pulling configuration from environment variables.
 * @returns {SentimentShiftMonitor}
 */
function createSentimentShiftMonitor() {
    const {
        KAFKA_BROKERS           = 'localhost:9092',
        KAFKA_CLIENT_ID         = 'agorapulse-monitor',
        SENTIMENT_INPUT_TOPIC   = 'sentiment-scores',
        MONITOR_ALERT_TOPIC     = 'sentiment-alerts',
        WINDOW_SIZE_SEC         = DEFAULT_WINDOW_SIZE_SEC,
        MIN_MESSAGES            = DEFAULT_MIN_MESSAGES,
        Z_SCORE_THRESHOLD       = DEFAULT_Z_SCORE_THRESH,
    } = process.env;

    const kafkaCfg = {
        clientId: KAFKA_CLIENT_ID,
        brokers: KAFKA_BROKERS.split(','),
    };

    return new SentimentShiftMonitor({
        kafka: kafkaCfg,
        inputTopic: SENTIMENT_INPUT_TOPIC,
        alertTopic: MONITOR_ALERT_TOPIC,
        windowSizeSec: Number(WINDOW_SIZE_SEC),
        minMessages: Number(MIN_MESSAGES),
        zScoreThreshold: Number(Z_SCORE_THRESHOLD),
    });
}

// ───────────────────────────────────────────────────────────────────────────────
// Exports
// ───────────────────────────────────────────────────────────────────────────────
module.exports = {
    SentimentShiftMonitor,
    createSentimentShiftMonitor,
    EVENT_TYPES,
};
```