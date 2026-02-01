```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 *
 * Module 16: AdaptiveModelSelector
 * --------------------------------
 * Dynamically chooses the best model version for online inference based on:
 *   • active A/B/N experiments
 *   • live performance metrics streamed back from the model-serving layer
 *   • manual overrides coming from feature-flag services (e.g., LaunchDarkly)
 *
 * Implements:
 *   • Strategy Pattern  – interchangeable selection algorithms
 *   • Observer Pattern  – RxJS observables for event streams
 *   • Factory Pattern   – pluggable strategy factory
 *
 * Dependencies:
 *   • rxjs                      – reactive streams
 *   • uuid                      – stable ids for selection sessions
 *   • @agorapulse/model-registry – shared internal sdk (stubbed if absent)
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

/* eslint-disable no-console */

import { Subject, merge, timer } from 'rxjs';
import {
  bufferTime,
  debounceTime,
  distinctUntilChanged,
  filter,
  map,
  shareReplay,
  switchMap,
  tap,
} from 'rxjs/operators';
import { v4 as uuid } from 'uuid';

// Lazy import to allow this module to be used in isolation (unit tests, etc.)
let ModelRegistry;
try {
  // eslint-disable-next-line global-require, import/no-extraneous-dependencies
  ModelRegistry = require('@agorapulse/model-registry').ModelRegistry;
} catch (err) {
  // Stub fallback for OSS usage / testing
  // eslint-disable-next-line no-console
  console.warn(
    '[AdaptiveModelSelector] @agorapulse/model-registry not found – using in-memory stub',
  );

  ModelRegistry = class InMemoryRegistry {
    constructor() {
      this._models = new Map(); // id → meta
    }

    async getModelMeta(id) {
      return this._models.get(id) || null;
    }

    async listModels(filterFn = () => true) {
      return Array.from(this._models.values()).filter(filterFn);
    }

    async registerModel(meta) {
      this._models.set(meta.id, meta);
    }
  };
}

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

/**
 * @typedef {Object} ModelPerformanceSample
 * @property {string} modelId          – unique model identifier
 * @property {number} latencyMs        – p95 latency in ms
 * @property {number} accuracy         – latest rolling accuracy
 * @property {number} throughput       – requests per second
 * @property {Date}   timestamp        – ISO time of the measurement
 */

/**
 * @typedef {Object} ModelSelectorConfig
 * @property {('bestAccuracy'|'lowestLatency'|'weightedRandom'|'roundRobin')} strategy
 * @property {boolean} [enableAutoRefresh]   – refresh model list periodically
 * @property {number}  [refreshIntervalSec]  – seconds between refreshes
 * @property {string[]} [allowedModels]      – whitelist of model ids
 */

// -----------------------------------------------------------------------------
// Strategy abstractions
// -----------------------------------------------------------------------------

class BaseSelectionStrategy {
  /**
   * @param {() => Promise<ModelPerformanceSample[]>} metricsProvider
   */
  constructor(metricsProvider) {
    this._metricsProvider = metricsProvider;
  }

  /**
   * Pick the next model id according to strategy.
   * @returns {Promise<string|null>}
   */
  // eslint-disable-next-line class-methods-use-this
  async pick() {
    throw new Error('pick() must be implemented by subclass');
  }
}

class BestAccuracyStrategy extends BaseSelectionStrategy {
  async pick() {
    const samples = await this._metricsProvider();
    const best = samples
      .filter((s) => Number.isFinite(s.accuracy))
      .sort((a, b) => b.accuracy - a.accuracy)[0];

    return best?.modelId ?? null;
  }
}

class LowestLatencyStrategy extends BaseSelectionStrategy {
  async pick() {
    const samples = await this._metricsProvider();
    const best = samples
      .filter((s) => Number.isFinite(s.latencyMs))
      .sort((a, b) => a.latencyMs - b.latencyMs)[0];

    return best?.modelId ?? null;
  }
}

class WeightedRandomStrategy extends BaseSelectionStrategy {
  async pick() {
    const samples = await this._metricsProvider();
    const total = samples.reduce((acc, s) => acc + (s.accuracy || 0), 0);
    if (!total) return null;

    let r = Math.random() * total;
    // eslint-disable-next-line no-restricted-syntax
    for (const s of samples) {
      r -= s.accuracy;
      if (r <= 0) return s.modelId;
    }
    return samples[0]?.modelId ?? null;
  }
}

class RoundRobinStrategy extends BaseSelectionStrategy {
  constructor(metricsProvider) {
    super(metricsProvider);
    this._index = 0;
  }

  async pick() {
    const samples = await this._metricsProvider();
    if (!samples.length) return null;
    const modelId = samples[this._index % samples.length].modelId;
    this._index += 1;
    return modelId;
  }
}

/**
 * Factory to build selection strategy from config.
 * @param {ModelSelectorConfig} cfg
 * @param {() => Promise<ModelPerformanceSample[]>} metricsProvider
 * @returns {BaseSelectionStrategy}
 */
function buildStrategy(cfg, metricsProvider) {
  switch (cfg.strategy) {
    case 'bestAccuracy':
      return new BestAccuracyStrategy(metricsProvider);
    case 'lowestLatency':
      return new LowestLatencyStrategy(metricsProvider);
    case 'weightedRandom':
      return new WeightedRandomStrategy(metricsProvider);
    case 'roundRobin':
    default:
      return new RoundRobinStrategy(metricsProvider);
  }
}

// -----------------------------------------------------------------------------
// Core selector
// -----------------------------------------------------------------------------

export class AdaptiveModelSelector {
  /**
   * @param {ModelRegistry} registry
   * @param {ModelSelectorConfig} cfg
   */
  constructor(registry, cfg) {
    this._registry = registry;
    this._cfg = {
      enableAutoRefresh: true,
      refreshIntervalSec: 30,
      allowedModels: undefined,
      ...cfg,
    };

    this._metrics$ = new Subject(); // next({ modelId, latencyMs, accuracy, ... })
    this._selectedModelId$ = new Subject();
    this._currentModelId = null;
    this._sessionId = uuid();

    this._strategist = buildStrategy(this._cfg, () =>
      this._latestMetrics(),
    );

    this._initStreams();
    if (this._cfg.enableAutoRefresh) {
      this._startPeriodicRefresh();
    }
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Push a new performance sample into the selector.
   * @param {ModelPerformanceSample} sample
   */
  ingestSample(sample) {
    if (
      this._cfg.allowedModels &&
      !this._cfg.allowedModels.includes(sample.modelId)
    ) {
      return; // ignore
    }
    this._metrics$.next(sample);
  }

  /**
   * Returns observable that emits whenever the selected model changes.
   * @returns {import('rxjs').Observable<string>}
   */
  get selection$() {
    return this._selectedModelId$.pipe(distinctUntilChanged(), shareReplay(1));
  }

  /**
   * Get id of the currently selected model synchronously.
   * Note: may be null if selection hasn't happened yet.
   * @returns {string|null}
   */
  get currentModelId() {
    return this._currentModelId;
  }

  /**
   * Manually trigger re-evaluation (e.g., after config change).
   * @returns {Promise<void>}
   */
  async reevaluate() {
    const next = await this._strategist.pick();
    if (next && next !== this._currentModelId) {
      this._publishSelection(next);
    }
  }

  /**
   * Clean up resources.
   */
  dispose() {
    this._metrics$.complete();
    this._selectedModelId$.complete();
    if (this._refreshSub) this._refreshSub.unsubscribe();
  }

  // ---------------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------------

  _initStreams() {
    // Buffer bursts of metrics → reevaluate every N seconds
    this._metrics$
      .pipe(
        bufferTime(1000), // 1 second bucket
        filter((bucket) => bucket.length > 0),
        tap((bucket) => {
          const latestByModel = bucket.reduce((acc, sample) => {
            acc[sample.modelId] = sample; // override – keep most recent
            return acc;
          }, {});
          Object.values(latestByModel).forEach((s) =>
            this._cacheMetric(s),
          );
        }),
        debounceTime(500), // wait for quiet period
        switchMap(() => this.reevaluate()),
      )
      .subscribe({
        error: (err) =>
          // eslint-disable-next-line no-console
          console.error('[AdaptiveModelSelector] stream error', err),
      });
  }

  _publishSelection(modelId) {
    this._currentModelId = modelId;
    this._selectedModelId$.next(modelId);
  }

  _metricsCache = new Map(); // modelId → last sample

  /**
   * Cache latest sample.
   * @param {ModelPerformanceSample} sample
   */
  _cacheMetric(sample) {
    this._metricsCache.set(sample.modelId, sample);
  }

  /**
   * Get latest metrics snapshot for selection.
   * @returns {Promise<ModelPerformanceSample[]>}
   */
  async _latestMetrics() {
    // we might supplement with registry latency if cache empty
    let samples = Array.from(this._metricsCache.values());

    if (samples.length === 0) {
      // cold start: fetch list of models, return placeholder metrics
      const modelMetas = await this._registry.listModels(
        (m) =>
          !this._cfg.allowedModels ||
          this._cfg.allowedModels.includes(m.id),
      );
      samples = modelMetas.map((meta) => ({
        modelId: meta.id,
        latencyMs: Number.POSITIVE_INFINITY,
        accuracy: 0,
        throughput: 0,
        timestamp: new Date(),
      }));
    }
    return samples;
  }

  _startPeriodicRefresh() {
    this._refreshSub = timer(
      this._cfg.refreshIntervalSec * 1000,
      this._cfg.refreshIntervalSec * 1000,
    )
      .pipe(
        tap(() => this.reevaluate().catch(() => {})),
        // On a refresh, also clear stale metrics >5min old
        tap(() => {
          const cutoff = Date.now() - 5 * 60 * 1000;
          for (const [id, sample] of this._metricsCache.entries()) {
            if (sample.timestamp.getTime() < cutoff) {
              this._metricsCache.delete(id);
            }
          }
        }),
      )
      .subscribe();
  }
}

// -----------------------------------------------------------------------------
// Convenience factory
// -----------------------------------------------------------------------------

/**
 * Build an AdaptiveModelSelector instance with defaults.
 * @param {Partial<ModelSelectorConfig>} [cfg]
 * @returns {AdaptiveModelSelector}
 */
export function createAdaptiveModelSelector(cfg = {}) {
  const registry = new ModelRegistry();
  const defaultCfg = {
    strategy: 'weightedRandom',
    enableAutoRefresh: true,
    refreshIntervalSec: 60,
  };
  return new AdaptiveModelSelector(registry, { ...defaultCfg, ...cfg });
}

// -----------------------------------------------------------------------------
// Example usage (guarded so it's not executed on import)
// -----------------------------------------------------------------------------
if (process.env.NODE_ENV !== 'test' && require.main === module) {
  (async () => {
    const selector = createAdaptiveModelSelector({
      strategy: 'bestAccuracy',
    });

    selector.selection$.subscribe((modelId) =>
      // eslint-disable-next-line no-console
      console.log(`[demo] selected model → ${modelId}`),
    );

    // Simulate live metrics
    const DEMO_MODELS = ['v1', 'v2', 'v3'];
    setInterval(() => {
      const sample = {
        modelId:
          DEMO_MODELS[Math.floor(Math.random() * DEMO_MODELS.length)],
        latencyMs: 50 + Math.random() * 100,
        accuracy: 0.8 + Math.random() * 0.15,
        throughput: 100 + Math.random() * 10,
        timestamp: new Date(),
      };
      selector.ingestSample(sample);
    }, 200);

    // Graceful shutdown
    process.on('SIGINT', () => {
      selector.dispose();
      // eslint-disable-next-line no-console
      console.log('\n[demo] shutdown');
      process.exit(0);
    });
  })();
}
```