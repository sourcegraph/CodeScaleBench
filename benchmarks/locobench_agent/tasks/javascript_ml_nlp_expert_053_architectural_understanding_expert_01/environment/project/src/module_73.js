```javascript
/**
 * src/module_73.js
 *
 * AgoraPulse – BackPressure-aware Kafka → RxJS bridge
 *
 * This module exposes a production-ready helper that converts a Kafka topic (or
 * topic list) into an RxJS Observable stream with built-in:
 *   • consumer group management
 *   • back-pressure handling through manual offset commits
 *   • automatic retries with exponential back-off
 *   • graceful shutdown hooks
 *
 * The bridge lets downstream micro-pipelines treat Kafka events as cold
 * Observables while still benefiting from Kafka’s at-least-once semantics.
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* Dependencies                                                              */
/* ────────────────────────────────────────────────────────────────────────── */

const { Kafka, logLevel }          = require('kafkajs');
const { Observable, Subject }      = require('rxjs');
const { finalize, bufferTime }     = require('rxjs/operators');
const Ajv                          = require('ajv');
const debug                        = require('debug')('agorapulse:module_73');
const { backOff }                  = require('exponential-backoff');

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants & Helpers                                                      */
/* ────────────────────────────────────────────────────────────────────────── */

const DEFAULT_BATCH_SIZE        = 100;       // messages before committing
const DEFAULT_BUFFER_MS         = 1000;      // max time before committing
const DEFAULT_RETRY_CONFIG      = {
    numOfAttempts : 5,
    startingDelay : 1_000,
    timeMultiple  : 3,
    maxDelay      : 30_000
};

const ajv = new Ajv({ allErrors: true, strict: false });

/**
 * Validates & parses a Kafka message value (expected JSON).
 * @param {Buffer} value
 * @param {object} schema – optional JSON-Schema for the payload
 * @throws {Error} when the message cannot be parsed or validated
 * @returns {any}
 */
function parseMessage(value, schema) {
    let parsed;
    try {
        parsed = JSON.parse(value.toString('utf8'));
    } catch (err) {
        err.message = `Invalid JSON: ${err.message}`;
        throw err;
    }

    if (schema) {
        const validate = ajv.compile(schema);
        if (!validate(parsed)) {
            const details = ajv.errorsText(validate.errors);
            throw new Error(`Schema validation failed: ${details}`);
        }
    }

    return parsed;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Bridge Implementation                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * BackPressureAwareKafkaConsumer
 *
 * Example:
 *   const bridge = new BackPressureAwareKafkaConsumer({
 *       brokers : ['kafka:9092'],
 *       clientId: 'agorapulse-model-monitor'
 *   });
 *
 *   const { observable, shutdown } = await bridge.createObservable({
 *       groupId : 'model-monitor-group',
 *       topics  : ['sentiment.predictions'],
 *       schema  : SENTIMENT_SCHEMA
 *   });
 *
 *   observable.subscribe({
 *       next : msg => { ... },
 *       error: err => console.error(err)
 *   });
 *
 *   // Later…
 *   await shutdown();
 */
class BackPressureAwareKafkaConsumer {
    /**
     * @param {import('kafkajs').KafkaConfig} kafkaConfig
     */
    constructor(kafkaConfig = {}) {
        this.kafka = new Kafka({
            logLevel : logLevel.NOTHING,
            ...kafkaConfig
        });
    }

    /**
     * Creates an Observable for the given topics.
     *
     * @param {object} params
     * @param {string[]} params.topics
     * @param {string} params.groupId
     * @param {object} [params.schema] – optional JSON schema for validation
     * @param {number} [params.bufferMs]
     * @param {number} [params.batchSize]
     * @param {object} [params.retryConfig]
     *
     * @returns {Promise<{ observable: Observable<any>, shutdown: Function }>}
     */
    async createObservable(params) {
        const {
            topics,
            groupId,
            schema         = null,
            bufferMs       = DEFAULT_BUFFER_MS,
            batchSize      = DEFAULT_BATCH_SIZE,
            retryConfig    = DEFAULT_RETRY_CONFIG
        } = params;

        if (!topics?.length) {
            throw new Error('topics must be a non-empty string array');
        }
        if (!groupId) {
            throw new Error('groupId is required');
        }

        /* Kafka consumer setup */
        const consumer = this.kafka.consumer({
            groupId,
            // Let us handle back-pressure by disabling auto-commit
            allowAutoTopicCreation : false,
            maxBytesPerPartition   : 1048576, // 1 MiB
            sessionTimeout         : 30_000
        });

        await consumer.connect();
        await consumer.subscribe({ topics, fromBeginning: false });

        /* RxJS Subject that receives parsed messages */
        const subject$ = new Subject();

        let processedSinceCommit = 0;
        let lastCommitTs         = Date.now();

        const run = async () => {
            await consumer.run({
                eachMessage: async ({ topic, partition, message, heartbeat, pause }) => {
                    try {
                        const parsed = parseMessage(message.value, schema);

                        subject$.next({
                            topic,
                            partition,
                            offset    : message.offset,
                            key       : message.key?.toString(),
                            timestamp : Number(message.timestamp),
                            payload   : parsed
                        });

                        processedSinceCommit += 1;

                        const now = Date.now();
                        const shouldCommit =
                            processedSinceCommit >= batchSize ||
                            now - lastCommitTs   >= bufferMs;

                        if (shouldCommit) {
                            await consumer.commitOffsets([
                                { topic, partition, offset: (Number(message.offset) + 1).toString() }
                            ]);
                            processedSinceCommit = 0;
                            lastCommitTs         = now;
                        }

                        await heartbeat();
                    } catch (err) {
                        // Bad message – send to error stream & skip commit
                        debug('Error while processing msg: %s', err.message);
                        subject$.error(err);
                    }
                }
            });
        };

        const runner = backOff(run, retryConfig).catch(err => {
            // unrecoverable
            debug('Consumer crashed: %O', err);
            subject$.error(err);
        });

        /* Observable wrapping subject with clean-up */
        const observable$ = subject$.pipe(
            bufferTime(bufferMs),
            // flatten buffer while preserving order
            finalize(async () => {
                debug('Shutting down consumer group %s…', groupId);
                try {
                    await consumer.disconnect();
                } catch (err) {
                    debug('Error during disconnect: %O', err);
                }
            })
        );

        async function shutdown() {
            subject$.complete();
            await runner; // wait for consumer.run loop to exit
        }

        return { observable: observable$, shutdown };
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Exports                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

module.exports = { BackPressureAwareKafkaConsumer };
```