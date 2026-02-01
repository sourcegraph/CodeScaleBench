```javascript
/**
 * AgoraPulse – Real-Time Model Monitor
 * -----------------------------------
 * src/module_10.js
 *
 * Monitors prediction streams and automatically triggers
 * drift / quality alerts when metrics violate configured SLAs.
 *
 * Design highlights
 *  • Kafka + RxJS  : event-driven, back-pressure aware pipeline
 *  • Strategy      : pluggable metric calculators
 *  • Observer      : alert subscribers (web-hook, Kafka topic, etc.)
 *  • Robustness    : schema validation, retry, graceful shutdown
 *
 * NOTE:  While the core project is TypeScript, this file is pure
 *        JavaScript for maximal interoperability with Node runtimes
 *        inside lightweight side-car containers.
 */

/* ────────────────────────────────────────────────────────────
 * External Dependencies
 * ──────────────────────────────────────────────────────────── */
const { Kafka, logLevel }       = require('kafkajs');
const {
  Observable,
  Subject,
  fromEventPattern,
  timer,
  merge,
}                                = require('rxjs');
const {
  bufferTime,
  filter,
  map,
  mergeMap,
  tap,
  catchError,
}                                = require('rxjs/operators');
const Ajv                       = require('ajv');
const _                         = require('lodash');
let   fetch;
try {
  // node-fetch ≥ 3 is ESM; fallback to common-js wrapper
  fetch = require('node-fetch');
} catch (e) {
  fetch = (...args) => import('node-fetch').then(({ default: fn }) => fn(...args));
}

/* ────────────────────────────────────────────────────────────
 * Configuration
 * ──────────────────────────────────────────────────────────── */
const DEFAULT_CONFIG = {
  kafka: {
    brokers: ['localhost:9092'],
    groupId: 'agorapulse-model-monitor',
    consumeTopic: 'model.predictions',
    alertTopic:   'monitor.drift_alerts',
  },
  monitor: {
    // Sliding window (ms) over which metrics are aggregated
    windowMs: 60_000,
    // Minimum number of samples to evaluate metrics
    minSamples: 500,
  },
  metrics: {
    // metricName : { strategy: Class, threshold: Number, comparator: '>'|'<'}
    accuracy:   { strategy: 'AccuracyMetric',   threshold: 0.92, comparator: '<' },
    klDivergence: { strategy: 'KLDivergenceMetric', threshold: 0.15, comparator: '>' },
  },
  alerts: {
    // Web-hook endpoints that receive JSON payloads
    webhooks: ['http://localhost:4000/hooks/model-alert'],
    // Debounce identical alerts for N ms (avoid flooding)
    debounceMs: 15_000,
  },
  logging: {
    level: 'info',
  },
};

/* ────────────────────────────────────────────────────────────
 * Utility: Logger (minimal wrapper around console)
 * ──────────────────────────────────────────────────────────── */
function createLogger(level = 'info') {
  const levels = ['error', 'warn', 'info', 'debug', 'trace'];
  const idx    = levels.indexOf(level);
  const logger = {};
  levels.forEach((lvl, i) => {
    logger[lvl] = i <= idx ? console[lvl] ? console[lvl].bind(console) : console.log.bind(console) : () => {};
  });
  return logger;
}

/* ────────────────────────────────────────────────────────────
 * JSON Schema for incoming prediction messages
 * ──────────────────────────────────────────────────────────── */
const PREDICTION_SCHEMA = {
  type: 'object',
  required: ['modelVersion', 'prediction', 'timestamp'],
  properties: {
    modelVersion: { type: 'string' },
    prediction:   {
      anyOf: [
        { type: 'number' },
        { type: 'string'  },
        { type: 'object'  },
      ],
    },
    label:        { type: ['number', 'string'] },
    userId:       { type: ['number', 'string'] },
    timestamp:    { type: 'number' },
    meta:         { type: 'object' },
  },
};

/* ────────────────────────────────────────────────────────────
 * Metric Strategy – Base Class
 * ──────────────────────────────────────────────────────────── */
/**
 * @abstract
 */
class MetricStrategy {
  /**
   * @param {Object[]} samples – array of messages
   * @return {{ metric: string, value: number }}
   */
  compute(/* samples */) {
    throw new Error('compute() not implemented');
  }
}

/* ────────────────────────────────────────────────────────────
 * Accuracy Metric
 * ──────────────────────────────────────────────────────────── */
class AccuracyMetric extends MetricStrategy {
  compute(samples) {
    const labeled = samples.filter(s => s.label !== undefined && s.label !== null);
    if (!labeled.length) return { metric: 'accuracy', value: 1 };
    const correct = labeled.filter(s => s.prediction === s.label).length;
    return { metric: 'accuracy', value: correct / labeled.length };
  }
}

/* ────────────────────────────────────────────────────────────
 * KL Divergence Metric
 *   • Assumes prediction field is a class string.
 *   • Compares distribution in sliding window with full
 *     moving average to detect drift.
 * ──────────────────────────────────────────────────────────── */
class KLDivergenceMetric extends MetricStrategy {
  constructor() {
    super();
    this.longTermCounts = {};
    this.longTermTotal  = 0;
  }

  _freqDist(samples) {
    return samples.reduce((acc, s) => {
      const key = String(s.prediction);
      acc[key]  = (acc[key] || 0) + 1;
      return acc;
    }, {});
  }

  _normalize(counts) {
    const total = _.sum(Object.values(counts));
    return _.mapValues(counts, c => c / (total || 1));
  }

  _kl(p, q) {
    let kl = 0;
    Object.keys(p).forEach(k => {
      if (p[k] === 0) return;
      if (!q[k]) q[k] = 1e-12; // smoothing
      kl += p[k] * Math.log(p[k] / q[k]);
    });
    return kl;
  }

  compute(samples) {
    const windowCounts = this._freqDist(samples);
    const windowProb   = this._normalize(windowCounts);

    // update long-term
    Object.entries(windowCounts).forEach(([k, v]) => {
      this.longTermCounts[k] = (this.longTermCounts[k] || 0) + v;
    });
    this.longTermTotal += samples.length;
    const longTermProb = this._normalize(this.longTermCounts);

    const value = this._kl(windowProb, longTermProb);
    return { metric: 'klDivergence', value };
  }
}

/* ────────────────────────────────────────────────────────────
 * Strategy Factory
 * ──────────────────────────────────────────────────────────── */
class MetricFactory {
  constructor() {
    this.registry = {
      AccuracyMetric,
      KLDivergenceMetric,
    };
  }

  create(strategyName) {
    const Strategy = this.registry[strategyName];
    if (!Strategy) throw new Error(`Unknown MetricStrategy: ${strategyName}`);
    return new Strategy();
  }
}

/* ────────────────────────────────────────────────────────────
 * Real-Time Monitor Core
 * ──────────────────────────────────────────────────────────── */
class RealTimeModelMonitor {
  /**
   * @param {object} userConfig
   */
  constructor(userConfig = {}) {
    this.config   = _.merge({}, DEFAULT_CONFIG, userConfig);
    this.logger   = createLogger(this.config.logging.level);
    this.kafka    = new Kafka({
      clientId:  'agorapulse-monitor',
      brokers:   this.config.kafka.brokers,
      logLevel:  logLevel.ERROR,
    });
    this.consumer = this.kafka.consumer({ groupId: this.config.kafka.groupId });
    this.producer = this.kafka.producer();
    this.metricFactory = new MetricFactory();
    this.metricInstances = {};
    this.ajv     = new Ajv();
    this.validate = this.ajv.compile(PREDICTION_SCHEMA);

    this.alertSubject = new Subject(); // multiplex alerts
  }

  /* ───────────────────────────
   * Kafka bindings
   * ─────────────────────────── */
  async _initKafka() {
    await Promise.all([this.consumer.connect(), this.producer.connect()]);
    await this.consumer.subscribe({ topic: this.config.kafka.consumeTopic, fromBeginning: false });
  }

  _createPredictionObservable() {
    const addHandler = (handler) => {
      this.consumer.run({
        eachMessage: async ({ message }) => handler(message),
      }).catch(e => this.logger.error('Consumer error', e));
    };

    const removeHandler = () => {
      // kafkajs doesn't support removing handler per run,
      // but we stop consumption in shutdown().
    };

    return fromEventPattern(
      addHandler,
      removeHandler,
      (raw) => {
        try {
          const msg = JSON.parse(raw.value.toString());
          return msg;
        } catch (e) {
          this.logger.warn('Invalid JSON message', e);
          return null;
        }
      },
    ).pipe(
      filter(Boolean),
      filter(msg => {
        const valid = this.validate(msg);
        if (!valid) this.logger.warn('Schema violation', this.validate.errors);
        return valid;
      }),
    );
  }

  /* ───────────────────────────
   * Alerting
   * ─────────────────────────── */
  async _publishAlert(alert) {
    const payload = JSON.stringify(alert);
    const tasks   = [];

    // Kafka
    tasks.push(
      this.producer.send({
        topic: this.config.kafka.alertTopic,
        messages: [{ value: payload }],
      }).catch(e => this.logger.error('Failed to publish Kafka alert', e)),
    );

    // web-hooks
    for (const url of this.config.alerts.webhooks) {
      tasks.push(
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payload,
        }).catch(e => this.logger.error(`Webhook ${url} failed`, e)),
      );
    }
    await Promise.all(tasks);
  }

  _wireAlertSubscribers() {
    const debounced = {};
    this.alertSubject.subscribe(async (alert) => {
      const key = `${alert.metric}:${alert.modelVersion}`;
      const last = debounced[key] || 0;
      const now  = Date.now();
      if (now - last < this.config.alerts.debounceMs) {
        this.logger.debug('Debounced alert', key);
        return;
      }
      debounced[key] = now;
      await this._publishAlert(alert);
      this.logger.warn(`ALERT [${alert.metric}]`, alert);
    });
  }

  /* ───────────────────────────
   * Metric evaluation logic
   * ─────────────────────────── */
  _evaluateMetrics(samples) {
    Object.entries(this.config.metrics).forEach(([name, meta]) => {
      if (!this.metricInstances[name]) {
        this.metricInstances[name] = this.metricFactory.create(meta.strategy);
      }
      const result = this.metricInstances[name].compute(samples);
      this.logger.debug(`Metric ${name}=${result.value.toFixed(4)}`);

      const cmp = meta.comparator === '>' ? (a, b) => a > b : (a, b) => a < b;
      if (samples.length >= this.config.monitor.minSamples && cmp(result.value, meta.threshold)) {
        const alert = {
          ...result,
          threshold: meta.threshold,
          comparator: meta.comparator,
          modelVersion: _.get(samples[0], 'modelVersion', 'unknown'),
          windowSize: samples.length,
          timestamp: Date.now(),
        };
        this.alertSubject.next(alert);
      }
    });
  }

  /* ───────────────────────────
   * Public API
   * ─────────────────────────── */
  async start() {
    await this._initKafka();
    this.logger.info('Real-Time Model Monitor started');

    this._wireAlertSubscribers();

    const prediction$ = this._createPredictionObservable();

    // Buffer predictions into sliding windows
    prediction$
      .pipe(
        bufferTime(this.config.monitor.windowMs),
        filter(buffer => buffer.length >= this.config.monitor.minSamples),
        tap(buffer => this._evaluateMetrics(buffer)),
        catchError(err => {
          this.logger.error('Stream processing error', err);
          return [];
        }),
      )
      .subscribe({
        error: (err) => this.logger.error('Fatal stream error', err),
      });
  }

  async shutdown() {
    this.logger.info('Shutting down model monitor...');
    try {
      await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
    } catch (e) {
      this.logger.error('Error during shutdown', e);
    }
    this.logger.info('Shutdown complete');
  }
}

/* ────────────────────────────────────────────────────────────
 * Module Exports
 * ──────────────────────────────────────────────────────────── */
module.exports = {
  RealTimeModelMonitor,
  MetricStrategy,
  AccuracyMetric,
  KLDivergenceMetric,
  MetricFactory,
  DEFAULT_CONFIG,
};
```