```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * ------------------------------------------------
 * Module 45 — RealTimeThresholdMonitor
 *
 * Purpose
 * -------
 * Listen to model-serving events (sentiment, toxicity, etc.) delivered over Kafka,
 * transform them into RxJS streams, calculate rolling window statistics, and emit
 * “threshold-breach” domain events when metrics exceed configured limits. These events
 * fan out to downstream services: auto-moderation bots, retraining pipelines,
 * alerting dashboards, etc.
 *
 * Design Highlights
 * -----------------
 * • Kafka <-> RxJS bridge for unified reactive processing
 * • Time-windowed metrics with configurable tumbling/rolling windows
 * • Pluggable threshold rules (Strategy Pattern)
 * • Robust error handling / auto-reconnect logic
 *
 * Dependencies
 * ------------
 * – kafkajs                    (Kafka client)
 * – rxjs                       (Reactive streams)
 * – lodash                     (Utility helpers)
 * – debug                      (Selective logging)
 *
 * NOTE: Keep this file dependency-light; heavy ML logic lives elsewhere.
 */

import { Kafka, logLevel } from 'kafkajs';
import {
  Subject,
  merge,
  timer,
  EMPTY,
  from,
  throwError,
  defer,
} from 'rxjs';
import {
  bufferTime,
  catchError,
  filter,
  map,
  mergeMap,
  retry,
  share,
  tap,
} from 'rxjs/operators';
import _ from 'lodash';
import debugLib from 'debug';

const log = debugLib('agorapulse:threshold-monitor');

/** -----------------------------------------------------------------------
 * Utility Helpers
 * --------------------------------------------------------------------- */

/**
 * Calculates the rate of items in an array matching a predicate.
 * @param {Array<any>} arr
 * @param {(item: any) => boolean} predicate
 * @returns {number} Between 0 and 1 (inclusive); returns 0 for empty array.
 */
const ratio = (arr, predicate) =>
  arr.length === 0 ? 0 : _.filter(arr, predicate).length / arr.length;

/** -----------------------------------------------------------------------
 * Threshold Strategy Interface
 * --------------------------------------------------------------------- */

/**
 * @typedef {Object} ThresholdStrategy
 * @property {(metrics: WindowMetrics) => boolean} breach
 * @property {string} reason
 */

/**
 * Generates a simple rate-threshold strategy.
 *
 * @param {keyof WindowMetrics} metricKey          Metric to evaluate
 * @param {number} limit                           Critical threshold (0..1)
 * @param {'>' | '<'} comparator                   Breach condition comparator
 * @param {string} reason                          Human-readable reason
 * @returns {ThresholdStrategy}
 */
const createRateThreshold = (metricKey, limit, comparator, reason) => ({
  reason,
  breach: (metrics) => {
    if (!_.isNumber(metrics[metricKey])) return false;
    return comparator === '>' ? metrics[metricKey] > limit : metrics[metricKey] < limit;
  },
});

/** -----------------------------------------------------------------------
 * Data Contracts
 * --------------------------------------------------------------------- */

/**
 * @typedef {Object} ModelEvent
 * @property {string} id               Unique inference event id
 * @property {string} modelName        Model name ("sentiment-v2", "toxicity-v1" …)
 * @property {number} createdAt        Epoch millis timestamp
 * @property {number} score            Raw model score (0..1) or logits
 * @property {string} label            Predicted class label ("POS", "NEG", …)
 * @property {Object<string,any>} meta Additional metadata (userId, geo, emojis …)
 */

/**
 * @typedef {Object} WindowMetrics
 * @property {number} size                     # events processed in window
 * @property {number} toxicityRate             % toxic events
 * @property {number} negativeSentimentRate    % negative sentiment events
 */

/**
 * @typedef {Object} ThresholdBreachEvent
 * @property {string} id
 * @property {number} emittedAt
 * @property {WindowMetrics} metrics
 * @property {string} reason
 */

/** -----------------------------------------------------------------------
 * RealTimeThresholdMonitor Class
 * --------------------------------------------------------------------- */

export class RealTimeThresholdMonitor {
  /**
   * @param {Object} opts
   * @param {string[]} opts.kafkaBrokers            Bootstrap brokers
   * @param {string}   opts.consumeTopic            Topic emitting ModelEvent JSON
   * @param {string}   opts.produceTopic            Topic to publish ThresholdBreachEvent JSON
   * @param {number}   [opts.windowMs=30_000]       Rolling window size (ms)
   * @param {number}   [opts.emitEveryMs=5_000]     Evaluation cadence (ms)
   * @param {ThresholdStrategy[]} [opts.strategies] Custom threshold strategies
   * @param {Object}   [opts.kafkaConfig]           Extra KafkaJS config
   */
  constructor(opts) {
    this.opts = {
      windowMs: 30_000,
      emitEveryMs: 5_000,
      strategies: [],
      ...opts,
    };

    if (!this.opts.kafkaBrokers?.length)
      throw new Error('Kafka brokers are required');

    this.kafka = new Kafka({
      brokers: this.opts.kafkaBrokers,
      logLevel: logLevel.ERROR,
      ...(this.opts.kafkaConfig || {}),
    });

    this.consumer = this.kafka.consumer({ groupId: 'agorapulse-threshold-monitor' });
    this.producer = this.kafka.producer();

    this.modelEvent$ = new Subject();
    this.breachEvent$ = new Subject();

    this._initStrategies();
  }

  /** Initialize default strategies if none were provided. */
  _initStrategies() {
    if (this.opts.strategies.length > 0) {
      this.strategies = this.opts.strategies;
      return;
    }

    // Default conservative thresholds
    this.strategies = [
      createRateThreshold(
        'toxicityRate',
        0.10,
        '>',
        'Toxicity > 10% — potential flare-up detected',
      ),
      createRateThreshold(
        'negativeSentimentRate',
        0.45,
        '>',
        'Negative sentiment > 45% — community sentiment dropping',
      ),
    ];
  }

  /** -------------------------------------------------------------------
   * Kafka Plumbing
   * ------------------------------------------------------------------- */

  /**
   * Connect to Kafka, start consuming ModelEvent messages, and pipe them
   * into the RxJS stream.
   */
  async start() {
    await Promise.all([this.consumer.connect(), this.producer.connect()]);
    await this.consumer.subscribe({ topic: this.opts.consumeTopic, fromBeginning: false });

    // Consume loop
    this.consumer.run({
      autoCommit: true,
      eachMessage: async ({ message }) => {
        try {
          const evt = JSON.parse(message.value.toString());
          this.modelEvent$.next(evt);
        } catch (err) {
          log('Deserialization error: %O', err);
        }
      },
    });

    log(`🚀 Threshold monitor consuming ${this.opts.consumeTopic}`);

    // Fire up RxJS pipeline
    this._wireUpStream();
  }

  /**
   * Disconnect Kafka clients and terminate streams.
   */
  async stop() {
    log('Stopping threshold monitor …');
    await Promise.allSettled([this.consumer.disconnect(), this.producer.disconnect()]);
    this.modelEvent$.complete();
    this.breachEvent$.complete();
  }

  /** -------------------------------------------------------------------
   * RxJS Stream Wiring
   * ------------------------------------------------------------------- */

  /**
   * Build reactive pipeline: Ingest ModelEvent → Buffer by time →
   * Calculate WindowMetrics → Evaluate strategies → Emit breach events.
   */
  _wireUpStream() {
    // 1. Buffer events per window
    const metrics$ = this.modelEvent$.pipe(
      bufferTime(this.opts.windowMs, null, Number.POSITIVE_INFINITY),
      filter((buffer) => buffer.length > 0),
      map(this._calcWindowMetrics.bind(this)),
      share(),
    );

    // 2. Evaluate threshold strategies
    const breach$ = metrics$.pipe(
      mergeMap((metrics) =>
        from(this.strategies).pipe(
          filter((s) => s.breach(metrics)),
          map((s) => this._createBreachEvent(metrics, s.reason)),
        ),
      ),
      share(),
    );

    // 3. Publish to Kafka and internal Subject
    breach$
      .pipe(
        mergeMap((evt) =>
          defer(() =>
            this.producer.send({
              topic: this.opts.produceTopic,
              messages: [{ value: JSON.stringify(evt) }],
            }),
          ).pipe(
            tap(() => this.breachEvent$.next(evt)),
            tap(() => log('⚠️  Threshold breached: %s', evt.reason)),
            retry({ count: 3, delay: 500 }),
            catchError((err) => {
              log('Kafka publish error: %O', err);
              return EMPTY;
            }),
          ),
        ),
      )
      .subscribe();

    // Optionally, log every metrics sample (low volume)
    metrics$
      .pipe(
        throttleTime(this.opts.emitEveryMs),
        tap((m) => log('Window metrics: %o', m)),
      )
      .subscribe();
  }

  /**
   * Convert buffered ModelEvents to aggregate metrics.
   * @param {ModelEvent[]} buffer
   * @returns {WindowMetrics}
   * @private
   */
  _calcWindowMetrics(buffer) {
    return {
      size: buffer.length,
      toxicityRate: ratio(buffer, (e) => e.label === 'TOXIC'),
      negativeSentimentRate: ratio(buffer, (e) => e.label === 'NEG'),
    };
  }

  /**
   * Build a domain event for a threshold breach.
   * @param {WindowMetrics} metrics
   * @param {string} reason
   * @returns {ThresholdBreachEvent}
   * @private
   */
  _createBreachEvent(metrics, reason) {
    return {
      id: _.uniqueId('breach_'),
      emittedAt: Date.now(),
      metrics,
      reason,
    };
  }
}

/** -----------------------------------------------------------------------
 * Default Export Factory
 * --------------------------------------------------------------------- */

/**
 * Factory helper so callers can do:
 *
 *   import createMonitor from './module_45.js';
 *   const monitor = createMonitor(config);
 *
 * @param {ConstructorParameters<typeof RealTimeThresholdMonitor>[0]} opts
 * @returns {RealTimeThresholdMonitor}
 */
export default function createMonitor(opts) {
  return new RealTimeThresholdMonitor(opts);
}

/** -----------------------------------------------------------------------
 * Usage Example (commented out)
 * --------------------------------------------------------------------- */
/*
(async () => {
  const monitor = createMonitor({
    kafkaBrokers: ['kafka:9092'],
    consumeTopic: 'agorapulse.model.sentiment.out',
    produceTopic: 'agorapulse.alerts.threshold',
  });

  monitor.breachEvent$.subscribe((evt) => {
    console.log('⚠️  BREACH EVENT:', evt);
  });

  await monitor.start();

  // Graceful shutdown
  process.on('SIGINT', () => monitor.stop().then(() => process.exit(0)));
})();
*/
```