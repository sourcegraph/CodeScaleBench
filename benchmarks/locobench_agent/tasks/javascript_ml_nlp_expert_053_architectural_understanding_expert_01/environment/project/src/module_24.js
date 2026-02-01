/**
 * src/module_24.js
 *
 * SentimentDriftMonitor
 * ---------------------
 * Listens to model‐level sentiment predictions flowing through Kafka, aggregates
 * them in real-time with RxJS, and raises drift alerts whenever the rolling
 * average sentiment for a given (domain, locale) pair diverges from the
 * registered baseline beyond a configurable threshold.  Alerts are fanned‐out
 * through Kafka and an optional web hook for downstream moderation tooling.
 *
 * The module purposely keeps a small state footprint (in-memory, sliding
 * windows) because it is horizontally scalable—instances are coordinated
 * through consumer group partitioning, and any alert raised includes enough
 * context to be processed idempotently.
 *
 * Dependencies:
 *   kafkajs     – Kafka client
 *   rxjs        – Reactive operators
 *   axios       – HTTP client for baseline + web hook calls
 *   pino        – Structured logger
 *   uuid        – For deterministic alert-id generation
 *
 * Usage:
 *   const monitor = new SentimentDriftMonitor(config);
 *   await monitor.start();
 *   // … later …
 *   await monitor.stop();
 */

'use strict';

const { Kafka, logLevel } = require('kafkajs');
const {
  Subject,
  timer,
  merge,
} = require('rxjs');
const {
  bufferTime,
  filter,
  map,
  mergeMap,
  tap,
} = require('rxjs/operators');
const axios = require('axios').default;
const pino = require('pino');
const { v4: uuidv4 } = require('uuid');

const DEFAULT_CONFIG = Object.freeze({
  kafka: {
    clientId: 'agorapulse-sentiment-drift-monitor',
    brokers: process.env.KAFKA_BROKERS
      ? process.env.KAFKA_BROKERS.split(',')
      : ['localhost:9092'],
    connectionTimeout: 6000,
    authenticationTimeout: 6000,
    logLevel: logLevel.ERROR,
  },
  topics: {
    predictions: 'prediction-events',
    alerts: 'drift-alerts',
  },
  consumerGroup: 'sentiment-drift-monitor',
  slideMs: 60_000, // 1-minute moving window
  emitEveryMs: 30_000, // Evaluate drift every 30s
  driftThreshold: 0.15, // Absolute delta from baseline
  webHook: process.env.DRIFT_WEB_HOOK || null,
  baselineEndpoint:
    process.env.BASELINE_ENDPOINT || 'http://baseline-cache.internal/baselines',
  logger: pino({
    name: 'SentimentDriftMonitor',
    level: process.env.LOG_LEVEL || 'info',
  }),
});

/**
 * SentimentDriftMonitor orchestrates the full life-cycle of the service.
 */
class SentimentDriftMonitor {
  /**
   * @param {Partial<typeof DEFAULT_CONFIG>} userConfig
   */
  constructor(userConfig = {}) {
    /** @type {typeof DEFAULT_CONFIG} */
    this.config = deepFreeze(mergeDefaults(DEFAULT_CONFIG, userConfig));

    /** @private */
    this._kafka = new Kafka(this.config.kafka);
    /** @private */
    this._producer = this._kafka.producer({
      allowAutoTopicCreation: false,
      idempotent: true,
    });
    /** @private */
    this._consumer = this._kafka.consumer({
      groupId: this.config.consumerGroup,
      allowAutoTopicCreation: false,
    });

    /** @private {Subject<PredictionEvent>} */
    this._event$ = new Subject();

    /** @private {boolean} */
    this._running = false;
  }

  /**
   * Boots the monitor: establishes Kafka connections and RxJS subscriptions.
   */
  async start() {
    if (this._running) return;
    this.config.logger.info('Booting SentimentDriftMonitor…');

    await Promise.all([this._producer.connect(), this._consumer.connect()]);
    await this._consumer.subscribe({
      topic: this.config.topics.predictions,
      fromBeginning: false,
    });

    // Pipe incoming Kafka messages into RxJS stream
    this._consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          const payload = JSON.parse(message.value.toString('utf8'));
          this._event$.next(payload);
        } catch (err) {
          this.config.logger.warn(
            { err, topic, partition, offset: message.offset },
            'Dropped malformed message',
          );
        }
      },
    });

    // Compose reactive pipeline
    const subscription = buildPipeline(
      this._event$,
      this.config,
      this._producer,
    );

    this._subscription = subscription;
    this._running = true;
    this.config.logger.info('SentimentDriftMonitor started.');
  }

  /**
   * Gracefully shuts down the monitor and releases resources.
   */
  async stop() {
    if (!this._running) return;
    this.config.logger.info('Shutting down SentimentDriftMonitor…');

    await Promise.all([
      this._subscription?.unsubscribe(),
      this._consumer.stop().catch(() => {}),
      this._consumer.disconnect().catch(() => {}),
      this._producer.disconnect().catch(() => {}),
    ]);

    this._running = false;
    this.config.logger.info('SentimentDriftMonitor stopped.');
  }
}

/* -------------------------------------------------------------------------- */
/*                                RxJS Graph                                  */
/* -------------------------------------------------------------------------- */

/**
 * Builds the RxJS pipeline that performs rolling aggregation + drift detection.
 *
 * @param {Subject<PredictionEvent>} event$
 * @param {typeof DEFAULT_CONFIG} cfg
 * @param {import('kafkajs').Producer} producer
 */
function buildPipeline(event$, cfg, producer) {
  // Sidechain that ticks at cfg.emitEveryMs to trigger window evaluation
  const tick$ = timer(cfg.emitEveryMs, cfg.emitEveryMs);

  // Merge prediction events with tick events: when a tick arrives, flush buffer
  return merge(event$, tick$)
    .pipe(
      bufferTime(cfg.slideMs, null, null, false), // Collect sliding window
      filter((buffer) => buffer.length > 0),
      mergeMap(async (buffer) => {
        const grouped = groupByDomainLocale(buffer);
        const baseline = await fetchBaseline(Object.keys(grouped), cfg);

        const alerts = detectDrift(grouped, baseline, cfg.driftThreshold);

        await Promise.all(
          alerts.map((alert) =>
            publishAlert(alert, producer, cfg.topics.alerts, cfg.webHook, cfg),
          ),
        );

        return alerts.length;
      }),
      tap((count) => {
        if (count > 0) cfg.logger.debug({ count }, 'Drift alerts emitted.');
      }),
    )
    .subscribe({
      error: (err) => cfg.logger.error({ err }, 'Fatal error in pipeline.'),
    });
}

/* -------------------------------------------------------------------------- */
/*                             Helper Functions                               */
/* -------------------------------------------------------------------------- */

/**
 * @typedef {Object} PredictionEvent
 * @property {string} id            – Unique prediction id
 * @property {string} domain        – e.g. "twitter", "tiktok"
 * @property {string} locale        – e.g. "en-US"
 * @property {number} sentiment     – Normalized sentiment score [-1, 1]
 * @property {number} ts            – Unix epoch milliseconds
 */

/**
 * Groups PredictionEvents by (domain, locale) tuple.
 * @param {PredictionEvent[]} events
 * @return {Record<string, {sum: number, count: number}>}
 */
function groupByDomainLocale(events) {
  return events.reduce((acc, evt) => {
    if (typeof evt.sentiment !== 'number') return acc; // skip malformed
    const key = `${evt.domain}::${evt.locale}`;
    const state = acc[key] ?? { sum: 0, count: 0 };
    state.sum += evt.sentiment;
    state.count += 1;
    acc[key] = state;
    return acc;
  }, {});
}

/**
 * Fetches baseline sentiment for each key from the configured endpoint.
 * Falls back to neutral (0) if endpoint is unreachable or returns 404.
 *
 * @param {string[]} keys
 * @param {typeof DEFAULT_CONFIG} cfg
 * @return {Promise<Record<string, number>>}
 */
async function fetchBaseline(keys, cfg) {
  try {
    const res = await axios.get(cfg.baselineEndpoint, {
      params: { keys },
      timeout: 2_000,
    });
    return res.data; // { "<domain>::<locale>": baselineScore }
  } catch (err) {
    cfg.logger.warn({ err }, 'Baseline endpoint unreachable. Using neutral.');
    return keys.reduce((acc, k) => {
      acc[k] = 0;
      return acc;
    }, {});
  }
}

/**
 * Detects drift between aggregated sentiment and baseline.
 *
 * @param {Record<string, {sum: number, count: number}>} grouped
 * @param {Record<string, number>} baseline
 * @param {number} threshold
 * @return {DriftAlert[]}
 */
function detectDrift(grouped, baseline, threshold) {
  /** @typedef {ReturnType<typeof buildDriftAlert>} DriftAlert */

  const alerts = [];

  for (const [key, agg] of Object.entries(grouped)) {
    if (agg.count === 0) continue;
    const average = agg.sum / agg.count;
    const base = baseline[key] ?? 0;
    if (Math.abs(average - base) >= threshold) {
      alerts.push(
        buildDriftAlert({
          key,
          baseline: base,
          observed: average,
          delta: average - base,
          sampleSize: agg.count,
        }),
      );
    }
  }
  return alerts;
}

/**
 * Constructs a DriftAlert object.
 */
function buildDriftAlert({
  key,
  baseline,
  observed,
  delta,
  sampleSize,
}) {
  const [domain, locale] = key.split('::');
  return {
    alertId: uuidv4(),
    domain,
    locale,
    baseline,
    observed,
    delta,
    sampleSize,
    triggeredAt: Date.now(),
  };
}

/**
 * Publishes drift alert to Kafka and optional web hook in parallel.
 *
 * @param {DriftAlert} alert
 * @param {import('kafkajs').Producer} producer
 * @param {string} topic
 * @param {string|null} webHook
 * @param {typeof DEFAULT_CONFIG} cfg
 */
async function publishAlert(alert, producer, topic, webHook, cfg) {
  try {
    await producer.send({
      topic,
      messages: [
        {
          key: `${alert.domain}::${alert.locale}`,
          value: JSON.stringify(alert),
        },
      ],
    });
  } catch (err) {
    cfg.logger.error({ err, alert }, 'Failed to publish drift alert.');
  }

  if (webHook) {
    axios
      .post(webHook, alert, { timeout: 1_500 })
      .catch((err) =>
        cfg.logger.warn({ err, alert }, 'Failed to POST drift alert to webHook'),
      );
  }
}

/* -------------------------------------------------------------------------- */
/*                              Utils / Helpers                               */
/* -------------------------------------------------------------------------- */

/**
 * Performs a deep merge of default + user config.
 * Arrays are not merged—they are replaced by the user config if provided.
 */
function mergeDefaults(def, user) {
  if (isPrimitive(def) || isPrimitive(user)) return user ?? def;
  const out = { ...def };
  for (const [k, v] of Object.entries(user || {})) {
    out[k] =
      v && typeof v === 'object' && !Array.isArray(v)
        ? mergeDefaults(def[k] ?? {}, v)
        : v;
  }
  return out;
}

/**
 * Recursively freezes an object to prevent mutations.
 */
function deepFreeze(obj) {
  if (obj && typeof obj === 'object' && !Object.isFrozen(obj)) {
    Object.freeze(obj);
    Object.getOwnPropertyNames(obj).forEach((prop) =>
      deepFreeze(obj[prop]),
    );
  }
  return obj;
}

function isPrimitive(v) {
  return v === null || (typeof v !== 'object' && typeof v !== 'function');
}

/* -------------------------------------------------------------------------- */
/*                          Module Exports                                    */
/* -------------------------------------------------------------------------- */

module.exports = {
  SentimentDriftMonitor,
  DEFAULT_CONFIG,
};
