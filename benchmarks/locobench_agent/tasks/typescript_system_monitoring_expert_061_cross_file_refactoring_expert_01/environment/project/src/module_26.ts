```typescript
/**
 * File: module_26.ts
 * Project: PulseSphere SocialOps (system_monitoring)
 *
 * Description:
 *  Adaptive, socially-aware capacity-scaling module.
 *
 *  In PulseSphere each incoming telemetry stream (infra metrics, user signals,
 *  traces) is enriched then routed through an event backbone.  This file adds an
 *  opinionated Strategy implementation that listens for correlated “spike
 *  alerts” (e.g. a trending hashtag or influencer live-stream) and chooses the
 *  best-fit CapacityScalingStrategy at runtime.
 *
 *  A “strategy” in this context is an algorithm that decides how many
 *  Kubernetes replicas (or VM’s, pods, etc.) to scale for a target service.
 *
 *  – ConservativeStrategy : small, safe step-ups – default
 *  – AggressiveStrategy   : big increments until saturation (for flash crowds)
 *  – BurstStrategy        : immediate, temporary over-provision then rollback
 *
 *  The module exposes a high-level SocialAwareScaler which:
 *   • Subscribes to social-signal events from Kafka/NATS
 *   • Pulls current infra metrics via the InternalMetricsClient
 *   • Chooses & executes the scaling algorithm
 *
 *  All public types are exported to enable re-use by other bounded contexts.
 *
 * NOTE: Actual I/O (real Kafka, K8s client) is abstracted behind interfaces so
 *       that the code remains testable and side-effect-free by default.
 */

import { Kafka, Admin, EachMessagePayload, logLevel } from 'kafkajs';
import { Logger } from 'pino';
import * as uuid from 'uuid';

//#region ————————————————————————————————————  Domain Types & Interfaces ————

/**
 * Normalized social interaction signal produced by PulseSphere’s enrichment
 * pipeline.
 */
export interface SocialSignal {
  readonly id: string;
  readonly service: string;          // micro-service or bounded context name
  readonly hashtag?: string;         // #trending 🔥
  readonly influencerId?: string;    // userId of the influencer causing surge
  readonly region?: string;          // geo-region (for edge scaling)
  readonly interactionsPerSecond: number;
  readonly timestamp: number;        // epoch millis
}

/**
 * Infrastructure utilisation metrics relevant for scaling decisions.
 */
export interface InfraMetrics {
  readonly cpu: number;              // %
  readonly memory: number;           // %
  readonly rps: number;              // requests/sec
  readonly errorRate: number;        // 0-1
  readonly timestamp: number;
}

/**
 * Abstraction over internal metrics system (Prometheus, OpenTelemetry, etc.)
 */
export interface InternalMetricsClient {
  fetchLatest(service: string): Promise<InfraMetrics>;
}

/**
 * Abstraction for executing a scaling action on orchestration layer.
 */
export interface ScalingExecutor {
  /**
   * Scale target service to replicaCount (K8s Deployment, HPA, etc.)
   */
  scale(service: string, replicaCount: number): Promise<void>;
}

/**
 * Strategy contract – determine desired replica count for a service.
 */
export interface CapacityScalingStrategy {
  /**
   * @param service    target micro-service
   * @param metrics    latest infra metrics
   * @param social     triggering social signal
   * @returns desired replica count (must be >= 0)
   */
  computeDesiredReplicaCount(
    service: string,
    metrics: InfraMetrics,
    social: SocialSignal
  ): number;
}

//#endregion

//#region ————————————————————————————————  Strategy Implementations ————

/**
 * Base class containing helper utilities common to all strategies.
 */
abstract class BaseScalingStrategy implements CapacityScalingStrategy {
  protected readonly MIN_REPLICAS = 1;
  protected readonly MAX_REPLICAS = 300;

  computeDesiredReplicaCount(
    service: string,
    metrics: InfraMetrics,
    social: SocialSignal
  ): number {
    const desired = this.calculate(service, metrics, social);

    // ‑— Guard rails —-
    return Math.min(Math.max(desired, this.MIN_REPLICAS), this.MAX_REPLICAS);
  }

  protected abstract calculate(
    service: string,
    metrics: InfraMetrics,
    social: SocialSignal
  ): number;
}

/**
 * Conservative – small step-up (+1) if utilisation or social interaction above
 * soft threshold.  Good for normal daily traffic growth.
 */
export class ConservativeScalingStrategy extends BaseScalingStrategy {
  protected calculate(
    _service: string,
    metrics: InfraMetrics,
    _social: SocialSignal
  ): number {
    const base = this.estimateCurrentReplicas(metrics);
    const utilisation = Math.max(metrics.cpu, metrics.memory);

    if (utilisation > 0.70) {
      return base + 1;
    }
    return base;
  }

  /**
   * Roughly infer current replica count via Requests Per Second / 100 heuristic.
   */
  private estimateCurrentReplicas(metrics: InfraMetrics): number {
    return Math.max(
      this.MIN_REPLICAS,
      Math.round(metrics.rps / 100) || this.MIN_REPLICAS
    );
  }
}

/**
 * Aggressive – double replicas until CPU drops below 60 % or interactions
 * stabilise.  Use when a major celebrity mentions the platform.
 */
export class AggressiveScalingStrategy extends BaseScalingStrategy {
  protected calculate(
    _service: string,
    metrics: InfraMetrics,
    _social: SocialSignal
  ): number {
    const current = this.estimateCurrentReplicas(metrics);
    if (metrics.cpu < 0.60 && metrics.memory < 0.60) {
      return current; // already over-provisioned
    }
    return current * 2;
  }

  private estimateCurrentReplicas(metrics: InfraMetrics): number {
    return Math.max(this.MIN_REPLICAS, Math.round(metrics.rps / 150));
  }
}

/**
 * Burst – immediate +N replicas for 10 min window, then fallback to
 * Conservative.  Useful for live-stream starts where you KNOW traffic will
 * spike instantly and drop off.
 */
export class BurstScalingStrategy extends BaseScalingStrategy {
  private readonly BURST_REPLICAS = 25;
  protected calculate(
    _service: string,
    metrics: InfraMetrics,
    social: SocialSignal
  ): number {
    const interactions = social.interactionsPerSecond;
    const current = this.estimateCurrentReplicas(metrics);

    if (interactions > 10_000) {
      return current + this.BURST_REPLICAS;
    }
    return current;
  }

  private estimateCurrentReplicas(metrics: InfraMetrics): number {
    return Math.max(this.MIN_REPLICAS, Math.round(metrics.rps / 200));
  }
}

//#endregion

//#region —————————————————————————————————————  Strategy Factory ————

/**
 * Factory for selecting optimal strategy given contextual cues.
 */
export class ScalingStrategyFactory {
  static choose(social: SocialSignal): CapacityScalingStrategy {
    const { interactionsPerSecond, influencerId } = social;

    // Simple heuristics – can be replaced by ML model later
    if (interactionsPerSecond > 8_000 || influencerId) {
      return new AggressiveScalingStrategy();
    }
    if (interactionsPerSecond > 12_000) {
      return new BurstScalingStrategy();
    }
    return new ConservativeScalingStrategy();
  }
}

//#endregion

//#region ————————————————————————————  Social-Aware Scaler Orchestration ————

/**
 * High-level orchestrator that glues:
 *   Kafka (signals) ➜ strategy selection ➜ scaling executor.
 */
export class SocialAwareScaler {
  private readonly kafkaConsumer: ReturnType<Kafka['consumer']>;
  private readonly logger: Logger;
  private isShuttingDown = false;

  constructor(
    private readonly kafka: Kafka,
    private readonly topic: string,
    private readonly metricsClient: InternalMetricsClient,
    private readonly scalingExecutor: ScalingExecutor,
    logger: Logger
  ) {
    this.logger = logger.child({ module: 'SocialAwareScaler' });
    this.kafkaConsumer = this.kafka.consumer({
      groupId: `social-aware-scaler-${uuid.v4()}`,
    });
  }

  /**
   * Initializes resources and starts consuming events.
   */
  async start(): Promise<void> {
    await this.kafkaConsumer.connect();
    await this.kafkaConsumer.subscribe({ topic: this.topic, fromBeginning: false });

    this.logger.info(`SocialAwareScaler subscribed to topic: ${this.topic}`);

    await this.kafkaConsumer.run({
      eachMessage: async (payload) => {
        if (this.isShuttingDown) return;
        await this.handleMessage(payload).catch((err) => {
          this.logger.error({ err }, 'Error handling social signal');
        });
      },
    });
  }

  /**
   * Graceful stop – flushes offsets and disconnects consumer.
   */
  async stop(): Promise<void> {
    this.isShuttingDown = true;
    await this.kafkaConsumer.disconnect();
    this.logger.info('SocialAwareScaler stopped');
  }

  /**
   * Core handler invoked for every incoming social signal message.
   */
  private async handleMessage(payload: EachMessagePayload): Promise<void> {
    const { message, partition } = payload;

    if (!message.value) {
      this.logger.warn({ partition }, 'Received empty Kafka message');
      return;
    }

    let signal: SocialSignal;
    try {
      signal = JSON.parse(message.value.toString()) as SocialSignal;
    } catch (err) {
      this.logger.warn({ err }, 'Failed to parse SocialSignal JSON');
      return;
    }

    await this.processSignal(signal);
  }

  /**
   * 1. Fetch latest infra metrics for target service
   * 2. Pick scaling strategy
   * 3. Compute desired replicas
   * 4. Execute scaling change
   */
  private async processSignal(signal: SocialSignal): Promise<void> {
    const { service } = signal;
    const metrics = await this.metricsClient.fetchLatest(service).catch((err) => {
      this.logger.error({ err, service }, 'Unable to fetch infra metrics');
      throw err;
    });

    const strategy = ScalingStrategyFactory.choose(signal);
    const desiredReplicas = strategy.computeDesiredReplicaCount(service, metrics, signal);

    this.logger.info(
      {
        service,
        strategy: strategy.constructor.name,
        desiredReplicas,
        interactions: signal.interactionsPerSecond,
      },
      'Scaling decision calculated'
    );

    await this.scalingExecutor.scale(service, desiredReplicas).catch((err) => {
      this.logger.error(
        { err, service, desiredReplicas },
        'ScalingExecutor failed'
      );
    });
  }
}

//#endregion

//#region ————————————————————————————  Local Stubs (for tests / dev) ————

/**
 * In-memory stub for unit/integration testing; not used in prod.
 */
export class InMemoryMetricsClient implements InternalMetricsClient {
  constructor(private readonly state: Record<string, InfraMetrics>) {}

  async fetchLatest(service: string): Promise<InfraMetrics> {
    const metrics = this.state[service];
    if (!metrics) {
      throw new Error(`Unknown service: ${service}`);
    }
    return metrics;
  }
}

/**
 * Dummy executor that logs instead of real cluster interaction.
 */
export class LoggingScalingExecutor implements ScalingExecutor {
  constructor(private readonly logger: Logger) {}

  async scale(service: string, replicaCount: number): Promise<void> {
    this.logger.info(
      { service, replicaCount },
      '[Mock] Scaling command issued'
    );
  }
}

//#endregion

//#region ————————————————————————————————  Bootstrapping Helper ————

/**
 * Helper function to wire together real Kafka + scaler in production.
 * Here we keep it optional so that importing this module doesn't side-effect.
 */
export async function bootstrapScaler(
  kafkaBrokers: string[],
  topic: string,
  metricsClient: InternalMetricsClient,
  scalingExecutor: ScalingExecutor,
  logger: Logger
): Promise<SocialAwareScaler> {
  const kafka = new Kafka({
    clientId: 'pulsesphere-scaler',
    brokers: kafkaBrokers,
    logLevel: logLevel.ERROR,
  });

  const scaler = new SocialAwareScaler(
    kafka,
    topic,
    metricsClient,
    scalingExecutor,
    logger
  );

  await scaler.start();

  process.on('SIGTERM', () => scaler.stop());
  process.on('SIGINT', () => scaler.stop());

  return scaler;
}

//#endregion
```