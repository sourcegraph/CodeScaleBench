```typescript
/**
 * File: src/module_35.ts
 * Module: SocialSignalCorrelator
 *
 * Purpose:
 *   Consumes real-time user-interaction signals (likes, comments, shares, live-stream spikes) from
 *   Apache Kafka, correlates them with infrastructure metrics pushed by sibling modules, detects
 *   viral surges and publishes capacity-orchestration commands to NATS.
 *
 *   Implements:
 *     • Observer Pattern       – Exposes `onMetric` to let other modules push infra-metrics.
 *     • Strategy Pattern       – Allows pluggable surge-detection strategies (simple, percentile, ML).
 *     • Command Pattern        – Encapsulates scaling instructions as serialisable Command objects.
 *     • Reactive Programming   – RxJS streams for back-pressure, windowing & composition.
 *
 *   NOTE: This file purposefully references domain types (`InfraMetric`, `ScalingCommand`, ...)
 *   that live in other packages of the PulseSphere monorepo. Only the most relevant subset is
 *   re-declared here to keep the file self-contained.
 */

import { Kafka, Consumer, EachMessagePayload, logLevel as KafkaLogLevel } from 'kafkajs';
import { connect, NatsConnection, StringCodec } from 'nats';
import { Subject, Observable, fromEventPattern, merge, timer } from 'rxjs';
import {
  bufferTime,
  filter,
  map,
  tap,
  withLatestFrom,
  shareReplay,
  debounceTime,
} from 'rxjs/operators';
import pino, { Logger } from 'pino';
import { v4 as uuidv4 } from 'uuid';

//#region ‑-– Domain Types ------------------------------------------------------------------------

/** Minimal representation of infrastructure metrics */
export interface InfraMetric {
  readonly serviceName: string;
  readonly cpu: number; // 0-100 %
  readonly memory: number; // 0-100 %
  readonly timestamp: number; // epoch millis
}

/** User-interaction event emitted by the social graph */
export interface SocialInteraction {
  readonly userId: string;
  readonly type: 'LIKE' | 'COMMENT' | 'SHARE' | 'STREAM_VIEW';
  readonly payloadId: string; // post / stream / story id
  readonly timestamp: number; // epoch millis
}

/** Scaling targets recognised by the orchestrator */
export type ScalingTarget = 'EDGE_CACHE' | 'TIMELINE_API' | 'LIVE_STREAM_API';

/** Command delivered downstream to capacity-orchestrator */
export interface ScalingCommand {
  readonly commandId: string;
  readonly issuedAt: number;
  readonly target: ScalingTarget;
  readonly desiredReplicas: number;
  readonly reason: string;
}

//#endregion

//#region ‑-– Strategy Interfaces -----------------------------------------------------------------

/**
 * SurgeDetectionStrategy separates spike-detection from stream handling.
 * Implementations MUST be pure functions to keep them testable & hot-swappable.
 */
export interface SurgeDetectionStrategy {
  detectSpike(eventsWindow: ReadonlyArray<SocialInteraction>): boolean;
}

/**
 * A naïve surge-detection strategy: produces a spike if the window length
 * exceeds the static threshold.
 */
export class ThresholdStrategy implements SurgeDetectionStrategy {
  constructor(private readonly threshold: number) {}

  detectSpike(eventsWindow: ReadonlyArray<SocialInteraction>): boolean {
    return eventsWindow.length >= this.threshold;
  }
}

//#endregion

//#region ‑-– Config -----------------------------------------------------------------------------

export interface SocialSignalCorrelatorConfig {
  kafkaBrokers: string[];
  kafkaGroupId: string;
  kafkaTopic: string;

  natsUrl: string; // ex: nats://nats.svc.cluster.local:4222
  natsSubject: string;

  // Windowing
  signalWindowMs: number; // e.g. 10_000 ms
  signalBufferEmitMs: number; // e.g. 2_000 ms

  // Spike detection
  detectionStrategy?: SurgeDetectionStrategy;

  // Correlation
  cpuThreshold: number; // e.g. 70 %
  memoryThreshold: number; // e.g. 80 %

  // Scaling
  replicaMultiple: number; // scale to currentReplicas * replicaMultiple

  logger?: Logger;
}

//#endregion

//#region ‑-– Main Class --------------------------------------------------------------------------

export class SocialSignalCorrelator {
  /* Public Observers -------------------------------------------------------------------------- */
  /**
   * Allows sibling modules (MetricsCollectorService, etc.) to push infra metrics.
   * Returns false if the metric was discarded (service not tracked).
   */
  public onMetric(metric: InfraMetric): boolean {
    if (!metric.serviceName) return false;
    this.infraMetricSubject.next(metric);
    return true;
  }

  /* Life-cycle --------------------------------------------------------------------------------- */
  constructor(private readonly cfg: SocialSignalCorrelatorConfig) {
    if (!cfg.detectionStrategy) {
      cfg.detectionStrategy = new ThresholdStrategy(5);
    }
    this.logger = cfg.logger ?? pino({ name: 'SocialSignalCorrelator' });
  }

  async start(): Promise<void> {
    await Promise.all([this.initKafka(), this.initNats()]);
    this.logger.info('SocialSignalCorrelator initialised successfully');
    this.bootstrapStreams();
  }

  async stop(): Promise<void> {
    await Promise.all([this.kafkaConsumer?.disconnect(), this.nats?.drain()]);
    this.signalSubject.complete();
    this.infraMetricSubject.complete();
    this.logger.info('SocialSignalCorrelator shut down gracefully');
  }

  /* Implementation Details --------------------------------------------------------------------- */

  private kafkaConsumer!: Consumer;
  private nats!: NatsConnection;
  private readonly signalSubject = new Subject<SocialInteraction>();
  private readonly infraMetricSubject = new Subject<InfraMetric>();
  private readonly logger: Logger;

  /** Connects to Apache Kafka and starts consuming the social signal topic. */
  private async initKafka(): Promise<void> {
    const kafka = new Kafka({
      brokers: this.cfg.kafkaBrokers,
      logLevel: KafkaLogLevel.ERROR,
      clientId: 'social-signal-correlator',
    });

    this.kafkaConsumer = kafka.consumer({ groupId: this.cfg.kafkaGroupId });
    await this.kafkaConsumer.connect();
    await this.kafkaConsumer.subscribe({ topic: this.cfg.kafkaTopic, fromBeginning: false });

    await this.kafkaConsumer.run({
      eachMessage: async (payload: EachMessagePayload) => {
        try {
          const raw = payload.message.value?.toString();
          if (!raw) return;

          const event: SocialInteraction = JSON.parse(raw);
          this.signalSubject.next(event);
        } catch (err) {
          this.logger.warn({ err }, 'Failed to deserialize SocialInteraction event');
        }
      },
    });

    this.logger.info(
      { topic: this.cfg.kafkaTopic, groupId: this.cfg.kafkaGroupId },
      'Kafka consumption started',
    );
  }

  /** Connects to NATS to publish scaling commands. */
  private async initNats(): Promise<void> {
    this.nats = await connect({ servers: this.cfg.natsUrl });
    this.logger.info({ url: this.cfg.natsUrl }, 'Connected to NATS');
  }

  /**
   * Central reactive pipelines: buffers social events, detects spikes, correlates with metrics
   * and emits scaling commands if necessary.
   */
  private bootstrapStreams(): void {
    const socialBuffer$ = this.signalSubject.pipe(
      bufferTime(this.cfg.signalWindowMs, undefined, Number.POSITIVE_INFINITY),
      tap((buf) =>
        this.logger.debug(`Buffered ${buf.length} interactions in last ${this.cfg.signalWindowMs}ms`),
      ),
      shareReplay(1), // keep last window for late subscribers
    );

    const latestMetrics$ = this.infraMetricSubject.pipe(
      debounceTime(500),
      shareReplay(1),
    );

    /* Merge social + infra pipelines and compute scaling decisions */
    merge(socialBuffer$)
      .pipe(
        filter((buf) => buf.length > 0),
        filter((buf) => this.cfg.detectionStrategy!.detectSpike(buf)),
        withLatestFrom(latestMetrics$),
        map(([spikeEvents, metric]) =>
          this.buildScalingCommand(spikeEvents, metric).filter(Boolean) as ScalingCommand[],
        ),
        filter((cmds) => cmds.length > 0),
      )
      .subscribe({
        next: (cmds) => this.publishScalingCommands(cmds),
        error: (err) => this.logger.error({ err }, 'Stream processing failed'),
      });

    /* Emit heartbeat logs to indicate liveness */
    timer(0, 60_000).subscribe(() => this.logger.info('SocialSignalCorrelator is healthy'));
  }

  private buildScalingCommand(
    spikeEvents: SocialInteraction[],
    metric: InfraMetric,
  ): Array<ScalingCommand | null> {
    /* Basic correlation rules – can be extracted to its own Strategy later */
    const highCpu = metric.cpu >= this.cfg.cpuThreshold;
    const highMem = metric.memory >= this.cfg.memoryThreshold;

    if (!highCpu && !highMem) return [null];

    const uniquePayloads = new Set(spikeEvents.map((e) => e.payloadId));
    const reason = `Detected viral surge (${spikeEvents.length} interactions, ${uniquePayloads.size} unique payloads) + high resource usage (CPU ${metric.cpu}%, MEM ${metric.memory}%)`;

    const desiredReplicas = Math.ceil(metric.cpu / 100 * this.cfg.replicaMultiple) + 1; // simplistic formula

    const cmd: ScalingCommand = {
      commandId: uuidv4(),
      issuedAt: Date.now(),
      target: this.mapServiceToTarget(metric.serviceName),
      desiredReplicas,
      reason,
    };

    return [cmd];
  }

  private mapServiceToTarget(serviceName: string): ScalingTarget {
    if (serviceName.includes('edge-cache')) return 'EDGE_CACHE';
    if (serviceName.includes('live-stream')) return 'LIVE_STREAM_API';
    return 'TIMELINE_API';
  }

  private async publishScalingCommands(cmds: ScalingCommand[]): Promise<void> {
    const sc = StringCodec();
    for (const cmd of cmds) {
      try {
        await this.nats.publish(this.cfg.natsSubject, sc.encode(JSON.stringify(cmd)));
        this.logger.info({ cmd }, 'Published scaling command');
      } catch (err) {
        this.logger.error({ err, cmd }, 'Failed to publish scaling command');
      }
    }
  }
}

//#endregion

//#region ‑-– Factory Helper ---------------------------------------------------------------------

/**
 * Convenient bootstrapper used by the DI container (e.g. Awilix).
 * Keeping setup logic here makes tests simpler.
 */
export async function createAndStartCorrelator(
  partial: Partial<SocialSignalCorrelatorConfig>,
): Promise<SocialSignalCorrelator> {
  const cfg: SocialSignalCorrelatorConfig = {
    kafkaBrokers: ['kafka:9092'],
    kafkaGroupId: 'pulse-sphere-signal-correlator',
    kafkaTopic: 'social.interaction.signals',

    natsUrl: 'nats://nats:4222',
    natsSubject: 'capacity.scaling.command',

    signalWindowMs: 10_000,
    signalBufferEmitMs: 2_000,

    cpuThreshold: 70,
    memoryThreshold: 80,

    replicaMultiple: 2,

    ...partial,
  };

  const service = new SocialSignalCorrelator(cfg);
  await service.start();
  return service;
}

//#endregion
```