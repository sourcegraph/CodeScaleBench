```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: src/module_37.js
 *
 * Purpose:
 *   Real-Time Model-Performance & Drift Monitor.
 *   Consumes model-monitoring metrics from Kafka, aggregates them in a sliding
 *   window with RxJS, detects threshold violations, and publishes retraining
 *   events back to Kafka.
 *
 *   This module is intentionally written in JavaScript (ES2022) so it can be
 *   executed by Node.js without a build step in lightweight edge environments.
 *
 * Key Dependencies:
 *   - kafkajs         : battle-tested Kafka client
 *   - rxjs            : functional reactive data-flow
 *   - lodash          : utility helpers
 *   - ajv             : fast JSON-schema validator
 *
 * Usage:
 *   import { ModelDriftMonitor } from './module_37.js';
 *
 *   const monitor = new ModelDriftMonitor({
 *       kafkaConfig: { clientId: 'agorapulse-monitor', brokers: ['kafka:9092'] },
 *       sourceTopic: 'model.metrics',
 *       alertTopic : 'model.retraining.events',
 *       slidingWindowMs: 60_000,      // 1 minute
 *       evaluationIntervalMs: 15_000, // evaluate every 15s
 *       thresholds: {
 *           accuracy : 0.80,
 *           f1       : 0.78,
 *           fairness : 0.90
 *       }
 *   });
 *
 *   await monitor.start();
 *
 *   // …later
 *   await monitor.stop();
 */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, merge, timer } from 'rxjs';
import {
    bufferTime,
    filter,
    map,
    tap,
    catchError,
    share,
} from 'rxjs/operators';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import { isNil, meanBy } from 'lodash';

const DEFAULT_SCHEMA = {
    $id        : 'https://agorapulse.ai/schemas/modelMetric.json',
    type       : 'object',
    required   : ['modelVersion', 'metric', 'value', 'timestamp'],
    properties : {
        modelVersion : { type: 'string', minLength: 1 },
        metric       : { type: 'string', enum: ['accuracy', 'f1', 'fairness'] },
        value        : { type: 'number', minimum: 0, maximum: 1 },
        timestamp    : { type: 'string', format: 'date-time' },
    },
    additionalProperties: true,
};

/**
 * @typedef {Object} DriftMonitorConfig
 * @property {Object} kafkaConfig        – All options forwarded to new Kafka()
 * @property {string} sourceTopic        – Kafka topic to consume metrics from
 * @property {string} alertTopic         – Kafka topic for drift / retrain events
 * @property {number} slidingWindowMs    – How long the aggregation window lasts
 * @property {number} evaluationIntervalMs – How often to evaluate window
 * @property {Record<string, number>} thresholds – Threshold per metric key
 * @property {number} [maxBatchSize=500] – Maximum number of events per batch
 */

export class ModelDriftMonitor {
    /**
     * @param {DriftMonitorConfig} config
     */
    constructor(config) {
        this._validateCtorConfig(config);

        this.kafka                = new Kafka({ ...config.kafkaConfig, logLevel: logLevel.ERROR });
        this.consumer             = this.kafka.consumer({ groupId: 'agorapulse-drift-monitor' });
        this.producer             = this.kafka.producer();
        this.sourceTopic          = config.sourceTopic;
        this.alertTopic           = config.alertTopic;
        this.slidingWindowMs      = config.slidingWindowMs;
        this.evaluationIntervalMs = config.evaluationIntervalMs;
        this.thresholds           = config.thresholds;
        this.maxBatchSize         = config.maxBatchSize ?? 500;

        this.message$             = new Subject(); // hot stream of validated messages
        this.ajv                  = addFormats(new Ajv()).addSchema(DEFAULT_SCHEMA);
        this.validator            = this.ajv.getSchema(DEFAULT_SCHEMA.$id);

        this._running             = false;
        this._subscriptions       = [];
    }

    async start() {
        if (this._running) return;
        await Promise.all([this.consumer.connect(), this.producer.connect()]);

        await this.consumer.subscribe({ topic: this.sourceTopic, fromBeginning: false });

        // 1. Wire Kafka -> Subject
        await this.consumer.run({
            autoCommit: true,
            eachMessage: async ({ message }) => {
                try {
                    const parsed = JSON.parse(message.value.toString('utf8'));
                    if (this.validator(parsed)) {
                        this.message$.next(parsed);
                    } else {
                        console.warn('[DriftMonitor] Validation failed:', this.validator.errors);
                    }
                } catch (err) {
                    console.error('[DriftMonitor] Malformed message', err);
                }
            },
        });

        // 2. Build reactive pipeline
        this._composePipeline();

        this._running = true;
        console.info('[DriftMonitor] Started');
    }

    async stop() {
        if (!this._running) return;
        this._subscriptions.forEach((sub) => sub.unsubscribe());
        await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
        this._running = false;
        console.info('[DriftMonitor] Stopped');
    }

    // ---------------------------  Internal Helpers  --------------------------

    /**
     * Validates constructor config; throws on error.
     * @private
     */
    _validateCtorConfig(cfg) {
        const missing = [
            ['kafkaConfig', cfg.kafkaConfig],
            ['sourceTopic', cfg.sourceTopic],
            ['alertTopic', cfg.alertTopic],
            ['slidingWindowMs', cfg.slidingWindowMs],
            ['evaluationIntervalMs', cfg.evaluationIntervalMs],
            ['thresholds', cfg.thresholds],
        ]
            .filter(([, v]) => isNil(v))
            .map(([k]) => k);

        if (missing.length) {
            throw new Error(`[DriftMonitor] Missing required config: ${missing.join(', ')}`);
        }
        if (cfg.slidingWindowMs <= 0 || cfg.evaluationIntervalMs <= 0) {
            throw new Error('[DriftMonitor] slidingWindowMs and evaluationIntervalMs must be > 0');
        }
    }

    /**
     * Builds RxJS pipeline that aggregates metrics & triggers alerts.
     * @private
     */
    _composePipeline() {
        // Shared, multicasted stream of incoming messages
        const shared$ = this.message$.pipe(share());

        // Buffer over sliding window & evaluate every evaluationIntervalMs
        const buffered$ = shared$.pipe(
            bufferTime(this.slidingWindowMs, this.evaluationIntervalMs, this.maxBatchSize),
            filter((batch) => batch.length > 0),
        );

        // Evaluate drift for each window
        const evaluate$ = buffered$.pipe(
            map((batch) => this._evaluateWindow(batch)),
            filter((alert) => alert !== null),
            tap((alert) => this._emitAlert(alert)),
            catchError((err, caught) => {
                console.error('[DriftMonitor] Stream error', err);
                return caught;
            }),
        );

        // Keep reference for later disposal
        this._subscriptions.push(evaluate$.subscribe());
    }

    /**
     * Compute aggregated metrics and determine if thresholds are violated.
     * Returns an alert payload or null.
     *
     * @param {Array<Object>} batch
     * @returns {Object|null}
     * @private
     */
    _evaluateWindow(batch) {
        const metricsToCheck = Object.keys(this.thresholds);
        const alerts = [];

        metricsToCheck.forEach((metric) => {
            // Filter by metric
            const values = batch.filter((m) => m.metric === metric);
            if (values.length === 0) return;

            const average = meanBy(values, 'value');
            const threshold = this.thresholds[metric];

            if (average < threshold) {
                alerts.push({
                    metric,
                    average,
                    threshold,
                    window      : this.slidingWindowMs,
                    modelVersion: values[values.length - 1].modelVersion, // last version
                });
            }
        });

        if (alerts.length === 0) return null;

        return {
            type          : 'MODEL_PERFORMANCE_ALERT',
            triggeredAt   : new Date().toISOString(),
            alerts,
            batchSize     : batch.length,
            slidingWindowMs: this.slidingWindowMs,
        };
    }

    /**
     * Publishes alert to Kafka asynchronously.
     * @param {Object} alert
     * @private
     */
    async _emitAlert(alert) {
        try {
            await this.producer.send({
                topic: this.alertTopic,
                messages: [
                    {
                        key  : 'model-drift',
                        value: JSON.stringify(alert),
                    },
                ],
            });
            console.warn('[DriftMonitor] Alert published:', JSON.stringify(alert));
        } catch (err) {
            console.error('[DriftMonitor] Failed to publish alert', err);
        }
    }
}

// ---------------------------  Self-Executable (CLI)  -------------------------

if (require.main === module) {
    (async () => {
        try {
            const monitor = new ModelDriftMonitor({
                kafkaConfig: {
                    clientId: 'agorapulse-drift-cli',
                    brokers : process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
                },
                sourceTopic          : process.env.SOURCE_TOPIC ?? 'model.metrics',
                alertTopic           : process.env.ALERT_TOPIC ?? 'model.retraining.events',
                slidingWindowMs      : Number(process.env.WINDOW_MS) || 60_000,
                evaluationIntervalMs : Number(process.env.EVAL_MS) || 15_000,
                thresholds           : {
                    accuracy : Number(process.env.THRESH_ACCURACY) || 0.80,
                    f1       : Number(process.env.THRESH_F1) || 0.78,
                    fairness : Number(process.env.THRESH_FAIRNESS) || 0.90,
                },
            });

            await monitor.start();

            // Graceful shutdown
            const shutdown = async () => {
                console.info('Shutdown signal received…');
                await monitor.stop();
                process.exit(0);
            };
            process.on('SIGINT', shutdown);
            process.on('SIGTERM', shutdown);
        } catch (err) {
            console.error('[DriftMonitor] Fatal error', err);
            process.exit(1);
        }
    })();
}
```