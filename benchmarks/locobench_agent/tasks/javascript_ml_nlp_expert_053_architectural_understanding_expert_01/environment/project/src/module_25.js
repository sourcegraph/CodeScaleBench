```javascript
/**
 * src/module_25.js
 *
 * Real-time sentiment inference and model-version routing.
 * --------------------------------------------------------
 * Consumes feature-engineered social events from Kafka,
 * discovers the currently-activated model version through
 * the internal Model Registry (MLflow façade), executes the
 * prediction via the correct model-serving endpoint, and
 * publishes the enriched event to the downstream topic.
 *
 * Architectural patterns demonstrated:
 *   • Strategy Pattern        – interchangeable model executors
 *   • Factory Pattern         – dynamic construction of strategies
 *   • Observer / Reactive     – RxJS pipeline over Kafka consumer
 *   • Circuit-Breaker pattern – graceful degradation & back-pressure
 *
 * External dependencies (declared in package.json):
 *   "kafkajs": "^2.2.4",
 *   "rxjs": "^7.8.1",
 *   "axios": "^1.6.0",
 *   "lru-cache": "^10.0.0",
 */

import { Kafka, logLevel } from 'kafkajs';
import axios from 'axios';
import LRU from 'lru-cache';
import {
  Subject,
  from,
  mergeMap,
  catchError,
  timeout,
  of,
  filter,
  tap,
} from 'rxjs';

/* -------------------------------------------------------------------------- */
/*                               Config Section                               */
/* -------------------------------------------------------------------------- */

const CONFIG = {
  kafka: {
    brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
    groupId: 'agorapulse.sentiment.router.v1',
    inputTopic: 'apulse.features.sentiment',
    outputTopic: 'apulse.inference.sentiment',
  },
  registry: {
    /* Base URL of internal MLflow façade */
    baseUrl: process.env.MODEL_REGISTRY_API ?? 'http://model-registry:5000/api',
    /* Refresh TTL for active model mapping (in ms) */
    ttlMs: 30_000,
  },
  serving: {
    requestTimeoutMs: 1_500, // per-inference timeout
    /* Hard fallback model if registry is unavailable */
    fallback: {
      name: 'sentiment-analysis',
      version: 'fallback',
      endpoint: 'http://sentiment-default:8080/predict',
    },
  },
};

/* -------------------------------------------------------------------------- */
/*                      Model Registry Abstraction Layer                      */
/* -------------------------------------------------------------------------- */

/**
 * ModelRegistryClient
 * Simple façade over internal Model Registry (MLflow REST).
 */
class ModelRegistryClient {
  constructor({ baseUrl, ttlMs }) {
    this.baseUrl = baseUrl;
    this.ttlMs = ttlMs;
    this.cache = new LRU({
      max: 128,
      ttl: ttlMs,
      // refreshing async fetches in background
      fetchMethod: async (key) => this.#fetchActiveVersion(key),
    });
  }

  /**
   * Resolve the currently active model deployment for a given task.
   * @param {string} taskName
   * @returns {Promise<ModelDescriptor>}
   */
  async getActiveModel(taskName) {
    try {
      return await this.cache.fetch(taskName);
    } catch (err) {
      console.error(
        '[ModelRegistry] Failed to resolve model. Using fallback.',
        err.message
      );
      return CONFIG.serving.fallback;
    }
  }

  /* -------------------------- Private helpers -------------------------- */

  /**
   * Actual HTTP call to registry. Private.
   * @param {string} taskName
   * @returns {Promise<ModelDescriptor>}
   */
  async #fetchActiveVersion(taskName) {
    const url = `${this.baseUrl}/v1/activeModel/${encodeURIComponent(
      taskName
    )}`;
    const { data } = await axios.get(url, { timeout: 1_000 });
    if (!data?.endpoint) {
      throw new Error(`Registry response malformed for task ${taskName}`);
    }
    return data;
  }
}

/* -------------------------------------------------------------------------- */
/*                        Strategy & Factory Implementations                  */
/* -------------------------------------------------------------------------- */

/**
 * Base interface for a ServingStrategy.
 * Each concrete strategy is bound to a fixed endpoint.
 */
class ServingStrategy {
  /**
   * @param {ModelDescriptor} descriptor
   */
  constructor(descriptor) {
    this.name = descriptor.name;
    this.version = descriptor.version;
    this.endpoint = descriptor.endpoint;
  }

  /**
   * Perform inference.
   * @param {object} payload – pre-computed feature vector
   * @returns {Promise<object>} model prediction result
   */
  async predict(payload) {
    throw new Error('predict() not implemented');
  }
}

/**
 * RESTServingStrategy – default REST/JSON POST executor
 */
class RESTServingStrategy extends ServingStrategy {
  async predict(payload) {
    const { data } = await axios.post(
      this.endpoint,
      payload,
      {
        timeout: CONFIG.serving.requestTimeoutMs,
        headers: {
          'Content-Type': 'application/json',
          'X-Model-Name': this.name,
          'X-Model-Version': this.version,
        },
      }
    );
    return data;
  }
}

/**
 * StrategyFactory – returns (and memoizes) a concrete executor
 */
class StrategyFactory {
  constructor() {
    this.cache = new Map();
  }

  /**
   * @param {ModelDescriptor} descriptor
   * @returns {ServingStrategy}
   */
  getStrategy(descriptor) {
    const key = `${descriptor.name}:${descriptor.version}`;
    if (this.cache.has(key)) return this.cache.get(key);

    // Future: plug different protocols (gRPC, WebSocket, wasm, etc.)
    const strategy = new RESTServingStrategy(descriptor);
    this.cache.set(key, strategy);
    return strategy;
  }
}

/* -------------------------------------------------------------------------- */
/*                         Kafka & Reactive Orchestration                     */
/* -------------------------------------------------------------------------- */

class SentimentRouterService {
  constructor() {
    this.kafka = new Kafka({
      clientId: 'agorapulse-sentiment-router',
      brokers: CONFIG.kafka.brokers,
      logLevel: logLevel.NOTHING,
    });

    this.consumer = this.kafka.consumer({ groupId: CONFIG.kafka.groupId });
    this.producer = this.kafka.producer({ idempotent: true });

    this.registry = new ModelRegistryClient(CONFIG.registry);
    this.strategyFactory = new StrategyFactory();

    this.event$ = new Subject();
  }

  /* --------------------------- Service Lifecycle --------------------------- */

  async init() {
    await this.consumer.connect();
    await this.producer.connect();

    await this.consumer.subscribe({ topic: CONFIG.kafka.inputTopic });

    this.consumer.run({
      eachMessage: async ({ message }) => {
        this.event$.next(message);
      },
    });

    this.#initPipeline();
    console.info('[SentimentRouter] Service initialized.');
  }

  async shutdown() {
    await Promise.all([
      this.consumer.disconnect(),
      this.producer.disconnect(),
    ]);
    console.info('[SentimentRouter] Service stopped.');
  }

  /* --------------------------- Internal Pipeline --------------------------- */

  #initPipeline() {
    this.event$
      .pipe(
        // Only process messages with value
        filter((msg) => Boolean(msg?.value)),
        // Decode & transform
        mergeMap((msg) => {
          let parsed;
          try {
            parsed = JSON.parse(msg.value.toString('utf8'));
          } catch (err) {
            console.warn('[Router] Malformed JSON, skipping message', err);
            return of(null);
          }
          return of({ parsed, meta: msg });
        }),
        filter(Boolean),
        // Attach model descriptor
        mergeMap(async ({ parsed, meta }) => {
          const modelDesc = await this.registry.getActiveModel(
            'sentiment-analysis'
          );
          return { parsed, meta, modelDesc };
        }),
        // Perform inference with timeout & error handling
        mergeMap(
          (enriched) =>
            from(
              this.strategyFactory
                .getStrategy(enriched.modelDesc)
                .predict(enriched.parsed.features)
            ).pipe(
              timeout({
                each: CONFIG.serving.requestTimeoutMs,
                with: () => {
                  throw new Error('Inference timeout');
                },
              }),
              catchError((err) => {
                console.error(
                  `[Router] Inference error (${err.message}).`,
                  'Payload will be dropped.'
                );
                return of(null);
              }),
              map((prediction) => ({ ...enriched, prediction }))
            ),
          4 // ↯ concurrency limit
        ),
        filter((res) => Boolean(res?.prediction)),
        // Publish downstream
        mergeMap(({ prediction, parsed }) =>
          this.producer
            .send({
              topic: CONFIG.kafka.outputTopic,
              messages: [
                {
                  key: parsed.message_id ?? null,
                  value: JSON.stringify({
                    ...parsed,
                    inference: prediction,
                    model_version: prediction?.model_version,
                    ts: Date.now(),
                  }),
                },
              ],
            })
            .then(() => null)
            .catch((err) =>
              console.error(
                '[Router] Failed to publish inference result.',
                err.message
              )
            )
        ),
        tap(() => {
          // simple metric logging
          process.stdout.write('.');
        })
      )
      .subscribe();
  }
}

/* -------------------------------------------------------------------------- */
/*                                  Startup                                   */
/* -------------------------------------------------------------------------- */

async function main() {
  const service = new SentimentRouterService();

  // Graceful shutdown via SIGTERM / SIGINT
  const stop = async () => {
    try {
      await service.shutdown();
      process.exit(0);
    } catch (err) {
      console.error('Error during shutdown', err);
      process.exit(1);
    }
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);

  // Start
  try {
    await service.init();
  } catch (err) {
    console.error('Fatal error during initialization', err);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Unhandled exception in main()', err);
  process.exit(1);
});

/* -------------------------------------------------------------------------- */
/*                              Type Declarations                             */
/* -------------------------------------------------------------------------- */

/**
 * @typedef {Object} ModelDescriptor
 * @property {string} name
 * @property {string} version
 * @property {string} endpoint
 */
```