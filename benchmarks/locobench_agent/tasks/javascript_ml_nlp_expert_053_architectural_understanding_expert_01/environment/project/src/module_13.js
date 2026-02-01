/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * ------------------------------------------------
 * Module: SentimentShiftSentinel
 *
 * src/module_13.js
 *
 * This module listens to the streaming sentiment-analysis output coming from the
 * model-serving layer (Kafka topic: `model.sentiment.v1`).  It computes a
 * rolling baseline and emits a domain event whenever the current sentiment
 * diverges from the baseline beyond a configurable threshold.  The threshold
 * calculation is pluggable (Strategy Pattern) so that different teams can swap
 * in their own logic without touching the sentinel core.
 *
 * Typical downstream listeners:
 *   • Moderation Service – auto-flag potential raids / toxicity spikes
 *   • Experiment Tracker – correlate sentiment drift with model versions
 *   • Auto-Retraining Orchestrator – schedule rapid fine-tune runs
 *
 * The module is written in vanilla Node.js (CommonJS) to keep the core runtime
 * dependencies minimal and interoperable with the rest of the platform.
 *
 * ------------------------------------------------
 * NOTE: This file purposefully avoids any project-private imports so that it
 * can be copy-pasted for review.  Replace the placeholder paths (`@agora/*`)
 * with the actual local packages when integrating into the monorepo.
 */

"use strict";

/* ────────────────────────────────────────────────────────────────────
 * External Dependencies
 * ──────────────────────────────────────────────────────────────────── */
const { Kafka }               = require("kafkajs");
const { EventEmitter }        = require("events");
const { Subject, from }       = require("rxjs");
const {
    bufferTime,
    filter,
    tap,
    mergeMap,
    catchError,
}                              = require("rxjs/operators");
const pino                    = require("pino");

/* ────────────────────────────────────────────────────────────────────
 * Internal / Project Dependencies (replace with real paths)
 * ──────────────────────────────────────────────────────────────────── */
// const { DomainEvent }      = require("@agora/events");
// const { emitEvent }        = require("@agora/event-bus");

/* ────────────────────────────────────────────────────────────────────
 * Constants
 * ──────────────────────────────────────────────────────────────────── */
const DEFAULT_KAFKA_BROKERS = process.env.KAFKA_BROKERS?.split(",") || [
    "localhost:9092",
];
const SENTIMENT_TOPIC       = process.env.SENTIMENT_TOPIC || "model.sentiment.v1";
const LOGGER                = pino({ name: "SentimentShiftSentinel" });

/* ────────────────────────────────────────────────────────────────────
 * Helper: Exponential Moving Average
 * ──────────────────────────────────────────────────────────────────── */
function ewma(prev, curr, alpha) {
    return prev == null ? curr : alpha * curr + (1 - alpha) * prev;
}

/* ────────────────────────────────────────────────────────────────────
 * Strategy Pattern: Threshold Calculation
 * ──────────────────────────────────────────────────────────────────── */

/**
 * @typedef {Object} StrategyContext
 * @property {number[]} windowValues – Sentiment scores inside the window
 * @property {number}   globalBaseline – Previously learned global baseline
 */

/**
 * BaseStrategy (non-instantiable)
 */
class BaseStrategy {
    /**
     * @param {Object} opts
     * @param {number} opts.alpha – Smoothing factor (0 < alpha ≤ 1)
     * @param {number} opts.k – Multiplier for standard deviation
     */
    constructor(opts = {}) {
        if (new.target === BaseStrategy) {
            throw new TypeError("Cannot instantiate abstract BaseStrategy");
        }
        this.alpha    = opts.alpha ?? 0.3;
        this.k        = opts.k     ?? 2.0;
        this.baseline = null;       // EWMA baseline
    }

    /**
     * @param {StrategyContext} ctx
     * @returns {{shiftValue: number, isShift: boolean}}
     */
    next(ctx) {
        throw new Error("next() must be implemented by subclasses");
    }
}

/**
 * StaticThresholdStrategy
 * Uses a fixed absolute threshold.
 */
class StaticThresholdStrategy extends BaseStrategy {
    constructor(threshold = 0.2) {
        super();
        this.threshold = threshold;
    }

    next({ windowValues }) {
        const currentAvg = mean(windowValues);
        if (this.baseline == null) this.baseline = currentAvg;

        const shiftValue = currentAvg - this.baseline;
        const isShift    = Math.abs(shiftValue) >= this.threshold;

        // Keep baseline static – no update
        return { shiftValue, isShift };
    }
}

/**
 * AdaptiveThresholdStrategy
 * Baseline & threshold adapt over time using EWMA and rolling std-dev.
 */
class AdaptiveThresholdStrategy extends BaseStrategy {
    constructor(opts = {}) {
        super(opts);
        this.stdDev = null;
    }

    next({ windowValues }) {
        const currentAvg = mean(windowValues);
        // Update baseline with EWMA
        this.baseline = ewma(this.baseline, currentAvg, this.alpha);
        // Update standard deviation (Bessel correction)
        const windowStd = std(windowValues);
        this.stdDev     = ewma(this.stdDev, windowStd, this.alpha);

        const dynamicThreshold = this.k * (this.stdDev || 0);
        const shiftValue       = currentAvg - this.baseline;
        const isShift          = Math.abs(shiftValue) >= dynamicThreshold;

        return { shiftValue, isShift };
    }
}

/* ────────────────────────────────────────────────────────────────────
 * Sentinel Core
 * ──────────────────────────────────────────────────────────────────── */

/**
 * Options for SentimentShiftSentinel
 * @typedef {Object} SentinelOptions
 * @property {string[]} [kafkaBrokers]
 * @property {number}   [windowMs] – Rolling window size
 * @property {BaseStrategy} strategy
 */
class SentimentShiftSentinel extends EventEmitter {
    /**
     * @param {SentinelOptions} opts
     */
    constructor(opts = {}) {
        super();
        this.kafkaBrokers = opts.kafkaBrokers ?? DEFAULT_KAFKA_BROKERS;
        this.windowMs     = opts.windowMs     ?? 60_000; // 1 minute
        this.strategy     = opts.strategy     ?? new AdaptiveThresholdStrategy();

        /* Streams */
        this._sentiment$  = new Subject();

        /* Kafka */
        this.kafka        = new Kafka({ brokers: this.kafkaBrokers });
        this.consumer     = this.kafka.consumer({
            groupId: "agora-sentinel-" + Math.random().toString(36).slice(2),
        });

        /* Control flags */
        this._isRunning = false;
    }

    /* ───── Private helpers ───── */

    async _initKafka() {
        await this.consumer.connect();
        await this.consumer.subscribe({ topic: SENTIMENT_TOPIC, fromBeginning: false });
        await this.consumer.run({
            eachMessage: async ({ message }) => {
                try {
                    const payload = JSON.parse(message.value.toString("utf8"));
                    // Expected schema: { score: number, ...metadata }
                    if (typeof payload.score === "number") {
                        this._sentiment$.next(payload.score);
                    } else {
                        LOGGER.warn({ payload }, "Invalid sentiment payload format");
                    }
                } catch (err) {
                    LOGGER.error({ err }, "Failed to parse Kafka message");
                }
            },
        });
    }

    _wireStream() {
        return this._sentiment$
            .pipe(
                // Aggregate by time window
                bufferTime(this.windowMs),
                filter((arr) => arr.length > 0),
                mergeMap((windowValues) => {
                    return from(
                        (async () => {
                            const { shiftValue, isShift } =
                                this.strategy.next({ windowValues });

                            if (isShift) {
                                const event = this._buildDomainEvent(shiftValue);
                                // emitEvent(event); // Uncomment when integrated
                                this.emit("shift", event); // Local Observer
                                LOGGER.info(
                                    { shiftValue: shiftValue.toFixed(3) },
                                    "Sentiment shift detected"
                                );
                            }
                            return isShift;
                        })()
                    );
                }),
                catchError((err, caught) => {
                    LOGGER.error({ err }, "Stream processing error");
                    return caught;
                })
            )
            .subscribe(); // Fire & forget
    }

    _buildDomainEvent(shiftValue) {
        const payload = {
            type:  "SENTIMENT_SHIFT_ALERT",
            ts:    Date.now(),
            meta:  {
                shift: shiftValue,
                windowMs: this.windowMs,
                strategy: this.strategy.constructor.name,
            },
        };
        return payload; // Replace with new DomainEvent(...) if available
    }

    /* ───── Public API ───── */

    /**
     * Start monitoring Kafka sentiment stream.
     */
    async start() {
        if (this._isRunning) return;
        LOGGER.info("Starting SentimentShiftSentinel");
        this._isRunning = true;

        await this._initKafka();
        this._subscription = this._wireStream();
    }

    /**
     * Gracefully shutdown Kafka consumer and RxJS subscription.
     */
    async stop() {
        if (!this._isRunning) return;
        LOGGER.info("Stopping SentimentShiftSentinel");
        await this.consumer.disconnect().catch((err) => {
            LOGGER.error({ err }, "Error during Kafka disconnect");
        });
        this._subscription?.unsubscribe();
        this._isRunning = false;
    }
}

/* ────────────────────────────────────────────────────────────────────
 * Utility functions
 * ──────────────────────────────────────────────────────────────────── */
function mean(arr) {
    if (arr.length === 0) return 0;
    return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function std(arr) {
    if (arr.length < 2) return 0;
    const mu = mean(arr);
    const variance =
        arr.reduce((acc, val) => acc + Math.pow(val - mu, 2), 0) / (arr.length - 1);
    return Math.sqrt(variance);
}

/* ────────────────────────────────────────────────────────────────────
 * Module Exports
 * ──────────────────────────────────────────────────────────────────── */
module.exports = {
    SentimentShiftSentinel,
    StaticThresholdStrategy,
    AdaptiveThresholdStrategy,
};

/* ────────────────────────────────────────────────────────────────────
 * Self-Invoking Entry (optional)
 * ──────────────────────────────────────────────────────────────────── */
if (require.main === module) {
    // Quick CLI entry for local testing: `node src/module_13.js`
    (async () => {
        const sentinel = new SentimentShiftSentinel();
        sentinel.on("shift", (evt) => {
            // eslint-disable-next-line no-console
            console.log("🔥 Sentiment shift event:", JSON.stringify(evt, null, 2));
        });

        process.on("SIGINT", async () => {
            await sentinel.stop();
            process.exit(0);
        });

        await sentinel.start();
    })().catch((err) => {
        LOGGER.fatal({ err }, "Fatal error in SentimentShiftSentinel");
        process.exit(1);
    });
}