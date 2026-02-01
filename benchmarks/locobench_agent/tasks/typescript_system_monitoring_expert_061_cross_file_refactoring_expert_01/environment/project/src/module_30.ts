```typescript
/***************************************************************************************************
 *  File:        src/module_30.ts
 *  Project:     PulseSphere SocialOps – system_monitoring
 *  Description: Metric-to-Social-Signal enrichment module.
 *
 *  This unit demonstrates several architectural patterns used throughout the code-base:
 *    • Strategy Pattern        – Pluggable strategies for fetching social signals
 *    • Chain of Responsibility – Multi-step metric enrichment pipeline
 *    • Observer Pattern        – Publish enriched metrics to interested downstream components
 *    • Command Pattern         – Encapsulate enrichment execution for scheduler / worker pools
 *
 *  NOTE: External project-specific dependencies (e.g. KafkaProducer, ConfigService) are assumed to
 *        exist elsewhere in the monorepo. Import paths are kept relative to convey intent.
 ***************************************************************************************************/

import EventEmitter from 'events';
import { randomUUID } from 'crypto';
import pino from 'pino';

import { Metric, EnrichedMetric, SocialSignal } from './types/metrics';
import { ConfigService } from './core/config';
import { KafkaProducer } from './infrastructure/messaging/kafkaProducer';
import { RedisClientType } from './infrastructure/cache/redisTypes';

/* -------------------------------------------------------------------------------------------------
 * Logger
 * -----------------------------------------------------------------------------------------------*/
const logger = pino({
  name: 'metric-social-enrichment',
  level: process.env.LOG_LEVEL ?? 'info',
});

/* -------------------------------------------------------------------------------------------------
 * Strategy Pattern – Social Signal Providers
 * -----------------------------------------------------------------------------------------------*/

/** Context object passed to strategies (kept intentionally minimal). */
export interface MetricContext {
  metric: Metric;
  correlationId: string;
}

/** Contract for all social-signal retrieval strategies. */
export interface SocialSignalStrategy {
  /**
   * Fetch social signals related to the supplied metric.
   * Implementations MUST be side-effect free and idempotent.
   */
  fetchSignals(ctx: MetricContext): Promise<SocialSignal | null>;
}

/* ----- Strategy #1: Redis Cache ----------------------------------------------------------------*/
class RedisSignalStrategy implements SocialSignalStrategy {
  constructor(private readonly redis: RedisClientType) {}

  async fetchSignals(ctx: MetricContext): Promise<SocialSignal | null> {
    const cacheKey = `social-signal:${ctx.metric.entityId}`;
    try {
      const raw = await this.redis.get(cacheKey);
      if (!raw) return null;

      logger.debug({ cacheKey, correlationId: ctx.correlationId }, 'Social signal retrieved from cache');
      return JSON.parse(raw) as SocialSignal;
    } catch (err) {
      logger.warn({ err, cacheKey }, 'Failed to fetch social signal from Redis');
      return null;
    }
  }
}

/* ----- Strategy #2: Live API -------------------------------------------------------------------*/
class LiveApiSignalStrategy implements SocialSignalStrategy {
  /**
   * A lightweight HTTP client is injected (axios-like interface).
   * Provided by platform DI container / service mesh sidecar.
   */
  constructor(private readonly http: { get<T>(url: string): Promise<{ data: T }> }) {}

  async fetchSignals(ctx: MetricContext): Promise<SocialSignal | null> {
    const endpoint = `/signals/${ctx.metric.entityType}/${ctx.metric.entityId}`;
    try {
      const { data } = await this.http.get<SocialSignal>(endpoint);
      logger.debug({ endpoint, correlationId: ctx.correlationId }, 'Social signal retrieved from live API');
      return data;
    } catch (err) {
      logger.error({ err, endpoint }, 'Failed to fetch social signal via Live API');
      return null;
    }
  }
}

/* ----- Strategy Selector / Factory -------------------------------------------------------------*/
class SocialSignalStrategyFactory {
  static build(config: ConfigService, deps: { redis?: RedisClientType; http?: any }): SocialSignalStrategy {
    const source = config.get<string>('signals.source', 'cache-first');

    if (source === 'live-only') {
      return new LiveApiSignalStrategy(deps.http);
    }

    if (source === 'cache-only') {
      return new RedisSignalStrategy(deps.redis!);
    }

    // Default strategy: try cache, then live API if needed.
    return new (class CompositeStrategy implements SocialSignalStrategy {
      private readonly cache = new RedisSignalStrategy(deps.redis!);
      private readonly live = new LiveApiSignalStrategy(deps.http);

      async fetchSignals(ctx: MetricContext): Promise<SocialSignal | null> {
        return (await this.cache.fetchSignals(ctx)) ?? (await this.live.fetchSignals(ctx));
      }
    })();
  }
}

/* -------------------------------------------------------------------------------------------------
 * Chain of Responsibility – Metric Enrichment Pipeline
 * -----------------------------------------------------------------------------------------------*/

abstract class EnrichmentHandler {
  private next: EnrichmentHandler | undefined;

  setNext(handler: EnrichmentHandler): EnrichmentHandler {
    this.next = handler;
    return handler;
  }

  async handle(metric: EnrichedMetric): Promise<EnrichedMetric> {
    const processed = await this.process(metric);
    if (this.next) {
      return this.next.handle(processed);
    }
    return processed;
  }

  protected abstract process(metric: EnrichedMetric): Promise<EnrichedMetric>;
}

/* ----- Handler #1: Inject Social Signals -------------------------------------------------------*/
class SocialSignalEnrichmentHandler extends EnrichmentHandler {
  constructor(private readonly strategy: SocialSignalStrategy) {
    super();
  }

  protected async process(metric: EnrichedMetric): Promise<EnrichedMetric> {
    const ctx: MetricContext = {
      metric,
      correlationId: metric.correlationId ?? randomUUID(),
    };

    const signals = await this.strategy.fetchSignals(ctx);
    return {
      ...metric,
      correlationId: ctx.correlationId,
      socialSignal: signals ?? undefined,
    };
  }
}

/* ----- Handler #2: Add Derived Tags -------------------------------------------------------------*/
class TaggingEnrichmentHandler extends EnrichmentHandler {
  protected async process(metric: EnrichedMetric): Promise<EnrichedMetric> {
    const trending = metric.socialSignal?.likes && metric.socialSignal.likes > 10_000;
    const tags = new Set(metric.tags ?? []);

    if (trending) tags.add('trending');
    if (metric.socialSignal?.comments) tags.add('has-comments');

    return {
      ...metric,
      tags: Array.from(tags),
    };
  }
}

/* -------------------------------------------------------------------------------------------------
 * Observer Pattern – Enrichment Event Bus
 * -----------------------------------------------------------------------------------------------*/

export interface EnrichedMetricListener {
  (metric: EnrichedMetric): void | Promise<void>;
}

/**
 * Simple event bus (in-memory). For cross-process propagation use Kafka topic instead.
 */
class EnrichmentEventBus extends EventEmitter {
  emitMetric(metric: EnrichedMetric): void {
    this.emit('metric', metric);
  }

  subscribe(listener: EnrichedMetricListener): () => void {
    this.on('metric', listener);
    return () => this.off('metric', listener);
  }
}

/* -------------------------------------------------------------------------------------------------
 * Command Pattern – EnrichMetricCommand
 * -----------------------------------------------------------------------------------------------*/

export class EnrichMetricCommand {
  readonly name = 'EnrichMetricCommand';
  constructor(public readonly payload: Metric) {}
}

/* -------------------------------------------------------------------------------------------------
 * MetricEnrichmentOrchestrator – Public API
 * -----------------------------------------------------------------------------------------------*/

export class MetricEnrichmentOrchestrator {
  private readonly bus = new EnrichmentEventBus();
  private readonly pipeline: EnrichmentHandler;
  private readonly producer: KafkaProducer;

  constructor(config: ConfigService, deps: { redis?: RedisClientType; http: any; producer: KafkaProducer }) {
    const strategy = SocialSignalStrategyFactory.build(config, deps);

    // Build pipeline
    this.pipeline = new SocialSignalEnrichmentHandler(strategy);
    this.pipeline.setNext(new TaggingEnrichmentHandler());

    this.producer = deps.producer;
  }

  /**
   * Execute the enrichment pipeline for a single metric and publish the result.
   */
  async execute(cmd: EnrichMetricCommand): Promise<void> {
    const baseMetric: EnrichedMetric = { ...cmd.payload, correlationId: randomUUID() };

    try {
      const enriched = await this.pipeline.handle(baseMetric);
      await this.producer.send('enriched-metrics', enriched);
      this.bus.emitMetric(enriched);

      logger.info(
        {
          entityId: enriched.entityId,
          correlationId: enriched.correlationId,
          tags: enriched.tags,
        },
        'Metric successfully enriched and published',
      );
    } catch (err) {
      logger.error({ err, entityId: cmd.payload.entityId }, 'Failed to enrich metric');
      throw err;
    }
  }

  /**
   * Consumers (e.g. alerting engine) subscribe to enriched metrics.
   */
  onEnrichedMetric(listener: EnrichedMetricListener): () => void {
    return this.bus.subscribe(listener);
  }
}

/* -------------------------------------------------------------------------------------------------
 * Convenience bootstrap for lightweight usage (e.g. CLI scripts, tests)
 * -----------------------------------------------------------------------------------------------*/

let _singleton: MetricEnrichmentOrchestrator | undefined;

/**
 * Acquire singleton orchestrator instance. Lazily constructs required dependencies
 * using default process-level configuration.
 */
export async function getMetricEnrichmentOrchestrator(): Promise<MetricEnrichmentOrchestrator> {
  if (_singleton) return _singleton;

  const config = await ConfigService.bootstrap();
  const redis = await config.optional<boolean>('redis.enabled', true)
    ? (await import('./infrastructure/cache/redisClient')).redisClient
    : undefined;

  const httpClient = await import('./infrastructure/http/client'); // dynamic import to avoid circular deps
  const producer = await KafkaProducer.connect(config);

  _singleton = new MetricEnrichmentOrchestrator(config, {
    redis,
    http: httpClient.default,
    producer,
  });

  return _singleton;
}
```
