```javascript
/**
 * src/module_21.js
 *
 * High-throughput domain-event ingestion and real-time feature-engineering pipeline
 * for AgoraPulse.  Bridges a Kafka topic => RxJS observable => pluggable
 * Strategy-based feature extractor => downstream Kafka sink.
 *
 * The module purposefully keeps business-logic agnostic; concrete strategies are
 * late-bound to support online A/B testing and hot-swaps without broker restarts.
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, timer, from } from 'rxjs';
import {
    catchError,
    filter,
    map,
    mergeMap,
    retryWhen,
    tap,
    timeout as rxTimeout,
} from 'rxjs/operators';
import Ajv from 'ajv';
import { readFile } from 'fs/promises';
import { join as joinPath } from 'path';
import pino from 'pino';

/* -------------------------------------------------------------------------- */
/* Configuration & logger                                                     */
/* -------------------------------------------------------------------------- */

const DEFAULT_CONSUMER_CONFIG = {
    clientId: 'agorapulse-realtime-consumer',
    brokers: ['localhost:9092'],
    groupId: 'agorapulse-realtime-group',
    topics: ['domain-events'],
    maxBytesPerPartition: 5242880, // 5 MB
};

const DEFAULT_PRODUCER_CONFIG = {
    clientId: 'agorapulse-feature-producer',
    brokers: ['localhost:9092'],
    topic: 'feature-events',
};

const log = pino({ name: 'module_21' });

/* -------------------------------------------------------------------------- */
/* DomainEventStream: Kafka => RxJS Subject                                   */
/* -------------------------------------------------------------------------- */

/**
 * DomainEventStream consumes Kafka topics and exposes a hot Subject emitting
 * validated domain events.
 */
export class DomainEventStream {
    /**
     * @param {object} config   Consumer configuration
     * @param {object} schema   JSON schema for basic envelope validation
     */
    constructor(config = DEFAULT_CONSUMER_CONFIG, schema) {
        this._config = { ...DEFAULT_CONSUMER_CONFIG, ...config };
        this._kafka = new Kafka({
            clientId: this._config.clientId,
            brokers: this._config.brokers,
            logLevel: logLevel.NOTHING,
        });

        this._consumer = this._kafka.consumer({ groupId: this._config.groupId });
        this._event$ = new Subject(); // Hot observable for subscribers

        if (!schema) {
            throw new Error('DomainEventStream requires a validation schema');
        }
        const ajv = new Ajv({ strict: false, removeAdditional: 'failing' });
        this._validator = ajv.compile(schema);
    }

    /**
     * Hot observable for downstream subscribers
     */
    get stream$() {
        return this._event$.asObservable();
    }

    /**
     * Connects to Kafka and starts consuming messages.
     */
    async start() {
        await this._consumer.connect();
        for (const topic of this._config.topics) {
            await this._consumer.subscribe({ topic, fromBeginning: false });
        }

        await this._consumer.run({
            eachMessage: async ({ topic, message }) => {
                try {
                    const payload = JSON.parse(message.value.toString());
                    if (this._validator(payload)) {
                        this._event$.next({ topic, partition: message.partition, payload });
                    } else {
                        log.warn(
                            { errors: this._validator.errors, payload },
                            'Schema validation failed'
                        );
                    }
                } catch (err) {
                    log.error({ err }, 'Failed to deserialize message');
                }
            },
        });

        log.info('DomainEventStream started');
    }

    /**
     * Graceful shutdown.
     */
    async stop() {
        await this._consumer.disconnect().catch((e) => log.error(e, 'Error disconnecting'));
        // Complete observable so that downstream can dispose
        this._event$.complete();
        log.info('DomainEventStream stopped');
    }
}

/* -------------------------------------------------------------------------- */
/* Feature Strategy interface + dynamic loader                                */
/* -------------------------------------------------------------------------- */

/**
 * Abstract base class for feature engineering strategies.
 * Concrete implementations must implement `extract(event)`.
 */
export class FeatureStrategy {
    /**
     * @param {object} event - validated domain event
     * @returns {Promise<object>} feature object (resolved)
     */
    // eslint-disable-next-line class-methods-use-this, no-unused-vars
    async extract(event) {
        throw new Error('FeatureStrategy.extract() must be implemented');
    }
}

/**
 * Dynamically loads strategy modules discovered in the provided directory.
 * Each file must export either:
 *  - default class extending FeatureStrategy
 *  - named class 'Strategy' extending FeatureStrategy
 *
 * @param {string} directory absolute path
 * @returns {Promise<Map<string, FeatureStrategy>>} map eventType -> strategy
 */
export async function loadStrategies(directory) {
    const entries = await readFile(joinPath(directory, 'manifest.json'), 'utf8').catch((err) => {
        throw new Error(`Unable to read strategy manifest: ${err.message}`);
    });

    const manifest = JSON.parse(entries);
    const strategies = new Map();

    await Promise.all(
        manifest.map(async ({ eventType, module }) => {
            try {
                /* eslint-disable import/no-dynamic-require, global-require */
                const imported = await import(joinPath(directory, module));
                const StrategyClass =
                    imported.default || imported.Strategy || Object.values(imported)[0];
                const instance = new StrategyClass();

                if (!(instance instanceof FeatureStrategy)) {
                    throw new Error(`Module ${module} does not export a FeatureStrategy`);
                }
                strategies.set(eventType, instance);
            } catch (err) {
                log.error({ err, module }, 'Failed to load strategy');
            }
        })
    );

    return strategies;
}

/* -------------------------------------------------------------------------- */
/* FeatureEngineeringPipeline                                                 */
/* -------------------------------------------------------------------------- */

export class FeatureEngineeringPipeline {
    /**
     * @param {Map<string, FeatureStrategy>} strategies
     * @param {object} producerConfig  Kafka producer configuration
     */
    constructor(strategies, producerConfig = DEFAULT_PRODUCER_CONFIG) {
        this._strategies = strategies;
        this._producerConfig = { ...DEFAULT_PRODUCER_CONFIG, ...producerConfig };

        // Producer is lazy-connected on first usage
        this._kafka = new Kafka({
            clientId: this._producerConfig.clientId,
            brokers: this._producerConfig.brokers,
            logLevel: logLevel.NOTHING,
        });
        this._producer = this._kafka.producer();
        this._connected = false;
    }

    /**
     * Attaches the pipeline to the DomainEventStream.
     * @param {DomainEventStream} eventStream
     * @returns {import('rxjs').Subscription}
     */
    attach(eventStream) {
        const PIPELINE_TIMEOUT_MS = 15_000;

        return eventStream.stream$
            .pipe(
                filter(({ payload }) => this._strategies.has(payload.eventType)),

                mergeMap(({ payload }) => {
                    const strategy = this._strategies.get(payload.eventType);
                    return from(strategy.extract(payload)).pipe(
                        map((features) => ({
                            key: payload.entityId ?? 'unknown',
                            eventType: payload.eventType,
                            timestamp: Date.now(),
                            features,
                        })),
                        rxTimeout(PIPELINE_TIMEOUT_MS),
                        retryWhen((errors) =>
                            errors.pipe(
                                tap((err) => log.warn({ err }, 'Retrying feature extraction')),
                                // Exponential backoff: wait 1s, 2s, 4s ...
                                mergeMap((err, i) => timer(Math.min(2 ** i * 1_000, 30_000)))
                            )
                        ),
                        catchError((err) => {
                            log.error({ err }, 'Giving up on feature extraction');
                            return []; // swallow & continue
                        })
                    );
                }),
                mergeMap((featureEvent) => this._emitFeatureEvent(featureEvent))
            )
            .subscribe({
                error: (err) => log.error({ err }, 'Pipeline error'),
                complete: () => log.info('FeatureEngineeringPipeline completed'),
            });
    }

    /* ---------------------------------------------------------------------- */
    /* Internal helpers                                                       */
    /* ---------------------------------------------------------------------- */

    async _emitFeatureEvent(featureEvent) {
        if (!this._connected) {
            await this._producer.connect();
            this._connected = true;
        }

        await this._producer
            .send({
                topic: this._producerConfig.topic,
                messages: [
                    {
                        key: featureEvent.key,
                        value: JSON.stringify(featureEvent),
                        timestamp: `${featureEvent.timestamp}`,
                    },
                ],
            })
            .catch((err) => log.error({ err }, 'Failed to send feature event'));
    }

    async shutdown() {
        if (this._connected) {
            await this._producer.disconnect().catch((err) => log.error(err, 'Producer disconnect'));
            this._connected = false;
        }
    }
}

/* -------------------------------------------------------------------------- */
/* Bootstrap helper                                                           */
/* -------------------------------------------------------------------------- */

/**
 * Kicks off the entire ingestion + pipeline with provided configs.
 *
 * @param {object} opts
 * @param {string} opts.strategyDir absolute path where strategies + manifest live
 * @param {object} [opts.consumerConfig] kafka consumer overrides
 * @param {object} [opts.producerConfig] kafka producer overrides
 * @param {object} [opts.schema] JSON schema used for envelope validation
 *
 * @returns {Promise<{shutdown: Function}>} handle to gracefully shutdown
 */
export async function bootstrap(opts) {
    const {
        strategyDir,
        consumerConfig = {},
        producerConfig = {},
        schema = DEFAULT_ENVELOPE_SCHEMA,
    } = opts;

    const strategies = await loadStrategies(strategyDir);
    log.info({ count: strategies.size }, 'Strategies loaded');

    const des = new DomainEventStream(consumerConfig, schema);
    const pipeline = new FeatureEngineeringPipeline(strategies, producerConfig);
    const subscription = pipeline.attach(des);

    await des.start();

    async function shutdown() {
        log.info('Shutting down...');
        subscription.unsubscribe();
        await pipeline.shutdown();
        await des.stop();
        log.info('Goodbye 👋');
    }

    return { shutdown };
}

/* -------------------------------------------------------------------------- */
/* Default JSON-schema for domain-event envelope                              */
/* -------------------------------------------------------------------------- */

export const DEFAULT_ENVELOPE_SCHEMA = {
    $id: 'https://agorapulse.ai/schemas/domainEventEnvelope.json',
    type: 'object',
    required: ['eventId', 'eventType', 'entityId', 'payload', 'createdAt'],
    additionalProperties: false,
    properties: {
        eventId: { type: 'string', format: 'uuid' },
        eventType: { type: 'string' },
        entityId: { type: 'string' },
        createdAt: { type: 'string', format: 'date-time' },
        payload: { type: 'object' },
    },
};

/* -------------------------------------------------------------------------- */
/* If executed directly: invoke bootstrap with defaults                       */
/* -------------------------------------------------------------------------- */

if (import.meta.url === `file://${process.argv[1]}`) {
    // eslint-disable-next-line unicorn/prefer-top-level-await
    bootstrap({
        strategyDir: joinPath(process.cwd(), 'strategies'),
    }).catch((err) => {
        log.fatal({ err }, 'Fatal error during bootstrap');
        process.exit(1);
    });
}
```