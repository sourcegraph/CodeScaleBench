```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: SentimentShiftMonitor
 * File  : src/module_61.js
 *
 * Purpose
 * -------
 * Listens to per-message sentiment classifications, aggregates them in near-real
 * time via RxJS windowing, detects statistically significant sentiment shifts
 * for individual communities, and emits a new domain event back to Kafka to
 * notify downstream pipelines (e.g. automated moderation, alerting, retraining
 * triggers).
 *
 * Design Notes
 * ------------
 * • Uses kafkajs for Kafka I/O and RxJS for in-process streaming.
 * • Buffers incoming messages into sliding windows (configurable) and compares
 *   metrics to the previous window to detect abrupt changes.
 * • Emits OpenTelemetry spans for distributed tracing/monitoring.
 * • Resilient to Kafka rebalance and transient network failures.
 * • Exposes a graceful shutdown hook to cooperate with Kubernetes SIGTERM.
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* Dependencies                                                             */
/* ────────────────────────────────────────────────────────────────────────── */
const { Kafka, logLevel } = require('kafkajs');
const { Subject, Subscription } = require('rxjs');
const {
  bufferTime,
  filter,
  map,
  pairwise,
  tap,
} = require('rxjs/operators');
const _ = require('lodash');
const debug = require('debug')('agorapulse:SentimentShiftMonitor');
const { v4: uuidv4 } = require('uuid');
const {
  trace,
  context,
  SpanStatusCode,
} = require('@opentelemetry/api');

/* ────────────────────────────────────────────────────────────────────────── */
/* Configuration                                                            */
/* ────────────────────────────────────────────────────────────────────────── */
const CONFIG = {
  kafka: {
    brokers: process.env.KAFKA_BROKERS
      ? process.env.KAFKA_BROKERS.split(',')
      : ['localhost:9092'],
    clientId: process.env.KAFKA_CLIENT_ID || 'agorapulse.sentiment-monitor',
    groupId: process.env.KAFKA_GROUP_ID || 'sentiment-monitor-consumer',
    inputTopic: process.env.KAFKA_INPUT_TOPIC || 'sentiment.classified',
    outputTopic: process.env.KAFKA_OUTPUT_TOPIC || 'sentiment.shift',
    ssl: process.env.KAFKA_SSL === 'true',
    sasl:
      process.env.KAFKA_SASL_USERNAME && process.env.KAFKA_SASL_PASSWORD
        ? {
            mechanism: 'plain',
            username: process.env.KAFKA_SASL_USERNAME,
            password: process.env.KAFKA_SASL_PASSWORD,
          }
        : undefined,
  },
  window: {
    durationMs: Number(process.env.WINDOW_DURATION_MS) || 60_000, // 1 min
    slideMs: Number(process.env.WINDOW_SLIDE_MS) || 30_000, // 30 s
    minMessages: Number(process.env.WINDOW_MIN_MESSAGES) || 50,
  },
  shiftDetection: {
    delta: Number(process.env.SENTIMENT_DELTA) || 0.15, // average sentiment delta
    percentileDelta:
      Number(process.env.PERCENTILE_DELTA) || 0.20, // change in 90th percentile
    stdDevMultiplier: Number(process.env.STD_DEV_MULTIPLIER) || 2,
  },
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Helper Functions                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Compute window statistics for a batch of sentiment scores.
 * @param {Array<{communityId:string, sentiment:number, ts:number}>} items
 */
function computeStats(items) {
  const sentiments = items.map((i) => i.sentiment);
  return {
    count: sentiments.length,
    avg: _.mean(sentiments),
    p90: _.nth(_.sortBy(sentiments), Math.floor(sentiments.length * 0.9)),
    std: Math.sqrt(_.mean(sentiments.map((v) => Math.pow(v - _.mean(sentiments), 2)))),
  };
}

/**
 * Determine if two windows represent a significant shift.
 */
function hasShift(prev, curr, criteria = CONFIG.shiftDetection) {
  if (prev.count < CONFIG.window.minMessages || curr.count < CONFIG.window.minMessages) {
    return false;
  }
  const avgShift = Math.abs(curr.avg - prev.avg) >= criteria.delta;
  const p90Shift = Math.abs(curr.p90 - prev.p90) >= criteria.percentileDelta;
  const stdShift = curr.std >= prev.std * criteria.stdDevMultiplier;
  return avgShift || p90Shift || stdShift;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Main Class                                                               */
/* ────────────────────────────────────────────────────────────────────────── */

class SentimentShiftMonitor {
  /**
   * @param {object} [config]
   */
  constructor(config = CONFIG) {
    this.config = config;
    this.kafka = new Kafka({
      clientId: config.kafka.clientId,
      brokers: config.kafka.brokers,
      ssl: config.kafka.ssl,
      sasl: config.kafka.sasl,
      logLevel: logLevel.NOTHING,
    });
    this.consumer = this.kafka.consumer({ groupId: config.kafka.groupId });
    this.producer = this.kafka.producer();
    this.subject = new Subject();
    this.subscription = new Subscription();
    this._running = false;
  }

  /**
   * Start consuming, processing, and emitting shift events.
   */
  async start() {
    if (this._running) return;
    this._running = true;

    debug('Connecting to Kafka...');
    await Promise.all([this.consumer.connect(), this.producer.connect()]);
    await this.consumer.subscribe({
      topic: this.config.kafka.inputTopic,
      fromBeginning: false,
    });
    debug('Kafka connected, starting stream processing');

    // Kick-off RxJS pipeline
    this._setupPipeline();

    // Forward Kafka messages into RxJS Subject
    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          const span = trace
            .getTracer('agorapulse.sentiment-monitor')
            .startSpan('processMessage', undefined, context.active());

          const data = JSON.parse(message.value.toString());
          // Expected shape: { communityId, sentimentScore, timestamp }
          const enriched = {
            ts: data.timestamp || Date.now(),
            sentiment: Number(data.sentimentScore),
            communityId: data.communityId,
          };
          this.subject.next(enriched);
          span.setStatus({ code: SpanStatusCode.OK });
          span.end();
        } catch (err) {
          debug('Malformed message skipped: %O', err);
        }
      },
    });
  }

  /**
   * Configure RxJS operators to window/compare sentiment metrics.
   */
  _setupPipeline() {
    const { durationMs, slideMs } = this.config.window;
    const tracer = trace.getTracer('agorapulse.sentiment-monitor');

    const sub = this.subject
      .pipe(
        // windowing
        bufferTime(durationMs, slideMs),
        filter((batch) => batch.length > 0),
        // group by community to avoid cross-talk
        map((batch) => _.groupBy(batch, 'communityId')),
        // flatten community-specific batches
        tap((groups) => {
          Object.entries(groups).forEach(([communityId, items]) => {
            const span = tracer.startSpan('computeStats');
            try {
              const stats = computeStats(items);
              span.end();
              this.subject.next({ communityId, stats, phase: 'stats' });
            } catch (e) {
              span.setStatus({ code: SpanStatusCode.ERROR, message: e.message });
              span.end();
            }
          });
        }),
        // only pass stat messages through
        filter((msg) => msg.phase === 'stats'),
        map((msg) => ({ communityId: msg.communityId, ...msg.stats })),
        // pairwise to compare consecutive windows
        groupByWindowed('communityId'),
        // detect shift
        filter((pair) => hasShift(pair.prev, pair.curr)),
        map(({ communityId, prev, curr }) => ({
          communityId,
          prev,
          curr,
          detectedAt: Date.now(),
          eventId: uuidv4(),
        }))
      )
      .subscribe({
        next: (event) => this._emitShift(event).catch((e) => debug('emit error: %O', e)),
        error: (err) => debug('Pipeline error: %O', err),
      });

    this.subscription.add(sub);
  }

  /**
   * Emit a sentiment.shift event to Kafka.
   * @private
   */
  async _emitShift(payload) {
    const span = trace
      .getTracer('agorapulse.sentiment-monitor')
      .startSpan('emitShift', undefined, context.active());
    try {
      await this.producer.send({
        topic: this.config.kafka.outputTopic,
        messages: [
          {
            key: payload.communityId,
            value: JSON.stringify(payload),
            timestamp: Date.now().toString(),
          },
        ],
      });
      debug('Sent sentiment shift event: %O', payload);
      span.setStatus({ code: SpanStatusCode.OK });
    } catch (err) {
      span.setStatus({ code: SpanStatusCode.ERROR, message: err.message });
      debug('Failed to emit shift: %O', err);
    } finally {
      span.end();
    }
  }

  /**
   * Gracefully stop the monitor and close resources.
   */
  async stop() {
    if (!this._running) return;
    this._running = false;

    debug('Shutting down monitor...');
    this.subscription.unsubscribe();
    await Promise.allSettled([this.consumer.disconnect(), this.producer.disconnect()]);
    debug('Shutdown complete');
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* RxJS Utility                                                             */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Custom operator: pairs consecutive statistical windows per community.
 * Emits { communityId, prev, curr } objects.
 */
function groupByWindowed(keyField) {
  return (source$) =>
    source$.pipe(
      // organize stream per community
      map((stats) => [stats[keyField], stats]),
      groupBy(([id]) => id),
      mergeMap((group$) =>
        group$.pipe(
          map(([, stats]) => stats),
          pairwise(),
          map(([prev, curr]) => ({
            communityId: curr[keyField],
            prev,
            curr,
          }))
        )
      )
    );
}

const { groupBy, mergeMap } = require('rxjs/operators');

/* ────────────────────────────────────────────────────────────────────────── */
/* Exports                                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

module.exports = {
  SentimentShiftMonitor,
  CONFIG,
};
```