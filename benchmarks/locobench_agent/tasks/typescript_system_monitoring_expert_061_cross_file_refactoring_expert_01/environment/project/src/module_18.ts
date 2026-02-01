```typescript
/**************************************************************************************************
 *  PulseSphere SocialOps – AdaptiveCapacityPlanner
 *  ----------------------------------------------------------------------------
 *  File:        src/module_18.ts
 *  Description: Real-time, socially-aware capacity-planning engine that consumes
 *               social-interaction signals + system-health telemetry from Kafka,
 *               selects an appropriate scaling strategy (Strategy Pattern),
 *               and issues replica-count updates to the cluster control-plane.
 *
 *  Architectural patterns employed:
 *    • Strategy Pattern (pluggable scaling algorithms)
 *    • Chain-of-Responsibility (strategy selection pipeline)
 *    • Observer / Event-Driven (Kafka → RxJS observable → planner)
 *
 *  NOTE: This module does not perform direct I/O with Kubernetes; instead it
 *        calls a dedicated “orchestrator” micro-service over the service-mesh.
 **************************************************************************************************/

/* ------------------------------------ Imports ----------------------------------------------- */
import { Kafka, EachMessagePayload } from 'kafkajs';
import axios, { AxiosInstance } from 'axios';
import { Subject, debounceTime, map, filter, Subscription } from 'rxjs';
import * as _ from 'lodash';

// Internal shared utilities (logger, types, config)
import { Logger } from './utils/logger';
import { globalConfig } from './config/global-config';

/* ------------------------------------ Enums & Interfaces ------------------------------------ */

/** High-level categories for social interaction events */
export enum InteractionType {
  LIKE = 'LIKE',
  COMMENT = 'COMMENT',
  SHARE = 'SHARE',
  STREAM_VIEW = 'STREAM_VIEW',
}

/** Aggregated social-interaction snapshot for a given window */
export interface SocialSignalSnapshot {
  readonly timestamp: number; // epoch millis
  /** Map<InteractionType, count> */
  readonly interactions: Record<InteractionType, number>;
  readonly trendingHashtags: string[];
}

/** Aggregated infrastructure health snapshot */
export interface SystemHealthSnapshot {
  readonly timestamp: number;
  cpu: number;        // 0..1
  memory: number;     // 0..1
  errorRate: number;  // 0..1
  currentReplicas: number;
}

/** Output produced by scaling strategies */
export interface ScalingDecision {
  readonly desiredReplicas: number;
  readonly reason: string;
  readonly strategy: string;
  readonly timestamp: number;
}

/** Pluggable capacity-scaling strategy */
export interface CapacityScalingStrategy {
  readonly name: string;
  /** Whether this strategy is applicable for the given snapshot combination */
  supports(
    social: SocialSignalSnapshot,
    health: SystemHealthSnapshot,
  ): boolean;

  /** Produce a scaling decision; called only if supports() === true */
  computeDesiredReplicas(
    social: SocialSignalSnapshot,
    health: SystemHealthSnapshot,
  ): ScalingDecision;
}

/* ------------------------------------ Concrete Strategies ----------------------------------- */

/**
 * Strategy #1 – ViralSpikeStrategy
 * Detects huge interaction spikes or hashtag storms and proactively scales up.
 */
export class ViralSpikeStrategy implements CapacityScalingStrategy {
  public readonly name = 'ViralSpikeStrategy';

  private readonly interactionSpikeThreshold = 50_000;      // interactions / window
  private readonly trendingHashtagThreshold = 5;             // unique hashtags

  supports(social: SocialSignalSnapshot): boolean {
    const totalInteractions = _.sum(_.values(social.interactions));
    return (
      totalInteractions >= this.interactionSpikeThreshold ||
      social.trendingHashtags.length >= this.trendingHashtagThreshold
    );
  }

  computeDesiredReplicas(
    social: SocialSignalSnapshot,
    health: SystemHealthSnapshot,
  ): ScalingDecision {
    const totalInteractions = _.sum(_.values(social.interactions));

    // Increase replicas proportionally, but cap to 10× current.
    const multiplier = Math.min(
      10,
      Math.ceil(totalInteractions / this.interactionSpikeThreshold),
    );

    return {
      desiredReplicas: Math.max(
        health.currentReplicas,
        health.currentReplicas * multiplier,
      ),
      reason: `Viral spike detected (interactions=${totalInteractions}).`,
      strategy: this.name,
      timestamp: Date.now(),
    };
  }
}

/**
 * Strategy #2 – ErrorMitigationStrategy
 * When error rate is elevated, increase replicas moderately to absorb load.
 */
export class ErrorMitigationStrategy implements CapacityScalingStrategy {
  public readonly name = 'ErrorMitigationStrategy';

  private readonly errorRateThreshold = 0.05; // 5%

  supports(_: SocialSignalSnapshot, health: SystemHealthSnapshot): boolean {
    return health.errorRate >= this.errorRateThreshold;
  }

  computeDesiredReplicas(
    _: SocialSignalSnapshot,
    health: SystemHealthSnapshot,
  ): ScalingDecision {
    const bump = Math.ceil(health.currentReplicas * 0.3); // +30 %
    return {
      desiredReplicas: health.currentReplicas + bump,
      reason: `Elevated error rate (${(health.errorRate * 100).toFixed(
        1,
      )} %) detected.`,
      strategy: this.name,
      timestamp: Date.now(),
    };
  }
}

/**
 * Strategy #3 – SteadyStateStrategy
 * Default conservative behaviour when no other strategy matches.
 */
export class SteadyStateStrategy implements CapacityScalingStrategy {
  public readonly name = 'SteadyStateStrategy';

  supports(): boolean {
    return true; // Always applicable as a fallback.
  }

  computeDesiredReplicas(
    _: SocialSignalSnapshot,
    health: SystemHealthSnapshot,
  ): ScalingDecision {
    // Small adjustments to reach target CPU utilisation (~60 %)
    const targetCpu = 0.6;
    const diff = health.cpu - targetCpu;

    const adjustment =
      Math.abs(diff) < 0.05 ? 0 : Math.round(health.currentReplicas * diff); // ± until near target

    return {
      desiredReplicas: Math.max(1, health.currentReplicas - adjustment),
      reason: 'Maintain steady-state capacity.',
      strategy: this.name,
      timestamp: Date.now(),
    };
  }
}

/* ------------------------------------ AdaptiveCapacityPlanner -------------------------------- */

/**
 * Receives telemetry, selects a strategy via CoR, and forwards scaling decision
 * to the orchestration service.
 */
export class AdaptiveCapacityPlanner {
  private readonly strategies: CapacityScalingStrategy[];
  private readonly decisionSubject = new Subject<ScalingDecision>();
  private readonly logger = new Logger('AdaptiveCapacityPlanner');
  private readonly orchestratorClient: AxiosInstance;

  private subscription?: Subscription;

  constructor(strategies?: CapacityScalingStrategy[]) {
    // Chain-of-Responsibility order (priority).
    this.strategies = strategies ?? [
      new ViralSpikeStrategy(),
      new ErrorMitigationStrategy(),
      new SteadyStateStrategy(),
    ];

    this.orchestratorClient = axios.create({
      baseURL: globalConfig.internalApi.orchestratorUrl,
      timeout: 5_000,
      headers: { 'x-service-account': globalConfig.auth.serviceAccountToken },
    });
  }

  /**
   * Start consuming snapshots. Emits a scaling decision at most every 5 s to
   * prevent thrashing.
   */
  public start(
    socialStream$: Subject<SocialSignalSnapshot>,
    healthStream$: Subject<SystemHealthSnapshot>,
  ): void {
    if (this.subscription) {
      throw new Error('Planner is already started.');
    }

    // Combine the two streams by timestamp proximity (within same tick).
    const combined$ = socialStream$
      .pipe(
        debounceTime(50),
        map((social) => ({ social })),
      )
      .pipe(
        // Map to latest health snapshot (simple in-memory storage)
        map(({ social }) => {
          const health = AdaptiveCapacityPlanner.latestHealthSnapshot;
          return health ? { social, health } : null;
        }),
        filter((payload): payload is { social: SocialSignalSnapshot; health: SystemHealthSnapshot } => Boolean(payload)),
        debounceTime(5_000), // emit at most every 5 s
      );

    this.subscription = combined$.subscribe({
      next: ({ social, health }) => this.handleSnapshot(social, health),
      error: (err) => this.logger.error('Stream error', err),
    });
  }

  public stop(): void {
    this.subscription?.unsubscribe();
  }

  /** Hook for health telemetry updates (called externally). */
  public static updateHealthSnapshot(snapshot: SystemHealthSnapshot): void {
    AdaptiveCapacityPlanner.latestHealthSnapshot = snapshot;
  }
  private static latestHealthSnapshot?: SystemHealthSnapshot;

  /* ------------------------------ Private helpers ------------------------------ */

  private handleSnapshot(
    social: SocialSignalSnapshot,
    health: SystemHealthSnapshot,
  ): void {
    const strategy = this.selectStrategy(social, health);
    const decision = strategy.computeDesiredReplicas(social, health);

    // Publish decision internally
    this.decisionSubject.next(decision);

    // Execute scaling via orchestrator
    this.applyScaling(decision).catch((err) =>
      this.logger.error('Failed to apply scaling decision', err),
    );
  }

  private selectStrategy(
    social: SocialSignalSnapshot,
    health: SystemHealthSnapshot,
  ): CapacityScalingStrategy {
    const matched = this.strategies.find((s) => s.supports(social, health));
    const chosen = matched ?? this.strategies[this.strategies.length - 1];

    this.logger.debug(
      `Selected strategy=${chosen.name} (currentReplicas=${health.currentReplicas})`,
    );

    return chosen;
  }

  private async applyScaling(decision: ScalingDecision): Promise<void> {
    try {
      await this.orchestratorClient.post('/scale', decision);
      this.logger.info(
        `Applied scaling: replicas=${decision.desiredReplicas} (${decision.strategy})`,
      );
    } catch (err) {
      // If orchestrator is down, nothing we can do—log and continue.
      this.logger.error(
        `Could not apply scaling (replicas=${decision.desiredReplicas})`,
        err,
      );
    }
  }

  /* ------------------------------ Observer accessors ------------------------------ */

  /** Expose read-only observable for downstream consumers (e.g., UI). */
  public decisions$(): Subject<ScalingDecision> {
    return this.decisionSubject;
  }
}

/* ------------------------------------ Kafka Integration ------------------------------------- */

type SnapshotTopicMapping = {
  socialTopic: string;
  healthTopic: string;
};

const mapping: SnapshotTopicMapping = {
  socialTopic: globalConfig.kafka.topics.socialSnapshot,
  healthTopic: globalConfig.kafka.topics.healthSnapshot,
};

export async function startKafkaSnapshotConsumers(
  planner: AdaptiveCapacityPlanner,
): Promise<void> {
  const kafka = new Kafka({
    clientId: 'adaptive-capacity-planner',
    brokers: globalConfig.kafka.brokers,
    connectionTimeout: 3_000,
  });

  const consumer = kafka.consumer({ groupId: 'capacity-planner-group' });

  await consumer.connect();
  await consumer.subscribe({ topic: mapping.socialTopic, fromBeginning: false });
  await consumer.subscribe({ topic: mapping.healthTopic, fromBeginning: false });

  const social$ = new Subject<SocialSignalSnapshot>();

  await consumer.run({
    eachMessage: async ({ topic, message }: EachMessagePayload) => {
      try {
        if (!message.value) {
          return;
        }

        const parsed = JSON.parse(message.value.toString());

        if (topic === mapping.socialTopic) {
          social$.next(parsed as SocialSignalSnapshot);
        } else if (topic === mapping.healthTopic) {
          AdaptiveCapacityPlanner.updateHealthSnapshot(
            parsed as SystemHealthSnapshot,
          );
        }
      } catch (err) {
        // Graceful parse failure handling
        // eslint-disable-next-line no-console
        console.error(`Failed to process Kafka message on topic ${topic}`, err);
      }
    },
  });

  planner.start(social$, new Subject<SystemHealthSnapshot>());
}

/* ------------------------------------ Bootstrap (CLI) --------------------------------------- */

if (require.main === module) {
  // Run as standalone process (Docker-sidecar or k8s Cron Job)
  const logger = new Logger('module_18');

  (async () => {
    try {
      const planner = new AdaptiveCapacityPlanner();
      await startKafkaSnapshotConsumers(planner);
      logger.info('AdaptiveCapacityPlanner started.');
    } catch (err) {
      logger.error('Fatal error during bootstrap', err);
      process.exit(1);
    }
  })();
}
```
