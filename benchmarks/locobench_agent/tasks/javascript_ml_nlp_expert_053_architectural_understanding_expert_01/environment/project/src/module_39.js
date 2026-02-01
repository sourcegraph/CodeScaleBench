```javascript
/**
 * @fileoverview Real-time model-quality monitor for the AgoraPulse platform.
 *
 * Listens to model-serving output events on Kafka, computes sliding–window
 * quality metrics (toxicity false-negative rate, group fairness disparity, etc.),
 * and emits alerts when thresholds are breached.
 *
 * Production readiness:
 *   – automatic reconnection & retry with exponential back-off
 *   – graceful shutdown hooks
 *   – typed payload validation (via `ajv`)
 *   – RxJS operators for windowing / metric aggregation
 *   – pluggable metrics + alert-routing strategies (Strategy & Observer pattern)
 *
 * Author: AgoraPulse OSS Team
 * License: MIT
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* Dependencies                                                             */
/* ────────────────────────────────────────────────────────────────────────── */
const { Kafka, logLevel }                = require('kafkajs');
const { Subject, timer, merge }          = require('rxjs');
const {
    bufferTime,
    filter,
    map,
    mergeMap,
    retryWhen,
    delayWhen,
    takeUntil,
}                                         = require('rxjs/operators');
const Ajv                                 = require('ajv').default;
const addFormats                          = require('ajv-formats');
const deepcopy                            = require('lodash.clonedeep');
const { v4: uuid }                        = require('uuid');

/* ────────────────────────────────────────────────────────────────────────── */
/* Configuration                                                            */
/* ────────────────────────────────────────────────────────────────────────── */
const CONFIG = Object.freeze({
    kafka: {
        brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
        clientId: 'ap-model-monitor',
        groupId:  'ap-model-monitor-group',
        inputTopic:  'model-serving-output',
        alertTopic:  'model-monitoring-alerts',
    },
    window: {
        ms: parseInt(process.env.MONITOR_WINDOW_MS, 10) || 10_000,  // 10s
        minEvents: parseInt(process.env.MONITOR_MIN_EVENTS, 10) || 300,
    },
    thresholds: {
        toxicityFNRate: parseFloat(process.env.TOXIC_FN_RATE) || 0.10,     // 10 %
        subgroupDisparityRatio: parseFloat(process.env.SUBGROUP_DISPARITY) || 0.75,
    },
    retry: {
        maxAttempts: 5,
        baseDelayMs: 2000,
    },
});

/* ────────────────────────────────────────────────────────────────────────── */
/* Payload schema                                                           */
/* ────────────────────────────────────────────────────────────────────────── */
const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);

const PAYLOAD_SCHEMA = {
    $id: 'modelServingOutput',
    type: 'object',
    additionalProperties: false,
    required: [
        'messageId',
        'timestamp',
        'userId',
        'groupId',
        'modelVersion',
        'predictedLabel',
        'actualLabel',
        'toxicityScore',
    ],
    properties: {
        messageId:      { type: 'string' },
        timestamp:      { type: 'string', format: 'date-time' },
        userId:         { type: 'string' },
        groupId:        { type: 'string' },
        modelVersion:   { type: 'string' },
        predictedLabel: { type: 'string', enum: ['toxic', 'not_toxic'] },
        actualLabel:    { type: 'string', enum: ['toxic', 'not_toxic'] },
        toxicityScore:  { type: 'number', minimum: 0, maximum: 1 },
    },
};

const validatePayload = ajv.compile(PAYLOAD_SCHEMA);

/* ────────────────────────────────────────────────────────────────────────── */
/* Helper utilities                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Compute false negative rate (FN_rate = FN / (FN + TP)).
 * @param {Array<Object>} events
 * @returns {number}
 */
function computeToxicityFalseNegativeRate(events) {
    let fn = 0, tp = 0;
    for (const e of events) {
        if (e.actualLabel === 'toxic') {
            if (e.predictedLabel !== 'toxic') fn += 1;
            else tp += 1;
        }
    }
    const denom = fn + tp;
    return denom === 0 ? 0 : fn / denom;
}

/**
 * Compute subgroup disparity ratio of false negative rates.
 * Returns min(FN_rate_subgroup) / max(FN_rate_subgroup)
 * where subgroup is defined by `groupId`.
 * @param {Array<Object>} events
 * @returns {number} – 1 means perfectly equal, < 1 indicates disparity
 */
function computeSubgroupDisparity(events) {
    const groupStats = new Map();  // groupId -> {fn, tp}
    for (const e of events) {
        if (e.actualLabel !== 'toxic') continue;
        const stats = groupStats.get(e.groupId) ?? { fn: 0, tp: 0 };
        if (e.predictedLabel !== 'toxic') stats.fn += 1;
        else stats.tp += 1;
        groupStats.set(e.groupId, stats);
    }

    if (groupStats.size < 2) return 1;  // need at least 2 groups to compare

    let minRate = 1, maxRate = 0;
    for (const { fn, tp } of groupStats.values()) {
        const rate = fn + tp === 0 ? 0 : fn / (fn + tp);
        minRate = Math.min(minRate, rate);
        maxRate = Math.max(maxRate, rate);
    }
    if (maxRate === 0) return 1;
    return minRate / maxRate;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Alert producer                                                           */
/* ────────────────────────────────────────────────────────────────────────── */
class AlertProducer {
    /**
     * @param {Kafka} kafka
     * @param {string} topic
     */
    constructor(kafka, topic) {
        this._producer = kafka.producer();
        this._topic     = topic;
        this._ready     = this._producer.connect();
    }

    /**
     * Emit an alert payload to Kafka.
     * @param {Object} alert
     * @returns {Promise<void>}
     */
    async send(alert) {
        await this._ready;
        await this._producer.send({
            topic: this._topic,
            messages: [{ key: alert.modelVersion, value: JSON.stringify(alert) }],
        });
    }

    async disconnect() {
        await this._producer.disconnect();
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Real-time monitoring service                                             */
/* ────────────────────────────────────────────────────────────────────────── */
class RealTimeModelMonitor {

    constructor(config = CONFIG) {
        this._config   = deepcopy(config);
        this._kafka    = new Kafka({
            clientId: config.kafka.clientId,
            brokers : config.kafka.brokers,
            logLevel: logLevel.NOTHING,
        });
        this._alertProducer = new AlertProducer(this._kafka, config.kafka.alertTopic);

        this._consumer      = this._kafka.consumer({ 
            groupId: config.kafka.groupId,
            retry: { retries: 0 }, // we manage retry manually with RxJS
        });

        this._stop$         = new Subject();
        this._input$        = new Subject();
    }

    /* ────────────── Public API ────────────── */

    async start() {
        await this._consumer.connect();
        await this._consumer.subscribe({ topic: this._config.kafka.inputTopic, fromBeginning: false });

        // Forward messages into RxJS Subject
        this._consumer.run({
            eachMessage: async ({ message }) => {
                try {
                    const payload = JSON.parse(message.value.toString());
                    if (!validatePayload(payload)) {
                        console.warn('[monitor] invalid payload, dropping', ajv.errorsText(validatePayload.errors));
                        return;
                    }
                    this._input$.next(payload);
                } catch (err) {
                    console.error('[monitor] failed to parse payload', err);
                }
            },
        });

        // Set up processing pipeline
        this._subscription = this._input$.pipe(
            bufferTime(this._config.window.ms),    // create sliding windows
            filter(batch => batch.length >= this._config.window.minEvents),
            map(events => ({
                events,
                fnRate      : computeToxicityFalseNegativeRate(events),
                disparity   : computeSubgroupDisparity(events),
                modelVersion: mostFrequent(events.map(e => e.modelVersion)),
                windowSize  : events.length,
                windowStart : events[0]?.timestamp,
                windowEnd   : events[events.length - 1]?.timestamp,
            })),
            filter(metrics => this._isAlert(metrics)),
            mergeMap(metrics => this._emitAlert(metrics)),
            retryWhen(retryExponential(this._config.retry)),
            takeUntil(this._stop$),
        ).subscribe({
            error: err => {
                // Will already retry; if still fails, log and continue
                console.error('[monitor] pipeline error', err);
            },
        });

        process.once('SIGINT',  () => this.stop());
        process.once('SIGTERM', () => this.stop());
    }

    async stop() {
        this._stop$.next(true);
        await this._subscription?.unsubscribe();
        await this._consumer.disconnect();
        await this._alertProducer.disconnect();
        console.log('[monitor] shutdown completed.');
        process.exit(0);
    }

    /* ────────────── Internal helpers ────────────── */

    /**
     * Determine whether metrics breach any configured thresholds.
     * @param {Object} metrics
     * @returns {boolean}
     */
    _isAlert(metrics) {
        return (
            metrics.fnRate   > this._config.thresholds.toxicityFNRate ||
            metrics.disparity < this._config.thresholds.subgroupDisparityRatio
        );
    }

    /**
     * Send alert via producer.
     * @param {Object} metrics
     */
    async _emitAlert(metrics) {
        const alert = {
            alertId     : uuid(),
            triggeredAt : new Date().toISOString(),
            ...metrics,
            thresholds  : this._config.thresholds,
            type        : 'MODEL_MONITORING',
        };
        await this._alertProducer.send(alert);
        console.log('[monitor] alert emitted', {
            fnRate   : metrics.fnRate.toFixed(3),
            disparity: metrics.disparity.toFixed(3),
            window   : `${metrics.windowStart} – ${metrics.windowEnd}`,
        });
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Utility functions                                                        */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Return the most frequent element in an array, tie-breaking arbitrarily.
 * @template T
 * @param {T[]} arr
 * @returns {T}
 */
function mostFrequent(arr) {
    const counts = new Map();
    for (const item of arr) counts.set(item, (counts.get(item) ?? 0) + 1);
    let max = 0, winner = arr[0];
    for (const [item, count] of counts) {
        if (count > max) {
            max = count;
            winner = item;
        }
    }
    return winner;
}

/**
 * Generate a retry strategy for RxJS `retryWhen` with exponential back-off.
 * @param {{maxAttempts: number, baseDelayMs: number}} opts
 */
function retryExponential({ maxAttempts, baseDelayMs }) {
    return (errors$) => errors$.pipe(
        mergeMap((err, i) => {
            const attempt = i + 1;
            if (attempt > maxAttempts) {
                console.error('[monitor] exceeded max retry attempts, giving up');
                return Promise.reject(err);
            }
            const delay = baseDelayMs * 2 ** (attempt - 1);
            console.warn(`[monitor] retrying in ${delay}ms (attempt ${attempt}/${maxAttempts})`);
            return timer(delay);
        }),
    );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Bootstrap                                                                */
/* ────────────────────────────────────────────────────────────────────────── */

if (require.main === module) {
    (async () => {
        try {
            const monitor = new RealTimeModelMonitor();
            await monitor.start();
            console.log('[monitor] service started.');
        } catch (err) {
            console.error('[monitor] fatal error, exiting', err);
            process.exit(1);
        }
    })();
}

module.exports = {
    RealTimeModelMonitor,
};
```