```javascript
/**
 * src/module_41.js
 *
 * SentimentWindowAggregator
 * -------------------------
 * Continuously consumes fine-grained sentiment events emitted by the micro-pipelines,
 * aggregates them in (overlapping) sliding time windows, and re-publishes summary
 * statistics back to Kafka for live dashboards, anomaly detectors, and model
 * monitoring jobs.
 *
 * Design goals:
 *   • Decouple ingestion, aggregation, and publishing via RxJS operators.
 *   • Keep the API surface minimal—call `.start()` to begin streaming and `.stop()`
 *     for graceful shutdown.
 *   • Back-pressure aware: uses `pause()`/`resume()` on the Kafka consumer whenever
 *     the internal RxJS queue grows beyond `highWaterMark`.
 *
 * Expected input message shape (JSON):
 *   {
 *     "topicId"        : "football_worldcup",
 *     "userId"         : "937261",
 *     "sentimentScore" : 0.73,           // Range: [-1, 1]
 *     "ts"             : 1675089259123   // Unix epoch millis
 *   }
 *
 * Output message shape (JSON):
 *   {
 *     "topicId"          : "football_worldcup",
 *     "windowStart"      : 1675089259000,  // Inclusive
 *     "windowEnd"        : 1675089264000,  // Exclusive
 *     "avgSentiment"     : 0.64,
 *     "numMessages"      : 542,
 *     "lastUpdated"      : 1675089264123
 *   }
 */

import { Kafka, logLevel } from 'kafkajs';
import {
    fromEvent,
    Subject,
    bufferTime,
    mergeMap,
    groupBy,
    map,
    reduce,
    filter,
    tap,
    merge,
    takeUntil,
    share,
} from 'rxjs';
import pino from 'pino';

// ---------------------------------------------------------------------------
// Configuration helpers
// ---------------------------------------------------------------------------

const env = (key, def) => process.env[key] ?? def;

const CONFIG = Object.freeze({
    kafka: {
        clientId      : env('AGORA_CLIENT_ID', 'agora-pulse.sentiment-window'),
        brokers       : (env('AGORA_KAFKA_BROKERS', 'localhost:9092')).split(','),
        inputTopic    : env('AGORA_SENTIMENT_INPUT_TOPIC', 'sentiment.raw'),
        outputTopic   : env('AGORA_SENTIMENT_AGG_TOPIC', 'sentiment.windowed'),
        groupId       : env('AGORA_SENTIMENT_GROUP', 'sentiment-window-agg'),
    },
    window: {
        sizeMs        : Number(env('AGORA_WINDOW_SIZE_MS', 5_000)),   // 5 s window
        slideMs       : Number(env('AGORA_WINDOW_SLIDE_MS', 1_000)),  // every 1 s
    },
    rx: {
        highWaterMark : Number(env('AGORA_RX_HWM', 10_000)),
    }
});

const logger = pino({
    name: 'SentimentWindowAggregator',
    level: env('LOG_LEVEL', 'info'),
});

// ---------------------------------------------------------------------------
// Utility functions
// ---------------------------------------------------------------------------

/**
 * Safely JSON.parse with fallback to null.
 * @param {string|Buffer} raw
 * @returns {object|null}
 */
function safeParse(raw) {
    try {
        return JSON.parse(raw.toString());
    } catch (err) {
        logger.warn({ err, raw }, 'Failed to parse JSON');
        return null;
    }
}

/**
 * Calculate average of an array of numbers
 * @param {number[]} list
 * @returns {number}
 */
const avg = (list) => list.reduce((a, b) => a + b, 0) / (list.length || 1);

// ---------------------------------------------------------------------------
// Core class
// ---------------------------------------------------------------------------

export class SentimentWindowAggregator {
    /**
     * @param {object} [config]
     */
    constructor(config = {}) {
        this.cfg = {
            ...CONFIG,
            ...config,
            kafka: { ...CONFIG.kafka, ...(config.kafka ?? {}) },
            window: { ...CONFIG.window, ...(config.window ?? {}) },
            rx: { ...CONFIG.rx, ...(config.rx ?? {}) }
        };

        this.kafka = new Kafka({
            clientId : this.cfg.kafka.clientId,
            brokers  : this.cfg.kafka.brokers,
            logLevel : logLevel.NOTHING, // we rely on pino
        });

        this.consumer = this.kafka.consumer({
            groupId: this.cfg.kafka.groupId,
        });

        this.producer = this.kafka.producer();

        // For a clean shutdown
        this._stop$ = new Subject();
        this._running = false;
    }

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    async start() {
        if (this._running) {
            logger.warn('Aggregator already running');
            return;
        }
        await this.consumer.connect();
        await this.producer.connect();
        await this.consumer.subscribe({ topic: this.cfg.kafka.inputTopic, fromBeginning: false });

        // RxJS stream from Kafka
        const message$ = fromEvent(this.consumer, 'message').pipe(
            map(({ topic, partition, message }) => safeParse(message.value)),
            filter(Boolean),
            share(), // multicast to buffering + hwm logic
        );

        this._setupBackpressureMonitoring(message$);

        // Sliding window aggregation
        const windowed$ = message$.pipe(
            bufferTime(this.cfg.window.sizeMs, this.cfg.window.slideMs),
            filter(buf => buf.length > 0), // skip empty buffers
            mergeMap(buffer => buffer),    // flatten each buffer to messages
            groupBy(msg => msg.topicId),
            mergeMap(group$ =>
                group$.pipe(
                    reduce((acc, msg) => {
                        acc.scores.push(msg.sentimentScore);
                        acc.count++;
                        return acc;
                    }, { topicId: group$.key, scores: [], count: 0 }),
                    map(({ topicId, scores, count }) => ({
                        topicId,
                        windowStart : Date.now() - this.cfg.window.sizeMs,
                        windowEnd   : Date.now(),
                        avgSentiment: Number(avg(scores).toFixed(3)),
                        numMessages : count,
                        lastUpdated : Date.now(),
                    }))
                )
            ),
            takeUntil(this._stop$),
        );

        // Publish aggregated result to Kafka
        this.publishSub = windowed$.subscribe({
            next: (payload) => this._publish(payload),
            error: (err) => logger.error({ err }, 'Stream error'),
            complete: () => logger.info('Window stream completed'),
        });

        // Kick off the Kafka consumption loop
        await this.consumer.run({
            autoCommit: true,
            eachMessage: async (payload) => {
                this.consumer.emit('message', payload);
            },
        });

        this._running = true;
        logger.info({ config: this.cfg }, 'SentimentWindowAggregator started');
    }

    async stop() {
        if (!this._running) return;
        this._stop$.next(true);
        this._stop$.complete();
        await this.publishSub?.unsubscribe();
        await this.consumer.disconnect();
        await this.producer.disconnect();
        this._running = false;
        logger.info('SentimentWindowAggregator stopped');
    }

    // -----------------------------------------------------------------------
    // Internals
    // -----------------------------------------------------------------------

    /**
     * Publish aggregated record to output Kafka topic.
     * @param {object} record
     * @private
     */
    async _publish(record) {
        try {
            await this.producer.send({
                topic: this.cfg.kafka.outputTopic,
                messages: [
                    {
                        key: record.topicId,
                        value: JSON.stringify(record),
                        timestamp: `${record.lastUpdated}`,
                    }
                ],
            });
            logger.debug({ record }, 'Published aggregated sentiment');
        } catch (err) {
            logger.error({ err, record }, 'Failed to publish aggregated sentiment');
        }
    }

    /**
     * Monitors the size of the RxJS internal buffer and applies back-pressure
     * by pausing / resuming the Kafka consumer.
     * @param {import('rxjs').Observable} stream$
     * @private
     */
    _setupBackpressureMonitoring(stream$) {
        let buffered = 0;

        // Keep a rolling counter
        stream$.pipe(
            tap(() => {
                buffered++;
                if (buffered > this.cfg.rx.highWaterMark) {
                    logger.warn({ buffered }, 'High water mark reached - pausing consumer');
                    this.consumer.pause([{ topic: this.cfg.kafka.inputTopic }]);
                }
            }),
            takeUntil(this._stop$)
        ).subscribe({
            complete: () => {
                // Ensure consumer is resumed when shutting down
                this.consumer.resume([{ topic: this.cfg.kafka.inputTopic }]);
            }
        });

        // Decrement counter when item exits buffer
        stream$.subscribe({
            next: () => {
                if (buffered > 0) buffered--;
                if (buffered < this.cfg.rx.highWaterMark / 2) {
                    // Resume when buffer drains below 50% threshold
                    this.consumer.resume([{ topic: this.cfg.kafka.inputTopic }]);
                }
            }
        });
    }
}

// Convenience factory -------------------------------------------------------

/**
 * @param {object} [override]
 * @returns {SentimentWindowAggregator}
 */
export function createSentimentWindowAggregator(override = {}) {
    return new SentimentWindowAggregator(override);
}

// ---------------------------------------------------------------------------
// Start automatically when invoked via CLI: `node src/module_41.js`
// ---------------------------------------------------------------------------

if (require.main === module) {
    // Graceful shutdown handlers
    const aggregator = createSentimentWindowAggregator();

    const shutdown = async (sig) => {
        logger.info({ sig }, 'Received shutdown signal');
        try {
            await aggregator.stop();
            process.exit(0);
        } catch (err) {
            logger.error({ err }, 'Error during shutdown');
            process.exit(1);
        }
    };

    process.once('SIGINT', shutdown);
    process.once('SIGTERM', shutdown);

    aggregator.start().catch((err) => {
        logger.error({ err }, 'Fatal error while starting aggregator');
        process.exit(1);
    });
}
```