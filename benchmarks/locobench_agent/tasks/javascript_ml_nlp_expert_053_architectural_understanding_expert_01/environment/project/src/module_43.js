```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module 43: Sliding-Window False-Negative Monitor
 *
 * This module listens to model-prediction events and moderation-override
 * events flowing through Kafka, joins them in real-time, computes the
 * rolling false-negative (FN) rate for any model version, and emits an
 * alert when the rate breaches a configurable threshold.
 *
 * Technologies used:
 *   • kafkajs      – low-latency Kafka client
 *   • rxjs         – functional reactive stream composition
 *   • prom-client  – Prometheus instrumentation
 *   • debug        – structured, leveled logging
 *   • lodash       – small utils (e.g., identity, noop)
 *
 * Author: AgoraPulse ML/NLP Platform Team
 * License: MIT
 */

import { Kafka, logLevel } from 'kafkajs';
import {
  bufferTime,
  filter,
  map,
  mergeMap,
  tap,
} from 'rxjs/operators';
import { Observable, Subject, fromEvent, merge, of, timer } from 'rxjs';
import { Gauge, Counter, register } from 'prom-client';
import pRetry from 'p-retry';
import debugLib from 'debug';
import { identity, noop } from 'lodash';

const debug = debugLib('agorapulse:monitor:false-negative');

/* ------------------------------------------------------------------ */
/* Configuration                                                      */
/* ------------------------------------------------------------------ */

export const DEFAULT_CONFIG = Object.freeze({
  kafka: {
    clientId: 'agorapulse-fn-monitor',
    brokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    connectionTimeout: 30_000,
    authenticationTimeout: 10_000,
    requestTimeout: 30_000,
    logLevel: logLevel.ERROR,
  },
  topics: {
    prediction: process.env.TOPIC_PREDICTION || 'agorapulse.predictions',
    override: process.env.TOPIC_OVERRIDE || 'agorapulse.moderation.overrides',
    alert: process.env.TOPIC_ALERT || 'agorapulse.alerts',
  },
  monitoring: {
    windowMs: Number(process.env.WINDOW_MS) || 60_000,      // 1 minute windows
    minSamples: Number(process.env.MIN_SAMPLES) || 100,      // require N messages before evaluating
    threshold: Number(process.env.FN_THRESHOLD) || 0.03,     // 3% false-negative threshold
  },
});

/* ------------------------------------------------------------------ */
/* Metrics                                                            */
/* ------------------------------------------------------------------ */

const labels = ['model_version'];

const fnRateGauge = new Gauge({
  name: 'agorapulse_model_fn_rate',
  help: 'Rolling false-negative rate for a given model version',
  labelNames: labels,
});

const alertCounter = new Counter({
  name: 'agorapulse_fn_alert_total',
  help: 'Total number of false-negative alerts emitted',
  labelNames: labels,
});

/* ------------------------------------------------------------------ */
/* Utility helpers                                                    */
/* ------------------------------------------------------------------ */

/**
 * Converts a kafkajs consumer into an RxJS Observable stream of
 * deserialized messages.
 * @param {import('kafkajs').Consumer} consumer
 * @param {string} topic
 * @returns {Observable<Object>}
 */
const topic$ = (consumer, topic) =>
  new Observable((subscriber) => {
    // Subscribe & forward messages to RxJS subscriber
    (async () => {
      try {
        await consumer.subscribe({ topic, fromBeginning: false });
        await consumer.run({
          eachMessage: async ({ message }) => {
            try {
              const payload = JSON.parse(
                message.value.toString('utf8'),
              );
              subscriber.next(payload);
            } catch (err) {
              debug('Failed to parse message on topic %s: %o', topic, err);
              // Skip malformed messages; do not crash the stream
            }
          },
        });
      } catch (err) {
        subscriber.error(err);
      }
    })();

    // Teardown
    return () => {
      consumer
        .stop()
        .then(noop)
        .catch((e) =>
          debug('Error stopping consumer for topic %s: %o', topic, e),
        );
    };
  });

/* ------------------------------------------------------------------ */
/* Core Monitor Class                                                 */
/* ------------------------------------------------------------------ */

export class FalseNegativeMonitor {
  /**
   * @param {Partial<typeof DEFAULT_CONFIG>} [cfg]
   */
  constructor(cfg = {}) {
    this.config = mergeDeep(DEFAULT_CONFIG, cfg);
    this.kafka = new Kafka(this.config.kafka);

    this.predictionConsumer = this.kafka.consumer({
      groupId: `${this.config.kafka.clientId}-prediction`,
    });
    this.overrideConsumer = this.kafka.consumer({
      groupId: `${this.config.kafka.clientId}-override`,
    });
    this.producer = this.kafka.producer();

    this.started = false;
  }

  /* ------------------------------------------------------------ */
  /* Lifecycle                                                    */
  /* ------------------------------------------------------------ */

  async start() {
    if (this.started) return;
    debug('Starting FalseNegativeMonitor…');

    await Promise.all([
      this.predictionConsumer.connect(),
      this.overrideConsumer.connect(),
      this.producer.connect(),
    ]);

    // Build reactive streams
    const prediction$ = topic$(
      this.predictionConsumer,
      this.config.topics.prediction,
    ).pipe(filter(isValidPrediction));

    const override$ = topic$(
      this.overrideConsumer,
      this.config.topics.override,
    ).pipe(filter(isValidOverride));

    // Join predictions with overrides on messageId within the window
    const evaluation$ = joinStreams(prediction$, override$);

    // Sliding-window aggregate & threshold evaluation
    this.subscription = evaluation$
      .pipe(
        bufferTime(this.config.monitoring.windowMs),
        filter((batch) => batch.length >= this.config.monitoring.minSamples),
        map(computeStats),
        tap((stat) => recordMetrics(stat)),
        filter(
          ({ falseNegativeRate }) =>
            falseNegativeRate >= this.config.monitoring.threshold,
        ),
        mergeMap((stat) => this._emitAlert(stat)),
      )
      .subscribe({
        next: ({ modelVersion }) => {
          alertCounter.inc({ model_version: modelVersion });
          debug(
            'Alert emitted for model %s (FN rate exceeded)',
            modelVersion,
          );
        },
        error: (err) => {
          debug('Stream error: %o', err);
          // Fatal – escalate & crash to let K8s restart the pod
          process.nextTick(() => {
            throw err;
          });
        },
      });

    this.started = true;
    debug('FalseNegativeMonitor started.');
  }

  async stop() {
    if (!this.started) return;

    debug('Stopping FalseNegativeMonitor…');
    this.subscription?.unsubscribe();

    await Promise.all([
      this.predictionConsumer.disconnect().catch(noop),
      this.overrideConsumer.disconnect().catch(noop),
      this.producer.disconnect().catch(noop),
    ]);

    this.started = false;
    debug('FalseNegativeMonitor stopped.');
  }

  /* ------------------------------------------------------------ */
  /* Internal helpers                                             */
  /* ------------------------------------------------------------ */

  /**
   * Post an alert to Kafka.
   * @param {ReturnType<typeof computeStats>} stat
   * @returns {Promise<import('kafkajs').RecordMetadata[]>}
   * @private
   */
  async _emitAlert(stat) {
    const { modelVersion, falseNegativeRate, total } = stat;

    const message = {
      modelVersion,
      falseNegativeRate,
      totalSamples: total,
      threshold: this.config.monitoring.threshold,
      ts: Date.now(),
    };

    return pRetry(
      () =>
        this.producer.send({
          topic: this.config.topics.alert,
          messages: [
            {
              key: modelVersion,
              value: JSON.stringify(message),
            },
          ],
        }),
      {
        retries: 3,
        onFailedAttempt: (error) =>
          debug(
            'Alert send failed (%d). %o',
            error.attemptNumber,
            error,
          ),
      },
    );
  }
}

/* ------------------------------------------------------------------ */
/* Stream joining & stats                                             */
/* ------------------------------------------------------------------ */

/**
 * Perform an in-memory join between predictions and overrides within a
 * bounded time window. Uses a naive Map-based cache for demonstration.
 *
 * @param {Observable<Object>} prediction$
 * @param {Observable<Object>} override$
 * @returns {Observable<JoinedEvent>}
 */
function joinStreams(prediction$, override$) {
  // Maps messageId -> prediction/override
  const cache = new Map();

  return merge(prediction$, override$).pipe(
    map((event) => {
      const counterpart =
        cache.get(event.messageId) || /** @type {any} */ ({});
      let joined = null;

      if (
        event.type === 'prediction' &&
        counterpart.type === 'override'
      ) {
        joined = { prediction: event, override: counterpart };
        cache.delete(event.messageId);
      } else if (
        event.type === 'override' &&
        counterpart.type === 'prediction'
      ) {
        joined = { prediction: counterpart, override: event };
        cache.delete(event.messageId);
      } else {
        // Not joined yet – store and wait for counterpart
        cache.set(event.messageId, event);
      }

      return joined;
    }),
    filter(Boolean),
  );
}

/**
 * @typedef {Object} JoinedEvent
 * @property {PredictionEvent} prediction
 * @property {OverrideEvent}   override
 */

/**
 * Compute stats for a batch of joined events.
 */
function computeStats(batch) {
  if (!batch.length) return null;

  const modelVersion = batch[0].prediction.modelVersion;
  const total = batch.length;
  const falseNegatives = batch.filter(
    (e) => e.prediction.isToxic === false && e.override.isToxic === true,
  ).length;

  const falseNegativeRate = falseNegatives / total;

  return {
    modelVersion,
    total,
    falseNegatives,
    falseNegativeRate,
  };
}

/**
 * Record Prometheus metrics for the batch.
 * @param {ReturnType<typeof computeStats>} stat
 */
function recordMetrics(stat) {
  if (!stat) return;
  const { modelVersion, falseNegativeRate } = stat;
  fnRateGauge.set({ model_version: modelVersion }, falseNegativeRate);
}

/* ------------------------------------------------------------------ */
/* Validation helpers                                                 */
/* ------------------------------------------------------------------ */

/**
 * @typedef {Object} PredictionEvent
 * @property {'prediction'} type
 * @property {string} messageId
 * @property {string} modelVersion
 * @property {boolean} isToxic
 * @property {number} ts
 */
function isValidPrediction(obj) {
  return (
    obj &&
    obj.type === 'prediction' &&
    typeof obj.messageId === 'string' &&
    typeof obj.modelVersion === 'string' &&
    typeof obj.isToxic === 'boolean'
  );
}

/**
 * @typedef {Object} OverrideEvent
 * @property {'override'} type
 * @property {string} messageId
 * @property {boolean} isToxic
 * @property {number} ts
 */
function isValidOverride(obj) {
  return (
    obj &&
    obj.type === 'override' &&
    typeof obj.messageId === 'string' &&
    typeof obj.isToxic === 'boolean'
  );
}

/* ------------------------------------------------------------------ */
/* Deep merge helper                                                  */
/* ------------------------------------------------------------------ */

/**
 * Shallowish deep merge (only for plain objects). Keeps it light to
 * avoid pulling a heavy library for one call-site.
 */
function mergeDeep(target, source) {
  const out = { ...target };
  for (const [k, v] of Object.entries(source)) {
    out[k] =
      v && typeof v === 'object' && !Array.isArray(v)
        ? mergeDeep(target[k] || {}, v)
        : v;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Graceful shutdown                                                  */
/* ------------------------------------------------------------------ */

if (require.main === module) {
  // CLI entry-point
  const monitor = new FalseNegativeMonitor();

  const shutdown = async (signal) => {
    debug('Received %s – shutting down…', signal);
    try {
      await monitor.stop();
      // Expose metrics one last time if the scraper comes in
      console.log(await register.metrics());
    } finally {
      process.exit(0);
    }
  };

  ['SIGINT', 'SIGTERM', 'SIGQUIT'].forEach((sig) =>
    process.on(sig, () => shutdown(sig)),
  );

  monitor
    .start()
    .catch((err) => {
      debug('Failed to start monitor: %o', err);
      process.exit(1);
    });
}
```