```javascript
/**
 * src/module_23.js
 *
 * EventStreamBridge
 * -----------------
 * A resilient, back-pressure aware bridge between Kafka topic(s) that emit
 * raw domain events and the internal RxJS event bus used by downstream
 * AgoraPulse feature-engineering micro-pipelines.
 *
 * Responsibilities:
 *  • Subscribe to one or more Kafka topics (wildcards supported)
 *  • Validate event envelopes against a Zod schema
 *  • Expose a cold RxJS Observable that replays the most-recent N events
 *  • Provide back-pressure handling by pausing / resuming the Kafka consumer
 *  • Publish basic Prometheus metrics for monitoring & alerting
 *
 * NOTE: This module is written in plain JavaScript (ES2022) to maximise
 *       portability across service boundaries inside the monorepo.
 */

/* ────────────────────────────────────────────────────────────────────────── */
import { EventEmitter }          from 'node:events';
import { setTimeout as wait }    from 'node:timers/promises';
import { Kafka, logLevel }       from 'kafkajs';
import { Subject, merge }        from 'rxjs';
import {
    filter,
    map,
    shareReplay,
    tap,
    throttleTime,
}                                from 'rxjs/operators';
import { z }                     from 'zod';
import pRetry                    from 'p-retry';
import * as winston              from 'winston';
import client, {
    Counter,
    Gauge,
}                                from 'prom-client';

/* ─────────────────────────────── Logger  ───────────────────────────────── */
const logger = winston.createLogger({
    level   : process.env.LOG_LEVEL || 'info',
    format  : winston.format.combine(
        winston.format.timestamp(),
        winston.format.json(),
    ),
    transports: [ new winston.transports.Console() ],
});

/* ──────────────────────────── Metrics Setup ────────────────────────────── */
const registry = new client.Registry();
client.collectDefaultMetrics({ register: registry });

const msgConsumedCounter = new Counter({
    name      : 'agorapulse_bridge_messages_total',
    help      : 'Total number of messages consumed from Kafka',
    labelNames: ['topic'],
});

const msgDroppedCounter = new Counter({
    name      : 'agorapulse_bridge_messages_dropped_total',
    help      : 'Total number of malformed / invalid messages dropped',
    labelNames: ['topic', 'reason'],
});

const consumerLagGauge = new Gauge({
    name      : 'agorapulse_bridge_consumer_lag',
    help      : 'Kafka consumer lag in messages',
    labelNames: ['topic', 'partition'],
});

registry.registerMetric(msgConsumedCounter);
registry.registerMetric(msgDroppedCounter);
registry.registerMetric(consumerLagGauge);

/* ─────────────────────────── Event Schema  ───────────────────────────────
 * Each event must contain a required envelope with metadata used throughout
 * the AgoraPulse data-plane.
 */
const EventEnvelopeSchema = z.object({
    eventId     : z.string().uuid(),
    timestamp   : z.number().int().positive(),
    eventType   : z.string().min(3),
    actorId     : z.string().min(1),
    payload     : z.any(),
    correlation : z.string().optional(),
});

/* ──────────────────────── Back-Pressure Settings ───────────────────────── */
const BATCH_SIZE               = 250;
const HIGH_WATERMARK_THRESHOLD = 2000;          // # of queued items
const LOW_WATERMARK_THRESHOLD  = 500;           // resume when queue < this

/* ───────────────────────── Class: EventStreamBridge ────────────────────── */
export class EventStreamBridge extends EventEmitter {

    /**
     * @param {Object} opts
     * @param {string[]} opts.topics – List of Kafka topics (supports * suffix)
     * @param {string}   opts.groupId – Kafka consumer group
     * @param {Object}   [opts.kafkaConfig] – KafkaJS client configuration
     * @param {number}   [opts.replayBuffer=1000] – Size of replay buffer
     */
    constructor({
        topics,
        groupId,
        kafkaConfig = {},
        replayBuffer = 1000,
    }) {
        super();

        if (!Array.isArray(topics) || topics.length === 0) {
            throw new TypeError('topics must be a non-empty array');
        }
        if (typeof groupId !== 'string' || groupId.length === 0) {
            throw new TypeError('groupId must be a non-empty string');
        }

        this.topics   = topics;
        this.groupId  = groupId;
        this.kafka    = new Kafka({
            clientId : 'agorapulse-event-bridge',
            brokers  : (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
            logLevel : logLevel.NOTHING,
            ...kafkaConfig,
        });

        this.consumer            = this.kafka.consumer({ groupId });
        this.subject             = new Subject();
        this.replay$             = this.subject.pipe(shareReplay(replayBuffer));
        this._pauseRequested     = false;
        this._queueDepthEstimate = 0;
    }

    /* ─────────────────── Public API ─────────────────── */

    /**
     * Returns a cold Observable stream of validated events
     * Downstream operators can further filter / transform as needed.
     */
    observe() {
        return this.replay$;
    }

    /**
     * Connect to Kafka, subscribe to topics and begin streaming events.
     * Automatically retries with exponential back-off.
     */
    async connect() {
        await pRetry(
            async () => {
                await this.consumer.connect();
                await this._subscribeToTopics();
            },
            {
                retries           : 5,
                minTimeout        : 1000,
                maxTimeout        : 15000,
                onFailedAttempt: err => {
                    logger.warn({ msg: 'Kafka connection attempt failed', ...err });
                },
            },
        );

        await this.consumer.run({
            autoCommit: false,
            eachBatch : async ({ batch, resolveOffset, heartbeat, pause }) => {
                // Back-pressure management
                if (this._pauseRequested) {
                    pause();
                    await wait(100); // small sleep to yield
                    return;
                }

                let processed = 0;
                for (const message of batch.messages) {
                    this._handleRawMessage(batch.topic, message);
                    resolveOffset(message.offset);
                    processed += 1;
                }

                // Update internal queue depth estimation
                this._queueDepthEstimate += processed;
                await heartbeat();

                // Commit offsets manually for reliability
                await this.consumer.commitOffsets([
                    { topic: batch.topic, partition: batch.partition, offset: (Number(batch.lastOffset()) + 1).toString() },
                ]);

                // Expose consumer lag gauge
                consumerLagGauge.set(
                    { topic: batch.topic, partition: batch.partition },
                    Number(batch.highWatermark) - Number(batch.lastOffset()),
                );
            },
        });

        logger.info({ msg: 'EventStreamBridge connected', topics: this.topics });
    }

    /**
     * Gracefully disconnect from Kafka and complete the Observable.
     */
    async disconnect() {
        try {
            await this.consumer.disconnect();
            this.subject.complete();
            logger.info({ msg: 'EventStreamBridge disconnected' });
        } catch (err) {
            logger.error({ msg: 'Error during disconnect', err });
        }
    }

    /* ─────────────────── Internal Helpers ─────────────────── */

    async _subscribeToTopics() {
        for (const topic of this.topics) {
            if (topic.endsWith('*')) {
                // Wildcard pattern subscription (prefix match)
                const prefix = topic.slice(0, -1);
                await this.consumer.subscribe({ topic: new RegExp(`^${prefix}.*`), fromBeginning: false });
            } else {
                await this.consumer.subscribe({ topic, fromBeginning: false });
            }
        }
    }

    _handleRawMessage(topic, message) {
        const rawPayload = message.value?.toString('utf8');
        let parsed;
        try {
            parsed = JSON.parse(rawPayload);
        } catch (err) {
            msgDroppedCounter.inc({ topic, reason: 'malformed-json' });
            logger.debug({ msg: 'Dropping malformed JSON', topic, err });
            return;
        }

        const validation = EventEnvelopeSchema.safeParse(parsed);
        if (!validation.success) {
            msgDroppedCounter.inc({ topic, reason: 'schema-violation' });
            if (process.env.NODE_ENV !== 'production') {
                logger.debug({ msg: 'Schema violation', topic, errors: validation.error.errors });
            }
            return;
        }

        // Push to the Subject.
        this.subject.next({
            ...validation.data,
            _kafka: {
                topic,
                partition: message.partition,
                offset: message.offset,
                timestamp: message.timestamp,
            },
        });

        msgConsumedCounter.inc({ topic });

        // Basic queuing heuristic for back-pressure
        this._queueDepthEstimate = Math.max(0, this._queueDepthEstimate - 1);
        if (this._queueDepthEstimate > HIGH_WATERMARK_THRESHOLD && !this._pauseRequested) {
            logger.warn({ msg: 'High watermark reached, pausing Kafka consumption' });
            this._pauseRequested = true;
        } else if (this._pauseRequested && this._queueDepthEstimate < LOW_WATERMARK_THRESHOLD) {
            logger.info({ msg: 'Queue drained, resuming Kafka consumption' });
            this._pauseRequested = false;
        }
    }

    /* ─────────────────── Static Utility ─────────────────── */

    /**
     * Expose an express-compatible handler that returns Prometheus metrics.
     * Example:
     *     app.get('/metrics', EventStreamBridge.metricsEndpoint());
     */
    static metricsEndpoint() {
        return async (_req, res) => {
            try {
                res.set('Content-Type', registry.contentType);
                res.end(await registry.metrics());
            } catch (err) {
                res.status(500).end(err);
            }
        };
    }
}

/* ────────────────────────────── Example Usage ────────────────────────────
 * The following snippet demonstrates how a micro-pipeline could consume the
 * event stream and perform light transformations before passing it on.
 *
 *      import express from 'express';
 *      import { EventStreamBridge } from './module_23.js';
 *
 *      const bridge = new EventStreamBridge({
 *          topics  : ['social_events.*'],
 *          groupId : 'moderation-pipeline-1',
 *      });
 *
 *      // Connect at process startup
 *      await bridge.connect();
 *
 *      // Down-stream RxJS subscription
 *      bridge.observe()
 *            .pipe(
 *                filter(e => e.eventType === 'MESSAGE_CREATED'),
 *                throttleTime(250),
 *                map(e => e.payload.text),
 *            )
 *            .subscribe({
 *                 next : text => console.log('New message:', text),
 *                 error: err => console.error('Stream error', err),
 *            });
 *
 *      // Expose Prometheus metrics
 *      const app = express();
 *      app.get('/metrics', EventStreamBridge.metricsEndpoint());
 *      app.listen(8080);
 *
 * Remember to handle graceful shutdown by invoking bridge.disconnect() during
 * SIGINT / SIGTERM events.
 */
/* ────────────────────────────────────────────────────────────────────────── */
export default EventStreamBridge;
```