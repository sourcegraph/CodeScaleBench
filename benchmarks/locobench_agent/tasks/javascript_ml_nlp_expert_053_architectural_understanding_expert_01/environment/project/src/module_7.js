```javascript
// File: src/module_7.js

/**
 * AgoraPulse – Real-Time Model Drift & Fairness Monitor
 *
 * This module continuously watches the predictions emitted by live models and
 * compares them with ground-truth feedback once it becomes available.  Using
 * RxJS we join the two asynchronous streams, compute windowed performance /
 * fairness metrics, and push alert events back to Kafka when thresholds are
 * crossed.
 *
 * Dependencies:
 *   - kafkajs          : battle-tested Kafka client for Node.js
 *   - rxjs             : reactive stream composition
 *   - ajv              : fast JSON schema validator
 *   - debug            : selective logging
 *
 * Environment Variables:
 *   KAFKA_BROKERS          – comma-separated list of brokers
 *   KAFKA_CLIENT_ID        – name of this service
 *   MONITOR_MODEL_ID       – modelId to monitor (optional, monitors all if unset)
 *   METRIC_WINDOW_SEC      – sliding window size in seconds (default: 300)
 *   ALERT_TOPIC            – topic to publish alerts to (default: model-alerts)
 *   PREDICTION_TOPIC       – topic with model predictions (default: model-predictions)
 *   GROUND_TRUTH_TOPIC     – topic with ground truth (default: moderation-outcomes)
 */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, merge, interval } from 'rxjs';
import {
  bufferTime,
  filter,
  map,
  groupBy,
  mergeMap,
  toArray,
  tap,
} from 'rxjs/operators';
import Ajv from 'ajv';
import debugLib from 'debug';

const log = debugLib('agorapulse:monitor');
const errorLog = debugLib('agorapulse:monitor:error');

/* ---------- Configuration ---------- */

const cfg = {
  kafka: {
    brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
    clientId: process.env.KAFKA_CLIENT_ID ?? 'agorapulse-model-drift-monitor',
  },
  topics: {
    predictions: process.env.PREDICTION_TOPIC ?? 'model-predictions',
    groundTruth: process.env.GROUND_TRUTH_TOPIC ?? 'moderation-outcomes',
    alerts: process.env.ALERT_TOPIC ?? 'model-alerts',
  },
  monitoring: {
    modelId: process.env.MONITOR_MODEL_ID, // optional
    windowSec: Number(process.env.METRIC_WINDOW_SEC) || 300, // 5 min default
  },
  thresholds: {
    minAccuracy: 0.84, // below this triggers accuracy alert
    maxFNR: 0.10, // false negative rate
    fairnessDelta: 0.08, // allowed delta between demographic groups
  },
};

/* ---------- Kafka plumbing ---------- */

const kafka = new Kafka({
  clientId: cfg.kafka.clientId,
  brokers: cfg.kafka.brokers,
  connectionTimeout: 15_000,
  authenticationTimeout: 10_000,
  reauthenticationThreshold: 10_000,
  logLevel: logLevel.NOTHING,
});

const producer = kafka.producer({ allowAutoTopicCreation: false });
const consumerPred = kafka.consumer({
  groupId: `${cfg.kafka.clientId}-predictions`,
});
const consumerTruth = kafka.consumer({
  groupId: `${cfg.kafka.clientId}-groundtruth`,
});

/* ---------- Schemas ---------- */

const ajv = new Ajv({ removeAdditional: true });

const predictionSchema = {
  type: 'object',
  required: ['messageId', 'modelId', 'prediction', 'prob', 'metadata', 'ts'],
  properties: {
    messageId: { type: 'string' },
    modelId: { type: 'string' },
    prediction: { type: 'string' },
    prob: { type: 'number' },
    metadata: { type: 'object' },
    ts: { type: 'string', format: 'date-time' },
  },
};

const groundTruthSchema = {
  type: 'object',
  required: ['messageId', 'truth', 'ts'],
  properties: {
    messageId: { type: 'string' },
    truth: { type: 'string' },
    ts: { type: 'string', format: 'date-time' },
  },
};

const validatePrediction = ajv.compile(predictionSchema);
const validateGroundTruth = ajv.compile(groundTruthSchema);

/* ---------- RxJS Subjects ---------- */

const predStream$ = new Subject();
const truthStream$ = new Subject();

/* ---------- Utility Functions ---------- */

function isValidPrediction(msg) {
  const ok = validatePrediction(msg);
  if (!ok) errorLog('Prediction schema error %o: %o', validatePrediction.errors, msg);
  return ok;
}
function isValidGroundTruth(msg) {
  const ok = validateGroundTruth(msg);
  if (!ok) errorLog('Ground truth schema error %o: %o', validateGroundTruth.errors, msg);
  return ok;
}

function accuracy(tp, fp, fn, tn) {
  return (tp + tn) / Math.max(tp + fp + fn + tn, 1);
}
function fnRate(fn, tp) {
  return fn / Math.max(fn + tp, 1);
}

/**
 * Computes fairness by measuring the maximum absolute delta in accuracy across
 * sensitive groups.
 */
function fairnessByGroup(records) {
  const grouped = {};
  for (const r of records) {
    const key = r.metadata?.demographic || 'unknown';
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(r);
  }

  const accByGroup = Object.entries(grouped).map(([group, recs]) => {
    let tp = 0,
      fp = 0,
      fn = 0,
      tn = 0;
    for (const r of recs) {
      const match = r.prediction === r.truth;
      if (match && r.truth === 'positive') tp += 1;
      else if (match && r.truth === 'negative') tn += 1;
      else if (!match && r.truth === 'positive') fn += 1;
      else if (!match && r.truth === 'negative') fp += 1;
    }
    return { group, acc: accuracy(tp, fp, fn, tn) };
  });

  if (accByGroup.length <= 1) return 0;
  const accVals = accByGroup.map((x) => x.acc);
  return Math.max(...accVals) - Math.min(...accVals);
}

/* ---------- Alert Publisher ---------- */

async function publishAlert(type, payload) {
  const event = {
    type,
    ts: new Date().toISOString(),
    ...payload,
  };
  try {
    await producer.send({
      topic: cfg.topics.alerts,
      messages: [{ value: JSON.stringify(event) }],
    });
    log('Published alert: %o', event);
  } catch (err) {
    errorLog('Unable to publish alert %o: %o', event, err);
  }
}

/* ---------- Metrics Computation Pipeline ---------- */

/**
 * We join predictions and ground-truth by messageId.  Any prediction that does
 * not obtain a ground-truth within `cfg.monitoring.windowSec` will be ignored.
 */
function buildMonitoringPipeline() {
  // Re-key streams by messageId
  const keyedPred$ = predStream$.pipe(
    filter(isValidPrediction),
    filter((p) => !cfg.monitoring.modelId || p.modelId === cfg.monitoring.modelId),
    map((p) => ['pred', p.messageId, p]),
  );

  const keyedTruth$ = truthStream$.pipe(
    filter(isValidGroundTruth),
    map((t) => ['truth', t.messageId, t]),
  );

  const joined$ = merge(keyedPred$, keyedTruth$).pipe(
    groupBy(([, id]) => id),
    mergeMap((group$) =>
      group$.pipe(
        toArray(),
        filter((items) => items.length === 2), // we have a pred + truth
        map((items) => {
          const pred = items.find((x) => x[0] === 'pred')[2];
          const truth = items.find((x) => x[0] === 'truth')[2];
          return { ...pred, truth: truth.truth };
        }),
      ),
    ),
  );

  // Windowed metrics
  joined$
    .pipe(
      bufferTime(cfg.monitoring.windowSec * 1000, undefined, Number.POSITIVE_INFINITY),
      filter((window) => window.length > 0),
      tap((window) => computeAndAlert(window)),
    )
    .subscribe();
}

function computeAndAlert(window) {
  let tp = 0,
    fp = 0,
    fn = 0,
    tn = 0;

  for (const r of window) {
    const positivePred = r.prediction === 'positive';
    const positiveTruth = r.truth === 'positive';
    if (positivePred && positiveTruth) tp += 1;
    else if (positivePred && !positiveTruth) fp += 1;
    else if (!positivePred && positiveTruth) fn += 1;
    else tn += 1;
  }

  const acc = accuracy(tp, fp, fn, tn);
  const fnr = fnRate(fn, tp);
  const fairnessGap = fairnessByGroup(window);

  log(
    'Window metrics (%d events) – acc=%d, fnr=%d, fairnessΔ=%d',
    window.length,
    acc.toFixed(4),
    fnr.toFixed(4),
    fairnessGap.toFixed(4),
  );

  if (acc < cfg.thresholds.minAccuracy) {
    publishAlert('ACCURACY_DROP', {
      modelId: cfg.monitoring.modelId,
      accuracy: acc,
      threshold: cfg.thresholds.minAccuracy,
    });
  }
  if (fnr > cfg.thresholds.maxFNR) {
    publishAlert('HIGH_FALSE_NEGATIVE_RATE', {
      modelId: cfg.monitoring.modelId,
      fnRate: fnr,
      threshold: cfg.thresholds.maxFNR,
    });
  }
  if (fairnessGap > cfg.thresholds.fairnessDelta) {
    publishAlert('FAIRNESS_GAP_EXCEEDED', {
      modelId: cfg.monitoring.modelId,
      fairnessGap,
      threshold: cfg.thresholds.fairnessDelta,
    });
  }
}

/* ---------- Kafka Consumer Wiring ---------- */

async function start() {
  await Promise.all([producer.connect(), consumerPred.connect(), consumerTruth.connect()]);
  await consumerPred.subscribe({ topic: cfg.topics.predictions, fromBeginning: false });
  await consumerTruth.subscribe({ topic: cfg.topics.groundTruth, fromBeginning: false });

  consumerPred.run({
    eachMessage: async ({ message }) => {
      try {
        const payload = JSON.parse(message.value.toString());
        predStream$.next(payload);
      } catch (err) {
        errorLog('Malformed prediction message: %o', err);
      }
    },
  });

  consumerTruth.run({
    eachMessage: async ({ message }) => {
      try {
        const payload = JSON.parse(message.value.toString());
        truthStream$.next(payload);
      } catch (err) {
        errorLog('Malformed ground truth message: %o', err);
      }
    },
  });

  buildMonitoringPipeline();

  // heartbeat so the process doesn't exit if all streams go quiet
  interval(60_000).subscribe(() => log('monitor alive'));
}

/* ---------- Graceful Shutdown ---------- */

async function shutdown(signal) {
  log('Received %s – shutting down...', signal);
  try {
    await Promise.all([
      consumerPred.disconnect(),
      consumerTruth.disconnect(),
      producer.disconnect(),
    ]);
    process.exit(0);
  } catch (err) {
    errorLog('Error during shutdown: %o', err);
    process.exit(1);
  }
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

/* ---------- Module Exports ---------- */

/**
 * start() is idempotent; calling it multiple times returns the same promise.
 */
let startedPromise;
export function startMonitoring() {
  if (!startedPromise) startedPromise = start().catch((err) => errorLog(err));
  return startedPromise;
}
```