```javascript
/**
 * AgoraPulse — Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * EventStreamRouter (module_40.js)
 *
 * Bridges Kafka topics carrying raw social-network events into the internal
 * RxJS-powered event bus.  Applies pluggable transformation strategies that
 * enrich / normalize each raw payload into a strongly-typed domain event.
 *
 * Design goals:
 *   • Resilient: auto-reconnects Kafka consumer, exponential back-off retries
 *   • Observable: exports Prometheus metrics & structured logs (winston)
 *   • Extensible: Strategy pattern for per-event transformation
 *   • Reactive: emits to RxJS Subject for downstream micro-pipelines
 *
 * Usage:
 *   const router = new EventStreamRouter({
 *     kafka: { brokers: ['kafka-broker:9092'], clientId: 'agorapulse-router' },
 *     topics: ['social.raw'],
 *     strategies: {
 *       tweet_created: new TweetCreatedStrategy(),
 *       reaction_added: new ReactionAddedStrategy()
 *     }
 *   });
 *
 *   router.events$.subscribe(event => {
 *     // push to feature engineering pipeline, etc.
 *   });
 *
 *   await router.start();
 */

'use strict';

const { Kafka, logLevel: KafkaLogLevel } = require('kafkajs');
const { Subject, of, throwError } = require('rxjs');
const { retryWhen, mergeMap, delay } = require('rxjs/operators');
const winston = require('winston');
const promClient = require('prom-client');

/* -------------------------------------------------------------------------- */
/*                               Configuration                                */
/* -------------------------------------------------------------------------- */

/**
 * Default maximum number of retry attempts for transient failures.
 * Exposed for test injection / tuning from the outside.
 */
const DEFAULT_MAX_RETRIES = 5;

/**
 * Create a Winston logger pre-configured for JSON logs.
 * The caller can pass a custom logger via constructor, otherwise this one
 * will be used.  Log level defaults to `info`.
 */
function createDefaultLogger(scope = 'EventStreamRouter') {
  return winston.createLogger({
    level: process.env.LOG_LEVEL || 'info',
    defaultMeta: { scope },
    format: winston.format.combine(
      winston.format.timestamp(),
      winston.format.json()
    ),
    transports: [new winston.transports.Console()]
  });
}

/* -------------------------------------------------------------------------- */
/*                         Prometheus Metric Registry                         */
/* -------------------------------------------------------------------------- */

const METRIC_PREFIX = 'agorapulse_router_';

const kafkaMessageCounter = new promClient.Counter({
  name: `${METRIC_PREFIX}messages_total`,
  help: 'Total number of Kafka messages consumed',
  labelNames: ['topic', 'status'] // status = parsed | failed
});

const kafkaLagGauge = new promClient.Gauge({
  name: `${METRIC_PREFIX}partition_lag`,
  help: 'Current consumer group lag per topic/partition',
  labelNames: ['topic', 'partition']
});

/* -------------------------------------------------------------------------- */
/*                               Event Router                                 */
/* -------------------------------------------------------------------------- */

/**
 * @typedef {import('kafkajs').KafkaConfig} KafkaConfig
 * @typedef {import('kafkajs').ConsumerRunConfig} ConsumerRunConfig
 * @typedef {import('kafkajs').EachMessagePayload} EachMessagePayload
 */

/**
 * @typedef {Object} RouterOptions
 * @property {KafkaConfig} kafka                 - connection details
 * @property {string[]}    topics                - Kafka topics to subscribe to
 * @property {Object.<string, import('./strategies').EventStrategy>} strategies
 *           Map of event_type ➜ Strategy instance
 * @property {string}      groupId               - Consumer group id
 * @property {number}      [maxRetries]          - Retry attempts for parsing
 * @property {winston.Logger} [logger]           - Custom Winston logger
 * @property {ConsumerRunConfig} [consumerConfig]- Extra config for consumer.run
 */

class EventStreamRouter {
  /**
   * @param {RouterOptions} opts
   */
  constructor(opts) {
    if (!opts || typeof opts !== 'object') {
      throw new Error('EventStreamRouter constructor expects options object.');
    }

    /* eslint-disable prefer-destructuring */
    this.topics = opts.topics;
    this.groupId = opts.groupId || 'agorapulse-router-group';
    this.strategies = opts.strategies || {};
    this.maxRetries = opts.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.consumerConfig = opts.consumerConfig || {};

    this.logger = opts.logger || createDefaultLogger();
    this.kafka = new Kafka({
      ...opts.kafka,
      // Surface KafkaJS logs through Winston for consistency
      logCreator: () => level => {
        const lvl =
          level === KafkaLogLevel.ERROR
            ? 'error'
            : level === KafkaLogLevel.WARN
            ? 'warn'
            : 'debug';

        return ({ namespace, message, ...extra }) =>
          this.logger.log(lvl, message, { namespace, ...extra });
      }
    });

    this.events$ = new Subject();

    this.consumer = this.kafka.consumer({ groupId: this.groupId });
    this._isRunning = false;
  }

  /* ---------------------------------------------------------------------- */
  /*                          Public Router API                             */
  /* ---------------------------------------------------------------------- */

  /**
   * Connects to Kafka and begins consuming.
   */
  async start() {
    if (this._isRunning) return;
    this.logger.info('Starting EventStreamRouter...', {
      topics: this.topics,
      groupId: this.groupId
    });

    await this.consumer.connect();

    for (const topic of this.topics) {
      await this.consumer.subscribe({ topic, fromBeginning: false });
    }

    await this.consumer.run({
      ...this.consumerConfig,
      eachMessage: async payload => this._handleMessage(payload)
    });

    // Periodic fetching of consumer lag
    this._lagInterval = setInterval(
      () => this._updateLagMetrics().catch(err => this.logger.warn(err.message)),
      15_000
    );

    this._isRunning = true;
  }

  /**
   * Gracefully stop consuming and disconnect from Kafka.
   */
  async stop() {
    if (!this._isRunning) return;
    clearInterval(this._lagInterval);

    await this.consumer.disconnect();
    this.events$.complete();

    this.logger.info('EventStreamRouter stopped.');
    this._isRunning = false;
  }

  /**
   * Dynamically registers / replaces a transformation strategy.
   * @param {string} eventType
   * @param {import('./strategies').EventStrategy} strategy
   */
  registerStrategy(eventType, strategy) {
    this.strategies[eventType] = strategy;
    this.logger.debug(`Strategy registered for eventType='${eventType}'`);
  }

  /* ---------------------------------------------------------------------- */
  /*                          Internal Helpers                               */
  /* ---------------------------------------------------------------------- */

  /**
   * Handle raw Kafka message → Strategy transform → emit to Subject.
   * @param {EachMessagePayload} param0
   * @private
   */
  async _handleMessage({ topic, partition, message }) {
    // Track metrics
    kafkaMessageCounter.inc({ topic, status: 'received' });

    // Step 1 — Parse JSON payload
    const rawValue = message.value.toString();
    let parsed;
    try {
      parsed = JSON.parse(rawValue);
    } catch (err) {
      this.logger.error('Invalid JSON in message', { topic, partition, err });
      kafkaMessageCounter.inc({ topic, status: 'failed' });
      return;
    }

    const { event_type: eventType } = parsed;
    if (!eventType || !this.strategies[eventType]) {
      this.logger.warn('No strategy found for event', { eventType });
      kafkaMessageCounter.inc({ topic, status: 'unhandled' });
      return;
    }

    // Step 2 — Apply transformation with retry
    of(parsed)
      .pipe(
        mergeMap(payload =>
          this.strategies[eventType].transform(payload)
        ),
        retryWhen(errors =>
          errors.pipe(
            mergeMap((err, attempt) => {
              if (attempt >= this.maxRetries) return throwError(err);
              const backoff = 250 * 2 ** attempt;
              this.logger.debug('Retrying transform', { attempt, backoff });
              return of(err).pipe(delay(backoff));
            })
          )
        )
      )
      .subscribe({
        next: transformed => {
          kafkaMessageCounter.inc({ topic, status: 'parsed' });
          this.events$.next(transformed);
        },
        error: err => {
          this.logger.error('Transform failed', { err, eventType });
          kafkaMessageCounter.inc({ topic, status: 'failed' });
        }
      });
  }

  /**
   * Query Kafka to compute current lag per partition and update Gauge.
   * Requires Kafka supporting `describeGroup` / `fetchOffsets`.
   * @private
   */
  async _updateLagMetrics() {
    const admin = this.kafka.admin();
    await admin.connect();
    const groupDescription = await admin.describeGroups([this.groupId]);
    const [{ members }] = groupDescription.groups;

    for (const member of members) {
      for (const assignment of Object.values(member.memberAssignment.topicPartitions || {})) {
        const { topic, partitions } = assignment;
        const offsets = await admin.fetchOffsets({ groupId: this.groupId, topic });

        partitions.forEach(partition => {
          const partitionOffset = offsets.find(o => o.partition === partition);
          if (!partitionOffset) return;

          const { offset: committedOffset, high } = partitionOffset;
          const lag = Number(high) - Number(committedOffset);
          kafkaLagGauge.set({ topic, partition }, lag);
        });
      }
    }
    await admin.disconnect();
  }
}

/* -------------------------------------------------------------------------- */
/*                               Exports                                      */
/* -------------------------------------------------------------------------- */

module.exports = { EventStreamRouter };
```