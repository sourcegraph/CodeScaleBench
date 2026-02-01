```typescript
/**
 * PulseSphere SocialOps – Social-Aware Auto-Scaler (Module 12)
 * ------------------------------------------------------------
 * This module implements a social context–aware autoscaling engine that
 * listens to the unified telemetry stream (metrics + enriched social
 * signals) and decides whether to scale infrastructure nodes up/down.
 *
 * Patterns used:
 *   • Strategy Pattern        – Pluggable scaling strategies
 *   • Observer Pattern        – Reactive stream processing (RxJS)
 *   • Command Pattern         – Emits ScaleUp / ScaleDown commands to Kafka
 *
 * External deps:
 *   • rxjs       – Reactive streams
 *   • kafkajs    – Kafka producer for scale commands
 *
 * NOTE: In production this module runs inside its own micro-service
 * container (autoscaler-svc). Configuration is injected via env-vars and
 * ConfigService (not shown for brevity).
 */

import { Observable, Subscription } from 'rxjs';
import { bufferTime, filter, map } from 'rxjs/operators';
import { Kafka, Producer, logLevel } from 'kafkajs';

/* ------------------------------------------------------------------ *
 *                          Domain Types                               *
 * ------------------------------------------------------------------ */

/** Enumeration of available social signal kinds we enrich metrics with. */
export enum SocialSignal {
  LIKE = 'LIKE',
  COMMENT = 'COMMENT',
  SHARE = 'SHARE',
  LIVESTREAM_WATCH = 'LIVESTREAM_WATCH',
  FOLLOW = 'FOLLOW',
}

/** Raw telemetry payload arriving from the Observability-Ingest bus. */
export interface MetricsEvent {
  timestamp: number;                 // epoch ms
  cpuLoad: number;                   // 0-100
  memoryUtilization: number;         // 0-100
  rps: number;                       // requests per second
  activeUsers: number;               // currently connected users
  socialSignalCounts: Partial<Record<SocialSignal, number>>; // counts per 5s window
}

/** Command emitted to Autoscaling Command Bus (Kafka topic). */
export interface ScalingCommand {
  clusterId: string;
  decision: 'SCALE_UP' | 'SCALE_DOWN' | 'NOOP';
  reason: string;
  desiredReplicaChange: number;      // positive or negative
  timestamp: number;
}

/* ------------------------------------------------------------------ *
 *                     Strategy Pattern Contracts                      *
 * ------------------------------------------------------------------ */

/** Encapsulates algorithm that converts aggregated metrics into a scaling decision. */
export interface ScalingStrategy {
  readonly name: string;
  evaluate(window: AggregatedWindow): ScalingCommand;
}

/** Aggregated metrics for a time window (e.g., 1 min). */
export interface AggregatedWindow {
  // aggregated statistics
  avgCpu: number;
  avgMem: number;
  avgRps: number;
  totalSocialSignals: number;
  windowStart: number;
  windowEnd: number;
  clusterId: string;
}

/* ------------------------------------------------------------------ *
 *                Concrete Scaling Strategy Implementations            *
 * ------------------------------------------------------------------ */

/**
 * ReactionBurstScalingStrategy
 * ----------------------------
 * Scales up rapidly when we see a burst of reactions (likes, comments, shares)
 * coupled with sustained CPU/RPS usage. Scales down cautiously.
 */
export class ReactionBurstScalingStrategy implements ScalingStrategy {
  public readonly name = 'ReactionBurstScalingStrategy';

  private readonly upscaleCpuThreshold = 70;
  private readonly upscaleRpsThreshold = 10_000;
  private readonly socialBurstThreshold = 5_000;
  private readonly maxStep = 10;

  private readonly downscaleCpuThreshold = 30;
  private readonly downscaleRpsThreshold = 3_000;
  private readonly holdOffWindows = 3; // wait windows before downscaling
  private downscaleCounter: Record<string, number> = {};

  evaluate(window: AggregatedWindow): ScalingCommand {
    const {
      avgCpu,
      avgRps,
      totalSocialSignals,
      clusterId,
      windowEnd,
    } = window;

    // Upscale logic
    if (
      avgCpu > this.upscaleCpuThreshold &&
      avgRps > this.upscaleRpsThreshold &&
      totalSocialSignals > this.socialBurstThreshold
    ) {
      const replicas = Math.min(
        Math.ceil(totalSocialSignals / this.socialBurstThreshold),
        this.maxStep,
      );
      this.downscaleCounter[clusterId] = 0; // reset
      return {
        clusterId,
        decision: 'SCALE_UP',
        desiredReplicaChange: replicas,
        reason: `Burst detected: social=${totalSocialSignals}, cpu=${avgCpu.toFixed(
          1,
        )}%, rps=${avgRps}`,
        timestamp: windowEnd,
      };
    }

    // Downscale logic with hold-off to avoid flapping
    if (
      avgCpu < this.downscaleCpuThreshold &&
      avgRps < this.downscaleRpsThreshold
    ) {
      const count = (this.downscaleCounter[clusterId] || 0) + 1;
      this.downscaleCounter[clusterId] = count;

      if (count >= this.holdOffWindows) {
        this.downscaleCounter[clusterId] = 0;
        return {
          clusterId,
          decision: 'SCALE_DOWN',
          desiredReplicaChange: -1,
          reason: `Sustained low load: cpu=${avgCpu.toFixed(
            1,
          )}%, rps=${avgRps}`,
          timestamp: windowEnd,
        };
      }
    } else {
      // reset counter if load picks back up
      this.downscaleCounter[clusterId] = 0;
    }

    return {
      clusterId,
      decision: 'NOOP',
      desiredReplicaChange: 0,
      reason: 'No scaling required',
      timestamp: windowEnd,
    };
  }
}

/**
 * LivestreamSpikeScalingStrategy
 * ------------------------------
 * Aggressively scales for livestream spikes: if watch events sky-rocket,
 * we pre-emptively add capacity ignoring CPU (users mostly watch, produce I/O).
 */
export class LivestreamSpikeScalingStrategy implements ScalingStrategy {
  public readonly name = 'LivestreamSpikeScalingStrategy';

  private liveSpikeThreshold = 20_000;
  private scaleStep = 15;

  evaluate(window: AggregatedWindow): ScalingCommand {
    const { totalSocialSignals, clusterId, windowEnd } = window;
    if (totalSocialSignals > this.liveSpikeThreshold) {
      return {
        clusterId,
        decision: 'SCALE_UP',
        desiredReplicaChange: this.scaleStep,
        reason: `Livestream spike detected (${totalSocialSignals} watches)`,
        timestamp: windowEnd,
      };
    }

    return {
      clusterId,
      decision: 'NOOP',
      desiredReplicaChange: 0,
      reason: 'No livestream spike',
      timestamp: windowEnd,
    };
  }
}

/* ------------------------------------------------------------------ *
 *                    Strategy Selector / Orchestrator                 *
 * ------------------------------------------------------------------ */

/**
 * Selects appropriate strategy based on cluster profile & telemetry.
 * In production this could consult ConfigService, FeatureFlags, etc.
 */
class StrategySelector {
  private readonly strategies: ScalingStrategy[];

  constructor(strategies: ScalingStrategy[]) {
    this.strategies = strategies;
  }

  /**
   * Chooses the first strategy whose evaluate() returns non-NOOP.
   * Falls back to last strategy (should be default guard).
   */
  selectCommand(window: AggregatedWindow): ScalingCommand {
    for (const strat of this.strategies) {
      const cmd = strat.evaluate(window);
      if (cmd.decision !== 'NOOP') {
        return cmd;
      }
    }
    // If everybody said NOOP, return the final NOOP
    return this.strategies[this.strategies.length - 1].evaluate(window);
  }
}

/* ------------------------------------------------------------------ *
 *                       Kafka Producer Wrapper                        *
 * ------------------------------------------------------------------ */

/** Wrapper to produce scaling commands to Kafka topic. */
class CommandBusProducer {
  private producer: Producer;
  private readonly topic: string;

  constructor(brokers: string[], topic: string) {
    const kafka = new Kafka({
      clientId: 'autoscaler-producer',
      brokers,
      logLevel: logLevel.ERROR,
    });
    this.producer = kafka.producer({ allowAutoTopicCreation: false });
    this.topic = topic;
  }

  async connect(): Promise<void> {
    await this.producer.connect();
  }

  async send(command: ScalingCommand): Promise<void> {
    try {
      await this.producer.send({
        topic: this.topic,
        messages: [
          {
            key: command.clusterId,
            value: JSON.stringify(command),
          },
        ],
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(
        '[CommandBusProducer] Failed to send scaling command',
        err,
      );
    }
  }

  async disconnect(): Promise<void> {
    await this.producer.disconnect();
  }
}

/* ------------------------------------------------------------------ *
 *                         Autoscaler Engine                           *
 * ------------------------------------------------------------------ */

interface AutoscalerConfig {
  clusterId: string;
  brokers: string[];
  commandTopic: string;
  evaluationWindowMs: number; // e.g., 60_000
}

/**
 * Consumes MetricsEvent observable, aggregates them in tumbling windows,
 * invokes strategy selector, emits ScalingCommand to Kafka.
 */
export class SocialAwareAutoscaler {
  private readonly metrics$: Observable<MetricsEvent>;
  private readonly cfg: AutoscalerConfig;
  private readonly selector: StrategySelector;
  private readonly producer: CommandBusProducer;
  private subscription?: Subscription;

  constructor(
    metrics$: Observable<MetricsEvent>,
    cfg: AutoscalerConfig,
    strategies: ScalingStrategy[] = [
      new ReactionBurstScalingStrategy(),
      new LivestreamSpikeScalingStrategy(),
    ],
  ) {
    this.metrics$ = metrics$;
    this.cfg = cfg;
    this.selector = new StrategySelector(strategies);
    this.producer = new CommandBusProducer(cfg.brokers, cfg.commandTopic);
  }

  async start(): Promise<void> {
    await this.producer.connect();

    this.subscription = this.metrics$
      .pipe(
        filter((e) => e && e.clusterId === undefined ? true : e.clusterId === this.cfg.clusterId),
        bufferTime(this.cfg.evaluationWindowMs),
        filter((window) => window.length > 0),
        map((window) => this.aggregateWindow(window)),
      )
      .subscribe({
        next: async (aggWin) => {
          const cmd = this.selector.selectCommand(aggWin);
          if (cmd.decision !== 'NOOP') {
            await this.producer.send(cmd);
          }
        },
        error: (err) => {
          // eslint-disable-next-line no-console
          console.error('[SocialAwareAutoscaler] stream error', err);
        },
      });
  }

  async stop(): Promise<void> {
    await this.subscription?.unsubscribe();
    await this.producer.disconnect();
  }

  /* ------------------------ helpers ------------------------ */

  /** Collapse array of MetricsEvent into AggregatedWindow stats. */
  private aggregateWindow(events: MetricsEvent[]): AggregatedWindow {
    const totalCpu = events.reduce((acc, e) => acc + e.cpuLoad, 0);
    const totalMem = events.reduce((acc, e) => acc + e.memoryUtilization, 0);
    const totalRps = events.reduce((acc, e) => acc + e.rps, 0);

    const totalSocialSignals = events.reduce((acc, e) => {
      const sum = Object.values(e.socialSignalCounts || {}).reduce(
        (s, v) => s + (v ?? 0),
        0,
      );
      return acc + sum;
    }, 0);

    const windowStart = events[0].timestamp;
    const windowEnd = events[events.length - 1].timestamp;
    const len = events.length;

    return {
      avgCpu: totalCpu / len,
      avgMem: totalMem / len,
      avgRps: totalRps / len,
      totalSocialSignals,
      windowStart,
      windowEnd,
      clusterId: this.cfg.clusterId,
    };
  }
}

/* ------------------------------------------------------------------ *
 *                Example bootstrap (would live elsewhere)             *
 * ------------------------------------------------------------------ */

// The boot logic below is provided for reference / local testing.
// In the actual microservice this lives in index.ts and pulls a real
// RxJS observable fed by Kafka consumer.

/*
import { fromEventPattern } from 'rxjs';
import { Kafka } from 'kafkajs';

async function createMetricsObservable(topic: string, brokers: string[]) {
  const kafka = new Kafka({ clientId: 'metrics-consumer', brokers });
  const consumer = kafka.consumer({ groupId: 'autoscaler-group' });

  await consumer.connect();
  await consumer.subscribe({ topic, fromBeginning: false });

  return fromEventPattern<MetricsEvent>(
    (handler) => {
      consumer.run({
        eachMessage: async ({ message }) => {
          if (message.value) {
            const evt = JSON.parse(message.value.toString()) as MetricsEvent;
            handler(evt);
          }
        },
      });
    },
    async () => {
      await consumer.disconnect();
    },
  );
}

(async () => {
  const brokers = process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'];
  const cfg: AutoscalerConfig = {
    clusterId: 'social-cluster-17',
    brokers,
    commandTopic: 'autoscaler.commands',
    evaluationWindowMs: 60_000,
  };

  const metrics$ = await createMetricsObservable(
    'telemetry.metrics',
    brokers,
  );

  const autoscaler = new SocialAwareAutoscaler(metrics$, cfg);
  await autoscaler.start();

  process.on('SIGINT', async () => {
    await autoscaler.stop();
    process.exit(0);
  });
})();
*/

export default SocialAwareAutoscaler;
```