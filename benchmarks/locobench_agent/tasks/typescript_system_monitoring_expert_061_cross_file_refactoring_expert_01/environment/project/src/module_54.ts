```typescript
/**
 *  PulseSphere SocialOps – System Monitoring
 *  ----------------------------------------------------
 *  File:          src/module_54.ts
 *  Responsibility:
 *      • Consumes infrastructure + social-signal streams (Kafka)
 *      • Detects anomalies using a pluggable Strategy Pattern
 *      • Emits self-healing commands (Command + Chain-of-Responsibility)
 *      • Designed for large-scale, production deployments
 */

import { EventEmitter } from 'events';
import pino, { Logger } from 'pino';
import { Kafka, Consumer, EachMessagePayload } from 'kafkajs';

/* ------------------------------------------------------------------ *
 |  Domain Models                                                     |
 * ------------------------------------------------------------------ */

/**
 * Represents a datapoint coming from infrastructure telemetry.
 */
export interface SystemMetricSample {
  ts: number;              // epoch millis
  host: string;            // server / pod id
  cpu: number;             // 0..1
  mem: number;             // 0..1
  net: number;             // bytes / sec
}

/**
 * Represents a datapoint coming from the social graph.
 */
export interface SocialMetricSample {
  ts: number;              // epoch millis
  region: string;
  likes: number;
  comments: number;
  shares: number;
  livestreamSpikes: number;
}

/**
 * Unified envelope – we enrich infra metrics with social context.
 */
export interface CorrelatedSample {
  ts: number;
  infra: SystemMetricSample;
  social: SocialMetricSample;
}

/* ------------------------------------------------------------------ *
 |  Anomaly-Detection Strategy                                        |
 * ------------------------------------------------------------------ */

/**
 * Strategy interface – implementors decide whether an input is anomalous.
 */
export interface AnomalyDetectionStrategy {
  readonly name: string;
  /**
   * @param window  – sliding window of recent samples
   * @param sample  – newest sample
   * @returns anomalyScore in range [0, 1] where values >= threshold
   *          are considered anomalous by the caller.
   */
  score(window: ReadonlyArray<CorrelatedSample>, sample: CorrelatedSample): number;
}

/**
 * Z-Score strategy – good for gaussian-like distributions.
 */
export class ZScoreStrategy implements AnomalyDetectionStrategy {
  public readonly name = 'z-score';

  constructor(private readonly zThreshold: number = 3) {}

  /* eslint-disable max-params */
  score(window: ReadonlyArray<CorrelatedSample>, sample: CorrelatedSample): number {
    if (window.length < 10) return 0; // not enough data

    // Compute mean + stddev of CPU utilisation within window
    const cpuValues = window.map((w) => w.infra.cpu);
    const mean = cpuValues.reduce((a, b) => a + b, 0) / cpuValues.length;
    const variance =
      cpuValues.reduce((sum, v) => sum + (v - mean) ** 2, 0) / cpuValues.length;
    const std = Math.sqrt(variance);

    if (std === 0) return 0;

    const z = Math.abs((sample.infra.cpu - mean) / std);

    return Math.min(z / this.zThreshold, 1); // normalise to [0,1]
  }
}

/**
 * Adaptive Percentile strategy – robust to outliers.
 */
export class AdaptivePercentileStrategy implements AnomalyDetectionStrategy {
  public readonly name = 'adaptive-percentile';

  constructor(private readonly percentile = 0.95) {}

  score(window: ReadonlyArray<CorrelatedSample>, sample: CorrelatedSample): number {
    if (window.length < 50) return 0;

    const cpuValues = window.map((w) => w.infra.cpu).sort((a, b) => a - b);
    const idx = Math.floor(this.percentile * cpuValues.length);
    const threshold = cpuValues[idx];

    if (sample.infra.cpu <= threshold) return 0;

    // linear scale above threshold
    return Math.min((sample.infra.cpu - threshold) / (1 - threshold), 1);
  }
}

/* ------------------------------------------------------------------ *
 |  Command Pattern ‑ Self-Healing Actions                            |
 * ------------------------------------------------------------------ */

/**
 * Command context propagated through the handler chain.
 */
export interface ScalingContext {
  severity: number; // 0..1
  reason: string;
  cluster: string;
  requestedReplicas: number;
}

/**
 * Base Command Interface.
 */
export interface Command {
  readonly name: string;
  execute(): Promise<void>;
}

/**
 * Concrete command – scale a cluster.
 */
export class ScaleClusterCommand implements Command {
  public readonly name = 'scale-cluster';

  constructor(private readonly ctx: ScalingContext) {}

  get context(): ScalingContext {
    return this.ctx;
  }

  async execute(): Promise<void> {
    // no-op – execution delegated to chain handlers
  }
}

/* ------------------------------------------------------------------ *
 |  Chain of Responsibility                                           |
 * ------------------------------------------------------------------ */

/**
 * Abstract handler that forwards to the next handler when it cannot handle a command.
 */
abstract class BaseHandler {
  protected next: BaseHandler | null = null;

  constructor(protected readonly logger: Logger) {}

  setNext(handler: BaseHandler): BaseHandler {
    this.next = handler;
    return handler;
  }

  async handle(cmd: Command): Promise<void> {
    const handled = await this.process(cmd);
    if (!handled && this.next) {
      return this.next.handle(cmd);
    }
    if (!handled && !this.next) {
      this.logger.warn({ cmd: cmd.name }, 'No handler accepted the command.');
    }
  }

  protected abstract process(cmd: Command): Promise<boolean>;
}

/**
 * Handler: Kubernetes Auto-scaler.
 */
class K8sScalerHandler extends BaseHandler {
  protected async process(cmd: Command): Promise<boolean> {
    if (cmd instanceof ScaleClusterCommand) {
      const ctx = cmd.context;
      if (!ctx.cluster.startsWith('k8s:')) return false;

      try {
        this.logger.info(
          { cluster: ctx.cluster, replicas: ctx.requestedReplicas },
          'Scaling Kubernetes cluster',
        );
        // In real code we would call the Kubernetes API here.
        // await k8sClient.scaleDeployment(ctx.cluster, ctx.requestedReplicas);
        return true;
      } catch (err) {
        this.logger.error(err, 'K8s scaling failed – passing to next handler');
        return false;
      }
    }
    return false;
  }
}

/**
 * Handler: AWS AutoScaling Group.
 */
class AWSASGHandler extends BaseHandler {
  protected async process(cmd: Command): Promise<boolean> {
    if (cmd instanceof ScaleClusterCommand) {
      const ctx = cmd.context;
      if (!ctx.cluster.startsWith('aws:')) return false;

      try {
        this.logger.info(
          { cluster: ctx.cluster, replicas: ctx.requestedReplicas },
          'Scaling AWS ASG',
        );
        // await awsSdk.scaleAsg(ctx.cluster, ctx.requestedReplicas);
        return true;
      } catch (err) {
        this.logger.error(err, 'AWS ASG scaling failed');
        return false;
      }
    }
    return false;
  }
}

/* ------------------------------------------------------------------ *
 |  Social-Aware Anomaly Detector (Observer + Strategy)               |
 * ------------------------------------------------------------------ */

interface DetectorOptions {
  windowSize?: number;
  anomalyThreshold?: number; // 0..1
  kafkaBrokers: string[];
  kafkaClientId: string;
  topics: { infra: string; social: string };
}

/**
 * SocialAnomalyDetector subscribes to two Kafka topics, correlates them, and
 * invokes remediation commands when anomalies are detected.
 */
export class SocialAnomalyDetector extends EventEmitter {
  private readonly log: Logger;
  private readonly strategy: AnomalyDetectionStrategy;
  private readonly window: CorrelatedSample[] = [];

  private consumer!: Consumer;
  private readonly windowSize: number;
  private readonly anomalyThreshold: number;

  constructor(
    strategy: AnomalyDetectionStrategy,
    private readonly options: DetectorOptions,
    private readonly commandChain: BaseHandler,
    logger: Logger = pino(),
  ) {
    super();
    this.strategy = strategy;
    this.log = logger.child({ module: 'SocialAnomalyDetector', strategy: strategy.name });
    this.windowSize = options.windowSize ?? 250;
    this.anomalyThreshold = options.anomalyThreshold ?? 0.8;
  }

  /* ----------------------------------------------- *
   * Public API                                      *
   * ----------------------------------------------- */

  async start(): Promise<void> {
    await this.bootKafkaConsumer();
    this.log.info('SocialAnomalyDetector started.');
  }

  async stop(): Promise<void> {
    if (this.consumer) await this.consumer.disconnect();
  }

  /* ----------------------------------------------- *
   * Internal Mechanics                              *
   * ----------------------------------------------- */

  private async bootKafkaConsumer(): Promise<void> {
    const kafka = new Kafka({
      clientId: this.options.kafkaClientId,
      brokers: this.options.kafkaBrokers,
    });

    this.consumer = kafka.consumer({ groupId: `${this.options.kafkaClientId}-detector` });

    await this.consumer.connect();
    await this.consumer.subscribe({ topic: this.options.topics.infra, fromBeginning: false });
    await this.consumer.subscribe({ topic: this.options.topics.social, fromBeginning: false });

    await this.consumer.run({
      eachMessage: async (payload) => {
        try {
          await this.ingest(payload);
        } catch (err) {
          this.log.error(err, 'failed to process message');
        }
      },
    });
  }

  /**
   * Ingests a single Kafka message, returning once correlations & detection
   * logic have been applied.
   */
  private async ingest({ topic, message }: EachMessagePayload): Promise<void> {
    const raw = message.value?.toString();
    if (!raw) return;

    const ts = Date.now();

    if (topic === this.options.topics.infra) {
      const infra: SystemMetricSample = JSON.parse(raw);
      // Look for matching social sample in last X millis
      const socialCandidate = this.findNearestSocialSample(infra.ts);
      if (!socialCandidate) return; // wait for social sample to arrive

      const correlated: CorrelatedSample = { ts, infra, social: socialCandidate };
      this.analyse(correlated);
    } else if (topic === this.options.topics.social) {
      // store social sample so infra can correlate later
      const social: SocialMetricSample = JSON.parse(raw);
      this.socialBuffer.push(social);
      this.trimSocialBuffer();
    }
  }

  /* ----------------------------------------------- *
   * Social sample buffer                            *
   * ----------------------------------------------- */

  private readonly socialBuffer: SocialMetricSample[] = [];
  private readonly socialRetentionMs = 30_000; // keep 30s of social data

  private findNearestSocialSample(ts: number): SocialMetricSample | undefined {
    if (this.socialBuffer.length === 0) return;

    let nearest: SocialMetricSample | undefined;
    let minDiff = Infinity;

    for (const s of this.socialBuffer) {
      const diff = Math.abs(s.ts - ts);
      if (diff < minDiff) {
        minDiff = diff;
        nearest = s;
      }
    }

    // Accept only if within 2 seconds
    if (minDiff > 2_000) return undefined;

    return nearest;
  }

  private trimSocialBuffer(): void {
    const cutoff = Date.now() - this.socialRetentionMs;
    while (this.socialBuffer.length && this.socialBuffer[0].ts < cutoff) {
      this.socialBuffer.shift();
    }
  }

  /* ----------------------------------------------- *
   * Analysis                                        *
   * ----------------------------------------------- */

  private analyse(sample: CorrelatedSample): void {
    // maintain sliding window
    this.window.push(sample);
    if (this.window.length > this.windowSize) this.window.shift();

    const score = this.strategy.score(this.window, sample);
    this.log.debug({ score }, 'Anomaly score calculated');

    if (score >= this.anomalyThreshold) {
      this.emit('anomaly', { score, sample });
      void this.handleAnomaly(score, sample).catch((err) =>
        this.log.error(err, 'failed to handle anomaly'),
      );
    }
  }

  /* ----------------------------------------------- *
   * Remediation Workflow                            *
   * ----------------------------------------------- */

  private async handleAnomaly(score: number, sample: CorrelatedSample): Promise<void> {
    const extraReplicas = Math.ceil(score * 10); // naive formula
    const cmd = new ScaleClusterCommand({
      severity: score,
      reason: `High CPU (${sample.infra.cpu}) + Social Surge (${sample.social.likes} likes)`,
      cluster: 'k8s:realtime-backend',
      requestedReplicas: extraReplicas,
    });

    this.log.warn(
      { severity: score, requestedReplicas: extraReplicas },
      'Anomaly detected – dispatching ScaleClusterCommand',
    );

    await this.commandChain.handle(cmd);
  }
}

/* ------------------------------------------------------------------ *
 |  Bootstrap                                                         |
 * ------------------------------------------------------------------ */

if (require.main === module) {
  // Stand-alone mode – launch detector with sensible defaults.
  (async () => {
    const logger = pino({ level: process.env.LOG_LEVEL || 'info' });

    // Build command handler chain
    const k8sHandler = new K8sScalerHandler(logger);
    const awsHandler = new AWSASGHandler(logger);
    k8sHandler.setNext(awsHandler);

    // Choose strategy based on ENV
    const strategy =
      process.env.ANOMALY_STRATEGY === 'percentile'
        ? new AdaptivePercentileStrategy(parseFloat(process.env.PERCENTILE || '0.95'))
        : new ZScoreStrategy(parseFloat(process.env.Z_THRESHOLD || '3'));

    const detector = new SocialAnomalyDetector(
      strategy,
      {
        windowSize: parseInt(process.env.WINDOW_SIZE || '250', 10),
        anomalyThreshold: parseFloat(process.env.ANOMALY_THRESHOLD || '0.8'),
        kafkaBrokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
        kafkaClientId: process.env.KAFKA_CLIENT_ID || 'pulsesphere-detector',
        topics: {
          infra: process.env.TOPIC_INFRA || 'system_metrics',
          social: process.env.TOPIC_SOCIAL || 'social_metrics',
        },
      },
      k8sHandler,
      logger,
    );

    process.on('SIGINT', async () => {
      logger.info('SIGINT received – shutting down gracefully');
      await detector.stop();
      process.exit(0);
    });

    await detector.start();
  })().catch((err) => {
    // eslint-disable-next-line no-console
    console.error('Fatal error during bootstrap', err);
    process.exit(1);
  });
}
```