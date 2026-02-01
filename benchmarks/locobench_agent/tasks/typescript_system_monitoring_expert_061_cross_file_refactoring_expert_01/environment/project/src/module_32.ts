```typescript
/**************************************************************************************************
 *  PulseSphere SocialOps – system_monitoring
 *  File:        src/module_32.ts
 *  Description: Correlates infrastructure metrics with real-time social signals.  The core engine
 *               consumes two asynchronous event streams (metrics + social signals) and calculates
 *               their short-term Pearson correlation inside a sliding time window.  When the
 *               correlation crosses a configured threshold, a `CorrelatedAnomalyEvent` is emitted,
 *               enabling downstream remediation services (auto-scaling, circuit breaking, etc.).
 *
 *  Design notes
 *  ─────────────
 *  • Observer Pattern – `CorrelationEngine` observes `MetricStream` and `SocialSignalStream`.
 *  • Strategy Pattern – interchangeable correlation algorithms (currently Pearson, Spearman).
 *  • Event-Driven    – output is published to the internal EventBus (Kafka/NATS abstraction).
 *  • Resilience      – strong runtime validation, back-pressure awareness, typed errors.
 *
 *  Author:  PulseSphere Core Observability Team
 **************************************************************************************************/

/* eslint-disable @typescript-eslint/no-explicit-any */

import { EventEmitter } from 'events';
import { v4 as uuid } from 'uuid';
import pino from 'pino';

//#region ───────────────────────────────────────  Domain types  ──────────────────────────────────

export enum SocialSignalType {
  LIKE = 'LIKE',
  COMMENT = 'COMMENT',
  SHARE = 'SHARE',
  LIVE_STREAM_VIEW = 'LIVE_STREAM_VIEW',
}

export interface SocialSignal {
  id: string;
  userId: string;
  type: SocialSignalType;
  value: number; // e.g. +1 for like, +N for livestream viewers
  timestamp: number; // epoch millis
  metadata?: Record<string, unknown>;
}

export interface InfraMetric {
  id: string;
  metricName: string;
  value: number;
  timestamp: number; // epoch millis
  tags?: Record<string, string>;
}

export interface CorrelatedAnomalyEvent {
  correlationId: string;
  metricName: string;
  signalType: SocialSignalType;
  correlationScore: number;
  windowSize: number; // number of samples
  startTime: number;
  endTime: number;
  createdAt: number;
}

//#endregion

//#region ──────────────────────────────────────  Config & Errors  ─────────────────────────────────

export interface CorrelationEngineConfig {
  /**
   * Size of the sliding window (in seconds) used for correlation.
   */
  windowInSeconds: number;

  /**
   * Minimum amount of samples required before computing correlation.
   */
  minSamples: number;

  /**
   * Threshold above (absolute) which an anomaly is triggered.
   * For Pearson, valid range is -1..1.
   */
  anomalyThreshold: number;

  /**
   * How often the engine will evaluate and emit correlation events (in milliseconds).
   */
  evaluationIntervalMs: number;
}

export class CorrelationError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'CorrelationError';
  }
}

//#endregion

//#region ──────────────────────────────  Sliding-Window collection  ──────────────────────────────

/**
 * Concurrent-safe, time-bounded sliding window for numeric series.
 */
class SlidingWindow {
  private readonly data: Array<{ t: number; v: number }> = [];

  constructor(private readonly windowMillis: number) {}

  append(value: number, timestamp: number) {
    this.data.push({ t: timestamp, v: value });
    this.trim(timestamp);
  }

  values(): number[] {
    return this.data.map((d) => d.v);
  }

  size(): number {
    return this.data.length;
  }

  /**
   * Removes samples that fall outside of the window.
   */
  private trim(currentTime: number) {
    const threshold = currentTime - this.windowMillis;
    // remove until first element is inside window
    while (this.data.length > 0 && this.data[0].t < threshold) {
      this.data.shift();
    }
  }
}

//#endregion

//#region ────────────────────────────────  Strategy – correlation  ───────────────────────────────

export interface CorrelationStrategy {
  /**
   * Computes correlation coefficient between series X and Y.
   *
   * Both arrays must be of equal length & >0
   */
  compute(x: number[], y: number[]): number;
}

export class PearsonCorrelationStrategy implements CorrelationStrategy {
  /* eslint-disable @typescript-eslint/no-non-null-assertion */
  compute(x: number[], y: number[]): number {
    if (x.length !== y.length || x.length === 0) {
      throw new CorrelationError(
        'Pearson requires two equally-sized, non-empty series.'
      );
    }

    const n = x.length;
    const sumX = x.reduce((a, b) => a + b, 0);
    const sumY = y.reduce((a, b) => a + b, 0);
    const sumX2 = x.reduce((a, b) => a + b * b, 0);
    const sumY2 = y.reduce((a, b) => a + b * b, 0);
    const sumXY = x.reduce((acc, curr, idx) => acc + curr * y[idx]!, 0);

    const numerator = n * sumXY - sumX * sumY;
    const denominator = Math.sqrt(
      (n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY)
    );

    if (denominator === 0) {
      return 0;
    }

    return numerator / denominator;
  }
  /* eslint-enable @typescript-eslint/no-non-null-assertion */
}

//#endregion

//#region ─────────────────────────────────  Event bus (simplified)  ──────────────────────────────

/**
 * Internal EventBus abstraction.  In production we delegate to Kafka or NATS
 * but for local dev / unit testing an EventEmitter is sufficient.
 */
export class EventBus extends EventEmitter {
  publish<T>(topic: string, payload: T) {
    this.emit(topic, payload);
  }

  subscribe<T>(
    topic: string,
    listener: (payload: T) => void
  ): () => void /* unsubscribe */ {
    this.on(topic, listener);
    return () => this.off(topic, listener);
  }
}

//#endregion

//#region ─────────────────────────────────  Correlation Engine  ──────────────────────────────────

export class CorrelationEngine {
  private readonly logger = pino({ name: 'CorrelationEngine' });

  private readonly metricWindow: SlidingWindow;
  private readonly socialWindow: SlidingWindow;

  private metricName: string | null = null;
  private signalType: SocialSignalType | null = null;

  private evaluationTimer?: NodeJS.Timeout;

  constructor(
    private readonly config: CorrelationEngineConfig,
    private readonly strategy: CorrelationStrategy,
    private readonly bus: EventBus
  ) {
    const windowMillis = config.windowInSeconds * 1000;
    this.metricWindow = new SlidingWindow(windowMillis);
    this.socialWindow = new SlidingWindow(windowMillis);
  }

  start(): void {
    if (this.evaluationTimer) return;

    this.logger.info(
      'Starting correlation engine, window=%ds threshold=%d',
      this.config.windowInSeconds,
      this.config.anomalyThreshold
    );

    this.evaluationTimer = setInterval(
      () => this.evaluate(),
      this.config.evaluationIntervalMs
    );
  }

  stop(): void {
    if (this.evaluationTimer) {
      clearInterval(this.evaluationTimer);
      this.evaluationTimer = undefined;
      this.logger.info('Correlation engine stopped.');
    }
  }

  /**
   * Observer callback for infrastructure metrics.
   */
  onMetric(metric: InfraMetric) {
    try {
      if (!Number.isFinite(metric.value)) return;

      this.metricWindow.append(metric.value, metric.timestamp);
      this.metricName ??= metric.metricName; // set first time
      this.logger.debug({ metric }, 'Metric appended to window.');
    } catch (err) {
      this.logger.error({ err, metric }, 'Failed to process metric.');
    }
  }

  /**
   * Observer callback for social signals.
   */
  onSocialSignal(signal: SocialSignal) {
    try {
      if (!Number.isFinite(signal.value)) return;

      this.socialWindow.append(signal.value, signal.timestamp);
      this.signalType ??= signal.type;
      this.logger.debug({ signal }, 'Social signal appended to window.');
    } catch (err) {
      this.logger.error({ err, signal }, 'Failed to process social signal.');
    }
  }

  private evaluate() {
    try {
      if (
        this.metricWindow.size() < this.config.minSamples ||
        this.socialWindow.size() < this.config.minSamples
      ) {
        this.logger.debug(
          'Not enough samples (%d/%d) – skipping evaluation.',
          Math.min(this.metricWindow.size(), this.socialWindow.size()),
          this.config.minSamples
        );
        return;
      }

      const x = this.metricWindow.values();
      const y = this.socialWindow.values();

      // Align lengths (in case sampling rates differ)
      const len = Math.min(x.length, y.length);
      const correlation = this.strategy.compute(
        x.slice(-len),
        y.slice(-len)
      );

      this.logger.debug(
        {
          correlation,
          metricSamples: x.length,
          socialSamples: y.length,
        },
        'Correlation evaluated.'
      );

      if (Math.abs(correlation) >= this.config.anomalyThreshold) {
        const event: CorrelatedAnomalyEvent = {
          correlationId: uuid(),
          metricName: this.metricName ?? 'unknown_metric',
          signalType:
            this.signalType ?? SocialSignalType.LIVE_STREAM_VIEW,
          correlationScore: correlation,
          windowSize: len,
          startTime: Date.now() - this.config.windowInSeconds * 1000,
          endTime: Date.now(),
          createdAt: Date.now(),
        };

        this.logger.warn(
          { event },
          'Correlation anomaly detected, publishing event.'
        );
        this.bus.publish<CorrelatedAnomalyEvent>('correlation.anomaly', event);
      }
    } catch (err) {
      this.logger.error({ err }, 'Failed during correlation evaluation.');
    }
  }
}

//#endregion

//#region ─────────────────────────────────────  Boot-strap helper  ───────────────────────────────

/**
 * Wiring function that registers the engine to the shared EventBus.
 * In production this happens in the DI container of the microservice.
 */
export function bootstrapCorrelationEngine(
  bus: EventBus,
  cfg: Partial<CorrelationEngineConfig> = {}
): CorrelationEngine {
  const defaultConfig: CorrelationEngineConfig = {
    windowInSeconds: 60,
    minSamples: 20,
    anomalyThreshold: 0.85,
    evaluationIntervalMs: 5_000,
  };

  const engine = new CorrelationEngine(
    { ...defaultConfig, ...cfg },
    new PearsonCorrelationStrategy(),
    bus
  );

  // wire observers
  bus.subscribe<InfraMetric>('metrics.ingest', (m) => engine.onMetric(m));
  bus.subscribe<SocialSignal>('social.ingest', (s) => engine.onSocialSignal(s));

  engine.start();
  return engine;
}

//#endregion
```