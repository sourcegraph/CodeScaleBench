```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module: Fairness Drift Monitor
 * File:   src/module_12.js
 *
 * Purpose:
 *   Listens to model-serving inference events coming from a Kafka topic,
 *   aggregates fairness metrics inside a sliding time-window, and emits an
 *   alert (Kafka message) whenever the absolute disparity between protected
 *   demographic groups exceeds a configurable threshold.  This keeps bias
 *   regressions in check and drives the automated retraining pipeline.
 *
 * Dependencies (peer / prod):
 *   - kafkajs        : battle-tested Kafka client for Node
 *   - rxjs           : functional reactive stream processing
 *   - lodash         : utility helpers (e.g. groupBy, meanBy)
 *   - pino           : fast structured logging
 *
 * ▓▓ NOTE ▓▓
 * This file is plain JavaScript (not TypeScript) to satisfy the
 * prompt requirements, yet uses modern ES2022+ syntax.
 */

import { Kafka, logLevel as kafkaLogLevel } from 'kafkajs';
import { fromEventPattern, timer } from 'rxjs';
import {
  bufferTime,
  filter,
  map,
  mergeMap,
  retry,
  tap,
  catchError,
} from 'rxjs/operators';
import _ from 'lodash';
import pino from 'pino';

/* -------------------------------------------------------------------------- */
/*                                Configuration                               */
/* -------------------------------------------------------------------------- */

const {
  KAFKA_BROKERS = 'localhost:9092',
  KAFKA_UI_COMPONENT = false,
  FAIRNESS_THRESHOLD = 0.10, // max allowed absolute disparity in TPR/FPR etc.
  DRIFT_WINDOW_MS = 5 * 60 * 1_000, // 5-min sliding window
  DRIFT_WINDOW_GRANULARITY_MS = 30 * 1_000, // stride length for buffer
} = process.env;

const MODEL_METRICS_TOPIC = 'model.monitoring.metrics';
const RETRAINING_REQUEST_TOPIC = 'model.retraining.request';

/* -------------------------------------------------------------------------- */
/*                                  Logging                                   */
/* -------------------------------------------------------------------------- */

const logger = pino({
  name: 'agorapulse-fairness-monitor',
  level: process.env.LOG_LEVEL || 'info',
  transport: KAFKA_UI_COMPONENT
    ? {
        // prettify logs when running in local dev / UI
        target: 'pino-pretty',
        options: { colorize: true },
      }
    : undefined,
});

/* -------------------------------------------------------------------------- */
/*                             Helper — Metrics                               */
/* -------------------------------------------------------------------------- */

/**
 * Compute fairness disparity between protected groups using True Positive Rate
 * (TPR) and False Positive Rate (FPR) differences.
 *
 * @param {Array<Object>} samples – list of inference results inside window
 *        Each sample schema:
 *        {
 *          demographic: 'male' | 'female' | ... | 'unknown',
 *          prediction: 0 | 1,
 *          actual:     0 | 1,
 *          timestamp:  number (ms)
 *        }
 * @returns {Object} statistics
 */
function computeDisparity(samples) {
  if (!samples.length) {
    return { tprDisparity: 0, fprDisparity: 0, detail: {} };
  }

  const byGroup = _.groupBy(samples, 'demographic');
  const groups = Object.keys(byGroup);
  const metrics = {};

  groups.forEach((group) => {
    const s = byGroup[group];
    /* True Positive Rate = TP / P */
    const positives = s.filter((x) => x.actual === 1);
    const truePos = positives.filter((x) => x.prediction === 1);
    const tpr = positives.length ? truePos.length / positives.length : 0;

    /* False Positive Rate = FP / N */
    const negatives = s.filter((x) => x.actual === 0);
    const falsePos = negatives.filter((x) => x.prediction === 1);
    const fpr = negatives.length ? falsePos.length / negatives.length : 0;

    metrics[group] = { tpr, fpr };
  });

  /* Compute max pairwise disparity */
  const tprValues = Object.values(metrics).map((m) => m.tpr);
  const fprValues = Object.values(metrics).map((m) => m.fpr);

  const tprDisparity = _.max(tprValues) - _.min(tprValues);
  const fprDisparity = _.max(fprValues) - _.min(fprValues);

  return { tprDisparity, fprDisparity, detail: metrics };
}

/* -------------------------------------------------------------------------- */
/*                          Kafka Client Bootstrap                            */
/* -------------------------------------------------------------------------- */

const kafka = new Kafka({
  clientId: 'agorapulse-fairness-monitor',
  brokers: KAFKA_BROKERS.split(','),
  logLevel: kafkaLogLevel.NOTHING,
});

const consumer = kafka.consumer({
  groupId: 'agorapulse.fairness.monitor.v1',
  sessionTimeout: 30_000,
});

const producer = kafka.producer();

/* -------------------------------------------------------------------------- */
/*                             Observables Setup                              */
/* -------------------------------------------------------------------------- */

/**
 * Convert Kafkajs message events into an RxJS stream of parsed objects
 */
function createMetricsStream() {
  return fromEventPattern(
    // addHandler
    (handler) =>
      consumer.run({
        autoCommit: true,
        eachMessage: async ({ message }) => {
          handler(message);
        },
      }),
    // removeHandler
    () => {
      // grace period; actual cleanup occurs via consumer.disconnect()
    }
  ).pipe(
    map((message) => {
      try {
        return JSON.parse(message.value.toString('utf8'));
      } catch (err) {
        logger.warn({ err }, 'Dropped malformed JSON payload');
        return null;
      }
    }),
    filter(Boolean) // remove nulls
  );
}

/* -------------------------------------------------------------------------- */
/*                              Monitor Logic                                 */
/* -------------------------------------------------------------------------- */

class FairnessDriftMonitor {
  #subscription; // RxJS Subscription

  async start() {
    await consumer.connect();
    await consumer.subscribe({ topic: MODEL_METRICS_TOPIC, fromBeginning: false });
    await producer.connect();

    const metrics$ = createMetricsStream().pipe(
      bufferTime(DRIFT_WINDOW_MS, DRIFT_WINDOW_GRANULARITY_MS),
      filter((windowSamples) => windowSamples.length > 0),
      map(computeDisparity),
      tap((stats) => {
        logger.debug(
          { tprDisparity: stats.tprDisparity, fprDisparity: stats.fprDisparity },
          'Window disparity computed'
        );
      }),
      filter(
        (stats) =>
          stats.tprDisparity > FAIRNESS_THRESHOLD ||
          stats.fprDisparity > FAIRNESS_THRESHOLD
      ),
      mergeMap((stats) => this.#emitRetrainingEvent(stats)),
      retry({
        delay: 1_000,
        resetOnSuccess: true,
      }),
      catchError((err, caught) => {
        logger.error({ err }, 'Stream processing fatal error, restarting');
        return caught;
      })
    );

    this.#subscription = metrics$.subscribe({
      next: () => {
        /* handled in mergeMap */
      },
      error: (err) => {
        logger.error({ err }, 'Subscription encountered stream error');
      },
      complete: () => {
        logger.info('Metrics stream completed');
      },
    });

    logger.info(
      {
        threshold: FAIRNESS_THRESHOLD,
        windowMs: DRIFT_WINDOW_MS,
      },
      'Fairness Drift Monitor started'
    );
  }

  async stop() {
    if (this.#subscription) {
      this.#subscription.unsubscribe();
    }
    await consumer.disconnect().catch((err) => logger.warn({ err }));
    await producer.disconnect().catch((err) => logger.warn({ err }));

    logger.info('Fairness Drift Monitor stopped');
  }

  /* ---------------------------------------------------------------------- */
  /*                         Internal Helper Methods                         */
  /* ---------------------------------------------------------------------- */

  /**
   * Publishes a retraining request to Kafka with the offending statistics
   * so that downstream orchestration kicks off an experiment/job.
   *
   * @param {Object} stats – disparity statistics
   * @returns {Promise<void>}
   */
  async #emitRetrainingEvent(stats) {
    const payload = {
      eventType: 'FAIRNESS_THRESHOLD_BREACH',
      triggeredAt: Date.now(),
      metadata: {
        tprDisparity: stats.tprDisparity,
        fprDisparity: stats.fprDisparity,
        detail: stats.detail,
        threshold: FAIRNESS_THRESHOLD,
        windowSizeMs: DRIFT_WINDOW_MS,
      },
    };

    try {
      await producer.send({
        topic: RETRAINING_REQUEST_TOPIC,
        messages: [{ value: JSON.stringify(payload) }],
      });

      logger.warn(
        { payload },
        '⚠️  Fairness drift detected — retraining event emitted'
      );
    } catch (err) {
      logger.error({ err }, 'Failed to publish retraining request');
      throw err; // bubble up for RxJS retry
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                            Module Entrypoint                               */
/* -------------------------------------------------------------------------- */

let monitor;

/**
 * When this module is run directly (`node module_12.js`) spin up the monitor.
 * In production use, the caller should import and manage lifecycle manually.
 */
async function main() {
  monitor = new FairnessDriftMonitor();
  await monitor.start();

  // Graceful shutdown
  const shutdown = async () => {
    logger.info('Received termination signal');
    await monitor.stop();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  // eslint-disable-next-line no-floating-promises
  main().catch((err) => {
    logger.fatal({ err }, 'Fatal startup error');
    process.exit(1);
  });
}

/* -------------------------------------------------------------------------- */
/*                              Public API                                    */
/* -------------------------------------------------------------------------- */

export default FairnessDriftMonitor;
export { computeDisparity };
```