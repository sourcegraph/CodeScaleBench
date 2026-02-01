```typescript
/**************************************************************************************************
 *  File:        src/module_44.ts
 *  Project:     PulseSphere SocialOps (system_monitoring)
 *  Description: Capacity orchestration module. Consumes social-interaction signals + infra metrics
 *               and issues scale-up / scale-down commands through an event bus. Implements the
 *               Strategy Pattern, allowing run-time swapping of orchestration algorithms.
 *
 *  NOTE: This module purposefully avoids direct Kafka/NATS dependencies to keep it self-contained
 *        for unit-testing. Production wiring lives in the IoC container where concrete transport
 *        adapters are injected.
 **************************************************************************************************/

/* eslint-disable no-console */

import { EventEmitter } from 'events';
import { setTimeout as safeSetTimeout } from 'timers/promises'; // Node 16+
import { randomUUID } from 'crypto';

/* -------------------------------------------------------------------------- */
/*                            🔌 Domain Interfaces                            */
/* -------------------------------------------------------------------------- */

/** Re-usable subset of all telemetry events emitted by upstream micro-services. */
export interface SocialPulseEvent {
  kind: 'social';
  hashtag?: string;
  likes: number;
  comments: number;
  shares: number;
  liveStreamViewers: number;
  timestamp: number; // epoch millis
}

export interface InfraMetricsEvent {
  kind: 'infra';
  cpuUsage: number; // percentage (0-100)
  rps: number;      // requests / second
  errorRate: number; // percentage (0-100)
  podCount: number;
  timestamp: number; // epoch millis
}

/** Union of supported telemetry payloads. */
export type TelemetryEvent = SocialPulseEvent | InfraMetricsEvent;

/** Command emitted by this module toward the platform’s orchestration subsystem. */
export interface OrchestrationCommand {
  id: string;
  action: 'scale_up' | 'scale_down' | 'hold';
  delta: number;          // #pods to add/remove
  reason: string;
  createdAt: number;      // epoch millis
}

/* -------------------------------------------------------------------------- */
/*                         ⚙️ Strategy Pattern Contracts                      */
/* -------------------------------------------------------------------------- */

export interface OrchestrationContext {
  social: AggregatedSocialStats;
  infra: AggregatedInfraStats;
}

export interface OrchestrationStrategy {
  /**
   * Human-readable strategy name.
   */
  readonly name: string;

  /**
   * Return a scaling decision based on the provided aggregated state.
   * Implementers must be side-effect free.
   */
  evaluate(ctx: OrchestrationContext): OrchestrationCommand;
}

/* -------------------------------------------------------------------------- */
/*                              📊 Aggregation Types                          */
/* -------------------------------------------------------------------------- */

export interface AggregatedSocialStats {
  likesPerSec: number;
  commentsPerSec: number;
  sharesPerSec: number;
  liveViewers: number;
  trendingScore: number; // weighted sum
}

export interface AggregatedInfraStats {
  avgCpu: number;
  peakRps: number;
  errorRate: number;
  currentPods: number;
}

/* -------------------------------------------------------------------------- */
/*                       🧮 Simple Sliding-Window Aggregator                  */
/* -------------------------------------------------------------------------- */

/**
 * Keeps recent telemetry in memory and exposes aggregated snapshots at any time.
 * Not production-grade for very high throughput, but good enough for the reference module.
 */
class SlidingWindowAggregator {
  private socialBuffer: SocialPulseEvent[] = [];
  private infraBuffer: InfraMetricsEvent[] = [];

  public constructor(private readonly windowMs: number) {}

  public ingest(event: TelemetryEvent): void {
    const now = Date.now();
    this.dropExpired(now);

    if (event.kind === 'social') {
      this.socialBuffer.push(event);
    } else {
      this.infraBuffer.push(event);
    }
  }

  public snapshot(): OrchestrationContext {
    const socialStats = this.aggregateSocial();
    const infraStats = this.aggregateInfra();
    return { social: socialStats, infra: infraStats };
  }

  private aggregateSocial(): AggregatedSocialStats {
    if (this.socialBuffer.length === 0) {
      return {
        likesPerSec: 0,
        commentsPerSec: 0,
        sharesPerSec: 0,
        liveViewers: 0,
        trendingScore: 0,
      };
    }

    const durationSec =
      (Math.max(...this.socialBuffer.map((e) => e.timestamp)) -
        Math.min(...this.socialBuffer.map((e) => e.timestamp))) /
        1000 || 1;

    const totalLikes = this.socialBuffer.reduce((sum, e) => sum + e.likes, 0);
    const totalComments = this.socialBuffer.reduce(
      (sum, e) => sum + e.comments,
      0,
    );
    const totalShares = this.socialBuffer.reduce((sum, e) => sum + e.shares, 0);
    const avgLiveViewers =
      this.socialBuffer.reduce((sum, e) => sum + e.liveStreamViewers, 0) /
      this.socialBuffer.length;

    const trendingScore =
      totalLikes * 0.25 +
      totalComments * 0.4 +
      totalShares * 0.35 +
      avgLiveViewers * 0.05;

    return {
      likesPerSec: totalLikes / durationSec,
      commentsPerSec: totalComments / durationSec,
      sharesPerSec: totalShares / durationSec,
      liveViewers: avgLiveViewers,
      trendingScore,
    };
  }

  private aggregateInfra(): AggregatedInfraStats {
    if (this.infraBuffer.length === 0) {
      return {
        avgCpu: 0,
        peakRps: 0,
        errorRate: 0,
        currentPods: 0,
      };
    }

    const avgCpu =
      this.infraBuffer.reduce((sum, e) => sum + e.cpuUsage, 0) /
      this.infraBuffer.length;
    const peakRps = Math.max(...this.infraBuffer.map((e) => e.rps));
    const weightedErrorRate =
      this.infraBuffer.reduce((sum, e) => sum + e.errorRate, 0) /
      this.infraBuffer.length;
    const latestPods =
      this.infraBuffer[this.infraBuffer.length - 1].podCount ?? 0;

    return {
      avgCpu,
      peakRps,
      errorRate: weightedErrorRate,
      currentPods: latestPods,
    };
  }

  private dropExpired(now: number): void {
    const lowerBound = now - this.windowMs;
    this.socialBuffer = this.socialBuffer.filter((e) => e.timestamp >= lowerBound);
    this.infraBuffer = this.infraBuffer.filter((e) => e.timestamp >= lowerBound);
  }
}

/* -------------------------------------------------------------------------- */
/*                  🧩 Built-in Strategy: Weighted Thresholds                 */
/* -------------------------------------------------------------------------- */

/**
 * Heuristic strategy suitable for 95% of use-cases where social virality directly
 * impacts backend load. Scales primarily on infra CPU/RPS but boosts aggressiveness
 * when a social spike is detected.
 */
export class WeightedThresholdStrategy implements OrchestrationStrategy {
  public readonly name = 'weighted_threshold/v1';

  public constructor(
    private readonly cfg: {
      cpuUpper: number; // ex: 70%
      cpuLower: number; // ex: 35%
      socialBoost: number; // ex: 1.5 => multiply RPS threshold
      maxScaleStep: number; // ex: 8 pods
      minPods: number;
      maxPods: number;
    },
  ) {}

  public evaluate(ctx: OrchestrationContext): OrchestrationCommand {
    const {
      social: { trendingScore },
      infra: { avgCpu, peakRps, currentPods },
    } = ctx;

    // Baseline decision purely on CPU
    let desiredPods = currentPods;
    if (avgCpu > this.cfg.cpuUpper) {
      desiredPods += Math.min(
        Math.ceil(((avgCpu - this.cfg.cpuUpper) / 10) * currentPods),
        this.cfg.maxScaleStep,
      );
    } else if (avgCpu < this.cfg.cpuLower) {
      desiredPods -= Math.ceil((this.cfg.cpuLower - avgCpu) / 10);
    }

    // Increase aggressiveness if trending score is unusually high
    if (trendingScore > 10_000) {
      desiredPods = Math.max(
        desiredPods,
        Math.ceil(
          (peakRps * this.cfg.socialBoost) /
            (50 * currentPods), // assume 50 req/s capacity per pod
        ),
      );
    }

    // Clamp desiredPods
    desiredPods = Math.max(this.cfg.minPods, Math.min(this.cfg.maxPods, desiredPods));

    const delta = desiredPods - currentPods;

    const action: OrchestrationCommand['action'] =
      delta > 0 ? 'scale_up' : delta < 0 ? 'scale_down' : 'hold';

    return {
      id: randomUUID(),
      action,
      delta: Math.abs(delta),
      reason: this.buildReason(avgCpu, trendingScore, delta),
      createdAt: Date.now(),
    };
  }

  /* ----------------------------- util helpers ----------------------------- */

  private buildReason(
    avgCpu: number,
    trendingScore: number,
    delta: number,
  ): string {
    if (delta === 0) {
      return `Within thresholds (cpu=${avgCpu.toFixed(
        1,
      )}%, trend=${trendingScore.toFixed(0)})`;
    }
    const direction = delta > 0 ? 'up' : 'down';
    return `Scaled ${direction} by ${Math.abs(
      delta,
    )} (cpu=${avgCpu.toFixed(1)}%, trend=${trendingScore.toFixed(0)})`;
  }
}

/* -------------------------------------------------------------------------- */
/*                   🤖 ML-Backed Strategy (placeholder stub)                */
/* -------------------------------------------------------------------------- */

export class MlForecastStrategy implements OrchestrationStrategy {
  public readonly name = 'ml_forecast/v0';

  public evaluate(ctx: OrchestrationContext): OrchestrationCommand {
    // In a real implementation, this would call out to an internal
    // gRPC service that predicts traffic 5-10 minutes ahead.
    // We simulate with a no-op holding pattern.
    return {
      id: randomUUID(),
      action: 'hold',
      delta: 0,
      reason: 'ML forecast stub: holding position',
      createdAt: Date.now(),
    };
  }
}

/* -------------------------------------------------------------------------- */
/*               🏗️   Orchestrator Engine (Observer + Strategy)              */
/* -------------------------------------------------------------------------- */

export interface CapacityOrchestratorOptions {
  windowMs?: number;
  pollIntervalMs?: number;
  defaultStrategy?: OrchestrationStrategy;
  logger?: Pick<Console, 'debug' | 'info' | 'warn' | 'error'>;
}

/**
 * Listens to telemetry events, maintains an in-memory sliding window, executes an
 * OrchestrationStrategy on a configurable interval, and publishes resulting commands
 * over an internal event bus.
 *
 * Usage:
 *   const orchestrator = new CapacityOrchestrator({ ...options });
 *   orchestrator.on('command', (cmd) => sendToKafka(cmd));
 *   orchestrator.start();
 */
export class CapacityOrchestrator extends EventEmitter {
  private readonly aggregator: SlidingWindowAggregator;
  private readonly logger: Required<CapacityOrchestratorOptions['logger']>;
  private strategy: OrchestrationStrategy;
  private running = false;

  public constructor(private readonly opts: CapacityOrchestratorOptions = {}) {
    super();
    this.aggregator = new SlidingWindowAggregator(opts.windowMs ?? 60_000);
    this.logger = opts.logger ?? console;
    this.strategy =
      opts.defaultStrategy ??
      new WeightedThresholdStrategy({
        cpuUpper: 75,
        cpuLower: 30,
        socialBoost: 1.5,
        maxScaleStep: 6,
        minPods: 2,
        maxPods: 120,
      });
  }

  /* -------------------------- Public API -------------------------- */

  /**
   * Feed incoming telemetry to the orchestrator.
   * Typically wired from the platform’s message broker.
   */
  public ingest(event: TelemetryEvent): void {
    try {
      this.aggregator.ingest(event);
    } catch (err) {
      this.logger.error('Failed to ingest telemetry event', err);
    }
  }

  /**
   * Replace the active orchestration strategy at runtime.
   */
  public useStrategy(newStrategy: OrchestrationStrategy): void {
    this.logger.info(
      `Switching strategy from ${this.strategy.name} to ${newStrategy.name}`,
    );
    this.strategy = newStrategy;
  }

  /** Start evaluation loop. Safe to call multiple times (idempotent). */
  public start(): void {
    if (this.running) return;
    this.running = true;
    this.loop().catch((err) => {
      this.logger.error('Fatal orchestrator loop error', err);
      process.exit(1); // Fail-fast; container orchestrator will restart us
    });
    this.logger.info('CapacityOrchestrator started');
  }

  /** Stop evaluation loop gracefully. */
  public stop(): void {
    this.running = false;
    this.logger.info('CapacityOrchestrator stopping...');
  }

  /* ----------------------- Internal Implementation ----------------------- */

  private async loop(): Promise<void> {
    const pollInterval = this.opts.pollIntervalMs ?? 10_000;
    while (this.running) {
      await safeSetTimeout(pollInterval);
      this.evaluateOnce();
    }
  }

  private evaluateOnce(): void {
    try {
      const ctx = this.aggregator.snapshot();
      const cmd = this.strategy.evaluate(ctx);

      this.logger.debug(
        `[${this.strategy.name}] decision: ${cmd.action} Δ${cmd.delta}`,
      );

      if (cmd.action !== 'hold') {
        this.emit('command', cmd); // consumers: k8s scaler, alerting, audit
      }
    } catch (err) {
      this.logger.error('Evaluation failed', err);
      // Emit self-healing alert maybe?
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                           🛂 Configuration Bootstrap                       */
/* -------------------------------------------------------------------------- */

/**
 * Factory helper that reads env vars and returns a ready-to-use orchestrator.
 * Intended for CLI / container entrypoint code.
 */
export function createOrchestratorFromEnv(): CapacityOrchestrator {
  const env = process.env;

  const strategy =
    env.ORCH_STRATEGY === 'ml'
      ? new MlForecastStrategy()
      : new WeightedThresholdStrategy({
          cpuUpper: parseFloat(env.ORCH_CPU_UPPER ?? '75'),
          cpuLower: parseFloat(env.ORCH_CPU_LOWER ?? '30'),
          socialBoost: parseFloat(env.ORCH_SOCIAL_BOOST ?? '1.5'),
          maxScaleStep: parseInt(env.ORCH_MAX_STEP ?? '6', 10),
          minPods: parseInt(env.ORCH_MIN_PODS ?? '2', 10),
          maxPods: parseInt(env.ORCH_MAX_PODS ?? '120', 10),
        });

  return new CapacityOrchestrator({
    windowMs: parseInt(env.ORCH_WINDOW_MS ?? '60000', 10),
    pollIntervalMs: parseInt(env.ORCH_POLL_MS ?? '10000', 10),
    defaultStrategy: strategy,
    logger: console,
  });
}

/**************************************************************************************************
 * End of module_44.ts
 **************************************************************************************************/
```