```typescript
/**
 * PulseSphere SocialOps – System Monitoring
 * File: src/module_15.ts
 *
 * This module wires together a Chain-of-Responsibility pipeline that
 * processes infrastructure/social alerts and applies automated
 * remediation strategies before escalating to human operators.
 *
 * Design patterns showcased:
 *  • Chain-of-Responsibility – alert-handling pipeline
 *  • Strategy – pluggable scaling strategies
 *  • Observer (implicit) – Kafka/NATS producers publish state-change events
 *
 * External dependencies are injected through environment variables
 * so that the code remains portable and test-friendly.
 */

import { randomUUID } from 'crypto';
import { Kafka, Producer as KafkaProducer, logLevel as KafkaLogLevel } from 'kafkajs';
import { connect as natsConnect, NatsConnection, StringCodec } from 'nats';

// ---------------------------------------------------------------------
// Domain model
// ---------------------------------------------------------------------

export enum AlertSeverity {
  INFO = 'INFO',
  WARNING = 'WARNING',
  CRITICAL = 'CRITICAL',
}

export interface SocialSignals {
  /** Likes per minute related to the item that triggered the alert */
  likesPerMinute: number;
  commentsPerMinute: number;
  sharesPerMinute: number;
  /** Whether an influencer is involved (extracted by PulseSphere ML) */
  influencerPresent: boolean;
}

export interface Alert {
  id: string;
  timestamp: Date;
  severity: AlertSeverity;
  message: string;
  metric: string;
  value: number;
  threshold: number;
  social: SocialSignals;
}

// ---------------------------------------------------------------------
// Strategy pattern – auto-scaling implementations
// ---------------------------------------------------------------------

/**
 * Contract for cluster scaling strategies.
 */
export interface ScalingStrategy {
  /** Initiates scaling and returns the resulting replica count. */
  scale(clusterName: string, delta: number): Promise<number>;
}

/**
 * Horizontal Pod Autoscaling – default strategy.
 */
export class HorizontalScalingStrategy implements ScalingStrategy {
  async scale(clusterName: string, delta: number): Promise<number> {
    // In real-life, call Kubernetes API (k8s-client) or Service Mesh adapter.
    console.info(
      `[HorizontalScalingStrategy] Scaling cluster "${clusterName}" by ${delta} replicas.`,
    );
    // Fake resulting replica count for demo purposes.
    const resultingReplicas = Math.max(1, 10 + delta);
    return resultingReplicas;
  }
}

/**
 * Vertical scaling – add CPU/memory to existing nodes.
 */
export class VerticalScalingStrategy implements ScalingStrategy {
  async scale(clusterName: string, delta: number): Promise<number> {
    console.info(
      `[VerticalScalingStrategy] Adding ${delta * 0.5} vCPU & ${delta}Gi RAM to "${clusterName}".`,
    );
    // Fake resulting capacity index.
    return 100 + delta * 10;
  }
}

// ---------------------------------------------------------------------
// Chain-of-Responsibility – alert handlers
// ---------------------------------------------------------------------

export interface AlertHandler {
  setNext(handler: AlertHandler): AlertHandler;
  handle(alert: Alert): Promise<void>;
}

/**
 * Reusable abstract handler.
 */
abstract class BaseAlertHandler implements AlertHandler {
  private nextHandler: AlertHandler | null = null;

  setNext(handler: AlertHandler): AlertHandler {
    this.nextHandler = handler;
    return handler;
  }

  async handle(alert: Alert): Promise<void> {
    if (!(await this.process(alert)) && this.nextHandler) {
      await this.nextHandler.handle(alert);
    }
  }

  /**
   * Concrete handlers override this and return true if the alert was handled.
   */
  protected abstract process(alert: Alert): Promise<boolean>;
}

/**
 * Handler 1 – Automatic cluster scaling.
 */
class AutoScalerHandler extends BaseAlertHandler {
  constructor(
    private readonly scalingStrategy: ScalingStrategy,
    private readonly kafkaProducer: KafkaProducer,
  ) {
    super();
  }

  protected async process(alert: Alert): Promise<boolean> {
    if (alert.metric !== 'cpu_usage' || alert.severity === AlertSeverity.INFO) {
      return false; // not interested; pass along
    }

    try {
      const delta = alert.severity === AlertSeverity.CRITICAL ? 5 : 2;
      //@TODO: derive cluster name from alert metadata
      const clusterName = 'social-feed-processing';

      const newReplicaCount = await this.scalingStrategy.scale(clusterName, delta);
      await this.kafkaProducer.send({
        topic: 'ops.cluster.scaled',
        messages: [
          {
            key: alert.id,
            value: JSON.stringify({
              alertId: alert.id,
              clusterName,
              newReplicaCount,
              severity: alert.severity,
              timestamp: new Date().toISOString(),
            }),
          },
        ],
      });

      console.info(
        `[AutoScalerHandler] Successfully scaled cluster "${clusterName}" → ${newReplicaCount} (alert: ${alert.id})`,
      );
      return true;
    } catch (err) {
      console.error('[AutoScalerHandler] Failed to scale cluster:', err);
      return false; // escalate further
    }
  }
}

/**
 * Handler 2 – Content throttling when virality spikes threaten stability.
 */
class ContentThrottlingHandler extends BaseAlertHandler {
  constructor(private readonly natsConn: NatsConnection) {
    super();
  }

  protected async process(alert: Alert): Promise<boolean> {
    const { social, severity } = alert;

    if (!social.influencerPresent || severity === AlertSeverity.INFO) {
      return false;
    }

    try {
      const sc = StringCodec();
      const throttleCmd = {
        alertId: alert.id,
        action: 'THROTTLE_CONTENT',
        level: severity === AlertSeverity.CRITICAL ? 'hard' : 'soft',
        reason: alert.message,
        issuedAt: new Date().toISOString(),
      };
      await this.natsConn.publish('ops.content.throttle', sc.encode(JSON.stringify(throttleCmd)));
      console.warn(
        `[ContentThrottlingHandler] Issued content throttle: ${JSON.stringify(throttleCmd)}`,
      );
      return true;
    } catch (err) {
      console.error('[ContentThrottlingHandler] Unable to publish throttle command:', err);
      return false; // pass to next handler
    }
  }
}

/**
 * Handler 3 – Escalate to Incident Commander (human on-call).
 */
class IncidentCommanderHandler extends BaseAlertHandler {
  protected async process(alert: Alert): Promise<boolean> {
    // Always handle if it reaches here.
    console.error(
      `[IncidentCommanderHandler] 🚨 Escalating alert ${alert.id} to human operator: ${alert.message}`,
    );
    // Integrate with PagerDuty/OpsGenie/etc.
    // For the demo, just log and pretend escalation succeeded.
    return true;
  }
}

// ---------------------------------------------------------------------
// Pipeline builder
// ---------------------------------------------------------------------

export interface AlertPipeline {
  handle(alert: Alert): Promise<void>;
  teardown(): Promise<void>;
}

/**
 * Creates a fully wired alert-handling pipeline.
 */
export async function createAlertPipeline(): Promise<AlertPipeline> {
  // --- Kafka -----------------------------------------------------------------
  const kafka = new Kafka({
    clientId: 'pulseSphere-ops',
    brokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    logLevel: KafkaLogLevel.ERROR,
  });
  const kafkaProducer = kafka.producer();
  await kafkaProducer.connect();

  // --- NATS ------------------------------------------------------------------
  const nats = await natsConnect({
    servers: (process.env.NATS_SERVERS || 'nats://localhost:4222').split(','),
  });

  // --- Handlers --------------------------------------------------------------
  const scalingStrategy: ScalingStrategy =
    process.env.SCALING_STRATEGY === 'vertical'
      ? new VerticalScalingStrategy()
      : new HorizontalScalingStrategy();

  const autoScaler = new AutoScalerHandler(scalingStrategy, kafkaProducer);
  const throttler = new ContentThrottlingHandler(nats);
  const commander = new IncidentCommanderHandler();

  autoScaler.setNext(throttler).setNext(commander);

  return {
    handle: async (alert: Alert) => {
      try {
        await autoScaler.handle(alert);
      } catch (err) {
        console.error('[AlertPipeline] Unhandled exception while processing alert:', err);
        // Fallback – always inform human
        await commander.handle(alert);
      }
    },
    teardown: async () => {
      await kafkaProducer.disconnect().catch(() => void 0);
      await nats.drain().catch(() => void 0);
    },
  };
}

// ---------------------------------------------------------------------
// Convenience helpers & mock data for local development
// ---------------------------------------------------------------------

/**
 * Generates a mock alert (useful for local manual testing).
 */
export function generateMockAlert(severity: AlertSeverity = AlertSeverity.CRITICAL): Alert {
  return {
    id: randomUUID(),
    timestamp: new Date(),
    severity,
    message: 'CPU usage exceeded 95% for 3m window',
    metric: 'cpu_usage',
    value: 96,
    threshold: 90,
    social: {
      likesPerMinute: 4200,
      commentsPerMinute: 312,
      sharesPerMinute: 77,
      influencerPresent: true,
    },
  };
}

// ---------------------------------------------------------------------
// If executed directly, spin up the pipeline and process mock alerts.
// ---------------------------------------------------------------------
if (require.main === module) {
  (async () => {
    const pipeline = await createAlertPipeline();

    // Simulate incoming alerts every 5 seconds.
    const interval = setInterval(async () => {
      const mockAlert = generateMockAlert(
        Math.random() > 0.5 ? AlertSeverity.WARNING : AlertSeverity.CRITICAL,
      );
      await pipeline.handle(mockAlert);
    }, 5000);

    // Graceful shutdown
    const shutdown = async () => {
      clearInterval(interval);
      await pipeline.teardown();
      process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
  })().catch((err) => {
    console.error('[Main] Fatal error:', err);
    process.exit(1);
  });
}
```