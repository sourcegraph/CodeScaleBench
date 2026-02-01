```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence – Sentiment Drift Monitor
 *
 * File:        src/module_18.js
 * Responsibility: Observe sentiment streams for a given model version and emit
 *                 drift events whenever statistically significant deviation is
 *                 detected compared with the reference (production) model.
 *
 * Design notes:
 *   • Built around RxJS Observables to keep the module fully event-driven.
 *   • Uses KafkaJS for robust, exactly-once stream consumption.
 *   • Emits domain events (“sentiment.drift”) back into Kafka to trigger the
 *     retraining pipeline downstream.
 *   • Lightweight statistical test: compares exponentially-weighted moving mean
 *     and variance using Welch’s t-test approximation.
 *
 * Author: AgoraPulse Engineering
 * Licence: Apache-2.0
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* External Dependencies                                                     */
/* ────────────────────────────────────────────────────────────────────────── */
const { Kafka, logLevel }           = require('kafkajs');
const { Subject, timer }            = require('rxjs');
const { bufferTime, filter, map }   = require('rxjs/operators');
const EventEmitter                  = require('events');

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants                                                                 */
/* ────────────────────────────────────────────────────────────────────────── */
const DEFAULT_KAFKA_BROKERS      = process.env.KAFKA_BROKERS?.split(',') || ['localhost:9092'];
const SENTIMENT_TOPIC            = process.env.SENTIMENT_TOPIC || /^sentiment\..*\.scores$/i;
const DRIFT_EVENT_TOPIC          = process.env.DRIFT_EVENT_TOPIC || 'sentiment.drift';
const WINDOW_MS                  = +process.env.WINDOW_MS || (5 * 60 * 1_000);   // 5 minutes
const EWMA_ALPHA                 = +process.env.EWMA_ALPHA || 0.3;
const DRIFT_THRESHOLD_T_SCORE    = +process.env.DRIFT_THRESHOLD_T_SCORE || 3.0;  // >3σ
const HEALTH_CHECK_INTERVAL_MS   = +process.env.HEALTH_CHECK_INTERVAL_MS || 15_000;

/* ────────────────────────────────────────────────────────────────────────── */
/* Helper Functions                                                          */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Exponentially-weighted moving statistics container.
 */
class EwmaStats {
    constructor(alpha = EWMA_ALPHA) {
        this.alpha      = alpha;
        this.mean       = 0;
        this.var        = 0; // variance
        this.initialised = false;
    }

    /**
     * Update running statistics with a new observation.
     * @param {number} x
     */
    update(x) {
        if (!this.initialised) {
            this.mean        = x;
            this.var         = 0;
            this.initialised = true;
            return;
        }

        const delta   = x - this.mean;
        this.mean     += this.alpha * delta;
        this.var      = (1 - this.alpha) * (this.var + this.alpha * delta ** 2);
    }
}

/**
 * Welch’s t-test simplified for two EWMA statistic holders (unequal var, n≈∞).
 * Returns absolute t-score.
 */
function tScore(statsA, statsB) {
    const numerator   = Math.abs(statsA.mean - statsB.mean);
    const denom       = Math.sqrt(statsA.var + statsB.var) || 1e-9;
    return numerator / Math.sqrt(denom);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* SentimentDriftMonitor                                                     */
/* ────────────────────────────────────────────────────────────────────────── */

class SentimentDriftMonitor extends EventEmitter {

    /**
     * @param {object}   options
     * @param {string[]} [options.brokers]
     * @param {RegExp|string} [options.sentimentTopic]
     * @param {string}   [options.driftEventTopic]
     */
    constructor(options = {}) {
        super();
        this.brokers           = options.brokers           || DEFAULT_KAFKA_BROKERS;
        this.sentimentTopic    = options.sentimentTopic    || SENTIMENT_TOPIC;
        this.driftEventTopic   = options.driftEventTopic   || DRIFT_EVENT_TOPIC;

        this.kafka             = new Kafka({
            clientId : 'sentiment-drift-monitor',
            brokers  : this.brokers,
            logLevel : logLevel.INFO,
        });

        this.consumer          = this.kafka.consumer({ groupId: `drift-monitor-${Date.now()}` });
        this.producer          = this.kafka.producer();

        this.message$          = new Subject();     // RxJS ingress
        this.statsPerModel     = new Map();         // { modelVersion -> EwmaStats }
        this.referenceModel    = process.env.REFERENCE_MODEL_VERSION || null;
        this._healthTimer      = null;
    }

    /* ─────────────── Lifecycle ─────────────── */

    async start() {
        await this.consumer.connect();
        await this.producer.connect();

        // Subscribe to all sentiment scoring topics.
        await this.consumer.subscribe({
            topic   : typeof this.sentimentTopic === 'string'
                      ? this.sentimentTopic
                      : { topic: this.sentimentTopic, fromBeginning: false },
        });

        // Consume loop
        this.consumer.run({
            eachMessage: async ({ message }) => {
                try {
                    const payload = JSON.parse(message.value.toString('utf-8'));
                    /**
                     * Expected payload:
                     * {
                     *   modelVersion: 'v1.2.3',
                     *   sentiment:    0.87,  // -1..1
                     *   timestamp:    1652633816252
                     * }
                     */
                    if (typeof payload.sentiment !== 'number') return;
                    this.message$.next(payload);
                } catch (err) {
                    console.error('[DriftMonitor] Invalid message', err);
                }
            },
        });

        // Main reactive pipeline
        this._wire();

        // Simple health check
        this._healthTimer = setInterval(() => this.emit('health', { ts: Date.now() }), HEALTH_CHECK_INTERVAL_MS);
        console.info('[DriftMonitor] Started.');
    }

    async stop() {
        await Promise.allSettled([this.consumer.disconnect(), this.producer.disconnect()]);
        this.message$.complete();
        clearInterval(this._healthTimer);
        console.info('[DriftMonitor] Stopped.');
    }

    /* ─────────────── Private ─────────────── */

    _wire() {
        // Buffer the stream into sliding windows for diagnostic logging.
        this.message$
            .pipe(bufferTime(WINDOW_MS))
            .subscribe(buffer => {
                if (!buffer.length) return;

                buffer.forEach(({ modelVersion, sentiment }) => {
                    let stats = this.statsPerModel.get(modelVersion);
                    if (!stats) {
                        stats = new EwmaStats();
                        this.statsPerModel.set(modelVersion, stats);
                    }
                    stats.update(sentiment);
                });

                this._detectDrift();
            });
    }

    _detectDrift() {
        if (!this.referenceModel) {
            // First model seen becomes reference.
            const first = [...this.statsPerModel.keys()][0];
            if (!first) return;
            this.referenceModel = first;
            console.info(`[DriftMonitor] Reference model set to ${first}`);
        }

        const refStats = this.statsPerModel.get(this.referenceModel);
        if (!refStats || !refStats.initialised) return;

        for (const [modelVersion, stats] of this.statsPerModel.entries()) {
            if (modelVersion === this.referenceModel || !stats.initialised) continue;

            const score = tScore(stats, refStats);
            if (score >= DRIFT_THRESHOLD_T_SCORE) {
                const event = {
                    eventType   : 'sentiment.drift',
                    detectedAt  : Date.now(),
                    reference   : this.referenceModel,
                    candidate   : modelVersion,
                    tScore      : score,
                    meanRef     : refStats.mean,
                    meanCand    : stats.mean,
                };

                // Fire internal event bus.
                this.emit('drift', event);

                // Publish domain event to Kafka.
                this.producer.send({
                    topic : this.driftEventTopic,
                    messages: [{ value: JSON.stringify(event) }],
                }).catch(err => console.error('[DriftMonitor] Failed to publish drift event', err));

                console.warn(`[DriftMonitor] Drift detected (model ${modelVersion}, t=${score.toFixed(2)})`);
            }
        }
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Module Exports                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

module.exports = { SentimentDriftMonitor };

/* ────────────────────────────────────────────────────────────────────────── */
/* CLI mode (node src/module_18.js)                                          */
/* ────────────────────────────────────────────────────────────────────────── */
if (require.main === module) {
    // eslint-disable-next-line no-unused-vars
    (async () => {
        const monitor = new SentimentDriftMonitor();
        monitor.on('drift', evt => {
            console.table(evt);
        });
        monitor.on('health', () => {
            /* heartbeat */
        });

        // Graceful shutdown
        const shutdown = async () => {
            console.info('\n[DriftMonitor] Shutdown signal received.');
            await monitor.stop();
            process.exit(0);
        };
        process.on('SIGINT',  shutdown);
        process.on('SIGTERM', shutdown);

        await monitor.start();
    })().catch(err => {
        console.error('[DriftMonitor] Fatal failure', err);
        process.exit(1);
    });
}
```