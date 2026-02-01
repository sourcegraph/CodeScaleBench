```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * -----------------------------------------------
 * src/module_34.js
 *
 * SentimentAggregator
 * -------------------
 * Consumes per-message sentiment scores from Kafka, aggregates them in a
 * sliding window (RxJS windowTime) and produces summary statistics back to
 * Kafka for real-time dashboards & model-monitoring alerts.
 *
 *  • Averaged sentiment
 *  • Volume (# messages)
 *  • Standard deviation (volatility gauge)
 *
 * Built-in resiliency:
 *  • Automatic consumer / producer reconnection
 *  • Circuit-breaker for repeated publishing failures
 *  • Runtime schema validation with AJV
 *
 * NOTE:  This file is plain JavaScript to allow usage in both TS and JS
 *        sub-projects without transpilation.
 */

/* ────────────────────────────────────────────────────────────────────────── */
/* External dependencies                                                     */
/* ────────────────────────────────────────────────────────────────────────── */
const { Kafka, logLevel }      = require('kafkajs');
const { Subject, from, timer } = require('rxjs');
const {
    bufferTime,
    filter,
    mergeMap,
    tap,
}                                = require('rxjs/operators');
const Ajv                       = require('ajv');
const addFormats                = require('ajv-formats');
const { v4: uuidv4 }            = require('uuid');
const winston                   = require('winston');
const CircuitBreaker            = require('opossum');

/* ────────────────────────────────────────────────────────────────────────── */
/* Configuration helpers                                                     */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Default logger (can be overridden via constructor)
 */
const logger = winston.createLogger({
    level   : process.env.LOG_LEVEL || 'info',
    format  : winston.format.combine(
        winston.format.timestamp(),
        winston.format.printf(
            ({ timestamp, level, message }) => `${timestamp} [${level}] ${message}`,
        ),
    ),
    transports: [ new winston.transports.Console() ],
});

/**
 * Runtime validation schema for inbound sentiment events.
 * Keeping it very small to minimise runtime overhead while still guarding against
 * malformed events that could poison our aggregates.
 */
const SENTIMENT_EVENT_SCHEMA = {
    $id      : 'SentimentEvent',
    type     : 'object',
    required : [ 'messageId', 'userId', 'sentiment', 'timestamp' ],
    properties: {
        messageId : { type: 'string', minLength: 1 },
        userId    : { type: 'string', minLength: 1 },
        sentiment : { type: 'number', minimum: -1, maximum: 1 },
        timestamp : { type: 'integer' },
    },
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Utilities                                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Calculate aggregated statistics for a batch of sentiment scores.
 * @param {number[]} scores
 * @returns {{avg: number, std: number}}
 */
function calculateStats(scores) {
    if (scores.length === 0) return { avg: 0, std: 0 };

    const mean = scores.reduce((acc, s) => acc + s, 0) / scores.length;
    const variance =
        scores.reduce((acc, s) => acc + (s - mean) ** 2, 0) / scores.length;
    return { avg: mean, std: Math.sqrt(variance) };
}

/* ────────────────────────────────────────────────────────────────────────── */
/* SentimentAggregator Class                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

class SentimentAggregator {
    /**
     * @param {object} cfg
     * @param {string[]} cfg.brokers             Kafka brokers
     * @param {string}   cfg.inputTopic          Topic to consume raw events
     * @param {string}   cfg.outputTopic         Topic to publish aggregates
     * @param {number}   [cfg.windowMs=10_000]   Sliding window size (ms)
     * @param {number}   [cfg.flushMs=5_000]     How often to emit aggregates
     * @param {string}   [cfg.groupId]           Consumer group id
     * @param {object}   [cfg.logger]            Override default winston logger
     */
    constructor(cfg) {
        this.config = {
            windowMs : cfg.windowMs  ?? 10_000,
            flushMs  : cfg.flushMs   ?? 5_000,
            groupId  : cfg.groupId   ?? `sentiment-aggregator-${uuidv4()}`,
            ...cfg,
        };

        this.logger = cfg.logger || logger.child({ module: 'SentimentAggregator' });

        this.kafka = new Kafka({
            clientId : 'agorapulse-sentiment-aggregator',
            brokers  : this.config.brokers,
            logLevel : logLevel.NOTHING,
        });

        this.consumer = this.kafka.consumer({ groupId: this.config.groupId });
        this.producer = this.kafka.producer({ idempotent: true });

        // RxJS Subject acts as a bridge between Kafka and reactive pipeline
        this.eventSubject = new Subject();

        // AJV validator compiled once
        const ajv = new Ajv({ strict: true });
        addFormats(ajv);
        this.validateEvent = ajv.compile(SENTIMENT_EVENT_SCHEMA);

        // Circuit-breaker around producer.send
        this.producerBreaker = new CircuitBreaker(
            (payload) => this.producer.send(payload),
            {
                errorThresholdPercentage : 50,
                timeout                  : 15_000,
                resetTimeout             : 30_000,
            },
        );

        this.producerBreaker.on('open',  () => this.logger.warn('Circuit breaker opened'));
        this.producerBreaker.on('close', () => this.logger.info('Circuit breaker closed'));
    }

    /* ───────────────────────── Lifecycle ───────────────────────── */

    /**
     * Connect to Kafka and start aggregation stream.
     */
    async start() {
        await Promise.all([ this.producer.connect(), this.consumer.connect() ]);
        await this.consumer.subscribe({ topic: this.config.inputTopic, fromBeginning: false });

        this.logger.info(
            `SentimentAggregator started | groupId=${this.config.groupId} ` +
            `windowMs=${this.config.windowMs} flushMs=${this.config.flushMs}`,
        );

        this._bindConsumer();
        this._bindAggregationPipeline();
    }

    /**
     * Gracefully stop processing.
     */
    async stop() {
        this.logger.info('Stopping SentimentAggregator…');
        await Promise.allSettled([
            this.consumer.disconnect(),
            this.producer.disconnect(),
        ]);
        this.eventSubject.complete();
    }

    /* ───────────────────────── Internals ───────────────────────── */

    /**
     * Attach Kafka consumer -> RxJS Subject
     * Private.
     */
    _bindConsumer() {
        this.consumer.run({
            autoCommit: true,
            eachMessage: async ({ message }) => {
                try {
                    const payload = JSON.parse(message.value.toString('utf-8'));
                    if (!this.validateEvent(payload)) {
                        this.logger.warn(
                            `Skipping invalid event: ${JSON.stringify(this.validateEvent.errors)}`,
                        );
                        return;
                    }
                    this.eventSubject.next(payload);
                } catch (err) {
                    this.logger.error(`Failed to process message: ${err.message}`);
                }
            },
        }).catch(err => {
            this.logger.error(`Consumer failure: ${err.message}`, err);
            // Automatic restart with backoff
            setTimeout(() => this._bindConsumer(), 5_000);
        });
    }

    /**
     * Create RxJS pipeline that buffers events, aggregates stats, and
     * publishes the roll-up back to Kafka.
     * Private.
     */
    _bindAggregationPipeline() {
        this.eventSubject
            .pipe(
                bufferTime(this.config.windowMs, null, Number.POSITIVE_INFINITY), // sliding window
                filter(batch => batch.length > 0),
                mergeMap(batch => from(this._publishAggregate(batch))),
                tap({
                    error: (err) => this.logger.error(`Aggregation pipeline error: ${err.message}`),
                }),
            )
            .subscribe(); // intentionally leak subscription, closed when subject completes
    }

    /**
     * Publish aggregate statistics to Kafka.
     * @param {object[]} batch
     * @returns {Promise<void>}
     * @private
     */
    async _publishAggregate(batch) {
        const scores = batch.map(e => e.sentiment);
        const { avg, std } = calculateStats(scores);
        const aggregatePayload = {
            aggregateId : uuidv4(),
            startTs     : batch[0].timestamp,
            endTs       : batch[batch.length - 1].timestamp,
            count       : scores.length,
            avg,
            std,
        };

        const message = {
            key   : aggregatePayload.aggregateId,
            value : JSON.stringify(aggregatePayload),
        };

        try {
            await this.producerBreaker.fire({
                topic : this.config.outputTopic,
                messages: [ message ],
            });
            this.logger.debug(
                `Published aggregate: count=${aggregatePayload.count} ` +
                    `avg=${aggregatePayload.avg.toFixed(4)}`,
            );
        } catch (err) {
            this.logger.error(`Publish failed: ${err.message}`);
            // Errors are handled by circuit-breaker; no manual retry here
        }
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Factory Helper                                                             */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Build a SentimentAggregator using environment variables (12-factor).
 * Exports the factory to allow DI containers / CLI scripts to spin up easily.
 */
function buildFromEnv(overrides = {}) {
    const envCfg = {
        brokers     : (process.env.KAFKA_BROKERS || '').split(',').filter(Boolean),
        inputTopic  : process.env.KAFKA_SENTIMENT_TOPIC || 'raw-sentiment',
        outputTopic : process.env.KAFKA_AGG_SENTIMENT_TOPIC || 'agg-sentiment',
        windowMs    : Number(process.env.SENTIMENT_WINDOW_MS) || undefined,
        flushMs     : Number(process.env.SENTIMENT_FLUSH_MS)  || undefined,
    };
    return new SentimentAggregator({ ...envCfg, ...overrides });
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Exports                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */
module.exports = {
    SentimentAggregator,
    buildFromEnv,
};
```