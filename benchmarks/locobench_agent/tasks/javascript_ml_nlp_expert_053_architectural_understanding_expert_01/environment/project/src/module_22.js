```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: src/module_22.js
 *
 * SentimentPipeline
 * -----------------
 * A fully-event-driven micro-pipeline that consumes raw community events from Kafka,
 * enriches them with sentiment scores via an external inference service, records
 * Prometheus metrics, and republishes results for downstream consumers.
 *
 * The pipeline embraces functional-reactive programming with RxJS and is designed
 * for production workloads: back-pressure aware, observable, and resilient to
 * runtime failures.
 *
 * Usage:
 *   const pipeline = new SentimentPipeline(config);
 *   await pipeline.run();
 *
 * Environment variables (fallbacks available via `config` argument):
 *   KAFKA_BROKERS          – comma-separated broker list
 *   KAFKA_GROUP_ID         – consumer group id
 *   IN_TOPIC               – input Kafka topic
 *   OUT_TOPIC              – output Kafka topic
 *   SENTIMENT_URL          – HTTP endpoint performing inference
 *   PIPELINE_TIMEOUT_MS    – sentiment request timeout
 */

'use strict';

/* ────────────────────────────────────────────────────────── External Imports ── */
const { Kafka, logLevel } = require('kafkajs');
const {
  Observable,
  defer,
  from,
  of,
  EMPTY,
  throwError,
  Subject,
  timer,
} = require('rxjs');
const {
  map,
  filter,
  mergeMap,
  catchError,
  timeoutWith,
  tap,
} = require('rxjs/operators');
const promClient = require('prom-client');
const axios = require('axios').default;
const pino = require('pino');
const { v4: uuidv4 } = require('uuid');

/* ──────────────────────────────────────────────────────────────── Constants ── */
const DEFAULT_TIMEOUT_MS = 2_500;

/* ────────────────────────────────────────────────────────────── Metrics ────── */
const metricNamespace = 'agorapulse_sentiment_pipeline';

const metrics = {
  processed: new promClient.Counter({
    name: `${metricNamespace}_processed_total`,
    help: 'Total number of processed events',
    labelNames: ['status'],
  }),
  latency: new promClient.Histogram({
    name: `${metricNamespace}_latency_ms`,
    help: 'Latency of the sentiment inference in milliseconds',
    buckets: [50, 100, 250, 500, 1_000, 2_500, 5_000],
  }),
};

/* ─────────────────────────────────────────────────────────────── Logger ────── */
const logger = pino({
  level: process.env.LOG_LEVEL || 'info',
  prettyPrint: process.env.NODE_ENV !== 'production',
});

/* ────────────────────────────────────────────────────────────── Helpers ────── */

/**
 * Utility: Converts Kafkajs consumer messages into a hot RxJS Observable.
 *
 * @param {import('kafkajs').Consumer} consumer
 * @param {string[]} topics
 * @returns {Observable<import('kafkajs').EachMessagePayload>}
 */
function createKafkaObservable(consumer, topics) {
  const subject$ = new Subject();

  (async () => {
    for (const topic of topics) {
      await consumer.subscribe({ topic, fromBeginning: false });
    }

    await consumer.run({
      eachMessage: async (payload) => {
        subject$.next(payload);
      },
    });
  })().catch((err) => subject$.error(err));

  return subject$.asObservable();
}

/**
 * Utility: Stringifies payloads while guaranteeing single-line JSON for
 * easier ingestion in downstream systems.
 */
function safeStringify(payload) {
  try {
    return JSON.stringify(payload);
  } catch (e) {
    logger.error({ err: e, payload }, 'Failed to stringify payload');
    return '{"error":"stringify_failed"}';
  }
}

/* ──────────────────────────────────────────────────────────── Pipeline ────── */

class SentimentPipeline {
  /**
   * @typedef {Object} PipelineConfig
   * @property {string[]} kafkaBrokers
   * @property {string} groupId
   * @property {string} inTopic
   * @property {string} outTopic
   * @property {string} sentimentServiceUrl
   * @property {number} [timeoutMs]
   */

  /**
   * @param {Partial<PipelineConfig>} cfg
   */
  constructor(cfg = {}) {
    /** @type {PipelineConfig} */
    this.config = {
      kafkaBrokers:
        cfg.kafkaBrokers ?? process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
      groupId: cfg.groupId ?? process.env.KAFKA_GROUP_ID ?? 'agorapulse.sentiment',
      inTopic: cfg.inTopic ?? process.env.IN_TOPIC ?? 'community.raw',
      outTopic: cfg.outTopic ?? process.env.OUT_TOPIC ?? 'community.sentiment',
      sentimentServiceUrl:
        cfg.sentimentServiceUrl ??
        process.env.SENTIMENT_URL ??
        'http://sentiment-inference:8080/predict',
      timeoutMs: cfg.timeoutMs ?? Number(process.env.PIPELINE_TIMEOUT_MS) || DEFAULT_TIMEOUT_MS,
    };

    this.kafka = new Kafka({
      clientId: 'agorapulse-sentiment-pipeline',
      brokers: this.config.kafkaBrokers,
      logLevel: logLevel.WARN,
    });

    this.consumer = this.kafka.consumer({ groupId: this.config.groupId });
    this.producer = this.kafka.producer({ idempotent: true });
    this.shutdownRequested = false;
  }

  /**
   * Boots the Kafka producer and consumer, wires the RxJS pipeline, and starts
   * consuming messages until the process receives a SIGINT / SIGTERM.
   */
  async run() {
    logger.info(this.config, 'Starting SentimentPipeline');

    // Connect Kafka clients
    await Promise.all([this.consumer.connect(), this.producer.connect()]);

    // Build the reactive data-flow
    const message$ = createKafkaObservable(this.consumer, [this.config.inTopic]);

    const subscription = message$
      .pipe(
        // Parse the Kafka message JSON payload
        map(({ topic, partition, message }) => {
          const eventString = message.value?.toString('utf8') ?? '';
          let event;
          try {
            event = JSON.parse(eventString);
          } catch (err) {
            logger.warn(
              { err, eventString },
              'Dropping message: invalid JSON',
            );
            metrics.processed.inc({ status: 'malformed' });
            // Returning EMPTY prevents further operators from running
            return EMPTY;
          }
          return { raw: event, meta: { topic, partition, offset: message.offset } };
        }),
        // Filter out everything except user messages
        filter((item) => item !== EMPTY && item.raw.eventType === 'MESSAGE_PUBLISHED'),
        // Perform sentiment inference with timeout
        mergeMap((item) => this._inferSentiment(item), 8), // up-to 8 concurrent inferences
        // Publish the enriched event to Kafka
        mergeMap((enrichedEvent) => this._publishResult(enrichedEvent)),
      )
      .subscribe({
        error: (err) => {
          logger.error({ err }, 'Pipeline stream encountered fatal error');
          process.exitCode = 1;
          this.shutdown().catch((e) => logger.error({ e }, 'Shutdown after fatal error failed'));
        },
      });

    // Graceful shutdown
    for (const signal of ['SIGINT', 'SIGTERM']) {
      process.once(signal, () => {
        logger.info({ signal }, 'Shutdown signal received');
        this.shutdownRequested = true;
        subscription.unsubscribe();
        this.shutdown().catch((e) => logger.error({ e }, 'Shutdown failure'));
      });
    }

    // Keep process alive
    logger.info('SentimentPipeline is now consuming events');
  }

  /**
   * Executes HTTP call to remote sentiment inference service.
   *
   * @private
   * @param {{ raw: any, meta: any }} item
   * @returns {Observable<{ enriched: any, raw: any }>}
   */
  _inferSentiment(item) {
    const startTime = Date.now();
    const { raw } = item;

    return defer(() =>
      axios.post(
        this.config.sentimentServiceUrl,
        { text: raw.payload.text ?? '' },
        { timeout: this.config.timeoutMs },
      ),
    ).pipe(
      map((resp) => resp.data),
      catchError((err) => {
        logger.warn({ err, eventId: raw.id }, 'Sentiment service error, defaulting to neutral');
        // Instead of failing entire stream, emit fallback result
        return of({ score: 0, label: 'neutral', error: 'fallback' });
      }),
      tap(() => {
        const latency = Date.now() - startTime;
        metrics.latency.observe(latency);
      }),
      map((sentiment) => ({
        enriched: {
          ...raw,
          sentiment,
          processedAt: new Date().toISOString(),
        },
        raw,
      })),
      tap(() => metrics.processed.inc({ status: 'ok' })),
    );
  }

  /**
   * Publishes enriched event to Kafka.
   *
   * @private
   * @param {{ enriched: any, raw: any }} param0
   * @returns {Observable<void>}
   */
  _publishResult({ enriched, raw }) {
    const message = {
      key: raw.userId?.toString() ?? uuidv4(),
      value: safeStringify(enriched),
      headers: {
        'x-correlation-id': raw.correlationId ?? uuidv4(),
        'x-produced-at': new Date().toISOString(),
      },
    };

    return from(
      this.producer.send({
        topic: this.config.outTopic,
        messages: [message],
      }),
    ).pipe(
      catchError((err) => {
        logger.error({ err, eventId: raw.id }, 'Failed to produce enriched event');
        metrics.processed.inc({ status: 'produce_error' });
        return EMPTY; // Swallow error: we don't want to crash pipeline
      }),
    );
  }

  /**
   * Gracefully disconnects Kafka clients.
   */
  async shutdown() {
    if (this.shutdownRequested) {
      return;
    }
    this.shutdownRequested = true;

    logger.info('Shutting down SentimentPipeline');
    try {
      await Promise.allSettled([this.consumer.disconnect(), this.producer.disconnect()]);
    } finally {
      // Flush logs
      logger.flush();
      process.exit(0);
    }
  }
}

/* ────────────────────────────────────────────────────────────── Bootstrap ─── */

if (require.main === module) {
  // If this module is executed directly, bootstrap the pipeline
  (async () => {
    try {
      const pipeline = new SentimentPipeline();
      await pipeline.run();
    } catch (err) {
      logger.error({ err }, 'Fatal bootstrapping error');
      process.exitCode = 1;
    }
  })();
}

/* ────────────────────────────────────────────────────────────── Exports ───── */
module.exports = { SentimentPipeline };
```