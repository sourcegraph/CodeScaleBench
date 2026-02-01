```javascript
/**
 * src/module_28.js
 *
 * Real-time Model Monitoring & Automated Retraining Trigger
 * ---------------------------------------------------------
 * Listens to prediction and ground-truth feedback topics, computes rolling
 * performance / fairness metrics, and emits a “retraining.request” domain
 * event when thresholds are violated for a configurable number of windows.
 *
 * Part of: AgoraPulse – Real-Time Social Signal Intelligence (ml_nlp)
 *
 * Dependencies:
 *   - kafkajs                : Kafka client
 *   - rxjs                   : Reactive stream processing
 *   - lodash                 : Utility helpers
 *
 * Environment variables:
 *   KAFKA_BROKERS            : comma-separated broker list
 *   PREDICTION_TOPIC         : topic with model outputs
 *   GROUNDTRUTH_TOPIC        : topic with moderated ground-truth labels
 *   MONITOR_WINDOW_MS        : metrics window size (default 30_000ms)
 *   METRIC_THRESHOLD_ACCURACY: e.g. 0.80
 *   METRIC_THRESHOLD_FAIRNESS: e.g. 0.90
 *   VIOLATION_STREAK         : consecutive windows before triggering
 *   RETRAIN_TOPIC            : destination topic for retraining requests
 */

'use strict';

const { Kafka, logLevel }   = require('kafkajs');
const {
  Subject,
  merge,
  timer,
  EMPTY
}                            = require('rxjs');
const {
  bufferTime,
  filter,
  map,
  tap,
  catchError,
  switchMap
}                            = require('rxjs/operators');
const _                      = require('lodash');

// --------------------------------------
// Configuration & Constants
// --------------------------------------
const CFG = {
  brokers:           process.env.KAFKA_BROKERS?.split(',')        || ['localhost:9092'],
  predictionTopic:   process.env.PREDICTION_TOPIC                 || 'ml.predictions.sentiment',
  groundTruthTopic:  process.env.GROUNDTRUTH_TOPIC                || 'ml.groundtruth.sentiment',
  monitorWindowMs:  +process.env.MONITOR_WINDOW_MS                || 30_000,
  thresholdAccuracy:+process.env.METRIC_THRESHOLD_ACCURACY        || 0.80,
  thresholdFairness:+process.env.METRIC_THRESHOLD_FAIRNESS        || 0.90,
  violationStreak:  +process.env.VIOLATION_STREAK                 || 3,
  retrainTopic:      process.env.RETRAIN_TOPIC                    || 'ml.retraining.request'
};

// --------------------------------------
// Kafka Bootstrap
// --------------------------------------
const kafka = new Kafka({
  clientId: 'agorapulse-model-monitor',
  brokers: CFG.brokers,
  logLevel: logLevel.NOTHING
});
const consumer = kafka.consumer({ groupId: 'model-monitor-group' });
const producer = kafka.producer({ allowAutoTopicCreation: true });

// Wrap Kafka messages into RxJS Subjects
const prediction$   = new Subject();
const groundTruth$  = new Subject();

// --------------------------------------
// Utility: safe JSON parse
// --------------------------------------
function safeJSON (buffer) {
  try { return JSON.parse(buffer.toString()); }
  catch (err) {
    console.error('[ModelMonitor] Malformed JSON:', err);
    return null;
  }
}

// --------------------------------------
// Domain-specific Metrics
// --------------------------------------
/**
 * Compute accuracy for binary classes {pos, neg}
 */
function accuracy (records) {
  if (!records.length) return 1;
  const hits = records.filter(r => r.pred === r.label).length;
  return hits / records.length;
}

/**
 * Demographic parity ratio between majority & minority group
 * Returns 1 when perfectly fair, <1 when disparity exists.
 */
function fairnessRatio (records) {
  const byGroup = _.groupBy(records, r => r.group || 'unknown');
  const sizes   = _.mapValues(byGroup, g => g.length);
  if (_.size(sizes) < 2) return 1; // only one group present
  const majority = _.max(_.values(sizes));
  const minority = _.min(_.values(sizes));
  return minority / majority;
}

// --------------------------------------
// Stateful Violation Tracking
// --------------------------------------
let consecutiveViolations = 0;

/**
 * Evaluate metrics, update violation streak,
 * and possibly trigger retraining event.
 */
async function evaluateWindow (records) {
  if (!records.length) return;

  const acc  = accuracy(records);
  const fair = fairnessRatio(records);
  const violates =
        acc  < CFG.thresholdAccuracy ||
        fair < CFG.thresholdFairness;

  if (violates) consecutiveViolations++;
  else          consecutiveViolations = 0;

  console.log('[ModelMonitor] Window metrics:',
              { acc: acc.toFixed(3), fair: fair.toFixed(3),
                violates, streak: consecutiveViolations });

  if (consecutiveViolations >= CFG.violationStreak) {
    consecutiveViolations = 0; // reset after firing
    await emitRetrainingEvent({ acc, fair, sampleSize: records.length });
  }
}

/**
 * Publish a retraining request to Kafka.
 */
async function emitRetrainingEvent (payload) {
  const event = {
    type:  'RETRAINING_REQUESTED',
    ts:    Date.now(),
    model: 'sentiment-v2',
    cause: payload
  };

  try {
    await producer.send({
      topic: CFG.retrainTopic,
      messages: [{ key: 'sentiment', value: JSON.stringify(event) }]
    });
    console.warn('[ModelMonitor] 🔁  Retraining event dispatched:', event);
  } catch (err) {
    console.error('[ModelMonitor] Failed to emit retraining event:', err);
  }
}

// --------------------------------------
// Stream Wiring
// --------------------------------------
// Combine prediction & ground-truth streams by messageId
const joined$ = merge(prediction$, groundTruth$).pipe(
  // buffer per monitoring window
  bufferTime(CFG.monitorWindowMs),
  // transform buffer into evaluation records
  map(buffer => {
    const byId = buffer.reduce((acc, m) => {
      acc[m.id] = acc[m.id] || {};
      Object.assign(acc[m.id], m);
      return acc;
    }, {});

    // keep only completed records (pred + label)
    return Object.values(byId).filter(r => r.pred !== undefined && r.label !== undefined);
  }),
  tap(evaluateWindow),
  catchError(err => {
    console.error('[ModelMonitor] Stream error:', err);
    return EMPTY;
  })
);

// --------------------------------------
// Initialization
// --------------------------------------
async function init () {
  await Promise.all([consumer.connect(), producer.connect()]);

  await consumer.subscribe({ topic: CFG.predictionTopic,  fromBeginning: false });
  await consumer.subscribe({ topic: CFG.groundTruthTopic, fromBeginning: false });

  await consumer.run({
    autoCommit: true,
    eachMessage: async ({ topic, message }) => {
      const data = safeJSON(message.value);
      if (!data) return;

      // unify payload
      const envelope = {
        id:    data.messageId || data.id,
        group: data.demographicGroup || 'unknown'
      };

      if (topic === CFG.predictionTopic) {
        prediction$.next({ ...envelope, pred: data.prediction });
      } else {
        groundTruth$.next({ ...envelope, label: data.label });
      }
    }
  });

  // kick off evaluation stream
  joined$.subscribe();

  console.log('[ModelMonitor] ✅  Started with config:', CFG);
}

// Boot & handle fatal errors
init().catch(err => {
  console.error('[ModelMonitor] Initialization failure:', err);
  process.exit(1);
});

// Graceful shutdown
const shutdown = async () => {
  console.log('[ModelMonitor] Shutting down …');
  await Promise.allSettled([
    consumer.disconnect(),
    producer.disconnect()
  ]);
  process.exit(0);
};

process.on('SIGINT',  shutdown);
process.on('SIGTERM', shutdown);

module.exports = {
  // exposed for unit tests
  _private: {
    accuracy,
    fairnessRatio,
    evaluateWindow
  }
};
```