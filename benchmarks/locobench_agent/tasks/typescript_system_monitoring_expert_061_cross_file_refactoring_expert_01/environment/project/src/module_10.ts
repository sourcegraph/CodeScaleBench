```typescript
/***************************************************************************************************
 *  PulseSphere SocialOps – Adaptive Capacity Orchestrator
 *  -----------------------------------------------------------------------------------------------
 *  File:          src/module_10.ts
 *  Responsibility: Listen to infrastructure metrics _and_ social-engagement signals, correlate
 *                  them in near-real-time and issue scale-up / scale-down commands to the cluster
 *                  control-plane before virality spikes impact SLOs.
 *
 *  Architectural patterns used:
 *    • Observer Pattern      – RxJS streams wrap Kafka/NATS topics.
 *    • Strategy Pattern      – Pluggable scaling strategies.
 *    • Chain of Responsibility – Post-decision handlers (dry-run, dispatch, notify).
 *    • Command Pattern       – Encapsulate calls to the Cluster Manager API.
 *
 *  External deps (peer deps declared in package.json):
 *    "@types/node", "kafkajs", "nats", "rxjs", "axios", "uuid"
 ***************************************************************************************************/

import axios, { AxiosInstance } from 'axios';
import { Kafka, EachMessagePayload, logLevel } from 'kafkajs';
import { connect, JSONCodec, NatsConnection, Subscription } from 'nats';
import { Subject, merge, Observable } from 'rxjs';
import { bufferTime, filter, map, catchError } from 'rxjs/operators';
import { v4 as uuid } from 'uuid';

/* -------------------------------------------------------------------------------------------------
 * Domain Models
 * -----------------------------------------------------------------------------------------------*/
interface InfraMetricEvent {
  timestamp: number;               // epoch millis
  clusterId: string;
  avgCpu: number;                  // aggregated CPU util %
  avgMem: number;                  // aggregated Mem util %
}

interface SocialSignalEvent {
  timestamp: number;
  userSegment: 'global' | 'region' | 'influencer';
  magnitude: number;               // e.g. delta of likes/min or new live viewers
  cause?: string;                  // optional hashtag / campaign identifier
}

interface AggregatedSignal {
  timestamp: number;
  windowMs: number;
  clusterId: string;
  avgCpu: number;
  avgMem: number;
  socialMagnitude: number;
}

enum ScaleDirection {
  SCALE_OUT = 'SCALE_OUT',
  SCALE_IN = 'SCALE_IN',
  NONE = 'NONE'
}

interface ScaleDecision {
  id: string;
  timestamp: number;
  direction: ScaleDirection;
  amount: number;                  // positive integer representing # replicas to add/remove
  reason: string;
  dryRun?: boolean;
}

/* -------------------------------------------------------------------------------------------------
 * Configuration
 * -----------------------------------------------------------------------------------------------*/
const CONFIG = {
  KAFKA_BROKERS: process.env.KAFKA_BROKERS?.split(',') ?? ['kafka:9092'],
  NATS_URL: process.env.NATS_URL ?? 'nats://nats:4222',
  OBSERVABILITY_WINDOW_MS: 5_000,
  SOCIAL_MAGNITUDE_THRESHOLD: 500,
  CPU_SCALE_OUT_THRESHOLD: 0.70,
  CPU_SCALE_IN_THRESHOLD: 0.25,
  MAX_REPLICAS_DELTA: 25,
  CLUSTER_MANAGER_BASE_URL: process.env.CLUSTER_MANAGER_URL ?? 'http://cluster-mgr.svc',
  DRY_RUN: process.env.DRY_RUN === 'true',
  LOG_LEVEL: process.env.LOG_LEVEL ?? 'info'
};

/* -------------------------------------------------------------------------------------------------
 * Observer – Event Buses
 * -----------------------------------------------------------------------------------------------*/

/**
 * MetricBus and SocialBus are RxJS Subjects that act as hot observable streams for downstream
 * consumers.
 */
const metricBus = new Subject<InfraMetricEvent>();
const socialBus = new Subject<SocialSignalEvent>();

/**
 * Consolidated view – merge metric & social streams, then buffer them in sliding window.
 */
const aggregatedStream: Observable<AggregatedSignal[]> = merge(metricBus, socialBus).pipe(
  bufferTime(CONFIG.OBSERVABILITY_WINDOW_MS),
  // Filter out empty windows
  filter(events => events.length > 0),
  map(events => {
    // Simple aggregation; in production we would use more robust windowing (e.g. Kafka Streams)
    const metrics = events.filter((e): e is InfraMetricEvent => (e as InfraMetricEvent).avgCpu !== undefined);
    const social = events.filter((e): e is SocialSignalEvent => (e as SocialSignalEvent).magnitude !== undefined);

    const clusterId = metrics.length ? metrics[0].clusterId : 'global';

    const avgCpu = metrics.reduce((sum, m) => sum + m.avgCpu, 0) / (metrics.length || 1);
    const avgMem = metrics.reduce((sum, m) => sum + m.avgMem, 0) / (metrics.length || 1);
    const socialMagnitude = social.reduce((sum, s) => sum + s.magnitude, 0);

    return [{
      timestamp: Date.now(),
      windowMs: CONFIG.OBSERVABILITY_WINDOW_MS,
      clusterId,
      avgCpu,
      avgMem,
      socialMagnitude
    }];
  })
);

/* -------------------------------------------------------------------------------------------------
 * Strategy Pattern – Scaling Decision Strategies
 * -----------------------------------------------------------------------------------------------*/
interface ScalingStrategy {
  /**
   * Inspect aggregated signal and decide whether to scale.
   * Returns a ScaleDecision or undefined if no action required.
   */
  evaluate(signal: AggregatedSignal): ScaleDecision | undefined;
}

/**
 * CPU-based auto-scaling strategy
 */
class CpuBasedScalingStrategy implements ScalingStrategy {
  evaluate(signal: AggregatedSignal): ScaleDecision | undefined {
    if (signal.avgCpu > CONFIG.CPU_SCALE_OUT_THRESHOLD) {
      const delta = Math.min(
        Math.ceil((signal.avgCpu - CONFIG.CPU_SCALE_OUT_THRESHOLD) * 100),
        CONFIG.MAX_REPLICAS_DELTA
      );

      return {
        id: uuid(),
        timestamp: Date.now(),
        direction: ScaleDirection.SCALE_OUT,
        amount: delta,
        reason: `Avg CPU high (${(signal.avgCpu * 100).toFixed(1)}%)`
      };
    }

    if (signal.avgCpu < CONFIG.CPU_SCALE_IN_THRESHOLD) {
      const delta = Math.min(
        Math.ceil((CONFIG.CPU_SCALE_IN_THRESHOLD - signal.avgCpu) * 100),
        CONFIG.MAX_REPLICAS_DELTA
      );
      return {
        id: uuid(),
        timestamp: Date.now(),
        direction: ScaleDirection.SCALE_IN,
        amount: delta,
        reason: `Avg CPU low (${(signal.avgCpu * 100).toFixed(1)}%)`
      };
    }

    return undefined;
  }
}

/**
 * Social-surge scaling strategy – reacts to sudden increases in social activity
 */
class SocialSurgeScalingStrategy implements ScalingStrategy {
  evaluate(signal: AggregatedSignal): ScaleDecision | undefined {
    if (signal.socialMagnitude >= CONFIG.SOCIAL_MAGNITUDE_THRESHOLD) {
      const delta = Math.min(
        Math.ceil(signal.socialMagnitude / CONFIG.SOCIAL_MAGNITUDE_THRESHOLD),
        CONFIG.MAX_REPLICAS_DELTA
      );

      return {
        id: uuid(),
        timestamp: Date.now(),
        direction: ScaleDirection.SCALE_OUT,
        amount: delta,
        reason: `Social magnitude spike (${signal.socialMagnitude})`
      };
    }
    return undefined;
  }
}

/* -------------------------------------------------------------------------------------------------
 * Command Pattern – Cluster Scaling Command
 * -----------------------------------------------------------------------------------------------*/
class ScaleCommand {
  constructor(
    private readonly decision: ScaleDecision,
    private readonly apiClient: AxiosInstance
  ) {}

  async execute(): Promise<void> {
    const { direction, amount } = this.decision;
    const verb = direction === ScaleDirection.SCALE_IN ? 'scale-in' : 'scale-out';
    const url = `/clusters/default/${verb}`;

    try {
      await this.apiClient.post(url, { replicas: amount, meta: { id: this.decision.id } });
      Logger.info(`[CMD] Successfully executed ${verb} x${amount}`);
    } catch (err) {
      Logger.error(`[CMD] Failed to execute ${verb}:`, err);
      throw err;
    }
  }
}

/* -------------------------------------------------------------------------------------------------
 * Chain of Responsibility – Decision Handlers
 * -----------------------------------------------------------------------------------------------*/
interface DecisionHandler {
  setNext(handler: DecisionHandler): DecisionHandler;
  handle(decision: ScaleDecision): Promise<void>;
}

abstract class AbstractDecisionHandler implements DecisionHandler {
  private nextHandler?: DecisionHandler;

  setNext(handler: DecisionHandler): DecisionHandler {
    this.nextHandler = handler;
    return handler;
  }

  async handle(decision: ScaleDecision): Promise<void> {
    const handled = await this.process(decision);
    if (!handled && this.nextHandler) {
      await this.nextHandler.handle(decision);
    }
  }

  protected abstract process(decision: ScaleDecision): Promise<boolean>;
}

/**
 * DryRunHandler – short-circuit chain when DRY_RUN enabled.
 */
class DryRunHandler extends AbstractDecisionHandler {
  protected async process(decision: ScaleDecision): Promise<boolean> {
    if (CONFIG.DRY_RUN) {
      Logger.warn(`[DRY-RUN] Decision ${decision.id} would ${decision.direction} by ${decision.amount}: ${decision.reason}`);
      return true; // stop propagation
    }
    return false;
  }
}

/**
 * CommandDispatchHandler – send ScaleCommand to Cluster Manager.
 */
class CommandDispatchHandler extends AbstractDecisionHandler {
  constructor(private readonly apiClient: AxiosInstance) {
    super();
  }

  protected async process(decision: ScaleDecision): Promise<boolean> {
    const cmd = new ScaleCommand(decision, this.apiClient);
    await cmd.execute();
    return false; // keep chain alive for notification
  }
}

/**
 * NotificationHandler – publish decision outcome back onto event bus (NATS)
 */
class NotificationHandler extends AbstractDecisionHandler {
  private readonly codec = JSONCodec();

  constructor(private readonly nats: NatsConnection) {
    super();
  }

  protected async process(decision: ScaleDecision): Promise<boolean> {
    try {
      await this.nats.publish('system.capacity.decisions', this.codec.encode(decision));
      Logger.info(`[NOTIFY] Published decision ${decision.id}`);
    } catch (err) {
      Logger.error('[NOTIFY] Failed to publish decision', err);
    }
    return true;
  }
}

/* -------------------------------------------------------------------------------------------------
 * Logger utility (simple wrapper; in real project we use pino or bunyan)
 * -----------------------------------------------------------------------------------------------*/
const Logger = {
  info: (...args: unknown[]) => CONFIG.LOG_LEVEL !== 'silent' && console.info('[INFO]', ...args),
  warn: (...args: unknown[]) => CONFIG.LOG_LEVEL !== 'silent' && console.warn('[WARN]', ...args),
  error: (...args: unknown[]) => CONFIG.LOG_LEVEL !== 'silent' && console.error('[ERROR]', ...args)
};

/* -------------------------------------------------------------------------------------------------
 * AdaptiveCapacityOrchestrator – connects everything together
 * -----------------------------------------------------------------------------------------------*/
class AdaptiveCapacityOrchestrator {
  private kafka: Kafka;
  private metricSub?: Subscription;
  private strategySet: ScalingStrategy[] = [
    new CpuBasedScalingStrategy(),
    new SocialSurgeScalingStrategy()
  ];

  private readonly apiClient: AxiosInstance;
  private nats!: NatsConnection;

  private readonly decisionChain: DecisionHandler;

  constructor() {
    this.kafka = new Kafka({
      clientId: 'adaptive-capacity-orchestrator',
      brokers: CONFIG.KAFKA_BROKERS,
      logLevel: logLevel.NOTHING
    });

    this.apiClient = axios.create({
      baseURL: CONFIG.CLUSTER_MANAGER_BASE_URL,
      timeout: 5_000
    });

    // Build CoR
    const dryRunHandler        = new DryRunHandler();
    const dispatchHandler      = new CommandDispatchHandler(this.apiClient);
    const notificationHandler  = new NotificationHandler(this.nats as unknown as NatsConnection); // placeholder; will be reset later

    dryRunHandler.setNext(dispatchHandler).setNext(notificationHandler);
    this.decisionChain = dryRunHandler;
  }

  async init(): Promise<void> {
    await this.initNats();
    await this.initKafka();

    // Patch notification handler's NATS conn
    (this.decisionChain as DryRunHandler)
      .setNext(new CommandDispatchHandler(this.apiClient))
      .setNext(new NotificationHandler(this.nats));

    // Start listening to aggregated stream
    aggregatedStream.subscribe({
      next: signals => this.onAggregatedSignal(signals[0]), // we produced single aggregatedSignal in map.
      error: err => Logger.error('[STREAM] Error processing signal', err)
    });

    Logger.info('AdaptiveCapacityOrchestrator initialized');
  }

  private async initKafka(): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: 'aco-consumers' });
    await consumer.connect();

    await consumer.subscribe({ topic: 'infra.metrics', fromBeginning: false });
    await consumer.subscribe({ topic: 'social.signals', fromBeginning: false });

    consumer.run({
      eachMessage: async (payload: EachMessagePayload) => {
        const { topic, message } = payload;
        const value = message.value?.toString();
        if (!value) return;

        try {
          if (topic === 'infra.metrics') {
            const metric: InfraMetricEvent = JSON.parse(value);
            metricBus.next(metric);
          } else if (topic === 'social.signals') {
            const social: SocialSignalEvent = JSON.parse(value);
            socialBus.next(social);
          }
        } catch (err) {
          Logger.error(`[KAFKA] Failed to parse message on ${topic}`, err);
        }
      }
    });

    Logger.info('[KAFKA] Consumer running');
  }

  private async initNats(): Promise<void> {
    this.nats = await connect({ servers: CONFIG.NATS_URL });
    Logger.info('[NATS] Connected');
  }

  /**
   * Evaluate aggregated signal through all strategies, then run decision chain.
   */
  private async onAggregatedSignal(signal: AggregatedSignal): Promise<void> {
    Logger.info(`[EVAL] AggregatedSignal cpu=${(signal.avgCpu*100).toFixed(1)}% mem=${(signal.avgMem*100).toFixed(1)}% social=${signal.socialMagnitude}`);

    for (const strategy of this.strategySet) {
      try {
        const decision = strategy.evaluate(signal);
        if (decision) {
          await this.decisionChain.handle(decision);
          // Only one strategy may trigger per window to avoid conflicting actions
          break;
        }
      } catch (err) {
        Logger.error('[EVAL] Strategy evaluation error', err);
      }
    }
  }

  /* ---------------------------------------------------------------------------------------------
   * Graceful shutdown helpers
   * -------------------------------------------------------------------------------------------*/
  async shutdown(): Promise<void> {
    try {
      await this.nats?.drain?.();
      Logger.info('[NATS] Drained');
    } catch (err) {
      Logger.warn('[NATS] Error during drain', err);
    }

    try {
      await this.kafka?.disconnect?.();
      Logger.info('[KAFKA] Disconnected');
    } catch (err) {
      Logger.warn('[KAFKA] Error during disconnect', err);
    }
  }
}

/* -------------------------------------------------------------------------------------------------
 * Bootstrap
 * -----------------------------------------------------------------------------------------------*/
(async () => {
  const orchestrator = new AdaptiveCapacityOrchestrator();

  process.on('SIGINT', async () => {
    Logger.info('SIGINT received, shutting down orchestrator...');
    await orchestrator.shutdown();
    process.exit(0);
  });

  process.on('SIGTERM', async () => {
    Logger.info('SIGTERM received, shutting down orchestrator...');
    await orchestrator.shutdown();
    process.exit(0);
  });

  try {
    await orchestrator.init();
  } catch (err) {
    Logger.error('Failed to initialize AdaptiveCapacityOrchestrator', err);
    process.exit(1);
  }
})();
```
