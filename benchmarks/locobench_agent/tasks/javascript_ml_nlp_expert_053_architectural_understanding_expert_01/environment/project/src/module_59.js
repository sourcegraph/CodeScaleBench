```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * src/module_59.js
 *
 * ModelMetricMonitor:
 * A resilient, streaming KPI supervisor that listens to model-serving
 * telemetry coming off Kafka, aggregates it with RxJS, and emits
 * domain events whenever pre-configured SLO/SLA thresholds are breached.
 *
 * The monitor works on arbitrary model metrics (latency p99, accuracy,
 * toxicity FN-rate, etc.), is partition-aware, reconnection-resilient,
 * and back-pressure friendly.  Down-stream consumers (alerting
 * micro-services, auto-retrain pipelines, dashboards) simply subscribe
 * to its EventEmitter interface.
 */

/* eslint-disable no-console */
'use strict';

/* ────────────────────────────────────────── Imports ──────────── */
const { Kafka }             = require('kafkajs');
const { Subject, EMPTY }     = require('rxjs');
const {
    bufferTime,
    catchError,
    filter,
    map,
    mergeMap,
    tap,
}                             = require('rxjs/operators');
const EventEmitter           = require('events');
const _                      = require('lodash');
const backOff                = require('exponential-backoff').backOff;
const debug                  = require('debug')('agorapulse:model-monitor');

/* ─────────────────────────── Configuration Types ────────────── */

/**
 * @typedef {Object} ThresholdRule
 * @property {string}  metric                 - Name of the metric being supervised.
 * @property {'min'|'max'} comparator         - Breach if metric is lower than (min) or higher than (max) requested value.
 * @property {number}  value                  - The boundary value.
 * @property {number}  timeWindowSec          - Aggregation window length (seconds).
 */

/**
 * @typedef {Object} MonitorOptions
 * @property {import('kafkajs').KafkaConfig} kafka
 * @property {string} topic                  - Kafka topic that carries model telemetry.
 * @property {ThresholdRule[]} thresholds
 * @property {number} [partition]            - Optional fixed partition assignment.
 * @property {number} [bufferSize]           - Max messages kept in memory per window.
 */

/* ───────────────────────────── Module Code ──────────────────── */

class ModelMetricMonitor extends EventEmitter {

    /**
     * @param {MonitorOptions} opts
     */
    constructor (opts) {
        super();

        /* Defensive copy & basic validation */
        this.opts          = Object.freeze({ bufferSize: 10_000, ...opts });
        this._validateOptions(this.opts);

        this.kafka         = new Kafka(this.opts.kafka);
        this.consumer      = this.kafka.consumer({
            groupId : `model-monitor-${process.pid}-${Date.now()}`,
        });

        this.subject       = new Subject();         // Rx entrypoint
        this._subscription = null;
        this._isRunning    = false;
    }

    /* ─────────── Public API ────────── */

    /**
     * Starts the Kafka consumer + RxJS pipeline.
     */
    async start () {
        if (this._isRunning) return;
        this._isRunning = true;

        await this._connectKafka();
        await this.consumer.subscribe({ topic : this.opts.topic, fromBeginning : false });

        /* Pipe incoming messages into the Subject */
        this._consumerLoop().catch((err) => {
            this._emitError(err);
            // Let backOff handle reconnection attempts
            this._restart();
        });

        /* Build Rx aggregation pipeline */
        this._subscription = this.subject.pipe(
            bufferTime(this._largestWindowMs(), null, this.opts.bufferSize),
            filter((buffer) => buffer.length > 0),
            mergeMap((buffer) => {
                const grouped = _.groupBy(buffer, 'modelVersion');
                return Object
                    .entries(grouped)
                    .map(([modelVersion, records]) => ({ modelVersion, records }));
            }),
            map(({ modelVersion, records }) => this._evaluate(modelVersion, records)),
            filter(Boolean), // keep only those that breached
            tap((breachEvent) => this.emit('threshold_breach', breachEvent)),
            catchError((err, caught) => {
                this._emitError(err);
                return caught ?? EMPTY;
            }),
        ).subscribe();

        debug('ModelMetricMonitor started.');
    }

    /**
     * Tears down the stream and disconnects from Kafka.
     */
    async stop () {
        if (!this._isRunning) return;
        this._isRunning = false;

        this._subscription?.unsubscribe();
        await this.consumer.disconnect().catch((err) => {
            this._emitError(err);
        });

        this.subject.complete();
        debug('ModelMetricMonitor stopped.');
    }

    /* ───────── Internal Helpers ───────── */

    /**
     * Endless async iterator reading from Kafka,
     * pushing every message to the RxJS Subject.
     */
    async _consumerLoop () {
        await this.consumer.run({
            partitionsConsumedConcurrently : 1,
            eachMessage : async ({ message /*, partition */ }) => {
                try {
                    const parsed = this._parseMessage(message);
                    this.subject.next(parsed);
                }
                catch (err) {
                    this._emitError(err, {
                        raw : message.value?.toString('utf8').slice(0, 250),
                    });
                }
            },
        });
    }

    /**
     * Connects to Kafka with exponential back-off.
     * @private
     */
    async _connectKafka () {
        await backOff(() => this.consumer.connect(), {
            startingDelay :   250,
            timeMultiple   :   2.0,
            numOfAttempts  :   6,
            jitter         :   'full',
            retry          : (e, attemptNo) => {
                debug(`Kafka connection attempt #${attemptNo} failed: ${e?.message}`);
                return true;
            },
        });
    }

    /**
     * Parses a Kafka message payload into an internal envelope.
     *
     * @param {import('kafkajs').KafkaMessage} message
     * @returns {{modelVersion: string, metric: string, value: number, timestamp: number}}
     * @throws Will throw if message is malformed.
     */
    _parseMessage (message) {
        const str = message.value?.toString('utf8');
        if (!str) throw new Error('Empty Kafka payload.');

        const data = JSON.parse(str);
        const { modelVersion, metric, value, timestamp } = data;
        if (!modelVersion || !metric || typeof value !== 'number') {
            throw new Error(`Malformed metric message: ${str}`);
        }
        return { modelVersion, metric, value, timestamp : timestamp ?? Date.now() };
    }

    /**
     * Evaluates a batch of metric samples against all configured thresholds.
     *
     * @param {string} modelVersion
     * @param {Array<{metric:string,value:number,timestamp:number}>} records
     * @returns {Object|null} Breach event envelope or null
     * @private
     */
    _evaluate (modelVersion, records) {
        const latestWindow = Date.now();

        for (const rule of this.opts.thresholds) {
            /* Filter records matching the metric & inside the time window */
            const windowStart = latestWindow - (rule.timeWindowSec * 1000);
            const slice       = records.filter(
                (r) => r.metric === rule.metric && r.timestamp >= windowStart,
            );
            if (slice.length === 0) continue;

            /* Use mean value for evaluation (easily swapped for p95/etc.) */
            const mean = _.meanBy(slice, 'value');

            const breached =
                (rule.comparator === 'min' && mean < rule.value) ||
                (rule.comparator === 'max' && mean > rule.value);

            if (breached) {
                return {
                    modelVersion,
                    rule,
                    mean,
                    sampleSize : slice.length,
                    breachedAt : new Date(latestWindow).toISOString(),
                };
            }
        }
        return null;
    }

    /**
     * Emits errors both to the EventEmitter and stderr w/ debug.
     *
     * @param {Error} err
     * @param {Record<string, any>} [context]
     * @private
     */
    _emitError (err, context = {}) {
        this.emit('error', err, context);
        debug('Error:', err, context);
    }

    /**
     * Restarts the service when Kafka crashes permanently.
     *
     * @private
     */
    async _restart () {
        try {
            await this.stop();
            await this.start();
        }
        catch (err) {
            this._emitError(err);
        }
    }

    /**
     * Returns the largest time window (ms) amongst configured thresholds.
     * RxJS bufferTime uses this to guarantee all rules have full coverage.
     */
    _largestWindowMs () {
        return _.maxBy(this.opts.thresholds, 'timeWindowSec').timeWindowSec * 1000;
    }

    /**
     * User input validation.
     * @private
     */
    _validateOptions (opts) {
        if (!opts.kafka || !opts.topic || !Array.isArray(opts.thresholds)) {
            throw new Error('Invalid ModelMetricMonitor options.');
        }
        if (opts.thresholds.some((t) => !['min', 'max'].includes(t.comparator))) {
            throw new Error('ThresholdRule.comparator must be "min" or "max".');
        }
    }
}

/* ──────────────────────────── Exports ───────────────────────── */

module.exports = {
    ModelMetricMonitor,
};
```