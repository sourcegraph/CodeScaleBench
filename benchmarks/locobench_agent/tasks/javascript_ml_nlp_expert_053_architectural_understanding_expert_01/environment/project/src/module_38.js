```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence ─ Module 38
 *
 * Real-Time Fairness & Drift Monitor
 * ----------------------------------
 * Listens to prediction events on a Kafka topic, maintains a sliding-window
 * cache of model outputs, computes fairness metrics (statistical parity,
 * equal opportunity) and basic concept-drift statistics (PSI), and emits
 * alert events whenever thresholds are breached.
 *
 * This module is intended to run inside the “model-monitoring” microservice
 * but can be imported by any Node process. All computational logic is
 * isolated from side-effects to support unit testing.
 *
 * Dependencies:
 *   npm i rxjs node-rdkafka fast-json-stable-stringify lodash
 */

'use strict';

import { fromEventPattern, timer, merge, EMPTY } from 'rxjs';
import {
    bufferTime,
    catchError,
    filter,
    map,
    mergeMap,
    tap,
    share,
} from 'rxjs/operators';
import Kafka from 'node-rdkafka';
import stringify from 'fast-json-stable-stringify';
import _ from 'lodash';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/**
 * Default configuration values. They can be overridden by environment
 * variables or by passing an explicit config object to `createMonitor()`.
 */
const DEFAULT_CONFIG = Object.freeze({
    kafka: {
        brokers: process.env.KAFKA_BROKERS || 'localhost:9092',
        inputTopic: process.env.PREDICTION_TOPIC || 'model.predictions',
        alertTopic: process.env.ALERT_TOPIC || 'model.alerts',
        groupId: process.env.KAFKA_GROUP_ID || 'fairness-monitor',
    },
    window: {
        // Sliding window size (in number of events)
        size: Number(process.env.WINDOW_SIZE) || 10_000,
        // Emit metrics to downstream consumers every N milliseconds
        emitIntervalMs: Number(process.env.EMIT_INTERVAL_MS) || 15_000,
    },
    thresholds: {
        // Maximum allowed difference between protected / unprotected groups
        statisticalParityDiff: Number(process.env.SP_DIFF) || 0.10,
        equalOpportunityDiff: Number(process.env.EO_DIFF) || 0.10,
        // Maximum allowed PSI change before drift alert is emitted
        psi: Number(process.env.PSI_THRESHOLD) || 0.2,
    },
});

// ---------------------------------------------------------------------------
// Domain Types
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} PredictionEvent
 * @property {string} modelId              – Deployed model identifier
 * @property {string} requestId            – Correlates back to user request
 * @property {number} timestamp            – Unix epoch millis, when prediction happened
 * @property {Object} features             – Raw feature dict (for PSI)
 * @property {number} score                – Raw model score
 * @property {0|1} prediction              – Final decision (e.g. toxic / not)
 * @property {0|1} label                   – Ground-truth (if available)
 * @property {Object<string,string>} attrs – Extra metadata (e.g. user country)
 * @property {'male'|'female'|'other'} attrs.gender – Example protected attr
 * @property {'white'|'black'|'latinx'|'asian'|'other'} attrs.race
 */

/**
 * @typedef {Object} AlertEvent
 * @property {string} type         – 'FAIRNESS_BREACH' | 'DRIFT_DETECTED'
 * @property {string} modelId
 * @property {number} timestamp
 * @property {Object} metrics
 */

// ---------------------------------------------------------------------------
// Utility Functions
// ---------------------------------------------------------------------------

/**
 * Compute Statistical Parity Difference for binary classification.
 *
 * P(Ŷ = 1 | A = unprotected) – P(Ŷ = 1 | A = protected)
 */
function statisticalParity(events, protectedPredicate) {
    const protectedGrp = events.filter(protectedPredicate);
    const unprotectedGrp = events.filter((e) => !protectedPredicate(e));

    const rate = (arr) =>
        arr.length === 0
            ? 0
            : arr.reduce((acc, e) => acc + e.prediction, 0) / arr.length;

    return rate(unprotectedGrp) - rate(protectedGrp);
}

/**
 * Compute Equal Opportunity Difference.
 *
 * P(Ŷ = 1 | Y = 1, A = unprotected) – P(Ŷ = 1 | Y = 1, A = protected)
 */
function equalOpportunity(events, protectedPredicate) {
    const positives = events.filter((e) => e.label === 1);

    const protectedPositives = positives.filter(protectedPredicate);
    const unprotectedPositives = positives.filter((e) => !protectedPredicate(e));

    const tpr = (arr) =>
        arr.length === 0
            ? 0
            : arr.reduce((acc, e) => acc + (e.prediction === 1 ? 1 : 0), 0) /
              arr.length;

    return tpr(unprotectedPositives) - tpr(protectedPositives);
}

/**
 * Population Stability Index between baseline and current feature distributions.
 *
 * PSI = Σ ( (curr_pct - base_pct) * ln(curr_pct / base_pct) )
 *
 * @param {number[]} baselineCounts
 * @param {number[]} currentCounts
 */
function populationStabilityIndex(baselineCounts, currentCounts) {
    const totalBaseline = _.sum(baselineCounts);
    const totalCurrent = _.sum(currentCounts);

    if (totalBaseline === 0 || totalCurrent === 0) return 0;

    return baselineCounts.reduce((psi, baseCount, idx) => {
        const currCount = currentCounts[idx];
        const basePct = baseCount / totalBaseline || 1e-6;
        const currPct = currCount / totalCurrent || 1e-6;
        return psi + (currPct - basePct) * Math.log(currPct / basePct);
    }, 0);
}

// ---------------------------------------------------------------------------
// Sliding Window Buffer
// ---------------------------------------------------------------------------

class SlidingWindow {
    /**
     * @param {number} capacity – Max number of events to keep in memory
     */
    constructor(capacity) {
        this.capacity = capacity;
        this.buffer = [];
    }

    push(event) {
        this.buffer.push(event);
        if (this.buffer.length > this.capacity) {
            // Remove oldest
            this.buffer.shift();
        }
    }

    toArray() {
        // Return shallow copy to avoid external mutation
        return this.buffer.slice();
    }

    size() {
        return this.buffer.length;
    }
}

// ---------------------------------------------------------------------------
// Kafka Helpers
// ---------------------------------------------------------------------------

function createKafkaConsumer({ brokers, groupId, topic }) {
    const consumer = new Kafka.KafkaConsumer(
        {
            'group.id': groupId,
            'metadata.broker.list': brokers,
            'enable.auto.commit': true,
        },
        {}
    );

    return new Promise((resolve) => {
        consumer.connect();
        consumer
            .on('ready', () => {
                consumer.subscribe([topic]);
                consumer.consume();
                resolve(consumer);
            })
            .on('event.error', (err) => {
                console.error(`[Kafka] Consumer error: ${err.message}`, err);
            });
    });
}

function createKafkaProducer({ brokers }) {
    const producer = new Kafka.Producer({
        'metadata.broker.list': brokers,
    });
    return new Promise((resolve) => {
        producer.connect();
        producer
            .on('ready', () => resolve(producer))
            .on('event.error', (err) => {
                console.error(`[Kafka] Producer error: ${err.message}`, err);
            });
    });
}

// ---------------------------------------------------------------------------
// Monitor Factory
// ---------------------------------------------------------------------------

/**
 * Factory that spins up a fully configured monitor.
 *
 * @param {Partial<typeof DEFAULT_CONFIG>} [override]
 * @returns {Promise<{stop: () => void}>}
 */
export async function createMonitor(override = {}) {
    const cfg = _.merge({}, DEFAULT_CONFIG, override);

    // -----------------------------------------------------------------------
    // Kafka Setup
    // -----------------------------------------------------------------------

    const consumer = await createKafkaConsumer({
        brokers: cfg.kafka.brokers,
        groupId: cfg.kafka.groupId,
        topic: cfg.kafka.inputTopic,
    });

    const producer = await createKafkaProducer({
        brokers: cfg.kafka.brokers,
    });

    // -----------------------------------------------------------------------
    // Observables
    // -----------------------------------------------------------------------

    const kafkaMessages$ = fromEventPattern(
        (handler) => consumer.on('data', handler),
        (handler) => consumer.off('data', handler)
    ).pipe(
        map(({ value }) => {
            try {
                return JSON.parse(value.toString());
            } catch (err) {
                console.error('[Monitor] Invalid JSON:', err);
                return null;
            }
        }),
        filter(Boolean),
        share()
    );

    const windowBuffer = new SlidingWindow(cfg.window.size);

    /**
     * Cache baseline distribution for PSI after first window is full.
     * Multi-model ready: baseline keyed by modelId + featureName.
     * { [modelId]: { [featureName]: number[] } }
     */
    const baselineDistributionMap = new Map();

    // Collect every incoming event into sliding window
    const collector$ = kafkaMessages$.pipe(
        tap((event) => windowBuffer.push(event))
    );

    /**
     * Heartbeat timer that triggers metric computation every N ms
     */
    const heartbeat$ = timer(cfg.window.emitIntervalMs, cfg.window.emitIntervalMs);

    /**
     * Metric computation stream
     */
    const compute$ = heartbeat$.pipe(
        mergeMap(() => {
            const events = windowBuffer.toArray();
            if (events.length < 50) {
                // Not enough data, skip
                return EMPTY;
            }

            const groupedByModel = _.groupBy(events, 'modelId');

            const alerts = [];

            // Per-model metrics
            Object.entries(groupedByModel).forEach(([modelId, modelEvents]) => {
                // ----- Fairness Metrics (gender) ----------------------------
                const spDiffGender = statisticalParity(
                    modelEvents,
                    (e) => e.attrs.gender === 'female'
                );
                const eoDiffGender = equalOpportunity(
                    modelEvents,
                    (e) => e.attrs.gender === 'female'
                );

                if (
                    Math.abs(spDiffGender) > cfg.thresholds.statisticalParityDiff ||
                    Math.abs(eoDiffGender) > cfg.thresholds.equalOpportunityDiff
                ) {
                    alerts.push({
                        type: 'FAIRNESS_BREACH',
                        modelId,
                        timestamp: Date.now(),
                        metrics: {
                            spDiffGender,
                            eoDiffGender,
                        },
                    });
                }

                // ----- Drift Metrics (PSI) ----------------------------------
                const featureName = 'score'; // Example numeric feature
                const currentScores = modelEvents.map((e) => e[featureName]);

                if (!baselineDistributionMap.has(modelId)) {
                    baselineDistributionMap.set(modelId, {});
                }
                const modelBaseline = baselineDistributionMap.get(modelId);

                const binCounts = (values, numBins = 10) => {
                    const min = Math.min(...values);
                    const max = Math.max(...values);
                    const binSize = (max - min) / numBins || 1;
                    const counts = Array(numBins).fill(0);
                    values.forEach((v) => {
                        const idx = Math.min(
                            numBins - 1,
                            Math.floor((v - min) / binSize)
                        );
                        counts[idx] += 1;
                    });
                    return counts;
                };

                const currentBins = binCounts(currentScores);
                if (!modelBaseline[featureName]) {
                    // Initialize baseline
                    modelBaseline[featureName] = currentBins;
                } else {
                    const psi = populationStabilityIndex(
                        modelBaseline[featureName],
                        currentBins
                    );
                    if (psi > cfg.thresholds.psi) {
                        alerts.push({
                            type: 'DRIFT_DETECTED',
                            modelId,
                            timestamp: Date.now(),
                            metrics: { psi },
                        });
                        // Update baseline for next comparisons
                        modelBaseline[featureName] = currentBins;
                    }
                }
            });

            return alerts;
        }),
        catchError((err, caught) => {
            console.error('[Monitor] Metric computation failed:', err);
            return caught;
        })
    );

    // -----------------------------------------------------------------------
    // Emit alerts back to Kafka
    // -----------------------------------------------------------------------

    const sendAlert = (alert) =>
        new Promise((resolve, reject) => {
            const payload = Buffer.from(stringify(alert));
            producer.produce(
                cfg.kafka.alertTopic,
                null,
                payload,
                alert.modelId, // key
                Date.now(),
                (err, offset) => {
                    if (err) {
                        console.error('[Monitor] Failed to produce alert', err);
                        return reject(err);
                    }
                    return resolve(offset);
                }
            );
        });

    const alert$ = compute$.pipe(
        mergeMap((alert) =>
            sendAlert(alert).catch((err) => {
                // Don't crash stream on producer errors
                console.error('[Monitor] Alert send error:', err);
                return null;
            })
        )
    );

    // -----------------------------------------------------------------------
    // Subscription
    // -----------------------------------------------------------------------

    const subscription = merge(collector$, alert$).subscribe({
        error: (err) => console.error('[Monitor] Stream error', err),
    });

    console.info('[Monitor] Fairness & Drift Monitor started.');

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    return {
        stop() {
            subscription.unsubscribe();
            consumer.disconnect();
            producer.disconnect();
            console.info('[Monitor] Stopped.');
        },
    };
}

// ---------------------------------------------------------------------------
// CLI Entrypoint (node src/module_38.js)
// ---------------------------------------------------------------------------
if (require.main === module) {
    createMonitor()
        .then((monitor) => {
            // Graceful shutdown
            process.on('SIGINT', () => {
                console.info('\n[Monitor] Caught SIGINT, shutting down...');
                monitor.stop();
                process.exit(0);
            });
        })
        .catch((err) => {
            console.error('[Monitor] Failed to start:', err);
            process.exit(1);
        });
}
```