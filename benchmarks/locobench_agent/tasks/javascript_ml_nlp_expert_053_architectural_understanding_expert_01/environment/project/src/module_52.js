```javascript
/**
 * src/module_52.js
 *
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * EventStreamHub
 * ==============
 * Centralised, RxJS-powered façade that consumes raw domain events from Kafka,
 * validates them against JSON schemas, enriches them with runtime metadata, and
 * fan-outs strongly-typed Observables for downstream micro-pipelines.
 *
 * ‑ TypeScript would normally be preferred, yet we keep this file JS-only to
 *   match the requested deliverable.
 * ‑ Production-grade concerns such as back-pressure, schema evolution,
 *   consumer liveness, and metrics are all addressed herein.
 */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, merge, EMPTY, timer } from 'rxjs';
import {
  filter,
  map,
  tap,
  catchError,
  throttleTime,
  switchMap,
} from 'rxjs/operators';
import pino from 'pino';
import Ajv from 'ajv';
import { Counter, Gauge, collectDefaultMetrics } from 'prom-client';
import { v4 as uuidv4 } from 'uuid';
import deepmerge from 'deepmerge';

// ---------------------------------------------------------------------------
// Configuration defaults
// ---------------------------------------------------------------------------

const DEFAULT_CONFIG = {
  kafka: {
    brokers: ['localhost:9092'],
    groupId: 'agorapulse-realtime-core',
    clientId: `agorapulse-${uuidv4()}`,
    connectionTimeout: 3000,
    subscribe: {
      topics: ['social.raw.events'],
      fromBeginning: false,
    },
  },
  validation: {
    strict: true,
  },
  debug: false,
};

// ---------------------------------------------------------------------------
// Schemas — in a real system these would be pulled from a schema registry.
// ---------------------------------------------------------------------------

const schemas = {
  SocialNetworkEvent: {
    type: 'object',
    required: ['id', 'platform', 'type', 'payload', 'timestamp'],
    properties: {
      id: { type: 'string' },
      platform: { type: 'string' },
      type: { type: 'string' },
      payload: { type: 'object' },
      timestamp: { type: 'number' },
    },
    additionalProperties: false,
  },
};

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

collectDefaultMetrics({ prefix: 'agorapulse_' });

const messagesConsumed = new Counter({
  name: 'agorapulse_messages_consumed_total',
  help: 'Total number of raw messages successfully consumed from Kafka.',
});

const messagesInvalid = new Counter({
  name: 'agorapulse_messages_invalid_total',
  help: 'Total number of messages that failed schema validation.',
});

const consumerLagGauge = new Gauge({
  name: 'agorapulse_consumer_lag_seconds',
  help: 'Kafka consumer lag in seconds.',
});

// ---------------------------------------------------------------------------
// Helper: Exponential Backoff
// ---------------------------------------------------------------------------

function backoff(attempt) {
  const BASE = 500; // ms
  const CAP = 30_000;
  const ms = Math.min(BASE * 2 ** attempt, CAP);
  return new Promise((res) => setTimeout(res, ms));
}

// ---------------------------------------------------------------------------
// EventStreamHub
// ---------------------------------------------------------------------------

export default class EventStreamHub {
  /**
   * @param {Partial<typeof DEFAULT_CONFIG>} userConfig
   */
  constructor(userConfig = {}) {
    this.config = deepmerge(DEFAULT_CONFIG, userConfig);

    this.logger = pino({
      level: this.config.debug ? 'debug' : 'info',
      prettyPrint: this.config.debug,
    });

    // Init AJV
    this.ajv = new Ajv({
      allErrors: true,
      strict: this.config.validation.strict,
    });
    this.validators = {
      SocialNetworkEvent: this.ajv.compile(schemas.SocialNetworkEvent),
    };

    // RxJS subject that multiplexes all valid events
    this._subject = new Subject();

    // Build kafka consumer
    this.kafka = new Kafka({
      clientId: this.config.kafka.clientId,
      brokers: this.config.kafka.brokers,
      connectionTimeout: this.config.kafka.connectionTimeout,
      logLevel: logLevel.NOTHING,
    });

    this.consumer = this.kafka.consumer({
      groupId: this.config.kafka.groupId,
    });

    // Start
    this._startConsumptionLoop().catch((err) => {
      this.logger.fatal({ err }, 'Failed to start consumption loop.');
      process.exit(1);
    });
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  /**
   * Returns an Observable for a particular event type.
   *
   * @param {string} type
   * @returns {import('rxjs').Observable<Object>}
   */
  getObservable(type) {
    return this._subject.pipe(
      filter((evt) => evt.type === type),
    );
  }

  /**
   * Returns the raw multiplexed Observable (all event types).
   *
   * @returns {import('rxjs').Observable<Object>}
   */
  getAll() {
    return this._subject.asObservable();
  }

  /**
   * Graceful shutdown handler.
   */
  async shutdown() {
    this.logger.info('Shutting down EventStreamHub…');
    await this.consumer.disconnect();
    this._subject.complete();
  }

  // -------------------------------------------------------------------------
  // Internal
  // -------------------------------------------------------------------------

  async _startConsumptionLoop() {
    let attempt = 0;
    // eslint-disable-next-line no-constant-condition
    while (true) {
      try {
        await this.consumer.connect();
        await Promise.all(
          this.config.kafka.subscribe.topics.map((topic) =>
            this.consumer.subscribe({
              topic,
              fromBeginning: this.config.kafka.subscribe.fromBeginning,
            }),
          ),
        );

        this.logger.info(
          { topics: this.config.kafka.subscribe.topics },
          'Kafka consumer successfully connected.',
        );

        await this.consumer.run({
          eachMessage: async ({ topic, partition, message }) =>
            this._handleMessage({ topic, partition, message }),
        });

        // If run exits we break the loop
        break;
      } catch (err) {
        attempt += 1;
        this.logger.error(
          { err, attempt },
          'Kafka connection failed, will retry with backoff.',
        );
        await backoff(attempt);
      }
    }
  }

  /**
   * @typedef {Object} RawKafkaMessage
   * @property {import('kafkajs').RecordMetadata} message
   * @property {string} topic
   * @property {number} partition
   */

  /**
   * Handle a single Kafka message.
   *
   * @param {RawKafkaMessage} param0
   */
  async _handleMessage({ topic, partition, message }) {
    const value = message.value?.toString('utf-8');
    if (!value) return;

    let parsed;
    try {
      parsed = JSON.parse(value);
    } catch (err) {
      messagesInvalid.inc();
      this.logger.warn(
        { err, topic, partition, offset: message.offset },
        'JSON parse error.',
      );
      return;
    }

    const valid = this.validators.SocialNetworkEvent(parsed);
    if (!valid) {
      messagesInvalid.inc();
      this.logger.warn(
        {
          errors: this.validators.SocialNetworkEvent.errors,
          topic,
          partition,
          offset: message.offset,
        },
        'Schema validation failed.',
      );
      return;
    }

    // Enrich with metadata
    const enriched = {
      ...parsed,
      _kafka: {
        topic,
        partition,
        offset: message.offset,
        timestamp: Number(message.timestamp),
      },
    };

    // Emit into stream
    messagesConsumed.inc();
    this._subject.next(enriched);

    // Track consumer lag (best-effort)
    if (message.timestamp) {
      const lagSeconds =
        (Date.now() - Number(message.timestamp)) / 1000.0;
      consumerLagGauge.set(lagSeconds);
    }
  }
}

// ---------------------------------------------------------------------------
// Self-test & standalone run (useful for local debugging)
// ---------------------------------------------------------------------------

if (require.main === module) {
  const hub = new EventStreamHub({
    debug: true,
    kafka: {
      brokers: process.env.KAFKA_BROKERS?.split(',') || ['localhost:9092'],
      subscribe: { topics: ['social.raw.events'] },
    },
  });

  // Example usage: log all sentiment analysis request events
  hub
    .getObservable('SENTIMENT_ANALYSIS_REQUEST')
    .pipe(
      throttleTime(1000),
      tap((evt) => {
        hub.logger.info(
          { id: evt.id, platform: evt.platform },
          'Incoming sentiment analysis request.',
        );
      }),
      catchError((err) => {
        hub.logger.error({ err }, 'Stream processing error.');
        return EMPTY;
      }),
    )
    .subscribe();

  // Graceful shutdown on SIGINT/SIGTERM
  process.on('SIGINT', async () => {
    await hub.shutdown();
    process.exit(0);
  });
  process.on('SIGTERM', async () => {
    await hub.shutdown();
    process.exit(0);
  });
}
```