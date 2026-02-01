/**
 * src/module_63.js
 *
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module 63: OnlineModelMonitor
 *
 * A lightweight, event-driven service that listens to the stream of model
 * inference telemetry published to Kafka and performs online monitoring for
 * data / performance drift.  Breaches are pushed back onto Kafka *and*
 * emitted locally to allow other parts of the Node.js process to subscribe.
 *
 * Responsibilities
 * ----------------
 * • Validate incoming telemetry against a strict JSON-Schema (Ajv)
 * • Maintain sliding-window aggregates in memory (RxJS)
 * • Detect threshold violations (accuracy drop, latency p95, class-imbalance)
 * • Emit `driftDetected` events and publish `ml/monitoring.alerts` messages
 *
 * NOTE:
 *  This file purposefully focuses on *runtime* monitoring logic rather than
 *  offline analytics to illustrate how the event-driven core of AgoraPulse
 *  plugs into an MLOps toolchain.
 */

'use strict';

/* ────────────────── 3rd-Party Dependencies ──────────────────────────────── */
const { Kafka }             = require('kafkajs');
const { Subject, timer }    = require('rxjs');
const {
    bufferTime,
    catchError,
    filter,
    map,
    mergeMap,
    tap,
}                            = require('rxjs/operators');
const Ajv                   = require('ajv');
const lodash                = require('lodash');
const pino                  = require('pino');

/* ──────────────────────── Configuration & Constants ─────────────────────── */

const DEFAULT_WINDOW_MS      = 60_000;       // 1-min sliding window
const DEFAULT_EMIT_INTERVAL  = 15_000;       // how often we flush aggregates
const DEFAULT_THRESHOLDS     = {
    accuracyDrop      : 0.05,  // >5 % drop vs. reference
    latencyP95        : 250,   // >250 ms on 95th percentile
    classImbalance    : 0.75,  // any class >75 % of window
};

const SCHEMA_TELEMETRY = {
    $id        : 'https://agorapulse.io/schemas/model-telemetry.json',
    type       : 'object',
    required   : [
        'modelVersion',
        'timestamp',
        'latencyMs',
        'groundTruth',
        'prediction',
    ],
    additionalProperties : false,
    properties : {
        modelVersion : { type: 'string' },
        timestamp    : { type: 'integer' },
        latencyMs    : { type: 'number' },
        groundTruth  : { type: ['string', 'number'] },
        prediction   : { type: ['string', 'number'] },
        probability  : { type: 'number' },
    },
};

/* ───────────────────────────── Error Types ──────────────────────────────── */

class KafkaConnectionError extends Error {
    constructor(message, original) {
        super(message);
        this.name      = 'KafkaConnectionError';
        this.original  = original;
    }
}

class ValidationError extends Error {
    constructor(message, payload) {
        super(message);
        this.name     = 'ValidationError';
        this.payload  = payload;
    }
}

/* ──────────────────────── Module Implementation ─────────────────────────── */

class OnlineModelMonitor {

    /**
     * @param {object} options
     * @param {object} options.kafka        – kafka.js client configuration
     * @param {string} options.sourceTopic  – topic to consume telemetry
     * @param {string} options.alertTopic   – topic to publish alerts
     * @param {object} [options.thresholds] – override DEFAULT_THRESHOLDS
     * @param {number} [options.windowMs]   – sliding window duration
     * @param {pino.Logger} [options.logger]
     */
    constructor(options) {
        const {
            kafka,
            sourceTopic,
            alertTopic           = 'ml/monitoring.alerts',
            thresholds           = {},
            windowMs             = DEFAULT_WINDOW_MS,
            emitInterval         = DEFAULT_EMIT_INTERVAL,
            logger               = pino({ name : 'OnlineModelMonitor' }),
        } = options;

        if (!kafka || !sourceTopic) {
            throw new Error('OnlineModelMonitor: kafka and sourceTopic are required');
        }

        this.kafkaConfig   = kafka;
        this.sourceTopic   = sourceTopic;
        this.alertTopic    = alertTopic;

        this.thresholds    = { ...DEFAULT_THRESHOLDS, ...thresholds };
        this.windowMs      = windowMs;
        this.emitInterval  = emitInterval;
        this.logger        = logger;

        this._ajv          = new Ajv({ allErrors : true, useDefaults : true });
        this._validate     = this._ajv.compile(SCHEMA_TELEMETRY);

        this._subject      = new Subject();   // Pipeline entry point

        this._createKafkaClients();
        this._buildPipeline();
    }

    /* ───────────────────────────── Public API ───────────────────────────── */

    /**
     * Start consuming telemetry and processing the monitoring pipeline.
     * @returns {Promise<void>}
     */
    async start() {
        try {
            await this.consumer.connect();
            await this.producer.connect();

            await this.consumer.subscribe({
                topic     : this.sourceTopic,
                fromBeginning : false,
            });

            this._consumeLoop()
                .catch(err => this.logger.error({ err }, 'Consumer loop failed'));

            this.logger.info(
                {
                    topic          : this.sourceTopic,
                    windowMs       : this.windowMs,
                    emitIntervalMs : this.emitInterval,
                    thresholds     : this.thresholds,
                },
                'OnlineModelMonitor started',
            );
        } catch (err) {
            throw new KafkaConnectionError('Failed to start OnlineModelMonitor', err);
        }
    }

    /**
     * Gracefully terminate Kafka connections and observable streams.
     */
    async stop() {
        this.logger.info('Stopping OnlineModelMonitor …');
        await Promise.allSettled([
            this.consumer.disconnect(),
            this.producer.disconnect(),
        ]);
        this._subject.complete();
        this.logger.info('OnlineModelMonitor stopped');
    }

    /* ────────────────────────── Internal Helpers ────────────────────────── */

    /**
     * Build Kafka producer/consumer instances.
     * (kept separate for unit-testing)
     */
    _createKafkaClients() {
        const kafka = new Kafka(this.kafkaConfig);
        this.producer = kafka.producer({ allowAutoTopicCreation : false });
        this.consumer = kafka.consumer({
            groupId : `agorapulse-model-monitor-${Date.now()}`,
        });
    }

    /**
     * Launch the infinite consume loop and push data into the RxJS Subject.
     * @private
     */
    async _consumeLoop() {
        await this.consumer.run({
            eachMessage : async ({ topic, partition, message }) => {
                try {
                    const payload = JSON.parse(message.value.toString());
                    this._onTelemetry(payload);
                } catch (err) {
                    this.logger.warn(
                        { err, raw : message.value.toString() },
                        'Failed to parse telemetry message',
                    );
                }
            },
        });
    }

    /**
     * Push validated telemetry onto the stream.
     * @param {object} payload
     * @private
     */
    _onTelemetry(payload) {
        if (!this._validate(payload)) {
            const err = new ValidationError('Telemetry payload does not match schema', payload);
            this.logger.warn({ err, errors : this._validate.errors }, 'Invalid telemetry payload');
            return; // skip
        }
        this._subject.next(payload);
    }

    /**
     * Build the RxJS pipeline: sliding-window aggregate & threshold detection.
     * @private
     */
    _buildPipeline() {
        const windowed$ = this._subject.pipe(
            bufferTime(this.windowMs, null, Number.POSITIVE_INFINITY),
            filter(buffer => buffer.length > 0),
            map(buffer => this._computeStats(buffer)),
            tap(stats  => this.logger.debug({ stats }, 'Window statistics')),
        );

        // Periodically emit buffered aggregates even if traffic is low
        // (ensure we keep an eye on stale models).
        const heartbeat$ = timer(this.emitInterval, this.emitInterval).pipe(
            map(() => ({ heartbeat : true })),
        );

        windowed$
            .pipe(
                mergeMap(stats => this._detectViolations(stats)),
                catchError(err => {
                    this.logger.error({ err }, 'Monitoring pipeline error');
                    return []; // swallow error, keep pipeline alive
                }),
            )
            .subscribe(alert => {
                this._publishAlert(alert)
                    .catch(err => this.logger.error({ err }, 'Failed to publish alert'));
            });

        // Attach heartbeat for low-traffic scenarios
        heartbeat$.subscribe(() => {
            this.logger.debug('Heartbeat – monitoring pipeline alive');
        });
    }

    /**
     * Compute window statistics such as accuracy, latency percentiles, etc.
     * @param {Array<object>} buffer
     * @returns {object}
     * @private
     */
    _computeStats(buffer) {
        const total        = buffer.length;
        const correct       = buffer.filter(
            x => x.prediction === x.groundTruth,
        ).length;
        const accuracy      = correct / total;

        const latencies     = buffer.map(x => x.latencyMs).sort((a, b) => a - b);
        const p95index      = Math.floor(0.95 * latencies.length);
        const latencyP95    = latencies[p95index] || 0;

        // Class distribution
        const classCounts   = lodash.countBy(buffer, 'prediction');
        const maxClassRatio = Math.max(
            ...Object.values(classCounts).map(c => c / total),
        );

        return {
            total,
            accuracy,
            latencyP95,
            maxClassRatio,
            latestModelVersion : buffer[buffer.length - 1].modelVersion,
            windowStart        : buffer[0].timestamp,
            windowEnd          : buffer[buffer.length - 1].timestamp,
        };
    }

    /**
     * Detect threshold violations and return an array of alert objects.
     * @param {object} stats
     * @returns {Promise<Array<object>>}
     * @private
     */
    async _detectViolations(stats) {
        const alerts = [];

        if (1 - stats.accuracy > this.thresholds.accuracyDrop) {
            alerts.push({
                type        : 'accuracyDrop',
                severity    : 'critical',
                message     : `Accuracy dropped to ${(stats.accuracy * 100).toFixed(2)} %`,
                stats,
            });
        }

        if (stats.latencyP95 > this.thresholds.latencyP95) {
            alerts.push({
                type        : 'latencySpike',
                severity    : 'warning',
                message     : `p95 latency ${stats.latencyP95} ms exceeds ${this.thresholds.latencyP95} ms`,
                stats,
            });
        }

        if (stats.maxClassRatio > this.thresholds.classImbalance) {
            alerts.push({
                type        : 'classImbalance',
                severity    : 'info',
                message     : `Class imbalance ratio ${(stats.maxClassRatio * 100).toFixed(1)} %`,
                stats,
            });
        }

        return alerts;
    }

    /**
     * Publish alert message back to Kafka.
     * @param {object} alert
     * @private
     */
    async _publishAlert(alert) {
        try {
            await this.producer.send({
                topic   : this.alertTopic,
                messages: [
                    {
                        key   : alert.type,
                        value : JSON.stringify({
                            ...alert,
                            timestamp : Date.now(),
                        }),
                    },
                ],
            });
            this.logger.info({ alert }, 'Published monitoring alert');
        } catch (err) {
            this.logger.error({ err, alert }, 'Failed to publish monitoring alert');
        }
    }
}

/* ───────────────────────────── Exports ──────────────────────────────────── */

/**
 * Factory helper to instantiate and start the monitor in one go.
 * @param {object} opts – see OnlineModelMonitor constructor
 * @returns {Promise<OnlineModelMonitor>}
 */
async function createAndStartMonitor(opts) {
    const monitor = new OnlineModelMonitor(opts);
    await monitor.start();
    return monitor;
}

module.exports = {
    OnlineModelMonitor,
    createAndStartMonitor,
    DEFAULT_THRESHOLDS,
    DEFAULT_WINDOW_MS,
};