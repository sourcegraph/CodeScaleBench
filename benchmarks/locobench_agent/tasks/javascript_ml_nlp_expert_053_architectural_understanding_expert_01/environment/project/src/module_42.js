```javascript
/**
 * AgoraPulse :: Real-Time Social Signal Intelligence
 * --------------------------------------------------
 * src/module_42.js
 *
 * This module implements an RxJS-powered, Kafka-backed monitor that keeps
 * track of model performance metrics (accuracy, bias, drift, etc.) emitted
 * by live model-serving micro-services.  When the aggregated statistics
 * violate configurable SLAs, the monitor publishes a
 * `model.retraining.requested` domain event so that the automated MLOps
 * pipeline can kick off a new hyper-parameter sweep and redeploy a candidate
 * model.
 *
 * Design notes:
 *  • Fully event-driven, leverages Kafka for transport.
 *  • Uses RxJS to aggregate rolling windows of metrics.
 *  • JSON schema validation via Ajv to guarantee contract safety.
 *  • Robust error handling & graceful shutdown hooks.
 *
 * Author: AgoraPulse Engineering
 */

import { Kafka, logLevel } from 'kafkajs';
import { Subject, timer, merge } from 'rxjs';
import {
  bufferTime,
  filter,
  map,
  tap,
  catchError,
} from 'rxjs/operators';
import Ajv from 'ajv';

// ---------------------------------------------------------------------------
// Constants / Config
// ---------------------------------------------------------------------------
const DEFAULT_CONFIG = Object.freeze({
  kafkaBrokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
  inTopicRegex: /^model\.metrics\..+$/i,
  outTopic: 'model.retraining.requested',
  bufferWindowMs: 30_000, // 30 seconds
  minimumSamples: 25,     // window must contain at least N samples
  thresholds: {
    accuracy: 0.85,           // lower bound
    toxicityFalseNegative: 0.02, // upper bound
    demographicParity: 0.75,  // lower bound fairness score
  },
});

// JSON Schema for incoming metric events
const METRIC_SCHEMA = {
  $id: 'https://agorapulse.ai/schemas/model-metric.json',
  type: 'object',
  required: [
    'modelName',
    'modelVersion',
    'timestamp',
    'metrics',
  ],
  properties: {
    modelName: { type: 'string', minLength: 1 },
    modelVersion: { type: 'string', minLength: 1 },
    timestamp: { type: 'string', format: 'date-time' },
    metrics: {
      type: 'object',
      required: ['accuracy', 'toxicityFalseNegative', 'demographicParity'],
      properties: {
        accuracy: { type: 'number', minimum: 0, maximum: 1 },
        toxicityFalseNegative: { type: 'number', minimum: 0, maximum: 1 },
        demographicParity: { type: 'number', minimum: 0, maximum: 1 },
      },
    },
  },
  additionalProperties: false,
};

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/**
 * Basic logger wrapper for consistent output.
 */
const logger = {
  info: (msg, meta) =>
    console.log(`[INFO] ${new Date().toISOString()} :: ${msg}`, meta || ''),
  warn: (msg, meta) =>
    console.warn(`[WARN] ${new Date().toISOString()} :: ${msg}`, meta || ''),
  error: (msg, meta) =>
    console.error(`[ERROR] ${new Date().toISOString()} :: ${msg}`, meta || ''),
};

// ---------------------------------------------------------------------------
// Main Monitor Class
// ---------------------------------------------------------------------------

export default class ModelPerformanceMonitor {
  /**
   * @param {Partial<typeof DEFAULT_CONFIG>} [config]
   */
  constructor(config = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this._ajv = new Ajv({ allErrors: true, strict: false }).addSchema(
      METRIC_SCHEMA,
      'modelMetric'
    );
    this._validate = this._ajv.getSchema('modelMetric');
    this._metrics$ = new Subject();
    this._isShuttingDown = false;

    this._kafka = new Kafka({
      clientId: 'agorapulse-model-monitor',
      brokers: this.config.kafkaBrokers,
      logLevel: logLevel.WARN,
    });

    this._consumer = this._kafka.consumer({
      groupId: 'model-monitor-group',
    });
    this._producer = this._kafka.producer({
      allowAutoTopicCreation: true,
    });
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  /**
   * Initialize Kafka connections and start streaming.
   */
  async start() {
    logger.info('Starting ModelPerformanceMonitor…');

    await Promise.all([this._consumer.connect(), this._producer.connect()]);

    await this._consumer.subscribe({
      topic: this.config.inTopicRegex,
      fromBeginning: false,
    });

    // Forward incoming Kafka messages into RxJS pipeline
    this._consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          const parsed = JSON.parse(message.value.toString('utf8'));
          if (!this._validate(parsed)) {
            logger.warn(`Schema validation failed for topic ${topic}`, {
              errors: this._ajv.errorsText(this._validate.errors),
            });
            return;
          }
          this._metrics$.next(parsed);
        } catch (err) {
          logger.error('Failed to parse metric message', { err });
        }
      },
    });

    // Hook termination signals
    ['SIGINT', 'SIGTERM', 'SIGQUIT'].forEach((sig) => {
      process.on(sig, async () => {
        if (!this._isShuttingDown) {
          this._isShuttingDown = true;
          logger.info(`Received ${sig}, shutting down gracefully…`);
          await this.stop();
          process.exit(0);
        }
      });
    });

    this._initStreamPipeline();
    logger.info('ModelPerformanceMonitor started.');
  }

  /**
   * Gracefully close Kafka connections.
   */
  async stop() {
    logger.info('Stopping ModelPerformanceMonitor…');
    await Promise.allSettled([
      this._consumer.disconnect(),
      this._producer.disconnect(),
    ]);
    this._metrics$.complete();
    logger.info('ModelPerformanceMonitor stopped.');
  }

  // -------------------------------------------------------------------------
  // Internal
  // -------------------------------------------------------------------------

  /**
   * Initialize RxJS aggregation pipeline.
   * Evaluates rolling windows & emits domain events when thresholds violated.
   */
  _initStreamPipeline() {
    const {
      bufferWindowMs,
      minimumSamples,
      thresholds: t,
      outTopic,
    } = this.config;

    this._metrics$
      .pipe(
        bufferTime(bufferWindowMs),
        filter((window) => window.length >= minimumSamples),
        map((window) => {
          // Aggregate metrics across the batch
          const acc = {
            accuracy: 0,
            toxicityFalseNegative: 0,
            demographicParity: 0,
          };
          window.forEach((evt) => {
            acc.accuracy += evt.metrics.accuracy;
            acc.toxicityFalseNegative +=
              evt.metrics.toxicityFalseNegative;
            acc.demographicParity += evt.metrics.demographicParity;
          });
          const n = window.length;
          return {
            accuracy: acc.accuracy / n,
            toxicityFalseNegative: acc.toxicityFalseNegative / n,
            demographicParity: acc.demographicParity / n,
            sampleCount: n,
            modelName: window[0].modelName,
            modelVersion: window[0].modelVersion,
          };
        }),
        filter(
          (agg) =>
            agg.accuracy < t.accuracy ||
            agg.toxicityFalseNegative > t.toxicityFalseNegative ||
            agg.demographicParity < t.demographicParity
        ),
        tap((agg) =>
          logger.warn(
            'Performance SLA breached, emitting retraining event…',
            agg
          )
        ),
        catchError((err, caught) => {
          logger.error('Stream pipeline error', { err });
          // Continue processing after error
          return caught;
        })
      )
      .subscribe(async (agg) => {
        const payload = {
          eventType: 'model.retraining.requested',
          createdAt: new Date().toISOString(),
          data: {
            modelName: agg.modelName,
            modelVersion: agg.modelVersion,
            triggerMetrics: agg,
          },
        };
        try {
          await this._producer.send({
            topic: outTopic,
            messages: [
              {
                key: `${agg.modelName}:${agg.modelVersion}`,
                value: JSON.stringify(payload),
              },
            ],
          });
          logger.info('Retraining event published', {
            key: payload.data.modelName,
          });
        } catch (err) {
          logger.error('Failed to publish retraining event', { err });
        }
      });
  }
}

// ---------------------------------------------------------------------------
// If the module is executed directly, start the monitor with default config.
// ---------------------------------------------------------------------------
if (require.main === module) {
  (async () => {
    const monitor = new ModelPerformanceMonitor();
    try {
      await monitor.start();
    } catch (err) {
      logger.error('Fatal error while starting monitor', { err });
      process.exit(1);
    }
  })();
}
```