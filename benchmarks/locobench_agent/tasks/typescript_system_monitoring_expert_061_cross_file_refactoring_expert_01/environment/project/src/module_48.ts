```typescript
/***************************************************************************************************
 *  File:        src/module_48.ts
 *  Project:     PulseSphere SocialOps – system_monitoring
 *
 *  Description:
 *  ------------
 *  CapacityOrchestratorModule
 *  --------------------------
 *  This module is responsible for transforming enriched telemetry (infra-metrics + social context)
 *  into concrete auto-scaling actions.  It combines several architecture patterns prescribed for
 *  PulseSphere:
 *
 *    • Chain-of-Responsibility  → composable rule handlers to determine whether we should scale.
 *    • Strategy Pattern        → pluggable scaling algorithms (reactive vs. predictive, etc.)
 *    • Command Pattern         → encapsulate the side-effectful scale request sent over the mesh.
 *    • Event-Driven            → consumes Kafka topic “telemetry.social.enriched”.
 *
 *  Usage:
 *  ------
 *  The module exports a single entry-point `CapacityOrchestrator` that is instantiated by the
 *  ProcessManager service.  No external entity should call its private methods directly; instead
 *  push telemetry events into the exposed `ingest` method or rely on the built-in Kafka consumer.
 *
 *  (C) 2024 Perceptor Labs – PulseSphere Team
 ***************************************************************************************************/

import { EventEmitter } from 'events';
import { Kafka, EachMessagePayload } from 'kafkajs';
import ms from 'ms';

/* -------------------------------------------------------------------------- */
/*                                Domain Types                                */
/* -------------------------------------------------------------------------- */

/**
 * Raw telemetry event emitted by upstream enrichment pipeline.
 */
export interface EnrichedTelemetry {
  tenantId: string;
  clusterId: string;

  /* Infrastructure metrics */
  cpuPct: number;         // e.g., 73.1
  memPct: number;         // e.g., 84.0
  reqPerSec: number;      // incoming HTTP RPS

  /* Social context signals */
  likesDelta: number;     // likes per second
  commentsDelta: number;  // comments per second
  sharesDelta: number;    // shares per second
  hashtagTrendScore: number; // 0-100, computed by HashtagTrendService

  timestamp: number;      // unix epoch millis
}

/**
 * A contextual object passed through the chain and into strategies.
 */
interface ScalingContext {
  readonly event: EnrichedTelemetry;
  clusterCurrentReplicas: number;
  // Possibly more metadata from config-service (maxReplicas, SLA, costBudget, ...)
}

/**
 * Final decision output by a scaling strategy.
 */
interface ScalingDecision {
  scaleNeeded: boolean;
  targetReplicas: number; // ignored if scaleNeeded === false
  rationale: string;
}

/* -------------------------------------------------------------------------- */
/*                            Chain-of-Responsibility                          */
/* -------------------------------------------------------------------------- */

abstract class ScalingRuleHandler {
  protected next?: ScalingRuleHandler;

  setNext(handler: ScalingRuleHandler): ScalingRuleHandler {
    this.next = handler;
    return handler;
  }

  async handle(ctx: ScalingContext): Promise<ScalingContext> {
    const processed = await this.process(ctx);
    if (this.next) {
      return this.next.handle(processed);
    }
    return processed;
  }

  protected abstract process(ctx: ScalingContext): Promise<ScalingContext>;
}

/**
 * Rule #1 – Basic infrastructure protection.
 * If CPU or Memory is over a high-water-mark, force a flag for scaling ASAP.
 */
class InfraThresholdRule extends ScalingRuleHandler {
  private CPU_HWM = 0.8;   // 80 %
  private MEM_HWM = 0.85;  // 85 %

  protected async process(ctx: ScalingContext): Promise<ScalingContext> {
    const { cpuPct, memPct } = ctx.event;

    if (cpuPct >= this.CPU_HWM * 100 || memPct >= this.MEM_HWM * 100) {
      ctx = Object.assign({}, ctx, { forcedScale: true });
    }

    return ctx;
  }
}

/**
 * Rule #2 – Social virality spike detection.
 * Uses a naive derivative; production system would call ML service.
 */
class SocialSpikeRule extends ScalingRuleHandler {
  private TREND_HWM = 70; // “trending” threshold

  protected async process(ctx: ScalingContext): Promise<ScalingContext> {
    const { likesDelta, sharesDelta, hashtagTrendScore } = ctx.event;

    const viralityScore = likesDelta * 0.3 + sharesDelta * 0.7;

    if (viralityScore > 800 || hashtagTrendScore > this.TREND_HWM) {
      ctx = Object.assign({}, ctx, { socialSpike: true });
    }
    return ctx;
  }
}

/**
 * Rule #3 – No-op: purposely last in the chain, can log or add context.
 */
class TerminalRule extends ScalingRuleHandler {
  protected async process(ctx: ScalingContext): Promise<ScalingContext> {
    // Nothing to do – could audit here.
    return ctx;
  }
}

/* -------------------------------------------------------------------------- */
/*                               Strategy Pattern                             */
/* -------------------------------------------------------------------------- */

/**
 * Strategy interface for producing scaling decisions.
 */
interface ScalingStrategy {
  supports(ctx: ScalingContext): boolean; // choose strategy
  execute(ctx: ScalingContext): Promise<ScalingDecision>;
}

/**
 * Reactive (threshold-based) strategy – if any forced flag is present.
 */
class ReactiveScalingStrategy implements ScalingStrategy {
  supports(ctx: ScalingContext): boolean {
    // Reactive strategy only if something flagged urgency.
    return (ctx as any).forcedScale || (ctx as any).socialSpike;
  }

  async execute(ctx: ScalingContext): Promise<ScalingDecision> {
    const multiplier = (ctx as any).socialSpike ? 1.5 : 1.25;
    const nextReplicas = Math.ceil(ctx.clusterCurrentReplicas * multiplier);

    return {
      scaleNeeded: nextReplicas > ctx.clusterCurrentReplicas,
      targetReplicas: nextReplicas,
      rationale: 'Reactive scaling due to threshold breach or social spike',
    };
  }
}

/**
 * Predictive strategy – uses a rolling average to smooth load.
 */
class PredictiveScalingStrategy implements ScalingStrategy {
  private readonly WINDOW = 6; // last 6 observations (approx 30s if period is 5s)

  private readonly history: Map<string, EnrichedTelemetry[]> = new Map();

  supports(ctx: ScalingContext): boolean {
    // Act as default strategy if others don’t match.
    return true;
  }

  async execute(ctx: ScalingContext): Promise<ScalingDecision> {
    const bucket = this.history.get(ctx.clusterCurrentReplicas.toString()) ?? [];
    bucket.push(ctx.event);
    if (bucket.length > this.WINDOW) bucket.shift();
    this.history.set(ctx.clusterCurrentReplicas.toString(), bucket);

    const avgRps =
      bucket.reduce((acc, cur) => acc + cur.reqPerSec, 0) / bucket.length;

    const rpsPerPod = avgRps / ctx.clusterCurrentReplicas;
    const TARGET_RPS_PER_POD = 250; // determined empirically

    const neededReplicas = Math.ceil(avgRps / TARGET_RPS_PER_POD);

    return {
      scaleNeeded: neededReplicas !== ctx.clusterCurrentReplicas,
      targetReplicas: neededReplicas,
      rationale: 'Predictive scaling based on moving average of RPS',
    };
  }
}

/* -------------------------------------------------------------------------- */
/*                                Command Pattern                             */
/* -------------------------------------------------------------------------- */

interface Command {
  execute(): Promise<void>;
}

/**
 * Encapsulates the action of sending a scale request to OrchestratorService.
 */
class ScaleClusterCommand implements Command {
  constructor(
    private readonly clusterId: string,
    private readonly targetReplicas: number,
    private readonly emitter: EventEmitter,
  ) {}

  async execute(): Promise<void> {
    // Payload adheres to Service Mesh contract for InternalOrchestrator.
    const payload = {
      type: 'SCALE_REQUEST',
      clusterId: this.clusterId,
      replicas: this.targetReplicas,
      issuedAt: Date.now(),
    };

    try {
      // Using EventEmitter here; in real system, this would be a gRPC mesh call.
      this.emitter.emit('orchestrator.scale', payload);
    } catch (err) {
      /* eslint-disable no-console */
      console.error('Failed to emit scale command', err);
      throw err;
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                     Capacity Orchestrator – Public API                     */
/* -------------------------------------------------------------------------- */

export interface CapacityOrchestratorOptions {
  kafkaBrokers: string[];
  topic?: string;
  groupId?: string;
  clusterReplicaProvider: (clusterId: string) => Promise<number>; // pulls current replica count
  orchestratorEmitter: EventEmitter;
  /**
   * How long to debounce identical decisions for the same cluster?
   * Prevents flip-flopping (default: 30s)
   */
  decisionCooldown?: string;
}

export class CapacityOrchestrator {
  private readonly kafka: Kafka;
  private readonly topic: string;
  private readonly groupId: string;
  private readonly chain: ScalingRuleHandler;
  private readonly strategies: ScalingStrategy[];
  private readonly lastDecisionAt: Map<string, number> = new Map();
  private readonly decisionCooldownMs: number;

  constructor(private readonly opts: CapacityOrchestratorOptions) {
    this.kafka = new Kafka({
      brokers: opts.kafkaBrokers,
      clientId: 'pulse-capacity-orchestrator',
    });
    this.topic = opts.topic ?? 'telemetry.social.enriched';
    this.groupId = opts.groupId ?? 'capacity-orchestrator-group';
    this.decisionCooldownMs = ms(opts.decisionCooldown ?? '30s');

    // Build CoR chain
    const infra = new InfraThresholdRule();
    const social = new SocialSpikeRule();
    const terminal = new TerminalRule();
    infra.setNext(social).setNext(terminal);
    this.chain = infra;

    this.strategies = [
      new ReactiveScalingStrategy(),
      new PredictiveScalingStrategy(),
    ];
  }

  /**
   * Launch kafka consumer loop.
   */
  async start(): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: this.groupId });
    await consumer.connect();
    await consumer.subscribe({ topic: this.topic, fromBeginning: false });

    await consumer.run({
      eachMessage: async (payload: EachMessagePayload) => {
        try {
          const data = JSON.parse(
            payload.message.value?.toString() || '{}',
          ) as EnrichedTelemetry;
          await this.ingest(data);
        } catch (err) {
          console.error('Failed to process telemetry message', err);
          // DLQ or alerting integration would go here.
        }
      },
    });

    console.info(
      `[CapacityOrchestrator] Consumer started on topic ${this.topic}`,
    );
  }

  /**
   * Ingest a telemetry event (can be called directly by tests).
   */
  async ingest(event: EnrichedTelemetry): Promise<void> {
    // Build context
    const replicaCount =
      (await this.opts.clusterReplicaProvider(event.clusterId)) ?? 1;

    let ctx: ScalingContext = {
      event,
      clusterCurrentReplicas: replicaCount,
    };

    // 1. Run through rule chain
    ctx = await this.chain.handle(ctx);

    // 2. Pick matching strategy
    const strategy =
      this.strategies.find((s) => s.supports(ctx)) ??
      this.strategies[this.strategies.length - 1];

    const decision = await strategy.execute(ctx);

    if (!decision.scaleNeeded) return;

    // 3. Debounce decisions
    const now = Date.now();
    const lastAt = this.lastDecisionAt.get(event.clusterId) ?? 0;
    if (now - lastAt < this.decisionCooldownMs) {
      return; // skip repeated decision
    }
    this.lastDecisionAt.set(event.clusterId, now);

    // 4. Emit command
    const cmd = new ScaleClusterCommand(
      event.clusterId,
      decision.targetReplicas,
      this.opts.orchestratorEmitter,
    );
    await cmd.execute();

    // 5. Audit log
    console.info(
      `[CapacityOrchestrator] scale cmd: cluster=${event.clusterId} → ${decision.targetReplicas} pods :: ${decision.rationale}`,
    );
  }

  /**
   * Graceful shutdown (flushes Kafka offsets, etc.)
   */
  async stop(timeout = '10s'): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: this.groupId });
    try {
      await consumer.disconnect();
    } catch (err) {
      console.warn('Consumer disconnect failed', err);
    }

    // Wait for pending decisions (simplified)
    await new Promise((res) => setTimeout(res, ms(timeout)));
  }
}

/* --------------------------------------------------------------------------------------------- */
export default CapacityOrchestrator;
```