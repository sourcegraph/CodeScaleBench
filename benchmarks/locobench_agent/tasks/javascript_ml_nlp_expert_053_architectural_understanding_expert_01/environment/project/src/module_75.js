```javascript
/***************************************************************************************************
 * AgoraPulse: Real-Time Social Signal Intelligence
 * -----------------------------------------------------------------------------------------------
 * File:        src/module_75.js
 * Module:      ConceptDriftMonitor
 *
 * Responsibilities
 * • Listens to prediction events coming from the model-serving layer via Apache Kafka
 * • Aggregates prediction labels over a sliding time window using RxJS streams
 * • Computes Jensen–Shannon divergence against a configurable baseline distribution
 * • Emits an alert when divergence crosses a configurable threshold
 * • Gradually adapts the baseline using an exponential moving average (EMA)
 *
 * Design Notes
 * • Fully event-driven; fits into the project’s Observer & Pipeline patterns
 * • Uses kafkajs for Kafka I/O and rxjs for in-process reactive composition
 * • Written in idiomatic, production-grade ES2022 JavaScript with rich JSDoc
 **************************************************************************************************/

import { Kafka, logLevel as KafkaLogLevel } from 'kafkajs';
import { Subject, bufferTime, map, filter, mergeMap, tap } from 'rxjs';
import { groupBy, sumBy } from 'lodash-es';

////////////////////////////////////////////////////////////////////////////////
// Utility Functions
////////////////////////////////////////////////////////////////////////////////

/**
 * Calculate Jensen-Shannon divergence between two categorical probability distributions.
 * Uses natural logarithm (base ‑ e).
 *
 * @template {Record<string, number>} T
 * @param {T} p - First probability distribution
 * @param {T} q - Second probability distribution
 * @returns {number} Divergence value in [0, 1] (0 = identical, 1 = maximal divergence)
 */
function jensenShannonDivergence(p, q) {
  const keys = new Set(Object.keys(p).concat(Object.keys(q)));
  const m = {};
  keys.forEach(k => {
    m[k] = 0.5 * ((p[k] ?? 0) + (q[k] ?? 0));
  });

  const kl = (a, b) =>
    Array.from(keys)
      .map(k => {
        if (a[k] === 0 || b[k] === 0) return 0;
        return a[k] * Math.log(a[k] / b[k]);
      })
      .reduce((acc, v) => acc + v, 0);

  return Math.sqrt(0.5 * kl(p, m) + 0.5 * kl(q, m));
}

/**
 * Transform a batch of messages into a normalized probability distribution of labels.
 *
 * @param {Array<{label:string}>} batch
 * @returns {Record<string, number>}
 */
function distributionFromBatch(batch) {
  if (batch.length === 0) return {};

  const counts = groupBy(batch, m => m.label);
  const total = batch.length;

  /** @type {Record<string,number>} */
  const dist = {};
  Object.entries(counts).forEach(([label, occurrences]) => {
    dist[label] = occurrences.length / total;
  });

  return dist;
}

/**
 * Perform an in-place exponential moving average update.
 *
 * @param {Record<string, number>} prev
 * @param {Record<string, number>} next
 * @param {number} alpha - Smoothing factor in (0, 1]
 */
function emaUpdate(prev, next, alpha) {
  const keys = new Set(Object.keys(prev).concat(Object.keys(next)));
  keys.forEach(k => {
    prev[k] = (1 - alpha) * (prev[k] ?? 0) + alpha * (next[k] ?? 0);
  });
}

/**
 * Safe JSON parse that returns null on failure.
 * @param {string} str
 * @returns {any|null}
 */
function safeJsonParse(str) {
  try {
    return JSON.parse(str);
  } catch {
    return null;
  }
}

////////////////////////////////////////////////////////////////////////////////
// ConceptDriftMonitor Class
////////////////////////////////////////////////////////////////////////////////

/**
 * @typedef {Object} ConceptDriftMonitorOptions
 * @property {import('kafkajs').KafkaConfig} kafkaConfig
 * @property {number} windowMs - Time window for aggregation
 * @property {number} divergenceThreshold - Alert threshold for JSD
 * @property {number} baselineEmaAlpha - EMA smoothing factor for baseline adaptation
 * @property {Record<string, number>} initialBaseline - Initial label distribution
 * @property {string} consumeTopic - Kafka topic containing prediction messages
 * @property {string} alertTopic - Kafka topic where drift alerts will be published
 * @property {Console} [logger] - Custom logger; defaults to console
 */

export class ConceptDriftMonitor {
  /**
   * @param {ConceptDriftMonitorOptions} opts
   */
  constructor(opts) {
    this._opts = {
      logger: console,
      ...opts,
    };

    // --- Validate configuration ------------------------------------------------
    if (this._opts.windowMs <= 0) {
      throw new Error('windowMs must be > 0');
    }
    if (
      this._opts.divergenceThreshold <= 0 ||
      this._opts.divergenceThreshold >= 1
    ) {
      throw new Error('divergenceThreshold must be in (0, 1)');
    }
    if (
      this._opts.baselineEmaAlpha <= 0 ||
      this._opts.baselineEmaAlpha > 1
    ) {
      throw new Error('baselineEmaAlpha must be in (0, 1]');
    }

    // --- Internal state --------------------------------------------------------
    /** @type {Record<string, number>} */
    this._baseline = { ...opts.initialBaseline };
    this._kafka = new Kafka({
      logLevel: KafkaLogLevel.ERROR,
      ...opts.kafkaConfig,
    });

    this._producer = this._kafka.producer();
    this._consumer = this._kafka.consumer({
      groupId: 'agorapulse-concept-drift-monitor',
    });

    /** @type {Subject<{label:string,timestamp:number}>} */
    this._stream$ = new Subject();

    // Bind
    this._handleBatch = this._handleBatch.bind(this);
  }

  ////////////////////////////////////////////////////////////////////////////
  // Public API
  ////////////////////////////////////////////////////////////////////////////

  /**
   * Initialize Kafka connections and start streaming.
   */
  async start() {
    const { logger } = this._opts;
    logger.info('[CDM] Starting ConceptDriftMonitor…');

    await this._producer.connect();
    await this._consumer.connect();
    await this._consumer.subscribe({
      topic: this._opts.consumeTopic,
      fromBeginning: false,
    });

    // Forward Kafka messages into RxJS pipeline
    await this._consumer.run({
      autoCommit: true,
      eachMessage: async ({ message }) => {
        const payload = safeJsonParse(message.value?.toString() ?? '');
        if (!payload || typeof payload.label !== 'string') return;

        // down-stream params (only what we need)
        this._stream$.next({
          label: payload.label,
          timestamp: Date.now(),
        });
      },
    });

    // Build reactive pipeline
    this._stream$
      .pipe(
        bufferTime(this._opts.windowMs),
        filter(batch => batch.length > 0),
        map(batch => ({
          batch,
          distribution: distributionFromBatch(batch),
        })),
        tap(this._handleBatch),
      )
      .subscribe({
        error: err => logger.error('[CDM] Stream error', err),
      });

    logger.info('[CDM] ConceptDriftMonitor started');
  }

  /**
   * Gracefully shut down Kafka connections and streams.
   */
  async stop() {
    const { logger } = this._opts;
    logger.info('[CDM] Stopping ConceptDriftMonitor…');

    // Complete RxJS stream to flush operators
    this._stream$.complete();
    await Promise.all([this._consumer.disconnect(), this._producer.disconnect()]);

    logger.info('[CDM] ConceptDriftMonitor stopped');
  }

  ////////////////////////////////////////////////////////////////////////////
  // Internal
  ////////////////////////////////////////////////////////////////////////////

  /**
   * Handle a buffered batch of messages.
   *
   * @param {{batch:Array<{label:string,timestamp:number}>, distribution:Record<string,number>}} param0
   * @private
   */
  async _handleBatch({ batch, distribution }) {
    const { logger } = this._opts;

    // --- Divergence ----------------------------------------------------------------
    const divergence = jensenShannonDivergence(distribution, this._baseline);

    logger.debug(
      `[CDM] JSD=${divergence.toFixed(4)} (threshold=${this._opts.divergenceThreshold})`,
    );

    if (divergence >= this._opts.divergenceThreshold) {
      logger.warn(
        `[CDM] Drift detected! JSD=${divergence.toFixed(4)} › threshold`,
      );
      await this._emitAlert(divergence, distribution);
    }

    // --- Update baseline -----------------------------------------------------------
    emaUpdate(this._baseline, distribution, this._opts.baselineEmaAlpha);
  }

  /**
   * Produce a drift alert message to the configured Kafka topic.
   *
   * @param {number} divergence
   * @param {Record<string, number>} currentDistribution
   * @private
   */
  async _emitAlert(divergence, currentDistribution) {
    const payload = {
      ts: Date.now(),
      divergence,
      currentDistribution,
      baseline: { ...this._baseline },
    };

    try {
      await this._producer.send({
        topic: this._opts.alertTopic,
        messages: [
          {
            key: 'concept-drift',
            value: JSON.stringify(payload),
          },
        ],
      });
    } catch (err) {
      this._opts.logger.error('[CDM] Failed to emit drift alert', err);
    }
  }
}

////////////////////////////////////////////////////////////////////////////////
// Example bootstrap (can be removed from production builds)
////////////////////////////////////////////////////////////////////////////////

if (require.main === module) {
  // Example CLI usage: node src/module_75.js
  // Loads config from environment variables for quick testing
  (async () => {
    const monitor = new ConceptDriftMonitor({
      kafkaConfig: {
        clientId: 'agorapulse-cdm-dev',
        brokers: (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
      },
      windowMs: Number(process.env.CDM_WINDOW_MS) || 30_000,
      divergenceThreshold:
        Number(process.env.CDM_THRESHOLD) || 0.25, // typical JSD threshold
      baselineEmaAlpha: Number(process.env.CDM_EMA_ALPHA) || 0.05,
      initialBaseline: {
        POS: 0.33,
        NEU: 0.34,
        NEG: 0.33,
      },
      consumeTopic: process.env.CDM_CONSUME_TOPIC || 'model_predictions',
      alertTopic: process.env.CDM_ALERT_TOPIC || 'model_monitoring_alerts',
    });

    // Graceful shutdown handlers
    const shutdown = async () => {
      await monitor.stop();
      process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);

    // Start service
    await monitor.start();
  })().catch(err => {
    // eslint-disable-next-line no-console
    console.error(err);
    process.exit(1);
  });
}
```