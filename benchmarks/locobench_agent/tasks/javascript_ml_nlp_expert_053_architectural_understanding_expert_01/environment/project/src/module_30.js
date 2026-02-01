```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * -----------------------------------------------
 * Module: src/module_30.js
 *
 * Purpose
 * -------
 *  Streaming model-monitoring utility that continuously evaluates the
 *  performance of on-line model predictions against ground-truth labels
 *  (as they trickle in) and emits “drift” or “degradation” events when
 *  statistically significant deviations are detected.
 *
 *  – Consumes Kafka topics `model-predictions`   (model output)
 *                        `moderator-verdicts`   (human ground-truth proxy)
 *  – Correlates by `messageId`
 *  – Maintains sliding windows of recent performance metrics
 *  – Computes:
 *        • Accuracy
 *        • Population-Stability-Index (PSI) on probability buckets
 *  – Emits:
 *        • local Node.js events   (EventEmitter)
 *        • Kafka topic `model-alerts`
 *
 *  Technologies
 *  ------------
 *   • Node.js v18+
 *   • KafkaJS        : https://kafka.js.org
 *   • rxjs           : https://rxjs.dev
 *   • pino           : https://getpino.io
 */

import { EventEmitter } from 'node:events';
import { Kafka, logLevel as kafkaLogLevel } from 'kafkajs';
import {
  Subject,
  bufferTime,
  filter,
  map,
  merge,
  timeout,
  catchError,
} from 'rxjs';
import pino from 'pino';

/* -------------------------------------------------------------------------- */
/*                               Helper Types                                 */
/* -------------------------------------------------------------------------- */

/**
 * @typedef {Object} PredictionMessage
 * @property {string} messageId  – Unique identifier for the social-network event
 * @property {number} probability – Model probability for the positive class
 * @property {number} timestamp  – unix epoch ms
 */

/**
 * @typedef {Object} VerdictMessage
 * @property {string} messageId
 * @property {boolean} label     – Human-provided ground-truth
 * @property {number} timestamp
 */

/**
 * @typedef {Object} DriftMonitorConfig
 * @property {string} brokers              – Comma-separated list of Kafka brokers
 * @property {string} groupId              – Kafka consumer group
 * @property {number} accuracyThreshold    – Minimum acceptable accuracy (0-1)
 * @property {number} psiThreshold         – PSI threshold signalling drift
 * @property {number} slidingWindowMinutes – Window size for metrics
 * @property {number} publishIntervalSec   – How often to compute/display metrics
 * @property {string} alertTopic           – Kafka topic to publish alerts
 * @property {boolean} dryRun              – If true, alerts are only logged
 */

/* -------------------------------------------------------------------------- */
/*                               Default Config                               */
/* -------------------------------------------------------------------------- */

const DEFAULT_CONFIG = /** @type {DriftMonitorConfig} */ ({
  brokers: process.env.KAFKA_BROKERS ?? 'localhost:9092',
  groupId: process.env.KAFKA_GROUP_ID ?? 'agorapulse-model-monitor',
  accuracyThreshold: Number(process.env.ACCURACY_THRESHOLD ?? 0.82),
  psiThreshold: Number(process.env.PSI_THRESHOLD ?? 0.2),
  slidingWindowMinutes: Number(process.env.SLIDING_WINDOW_MIN ?? 10),
  publishIntervalSec: Number(process.env.PUBLISH_INTERVAL_SEC ?? 60),
  alertTopic: process.env.ALERT_TOPIC ?? 'model-alerts',
  dryRun: process.env.DRY_RUN === 'true',
});

/* -------------------------------------------------------------------------- */
/*                           Metric Utility Functions                         */
/* -------------------------------------------------------------------------- */

/**
 * Simple accuracy calculation.
 *
 * @param {Array<{pred:boolean, label:boolean}>} pairs
 * @returns {number}
 */
function computeAccuracy(pairs) {
  if (!pairs.length) return 1.0;
  const correct = pairs.reduce((acc, cur) => acc + Number(cur.pred === cur.label), 0);
  return correct / pairs.length;
}

/**
 * Population Stability Index (PSI) implementation for two probability
 * distributions (reference vs. current).
 *
 * @see https://www.listendata.com/2015/05/population-stability-index.html
 *
 * @param {number[]} referenceProbabilities
 * @param {number[]} currentProbabilities
 * @param {number}   [bins=10]
 * @returns {number}
 */
function computePSI(referenceProbabilities, currentProbabilities, bins = 10) {
  if (!referenceProbabilities.length || !currentProbabilities.length) return 0;

  const bucketEdges = [];
  for (let i = 1; i < bins; i += 1) {
    bucketEdges.push(i / bins);
  }

  const bucketize = (prob) =>
    bucketEdges.findIndex((edge) => prob < edge) + 1; // returns [1..bins]

  const refCount = new Array(bins).fill(0);
  for (const p of referenceProbabilities) refCount[bucketize(p) - 1]++;

  const curCount = new Array(bins).fill(0);
  for (const p of currentProbabilities) curCount[bucketize(p) - 1]++;

  const refTotal = referenceProbabilities.length;
  const curTotal = currentProbabilities.length;

  let psi = 0;
  for (let i = 0; i < bins; i += 1) {
    const refPct = Math.max(refCount[i] / refTotal, 1e-6); // avoid div/0
    const curPct = Math.max(curCount[i] / curTotal, 1e-6);
    psi += (curPct - refPct) * Math.log(curPct / refPct);
  }
  return psi;
}

/* -------------------------------------------------------------------------- */
/*                               Drift Monitor                                */
/* -------------------------------------------------------------------------- */

export class StreamingDriftMonitor extends EventEmitter {
  /**
   * @param {Partial<DriftMonitorConfig>} [cfg]
   */
  constructor(cfg = {}) {
    super();

    /** @type {DriftMonitorConfig} */
    this.cfg = { ...DEFAULT_CONFIG, ...cfg };

    this.log = pino({
      name: 'StreamingDriftMonitor',
      level: process.env.LOG_LEVEL ?? 'info',
    });

    this.kafka = new Kafka({
      clientId: 'agp-drift-monitor',
      brokers: this.cfg.brokers.split(','),
      logLevel: kafkaLogLevel.ERROR,
    });

    this.consumer = this.kafka.consumer({ groupId: this.cfg.groupId });
    this.producer = this.kafka.producer();

    // RxJS Subjects for incoming streams
    /** @type {Subject<PredictionMessage>} */
    this.prediction$ = new Subject();
    /** @type {Subject<VerdictMessage>} */
    this.verdict$ = new Subject();

    // Historical reference distribution to compare PSI against
    /** @type {number[]} */
    this.referenceDistribution = [];
  }

  /* ---------------------------------------------------------------------- */
  /*                              Public API                                */
  /* ---------------------------------------------------------------------- */

  /**
   * Establish Kafka connections, wire up streams, and start monitoring loop.
   */
  async start() {
    await Promise.all([this.consumer.connect(), this.producer.connect()]);

    // Handle graceful shutdown
    const shutdownSignals = ['SIGINT', 'SIGTERM'];
    shutdownSignals.forEach((sig) => {
      process.on(sig, async () => {
        this.log.warn({ sig }, 'Shutting down DriftMonitor…');
        await this.stop();
        process.exit(0);
      });
    });

    await this.consumer.subscribe({ topic: 'model-predictions', fromBeginning: false });
    await this.consumer.subscribe({ topic: 'moderator-verdicts', fromBeginning: false });

    // Consume messages and push to subjects
    void this.consumer.run({
      eachMessage: async ({ topic, message }) => {
        try {
          if (!message.value) return;
          const payload = JSON.parse(message.value.toString());
          if (topic === 'model-predictions') {
            this.prediction$.next(/** @type {PredictionMessage} */ (payload));
          } else if (topic === 'moderator-verdicts') {
            this.verdict$.next(/** @type {VerdictMessage} */ (payload));
          }
        } catch (err) {
          this.log.error({ err, topic }, 'Failed to parse Kafka message');
        }
      },
    });

    this._wireMetricsPipeline();
  }

  /**
   * Disconnect from Kafka and teardown observables.
   */
  async stop() {
    try {
      await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
      this.prediction$.complete();
      this.verdict$.complete();
    } catch (err) {
      this.log.error({ err }, 'Failed to cleanly shut down DriftMonitor');
    }
  }

  /* ---------------------------------------------------------------------- */
  /*                           Private – RxJS magic                         */
  /* ---------------------------------------------------------------------- */

  _wireMetricsPipeline() {
    // Sliding window bufferTime
    const windowSizeMs = this.cfg.slidingWindowMinutes * 60_000;
    const publishIntervalMs = this.cfg.publishIntervalSec * 1000;

    // Join predictions with their ground-truth label
    const joined$ = this.prediction$.pipe(
      // For each prediction, wait for its corresponding verdict
      map((pred) => {
        return this.verdict$
          .pipe(
            filter((verdict) => verdict.messageId === pred.messageId),
            map((verdict) => ({
              pred: pred.probability >= 0.5, // binary classification threshold
              probability: pred.probability,
              label: verdict.label,
            })),
            timeout({
              each: 30_000,
              with: () => {
                this.log.warn(
                  { messageId: pred.messageId },
                  'Timed-out waiting for verdict'
                );
                return []; // empty stream
              },
            }),
            catchError((err, caught) => {
              this.log.error({ err }, 'Error in verdict join');
              return caught;
            })
          )
          .toPromise();
      })
    );

    // Buffer results in time windows
    joined$
      .pipe(bufferTime(windowSizeMs, undefined, undefined, undefined))
      .subscribe({
        next: async (buffer) => {
          if (!buffer.length) return;

          // Flatten and remove empty promises
          const resolved = (await Promise.all(buffer)).filter(Boolean);

          const accuracy = computeAccuracy(resolved);
          const probs = resolved.map((r) => Number(r.probability));

          // Initialize reference distribution once
          if (this.referenceDistribution.length === 0) {
            this.referenceDistribution.push(...probs);
            this.log.info('Reference distribution initialized (%d items)', probs.length);
            return;
          }

          const psi = computePSI(this.referenceDistribution, probs);

          this._maybeEmitAlert({ accuracy, psi });

          // Periodically refresh reference distribution to last N windows
          if (Math.random() < 0.05) {
            // 5% chance each batch – simple reservoir sampling strategy
            this.referenceDistribution.splice(
              0,
              this.referenceDistribution.length,
              ...probs
            );
            this.log.debug('Reference distribution refreshed');
          }
        },
        error: (err) => {
          this.log.error({ err }, 'Error in metrics pipeline');
        },
      });

    // Periodic logging heartbeat
    mergedHeartbeat(this.prediction$, this.verdict$, publishIntervalMs).subscribe({
      next: (stats) => {
        this.log.debug(stats, 'Stream heartbeat');
      },
    });
  }

  /**
   * Check metrics against thresholds and emit alerts.
   *
   * @param {{accuracy:number, psi:number}} metrics
   */
  async _maybeEmitAlert(metrics) {
    const { accuracy, psi } = metrics;
    const accuracyBad = accuracy < this.cfg.accuracyThreshold;
    const psiBad = psi > this.cfg.psiThreshold;

    this.log.info(
      { accuracy: accuracy.toFixed(4), psi: psi.toFixed(4) },
      'Window metrics'
    );

    if (accuracyBad || psiBad) {
      const alert = {
        type: accuracyBad ? 'DEGRADATION' : 'DRIFT',
        accuracy,
        psi,
        occurredAt: Date.now(),
      };

      this.emit('alert', alert);

      if (this.cfg.dryRun) {
        this.log.warn({ alert }, '(dry-run) Would publish model alert');
        return;
      }

      try {
        await this.producer.send({
          topic: this.cfg.alertTopic,
          messages: [{ value: JSON.stringify(alert) }],
        });
        this.log.warn({ alert }, 'Model alert published');
      } catch (err) {
        this.log.error({ err, alert }, 'Failed to publish model alert');
      }
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                             Auxiliary utilities                            */
/* -------------------------------------------------------------------------- */

/**
 * Merge prediction & verdict streams just for heartbeat statistics.
 *
 * @param {Subject<PredictionMessage>} pred$
 * @param {Subject<VerdictMessage>} ver$
 * @param {number} everyMs
 * @returns {import('rxjs').Observable<{predCount:number,verCount:number}>}
 */
function mergedHeartbeat(pred$, ver$, everyMs) {
  let predCount = 0;
  let verCount = 0;

  pred$.subscribe(() => predCount++);
  ver$.subscribe(() => verCount++);

  return new Subject().pipe(
    // Use an interval to emit counts
    map(() => ({
      predCount,
      verCount,
    })),
    bufferTime(everyMs),
    map((buffer) => buffer.at(-1) ?? { predCount, verCount })
  );
}

/* -------------------------------------------------------------------------- */
/*                        Autostart when executed directly                    */
/* -------------------------------------------------------------------------- */

if (require.main === module) {
  const monitor = new StreamingDriftMonitor();
  monitor.start().catch((err) => {
    // eslint-disable-next-line no-console
    console.error('Failed to start StreamingDriftMonitor', err);
    process.exit(1);
  });
}
```