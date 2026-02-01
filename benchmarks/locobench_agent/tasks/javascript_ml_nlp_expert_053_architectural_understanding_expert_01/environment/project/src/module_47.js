```javascript
/*************************************************************************
 * File:        src/module_47.js
 * Project:     AgoraPulse: Real-Time Social Signal Intelligence (ml_nlp)
 * Description: Real-time sentiment window aggregator.  Consumes fine-grained
 *              sentiment events from Kafka, computes rolling statistics per
 *              (network, conversationId) key, and publishes aggregate
 *              insights downstream.  Serves as a bridge between the
 *              low-level NLP micro-pipelines and the moderation/dashboard
 *              layers.
 *
 * Author:      AgoraPulse Engineering
 *************************************************************************/

'use strict';

/* ---------------------------------------------------------------------- *\
 | Dependencies                                                           |
\* ---------------------------------------------------------------------- */
const { KafkaClient, ConsumerGroup, Producer } = require('kafka-node');
const { Subject, merge, timer } = require('rxjs');
const {
    bufferTime,
    catchError,
    filter,
    map,
    mergeMap,
    retry,
    tap
} = require('rxjs/operators');
const _ = require('lodash');
const EventEmitter = require('events');
const debug = require('debug')('agorapulse:sentiment-aggregator');

/* ---------------------------------------------------------------------- *\
 | Configuration                                                          |
\* ---------------------------------------------------------------------- */

const CONFIG = {
    kafka: {
        brokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
        clientId: process.env.KAFKA_CLIENT_ID || 'agorapulse-sentiment-aggregator',
        groupId: process.env.KAFKA_GROUP_ID || 'agorapulse-sentiment-aggregator-group',
        inputTopic: process.env.KAFKA_INPUT_TOPIC || 'sentiment.events',
        outputTopic: process.env.KAFKA_OUTPUT_TOPIC || 'sentiment.aggregates',
        // If the upstream pipeline re-partitions events by conversation-key,
        // we can use balanced consumer groups safely.
        sessionTimeout: 15000
    },
    window: {
        // Length of the sliding window from which aggregates are computed.
        durationMs: Number(process.env.WINDOW_DURATION_MS) || 60_000,
        // How frequently we flush window aggregates downstream.
        emitEveryMs: Number(process.env.WINDOW_EMIT_FREQUENCY_MS) || 5_000
    },
    monitoring: {
        // Threshold above which we emit alerts for negative sentiment spikes.
        negativeSpikeThreshold: Number(process.env.NEGATIVE_SPIKE_THRESHOLD) || -0.4
    }
};

/* ---------------------------------------------------------------------- *\
 | Helper functions                                                       |
\* ---------------------------------------------------------------------- */

/**
 * Safely parse JSON, returning null on error.
 * @param {string} str – raw JSON string
 * @returns {object|null}
 */
function safeJsonParse(str) {
    try {
        return JSON.parse(str);
    } catch (err) {
        debug('Failed to parse JSON:', err);
        return null;
    }
}

/**
 * Compute sentiment aggregate statistics from a collection of events.
 * @param {Array<object>} events – Sentiment events in the window
 * @returns {object} – Aggregated metrics
 */
function computeAggregate(events) {
    const scores = events.map(e => Number(e.sentimentScore)).filter(_.isFinite);
    const count = scores.length;

    if (count === 0) {
        return {
            count: 0,
            avg: 0,
            min: 0,
            max: 0
        };
    }

    const sum = _.sum(scores);
    return {
        count,
        avg: sum / count,
        min: _.min(scores),
        max: _.max(scores)
    };
}

/* ---------------------------------------------------------------------- *\
 | Class: SentimentWindowAggregator                                       |
\* ---------------------------------------------------------------------- */

/**
 * Aggregates fine-grained sentiment events into rolling window statistics.
 * Emits 'alert' events when negative sentiment spikes occur.
 */
class SentimentWindowAggregator extends EventEmitter {
    /**
     * Constructor.
     *
     * @param {object} [options] – Optional overrides for CONFIG.
     */
    constructor(options = {}) {
        super();
        this.config = _.merge({}, CONFIG, options);

        // Rx subjects.
        this._event$ = new Subject();
        this._shutdown$ = new Subject();

        // Kafka wiring.
        this._kafkaClient = new KafkaClient({
            kafkaHost: this.config.kafka.brokers.join(','),
            clientId: this.config.kafka.clientId
        });

        this._consumerGroup = null;
        this._producer = null;
    }

    /* ------------------------------------------------------------------ */
    /* Public API                                                         */
    /* ------------------------------------------------------------------ */

    /**
     * Start consuming / producing streams.
     */
    start() {
        this._initKafka()
            .then(() => this._initPipeline())
            .catch(err => {
                debug('Failed to start SentimentWindowAggregator:', err);
                this.emit('error', err);
            });
    }

    /**
     * Graceful shutdown.
     */
    async stop() {
        debug('Shutting down SentimentWindowAggregator…');
        this._shutdown$.next();

        await Promise.all([
            this._closeConsumer(),
            this._closeProducer()
        ]);

        this._event$.complete();
        this._shutdown$.complete();
        debug('Shutdown complete');
    }

    /* ------------------------------------------------------------------ */
    /* Initialization helpers                                             */
    /* ------------------------------------------------------------------ */

    async _initKafka() {
        /* ------------------------------ Consumer ----------------------- */
        const consumerOpts = {
            kafkaHost: this.config.kafka.brokers.join(','),
            groupId: this.config.kafka.groupId,
            sessionTimeout: this.config.kafka.sessionTimeout,
            protocol: ['roundrobin'],
            fromOffset: 'latest'
        };

        this._consumerGroup = new ConsumerGroup(consumerOpts, [this.config.kafka.inputTopic]);
        this._consumerGroup.on('error', err => this.emit('error', err));

        // Forward each Kafka message into the Rx stream.
        this._consumerGroup.on('message', kafkaMsg => {
            const payload = safeJsonParse(kafkaMsg.value);
            if (payload) {
                this._event$.next(payload);
            }
        });

        /* ------------------------------ Producer ----------------------- */
        this._producer = new Producer(this._kafkaClient);
        await new Promise((resolve, reject) => {
            this._producer.on('ready', resolve);
            this._producer.on('error', reject);
        });

        debug('Kafka consumer & producer ready');
    }

    _initPipeline() {
        const { durationMs, emitEveryMs } = this.config.window;
        const { negativeSpikeThreshold } = this.config.monitoring;

        // Build stream pipeline.
        const aggregate$ = this._event$.pipe(
            // Organize events by (network, conversationId) key.
            // Assuming payload shape: { network, conversationId, sentimentScore, … }
            map(event => ({
                key: `${event.network}:${event.conversationId}`,
                event
            })),
            // bufferTime collects events within the sliding window.
            bufferTime(durationMs, emitEveryMs),
            filter(batch => batch.length > 0),
            map(batch => {
                // Bucket by key.
                const buckets = _.groupBy(batch, 'key');

                // Convert each bucket to aggregated metrics.
                return Object.entries(buckets).map(([key, items]) => {
                    const events = items.map(i => i.event);
                    const aggregate = computeAggregate(events);
                    const [network, conversationId] = key.split(':');

                    return {
                        network,
                        conversationId,
                        aggregate,
                        windowDurationMs: durationMs,
                        generatedAt: new Date().toISOString()
                    };
                });
            }),
            mergeMap(buckets => buckets) // flatten
        );

        /* -------------------------- Subscribe -------------------------- */
        this._subscription = merge(
            // Main path: forward aggregates to Kafka
            aggregate$.pipe(
                tap(agg => this._publishAggregate(agg)),
                catchError(err => {
                    this.emit('error', err);
                    return [];
                })
            ),

            // Monitoring path: detect negative spikes
            aggregate$.pipe(
                filter(agg => agg.aggregate.avg <= negativeSpikeThreshold),
                tap(agg => this.emit('alert', {
                    type: 'NEGATIVE_SENTIMENT_SPIKE',
                    payload: agg
                })),
                catchError(err => {
                    this.emit('error', err);
                    return [];
                })
            )
        )
            // Retry on unexpected stream errors.
            .pipe(retry({ count: Infinity, delay: () => timer(1_000) }))
            // Ensure we unsubscribe when shutdown$ fires.
            .subscribe({
                complete: () => debug('Aggregator pipeline completed')
            });

        debug('SentimentWindowAggregator pipeline started');
    }

    /* ------------------------------------------------------------------ */
    /* Kafka publish helpers                                              */
    /* ------------------------------------------------------------------ */

    /**
     * Produce an aggregate record to the output Kafka topic.
     * @param {object} agg – Aggregate payload
     * @private
     */
    _publishAggregate(agg) {
        const payloads = [
            {
                topic: this.config.kafka.outputTopic,
                messages: JSON.stringify(agg),
                key: `${agg.network}:${agg.conversationId}`
            }
        ];

        this._producer.send(payloads, err => {
            if (err) {
                this.emit('error', err);
            }
        });
    }

    /* ------------------------------------------------------------------ */
    /* Shutdown helpers                                                   */
    /* ------------------------------------------------------------------ */

    _closeConsumer() {
        if (!this._consumerGroup) return Promise.resolve();

        return new Promise(resolve => {
            this._consumerGroup.close(true, () => {
                debug('Kafka consumer closed');
                resolve();
            });
        });
    }

    _closeProducer() {
        if (!this._producer) return Promise.resolve();

        return new Promise(resolve => {
            this._producer.close(() => {
                debug('Kafka producer closed');
                resolve();
            });
        });
    }
}

/* ---------------------------------------------------------------------- *\
 | Module exports                                                         |
\* ---------------------------------------------------------------------- */

module.exports = {
    SentimentWindowAggregator
};
```