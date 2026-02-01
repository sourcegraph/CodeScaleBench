```typescript
/**
 * File: src/module_23.ts
 * PulseSphere SocialOps – Adaptive, socially-aware auto-scaling module
 *
 * This module demonstrates a partial, but production-grade implementation of the
 * Strategy + Observer + Chain-of-Responsibility patterns.  It listens to
 * Apache-Kafka  & NATS event streams, merges infrastructure telemetry with
 * social-interaction spikes, computes a composite “trending-pressure” score and,
 * if necessary, emits a **ScaleCommand** to the Platform Orchestrator.
 *
 * NOTE: To stay self-contained, certain domain interfaces/classes are re-declared
 * here. In the real codebase they live inside dedicated packages
 * (`@pulsesphere/contracts`, `@pulsesphere/eventing`, etc.).
 */

import { Kafka, EachMessagePayload, logLevel as KafkaLogLevel } from 'kafkajs';
import {
  connect as connectNats,
  JSONCodec,
  NatsConnection,
  Subscription,
} from 'nats';
import { EventEmitter } from 'events';

// ---------------------------------------------------------------------------
// Section 1: Domain contracts & shared utilities
// ---------------------------------------------------------------------------

/** Infrastructure usage snapshot emitted by Prometheus / OpenTelemetry */
export interface InfraMetric {
  timestamp: number; // unix(ms)
  cpu: number; // %
  memory: number; // MB
  rps: number; // requests per second
  podCount: number; // k8s replica count
}

/** Social interaction sample (e.g., aggregated per second) */
export interface SocialPulse {
  timestamp: number;
  likes: number;
  comments: number;
  shares: number;
  newFollowers: number;
}

/** Composite envelope emitted by this module after enrichment */
export interface EnrichedMetric {
  timestamp: number;
  infra: InfraMetric;
  social: SocialPulse;
  trendingPressure: number; // [0..1]
}

/** Scaling targets we support right now */
export enum ScaleAction {
  NOOP = 'NOOP',
  SCALE_UP = 'SCALE_UP',
  SCALE_DOWN = 'SCALE_DOWN',
}

/** Command object pushed on to the Orchestrator’s command bus */
export interface ScaleCommand {
  action: ScaleAction;
  desiredPods: number;
  reason: string;
  correlationId: string;
  issuedAt: number; // unix(ms)
}

// ---------------------------------------------------------------------------
// Section 2: Observer pattern – stream ingestion & event dispatch
// ---------------------------------------------------------------------------

/**
 * SocialInfraBus coordinates Infra + Social subsystems and exposes an
 * EventEmitter-style API for downstream consumers.
 */
class SocialInfraBus extends EventEmitter {
  private readonly kafka: Kafka;
  private readonly natsConnPromise: Promise<NatsConnection>;
  private readonly json = JSONCodec();

  constructor(
    private readonly kafkaBrokers: string[],
    private readonly kafkaInfraTopic = 'telemetry.infra',
    private readonly natsSocialSubject = 'pulse.social.*',
  ) {
    super();
    this.kafka = new Kafka({
      clientId: 'pulsesphere-system-monitoring',
      brokers: kafkaBrokers,
      logLevel: KafkaLogLevel.ERROR,
    });
    this.natsConnPromise = connectNats({ servers: process.env.NATS_URL });
  }

  async start(): Promise<void> {
    await Promise.all([this.consumeInfraStream(), this.consumeSocialStream()]);
  }

  private async consumeInfraStream(): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: 'infra-metric-consumers' });
    await consumer.connect();
    await consumer.subscribe({ topic: this.kafkaInfraTopic, fromBeginning: false });

    consumer.run({
      eachMessage: async ({ message }: EachMessagePayload) => {
        try {
          const payload = message.value?.toString('utf8');
          if (!payload) return;
          const metric = JSON.parse(payload) as InfraMetric;
          this.emit('infra', metric);
        } catch (err) {
          console.error('[InfraConsumer] Bad message', err);
        }
      },
    });
  }

  private async consumeSocialStream(): Promise<void> {
    const nc = await this.natsConnPromise;
    const sub: Subscription = nc.subscribe(this.natsSocialSubject);
    (async () => {
      for await (const m of sub) {
        try {
          const social = this.json.decode(m.data) as SocialPulse;
          this.emit('social', social);
        } catch (err) {
          console.error('[SocialConsumer] Bad message', err);
        }
      }
    })().catch((e) => console.error('NATS subscription failure', e));
  }
}

// ---------------------------------------------------------------------------
// Section 3: Strategy pattern – trending pressure calculation
// ---------------------------------------------------------------------------

/**
 * Compute trending “pressure” based on infra + social deltas.
 *
 * Contract for pluggable algorithms – multiple strategies can coexist and be
 * A/B tested via feature flags.
 */
export interface TrendingPressureStrategy {
  compute(
    lastEnriched: EnrichedMetric | null,
    nextInfra: InfraMetric,
    nextSocial: SocialPulse,
  ): EnrichedMetric;
}

/**
 * Default implementation – uses exponentially weighted moving average (EWMA)
 * on infra RPS + social interactions to produce a [0..1] pressure indicator.
 */
export class EWMAPressureStrategy implements TrendingPressureStrategy {
  private readonly alpha: number;

  // eslint-disable-next-line no-useless-constructor
  constructor(alpha = 0.3) {
    this.alpha = alpha;
  }

  compute(
    lastEnriched: EnrichedMetric | null,
    nextInfra: InfraMetric,
    nextSocial: SocialPulse,
  ): EnrichedMetric {
    const lastPressure = lastEnriched?.trendingPressure ?? 0;
    const socialIntensity =
      nextSocial.likes +
      2 * nextSocial.comments +
      3 * nextSocial.shares +
      4 * nextSocial.newFollowers;

    // Basic linear combination, could be replaced by ML model
    const rawScore =
      0.6 * (nextInfra.rps / Math.max(nextInfra.podCount, 1)) +
      0.4 * socialIntensity;

    // Normalize (very naive; real implementation uses dynamic baselines)
    const normalized = Math.tanh(rawScore / 10); // [0;1) roughly

    const ewma = this.alpha * normalized + (1 - this.alpha) * lastPressure;

    return {
      timestamp: Date.now(),
      infra: nextInfra,
      social: nextSocial,
      trendingPressure: Number(ewma.toFixed(4)),
    };
  }
}

// ---------------------------------------------------------------------------
// Section 4: Chain-of-Responsibility – scale decision rules
// ---------------------------------------------------------------------------

interface ScaleRule {
  setNext(rule: ScaleRule | null): void;
  evaluate(metric: EnrichedMetric): ScaleCommand | null;
}

abstract class AbstractScaleRule implements ScaleRule {
  protected next: ScaleRule | null = null;

  setNext(rule: ScaleRule | null): void {
    this.next = rule;
  }

  evaluate(metric: EnrichedMetric): ScaleCommand | null {
    const result = this.doEvaluate(metric);
    if (result) return result;
    if (this.next) return this.next.evaluate(metric);
    return null;
  }

  protected abstract doEvaluate(metric: EnrichedMetric): ScaleCommand | null;

  protected createCommand(
    action: ScaleAction,
    desiredPods: number,
    reason: string,
  ): ScaleCommand {
    return {
      action,
      desiredPods,
      reason,
      correlationId: crypto.randomUUID(),
      issuedAt: Date.now(),
    };
  }
}

/** Scale-up if pressure > 0.8 and we’re not yet at maxPods */
class AggressiveScaleUpRule extends AbstractScaleRule {
  constructor(private readonly maxPods = 100) {
    super();
  }

  protected doEvaluate(metric: EnrichedMetric): ScaleCommand | null {
    const { trendingPressure, infra } = metric;
    if (trendingPressure > 0.8 && infra.podCount < this.maxPods) {
      return this.createCommand(
        ScaleAction.SCALE_UP,
        Math.min(infra.podCount * 2, this.maxPods),
        `High trending pressure (${trendingPressure})`,
      );
    }
    return null;
  }
}

/** Scale-down if pressure < 0.2 consistently */
class ConservativeScaleDownRule extends AbstractScaleRule {
  private readonly window: number[] = [];
  constructor(private readonly minPods = 2, private readonly n = 5) {
    super();
  }

  protected doEvaluate(metric: EnrichedMetric): ScaleCommand | null {
    this.window.push(metric.trendingPressure);
    if (this.window.length > this.n) this.window.shift();
    if (
      this.window.length === this.n &&
      this.window.every((x) => x < 0.2) &&
      metric.infra.podCount > this.minPods
    ) {
      return this.createCommand(
        ScaleAction.SCALE_DOWN,
        Math.max(Math.ceil(metric.infra.podCount / 2), this.minPods),
        `Sustained low pressure for ${this.n} intervals`,
      );
    }
    return null;
  }
}

/** Fallback rule – do nothing */
class NoOpRule extends AbstractScaleRule {
  protected doEvaluate(): ScaleCommand | null {
    return this.createCommand(ScaleAction.NOOP, -1, 'Default – no action');
  }
}

/**
 * Build the rule chain: aggressive-up -> conservative-down -> noop
 */
function buildScaleRuleChain(): ScaleRule {
  const up = new AggressiveScaleUpRule();
  const down = new ConservativeScaleDownRule();
  const noop = new NoOpRule();
  up.setNext(down);
  down.setNext(noop);
  return up;
}

// ---------------------------------------------------------------------------
// Section 5: Orchestrator bridge (could be Kafka/NATS/HTTP etc.)
// ---------------------------------------------------------------------------

/**
 * In real life this would push commands onto a Kafka topic that is consumed
 * by the Kubernetes-orchestrator service.  Here we simply log & swallow.
 */
class OrchestratorCommandBus {
  async dispatch(cmd: ScaleCommand): Promise<void> {
    if (cmd.action === ScaleAction.NOOP) return;
    // Replace with production-grade serializer & producer
    console.log('[OrchestratorCommandBus] Dispatching', cmd);
  }
}

// ---------------------------------------------------------------------------
// Section 6: Glue – wire everything together
// ---------------------------------------------------------------------------

import * as crypto from 'crypto';

export class AdaptiveScalingController {
  private lastEnriched: EnrichedMetric | null = null;
  private readonly bus: SocialInfraBus;
  private readonly pressureStrategy: TrendingPressureStrategy;
  private readonly ruleChain: ScaleRule;
  private readonly orchestrator = new OrchestratorCommandBus();

  constructor(kafkaBrokers: string[]) {
    this.bus = new SocialInfraBus(kafkaBrokers);
    this.pressureStrategy = new EWMAPressureStrategy(0.25);
    this.ruleChain = buildScaleRuleChain();

    // Bind listeners
    this.bus.on('infra', (infra: InfraMetric) =>
      this.handleTelemetry(infra, null),
    );
    this.bus.on('social', (social: SocialPulse) =>
      this.handleTelemetry(null, social),
    );
  }

  async start(): Promise<void> {
    await this.bus.start();
    console.log('[AdaptiveScalingController] Started');
  }

  private pendingInfra: InfraMetric | null = null;
  private pendingSocial: SocialPulse | null = null;

  /**
   * Called whenever we receive either an infra or a social sample.  We wait until we
   * have both for the same “tick” (1-second grace window) before computing pressure.
   */
  private async handleTelemetry(
    infraSample: InfraMetric | null,
    socialSample: SocialPulse | null,
  ): Promise<void> {
    if (infraSample) this.pendingInfra = infraSample;
    if (socialSample) this.pendingSocial = socialSample;

    // Align timestamps within ±1s
    if (
      this.pendingInfra &&
      this.pendingSocial &&
      Math.abs(this.pendingInfra.timestamp - this.pendingSocial.timestamp) <
        1_000
    ) {
      const enriched = this.pressureStrategy.compute(
        this.lastEnriched,
        this.pendingInfra,
        this.pendingSocial,
      );
      this.lastEnriched = enriched;

      const command = this.ruleChain.evaluate(enriched);
      if (command) await this.orchestrator.dispatch(command);

      // Clear
      this.pendingInfra = null;
      this.pendingSocial = null;
    }
  }
}

// ---------------------------------------------------------------------------
// Section 7: Bootstrap (only in CLI/Woker context)
// ---------------------------------------------------------------------------

if (require.main === module) {
  // eslint-disable-next-line @typescript-eslint/no-floating-promises
  new AdaptiveScalingController(
    (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
  )
    .start()
    .catch((err) => {
      console.error('[AdaptiveScalingController] Fatal error', err);
      process.exit(1);
    });
}
```