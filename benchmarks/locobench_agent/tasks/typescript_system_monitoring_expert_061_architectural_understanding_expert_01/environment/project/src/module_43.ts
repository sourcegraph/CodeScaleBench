typescript
/**
 * File: module_43.ts
 * Project: PulseSphere SocialOps (system_monitoring)
 *
 * Description:
 *  • Listens to real-time, socially-enriched telemetry fed by the Event Backbone (Kafka / NATS)
 *  • Calculates trending scores using interchangeable Strategy implementations
 *  • Decides whether to trigger auto-scaling commands through a Chain-of-Responsibility
 *  • Issues concrete scale-up / scale-down commands (Command Pattern)
 *
 * The module can be wired into the service mesh side-car that runs next to the
 * autoscaler-controller micro-service.  It is completely stateless and can be
 * horizontally replicated (Kafka consumer groups guarantee partition safety).
 */

import { EventEmitter } from 'events';
import { randomUUID } from 'crypto';
import * as zod from 'zod';

// -----------------------------------------------------------------------------
// SECTION: Domain Types / Schemas
// -----------------------------------------------------------------------------

export enum SocialSignalType {
  LIKE = 'LIKE',
  COMMENT = 'COMMENT',
  SHARE = 'SHARE',
  LIVE_STREAM_JOIN = 'LIVE_STREAM_JOIN',
  HASH_TAG_MENTION = 'HASH_TAG_MENTION',
}

export interface SocialSignal {
  readonly id: string;
  readonly type: SocialSignalType;
  readonly userId: string;
  readonly postId?: string;
  readonly createdAt: number; // Unix epoch ms
  readonly metadata?: Record<string, unknown>;
}

const SocialSignalSchema: zod.ZodSchema<SocialSignal> = zod.object({
  id: zod.string().uuid(),
  type: zod.nativeEnum(SocialSignalType),
  userId: zod.string(),
  postId: zod.string().optional(),
  createdAt: zod.number(),
  metadata: zod.record(zod.any()).optional(),
});

export interface MetricSample {
  readonly cpu: number; // %
  readonly memory: number; // %
  readonly latencyMs: number;
  readonly windowStart: number; // Unix epoch ms
  readonly windowEnd: number; // Unix epoch ms
}

// Composite event that correlation service emits
export interface EnrichedEvent {
  readonly socialSignal: SocialSignal;
  readonly infraMetrics: MetricSample;
}

// -----------------------------------------------------------------------------
// SECTION: Event Bus Abstraction
// -----------------------------------------------------------------------------

/**
 * A lightweight wrapper over Node EventEmitter so we can swap it out
 * with Kafka / NATS in production without breaking the handler APIs.
 */
export class InternalEventBus extends EventEmitter {
  public static readonly instance = new InternalEventBus();
  private constructor() {
    super();
  }
}

// The channel through which enrichment service publishes events
export const SOCIAL_TELEMETRY_EVENT = 'SOCIAL_TELEMETRY_EVENT';

// -----------------------------------------------------------------------------
// SECTION: Trending Score Strategies (Strategy Pattern)
// -----------------------------------------------------------------------------

export interface TrendingScoreStrategy {
  /**
   * Produces a score between 0.0 – 1.0 (higher → trending).
   */
  calculate(events: EnrichedEvent[]): number;
}

/**
 * Simple linear scoring strategy that looks at event volume per interval.
 */
export class LinearTrendStrategy implements TrendingScoreStrategy {
  constructor(private readonly windowSizeMs = 60_000) {}
  calculate(events: EnrichedEvent[]): number {
    const now = Date.now();
    const windowStart = now - this.windowSizeMs;

    const eventsInWindow = events.filter(
      ev => ev.socialSignal.createdAt >= windowStart,
    ).length;

    // Normalize based on empirical upper bound; fallback to clamp 1.0
    const normalized = Math.min(eventsInWindow / 5_000, 1);
    return normalized;
  }
}

/**
 * Exponential scoring strategy that exponentially weighs newer events.
 */
export class ExponentialTrendStrategy implements TrendingScoreStrategy {
  constructor(
    private readonly decayLambda = 0.00025, // bigger → sharper decay
  ) {}

  calculate(events: EnrichedEvent[]): number {
    const now = Date.now();
    let score = 0;

    for (const ev of events) {
      const ageMs = now - ev.socialSignal.createdAt;
      // Negative exponent for decay: e^(-λ·age)
      const weight = Math.exp(-this.decayLambda * ageMs);
      score += weight;
    }
    // Normalization heuristic; convert open-ended sum to 0–1 range
    return Math.tanh(score / 100); // tanh saturates to 1
  }
}

// -----------------------------------------------------------------------------
// SECTION: Command Pattern – Scaling Commands
// -----------------------------------------------------------------------------

export interface Command<T = void> {
  /**
   * Execute the command.
   */
  execute(): Promise<T>;
}

/**
 * Abstract base class for scaling actions.
 */
abstract class ScalingCommand implements Command<void> {
  constructor(protected readonly correlationId: string) {}
  abstract execute(): Promise<void>;
}

/**
 * Scale-up command that talks to the orchestration subsystem.
 */
export class ScaleUpCommand extends ScalingCommand {
  constructor(
    correlationId: string,
    private readonly replicasToAdd: number,
  ) {
    super(correlationId);
  }

  public async execute(): Promise<void> {
    // In real life, call Kubernetes HPA / custom autoscaler API.
    try {
      console.info(
        `[ScaleUpCommand:${this.correlationId}] Requesting +${this.replicasToAdd} replicas`,
      );
      // simulate async API call
      await new Promise(res => setTimeout(res, 50));
    } catch (err) {
      console.error(
        `[ScaleUpCommand:${this.correlationId}] failed: ${(err as Error).message}`,
      );
      throw err;
    }
  }
}

/**
 * Scale-down command to free up resources.
 */
export class ScaleDownCommand extends ScalingCommand {
  constructor(
    correlationId: string,
    private readonly replicasToRemove: number,
  ) {
    super(correlationId);
  }

  public async execute(): Promise<void> {
    try {
      console.info(
        `[ScaleDownCommand:${this.correlationId}] Requesting -${this.replicasToRemove} replicas`,
      );
      // simulate async API call
      await new Promise(res => setTimeout(res, 50));
    } catch (err) {
      console.error(
        `[ScaleDownCommand:${this.correlationId}] failed: ${(err as Error).message}`,
      );
      throw err;
    }
  }
}

// -----------------------------------------------------------------------------
// SECTION: Chain of Responsibility – Decision Handlers
// -----------------------------------------------------------------------------

/**
 * Context passed to each decision handler in the chain.
 */
export interface DecisionContext {
  readonly avgCpu: number;
  readonly trendingScore: number;
  readonly correlationId: string;
}

export abstract class DecisionHandler {
  protected nextHandler?: DecisionHandler;

  public setNext(handler: DecisionHandler): DecisionHandler {
    this.nextHandler = handler;
    return handler;
  }

  /**
   * Each handler either:
   *  • Executes an action and returns true  (chain terminates)
   *  • Returns false to delegate to next    (chain continues)
   */
  abstract handle(ctx: DecisionContext): Promise<boolean>;
}

/**
 * Handler for clear overload scenarios (CPU > 85% & trending spike).
 */
export class OverloadHandler extends DecisionHandler {
  public async handle(ctx: DecisionContext): Promise<boolean> {
    const { avgCpu, trendingScore, correlationId } = ctx;
    if (avgCpu > 0.85 && trendingScore > 0.7) {
      const replicas = Math.ceil(trendingScore * 10);
      await new ScaleUpCommand(correlationId, replicas).execute();
      return true;
    }
    return this.nextHandler ? this.nextHandler.handle(ctx) : false;
  }
}

/**
 * Handler for gentle ramp-ups when virality is rising but infra ok.
 */
export class SpikeHandler extends DecisionHandler {
  public async handle(ctx: DecisionContext): Promise<boolean> {
    const { avgCpu, trendingScore, correlationId } = ctx;
    if (trendingScore > 0.5 && avgCpu <= 0.85) {
      await new ScaleUpCommand(correlationId, 2).execute();
      return true;
    }
    return this.nextHandler ? this.nextHandler.handle(ctx) : false;
  }
}

/**
 * Handler for under-utilization; decide scale-down.
 */
export class UnderUtilizationHandler extends DecisionHandler {
  public async handle(ctx: DecisionContext): Promise<boolean> {
    const { avgCpu, trendingScore, correlationId } = ctx;
    if (avgCpu < 0.25 && trendingScore < 0.2) {
      await new ScaleDownCommand(correlationId, 1).execute();
      return true;
    }
    return this.nextHandler ? this.nextHandler.handle(ctx) : false;
  }
}

// -----------------------------------------------------------------------------
// SECTION: Monitor Orchestrator
// -----------------------------------------------------------------------------

interface MonitorOptions {
  /**
   * Strategy used to compute trending score.
   */
  strategy?: TrendingScoreStrategy;

  /**
   * Size of the in-memory sliding window (ms).
   */
  bufferWindowMs?: number;
}

/**
 * Main orchestrator class: listens to enriched events, maintains buffers,
 * triggers decision chain.
 */
export class SocialTrendMonitor {
  private readonly bufferWindowMs: number;
  private readonly strategy: TrendingScoreStrategy;
  private readonly eventsBuffer: EnrichedEvent[] = [];

  // Compose the chain once in the constructor
  private readonly decisionChain: DecisionHandler = (() => {
    const overload = new OverloadHandler();
    const spike = new SpikeHandler();
    const underUtil = new UnderUtilizationHandler();

    overload.setNext(spike).setNext(underUtil);
    return overload;
  })();

  private readonly bus = InternalEventBus.instance;

  constructor(opts: MonitorOptions = {}) {
    this.strategy = opts.strategy ?? new LinearTrendStrategy();
    this.bufferWindowMs = opts.bufferWindowMs ?? 5 * 60_000; // default: 5min
  }

  public start(): void {
    this.bus.on(SOCIAL_TELEMETRY_EVENT, this.onTelemetryEvent);
    console.info('[SocialTrendMonitor] started.');
  }

  public stop(): void {
    this.bus.off(SOCIAL_TELEMETRY_EVENT, this.onTelemetryEvent);
    console.info('[SocialTrendMonitor] stopped.');
  }

  // Using arrow fn to preserve "this" context when registering to EventEmitter.
  private readonly onTelemetryEvent = (raw: unknown): void => {
    try {
      // Validate payload; will throw if invalid
      const enriched = this.parseEvent(raw);

      this.addToBuffer(enriched);
      this.evaluateDecisions(enriched.infraMetrics);
    } catch (err) {
      console.warn(
        `[SocialTrendMonitor] Invalid event skipped: ${(err as Error).message}`,
      );
    }
  };

  private parseEvent(raw: unknown): EnrichedEvent {
    // We only validate the socialSignal; infraMetric assumed trustworthy
    const e = raw as EnrichedEvent;
    SocialSignalSchema.parse(e.socialSignal);
    return e;
  }

  /**
   * Maintains a sliding window buffer limited by bufferWindowMs.
   */
  private addToBuffer(evt: EnrichedEvent): void {
    this.eventsBuffer.push(evt);
    const expiry = Date.now() - this.bufferWindowMs;

    // Remove old items (simple filter; O(n) but n small in window)
    while (this.eventsBuffer[0]?.socialSignal.createdAt < expiry) {
      this.eventsBuffer.shift();
    }
  }

  /**
   * Calculates trending score & routes through decision chain.
   */
  private async evaluateDecisions(metric: MetricSample): Promise<void> {
    const trendingScore = this.strategy.calculate(this.eventsBuffer);

    const ctx: DecisionContext = {
      avgCpu: metric.cpu / 100,
      trendingScore,
      correlationId: randomUUID(),
    };

    try {
      const handled = await this.decisionChain.handle(ctx);
      if (!handled) {
        console.debug(
          `[DecisionChain:${ctx.correlationId}] No scaling action required.`,
        );
      }
    } catch (err) {
      console.error(
        `[DecisionChain:${ctx.correlationId}] Error during decision processing: ${
          (err as Error).message
        }`,
      );
    }
  }
}

// -----------------------------------------------------------------------------
// SECTION: Public bootstrap helper
// -----------------------------------------------------------------------------

/**
 * Convenience helper to spin up the monitor from DI container / main entry.
 */
export function bootstrapSocialTrendMonitor(opts?: MonitorOptions): () => void {
  const monitor = new SocialTrendMonitor(opts);
  monitor.start();
  return () => monitor.stop();
}

// -----------------------------------------------------------------------------
// SECTION: Example Integration (Removed in Production Build)
// -----------------------------------------------------------------------------
// The following code is wrapped in an environment guard so it is ignored
// in the production bundle by tree-shaking / dead-code-elimination.
// This serves as a local dev smoke-test when running `ts-node src/module_43.ts`.
if (process.env['NODE_ENV'] !== 'production' && require.main === module) {
  /* eslint-disable @typescript-eslint/no-var-requires */
  const faker = require('faker') as typeof import('@faker-js/faker');

  const stopMonitor = bootstrapSocialTrendMonitor({
    strategy: new ExponentialTrendStrategy(0.0001),
    bufferWindowMs: 2 * 60_000,
  });

  const bus = InternalEventBus.instance;

  // Simulate event generation
  setInterval(() => {
    const now = Date.now();
    const fakeEvent: EnrichedEvent = {
      socialSignal: {
        id: randomUUID(),
        type:
          Object.values(SocialSignalType)[
            Math.floor(Math.random() * Object.values(SocialSignalType).length)
          ],
        userId: faker.datatype.uuid(),
        createdAt: now,
      },
      infraMetrics: {
        cpu: 20 + Math.random() * 80,
        memory: 30 + Math.random() * 50,
        latencyMs: Math.random() * 250,
        windowStart: now - 5_000,
        windowEnd: now,
      },
    };
    bus.emit(SOCIAL_TELEMETRY_EVENT, fakeEvent);
  }, 500);

  // Auto-stop after 30s
  setTimeout(() => {
    stopMonitor();
    console.info('Demo stopped.');
    process.exit(0);
  }, 30_000);
}