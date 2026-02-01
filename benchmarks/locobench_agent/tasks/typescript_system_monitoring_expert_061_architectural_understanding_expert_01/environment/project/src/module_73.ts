```typescript
/**************************************************************************************************
 * PulseSphere SocialOps – System Monitoring
 *
 *  File:        src/module_73.ts
 *  Purpose:     Social-context-aware autoscaling engine.  Consumes infrastructure metrics
 *               (CPU, memory, latency) and high-cardinality social-engagement signals
 *               (likes, shares, live-stream spikes) from Kafka; enriches & normalises them;
 *               then delegates to pluggable Strategy implementations that recommend a scaling
 *               decision. Can be wired into the platform’s deployment-automation service or
 *               used in “dry-run” mode for capacity-planning analytics.
 *
 *  Architectural Patterns Demonstrated:
 *   • Strategy Pattern       – multiple scaling algorithms selected at runtime
 *   • Chain of Responsibility – composable pre-processors (normalisers, throttlers, enrichers)
 *   • Observer Pattern       – reactive subscription to the Event-Driven backbone (Kafka)
 *
 *  External deps: kafkajs (Kafka client), rxjs (reactive streams), winston (structured logging)
 **************************************************************************************************/

/* eslint-disable @typescript-eslint/no-floating-promises */

import { Kafka, Consumer, EachMessagePayload } from 'kafkajs';
import { Subject, from, merge, Observable } from 'rxjs';
import {
  bufferTime,
  filter,
  map,
  mergeMap,
  tap,
  timeoutWith,
  catchError,
} from 'rxjs/operators';
import winston from 'winston';

// ───────────────────────────────────────────────────────────────────────────────
// Domain Models
// ───────────────────────────────────────────────────────────────────────────────

export interface InfraMetrics {
  timestamp: number; // epoch ms
  cpuUtil: number; // 0-100
  memUtil: number; // 0-100
  p95LatencyMs: number;
}

export interface SocialSignals {
  timestamp: number; // epoch ms
  likesPerSec: number;
  commentsPerSec: number;
  sharesPerSec: number;
  liveViews: number;
}

export interface ScaleDecision {
  action: 'scale_up' | 'scale_down' | 'maintain';
  delta: number; // positive => add N replicas, negative => remove N
  reason: string;
}

// ───────────────────────────────────────────────────────────────────────────────
// Logger
// ───────────────────────────────────────────────────────────────────────────────

const log = winston.createLogger({
  level: process.env.LOG_LEVEL ?? 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.splat(),
    winston.format.errors({ stack: true }),
    winston.format.json(),
  ),
  transports: [new winston.transports.Console()],
});

// ───────────────────────────────────────────────────────────────────────────────
// Strategy Pattern – Scaling algorithms
// ───────────────────────────────────────────────────────────────────────────────

export interface ScalingStrategy {
  readonly id: string;
  evaluate(
    infra: InfraMetrics[],
    social: SocialSignals[],
  ): ScaleDecision | Promise<ScaleDecision>;
}

/**
 * Strategy: ConservativeScalingStrategy
 *
 * Rules:
 *  • Scale up only when CPU > 70% _and_ social interaction rate > threshold
 *  • Scale down when CPU < 30% for sustained period
 */
export class ConservativeScalingStrategy implements ScalingStrategy {
  public readonly id = 'conservative';

  private static readonly CPU_UP_THRESHOLD = 0.7;
  private static readonly CPU_DOWN_THRESHOLD = 0.3;
  private static readonly SOCIAL_THRESHOLD = 500; // interactions/sec

  async evaluate(
    infra: InfraMetrics[],
    social: SocialSignals[],
  ): Promise<ScaleDecision> {
    const latestInfra = infra[infra.length - 1];
    const latestSocial = social[social.length - 1];

    if (
      latestInfra.cpuUtil / 100 > ConservativeScalingStrategy.CPU_UP_THRESHOLD &&
      ConservativeScalingStrategy.socialScore(latestSocial) >
        ConservativeScalingStrategy.SOCIAL_THRESHOLD
    ) {
      return {
        action: 'scale_up',
        delta: 2,
        reason: 'High CPU and social buzz detected',
      };
    }

    // Downscale only if CPU low for 5 consecutive intervals
    const lowCpu = infra.every(
      (m) => m.cpuUtil / 100 < ConservativeScalingStrategy.CPU_DOWN_THRESHOLD,
    );
    if (lowCpu) {
      return {
        action: 'scale_down',
        delta: -1,
        reason: 'CPU utilisation consistently low',
      };
    }

    return { action: 'maintain', delta: 0, reason: 'Within normal range' };
  }

  private static socialScore(s: SocialSignals): number {
    return s.likesPerSec + s.commentsPerSec + s.sharesPerSec + s.liveViews / 10;
  }
}

/**
 * Strategy: AggressiveScalingStrategy
 *
 * Rules:
 *  • Predicts near-future load using current social velocity
 *  • Scales fast in either direction; good for event-driven bursts
 */
export class AggressiveScalingStrategy implements ScalingStrategy {
  public readonly id = 'aggressive';

  async evaluate(
    infra: InfraMetrics[],
    social: SocialSignals[],
  ): Promise<ScaleDecision> {
    const latestSocial = social[social.length - 1];
    const velocity =
      latestSocial.likesPerSec *
        2 +
      latestSocial.commentsPerSec +
      latestSocial.sharesPerSec * 3 +
      latestSocial.liveViews / 5;

    if (velocity > 2000) {
      return {
        action: 'scale_up',
        delta: Math.ceil(velocity / 1000), // explode quickly
        reason: `Predicted viral spike (velocity=${velocity})`,
      };
    }

    if (velocity < 200 && infra[infra.length - 1].cpuUtil < 20) {
      return {
        action: 'scale_down',
        delta: -Math.max(1, Math.floor(200 / (velocity + 1))),
        reason: 'Traffic subsided',
      };
    }

    return { action: 'maintain', delta: 0, reason: 'Steady state' };
  }
}

// ───────────────────────────────────────────────────────────────────────────────
// Chain of Responsibility – Pre-processors
// ───────────────────────────────────────────────────────────────────────────────

type Processor<I, O> = (input: I) => O;

/**
 * Normalises CPU, memory to 0–1 range and truncates extraneous properties.
 */
const infraNormaliser: Processor<InfraMetrics, InfraMetrics> = (m) => ({
  timestamp: m.timestamp,
  cpuUtil: Math.min(Math.max(m.cpuUtil, 0), 100),
  memUtil: Math.min(Math.max(m.memUtil, 0), 100),
  p95LatencyMs: m.p95LatencyMs,
});

/**
 * Dedupes signals coming within 50 ms of each other (noise reduction).
 */
const socialDeDuper: Processor<SocialSignals[], SocialSignals[]> = (arr) => {
  const seen = new Set<number>();
  return arr.filter((sig) => {
    if (seen.has(sig.timestamp)) return false;
    seen.add(sig.timestamp);
    return true;
  });
};

// ───────────────────────────────────────────────────────────────────────────────
// Observer – Kafka Consumer (Event-Driven backbone)
// ───────────────────────────────────────────────────────────────────────────────

interface StreamConfig {
  kafkaBrokers: string[];
  infraTopic: string;
  socialTopic: string;
  groupId: string;
  readBatchMs: number;
}

export class SocialContextAwareAutoScaler {
  private readonly kafka: Kafka;
  private readonly consumer: Consumer;
  private readonly metrics$ = new Subject<InfraMetrics>();
  private readonly social$ = new Subject<SocialSignals>();

  private readonly strategies: Map<string, ScalingStrategy> = new Map();
  private readonly processorInterval: number;

  constructor(private readonly cfg: StreamConfig) {
    this.kafka = new Kafka({
      clientId: 'autoscaler-service',
      brokers: cfg.kafkaBrokers,
      connectionTimeout: 5_000,
      retry: { retries: 3 },
    });
    this.consumer = this.kafka.consumer({ groupId: cfg.groupId });
    this.processorInterval = cfg.readBatchMs;
    // Register default strategies; can be extended at runtime.
    this.registerStrategy(new ConservativeScalingStrategy());
    this.registerStrategy(new AggressiveScalingStrategy());
  }

  /** Register new strategy implementation at runtime */
  public registerStrategy(strategy: ScalingStrategy): void {
    this.strategies.set(strategy.id, strategy);
  }

  /** Bootstraps Kafka consumers & processing pipeline */
  public async start(strategyId: string): Promise<void> {
    const strategy = this.strategies.get(strategyId);
    if (!strategy) {
      throw new Error(`Unknown scaling strategy: ${strategyId}`);
    }

    await this.consumer.connect();
    await this.consumer.subscribe({ topic: this.cfg.infraTopic, fromBeginning: false });
    await this.consumer.subscribe({ topic: this.cfg.socialTopic, fromBeginning: false });

    log.info('SocialContextAwareAutoScaler started with strategy=%s', strategyId);

    // Kafka → RxJS bridge
    void this.consumer.run({
      autoCommit: true,
      eachMessage: async (payload: EachMessagePayload) => {
        const msg = payload.message.value?.toString();
        if (!msg) return;

        try {
          if (payload.topic === this.cfg.infraTopic) {
            this.metrics$.next(infraNormaliser(JSON.parse(msg)));
          } else if (payload.topic === this.cfg.socialTopic) {
            this.social$.next(JSON.parse(msg));
          }
        } catch (err) /* istanbul ignore next */ {
          log.warn('Failed to parse message: %s', err);
        }
      },
    });

    // Processing pipeline
    const infraBuffered$ = this.metrics$.pipe(
      bufferTime(this.processorInterval),
      filter((batch) => batch.length > 0),
    );

    const socialBuffered$ = this.social$.pipe(
      bufferTime(this.processorInterval),
      map(socialDeDuper),
      filter((batch) => batch.length > 0),
    );

    // Combine latest batches; if one stream is silent, wait up to interval*2 then continue
    merge(
      infraBuffered$.pipe(map((infra) => ({ infra, social: [] as SocialSignals[] }))),
      socialBuffered$.pipe(map((social) => ({ infra: [] as InfraMetrics[], social }))),
    )
      .pipe(
        // Achieve "zip-latest" semantics
        mergeMap(({ infra, social }) =>
          from(
            Promise.all([
              infra.length ? infra : this.peekLastBatch(infraBuffered$),
              social.length ? social : this.peekLastBatch(socialBuffered$),
            ]),
          ).pipe(
            timeoutWith(this.processorInterval * 2, from([[infra, social]])),
            map(([i, s]) => ({ infra: i, social: s })),
          ),
        ),
        catchError((err, caught) => {
          log.error('Stream processing error: %s', err);
          return caught;
        }),
      )
      .subscribe(async ({ infra, social }) => {
        try {
          const decision = await strategy.evaluate(infra, social);
          this.emitDecision(decision);
        } catch (err) /* istanbul ignore next */ {
          log.error('Strategy evaluation failed: %s', err);
        }
      });
  }

  public async stop(): Promise<void> {
    await this.consumer.disconnect();
    this.metrics$.complete();
    this.social$.complete();
    log.info('SocialContextAwareAutoScaler stopped');
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Helpers
  // ───────────────────────────────────────────────────────────────────────────

  private emitDecision(decision: ScaleDecision): void {
    // In production, publish to deployment-automation command topic or REST endpoint
    log.info('ScaleDecision: %o', decision);
  }

  /**
   * Snapshot last emitted batch from observable; used to merge uneven cadence streams.
   */
  private peekLastBatch<T>(obs: Observable<T[]>): Promise<T[]> {
    return new Promise<T[]>((resolve) => {
      let sub: any;
      sub = obs.subscribe({
        next: (v) => {
          resolve(v);
          sub.unsubscribe();
        },
        complete: () => resolve([]),
      });
    });
  }
}

// ───────────────────────────────────────────────────────────────────────────────
// Example bootstrap (executed only when run directly, not when imported)
// ───────────────────────────────────────────────────────────────────────────────
/* istanbul ignore next */
if (require.main === module) {
  // Minimal config via env vars
  const cfg: StreamConfig = {
    kafkaBrokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    infraTopic: process.env.INFRA_TOPIC || 'infra.metrics',
    socialTopic: process.env.SOCIAL_TOPIC || 'social.signals',
    groupId: process.env.GROUP_ID || 'autoscaler-group',
    readBatchMs: Number(process.env.BATCH_MS) || 5_000,
  };

  const scaler = new SocialContextAwareAutoScaler(cfg);

  scaler
    .start(process.env.SCALING_STRATEGY || 'conservative')
    .catch((err) => {
      log.error('Failed to start autoscaler: %s', err);
      process.exitCode = 1;
    });

  // Graceful shutdown
  process.on('SIGINT', async () => {
    log.info('SIGINT received');
    await scaler.stop();
    process.exit(0);
  });
}
```
