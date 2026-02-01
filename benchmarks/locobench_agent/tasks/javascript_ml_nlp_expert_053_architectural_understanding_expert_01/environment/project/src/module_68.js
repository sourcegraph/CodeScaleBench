```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence (ml_nlp)
 * ---------------------------------------------------------
 * Module 68 – Toxicity Spike Monitor
 *
 * This module listens to the real-time toxicity score stream produced by the
 * ML model–serving layer and detects statistically significant spikes that
 * may indicate coordinated harassment or model degradation.  Once a spike is
 * detected it publishes a `TOXICITY_SPIKE_DETECTED` domain event to Kafka so
 * that downstream workflows (auto-moderation rules, model retraining triggers,
 * alerting dashboards, etc.) can react in near real-time.
 *
 * Design notes:
 *  • Built around RxJS for expressive, back-pressure-aware streaming logic.
 *  • Uses an adaptive Exponential Moving Average (EMA) for the baseline.
 *  • Spike threshold is configurable via
 *      – absolute delta (score > X)  OR
 *      – relative delta (% over EMA) OR
 *      – z-score (std-dev over EMA)  – default
 *  • Fully resilient against stream stalls, Kafka outages, and invalid data.
 *
 *  Author: agora-pulse-core
 *  License: MIT
 */

import { Kafka, logLevel as KafkaLogLevel } from 'kafkajs';
import {
    Observable,
    filter,
    map,
    merge,
    retry,
    share,
    tap,
    bufferTime,
    throttleTime,
} from 'rxjs';

import { mean, std } from 'mathjs';

/* -------------------------------------------------------------------------- */
/*                                   Types                                    */
/* -------------------------------------------------------------------------- */

/**
 * @typedef {Object} ToxicityScore
 * @property {string} messageId   - UUID of the social-network message.
 * @property {number} score       - Toxicity score in range [0, 1].
 * @property {number} timestamp   - Unix epoch millis.
 */

/**
 * @typedef {'absolute' | 'relative' | 'zScore'} ThresholdMode
 */

/**
 * @typedef {Object} SpikeDetectorConfig
 * @property {Observable<ToxicityScore>} stream          - RxJS stream of toxicity scores.
 * @property {number} [emaAlpha=0.1]                     - Smoothing factor for EMA (0 < α ≤ 1).
 * @property {ThresholdMode} [mode='zScore']             - Spike evaluation mode.
 * @property {number} [absoluteThreshold=0.9]            - Minimum score (abs mode).
 * @property {number} [relativeThreshold=0.25]           - Percent over baseline (rel mode).
 * @property {number} [zThreshold=3]                     - Z-score cutoff (zScore mode).
 * @property {number} [minConsecutive=3]                 - Min consecutive spikes to trigger.
 * @property {number} [summaryFrequencySec=60]           - Frequency of summary reports.
 * @property {Kafka}  kafka                              - Pre-configured Kafka client.
 * @property {string} topic                              - Kafka topic to publish events.
 */

/* -------------------------------------------------------------------------- */
/*                              Helper utilities                              */
/* -------------------------------------------------------------------------- */

/**
 * Simple Exponential Moving Average tracker.
 */
class EMA {
    /**
     * @param {number} alpha
     */
    constructor(alpha = 0.1) {
        this.alpha = alpha;
        this.initialized = false;
        this.value = 0;
    }

    /**
     * Update EMA with the next observation.
     * @param {number} x
     * @returns {number} current EMA value
     */
    update(x) {
        if (!Number.isFinite(x)) return this.value;
        if (!this.initialized) {
            this.value = x;
            this.initialized = true;
            return this.value;
        }
        this.value = this.alpha * x + (1 - this.alpha) * this.value;
        return this.value;
    }
}

/* -------------------------------------------------------------------------- */
/*                             Spike Detector Core                            */
/* -------------------------------------------------------------------------- */

/**
 * Build the toxicity spike detection pipeline.
 * @param {SpikeDetectorConfig} cfg
 * @returns {{ start(): void, stop(): Promise<void> }}
 */
export function createToxicitySpikeDetector(cfg) {
    validateConfig(cfg);

    const ema = new EMA(cfg.emaAlpha);
    let consecutiveCounter = 0;
    let kafkaProducer;

    /**
     * Determine if current sample is a spike.
     * @param {number} value
     * @returns {boolean}
     */
    function isSpike(value) {
        const baseline = ema.update(value);
        switch (cfg.mode) {
            case 'absolute':
                return value >= cfg.absoluteThreshold;
            case 'relative':
                return value >= baseline * (1 + cfg.relativeThreshold);
            case 'zScore':
            default:
                // calculate z-score assuming EMA as mean, fallback std=0.1
                const z = baseline === 0 ? 0 : (value - baseline) / (cfg.std ?? 0.1);
                return z >= cfg.zThreshold;
        }
    }

    /**
     * Publish event to Kafka.
     * @param {ToxicityScore} sample
     * @param {number} baseline
     */
    async function publishSpike(sample, baseline) {
        const payload = {
            type: 'TOXICITY_SPIKE_DETECTED',
            version: 1,
            data: {
                messageId: sample.messageId,
                score: sample.score,
                baseline,
                timestamp: sample.timestamp,
            },
        };

        try {
            await kafkaProducer.send({
                topic: cfg.topic,
                messages: [{ key: sample.messageId, value: JSON.stringify(payload) }],
            });
        } catch (err) {
            console.error('[ToxicitySpikeDetector] Kafka publish failed:', err);
        }
    }

    /**
     * Start pipeline.
     */
    async function start() {
        kafkaProducer = cfg.kafka.producer();
        await kafkaProducer.connect();

        const shared$ = cfg.stream.pipe(
            // Guard against faulty data.
            filter(s => Number.isFinite(s?.score) && s.score >= 0 && s.score <= 1),
            share(),
        );

        /* -------------------------------- Spike Path ------------------------------- */
        const spikeSub = shared$
            .pipe(
                filter(s => {
                    const spike = isSpike(s.score);
                    if (spike) {
                        consecutiveCounter += 1;
                    } else {
                        consecutiveCounter = 0;
                    }
                    return spike && consecutiveCounter >= cfg.minConsecutive;
                }),
                throttleTime(5000), // de-bounce to avoid storm
                tap(async s => {
                    await publishSpike(s, ema.value);
                    // reset counter after publishing
                    consecutiveCounter = 0;
                }),
                retry({ delay: 500 }),
            )
            .subscribe({
                error: err => console.error('[ToxicitySpikeDetector] Spike stream error:', err),
            });

        /* -------------------------- Periodic Summary Path -------------------------- */
        const summarySub = shared$
            .pipe(
                bufferTime(cfg.summaryFrequencySec * 1000),
                filter(buf => buf.length > 0),
                map(buf => {
                    const scores = buf.map(s => s.score);
                    return {
                        timestamp: Date.now(),
                        count: buf.length,
                        mean: mean(scores),
                        stdDev: std(scores) || 0,
                        max: Math.max(...scores),
                    };
                }),
                tap(summary => {
                    // Expose aggregated std-dev to spike logic
                    cfg.std = summary.stdDev;
                }),
                tap(async summary => {
                    try {
                        await kafkaProducer.send({
                            topic: cfg.topic,
                            messages: [
                                {
                                    key: `summary-${summary.timestamp}`,
                                    value: JSON.stringify({
                                        type: 'TOXICITY_SUMMARY',
                                        version: 1,
                                        data: summary,
                                    }),
                                },
                            ],
                        });
                    } catch (err) {
                        console.error('[ToxicitySpikeDetector] Kafka summary publish failed:', err);
                    }
                }),
                retry({ delay: 1000 }),
            )
            .subscribe({
                // Sink
                next: () => {},
                error: err => console.error('[ToxicitySpikeDetector] Summary stream error:', err),
            });

        console.info('[ToxicitySpikeDetector] Started.');
        return { spikeSub, summarySub };
    }

    /**
     * Stop pipeline.
     */
    async function stop() {
        if (kafkaProducer) {
            await kafkaProducer.disconnect().catch(() => {});
        }
        console.info('[ToxicitySpikeDetector] Stopped.');
    }

    return { start, stop };
}

/* -------------------------------------------------------------------------- */
/*                              Helper functions                              */
/* -------------------------------------------------------------------------- */

function validateConfig(cfg) {
    if (!cfg.stream || !(cfg.stream instanceof Observable)) {
        throw new TypeError('cfg.stream must be an RxJS Observable');
    }
    if (!cfg.kafka || !(cfg.kafka instanceof Kafka)) {
        throw new TypeError('cfg.kafka must be an instance of kafkajs.Kafka');
    }
    if (!cfg.topic) throw new Error('cfg.topic is required');
    cfg.mode = cfg.mode ?? 'zScore';
    cfg.emaAlpha = clamp(cfg.emaAlpha ?? 0.1, 0.01, 0.5);
    cfg.absoluteThreshold = clamp(cfg.absoluteThreshold ?? 0.9, 0, 1);
    cfg.relativeThreshold = clamp(cfg.relativeThreshold ?? 0.2, 0, 1);
    cfg.zThreshold = cfg.zThreshold ?? 3;
    cfg.minConsecutive = cfg.minConsecutive ?? 3;
    cfg.summaryFrequencySec = cfg.summaryFrequencySec ?? 60;
}

function clamp(x, min, max) {
    return Math.min(Math.max(x, min), max);
}

/* -------------------------------------------------------------------------- */
/*                               Example Usage                                */
/* -------------------------------------------------------------------------- */
/*
import { fromEventPattern } from 'rxjs';
import { Kafka } from 'kafkajs';
import { createToxicitySpikeDetector } from './module_68.js';

// Fake toxicity stream.
const toxicity$ = fromEventPattern(handler => {
    const id = setInterval(() => {
        handler({
            messageId: crypto.randomUUID(),
            score: Math.random(), // demo
            timestamp: Date.now(),
        });
    }, 300);
    return () => clearInterval(id);
});

const kafka = new Kafka({
    brokers: ['localhost:9092'],
    clientId: 'agorapulse-detectors',
    logLevel: KafkaLogLevel.WARN,
});

const detector = createToxicitySpikeDetector({
    stream: toxicity$,
    kafka,
    topic: 'ap.events.toxicity',
});

detector.start();

// gracefully shutdown
process.on('SIGINT', async () => {
    await detector.stop();
    process.exit(0);
});
*/
```