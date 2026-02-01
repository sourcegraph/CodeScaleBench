```typescript
/**
 * src/module_64.ts
 *
 * SocialImpactCorrelationService
 *
 * This module listens to two Kafka topics (`infra-metrics` & `social-interactions`),
 * continuously correlates infrastructure anomalies with spikes in user-generated
 * activity and emits enriched alerts when statistically significant relationships
 * are detected.
 *
 * Key patterns utilised:
 *  • Strategy          – multiple correlation algorithms can be swapped dynamically
 *  • Chain-of-Responsibility – flexible alert‐handling / escalation pipeline
 *  • Observer          – external components may subscribe to correlation events
 *
 * NOTE: This file purposefully contains all required code in a single module so it
 * can compile in isolation for the demo. In the real code-base most of these types
 * live in dedicated packages.
 */

import { EventEmitter } from 'node:events';
import { Kafka, Producer, Consumer, logLevel, EachMessagePayload } from 'kafkajs';
import pino from 'pino';

// ────────────────────────────────────────────────────────────────────────────────
// CONFIGURATION
// ────────────────────────────────────────────────────────────────────────────────

/**
 * Service-level configuration. In production these values are normally injected
 * via environment variables or a configuration-management system (Consul, Vault,
 * Kubernetes ConfigMaps, etc.).
 */
export interface CorrelatorConfig {
  kafkaBrokers: string[];
  metricsTopic: string;
  socialTopic: string;
  alertTopic: string;
  groupId: string;
  correlationWindowMs: number; // Size of sliding window
  evaluationIntervalMs: number; // How often we evaluate correlation
  correlationThreshold: number; // Pearson coefficient threshold for alerting
  maxBatchSize: number; // Number of messages before we force evaluation
}

// Default values for local development
const defaultConfig: Readonly<CorrelatorConfig> = {
  kafkaBrokers: ['localhost:9092'],
  metricsTopic: 'infra-metrics',
  socialTopic: 'social-interactions',
  alertTopic: 'enriched-alerts',
  groupId: 'social-impact-correlator',
  correlationWindowMs: 5 * 60 * 1000, // 5 minutes
  evaluationIntervalMs: 30 * 1000, // 30 seconds
  correlationThreshold: 0.7,
  maxBatchSize: 2_000,
};

// ────────────────────────────────────────────────────────────────────────────────
// DOMAIN TYPES
// ────────────────────────────────────────────────────────────────────────────────

export interface MetricEvent {
  readonly timestamp: number;
  readonly metric: string; // e.g. "cpu_usage", "latency_p99"
  readonly value: number;
  readonly tags: Record<string, string>;
}

export type SocialType = 'like' | 'comment' | 'share' | 'live-stream' | 'follow';

export interface SocialEvent {
  readonly timestamp: number;
  readonly type: SocialType;
  readonly userId: string;
  readonly contentId: string;
}

// ────────────────────────────────────────────────────────────────────────────────
// STRATEGY: Correlation algorithms
// ────────────────────────────────────────────────────────────────────────────────

export interface CorrelationStrategy {
  /**
   * Compute a correlation coefficient between two numeric data series.
   * A return value of `NaN` means the calculation wasn’t possible.
   */
  compute(
    metricSeries: number[],
    socialSeries: number[],
  ): number;
}

/**
 * Pearson correlation – default implementation.
 * Returns value in range [-1, 1].
 */
export class PearsonCorrelationStrategy implements CorrelationStrategy {
  compute(metricSeries: number[], socialSeries: number[]): number {
    if (metricSeries.length !== socialSeries.length || metricSeries.length < 2) {
      return Number.NaN;
    }

    const n = metricSeries.length;
    const sumX = metricSeries.reduce((a, b) => a + b, 0);
    const sumY = socialSeries.reduce((a, b) => a + b, 0);

    const sumXY = metricSeries.reduce((acc, x, i) => acc + x * socialSeries[i], 0);
    const sumX2 = metricSeries.reduce((acc, x) => acc + x * x, 0);
    const sumY2 = socialSeries.reduce((acc, y) => acc + y * y, 0);

    const numerator = n * sumXY - sumX * sumY;
    const denominator = Math.sqrt(
      (n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY),
    );

    if (denominator === 0) return Number.NaN;
    return numerator / denominator;
  }
}

/**
 * A no-op implementation which always returns zero.
 * Can be used when correlation analysis is temporarily disabled.
 */
export class NullCorrelationStrategy implements CorrelationStrategy {
  /* eslint-disable-next-line @typescript-eslint/no-unused-vars */
  compute(metricSeries: number[], socialSeries: number[]): number {
    return 0;
  }
}

// ────────────────────────────────────────────────────────────────────────────────
// CHAIN-OF-RESPONSIBILITY: Alert handling
// ────────────────────────────────────────────────────────────────────────────────

interface AlertContext {
  metric: string;
  coefficient: number;
  windowStart: number;
  windowEnd: number;
}

abstract class AlertHandler {
  private next?: AlertHandler;

  constructor(protected readonly logger = pino().child({ module: 'AlertHandler' })) {}

  setNext(handler: AlertHandler): AlertHandler {
    this.next = handler;
    return handler;
  }

  async handle(context: AlertContext): Promise<void> {
    if (await this.doHandle(context)) return;
    if (this.next) await this.next.handle(context);
  }

  protected abstract doHandle(context: AlertContext): Promise<boolean>;
}

/**
 * Handler that sends alerts with high coefficients (> threshold * 1.2) to Kafka.
 */
class HighImpactAlertHandler extends AlertHandler {
  constructor(
    private readonly producer: Producer,
    private readonly threshold: number,
    logger = pino(),
  ) {
    super(logger.child({ handler: 'HighImpactAlertHandler' }));
  }

  protected async doHandle(context: AlertContext): Promise<boolean> {
    if (context.coefficient >= this.threshold * 1.2) {
      const payload = {
        ...context,
        severity: 'HIGH',
        generatedAt: Date.now(),
      };

      try {
        await this.producer.send({
          topic: 'enriched-alerts',
          messages: [{ value: JSON.stringify(payload) }],
        });
        this.logger.warn({ alert: payload }, 'High impact alert emitted');
      } catch (err) {
        this.logger.error({ err }, 'Failed to send high impact alert');
      }
      return true; // handled
    }
    return false; // delegate to next handler
  }
}

/**
 * Default/fallback handler – just logs the correlation result.
 */
class LogOnlyAlertHandler extends AlertHandler {
  protected async doHandle(context: AlertContext): Promise<boolean> {
    this.logger.info({ context }, 'Correlation below threshold, nothing to do.');
    return true; // always handles
  }
}

// ────────────────────────────────────────────────────────────────────────────────
// SERVICE IMPLEMENTATION
// ────────────────────────────────────────────────────────────────────────────────

export class SocialImpactCorrelationService extends EventEmitter {
  private readonly logger = pino().child({ service: 'SocialImpactCorrelationService' });

  private readonly kafka: Kafka;
  private readonly producer: Producer;
  private readonly consumer: Consumer;

  private readonly metricBuffer: MetricEvent[] = [];
  private readonly socialBuffer: SocialEvent[] = [];

  private evaluationTimer?: NodeJS.Timeout;
  private batchingCounter = 0;

  constructor(
    private readonly config: Partial<CorrelatorConfig> = {},
    private correlationStrategy: CorrelationStrategy = new PearsonCorrelationStrategy(),
  ) {
    super();
    this.config = { ...defaultConfig, ...config };

    this.kafka = new Kafka({
      clientId: 'pulse-sphere-correlator',
      brokers: this.config.kafkaBrokers,
      logLevel: logLevel.WARN,
    });

    this.consumer = this.kafka.consumer({ groupId: this.config.groupId });
    this.producer = this.kafka.producer();
  }

  // ────────────────────  Lifecycle  ────────────────────

  async start(): Promise<void> {
    await this.producer.connect();
    await this.consumer.connect();

    await this.consumer.subscribe({ topic: this.config.metricsTopic, fromBeginning: false });
    await this.consumer.subscribe({ topic: this.config.socialTopic, fromBeginning: false });

    await this.consumer.run({
      eachMessage: async (payload) => this.handleMessage(payload),
    });

    this.logger.info('Kafka consumer started');

    this.evaluationTimer = setInterval(
      () => void this.evaluateCorrelation(),
      this.config.evaluationIntervalMs,
    );
  }

  async stop(): Promise<void> {
    if (this.evaluationTimer) clearInterval(this.evaluationTimer);
    await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
    this.logger.info('Correlation service stopped');
  }

  // ────────────────────  Kafka Message Handling  ────────────────────

  private async handleMessage({ topic, message }: EachMessagePayload): Promise<void> {
    try {
      if (!message.value) return;
      const parsed = JSON.parse(message.value.toString());

      if (topic === this.config.metricsTopic) {
        this.metricBuffer.push(parsed as MetricEvent);
      } else if (topic === this.config.socialTopic) {
        this.socialBuffer.push(parsed as SocialEvent);
      }

      // Increment message counter for batch evaluation
      if (++this.batchingCounter >= this.config.maxBatchSize) {
        this.batchingCounter = 0;
        await this.evaluateCorrelation();
      }
    } catch (error) {
      this.logger.error({ error }, 'Failed to process message');
    }
  }

  // ────────────────────  Core Logic  ────────────────────

  private async evaluateCorrelation(): Promise<void> {
    const now = Date.now();
    const windowStart = now - this.config.correlationWindowMs;

    // Discard events outside the sliding window
    this.pruneBuffer(this.metricBuffer, windowStart);
    this.pruneBuffer(this.socialBuffer, windowStart);

    if (this.metricBuffer.length === 0 || this.socialBuffer.length === 0) {
      this.logger.debug('No events in buffer to evaluate');
      return;
    }

    // Prepare aligned series based on minute buckets
    const metricSeries = this.createTimeSeries(this.metricBuffer, windowStart, now);
    const socialSeries = this.createTimeSeries(this.socialBuffer, windowStart, now);

    const coefficient = this.correlationStrategy.compute(metricSeries, socialSeries);

    if (Number.isNaN(coefficient)) {
      this.logger.debug('Insufficient data to compute correlation');
      return;
    }

    this.logger.info(
      { coefficient: coefficient.toFixed(3) },
      'Correlation computed',
    );

    // Notify external observers
    this.emit('correlation', { coefficient, metricSeries, socialSeries, windowStart, windowEnd: now });

    if (coefficient >= this.config.correlationThreshold) {
      await this.handleAlert({
        metric: 'multi',
        coefficient,
        windowStart,
        windowEnd: now,
      });
    }
  }

  /**
   * Build a minute-bucket time-series of counts/averages from raw events.
   * For simplicity this implementation counts number of events per minute.
   */
  private createTimeSeries<T extends { timestamp: number }>(
    events: readonly T[],
    start: number,
    end: number,
  ): number[] {
    const minutes = Math.ceil((end - start) / 60_000);
    const series = new Array<number>(minutes).fill(0);

    for (const event of events) {
      const offset = Math.floor((event.timestamp - start) / 60_000);
      if (offset >= 0 && offset < minutes) {
        series[offset] += 1;
      }
    }
    return series;
  }

  private pruneBuffer(buffer: Array<{ timestamp: number }>, windowStart: number): void {
    while (buffer.length && buffer[0].timestamp < windowStart) buffer.shift();
  }

  // ────────────────────  Alert Flow  ────────────────────

  private async handleAlert(context: AlertContext): Promise<void> {
    // Build chain dynamically to demonstrate extendability
    const rootHandler = new HighImpactAlertHandler(
      this.producer,
      this.config.correlationThreshold,
      this.logger,
    );
    rootHandler.setNext(new LogOnlyAlertHandler(this.logger));

    await rootHandler.handle(context);
  }
}

// ────────────────────────────────────────────────────────────────────────────────
// SELF-BOOTSTRAP (only when executed directly, not when imported as a module)
// ────────────────────────────────────────────────────────────────────────────────

if (require.main === module) {
  // eslint-disable-next-line no-console
  console.log('Starting SocialImpactCorrelationService…');

  const service = new SocialImpactCorrelationService();

  service.start().catch((err) => {
    // eslint-disable-next-line no-console
    console.error('Fatal error starting service:', err);
    process.exit(1);
  });

  process.on('SIGINT', async () => {
    // eslint-disable-next-line no-console
    console.log('Graceful shutdown initiated (SIGINT)');
    await service.stop();
    process.exit(0);
  });

  process.on('SIGTERM', async () => {
    // eslint-disable-next-line no-console
    console.log('Graceful shutdown initiated (SIGTERM)');
    await service.stop();
    process.exit(0);
  });
}
```