```javascript
// File: src/module_14.js
// Project: AgoraPulse - Real-Time Social Signal Intelligence
//
// -----------------------------------------------------------------------------
// WindowedSentimentAggregator
// -----------------------------------------------------------------------------
// Listens to low-level “sentiment-prediction” events coming from the real-time
// feature pipeline, performs sliding-window aggregation per community, and
// republishes window-level aggregates to a downstream Kafka topic so that
// dashboards, alerting rules, and adaptive-content engines can react in near
// real time.
//
// ─── Tech Stack ────────────────────────────────────────────────────────────────
// • KafkaJS             – stream transport (consumer / producer)
// • RxJS                – reactive in-process pipeline
// • Axios               – HTTP client for model-monitoring callbacks
// • uuid                – correlation / id generation
// -----------------------------------------------------------------------------
// Author: AgoraPulse Core Engineering
// License: Apache-2.0
// -----------------------------------------------------------------------------

/* eslint-disable no-console */

'use strict';

const { Kafka, logLevel } = require('kafkajs');
const {
  Subject,
  BehaviorSubject,
  timer,
  of,
} = require('rxjs');
const {
  groupBy,
  bufferTime,
  mergeMap,
  map,
  filter,
  tap,
  catchError,
  retryWhen,
  delayWhen,
} = require('rxjs/operators');
const axios = require('axios').default;
const { v4: uuidv4 } = require('uuid');

/* -------------------------------------------------------------------------- */
/*                               Config Defaults                              */
/* -------------------------------------------------------------------------- */

/**
 * Default configuration.  Override by passing a partial config object when
 * instantiating the aggregator or by using environment variables.
 */
const DEFAULT_CONFIG = Object.freeze({
  kafka: {
    brokers: process.env.KAFKA_BROKERS?.split(',') || ['localhost:9092'],
    clientId: process.env.KAFKA_CLIENT_ID || 'agorapulse-sentiment-aggregator',
    ssl: process.env.KAFKA_SSL === 'true',
  },
  topics: {
    source: process.env.KAFKA_TOPIC_SOURCE || 'social.predictions.sentiment',
    sink: process.env.KAFKA_TOPIC_SINK || 'social.aggregates.sentiment.window',
  },
  window: {
    /* Sliding time window size in milliseconds */
    durationMs: Number(process.env.AGG_WINDOW_MS) || 30_000,
    /* Maximum number of items kept inside a single buffer before it flushes */
    maxBufferSize: Number(process.env.AGG_WINDOW_MAX_SIZE) || 5_000,
  },
  monitoring: {
    /* HTTP Endpoint to push anomaly notifications to model-monitoring service */
    endpoint:
      process.env.MODEL_MON_MONITORING_ENDPOINT ||
      'http://localhost:7000/api/v1/alerts',
    /* If `avgSentiment` goes below this threshold an alert is emitted */
    negativeSentimentThreshold:
      Number(process.env.NEG_SENTIMENT_THRESHOLD) || -0.6,
  },
  retry: {
    /* Exponential back-off base (ms) for transient failures */
    baseDelayMs: 1000,
    /* Maximum amount of retries before giving up */
    maxRetries: 5,
  },
});

/* -------------------------------------------------------------------------- */
/*                             Utility / Type Guards                          */
/* -------------------------------------------------------------------------- */

/**
 * Parses a Kafka message value (assumed JSON) into a plain object.
 * @param {import('kafkajs').KafkaMessage} msg
 * @returns {{communityId: string, sentiment: number, timestamp: number, ...}}
 */
function parseMessage(msg) {
  try {
    // KafkaJS delivers the message value as a Buffer
    return JSON.parse(msg.value.toString('utf8'));
  } catch (err) {
    console.error(`[Aggregator] Failed to parse message:`, err);
    return null;
  }
}

/**
 * Calculates windowed sentiment statistics.
 * @param {Array<{sentiment: number, timestamp: number}>} events
 * @returns {{count: number, avgSentiment: number, min: number, max: number}}
 */
function calculateStats(events) {
  const count = events.length;
  if (count === 0) {
    return { count: 0, avgSentiment: 0, min: 0, max: 0 };
  }
  let sum = 0;
  let min = Infinity;
  let max = -Infinity;
  for (const { sentiment } of events) {
    sum += sentiment;
    if (sentiment < min) min = sentiment;
    if (sentiment > max) max = sentiment;
  }
  return {
    count,
    avgSentiment: sum / count,
    min,
    max,
  };
}

/* -------------------------------------------------------------------------- */
/*                          WindowedSentimentAggregator                       */
/* -------------------------------------------------------------------------- */

class WindowedSentimentAggregator {
  /**
   * @param {Partial<typeof DEFAULT_CONFIG>} [customConfig]
   */
  constructor(customConfig = {}) {
    this.config = deepMerge(DEFAULT_CONFIG, customConfig);

    // Kafka client / producer / consumer
    this.kafka = new Kafka({
      clientId: this.config.kafka.clientId,
      brokers: this.config.kafka.brokers,
      ssl: this.config.kafka.ssl,
      logLevel: logLevel.NOTHING,
    });

    this.producer = this.kafka.producer();
    this.consumer = this.kafka.consumer({ groupId: this.config.kafka.clientId });

    // RxJS subject as the bridge between Kafka messages and reactive ops
    this._event$ = new Subject();

    // Stop / shutdown coordination
    this._isShuttingDown$ = new BehaviorSubject(false);
  }

  /* -------------------------------------------------------------------- */
  /*                              Lifecycle                               */
  /* -------------------------------------------------------------------- */

  /**
   * Initializes Kafka connections and spins up the reactive pipeline.
   */
  async start() {
    console.info('[Aggregator] Starting WindowedSentimentAggregator …');

    await Promise.all([this.producer.connect(), this.consumer.connect()]);

    await this.consumer.subscribe({
      topic: this.config.topics.source,
      fromBeginning: false,
    });

    // Forward valid messages to the Subject
    this.consumer.run({
      eachMessage: async ({ message }) => {
        const payload = parseMessage(message);
        if (payload && payload.communityId && typeof payload.sentiment === 'number') {
          this._event$.next(payload);
        }
        // Invalid messages are silently ignored; statistics would capture them separately
      },
    });

    // Build reactive graph
    this._subscription = this._buildReactivePipeline();

    // Graceful shutdown signals
    process.once('SIGINT', () => this.stop());
    process.once('SIGTERM', () => this.stop());
  }

  /**
   * Tears down Kafka resources and reactive streams.
   */
  async stop() {
    // Ensure idempotency
    if (this._isShuttingDown$.value) return;
    this._isShuttingDown$.next(true);

    console.info('[Aggregator] Shutting down WindowedSentimentAggregator …');

    // Wait for in-flight buffers to flush
    await this._subscription?.unsubscribe?.();

    await Promise.all([
      this.consumer.disconnect().catch(() => undefined),
      this.producer.disconnect().catch(() => undefined),
    ]);

    console.info('[Aggregator] Graceful shutdown complete.');
  }

  /* -------------------------------------------------------------------- */
  /*                           Reactive Pipeline                          */
  /* -------------------------------------------------------------------- */

  /**
   * Creates the RxJS pipeline that does:
   *   1. groupBy communityId
   *   2. bufferTime → window aggregations
   *   3. calculate statistics
   *   4. forward to sink Kafka topic
   *   5. trigger monitoring on negative spikes
   *
   * @returns {import('rxjs').Subscription}
   */
  _buildReactivePipeline() {
    const {
      window: { durationMs, maxBufferSize },
      monitoring: { negativeSentimentThreshold },
    } = this.config;

    return this._event$
      .pipe(
        // ------------------------------------
        // Split stream per community
        // ------------------------------------
        groupBy((event) => event.communityId),

        // ------------------------------------
        // Per-community sliding window
        // ------------------------------------
        mergeMap((community$) =>
          community$.pipe(
            bufferTime(durationMs, undefined, maxBufferSize),
            filter((events) => events.length > 0),
            map((events) => ({
              communityId: community$.key,
              windowStart: events[0].timestamp,
              windowEnd: events[events.length - 1].timestamp,
              stats: calculateStats(events),
            }))
          )
        ),

        // ------------------------------------
        // Post-processing & side effects
        // ------------------------------------
        tap((aggregate) => this._publishAggregate(aggregate)),
        mergeMap((aggregate) => this._maybeSendMonitoringAlert(aggregate, negativeSentimentThreshold)),

        // ------------------------------------
        // Error handling / resiliency
        // ------------------------------------
        catchError((err, caught$) => {
          console.error('[Aggregator] Stream error encountered:', err);
          // Let the stream continue (swallow error) – or one could return of()
          return caught$;
        })
      )
      .subscribe();
  }

  /* -------------------------------------------------------------------- */
  /*                          Side-Effect Functions                       */
  /* -------------------------------------------------------------------- */

  /**
   * Publishes the computed aggregate to a Kafka topic.
   * @param {{
   *  communityId: string,
   *  windowStart: number,
   *  windowEnd: number,
   *  stats: {count:number, avgSentiment:number, min:number, max:number}
   * }} aggregate
   */
  async _publishAggregate(aggregate) {
    const payload = {
      ...aggregate,
      aggregateId: uuidv4(),
      createdAt: Date.now(),
    };

    try {
      await this.producer.send({
        topic: this.config.topics.sink,
        messages: [
          {
            key: aggregate.communityId,
            value: JSON.stringify(payload),
          },
        ],
      });

      console.debug(
        `[Aggregator] Sent aggregate for community=${aggregate.communityId} ` +
          `(count=${aggregate.stats.count}, avg=${aggregate.stats.avgSentiment.toFixed(3)})`
      );
    } catch (err) {
      console.error('[Aggregator] Failed to publish aggregate:', err);
    }
  }

  /**
   * Sends a monitoring alert if negative sentiment exceeds threshold.
   * Returns a cold Observable so that mergeMap can subscribe to it.
   *
   * @param {{communityId:string, stats:{avgSentiment:number}}} aggregate
   * @param {number} threshold
   */
  _maybeSendMonitoringAlert(aggregate, threshold) {
    if (aggregate.stats.avgSentiment >= threshold) {
      return of(null); // No alert required
    }

    const alertPayload = {
      id: uuidv4(),
      type: 'NEGATIVE_SENTIMENT_SPIKE',
      timestamp: Date.now(),
      communityId: aggregate.communityId,
      aggregatedWindow: {
        start: aggregate.windowStart,
        end: aggregate.windowEnd,
      },
      metrics: aggregate.stats,
      threshold,
      // Additional metadata for correlation
      source: 'WindowedSentimentAggregator',
      environment: process.env.NODE_ENV || 'development',
    };

    console.warn(
      `[Aggregator] Negative sentiment alert for community=${aggregate.communityId} ` +
        `(avg=${aggregate.stats.avgSentiment.toFixed(3)} < ${threshold})`
    );

    // Return an Observable to integrate nicely with RxJS error handling
    return of(alertPayload).pipe(
      mergeMap((payload) =>
        axios
          .post(this.config.monitoring.endpoint, payload, {
            timeout: 5_000,
          })
          .then(() => null) // Map to null to keep stream type consistent
      ),
      retryWithBackoff(this.config.retry),
      catchError((err) => {
        console.error('[Aggregator] Failed to send monitoring alert:', err);
        return of(null); // Swallow error so the main stream remains alive
      })
    );
  }
}

/* -------------------------------------------------------------------------- */
/*                              Helper Functions                              */
/* -------------------------------------------------------------------------- */

/**
 * Performs a deep merge of `source` into `target`. Arrays & primitives in
 * `source` fully overwrite `target`'s values to avoid unexpected semantics.
 *
 * @param {object} target
 * @param {object} source
 * @returns {object} new merged object
 */
function deepMerge(target, source) {
  // Simple implementation sufficient for config objects
  if (!source) return { ...target };
  const output = { ...target };
  for (const [key, value] of Object.entries(source)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      output[key] = deepMerge(target[key] || {}, value);
    } else {
      output[key] = value;
    }
  }
  return output;
}

/**
 * Factory for RxJS `retryWhen` with exponential back-off.
 *
 * @param {{baseDelayMs:number, maxRetries:number}} cfg
 */
function retryWithBackoff(cfg) {
  const { baseDelayMs, maxRetries } = cfg;
  return retryWhen((errors) =>
    errors.pipe(
      mergeMap((error, i) => {
        const attempt = i + 1;
        if (attempt > maxRetries) {
          console.error(
            `[Aggregator] Max retries (${maxRetries}) exceeded. Giving up.`,
            error
          );
          throw error;
        }
        const delayMs = baseDelayMs * 2 ** i;
        console.warn(
          `[Aggregator] Attempt ${attempt} failed – retrying in ${delayMs}ms`
        );
        return timer(delayMs);
      })
    )
  );
}

/* -------------------------------------------------------------------------- */
/*                               Entry-point                                 */
/* -------------------------------------------------------------------------- */

if (require.main === module) {
  // Launch directly if executed as a node process
  const aggregator = new WindowedSentimentAggregator();

  aggregator
    .start()
    .then(() =>
      console.info('[Aggregator] WindowedSentimentAggregator is up & running.')
    )
    .catch((err) => {
      console.error('[Aggregator] Startup failed:', err);
      process.exitCode = 1;
    });
}

module.exports = {
  WindowedSentimentAggregator,
};
```