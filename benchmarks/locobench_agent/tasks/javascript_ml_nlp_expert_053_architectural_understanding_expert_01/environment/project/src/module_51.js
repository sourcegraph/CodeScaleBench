```javascript
/**
 * src/module_51.js
 *
 * AgoraPulse: Real-Time Social Signal Intelligence
 * ------------------------------------------------
 * SentimentDriftMonitor
 *
 * Listens to the real-time sentiment stream, aggregates statistics in
 * sliding windows, detects distributional drift or fairness regressions,
 * and fires domain events that can trigger automated retraining or alerting.
 *
 * Designed as a plug-and-play micro-pipeline that can be spun up
 * horizontally. All heavy lifting is handled through RxJS operators, while
 * Kafka provides at-least-once durability for both the input stream and the
 * output domain events.
 *
 * Patterns demonstrated:
 *  • Observer/Reactive (RxJS)
 *  • Pipeline (RxJS operator chain)
 *  • Factory (config-driven Kafka client instantiation)
 *  • Strategy (pluggable drift detectors)
 * ------------------------------------------------
 */

"use strict";

/* External dependencies */
const { Kafka, logLevel } = require("kafkajs");
const { Subject, timer } = require("rxjs");
const {
  bufferTime,
  filter,
  map,
  mergeMap,
  catchError,
} = require("rxjs/operators");
const { v4: uuidv4 } = require("uuid");
const _ = require("lodash");
const EventEmitter = require("eventemitter3");
const debug = require("debug")("agorapulse:sentiment-monitor");

/**
 * @typedef {Object} SentimentRecord
 * @property {number} score           - Continuous sentiment score [-1, 1]
 * @property {string} modelVersion    - Semantic version of the model
 * @property {string} locale          - RFC5646 locale, e.g. "en-US"
 * @property {string} group           - Sensitive group, e.g., "gender=male"
 * @property {number} ts              - Epoch milliseconds
 */

/**
 * @typedef {Object} DriftEventPayload
 * @property {string} id
 * @property {string} modelVersion
 * @property {string} type            - "distribution_drift" | "fairness_drift"
 * @property {string} metric          - Human-readable metric name
 * @property {object} details         - Arbitrary JSON blob
 * @property {number} detectedAt      - Epoch milliseconds
 */

class SentimentDriftMonitor extends EventEmitter {
  /**
   * @param {Object} opts
   * @param {string[]} opts.brokers              - List of Kafka brokers
   * @param {string}   opts.inputTopic           - e.g. "agora.sentiment.stream"
   * @param {string}   opts.outputTopic          - e.g. "agora.events.drift"
   * @param {number}   opts.windowMs             - Sliding window size (ms)
   * @param {number}   opts.windowEveryMs        - Window slide interval (ms)
   * @param {number}   opts.negativityThreshold  - Trigger when mean score < x
   * @param {number}   opts.fairnessDelta        - Trigger when difference
   * @param {('warn'|'throw')} [opts.errorMode]  - Error handling strategy
   */
  constructor(opts) {
    super();
    this.config = Object.freeze({
      brokers: opts.brokers,
      inputTopic: opts.inputTopic,
      outputTopic: opts.outputTopic,
      windowMs: opts.windowMs ?? 60_000,
      windowEveryMs: opts.windowEveryMs ?? 10_000,
      negativityThreshold: opts.negativityThreshold ?? -0.5,
      fairnessDelta: opts.fairnessDelta ?? 0.25,
      errorMode: opts.errorMode ?? "warn",
    });

    /* Kafka clients are lazy-instantiated in init() */
    this.kafka = new Kafka({
      clientId: "agorapulse-sentiment-monitor",
      brokers: this.config.brokers,
      logLevel: logLevel.NOTHING,
    });

    this.consumer = this.kafka.consumer({ groupId: "sentiment-monitor" });
    this.producer = this.kafka.producer();

    /* -------- Reactive bits -------- */
    this._rawSubject = new Subject(); // pushes SentimentRecord
    this._subscription = null; // RxJS subscription handle

    /* Graceful shutdown wiring */
    ["SIGINT", "SIGTERM", "uncaughtException"].forEach((sig) =>
      process.on(sig, () => this.shutdown().catch(console.error))
    );
  }

  /**
   * Bootstraps Kafka consumers/producers and wiring.
   */
  async init() {
    debug("Initializing SentimentDriftMonitor…");
    await Promise.all([this.consumer.connect(), this.producer.connect()]);
    await this.consumer.subscribe({ topic: this.config.inputTopic });

    /* Emit Kafka messages into our RxJS subject */
    await this.consumer.run({
      eachMessage: async ({ message }) => {
        try {
          const data = JSON.parse(message.value.toString("utf8"));
          this._rawSubject.next(/** @type {SentimentRecord} */ (data));
        } catch (err) {
          debug("Malformed message ignored:", err);
        }
      },
    });

    /* Build reactive pipeline */
    this._subscription = this._rawSubject
      .pipe(
        bufferTime(this.config.windowMs, this.config.windowEveryMs),
        filter((batch) => batch.length > 0),
        mergeMap((batch) => this._evaluateWindow(batch)),
        mergeMap((driftEventPayload) => this._publishDriftEvent(driftEventPayload)),
        catchError((err, caught$) => {
          this._handleError(err);
          /* Keep the stream alive */
          return caught$;
        })
      )
      .subscribe({
        next: (payload) => this.emit("drift", payload),
        error: (err) => this._handleError(err),
        complete: () => debug("Drift monitor observable completed."),
      });

    debug("SentimentDriftMonitor initialized.");
  }

  /* --------------------------------------------------------------- *
   * PRIVATE
   * --------------------------------------------------------------- */

  /**
   * Evaluates a single window for drift/fairness problems.
   * Emits zero, one, or many DriftEventPayload objects.
   *
   * @param {SentimentRecord[]} batch
   * @returns {DriftEventPayload[]}
   */
  _evaluateWindow(batch) {
    const events = [];
    const now = Date.now();

    /* ----- 1) Distributional drift (negativity spike) ----- */
    const meanScore = _.meanBy(batch, "score");
    debug("Window mean score:", meanScore.toFixed(3));

    if (meanScore <= this.config.negativityThreshold) {
      events.push({
        id: uuidv4(),
        modelVersion: _.get(batch, "[0].modelVersion", "unknown"),
        type: "distribution_drift",
        metric: "mean_sentiment_score",
        details: { meanScore, threshold: this.config.negativityThreshold },
        detectedAt: now,
      });
    }

    /* ----- 2) Fairness drift between sensitive groups ----- */
    const groupedByGroup = _.groupBy(batch, "group");
    const groupMeans = _.mapValues(groupedByGroup, (records) =>
      _.meanBy(records, "score")
    );

    // Simple binary disparity check: max - min
    const maxGroup = _.max(_.values(groupMeans));
    const minGroup = _.min(_.values(groupMeans));
    const disparity = maxGroup - minGroup;

    if (disparity >= this.config.fairnessDelta) {
      events.push({
        id: uuidv4(),
        modelVersion: _.get(batch, "[0].modelVersion", "unknown"),
        type: "fairness_drift",
        metric: "group_sentiment_disparity",
        details: {
          disparity,
          threshold: this.config.fairnessDelta,
          groupMeans,
        },
        detectedAt: now,
      });
    }

    return events;
  }

  /**
   * Produces a drift detection event to Kafka.
   *
   * @param {DriftEventPayload} payload
   * @returns {Promise<DriftEventPayload>}
   */
  async _publishDriftEvent(payload) {
    debug("Publishing drift event:", payload.type, payload.metric);
    await this.producer.send({
      topic: this.config.outputTopic,
      messages: [{ key: payload.type, value: JSON.stringify(payload) }],
    });

    return payload;
  }

  /**
   * @param {Error} err
   * @private
   */
  _handleError(err) {
    if (this.config.errorMode === "throw") {
      throw err;
    } else {
      console.error("SentimentDriftMonitor error:", err);
    }
  }

  /* --------------------------------------------------------------- *
   * PUBLIC
   * --------------------------------------------------------------- */

  /**
   * Flushes Kafka producer and tears down resources.
   */
  async shutdown() {
    debug("Shutting down SentimentDriftMonitor…");
    try {
      this._subscription && this._subscription.unsubscribe();
      await Promise.all([
        this.consumer.disconnect().catch(() => undefined),
        this.producer.disconnect().catch(() => undefined),
      ]);
      this._rawSubject.complete();
      debug("Shutdown complete.");
    } catch (err) {
      console.error("Error during shutdown:", err);
    } finally {
      process.exit(0);
    }
  }
}

module.exports = SentimentDriftMonitor;
```