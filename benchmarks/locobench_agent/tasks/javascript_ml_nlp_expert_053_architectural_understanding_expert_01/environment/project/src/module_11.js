```javascript
'use strict';

/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * module_11.js
 *
 * ModelVersionResolver:
 * Listens to registry-emitted Kafka events about new model versions,
 * evaluates whether a candidate should be promoted to production, and
 * emits promotion / rejection events downstream. Implements a Strategy
 * pattern so promotion logic can be swapped at runtime (e.g. precision-
 * oriented vs. recall-oriented).
 *
 * Dependencies:
 *  - kafkajs         – Kafka client
 *  - axios           – HTTP client for Registry / ExperimentTracker
 *  - rxjs            – Reactive wrappers around Kafka streams
 *  - lodash          – Utility helpers
 *  - winston         – Structured logging
 *
 * Environment variables (with sane defaults):
 *  - REGISTRY_API_URL          – Base URL for Model Registry REST API
 *  - PROMOTION_METRIC          – Metric key (e.g. "f1", "auc", "latency")
 *  - PROMOTION_MIN_IMPROVEMENT – % improvement needed to promote
 *  - KAFKA_BROKERS             – Comma-sep broker list
 *  - KAFKA_CLIENT_ID           – Kafka client id
 */

require('dotenv').config();

const { Kafka, logLevel } = require('kafkajs');
const { Observable, fromEventPattern } = require('rxjs');
const { map, filter, catchError } = require('rxjs/operators');
const axios = require('axios').default;
const _ = require('lodash');
const winston = require('winston');
const EventEmitter = require('events');

// ---------------------------------------------------------------------------
// Configuration & Logger
// ---------------------------------------------------------------------------

const CONFIG = {
  registryApiUrl: process.env.REGISTRY_API_URL || 'http://registry:5000/api',
  promotionMetric: process.env.PROMOTION_METRIC || 'f1',
  promotionMinImprovement:
    Number(process.env.PROMOTION_MIN_IMPROVEMENT) || 0.02,
  kafka: {
    clientId: process.env.KAFKA_CLIENT_ID || 'agorapulse-model-resolver',
    brokers:
      process.env.KAFKA_BROKERS?.split(',') || ['kafka:9092', 'kafka:9093'],
    groupId: 'model-resolver-consumer',
    topics: {
      registryEvents: 'model.registry.events',
      resolverPromotions: 'model.resolver.promotions',
      resolverRejections: 'model.resolver.rejections',
    },
  },
};

const log = winston.createLogger({
  level: 'info',
  defaultMeta: { service: 'model-version-resolver' },
  transports: [new winston.transports.Console()],
});

// ---------------------------------------------------------------------------
// Helper Functions
// ---------------------------------------------------------------------------

/**
 * Fetch metrics for a model version from Registry REST API.
 * @param {string} modelId
 * @returns {Promise<Object>} – resolved with { metrics: {...}, metadata: {...} }
 */
async function fetchModelMetrics(modelId) {
  try {
    const { data } = await axios.get(
      `${CONFIG.registryApiUrl}/models/${modelId}/metrics`
    );
    return data;
  } catch (err) {
    log.error(`Failed to retrieve metrics for model ${modelId}: ${err.message}`);
    throw err;
  }
}

/**
 * Determine if candidate should be promoted over “current”.
 *
 * @param {Object} candidateMetrics
 * @param {Object} currentMetrics
 * @param {string} metricKey
 * @param {number} minImprovement – fractional threshold (e.g. 0.02 == 2%)
 */
function shouldPromote(
  candidateMetrics,
  currentMetrics,
  metricKey,
  minImprovement
) {
  const candidateScore = _.get(candidateMetrics, metricKey);
  const currentScore = _.get(currentMetrics, metricKey, 0);
  if (!_.isFinite(candidateScore)) return false;

  const relativeImprovement =
    currentScore === 0 ? 1 : (candidateScore - currentScore) / currentScore;

  return relativeImprovement >= minImprovement;
}

/**
 * Retry helper with exponential back-off.
 *
 * @template T
 * @param {() => Promise<T>} fn
 * @param {number} [attempts=5]
 * @param {number} [delayMs=250]
 * @returns {Promise<T>}
 */
async function retry(fn, attempts = 5, delayMs = 250) {
  let lastErr;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (attempt === attempts) break;
      await new Promise((r) => setTimeout(r, delayMs * 2 ** (attempt - 1)));
    }
  }
  throw lastErr;
}

// ---------------------------------------------------------------------------
// Kafka Reactive Utilities
// ---------------------------------------------------------------------------

/**
 * Wrap a Kafka consumer into an RxJS Observable.
 *
 * @param {import('kafkajs').Kafka} kafka
 * @param {string} topic
 * @returns {Observable<Object>} parsed JSON messages
 */
function createKafkaObservable(kafka, topic) {
  const consumer = kafka.consumer({ groupId: CONFIG.kafka.groupId });

  const connect = async () => {
    await consumer.connect();
    await consumer.subscribe({ topic, fromBeginning: false });
  };

  // Convert Kafka message handler to add/remove functions for RxJS
  return fromEventPattern(
    (handler) => {
      retry(connect)
        .then(() => consumer.run({ eachMessage: async ({ message }) => handler(message) }))
        .catch((err) => log.error(`Kafka connection failed: ${err.message}`));
    },
    () => consumer.disconnect()
  ).pipe(
    map((msg) => {
      try {
        return JSON.parse(msg.value.toString('utf-8'));
      } catch (err) {
        log.warn(`Invalid JSON in Kafka message: ${err.message}`);
        return null;
      }
    }),
    filter(Boolean)
  );
}

// ---------------------------------------------------------------------------
// Promotion Strategies
// ---------------------------------------------------------------------------

class PromotionStrategy {
  /**
   * Decide whether to promote candidateModelId over currentModelId.
   * @param {string} candidateModelId
   * @param {string} currentModelId
   * @returns {Promise<boolean>}
   */
  async shouldPromote(candidateModelId, currentModelId) {
    throw new Error('Strategy must implement shouldPromote');
  }
}

/**
 * Default strategy – compare metric key with minimum improvement threshold.
 */
class MetricImprovementStrategy extends PromotionStrategy {
  constructor(metricKey, minImprovement) {
    super();
    this.metricKey = metricKey;
    this.minImprovement = minImprovement;
  }

  async shouldPromote(candidateModelId, currentModelId) {
    const [candidate, current] = await Promise.all([
      fetchModelMetrics(candidateModelId),
      currentModelId ? fetchModelMetrics(currentModelId) : { metrics: {} },
    ]);

    return shouldPromote(
      candidate.metrics,
      current.metrics,
      this.metricKey,
      this.minImprovement
    );
  }
}

// ---------------------------------------------------------------------------
// ModelVersionResolver – orchestrates everything
// ---------------------------------------------------------------------------

class ModelVersionResolver extends EventEmitter {
  /**
   * @param {PromotionStrategy} strategy
   * @param {import('kafkajs').Kafka} kafka
   */
  constructor(strategy, kafka) {
    super();
    this.strategy = strategy;
    this.kafka = kafka;
    this.currentProductionModelId = null; // populated on startup
    this._producer = this.kafka.producer();
  }

  /**
   * Initialise producer & ingest observables.
   */
  async init() {
    await this._producer.connect();
    await this.loadCurrentProductionModelId();
    this.subscribeToRegistryEvents();
  }

  /**
   * Hit Registry API to determine which model is currently production.
   */
  async loadCurrentProductionModelId() {
    try {
      const { data } = await axios.get(
        `${CONFIG.registryApiUrl}/models/production`
      );
      this.currentProductionModelId = data.modelId || null;
      log.info(`Current production model: ${this.currentProductionModelId}`);
    } catch (err) {
      log.warn(
        `Could not determine production model from registry: ${err.message}`
      );
    }
  }

  /**
   * Emit promotion / rejection events to Kafka.
   * @param {string} eventTopic
   * @param {Object} payload
   */
  async emitKafkaEvent(eventTopic, payload) {
    try {
      await this._producer.send({
        topic: eventTopic,
        messages: [{ key: payload.modelId, value: JSON.stringify(payload) }],
      });
    } catch (err) {
      log.error(`Failed to emit Kafka event to ${eventTopic}: ${err.message}`);
    }
  }

  /**
   * Main stream subscription.
   */
  subscribeToRegistryEvents() {
    const kafkaObservable = createKafkaObservable(
      this.kafka,
      CONFIG.kafka.topics.registryEvents
    );

    kafkaObservable
      .pipe(
        filter((evt) => evt.eventType === 'MODEL_REGISTERED'),
        catchError((err, obs) => {
          log.error(`Observable error: ${err.message}`);
          return obs; // resume
        })
      )
      .subscribe({
        next: (evt) => this.handleCandidateModel(evt.payload),
        error: (err) => log.error(`Fatal resolver stream error: ${err.message}`),
      });
  }

  /**
   * Evaluate and potentially promote a candidate model.
   *
   * @param {{ modelId: string }} payload
   */
  async handleCandidateModel({ modelId }) {
    log.info(`Received candidate model ${modelId}`);
    try {
      const promote = await this.strategy.shouldPromote(
        modelId,
        this.currentProductionModelId
      );

      if (promote) {
        await this.promoteModel(modelId);
      } else {
        await this.rejectModel(modelId);
      }
    } catch (err) {
      log.error(`Error evaluating candidate ${modelId}: ${err.message}`);
    }
  }

  /**
   * Promote candidate model to production.
   *
   * @param {string} modelId
   */
  async promoteModel(modelId) {
    await this.emitKafkaEvent(CONFIG.kafka.topics.resolverPromotions, {
      modelId,
      promotedAt: new Date().toISOString(),
    });
    this.currentProductionModelId = modelId;
    log.info(`Promoted model ${modelId} to production`);
    this.emit('promoted', modelId);
  }

  /**
   * Reject candidate model.
   *
   * @param {string} modelId
   */
  async rejectModel(modelId) {
    await this.emitKafkaEvent(CONFIG.kafka.topics.resolverRejections, {
      modelId,
      rejectedAt: new Date().toISOString(),
    });
    log.info(`Rejected model ${modelId}`);
    this.emit('rejected', modelId);
  }

  /**
   * Graceful shutdown.
   */
  async shutdown() {
    await this._producer.disconnect();
  }
}

// ---------------------------------------------------------------------------
// Module API
// ---------------------------------------------------------------------------

/**
 * Start the ModelVersionResolver with default configuration.
 *
 * @returns {Promise<ModelVersionResolver>}
 */
async function startResolver() {
  const kafka = new Kafka({
    clientId: CONFIG.kafka.clientId,
    brokers: CONFIG.kafka.brokers,
    logLevel: logLevel.WARN,
  });

  const strategy = new MetricImprovementStrategy(
    CONFIG.promotionMetric,
    CONFIG.promotionMinImprovement
  );

  const resolver = new ModelVersionResolver(strategy, kafka);
  await resolver.init();

  // Handle termination signals
  const shutdown = async () => {
    log.info('Shutting down ModelVersionResolver...');
    await resolver.shutdown();
    process.exit(0);
  };
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);

  return resolver;
}

module.exports = {
  startResolver,
  PromotionStrategy,
  MetricImprovementStrategy,
  ModelVersionResolver,
};
```