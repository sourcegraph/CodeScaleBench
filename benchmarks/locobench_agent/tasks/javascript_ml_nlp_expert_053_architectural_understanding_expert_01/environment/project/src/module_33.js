```javascript
/******************************************************************************************
 *  AgoraPulse: Real-Time Social Signal Intelligence ‑ ml_nlp
 *  ---------------------------------------------------------------------------------------
 *  File:          src/module_33.js
 *  Description:   Real-time model-quality monitor that subscribes to the model-serving
 *                 Kafka topic, computes windowed quality metrics (accuracy, precision,
 *                 recall, F1) per model version, and emits domain events whenever
 *                 performance degradation crosses dynamic thresholds.
 *  ------------------------------------------------------------------------------------------------
 *  Author:        AgoraPulse Engineering
 *  License:       MIT
 ******************************************************************************************/

/* eslint-disable  no-console */

import EventEmitter from 'events';
import path from 'path';
import fs from 'fs';
import { KafkaConsumer } from 'node-rdkafka';
import {
  Subject,
  timer,
  EMPTY,
} from 'rxjs';
import {
  bufferTime,
  filter,
  groupBy,
  map,
  mergeMap,
  catchError,
} from 'rxjs/operators';

//////////////////////////////////////////////////////////////////////////////////////////
// Configuration
//////////////////////////////////////////////////////////////////////////////////////////

const CONFIG_PATH = process.env.AGORA_CONFIG_PATH
  || path.join(process.cwd(), 'config', 'monitoring.json');

let config = {
  kafka: {
    brokers: 'localhost:9092',
    topic: 'agorapulse.model.predictions',
    groupId: 'agorapulse-model-monitor',
  },
  monitoring: {
    windowSizeSec: 60,
    slideIntervalSec: 10,
    minSamples: 100,
    alertThreshold: 0.02, // 2% drop
  },
};

try {
  if (fs.existsSync(CONFIG_PATH)) {
    const fileCfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
    config = {
      ...config,
      ...fileCfg,
    };
  }
} catch (err) {
  // Config errors should not crash the process; log and continue with defaults.
  console.warn(`(module_33) Failed to read monitoring config: ${err.message}`);
}

//////////////////////////////////////////////////////////////////////////////////////////
// Helper types / utilities
//////////////////////////////////////////////////////////////////////////////////////////

/**
 * Confusion matrix aggregator for binary classifiers.
 * Supports streaming updates & metric calculations.
 */
class ConfusionMatrix {
  tp = 0;

  fp = 0;

  tn = 0;

  fn = 0;

  add(predicted, actual) {
    // Accept Boolean or 0/1
    const p = typeof predicted === 'boolean' ? predicted : Boolean(predicted);
    const a = typeof actual === 'boolean' ? actual : Boolean(actual);

    if (p && a) this.tp += 1;
    else if (p && !a) this.fp += 1;
    else if (!p && a) this.fn += 1;
    else this.tn += 1;
  }

  get total() {
    return this.tp + this.fp + this.tn + this.fn;
  }

  accuracy() {
    const { tp, tn } = this;
    const { total } = this;
    return total === 0 ? 0 : (tp + tn) / total;
  }

  precision() {
    const { tp, fp } = this;
    return tp + fp === 0 ? 0 : tp / (tp + fp);
  }

  recall() {
    const { tp, fn } = this;
    return tp + fn === 0 ? 0 : tp / (tp + fn);
  }

  f1() {
    const p = this.precision();
    const r = this.recall();
    return p + r === 0 ? 0 : (2 * p * r) / (p + r);
  }

  snapshot() {
    return {
      tp: this.tp,
      fp: this.fp,
      tn: this.tn,
      fn: this.fn,
      accuracy: this.accuracy(),
      precision: this.precision(),
      recall: this.recall(),
      f1: this.f1(),
      total: this.total,
    };
  }
}

/**
 * Sliding window metrics aggregator.
 * Keeps the last N windows to smooth alerts.
 */
class SlidingWindowMetrics {
  constructor(maxWindows = 6) {
    this.maxWindows = maxWindows;
    this.windows = [];
  }

  push(metrics) {
    if (this.windows.length >= this.maxWindows) {
      this.windows.shift();
    }
    this.windows.push(metrics);
  }

  /**
   * Get averaged metrics across all held windows.
   */
  average() {
    if (this.windows.length === 0) {
      return null;
    }
    const sum = this.windows.reduce(
      (acc, cur) => {
        acc.accuracy += cur.accuracy;
        acc.precision += cur.precision;
        acc.recall += cur.recall;
        acc.f1 += cur.f1;
        acc.count += 1;
        return acc;
      },
      { accuracy: 0, precision: 0, recall: 0, f1: 0, count: 0 },
    );

    const { count } = sum;
    return {
      accuracy: sum.accuracy / count,
      precision: sum.precision / count,
      recall: sum.recall / count,
      f1: sum.f1 / count,
    };
  }
}

//////////////////////////////////////////////////////////////////////////////////////////
// Core Monitor Class
//////////////////////////////////////////////////////////////////////////////////////////

/**
 * Real-time model-monitor service.
 * Emits:
 *   - 'metrics'  : { modelVersion, metrics }
 *   - 'drift'    : { modelVersion, previousMetrics, currentMetrics }
 *   - 'error'    : Error
 */
export class ModelPerformanceMonitor extends EventEmitter {
  constructor(cfg = config) {
    super();
    this.cfg = cfg;
    this.kafkaConsumer = null;
    this.msgSubject = new Subject();
    this.metricWindows = new Map(); // modelVersion -> SlidingWindowMetrics
    this.currentBaseline = null; // String model version id
    this._initStreams();
  }

  ////////////////////////////////////////////////////////////////////////////
  // Public API
  ////////////////////////////////////////////////////////////////////////////

  async start() {
    try {
      await this._initKafka();
      this.kafkaConsumer.consume();
      console.log('(module_33) ModelPerformanceMonitor started.');
    } catch (err) {
      this.emit('error', err);
    }
  }

  async stop() {
    try {
      this.msgSubject.complete();
      if (this.kafkaConsumer) {
        await new Promise((resolve) => {
          this.kafkaConsumer.disconnect(() => resolve());
        });
      }
      console.log('(module_33) ModelPerformanceMonitor stopped.');
    } catch (err) {
      this.emit('error', err);
    }
  }

  ////////////////////////////////////////////////////////////////////////////
  // Initialization helpers
  ////////////////////////////////////////////////////////////////////////////

  _initKafka() {
    return new Promise((resolve, reject) => {
      const {
        brokers, groupId, topic,
      } = this.cfg.kafka;

      const consumer = new KafkaConsumer(
        {
          'group.id': groupId,
          'metadata.broker.list': brokers,
          'enable.auto.commit': true,
        },
        {},
      );

      consumer
        .on('ready', () => {
          consumer.subscribe([topic]);
          this.kafkaConsumer = consumer;

          consumer.on('data', (data) => {
            try {
              const message = JSON.parse(data.value.toString());
              this.msgSubject.next(message);
            } catch (err) {
              // Skip malformed message
              this.emit('error', new Error(`Malformed Kafka message: ${err.message}`));
            }
          });

          resolve();
        })
        .on('event.error', reject);

      consumer.connect();
    });
  }

  /**
   * Build the reactive pipeline that:
   *   - Buffers messages into window size
   *   - Groups by model version
   *   - Computes metrics
   *   - Maintains sliding windows
   *   - Detects degradation
   */
  _initStreams() {
    const {
      windowSizeSec,
      slideIntervalSec,
      minSamples,
      alertThreshold,
    } = this.cfg.monitoring;

    // Timer driving sliding windows
    const heartbeat$ = timer(0, slideIntervalSec * 1_000);

    heartbeat$
      .pipe(
        mergeMap(() => this.msgSubject.pipe(
          bufferTime(windowSizeSec * 1_000),
          filter((batch) => batch && batch.length > 0),
        )),
        // Each batch is the messages in the window
        mergeMap((batch) => {
          // Group by model version
          const groups = new Map();
          batch.forEach((msg) => {
            const { modelVersion } = msg;
            if (!groups.has(modelVersion)) {
              groups.set(modelVersion, []);
            }
            groups.get(modelVersion).push(msg);
          });
          return Array.from(groups.entries());
        }),
        // [modelVersion, messages[]]
        mergeMap(([modelVersion, messages]) => {
          const matrix = new ConfusionMatrix();
          messages.forEach(({ predicted, actual }) => {
            matrix.add(predicted, actual);
          });

          const snapshot = matrix.snapshot();

          return [
            {
              modelVersion,
              snapshot,
            },
          ];
        }),
        catchError((err) => {
          this.emit('error', err);
          return EMPTY; // Swallow error for stream continuity
        }),
      )
      .subscribe({
        next: ({
          modelVersion,
          snapshot,
        }) => {
          if (snapshot.total < minSamples) {
            return; // Not enough data to be meaningful
          }

          // Update sliding window
          const windowAgg = this._getOrCreateWindow(modelVersion);
          windowAgg.push(snapshot);

          // Determine baseline automatically if not set
          if (!this.currentBaseline) {
            this.currentBaseline = modelVersion;
          }

          const avgMetrics = windowAgg.average();

          // Emit metrics event
          this.emit('metrics', {
            modelVersion,
            metrics: avgMetrics,
          });

          // Compare against baseline
          if (modelVersion !== this.currentBaseline) {
            const baselineMetrics = this.metricWindows
              .get(this.currentBaseline)?.average();

            if (baselineMetrics) {
              // Drift if F1 drop exceeds threshold
              const delta = baselineMetrics.f1 - avgMetrics.f1;
              if (delta > alertThreshold) {
                this.emit('drift', {
                  modelVersion,
                  previousMetrics: baselineMetrics,
                  currentMetrics: avgMetrics,
                  delta,
                });
              }
            }
          }
        },
      });
  }

  _getOrCreateWindow(modelVersion) {
    if (!this.metricWindows.has(modelVersion)) {
      this.metricWindows.set(
        modelVersion,
        new SlidingWindowMetrics(
          Math.floor(
            (this.cfg.monitoring.windowSizeSec
              / this.cfg.monitoring.slideIntervalSec),
          ),
        ),
      );
    }
    return this.metricWindows.get(modelVersion);
  }
}

//////////////////////////////////////////////////////////////////////////////////////////
// Self-execute when launched directly ‑ allows standalone daemon execution
//////////////////////////////////////////////////////////////////////////////////////////

if (require.main === module) {
  const monitor = new ModelPerformanceMonitor();

  monitor.on('metrics', ({ modelVersion, metrics }) => {
    console.log(`[metrics] v=${modelVersion} f1=${metrics.f1.toFixed(3)} acc=${metrics.accuracy.toFixed(3)}`);
  });

  monitor.on('drift', ({
    modelVersion, delta, currentMetrics, previousMetrics,
  }) => {
    console.warn(`[drift] Model ${modelVersion} dropped by ${(delta * 100).toFixed(2)}% F1`);
    // Persist drift event for downstream consumers
    // In production this would emit to another Kafka topic.
  });

  monitor.on('error', (err) => {
    console.error(`[error] ${err.stack}`);
  });

  /* Graceful shutdown */
  process.on('SIGINT', async () => {
    console.log('\nStopping ModelPerformanceMonitor...');
    await monitor.stop();
    process.exit(0);
  });

  monitor.start().catch((err) => console.error(err));
}
```