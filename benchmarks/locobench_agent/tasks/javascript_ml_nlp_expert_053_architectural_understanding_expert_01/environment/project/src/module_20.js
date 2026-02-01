```javascript
/* eslint-disable no-console */
'use strict';

/*
 * AgoraPulse – Real-Time Social Signal Intelligence
 * ------------------------------------------------
 * Module: src/module_20.js
 * Name  : ModelDriftMonitor
 *
 * Purpose:
 *   Stream online model-quality metrics from Kafka, aggregate them inside
 *   sliding RxJS windows, detect statistically significant degradation, and
 *   raise a `model.retraining.trigger` event when thresholds are crossed.
 *
 *   The monitor is stateless and horizontally scalable—instances share a
 *   consumer-group and window their own slice of the stream. All parameters
 *   are environment-driven so Ops can tune behaviour without redeploying.
 *
 * Key Dependencies:
 *   kafkajs  – battle-tested Kafka driver
 *   rxjs     – functional reactive stream processing
 *   pino     – super-fast structured logger
 *   uuid     – key/trace id generation
 *   axios    – optional webhook integration (e.g. PagerDuty/Slack)
 */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, timer } from 'rxjs';
import {
  filter,
  map,
  windowTime,
  mergeMap,
  reduce,
  tap,
} from 'rxjs/operators';
import pino from 'pino';
import { v4 as uuidv4 } from 'uuid';
import axios from 'axios';

/* -------------------------------------------------------------------------- */
/*                                Configuration                               */
/* -------------------------------------------------------------------------- */

const cfg = {
  kafka: {
    brokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    clientId: process.env.KAFKA_CLIENT_ID || 'agorapulse-drift-monitor',
    groupId: process.env.KAFKA_GROUP_ID || 'agorapulse.drift.monitor',
    inboundTopic: process.env.KAFKA_INBOUND_TOPIC || 'model.predictions',
    outboundTopic: process.env.KAFKA_OUTBOUND_TOPIC || 'model.retraining.trigger',
  },
  window: {
    /* windowTime arguments: window size & sliding interval in ms */
    sizeMs: Number(process.env.WINDOW_SIZE_MS) || 60_000, // 1 minute
    slideMs: Number(process.env.WINDOW_SLIDE_MS) || 15_000, // 15-sec hop
  },
  thresholds: {
    minAccuracy: Number(process.env.MIN_ACCURACY) || 0.85,
    maxToxicFNRate: Number(process.env.MAX_TOXIC_FN_RATE) || 0.12,
  },
  alerting: {
    webhookUrl: process.env.ALERT_WEBHOOK_URL || '', // optional
  },
};

/* -------------------------------------------------------------------------- */
/*                                   Logger                                   */
/* -------------------------------------------------------------------------- */

const logger = pino({
  name: 'ModelDriftMonitor',
  level: process.env.LOG_LEVEL || 'info',
});

/* -------------------------------------------------------------------------- */
/*                              Helper Functions                              */
/* -------------------------------------------------------------------------- */

/**
 * Parse and validate a Kafka message.
 * @param {import('kafkajs').KafkaMessage} message
 * @returns {null|object}
 */
function deserializeMessage(message) {
  try {
    const data = JSON.parse(message.value.toString('utf8'));

    // minimal schema validation
    if (!data || !data.modelVersion || !data.prediction) {
      logger.debug({ data }, 'Dropping message – missing required fields');
      return null;
    }

    // label may be null until ground truth arrives
    return {
      modelVersion: String(data.modelVersion),
      prediction: data.prediction, // 'toxic' | 'non-toxic' | any label
      label: data.label ?? null,
      timestamp: data.timestamp || Date.now(),
      meta: data.meta || {},
    };
  } catch (err) {
    logger.warn({ err }, 'Failed to parse Kafka message – dropping');
    return null;
  }
}

/**
 * Compute online classification metrics from aggregated counters.
 */
function computeMetrics(counter) {
  const {
    TP = 0, TN = 0, FP = 0, FN = 0, toxicFN = 0,
  } = counter;

  const total = TP + TN + FP + FN;
  if (total === 0) return null;

  const accuracy = (TP + TN) / total;
  const precision = TP / (TP + FP || 1);
  const recall = TP / (TP + FN || 1);
  const toxicFNRate = toxicFN / (toxicFN + TP || 1);

  return { accuracy, precision, recall, toxicFNRate, total };
}

/**
 * Determine whether any metrics violate configured thresholds.
 */
function detectBreaches(metrics) {
  const breaches = [];

  if (metrics.accuracy < cfg.thresholds.minAccuracy) {
    breaches.push({
      type: 'accuracy_drop',
      value: metrics.accuracy,
      threshold: cfg.thresholds.minAccuracy,
      message: `Accuracy below ${cfg.thresholds.minAccuracy}`,
    });
  }

  if (metrics.toxicFNRate > cfg.thresholds.maxToxicFNRate) {
    breaches.push({
      type: 'toxic_false_negative_spike',
      value: metrics.toxicFNRate,
      threshold: cfg.thresholds.maxToxicFNRate,
      message: `Toxic FN rate above ${cfg.thresholds.maxToxicFNRate}`,
    });
  }

  return breaches;
}

/* -------------------------------------------------------------------------- */
/*                                Observables                                 */
/* -------------------------------------------------------------------------- */

/**
 * Convert a Kafka consumer into an RxJS subject.
 */
function createKafkaSubject({ kafka, topic, groupId }) {
  const subject = new Subject();

  const consumer = kafka.consumer({ groupId });

  consumer
    .connect()
    .then(() => consumer.subscribe({ topic, fromBeginning: false }))
    .then(() => {
      logger.info({ topic }, 'Kafka consumer subscribed');
      return consumer.run({
        eachMessage: async ({ message }) => {
          const parsed = deserializeMessage(message);
          if (parsed) subject.next(parsed);
        },
      });
    })
    .catch((err) => {
      logger.error({ err }, 'Kafka consumer error – terminating process');
      process.exit(1);
    });

  /* Graceful shutdown */
  const shutdown = async () => {
    logger.info('Shutting down Kafka consumer');
    await consumer.disconnect();
    subject.complete();
  };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);

  return subject;
}

/* -------------------------------------------------------------------------- */
/*                                Aggregation                                 */
/* -------------------------------------------------------------------------- */

/**
 * Build an RxJS pipeline that maintains per-model windows and produces
 * aggregation objects whenever a window closes.
 *
 * @param {Subject} inbound$
 * @param {import('kafkajs').Producer} producer
 */
function wireMetricPipeline(inbound$, producer) {
  inbound$
    /* group events into sliding time windows */
    .pipe(
      windowTime(cfg.window.sizeMs, cfg.window.slideMs),
      mergeMap((window$) =>
        window$.pipe(
          /* aggregate inside the window */
          reduce((acc, evt) => {
            const {
              modelVersion, prediction, label,
            } = evt;

            if (!acc[modelVersion]) {
              acc[modelVersion] = {
                modelVersion,
                TP: 0, TN: 0, FP: 0, FN: 0, toxicFN: 0,
              };
            }
            const modelCounter = acc[modelVersion];

            // Only count when ground truth is available
            if (label === null || label === undefined) {
              return acc;
            }

            const isPositive = label === 'toxic';
            const predictedPositive = prediction === 'toxic';

            if (predictedPositive && isPositive) modelCounter.TP += 1;
            else if (!predictedPositive && !isPositive) modelCounter.TN += 1;
            else if (predictedPositive && !isPositive) modelCounter.FP += 1;
            else if (!predictedPositive && isPositive) {
              modelCounter.FN += 1;
              modelCounter.toxicFN += 1; // additional tracker
            }

            return acc;
          }, {}),
        )),
      /* keep non-empty windows */
      filter((agg) => Object.keys(agg).length > 0),
      map((agg) => Object.values(agg)),
      mergeMap((modelAggs) => modelAggs),
    )
    .pipe(
      /* compute metrics */
      map((counter) => ({
        modelVersion: counter.modelVersion,
        metrics: computeMetrics(counter),
        counter,
        window: {
          sizeMs: cfg.window.sizeMs,
          slideMs: cfg.window.slideMs,
          closedAt: Date.now(),
        },
      })),
      /* filter out empty metric sets */
      filter((payload) => payload.metrics !== null),
      tap(async (payload) => {
        const { modelVersion, metrics } = payload;
        const breaches = detectBreaches(metrics);
        if (breaches.length === 0) return;

        const event = {
          id: uuidv4(),
          modelVersion,
          breaches,
          metrics,
          emittedAt: Date.now(),
        };

        try {
          await producer.send({
            topic: cfg.kafka.outboundTopic,
            messages: [
              {
                key: modelVersion,
                value: JSON.stringify(event),
                headers: {
                  'content-type': 'application/json',
                },
              },
            ],
          });
          logger.warn(
            { modelVersion, breaches },
            'Metric breach detected – retraining event emitted',
          );
        } catch (err) {
          logger.error({ err }, 'Failed to publish retraining event');
        }

        /* Optional: push to external webhook */
        if (cfg.alerting.webhookUrl) {
          axios.post(cfg.alerting.webhookUrl, event).catch((err) => {
            logger.error({ err }, 'Failed to push alert webhook');
          });
        }
      }),
    )
    .subscribe({
      error: (err) => logger.error({ err }, 'Metric pipeline error'),
    });
}

/* -------------------------------------------------------------------------- */
/*                                  Startup                                   */
/* -------------------------------------------------------------------------- */

async function main() {
  logger.info({ cfg }, 'Starting ModelDriftMonitor');

  const kafka = new Kafka({
    clientId: cfg.kafka.clientId,
    brokers: cfg.kafka.brokers,
    logLevel: logLevel.ERROR,
  });

  /* Producer is used for retraining triggers */
  const producer = kafka.producer();

  try {
    await producer.connect();
    logger.info('Kafka producer connected');
  } catch (err) {
    logger.error({ err }, 'Unable to connect Kafka producer – bailing out');
    process.exit(1);
  }

  /* Heartbeat timer (basic liveness metric) */
  const heartbeat = timer(0, 30_000).subscribe(() => {
    logger.debug('💓');
  });

  const kafkaSubject = createKafkaSubject({
    kafka,
    topic: cfg.kafka.inboundTopic,
    groupId: cfg.kafka.groupId,
  });

  wireMetricPipeline(kafkaSubject, producer);

  /* graceful producer shutdown */
  const shutdown = async () => {
    logger.info('Flushing Kafka producer & shutting down');
    heartbeat.unsubscribe();
    await producer.disconnect();
    process.exit(0);
  };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}

main().catch((err) => {
  logger.fatal({ err }, 'Fatal exception in drift monitor – exiting');
  process.exit(1);
});
```