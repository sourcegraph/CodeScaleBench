```typescript
/**
 * File: src/module_37.ts
 * Module: AdaptiveScalingDecisionEngine
 *
 * Description:
 *  This module wires together the “socially-aware” adaptive scaling logic for PulseSphere. It
 *  listens to enriched metric events (received over Kafka), evaluates them against a
 *  chain-of-responsibility of scaling strategies, and finally emits scaling commands that will be
 *  picked up by the Deployment Automation service. The engine supports dynamic, multi-tenant
 *  configuration at runtime and ships Prometheus metrics for observability.
 *
 * Patterns used:
 *   • Strategy Pattern              – pluggable scaling strategies
 *   • Chain of Responsibility       – sequential evaluation until one strategy claims ownership
 *   • Observer Pattern              – internal EventEmitter to multicast decisions
 *   • Command Pattern               – ScalingCommand object represents an executable action
 *   • Event-Driven Architecture     – Kafka used as transport for events/commands
 *
 * External Dependencies (peer deps):
 *   npm i kafkajs prom-client @types/node
 */

import { EventEmitter } from 'node:events';
import { Kafka, Consumer, Producer, EachMessagePayload, logLevel } from 'kafkajs';
import {
  Counter,
  Gauge,
  Histogram,
  collectDefaultMetrics,
  Registry,
} from 'prom-client';

/* -------------------------------------------------------------------------- */
/*                                Configuration                               */
/* -------------------------------------------------------------------------- */

interface EngineConfig {
  kafkaBrokers: string[];
  metricsTopic: string;
  commandTopic: string;
  clientId: string;
  groupId: string;
  /** Scale-up replication factor when an up-action is triggered */
  scaleUpStep: number;
  /** Scale-down step to avoid aggressive contraction */
  scaleDownStep: number;
  /** Thresholds for ViralSurgeStrategy */
  viralSurgeRps: number;
  /** Thresholds for HighLatencyStrategy (in ms) */
  p95LatencyMs: number;
  /** Enable verbose logging */
  debug: boolean;
}

class ConfigLoader {
  static load(): EngineConfig {
    const env = process.env;

    const requiredVars = ['KAFKA_BROKERS'];
    requiredVars.forEach((v) => {
      if (!env[v]) {
        throw new Error(`Missing required env var: ${v}`);
      }
    });

    return {
      kafkaBrokers: env.KAFKA_BROKERS.split(',').map((s) => s.trim()),
      metricsTopic: env.METRICS_TOPIC ?? 'telemetry.social_metrics',
      commandTopic: env.COMMAND_TOPIC ?? 'commands.scaling',
      clientId: env.KAFKA_CLIENT_ID ?? 'pulse-sphere-scaling-engine',
      groupId: env.KAFKA_GROUP_ID ?? 'pulse-sphere-scaling-engine-group',
      scaleUpStep: parseInt(env.SCALE_UP_STEP ?? '3', 10),
      scaleDownStep: parseInt(env.SCALE_DOWN_STEP ?? '1', 10),
      viralSurgeRps: parseInt(env.VIRAL_SURGE_RPS ?? '10000', 10),
      p95LatencyMs: parseInt(env.P95_LATENCY_MS ?? '250', 10),
      debug: (env.DEBUG ?? 'false').toLowerCase() === 'true',
    };
  }
}

/* -------------------------------------------------------------------------- */
/*                              Domain Interfaces                             */
/* -------------------------------------------------------------------------- */

/** Message model emitted by upstream metric aggregators */
interface SocialMetricEvent {
  tenantId: string;
  timestamp: number;
  totalRps: number; // Request rate
  socialRps: number; // Social-interaction burst rate (likes/comments/shares per second)
  p95LatencyMs: number;
  avgCpuPct: number;
  currentReplicas: number;
}

/** Allowed scaling actions */
type ScalingAction = 'SCALE_UP' | 'SCALE_DOWN' | 'NOOP';

/** Result of a strategy evaluation */
interface ScalingDecision {
  action: ScalingAction;
  /** Replica delta; positive = add replicas, negative = remove replicas */
  replicaDelta: number;
  explanation: string;
}

/** Command dispatched to orchestrator */
interface ScalingCommand {
  tenantId: string;
  targetReplicas: number;
  reason: string;
  timestamp: number;
}

/* -------------------------------------------------------------------------- */
/*                              Strategy Pattern                              */
/* -------------------------------------------------------------------------- */

interface IScalingStrategy {
  setNext(next: IScalingStrategy): IScalingStrategy;
  evaluate(event: SocialMetricEvent): ScalingDecision | null;
}

abstract class BaseScalingStrategy implements IScalingStrategy {
  private next?: IScalingStrategy;

  setNext(next: IScalingStrategy): IScalingStrategy {
    this.next = next;
    return next;
  }

  evaluate(event: SocialMetricEvent): ScalingDecision | null {
    const decision = this.apply(event);
    if (decision) return decision;
    return this.next?.evaluate(event) ?? null;
  }

  /** Implemented by subclasses */
  protected abstract apply(event: SocialMetricEvent): ScalingDecision | null;
}

class ViralSurgeScalingStrategy extends BaseScalingStrategy {
  constructor(
    private readonly thresholdRps: number,
    private readonly scaleUpStep: number
  ) {
    super();
  }

  protected apply(event: SocialMetricEvent): ScalingDecision | null {
    if (event.socialRps > this.thresholdRps) {
      const replicaDelta = this.scaleUpStep;
      return {
        action: 'SCALE_UP',
        replicaDelta,
        explanation: `Social RPS ${event.socialRps} exceeded threshold ${this.thresholdRps}.`,
      };
    }
    return null;
  }
}

class HighLatencyScalingStrategy extends BaseScalingStrategy {
  constructor(
    private readonly latencyMs: number,
    private readonly scaleUpStep: number
  ) {
    super();
  }

  protected apply(event: SocialMetricEvent): ScalingDecision | null {
    if (event.p95LatencyMs > this.latencyMs) {
      return {
        action: 'SCALE_UP',
        replicaDelta: this.scaleUpStep,
        explanation: `p95 latency ${event.p95LatencyMs}ms exceeded threshold ${this.latencyMs}ms.`,
      };
    }
    return null;
  }
}

class AggressiveContractionStrategy extends BaseScalingStrategy {
  constructor(private readonly scaleDownStep: number) {
    super();
  }

  protected apply(event: SocialMetricEvent): ScalingDecision | null {
    // Basic heuristic: if socialRps is negligible and CPU < 30% for 2+ replicas, scale down.
    if (event.socialRps < 100 && event.avgCpuPct < 30 && event.currentReplicas > 1) {
      return {
        action: 'SCALE_DOWN',
        replicaDelta: -this.scaleDownStep,
        explanation: `Low load detected (socialRps=${event.socialRps}, cpu=${event.avgCpuPct}%).`,
      };
    }
    return null;
  }
}

class DefaultNoopStrategy extends BaseScalingStrategy {
  protected apply(): ScalingDecision | null {
    return {
      action: 'NOOP',
      replicaDelta: 0,
      explanation: 'No scaling conditions met.',
    };
  }
}

/* -------------------------------------------------------------------------- */
/*                           Observability Metrics                            */
/* -------------------------------------------------------------------------- */

class MetricsCollector {
  public readonly registry: Registry;
  private readonly eventsConsumed: Counter<string>;
  private readonly scalingDecisions: Counter<string>;
  private readonly decisionLatency: Histogram<string>;
  private readonly currentReplicasGauge: Gauge<string>;

  constructor() {
    this.registry = new Registry();
    collectDefaultMetrics({ register: this.registry });

    this.eventsConsumed = new Counter({
      name: 'ps_scaling_events_total',
      help: 'Total metric events consumed',
      registers: [this.registry],
    });

    this.scalingDecisions = new Counter({
      name: 'ps_scaling_decisions_total',
      help: 'Total scaling decisions by action',
      labelNames: ['action'],
      registers: [this.registry],
    });

    this.decisionLatency = new Histogram({
      name: 'ps_scaling_decision_latency_ms',
      help: 'Latency between event receive and decision emit',
      buckets: [5, 10, 25, 50, 100, 250, 500, 1000],
      registers: [this.registry],
    });

    this.currentReplicasGauge = new Gauge({
      name: 'ps_current_replicas',
      help: 'Current replicas per tenant',
      labelNames: ['tenantId'],
      registers: [this.registry],
    });
  }

  public incrementEvent() {
    this.eventsConsumed.inc();
  }

  public recordDecision(action: ScalingAction) {
    this.scalingDecisions.inc({ action });
  }

  public observeLatency(ms: number) {
    this.decisionLatency.observe(ms);
  }

  public setReplicas(tenantId: string, replicas: number) {
    this.currentReplicasGauge.set({ tenantId }, replicas);
  }
}

/* -------------------------------------------------------------------------- */
/*                          Scaling Decision Engine                           */
/* -------------------------------------------------------------------------- */

export class AdaptiveScalingDecisionEngine extends EventEmitter {
  private consumer!: Consumer;
  private producer!: Producer;
  private readonly strategyChain: IScalingStrategy;
  private readonly metrics = new MetricsCollector();

  constructor(private readonly config: EngineConfig) {
    super();

    /* Build strategy chain */
    const viral = new ViralSurgeScalingStrategy(
      config.viralSurgeRps,
      config.scaleUpStep
    );
    const latency = new HighLatencyScalingStrategy(
      config.p95LatencyMs,
      config.scaleUpStep
    );
    const contraction = new AggressiveContractionStrategy(config.scaleDownStep);
    const noop = new DefaultNoopStrategy();

    viral.setNext(latency).setNext(contraction).setNext(noop);
    this.strategyChain = viral;

    if (config.debug) {
      this.on('decision', (cmd: ScalingCommand) => {
        // eslint-disable-next-line no-console
        console.debug(`[Decision] Tenant=${cmd.tenantId} => replicas=${cmd.targetReplicas}. Reason: ${cmd.reason}`);
      });
    }
  }

  /* ----------------------------- Public API ------------------------------ */

  public async start(): Promise<void> {
    await this.bootstrapKafka();
    await this.consumer.subscribe({ topic: this.config.metricsTopic });
    await this.producer.connect();

    await this.consumer.run({
      partitionsConsumedConcurrently: 3,
      eachMessage: this.handleMessage.bind(this),
    });

    if (this.config.debug) {
      // eslint-disable-next-line no-console
      console.info('AdaptiveScalingDecisionEngine started...');
    }
  }

  public async shutdown(): Promise<void> {
    await this.consumer?.disconnect();
    await this.producer?.disconnect();
  }

  /* -------------------------- Internal Methods --------------------------- */

  private async bootstrapKafka(): Promise<void> {
    const kafka = new Kafka({
      clientId: this.config.clientId,
      brokers: this.config.kafkaBrokers,
      logLevel: this.config.debug ? logLevel.INFO : logLevel.ERROR,
    });

    this.consumer = kafka.consumer({ groupId: this.config.groupId });
    this.producer = kafka.producer();
    await this.consumer.connect();
  }

  private async handleMessage({ message }: EachMessagePayload): Promise<void> {
    const start = Date.now();
    this.metrics.incrementEvent();

    try {
      if (!message.value) {
        throw new Error('Empty message value');
      }

      const event: SocialMetricEvent = JSON.parse(message.value.toString());
      this.metrics.setReplicas(event.tenantId, event.currentReplicas);

      const decision = this.strategyChain.evaluate(event);
      if (!decision) return; // should not happen (DefaultNoop prevents)

      this.metrics.recordDecision(decision.action);
      const command: ScalingCommand = this.buildCommand(event, decision);

      // Notify in-process observers
      this.emit('decision', command);

      // Dispatch to Kafka for execution by Deployment Automation
      await this.producer.send({
        topic: this.config.commandTopic,
        messages: [{ value: JSON.stringify(command) }],
      });
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error('Failed to process metric event:', error);
    } finally {
      this.metrics.observeLatency(Date.now() - start);
    }
  }

  private buildCommand(
    event: SocialMetricEvent,
    decision: ScalingDecision
  ): ScalingCommand {
    const targetReplicas = Math.max(
      1,
      event.currentReplicas + decision.replicaDelta
    );

    return {
      tenantId: event.tenantId,
      targetReplicas,
      reason: decision.explanation,
      timestamp: Date.now(),
    };
  }
}

/* -------------------------------------------------------------------------- */
/*                     Bootstrap if executed as standalone                    */
/* -------------------------------------------------------------------------- */

if (require.main === module) {
  (async () => {
    try {
      const engine = new AdaptiveScalingDecisionEngine(ConfigLoader.load());
      await engine.start();

      process.on('SIGTERM', async () => {
        // eslint-disable-next-line no-console
        console.info('Gracefully shutting down AdaptiveScalingDecisionEngine');
        await engine.shutdown();
        process.exit(0);
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Fatal error while starting engine:', err);
      process.exit(1);
    }
  })();
}
```
