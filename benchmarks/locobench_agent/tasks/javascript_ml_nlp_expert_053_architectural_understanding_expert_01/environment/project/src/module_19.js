```javascript
'use strict';

/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: src/module_19.js
 * Purpose: Online model-monitoring service that consumes real-time
 *          toxicity-classification results, computes rolling metrics
 *          (accuracy, fairness gap, drift statistics) and emits
 *          MODEL_RETRAINING_REQUIRED events to Kafka whenever
 *          thresholds are violated.
 *
 * Author: AgoraPulse Engineering
 */

///////////////////////
// External Imports  //
///////////////////////

const { Kafka, CompressionTypes, logLevel } = require('kafkajs');
const {
    Subject,
    pipe,
} = require('rxjs');
const {
    bufferTime,
    filter,
    map,
    mergeMap,
    catchError,
} = require('rxjs/operators');
const _ = require('lodash');
const winston = require('winston');
const { v4: uuidv4 } = require('uuid');

///////////////////////
// Config & Defaults //
///////////////////////

const cfg = {
    kafkaBrokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    kafkaGroupId: process.env.KAFKA_GROUP_ID || 'agorapulse-model-monitor',
    inTopic: process.env.KAFKA_IN_TOPIC || 'classification.results.toxicity',
    outTopic: process.env.KAFKA_OUT_TOPIC || 'model.events',
    windowMs: parseInt(process.env.WINDOW_MS, 10) || 30_000,          // 30-second tumbling window
    minSamples: parseInt(process.env.MIN_SAMPLES, 10) || 100,         // min samples per window
    accuracyThreshold: parseFloat(process.env.ACC_THRESHOLD) || 0.90, // min acceptable accuracy
    fairnessGapThreshold: parseFloat(process.env.FAIR_GAP) || 0.10,   // max acceptable fairness gap
};

///////////////////////
// Logger Bootstrap  //
///////////////////////

const logger = winston.createLogger({
    level: process.env.LOG_LEVEL || 'info',
    transports: [
        new winston.transports.Console({
            format: winston.format.combine(
                winston.format.colorize(),
                winston.format.timestamp(),
                winston.format.printf(
                    ({ timestamp, level, message }) => `[${timestamp}] ${level}: ${message}`
                )
            ),
        }),
    ],
});

///////////////////
// Helper Types  //
///////////////////

/**
 * @typedef {Object} ClassificationResult
 * @property {string} modelId        – Model version hash/id.
 * @property {boolean} groundTruth   – The true toxicity label.
 * @property {boolean} prediction    – Predicted toxicity label by the model.
 * @property {string} protectedAttr  – A protected attribute (e.g., gender, race).
 * @property {number}  timestamp     – Epoch millis of event creation.
 */

///////////////////////////////
// Metrics Helper Functions  //
///////////////////////////////

/**
 * Compute basic confusion-matrix counts.
 * @param {ClassificationResult[]} batch
 */
function computeCounts(batch) {
    let tp = 0, fp = 0, tn = 0, fn = 0;
    for (const { groundTruth, prediction } of batch) {
        if (groundTruth && prediction) tp++;
        else if (!groundTruth && prediction) fp++;
        else if (!groundTruth && !prediction) tn++;
        else fn++; // groundTruth && !prediction
    }
    return { tp, fp, tn, fn };
}

/**
 * Compute accuracy score.
 * @param {{tp:number, fp:number, tn:number, fn:number}} c
 */
function accuracy(c) {
    const total = c.tp + c.fp + c.tn + c.fn;
    return total === 0 ? 0 : (c.tp + c.tn) / total;
}

/**
 * Compute False Negative Rate (FNR).
 */
function fnr(c) {
    const positives = c.tp + c.fn;
    return positives === 0 ? 0 : c.fn / positives;
}

/**
 * Compute fairness gap across protected attribute groups.
 * Here, we use difference in FNR between max and min groups.
 * @param {ClassificationResult[]} batch
 */
function fairnessGap(batch) {
    const grouped = _.groupBy(batch, 'protectedAttr');
    const fnrs = _.mapValues(grouped, g => fnr(computeCounts(g)));
    const gap = _.max(_.values(fnrs)) - _.min(_.values(fnrs));
    return { gap, perGroupFnr: fnrs };
}

////////////////////////////////////
//  Kafka Client Initialisation   //
////////////////////////////////////

const kafka = new Kafka({
    brokers: cfg.kafkaBrokers,
    clientId: 'agorapulse-model-monitor',
    logLevel: logLevel.ERROR,
});

const consumer = kafka.consumer({ groupId: cfg.kafkaGroupId });
const producer = kafka.producer();

////////////////////////////////////
//       Reactive Pipeline        //
////////////////////////////////////

/**
 * Subject that will receive every decoded ClassificationResult.
 * Leveraging RxJS for windowed aggregation.
 */
const classificationSubject = new Subject();

/**
 * Transform Kafka messages into structured objects and push
 * them into the RxJS pipeline.
 */
async function ingestLoop() {
    await consumer.connect();
    await consumer.subscribe({ topic: cfg.inTopic, fromBeginning: false });

    await consumer.run({
        eachMessage: async ({ topic, partition, message }) => {
            try {
                const payload = JSON.parse(message.value.toString());
                validatePayload(payload);
                classificationSubject.next(payload);
            } catch (err) {
                logger.warn(`Ignoring malformed message: ${err.message}`);
            }
        },
    });
}

/**
 * Basic payload validation.
 * @param {any} p
 * @throws {Error} if payload is invalid.
 */
function validatePayload(p) {
    const required = ['modelId', 'groundTruth', 'prediction', 'protectedAttr', 'timestamp'];
    for (const field of required) {
        if (!(field in p)) {
            throw new Error(`Missing field "${field}"`);
        }
    }
}

///////////////////////////
//   Monitoring Logic    //
///////////////////////////

/**
 * Main RxJS pipeline:
 * 1. Buffer events in tumbling windows.
 * 2. Filter out small windows (< minSamples).
 * 3. Compute metrics.
 * 4. If metrics violate thresholds, emit a
 *    MODEL_RETRAINING_REQUIRED event.
 */
function startMonitoring() {
    classificationSubject.pipe(
        bufferTime(cfg.windowMs),
        filter(batch => batch.length >= cfg.minSamples),
        map(batch => {
            const counts = computeCounts(batch);
            const acc = accuracy(counts);
            const { gap: fairnessGapValue, perGroupFnr } = fairnessGap(batch);

            return {
                batchSize: batch.length,
                modelId: _.first(batch).modelId,
                counts,
                accuracy: acc,
                fairnessGap: fairnessGapValue,
                perGroupFnr,
                windowStartedAt: _.first(batch).timestamp,
                windowEndedAt: _.last(batch).timestamp,
            };
        }),
        mergeMap(async (windowMetrics) => {
            const alerts = evaluateWindowMetrics(windowMetrics);
            if (alerts.length > 0) {
                await publishRetrainingEvent(windowMetrics, alerts);
            }
            return windowMetrics;
        }),
        catchError(err => {
            logger.error(`Error in monitoring pipeline: ${err.stack || err}`);
            // Swallow error so stream continues
            return [];
        })
    ).subscribe(windowMetrics => {
        logger.debug(
            `Window (${new Date(windowMetrics.windowStartedAt).toISOString()} – ${new Date(
                windowMetrics.windowEndedAt
            ).toISOString()}), size=${windowMetrics.batchSize}, ` +
                `acc=${windowMetrics.accuracy.toFixed(3)}, fairnessGap=${windowMetrics.fairnessGap.toFixed(3)}`
        );
    });
}

/**
 * Evaluate metrics for breaches.
 * @returns {string[]} – List of triggered alerts.
 */
function evaluateWindowMetrics({ accuracy: acc, fairnessGap: gap }) {
    const alerts = [];
    if (acc < cfg.accuracyThreshold) {
        alerts.push('ACCURACY_DROP');
    }
    if (gap > cfg.fairnessGapThreshold) {
        alerts.push('FAIRNESS_REGRESSION');
    }
    return alerts;
}

/**
 * Publish a MODEL_RETRAINING_REQUIRED event to Kafka.
 * @param {object} metrics
 * @param {string[]} alerts
 */
async function publishRetrainingEvent(metrics, alerts) {
    const event = {
        eventId: uuidv4(),
        eventType: 'MODEL_RETRAINING_REQUIRED',
        createdAt: Date.now(),
        modelId: metrics.modelId,
        alerts,
        metrics,
    };

    try {
        await producer.send({
            topic: cfg.outTopic,
            compression: CompressionTypes.GZIP,
            messages: [
                {
                    key: event.modelId,
                    value: JSON.stringify(event),
                },
            ],
        });
        logger.warn(
            `Emitted MODEL_RETRAINING_REQUIRED for model=${event.modelId}, alerts=${alerts.join(
                ','
            )}`
        );
    } catch (err) {
        logger.error(`Failed to publish retraining event: ${err.message}`);
    }
}

///////////////////////////
//   Service Lifecycle   //
///////////////////////////

async function bootstrap() {
    logger.info('🚀  AgoraPulse Model-Monitoring Service starting…');

    try {
        await producer.connect();
        startMonitoring();
        await ingestLoop();
    } catch (err) {
        logger.error(`Fatal error – shutting down: ${err.stack || err}`);
        process.exitCode = 1;
    }
}

bootstrap().catch((err) => {
    logger.error(`Unhandled bootstrap error: ${err.stack || err}`);
    process.exitCode = 1;
});

// Graceful shutdown
process.on('SIGINT', async () => {
    logger.info('SIGINT received – closing Kafka connections…');
    await Promise.allSettled([producer.disconnect(), consumer.disconnect()]);
    logger.info('Shutdown complete.');
    process.exit(0);
});

///////////////////////////
//  Module Exports (for
//  unit-testing)        //
///////////////////////////

module.exports = {
    computeCounts,
    accuracy,
    fnr,
    fairnessGap,
    evaluateWindowMetrics,
};
```