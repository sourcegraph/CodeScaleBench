```javascript
/* ===========================================================================
 * AgoraPulse - Real-Time Social Signal Intelligence
 * ---------------------------------------------------------------------------
 * Module:  src/module_53.js
 *
 * Purpose: Real-Time, windowed sentiment aggregator.  Subscribes to the
 *          low-level sentiment-score stream (`nlp.sentiment.raw`) emitted by
 *          the ML micro-pipelines, performs sliding-window aggregation, and
 *          publishes a lightweight signal (`nlp.sentiment.aggregated`) for
 *          dashboards and downstream automation.
 *
 * Author:  AgoraPulse Engineering
 * License: Apache-2.0
 * ==========================================================================*/

'use strict';

/* --- External Dependencies ------------------------------------------------ */
const { Kafka, logLevel }                 = require('kafkajs');
const { Subject, from, timer }            = require('rxjs');
const {
    bufferTime,
    groupBy,
    mergeMap,
    map,
    reduce,
    retryWhen,
    delay,
    tap,
}                                          = require('rxjs/operators');
const pino                                = require('pino');
const promClient                          = require('prom-client');

/* --- Constants & Configuration ------------------------------------------- */

/**
 * @typedef {Object} AggregatorConfig
 * @property {string}  clientId
 * @property {string[]} brokers
 * @property {number}  windowMs            – Size of aggregation window
 * @property {number}  publishIntervalMs   – Cadence for publishing aggregates
 * @property {string}  inTopic             – Raw sentiment topic
 * @property {string}  outTopic            – Aggregated sentiment topic
 * @property {number}  maxRetries          – Kafka reconnect attempts
 */

const DEFAULT_CONFIG = /** @type {AggregatorConfig} */ ({
    clientId:           'agorapulse.sentiment-aggregator',
    brokers:            process.env.KAFKA_BROKERS?.split(',') || ['localhost:9092'],
    windowMs:           5_000, // 5s window
    publishIntervalMs:  5_000,
    inTopic:            'nlp.sentiment.raw',
    outTopic:           'nlp.sentiment.aggregated',
    maxRetries:         5,
});

/* --- Logger ---------------------------------------------------------------- */
const logger = pino({
    level : process.env.LOG_LEVEL || 'info',
    name  : 'sentiment-aggregator',
});

/* --- Prometheus Metrics ---------------------------------------------------- */
const messagesConsumed = new promClient.Counter({
    name: 'sentiment_aggregator_messages_consumed_total',
    help: 'Total raw sentiment messages consumed',
});
const messagesProduced = new promClient.Counter({
    name: 'sentiment_aggregator_messages_produced_total',
    help: 'Total aggregated sentiment messages produced',
});
const processingLag = new promClient.Gauge({
    name: 'sentiment_aggregator_processing_lag_ms',
    help: 'Lag between message timestamp and aggregation publish time',
});

/* --- Aggregator Implementation -------------------------------------------- */

class SentimentAggregator {
    /**
     * @param {Partial<AggregatorConfig>} [cfg]
     */
    constructor(cfg = {}) {
        /** @type {AggregatorConfig} */
        this.config   = { ...DEFAULT_CONFIG, ...cfg };
        this.kafka    = new Kafka({
            clientId : this.config.clientId,
            brokers  : this.config.brokers,
            logLevel : logLevel.WARN,
        });
        this.consumer = this.kafka.consumer({ groupId: `${this.config.clientId}-group` });
        this.producer = this.kafka.producer();
        this.message$ = new Subject();          // RxJS bridge
        this._shutdownRequested = false;
    }

    /* ---------------------------------------------------------------------- */
    async init() {
        logger.info('Initializing Kafka connections…');
        await Promise.all([
            this.producer.connect(),
            this.consumer.connect(),
        ]);

        /* Subscribe to raw sentiment topic */
        await this.consumer.subscribe({ topic: this.config.inTopic, fromBeginning: false });

        /* Forward each consumed Kafka message into Rx stream ---------------- */
        this.consumer.run({
            eachMessage: async ({ message }) => {
                try {
                    const payload  = JSON.parse(message.value.toString('utf8'));
                    messagesConsumed.inc();

                    this.message$.next(payload);

                    /* Track processing lag */
                    if (typeof payload.ts === 'number') {
                        processingLag.set(Date.now() - payload.ts);
                    }
                } catch (err) {
                    logger.warn({ err }, 'Malformed sentiment payload, skipping.');
                }
            },
        });

        /* Start aggregation pipeline -------------------------------------- */
        this._buildPipeline();

        /* Graceful shutdown signals --------------------------------------- */
        process
            .once('SIGINT',  () => this.shutdown('SIGINT'))
            .once('SIGTERM', () => this.shutdown('SIGTERM'));

        logger.info({ inTopic: this.config.inTopic, outTopic: this.config.outTopic },
            'Sentiment aggregator ready.');
    }

    /* ---------------------------------------------------------------------- */
    _buildPipeline() {
        this.message$
            .pipe(

                /* Batch in fixed time windows so we can compute aggregates */
                bufferTime(this.config.windowMs),

                /* Ignore empty windows */
                filterBatch => filterBatch.length > 0 ? filterBatch : null,
                mergeMap(batch => batch ? from([batch]) : from([])),

                /* Group by topicId (logical subreddit/space/live-stream id) */
                mergeMap(batch => from(batch).pipe(
                    groupBy(msg => msg.topicId),
                    mergeMap(group$ => group$.pipe(
                        reduce((acc, cur) => {
                            acc.sum         += cur.sentimentScore;
                            acc.count       += 1;
                            acc.latestUser  = cur.userId;                 // Example enrichment
                            return acc;
                        }, { topicId: group$.key, sum: 0, count: 0 }),
                        map(acc => ({
                            topicId        : acc.topicId,
                            avgSentiment   : Number((acc.sum / acc.count).toFixed(4)),
                            sampleSize     : acc.count,
                            representativeUser: acc.latestUser,
                            ts             : Date.now(),
                        })),
                    )),
                )),

                /* Retry on transient upstream errors, capped back-off */
                retryWhen(errs => errs.pipe(
                    tap(err => logger.error({ err }, 'Stream error, will retry…')),
                    delay(1_000),   // Simple back-off; exponential not required here
                    take(this.config.maxRetries),
                )),
            )
            .subscribe({
                next  : aggregate => this._publishAggregate(aggregate),
                error : err => logger.fatal({ err }, 'Unrecoverable RxJS pipeline error.'),
            });
    }

    /* ---------------------------------------------------------------------- */
    /**
     * Publish aggregated sentiment to Kafka.
     * @param {Object} aggregate
     * @private
     */
    async _publishAggregate(aggregate) {
        try {
            await this.producer.send({
                topic: this.config.outTopic,
                messages: [
                    {
                        key  : aggregate.topicId,
                        value: JSON.stringify(aggregate),
                    },
                ],
            });
            messagesProduced.inc();
            logger.debug({ aggregate }, 'Published aggregated sentiment.');
        } catch (err) {
            logger.error({ err }, 'Failed to publish aggregated sentiment.');
        }
    }

    /* ---------------------------------------------------------------------- */
    /**
     * Gracefully shutdown Kafka connections & Rx pipeline.
     * @param {string} reason – Signal reason
     */
    async shutdown(reason = 'unknown') {
        if (this._shutdownRequested) return;
        this._shutdownRequested = true;

        logger.info({ reason }, 'Shutting down sentiment aggregator…');
        try {
            await this.consumer.disconnect();
            await this.producer.disconnect();
            this.message$.complete();
            logger.info('Aggregator shutdown complete.');
            process.exit(0);
        } catch (err) {
            logger.error({ err }, 'Error during shutdown.');
            process.exit(1);
        }
    }
}

/* --- Module Entrypoint ---------------------------------------------------- */
if (require.main === module) {
    /* Run with default config merged with ENV overrides */
    const aggregator = new SentimentAggregator({
        windowMs:          Number(process.env.WINDOW_MS)          || undefined,
        publishIntervalMs: Number(process.env.PUBLISH_INTERVAL_MS) || undefined,
        inTopic:           process.env.IN_TOPIC                    || undefined,
        outTopic:          process.env.OUT_TOPIC                   || undefined,
    });

    aggregator.init().catch(err => {
        logger.fatal({ err }, 'Failed to start sentiment aggregator.');
        process.exit(1);
    });
}

/* --- Export for tests / embedding ---------------------------------------- */
module.exports = { SentimentAggregator };
```