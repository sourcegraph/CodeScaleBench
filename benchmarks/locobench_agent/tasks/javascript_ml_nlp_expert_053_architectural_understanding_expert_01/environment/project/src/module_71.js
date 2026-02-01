```javascript
/**
 * AgoraPulse :: Real-Time Sentiment Aggregator & Monitor
 *
 * This module consumes `sentiment.scored` events coming from the streaming
 * feature-engineering pipeline, aggregates them over a sliding time window,
 * stores roll-up metrics in Redis for quick dashboard retrieval, and publishes
 * anomaly alerts to `sentiment.alerts` when negativity spikes.
 *
 * Patterns used:
 *  - Strategy Pattern …… interchangeable aggregation strategies
 *  - Factory Pattern ……… strategy resolver
 *  - Observer Pattern …… RxJS streams as event emitters
 *
 * Dependencies (npm):
 *  kafkajs, rxjs, ioredis, ajv, uuid, dotenv
 *
 * Author: AgoraPulse Engineering
 * ---------------------------------------------------------------------------*/
import 'dotenv/config';
import { Kafka, logLevel as KafkaLogLevel } from 'kafkajs';
import { Observable, fromEventPattern, timer } from 'rxjs';
import {
  bufferTime,
  filter,
  map,
  mergeMap,
  reduce,
  share,
  tap,
} from 'rxjs/operators';
import Redis from 'ioredis';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import { v4 as uuid } from 'uuid';

/* ========================================================================== */
/* =============================— Constants —================================ */

const {
  KAFKA_BROKERS = '',
  KAFKA_CLIENT_ID = 'agorapulse-sentiment-monitor',
  REDIS_URL = 'redis://localhost:6379',
  AGG_WINDOW_MS = '5000',
  NEG_ALERT_THRESHOLD = '0.4',
  VERBOSE_LOGGING = 'false',
} = process.env;

/* ========================================================================== */
/* ========================— Schema Definitions —============================ */

const sentimentEventSchema = {
  $id: 'https://agorapulse.ai/schema/sentiment-event.json',
  type: 'object',
  required: ['tenantId', 'messageId', 'sentiment', 'timestamp'],
  properties: {
    tenantId: { type: 'string', minLength: 1 },
    messageId: { type: 'string', minLength: 1 },
    sentiment: { type: 'number', minimum: -1, maximum: 1 },
    timestamp: { type: 'number' },
    // Optional fields enrichers may add later
    language: { type: 'string' },
    features: { type: 'object' },
  },
};

/* ========================================================================== */
/* ===================— Strategy Pattern for Aggregation —=================== */

/**
 * @typedef {Object} AggregationResult
 * @property {number} count
 * @property {number} mean
 * @property {number} positiveRatio
 * @property {number} negativeRatio
 * @property {number} neutralRatio
 */

/**
 * Base interface for aggregation strategies.
 * @interface
 */
class AggregationStrategy {
  /**
   * Aggregate window of sentiment scores
   * @param {Array<Object>} window
   * @returns {AggregationResult}
   */
  aggregate(window) {
    throw new Error('aggregate() must be implemented by subclass');
  }
}

/**
 * Default implementation: mean sentiment & ratio calculations
 */
class MeanSentimentStrategy extends AggregationStrategy {
  aggregate(window) {
    const count = window.length;
    if (count === 0) {
      return {
        count: 0,
        mean: 0,
        positiveRatio: 0,
        negativeRatio: 0,
        neutralRatio: 0,
      };
    }

    let sum = 0,
      pos = 0,
      neg = 0,
      neutral = 0;
    for (const e of window) {
      sum += e.sentiment;
      if (e.sentiment > 0.05) pos += 1;
      else if (e.sentiment < -0.05) neg += 1;
      else neutral += 1;
    }
    const mean = sum / count;

    return {
      count,
      mean,
      positiveRatio: pos / count,
      negativeRatio: neg / count,
      neutralRatio: neutral / count,
    };
  }
}

/**
 * Simple factory to resolve desired strategy.
 * Could be extended to register additional strategies via IoC.
 * @param {string} name
 * @returns {AggregationStrategy}
 */
function aggregationStrategyFactory(name = 'mean') {
  switch (name.toLowerCase()) {
    case 'mean':
      return new MeanSentimentStrategy();
    default:
      throw new Error(`Unknown AggregationStrategy: ${name}`);
  }
}

/* ========================================================================== */
/* =====================— SentimentMonitor class —=========================== */

export class SentimentMonitor {
  /**
   * @param {Object} [options]
   * @param {string[]} [options.brokers]
   * @param {string}   [options.clientId]
   * @param {Redis}    [options.redis]
   * @param {AggregationStrategy} [options.strategy]
   * @param {number}   [options.windowMs]
   * @param {number}   [options.negAlertThreshold]
   */
  constructor(options = {}) {
    /* -------- Kafka -------- */
    this.kafka = new Kafka({
      clientId: options.clientId ?? KAFKA_CLIENT_ID,
      brokers: options.brokers ?? KAFKA_BROKERS.split(',').filter(Boolean),
      logLevel: VERBOSE_LOGGING === 'true' ? KafkaLogLevel.INFO : KafkaLogLevel.ERROR,
    });

    this.consumer = this.kafka.consumer({
      groupId: `sentiment-monitor-${uuid()}`,
      // autoCommit disabled for at-least-once semantics with explicit commits
      allowAutoTopicCreation: false,
    });
    this.producer = this.kafka.producer();

    /* -------- Redis -------- */
    this.redis =
      options.redis ??
      new Redis(REDIS_URL, {
        enableOfflineQueue: true,
        lazyConnect: true,
        keyPrefix: 'agorapulse:',
      });

    /* -------- Aggregation -----*/
    this.strategy = options.strategy ?? aggregationStrategyFactory('mean');
    this.windowMs = Number(options.windowMs ?? AGG_WINDOW_MS);
    this.negAlertThreshold = Number(options.negAlertThreshold ?? NEG_ALERT_THRESHOLD);
    if (Number.isNaN(this.windowMs) || this.windowMs <= 0) {
      throw new Error('Invalid aggregation window');
    }

    /* -------- Validation -----*/
    const ajv = new Ajv({ allErrors: true, strict: false });
    addFormats(ajv);
    this.validateEvent = ajv.compile(sentimentEventSchema);

    /* -------- Internal state -----*/
    this._subscription = null;
    this._running = false;
  }

  /* ---------------------------------------------------------------------- */
  /* ========================— Public API —================================ */

  async start() {
    if (this._running) return;
    this._running = true;

    // Connect external resources
    await Promise.all([this.consumer.connect(), this.producer.connect(), this.redis.connect()]).catch(
      (err) => {
        console.error('Failed to connect infrastructure', err);
        throw err;
      }
    );

    await this.consumer.subscribe({
      topic: 'sentiment.scored',
      fromBeginning: false,
    });

    // Create Observable from Kafka events
    const kafka$ = this._createKafkaObservable().pipe(share());

    // Build processing pipeline
    const aggregation$ = kafka$.pipe(
      // bufferTime emits an array every windowMs millis
      bufferTime(this.windowMs),
      mergeMap((window) => {
        const result = this.strategy.aggregate(window);
        return [result];
      }),
      tap((res) => this._persistToRedis(res)),
      tap((res) => this._publishAlertIfNeeded(res))
    );

    // Subscribe & retain handle for stop()
    this._subscription = aggregation$.subscribe({
      error: (err) => {
        console.error('Aggregation stream error!', err);
        // optional: escalate / restart
      },
    });

    console.info(
      `SentimentMonitor started. window=${this.windowMs}ms threshold=${this.negAlertThreshold}`
    );
  }

  async stop() {
    if (!this._running) return;
    this._running = false;

    // Gracefully complete Rx subscription
    this._subscription?.unsubscribe();

    // Flush and disconnect external clients
    await Promise.allSettled([this.consumer.disconnect(), this.producer.disconnect()]);
    await this.redis.quit();
    console.info('SentimentMonitor stopped.');
  }

  /* ---------------------------------------------------------------------- */
  /* ========================— Internals —================================= */

  /**
   * Creates an RxJS Observable from kafka-js consumer.
   * Each message is parsed & validated, then acknowledged.
   * @private
   */
  _createKafkaObservable() {
    return new Observable((subscriber) => {
      const run = async () => {
        try {
          await this.consumer.run({
            eachMessage: async ({ topic, partition, message }) => {
              try {
                const event = JSON.parse(message.value.toString());
                if (!this.validateEvent(event)) {
                  console.warn(
                    'Invalid sentiment event received, discarding',
                    this.validateEvent.errors
                  );
                  // Commit offset even for bad msg to avoid poison pill
                  await this.consumer.commitOffsets([
                    { topic, partition, offset: (Number(message.offset) + 1).toString() },
                  ]);
                  return;
                }

                subscriber.next(event);

                // Commit offset when processed
                await this.consumer.commitOffsets([
                  { topic, partition, offset: (Number(message.offset) + 1).toString() },
                ]);
              } catch (err) {
                console.error('Failed to process sentiment message', err);
                // Don't commit offset here; let Kafka retry later
              }
            },
          });
        } catch (err) {
          subscriber.error(err);
        }
      };

      run();

      // teardown
      return () => {
        /* no-op; handled in stop() */
      };
    });
  }

  /**
   * Persists aggregated metrics in Redis for quick query by dashboards.
   * TTL is slightly larger than aggregation window.
   * @param {AggregationResult} res
   * @private
   */
  async _persistToRedis(res) {
    const ttlSec = Math.ceil((this.windowMs * 2) / 1000);
    try {
      await this.redis.set(
        'sentiment:rolling',
        JSON.stringify({ ts: Date.now(), ...res }),
        'EX',
        ttlSec
      );
    } catch (err) {
      console.error('Failed to persist sentiment aggregates to Redis', err);
    }
  }

  /**
   * Publishes negative sentiment spike alerts to Kafka topic.
   * @param {AggregationResult} res
   * @private
   */
  async _publishAlertIfNeeded(res) {
    if (res.count === 0) return;
    if (res.negativeRatio >= this.negAlertThreshold) {
      const alert = {
        alertId: uuid(),
        ts: Date.now(),
        type: 'NEGATIVITY_SPIKE',
        payload: {
          negativeRatio: res.negativeRatio,
          windowSize: res.count,
        },
      };

      try {
        await this.producer.send({
          topic: 'sentiment.alerts',
          messages: [{ key: alert.alertId, value: JSON.stringify(alert) }],
        });
        console.warn(
          `NEGATIVITY_SPIKE alert emitted: ratio=${res.negativeRatio.toFixed(2)}`
        );
      } catch (err) {
        console.error('Failed to produce sentiment alert', err);
      }
    }
  }
}

/* ========================================================================== */
/* ==========================— CLI Entrypoint —============================= */

/**
 * Allows running the monitor directly:
 *   node src/module_71.js
 */
if (require.main === module) {
  const monitor = new SentimentMonitor();
  monitor
    .start()
    .catch((err) => {
      console.error('Fatal error starting SentimentMonitor', err);
      process.exitCode = 1;
    });

  // Graceful shutdown
  ['SIGINT', 'SIGTERM'].forEach((sig) =>
    process.on(sig, async () => {
      console.info(`Received ${sig}, shutting down...`);
      await monitor.stop();
      process.exit(0);
    })
  );
}
```