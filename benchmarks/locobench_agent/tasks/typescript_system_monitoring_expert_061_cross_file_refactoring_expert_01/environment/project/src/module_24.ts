```typescript
/***************************************************************************************************
 *  File:          src/module_24.ts
 *  Project:       PulseSphere SocialOps (system_monitoring)
 *  Description:   Social-context aware, pluggable autoscaling engine.  The engine consumes
 *                 infrastructure metrics + real-time social-interaction signals, applies a
 *                 configurable chain of ScalingStrategies, and emits ScalingDecisionEvents to the
 *                 event backbone (Kafka + NATS) for downstream capacity-orchestration services.
 *
 *  Architectural  Patterns demonstrated:
 *                 • Observer                        – RxJS observables for live telemetry streams.
 *                 • Strategy                        – Swappable ScalingStrategy implementations.
 *                 • Chain-of-Responsibility         – Strategies executed sequentially until one
 *                                                     produces a decision.
 *                 • Command                         – ScalingDecisionEvent acts as a command
 *                                                     representing the desired scaling action.
 *
 *  NOTE: This module purposefully avoids framework-specific wiring (e.g., NestJS, Inversify)
 *        to keep it framework-agnostic and easy to integrate into existing services.
 ***************************************************************************************************/

import { Kafka, Producer, logLevel as KafkaLogLevel } from 'kafkajs';
import { connect as connectNats, NatsConnection, StringCodec } from 'nats';
import {
  Observable,
  Subject,
  merge,
  bufferTime,
  catchError,
  map,
  filter,
  tap,
} from 'rxjs';
import pino from 'pino';
import os from 'os';

/* =================================================================================================
 * Type & Interface Definitions
 * ===============================================================================================*/

/**
 * Infrastructure metric sampled from Prometheus / OpenTelemetry pipeline.
 * Example: { cpuLoad: 0.73, memUsage: 0.66, tenant: 'europe', ts: 1661299128911 }
 */
export interface MetricEvent {
  readonly ts: number; // epoch millis
  readonly tenant: string; // shard / tenant / cluster id
  readonly cpuLoad: number; // 0-1
  readonly memUsage: number; // 0-1
}

/**
 * Social interaction signal (likes, comments, shares, etc.) aggregated every few seconds.
 */
export interface SocialSignalEvent {
  readonly ts: number;
  readonly tenant: string;
  readonly interactionRate: number; // events per second
  readonly hashtag?: string;
}

/**
 * A command that instructs downstream services to scale a cluster up/down.
 */
export interface ScalingDecisionEvent {
  readonly ts: number;
  readonly tenant: string;
  readonly desiredReplicas: number;
  readonly rationale: string;
}

/**
 * Encapsulates a scaling strategy.
 */
export interface ScalingStrategy {
  /**
   * Inspect collected metrics + signals and decide whether to scale.
   *
   * @param metrics      Aggregated infra metrics
   * @param socialSignal Aggregated social interaction rate
   *
   * @returns ScalingDecisionEvent | null – Return null if the strategy chooses to abstain.
   */
  evaluate(
    metrics: AggregatedMetric,
    socialSignal: AggregatedSocialSignal,
  ): ScalingDecisionEvent | null;
}

/* =================================================================================================
 * Helper Aggregation Structures
 * ===============================================================================================*/

export interface AggregatedMetric {
  readonly windowStart: number;
  readonly windowEnd: number;
  readonly tenant: string;
  readonly avgCpuLoad: number;
  readonly avgMemUsage: number;
}

export interface AggregatedSocialSignal {
  readonly windowStart: number;
  readonly windowEnd: number;
  readonly tenant: string;
  readonly avgInteractionRate: number;
}

/* =================================================================================================
 * Logger
 * ===============================================================================================*/
const logger = pino({
  name: 'SocialContextAwareScaler',
  level: process.env.LOG_LEVEL ?? 'info',
  base: {
    hostname: os.hostname(),
    pid: process.pid,
  },
});

/* =================================================================================================
 * Default Scaling Strategies
 * ===============================================================================================*/

/**
 * A simple linear scaling strategy: scale up when CPU or memory crosses threshold.
 */
export class BasicLinearScalingStrategy implements ScalingStrategy {
  private readonly cpuThreshold: number;
  private readonly memThreshold: number;
  private readonly step: number;

  constructor({
    cpuThreshold = 0.75,
    memThreshold = 0.80,
    step = 2,
  }: Partial<{ cpuThreshold: number; memThreshold: number; step: number }> = {}) {
    this.cpuThreshold = cpuThreshold;
    this.memThreshold = memThreshold;
    this.step = step;
  }

  evaluate(
    metrics: AggregatedMetric,
    _social: AggregatedSocialSignal,
  ): ScalingDecisionEvent | null {
    const { avgCpuLoad, avgMemUsage } = metrics;
    if (avgCpuLoad > this.cpuThreshold || avgMemUsage > this.memThreshold) {
      const target = Math.ceil(((avgCpuLoad + avgMemUsage) / 2) * 10) + this.step;
      return {
        ts: Date.now(),
        tenant: metrics.tenant,
        desiredReplicas: target,
        rationale: `LinearScaling: CPU=${avgCpuLoad.toFixed(
          2,
        )}, MEM=${avgMemUsage.toFixed(2)}`,
      };
    }
    return null;
  }
}

/**
 * Burst-aware strategy: looks for sudden social-interaction spikes and scales pre-emptively.
 */
export class BurstAwareScalingStrategy implements ScalingStrategy {
  private readonly interactionSpikeFactor: number;
  private readonly minIncrease: number;

  // Cache last interaction rate per tenant to detect spikes
  private readonly lastInteractionRate: Map<string, number> = new Map();

  constructor(
    interactionSpikeFactor = 2.5, // multiplier
    minIncrease = 3, // minimum extra replicas
  ) {
    this.interactionSpikeFactor = interactionSpikeFactor;
    this.minIncrease = minIncrease;
  }

  evaluate(
    _metrics: AggregatedMetric,
    socialSignal: AggregatedSocialSignal,
  ): ScalingDecisionEvent | null {
    const { tenant, avgInteractionRate } = socialSignal;
    const previous = this.lastInteractionRate.get(tenant) ?? 0;

    // Store current for next evaluation
    this.lastInteractionRate.set(tenant, avgInteractionRate);

    if (previous === 0) {
      return null; // not enough data yet
    }

    const spikeRatio = avgInteractionRate / previous;
    if (spikeRatio >= this.interactionSpikeFactor) {
      return {
        ts: Date.now(),
        tenant,
        desiredReplicas: Math.ceil(spikeRatio * this.minIncrease),
        rationale: `BurstAwareScaling: Interaction spike x${spikeRatio.toFixed(2)}`,
      };
    }
    return null;
  }
}

/* =================================================================================================
 * SocialContextAwareScaler – Strategy Chain Orchestrator
 * ===============================================================================================*/

export interface ScalerConfig {
  tenant: string;
  bufferTimeMs: number;
  strategies: ScalingStrategy[];
  kafkaBrokers: string[];
  kafkaTopic: string;
  natsUrl: string;
}

export class SocialContextAwareScaler {
  private readonly metric$ = new Subject<MetricEvent>();
  private readonly social$ = new Subject<SocialSignalEvent>();

  private readonly aggregatedMetric$: Observable<AggregatedMetric>;
  private readonly aggregatedSocial$: Observable<AggregatedSocialSignal>;
  private readonly strategyChain: ScalingStrategy[];

  private readonly kafkaProducer: Producer;
  private natsConnection!: NatsConnection;
  private readonly sc = StringCodec();

  constructor(private readonly cfg: ScalerConfig) {
    this.strategyChain = cfg.strategies;

    // ----------------------------------
    // Aggregate infra metrics per window
    // ----------------------------------
    this.aggregatedMetric$ = this.metric$.pipe(
      bufferTime(cfg.bufferTimeMs),
      filter((buf) => buf.length > 0),
      map((buf) => this.aggregateMetrics(buf)),
    );

    // ----------------------------------
    // Aggregate social signals per window
    // ----------------------------------
    this.aggregatedSocial$ = this.social$.pipe(
      bufferTime(cfg.bufferTimeMs),
      filter((buf) => buf.length > 0),
      map((buf) => this.aggregateSocial(buf)),
    );

    // Kafka producer
    const kafka = new Kafka({
      brokers: cfg.kafkaBrokers,
      clientId: `scaler-${cfg.tenant}-${os.hostname()}`,
      logLevel: KafkaLogLevel.ERROR,
    });
    this.kafkaProducer = kafka.producer({
      allowAutoTopicCreation: false,
    });
  }

  /**
   * Starts streaming, decision evaluation, and event publication.
   */
  async start(): Promise<void> {
    await this.kafkaProducer.connect();
    this.natsConnection = await connectNats({ servers: this.cfg.natsUrl });

    // Combine aggregations on each window and run strategy chain
    merge(this.aggregatedMetric$, this.aggregatedSocial$)
      .pipe(
        // Wait until both aggregated values for current window exist
        // Use a simple stateful merge to pair metric + social for same window.
        this.pairWindow(),
        tap(({ metric, social }) => {
          const decision = this.runStrategyChain(metric, social);
          if (decision) {
            this.publishDecision(decision).catch((err) =>
              logger.error(
                { err, tenant: this.cfg.tenant },
                'Failed to publish scaling decision',
              ),
            );
          }
        }),
        catchError((err, caught) => {
          logger.error({ err }, 'Stream processing error');
          return caught;
        }),
      )
      .subscribe();
  }

  /**
   * Push incoming raw events into the scaler.
   */
  onMetricEvent(event: MetricEvent): void {
    if (event.tenant !== this.cfg.tenant) return;
    this.metric$.next(event);
  }

  onSocialSignal(event: SocialSignalEvent): void {
    if (event.tenant !== this.cfg.tenant) return;
    this.social$.next(event);
  }

  /**
   * Graceful shutdown.
   */
  async stop(): Promise<void> {
    await Promise.allSettled([this.kafkaProducer.disconnect(), this.natsConnection?.drain()]);
  }

  /* ---------------------------------------------------------------------------------------------
   * Internal Helpers
   * ------------------------------------------------------------------------------------------ */

  private aggregateMetrics(buf: MetricEvent[]): AggregatedMetric {
    const avgCpu = buf.reduce((acc, e) => acc + e.cpuLoad, 0) / buf.length;
    const avgMem = buf.reduce((acc, e) => acc + e.memUsage, 0) / buf.length;
    return {
      windowStart: buf[0].ts,
      windowEnd: buf[buf.length - 1].ts,
      tenant: buf[0].tenant,
      avgCpuLoad: avgCpu,
      avgMemUsage: avgMem,
    };
  }

  private aggregateSocial(buf: SocialSignalEvent[]): AggregatedSocialSignal {
    const avgRate = buf.reduce((acc, e) => acc + e.interactionRate, 0) / buf.length;
    return {
      windowStart: buf[0].ts,
      windowEnd: buf[buf.length - 1].ts,
      tenant: buf[0].tenant,
      avgInteractionRate: avgRate,
    };
  }

  /**
   * Custom RxJS operator: pairs the latest AggregatedMetric & AggregatedSocialSignal belonging to
   * the same window. It maintains simple in-memory caches; suitable for small window counts.
   */
  private pairWindow() {
    type Pair =
      | { type: 'metric'; data: AggregatedMetric }
      | { type: 'social'; data: AggregatedSocialSignal };

    return (source: Observable<AggregatedMetric | AggregatedSocialSignal>) =>
      new Observable<{ metric: AggregatedMetric; social: AggregatedSocialSignal }>((subscriber) => {
        let metricCache: AggregatedMetric | null = null;
        let socialCache: AggregatedSocialSignal | null = null;

        const subscription = source.subscribe({
          next: (ev) => {
            const wrapped: Pair =
              'avgCpuLoad' in ev
                ? { type: 'metric', data: ev }
                : { type: 'social', data: ev };

            if (wrapped.type === 'metric') {
              metricCache = wrapped.data;
            } else {
              socialCache = wrapped.data;
            }

            if (metricCache && socialCache) {
              subscriber.next({ metric: metricCache, social: socialCache });
              // Reset caches after emission
              metricCache = null;
              socialCache = null;
            }
          },
          error: (err) => subscriber.error(err),
          complete: () => subscriber.complete(),
        });

        return () => subscription.unsubscribe();
      });
  }

  /**
   * Runs the configured strategy chain until one returns a non-null decision.
   */
  private runStrategyChain(
    metric: AggregatedMetric,
    social: AggregatedSocialSignal,
  ): ScalingDecisionEvent | null {
    for (const strat of this.strategyChain) {
      try {
        const decision = strat.evaluate(metric, social);
        if (decision) {
          logger.info(
            {
              tenant: decision.tenant,
              rationale: decision.rationale,
              desiredReplicas: decision.desiredReplicas,
            },
            `Scaling decision produced by ${strat.constructor.name}`,
          );
          return decision;
        }
      } catch (err) {
        logger.warn(
          { err, strategy: strat.constructor.name },
          'Strategy evaluation failed – continuing with next strategy',
        );
      }
    }
    return null;
  }

  /**
   * Publishes scaling decision to Kafka (primary) and NATS (secondary/fallback).
   */
  private async publishDecision(decision: ScalingDecisionEvent): Promise<void> {
    // Kafka
    await this.kafkaProducer.send({
      topic: this.cfg.kafkaTopic,
      messages: [{ key: decision.tenant, value: JSON.stringify(decision) }],
    });

    // NATS
    this.natsConnection.publish(
      this.cfg.kafkaTopic, // re-use topic string for subject
      this.sc.encode(JSON.stringify(decision)),
    );
  }
}

/* =================================================================================================
 * Factory Helper
 * ===============================================================================================*/

/**
 * Create a default scaler instance for given tenant with two pre-configured strategies.
 */
export function createDefaultScaler(tenant: string): SocialContextAwareScaler {
  const bufferTimeMs = parseInt(process.env.SCALER_WINDOW_MS ?? '5000', 10);
  return new SocialContextAwareScaler({
    tenant,
    bufferTimeMs,
    strategies: [
      new BurstAwareScalingStrategy(), // first handle social spikes
      new BasicLinearScalingStrategy(), // fallback to infra pressure
    ],
    kafkaBrokers: (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
    kafkaTopic: process.env.KAFKA_SCALING_TOPIC ?? 'scaling.decisions',
    natsUrl: process.env.NATS_URL ?? 'nats://localhost:4222',
  });
}
```