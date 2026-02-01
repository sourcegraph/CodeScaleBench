```javascript
/**
 * src/module_35.js
 *
 * KafkaRxBridge
 * -------------
 * A thin but powerful wrapper that turns Kafka topics into RxJS observables
 * and vice-versa.  Used by the event-driven core to fan-out domain events
 * through both Kafka and RxJS with unified back-pressure semantics.
 *
 * Production-grade features included:
 *  • Automatic reconnects with exponential back-off
 *  • Graceful shutdown hooks
 *  • Prometheus metrics
 *  • Pluggable serializers / deserializers
 *  • Type-safe (via JSDoc) message envelopes
 *
 * NOTE: This file is written in modern ES2022 JavaScript; consumers can compile
 *       down to earlier versions through Babel if necessary.
 */

import { Kafka, logLevel } from 'kafkajs';
import { Observable, Subject } from 'rxjs';
import { tap, finalize } from 'rxjs/operators';
import pRetry from 'p-retry';
import pino from 'pino';
import * as promClient from 'prom-client';

// ---------------------------------------------------------------------------
// Configuration helpers
// ---------------------------------------------------------------------------

const {
  KAFKA_BROKERS = '',
  KAFKA_CLIENT_ID = 'agora-pulse-core',
  KAFKA_LOG_LEVEL = 'WARN',
  KAFKA_DEFAULT_GROUP_ID = 'agora-pulse-pipeline',
} = process.env;

const toKafkaLogLevel = (lvl) =>
  ({
    TRACE: logLevel.DEBUG,
    DEBUG: logLevel.DEBUG,
    INFO: logLevel.INFO,
    WARN: logLevel.WARN,
    ERROR: logLevel.ERROR,
  }[lvl.toUpperCase()] ?? logLevel.WARN);

// ---------------------------------------------------------------------------
// Logger
// ---------------------------------------------------------------------------

const logger = pino({
  name: 'KafkaRxBridge',
  level: (process.env.LOG_LEVEL || 'info').toLowerCase(),
});

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

const metrics = {
  messagesConsumed: new promClient.Counter({
    name: 'agorapulse_kafka_messages_consumed_total',
    help: 'Total number of messages consumed by KafkaRxBridge',
    labelNames: ['topic'],
  }),
  messagesProduced: new promClient.Counter({
    name: 'agorapulse_kafka_messages_produced_total',
    help: 'Total number of messages produced by KafkaRxBridge',
    labelNames: ['topic'],
  }),
  consumerLag: new promClient.Gauge({
    name: 'agorapulse_kafka_consumer_lag',
    help: 'Current consumer lag (high watermark offset - committed)',
    labelNames: ['topic', 'partition'],
  }),
};

// ---------------------------------------------------------------------------
// Default (de)serializers – can be overridden per-method call
// ---------------------------------------------------------------------------

const defaultSerializer = (data) => Buffer.from(JSON.stringify(data));
const defaultDeserializer = (buf) => JSON.parse(buf.toString());

// ---------------------------------------------------------------------------
// KafkaRxBridge implementation
// ---------------------------------------------------------------------------

export class KafkaRxBridge {
  /**
   * @param {Object} [options]
   * @param {string[]} [options.brokers]
   * @param {string}   [options.clientId]
   * @param {logLevel} [options.logLevel]
   */
  constructor({
    brokers = KAFKA_BROKERS.split(',').filter(Boolean),
    clientId = KAFKA_CLIENT_ID,
    logLevel = toKafkaLogLevel(KAFKA_LOG_LEVEL),
  } = {}) {
    if (!brokers.length) {
      throw new Error(
        'KafkaRxBridge: At least one broker address must be provided in env KAFKA_BROKERS or constructor options',
      );
    }

    this.kafka = new Kafka({ brokers, clientId, logLevel });
    this._subscriptions = new Set(); // Track active consumers for shutdown
    logger.info({ brokers, clientId }, 'KafkaRxBridge initialized');
  }

  /**
   * Turns a Kafka topic into an RxJS Observable stream.
   *
   * @template T
   * @param {string|string[]} topics
   * @param {Object} [opts]
   * @param {string}  [opts.groupId]                    Consumer group id
   * @param {number}  [opts.maxBytesPerPartition=1048576]
   * @param {Function} [opts.deserializer]              (msg.value) => T
   * @param {boolean} [opts.autoCommit=true]            Auto-commit after nextTick
   * @returns {Observable<{value: T, topic: string, partition: number, offset: string}>}
   */
  createTopicObservable(
    topics,
    {
      groupId = KAFKA_DEFAULT_GROUP_ID,
      maxBytesPerPartition = 1_048_576,
      deserializer = defaultDeserializer,
      autoCommit = true,
    } = {},
  ) {
    const topicList = Array.isArray(topics) ? topics : [topics];
    const subject = new Subject();

    const consumer = this.kafka.consumer({ groupId, maxBytesPerPartition });
    this._subscriptions.add(consumer);

    const connectAndRun = async () => {
      await consumer.connect();
      for (const topic of topicList) {
        await consumer.subscribe({ topic, fromBeginning: false });
      }

      await consumer.run({
        eachMessage: async ({ topic, partition, message, heartbeat, commitOffsetsIfNecessary }) => {
          try {
            metrics.messagesConsumed.inc({ topic });
            const deserialized = deserializer(message.value);
            const payload = { value: deserialized, topic, partition, offset: message.offset };

            // Push downstream
            subject.next(payload);

            // Back-pressure: wait until next micro-task tick to commit to allow
            // synchronous observers to throw (so we can gracefully stop)
            if (autoCommit) {
              setImmediate(async () => {
                try {
                  await commitOffsetsIfNecessary();
                  await heartbeat();
                } catch (err) {
                  logger.warn({ err }, 'Commit / heartbeat failed');
                }
              });
            }
          } catch (err) {
            logger.error({ err }, 'Failed to process message – closing observable');
            subject.error(err);
          }
        },
      });
    };

    // Attach retry logic
    pRetry(connectAndRun, {
      forever: true,
      onFailedAttempt: (err) =>
        logger.warn(
          { attempt: err.attemptNumber, retriesLeft: err.retriesLeft, err },
          'Kafka consumer failed – retrying',
        ),
    }).catch((err) => {
      // This should never happen because forever: true, but guard anyway
      subject.error(err);
    });

    const observable = subject.asObservable().pipe(
      tap(({ topic, partition, offset }) => {
        metrics.consumerLag.set({ topic, partition }, Number(offset));
      }),
      finalize(async () => {
        logger.info({ topics: topicList }, 'Observable finalizing – disconnecting consumer');
        try {
          await consumer.disconnect();
        } catch (err) {
          logger.warn({ err }, 'Error disconnecting consumer');
        } finally {
          this._subscriptions.delete(consumer);
        }
      }),
    );

    return observable;
  }

  /**
   * Pushes an RxJS or AsyncIterable stream into a Kafka topic.
   *
   * @template T
   * @param {Observable<T>|AsyncIterable<T>} stream
   * @param {string} topic
   * @param {Object} [opts]
   * @param {Function} [opts.serializer] (data: T) => Buffer
   * @param {number}   [opts.batchSize=100]
   * @returns {Promise<void>}
   */
  async produceFromStream(
    stream,
    topic,
    { serializer = defaultSerializer, batchSize = 100 } = {},
  ) {
    const producer = this.kafka.producer();
    await producer.connect();
    logger.info({ topic }, 'Kafka producer connected');

    const sendBatch = async (messages) => {
      if (!messages.length) return;
      await producer.send({ topic, messages });
      messages.forEach(() => metrics.messagesProduced.inc({ topic }));
    };

    const buffer = [];
    const flushIfNeeded = async () => {
      if (buffer.length >= batchSize) {
        await sendBatch(buffer.splice(0, buffer.length));
      }
    };

    const finalize = async () => {
      await sendBatch(buffer);
      await producer.disconnect();
      logger.info({ topic }, 'Kafka producer disconnected');
    };

    // Stream may be an RxJS observable or AsyncIterable
    const asyncIter = typeof stream[Symbol.asyncIterator] === 'function'
      ? stream[Symbol.asyncIterator]()
      : stream[Symbol.iterator] // RxJS observable
        ? (async function* () {
            let done = false;
            const sub = stream.subscribe({
              next: (val) => buffer.push({ value: serializer(val) }),
              error: async (err) => {
                logger.error({ err }, 'Stream error – terminating producer');
                done = true;
                await finalize();
              },
              complete: async () => {
                done = true;
                await finalize();
              },
            });

            while (!done) {
              await flushIfNeeded();
              await new Promise((r) => setTimeout(r, 10));
            }
            sub.unsubscribe();
          })()
        : null;

    if (!asyncIter) {
      throw new Error('Unsupported stream type. Provide Observable or AsyncIterable.');
    }

    for await (const data of asyncIter) {
      if (data != null) buffer.push({ value: serializer(data) });
      await flushIfNeeded();
    }

    await finalize();
  }

  // -------------------------------------------------------------------------
  // Graceful shutdown helpers
  // -------------------------------------------------------------------------

  /**
   * Disconnects all active consumers/producers managed by this bridge.
   * Should be called on application shutdown.
   */
  async close() {
    logger.info('Closing KafkaRxBridge…');
    await Promise.all(
      [...this._subscriptions].map((sub) =>
        sub
          .disconnect()
          .catch((err) => logger.warn({ err }, 'Failed to disconnect consumer')),
      ),
    );
    this._subscriptions.clear();
    logger.info('KafkaRxBridge closed');
  }
}

// ---------------------------------------------------------------------------
// Process signal handling
// ---------------------------------------------------------------------------

/* c8 ignore start */
const bridges = new Set();
export const registerBridgeInstance = (bridge) => bridges.add(bridge);

const handleTerminationSignal = async (signal) => {
  logger.info({ signal }, 'Received termination signal – shutting down bridges');
  await Promise.all([...bridges].map((b) => b.close()));
  process.exit(0);
};

process.once('SIGTERM', handleTerminationSignal);
process.once('SIGINT', handleTerminationSignal);
/* c8 ignore end */
```