```javascript
/**
 * src/module_2.js
 *
 * High-throughput micro-pipeline that consumes raw social signals from Kafka,
 * performs on-the-fly feature engineering, retrieves the active model endpoint
 * from the Model Registry, invokes the model, and republishes enriched insights.
 *
 * The entire flow is implemented with RxJS to guarantee back-pressure handling,
 * fine-grained error isolation, and seamless composition with additional stages.
 *
 * NOTE: This file is plain JavaScript but uses JSDoc for IDE type-hints.
 */

/* ────────────────────────────────────────────────────────────────────────── */
/*                                Dependencies                               */
/* ────────────────────────────────────────────────────────────────────────── */

import { Kafka, logLevel } from 'kafkajs';
import axios from 'axios';
import { gzipSync, gunzipSync } from 'zlib';
import { Subject, from, EMPTY, of, merge } from 'rxjs';
import {
  map,
  mergeMap,
  catchError,
  bufferTime,
  filter,
  tap,
} from 'rxjs/operators';
import { v4 as uuidv4 } from 'uuid';
import * as promClient from 'prom-client';

/* ────────────────────────────────────────────────────────────────────────── */
/*                                Configuration                              */
/* ────────────────────────────────────────────────────────────────────────── */

const {
  KAFKA_BROKERS = 'localhost:9092',
  KAFKA_GROUP_ID = 'agorapulse-signal-pipeline',
  RAW_TOPIC = 'community.signals',
  INSIGHT_TOPIC = 'community.insights',
  MODEL_REGISTRY_URL = 'http://model-registry:5000',
  FEATURE_STORE_URL = 'http://feature-store:4000',
  METRIC_PUSHGATEWAY = '',
  NODE_ENV = 'development',
} = process.env;

const IS_DEV = NODE_ENV !== 'production';

/* ────────────────────────────────────────────────────────────────────────── */
/*                               Metrics setup                               */
/* ────────────────────────────────────────────────────────────────────────── */

const registry = new promClient.Registry();
promClient.collectDefaultMetrics({ register: registry });
const messagesConsumed = new promClient.Counter({
  name: 'signals_consumed_total',
  help: 'Total number of raw social signals consumed',
});
const messagesProduced = new promClient.Counter({
  name: 'insights_produced_total',
  help: 'Total number of processed insights produced',
});
const processingDuration = new promClient.Histogram({
  name: 'processing_duration_seconds',
  help: 'Time spent processing single message',
  buckets: [0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5],
});
registry.registerMetric(messagesConsumed);
registry.registerMetric(messagesProduced);
registry.registerMetric(processingDuration);

if (METRIC_PUSHGATEWAY) {
  const gateway = new promClient.Pushgateway(METRIC_PUSHGATEWAY, {}, registry);
  setInterval(() => {
    gateway.pushAdd({ jobName: 'signal_pipeline' }).catch((err) =>
      console.error('Failed to push metrics:', err),
    );
  }, 10_000);
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                        Auxiliary HTTP helper functions                    */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Generic REST GET with retry/backoff
 * @param {string} url
 * @param {number} [retries=3]
 * @returns {Promise<any>}
 */
async function httpGet(url, retries = 3) {
  try {
    const res = await axios.get(url, { timeout: 5_000 });
    return res.data;
  } catch (error) {
    if (retries === 0) throw error;
    await new Promise((r) => setTimeout(r, (4 - retries) * 200));
    return httpGet(url, retries - 1);
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Feature Store Client                            */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * FeatureStoreClient caches features in-memory for 60 seconds to avoid
 * redundant requests.
 */
class FeatureStoreClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    /** @type {Map<string, {expires: number, value: any}>} */
    this.cache = new Map();
  }

  /**
   * Retrieves features for the given user id.
   * @param {string} userId
   * @returns {Promise<Record<string, any>>}
   */
  async getUserFeatures(userId) {
    const now = Date.now();
    const hit = this.cache.get(userId);
    if (hit && hit.expires > now) return hit.value;

    const data = await httpGet(`${this.baseUrl}/users/${userId}`);
    this.cache.set(userId, { value: data, expires: now + 60_000 });
    return data;
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                            Model Registry Client                          */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Simple MLflow-like registry adapter that returns the best model endpoint
 * for a task (e.g., sentiment-analysis).
 */
class ModelRegistryClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
  }

  /**
   * Fetch the production model URL for a given task.
   * @param {string} task
   * @returns {Promise<string>} URL of model serving endpoint
   */
  async getProductionEndpoint(task) {
    const data = await httpGet(`${this.baseUrl}/registry/production/${task}`);
    if (!data || !data.endpoint) {
      throw new Error(`No production model found for task: ${task}`);
    }
    return data.endpoint;
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                             Model Serving Client                          */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Invokes the active model endpoint and returns predictions.
 */
class ModelServingClient {
  constructor(endpoint) {
    this.endpoint = endpoint;
  }

  /**
   * Predict using the model.
   * @param {Record<string, any>} payload
   * @returns {Promise<any>}
   */
  async predict(payload) {
    try {
      const res = await axios.post(this.endpoint, payload, {
        timeout: 3_000,
      });
      return res.data;
    } catch (error) {
      throw new Error(
        `Model invocation failed (${this.endpoint}): ${error.message}`,
      );
    }
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                              Kafka utilities                              */
/* ────────────────────────────────────────────────────────────────────────── */

/** @type {Kafka} */
const kafka = new Kafka({
  brokers: KAFKA_BROKERS.split(','),
  clientId: 'agorapulse-pipeline',
  logLevel: IS_DEV ? logLevel.DEBUG : logLevel.ERROR,
});

const consumer = kafka.consumer({ groupId: KAFKA_GROUP_ID });
const producer = kafka.producer();

/* ────────────────────────────────────────────────────────────────────────── */
/*                               Pipeline codec                              */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Decodes incoming Kafka value Buffer into a JavaScript object.
 * Values are gzip-compressed JSON strings.
 * @param {Buffer} buffer
 * @returns {any}
 */
function decodeMessage(buffer) {
  const json = gunzipSync(buffer).toString('utf8');
  return JSON.parse(json);
}

/**
 * Encodes outgoing object as Buffer.
 * @param {any} obj
 * @returns {Buffer}
 */
function encodeMessage(obj) {
  const json = JSON.stringify(obj);
  return gzipSync(Buffer.from(json, 'utf8'));
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                          Reactive Pipeline Assembly                       */
/* ────────────────────────────────────────────────────────────────────────── */

const input$ = new Subject();

/**
 * Bootstraps Kafka consumer and directs messages into the RxJS Subject.
 */
async function startKafkaConsumer() {
  await consumer.connect();
  await consumer.subscribe({ topic: RAW_TOPIC, fromBeginning: false });

  await consumer.run({
    autoCommit: true,
    eachMessage: async ({ message }) => {
      try {
        input$.next(message);
      } catch (err) {
        console.error('Failed to push message into stream:', err);
      }
    },
  });
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                            Main Processing Flow                           */
/* ────────────────────────────────────────────────────────────────────────── */

async function main() {
  // Wire external clients
  const featureStore = new FeatureStoreClient(FEATURE_STORE_URL);
  const registry = new ModelRegistryClient(MODEL_REGISTRY_URL);
  const sentimentEndpoint = await registry.getProductionEndpoint(
    'sentiment-analysis',
  );
  const modelClient = new ModelServingClient(sentimentEndpoint);

  // Connect Kafka producer
  await producer.connect();

  // Build reactive pipeline
  input$
    .pipe(
      // Decode Kafka message value
      map((msg) => {
        messagesConsumed.inc();
        return {
          key: msg.key?.toString('utf8'),
          value: decodeMessage(msg.value),
          ts: msg.timestamp,
        };
      }),

      // Enrich with user features
      mergeMap(async (event) => {
        const userFeatures = await featureStore.getUserFeatures(
          event.value.user_id,
        );
        return { ...event, features: userFeatures };
      }),

      // Call model
      mergeMap(async (event) => {
        const start = Date.now();
        const prediction = await modelClient.predict({
          text: event.value.text,
          features: event.features,
        });
        processingDuration.observe((Date.now() - start) / 1000);

        return {
          id: uuidv4(),
          user_id: event.value.user_id,
          text: event.value.text,
          prediction,
          ts: Date.now(),
        };
      }),

      // Batch results for throughput optimisation
      bufferTime(300), // 300ms windows
      filter((batch) => batch.length > 0),

      // Publish to Kafka
      mergeMap((batch) =>
        from(
          producer.send({
            topic: INSIGHT_TOPIC,
            messages: batch.map((insight) => ({
              key: insight.user_id,
              value: encodeMessage(insight),
            })),
          }),
        ).pipe(
          tap(() => {
            messagesProduced.inc(batch.length);
          }),
        ),
      ),

      // Error handling for each stage
      catchError((err, caught) => {
        console.error('Stream error:', err);
        // Swallow this message and continue with stream
        return caught;
      }),
    )
    .subscribe({
      error(err) {
        // Fatal: should never be reached due to catchError
        console.error('Fatal stream failure:', err);
        process.exit(1);
      },
    });

  console.info('Signal processing pipeline started.');
  await startKafkaConsumer();
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                                  Startup                                  */
/* ────────────────────────────────────────────────────────────────────────── */

main().catch((err) => {
  console.error('Pipeline initialization failed:', err);
  process.exit(1);
});

process.on('SIGTERM', async () => {
  console.info('Shutting down gracefully...');
  await consumer.disconnect();
  await producer.disconnect();
  process.exit(0);
});
```