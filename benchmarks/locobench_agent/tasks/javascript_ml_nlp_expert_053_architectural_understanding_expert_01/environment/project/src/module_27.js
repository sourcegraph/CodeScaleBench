```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Module 27: AdaptiveThresholdMonitor
 *
 * This module listens to a Kafka topic that streams classification
 * results produced by on-line model-serving micro-services.
 * It computes rolling-window metrics (accuracy, toxicity FN rate,
 * fairness gaps, etc.) with RxJS and decides—via pluggable
 * strategy implementations—whether the active model has degraded
 * enough to trigger an automated re-training event.
 *
 * Patterns demonstrated:
 *   • Strategy Pattern         – Different thresholding algorithms
 *   • Factory Pattern          – Constructing strategies from config
 *   • Observer / Reactive Core – Kafka → RxJS pipeline
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

'use strict';

const { Kafka } = require('kafkajs');
const axios = require('axios');
const {
  Subject,
  bufferTime,
  map,
  filter,
  mergeMap,
  tap,
  catchError,
} = require('rxjs');
const _ = require('lodash');

// ---------------------------------------------------------------------------
// Environment & default configuration
// ---------------------------------------------------------------------------

const cfg = {
  kafka: {
    brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
    clientId: process.env.KAFKA_CLIENT_ID ?? 'agorapulse-monitor',
    topicIn: process.env.KAFKA_METRICS_TOPIC ?? 'apulse.classification.metrics',
    topicOut: process.env.KAFKA_RETRAIN_TOPIC ?? 'apulse.model.retrain',
    groupId: process.env.KAFKA_GROUP_ID ?? 'apulse-monitor-group',
  },
  monitoring: {
    windowMs: Number(process.env.MONITOR_WINDOW_MS) || 60_000, // 1 minute window
    emitIfEmpty: false,
    strategy: process.env.MONITOR_STRATEGY ?? 'STATIC_THRESHOLD', // STATIC_THRESHOLD | DRIFT | FAIRNESS
  },
  retrainServiceUrl: process.env.RETRAIN_SERVICE_URL ?? 'http://model-service/api/v1/retrain',
};

// ---------------------------------------------------------------------------
// Utility: Rolling metric aggregator
// ---------------------------------------------------------------------------

class MetricWindow {
  constructor(samples) {
    this.samples = samples;
    this.count = samples.length;
    this.metrics = this._computeStats(samples);
  }

  _computeStats(samples) {
    /* Expected sample shape:
     * {
     *   modelVersion: 'sentiment-v4',
     *   isToxic: false,
     *   trueLabel: 0/1,
     *   predictedLabel: 0/1,
     *   demographic: 'en-US|f'
     * }
     */
    const accuracy =
      _.meanBy(samples, (s) => (s.trueLabel === s.predictedLabel ? 1 : 0)) || 0;

    // Toxicity false-negative rate (FN / all toxic true labels)
    const toxicTruth = samples.filter((s) => s.trueLabel === 1);
    const toxicFN =
      toxicTruth.length === 0
        ? 0
        : toxicTruth.filter((s) => s.predictedLabel === 0).length /
          toxicTruth.length;

    // Fairness gap between two demographic groups as an example
    const [groupA, groupB] = _.partition(
      samples,
      (s) => (s.demographic ?? '').includes('f') // simple gender split
    );
    const accA =
      _.meanBy(groupA, (s) => (s.trueLabel === s.predictedLabel ? 1 : 0)) || 0;
    const accB =
      _.meanBy(groupB, (s) => (s.trueLabel === s.predictedLabel ? 1 : 0)) || 0;

    return {
      accuracy,
      toxicFN,
      fairnessGap: Math.abs(accA - accB),
      modelVersion: _.get(samples, '[0].modelVersion', 'unknown'),
    };
  }
}

// ---------------------------------------------------------------------------
// Strategy interface & implementations
// ---------------------------------------------------------------------------

class ThresholdStrategy {
  /**
   * @param {object} metrics – aggregated metrics for the window
   * @return {boolean}      – whether to trigger retrain
   */
  evaluates(metrics) {
    throw new Error('evaluates() must be implemented');
  }
}

class StaticThresholdStrategy extends ThresholdStrategy {
  constructor({
    minAccuracy = 0.92,
    maxToxicFN = 0.03,
    maxFairnessGap = 0.05,
  } = {}) {
    super();
    this.minAccuracy = minAccuracy;
    this.maxToxicFN = maxToxicFN;
    this.maxFairnessGap = maxFairnessGap;
  }

  evaluates(m) {
    return (
      m.accuracy < this.minAccuracy ||
      m.toxicFN > this.maxToxicFN ||
      m.fairnessGap > this.maxFairnessGap
    );
  }
}

class DriftDetectionStrategy extends ThresholdStrategy {
  /**
   * Naive drift detector comparing current window to a longer baseline.
   * Baseline should be updated externally (e.g., daily job); here we keep
   * it in memory for demo purposes.
   */
  constructor({ epsilon = 0.03 } = {}) {
    super();
    this.epsilon = epsilon;
    this.baseline = null; // will be filled with first window
  }

  evaluates(m) {
    if (!this.baseline) {
      this.baseline = m;
      return false; // no trigger on first window
    }

    const driftDetected =
      Math.abs(m.accuracy - this.baseline.accuracy) > this.epsilon ||
      Math.abs(m.toxicFN - this.baseline.toxicFN) > this.epsilon ||
      Math.abs(m.fairnessGap - this.baseline.fairnessGap) > this.epsilon;

    if (driftDetected) {
      // Reset baseline to avoid duplicate alerts
      this.baseline = m;
    }
    return driftDetected;
  }
}

class FairnessStrategy extends ThresholdStrategy {
  constructor({ maxFairnessGap = 0.03 } = {}) {
    super();
    this.maxFairnessGap = maxFairnessGap;
  }

  evaluates(m) {
    return m.fairnessGap > this.maxFairnessGap;
  }
}

// ---------------------------------------------------------------------------
// Strategy factory
// ---------------------------------------------------------------------------

class StrategyFactory {
  static create(type) {
    switch (type) {
      case 'STATIC_THRESHOLD':
        return new StaticThresholdStrategy();
      case 'DRIFT':
        return new DriftDetectionStrategy();
      case 'FAIRNESS':
        return new FairnessStrategy();
      default:
        throw new Error(`Unknown strategy type: ${type}`);
    }
  }
}

// ---------------------------------------------------------------------------
// Core Monitor
// ---------------------------------------------------------------------------

class AdaptiveThresholdMonitor {
  constructor(config) {
    this.config = _.cloneDeep(config);
    this.kafka = new Kafka({
      clientId: config.kafka.clientId,
      brokers: config.kafka.brokers,
    });

    this.consumer = this.kafka.consumer({ groupId: config.kafka.groupId });
    this.producer = this.kafka.producer();
    this.subject = new Subject(); // RxJS entry point
    this.strategy = StrategyFactory.create(config.monitoring.strategy);
    this.running = false;
  }

  async start() {
    try {
      await this.consumer.connect();
      await this.producer.connect();

      await this.consumer.subscribe({
        topic: this.config.kafka.topicIn,
        fromBeginning: false,
      });

      this.consumer.run({
        eachMessage: async ({ message }) => {
          try {
            const payload = JSON.parse(message.value.toString('utf-8'));
            this.subject.next(payload);
          } catch (err) {
            console.error('Failed to parse incoming metric', err);
          }
        },
      });

      this._setupReactivePipeline();
      this.running = true;
      console.info('[Monitor] AdaptiveThresholdMonitor started.');
    } catch (err) {
      console.error('[Monitor] Failed to start:', err);
      await this.shutdown();
      throw err;
    }
  }

  _setupReactivePipeline() {
    this.subject
      .pipe(
        bufferTime(this.config.monitoring.windowMs, null, undefined, {
          shouldFlush: () => this.config.monitoring.emitIfEmpty,
        }),
        filter((samples) => samples.length > 0),
        map((samples) => new MetricWindow(samples)),
        tap((mw) =>
          console.debug(
            `[Monitor] Metrics for window – accuracy=${mw.metrics.accuracy.toFixed(
              4
            )}, toxicFN=${mw.metrics.toxicFN.toFixed(
              4
            )}, fairnessGap=${mw.metrics.fairnessGap.toFixed(4)}`
          )
        ),
        filter((mw) => {
          const trigger = this.strategy.evaluates(mw.metrics);
          if (trigger) {
            console.warn(
              `[Monitor] Threshold breach detected (strategy=${this.config.monitoring.strategy})`
            );
          }
          return trigger;
        }),
        mergeMap((mw) =>
          this._emitRetrainingEvent(mw.metrics).pipe(
            catchError((err) => {
              console.error('[Monitor] Failed to emit retrain event:', err);
              return []; // swallow error so stream continues
            })
          )
        )
      )
      .subscribe({
        next: (res) => {
          console.info(
            `[Monitor] Retraining event acknowledged: ${JSON.stringify(res)}`
          );
        },
        error: (err) => {
          console.error('[Monitor] Stream error:', err);
        },
      });
  }

  _emitRetrainingEvent(metrics) {
    // Option 1: send to REST retrain service
    const payload = {
      triggeredAt: new Date().toISOString(),
      reason: `Strategy ${this.config.monitoring.strategy} triggered`,
      metrics,
    };

    return (
      axios
        .post(this.config.retrainServiceUrl, payload, {
          timeout: 5000,
        })
        // convert Promise to Observable for mergeMap above
        .then((res) => res.data)
    );

    /* Option 2: or send to Kafka topic
     return from(
       this.producer.send({
         topic: this.config.kafka.topicOut,
         messages: [
           {
             key: String(Date.now()),
             value: JSON.stringify(payload),
           },
         ],
       })
     );
    */
  }

  async shutdown() {
    if (!this.running) return;

    try {
      await this.consumer.disconnect();
      await this.producer.disconnect();
      this.subject.complete();
      console.info('[Monitor] Shutdown complete.');
    } catch (err) {
      console.error('[Monitor] Error during shutdown:', err);
    } finally {
      this.running = false;
    }
  }
}

// ---------------------------------------------------------------------------
// Bootstrap when executed directly
// ---------------------------------------------------------------------------

if (require.main === module) {
  (async () => {
    const monitor = new AdaptiveThresholdMonitor(cfg);

    // Graceful shutdown on SIGTERM/SIGINT
    const handleShutdown = async () => {
      console.info('[Monitor] Caught termination signal, shutting down...');
      await monitor.shutdown();
      process.exit(0);
    };

    process.on('SIGTERM', handleShutdown);
    process.on('SIGINT', handleShutdown);

    try {
      await monitor.start();
    } catch (err) {
      console.error('[Monitor] Fatal error:', err);
      process.exit(1);
    }
  })();
}

module.exports = { AdaptiveThresholdMonitor, StrategyFactory };
```