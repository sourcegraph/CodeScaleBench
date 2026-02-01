```typescript
/**
 *  src/module_34.ts
 *
 *  CorrelatedMetricsAnalyzer
 *  -------------------------------------------------------------
 *  Consumes raw infrastructure metrics from Kafka, enriches them
 *  with live social-interaction signals and evaluates whether an
 *  alert or an auto-scaling action must be triggered. Evaluation
 *  follows a Chain-of-Responsibility pipeline, and scaling actions
 *  are delegated to interchangeable Strategy implementations.
 *
 *  Architectural patterns showcased:
 *    • Event-Driven ingestion (Kafka)
 *    • Chain-of-Responsibility (metric evaluators)
 *    • Strategy Pattern (scaling decision)
 *
 *  NOTE:
 *  ‑ External service clients (Kafka, NATS, social-signal back-end)
 *    are intentionally lightweight to keep this single-file demo
 *    self-contained. In the real codebase they live in dedicated
 *    packages with resiliency, metrics and tracing built-in.
 *  -------------------------------------------------------------
 */

import { Kafka, Consumer, KafkaMessage, logLevel } from 'kafkajs';
import { connect, NatsConnection, StringCodec } from 'nats';

////////////////////////////////////////////////////////////////////////////////
// Domain types
////////////////////////////////////////////////////////////////////////////////

/**
 * Raw metric emitted by the telemetry pipeline.
 */
export interface MetricEvent {
  tenantId: string;
  hostId: string;
  timestamp: number;         // Unix epoch millis
  cpu: number;               // percentage (0-100)
  memory: number;            // percentage (0-100)
  p95LatencyMs: number;      // API latency
  reqPerSec: number;         // throughput
}

/**
 * Enriched social-interaction context for a given tenant.
 */
export interface SocialSignal {
  tenantId: string;
  likeRate: number;          // likes per second
  shareRate: number;         // shares per second
  commentRate: number;       // comments per second
  sentimentScore: number;    // ‑1 .. 1
  isTrending: boolean;       // heuristic flag
}

/**
 * Combined context forwarded through the evaluator chain.
 */
export interface EvaluationContext {
  metric: MetricEvent;
  social: SocialSignal;
}

/**
 * Decision produced by the evaluator chain.
 */
export interface AlertDecision {
  shouldAlert: boolean;
  severity: 'info' | 'warning' | 'critical';
  reason: string;
}

/**
 * Decision that drives downstream auto-scaling. Produced by
 * Strategy implementations.
 */
export interface ScalingDecision {
  action: 'scale_out' | 'scale_in' | 'no_op';
  replicasDelta: number;      // positive => add, negative => remove
  rationale: string;
}

////////////////////////////////////////////////////////////////////////////////
// Social-signal client (stub)
////////////////////////////////////////////////////////////////////////////////

class SocialSignalClient {
  /**
   * Fetches latest social metrics for the specified tenant. In the
   * actual platform this call queries a Redis cache or hits a
   * high-throughput gRPC micro-service.
   */
  async fetch(tenantId: string): Promise<SocialSignal> {
    // TODO: Replace stub with real RPC call.
    return {
      tenantId,
      likeRate: Math.random() * 500,
      shareRate: Math.random() * 120,
      commentRate: Math.random() * 200,
      sentimentScore: Math.random() * 2 - 1,
      isTrending: Math.random() > 0.85,
    };
  }
}

////////////////////////////////////////////////////////////////////////////////
// Chain-of-Responsibility for metric evaluation
////////////////////////////////////////////////////////////////////////////////

abstract class MetricHandler {
  protected next?: MetricHandler;

  withNext(handler: MetricHandler): MetricHandler {
    this.next = handler;
    return handler;
  }

  async handlePayload(ctx: EvaluationContext): Promise<AlertDecision> {
    const decision = await this.evaluate(ctx);

    // Short-circuit if current handler triggers an alert:
    if (decision.shouldAlert || !this.next) {
      return decision;
    }

    // Otherwise continue processing downstream:
    return this.next.handlePayload(ctx);
  }

  protected abstract evaluate(ctx: EvaluationContext): Promise<AlertDecision>;
}

/**
 * CPU usage anomaly detector.
 */
class CpuUsageHandler extends MetricHandler {
  protected async evaluate(ctx: EvaluationContext): Promise<AlertDecision> {
    const { cpu } = ctx.metric;
    const isHot = cpu > 85;
    const severity: AlertDecision['severity'] =
      cpu > 95 ? 'critical' : 'warning';

    if (isHot) {
      return {
        shouldAlert: true,
        severity,
        reason: `CPU at ${cpu.toFixed(1)}%`,
      };
    }
    return { shouldAlert: false, severity: 'info', reason: '' };
  }
}

/**
 * Memory pressure detector.
 */
class MemoryUsageHandler extends MetricHandler {
  protected async evaluate(ctx: EvaluationContext): Promise<AlertDecision> {
    const { memory } = ctx.metric;
    const isOomRisk = memory > 90;

    if (isOomRisk) {
      return {
        shouldAlert: true,
        severity: memory > 97 ? 'critical' : 'warning',
        reason: `Memory utilization at ${memory.toFixed(1)}%`,
      };
    }
    return { shouldAlert: false, severity: 'info', reason: '' };
  }
}

/**
 * Latency spike detector that factors in social trending context.
 */
class LatencySpikeHandler extends MetricHandler {
  protected async evaluate(ctx: EvaluationContext): Promise<AlertDecision> {
    const { p95LatencyMs } = ctx.metric;
    const trendingFactor = ctx.social.isTrending ? 0.8 : 1; // trending = more strict

    if (p95LatencyMs * trendingFactor > 400) {
      return {
        shouldAlert: true,
        severity: p95LatencyMs > 800 ? 'critical' : 'warning',
        reason: `P95 latency ${p95LatencyMs.toFixed(0)}ms (trending=${ctx.social.isTrending})`,
      };
    }
    return { shouldAlert: false, severity: 'info', reason: '' };
  }
}

////////////////////////////////////////////////////////////////////////////////
// Scaling strategy pattern
////////////////////////////////////////////////////////////////////////////////

interface ScalingStrategy {
  decide(ctx: EvaluationContext, alert: AlertDecision): Promise<ScalingDecision>;
}

/**
 * Reactive scaling strategy: add replicas when any alert occurs.
 */
class ReactiveScalingStrategy implements ScalingStrategy {
  async decide(_: EvaluationContext, alert: AlertDecision): Promise<ScalingDecision> {
    if (!alert.shouldAlert) {
      return { action: 'no_op', replicasDelta: 0, rationale: 'All clear' };
    }

    const delta = alert.severity === 'critical' ? 3 : 1;
    return {
      action: 'scale_out',
      replicasDelta: delta,
      rationale: `Reactive strategy for ${alert.reason}`,
    };
  }
}

/**
 * Predictive strategy looks at social trending signals to
 * proactively scale out before an alert fires.
 */
class PredictiveScalingStrategy implements ScalingStrategy {
  async decide(ctx: EvaluationContext): Promise<ScalingDecision> {
    const { likeRate, shareRate, isTrending } = ctx.social;
    const highSocialTraffic = (likeRate + shareRate) > 500 || isTrending;

    if (highSocialTraffic) {
      const delta = Math.ceil((likeRate + shareRate) / 500); // heuristic
      return {
        action: 'scale_out',
        replicasDelta: delta,
        rationale: `Predictive social surge (likeRate=${likeRate.toFixed(0)}, shareRate=${shareRate.toFixed(0)})`,
      };
    }

    return { action: 'no_op', replicasDelta: 0, rationale: 'Social calm' };
  }
}

////////////////////////////////////////////////////////////////////////////////
// Alerting and scaling command publishers (stubs)
////////////////////////////////////////////////////////////////////////////////

class AlertingService {
  async send(decision: AlertDecision, ctx: EvaluationContext): Promise<void> {
    // Real implementation pushes to PagerDuty, Slack or OpsGenie.
    console.log(
      `[ALERT] tenant=${ctx.metric.tenantId} host=${ctx.metric.hostId} severity=${decision.severity} reason="${decision.reason}"`
    );
  }
}

class ScalingCommandPublisher {
  private nc?: NatsConnection;
  private readonly codec = StringCodec();

  constructor(private readonly natsUrl: string) {}

  async connect(): Promise<void> {
    this.nc = await connect({ servers: this.natsUrl });
  }

  async publish(decision: ScalingDecision, tenantId: string): Promise<void> {
    if (!this.nc) {
      throw new Error('NATS not connected');
    }
    const payload = JSON.stringify({ ...decision, tenantId, timestamp: Date.now() });
    this.nc.publish('autoscale.command', this.codec.encode(payload));
  }

  async close(): Promise<void> {
    await this.nc?.drain();
  }
}

////////////////////////////////////////////////////////////////////////////////
// Main analyzer orchestrator
////////////////////////////////////////////////////////////////////////////////

export class CorrelatedMetricsAnalyzer {
  private readonly kafka: Kafka;
  private consumer!: Consumer;
  private readonly evaluatorChain: MetricHandler;
  private readonly socialClient = new SocialSignalClient();
  private readonly alertingSvc = new AlertingService();
  private readonly scalingPublisher: ScalingCommandPublisher;

  private readonly strategies: ScalingStrategy[] = [
    new PredictiveScalingStrategy(),
    new ReactiveScalingStrategy(),
  ];

  constructor(
    kafkaBrokers: string[],
    private readonly natsUrl: string,
    private readonly groupId = 'correlated-metrics-analyzer'
  ) {
    this.kafka = new Kafka({ brokers: kafkaBrokers, logLevel: logLevel.ERROR });
    // Compose handler chain
    this.evaluatorChain = new CpuUsageHandler()
      .withNext(new MemoryUsageHandler())
      .withNext(new LatencySpikeHandler());

    this.scalingPublisher = new ScalingCommandPublisher(this.natsUrl);
  }

  /**
   * Bootstraps Kafka + NATS connections and starts consuming.
   */
  async start(): Promise<void> {
    await this.scalingPublisher.connect();

    this.consumer = this.kafka.consumer({ groupId: this.groupId });
    await this.consumer.connect();
    await this.consumer.subscribe({ topic: 'system.metrics', fromBeginning: false });

    await this.consumer.run({
      eachMessage: async ({ message }) => {
        try {
          const metric = this.deserializeMetric(message);
          const social = await this.socialClient.fetch(metric.tenantId);

          const ctx: EvaluationContext = { metric, social };
          const alert = await this.evaluatorChain.handlePayload(ctx);

          // Fire alert if needed:
          if (alert.shouldAlert) {
            await this.alertingSvc.send(alert, ctx);
          }

          // Determine scaling action via first strategy that proposes an action:
          for (const strategy of this.strategies) {
            const scaling = await strategy.decide(ctx, alert);
            if (scaling.action !== 'no_op') {
              await this.scalingPublisher.publish(scaling, metric.tenantId);
              break;
            }
          }
        } catch (err) {
          // Production code: push to error monitoring/metrics
          console.error('[CorrelatedMetricsAnalyzer] Processing error', err);
        }
      },
    });

    console.info('[CorrelatedMetricsAnalyzer] Started.');
  }

  /**
   * Gracefully stops all connections.
   */
  async stop(): Promise<void> {
    try {
      await this.consumer?.disconnect();
      await this.scalingPublisher.close();
    } finally {
      console.info('[CorrelatedMetricsAnalyzer] Stopped.');
    }
  }

  ////////////////////////////////////////////////////////////////////////////
  // Helpers
  ////////////////////////////////////////////////////////////////////////////

  private deserializeMetric(msg: KafkaMessage): MetricEvent {
    if (!msg.value) {
      throw new Error('Empty Kafka message');
    }
    const parsed: unknown = JSON.parse(msg.value.toString());

    // Basic runtime validation (replace with io-ts / zod in real code).
    const required = ['tenantId', 'hostId', 'timestamp', 'cpu', 'memory', 'p95LatencyMs', 'reqPerSec'];
    for (const field of required) {
      if (!(field in (parsed as Record<string, unknown>))) {
        throw new Error(`MetricEvent missing ${field}`);
      }
    }
    return parsed as MetricEvent;
  }
}

////////////////////////////////////////////////////////////////////////////////
// Entrypoint (only executed when run directly with ts-node / node)
////////////////////////////////////////////////////////////////////////////////

if (require.main === module) {
  // Boot parameters via env vars for containerization friendliness.
  const brokers = process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'];
  const natsUrl = process.env.NATS_URL ?? 'nats://localhost:4222';

  const analyzer = new CorrelatedMetricsAnalyzer(brokers, natsUrl);

  analyzer.start().catch((err) => {
    console.error('[CorrelatedMetricsAnalyzer] Fatal startup error', err);
    process.exit(1);
  });

  // SIGTERM/SIGINT for graceful shutdown in Kubernetes
  const shutdown = async () => {
    console.log('[CorrelatedMetricsAnalyzer] Caught termination signal');
    await analyzer.stop();
    process.exit(0);
  };

  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}
```