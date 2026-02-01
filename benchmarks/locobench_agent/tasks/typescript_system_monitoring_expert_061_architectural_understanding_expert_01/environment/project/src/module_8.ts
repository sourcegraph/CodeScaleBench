```typescript
/**
 * PulseSphere SocialOps
 * File: src/module_8.ts
 *
 * Purpose:
 *  • Collect low–level infrastructure metrics AND social-interaction signals
 *  • Aggregate them in configurable time-windows
 *  • Evaluate them through pluggable scaling strategies (Strategy Pattern)
 *  • Emit actionable ScalingDecision events that can be handled by an
 *    auto-remediation micro-service (e.g. K8s HPA controller wrapper)
 *
 *  This module purposefully avoids direct dependencies on concrete
 *  message-buses (Kafka/NATS) to keep it self-contained; instead it
 *  utilises Node’s EventEmitter so that higher-level adapters can bridge
 *  inbound/outbound events to the platform’s real event backbone.
 */

import { EventEmitter } from 'events';

/* ------------------------------------------------------------------ */
/*  Domain Types                                                      */
/* ------------------------------------------------------------------ */

/**
 * Infrastructure metrics we actively care about for scaling decisions.
 */
export enum SystemMetricType {
  CPU = 'cpu',
  MEMORY = 'memory',
  RPS = 'request_per_sec',
}

/**
 * Social engagement signals flowing into the observability fabric.
 */
export enum SocialInteractionType {
  LIKE = 'like',
  COMMENT = 'comment',
  SHARE = 'share',
  STREAM_VIEW = 'stream_view',
}

/**
 * Raw infrastructure metric emitted by telemetry collectors.
 */
export interface SystemMetricEvent {
  timestamp: number; // epoch millis
  microservice: string;
  type: SystemMetricType;
  value: number; // e.g. CPU: 0-100 %, MEM: MB, RPS: req/sec
}

/**
 * Raw social-interaction metric emitted by social-context collectors.
 */
export interface SocialInteractionEvent {
  timestamp: number; // epoch millis
  type: SocialInteractionType;
  count: number;
  userSegment?: string; // Optionally segment audience
}

/**
 * Windowed aggregation of metrics and interactions.
 */
export interface AggregatedMetrics {
  windowMs: number;

  cpuAvg: number; // %
  memoryAvg: number; // MB
  rpsAvg: number; // req/s

  interactionsPerSec: number; // aggregated across all social types
}

/**
 * Decision produced by a ScalingStrategy.
 */
export interface ScalingDecision {
  readonly action: 'scale_out' | 'scale_in' | 'no_action';
  readonly reason: string;
  /**
   * Suggested replica target. Optional when action === 'no_action'
   * Consumers MUST validate with min/max replica limits.
   */
  readonly targetReplicas?: number;
}

/**
 * Additional context delivered to a strategy during evaluation.
 */
export interface ScalingContext {
  readonly metrics: AggregatedMetrics;
  readonly currentReplicas: number;
  readonly minReplicas: number;
  readonly maxReplicas: number;
}

/* ------------------------------------------------------------------ */
/*  Metrics Aggregator (Observer Pattern)                             */
/* ------------------------------------------------------------------ */

export interface MetricsAggregatorEvents {
  aggregated: (data: AggregatedMetrics) => void;
}

/**
 * Simple ring-buffer aggregator.
 * Emits 'aggregated' events every `emitIntervalMs` with the averaged stats
 * of the previous `windowMs` interval.
 */
export class MetricsAggregator extends EventEmitter {
  private readonly windowMs: number;
  private readonly emitIntervalMs: number;

  // In-memory buffers (time-series)
  private systemMetrics: SystemMetricEvent[] = [];
  private socialMetrics: SocialInteractionEvent[] = [];

  private emitTimer?: NodeJS.Timeout;

  constructor(opts: { windowMs?: number; emitIntervalMs?: number }) {
    super();
    this.windowMs = opts.windowMs ?? 30_000;
    this.emitIntervalMs = opts.emitIntervalMs ?? 10_000;
  }

  /** Start periodic aggregation */
  public start(): void {
    if (!this.emitTimer) {
      this.emitTimer = setInterval(() => this.aggregate(), this.emitIntervalMs);
    }
  }

  /** Stop periodic aggregation */
  public stop(): void {
    if (this.emitTimer) {
      clearInterval(this.emitTimer);
      this.emitTimer = undefined;
    }
  }

  /** Ingest infrastructure metric. Called by upstream collectors. */
  public ingestSystemMetric(event: SystemMetricEvent): void {
    this.systemMetrics.push(event);
    this.trimBuffers();
  }

  /** Ingest social-interaction metric. */
  public ingestSocialMetric(event: SocialInteractionEvent): void {
    this.socialMetrics.push(event);
    this.trimBuffers();
  }

  /** Perform aggregation and emit result */
  private aggregate(): void {
    try {
      const now = Date.now();
      const from = now - this.windowMs;

      const sysWindow = this.systemMetrics.filter((e) => e.timestamp >= from);
      const socialWindow = this.socialMetrics.filter((e) => e.timestamp >= from);

      const agg: AggregatedMetrics = {
        windowMs: this.windowMs,
        cpuAvg: avg(sysWindow.filter((e) => e.type === SystemMetricType.CPU).map((e) => e.value)),
        memoryAvg: avg(
          sysWindow.filter((e) => e.type === SystemMetricType.MEMORY).map((e) => e.value),
        ),
        rpsAvg: avg(
          sysWindow.filter((e) => e.type === SystemMetricType.RPS).map((e) => e.value),
        ),
        interactionsPerSec:
          sum(socialWindow.map((e) => e.count)) / (this.windowMs / 1_000),
      };

      this.emit('aggregated', agg);
    } catch (err) {
      // In production we would instrument this path for error alerts
      console.error('[MetricsAggregator] aggregation failed: %o', err);
    }
  }

  /** Remove events outside the aggregation window to keep memory bounded */
  private trimBuffers(): void {
    const cutoff = Date.now() - this.windowMs * 2; // keep double window for overlap
    this.systemMetrics = this.systemMetrics.filter((e) => e.timestamp >= cutoff);
    this.socialMetrics = this.socialMetrics.filter((e) => e.timestamp >= cutoff);
  }
}

/* ------------------------------------------------------------------ */
/*  Strategy Pattern ‑ Pluggable scaling policies                     */
/* ------------------------------------------------------------------ */

/**
 * Strategy interface
 */
export interface ScalingStrategy {
  /**
   * Supply current context and receive a decision. MUST be side-effect free.
   */
  evaluate(ctx: ScalingContext): ScalingDecision;
}

/**
 * Scale out aggressively when CPU > cpuThreshold AND interactions increasing.
 */
export class SentimentBoostScalingStrategy implements ScalingStrategy {
  constructor(
    private readonly cpuThreshold: number = 70, // %
    private readonly interactionsThreshold: number = 500, // per-sec
  ) {}

  evaluate(ctx: ScalingContext): ScalingDecision {
    const { metrics, currentReplicas, maxReplicas } = ctx;

    const cpuHot = metrics.cpuAvg >= this.cpuThreshold;
    const socialHot = metrics.interactionsPerSec >= this.interactionsThreshold;

    if (cpuHot && socialHot && currentReplicas < maxReplicas) {
      const target = Math.min(maxReplicas, currentReplicas + Math.ceil(currentReplicas * 0.5));
      return {
        action: 'scale_out',
        targetReplicas: target,
        reason: `CPU (${metrics.cpuAvg.toFixed(
          1,
        )}%) + High social boost (${metrics.interactionsPerSec.toFixed(0)}/s)`,
      };
    }

    return { action: 'no_action', reason: 'Thresholds not exceeded' };
  }
}

/**
 * Conservative CPU-only reactive strategy.
 */
export class ReactiveCpuScalingStrategy implements ScalingStrategy {
  constructor(
    private readonly scaleOutThreshold: number = 80,
    private readonly scaleInThreshold: number = 40,
    private readonly step: number = 1,
  ) {}

  evaluate(ctx: ScalingContext): ScalingDecision {
    const { metrics, currentReplicas, minReplicas, maxReplicas } = ctx;

    if (metrics.cpuAvg >= this.scaleOutThreshold && currentReplicas < maxReplicas) {
      return {
        action: 'scale_out',
        targetReplicas: Math.min(maxReplicas, currentReplicas + this.step),
        reason: `CPU ${metrics.cpuAvg.toFixed(1)}% >= ${this.scaleOutThreshold}%`,
      };
    }

    if (metrics.cpuAvg <= this.scaleInThreshold && currentReplicas > minReplicas) {
      return {
        action: 'scale_in',
        targetReplicas: Math.max(minReplicas, currentReplicas - this.step),
        reason: `CPU ${metrics.cpuAvg.toFixed(1)}% <= ${this.scaleInThreshold}%`,
      };
    }

    return { action: 'no_action', reason: 'Within CPU thresholds' };
  }
}

/**
 * Composite strategy – chains multiple strategies and picks the first
 * actionable decision (Chain-of-Responsibility pattern).
 */
export class CompositeScalingStrategy implements ScalingStrategy {
  constructor(private readonly strategies: ScalingStrategy[]) {}

  evaluate(ctx: ScalingContext): ScalingDecision {
    for (const strat of this.strategies) {
      const decision = strat.evaluate(ctx);
      if (decision.action !== 'no_action') {
        return decision;
      }
    }
    return { action: 'no_action', reason: 'No strategy triggered' };
  }
}

/* ------------------------------------------------------------------ */
/*  Scaling Advisor (Observer + Strategy)                             */
/* ------------------------------------------------------------------ */

export interface ScalingAdvisorEvents {
  decision: (decision: ScalingDecision) => void;
}

/**
 * Subscribes to MetricsAggregator → Feeds selected ScalingStrategy →
 * Emits ScalingDecision events.
 */
export class ScalingAdvisor extends EventEmitter {
  private currentReplicas: number;
  private readonly minReplicas: number;
  private readonly maxReplicas: number;
  private readonly strategy: ScalingStrategy;

  constructor(opts: {
    aggregator: MetricsAggregator;
    strategy: ScalingStrategy;
    minReplicas?: number;
    maxReplicas?: number;
    initialReplicas?: number;
  }) {
    super();

    this.strategy = opts.strategy;
    this.minReplicas = opts.minReplicas ?? 2;
    this.maxReplicas = opts.maxReplicas ?? 100;
    this.currentReplicas = opts.initialReplicas ?? this.minReplicas;

    // Subscribe to aggregated metrics
    opts.aggregator.on('aggregated', (metrics) => this.onAggregated(metrics));
  }

  /** Called each time a new aggregation window is emitted */
  private onAggregated(metrics: AggregatedMetrics): void {
    try {
      const ctx: ScalingContext = {
        metrics,
        currentReplicas: this.currentReplicas,
        minReplicas: this.minReplicas,
        maxReplicas: this.maxReplicas,
      };

      const decision = this.strategy.evaluate(ctx);

      if (decision.action !== 'no_action' && decision.targetReplicas != null) {
        this.currentReplicas = decision.targetReplicas;
      }

      this.emit('decision', decision);
    } catch (err) {
      console.error('[ScalingAdvisor] evaluation failed: %o', err);
    }
  }
}

/* ------------------------------------------------------------------ */
/*  Helper functions                                                  */
/* ------------------------------------------------------------------ */

function avg(arr: number[]): number {
  return arr.length ? sum(arr) / arr.length : 0;
}

function sum(arr: number[]): number {
  return arr.reduce((a, b) => a + b, 0);
}
```