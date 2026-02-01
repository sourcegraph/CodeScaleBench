```javascript
/* -----------------------------------------------------------------------------
   AgoraPulse: Real-Time Social Signal Intelligence
   File:        src/module_26.js
   Purpose:     Online Model-Drift & Fairness Monitor
   Author:      AgoraPulse Engineering
   -----------------------------------------------------------------------------
   This module listens to a Kafka topic that streams inference results coming
   from the model-serving tier. It computes online statistics over sliding
   windows and fires domain events when drift or fairness regressions are
   detected. The events are published back to Kafka for the Orchestration
   service to pick up and, if necessary, trigger automated retraining.

   Core Tech:
     • KafkaJS               – message transport
     • RxJS                  – reactive, back-pressure aware stream processing
     • prom-client           – metrics surfaced to Prometheus / Grafana
     • pino                  – structured, high-perf logger
     • uuid                  – generate unique IDs for outbound events
 ----------------------------------------------------------------------------- */

import { Kafka, logLevel as kafkaLogLevel } from 'kafkajs';
import { Subject, timer, from } from 'rxjs';
import {
  bufferTime,
  catchError,
  filter,
  mergeMap,
  tap,
} from 'rxjs/operators';
import { Counter, Gauge, register as promRegistry } from 'prom-client';
import pino from 'pino';
import { v4 as uuid } from 'uuid';

/* ------------------------------- Constants --------------------------------- */

const CONFIG = {
  kafka: {
    clientId: 'agorapulse.drift-monitor',
    brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
    groupId: 'drift-monitor-consumers',
    topicIn: 'model-serving.sentiment-scores.v1',
    topicOut: 'model-monitoring.events.v1',
    connectionTimeout: 30_000,
  },
  monitoring: {
    windowSizeMs: 5 * 60_000, // 5-minute windows
    baselineWindowMs: 60 * 60_000, // 1-hour baseline
    driftThreshold: 0.15, // Jensen-Shannon divergence threshold
    fairnessThreshold: 0.1, // difference in accuracy between groups
    emitIntervalMs: 60_000, // evaluate every minute
  },
};

/* -------------------------------- Logger ----------------------------------- */

const log = pino({
  name: 'drift-monitor',
  level: process.env.LOG_LEVEL ?? 'info',
});

/* ------------------------------ Kafka Init --------------------------------- */

const kafka = new Kafka({
  clientId: CONFIG.kafka.clientId,
  brokers: CONFIG.kafka.brokers,
  connectionTimeout: CONFIG.kafka.connectionTimeout,
  logLevel: kafkaLogLevel.NOTHING,
});

const consumer = kafka.consumer({ groupId: CONFIG.kafka.groupId });
const producer = kafka.producer();

/* ------------------------------ Prom Metrics -------------------------------- */

const driftEventsCounter = new Counter({
  name: 'agorapulse_drift_events_total',
  help: 'Number of drift events produced',
  labelNames: ['type'],
});

const divergenceGauge = new Gauge({
  name: 'agorapulse_divergence_current',
  help: 'Current Jensen-Shannon divergence value',
});

const fairnessGauge = new Gauge({
  name: 'agorapulse_fairness_gap_current',
  help: 'Current fairness gap value',
});

/* --------------------------- Helper Functions ------------------------------ */

/**
 * Compute Jensen-Shannon divergence between two discrete probability arrays.
 * @param {number[]} p - baseline distribution
 * @param {number[]} q - current distribution
 * @returns {number} - divergence in [0, 1]
 */
function jensenShannon(p, q) {
  const m = p.map((pi, i) => 0.5 * (pi + q[i]));
  const kl = (a, b) =>
    a.reduce((acc, ai, i) => (ai === 0 ? acc : acc + ai * Math.log2(ai / b[i])), 0);
  return 0.5 * kl(p, m) + 0.5 * kl(q, m);
}

/**
 * Creates a probability histogram from raw values.
 * @param {number[]} arr
 * @param {number} bins
 * @returns {number[]} length = bins, sums to 1
 */
function histogram(arr, bins = 20) {
  if (arr.length === 0) return Array(bins).fill(0);
  const min = Math.min(...arr);
  const max = Math.max(...arr);
  const width = (max - min) / bins || 1;
  const hist = Array(bins).fill(0);
  for (const x of arr) {
    const idx =
      width === 0 ? 0 : Math.min(bins - 1, Math.floor((x - min) / width));
    hist[idx] += 1;
  }
  return hist.map((c) => c / arr.length);
}

/**
 * Compute group fairness gap given accuracy per group.
 * @param {Object<string, number[]>} groupScores - map group -> [yTrue, yPred]
 * @returns {number} absolute gap between max and min accuracy
 */
function fairnessGap(groupScores) {
  const accuracies = Object.values(groupScores).map(([tp, n]) =>
    n === 0 ? 0 : tp / n
  );
  return Math.max(...accuracies) - Math.min(...accuracies);
}

/* ----------------------------- Drift Monitor ------------------------------ */

class DriftMonitor {
  constructor() {
    // Buffer for incoming scores: { score: number, label: number, group: string }
    this._rawScores$ = new Subject();

    // Sliding data stores
    this._baseline = [];
    this._currentWindow = [];

    // Group-wise counters for fairness metrics
    this._groupCountersBaseline = {};
    this._groupCountersCurrent = {};

    this._initializedBaseline = false;
  }

  /* ---------------------------- Public API ---------------------------- */

  async start() {
    await Promise.all([consumer.connect(), producer.connect()]);
    await consumer.subscribe({
      topic: CONFIG.kafka.topicIn,
      fromBeginning: false,
    });

    // 1. Stream Kafka messages into RxJS subject
    consumer.run({
      eachMessage: async ({ message }) => {
        try {
          const payload = JSON.parse(message.value.toString());
          const { sentiment, groundTruth, userDemographic } = payload;

          // Validate required fields
          if (
            typeof sentiment !== 'number' ||
            typeof groundTruth !== 'number' ||
            !userDemographic
          ) {
            log.warn({ payload }, 'Malformed message skipped');
            return;
          }

          this._rawScores$.next({
            score: sentiment,
            label: groundTruth,
            group: String(userDemographic),
          });
        } catch (err) {
          log.error({ err }, 'Failed to parse incoming message');
        }
      },
    });

    // 2. Windowed buffering
    this._rawScores$
      .pipe(
        bufferTime(CONFIG.monitoring.windowSizeMs),
        filter((batch) => batch.length > 0),
        mergeMap((batch) => from(this._processBatch(batch))),
        catchError((err, src) => {
          log.error({ err }, 'Error in processing pipeline');
          return src; // keep stream alive
        })
      )
      .subscribe();

    log.info('DriftMonitor started');
  }

  async stop() {
    await Promise.all([consumer.disconnect(), producer.disconnect()]);
    log.info('DriftMonitor stopped');
  }

  /* --------------------------- Core Pipeline --------------------------- */

  async _processBatch(batch) {
    if (!this._initializedBaseline) {
      this._updateBaseline(batch);
      return;
    }

    this._updateCurrent(batch);

    // At periodic emit intervals, evaluate metrics
    if (Date.now() % CONFIG.monitoring.emitIntervalMs < this._jitter()) {
      this._evaluateDrift();
      this._evaluateFairness();
      // Slide window
      this._currentWindow = [];
      this._groupCountersCurrent = {};
    }
  }

  _updateBaseline(batch) {
    this._baseline.push(...batch);
    for (const item of batch) {
      this._updateGroupCounters(this._groupCountersBaseline, item);
    }
    const baselineDuration =
      this._baseline[batch.length - 1]?.timestamp -
      this._baseline[0]?.timestamp;
    if (
      !this._initializedBaseline &&
      baselineDuration >= CONFIG.monitoring.baselineWindowMs
    ) {
      this._initializedBaseline = true;
      log.info(
        { size: this._baseline.length },
        'Baseline window initialized. Starting monitoring.'
      );
    }
  }

  _updateCurrent(batch) {
    this._currentWindow.push(...batch);
    for (const item of batch) {
      this._updateGroupCounters(this._groupCountersCurrent, item);
    }
  }

  _updateGroupCounters(counterObj, { label, score, group }) {
    const correct = Math.round(score) === Math.round(label) ? 1 : 0;
    const [tp = 0, total = 0] = counterObj[group] ?? [];
    counterObj[group] = [tp + correct, total + 1];
  }

  _evaluateDrift() {
    const baselineScores = this._baseline.map((d) => d.score);
    const currentScores = this._currentWindow.map((d) => d.score);
    if (baselineScores.length === 0 || currentScores.length === 0) {
      return;
    }

    const p = histogram(baselineScores);
    const q = histogram(currentScores);
    const divergence = jensenShannon(p, q);
    divergenceGauge.set(divergence);

    if (divergence > CONFIG.monitoring.driftThreshold) {
      log.warn({ divergence }, 'Drift detected');
      driftEventsCounter.inc({ type: 'drift' });
      this._emitEvent('MODEL_DRIFT', { divergence });
      // Re-establish baseline to adapt
      this._baseline = [...this._currentWindow];
      this._groupCountersBaseline = { ...this._groupCountersCurrent };
    }
  }

  _evaluateFairness() {
    const gap = fairnessGap(this._groupCountersCurrent);
    fairnessGauge.set(gap);
    if (gap > CONFIG.monitoring.fairnessThreshold) {
      log.warn({ gap }, 'Fairness regression detected');
      driftEventsCounter.inc({ type: 'fairness' });
      this._emitEvent('FAIRNESS_REGRESSION', { gap });
    }
  }

  _emitEvent(type, payload) {
    const event = {
      eventId: uuid(),
      type,
      timestamp: new Date().toISOString(),
      payload,
    };

    producer
      .send({
        topic: CONFIG.kafka.topicOut,
        messages: [{ value: JSON.stringify(event) }],
      })
      .catch((err) => log.error({ err }, 'Failed to publish event'));
  }

  _jitter() {
    return Math.floor(Math.random() * 1000); // ±1s to avoid thundering herd
  }
}

/* ------------------------ Start/Stop Lifecycle ----------------------------- */

const monitor = new DriftMonitor();

process.once('SIGINT', async () => {
  log.info('SIGINT received');
  await monitor.stop();
  process.exit(0);
});
process.once('SIGTERM', async () => {
  log.info('SIGTERM received');
  await monitor.stop();
  process.exit(0);
});

// Expose Prometheus metrics on :9464/metrics
import http from 'http';
const metricsServer = http.createServer(async (req, res) => {
  if (req.url === '/metrics') {
    res.setHeader('Content-Type', promRegistry.contentType);
    res.end(await promRegistry.metrics());
  } else {
    res.writeHead(404);
    res.end();
  }
});
metricsServer.listen(9464, () => log.info('Metrics server on :9464/metrics'));

// Fire it up!
monitor.start().catch((err) => {
  log.fatal({ err }, 'Failed to start DriftMonitor');
  process.exit(1);
});

export default monitor;
```