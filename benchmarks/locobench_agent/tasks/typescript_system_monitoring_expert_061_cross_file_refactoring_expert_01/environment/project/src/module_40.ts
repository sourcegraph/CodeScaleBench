```typescript
/**
 * PulseSphere SocialOps
 * -------------------------------------------------------------
 * Module 40  |  Sentiment-Aware Auto-Scaler & Metric Enrichment
 *
 * This module consumes:
 *   1. Real-time social-interaction events (likes, comments, shares, etc.)
 *   2. Infrastructure-level metrics (CPU, memory, network, etc.)
 *
 * It then:
 *   • Correlates infra metrics with social sentiment signals
 *   • Enriches the metric stream with social context (Chain-of-Responsibility)
 *   • Decides whether to scale a target service (Strategy)
 *   • Issues scaling commands that can be executed against the mesh (Command)
 *   • Uses the Observer pattern to decouple producers/consumers
 *
 * External deps (peer-installed in the workspace):
 *   - kafkajs          : Apache Kafka client
 *   - nats             : NATS client
 *   - pino             : logger
 *   - node-fetch       : lightweight fetch for Service Mesh control plane (HTTP)
 */

import { Kafka, EachMessagePayload } from 'kafkajs';
import { connect, NatsConnection, StringCodec, Subscription } from 'nats';
import pino, { Logger } from 'pino';
import fetch from 'node-fetch';
import { EventEmitter } from 'events';

// ---------------------------------------------------------------------------
// Configuration Management
// ---------------------------------------------------------------------------

interface Module40Config {
  kafkaBrokers: string[];
  natsUrl: string;
  scalingEndpoint: string; // Service-Mesh control plane endpoint
  minReplicas: number;
  maxReplicas: number;
  reactiveCpuThreshold: number; // % CPU
  socialImpactMultiplier: number; // weight of social impact in scaling formula
}

/**
 * Very small helper to load configuration. In production, this would be
 * replaced by a robust solution (e.g., @pulssphere/config).
 */
class ConfigLoader {
  static load(): Module40Config {
    // For brevity we use env vars. Validate and provide defaults.
    const env = process.env;
    const cfg: Module40Config = {
      kafkaBrokers: (env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
      natsUrl: env.NATS_URL ?? 'nats://localhost:4222',
      scalingEndpoint: env.SCALING_ENDPOINT ?? 'http://mesh-ctl.scale.local',
      minReplicas: Number(env.MIN_REPLICAS ?? 2),
      maxReplicas: Number(env.MAX_REPLICAS ?? 100),
      reactiveCpuThreshold: Number(env.REACT_CPU_THRESHOLD ?? 0.70),
      socialImpactMultiplier: Number(env.SOCIAL_IMPACT_MUL ?? 1.2),
    };

    // Basic validation
    if (cfg.minReplicas < 1 || cfg.maxReplicas < cfg.minReplicas) {
      throw new Error('Invalid replica configuration');
    }

    return cfg;
  }
}

// ---------------------------------------------------------------------------
// Domain Events & Models
// ---------------------------------------------------------------------------

interface SocialSignalEvent {
  userId: string;
  postId: string;
  signalType: 'like' | 'comment' | 'share' | 'live';
  timestamp: number; // epoch millis
  weight: number; // e.g. live > share > comment > like
}

interface InfrastructureMetric {
  serviceName: string;
  cpuUtil: number; // 0..1
  memUtil: number; // 0..1
  requestRate: number; // req/s
  timestamp: number;
  // ...additional telemetry fields
}

interface EnrichedMetric extends InfrastructureMetric {
  socialImpactScore: number; // computed
}

interface ScalingDecision {
  targetService: string;
  desiredReplicas: number;
  reason: string;
}

// ---------------------------------------------------------------------------
// Observer Pattern – Social Signal Hub
// ---------------------------------------------------------------------------

type SocialSignalListener = (e: SocialSignalEvent) => void;

/**
 * Observes Kafka topic `social_signals` and notifies registered listeners
 */
class SocialSignalHub {
  private readonly emitter = new EventEmitter();
  private readonly logger: Logger = pino({ name: 'SocialSignalHub' });
  private readonly kafka: Kafka;
  private readonly config: Module40Config;

  constructor(config: Module40Config) {
    this.config = config;
    this.kafka = new Kafka({ brokers: config.kafkaBrokers, clientId: 'module_40' });
  }

  public onSocialSignal(listener: SocialSignalListener): void {
    this.emitter.on('social', listener);
  }

  public async start(): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: 'module_40_social' });
    await consumer.connect();
    await consumer.subscribe({ topic: 'social_signals', fromBeginning: false });

    await consumer.run({
      eachMessage: async ({ message }: EachMessagePayload) => {
        try {
          const payload = message.value?.toString() || '{}';
          const event: SocialSignalEvent = JSON.parse(payload);
          this.emitter.emit('social', event);
        } catch (err) {
          this.logger.warn({ err }, 'Failed to process social signal');
        }
      },
    });

    this.logger.info('SocialSignalHub started');
  }
}

// ---------------------------------------------------------------------------
// Chain of Responsibility – Metric Enrichment
// ---------------------------------------------------------------------------

abstract class MetricEnricher {
  protected next?: MetricEnricher;

  withNext(enricher: MetricEnricher): MetricEnricher {
    this.next = enricher;
    return enricher;
  }

  async handle(metric: InfrastructureMetric): Promise<EnrichedMetric> {
    const enriched = await this.process(metric);
    return this.next ? this.next.handle(enriched) : enriched;
  }

  protected abstract process(metric: InfrastructureMetric): Promise<EnrichedMetric>;
}

/**
 * Adds a social impact score based on cached/observed social data
 */
class SocialImpactEnricher extends MetricEnricher {
  private readonly signalBuffer: Map<string, SocialSignalEvent[]> = new Map();
  private readonly logger: Logger = pino({ name: 'SocialImpactEnricher' });
  private readonly impactMultiplier: number;

  constructor(hub: SocialSignalHub, impactMultiplier: number) {
    super();
    this.impactMultiplier = impactMultiplier;
    // Feed internal buffer with signals
    hub.onSocialSignal((e) => this.pushSignal(e));
  }

  protected async process(metric: InfrastructureMetric): Promise<EnrichedMetric> {
    const key = metric.serviceName;
    const now = Date.now();
    const windowMs = 30_000; // 30s sliding window

    const signals = this.signalBuffer.get(key) ?? [];
    const recentSignals = signals.filter((s) => now - s.timestamp <= windowMs);
    const score =
      recentSignals.reduce((acc, s) => acc + s.weight, 0) *
      this.impactMultiplier;

    return { ...metric, socialImpactScore: score };
  }

  private pushSignal(signal: SocialSignalEvent): void {
    const key = this.mapPostToService(signal.postId);
    const buf = this.signalBuffer.get(key) ?? [];
    buf.push(signal);
    this.signalBuffer.set(key, buf);
  }

  // naive mapping for demo purposes
  private mapPostToService(postId: string): string {
    // Assume prefix of postId is serviceName
    return postId.split('_')[0];
  }
}

/**
 * Example of another Enricher in the chain:
 *   Could add geolocation, trend momentum, etc.
 * For brevity, we pass the metric through unchanged.
 */
class PassthroughEnricher extends MetricEnricher {
  protected async process(metric: InfrastructureMetric): Promise<EnrichedMetric> {
    return metric as EnrichedMetric;
  }
}

// ---------------------------------------------------------------------------
// Strategy Pattern – Scaling Strategies
// ---------------------------------------------------------------------------

interface ScalingStrategy {
  decide(metric: EnrichedMetric, cfg: Module40Config): ScalingDecision | null;
}

/**
 * Reactive strategy – immediate scaling based on CPU & social impact
 */
class ReactiveScalingStrategy implements ScalingStrategy {
  private readonly logger: Logger = pino({ name: 'ReactiveScalingStrategy' });

  decide(metric: EnrichedMetric, cfg: Module40Config): ScalingDecision | null {
    const cpuTrigger = metric.cpuUtil >= cfg.reactiveCpuThreshold;
    const highImpact = metric.socialImpactScore > 60;

    if (!cpuTrigger && !highImpact) return null;

    // simple formula: base + impact factor
    const desired = Math.min(
      cfg.maxReplicas,
      Math.round(metric.requestRate / 100) + Math.ceil(metric.socialImpactScore / 20)
    );

    this.logger.debug({ metric, desired }, 'Reactive decision generated');

    return {
      targetService: metric.serviceName,
      desiredReplicas: Math.max(cfg.minReplicas, desired),
      reason: `Reactive-CPU=${cpuTrigger} SocialImpact=${metric.socialImpactScore.toFixed(2)}`,
    };
  }
}

// ---------------------------------------------------------------------------
// Command Pattern – Scaling Commands
// ---------------------------------------------------------------------------

interface ScaleCommand {
  execute(): Promise<void>;
  describe(): string;
}

class AddReplicaCommand implements ScaleCommand {
  constructor(
    private readonly endpoint: string,
    private readonly service: string,
    private readonly count: number,
    private readonly logger: Logger = pino({ name: 'AddReplicaCommand' })
  ) {}

  public async execute(): Promise<void> {
    const url = `${this.endpoint}/scale/${this.service}`;
    const payload = { delta: this.count };
    this.logger.info({ service: this.service, delta: this.count }, 'Scaling up');
    const res = await fetch(url, {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'content-type': 'application/json' },
    });

    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Failed to scale up: ${res.status} - ${txt}`);
    }
  }

  describe(): string {
    return `AddReplicaCommand(service=${this.service}, +${this.count})`;
  }
}

class RemoveReplicaCommand implements ScaleCommand {
  constructor(
    private readonly endpoint: string,
    private readonly service: string,
    private readonly count: number,
    private readonly logger: Logger = pino({ name: 'RemoveReplicaCommand' })
  ) {}

  public async execute(): Promise<void> {
    const url = `${this.endpoint}/scale/${this.service}`;
    const payload = { delta: -this.count };
    this.logger.info({ service: this.service, delta: -this.count }, 'Scaling down');
    const res = await fetch(url, {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'content-type': 'application/json' },
    });

    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Failed to scale down: ${res.status} - ${txt}`);
    }
  }

  describe(): string {
    return `RemoveReplicaCommand(service=${this.service}, -${this.count})`;
  }
}

// ---------------------------------------------------------------------------
// Command Executor
// ---------------------------------------------------------------------------

class CommandExecutor {
  private readonly logger: Logger = pino({ name: 'CommandExecutor' });

  async dispatch(command: ScaleCommand): Promise<void> {
    this.logger.debug({ cmd: command.describe() }, 'Dispatching command');
    try {
      await command.execute();
      this.logger.info({ cmd: command.describe() }, 'Command executed successfully');
    } catch (err) {
      this.logger.error({ err, cmd: command.describe() }, 'Command execution failed');
    }
  }
}

// ---------------------------------------------------------------------------
// Metric Consumer
// ---------------------------------------------------------------------------

class InfrastructureMetricConsumer {
  private readonly config: Module40Config;
  private readonly natsConn!: Promise<NatsConnection>;
  private readonly logger: Logger = pino({ name: 'InfraMetricConsumer' });
  private readonly stringCodec = StringCodec();

  constructor(config: Module40Config) {
    this.config = config;
    this.natsConn = connect({ servers: config.natsUrl });
  }

  public async start(
    enricher: MetricEnricher,
    strategy: ScalingStrategy,
    executor: CommandExecutor
  ): Promise<void> {
    const conn = await this.natsConn;
    const sub: Subscription = conn.subscribe('infra.metrics');
    this.logger.info('Subscribed to infra.metrics');

    for await (const msg of sub) {
      try {
        const metric: InfrastructureMetric = JSON.parse(this.stringCodec.decode(msg.data));
        const enriched = await enricher.handle(metric);
        const decision = strategy.decide(enriched, this.config);
        if (decision) {
          const delta = decision.desiredReplicas - this.estimateCurrentReplicas(enriched);
          const cmd: ScaleCommand =
            delta > 0
              ? new AddReplicaCommand(this.config.scalingEndpoint, decision.targetService, delta)
              : new RemoveReplicaCommand(
                  this.config.scalingEndpoint,
                  decision.targetService,
                  Math.abs(delta)
                );
          executor.dispatch(cmd);
        }
      } catch (err) {
        this.logger.warn({ err }, 'Failed to process infra metric');
      }
    }
  }

  /**
   * In a real implementation, we would query the mesh control plane or cache
   * to retrieve current replica counts. For this demo we approximate it from
   * request rate.
   */
  private estimateCurrentReplicas(metric: InfrastructureMetric): number {
    return Math.max(1, Math.round(metric.requestRate / 150));
  }
}

// ---------------------------------------------------------------------------
// Bootstrapping
// ---------------------------------------------------------------------------

(async function bootstrap(): Promise<void> {
  const config = ConfigLoader.load();
  const logger = pino({ name: 'Module40Bootstrap' });

  // Initialize components
  const socialHub = new SocialSignalHub(config);
  const socialEnricher = new SocialImpactEnricher(socialHub, config.socialImpactMultiplier);
  const rootEnricher = socialEnricher.withNext(new PassthroughEnricher());

  const strategy = new ReactiveScalingStrategy();
  const executor = new CommandExecutor();
  const infraConsumer = new InfrastructureMetricConsumer(config);

  try {
    await socialHub.start();
    await infraConsumer.start(rootEnricher, strategy, executor);
  } catch (err) {
    logger.fatal({ err }, 'Module 40 failed to start');
    process.exit(1);
  }

  process.on('SIGINT', () => {
    logger.info('Module 40 shutting down (SIGINT)');
    process.exit(0);
  });
})();
```