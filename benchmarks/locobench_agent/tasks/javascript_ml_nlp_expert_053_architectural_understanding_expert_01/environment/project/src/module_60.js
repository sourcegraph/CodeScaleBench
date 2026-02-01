/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * Module: ModelPerformanceMonitor
 * File  : src/module_60.js
 *
 * Responsible for:
 *  ◦ Subscribing to stream of model-serving metrics (Kafka topic: model-metrics.*)
 *  ◦ Calculating rolling performance statistics in real-time via RxJS
 *  ◦ Detecting drift / threshold violations by delegating to pluggable Strategy instances
 *  ◦ Emitting alert events to an alert topic & optional Web-hook integrations
 *
 * Patterns showcased:
 *  ◦ Observer (RxJS Subjects as event bus)
 *  ◦ Strategy (different drift-detection algorithms)
 *  ◦ Factory  (resolve strategy from config at runtime)
 *
 * External deps: kafkajs, rxjs, axios, uuid
 */

'use strict';

/* ────────────────────────────────────────────────────
 * Imports
 * ──────────────────────────────────────────────────── */
const { Kafka, logLevel } = require('kafkajs');
const {
    Subject,
    operators: { bufferTime, filter, map, mergeMap, tap, timeoutWith },
} = require('rxjs');
const axios = require('axios').default;
const { v4: uuid } = require('uuid');

/* ────────────────────────────────────────────────────
 * Constants & Config
 * ──────────────────────────────────────────────────── */

const DEFAULT_KAFKA_BROKERS = process.env.KAFKA_BROKERS?.split(',') || ['localhost:9092'];
const METRICS_TOPIC = /^model-metrics\./;     // any partitioned topic that starts with model-metrics.
const ALERTS_TOPIC = 'model-alerts';

const DEFAULT_ROLLING_WINDOW_MS = 60_000;     // 1 minute sliding window
const DEFAULT_FLUSH_INTERVAL_MS = 5_000;      // flush every 5s

/* ────────────────────────────────────────────────────
 * Error Types
 * ──────────────────────────────────────────────────── */

class StrategyConfigurationError extends Error {}
class MetricsProcessingError extends Error {}
class AlertDispatchError extends Error {}

/* ────────────────────────────────────────────────────
 * Strategy Interfaces
 * ──────────────────────────────────────────────────── */

/**
 * @typedef {Object} MetricDatum
 * @property {string}  modelId
 * @property {string}  modelVersion
 * @property {number}  latencyMs
 * @property {number}  throughput
 * @property {number}  accuracy
 * @property {number}  precision
 * @property {number}  recall
 * @property {number}  f1
 * @property {string}  ts   – ISO timestamp emitted by the serving layer
 */

/**
 * Abstract Strategy
 * Must expose evaluate(metrics:Array<MetricDatum>): Promise<EvaluationResult>
 *
 * @typedef {Object} EvaluationResult
 * @property {boolean} drift
 * @property {string}  severity   – e.g. “warning”, “critical”
 * @property {string}  reason
 * @property {object}  context – free-form data that might help downstream consumers
 */
class DriftDetectionStrategy {
    /* eslint-disable-next-line no-unused-vars */
    async evaluate(windowedMetrics, modelMeta) {
        throw new Error('evaluate() must be implemented by subclass');
    }
}

/* ────────────────────────────────────────────────────
 * Strategy Implementations
 * ──────────────────────────────────────────────────── */

/**
 * A simple static threshold strategy: if any metric drops below config.thresholds
 * for more than config.toleranceCount occurrences in the rolling window,
 * flag drift.
 */
class ThresholdStrategy extends DriftDetectionStrategy {
    /**
     * @param {{
     *   thresholds: { accuracy?:number, f1?:number, precision?:number, recall?:number },
     *   toleranceCount?: number
     * }} cfg
     */
    constructor(cfg = {}) {
        super();
        if (!cfg.thresholds || Object.keys(cfg.thresholds).length === 0) {
            throw new StrategyConfigurationError('ThresholdStrategy requires at least one threshold');
        }
        this.thresholds = cfg.thresholds;
        this.toleranceCount = cfg.toleranceCount ?? 3;
    }

    async evaluate(windowedMetrics /*: MetricDatum[] */, modelMeta) {
        const violations = windowedMetrics.filter((m) =>
            Object.entries(this.thresholds).some(([metric, cut]) => m[metric] < cut),
        );

        const drift = violations.length >= this.toleranceCount;

        if (drift) {
            const offending = violations.slice(-1)[0]; // last violation
            return {
                drift: true,
                severity: 'critical',
                reason: `Metric(s) under threshold for ${violations.length} events`,
                context: { offending, modelMeta },
            };
        }
        return { drift: false };
    }
}

/**
 * Future placeholder: integrate more sophisticated statistical tests,
 * e.g., Kolmogorov–Smirnov, Population Stability Index, etc.
 */
class StatisticalDriftStrategy extends DriftDetectionStrategy {
    constructor(cfg = {}) {
        super();
        this.cfg = cfg;
    }

    async evaluate() {
        // TODO implement statistical drift detection
        return { drift: false };
    }
}

/* ────────────────────────────────────────────────────
 * Strategy Factory
 * ──────────────────────────────────────────────────── */
const StrategyFactory = {
    /**
     * @param {{type:string}} cfg
     * @returns {DriftDetectionStrategy}
     */
    create(cfg) {
        switch (cfg.type) {
            case 'threshold':
                return new ThresholdStrategy(cfg);
            case 'statistical':
                return new StatisticalDriftStrategy(cfg);
            default:
                throw new StrategyConfigurationError(`Unsupported strategy type: ${cfg.type}`);
        }
    },
};

/* ────────────────────────────────────────────────────
 * Model Registry Helper – fetch model metadata
 * ──────────────────────────────────────────────────── */

/**
 * Minimal MLflow-compatible client for retrieving model extra metadata
 * @param {string} modelId
 * @param {string} version
 * @returns {Promise<object|null>}
 */
async function fetchModelMeta(modelId, version) {
    const registryUrl = process.env.MODEL_REGISTRY_URL;
    if (!registryUrl) return null;

    try {
        const { data } = await axios.get(
            `${registryUrl}/api/2.0/mlflow/model-versions/get`,
            { params: { name: modelId, version } },
        );
        return data?.model_version ?? null;
    } catch (err) {
        console.warn('[ModelRegistry] Unable to fetch model metadata', err.message);
        return null;
    }
}

/* ────────────────────────────────────────────────────
 * Alert Dispatcher
 * ──────────────────────────────────────────────────── */

class AlertDispatcher {
    /**
     * @param {Producer} kafkaProducer kafkajs producer
     * @param {string[]} [webhooks] optional URLs to POST alert payloads
     */
    constructor(kafkaProducer, webhooks = []) {
        this.producer = kafkaProducer;
        this.webhooks = webhooks;
    }

    /**
     * @param {object} alertPayload – result of strategy plus metadata
     * @returns {Promise<void>}
     */
    async dispatch(alertPayload) {
        const payloadString = JSON.stringify(alertPayload);

        try {
            // 1. Kafka
            await this.producer.send({
                topic: ALERTS_TOPIC,
                messages: [{ key: alertPayload.modelId, value: payloadString }],
            });
        } catch (err) {
            throw new AlertDispatchError(`Kafka dispatch failed: ${err.message}`);
        }

        // 2. Web-hooks
        if (this.webhooks.length) {
            await Promise.allSettled(
                this.webhooks.map((url) =>
                    axios.post(url, alertPayload).catch((err) => {
                        console.warn(`[AlertWebhook] POST ${url} failed`, err.message);
                    }),
                ),
            );
        }
    }
}

/* ────────────────────────────────────────────────────
 * Main Monitor Class
 * ──────────────────────────────────────────────────── */

class ModelPerformanceMonitor {
    /**
     * @param {{
     *      kafkaBrokers?: string[],
     *      rollingWindowMs?: number,
     *      flushIntervalMs?: number,
     *      strategyConfig: {type:string, [k:string]:any},
     *      alertWebhooks?: string[]
     * }} options
     */
    constructor(options) {
        /* Configuration */
        this.kafkaBrokers = options.kafkaBrokers || DEFAULT_KAFKA_BROKERS;
        this.rollingWindowMs = options.rollingWindowMs ?? DEFAULT_ROLLING_WINDOW_MS;
        this.flushIntervalMs = options.flushIntervalMs ?? DEFAULT_FLUSH_INTERVAL_MS;
        this.strategy = StrategyFactory.create(options.strategyConfig);
        this.alertWebhooks = options.alertWebhooks ?? [];

        /* Internal State */
        this.kafka = new Kafka({
            clientId: 'model-performance-monitor',
            brokers: this.kafkaBrokers,
            logLevel: logLevel.WARN,
        });
        this.consumer = this.kafka.consumer({ groupId: `perf-monitor-${uuid()}` });
        this.producer = this.kafka.producer();

        /* RxJS stream to buffer incoming messages */
        this.metricSubject = new Subject();

        /* Bind handlers */
        this._setupPipeline();
    }

    /* create RxJS pipeline with rolling window buffer and strategy evaluation */
    _setupPipeline() {
        this.metricSubject
            .pipe(
                bufferTime(this.flushIntervalMs),
                filter((batch) => batch.length > 0),
                mergeMap(async (batch) => {
                    // fetch model meta once per batch (assumes same model in window)
                    const { modelId, modelVersion } = batch[0];
                    const modelMeta = await fetchModelMeta(modelId, modelVersion);
                    return { batch, modelMeta };
                }),
                mergeMap(async ({ batch, modelMeta }) => {
                    const evaluation = await this.strategy.evaluate(batch, modelMeta);
                    return { evaluation, batch, modelMeta };
                }),
                filter(({ evaluation }) => evaluation.drift === true),
                tap(({ evaluation, batch, modelMeta }) =>
                    this._emitAlert(batch, evaluation, modelMeta),
                ),
            )
            .subscribe({
                error: (err) => console.error('[MonitorPipeline] Stream error', err),
            });
    }

    async _emitAlert(batch, evaluation, modelMeta) {
        const cleanPayload = {
            id: uuid(),
            ts: new Date().toISOString(),
            modelId: batch[0].modelId,
            modelVersion: batch[0].modelVersion,
            evaluation,
            windowSize: batch.length,
            modelMeta,
        };
        try {
            await this.alertDispatcher.dispatch(cleanPayload);
            console.log('[Monitor] Alert emitted', cleanPayload.id);
        } catch (err) {
            console.error('[Monitor] Failed to dispatch alert', err);
        }
    }

    /* Subscribe to metrics topic(s) and push to subject */
    async _consume() {
        await this.consumer.subscribe({ topic: METRICS_TOPIC, fromBeginning: false });

        await this.consumer.run({
            eachMessage: async ({ message }) => {
                try {
                    const metric = JSON.parse(message.value.toString());
                    metric.tsIngested = Date.now();
                    this.metricSubject.next(metric);
                } catch (err) {
                    console.warn('[Monitor] Malformed metric payload', err.message);
                }
            },
        });
    }

    /* ───────── External Lifecycle API ───────── */

    async start() {
        console.log('[Monitor] Starting …');

        await Promise.all([this.consumer.connect(), this.producer.connect()]);
        this.alertDispatcher = new AlertDispatcher(this.producer, this.alertWebhooks);
        await this._consume();

        console.log('[Monitor] Ready. Listening for model metrics.');
    }

    async shutdown() {
        console.log('[Monitor] Shutting down …');
        await Promise.allSettled([
            this.consumer.disconnect().catch(() => {}),
            this.producer.disconnect().catch(() => {}),
        ]);
        this.metricSubject.complete();
        console.log('[Monitor] Bye!');
    }
}

/* ────────────────────────────────────────────────────
 * Module Exports
 * ──────────────────────────────────────────────────── */

module.exports = {
    ModelPerformanceMonitor,
    StrategyFactory,
    ThresholdStrategy,
    StatisticalDriftStrategy,
    AlertDispatcher,
    fetchModelMeta,
    // Error classes for external callers
    StrategyConfigurationError,
    MetricsProcessingError,
    AlertDispatchError,
};

/* ────────────────────────────────────────────────────
 * CLI bootstrap (when invoked directly)
 * ──────────────────────────────────────────────────── */
if (require.main === module) {
    (async () => {
        const monitor = new ModelPerformanceMonitor({
            strategyConfig: {
                type: 'threshold',
                thresholds: { accuracy: 0.8, f1: 0.75 },
                toleranceCount: 5,
            },
            alertWebhooks: process.env.ALERT_WEBHOOKS?.split(',') ?? [],
        });

        process.on('SIGINT', () => monitor.shutdown().then(() => process.exit(0)));
        process.on('SIGTERM', () => monitor.shutdown().then(() => process.exit(0)));

        try {
            await monitor.start();
        } catch (err) {
            console.error('[Monitor] Fatal error', err);
            process.exit(1);
        }
    })();
}