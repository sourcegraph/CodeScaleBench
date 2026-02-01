```javascript
/**
 * src/module_29.js
 *
 * Real-Time Model Drift Monitor for AgoraPulse
 * -------------------------------------------
 * Listens to prediction/feedback event streams, computes selected drift metrics
 * over sliding time-windows, and publishes “model.drift.detected” domain events
 * when thresholds are breached.  Uses RxJS for reactive windowing, incorporates
 * Strategy Pattern for pluggable drift metrics, and exponential back-off retry
 * when emitting events to Kafka.
 *
 * NOTE: This module purposefully contains no direct Kafka implementation in order
 * to remain testable and side-effect free.  Callers must inject an
 * `IEventBus` implementation that exposes `publish(topic, message)` and
 * `events$(topic)` returning an RxJS Observable.
 *
 * Author: AgoraPulse Engineering
 * License: MIT
 */

import { Observable, timer, merge, EMPTY, throwError } from 'rxjs';
import {
  bufferTime,
  catchError,
  filter,
  map,
  mergeMap,
  retryWhen,
  scan,
  share,
  switchMap,
  tap,
} from 'rxjs/operators';
import EventEmitter from 'events';
import { mean, isNumber } from 'lodash';

/**
 * ------------------------------------------
 * Types & Interfaces
 * ------------------------------------------
 */

/**
 * @typedef {Object} PredictionEvent
 * @property {string} modelId
 * @property {number[]} probabilities – Soft-max array over classes
 * @property {number} timestamp        – Unix millis
 */

/**
 * @typedef {Object} FeedbackEvent
 * @property {string} modelId
 * @property {number} trueLabel        – Ground-truth label index
 * @property {number} timestamp
 */

/**
 * @typedef {Object} DriftAlert
 * @property {string} modelId
 * @property {string} metric           – Name of drift metric
 * @property {number} value            – Raw metric value
 * @property {number} threshold        – Configured threshold
 * @property {number} windowMillis
 */

/**
 * @typedef {Object} DriftMetricContext
 * @property {PredictionEvent[]} predictions
 * @property {FeedbackEvent[]} feedbacks
 */

/**
 * @callback DriftMetricFn
 * @param {DriftMetricContext} ctx
 * @returns {number}  – Computed metric value
 */

/**
 * Pluggable metric strategy definition
 */
export class DriftMetricStrategy {
  /**
   * @param {string} name
   * @param {DriftMetricFn} fn
   */
  constructor(name, fn) {
    this.name = name;
    this.fn = fn;
  }

  /**
   * Compute the metric for provided context
   * @param {DriftMetricContext} ctx
   * @returns {number}
   */
  compute(ctx) {
    return this.fn(ctx);
  }
}

/**
 * ------------------------------------------
 * Built-in Metric Strategies
 * ------------------------------------------
 */

/**
 * Simple Accuracy Delta metric.
 * Computes absolute delta between current accuracy and reference baseline.
 *
 * Baseline is passed at construction and stored in closure.
 */
export const accuracyDeltaMetric = (baselineAccuracy) =>
  new DriftMetricStrategy('accuracy_delta', ({ predictions, feedbacks }) => {
    if (predictions.length === 0 || feedbacks.length === 0) return 0;

    // Map prediction array to hard labels
    const hardPreds = predictions.map((p) => p.probabilities.indexOf(Math.max(...p.probabilities)));

    // Join by time proximity (max 200ms skew)
    const joined = hardPreds.reduce(
      (acc, predLabel, idx) => {
        const predTs = predictions[idx].timestamp;
        const match = feedbacks.find((f) => Math.abs(f.timestamp - predTs) < 200);
        if (match) {
          acc.total++;
          if (match.trueLabel === predLabel) acc.correct++;
        }
        return acc;
      },
      { total: 0, correct: 0 }
    );

    if (joined.total === 0) return 0;

    const currentAcc = joined.correct / joined.total;
    return Math.abs(baselineAccuracy - currentAcc);
  });

/**
 * KL-Divergence between current prediction distribution and baseline
 * Baseline distribution passed at construction
 */
export const klDivergenceMetric = (baselineProbDist) =>
  new DriftMetricStrategy('kl_divergence', ({ predictions }) => {
    if (predictions.length === 0) return 0;

    const dims = baselineProbDist.length;
    const runningSum = new Array(dims).fill(0);

    predictions.forEach((p) => {
      p.probabilities.forEach((prob, i) => {
        runningSum[i] += prob;
      });
    });

    const currentDist = runningSum.map((x) => x / predictions.length);

    // Smooth to avoid log(0)
    const EPS = 1e-12;

    const kl = currentDist.reduce((acc, p, i) => {
      const q = baselineProbDist[i] + EPS;
      const pAdj = p + EPS;
      return acc + pAdj * Math.log(pAdj / q);
    }, 0);

    return kl;
  });

/**
 * ------------------------------------------
 * Retry / Backoff helper
 * ------------------------------------------
 */

/**
 * Generic exponential back-off with jitter
 * @param {number} maxRetries
 * @param {number} baseDelayMs
 */
const expBackoff = (maxRetries = 5, baseDelayMs = 250) => (errors) =>
  errors.pipe(
    scan((acc, err) => {
      if (acc.retryCount >= maxRetries) {
        throw err;
      }
      return { retryCount: acc.retryCount + 1, err };
    }, {
      retryCount: 0,
      err: null
    }),
    switchMap(({ retryCount, err }) => {
      const backoffDelay = baseDelayMs * Math.pow(2, retryCount);
      const jitter = Math.floor(Math.random() * baseDelayMs);
      console.warn(
        `[DriftMonitor] publish failed: ${err.message}. ` +
          `retry #${retryCount} in ${backoffDelay + jitter}ms`
      );
      return timer(backoffDelay + jitter);
    })
  );

/**
 * ------------------------------------------
 * Core Monitor Class
 * ------------------------------------------
 */

export class RealTimeDriftMonitor extends EventEmitter {
  /**
   * @param {{
   *   eventBus: {
   *     publish(topic: string, msg: any): Promise<void>,
   *     events$(topic: string): Observable<any>
   *   },
   *   windowMillis: number,
   *   metrics: {
   *     strategy: DriftMetricStrategy,
   *     threshold: number
   *   }[],
   *   monitoredModelId: string,
   *   publishTopic?: string
   * }} params
   */
  constructor({
    eventBus,
    windowMillis = 60_000,
    metrics = [],
    monitoredModelId,
    publishTopic = 'model.drift.detected',
  }) {
    super();

    if (!eventBus || !eventBus.publish || !eventBus.events$) {
      throw new Error('eventBus must implement publish() and events$()');
    }

    this.eventBus = eventBus;
    this.windowMillis = windowMillis;
    this.metrics = metrics;
    this.modelId = monitoredModelId;
    this.publishTopic = publishTopic;

    this._buildPipeline();
  }

  /**
   * Builds the RxJS pipeline
   * Creates windowed buffers for predictions and feedbacks
   * Computes metrics & triggers alert publishing
   * @private
   */
  _buildPipeline() {
    // Shared streams
    const prediction$ = this.eventBus
      .events$('model.prediction')
      .pipe(
        filter((evt) => evt.modelId === this.modelId),
        share()
      );

    const feedback$ = this.eventBus
      .events$('model.feedback')
      .pipe(
        filter((evt) => evt.modelId === this.modelId),
        share()
      );

    // Windowed buffers
    const predictionWindow$ = prediction$.pipe(bufferTime(this.windowMillis));
    const feedbackWindow$ = feedback$.pipe(bufferTime(this.windowMillis));

    // Combine windows when either arrives
    const evaluation$ = merge(predictionWindow$, feedbackWindow$).pipe(
      // Wait until both windows have emitted at least once
      scan(
        (acc, curr) => {
          if (isPredictionWindow(curr)) {
            acc.predictions = curr;
          } else {
            acc.feedbacks = curr;
          }
          return acc;
        },
        { predictions: [], feedbacks: [] }
      ),
      filter((ctx) => ctx.predictions.length > 0), // require predictions window
      map((ctx) => ({ ...ctx })) // shallow copy
    );

    // Evaluate each configured metric
    evaluation$
      .pipe(
        mergeMap((ctx) =>
          merge(
            ...this.metrics.map((metricCfg) =>
              this._evaluateMetric(ctx, metricCfg).pipe(
                catchError((err) => {
                  console.error('[DriftMonitor] metric evaluation error', err);
                  return EMPTY;
                })
              )
            )
          )
        )
      )
      .subscribe({
        next: (alert) => this._emitAlert(alert),
        error: (err) => console.error('[DriftMonitor] pipeline error', err),
      });
  }

  /**
   * Evaluate a single metric configuration
   * @param {DriftMetricContext} ctx
   * @param {{strategy: DriftMetricStrategy, threshold: number}} metricCfg
   * @returns {Observable<DriftAlert>}
   * @private
   */
  _evaluateMetric(ctx, metricCfg) {
    return new Observable((subscriber) => {
      try {
        const value = metricCfg.strategy.compute(ctx);

        if (!isNumber(value) || Number.isNaN(value) || !Number.isFinite(value)) {
          throw new Error(
            `Metric ${metricCfg.strategy.name} produced invalid value ${value}`
          );
        }

        if (value >= metricCfg.threshold) {
          const alert = /** @type {DriftAlert} */ ({
            modelId: this.modelId,
            metric: metricCfg.strategy.name,
            value,
            threshold: metricCfg.threshold,
            windowMillis: this.windowMillis,
          });
          subscriber.next(alert);
        }
        subscriber.complete();
      } catch (err) {
        subscriber.error(err);
      }
    });
  }

  /**
   * Emits alert via eventBus with retry and also via internal EventEmitter
   * @param {DriftAlert} alert
   * @private
   */
  _emitAlert(alert) {
    // Fire locally
    this.emit('drift', alert);

    // Publish to external bus with retry/backoff
    // Wrap promise so we can .pipe on it
    Observable.defer(() => this.eventBus.publish(this.publishTopic, alert))
      .pipe(retryWhen(expBackoff()))
      .subscribe({
        error: (err) =>
          console.error('[DriftMonitor] failed to publish alert', err),
      });
  }
}

/**
 * Type predicate to help flow analysis
 * @param {any[]} arr
 * @returns {boolean}
 */
function isPredictionWindow(arr) {
  return arr.length === 0 || 'probabilities' in arr[0];
}
```