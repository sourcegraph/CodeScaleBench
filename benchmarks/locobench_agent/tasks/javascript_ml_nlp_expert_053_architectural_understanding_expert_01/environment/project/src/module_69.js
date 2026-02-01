```javascript
/**
 * src/module_69.js
 *
 * A high–level Kafka → RxJS bridge that converts raw
 * domain-event messages arriving on a Kafka topic into an
 * RxJS Observable stream.  The class exposed by this module
 * is intended to be used by downstream micro-pipelines
 * (feature engineering, inference, monitoring, etc.) that
 * consume the real-time event bus inside AgoraPulse.
 *
 * Responsibilities
 *  • Manage a highly-available KafkaJS consumer
 *  • Perform basic JSON decoding & schema validation
 *  • Surface an RxJS Observable with built-in
 *    back-pressure and automatic retries
 *  • Expose checkpoint hooks for at-least-once semantics
 *
 * NOTE: This is JavaScript (ES2022).  Consumers written
 * in TypeScript can still import it thanks to proper
 * JSDoc typings.
 */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, finalize, Observable, asyncScheduler } from 'rxjs';
import { observeOn, bufferTime } from 'rxjs/operators';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';

/**
 * Default, overridable configuration values.
 */
const DEFAULT_CONFIG = Object.freeze({
  brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
  clientId: process.env.KAFKA_CLIENT_ID ?? 'agorapulse-bridge',
  groupId: process.env.KAFKA_GROUP_ID ?? 'agorapulse-pipelines',
  topic: process.env.KAFKA_TOPIC ?? 'agorapulse.domain.events',
  schema: {
    $id: 'https://agorapulse.ai/schemas/domainEvent.json',
    type: 'object',
    required: ['eventId', 'timestamp', 'type', 'payload'],
    properties: {
      eventId: { type: 'string', minLength: 1 },
      timestamp: { type: 'integer', minimum: 0 },
      type: { type: 'string', minLength: 1 },
      payload: { type: 'object' }
    },
    additionalProperties: true
  },
  batchSize: 100, // max messages in memory per poll
  pollInterval: 500, // ms
  backoff: {
    maxRetries: 5,
    baseDelay: 500 // ms
  },
  rxBufferMs: 200 // time-slice for bufferTime()
});

/**
 * Custom error class to signal unrecoverable consumer issues.
 */
export class ConsumerFatalError extends Error {
  constructor(message, original) {
    super(message);
    this.name = 'ConsumerFatalError';
    this.original = original;
  }
}

/**
 * KafkaRxBridge
 *
 * Example usage:
 *   const bridge = new KafkaRxBridge({ topic: 'social.events' });
 *   const observable = bridge.connect();
 *
 *   observable.subscribe({
 *     next: evt => { /* do stuff *\/ },
 *     error: err => { /* centralised logging *\/ }
 *   });
 */
export class KafkaRxBridge {
  /**
   * @typedef {ReturnType<Ajv['compile']>} ValidateFn
   *
   * @param {Partial<typeof DEFAULT_CONFIG>} [options]
   */
  constructor(options = {}) {
    this.config = { ...DEFAULT_CONFIG, ...options };
    this._ajv = new Ajv({ allErrors: true, strict: false });
    addFormats(this._ajv);
    /** @type {ValidateFn} */
    this._validate = this._ajv.compile(this.config.schema);

    this._subject = new Subject();
    this._kafka = new Kafka({
      clientId: this.config.clientId,
      brokers: this.config.brokers,
      logLevel: logLevel.ERROR
    });

    this._consumer = this._kafka.consumer({ groupId: this.config.groupId });
    this._connected = false;
    this._currentRetry = 0;
  }

  /**
   * Connects to Kafka and returns an Observable stream that
   * consumers can subscribe to.  Behind the scenes the
   * Observable is backed by an RxJS Subject.
   *
   * @returns {Observable<Object>} cold Observable that becomes
   *          hot once the underlying Subject emits
   */
  connect() {
    if (!this._connecting) {
      this._connecting = this._startConsumerLoop();
    }

    // Expose an Observable with some buffering and scheduler control
    return this._subject.pipe(
      bufferTime(this.config.rxBufferMs),
      observeOn(asyncScheduler),
      finalize(() => this.close())
    );
  }

  /**
   * Gracefully closes the Kafka consumer and RxJS subject.
   */
  async close() {
    try {
      if (this._connected) {
        await this._consumer.disconnect();
        this._connected = false;
      }
      this._subject.complete();
    } catch (err) {
      // Idempotent; swallow secondary errors after completion
      console.error('[KafkaRxBridge] Error during close()', err);
    }
  }

  /**
   * Internal helper to spin up the Kafka consumer with
   * exponential backoff retries.
   * @private
   */
  async _startConsumerLoop() {
    const { maxRetries, baseDelay } = this.config.backoff;

    while (this._currentRetry <= maxRetries) {
      try {
        await this._consumer.connect();
        await this._consumer.subscribe({ topic: this.config.topic, fromBeginning: false });
        this._connected = true;
        this._currentRetry = 0; // reset for next time
        await this._run();
        break; // normal exit
      } catch (error) {
        this._connected = false;
        const fatal = error.type === 'UNKNOWN_TOPIC_OR_PARTITION' ||
                      error.code === 'ECONNREFUSED';
        if (fatal) {
          this._subject.error(new ConsumerFatalError('Unrecoverable Kafka error', error));
          throw error;
        }

        this._currentRetry += 1;
        if (this._currentRetry > maxRetries) {
          this._subject.error(new ConsumerFatalError('Exceeded max retry attempts', error));
          throw error;
        }
        const delay = baseDelay * 2 ** (this._currentRetry - 1);
        console.warn(`[KafkaRxBridge] Retry ${this._currentRetry}/${maxRetries} in ${delay} ms`);
        await this._sleep(delay);
      }
    }
  }

  /**
   * Core polling loop. Uses KafkaJS `eachBatch` for manual
   * back-pressure control and explicit offset commits.
   * @private
   */
  async _run() {
    await this._consumer.run({
      autoCommit: false,
      eachBatchAutoResolve: false,
      eachBatch: async ({
        batch,
        resolveOffset,
        heartbeat,
        commitOffsetsIfNecessary
      }) => {
        for (const message of batch.messages) {
          try {
            const parsed = this._decode(message);
            this._subject.next(parsed);
          } catch (err) {
            // Push validation errors downstream but continue processing
            this._subject.error(err);
            console.error('[KafkaRxBridge] Bad message skipped', err);
          } finally {
            resolveOffset(message.offset);
          }
        }

        await commitOffsetsIfNecessary();
        await heartbeat();
      }
    });
  }

  /**
   * Attempt to decode & validate a Kafka message.
   * @param {import('kafkajs').Message} message
   * @returns {Object} domain event
   * @throws {Error} if JSON parse or schema validation fails
   * @private
   */
  _decode(message) {
    let value;
    try {
      value = JSON.parse(message.value.toString());
    } catch (err) {
      throw new Error(`JSON parse error: ${err.message}`);
    }

    if (!this._validate(value)) {
      const errors = this._validate.errors?.map(e => `${e.instancePath} ${e.message}`).join('; ');
      throw new Error(`Schema validation failed: ${errors}`);
    }

    return {
      ...value,
      kafkaMeta: {
        partition: message.partition,
        offset: message.offset
      }
    };
  }

  _sleep(ms) {
    return new Promise(res => setTimeout(res, ms));
  }
}

export default KafkaRxBridge;
```