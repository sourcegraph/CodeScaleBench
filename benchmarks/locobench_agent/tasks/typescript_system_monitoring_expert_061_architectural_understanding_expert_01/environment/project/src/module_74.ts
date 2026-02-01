```typescript
/**************************************************************************************************
 *  File: module_74.ts
 *  Project: PulseSphere SocialOps – system_monitoring
 *
 *  Description:
 *  ------------
 *  “TelemetryEnricher” is a high-throughput component responsible for stitching together real-time
 *  infrastructure metrics with the surrounding social context (likes, comments, shares,
 *  live-stream spikes, etc.).  By default, raw metrics emitted by low-level agents arrive without
 *  any correlation to user-facing behaviour; this class listens to both streams, buffers social
 *  signals for a configurable sliding-window and applies an enrichment strategy before relaying
 *  the composite event onto the platform Event-Bus (Kafka / NATS).
 *
 *  Architectural patterns showcased
 *  --------------------------------
 *   • Strategy Pattern – interchangeable enrichment algorithms
 *   • Observer Pattern – EventEmitter-based pub/sub
 *   • Chain of Responsibility (light) – runtime validation pipeline
 *
 *  Author: PulseSphere Engineering
 **************************************************************************************************/

/* --------------------------------- 3rd-party imports ----------------------------------------- */
import { EventEmitter } from 'node:events';
import { setInterval, clearInterval } from 'node:timers';
import { v4 as uuid } from 'uuid';
import Ajv, { JSONSchemaType, ValidateFunction } from 'ajv';
import winston from 'winston';

/* ------------------------------------ Domain Types ------------------------------------------- */

/**
 * Fine-grained social interaction arriving from upstream engagement micro-services.
 */
export interface SocialSignal {
  timestamp: number; // epoch-ms
  signalType: 'like' | 'comment' | 'share' | 'livestream_spike';
  magnitude: number; // e.g. burst size for shares
  userId?: string;   // may be omitted for anonymous activity
}

/**
 * Raw infrastructure metric emitted by node-level collectors.
 */
export interface InfrastructureMetric {
  timestamp: number;            // epoch-ms
  metric: string;               // e.g. cpu_utilisation
  value: number;
  tags?: Record<string, string>; // open-ended tag set
}

/**
 * Aggregate view used by our observability lake.
 */
export interface TelemetryEvent {
  id: string;
  timestamp: number;
  description: string;
  data: {
    metric: InfrastructureMetric;
    socialContext: SocialSignalSummary;
  };
}

/**
 * Rolling window count of signals – pre-computed to keep payload small.
 */
export interface SocialSignalSummary {
  likes: number;
  comments: number;
  shares: number;
  livestreamSpikes: number;
}

/* -------------------------------- Strategy Abstractions -------------------------------------- */

/**
 * Contract every enrichment strategy must satisfy.
 */
export interface EnrichmentStrategy {
  readonly name: string;
  enrich(
    metric: InfrastructureMetric,
    socialSignals: ReadonlyArray<SocialSignal>
  ): TelemetryEvent;
}

/**
 * Registry helper – supports dynamic wiring through configuration / DI container.
 */
export class StrategyRegistry {
  private readonly strategies = new Map<string, EnrichmentStrategy>();

  register(strategy: EnrichmentStrategy): void {
    if (this.strategies.has(strategy.name)) {
      throw new Error(`Strategy "${strategy.name}" already registered`);
    }
    this.strategies.set(strategy.name, strategy);
  }

  get(name: string): EnrichmentStrategy {
    const strategy = this.strategies.get(name);
    if (!strategy) {
      throw new Error(`Strategy "${name}" is not registered`);
    }
    return strategy;
  }
}

/* ----------------------------- Concrete Strategy Implementations ----------------------------- */

/**
 * Very fast, coarse-grained: sums signals inside the window and attaches
 * them verbatim without touching metric value.
 */
export class SimpleMergeStrategy implements EnrichmentStrategy {
  readonly name = 'simple_merge';

  enrich(
    metric: InfrastructureMetric,
    socialSignals: ReadonlyArray<SocialSignal>
  ): TelemetryEvent {
    const summary = aggregateSignals(socialSignals);
    return buildTelemetryEvent(metric, summary, this.name);
  }
}

/**
 * Gives a weighted boost to metric.value if social engagement is high.
 * (Illustrative logic.)
 */
export class WeightedMergeStrategy implements EnrichmentStrategy {
  readonly name = 'weighted_merge';

  enrich(
    metric: InfrastructureMetric,
    socialSignals: ReadonlyArray<SocialSignal>
  ): TelemetryEvent {
    const summary = aggregateSignals(socialSignals);
    const intensity =
      summary.likes * 0.1 +
      summary.comments * 0.2 +
      summary.shares * 0.3 +
      summary.livestreamSpikes * 0.4;

    const boostedMetric: InfrastructureMetric = {
      ...metric,
      value: metric.value * (1 + intensity / 1000),
      tags: {
        ...(metric.tags ?? {}),
        boosted: 'true',
      },
    };

    return buildTelemetryEvent(boostedMetric, summary, this.name);
  }
}

/* ---------------------------------- Telemetry Enricher --------------------------------------- */

export interface TelemetryEnricherOptions {
  bufferWindowMs?: number;     // sliding-window to retain social signals
  flushCycleMs?: number;       // housekeeping cadence
  strategyName?: string;       // selected strategy from registry
  logger?: winston.Logger;     // allow caller-provided logger
}

/**
 * Bridges two disparate streams – infra metrics & social signals – into a unified event.
 * Emits 'telemetry' events downstream (Kafka producer is wired by external adapter).
 */
export class TelemetryEnricher extends EventEmitter {
  /* ----------------------------- immutable collaborators ------------------------------ */
  private readonly strategy: EnrichmentStrategy;
  private readonly logger: winston.Logger;
  private readonly validateSignal: ValidateFunction<SocialSignal>;
  private readonly validateMetric: ValidateFunction<InfrastructureMetric>;

  /* ----------------------------- runtime mutables ------------------------------------- */
  private signalBuffer: SocialSignal[] = [];
  private readonly windowMs: number;
  private readonly housekeepingInterval: NodeJS.Timeout;

  constructor(
    registry: StrategyRegistry,
    opts: TelemetryEnricherOptions = {},
  ) {
    super();

    /* ---- strategy selection ---- */
    const strategyName = opts.strategyName ?? 'simple_merge';
    this.strategy = registry.get(strategyName);

    /* ---- config defaults ---- */
    this.windowMs = opts.bufferWindowMs ?? 5_000;

    /* ---- logger ---- */
    this.logger =
      opts.logger ??
      winston.createLogger({
        level: 'info',
        transports: [new winston.transports.Console()],
        format: winston.format.json(),
      });

    /* ---- validators ---- */
    const ajv = new Ajv({ useDefaults: true, strict: false });
    this.validateSignal = ajv.compile<SocialSignal>(socialSignalSchema);
    this.validateMetric = ajv.compile<InfrastructureMetric>(
      infrastructureMetricSchema,
    );

    /* ---- start housekeeping ---- */
    const flushCycle = opts.flushCycleMs ?? 3_000;
    this.housekeepingInterval = setInterval(
      () => this.pruneOldSignals(),
      flushCycle,
    );
  }

  /**************************** Public API – ingestion ******************************************/

  ingestSocialSignal(signal: SocialSignal): void {
    if (!this.validateSignal(signal)) {
      this.logger.warn('Dropping invalid SocialSignal', {
        errors: this.validateSignal.errors,
        signal,
      });
      return;
    }
    this.signalBuffer.push(signal);
  }

  ingestInfrastructureMetric(metric: InfrastructureMetric): void {
    if (!this.validateMetric(metric)) {
      this.logger.warn('Dropping invalid InfrastructureMetric', {
        errors: this.validateMetric.errors,
        metric,
      });
      return;
    }

    const now = Date.now();
    const relevantSignals = this.signalBuffer.filter(
      (s) => now - s.timestamp <= this.windowMs,
    );

    const enriched = this.strategy.enrich(metric, relevantSignals);

    try {
      this.emit('telemetry', enriched);
    } catch (err) {
      this.logger.error('Failed to emit telemetry event', { err });
    }
  }

  /**************************** Lifecycle *******************************************************/

  shutdown(): void {
    clearInterval(this.housekeepingInterval);
    this.removeAllListeners('telemetry');
    this.logger.info('TelemetryEnricher shutdown complete');
  }

  /**************************** Private helpers ***********************************************/

  /**
   * Keeps memory footprint bounded by sliding-window.
   */
  private pruneOldSignals(): void {
    const cutoff = Date.now() - this.windowMs;
    const before = this.signalBuffer.length;
    this.signalBuffer = this.signalBuffer.filter((s) => s.timestamp >= cutoff);
    const after = this.signalBuffer.length;

    if (before !== after) {
      this.logger.debug('Pruned stale SocialSignals', { before, after });
    }
  }
}

/* --------------------------------- Utility Functions ---------------------------------------- */

function aggregateSignals(signals: ReadonlyArray<SocialSignal>): SocialSignalSummary {
  return signals.reduce<SocialSignalSummary>(
    (acc, s) => {
      switch (s.signalType) {
        case 'like':
          acc.likes += s.magnitude;
          break;
        case 'comment':
          acc.comments += s.magnitude;
          break;
        case 'share':
          acc.shares += s.magnitude;
          break;
        case 'livestream_spike':
          acc.livestreamSpikes += s.magnitude;
          break;
      }
      return acc;
    },
    { likes: 0, comments: 0, shares: 0, livestreamSpikes: 0 },
  );
}

function buildTelemetryEvent(
  metric: InfrastructureMetric,
  socialSummary: SocialSignalSummary,
  originStrategy: string,
): TelemetryEvent {
  return {
    id: uuid(),
    timestamp: Date.now(),
    description: `Metric "${metric.metric}" enriched via "${originStrategy}"`,
    data: {
      metric,
      socialContext: socialSummary,
    },
  };
}

/* -------------------------------- AJV JSON Schemas ------------------------------------------ */

const socialSignalSchema: JSONSchemaType<SocialSignal> = {
  type: 'object',
  properties: {
    timestamp: { type: 'integer' },
    signalType: {
      type: 'string',
      enum: ['like', 'comment', 'share', 'livestream_spike'],
    },
    magnitude: { type: 'number', minimum: 0 },
    userId: { type: 'string', nullable: true },
  },
  required: ['timestamp', 'signalType', 'magnitude'],
  additionalProperties: false,
};

const infrastructureMetricSchema: JSONSchemaType<InfrastructureMetric> = {
  type: 'object',
  properties: {
    timestamp: { type: 'integer' },
    metric: { type: 'string' },
    value: { type: 'number' },
    tags: {
      type: 'object',
      propertyNames: { type: 'string' },
      additionalProperties: { type: 'string' },
      nullable: true,
    },
  },
  required: ['timestamp', 'metric', 'value'],
  additionalProperties: false,
};

/* ---------------------------------- Module Bootstrap ----------------------------------------
 * The below is **optional** – it self-registers default strategies when this module is imported.
 * Apps can import {StrategyRegistry} themselves and override.
 * ------------------------------------------------------------------------------------------- */

export const defaultRegistry = new StrategyRegistry();
defaultRegistry.register(new SimpleMergeStrategy());
defaultRegistry.register(new WeightedMergeStrategy());
```