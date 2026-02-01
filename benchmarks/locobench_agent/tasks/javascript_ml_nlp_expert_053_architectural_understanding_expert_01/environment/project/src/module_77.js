```javascript
'use strict';

import { Kafka, logLevel } from 'kafkajs';
import axios from 'axios';
import NodeCache from 'node-cache';
import { Subject } from 'rxjs';
import { filter, map, tap, catchError } from 'rxjs/operators';
import EventEmitter from 'events';

const DEFAULT_CACHE_TTL = 60 * 5; // 5 minutes

/**
 * ModelVersionManager manages model versions selection and updates,
 * interacts with MLflow Model Registry, caches metadata, and listens for updates via Kafka.
 */
class ModelVersionManager extends EventEmitter {
  /**
   * @param {Object} options
   * @param {string} options.mlflowBaseUrl - MLflow base URL
   * @param {string} options.kafkaBrokers - Comma-separated Kafka broker list
   * @param {string} [options.registryTopic='model.registry.events'] - Kafka topic for registry events
   * @param {number} [options.cacheTtl=DEFAULT_CACHE_TTL] - Cache TTL in seconds
   * @param {import('kafkajs').LogCreator} [options.kafkaLogger] - Optional Kafka logger
   */
  constructor(options) {
    super();
    const {
      mlflowBaseUrl,
      kafkaBrokers,
      registryTopic = 'model.registry.events',
      cacheTtl = DEFAULT_CACHE_TTL,
      kafkaLogger,
    } = options;

    if (!mlflowBaseUrl) throw new Error('mlflowBaseUrl is required');
    if (!kafkaBrokers) throw new Error('kafkaBrokers is required');

    this.mlflowBaseUrl = mlflowBaseUrl.replace(/\/+$/, '');
    this.registryTopic = registryTopic;
    this.cache = new NodeCache({ stdTTL: cacheTtl, checkperiod: cacheTtl / 2 });
    this.strategies = new Map();

    this.kafka = new Kafka({
      clientId: 'agorapulse-model-version-manager',
      brokers: kafkaBrokers.split(','),
      logLevel: logLevel.NOTHING,
      logCreator: kafkaLogger,
    });

    this.consumer = this.kafka.consumer({ groupId: 'model-version-manager-group' });
    this._initStream();
  }

  /**
   * Register a custom version selection strategy.
   * @param {string} name - strategy name
   * @param {(context:Object, candidates:Array<Object>) => Object} fn - selection function
   */
  registerStrategy(name, fn) {
    if (this.strategies.has(name)) throw new Error(`Strategy ${name} already registered`);
    this.strategies.set(name, fn);
  }

  /**
   * Pick model version for given context using specified strategy.
   * @param {Object} params
   * @param {string} params.modelName - Registered model name
   * @param {Object} params.context - Context metadata
   * @param {string} [params.strategy='latest'] - Strategy name
   * @returns {Promise<Object>} - Selected model version metadata
   */
  async pickModel({ modelName, context = {}, strategy = 'latest' }) {
    if (!modelName) throw new Error('modelName is required');

    const candidates = await this._fetchModelVersions(modelName);
    if (!candidates.length) throw new Error(`No versions found for model ${modelName}`);

    const selector = this.strategies.get(strategy) || this._defaultLatestStrategy;
    const chosen = selector(context, candidates);
    if (!chosen) throw new Error(`Strategy ${strategy} returned no version for model ${modelName}`);
    return chosen;
  }

  /** Gracefully shut down Kafka consumer. */
  async shutdown() {
    await this.consumer.disconnect();
    this.removeAllListeners();
    this.cache.close();
  }

  /* ---------------------- Private Helpers ---------------------- */

  /** Fetch versions from cache or MLflow REST API. */
  async _fetchModelVersions(modelName) {
    const cacheKey = `mlflow:model:${modelName}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    try {
      const res = await axios.get(
        `${this.mlflowBaseUrl}/api/2.0/mlflow/model-versions/search`,
        { params: { filter: `name='${modelName}'` }, timeout: 5000 }
      );
      const versions = (res.data?.model_versions || []).map(this._normalizeModelVersion);
      this.cache.set(cacheKey, versions);
      return versions;
    } catch (err) {
      this.emit('error', err);
      throw new Error(`Failed to fetch versions for ${modelName}: ${err.message}`);
    }
  }

  /** Normalize MLflow model version into app-friendly shape. */
  _normalizeModelVersion(v) {
    return {
      id: v.version,
      name: v.name,
      stage: v.current_stage,
      creationTimestamp: Number(v.creation_timestamp),
      user: v.user_id,
      tags: v.tags?.reduce((acc, t) => ({ ...acc, [t.key]: t.value }), {}) ?? {},
      runId: v.run_id,
    };
  }

  /** Default "latest" selection strategy. */
  _defaultLatestStrategy(_context, candidates) {
    return candidates.sort((a, b) => b.creationTimestamp - a.creationTimestamp)[0];
  }

  /** Initialize Kafka consumer and RxJS pipeline. */
  async _initStream() {
    await this.consumer.connect();
    await this.consumer.subscribe({ topic: this.registryTopic, fromBeginning: false });

    const message$ = new Subject();
    this.consumer.run({
      eachMessage: async ({ message }) => message$.next(message),
    });

    message$
      .pipe(
        map((msg) => {
          try {
            return JSON.parse(msg.value.toString());
          } catch (err) {
            this.emit('warn', `Invalid JSON: ${err.message}`);
            return null;
          }
        }),
        filter(Boolean),
        filter((evt) => ['MODEL_VERSION_UPDATED', 'MODEL_VERSION_CREATED'].includes(evt.type)),
        tap((evt) => this._invalidateCache(evt.payload.modelName)),
        catchError((err, caught) => {
          this.emit('error', err);
          return caught;
        })
      )
      .subscribe();
  }

  /** Invalidate cache entry for given model. */
  _invalidateCache(modelName) {
    const key = `mlflow:model:${modelName}`;
    if (this.cache.del(key)) this.emit('cacheInvalidated', modelName);
  }
}

/* ---------------------- Built-in Strategies ---------------------- */

/**
 * Create a traffic-split strategy:
 *   manager.registerStrategy('split50', createTrafficSplitStrategy([
 *     {percentage: 0.5, stage: 'Production'},
 *     {percentage: 0.5, stage: 'Staging'}
 *   ]));
 */
export function createTrafficSplitStrategy(splits) {
  const cumulative = [];
  let total = 0;
  for (const s of splits) {
    total += s.percentage;
    cumulative.push({ threshold: total, stage: s.stage });
  }
  if (Math.abs(total - 1) > 1e-6) throw new Error('Percentages must sum to 1');

  return (context = {}, candidates = []) => {
    const userId = context.userId;
    if (userId === undefined) throw new Error('traffic-split requires context.userId');

    const hash = _hashToFloat(userId);
    const bucket = cumulative.find((c) => hash < c.threshold);
    if (!bucket) return null;

    return candidates
      .filter((c) => c.stage.toLowerCase() === bucket.stage.toLowerCase())
      .sort((a, b) => b.creationTimestamp - a.creationTimestamp)[0];
  };
}

/** Hash a string/number to a deterministic float [0,1). */
function _hashToFloat(input) {
  const str = String(input);
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = (hash << 5) - hash + str.charCodeAt(i) | 0;
  return (Math.abs(hash) % 10000) / 10000;
}

export default ModelVersionManager;
```