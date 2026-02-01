```typescript
/* ---------------------------------------------------------------------
 * File:        src/module_72.ts
 * Project:     PulseSphere SocialOps – System Monitoring
 * Description: Social-aware correlation engine that enriches raw infra
 *              metrics with real-time community-interaction signals.
 * ---------------------------------------------------------------------
 * Pattern(s):  Strategy, Chain-of-Responsibility, Observer
 * ---------------------------------------------------------------------
 * Why this exists:
 *   – SREs need to know whether a CPU spike is caused by a celebrity
 *     joining a live stream or a rogue cron-job.  By correlating metrics
 *     with social noise we can surface intent and react pro-actively.
 * ------------------------------------------------------------------- */

import { EventEmitter } from 'events';
import pino from 'pino';
import { Kafka, Producer } from 'kafkajs';

/* ---------------------------------------------------------------------
 * Domain Types
 * ------------------------------------------------------------------- */

export interface InfraMetric {
  /** e.g. 'api.latency.p95' */
  name: string;
  /** epoch ms */
  timestamp: number;
  /** units depend on metric (ms, %, MB, …) */
  value: number;
  /** additional labels such as cluster, dc, service, etc. */
  labels: Record<string, string>;
}

export interface SocialSignal {
  /** e.g. 'likes', 'comments', 'shares', 'live_stream_viewers' */
  signalType: string;
  /** epoch ms */
  timestamp: number;
  /** absolute count */
  value: number;
  /** contextual data such as hashtag or influencer id */
  context?: Record<string, string | number>;
}

export interface EnrichedMetric extends InfraMetric {
  /** sum of correlation scores from all strategies */
  correlationScore: number;
  /** individual strategy results for debugging */
  evidence: CorrelationEvidence[];
}

export interface CorrelationEvidence {
  strategy: string;
  score: number;
  details?: string;
}

export interface CorrelationStrategy {
  /** name for diagnostics */
  readonly name: string;
  /**
   * @returns `null` if the strategy is not applicable; otherwise a score
   *           0.0‒1.0 representing strength of correlation
   */
  evaluate(metric: InfraMetric, signals: SocialSignal[]): CorrelationEvidence | null;
}

/* ---------------------------------------------------------------------
 * Strategy Implementations
 * ------------------------------------------------------------------- */

/**
 * Correlates latency spikes with concurrent increases in live viewers.
 */
export class LatencyVsLiveViewersStrategy implements CorrelationStrategy {
  public readonly name = 'LatencyVsLiveViewers';

  private static readonly LATENCY_METRIC_REGEX = /(latency|response_time)/i;
  private static readonly LIVE_VIEWER_SIGNAL = 'live_stream_viewers';

  evaluate(metric: InfraMetric, signals: SocialSignal[]): CorrelationEvidence | null {
    if (!LatencyVsLiveViewersStrategy.LATENCY_METRIC_REGEX.test(metric.name)) {
      return null;
    }

    const relevantSignals = signals.filter(
      s =>
        s.signalType === LatencyVsLiveViewersStrategy.LIVE_VIEWER_SIGNAL &&
        Math.abs(s.timestamp - metric.timestamp) < 10_000, // ±10s
    );

    if (!relevantSignals.length) {
      return null;
    }

    // Basic heuristic: more viewers → higher correlation
    const maxViewerCount = Math.max(...relevantSignals.map(s => s.value));
    const score = Math.min(maxViewerCount / 50_000, 1); // cap at 50k viewers

    return {
      strategy: this.name,
      score,
      details: `Peak viewers=${maxViewerCount}`,
    };
  }
}

/**
 * Correlates sudden hashtag rises with CPU/memory saturation.
 */
export class TrendingHashtagSaturationStrategy implements CorrelationStrategy {
  public readonly name = 'TrendingHashtagSaturation';

  private static readonly RESOURCE_METRIC_REGEX = /(cpu|memory|load|requests_per_sec)/i;
  private static readonly HASHTAG_SIGNAL = 'hashtag_mentions';

  evaluate(metric: InfraMetric, signals: SocialSignal[]): CorrelationEvidence | null {
    if (!TrendingHashtagSaturationStrategy.RESOURCE_METRIC_REGEX.test(metric.name)) {
      return null;
    }

    const hashtagSignals = signals.filter(
      s =>
        s.signalType === TrendingHashtagSaturationStrategy.HASHTAG_SIGNAL &&
        Math.abs(s.timestamp - metric.timestamp) < 30_000,
    );

    if (!hashtagSignals.length) {
      return null;
    }

    const sorted = [...hashtagSignals].sort((a, b) => b.value - a.value);
    const top = sorted[0];
    const score = Math.min(top.value / 10_000, 1);

    return {
      strategy: this.name,
      score,
      details: `Hashtag=${top.context?.hashtag ?? 'unknown'} volume=${top.value}`,
    };
  }
}

/* ---------------------------------------------------------------------
 * Correlation Engine
 * ------------------------------------------------------------------- */

/**
 * Emits 'enriched' events with EnrichedMetric payloads.
 */
export class SocialCorrelationEngine extends EventEmitter {
  private readonly log = pino({ name: 'SocialCorrelationEngine' });
  private readonly strategies: CorrelationStrategy[];
  private readonly signalWindowMs: number;
  private readonly recentSignals: SocialSignal[] = [];
  private readonly kafkaProducer?: Producer;

  constructor(opts: {
    strategies?: CorrelationStrategy[];
    /** signals are kept for this many ms for correlation   (default 60s) */
    signalWindowMs?: number;
    /** (optional) Kafka instance to publish enriched metrics */
    kafka?: Kafka;
  }) {
    super();
    this.strategies = opts.strategies?.length
      ? opts.strategies
      : [new LatencyVsLiveViewersStrategy(), new TrendingHashtagSaturationStrategy()];
    this.signalWindowMs = opts.signalWindowMs ?? 60_000;

    if (opts.kafka) {
      this.kafkaProducer = opts.kafka.producer();
      this.kafkaProducer.connect().catch(err =>
        this.log.error({ err }, 'Failed to connect Kafka producer'),
      );
    }
  }

  /**
   * Collects a social signal for future correlations.
   */
  public ingestSocialSignal(signal: SocialSignal): void {
    this.recentSignals.push(signal);
    this.trimSignalWindow();
  }

  /**
   * Ingest a raw infrastructure metric and emit an enriched metric
   * as soon as correlation is complete.
   */
  public async ingestMetric(metric: InfraMetric): Promise<void> {
    try {
      const signalsSnapshot = this.getSignalsFor(metric.timestamp);
      const evidence: CorrelationEvidence[] = [];

      for (const strategy of this.strategies) {
        try {
          const result = strategy.evaluate(metric, signalsSnapshot);
          if (result) {
            evidence.push(result);
          }
        } catch (err) {
          this.log.warn(
            { err, strategy: strategy.name },
            'Correlation strategy failure; continuing with others',
          );
        }
      }

      const correlationScore = evidence.reduce((sum, e) => sum + e.score, 0);
      const enriched: EnrichedMetric = {
        ...metric,
        correlationScore: Number(correlationScore.toFixed(3)),
        evidence,
      };

      this.emit('enriched', enriched);
      if (this.kafkaProducer) {
        await this.publishToKafka(enriched);
      }
    } catch (err) {
      this.log.error({ err, metric }, 'Failed to correlate metric');
    }
  }

  /* -------------------------------------------------------------------
   * Internals
   * ----------------------------------------------------------------- */

  private trimSignalWindow(): void {
    const cutoff = Date.now() - this.signalWindowMs;
    while (this.recentSignals.length && this.recentSignals[0].timestamp < cutoff) {
      this.recentSignals.shift();
    }
  }

  private getSignalsFor(timestamp: number): SocialSignal[] {
    return this.recentSignals.filter(
      s => Math.abs(s.timestamp - timestamp) <= this.signalWindowMs,
    );
  }

  private async publishToKafka(enriched: EnrichedMetric): Promise<void> {
    try {
      await this.kafkaProducer!.send({
        topic: 'enriched_metrics',
        messages: [{ key: enriched.name, value: JSON.stringify(enriched) }],
      });
    } catch (err) {
      this.log.error({ err }, 'Failed to publish enriched metric to Kafka');
    }
  }

  /* -------------------------------------------------------------------
   * Graceful Shutdown
   * ----------------------------------------------------------------- */

  public async close(): Promise<void> {
    if (this.kafkaProducer) {
      await this.kafkaProducer.disconnect().catch(err =>
        this.log.warn({ err }, 'Kafka producer disconnect failed'),
      );
    }
    this.removeAllListeners();
  }
}

/* ---------------------------------------------------------------------
 * Example Usage (would live elsewhere in real project)
 * ------------------------------------------------------------------- */

// Only executed when run directly, not when imported:
if (require.main === module) {
  (async () => {
    const engine = new SocialCorrelationEngine({});

    engine.on('enriched', metric => {
      // eslint-disable-next-line no-console
      console.log('ENRICHED METRIC', metric);
    });

    // Fake signal/metric ingestion
    engine.ingestSocialSignal({
      signalType: 'live_stream_viewers',
      timestamp: Date.now(),
      value: 25_000,
      context: { influencerId: 'abc123' },
    });

    await engine.ingestMetric({
      name: 'api.latency.p95',
      value: 325,
      timestamp: Date.now(),
      labels: { service: 'video-stream' },
    });

    await engine.close();
  })().catch(err => {
    // eslint-disable-next-line no-console
    console.error(err);
    process.exit(1);
  });
}
```