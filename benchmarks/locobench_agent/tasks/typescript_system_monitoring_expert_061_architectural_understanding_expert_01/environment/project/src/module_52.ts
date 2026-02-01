```typescript
/**
 * PulseSphere SocialOps
 * Module 52 — Social-Aware Anomaly Detection core
 *
 * This module encapsulates an extensible, strategy-based anomaly-detection engine
 * that enriches standard infrastructure metrics with near-real-time social-interaction
 * signals. The detector publishes alerts back into the platform’s event backbone
 * (Apache Kafka) so downstream services (e.g. auto-remediators, incident bots,
 * dashboards) can consume them.
 *
 * Architectural patterns exercised:
 *   • Strategy Pattern            – plug-and-play detection algorithms
 *   • Chain of Responsibility     – strategies are evaluated in order of precedence
 *   • Observer Pattern            – anomaly listeners can subscribe at runtime
 *   • Command Pattern             – runtime commands allow dynamic registration
 */

import { Kafka, Producer, logLevel as KafkaLogLevel } from 'kafkajs';
import pino, { Logger } from 'pino';

/* -------------------------------------------------------------------------- */
/*                              Domain primitives                             */
/* -------------------------------------------------------------------------- */

export type SeverityLevel = 'INFO' | 'WARN' | 'CRITICAL';

export interface MetricSample {
  /** RFC 3339 timestamp */
  timestamp: string;
  /** e.g. cpu.utilisation, http.latency.p95 */
  name: string;
  /** Normalised value */
  value: number;
  /** Key-value metadata (hostId, cluster, …) */
  tags: Record<string, string>;
}

export interface SocialSignal {
  timestamp: string;
  /**
   * Interaction artefact:
   *   like, comment, share, reaction, livestream_view, follower_gain, …
   */
  type: string;
  /** Absolute count since last collection interval */
  count: number;
}

export interface EnrichedMetric {
  metric: MetricSample;
  /** Aggregated interactions for the same interval */
  social: SocialAggregation;
}

export interface SocialAggregation {
  intervalStart: string;
  intervalEnd: string;
  /** Total social volume across all interaction types */
  totalInteractions: number;
  /** Breakdown per interaction type */
  breakdown: Record<string, number>;
}

export interface Anomaly {
  severity: SeverityLevel;
  message: string;
  metric: string;
  timestamp: string;
  context?: Record<string, unknown>;
}

/* -------------------------------------------------------------------------- */
/*                            Strategy Pattern API                            */
/* -------------------------------------------------------------------------- */

/**
 * Pluggable detection algorithm.
 * Return `null` if no anomaly was detected.
 */
export interface AnomalyDetectionStrategy {
  name: string;
  detect(data: ReadonlyArray<EnrichedMetric>): Anomaly | null;
}

/* -------------------------------------------------------------------------- */
/*                       Concrete detection strategy: static                  */
/* -------------------------------------------------------------------------- */

/**
 * Simple threshold-based detection.
 *
 * Example cfg:
 * {
 *   "cpu.utilisation": { "warn": 0.70, "critical": 0.9 },
 *   "http.latency.p95": { "warn": 250, "critical": 500 }
 * }
 */
export class StaticThresholdStrategy implements AnomalyDetectionStrategy {
  public readonly name = 'StaticThresholdStrategy';

  constructor(
    private readonly thresholds: Record<
      string,
      { warn: number; critical: number }
    >,
  ) {}

  detect(data: ReadonlyArray<EnrichedMetric>): Anomaly | null {
    if (!data.length) return null;

    const latest = data[data.length - 1]; // evaluate most recent
    const limits = this.thresholds[latest.metric.name];
    if (!limits) return null;

    if (latest.metric.value >= limits.critical) {
      return {
        severity: 'CRITICAL',
        message: `Critical threshold breached for ${latest.metric.name}`,
        metric: latest.metric.name,
        timestamp: latest.metric.timestamp,
        context: { value: latest.metric.value, limits },
      };
    }

    if (latest.metric.value >= limits.warn) {
      return {
        severity: 'WARN',
        message: `Warning threshold breached for ${latest.metric.name}`,
        metric: latest.metric.name,
        timestamp: latest.metric.timestamp,
        context: { value: latest.metric.value, limits },
      };
    }

    return null;
  }
}

/* -------------------------------------------------------------------------- */
/*              Concrete detection strategy: social-spike correlation         */
/* -------------------------------------------------------------------------- */

export interface SocialSpikeConfig {
  /**
   * Percentage (%) growth in social interactions compared with previous window
   * to consider “viral”.
   */
  spikePercentage: number;
  /** Sliding-window size (ms) used to compute social growth */
  correlationWindowMs: number;
  /**
   * CPU/latency growth (multiplier) that, combined with a social spike,
   * elevates severity despite not exceeding static thresholds.
   */
  infraGrowthFactor: number;
}

/**
 * Detects anomalies when a social-interaction spike co-relates with a
 * simultaneous infra KPI uptick. Useful for catching early viral events.
 */
export class SocialSpikeAwareStrategy implements AnomalyDetectionStrategy {
  public readonly name = 'SocialSpikeAwareStrategy';

  constructor(private readonly cfg: SocialSpikeConfig) {}

  detect(data: ReadonlyArray<EnrichedMetric>): Anomaly | null {
    if (data.length < 2) return null;

    const now = new Date(data[data.length - 1].metric.timestamp).getTime();
    const windowStart = now - this.cfg.correlationWindowMs;

    const windowData = data.filter(
      (d) => new Date(d.metric.timestamp).getTime() >= windowStart,
    );
    if (windowData.length < 2) return null;

    // Calculate social volume delta
    const firstSocial = windowData[0].social.totalInteractions;
    const lastSocial =
      windowData[windowData.length - 1].social.totalInteractions;

    if (firstSocial === 0) return null; // avoid div-by-zero

    const socialGrowthPct = ((lastSocial - firstSocial) / firstSocial) * 100;

    if (socialGrowthPct < this.cfg.spikePercentage) {
      // No viral spike
      return null;
    }

    // Compute infra growth factor for the same metric
    const firstVal = windowData[0].metric.value;
    const lastVal = windowData[windowData.length - 1].metric.value;
    if (firstVal === 0) return null;

    const infraGrowth = lastVal / firstVal;

    if (infraGrowth < this.cfg.infraGrowthFactor) {
      // Infra metrics stable; ignore
      return null;
    }

    return {
      severity: 'WARN',
      message: `Potential viral event: ${socialGrowthPct.toFixed(
        2,
      )}% social spike linked to ${(
        (infraGrowth - 1) *
        100
      ).toFixed(2)}% ${windowData[0].metric.name} increase`,
      metric: windowData[0].metric.name,
      timestamp: windowData[windowData.length - 1].metric.timestamp,
      context: {
        socialGrowthPct,
        infraGrowth,
        windowSize: this.cfg.correlationWindowMs,
      },
    };
  }
}

/* -------------------------------------------------------------------------- */
/*                         Anomaly-event publication layer                    */
/* -------------------------------------------------------------------------- */

export interface AlertDispatcher {
  publish(alert: Anomaly): Promise<void>;
}

/**
 * Kafka-backed dispatcher for anomaly events
 */
export class KafkaAlertDispatcher implements AlertDispatcher {
  private producer!: Producer;

  constructor(
    private readonly kafkaBrokers: string[],
    private readonly topic: string,
    private readonly logger: Logger = pino({ name: 'KafkaAlertDispatcher' }),
  ) {}

  async init(): Promise<void> {
    const kafka = new Kafka({
      clientId: 'pulsesphere-anomaly-detector',
      brokers: this.kafkaBrokers,
      logLevel: KafkaLogLevel.ERROR,
    });

    this.producer = kafka.producer();

    try {
      await this.producer.connect();
      this.logger.info('Kafka producer connected');
    } catch (err) {
      this.logger.error({ err }, 'Failed to connect Kafka producer');
      throw err;
    }
  }

  async publish(alert: Anomaly): Promise<void> {
    if (!this.producer) {
      throw new Error('Kafka Producer not initialised');
    }

    try {
      await this.producer.send({
        topic: this.topic,
        messages: [
          {
            key: alert.metric,
            value: JSON.stringify(alert),
            timestamp: `${Date.now()}`,
          },
        ],
      });

      this.logger.info(
        { metric: alert.metric, severity: alert.severity },
        'Alert published to Kafka',
      );
    } catch (err) {
      this.logger.error({ err }, 'Unable to publish alert');
      throw err;
    }
  }

  async close(): Promise<void> {
    await this.producer.disconnect();
  }
}

/* -------------------------------------------------------------------------- */
/*                      Core detector (Chain of Responsibility)               */
/* -------------------------------------------------------------------------- */

export interface DetectorOptions {
  strategies: AnomalyDetectionStrategy[];
  dispatcher: AlertDispatcher;
  /** Keep an internal rolling buffer for correlation computations */
  historySize?: number;
  logger?: Logger;
}

/**
 * Social-aware detector:
 *   1. Maintains a ring-buffer of recent enriched metrics
 *   2. Evaluates strategies in order of precedence
 *   3. Publishes first anomaly detected
 *   4. Notifies in-process subscribers (Observer Pattern)
 */
export class SocialAwareAnomalyDetector {
  private readonly history: EnrichedMetric[] = [];
  private readonly listeners: Array<(a: Anomaly) => void> = [];
  private readonly historySize: number;
  private readonly log: Logger;

  constructor(private readonly opt: DetectorOptions) {
    if (!opt.strategies.length) {
      throw new Error('At least one detection strategy must be provided');
    }

    this.historySize = opt.historySize ?? 600; // default: last 600 samples
    this.log = opt.logger ?? pino({ name: 'AnomalyDetector' });
  }

  /* ----------------------------- Observer API ----------------------------- */

  public subscribe(listener: (a: Anomaly) => void): () => void {
    this.listeners.push(listener);
    // Return unsubscribe fn
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  private notify(alert: Anomaly): void {
    for (const l of this.listeners) {
      queueMicrotask(() => l(alert));
    }
  }

  /* ----------------------------- Command API ------------------------------ */

  /**
   * Register a new detection strategy at runtime (LIFO precedence)
   */
  public registerStrategy(strategy: AnomalyDetectionStrategy): void {
    this.opt.strategies.unshift(strategy);
    this.log.info({ strategy: strategy.name }, 'Strategy registered');
  }

  /* ---------------------------- Ingress pipeline -------------------------- */

  /**
   * Feed new sample(s) into the detector
   */
  public async process(samples: EnrichedMetric[]): Promise<void> {
    // Keep history bounded
    this.history.push(...samples);
    if (this.history.length > this.historySize) {
      this.history.splice(0, this.history.length - this.historySize);
    }

    for (const strategy of this.opt.strategies) {
      try {
        const alert = strategy.detect(this.history);
        if (alert) {
          await this.opt.dispatcher.publish(alert);
          this.notify(alert);
          // Short-circuit once the first strategy reports an anomaly
          break;
        }
      } catch (err) {
        // Defensive: a faulty strategy should not break the pipeline
        this.log.warn(
          { err, strategy: strategy.name },
          'Strategy execution failed',
        );
      }
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                          Factory / helper bootstrap                        */
/* -------------------------------------------------------------------------- */

export interface DetectorBootstrapConfig {
  kafkaBrokers: string[];
  alertTopic: string;
}

/**
 * Convenience factory that wires commonly used detector configuration.
 */
export async function createDefaultDetector(
  bootstrapCfg: DetectorBootstrapConfig,
  thresholdCfg: ConstructorParameters<typeof StaticThresholdStrategy>[0],
): Promise<SocialAwareAnomalyDetector> {
  const kafkaDispatcher = new KafkaAlertDispatcher(
    bootstrapCfg.kafkaBrokers,
    bootstrapCfg.alertTopic,
  );
  await kafkaDispatcher.init();

  const strategies: AnomalyDetectionStrategy[] = [
    new StaticThresholdStrategy(thresholdCfg),
    new SocialSpikeAwareStrategy({
      spikePercentage: 80,
      correlationWindowMs: 5 * 60 * 1000, // 5 min
      infraGrowthFactor: 1.3,
    }),
  ];

  return new SocialAwareAnomalyDetector({
    strategies,
    dispatcher: kafkaDispatcher,
  });
}
```