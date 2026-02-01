```typescript
/**
 * PulseSphere SocialOps – Capacity Planner Module
 * ------------------------------------------------
 * This module correlates social signals with traditional infrastructure
 * metrics to proactively decide cluster scaling actions.
 *
 * Patterns used:
 *   • Strategy —— Multiple scaling strategies (reactive / conservative)
 *   • Observer  —— RxJS streams to observe Kafka / NATS event buses
 *   • Command   —— Generated `ScalingDecision` is a command pushed to an
 *                  orchestration topic (handled by a dedicated scaler svc)
 */

import { Subject, merge, Observable, Subscription, throttleTime, filter, map } from 'rxjs';
import { Logger } from '@pulsesphere/common-logging';
import { KafkaConsumer } from '@pulsesphere/eventing-kafka'; // Thin wrapper around kafkajs
import { NatsSubscriber } from '@pulsesphere/eventing-nats';
import { v4 as uuid } from 'uuid';
import convict from 'convict';

// -----------------------------------------------------------------------------
// Configuration
// -----------------------------------------------------------------------------
const config = convict({
  capacityPlanner: {
    decisionIntervalMs: {
      doc: 'Minimum interval between two consecutive scaling decisions per cluster',
      format: 'nat',
      default: 10_000,
      env: 'PS_DECISION_INTERVAL_MS'
    },
    socialSignalWeight: {
      doc: 'Multiplicative factor for social-weighted request prediction',
      format: Number,
      default: 1.3,
      env: 'PS_SOCIAL_SIGNAL_WEIGHT'
    },
    cpuTarget: {
      doc: 'Target CPU utilisation ratio (0…1)',
      format: (val: number) => {
        if (val <= 0 || val > 1) throw new Error('cpuTarget must be in (0,1]');
      },
      default: 0.70,
      env: 'PS_TARGET_CPU'
    },
    strategy: {
      doc: 'Scaling strategy [reactive|conservative]',
      format: ['reactive', 'conservative'],
      default: 'reactive',
      env: 'PS_SCALING_STRATEGY'
    }
  }
}).get('capacityPlanner');

// -----------------------------------------------------------------------------
// Domain Types
// -----------------------------------------------------------------------------
export enum SocialEventType {
  LIKE = 'LIKE',
  COMMENT = 'COMMENT',
  SHARE = 'SHARE',
  LIVE_STREAM_START = 'LIVE_STREAM_START',
  LIVE_STREAM_PEAK = 'LIVE_STREAM_PEAK'
}

export interface SocialSignal {
  id: string;
  applicationId: string;
  clusterId: string;
  eventType: SocialEventType;
  userId: string;
  timestamp: number; // epoch ms
  weight: number;
}

export interface InfraMetric {
  clusterId: string;
  applicationId: string;
  cpu: number; // utilisation ratio 0..1
  memory: number; // utilisation ratio 0..1
  rps: number; // requests per second
  timestamp: number;
}

export interface CorrelatedMetrics {
  clusterId: string;
  applicationId: string;
  effectiveRps: number;
  avgCpu: number;
  avgMemory: number;
}

export interface ScalingDecision {
  decisionId: string;
  clusterId: string;
  applicationId: string;
  desiredReplicas: number;
  reason: string;
  createdAt: number;
}

// -----------------------------------------------------------------------------
// Strategy Pattern
// -----------------------------------------------------------------------------
interface ScalingStrategy {
  makeDecision(metrics: CorrelatedMetrics, currentReplicas: number): ScalingDecision | null;
}

class ReactiveScalingStrategy implements ScalingStrategy {
  constructor(private readonly logger: Logger) {}

  makeDecision(metrics: CorrelatedMetrics, currentReplicas: number): ScalingDecision | null {
    const projectedReplicas = Math.ceil(
      (metrics.avgCpu / config.cpuTarget) * currentReplicas
    );

    if (projectedReplicas === currentReplicas) {
      this.logger.debug(`Reactive strategy: No scaling needed for cluster=${metrics.clusterId}`);
      return null;
    }

    return {
      decisionId: uuid(),
      clusterId: metrics.clusterId,
      applicationId: metrics.applicationId,
      desiredReplicas: projectedReplicas,
      reason: `CPU avg ${metrics.avgCpu.toFixed(2)} requires adjustment toward target ${config.cpuTarget}`,
      createdAt: Date.now()
    };
  }
}

class ConservativeScalingStrategy implements ScalingStrategy {
  constructor(private readonly logger: Logger) {}

  makeDecision(metrics: CorrelatedMetrics, currentReplicas: number): ScalingDecision | null {
    // Only scale up if CPU > 0.85 or effectiveRps exceeded 130% of historical baseline
    if (metrics.avgCpu > 0.85) {
      const newReplicas = currentReplicas + 1;
      return {
        decisionId: uuid(),
        clusterId: metrics.clusterId,
        applicationId: metrics.applicationId,
        desiredReplicas: newReplicas,
        reason: `High CPU (${metrics.avgCpu.toFixed(2)}) detected`,
        createdAt: Date.now()
      };
    }

    // Scale down if CPU < 0.40 for prolonged period (handled by external decay process)
    return null;
  }
}

// -----------------------------------------------------------------------------
// Capacity Planner (Observer + Command)
// -----------------------------------------------------------------------------
export class CapacityPlanner {
  private readonly logger = new Logger('CapacityPlanner');
  private readonly social$ = new Subject<SocialSignal>();
  private readonly infra$ = new Subject<InfraMetric>();
  private readonly decisions$ = new Subject<ScalingDecision>();
  private readonly subscriptions = new Subscription();
  private readonly strategy: ScalingStrategy;
  private readonly lastDecisionAt: Map<string, number> = new Map();
  private readonly replicaCache: Map<string, number> = new Map(); // clusterId -> replicas

  constructor(
    private readonly kafkaConsumer: KafkaConsumer,
    private readonly natsSubscriber: NatsSubscriber
  ) {
    this.strategy =
      config.strategy === 'reactive'
        ? new ReactiveScalingStrategy(this.logger)
        : new ConservativeScalingStrategy(this.logger);
  }

  /**
   * Initialise stream subscriptions to event buses
   */
  public async init(): Promise<void> {
    await Promise.all([this.kafkaConsumer.connect(), this.natsSubscriber.connect()]);

    // Social signals from NATS
    this.subscriptions.add(
      this.natsSubscriber
        .subscribe<SocialSignal>('social.signals.*')
        .pipe(
          map((msg) => msg.data),
          filter((sig) => !!sig.clusterId) // Filter out invalid events early
        )
        .subscribe({
          next: (sig) => this.social$.next(sig),
          error: (err) => this.logger.error('NATS subscription error', err)
        })
    );

    // Infra metrics from Kafka
    this.subscriptions.add(
      this.kafkaConsumer
        .subscribe<InfraMetric>({ topic: 'infra.metrics', fromBeginning: false })
        .pipe(map((m) => m.value))
        .subscribe({
          next: (metric) => this.infra$.next(metric),
          error: (err) => this.logger.error('Kafka subscription error', err)
        })
    );

    // Correlation & decision pipeline
    this.subscriptions.add(
      this.createCorrelationStream()
        .pipe(throttleTime(config.decisionIntervalMs))
        .subscribe({
          next: (correlated) => this.handleMetrics(correlated),
          error: (err) => this.logger.error('Correlation pipeline error', err)
        })
    );

    this.logger.info('CapacityPlanner initialised');
  }

  /**
   * Clean up resources
   */
  public async shutdown(): Promise<void> {
    this.subscriptions.unsubscribe();
    await Promise.all([this.kafkaConsumer.disconnect(), this.natsSubscriber.disconnect()]);
    this.logger.info('CapacityPlanner shut down');
  }

  /**
   * Expose the decision observable for downstream consumers
   */
  public decisions(): Observable<ScalingDecision> {
    return this.decisions$.asObservable();
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  private createCorrelationStream(): Observable<CorrelatedMetrics> {
    // Map clusterId -> aggregated stats
    const socialAgg: Record<string, { score: number }> = {};
    const infraAgg: Record<string, InfraMetric> = {};

    // Merge the two streams
    return merge(this.social$, this.infra$).pipe(
      map((event) => {
        if ('eventType' in event) {
          // SocialSignal
          const sig = event as SocialSignal;
          const key = sig.clusterId;
          const factor = this.computeSignalWeight(sig);
          socialAgg[key] = { score: (socialAgg[key]?.score ?? 0) + factor };
        } else {
          // InfraMetric
          const metric = event as InfraMetric;
          infraAgg[metric.clusterId] = metric;
        }

        const results: CorrelatedMetrics[] = [];

        for (const clusterId of Object.keys(infraAgg)) {
          const infra = infraAgg[clusterId];
          const socialScore = socialAgg[clusterId]?.score ?? 0;
          const effectiveRps = infra.rps + socialScore * config.socialSignalWeight;

          results.push({
            clusterId,
            applicationId: infra.applicationId,
            effectiveRps,
            avgCpu: infra.cpu,
            avgMemory: infra.memory
          });

          // Reset social score after each read to avoid duplication
          socialAgg[clusterId] = { score: 0 };
        }

        // Return array; will be expanded by RxJS flatMap later
        return results;
      }),
      // Flatten
      map((arr) => arr).pipe(flattenArrayOperator()) // custom operator below
    );
  }

  private handleMetrics(metrics: CorrelatedMetrics): void {
    const clusterId = metrics.clusterId;
    const now = Date.now();
    const lastAt = this.lastDecisionAt.get(clusterId) ?? 0;

    if (now - lastAt < config.decisionIntervalMs) {
      this.logger.debug(`Skipping decision for cluster=${clusterId} (cooldown)`);
      return;
    }

    const currentReplicas = this.replicaCache.get(clusterId) ?? 1;
    const decision = this.strategy.makeDecision(metrics, currentReplicas);

    if (decision) {
      this.logger.info(
        `Scaling decision generated for cluster=${clusterId}: ${currentReplicas} -> ${decision.desiredReplicas}`
      );
      this.replicaCache.set(clusterId, decision.desiredReplicas);
      this.lastDecisionAt.set(clusterId, now);
      this.decisions$.next(decision);
    }
  }

  private computeSignalWeight(sig: SocialSignal): number {
    switch (sig.eventType) {
      case SocialEventType.LIVE_STREAM_PEAK:
        return 5;
      case SocialEventType.LIVE_STREAM_START:
        return 3;
      case SocialEventType.SHARE:
        return 2;
      case SocialEventType.COMMENT:
        return 1.5;
      case SocialEventType.LIKE:
      default:
        return 1;
    }
  }
}

// -----------------------------------------------------------------------------
// RxJS Custom Operator to flatten CorrelatedMetrics[][] -> CorrelatedMetrics[]
// -----------------------------------------------------------------------------
import { OperatorFunction } from 'rxjs';
import { from } from 'rxjs';
import { mergeMap } from 'rxjs/operators';

function flattenArrayOperator<T>(): OperatorFunction<T[], T> {
  return (source) => source.pipe(mergeMap((value) => from(value)));
}

// -----------------------------------------------------------------------------
// Module Usage Example (to be bootstrapped by DI container)
// -----------------------------------------------------------------------------
/*
(async () => {
  const kafka = new KafkaConsumer({ clientId: 'capacity-planner', brokers: ['kafka:9092'] });
  const nats = new NatsSubscriber({ servers: ['nats://nats:4222'] });

  const planner = new CapacityPlanner(kafka, nats);
  await planner.init();

  planner.decisions().subscribe({
    next: (decision) => {
      // Publish to orchestrator topic, e.g. 'cluster.scaling'
      console.log('ScalingDecision:', decision);
    }
  });

  // Graceful shutdown
  process.on('SIGINT', async () => {
    await planner.shutdown();
    process.exit(0);
  });
})();
*/

// -----------------------------------------------------------------------------
// Type augmentation for external libraries (example placeholders)
// -----------------------------------------------------------------------------
declare module '@pulsesphere/eventing-kafka' {
  import { Observable } from 'rxjs';

  export interface KafkaConsumer {
    connect(): Promise<void>;
    disconnect(): Promise<void>;
    subscribe<T>(opts: { topic: string; fromBeginning: boolean }): Observable<{ value: T }>;
  }

  export class KafkaConsumer {
    constructor(params: Record<string, unknown>);
  }
}

declare module '@pulsesphere/eventing-nats' {
  import { Observable } from 'rxjs';

  export interface NatsSubscriber {
    connect(): Promise<void>;
    disconnect(): Promise<void>;
    subscribe<T>(subject: string): Observable<{ data: T }>;
  }

  export class NatsSubscriber {
    constructor(params: Record<string, unknown>);
  }
}

declare module '@pulsesphere/common-logging' {
  export class Logger {
    constructor(component: string);
    info(msg: string, meta?: unknown): void;
    debug(msg: string, meta?: unknown): void;
    error(msg: string, meta?: unknown): void;
  }
}
```