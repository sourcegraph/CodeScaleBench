```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * ------------------------------------------------
 * Module: src/module_36.js
 * Responsibility: End-to-end latency & consumer-lag guardrail for the event-driven
 *                 core.  Continuously monitors Kafka consumer-group offsets and
 *                 RxJS micro-pipeline latency streams, emitting domain events
 *                 whenever SLOs are violated.  Down-stream subscribers (e.g.
 *                 auto-scaling, model re-training, alerting services) can react
 *                 in real time.
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

'use strict';

/* ────────────────────────────────────────────────────────────
 * External dependencies
 * ──────────────────────────────────────────────────────────── */
const { EventEmitter }              = require('events');
const { Kafka, logLevel }           = require('kafkajs');
const { Histogram, Gauge, register }= require('prom-client');
const { Observable, merge, timer }  = require('rxjs');
const { filter, tap, throttleTime } = require('rxjs/operators');
const pino                          = require('pino');

/* ────────────────────────────────────────────────────────────
 * Constants & Configuration
 * ──────────────────────────────────────────────────────────── */
const DEFAULT_KAFKA_BROKERS          = (process.env.KAFKA_BROKERS || 'localhost:9092').split(',');
const DEFAULT_CONSUMER_GROUP         = process.env.KAFKA_CONSUMER_GROUP || 'agorapulse.core';
const POLL_INTERVAL_MS               = 5_000;   // How often to poll Kafka lag (ms)
const PIPELINE_LATENCY_SLO_MS        = 1_500;   // Max acceptable RxJS stage latency
const KAFKA_LAG_SLO_MESSAGES         = 3_000;   // Max acceptable consumer lag
const METRICS_PREFIX                 = 'agorapulse_lag_monitor_';

/* ────────────────────────────────────────────────────────────
 * Metrics
 * ──────────────────────────────────────────────────────────── */
const kafkaLagGauge = new Gauge({
    name      : `${METRICS_PREFIX}kafka_consumer_lag`,
    help      : 'Current Kafka consumer-group lag',
    labelNames: ['topic', 'partition']
});

const pipelineLatencyHist = new Histogram({
    name      : `${METRICS_PREFIX}pipeline_latency_ms`,
    help      : 'Observed end-to-end RxJS pipeline latency',
    buckets   : [50, 100, 250, 500, 1_000, 1_500, 3_000, 5_000]
});

/* ────────────────────────────────────────────────────────────
 * Helper: Create pino logger with sensible defaults
 * ──────────────────────────────────────────────────────────── */
function createLogger(moduleName) {
    return pino({
        name: moduleName,
        level: process.env.LOG_LEVEL || 'info',
        base: undefined       // Avoid pid, hostname clutter in lambdas/containers
    });
}

/* ────────────────────────────────────────────────────────────
 * RealTimeLagMonitor
 * ──────────────────────────────────────────────────────────── */
class RealTimeLagMonitor extends EventEmitter {
    /**
     * @param {Object}                cfg
     * @param {Observable<number>}    latency$   Observable emitting latency in ms
     */
    constructor(cfg, latency$) {
        super();

        /* Config merge with sane defaults */
        this.cfg = Object.freeze({
            kafkaBrokers  : cfg.brokers   || DEFAULT_KAFKA_BROKERS,
            consumerGroup : cfg.groupId   || DEFAULT_CONSUMER_GROUP,
            pollIntervalMs: cfg.pollEvery || POLL_INTERVAL_MS,
            lagSLO        : cfg.lagSLOMessages || KAFKA_LAG_SLO_MESSAGES,
            latencySLO    : cfg.pipelineLatencySLO || PIPELINE_LATENCY_SLO_MS
        });

        /* Logger */
        this.log = createLogger('RealTimeLagMonitor');

        /* Kafka client (lazily connected on start) */
        this.kafka = new Kafka({
            clientId : 'agorapulse-lag-monitor',
            brokers  : this.cfg.kafkaBrokers,
            logLevel : logLevel.NOTHING // pino handles logging
        });

        /* RxJS latency observable */
        this.latency$ = latency$;

        /* Lifecycle flag */
        this.stopped = false;
    }

    /* ──────────────────────────────
     * Public API
     * ────────────────────────────── */

    /**
     * Establishes connection to Kafka Admin client and starts polling as well
     * as latency subscriptions. Returns Promise<void>.
     */
    async start() {
        if (this.admin) {
            this.log.warn('LagMonitor already started');
            return;
        }

        this.admin = this.kafka.admin();
        await this.admin.connect();
        this.log.info({ brokers: this.cfg.kafkaBrokers }, 'Kafka admin connected');

        /* Kick off periodic lag polling */
        this._pollLoop();

        /* Subscribe to pipeline latency stream */
        this._subscribeToLatency();

        this.log.info('RealTimeLagMonitor started');
    }

    /**
     * Graceful shutdown
     */
    async stop() {
        this.stopped = true;

        if (this.latencySub) {
            this.latencySub.unsubscribe();
        }

        if (this.admin) {
            await this.admin.disconnect();
            this.admin = null;
        }

        this.log.info('RealTimeLagMonitor stopped');
    }

    /* ──────────────────────────────
     * Private helpers
     * ────────────────────────────── */

    /**
     * Poll Kafka for current lag and evaluate against SLO.
     */
    async _pollKafkaLag() {
        try {
            const topicPartitions = await this.admin.fetchTopicOffsetsByTimestamp(Date.now());

            const groupOffsets = await this.admin.fetchOffsets({
                groupId: this.cfg.consumerGroup
            });

            // The returned data structures differ; unify into map for lookup
            const latestOffsetMap = new Map();     // Key: `${topic}:${partition}`
            topicPartitions.forEach(({ topic, partitions }) => {
                partitions.forEach(p => {
                    latestOffsetMap.set(`${topic}:${p.partition}`, BigInt(p.offset));
                });
            });

            const lagSummary = groupOffsets
                .flatMap(record => record.partitions.map(p => ({
                    topic     : record.topic,
                    partition : p.partition,
                    consumerOffset: BigInt(p.offset),
                    latestOffset  : latestOffsetMap.get(`${record.topic}:${p.partition}`) || BigInt(0)
                })))
                .map(p => ({
                    ...p,
                    lag: p.latestOffset - p.consumerOffset
                }));

            /* Record metrics */
            lagSummary.forEach(({ topic, partition, lag }) => {
                kafkaLagGauge.labels(topic, String(partition)).set(Number(lag));
            });

            /* Evaluate SLOs */
            const violators = lagSummary.filter(p => p.lag > BigInt(this.cfg.lagSLO));

            if (violators.length) {
                /* Emit service-level event */
                const payload = {
                    type      : 'KAFKA_CONSUMER_LAG_VIOLATION',
                    timestamp : Date.now(),
                    violators : violators.map(v => ({
                        topic     : v.topic,
                        partition : v.partition,
                        lag       : Number(v.lag)
                    }))
                };

                this.emit('slo.violation', payload);
                this.log.warn({ payload }, 'Kafka consumer lag violation detected');
            }

        } catch (err) {
            this.log.error({ err }, 'Failed to poll Kafka lag');
            this.emit('error', err);
        }
    }

    /**
     * Starts background loop for lag polling until stopped=true
     */
    _pollLoop() {
        const loop = async () => {
            if (this.stopped) return;
            await this._pollKafkaLag();
            setTimeout(loop, this.cfg.pollIntervalMs);
        };
        loop().catch(err => {
            this.log.error({ err }, 'Lag polling loop crashed');
        });
    }

    /**
     * Subscribes to RxJS latency observable and checks SLO adherence.
     */
    _subscribeToLatency() {
        if (!this.latency$ || !(this.latency$ instanceof Observable)) {
            this.log.warn('No latency observable supplied; latency monitoring disabled');
            return;
        }

        /* Reduce noise with throttle; record metric & check SLO */
        this.latencySub = this.latency$
            .pipe(
                throttleTime(250),
                tap(latencyMs => pipelineLatencyHist.observe(latencyMs)),
                filter(latencyMs => latencyMs >= this.cfg.latencySLO)
            )
            .subscribe({
                next: latencyMs => {
                    const payload = {
                        type      : 'PIPELINE_LATENCY_VIOLATION',
                        timestamp : Date.now(),
                        latencyMs
                    };

                    this.emit('slo.violation', payload);
                    this.log.warn({ latencyMs }, 'Pipeline latency violation detected');
                },
                error: err => {
                    this.log.error({ err }, 'Latency observable emitted error');
                    this.emit('error', err);
                }
            });
    }

    /* ──────────────────────────────
     * Expose Prometheus metrics in text format
     * ────────────────────────────── */
    static metrics() {
        return register.metrics();
    }
}

/* ────────────────────────────────────────────────────────────
 * Factory
 * ──────────────────────────────────────────────────────────── */

/**
 * Factory method for creating a RealTimeLagMonitor
 *
 * @param {Object}             cfg          Configuration (brokers, groupId, etc.)
 * @param {Observable<number>} latency$     RxJS stream emitting latency in ms
 * @returns {RealTimeLagMonitor}
 */
function createLagMonitor(cfg = {}, latency$) {
    return new RealTimeLagMonitor(cfg, latency$);
}

/* ────────────────────────────────────────────────────────────
 * Exports
 * ──────────────────────────────────────────────────────────── */
module.exports = {
    createLagMonitor,
    RealTimeLagMonitor
};
```