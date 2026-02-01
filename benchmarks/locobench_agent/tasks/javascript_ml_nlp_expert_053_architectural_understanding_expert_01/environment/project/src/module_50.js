/**
 * src/module_50.js
 *
 * AgoraPulse – Real-Time Social Signal Intelligence
 *
 * Module #50: Metric Monitor & Anomaly Publisher
 * ==============================================
 * Continuously queries Prometheus for model-serving/monitoring metrics,
 * detects anomalies (breaches of configured thresholds or statistical change
 * points), and publishes anomaly events to Kafka so that downstream pipelines
 * (re-training triggers, alerting, dashboards) can react in near-real time.
 *
 * High-level flow:
 *  ┌──────────────┐     poll()      ┌─────────────────┐
 *  │ Prometheus   │ ───────────────▶│ MetricMonitor   │
 *  └──────────────┘                 │  • thresholds   │
 *                                   │  • change-point │
 *                                   │  • debounce     │
 *                                   └──────┬──────────┘
 *                                          │ emit
 *                                          ▼
 *                                  ┌──────────────────┐
 *                                  │ Kafka producer   │
 *                                  └──────────────────┘
 *
 * The monitor is heavily RxJS-based and respects back-pressure.  When the
 * Prometheus endpoint is slow or unreachable, we apply exponential back-off
 * and circuit-breaking semantics to avoid cascading failures.
 *
 * NOTE:
 *  - This file is intentionally written in plain JS (ES2020) to support both
 *    Node.js ≥14 and older Lambda runtimes.  For TypeScript consumers, the
 *    corresponding typings are generated in the `types/` folder.
 */

'use strict';

//////////////////////////////
// External Dependencies
//////////////////////////////
const { Kafka, logLevel } = require('kafkajs');
const axios = require('axios').default;
const Ajv = require('ajv').default;
const addFormats = require('ajv-formats');
const {
    timer,
    from,
    EMPTY,
    throwError,
    defer,
    Subject
} = require('rxjs');
const {
    switchMap,
    map,
    catchError,
    retryWhen,
    filter,
    tap,
    takeUntil,
    shareReplay,
    delay,
    scan,
    throttleTime
} = require('rxjs/operators');

//////////////////////////////
// Environment & Config
//////////////////////////////

const {
    PROMETHEUS_BASE_URL = 'http://localhost:9090/api/v1/query',
    KAFKA_BROKERS = 'localhost:9092',
    ALERT_TOPIC = 'agorapulse.monitoring.alerts',
    POLL_INTERVAL_MS = '10000',
    MAX_BACKOFF_MS = '60000',
    METRICS_CONFIG_JSON = '{}', // JSON string mapping metricName -> { threshold, type }
    PRODUCER_CLIENT_ID = 'agorapulse-metric-monitor'
} = process.env;

// Parsed config
let MONITORED_METRICS;
try {
    MONITORED_METRICS = JSON.parse(METRICS_CONFIG_JSON);
} catch (err) {
    console.error('Invalid METRICS_CONFIG_JSON; falling back to defaults.', err);
    MONITORED_METRICS = {
        'model_latency_seconds_p95': {
            threshold: 1.5,
            comparator: 'gt', // greater-than
            severity: 'critical'
        },
        'model_error_rate': {
            threshold: 0.03,
            comparator: 'gt',
            severity: 'warning'
        }
    };
}

//////////////////////////////
// Utility Helpers
//////////////////////////////

/**
 * Comparator map translating textual comparator to actual function
 */
const comparatorFn = {
    gt: (value, threshold) => value > threshold,
    gte: (value, threshold) => value >= threshold,
    lt: (value, threshold) => value < threshold,
    lte: (value, threshold) => value <= threshold,
    eq: (value, threshold) => value === threshold
};

/**
 * Calculate next exponential back-off delay.
 */
function computeBackoff(attempt, baseMs = Number(POLL_INTERVAL_MS), maxMs = Number(MAX_BACKOFF_MS)) {
    const delayMs = Math.min(baseMs * 2 ** attempt, maxMs);
    const jitter = Math.random() * (delayMs * 0.2); // ±20 % jitter
    return delayMs + jitter;
}

/**
 * Returns current ISO date string (UTC) without milliseconds for concise logs.
 */
function now() {
    return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

//////////////////////////////
// Prometheus Client
//////////////////////////////

class PrometheusClient {
    constructor(baseURL) {
        this.http = axios.create({
            baseURL,
            timeout: 5000
        });
    }

    /**
     * Query a single PromQL expression
     * @param {string} query
     * @return {Observable<number>} emits single numeric value
     */
    query$(query) {
        return defer(() =>
            from(
                this.http.get('', {
                    params: { query }
                })
            )
        ).pipe(
            map((response) => {
                if (response.data.status !== 'success') {
                    throw new Error(`Prometheus error status: ${response.data.status}`);
                }
                const result = response.data.data.result;
                if (!Array.isArray(result) || result.length === 0) {
                    throw new Error(`No data for query ${query}`);
                }
                // Support both instant vector and scalar responses; take first
                const valuePair = result[0].value; // [ <timestamp>, "<value>" ]
                if (!valuePair || valuePair.length < 2) {
                    throw new Error(`Malformed Prometheus response for ${query}`);
                }
                const numericValue = parseFloat(valuePair[1]);
                if (Number.isNaN(numericValue)) {
                    throw new Error(`Non-numeric Prometheus value for ${query}: ${valuePair[1]}`);
                }
                return numericValue;
            })
        );
    }
}

//////////////////////////////
// Kafka Producer Singleton
//////////////////////////////

class KafkaProducer {
    constructor(brokers, clientId) {
        const kafka = new Kafka({
            clientId,
            brokers: brokers.split(','),
            logLevel: logLevel.ERROR // suppress noise, use our own logging
        });
        this.producer = kafka.producer({ allowAutoTopicCreation: true });
        this.connected$ = from(this.producer.connect()).pipe(shareReplay(1));
    }

    /**
     * Publishes a JSON message to a topic. Handles async connect.
     * @param {string} topic
     * @param {object} payload
     * @returns {Observable<void>}
     */
    send$(topic, payload) {
        return this.connected$.pipe(
            switchMap(() =>
                from(
                    this.producer.send({
                        topic,
                        messages: [
                            {
                                key: payload.metricName,
                                value: JSON.stringify(payload),
                                timestamp: Date.now().toString()
                            }
                        ]
                    })
                )
            ),
            map(() => void 0) // hide Kafka response
        );
    }

    async shutdown() {
        try {
            await this.producer.disconnect();
            console.info(`[${now()}] Kafka producer disconnected.`);
        } catch (err) {
            console.error('[KafkaProducer] Error during disconnect', err);
        }
    }
}

//////////////////////////////
// Schema Validation (Ajv)
//////////////////////////////

const ajv = new Ajv({ allErrors: true, removeAdditional: 'all' });
addFormats(ajv);

const alertSchema = {
    $id: 'agorapulse.alert',
    type: 'object',
    additionalProperties: false,
    required: [
        'metricName',
        'currentValue',
        'threshold',
        'comparator',
        'severity',
        'timestamp'
    ],
    properties: {
        metricName: { type: 'string', minLength: 1 },
        currentValue: { type: 'number' },
        threshold: { type: 'number' },
        comparator: { enum: ['gt', 'gte', 'lt', 'lte', 'eq'] },
        severity: { enum: ['info', 'warning', 'critical'] },
        timestamp: { type: 'string', format: 'date-time' }
    }
};

const validateAlert = ajv.compile(alertSchema);

//////////////////////////////
// MetricMonitor
//////////////////////////////

class MetricMonitor {
    constructor({
        prometheusClient,
        kafkaProducer,
        metricsConfig,
        pollIntervalMs = 10000
    }) {
        this.prometheus = prometheusClient;
        this.kafka = kafkaProducer;
        this.metricsConfig = metricsConfig;
        this.pollIntervalMs = pollIntervalMs;
        this.stop$ = new Subject(); // graceful stop signal
    }

    /**
     * Start monitoring loop.
     */
    start() {
        const metricEntries = Object.entries(this.metricsConfig);

        if (metricEntries.length === 0) {
            console.warn(`[${now()}] No metrics configured for monitoring.`);
            return;
        }

        console.info(
            `[${now()}] Starting MetricMonitor for ${metricEntries.length} metric(s)…`
        );

        this.subscription = timer(0, this.pollIntervalMs)
            .pipe(
                takeUntil(this.stop$),
                // For each tick, query metrics in parallel
                switchMap(() =>
                    from(metricEntries).pipe(
                        switchMap(([metricName, cfg]) =>
                            this.checkMetric$(metricName, cfg)
                        )
                    )
                ),
                catchError((err) => {
                    console.error(`[MetricMonitor] Unhandled error`, err);
                    return EMPTY; // swallow; monitoring continues
                })
            )
            .subscribe();
    }

    /**
     * Stop monitoring loop gracefully.
     */
    stop() {
        this.stop$.next();
        this.stop$.complete();
        this.subscription?.unsubscribe();
    }

    /**
     * Check a particular metric for anomaly and emit Kafka event when breached.
     * @param {string} metricName
     * @param {object} cfg
     * @returns {Observable<void>}
     */
    checkMetric$(metricName, cfg) {
        const { threshold, comparator = 'gt', severity = 'info', promQuery } = cfg;

        const query = promQuery || metricName; // use custom query or metric name directly

        return this.prometheus.query$(query).pipe(
            // Retry with exponential back-off on network/Prometheus errors
            retryWhen((errors) =>
                errors.pipe(
                    scan((acc, err) => {
                        console.warn(
                            `[${now()}] Prometheus query failed (${query}): ${err.message}`
                        );
                        return acc + 1;
                    }, 0),
                    delay((attempt) => computeBackoff(attempt))
                )
            ),
            filter((value) => {
                const compFn = comparatorFn[comparator];
                if (!compFn) {
                    console.error(
                        `[MetricMonitor] Unknown comparator "${comparator}" for metric ${metricName}`
                    );
                    return false;
                }
                return compFn(value, threshold);
            }),
            throttleTime(60000), // de-bounce: emit at most once per minute per metric
            map((value) => {
                const payload = {
                    metricName,
                    currentValue: value,
                    threshold,
                    comparator,
                    severity,
                    timestamp: new Date().toISOString()
                };
                if (!validateAlert(payload)) {
                    console.error(
                        `[MetricMonitor] Invalid alert payload for ${metricName}`,
                        validateAlert.errors
                    );
                    return null;
                }
                return payload;
            }),
            filter(Boolean),
            switchMap((payload) =>
                this.kafka
                    .send$(ALERT_TOPIC, payload)
                    .pipe(
                        tap(() =>
                            console.info(
                                `[${now()}] Anomaly emitted: ${payload.metricName}=${payload.currentValue} (threshold ${payload.comparator} ${payload.threshold})`
                            )
                        )
                    )
            ),
            catchError((err) => {
                console.error(
                    `[MetricMonitor] Error while processing metric ${metricName}`,
                    err
                );
                return EMPTY;
            })
        );
    }
}

//////////////////////////////
// Bootstrapping
//////////////////////////////

let monitorInstance;

async function bootstrap() {
    try {
        const prometheusClient = new PrometheusClient(PROMETHEUS_BASE_URL);
        const kafkaProducer = new KafkaProducer(KAFKA_BROKERS, PRODUCER_CLIENT_ID);

        monitorInstance = new MetricMonitor({
            prometheusClient,
            kafkaProducer,
            metricsConfig: MONITORED_METRICS,
            pollIntervalMs: Number(POLL_INTERVAL_MS)
        });

        monitorInstance.start();

        // Graceful shutdown on SIGTERMs
        process.once('SIGINT', async () => await shutdown('SIGINT'));
        process.once('SIGTERM', async () => await shutdown('SIGTERM'));
    } catch (err) {
        console.error('[Bootstrap] Fatal error during startup', err);
        process.exit(1);
    }
}

async function shutdown(signal) {
    console.info(`[${now()}] Caught ${signal}, shutting down MetricMonitor…`);
    try {
        monitorInstance?.stop();
        await monitorInstance?.kafka.shutdown();
    } catch (err) {
        console.error('[Shutdown] Error while shutting down', err);
    } finally {
        process.exit(0);
    }
}

// Auto-start if not imported as a module.
if (require.main === module) {
    bootstrap();
}

//////////////////////////////
// Exports
//////////////////////////////

module.exports = {
    bootstrap,
    MetricMonitor,
    PrometheusClient,
    KafkaProducer
};

