'use strict';

/**
 * Model Monitoring and Alert Service
 * ----------------------------------
 * Listens to real-time model serving metrics, evaluates them against
 * configurable alerting rules, and emits domain events when thresholds
 * are breached. Designed to be extended with custom rule strategies and to
 * integrate seamlessly with AgoraPulse’s event-driven architecture.
 *
 * Uses:
 *  - kafkajs for durable stream ingestion / emission
 *  - rxjs for functional, reactive transformations
 *  - winston for structured logging
 *
 * All heavy-weight objects (Kafka connections, logger, etc.) are singletons
 * to avoid resource leaks in serverless / worker environments.
 */

const { Kafka, logLevel } = require('kafkajs');
const { fromEventPattern } = require('rxjs');
const { bufferTime, filter, catchError } = require('rxjs/operators');
const { v4: uuidv4 } = require('uuid');
const _ = require('lodash');
const winston = require('winston');

/* ------------------------------------------------------------------------ */
/*                            Configuration Helpers                         */
/* ------------------------------------------------------------------------ */

const CONFIG = {
    kafkaBrokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    metricsTopic: process.env.METRICS_TOPIC || 'model.monitoring.metrics',
    alertTopic: process.env.ALERT_TOPIC || 'model.monitoring.alerts',
    consumerGroupId: process.env.CONSUMER_GROUP_ID || 'agorapulse-monitoring',
    ruleRefreshMs: Number(process.env.RULE_REFRESH_MS) || 30_000,
    bufferWindowMs: Number(process.env.BUFFER_WINDOW_MS) || 10_000
};

/* ------------------------------------------------------------------------ */
/*                              Logger Singleton                            */
/* ------------------------------------------------------------------------ */

const logger = winston.createLogger({
    level: process.env.LOG_LEVEL || 'info',
    format: winston.format.combine(
        winston.format.timestamp(),
        winston.format.errors({ stack: true }),
        winston.format.splat(),
        winston.format.json()
    ),
    transports: [new winston.transports.Console()]
});

/* ------------------------------------------------------------------------ */
/*                         Kafka Client Singleton                           */
/* ------------------------------------------------------------------------ */

const kafka = new Kafka({
    clientId: 'agorapulse-monitoring-service',
    brokers: CONFIG.kafkaBrokers,
    logLevel: logLevel.ERROR
});

let producerInstance;

/**
 * Lazy producer creation to avoid unnecessary connections when imported as a library.
 */
async function getProducer() {
    if (!producerInstance) {
        producerInstance = kafka.producer({ allowAutoTopicCreation: true });
        await producerInstance.connect();
    }
    return producerInstance;
}

/* ------------------------------------------------------------------------ */
/*                              Domain Models                               */
/* ------------------------------------------------------------------------ */

/**
 * Abstract monitoring rule.
 * Concrete strategies must implement:
 *    - id        : unique identifier (string)
 *    - description: human readable explanation
 *    - evaluate(bufferedMetrics) -> {alert?: object} | null
 */
class MonitoringRule {
    constructor() {
        if (this.constructor === MonitoringRule) {
            throw new TypeError('Abstract class "MonitoringRule" cannot be instantiated directly.');
        }
    }

    /**
     * Evaluates a set of metrics aggregated in the buffer window.
     * @param {Array<Object>} metrics
     * @returns {null|Object} alert payload when triggered
     */
    evaluate(/* metrics */) {
        throw new Error('evaluate() must be implemented by subclass');
    }
}

/**
 * Rule: Alert when toxicity false negatives exceed threshold.
 */
class ToxicityFNRule extends MonitoringRule {
    constructor(threshold = 0.05 /* 5% */) {
        super();
        this.threshold = threshold;
        this.id = 'toxicity-fn-rate';
        this.description = `Toxicity False Negative rate > ${threshold * 100}%`;
    }

    evaluate(metrics) {
        const toxMetrics = metrics.filter(
            (m) => m.metricName === 'toxicity_false_negative_rate'
        );

        if (_.isEmpty(toxMetrics)) return null;

        const average = _.meanBy(toxMetrics, 'value');

        if (average > this.threshold) {
            return {
                id: uuidv4(),
                ruleId: this.id,
                severity: 'high',
                message: `Toxicity false negative rate ${average.toFixed(3)} exceeded threshold ${this.threshold}`,
                meta: { average, threshold: this.threshold, samples: toxMetrics.length },
                timestamp: Date.now()
            };
        }

        return null;
    }
}

/**
 * Rule: Alert when overall latency p95 crosses threshold.
 */
class LatencyRule extends MonitoringRule {
    constructor(p95ThresholdMs = 500) {
        super();
        this.p95ThresholdMs = p95ThresholdMs;
        this.id = 'latency-p95';
        this.description = `p95 Latency > ${p95ThresholdMs}ms`;
    }

    evaluate(metrics) {
        const latencyMetrics = metrics.filter(
            (m) => m.metricName === 'latency_ms' && m.percentile === 0.95
        );

        if (_.isEmpty(latencyMetrics)) return null;

        const maxP95 = _.maxBy(latencyMetrics, 'value').value;

        if (maxP95 > this.p95ThresholdMs) {
            return {
                id: uuidv4(),
                ruleId: this.id,
                severity: 'medium',
                message: `Latency p95 ${maxP95}ms exceeded threshold ${this.p95ThresholdMs}ms`,
                meta: { maxP95, threshold: this.p95ThresholdMs, samples: latencyMetrics.length },
                timestamp: Date.now()
            };
        }

        return null;
    }
}

/* ------------------------------------------------------------------------ */
/*                          Monitoring Service                              */
/* ------------------------------------------------------------------------ */

class MonitoringService {
    /**
     * @param {Kafka} kafkaClient
     * @param {Array<MonitoringRule>} rules
     * @param {Object} config
     */
    constructor(kafkaClient, rules = [], config = {}) {
        this.kafka = kafkaClient;
        this.rules = rules;
        this.config = { ...CONFIG, ...config };
        this.consumer = this.kafka.consumer({
            groupId: this.config.consumerGroupId
        });
        this.running = false;
    }

    /**
     * Adds a rule at runtime (supports dynamic refresh).
     * @param {MonitoringRule} rule
     */
    addRule(rule) {
        logger.info('Registering rule: %s', rule.id);
        this.rules.push(rule);
    }

    /**
     * Removes a rule by id (if present).
     * @param {String} ruleId
     */
    removeRule(ruleId) {
        _.remove(this.rules, (r) => r.id === ruleId);
        logger.info('Removed rule: %s', ruleId);
    }

    /**
     * Start consuming metrics stream and evaluating rules.
     */
    async start() {
        if (this.running) {
            logger.warn('MonitoringService already running');
            return;
        }

        await this.consumer.connect();
        await this.consumer.subscribe({ topic: this.config.metricsTopic, fromBeginning: false });

        const metricsObservable = this._createMetricsObservable();

        const buffered$ = metricsObservable.pipe(
            // buffer metrics over configurable time window
            bufferTime(this.config.bufferWindowMs),
            // discard empty buffers
            filter((buffer) => buffer.length > 0)
        );

        this.subscription = buffered$.subscribe({
            next: (buffer) => this._evaluateRules(buffer).catch((err) => {
                logger.error('Failed evaluating rules: %o', err);
            }),
            error: (err) => logger.error('Metrics stream error: %o', err)
        });

        this.running = true;
        logger.info('MonitoringService started. Listening on topic "%s"', this.config.metricsTopic);
    }

    /**
     * Graceful shutdown.
     */
    async stop() {
        if (!this.running) return;
        await this.subscription?.unsubscribe();
        await this.consumer.disconnect();
        if (producerInstance) await producerInstance.disconnect();
        this.running = false;
        logger.info('MonitoringService stopped');
    }

    /* ----------------------- Private Helpers ---------------------------- */

    /**
     * Wrap Kafka consumer in RxJS observable.
     * @returns {Observable<Object>} stream of raw metric objects
     */
    _createMetricsObservable() {
        const addHandler = (handler) => {
            this.consumer.run({
                eachMessage: async ({ message }) => {
                    try {
                        const parsed = JSON.parse(message.value.toString('utf8'));
                        handler(parsed);
                    } catch (err) {
                        logger.warn('Discarding malformed metric: %s', message.value);
                    }
                }
            }).catch((err) => handler(err, true)); // pass error to handler's second arg
        };

        const removeHandler = () => {
            // kafkaJS does not support removing handlers; we rely on consumer.stop elsewhere
        };

        return fromEventPattern(
            addHandler,
            removeHandler
        ).pipe(
            filter((event) => !event?.isTrusted), // rudimentary error filtering
            catchError((err, caught) => {
                logger.error('Observable error: %o', err);
                return caught;
            })
        );
    }

    /**
     * Evaluate all registered rules against buffered metrics.
     * Emits alert events for each triggered rule.
     *
     * @param {Array<Object>} buffer
     */
    async _evaluateRules(buffer) {
        if (_.isEmpty(this.rules)) return;

        const alerts = [];
        for (const rule of this.rules) {
            try {
                const alert = rule.evaluate(buffer);
                if (alert) alerts.push(alert);
            } catch (err) {
                logger.error('Error evaluating rule %s: %o', rule.id, err);
            }
        }

        if (!_.isEmpty(alerts)) {
            logger.warn('Triggered %d alerts', alerts.length);
            await this._emitAlerts(alerts);
        }
    }

    /**
     * Emit alert payloads as one message per alert.
     * @param {Array<Object>} alerts
     */
    async _emitAlerts(alerts) {
        const producer = await getProducer();

        const messages = alerts.map((a) => ({
            key: a.ruleId,
            value: JSON.stringify(a),
            timestamp: String(a.timestamp)
        }));

        await producer.send({
            topic: this.config.alertTopic,
            messages
        });

        logger.info('Published %d alerts to topic "%s"', messages.length, this.config.alertTopic);
    }
}

/* ------------------------------------------------------------------------ */
/*                    Default Service Bootstrap (CLI)                       */
/* ------------------------------------------------------------------------ */

if (require.main === module) {
    // When executed directly `node src/module_72.js`
    (async () => {
        try {
            const service = new MonitoringService(kafka, [
                new ToxicityFNRule(Number(process.env.TOX_FN_THRESHOLD) || 0.05),
                new LatencyRule(Number(process.env.LATENCY_P95_MS) || 500)
            ]);

            // Graceful shutdown
            const shutdownSignals = ['SIGINT', 'SIGTERM', 'SIGQUIT'];
            shutdownSignals.forEach((signal) =>
                process.on(signal, async () => {
                    logger.info('Received %s. Shutting down...', signal);
                    await service.stop();
                    process.exit(0);
                })
            );

            await service.start();
        } catch (err) {
            logger.error('Fatal error starting MonitoringService: %o', err);
            process.exit(1);
        }
    })();
}

/* ------------------------------------------------------------------------ */
/*                       Module Exports for testing                         */
/* ------------------------------------------------------------------------ */

module.exports = {
    MonitoringService,
    MonitoringRule,
    ToxicityFNRule,
    LatencyRule,
    getProducer // exported for unit tests / mocks
};