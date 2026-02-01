```javascript
'use strict';

/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module 46: Real-Time Concept-Drift Monitor
 *
 * This module listens to the model-serving Kafka topic that contains model
 * inferences (sentiment, toxicity, stance, etc.). It computes sliding-window
 * statistics and fires a `model.retrain.requested` event whenever the
 * distribution of predictions drifts beyond an adaptive KL-divergence
 * threshold.
 *
 * Design goals:
 *  • Non-blocking, back-pressure-aware stream processing (RxJS)
 *  • Pluggable drift metric & adaptive threshold
 *  • Tight Prometheus integration for observability
 *  • Safe startup/shutdown semantics
 *
 * NOTE: External wiring (env vars, DI container, etc.) is expected to pass
 *       configuration. This file purposefully contains no CLI boilerplate.
 */

/* ──────────────────────────────────────────────────────────────────────────────
 * Dependencies
 * ─────────────────────────────────────────────────────────────────────────── */
const { Subject, timer, merge, throwError } = require('rxjs');
const {
    bufferTime,
    filter,
    map,
    pairwise,
    switchMap,
    tap,
    catchError,
} = require('rxjs/operators');
const Kafka = require('node-rdkafka');
const winston = require('winston');
const promClient = require('prom-client');
const _ = require('lodash');

/* ──────────────────────────────────────────────────────────────────────────────
 * Logger
 * ─────────────────────────────────────────────────────────────────────────── */
const log = winston.createLogger({
    level: process.env.LOG_LEVEL || 'info',
    transports: [new winston.transports.Console({ format: winston.format.simple() })],
});

/* ──────────────────────────────────────────────────────────────────────────────
 * Prometheus metrics
 * ─────────────────────────────────────────────────────────────────────────── */
const registry = new promClient.Registry();
promClient.collectDefaultMetrics({ register: registry });

const driftGauge = new promClient.Gauge({
    name: 'agorapulse_model_kl_drift',
    help: 'Current KL-divergence between baseline window and active window.',
    registers: [registry],
});

const retrainCounter = new promClient.Counter({
    name: 'agorapulse_model_retrain_requests_total',
    help: 'Number of retraining requests emitted by the drift monitor.',
    registers: [registry],
});

/* ──────────────────────────────────────────────────────────────────────────────
 * Helper functions
 * ─────────────────────────────────────────────────────────────────────────── */

/**
 * Returns a frequency dictionary of categorical labels in the window.
 * Example output: { positive: 0.4, neutral: 0.35, negative: 0.25 }
 *
 * @param {Array<Object>} window – Stream window of inference messages
 * @param {string} labelKey    – Key containing the categorical prediction
 */
function computeDistribution(window, labelKey = 'prediction') {
    const counts = _.countBy(window, labelKey);
    const total = window.length || 1;
    return _.mapValues(counts, (c) => c / total);
}

/**
 * Computes the KL divergence D(P || Q) between two discrete distributions.
 * Missing keys are smoothed with epsilon to avoid Math.log(0).
 *
 * @param {Object} P – baseline distribution
 * @param {Object} Q – candidate distribution
 * @param {number} eps – smoothing factor
 */
function klDivergence(P, Q, eps = 1e-6) {
    const keys = _.union(Object.keys(P), Object.keys(Q));
    let kl = 0.0;

    keys.forEach((k) => {
        const p = (P[k] ?? 0) + eps;
        const q = (Q[k] ?? 0) + eps;
        kl += p * Math.log(p / q);
    });

    return kl;
}

/* ──────────────────────────────────────────────────────────────────────────────
 * DriftMonitor class
 * ─────────────────────────────────────────────────────────────────────────── */

/**
 * Real-time drift monitor using RxJS & Kafka.
 */
class DriftMonitor {
    /**
     * @param {Object} params
     * @param {Object} params.kafkaConfig      – Global Kafka client config
     * @param {Object} params.consumerConfig   – Consumer-specific config
     * @param {string} params.sourceTopic      – Topic with model inferences
     * @param {string} params.targetTopic      – Topic for retrain events
     * @param {number} params.windowMs         – Sliding window size (ms)
     * @param {number} params.baselineMs       – Time to learn baseline (ms)
     * @param {number} params.thresholdInitial – Starting KL divergence threshold
     * @param {number} params.thresholdGrowth  – Factor to grow threshold over time
     */
    constructor({
        kafkaConfig,
        consumerConfig,
        sourceTopic,
        targetTopic = 'model.retrain',
        windowMs = 30_000,
        baselineMs = 600_000,
        thresholdInitial = 0.05,
        thresholdGrowth = 1.5,
    }) {
        if (!sourceTopic) throw new Error('sourceTopic is required');

        this.kafkaConfig = kafkaConfig;
        this.consumerConfig = consumerConfig;
        this.sourceTopic = sourceTopic;
        this.targetTopic = targetTopic;
        this.windowMs = windowMs;
        this.baselineMs = baselineMs;
        this.threshold = thresholdInitial;
        this.thresholdGrowth = thresholdGrowth;

        this._message$ = new Subject(); // central message bus
        this._baselineReady = false;
        this._baselineDistribution = null;

        this._consumer = null;
        this._producer = null;
        this._subscriptions = [];
    }

    /* ─────────────── Public API ─────────────── */

    /**
     * Initialize Kafka clients and reactive pipeline.
     */
    async start() {
        await this._initKafka();
        this._wireStreamPipeline();
        log.info('DriftMonitor started.');
    }

    /**
     * Gracefully flush and close all resources.
     */
    async stop() {
        log.info('Stopping DriftMonitor …');
        this._subscriptions.forEach((sub) => sub.unsubscribe());

        await Promise.all([
            new Promise((res) => this._consumer.disconnect(res)),
            new Promise((res) => this._producer.flush(10_000, () => this._producer.disconnect(res))),
        ]);

        log.info('DriftMonitor stopped.');
    }

    /* ─────────────── Internal – Kafka setup ─────────────── */

    async _initKafka() {
        this._consumer = new Kafka.KafkaConsumer(
            this.kafkaConfig,
            Object.assign(
                {
                    'group.id': `drift-monitor-${Date.now()}`,
                    'enable.auto.commit': true,
                },
                this.consumerConfig,
            ),
        );

        this._producer = new Kafka.Producer(this.kafkaConfig);

        // Consumer wiring
        await new Promise((resolve, reject) => {
            this._consumer
                .on('ready', () => {
                    this._consumer.subscribe([this.sourceTopic]);
                    this._consumer.consume();
                    resolve();
                })
                .on('data', (msg) => {
                    try {
                        const payload = JSON.parse(msg.value.toString());
                        this._message$.next(payload);
                    } catch (err) {
                        log.warn(`Failed to parse message: ${err.message}`);
                    }
                })
                .on('event.error', reject);

            this._consumer.connect();
        });

        // Producer wiring
        await new Promise((resolve, reject) => {
            this._producer
                .on('ready', resolve)
                .on('event.error', reject)
                .connect();
        });

        log.info('Kafka consumer & producer ready.');
    }

    /* ─────────────── Internal – Stream pipeline ─────────────── */

    _wireStreamPipeline() {
        // Window the messages into bufferTime windows
        const window$ = this._message$.pipe(bufferTime(this.windowMs), filter((w) => w.length > 0));

        // Baseline learner: first N minutes form baseline distribution
        const baseline$ = window$.pipe(
            takeUntil(timer(this.baselineMs)),
            tap((w) => {
                const dist = computeDistribution(w);
                if (!this._baselineDistribution) {
                    this._baselineDistribution = dist;
                } else {
                    // Exponential moving average to smooth baseline
                    Object.keys(dist).forEach((k) => {
                        this._baselineDistribution[k] =
                            0.9 * this._baselineDistribution[k] + 0.1 * dist[k];
                    });
                }
            }),
        );

        // After baseline period, start monitoring
        const monitoring$ = window$.pipe(
            skipUntil(timer(this.baselineMs)),
            map((w) => ({
                window: w,
                distribution: computeDistribution(w),
            })),
            pairwise(),
            map(([prev, curr]) => {
                const kl = klDivergence(this._baselineDistribution, curr.distribution);
                return { ...curr, kl };
            }),
            tap(({ kl }) => driftGauge.set(kl)),
            filter(({ kl }) => kl >= this.threshold),
            tap(({ kl }) => {
                log.warn(`Drift detected: KL=${kl.toFixed(4)} exceeds threshold=${this.threshold}`);
                this._emitRetrainEvent({ kl });
                retrainCounter.inc();
                // After each trigger, relax threshold to avoid flapping.
                this.threshold *= this.thresholdGrowth;
                log.info(`New drift threshold set to ${this.threshold.toFixed(4)}`);
            }),
            catchError((err, caught) => {
                log.error(`Stream error: ${err.stack || err}`);
                return caught; // restart stream
            }),
        );

        // Subscriptions
        this._subscriptions.push(baseline$.subscribe());
        this._subscriptions.push(monitoring$.subscribe());
    }

    /* ─────────────── Internal – Retrain producer ─────────────── */

    _emitRetrainEvent(payload) {
        const event = {
            event_type: 'model.retrain.requested',
            timestamp: Date.now(),
            metadata: {
                reason: 'concept_drift',
                ...payload,
            },
        };

        const buf = Buffer.from(JSON.stringify(event));
        this._producer.produce(
            this.targetTopic,
            null,
            buf,
            null,
            Date.now(),
            (err) => {
                if (err) {
                    log.error(`Failed to emit retrain event: ${err.message}`);
                } else {
                    log.info(`Retrain event produced to ${this.targetTopic}`);
                }
            },
        );
    }

    /* ─────────────── Prometheus exposition ─────────────── */

    /**
     * Expose current metrics in Prometheus plain-text format.
     * @returns {string}
     */
    getMetrics() {
        return registry.metrics();
    }
}

/* ──────────────────────────────────────────────────────────────────────────────
 * Factory helper
 * ─────────────────────────────────────────────────────────────────────────── */

/**
 * Factory to instantiate a DriftMonitor from environment variables.
 */
function createDriftMonitorFromEnv() {
    const kafkaConfig = {
        'metadata.broker.list': process.env.KAFKA_BROKERS || 'localhost:9092',
        dr_cb: true,
    };

    return new DriftMonitor({
        kafkaConfig,
        consumerConfig: {},
        sourceTopic: process.env.SOURCE_TOPIC || 'model.inference',
        targetTopic: process.env.TARGET_TOPIC || 'model.retrain',
        windowMs: parseInt(process.env.WINDOW_MS || '30000', 10),
        baselineMs: parseInt(process.env.BASELINE_MS || '600000', 10),
        thresholdInitial: parseFloat(process.env.KL_THRESHOLD || '0.05'),
        thresholdGrowth: parseFloat(process.env.THRESHOLD_GROWTH || '1.5'),
    });
}

/* ──────────────────────────────────────────────────────────────────────────────
 * Module exports
 * ─────────────────────────────────────────────────────────────────────────── */
module.exports = {
    DriftMonitor,
    createDriftMonitorFromEnv,
};
```