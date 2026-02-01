```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 *
 * Module: src/module_6.js
 * Responsibility: Online model-drift monitoring & automated re-training trigger
 *
 * This module consumes model-serving inference events from Kafka, maintains
 * rolling distribution windows, performs statistical drift detection, updates
 * Prometheus metrics, and publishes `RetrainingRequested` domain events when
 * drift is detected persistently.
 *
 * NOTE: Runtime dependencies (peer):
 *   - node-rdkafka            (Kafka consumer/producer)
 *   - rxjs                    (reactive streams)
 *   - prom-client             (Prometheus instrumentation)
 *   - deque                   (lightweight double-ended queue)
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

'use strict';

/* ──────────────────────────────────────────────────────────────────
 * External imports
 * ────────────────────────────────────────────────────────────────── */
const Kafka          = require('node-rdkafka');
const { Subject }    = require('rxjs');
const { bufferTime } = require('rxjs/operators');
const promClient     = require('prom-client');
const Deque          = require('dequeue'); // tiny & fast circular deque

/* ──────────────────────────────────────────────────────────────────
 * Configuration
 * ────────────────────────────────────────────────────────────────── */
const DRIFT_CONFIG = Object.freeze({
    kafka: {
        brokers: process.env.KAFKA_BROKERS || 'localhost:9092',
        groupId: process.env.KAFKA_GROUP_ID || 'agorapulse.drift-monitor',
        inferenceTopic: process.env.KAFKA_INFERENCE_TOPIC || 'inference.outcomes',
        controlTopic: process.env.KAFKA_CONTROL_TOPIC   || 'model.retraining',
    },
    stats: {
        baselineEvents: 5_000,               // #events to build baseline
        windowSize:     2_000,               // sliding window length
        alpha:          0.01,                // chi-square significance level
        consecutiveDriftTrigger: 3,          // #consecutive drift windows to trigger retraining
    },
    metrics: {
        prefix: 'agorapulse_drift_',
        collectDefault: true,
    },
});

/* ──────────────────────────────────────────────────────────────────
 * Prometheus metrics registry
 * ────────────────────────────────────────────────────────────────── */
promClient.collectDefaultMetrics({ prefix: DRIFT_CONFIG.metrics.prefix });

const driftDetectedCounter = new promClient.Counter({
    name: `${DRIFT_CONFIG.metrics.prefix}detected_total`,
    help: 'Total drift detections (window-level)',
    labelNames: [ 'model_version' ],
});

const retrainTriggeredCounter = new promClient.Counter({
    name: `${DRIFT_CONFIG.metrics.prefix}retrain_triggered_total`,
    help: 'Total retrain events emitted (model-level)',
    labelNames: [ 'model_version' ],
});

/* ──────────────────────────────────────────────────────────────────
 * Drift detection strategies
 * ────────────────────────────────────────────────────────────────── */

/**
 * AbstractStrategy – contract for drift detection implementations.
 */
class AbstractStrategy {
    /**
     * @param {number} alpha – significance level
     */
    constructor(alpha) {
        if (this.constructor === AbstractStrategy)
            throw new TypeError('Cannot instantiate AbstractStrategy directly');
        this.alpha = alpha;
    }

    /**
     * @param {number[]} baseline – baseline distribution
     * @param {number[]} window   – current window distribution
     * @returns {boolean} – true if drift detected
     */
    detect(baseline, window) { throw new Error('Not implemented'); }
}

/**
 * ChiSquaredStrategy – χ² goodness-of-fit test for categorical distributions.
 */
class ChiSquaredStrategy extends AbstractStrategy {
    detect(baseline, window) {
        if (baseline.length !== window.length) return true; // shape mismatch
        const totalBaseline = baseline.reduce((a,b)=>a+b, 0);
        const totalWindow   = window.reduce((a,b)=>a+b, 0);
        let chi2 = 0;
        for (let i = 0; i < baseline.length; i++) {
            const expected = (baseline[i]/totalBaseline)*totalWindow + 1e-9; // avoid /0
            chi2 += Math.pow(window[i] - expected, 2) / expected;
        }
        // Degrees of freedom = k ‑ 1
        const dof = baseline.length - 1;
        // Use Wilson-Hilferty approximation to get p-value without big lib
        const pValue = 1 - normalCDF(Math.pow((chi2 / dof) ** (1/3) - 1 + 2/(9*dof), -1) );
        return pValue < this.alpha;
    }
}

/* ──────────────────────────────────────────────────────────────────
 * Utility functions
 * ────────────────────────────────────────────────────────────────── */

/**
 * Inverse of standard normal CDF using Hart approximation (for p<0.5)
 * See: https://stackoverflow.com/a/56656331
 * @param {number} p – probability
 * @returns {number}
 */
function normalInvCDF(p) {
    if (p <= 0 || p >= 1) throw new RangeError('p outside (0,1)');
    const a1= -39.696830, a2=220.946098, a3=-275.928510, a4=138.357751, a5=-30.664798, a6=2.506628;
    const b1= -54.476098, b2=161.585836, b3=-155.698979, b4=66.801311,  b5=-13.280681;
    const c1= -0.007784,  c2=-0.322396,  c3=-2.400758,  c4=-2.549732,  c5=4.374664,   c6=2.938163;
    const d1= 0.007784,   d2=0.322396,   d3=2.400758,   d4=2.549732,   d5=4.374664,    d6=2.938163;

    let q, r, x;
    if (p < 0.02425) {
        q = Math.sqrt(-2*Math.log(p));
        x = (((((c1*q+c2)*q+c3)*q+c4)*q+c5)*q+c6)/
            ((((d1*q+d2)*q+d3)*q+d4)*q+d5)*q+1;
    } else if (p > 1-0.02425) {
        q = Math.sqrt(-2*Math.log(1-p));
        x = -(((((c1*q+c2)*q+c3)*q+c4)*q+c5)*q+c6)/
             ((((d1*q+d2)*q+d3)*q+d4)*q+d5)*q+1;
    } else {
        q = p - 0.5; r = q*q;
        x = (((((a1*r+a2)*r+a3)*r+a4)*r+a5)*r+a6)*q/
            (((((b1*r+b2)*r+b3)*r+b4)*r+b5)*r+1);
    }
    return x;
}

/**
 * CDF of standard normal distribution.
 * @param {number} z
 * @returns {number}
 */
function normalCDF(z) {
    return 0.5 * (1 + erf(z / Math.sqrt(2)));
}

/**
 * Error function approximation (Abramowitz and Stegun formula 7.1.26).
 * @param {number} x
 * @returns {number}
 */
function erf(x) {
    const sign = Math.sign(x);
    x = Math.abs(x);

    const a1 =  0.254829592,
          a2 = -0.284496736,
          a3 =  1.421413741,
          a4 = -1.453152027,
          a5 =  1.061405429,
          p  =  0.3275911;

    const t = 1/(1 + p*x);
    const y = 1 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t*Math.exp(-x*x);

    return sign * y;
}

/* ──────────────────────────────────────────────────────────────────
 * DriftMonitor – orchestrates consumption, detection, & publishing
 * ────────────────────────────────────────────────────────────────── */
class DriftMonitor {
    /**
     * @param {AbstractStrategy} strategy – detection strategy
     */
    constructor(strategy) {
        this.strategy = strategy;
        this.consumer = null;
        this.producer = null;
        this.subject  = new Subject();
        this.modelState = new Map(); // modelVersion -> { baseline:[], window:Deque, driftCount:int }
    }

    /* ───────── PUBLIC API ───────── */

    start() {
        this._initKafka();
        this._initPipeline();
    }

    stop() {
        this.consumer && this.consumer.disconnect();
        this.producer && this.producer.disconnect();
        this.subject.complete();
    }

    /* ───────── PRIVATE METHODS ───────── */

    _initKafka() {
        const { brokers, groupId, inferenceTopic } = DRIFT_CONFIG.kafka;

        // --- Consumer
        this.consumer = new Kafka.KafkaConsumer({
            'metadata.broker.list': brokers,
            'group.id': groupId,
            'enable.auto.commit': true,
        }, {});
        this.consumer
            .on('ready', () => {
                this.consumer.subscribe([ inferenceTopic ]);
                this.consumer.consume();
                console.info('[DriftMonitor] Kafka consumer ready');
            })
            .on('data', msg => {
                try {
                    const event = JSON.parse(msg.value.toString());
                    this.subject.next(event);
                } catch (e) {
                    console.error('[DriftMonitor] Failed to parse message', e);
                }
            })
            .on('event.error', err => console.error('[DriftMonitor] Consumer error', err))
            .connect();

        // --- Producer
        this.producer = new Kafka.Producer({
            'metadata.broker.list': brokers,
        });
        this.producer
            .on('ready', () => console.info('[DriftMonitor] Kafka producer ready'))
            .on('event.error', err => console.error('[DriftMonitor] Producer error', err))
            .connect();
    }

    _initPipeline() {
        // Aggregate events in 2-second micro-batches
        this.subject
            .pipe(bufferTime(2_000))
            .subscribe(events => {
                if (!events.length) return;
                for (const evt of events) this._processEvent(evt);
            });
    }

    /**
     * @param {Object} evt – inference outcome event
     * Expected shape: {
     *   modelVersion: 'abc-123',
     *   timestamp:    16801010101,
     *   sentimentBucket: 0|1|2, // 0=neg,1=neu,2=pos
     * }
     */
    _processEvent(evt) {
        const { modelVersion, sentimentBucket } = evt;
        if (typeof modelVersion !== 'string' || sentimentBucket == null) return;

        if (!this.modelState.has(modelVersion))
            this._initModel(modelVersion);

        const state = this.modelState.get(modelVersion);
        // Update baseline if not ready
        if (state.baselineEventCount < DRIFT_CONFIG.stats.baselineEvents) {
            state.baseline[sentimentBucket]++;
            state.baselineEventCount++;
            return;
        }

        // Update sliding window
        if (state.window.length >= DRIFT_CONFIG.stats.windowSize) {
            const oldest = state.window.shift();
            state.windowCounts[oldest]--;
        }
        state.window.push(sentimentBucket);
        state.windowCounts[sentimentBucket]++;

        // Perform detection once window filled
        if (state.window.length === DRIFT_CONFIG.stats.windowSize) {
            const drifted = this.strategy.detect(state.baseline, state.windowCounts);
            if (drifted) {
                driftDetectedCounter.inc({ model_version: modelVersion });
                state.driftStreak++;
                if (state.driftStreak >= DRIFT_CONFIG.stats.consecutiveDriftTrigger)
                    this._emitRetrain(modelVersion, evt.timestamp);
            } else {
                state.driftStreak = 0; // reset on stable window
            }
        }
    }

    _initModel(modelVersion) {
        this.modelState.set(modelVersion, {
            baseline:          [0,0,0], // 3-bucket sentiment distribution
            baselineEventCount: 0,
            window:            new Deque(),
            windowCounts:      [0,0,0],
            driftStreak:       0,
        });
    }

    _emitRetrain(modelVersion, ts) {
        const { controlTopic } = DRIFT_CONFIG.kafka;
        const payload = Buffer.from(JSON.stringify({
            type: 'RetrainingRequested',
            modelVersion,
            timestamp: ts,
            reason: 'ConceptDriftDetected',
        }));
        this.producer.produce(
            controlTopic,
            null,
            payload,
            modelVersion, // key
            Date.now()
        );
        retrainTriggeredCounter.inc({ model_version: modelVersion });
        console.warn(`[DriftMonitor] Retraining requested for model ${modelVersion}`);
        // Reset streak to avoid duplicate triggers until baseline refreshed
        this.modelState.get(modelVersion).driftStreak = 0;
    }
}

/* ──────────────────────────────────────────────────────────────────
 * Factory function – extensibility for other strategies
 * ────────────────────────────────────────────────────────────────── */

/**
 * Creates a drift detection strategy.
 * @param {'chi2'|'ks'|'kl'} type
 * @param {object} [opts]
 */
function createStrategy(type='chi2', opts={}) {
    switch (type) {
        case 'chi2': return new ChiSquaredStrategy(opts.alpha || DRIFT_CONFIG.stats.alpha);
        default: throw new RangeError(`Unknown strategy: ${type}`);
    }
}

/* ──────────────────────────────────────────────────────────────────
 * Module bootstrap (if run standalone)
 * ────────────────────────────────────────────────────────────────── */
if (require.main === module) {
    const strategy = createStrategy(process.env.DRIFT_STRATEGY || 'chi2');
    const monitor  = new DriftMonitor(strategy);
    monitor.start();

    // Graceful shutdown
    process.on('SIGINT', () => monitor.stop());
    process.on('SIGTERM', () => monitor.stop());
}

/* ──────────────────────────────────────────────────────────────────
 * Exports
 * ────────────────────────────────────────────────────────────────── */
module.exports = {
    DriftMonitor,
    createStrategy,
    ChiSquaredStrategy,
};
```