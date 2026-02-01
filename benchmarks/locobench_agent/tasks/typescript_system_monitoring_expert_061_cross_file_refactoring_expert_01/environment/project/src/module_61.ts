```typescript
/**
 *  ██████╗ ██╗   ██╗██╗     ███████╗███████╗███████╗ ██████╗ ██████╗ ███████╗
 *  ██╔══██╗██║   ██║██║     ██╔════╝██╔════╝██╔════╝██╔════╝██╔═══██╗██╔════╝
 *  ██████╔╝██║   ██║██║     █████╗  ███████╗█████╗  ██║     ██║   ██║███████╗
 *  ██╔═══╝ ██║   ██║██║     ██╔══╝  ╚════██║██╔══╝  ██║     ██║   ██║╚════██║
 *  ██║     ╚██████╔╝███████╗███████╗███████║███████╗╚██████╗╚██████╔╝███████║
 *  ╚═╝      ╚═════╝ ╚══════╝╚══════╝╚══════╝╚══════╝ ╚═════╝ ╚═════╝ ╚══════╝
 *
 * PulseSphere SocialOps – Capacity Orchestration Engine
 * -----------------------------------------------------
 * This module consumes enriched telemetry events, pushes them through a
 * Chain-of-Responsibility pipeline, and leverages pluggable Strategy
 * implementations to decide whether to scale infrastructure resources.
 *
 * Patterns in play:
 *  • Chain-of-Responsibility   – incremental enrichment + anomaly detection
 *  • Strategy                  – dynamic selection of scaling policy
 *  • Observer / Event Driven   – NATS subscription for real-time telemetry
 *
 * It purposely DOES NOT interact with cloud APIs; instead, it emits a
 * domain-specific “ScalingCommand” to a Kafka topic consumed by the
 * dedicated autoscaling micro-service.
 */

import { connect, JSONCodec, NatsConnection, Subscription } from 'nats';
import pino from 'pino';
import { v4 as uuid } from 'uuid';

// --- Logger -----------------------------------------------------------------

// Centralised logger; in production this would be a shared infra component.
const log = pino({
  name: 'capacity-orchestration-engine',
  level: process.env.LOG_LEVEL || 'info',
});

// --- Domain Models ----------------------------------------------------------

/**
 * Telemetry – Metrics about infrastructure fused with social signals.
 */
export interface TelemetryEvent {
  serverId: string;
  timestamp: number;           // epoch millis
  metrics: {
    cpu: number;               // utilisation 0-100
    memory: number;            // utilisation 0-100
    latencyMs: number;         // p99 latency
  };
  social: {
    likeRate: number;          // likes / second
    commentRate: number;       // comments / second
    shareRate: number;         // shares / second
    influencerOnline?: boolean; // heuristically detected presence
  };
}

/**
 * Aggregated state after passing the handler pipeline.
 */
interface AggregatedState {
  cpuAvg: number;
  memoryAvg: number;
  latencyP99: number;
  socialPressureScore: number; // Normalised 0-1
  sampleSize: number;
}

/**
 * Resulting scaling decision.
 */
export enum ScalingDirective {
  SCALE_UP = 'scale_up',
  SCALE_DOWN = 'scale_down',
  MAINTAIN = 'maintain',
}

export interface ScalingCommand {
  id: string;
  directive: ScalingDirective;
  reason: string;
  value?: number;       // # of instances to add/remove
  timestamp: number;    // epoch millis
}

// --- Chain-of-Responsibility  ----------------------------------------------

/**
 * Contract for pipeline handlers.
 */
interface TelemetryHandler {
  setNext(next: TelemetryHandler): TelemetryHandler;
  handle(event: TelemetryEvent, state: AggregatedState): Promise<AggregatedState>;
}

/**
 * Boilerplate base handler.
 */
abstract class BaseHandler implements TelemetryHandler {
  private next?: TelemetryHandler;

  public setNext(next: TelemetryHandler): TelemetryHandler {
    this.next = next;
    return next;
  }

  public async handle(event: TelemetryEvent, state: AggregatedState): Promise<AggregatedState> {
    const updated = await this.process(event, state);
    if (this.next) {
      return this.next.handle(event, updated);
    }
    return updated;
  }

  protected abstract process(
    event: TelemetryEvent,
    state: AggregatedState,
  ): Promise<AggregatedState>;
}

/**
 * Handler: CPU & Memory aggregation.
 */
class ResourceAggregationHandler extends BaseHandler {
  protected async process(event: TelemetryEvent, state: AggregatedState): Promise<AggregatedState> {
    const { cpu, memory } = event.metrics;
    const { sampleSize } = state;

    const nextSize = sampleSize + 1;

    return {
      ...state,
      cpuAvg: (state.cpuAvg * sampleSize + cpu) / nextSize,
      memoryAvg: (state.memoryAvg * sampleSize + memory) / nextSize,
      sampleSize: nextSize,
    };
  }
}

/**
 * Handler: Latency tracking.
 */
class LatencyHandler extends BaseHandler {
  protected async process(event: TelemetryEvent, state: AggregatedState): Promise<AggregatedState> {
    return { ...state, latencyP99: Math.max(state.latencyP99, event.metrics.latencyMs) };
  }
}

/**
 * Handler: Social spike detection.
 */
class SocialPressureHandler extends BaseHandler {
  private static MAX_SOCIAL_RATE = 10_000; // arbitrary, domain specific

  protected async process(event: TelemetryEvent, state: AggregatedState): Promise<AggregatedState> {
    const { likeRate, commentRate, shareRate, influencerOnline } = event.social;
    const rawTotal = likeRate + commentRate + shareRate;

    const pressure = Math.min(
      rawTotal / SocialPressureHandler.MAX_SOCIAL_RATE,
      1,
    );

    // boost if influencer present
    const finalPressure = influencerOnline ? Math.min(1, pressure * 1.3) : pressure;

    return { ...state, socialPressureScore: Math.max(state.socialPressureScore, finalPressure) };
  }
}

// --- Strategy Pattern -------------------------------------------------------

/**
 * Input summarised snapshot for policy evaluation.
 */
interface PolicyInput extends AggregatedState {}

/**
 * Scaling policy contract.
 */
interface CapacityStrategy {
  evaluate(input: PolicyInput): ScalingCommand | null;
  readonly name: string;
}

/**
 * Conservative policy – only scales up if absolutely necessary.
 */
class ConservativeStrategy implements CapacityStrategy {
  public readonly name = 'conservative';

  evaluate(input: PolicyInput): ScalingCommand | null {
    if (input.cpuAvg > 90 || input.socialPressureScore > 0.9) {
      return {
        id: uuid(),
        directive: ScalingDirective.SCALE_UP,
        reason: `high utilisation (${input.cpuAvg.toFixed(2)}% CPU) or social spike`,
        value: Math.ceil(input.cpuAvg / 20), // minimal bump
        timestamp: Date.now(),
      };
    }

    if (input.cpuAvg < 30 && input.socialPressureScore < 0.2) {
      return {
        id: uuid(),
        directive: ScalingDirective.SCALE_DOWN,
        reason: 'sustained low utilisation',
        value: 1,
        timestamp: Date.now(),
      };
    }

    return null;
  }
}

/**
 * Aggressive policy – trades cost for latency guarantees.
 */
class AggressiveStrategy implements CapacityStrategy {
  public readonly name = 'aggressive';

  evaluate(input: PolicyInput): ScalingCommand | null {
    if (input.latencyP99 > 250 || input.cpuAvg > 70 || input.socialPressureScore > 0.6) {
      return {
        id: uuid(),
        directive: ScalingDirective.SCALE_UP,
        reason: 'latency / cpu / social threshold breached',
        value: Math.max(2, Math.ceil(input.cpuAvg / 15)),
        timestamp: Date.now(),
      };
    }

    if (input.cpuAvg < 25 && input.latencyP99 < 80 && input.socialPressureScore < 0.1) {
      return {
        id: uuid(),
        directive: ScalingDirective.SCALE_DOWN,
        reason: 'aggressive cost optimisation',
        value: 2,
        timestamp: Date.now(),
      };
    }

    return null;
  }
}

/**
 * Strategy context – selects policy based on runtime configuration.
 */
class StrategySelector {
  private readonly strategy: CapacityStrategy;

  constructor() {
    const policy = process.env.CAPACITY_POLICY ?? 'conservative';
    switch (policy) {
      case 'aggressive':
        this.strategy = new AggressiveStrategy();
        break;
      case 'conservative':
      default:
        this.strategy = new ConservativeStrategy();
    }
    log.info({ chosenPolicy: this.strategy.name }, 'Capacity policy initialised');
  }

  public decide(input: PolicyInput): ScalingCommand | null {
    return this.strategy.evaluate(input);
  }
}

// --- Event-Driven Orchestration ---------------------------------------------

/**
 * CapacityOrchestrationEngine – wires everything together.
 */
export class CapacityOrchestrationEngine {
  private readonly strategy = new StrategySelector();
  private readonly codec = JSONCodec();
  private nc?: NatsConnection;
  private sub?: Subscription;
  private state: AggregatedState = {
    cpuAvg: 0,
    memoryAvg: 0,
    latencyP99: 0,
    socialPressureScore: 0,
    sampleSize: 0,
  };

  // Build handler chain
  private readonly pipeline: TelemetryHandler;

  constructor(private subject = 'telemetry.enriched') {
    const cpuMem = new ResourceAggregationHandler();
    const latency = new LatencyHandler();
    const social = new SocialPressureHandler();

    cpuMem.setNext(latency).setNext(social);
    this.pipeline = cpuMem;
  }

  /**
   * Connect to NATS and begin streaming telemetry events.
   */
  public async start(): Promise<void> {
    try {
      this.nc = await connect({ servers: process.env.NATS_URL || 'nats://localhost:4222' });
      log.info('Connected to NATS', { servers: this.nc.getServer() });

      this.sub = this.nc.subscribe(this.subject);
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      for await (const msg of this.sub) {
        try {
          const event = this.codec.decode(msg.data) as TelemetryEvent;
          await this.processEvent(event);
        } catch (err) {
          log.warn({ err }, 'Failed to process telemetry message');
        }
      }
    } catch (err) {
      log.error({ err }, 'Could not initialise NATS consumer');
      throw err;
    }
  }

  /**
   * Graceful shutdown.
   */
  public async stop(): Promise<void> {
    try {
      await this.sub?.drain();
      await this.nc?.drain();
      log.info('CapacityOrchestrationEngine stopped');
    } catch (err) {
      log.error({ err }, 'Error during shutdown');
    }
  }

  /**
   * Execute pipeline & strategy, then publish scaling command if necessary.
   */
  private async processEvent(event: TelemetryEvent): Promise<void> {
    // Reset aggregation periodically (every 60 seconds)
    if (this.state.timestamp && Date.now() - (this.state as any).timestamp > 60_000) {
      this.flush();
    }

    this.state = await this.pipeline.handle(event, this.state);

    const decision = this.strategy.decide(this.state);
    if (decision) {
      await this.publishScalingCommand(decision);
      this.flush(); // start new window
    }
  }

  private flush(): void {
    this.state = {
      cpuAvg: 0,
      memoryAvg: 0,
      latencyP99: 0,
      socialPressureScore: 0,
      sampleSize: 0,
    } as AggregatedState & { timestamp?: number };
    (this.state as any).timestamp = Date.now();
  }

  /**
   * Emits the scaling command to downstream consumers.
   * In a real system we might push to Kafka; here we log & optionally publish.
   */
  private async publishScalingCommand(cmd: ScalingCommand): Promise<void> {
    log.info({ cmd }, 'ScalingCommand emitted');

    const scalingSubject = 'capacity.command';
    if (!this.nc) {
      log.error('NATS connection not initialised – cannot publish scaling command');
      return;
    }

    try {
      this.nc.publish(scalingSubject, this.codec.encode(cmd));
    } catch (err) {
      log.error({ err }, 'Failed to publish ScalingCommand');
    }
  }
}

// --- Entrypoint (when executed directly) ------------------------------------

/* istanbul ignore next */
(async () => {
  // Execute only if this file is launched as a standalone script.
  if (require.main === module) {
    const engine = new CapacityOrchestrationEngine(
      process.env.TELEMETRY_SUBJECT || 'telemetry.enriched',
    );

    process.once('SIGINT', () => engine.stop());
    process.once('SIGTERM', () => engine.stop());

    await engine.start();
  }
})();
```