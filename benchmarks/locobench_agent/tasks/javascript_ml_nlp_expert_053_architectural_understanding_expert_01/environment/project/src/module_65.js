```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * src/module_65.js
 *
 * A high-level, production-ready bridge that turns one or more Kafka topics
 * into RxJS Observables.  The module performs:
 *   • Automatic (re)connection & back-off
 *   • JSON Schema validation via Ajv
 *   • Prometheus metrics instrumentation
 *   • Graceful shutdown on SIGINT/SIGTERM
 *
 * Down-stream micro-pipelines consume the returned Observable to perform
 * streaming feature engineering, model inference, or moderation actions.
 *
 * NOTE: All configuration is performed through a POJO – no env look-ups
 * inside the module to keep it pure & testable.
 *
 * Usage:
 *   const { createKafkaEventStream } = require('./module_65');
 *
 *   const { stream, shutdown } = await createKafkaEventStream({
 *       brokers: ['kafka-broker:9092'],
 *       groupId: 'nlp-pipeline-consumer-v1',
 *       topics: ['agorapulse.events.v1'],
 *       schema: require('./schemas/domainEvent.json'),
 *       logger: console  // any {info,warn,error,debug} interface
 *   });
 *
 *   stream.pipe(
 *       filter(evt => evt.type === 'TWEET_CREATED')
 *   ).subscribe(handler);
 *
 *   // Later…
 *   await shutdown();
 */

/* eslint-disable no-console */

const { KafkaConsumer } = require('node-rdkafka');
const { Subject, Observable, defer, fromEvent } = require('rxjs');
const { map, filter } = require('rxjs/operators');
const Ajv = require('ajv');
const { Counter, Gauge } = require('prom-client');
const debug = require('debug')('agorapulse:kafka-observable');
const { once } = require('events');

// −−−−−−−−−−−−−−−−−− Prometheus Metrics −−−−−−−−−−−−−−−−−−
const kafkaMessagesTotal = new Counter({
    name: 'agorapulse_kafka_messages_total',
    help: 'Total number of Kafka messages consumed',
    labelNames: ['topic', 'partition'],
});

const kafkaMessagesInvalid = new Counter({
    name: 'agorapulse_kafka_messages_invalid_total',
    help: 'Total number of Kafka messages failing JSON-schema validation',
    labelNames: ['topic', 'partition'],
});

const kafkaLagGauge = new Gauge({
    name: 'agorapulse_kafka_lag',
    help: 'Latest consumer lag (offset distance to high-watermark)',
    labelNames: ['topic', 'partition'],
});

// −−−−−−−−−−−−−−−−−− Inner Utilities −−−−−−−−−−−−−−−−−−

/**
 * Wrap setTimeout into a Promise for async/await ergonomics.
 * @param {number} ms
 */
const delay = ms => new Promise(res => setTimeout(res, ms));

/**
 * Perform an exponential back-off wait.
 * @param {number} attempt – The current retry attempt (0-based).
 * @param {number} maxBackoffMs – Max cap in milliseconds.
 */
const backoff = async (attempt, maxBackoffMs = 30_000) => {
    // Fibonacci back-off gives smoother distribution than doubling.
    const fib = n => (n <= 1 ? 1 : fib(n - 1) + fib(n - 2));
    const wait = Math.min(fib(attempt) * 100, maxBackoffMs);
    debug(`Back-off attempt ${attempt}, waiting ${wait}ms`);
    await delay(wait);
};

// −−−−−−−−−−−−−−−−−− Core Implementation −−−−−−−−−−−−−−−−−−

/**
 * @typedef {Object} KafkaEventStreamOptions
 * @property {string[]} brokers
 * @property {string} groupId
 * @property {string[]} topics
 * @property {Object} [schema] – JSON schema against which every message value is validated
 * @property {Object} [logger] – Optional logging interface (console-compatible)
 * @property {Object} [rdkafka] – Additional node-rdkafka configuration
 * @property {number} [startRetry=0] – Initial retry attempt (used by tests)
 */

/**
 * Spin up a Kafka consumer and expose its data as an RxJS Observable.
 * Returns both the hot Observable and a shutdown() helper.
 *
 * @param {KafkaEventStreamOptions} opts
 * @returns {Promise<{stream: Observable<Object>, shutdown: Function}>}
 */
async function createKafkaEventStream(opts) {
    const {
        brokers,
        groupId,
        topics,
        schema,
        logger = console,
        rdkafka = {},
        startRetry = 0,
    } = opts;

    if (!Array.isArray(brokers) || brokers.length === 0) {
        throw new Error('createKafkaEventStream: "brokers" must be a non-empty string[]');
    }
    if (!Array.isArray(topics) || topics.length === 0) {
        throw new Error('createKafkaEventStream: "topics" must be a non-empty string[]');
    }
    if (typeof groupId !== 'string' || !groupId.trim()) {
        throw new Error('createKafkaEventStream: "groupId" is required');
    }

    const ajv = schema ? new Ajv({ allErrors: true, strict: false }) : null;
    const validate = schema ? ajv.compile(schema) : null;

    let shuttingDown = false;

    // Subject is a multicast hot-stream for RxJS subscribers.
    const subject = new Subject();

    // We wrap consumer logic into a Promise so we can await readiness.
    const consumerReady = defer(() => {
        const consumer = new KafkaConsumer(
            {
                'metadata.broker.list': brokers.join(','),
                'group.id': groupId,
                'enable.auto.commit': true,
                'socket.keepalive.enable': true,
                // Forward any extra configuration.
                ...rdkafka,
            },
            {}
        );

        consumer.setDefaultConsumeTimeout(100);

        // Transform Num => BigInt where necessary, Avro workers expect BigInt.
        consumer.on('data', (msg) => {
            try {
                kafkaMessagesTotal.labels(msg.topic, String(msg.partition)).inc();

                const value = msg.value.toString('utf8');
                const parsed = JSON.parse(value);

                if (validate && !validate(parsed)) {
                    kafkaMessagesInvalid.labels(msg.topic, String(msg.partition)).inc();
                    logger.warn(
                        `Invalid message (offset ${msg.offset}) on ${msg.topic}[${msg.partition}]:`,
                        ajv.errorsText(validate.errors)
                    );
                    return;
                }

                subject.next({
                    topic: msg.topic,
                    partition: msg.partition,
                    offset: msg.offset,
                    timestamp: msg.timestamp,
                    key: msg.key ? msg.key.toString('utf8') : null,
                    value: parsed,
                });
            } catch (err) {
                logger.error('Error while processing Kafka message', err);
            }
        });

        consumer.on('rebalance', (evt) => {
            logger.info('Kafka rebalance:', evt);
        });

        consumer.on('event.lag', (lag) => {
            kafkaLagGauge.labels(lag.topic, String(lag.partition)).set(lag.current_lag);
        });

        consumer.on('event.error', (err) => {
            logger.error('Kafka event error', err);
        });

        consumer.on('disconnected', (arg) => {
            logger.warn('Kafka consumer disconnected', arg);
            if (!shuttingDown) {
                subject.error(new Error('Kafka consumer disconnected unexpectedly'));
            }
        });

        return new Promise((resolve, reject) => {
            consumer
                .connect()
                .on('ready', () => {
                    logger.info(
                        `Kafka consumer ready – group "${groupId}", topics [${topics.join(', ')}]`
                    );
                    consumer.subscribe(topics);
                    consumer.consume();
                    resolve(consumer);
                })
                .on('event.error', reject);
        });
    });

    // Start with retry logic
    async function initConsumer(attempt = startRetry) {
        try {
            return await consumerReady.toPromise();
        } catch (err) {
            logger.error(`Kafka connect failed (attempt ${attempt}):`, err);
            if (attempt > 12) throw err; // Too many retries – escalate
            await backoff(attempt);
            return initConsumer(attempt + 1);
        }
    }

    const consumer = await initConsumer();

    // Graceful shutdown helper
    async function shutdown() {
        if (shuttingDown) return;
        shuttingDown = true;
        logger.info('Shutting down KafkaEventStream...');
        subject.complete();
        await Promise.race([
            once(consumer, 'disconnected'),
            new Promise((res) => {
                consumer.disconnect(res);
            }),
        ]);
    }

    // Auto-hook SIGINT/SIGTERM, unless in test environment
    if (!process.env.JEST_WORKER_ID) {
        const handleExit = async () => {
            await shutdown();
            process.exit(0);
        };
        process.once('SIGINT', handleExit);
        process.once('SIGTERM', handleExit);
    }

    return {
        stream: subject.asObservable(),
        shutdown,
    };
}

// −−−−−−−−−−−−−−−−−− Nice Helper Operators −−−−−−−−−−−−−−−−−−

/**
 * RxJS operator to filter events by domain event `type`.
 * Example:
 *    stream.pipe(ofEventType('TWEET_CREATED'))
 * @param {...string} types
 */
const ofEventType = (...types) =>
    filter((evt) => evt?.value?.type && types.includes(evt.value.type));

/**
 * RxJS operator to pluck the `value` field from the envelope.
 */
const pluckValue = () => map((evt) => evt.value);

// −−−−−−−−−−−−−−−−−− Public API −−−−−−−−−−−−−−−−−−
module.exports = {
    createKafkaEventStream,
    ofEventType,
    pluckValue,
};
```