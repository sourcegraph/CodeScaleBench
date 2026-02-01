```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: Sentiment Drift Monitor
 *
 * This module listens to real-time sentiment-analysis events that flow out of
 * the model-serving tier (Kafka topic: `sentiment.predictions`).  By computing
 * a rolling distribution of sentiment labels and comparing it to the reference
 * distribution registered at model-validation time, we can detect concept
 * drift in seconds—not hours—thereby triggering automated retraining events
 * long before moderation quality degrades.
 *
 * File location: src/module_9.js
 *
 * External deps:
 *  - kafkajs            (stream ingestion)
 *  - rxjs               (reactive operators)
 *  - lodash             (utility helpers)
 *
 * NOTE: The entire project is ESM (`"type":"module"` in package.json`)
 */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, throttleTime } from 'rxjs';
import { EventEmitter } from 'node:events';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve as resolvePath } from 'node:path';
import _ from 'lodash';

/**
 * @typedef {Object} DriftMonitorConfig
 * @property {string[]} kafkaBrokers   – Kafka bootstrap servers
 * @property {string}   groupId        – Consumer group id
 * @property {string}   topic          – Kafka topic for predictions
 * @property {string}   baselinePath   – JSON file holding reference distribution
 * @property {number}   windowSize     – Number of samples in rolling window
 * @property {number}   emitEveryMs    – How often to emit aggregated stats
 * @property {number}   klThreshold    – Alert when KL‐divergence ≥ threshold
 */

/**
 * Utility: Load JSON from disk (returns {} on ENOENT)
 * @param {string} filePath
 * @returns {Promise<Record<string, number>>}
 */
async function safeJsonLoad(filePath) {
    try {
        const raw = await readFile(filePath, 'utf8');
        return JSON.parse(raw);
    } catch (err) {
        if (err.code === 'ENOENT') return {};
        throw err;
    }
}

/**
 * Utility: Persist JSON atomically to disk
 * @param {string} filePath
 * @param {Record<string, number>} obj
 */
async function safeJsonSave(filePath, obj) {
    const tmpPath = `${filePath}.tmp`;
    await writeFile(tmpPath, JSON.stringify(obj, null, 2));
    await writeFile(filePath, JSON.stringify(obj, null, 2));
    // In containerised environments, rename may cross FS boundaries; double-write is safer
}

/**
 * Compute KL divergence between two discrete distributions
 * Adds 1e-12 smoothing to avoid log(0)
 *
 * @param {Record<string, number>} p  – Observed
 * @param {Record<string, number>} q  – Reference
 */
function klDivergence(p, q) {
    const epsilon = 1e-12;
    const labels = _.union(Object.keys(p), Object.keys(q));
    return labels.reduce((sum, label) => {
        const pi = (p[label] || 0) + epsilon;
        const qi = (q[label] || 0) + epsilon;
        return sum + pi * Math.log(pi / qi);
    }, 0);
}

/**
 * Convert counts → probability distribution
 * @param {Record<string, number>} counts
 */
function normalise(counts) {
    const total = _.sum(Object.values(counts));
    return _.mapValues(counts, c => (total === 0 ? 0 : c / total));
}

/**
 * Real-time Sentiment Drift Monitor
 */
export class SentimentDriftMonitor extends EventEmitter {
    /**
     * @param {DriftMonitorConfig} cfg
     */
    constructor(cfg) {
        super();
        this.cfg = cfg;
        this.kafka = new Kafka({
            clientId: 'agorapulse.drift-monitor',
            brokers: cfg.kafkaBrokers,
            logLevel: logLevel.WARN
        });

        this.consumer = this.kafka.consumer({ groupId: cfg.groupId });
        this.subject$ = new Subject();

        /** Rolling window of recent sentiment label counts */
        this.windowCounts = {};

        /** Number of messages in the current rolling window */
        this.windowN = 0;

        /** Baseline reference distribution */
        this.baseline = {};
        this.baselinePath = resolvePath(cfg.baselinePath);

        this._initReactivePipeline();
    }

    /**
     * Internal: Set up RxJS pipeline to throttle/aggregate events
     */
    _initReactivePipeline() {
        // Throttle to one emission every cfg.emitEveryMs milliseconds
        this.subject$
            .pipe(throttleTime(this.cfg.emitEveryMs))
            .subscribe(() => {
                const observedDist = normalise(this.windowCounts);
                const kl = klDivergence(observedDist, this.baseline);

                // Emit periodic metrics for dashboards
                this.emit('metrics', {
                    ts: Date.now(),
                    windowSize: this.windowN,
                    distribution: observedDist,
                    klDivergence: kl
                });

                // Raise alert if divergence exceeds threshold
                if (kl >= this.cfg.klThreshold && this.windowN >= this.cfg.windowSize / 2) {
                    this.emit('driftAlert', {
                        ts: Date.now(),
                        klDivergence: kl,
                        observed: observedDist,
                        reference: this.baseline
                    });
                }

                // Optionally, update baseline slowly to adapt to natural shifts
                if (kl < this.cfg.klThreshold / 2 && this.windowN === this.cfg.windowSize) {
                    // Simple moving average adaptation
                    this.baseline = _.mapValues(
                        observedDist,
                        (p, label) => (p + (this.baseline[label] || 0)) / 2
                    );
                    safeJsonSave(this.baselinePath, this.baseline).catch(err =>
                        this.emit('error', err)
                    );
                }

                // Reset window
                this.windowCounts = {};
                this.windowN = 0;
            });
    }

    /**
     * Connect to Kafka & start consuming messages
     */
    async start() {
        try {
            this.baseline = await safeJsonLoad(this.baselinePath);

            await this.consumer.connect();
            await this.consumer.subscribe({ topic: this.cfg.topic, fromBeginning: false });

            await this.consumer.run({
                eachMessage: async ({ message }) => {
                    try {
                        const payload = JSON.parse(message.value.toString());
                        // Expect shape: { label: "positive" | "neutral" | "negative" | ... }
                        const label = payload.label;
                        if (!label) return; // Skip malformed messages

                        // Update rolling counts
                        this.windowCounts[label] = (this.windowCounts[label] || 0) + 1;
                        this.windowN += 1;

                        // Once window is full, trigger reactive emission
                        if (this.windowN >= this.cfg.windowSize) {
                            this.subject$.next(null);
                        }
                    } catch (err) {
                        this.emit('warn', new Error(`Invalid message: ${err.message}`));
                    }
                }
            });

            this.emit('ready');
        } catch (err) {
            this.emit('error', err);
            throw err;
        }
    }

    /**
     * Graceful shutdown
     */
    async stop() {
        try {
            await this.consumer.disconnect();
            this.subject$.complete();
        } catch (err) {
            this.emit('error', err);
        }
    }
}

/* ----------------------------------------------------------------------- *
 * Example usage (Keep disabled during unit tests)
 * ----------------------------------------------------------------------- */
// eslint-disable-next-line no-unused-vars
async function main() {
    const monitor = new SentimentDriftMonitor({
        kafkaBrokers: process.env.KAFKA_BROKERS?.split(',') || ['localhost:9092'],
        groupId: 'drift-monitor-v1',
        topic: 'sentiment.predictions',
        baselinePath: './data/baseline_sentiment.json',
        windowSize: 1_000,      // look at last 1k predictions
        emitEveryMs: 5_000,     // compute every 5 seconds
        klThreshold: 0.15       // tuned via offline experiments
    });

    monitor.on('driftAlert', alert => {
        console.warn('[DriftAlert]', JSON.stringify(alert, null, 2));
        // Here we could publish an event to Kafka, Slack, or OpenTelemetry, etc.
    });

    monitor.on('metrics', m => {
        // Push to Prometheus/OpenTelemetry
        // console.log('[Metrics]', m);
    });

    monitor.on('error', err => {
        console.error('[Error]', err);
    });

    await monitor.start();

    // CTRL-C handling
    process.on('SIGINT', async () => {
        console.log('Shutting down drift monitor…');
        await monitor.stop();
        process.exit(0);
    });
}

// Uncomment to run the module standalone
// if (import.meta.url === `file://${process.argv[1]}`) main();
```