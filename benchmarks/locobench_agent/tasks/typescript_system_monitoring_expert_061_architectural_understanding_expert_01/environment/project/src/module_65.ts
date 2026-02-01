```typescript
/**
 * File: src/module_65.ts
 * Project: PulseSphere SocialOps (system_monitoring)
 *
 * Description:
 *  Social-Aware Autoscaler.
 *
 *  This module implements a chain-of-responsibility of scaling strategies that
 *  combines traditional infrastructure metrics with real-time social-engagement
 *  signals.  Each strategy in the chain can decide to scale the service up or
 *  down; if no strategy triggers, the default/terminal node is a no-op.
 *
 *  The autoscaler listens to two high-frequency streams:
 *    1. Infrastructure telemetry (CPU, memory, latency …)
 *    2. Social context (likes, shares, hashtag spikes …)
 *
 *  Both streams are merged into a single observable “tick”, so that strategies
 *  always receive coherent snapshots.  Decisions are published on the
 *  event-bus (NATS) for the Orchestration micro-service to consume.
 *
 *  – Patterns used: Observer, Chain-of-Responsibility, Strategy.
 *  – RxJS drives the event pipeline.
 */

import { NatsConnection, connect, StringCodec } from "nats";
import { Observable, combineLatest, interval, from, EMPTY, throwError } from "rxjs";
import { catchError, map, switchMap, takeUntil, tap } from "rxjs/operators";

/* -------------------------------------------------------------------------- */
/*                                Domain types                                */
/* -------------------------------------------------------------------------- */

export enum SocialMetric {
  LIKES = "likes",
  SHARES = "shares",
  COMMENTS = "comments",
  LIVE_STREAM_VIEWERS = "live_stream_viewers",
  HASHTAG_TREND_SCORE = "hashtag_trend_score",
}

export interface SocialSignals {
  [SocialMetric.LIKES]: number;
  [SocialMetric.SHARES]: number;
  [SocialMetric.COMMENTS]: number;
  [SocialMetric.LIVE_STREAM_VIEWERS]: number;
  [SocialMetric.HASHTAG_TREND_SCORE]: number;
  timestamp: Date;
}

export interface InfraMetrics {
  cpuPercent: number; // 0 – 100
  memPercent: number; // 0 – 100
  rps: number;        // requests per second
  latencyMsP95: number;
  timestamp: Date;
}

/**
 * Desired scaling change.
 */
export class ScalingDecision {
  constructor(
    public readonly scaleOut: number, // positive = add pods; negative = remove pods
    public readonly reason: string,
    public readonly triggeredBy: string, // strategy name
    public readonly ts: Date = new Date(),
  ) {}
}

/* -------------------------------------------------------------------------- */
/*                         Telemetry acquisition services                     */
/* -------------------------------------------------------------------------- */

/**
 * Abstract contract for any service that can stream SocialSignals.
 */
export interface ISocialSignalProvider {
  stream(): Observable<SocialSignals>;
}

/**
 * Abstract contract for infrastructure metrics.
 */
export interface IInfraMetricsProvider {
  stream(): Observable<InfraMetrics>;
}

/**
 * Dummy implementation returning random social data.
 * Real-world code would consume from Kafka topic “social-signals”.
 */
export class MockSocialSignalProvider implements ISocialSignalProvider {
  stream(): Observable<SocialSignals> {
    return interval(1000).pipe(
      map((): SocialSignals => ({
        [SocialMetric.LIKES]: Math.random() * 500,
        [SocialMetric.SHARES]: Math.random() * 200,
        [SocialMetric.COMMENTS]: Math.random() * 150,
        [SocialMetric.LIVE_STREAM_VIEWERS]: Math.random() * 10000,
        [SocialMetric.HASHTAG_TREND_SCORE]: Math.random() * 100,
        timestamp: new Date(),
      })),
    );
  }
}

/**
 * Dummy implementation returning random infra metrics.
 */
export class MockInfraMetricsProvider implements IInfraMetricsProvider {
  stream(): Observable<InfraMetrics> {
    return interval(1000).pipe(
      map((): InfraMetrics => ({
        cpuPercent: 30 + Math.random() * 60,
        memPercent: 40 + Math.random() * 50,
        rps: 500 + Math.random() * 1500,
        latencyMsP95: 100 + Math.random() * 400,
        timestamp: new Date(),
      })),
    );
  }
}

/* -------------------------------------------------------------------------- */
/*                       Strategy / Chain-of-Responsibility                   */
/* -------------------------------------------------------------------------- */

export type MetricsEnvelope = {
  infra: InfraMetrics;
  social: SocialSignals;
};

/**
 * Base class for a scaling strategy.  Concrete subclasses decide whether or
 * not to produce a scaling decision; if they do not, the request is forwarded
 * to `next`.
 */
export abstract class AbstractScalingStrategy {
  protected next: AbstractScalingStrategy | null = null;

  constructor(public readonly name: string) {}

  /** Set next strategy in the chain. */
  setNext(next: AbstractScalingStrategy): AbstractScalingStrategy {
    this.next = next;
    return next;
  }

  /** Determine if we should scale. */
  protected abstract evaluate(payload: MetricsEnvelope): ScalingDecision | null;

  /**
   * Execute evaluation, propagate down the chain if needed.
   */
  execute(payload: MetricsEnvelope): ScalingDecision | null {
    const decision = this.evaluate(payload);
    if (decision) {
      return decision;
    }
    return this.next?.execute(payload) ?? null;
  }
}

/* --------------------------- Concrete strategies -------------------------- */

/**
 * Detect hashtag spikes; aggressively scale-out.
 */
export class HashtagSpikeStrategy extends AbstractScalingStrategy {
  private static readonly THRESHOLD = 70; // trending score

  protected evaluate({ social }: MetricsEnvelope): ScalingDecision | null {
    if (social[SocialMetric.HASHTAG_TREND_SCORE] > HashtagSpikeStrategy.THRESHOLD) {
      const delta = Math.ceil(social[SocialMetric.HASHTAG_TREND_SCORE] / 15);
      return new ScalingDecision(
        delta,
        `Hashtag trend score ${social[SocialMetric.HASHTAG_TREND_SCORE].toFixed(1)} > ${HashtagSpikeStrategy.THRESHOLD}`,
        this.name,
      );
    }
    return null;
  }
}

/**
 * Ensure p95 latency stays below target.
 */
export class LatencyGuardStrategy extends AbstractScalingStrategy {
  private readonly targetLatency: number; // e.g. 200ms

  constructor(targetLatency: number) {
    super("LatencyGuardStrategy");
    this.targetLatency = targetLatency;
  }

  protected evaluate({ infra }: MetricsEnvelope): ScalingDecision | null {
    if (infra.latencyMsP95 > this.targetLatency) {
      const delta = Math.ceil((infra.latencyMsP95 - this.targetLatency) / 50);
      return new ScalingDecision(
        delta,
        `Latency ${infra.latencyMsP95.toFixed(0)}ms > ${this.targetLatency}ms target`,
        this.name,
      );
    }

    // attempt scale-in if latency is way under target AND CPU/MEM low
    if (infra.latencyMsP95 < this.targetLatency * 0.5 && infra.cpuPercent < 35 && infra.memPercent < 35) {
      return new ScalingDecision(
        -1,
        "Latency healthy and resource usage low – scale in",
        this.name,
      );
    }
    return null;
  }
}

/**
 * Back-off when cost spikes (simplified).
 */
export class CostOptimizationStrategy extends AbstractScalingStrategy {
  protected evaluate({ infra }: MetricsEnvelope): ScalingDecision | null {
    // Suppose each pod ~ 60% CPU.  If CPU < 35% → consider reducing pods.
    if (infra.cpuPercent < 35 && infra.memPercent < 40) {
      return new ScalingDecision(
        -1,
        "Under-utilised resources",
        this.name,
      );
    }
    return null;
  }
}

/**
 * Default/no-op strategy to terminate chain.
 */
export class NoOpStrategy extends AbstractScalingStrategy {
  protected evaluate(): ScalingDecision | null {
    return null;
  }
}

/* -------------------------------------------------------------------------- */
/*                             NATS / Event Bus                               */
/* -------------------------------------------------------------------------- */

/**
 * Wraps NATS connection for publishing decisions.
 */
export class ScalingDecisionPublisher {
  private conn?: NatsConnection;
  private readonly codec = StringCodec();

  constructor(
    private readonly natsUrl: string,
    private readonly subject: string = "scaling.decisions",
  ) {}

  async init(): Promise<void> {
    try {
      this.conn = await connect({ servers: this.natsUrl });
      console.info("[autoscaler] Connected to NATS:", this.natsUrl);
    } catch (err) {
      console.error("[autoscaler] Failed to connect to NATS", err);
      throw err;
    }
  }

  async publish(decision: ScalingDecision): Promise<void> {
    if (!this.conn) {
      throw new Error("NATS connection not initialised");
    }
    const payload = JSON.stringify(decision);
    this.conn.publish(this.subject, this.codec.encode(payload));
  }

  async close(): Promise<void> {
    await this.conn?.drain();
  }
}

/* -------------------------------------------------------------------------- */
/*                              Autoscaler Core                               */
/* -------------------------------------------------------------------------- */

export interface AutoscalerConfig {
  natsUrl: string;
  publishSubject?: string;
  targetLatencyMs?: number;
  dryRun?: boolean;
  shutdown$?: Observable<unknown>; // triggers graceful stop
}

export class SocialAwareAutoscaler {
  private readonly socialProvider: ISocialSignalProvider;
  private readonly infraProvider: IInfraMetricsProvider;
  private readonly publisher: ScalingDecisionPublisher;
  private readonly rootStrategy: AbstractScalingStrategy;

  constructor(
    socialProvider: ISocialSignalProvider,
    infraProvider: IInfraMetricsProvider,
    private readonly config: AutoscalerConfig,
  ) {
    this.socialProvider = socialProvider;
    this.infraProvider = infraProvider;
    this.publisher = new ScalingDecisionPublisher(
      config.natsUrl,
      config.publishSubject,
    );

    /* Build chain: HashtagSpike → LatencyGuard → CostOptimization → NoOp */
    this.rootStrategy = new HashtagSpikeStrategy("HashtagSpikeStrategy");
    this.rootStrategy
      .setNext(new LatencyGuardStrategy(config.targetLatencyMs ?? 200))
      .setNext(new CostOptimizationStrategy("CostOptimizationStrategy"))
      .setNext(new NoOpStrategy("NoOp"));
  }

  /**
   * Start streaming and processing metrics.
   */
  async start(): Promise<void> {
    await this.publisher.init();

    const social$ = this.socialProvider.stream();
    const infra$ = this.infraProvider.stream();

    combineLatest([infra$, social$])
      .pipe(
        map(([infra, social]) => ({ infra, social } as MetricsEnvelope)),
        tap((env) => {
          // basic sanity validation
          if (!env.infra || !env.social) {
            console.warn("[autoscaler] Skipping tick with incomplete data");
          }
        }),
        map((env) => this.rootStrategy.execute(env)),
        // filter out nulls
        switchMap((decision) => (decision ? from(this.handleDecision(decision)) : EMPTY)),
        catchError((err) => {
          console.error("[autoscaler] Error in processing pipeline", err);
          return throwError(() => err);
        }),
        takeUntil(this.config.shutdown$ ?? EMPTY),
      )
      .subscribe({
        error: (err) => {
          console.error("[autoscaler] Pipeline terminated with error", err);
          void this.stop();
        },
        complete: () => {
          console.info("[autoscaler] Pipeline completed");
          void this.stop();
        },
      });
  }

  private async handleDecision(decision: ScalingDecision): Promise<void> {
    console.info(
      `[autoscaler] Decision: ${decision.scaleOut >= 0 ? "+" : ""}${decision.scaleOut} pods – ${decision.reason}`,
    );

    if (this.config.dryRun) {
      // Dry-run: just log
      return;
    }

    try {
      await this.publisher.publish(decision);
    } catch (err) {
      console.error("[autoscaler] Failed to publish decision", err);
    }
  }

  /**
   * Graceful shutdown.
   */
  async stop(): Promise<void> {
    console.info("[autoscaler] Stopping ‑ closing NATS connection");
    await this.publisher.close();
  }
}

/* -------------------------------------------------------------------------- */
/*                        Bootstrap (if executed standalone)                  */
/* -------------------------------------------------------------------------- */

if (require.main === module) {
  (async () => {
    const autoscaler = new SocialAwareAutoscaler(
      new MockSocialSignalProvider(),
      new MockInfraMetricsProvider(),
      {
        natsUrl: process.env.NATS_URL ?? "nats://localhost:4222",
        targetLatencyMs: 200,
        dryRun: process.env.DRY_RUN === "true",
      },
    );

    await autoscaler.start();

    // graceful shutdown on SIGINT / SIGTERM
    process.on("SIGINT", () => autoscaler.stop().then(() => process.exit(0)));
    process.on("SIGTERM", () => autoscaler.stop().then(() => process.exit(0)));
  })().catch((err) => {
    console.error("[autoscaler] Fatal error", err);
    process.exit(1);
  });
}
```