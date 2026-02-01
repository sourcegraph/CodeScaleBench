```typescript
/******************************************************************************************
 *  File:        src/module_33.ts
 *  Project:     PulseSphere SocialOps (system_monitoring)
 *
 *  Description:
 *  Social-Aware Auto-Scaler micro-service. Listens to infrastructure telemetry (CPU/memory)
 *  from Apache Kafka, listens to near-real-time social-interaction signals from NATS,
 *  merges the two streams and decides—via configurable Strategy pattern—whether capacity
 *  should be scaled up/down. If a scaling decision is made it emits a Command event back
 *  to the message bus. Additionally, it forwards critical alerts through a simple
 *  Chain-of-Responsibility notifier pipeline (Slack → PagerDuty → Log).
 *
 *  NOTE: 3rd-party SDKs are thinly wrapped to allow mocking in unit tests; production
 *  credentials and topics/subjects are injected via env-vars or Secret-Manager.
 ******************************************************************************************/

/* ================================== Imports ========================================= */

import { Kafka, Producer, EachMessagePayload } from 'kafkajs';
import { connect as natsConnect, NatsConnection, Subscription, JSONCodec } from 'nats';
import pino, { Logger } from 'pino';
import { v4 as uuid } from 'uuid';

/* ============================== Domain & Contracts ================================== */

/**
 * Represents infrastructure telemetry pulled from Prometheus-push gateway (simplified).
 */
export interface SystemMetric {
  timestamp: number;              // unix epoch ms
  instanceId: string;             // k8s node or pod id
  cpuLoadPct: number;             // e.g., 0.73 means 73%
  memoryLoadPct: number;
}

/**
 * Represents social-interaction spikes (likes, comments, shares, etc.)
 */
export interface SocialSignal {
  timestamp: number;
  campaignId?: string;
  hashtag?: string;
  deltaPerSecond: number;         // increase of interactions per sec
}

/**
 * Consolidated view that Strategies will look at.
 */
export interface CombinedMetrics {
  system: SystemMetric;
  social?: SocialSignal;
}

/**
 * Command event that goes onto Kafka for Orchestration service.
 */
export interface ScalingCommand {
  commandId: string;
  issuedAt: number;
  targetGroup: string;            // e.g., "video-processor-pods"
  action: 'SCALE_UP' | 'SCALE_DOWN';
  desiredReplicas: number;
  reason: string;
}

/* =========================== Strategy Pattern ======================================= */

export interface ScalingStrategy {
  readonly name: string;
  evaluate(input: CombinedMetrics): ScalingCommand | null;
}

/**
 * 1. Pure CPU strategy—scale if CPU surpasses threshold.
 */
export class CpuLoadStrategy implements ScalingStrategy {
  readonly name = 'CpuLoadStrategy';

  constructor(
    private readonly cpuUpperThreshold = 0.8,
    private readonly cpuLowerThreshold = 0.25,
    private readonly maxReplicas = 16,
    private readonly minReplicas = 2
  ) {}

  evaluate(input: CombinedMetrics): ScalingCommand | null {
    const { cpuLoadPct, instanceId } = input.system;
    let action: ScalingCommand['action'] | null = null;
    let desired: number | null = null;

    if (cpuLoadPct >= this.cpuUpperThreshold) {
      action = 'SCALE_UP';
      desired = Math.min(this.maxReplicas, Math.ceil(cpuLoadPct * 10));
    } else if (cpuLoadPct <= this.cpuLowerThreshold) {
      action = 'SCALE_DOWN';
      desired = Math.max(this.minReplicas, Math.floor(cpuLoadPct * 10));
    }

    if (action && desired !== null) {
      return {
        commandId: uuid(),
        issuedAt: Date.now(),
        targetGroup: instanceId,
        action,
        desiredReplicas: desired,
        reason: `CPU load ${cpuLoadPct * 100}% triggered ${action}`
      };
    }
    return null;
  }
}

/**
 * 2. Social trend strategy—scale on viral spikes regardless of current CPU.
 */
export class SocialTrendingStrategy implements ScalingStrategy {
  readonly name = 'SocialTrendingStrategy';

  constructor(
    private readonly spikeThreshold = 5000,        // interactions/sec
    private readonly surgeReplicas = 8
  ) {}

  evaluate(input: CombinedMetrics): ScalingCommand | null {
    if (!input.social) return null;
    const { deltaPerSecond, hashtag } = input.social;
    if (deltaPerSecond >= this.spikeThreshold) {
      return {
        commandId: uuid(),
        issuedAt: Date.now(),
        targetGroup: hashtag ?? 'global',
        action: 'SCALE_UP',
        desiredReplicas: this.surgeReplicas,
        reason: `Social spike (${deltaPerSecond}/s) for #${hashtag}`
      };
    }
    return null;
  }
}

/**
 * 3. Hybrid strategy—showcases Strategy composition.
 */
export class HybridStrategy implements ScalingStrategy {
  readonly name = 'HybridStrategy';
  private readonly innerStrategies: ScalingStrategy[];

  constructor(...strategies: ScalingStrategy[]) {
    this.innerStrategies = strategies;
  }

  evaluate(input: CombinedMetrics): ScalingCommand | null {
    for (const strat of this.innerStrategies) {
      const cmd = strat.evaluate(input);
      if (cmd) return cmd;
    }
    return null;
  }
}

/* =================== Chain-of-Responsibility for Alerting =========================== */

interface AlertHandler {
  setNext(handler: AlertHandler): AlertHandler;
  handle(message: string): Promise<void>;
}

abstract class AbstractHandler implements AlertHandler {
  protected nextHandler?: AlertHandler;
  setNext(handler: AlertHandler): AlertHandler {
    this.nextHandler = handler;
    return handler;
  }
  async handle(message: string): Promise<void> {
    if (this.nextHandler) {
      await this.nextHandler.handle(message);
    }
  }
}

class SlackNotifierHandler extends AbstractHandler {
  constructor(private readonly logger: Logger) { super(); }
  async handle(message: string): Promise<void> {
    try {
      // Placeholder for Slack webhook call
      this.logger.info({ msg: 'SlackNotifier', message });
      // Success, stop chain.
    } catch (err) {
      this.logger.error({ err, msg: 'SlackNotifierFailed' });
      await super.handle(message);
    }
  }
}

class PagerDutyHandler extends AbstractHandler {
  constructor(private readonly logger: Logger) { super(); }
  async handle(message: string): Promise<void> {
    try {
      // Placeholder for PagerDuty event trigger
      this.logger.info({ msg: 'PagerDutyNotifier', message });
    } catch (err) {
      this.logger.error({ err, msg: 'PagerDutyNotifierFailed' });
      await super.handle(message);
    }
  }
}

class FallbackLoggerHandler extends AbstractHandler {
  constructor(private readonly logger: Logger) { super(); }
  async handle(message: string): Promise<void> {
    this.logger.warn({ msg: 'FallbackLogger', message });
    await super.handle(message);
  }
}

/* ============================ Auto-Scaler Service =================================== */

export class SocialAwareAutoScaler {
  private readonly kafka: Kafka;
  private readonly kafkaProducer: Producer;
  private readonly natsConn: NatsConnection;
  private readonly jc = JSONCodec();

  private readonly logger: Logger;
  private readonly strategy: ScalingStrategy;

  private slackHandler: AlertHandler;

  constructor(
    private readonly kafkaBrokers: string[],
    private readonly natsUrl: string,
    strategy?: ScalingStrategy
  ) {
    this.logger = pino({ name: 'SocialAwareAutoScaler' });
    this.kafka = new Kafka({ clientId: 'auto-scaler', brokers: kafkaBrokers });
    this.kafkaProducer = this.kafka.producer();
    this.strategy = strategy ?? new HybridStrategy(
      new SocialTrendingStrategy(),
      new CpuLoadStrategy()
    );
    this.natsConn = {} as any; // will connect later

    // Alert pipeline
    this.slackHandler = new SlackNotifierHandler(this.logger);
    this.slackHandler
      .setNext(new PagerDutyHandler(this.logger))
      .setNext(new FallbackLoggerHandler(this.logger));
  }

  /* ---------- Bootstrapping ---------- */

  async start(): Promise<void> {
    try {
      await this.kafkaProducer.connect();
      this.logger.info('Kafka producer connected');

      // Connect to NATS
      this.natsConn = await natsConnect({ servers: this.natsUrl });
      this.logger.info('NATS connected');

      // Subscribe to streams
      await this.subscribeSystemMetrics();
      await this.subscribeSocialSignals();

      this.logger.info(`Auto-Scaler started with strategy ${this.strategy.name}`);
    } catch (err) {
      this.logger.fatal({ err }, 'Failed to start Auto-Scaler');
      process.exit(1);
    }
  }

  async shutdown(): Promise<void> {
    await Promise.allSettled([this.kafkaProducer.disconnect(), this.natsConn.close()]);
    this.logger.info('Graceful shutdown complete.');
  }

  /* ---------- Internal Subscription Logic ---------- */

  private async subscribeSystemMetrics(): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: 'auto-scaler-group' });
    await consumer.connect();
    await consumer.subscribe({ topic: 'telemetry.system', fromBeginning: false });

    consumer.run({
      eachMessage: async (payload: EachMessagePayload) => {
        try {
          const metric: SystemMetric = JSON.parse(payload.message.value!.toString());

          // Merge with any cached social signal if available
          const combined: CombinedMetrics = { system: metric, social: this.lastSocialSignal };

          await this.maybeScale(combined);
        } catch (err) {
          this.logger.error({ err }, 'Failed to handle system metric message');
        }
      }
    });
  }

  private lastSocialSignal?: SocialSignal;
  private async subscribeSocialSignals(): Promise<void> {
    const sub: Subscription = this.natsConn.subscribe('social.trending');
    (async () => {
      for await (const msg of sub) {
        try {
          const signal: SocialSignal = this.jc.decode(msg.data);
          this.lastSocialSignal = signal; // simple cache
          const dummySystem: SystemMetric = {
            timestamp: signal.timestamp,
            instanceId: 'social-only',
            cpuLoadPct: 0,
            memoryLoadPct: 0
          };
          await this.maybeScale({ system: dummySystem, social: signal });

        } catch (err) {
          this.logger.error({ err }, 'Failed to handle social signal message');
        }
      }
    })().catch(err => this.logger.error({ err }, 'NATS subscription failed'));
  }

  /* ---------- Core Decision Loop ---------- */

  private async maybeScale(input: CombinedMetrics): Promise<void> {
    const cmd = this.strategy.evaluate(input);
    if (cmd) {
      this.logger.info({ cmd }, 'Scaling decision issued');

      try {
        await this.kafkaProducer.send({
          topic: 'orchestration.scaling.command',
          messages: [{ key: cmd.targetGroup, value: JSON.stringify(cmd) }]
        });
      } catch (err) {
        this.logger.error({ err }, 'Failed to publish scaling command');
        await this.slackHandler.handle(`Scaling command failed: ${err}`);
      }
    }
  }
}

/* ============================= Run if main ========================================== */

if (require.main === module) {
  const scaler = new SocialAwareAutoScaler(
    process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
    process.env.NATS_URL ?? 'nats://127.0.0.1:4222'
  );

  scaler.start();

  // Graceful shutdown
  process.on('SIGINT', async () => {
    await scaler.shutdown();
    process.exit(0);
  });
}
```