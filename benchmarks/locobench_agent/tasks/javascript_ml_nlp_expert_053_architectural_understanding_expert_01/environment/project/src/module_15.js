```javascript
/**
 * src/module_15.js
 *
 * Model Registry & Versioning utilities for AgoraPulse
 *
 * This module encapsulates all MLflow Model Registry interactions and exposes a
 * reactive façade that other services can subscribe to.  Whenever a new model
 * version is registered, promoted, or archived, a Kafka message is emitted and
 * an RxJS stream pushes the domain event to any in-process observers (e.g.,
 * monitoring dashboards, live A/B test orchestrators).
 *
 * The implementation purposefully keeps no hard dependency on the surrounding
 * runtime—everything is driven by configuration, dependency injection and
 * explicit lifecycle methods.  This makes the module easy to reuse in Lambda
 * functions, Nest services, or plain Node scripts.
 */

import axios from 'axios';
import { Subject } from 'rxjs';
import { Kafka, logLevel as KafkaLogLevel } from 'kafkajs';
import crypto from 'crypto';

/* -------------------------------------------------------------------------- */
/*                               Config Helpers                               */
/* -------------------------------------------------------------------------- */

/**
 * Basic environment/configuration resolution with sane defaults.
 * All runtime parameters can be overridden via env-vars or a config server.
 */
const config = {
  mlflow: {
    baseUrl: process.env.MLFLOW_BASE_URL || 'http://mlflow.registry.svc:5000/api/2.0',
    token: process.env.MLFLOW_TOKEN || '',
    requestTimeout: Number(process.env.MLFLOW_TIMEOUT_MS || 10_000),
  },
  kafka: {
    clientId: process.env.KAFKA_CLIENT_ID || 'agorapulse-model-service',
    brokers: (process.env.KAFKA_BROKERS || 'kafka:9092').split(','),
    ssl: Boolean(process.env.KAFKA_USE_SSL),
    sasl:
      process.env.KAFKA_SASL_USERNAME && process.env.KAFKA_SASL_PASSWORD
        ? {
            mechanism: process.env.KAFKA_SASL_MECHANISM || 'plain',
            username: process.env.KAFKA_SASL_USERNAME,
            password: process.env.KAFKA_SASL_PASSWORD,
          }
        : undefined,
    topic: process.env.KAFKA_MODEL_TOPIC || 'model.registry.events',
  },
};

/* -------------------------------------------------------------------------- */
/*                                 Constants                                  */
/* -------------------------------------------------------------------------- */

export const MODEL_EVENT_TYPES = Object.freeze({
  REGISTERED: 'MODEL_VERSION_REGISTERED',
  PROMOTED: 'MODEL_VERSION_PROMOTED',
  ARCHIVED: 'MODEL_VERSION_ARCHIVED',
  DELETED: 'MODEL_VERSION_DELETED',
});

/* -------------------------------------------------------------------------- */
/*                             Helper / Util Fns                              */
/* -------------------------------------------------------------------------- */

/**
 * Generates a deterministic hash from arbitrary JSON payloads.  Useful for
 * idempotency keys when interacting with external services that lack built-in
 * de-duplication safeguards.
 *
 * @param {unknown} payload - Data to hash.
 * @returns {string} A SHA-256 hash string.
 */
const payloadHash = (payload) =>
  crypto.createHash('sha256').update(JSON.stringify(payload)).digest('hex');

/* -------------------------------------------------------------------------- */
/*                           Model Registry Client                            */
/* -------------------------------------------------------------------------- */

/**
 * Thin, strongly-typed wrapper around the MLflow Registry REST API.
 */
export class ModelRegistryClient {
  /**
   * @param {object} opts
   * @param {string} opts.baseUrl
   * @param {number} opts.timeout
   * @param {string} [opts.token]
   */
  constructor({ baseUrl, timeout, token = '' }) {
    this._axios = axios.create({
      baseURL: baseUrl.replace(/\/+$/, ''), // Trim trailing slash
      timeout,
      headers: token
        ? {
            Authorization: `Bearer ${token}`,
          }
        : {},
    });
  }

  /* ------------------------------ API Methods ----------------------------- */

  async getModel(name) {
    const { data } = await this._axios.get(`/mlflow/registered-models/get`, {
      params: { name },
    });
    return data?.registered_model;
  }

  async createModel(name, description = '') {
    const { data } = await this._axios.post(`/mlflow/registered-models/create`, {
      name,
      description,
    });
    return data?.registered_model;
  }

  async registerVersion({ name, sourcePath, runId, tags = {} } = {}) {
    const { data } = await this._axios.post(
      `/mlflow/model-versions/create`,
      {
        name,
        source: sourcePath,
        run_id: runId,
        tags: Object.entries(tags).map(([k, v]) => ({ key: k, value: String(v) })),
      },
      {
        headers: {
          'Idempotency-Key': payloadHash({ name, sourcePath, runId }),
        },
      },
    );
    return data?.model_version;
  }

  async transitionStage({ name, version, stage = 'Staging' }) {
    const { data } = await this._axios.post(`/mlflow/model-versions/transition-stage`, {
      name,
      version,
      stage,
      archive_existing_versions: stage === 'Production',
    });
    return data?.model_version;
  }

  async deleteVersion({ name, version }) {
    await this._axios.delete(`/mlflow/model-versions/delete`, {
      data: { name, version },
    });
  }

  async getLatestVersion({ name, stage = 'Production' }) {
    const { data } = await this._axios.get(`/mlflow/registered-models/get-latest-versions`, {
      params: { name, stages: [stage] },
    });
    return data?.model_versions?.[0];
  }
}

/* -------------------------------------------------------------------------- */
/*                           Reactive Event Emitter                           */
/* -------------------------------------------------------------------------- */

/**
 * Provides both an in-memory RxJS stream and a Kafka producer for model events.
 */
export class ModelEventEmitter {
  /**
   * @param {import('kafkajs').Producer} kafkaProducer
   * @param {string} kafkaTopic
   */
  constructor(kafkaProducer, kafkaTopic) {
    this._kafkaProducer = kafkaProducer;
    this._topic = kafkaTopic;
    this._subject$ = new Subject();
  }

  /**
   * Observable anyone can subscribe to in-process.
   */
  get observable$() {
    return this._subject$.asObservable();
  }

  /**
   * Emits an event both locally and to Kafka.
   *
   * @param {string} type - Domain event type.
   * @param {object} payload - Arbitrary event payload.
   */
  async emit(type, payload) {
    const event = {
      type,
      timestamp: new Date().toISOString(),
      payload,
      id: crypto.randomUUID(),
    };

    // Emit in-memory for low-latency consumers
    this._subject$.next(event);

    // Fire-and-forget to Kafka
    try {
      await this._kafkaProducer.send({
        topic: this._topic,
        messages: [{ value: JSON.stringify(event) }],
      });
    } catch (err) {
      // Don’t crash the caller—just log & continue.
      // Proper observability would ship this to a centralized logger.
      // eslint-disable-next-line no-console
      console.error('[ModelEventEmitter] Failed to write to Kafka', err);
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                          Model Versioning Service                          */
/* -------------------------------------------------------------------------- */

/**
 * Orchestrates higher-level workflows such as auto-promotion and cleanup.
 */
export class ModelVersioningService {
  /**
   * @param {ModelRegistryClient} registryClient
   * @param {ModelEventEmitter} eventEmitter
   */
  constructor(registryClient, eventEmitter) {
    this._registry = registryClient;
    this._events = eventEmitter;
  }

  /**
   * Registers a new candidate model version, evaluates it against business
   * metrics, and, if it qualifies, auto-promotes it to the *Staging* stage.
   *
   * @param {object} opts
   * @param {string} opts.name
   * @param {string} opts.sourcePath
   * @param {string} opts.runId
   * @param {object} opts.metrics
   * @param {number} opts.metrics.f1
   * @param {number} opts.metrics.latencyMsP99
   * @param {object} [opts.tags]
   */
  async registerAndMaybePromote(opts) {
    const { name, sourcePath, runId, metrics, tags = {} } = opts;

    const version = await this._registry.registerVersion({
      name,
      sourcePath,
      runId,
      tags: {
        ...tags,
        ...Object.fromEntries(
          Object.entries(metrics).map(([k, v]) => [`metric.${k}`, v]),
        ),
      },
    });

    await this._events.emit(MODEL_EVENT_TYPES.REGISTERED, { name, version: version.version });

    // Business thresholds: we only auto-promote if F1 > 0.87 and latency < 50 ms
    if (metrics.f1 > 0.87 && metrics.latencyMsP99 < 50) {
      const promoted = await this._registry.transitionStage({
        name,
        version: version.version,
        stage: 'Staging',
      });

      await this._events.emit(MODEL_EVENT_TYPES.PROMOTED, {
        name,
        version: promoted.version,
        stage: 'Staging',
      });
    }

    return version;
  }

  /**
   * Archives an old model version and notifies downstream consumers.
   *
   * @param {string} name
   * @param {number|string} version
   */
  async archiveVersion(name, version) {
    await this._registry.transitionStage({ name, version, stage: 'Archived' });
    await this._events.emit(MODEL_EVENT_TYPES.ARCHIVED, { name, version });
  }

  /**
   * Deletes a model version outright. Use with caution—this is irreversible.
   *
   * @param {string} name
   * @param {number|string} version
   */
  async deleteVersion(name, version) {
    await this._registry.deleteVersion({ name, version });
    await this._events.emit(MODEL_EVENT_TYPES.DELETED, { name, version });
  }
}

/* -------------------------------------------------------------------------- */
/*                          Singleton Factory Helpers                         */
/* -------------------------------------------------------------------------- */

/**
 * Lazily-initialized Kafka producer so that unit tests can stub it out easily.
 */
let _kafkaProducerSingleton = null;
export async function getKafkaProducer() {
  if (_kafkaProducerSingleton) return _kafkaProducerSingleton;

  const kafka = new Kafka({
    clientId: config.kafka.clientId,
    brokers: config.kafka.brokers,
    logLevel: KafkaLogLevel.NOTHING,
    ssl: config.kafka.ssl,
    sasl: config.kafka.sasl,
  });

  _kafkaProducerSingleton = kafka.producer({
    allowAutoTopicCreation: true,
    idempotent: true,
    maxInFlightRequests: 1,
  });

  await _kafkaProducerSingleton.connect();
  return _kafkaProducerSingleton;
}

/**
 * Convenience bootstrap function that wires up the Registry client, Kafka
 * producer, and EventEmitter into a fully-operational service instance.
 *
 * @returns {Promise<ModelVersioningService>}
 */
export async function createModelVersioningService() {
  const producer = await getKafkaProducer();
  const emitter = new ModelEventEmitter(producer, config.kafka.topic);

  const registry = new ModelRegistryClient({
    baseUrl: config.mlflow.baseUrl,
    timeout: config.mlflow.requestTimeout,
    token: config.mlflow.token,
  });

  return new ModelVersioningService(registry, emitter);
}

/* -------------------------------------------------------------------------- */
/*                              Graceful Shutdown                             */
/* -------------------------------------------------------------------------- */

/**
 * Cleanly disconnects the Kafka producer.  Intended to be called from the
 * parent process inside an *unhandledRejection* / *SIGTERM* handler.
 */
export async function shutdown() {
  if (_kafkaProducerSingleton) {
    try {
      await _kafkaProducerSingleton.disconnect();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('[shutdown] Failed to close Kafka producer', err);
    }
  }
}
```