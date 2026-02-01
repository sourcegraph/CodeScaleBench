```javascript
/**
 * src/module_78.js
 *
 * Real-time Toxicity Drift Monitor for AgoraPulse
 * ------------------------------------------------
 * Watches an RxJS stream of moderation classification results, calculates rolling
 * false-negative rates, and dispatches Kafka events to trigger automated
 * retraining when accuracy degrades beyond a configurable threshold.
 *
 * The module purposefully avoids any framework-specific code so that it can be
 * consumed by both Node-based micro-services and browser dashboards that bundle
 * Kafka-WebSocket bridges.  All hard dependencies are kept minimal—RxJS for
 * streaming composition, kafkajs for transport, and pino for structured logs.
 *
 * Usage:
 *   import { ToxicityDriftMonitor } from './module_78.js';
 *
 *   const monitor = new ToxicityDriftMonitor({
 *       modelName: 'toxicity-v4.2.1',
 *       brokers: ['kafka-01:9092', 'kafka-02:9092'],
 *       retrainTopic: 'ml.model.retrain',
 *       windowSizeSec: 60,
 *       falseNegativeRateThreshold: 0.03          // 3 %
 *   });
 *
 *   await monitor.init();
 *   monitor.watch(event$);                        // RxJS Observable<ModerationEvent>
 *
 *   // … later …
 *   await monitor.shutdown();
 */

import pino from 'pino';
import { Kafka } from 'kafkajs';
import { bufferTime, filter, map, tap } from 'rxjs/operators';
import { fromEvent, Observable, Subject } from 'rxjs';

const DEFAULTS = Object.freeze({
    windowSizeSec: 60,
    falseNegativeRateThreshold: 0.05, // 5 %
    retrainTopic: 'ml.model.retrain'
});

/**
 * @typedef {Object} ModerationEvent
 * @property {string} id            – Unique identifier of the message / post
 * @property {string} text          – Raw text
 * @property {'toxic'|'non-toxic'} prediction
 * @property {'toxic'|'non-toxic'|null} [groundTruth]
 * @property {string} model         – Name or version tag of the model
 * @property {number} score         – Continuous toxicity score, 0-1
 */

/**
 * Retrain event envelope pushed to Kafka.
 *
 * @typedef {Object} RetrainEvent
 * @property {'MODEL_RETRAIN_REQUEST'} type
 * @property {Object} payload
 * @property {string} payload.modelName
 * @property {number} payload.falseNegativeRate
 * @property {number} payload.windowSizeSec
 * @property {number} payload.windowSampleCount
 * @property {string} payload.reason
 */

export class ToxicityDriftMonitor {
    /**
     * @param {Object} cfg
     * @param {string} cfg.modelName                        – The model to monitor.
     * @param {string[]} cfg.brokers                        – Kafka broker list.
     * @param {string} [cfg.retrainTopic]                   – Kafka topic to emit retrain events to.
     * @param {number} [cfg.windowSizeSec]                  – Sliding window size in seconds.
     * @param {number} [cfg.falseNegativeRateThreshold]     – Threshold (0-1).
     * @param {import('pino').Logger} [cfg.logger]          – Optional external logger.
     */
    constructor(cfg = {}) {
        if (!cfg.modelName) {
            throw new Error('ToxicityDriftMonitor requires a `modelName`.');
        }
        if (!Array.isArray(cfg.brokers) || cfg.brokers.length === 0) {
            throw new Error('ToxicityDriftMonitor requires at least one Kafka `broker`.');
        }

        this.config = {
            ...DEFAULTS,
            ...cfg
        };

        this._logger = cfg.logger || pino({
            name: 'ToxicityDriftMonitor',
            level: process.env.LOG_LEVEL || 'info'
        });

        // Kafka bootstrap.
        this._kafka = new Kafka({
            clientId: `drift-monitor-${this.config.modelName}`,
            brokers: this.config.brokers
        });

        this._producer = this._kafka.producer({
            allowAutoTopicCreation: false,
            idempotent: true
        });

        this._connected = false;
        this._subscriptions = [];
    }

    /**
     * Opens a connection to Kafka.
     */
    async init() {
        if (this._connected) return;

        try {
            await this._producer.connect();
            this._connected = true;
            this._logger.info({ brokers: this.config.brokers }, 'Kafka producer connected.');
        } catch (err) {
            this._logger.error({ err }, 'Failed to connect Kafka producer.');
            throw err;
        }
    }

    /**
     * Starts observing a stream of ModerationEvents.
     *
     * @param {Observable<ModerationEvent>} event$
     */
    watch(event$) {
        if (!(event$ instanceof Observable)) {
            throw new TypeError('`event$` must be an RxJS Observable.');
        }

        const sub = event$
            .pipe(
                filter(evt => evt.model === this.config.modelName),
                bufferTime(this.config.windowSizeSec * 1000),
                filter(batch => batch.length > 0),
                map(batch => this._calculateStats(batch)),
                filter(stats => stats.falseNegativeRate >= this.config.falseNegativeRateThreshold),
                tap(stats => this._emitRetrainEvent(stats))
            )
            .subscribe({
                error: err => this._logger.error({ err }, 'Error in drift monitor pipeline.')
            });

        this._subscriptions.push(sub);
        this._logger.info('Toxicity drift monitor subscribed to event stream.');
    }

    /**
     * Unsubscribes from all streams and disconnects producer.
     */
    async shutdown() {
        for (const sub of this._subscriptions) {
            sub?.unsubscribe();
        }
        this._subscriptions = [];

        if (this._connected) {
            await this._producer.disconnect();
            this._connected = false;
            this._logger.info('Kafka producer disconnected.');
        }
    }

    /**
     * Compute false negative rate for a batch of moderation events.
     *
     * @private
     * @param {ModerationEvent[]} batch
     * @returns {{
     *   falseNegativeRate: number,
     *   batchSize: number,
     *   falseNegatives: number
     * }}
     */
    _calculateStats(batch) {
        const withGroundTruth = batch.filter(e => e.groundTruth != null);
        const falseNegatives = withGroundTruth.filter(
            e => e.groundTruth === 'toxic' && e.prediction !== 'toxic'
        ).length;

        const stats = {
            falseNegativeRate:
                withGroundTruth.length === 0 ? 0 : falseNegatives / withGroundTruth.length,
            batchSize: withGroundTruth.length,
            falseNegatives
        };

        this._logger.debug(stats, 'Calculated window stats');
        return stats;
    }

    /**
     * Build and send a retrain event to Kafka.
     *
     * @private
     * @param {{
     *  falseNegativeRate: number,
     *  batchSize: number,
     *  falseNegatives: number
     * }} stats
     */
    async _emitRetrainEvent(stats) {
        const event /** @type {RetrainEvent} */ = {
            type: 'MODEL_RETRAIN_REQUEST',
            payload: {
                modelName: this.config.modelName,
                falseNegativeRate: stats.falseNegativeRate,
                windowSizeSec: this.config.windowSizeSec,
                windowSampleCount: stats.batchSize,
                reason: `False negative rate ${(stats.falseNegativeRate * 100).toFixed(2)}% exceeds threshold ${(this.config.falseNegativeRateThreshold * 100).toFixed(2)}%.`
            }
        };

        try {
            await this._producer.send({
                topic: this.config.retrainTopic,
                messages: [
                    {
                        key: this.config.modelName,
                        value: JSON.stringify(event),
                        headers: { 'content-type': 'application/json' }
                    }
                ]
            });
            this._logger.warn(
                { model: this.config.modelName, stats },
                'Drift detected – retrain request emitted.'
            );
        } catch (err) {
            this._logger.error({ err }, 'Failed to publish retrain event.');
        }
    }
}

/**
 * Convenience factory.
 *
 * @param {ConstructorParameters<typeof ToxicityDriftMonitor>[0]} cfg
 * @returns {Promise<ToxicityDriftMonitor>}
 */
export async function createToxicityDriftMonitor(cfg) {
    const monitor = new ToxicityDriftMonitor(cfg);
    await monitor.init();
    return monitor;
}

export default ToxicityDriftMonitor;
```