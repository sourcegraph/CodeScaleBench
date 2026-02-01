```typescript
/***************************************************************************************************
 *  File:         src/module_9.ts
 *  Project:      PulseSphere SocialOps (system_monitoring)
 *  Description:  Adaptive Capacity Orchestrator
 *
 *  This module consumes real-time social-signal and infrastructure-health events from Kafka,
 *  evaluates capacity-scaling decisions via pluggable strategies, passes the decision through a
 *  remediation chain, and finally executes scale commands against the cluster layer.
 *
 *  Architectural patterns showcased:
 *    • Observer Pattern             – Observers react to streamed events.
 *    • Strategy Pattern             – Hot-swappable capacity-evaluation strategies.
 *    • Command Pattern              – Encapsulates cluster actions (scale-up / scale-down).
 *    • Chain of Responsibility      – Guards & remediation pipeline before an action is executed.
 *
 *  NOTE: In production each dependency (Kafka, Kubernetes, Prom-API, NATS, etc.) would be wrapped
 *        in its own adapter; here they are simplified for brevity yet remain realistic.
 ***************************************************************************************************/

import { Kafka, EachMessagePayload } from 'kafkajs';
import { EventEmitter } from 'events';
import chalk from 'chalk';

/* -------------------------------------------------------------------------------------------------
 * Domain & DTOs
 * ---------------------------------------------------------------------------------------------- */

export interface SocialMetricEvent {
  readonly timestamp: number;            // Unix epoch (ms)
  readonly hashtag?: string;             // Trending tag if applicable
  readonly likes: number;
  readonly comments: number;
  readonly shares: number;
  readonly clusterLoad: number;          // 0–100 (% CPU)
}

export interface ScaleDecision {
  readonly action: 'scale_up' | 'scale_down' | 'none';
  readonly replicasDelta: number;        // +n or –n
  readonly reason: string;
}

export interface CapacityStrategy {
  evaluate(event: SocialMetricEvent): ScaleDecision;
}

/* -------------------------------------------------------------------------------------------------
 * Configuration
 * ---------------------------------------------------------------------------------------------- */

export interface OrchestratorConfig {
  kafkaBrokers: string[];
  topic: string;
  serviceName: string;
  reactive: {
    likeThreshold: number;
    shareThreshold: number;
    loadThreshold: number;
    scaleStep: number;
  };
  predictiveWindowSec: number;
  maxReplicas: number;
  minReplicas: number;
}

export const defaultConfig: OrchestratorConfig = {
  kafkaBrokers: ['kafka:9092'],
  topic: 'pulse.telemetry.social',
  serviceName: 'capacity-orchestrator',
  reactive: {
    likeThreshold: 10_000,
    shareThreshold: 5_000,
    loadThreshold: 75,
    scaleStep: 2,
  },
  predictiveWindowSec: 180,
  maxReplicas: 100,
  minReplicas: 3,
};

/* -------------------------------------------------------------------------------------------------
 * Strategy Implementations
 * ---------------------------------------------------------------------------------------------- */

/**
 * ReactiveStrategy – simple threshold-based scaling.
 */
export class ReactiveStrategy implements CapacityStrategy {
  constructor(private readonly cfg: OrchestratorConfig['reactive']) {}

  evaluate(event: SocialMetricEvent): ScaleDecision {
    const {
      likeThreshold,
      shareThreshold,
      loadThreshold,
      scaleStep,
    } = this.cfg;

    const socialSurge =
      event.likes >= likeThreshold || event.shares >= shareThreshold;
    const infraStress = event.clusterLoad >= loadThreshold;

    /* Scale up aggressively on social surge or infra stress */
    if (socialSurge || infraStress) {
      return {
        action: 'scale_up',
        replicasDelta: scaleStep,
        reason: socialSurge
          ? `Social surge detected (${event.likes} likes / ${event.shares} shares)`
          : `Infra stress detected (${event.clusterLoad}% load)`,
      };
    }

    /* Conservative scale-down when things look good */
    if (!socialSurge && event.clusterLoad < loadThreshold * 0.6) {
      return {
        action: 'scale_down',
        replicasDelta: 1,
        reason: 'Load normalized',
      };
    }

    return { action: 'none', replicasDelta: 0, reason: 'No scaling action' };
  }
}

/**
 * PredictiveMovingAverageStrategy – forecasts replicas based on smoothed social metrics.
 */
export class PredictiveMovingAverageStrategy implements CapacityStrategy {
  private readonly window: SocialMetricEvent[] = [];

  constructor(
    private readonly windowSec: number,
    private readonly maxReplicas: number,
    private readonly minReplicas: number,
  ) {}

  evaluate(event: SocialMetricEvent): ScaleDecision {
    // Purge window
    const now = Date.now();
    this.window.push(event);
    while (
      this.window.length &&
      now - this.window[0].timestamp > this.windowSec * 1_000
    ) {
      this.window.shift();
    }

    // Simple moving average of shares
    const totalShares = this.window.reduce((sum, ev) => sum + ev.shares, 0);
    const avgShares = totalShares / Math.max(this.window.length, 1);

    // Map average shares to desired replicas linearly
    // Design assumption: 0 shares -> minReplicas, 50k shares -> maxReplicas
    const targetReplicas =
      this.minReplicas +
      ((Math.min(avgShares, 50_000) / 50_000) *
        (this.maxReplicas - this.minReplicas));

    const currentReplicas = ClusterFacade.getReplicaCount();
    const diff = Math.round(targetReplicas - currentReplicas);

    if (diff === 0) {
      return { action: 'none', replicasDelta: 0, reason: 'Forecast steady' };
    }

    return {
      action: diff > 0 ? 'scale_up' : 'scale_down',
      replicasDelta: Math.abs(diff),
      reason: `MovingAvg shares: ${avgShares.toFixed(0)}`,
    };
  }
}

/* -------------------------------------------------------------------------------------------------
 * Cluster Facade – abstracts underlying orchestrator (Kubernetes, Nomad, etc.)
 * ---------------------------------------------------------------------------------------------- */

export interface ClusterAPI {
  scale(delta: number): Promise<void>;
  getReplicas(): number;
}

class InMemoryClusterAPI implements ClusterAPI {
  private replicas = 5;

  async scale(delta: number): Promise<void> {
    const newReplicas = Math.max(1, this.replicas + delta);
    console.log(
      chalk.magenta(
        `[ClusterAPI] Scaling from ${this.replicas} → ${newReplicas} replicas`,
      ),
    );
    this.replicas = newReplicas;
    // Real implementation would call K8s API server here.
  }

  getReplicas(): number {
    return this.replicas;
  }
}

const clusterApi = new InMemoryClusterAPI();

export class ClusterFacade {
  static async scale(delta: number): Promise<void> {
    await clusterApi.scale(delta);
  }

  static getReplicaCount(): number {
    return clusterApi.getReplicas();
  }
}

/* -------------------------------------------------------------------------------------------------
 * Command Pattern
 * ---------------------------------------------------------------------------------------------- */

abstract class ScaleCommand {
  constructor(
    protected readonly delta: number,
    protected readonly reason: string,
  ) {}

  abstract execute(): Promise<void>;
}

class ScaleUpCommand extends ScaleCommand {
  async execute(): Promise<void> {
    console.log(
      chalk.green(
        `[ScaleUpCommand] +${this.delta} replicas. Reason: ${this.reason}`,
      ),
    );
    await ClusterFacade.scale(this.delta);
  }
}

class ScaleDownCommand extends ScaleCommand {
  async execute(): Promise<void> {
    console.log(
      chalk.yellow(
        `[ScaleDownCommand] -${this.delta} replicas. Reason: ${this.reason}`,
      ),
    );
    await ClusterFacade.scale(-this.delta);
  }
}

/* -------------------------------------------------------------------------------------------------
 * Chain of Responsibility – Remediation Pipeline
 * ---------------------------------------------------------------------------------------------- */

interface Handler {
  setNext(next: Handler): Handler;
  handle(decision: ScaleDecision): Promise<void>;
}

abstract class AbstractHandler implements Handler {
  private next?: Handler;

  setNext(next: Handler): Handler {
    this.next = next;
    return next;
  }

  async handle(decision: ScaleDecision): Promise<void> {
    if (this.next) {
      await this.next.handle(decision);
    }
  }
}

/**
 * BudgetGuardHandler – ensures we don't exceed financial constraints.
 * Example: block scale-up past certain replica count to avoid budget shock.
 */
class BudgetGuardHandler extends AbstractHandler {
  constructor(private readonly maxReplicas: number) {
    super();
  }

  override async handle(decision: ScaleDecision): Promise<void> {
    const projectedReplicas =
      ClusterFacade.getReplicaCount() +
      (decision.action === 'scale_up' ? decision.replicasDelta : 0);
    if (decision.action === 'scale_up' && projectedReplicas > this.maxReplicas) {
      console.warn(
        chalk.red(
          `[BudgetGuard] Aborted scale-up – projected replicas (${projectedReplicas}) exceeds budget cap (${this.maxReplicas}).`,
        ),
      );
      return; // stop chain
    }
    await super.handle(decision);
  }
}

/**
 * CooldownGuardHandler – rate-limits scaling frequency.
 */
class CooldownGuardHandler extends AbstractHandler {
  private lastActionAt = 0;
  constructor(private readonly minIntervalMs: number) {
    super();
  }

  override async handle(decision: ScaleDecision): Promise<void> {
    const now = Date.now();
    if (decision.action !== 'none' && now - this.lastActionAt < this.minIntervalMs) {
      console.info(
        chalk.gray('[CooldownGuard] Scaling skipped – still in cooldown window.'),
      );
      return;
    }
    if (decision.action !== 'none') {
      this.lastActionAt = now;
    }
    await super.handle(decision);
  }
}

/**
 * ExecuteCommandHandler – last handler that executes the scaling command.
 */
class ExecuteCommandHandler extends AbstractHandler {
  override async handle(decision: ScaleDecision): Promise<void> {
    if (decision.action === 'none') {
      console.debug(chalk.gray('[Execute] No scaling needed.'));
      return;
    }

    const CommandClass =
      decision.action === 'scale_up' ? ScaleUpCommand : ScaleDownCommand;
    const command = new CommandClass(decision.replicasDelta, decision.reason);

    try {
      await command.execute();
    } catch (err) {
      console.error(chalk.red(`[Execute] Scaling command failed: ${err}`));
    }
  }
}

/* -------------------------------------------------------------------------------------------------
 * Observer Pattern – Kafka Consumer & Event Dispatcher
 * ---------------------------------------------------------------------------------------------- */

export interface TelemetryObserver {
  update(event: SocialMetricEvent): Promise<void>;
}

class TelemetrySubject extends EventEmitter {
  private observers = new Set<TelemetryObserver>();

  addObserver(observer: TelemetryObserver): void {
    this.observers.add(observer);
  }

  removeObserver(observer: TelemetryObserver): void {
    this.observers.delete(observer);
  }

  async notify(event: SocialMetricEvent): Promise<void> {
    for (const obs of this.observers) {
      try {
        await obs.update(event);
      } catch (err) {
        console.error(
          chalk.red(`[TelemetrySubject] Observer failed: ${err as string}`),
        );
      }
    }
  }
}

class KafkaSocialConsumer {
  private kafka: Kafka;

  constructor(
    private readonly cfg: OrchestratorConfig,
    private readonly subject: TelemetrySubject,
  ) {
    this.kafka = new Kafka({
      clientId: cfg.serviceName,
      brokers: cfg.kafkaBrokers,
    });
  }

  async start(): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: this.cfg.serviceName });

    await consumer.connect();
    await consumer.subscribe({ topic: this.cfg.topic });

    await consumer.run({
      eachMessage: async (payload: EachMessagePayload) => {
        try {
          const messageValue = payload.message.value?.toString();
          if (!messageValue) return;
          const event: SocialMetricEvent = JSON.parse(messageValue);
          await this.subject.notify(event);
        } catch (err) {
          console.error(
            chalk.red(`[KafkaConsumer] Failed to process message: ${err}`),
          );
        }
      },
    });

    console.log(
      chalk.blue(
        `[KafkaConsumer] Listening on topic '${this.cfg.topic}' (${this.cfg.kafkaBrokers.join(
          ',',
        )})`,
      ),
    );
  }
}

/* -------------------------------------------------------------------------------------------------
 * Concrete Observer – CapacityEvaluator
 * ---------------------------------------------------------------------------------------------- */

class CapacityEvaluator implements TelemetryObserver {
  private readonly strategy: CapacityStrategy;
  private readonly remediationChain: Handler;

  constructor(strategy: CapacityStrategy, cfg: OrchestratorConfig) {
    this.strategy = strategy;

    /* Build remediation chain */
    const budget = new BudgetGuardHandler(cfg.maxReplicas);
    const cooldown = new CooldownGuardHandler(60_000); // 1 minute
    const executor = new ExecuteCommandHandler();
    budget.setNext(cooldown).setNext(executor);

    this.remediationChain = budget;
  }

  async update(event: SocialMetricEvent): Promise<void> {
    const decision = this.strategy.evaluate(event);
    await this.remediationChain.handle(decision);
  }
}

/* -------------------------------------------------------------------------------------------------
 * Bootstrap
 * ---------------------------------------------------------------------------------------------- */

export async function bootstrap(
  cfg: OrchestratorConfig = defaultConfig,
): Promise<void> {
  const telemetrySubject = new TelemetrySubject();

  /* Choose strategy dynamically (simplified) */
  const strategy: CapacityStrategy =
    process.env.CAPACITY_STRATEGY === 'predictive'
      ? new PredictiveMovingAverageStrategy(
          cfg.predictiveWindowSec,
          cfg.maxReplicas,
          cfg.minReplicas,
        )
      : new ReactiveStrategy(cfg.reactive);

  const evaluator = new CapacityEvaluator(strategy, cfg);
  telemetrySubject.addObserver(evaluator);

  const kafkaConsumer = new KafkaSocialConsumer(cfg, telemetrySubject);
  await kafkaConsumer.start();
}

/* Execute directly when run as a script */
if (require.main === module) {
  bootstrap().catch((err) => {
    console.error(chalk.red(`[Bootstrap] Fatal error: ${err}`));
    process.exit(1);
  });
}
```
