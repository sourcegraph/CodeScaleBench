```javascript
/**
 * src/module_1.js
 *
 * Central event-bus abstraction that bridges Kafka topics with RxJS streams
 * and allows registration of fault-tolerant, hot-swappable micro-pipelines.
 *
 * This module is a cornerstone of the AgoraPulse real-time architecture:
 * every domain event emitted by upstream collectors is validated, decoded,
 * and fanned-out through an RxJS Subject to any number of downstream feature
 * engineering, model-serving, or monitoring pipelines.
 *
 * Dependencies:
 *   - kafkajs      : battle-tested Kafka client for Node.js
 *   - rxjs         : reactive streams
 *   - pino         : ridiculously fast JSON logger
 *   - ajv          : JSON-schema validator
 *
 * NOTE:  Module is written in vanilla JavaScript instead of TypeScript to
 *        minimise boilerplate in this code-generation exercise.  In the real
 *        repository everything is authored in TypeScript and transpiled.
 */

'use strict';

const { Kafka, logLevel } = require('kafkajs');
const {
  Subject,
  defer,
  timer,
} = require('rxjs');
const {
  filter,
  map,
  retryWhen,
  switchMap,
  takeUntil,
  tap,
  timeoutWith,
} = require('rxjs/operators');
const pino = require('pino');
const Ajv = require('ajv');

/* ------------------------------------------------------------------------- *
 * Constants                                                                 *
 * ------------------------------------------------------------------------- */

/** Default JSON schema for a minimal domain event.  Can be overridden. */
const DEFAULT_EVENT_SCHEMA = {
  type:       'object',
  required:   ['id', 'type', 'timestamp', 'payload'],
  properties: {
    id:        { type: 'string' },
    type:      { type: 'string' },
    timestamp: { type: 'string', format: 'date-time' },
    payload:   { type: 'object' },
  },
};

/** Hard cap on how many times a pipeline may automatically restart. */
const DEFAULT_PIPELINE_MAX_RETRIES = 5;

/** Amount of time (ms) after which an event must be processed. */
const DEFAULT_PROCESSING_TIMEOUT = 10_000; // 10 seconds

/* ------------------------------------------------------------------------- *
 * Utilities                                                                 *
 * ------------------------------------------------------------------------- */

/**
 * Exponential back-off generator.
 *
 * @param {number} maxRetries
 * @param {number} baseMs
 * @returns {(attempt: number) => number}
 */
function backoffMs(maxRetries, baseMs = 250) {
  return attempt => Math.min(baseMs * Math.pow(2, attempt), 30_000);
}

/**
 * Make sure an object looks like an AgoraPulse domain event or throw.
 *
 * @param {object} event
 * @param {Ajv.ValidateFunction} validateFn
 */
function assertValidEvent(event, validateFn) {
  if (!validateFn(event)) {
    const error = validateFn.errors?.[0];
    throw new Error(
      `Invalid event: ${error?.instancePath ?? ''} ${error?.message ?? ''}`
    );
  }
}

/* ------------------------------------------------------------------------- *
 * EventHub                                                                  *
 * ------------------------------------------------------------------------- */

/**
 * Options for {@link EventHub}.
 *
 * @typedef {object} EventHubOptions
 * @property {string[]} brokers              Kafka bootstrap list
 * @property {string}   groupId              Kafka consumer group
 * @property {string[]} topics               Topics to subscribe to
 * @property {object}   [schema]             JSON schema for domain events
 * @property {pino.Logger} [logger]          Logger instance
 */

/**
 * Bridges Kafka topics with RxJS, exposes event$ hot observable and allows
 * run-time registration of micro-pipelines.
 */
class EventHub {
  /**
   * @param {EventHubOptions} opts
   */
  constructor(opts) {
    if (!opts?.brokers?.length) {
      throw new Error('EventHub: `brokers` option is required.');
    }
    if (!opts?.topics?.length) {
      throw new Error('EventHub: `topics` option is required.');
    }
    this._opts        = opts;
    this._logger      = opts.logger || pino({ level: 'info' });
    this._kafka       = new Kafka({
      brokers:  opts.brokers,
      logLevel: logLevel.NOTHING, // KafkaJS logging is proxied through pino
    });
    this._consumer    = this._kafka.consumer({ groupId: opts.groupId });
    this._event$      = new Subject();
    this._ajv         = new Ajv({ coerceTypes: true, strict: false });
    this._validate    = this._ajv.compile(opts.schema ?? DEFAULT_EVENT_SCHEMA);
    this._pipelines   = new Map();        // id -> subscription
    this._stopped$    = new Subject();    // notify teardown
  }

  /** @returns {import('rxjs').Observable<object>} Hot event stream */
  get event$() { return this._event$.asObservable(); }

  /**
   * Start Kafka consumer & RxJS bridge.
   *
   * @returns {Promise<void>}
   */
  async start() {
    const log = this._logger.child({ module: 'EventHub' });
    await this._consumer.connect();
    await Promise.all(
      this._opts.topics.map(topic => this._consumer.subscribe({ topic }))
    );
    log.info({ topics: this._opts.topics }, 'Kafka consumer connected.');

    // Consume loop
    await this._consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          // KafkaJS delivers Buffer objects, convert to string → JSON.
          const raw  = message.value?.toString('utf8');
          const evt  = JSON.parse(raw);
          assertValidEvent(evt, this._validate);
          this._event$.next(evt); // fan-out
        } catch (err) {
          log.warn(
            { err, topic, partition, offset: message?.offset },
            'Failed to process Kafka message.'
          );
        }
      },
    });

    log.info('EventHub streaming.');
  }

  /**
   * Stop everything and clean resources.
   *
   * @returns {Promise<void>}
   */
  async stop() {
    this._logger.info('EventHub shutting down...');
    this._stopped$.next(true);
    this._stopped$.complete();
    await Promise.all(
      [...this._pipelines.values()].map(sub => sub?.unsubscribe())
    );
    this._pipelines.clear();
    await this._consumer.disconnect();
    this._event$.complete();
  }

  /**
   * Register a micro-pipeline.
   *
   * @param {string} id                                   Unique identifier
   * @param {(event$: import('rxjs').Observable<object>) => import('rxjs').Subscription} factory
   *        Function that receives the shared event$ stream and returns a
   *        subscription (side-effects, model invocations, DB writes, ...).
   * @param {object} [opts]
   * @param {number} [opts.maxRetries=5]      Auto-restart attempts
   *
   * @returns {void}
   */
  registerPipeline(id, factory, opts = {}) {
    if (this._pipelines.has(id)) {
      throw new Error(`Pipeline "${id}" already registered.`);
    }
    const { maxRetries = DEFAULT_PIPELINE_MAX_RETRIES } = opts;
    const log = this._logger.child({ pipeline: id });

    // Wrap pipeline with automatic restart logic.
    const subscription = this.event$
      .pipe(
        timeoutWith(
          DEFAULT_PROCESSING_TIMEOUT,
          defer(() => {
            throw new Error(`Pipeline "${id}" processing timeout exceeded.`);
          })
        ),
        retryWhen(errors =>
          errors.pipe(
            tap(err => {
              log.error({ err }, 'Pipeline failure.');
            }),
            switchMap((err, attempt) => {
              if (attempt >= maxRetries) {
                log.fatal(
                  { attempt, maxRetries },
                  'Pipeline reached retry ceiling—bailing out!'
                );
                return throw err; // Escalate fatal
              }
              const delayMs = backoffMs(maxRetries)(attempt);
              log.warn(
                { attempt, delayMs },
                'Restarting pipeline after back-off.'
              );
              return timer(delayMs);
            })
          )
        ),
        takeUntil(this._stopped$)
      )
      .subscribe({
        next: () => {/* noop – side-effects happen in factory */},
        error: err => log.fatal({ err }, 'Unrecoverable pipeline error.'),
      });

    // Execute user factory (side-effects) while keeping reference
    const userSubscription = factory(this.event$);
    this._pipelines.set(id, {
      core: subscription,
      user: userSubscription,
    });

    log.info('Pipeline registered.');
  }
}

/* ------------------------------------------------------------------------- *
 * Built-in example pipeline                                                 *
 * ------------------------------------------------------------------------- */

/**
 * Example: route `reaction` events to a simple counter.
 *
 * Showcases how downstream services might consume the event stream; here we
 * merely keep an in-memory map, but the same pattern could push to Redis,
 * InfluxDB, or Prometheus for live dashboards.
 *
 * @param {import('rxjs').Observable<object>} event$
 * @param {pino.Logger} [logger]
 * @returns {import('rxjs').Subscription}
 */
function reactionCounterPipeline(event$, logger = pino()) {
  const counts = new Map(); // emoji -> occurrences

  return event$
    .pipe(
      filter(evt => evt.type === 'REACTION'),
      map(evt => evt.payload?.emoji ?? '❓')
    )
    .subscribe({
      next: emoji => {
        const newCount = (counts.get(emoji) ?? 0) + 1;
        counts.set(emoji, newCount);
        logger.debug({ emoji, newCount }, 'Reaction counter updated.');
      },
      error: err => logger.error({ err }, 'Reaction counter pipeline failed.'),
      complete: () => logger.info('Reaction counter pipeline completed.'),
    });
}

/* ------------------------------------------------------------------------- *
 * Exports                                                                   *
 * ------------------------------------------------------------------------- */

module.exports = {
  EventHub,
  reactionCounterPipeline,
};
```