'use strict';

/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * src/module_64.js
 *
 * A production-grade “ModelDriftMonitor” that consumes prediction events from
 * Kafka, aggregates them in a sliding window via RxJS, computes the
 * Kullback–Leibler divergence against a configurable baseline distribution, and
 * notifies downstream systems when distributional drift is detected.
 *
 * Exposed API:
 *   const monitor = new ModelDriftMonitor(opts);
 *   await monitor.start();
 *   monitor.on('drift',  evt => { … });
 *   …
 *   await monitor.stop();
 *
 * Dependencies (add to package.json):
 *   "kafkajs":  "^2.2.4",
 *   "rxjs":     "^7.8.1"
 */

const { Kafka, logLevel: KafkaLogLevel } = require('kafkajs');
const { Subject } = require('rxjs');
const { bufferTime, filter } = require('rxjs/operators');
const fs   = require('fs');
const path = require('path');
const { EventEmitter } = require('events');

/* -------------------------------------------------------------------------- */
/*                               Helper Methods                               */
/* -------------------------------------------------------------------------- */

/**
 * Compute K-L divergence D(P || Q) for discrete distributions.
 * Both arguments are objects whose keys correspond to labels and whose values
 * are probabilities that sum to 1.
 *
 * Returns Number in [0, ∞).
 */
function kullbackLeibler(p, q, eps = 1e-12) {
    let divergence = 0.0;
    const labels = new Set([...Object.keys(p), ...Object.keys(q)]);
    labels.forEach(label => {
        const p_i = Math.max(p[label] ?? 0, eps);
        const q_i = Math.max(q[label] ?? 0, eps);
        divergence += p_i * Math.log(p_i / q_i);
    });
    return divergence;
}

/**
 * Turn an array of label strings into a probability distribution object.
 */
function toDistribution(labelsArray) {
    const total = labelsArray.length;
    const counts = {};
    labelsArray.forEach(l => { counts[l] = (counts[l] || 0) + 1; });
    Object.keys(counts).forEach(k => { counts[k] = counts[k] / total; });
    return counts;
}

/* -------------------------------------------------------------------------- */
/*                             ModelDriftMonitor                              */
/* -------------------------------------------------------------------------- */

class ModelDriftMonitor extends EventEmitter {
    /**
     * @param {Object}  options
     * @param {Object}  options.kafka.brokers          – Array of broker addresses
     * @param {String}  options.topicIn                – Topic containing prediction events
     * @param {String}  options.topicOut               – Topic for drift alert events
     * @param {Number}  [options.windowMs=60000]       – Sliding window size
     * @param {Number}  [options.minSamples=500]       – Minimum samples per window
     * @param {Number}  [options.driftThreshold=0.15]  – K-L divergence threshold
     * @param {String}  [options.baselinePath]         – Path to baseline JSON
     * @param {Object}  [options.logger=console]       – Custom logger
     */
    constructor({
        kafka       = { brokers: ['localhost:9092'] },
        consumerConfig = {},
        producerConfig = {},
        topicIn,
        topicOut,
        windowMs        = 60_000,
        minSamples      = 500,
        driftThreshold  = 0.15,
        baselinePath    = path.join(__dirname, '../resources/baseline_distribution.json'),
        logger          = console,
    } = {}) {
        super();

        if (!topicIn || !topicOut) throw new Error('Both topicIn and topicOut must be provided.');

        this._logger         = logger;
        this._topicIn        = topicIn;
        this._topicOut       = topicOut;
        this._windowMs       = windowMs;
        this._minSamples     = minSamples;
        this._driftThreshold = driftThreshold;
        this._baseline       = this._loadBaseline(baselinePath);
        this._ready          = false;

        this._kafka    = new Kafka({
            clientId: 'agorapulse-model-drift-monitor',
            brokers: kafka.brokers,
            logLevel: KafkaLogLevel.NOTHING,
        });

        this._consumer = this._kafka.consumer({
            groupId: consumerConfig.groupId || 'model-drift-monitor-group',
            allowAutoTopicCreation: false,
            ...consumerConfig,
        });

        this._producer = this._kafka.producer({
            allowAutoTopicCreation: false,
            ...producerConfig,
        });

        this._subject   = new Subject();       // RxJS entrypoint
        this._sub       = null;                // RxJS subscription handle
    }

    /* ---------------------------------------------------------------------- */
    /*                           Lifecycle Management                         */
    /* ---------------------------------------------------------------------- */

    async start() {
        if (this._ready) {
            this._logger.warn('[DriftMonitor] Already started.');
            return;
        }

        this._logger.info('[DriftMonitor] Initializing Kafka consumer/producer…');
        await Promise.all([
            this._consumer.connect(),
            this._producer.connect(),
        ]);

        await this._consumer.subscribe({ topic: this._topicIn, fromBeginning: false });

        // Forward Kafka events into RxJS pipeline
        await this._consumer.run({
            eachMessage: async ({ message }) => {
                try {
                    // The prediction service publishes JSON lines with at least { label: 'positive' }
                    const payload = JSON.parse(message.value.toString('utf8'));
                    if (payload && payload.label) {
                        this._subject.next(payload.label);
                    }
                } catch (err) {
                    this._logger.error('[DriftMonitor] Failed to parse message:', err);
                }
            },
        });

        this._initializePipeline();

        this._ready = true;
        this._logger.info('[DriftMonitor] Started.');
    }

    async stop() {
        if (!this._ready) return;
        this._logger.info('[DriftMonitor] Shutting down…');

        this._subject.complete();
        await this._sub?.unsubscribe();

        await Promise.allSettled([
            this._consumer.disconnect(),
            this._producer.disconnect(),
        ]);

        this._ready = false;
        this._logger.info('[DriftMonitor] Stopped.');
    }

    /* ---------------------------------------------------------------------- */
    /*                          Internal Implementation                       */
    /* ---------------------------------------------------------------------- */

    _loadBaseline(baselinePath) {
        try {
            const raw = fs.readFileSync(baselinePath, 'utf8');
            const data = JSON.parse(raw);
            if (typeof data !== 'object' || Array.isArray(data)) {
                throw new Error('Baseline must be an object of label:probability pairs');
            }
            return data;
        } catch (err) {
            // Fall back to uniform distribution if no baseline found.
            this._logger.warn(`[DriftMonitor] Could not load baseline (${baselinePath}). Falling back to uniform distribution. Error:`, err.message);
            return { positive: 0.33, negative: 0.33, neutral: 0.34 };
        }
    }

    _initializePipeline() {
        // Aggregate labels for each window, compute divergence, emit drift events.
        this._sub = this._subject.pipe(
            bufferTime(this._windowMs),
            filter(arr => arr.length >= this._minSamples)
        ).subscribe({
            next: async labelsArr => { await this._evaluateWindow(labelsArr); },
            error: err => { this._logger.error('[DriftMonitor] Pipeline error:', err); },
        });
    }

    async _evaluateWindow(labelsArr) {
        const currentDist = toDistribution(labelsArr);
        const divergence  = kullbackLeibler(currentDist, this._baseline);

        this._logger.debug(`[DriftMonitor] K-L divergence: ${divergence.toFixed(4)}`);

        if (divergence >= this._driftThreshold) {
            const alertPayload = {
                timestamp: Date.now(),
                divergence,
                baseline:   this._baseline,
                observed:   currentDist,
                windowSize: labelsArr.length,
                threshold:  this._driftThreshold,
            };

            // Fire internal event listeners
            this.emit('drift', alertPayload);

            // Publish to Kafka topicOut
            try {
                await this._producer.send({
                    topic: this._topicOut,
                    messages: [{ value: JSON.stringify(alertPayload) }],
                });
                this._logger.warn('[DriftMonitor] Drift detected and published.');
            } catch (err) {
                this._logger.error('[DriftMonitor] Failed to publish drift alert:', err);
            }
        }
    }
}

/* -------------------------------------------------------------------------- */
/*                             Module Exports                                 */
/* -------------------------------------------------------------------------- */

module.exports = {
    ModelDriftMonitor,
    kullbackLeibler,
    toDistribution,
};