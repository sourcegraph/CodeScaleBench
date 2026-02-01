```javascript
/**
 * src/module_4.js
 *
 * ModelPerformanceMonitor — watches real-time model-performance events coming
 * from Kafka, checks them against configurable thresholds, and emits
 * “retraining-requested” domain events when drift / fairness regressions are
 * detected.  Thresholds can be inspected and tuned at runtime via a tiny HTTP
 * API so on-call ML engineers can react without redeploying code.
 *
 * Dependencies (peer):
 *  – kafkajs
 *  – rxjs
 *  – express
 *  – lodash
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/*                                   Imports                                 */
/* ────────────────────────────────────────────────────────────────────────── */
const { Kafka }          = require('kafkajs');
const express            = require('express');
const { fromEventPattern } = require('rxjs');
const { map, filter, groupBy, mergeMap, bufferTime } = require('rxjs/operators');
const _                  = require('lodash');

/* ────────────────────────────────────────────────────────────────────────── */
/*                                   Config                                  */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Hard defaults in case nothing is provided via env or programmatic injection.
 * All numeric values are treated as “worse than or equal to”.
 */
const DEFAULT_THRESHOLDS = Object.freeze({
  accuracy:               0.80, // ≤ 80% triggers alert
  f1Score:                0.78,
  fairnessDisparity:      0.10, // ≥ 10% delta between groups triggers alert
  toxicityFalseNegatives: 20,   // ≥ 20 FN per minute triggers alert
});

/* Kafka topic names */
const METRICS_TOPIC    = process.env.METRICS_TOPIC    || 'model-metrics';
const RETRAIN_TOPIC    = process.env.RETRAIN_TOPIC    || 'model-retraining-requests';

/* ────────────────────────────────────────────────────────────────────────── */
/*                          ModelPerformanceMonitor                          */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * @typedef {Object} MetricEvent
 * @property {string} modelId          - Unique identifier of the model
 * @property {string} version          - Version (semver or hash) of the model
 * @property {number} accuracy
 * @property {number} f1Score
 * @property {number} fairnessDisparity
 * @property {number} toxicityFalseNegatives
 * @property {number} ts               - Event timestamp (epoch millis)
 */

class ModelPerformanceMonitor {
  /**
   * @param {Object}   kafkaCfg
   * @param {string[]} kafkaCfg.brokers
   * @param {string}   [kafkaCfg.clientId='agorapulse-monitor']
   * @param {Object}   [thresholdOverrides]
   */
  constructor (kafkaCfg, thresholdOverrides = {}) {
    this._thresholds = { ...DEFAULT_THRESHOLDS, ...thresholdOverrides };

    const cfg = {
      clientId: kafkaCfg.clientId || 'agorapulse-monitor',
      brokers : kafkaCfg.brokers,
    };

    this.kafka            = new Kafka(cfg);
    this.consumer         = this.kafka.consumer({ groupId: `${cfg.clientId}-grp` });
    this.producer         = this.kafka.producer();
    this._expressApp      = express();
    this._server          = null;
    this._isStarted       = false;

    this._setupHttpApi();
  }

  /* ────────────────────────────── Public API ───────────────────────────── */

  /**
   * Begin consuming metrics and evaluating them.
   */
  async start () {
    if (this._isStarted) return;

    await this.producer.connect();
    await this.consumer.connect();
    await this.consumer.subscribe({ topic: METRICS_TOPIC, fromBeginning: false });

    // Wrap kafka consumer run loop so we can expose it as an RxJS observable.
    const addHandler = handler => this.consumer.run({
      eachMessage: async ({ message }) => handler(message),
    });
    const removeHandler = () => {
      /* kafkajs does not support removing handler individually */
    };

    const observable$ = fromEventPattern(
      addHandler,
      removeHandler,
      /** @returns {MetricEvent} */
      (raw) => {
        try {
          return JSON.parse(raw.value.toString('utf8'));
        } catch (err) {
          console.error('[monitor] JSON parse error:', err);
          return null;
        }
      },
    ).pipe(filter(Boolean));

    this._wireEvaluationPipeline(observable$);

    // Start HTTP server
    const PORT = process.env.MONITOR_PORT || 5090;
    this._server = this._expressApp.listen(PORT, () =>
      console.info(`[monitor] Threshold API listening on :${PORT}`),
    );

    this._isStarted = true;
    console.info('[monitor] Started');
  }

  /**
   * Graceful shutdown.
   */
  async stop () {
    if (!this._isStarted) return;
    await Promise.all([
      this.consumer.disconnect(),
      this.producer.disconnect(),
    ]);
    if (this._server) {
      await new Promise(res => this._server.close(res));
    }
    this._isStarted = false;
    console.info('[monitor] Stopped');
  }

  /**
   * Return current thresholds (defensive copy).
   */
  get thresholds () {
    return { ...this._thresholds };
  }

  /**
   * Merge patch of thresholds; values set to `null` will restore defaults.
   * @param {Partial<typeof DEFAULT_THRESHOLDS>} patch
   */
  updateThresholds (patch) {
    for (const [k, v] of Object.entries(patch)) {
      if (!(k in DEFAULT_THRESHOLDS)) continue;
      if (v === null || v === undefined) {
        this._thresholds[k] = DEFAULT_THRESHOLDS[k];
      } else if (!Number.isFinite(v)) {
        // eslint-disable-next-line max-len
        throw new TypeError(`Threshold for ${k} must be a finite number or null; got ${v}`);
      } else {
        this._thresholds[k] = v;
      }
    }
  }

  /* ────────────────────────────── Internals ────────────────────────────── */

  /**
   * Build RxJS evaluation pipeline.
   * @private
   * @param {import('rxjs').Observable<MetricEvent>} metrics$
   */
  _wireEvaluationPipeline (metrics$) {
    // Group by modelId+version so we can issue per-model retrain events.
    metrics$
      .pipe(
        groupBy(evt => `${evt.modelId}:${evt.version}`),
        mergeMap(model$ => model$.pipe(
          bufferTime(60_000, null, 1_000), // 1-min tumbling window, max 1k events
          map(buffer => ({
            idVersion: model$.key,
            events   : buffer,
          })),
        )),
        filter(({ events }) => events.length > 0),
        map(({ idVersion, events }) => this._evaluateWindow(idVersion, events)),
        filter(Boolean), // null = no alert
      )
      .subscribe(alert => this._emitRetrainEvent(alert))
      .add(err => console.error('[monitor] stream error', err));
  }

  /**
   * Check an aggregated window of metrics against thresholds.
   * @private
   * @param {string} idVersion
   * @param {MetricEvent[]} events
   * @returns {Object|null} retrain alert or null
   */
  _evaluateWindow (idVersion, events) {
    const latest = _.last(events);
    if (!latest) return null;

    const violated = [];

    if (latest.accuracy <= this._thresholds.accuracy)
      violated.push('accuracy');
    if (latest.f1Score <= this._thresholds.f1Score)
      violated.push('f1Score');
    if (latest.fairnessDisparity >= this._thresholds.fairnessDisparity)
      violated.push('fairnessDisparity');

    // Aggregate toxicity FN across window
    const toxicityFN = _.sumBy(events, 'toxicityFalseNegatives');
    if (toxicityFN >= this._thresholds.toxicityFalseNegatives)
      violated.push('toxicityFalseNegatives');

    if (!violated.length) return null;

    const [modelId, version] = idVersion.split(':');

    return {
      modelId,
      version,
      violated,
      ts: Date.now(),
      metadata: {
        windowSize: events.length,
        windowStart: events[0].ts,
        windowEnd: latest.ts,
      },
    };
  }

  /**
   * Emit retrain event to Kafka.
   * @private
   * @param {Object} alert
   */
  async _emitRetrainEvent (alert) {
    try {
      await this.producer.send({
        topic: RETRAIN_TOPIC,
        messages: [
          { key: alert.modelId, value: JSON.stringify(alert) },
        ],
      });
      console.info(
        `[monitor] Retrain requested for model=${alert.modelId}@${alert.version}; violated=${alert.violated.join(',')}`,
      );
    } catch (err) {
      console.error('[monitor] Failed to publish retrain event', err);
    }
  }

  /**
   * Configure minimal HTTP API for runtime threshold management.
   * @private
   */
  _setupHttpApi () {
    this._expressApp.use(express.json({ limit: '1kb' }));

    this._expressApp.get('/thresholds', (_req, res) => {
      res.json(this.thresholds);
    });

    this._expressApp.put('/thresholds', (req, res) => {
      try {
        this.updateThresholds(req.body || {});
        res.status(204).end();
      } catch (err) {
        res.status(400).json({ error: err.message });
      }
    });

    // Health checks for orchestration probes
    this._expressApp.get('/healthz', (_req, res) => res.status(200).end());
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                                 Bootstrap                                 */
/* ────────────────────────────────────────────────────────────────────────── */

if (require.main === module) {
  // If executed directly, start monitor with env-derived config.
  const brokers = (process.env.KAFKA_BROKERS || 'localhost:9092').split(',');

  const monitor = new ModelPerformanceMonitor({ brokers });

  monitor
    .start()
    .catch(err => {
      console.error('[monitor] Failed to start', err);
      process.exitCode = 1;
    });

  // Graceful shutdown
  const shutdown = async () => {
    await monitor.stop();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                                   Exports                                 */
/* ────────────────────────────────────────────────────────────────────────── */

module.exports = {
  ModelPerformanceMonitor,
  DEFAULT_THRESHOLDS,
};
```