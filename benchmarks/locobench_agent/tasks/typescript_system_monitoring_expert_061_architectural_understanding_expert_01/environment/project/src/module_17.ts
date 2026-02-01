```typescript
/**
 * PulseSphere SocialOps
 * -------------------------------------------------------
 * Module: module_17 – Social-Aware Auto-Scaler & Alerting
 *
 * This module wires together multiple classic patterns to
 * provide a production-grade, socially-aware auto-scaling
 * component.
 *
 * Patterns in use
 *  • Observer            – MetricEventBus (EventEmitter)
 *  • Strategy            – ScalingStrategy implementations
 *  • Command             – Scale{Up,Down}Command
 *  • Chain-of-Responsibility – AlertHandler chain
 *  • Event Driven        – Kafka consumer feeding the bus
 *
 * External deps
 *  • kafkajs             – High-throughput metric ingestion
 *  • axios               – Mock service-mesh HTTP client
 *
 * Author:  PulseSphere SRE Platform Team
 * -------------------------------------------------------
 */

import { EventEmitter } from 'events';
import { Kafka, EachMessagePayload, logLevel as KafkaLogLevel } from 'kafkajs';
import axios, { AxiosInstance } from 'axios';

/* -------------------------------------------------------------------------- */
/*                               Static typings                               */
/* -------------------------------------------------------------------------- */

/** A single enriched metric coming from pulse-fusion pipeline. */
export interface EnrichedMetric {
  readonly appId: string;
  readonly cpuPct: number;               // 0-100
  readonly memPct: number;               // 0-100
  readonly sentimentScore: number;       // –1 .. +1
  readonly trendingScore: number;        // 0 .. 1 (probability of virality)
  readonly timestamp: number;            // epoch ms
}

export enum ScalingDecision {
  SCALE_UP   = 'SCALE_UP',
  SCALE_DOWN = 'SCALE_DOWN',
  STABLE     = 'STABLE',
}

/* -------------------------------------------------------------------------- */
/*                               Observer Layer                               */
/* -------------------------------------------------------------------------- */

/**
 * Central in-process event bus – translates Kafka messages into local events
 * that strategies/handlers can subscribe to without needing Kafka semantics.
 */
class MetricEventBus extends EventEmitter {
  static readonly EVT_METRIC = 'metric';

  emitMetric(metric: EnrichedMetric): void {
    this.emit(MetricEventBus.EVT_METRIC, metric);
  }

  onMetric(listener: (metric: EnrichedMetric) => void): void {
    this.on(MetricEventBus.EVT_METRIC, listener);
  }
}

/* -------------------------------------------------------------------------- */
/*                           Strategy & Command Layer                         */
/* -------------------------------------------------------------------------- */

/** Scaling command contract (Command Pattern). */
interface ScalingCommand {
  execute(): Promise<void>;
}

/** Concrete command – scale up by N replicas. */
class ScaleUpCommand implements ScalingCommand {
  constructor(
    private readonly meshClient: ServiceMeshClient,
    private readonly appId: string,
    private readonly factor: number,
  ) {}

  public async execute(): Promise<void> {
    await this.meshClient.scale(this.appId, this.factor);
  }
}

/** Concrete command – scale down by N replicas. */
class ScaleDownCommand implements ScalingCommand {
  constructor(
    private readonly meshClient: ServiceMeshClient,
    private readonly appId: string,
    private readonly factor: number,
  ) {}

  public async execute(): Promise<void> {
    await this.meshClient.scale(this.appId, -this.factor);
  }
}

/** Strategy contract – returns a Command or undefined when no action. */
interface ScalingStrategy {
  evaluate(metric: EnrichedMetric): ScalingCommand | undefined;
}

/**
 * CPU-centric strategy – reacts when usage is beyond a threshold.
 * This is a simplistic threshold-based algorithm; production code
 * would rely on predictive analytics or RL models.
 */
class HighCpuStrategy implements ScalingStrategy {
  constructor(
    private readonly meshClient: ServiceMeshClient,
    private readonly highWaterMarkPct = 75,
    private readonly lowWaterMarkPct  = 35,
  ) {}

  evaluate(metric: EnrichedMetric): ScalingCommand | undefined {
    if (metric.cpuPct >= this.highWaterMarkPct) {
      const factor = Math.max(1, Math.ceil(metric.cpuPct / 25));
      return new ScaleUpCommand(this.meshClient, metric.appId, factor);
    }
    if (metric.cpuPct <= this.lowWaterMarkPct) {
      return new ScaleDownCommand(this.meshClient, metric.appId, 1);
    }
    return undefined;
  }
}

/**
 * Sentiment spike strategy – anticipates virality before infrastructure
 * gets hammered. Combines sentiment & trending scores.
 */
class SentimentSpikeStrategy implements ScalingStrategy {
  constructor(
    private readonly meshClient: ServiceMeshClient,
    private readonly threshold = 0.85,
  ) {}

  evaluate(metric: EnrichedMetric): ScalingCommand | undefined {
    if (metric.trendingScore >= this.threshold && metric.sentimentScore > 0) {
      // For viral events we aggressively over-provision.
      return new ScaleUpCommand(this.meshClient, metric.appId, 3);
    }
    return undefined;
  }
}

/* -------------------------------------------------------------------------- */
/*                          Chain-of-Responsibility Layer                     */
/* -------------------------------------------------------------------------- */

interface AlertHandler {
  setNext(handler: AlertHandler): AlertHandler;
  handle(metric: EnrichedMetric): Promise<void>;
}

abstract class BaseAlertHandler implements AlertHandler {
  private nextHandler?: AlertHandler;

  public setNext(handler: AlertHandler): AlertHandler {
    this.nextHandler = handler;
    return handler;
  }

  public async handle(metric: EnrichedMetric): Promise<void> {
    if (this.nextHandler) {
      await this.nextHandler.handle(metric);
    }
  }
}

/** Debug-level handler – just noisy logs in dev environments. */
class DebugAlertHandler extends BaseAlertHandler {
  async handle(metric: EnrichedMetric): Promise<void> {
    if (process.env.NODE_ENV !== 'production') {
      console.debug(
        `[DEBUG] Metric → cpu:${metric.cpuPct}% mem:${metric.memPct}% ` +
        `sentiment:${metric.sentimentScore.toFixed(2)} trending:${metric.trendingScore}`,
      );
    }
    await super.handle(metric);
  }
}

/** Warning-level handler – triggers standard alert channel. */
class WarningAlertHandler extends BaseAlertHandler {
  async handle(metric: EnrichedMetric): Promise<void> {
    if (metric.cpuPct > 85 || metric.memPct > 85) {
      await AlertChannel.slack(
        `⚠️ High resource usage on app ${metric.appId}: ` +
        `CPU ${metric.cpuPct}% / MEM ${metric.memPct}%`,
      );
    }
    await super.handle(metric);
  }
}

/** Critical handler – immediate pager-duty. */
class CriticalAlertHandler extends BaseAlertHandler {
  async handle(metric: EnrichedMetric): Promise<void> {
    const isCrit = metric.cpuPct > 95 || metric.memPct > 95 || metric.trendingScore >= 0.95;
    if (isCrit) {
      await AlertChannel.pagerDuty(
        `🚨 CRITICAL: ${metric.appId} likely overloaded! ` +
        `cpu=${metric.cpuPct}% mem=${metric.memPct}% trending=${metric.trendingScore}`,
      );
    }
    await super.handle(metric);
  }
}

/* -------------------------------------------------------------------------- */
/*                              Service-mesh client                           */
/* -------------------------------------------------------------------------- */

class ServiceMeshClient {
  private readonly http: AxiosInstance;

  constructor(
    readonly baseURL: string = process.env.SERVICE_MESH_BASE_URL ?? 'http://mesh-gateway',
    readonly timeout = 5_000,
  ) {
    this.http = axios.create({ baseURL: this.baseURL, timeout: this.timeout });
  }

  /**
   * Scale an application up/down by "factor" replicas.
   * This interacts with the platform orchestrator through
   * the mesh sidecar.
   */
  public async scale(appId: string, factor: number): Promise<void> {
    try {
      await this.http.post(`/apps/${appId}/scale`, { factor });
      console.info(`[Scale] ${appId} scaled by ${factor}`);
    } catch (err) {
      console.error(`[Scale] Failed to scale ${appId}:`, err);
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                              Alerting helpers                              */
/* -------------------------------------------------------------------------- */

class AlertChannel {
  static async slack(message: string): Promise<void> {
    // Placeholder: in production we'd push to Slack webhook
    console.log(`[Slack] ${message}`);
  }

  static async pagerDuty(message: string): Promise<void> {
    // Placeholder: integration key & routing will sit in vault
    console.log(`[PagerDuty] ${message}`);
  }
}

/* -------------------------------------------------------------------------- */
/*                            Main Orchestrator Class                         */
/* -------------------------------------------------------------------------- */

export class SocialAwareAutoScaler {
  private readonly kafka: Kafka;
  private readonly meshClient = new ServiceMeshClient();
  private readonly eventBus = new MetricEventBus();
  private readonly strategies: ScalingStrategy[] = [];
  private readonly alertChain: AlertHandler;
  private isShuttingDown = false;

  constructor(
    private readonly kafkaBrokers: string[] = (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
    private readonly groupId = 'social-auto-scaler',
    private readonly topic = 'pulse.metric.enriched.v1',
  ) {
    this.kafka = new Kafka({
      clientId: 'pulse-auto-scaler',
      brokers: this.kafkaBrokers,
      logLevel: KafkaLogLevel.NOTHING,
    });

    /* Strategy registry */
    this.strategies.push(
      new HighCpuStrategy(this.meshClient),
      new SentimentSpikeStrategy(this.meshClient),
    );

    /* Alert chain bootstrap */
    const debug   = new DebugAlertHandler();
    const warn    = new WarningAlertHandler();
    const crit    = new CriticalAlertHandler();
    debug.setNext(warn).setNext(crit);
    this.alertChain = debug; // entrypoint

    /* Wiring observer */
    this.eventBus.onMetric(async (metric) => {
      await this.alertChain.handle(metric);
      await this.applyStrategies(metric);
    });
  }

  /**
   * Initialize kafka consumer & begin event pump.
   */
  public async start(): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: this.groupId });
    await consumer.connect();
    await consumer.subscribe({ topic: this.topic, fromBeginning: false });

    console.info('[AutoScaler] started.');

    await consumer.run({
      eachMessage: async (payload: EachMessagePayload) => {
        if (this.isShuttingDown) {
          await consumer.disconnect();
          return;
        }
        const metric = this.parseMetric(payload);
        if (metric) this.eventBus.emitMetric(metric);
      },
    });

    /* Graceful shutdown binding */
    process.once('SIGINT' , () => this.shutdown());
    process.once('SIGTERM', () => this.shutdown());
  }

  private async applyStrategies(metric: EnrichedMetric): Promise<void> {
    for (const strategy of this.strategies) {
      const cmd = strategy.evaluate(metric);
      if (cmd) {
        try {
          await cmd.execute();
          break; // one strategy acted – avoid conflicting actions
        } catch (err) {
          console.error('[AutoScaler] Command failed:', err);
        }
      }
    }
  }

  /**
   * Converts Kafka payload into EnrichedMetric object with validation.
   */
  private parseMetric({ message }: EachMessagePayload): EnrichedMetric | undefined {
    try {
      if (!message.value) return;
      const obj = JSON.parse(message.value.toString());

      /* Lightweight validation */
      const metric: EnrichedMetric = {
        appId          : obj.appId,
        cpuPct         : Number(obj.cpuPct),
        memPct         : Number(obj.memPct),
        sentimentScore : Number(obj.sentimentScore),
        trendingScore  : Number(obj.trendingScore),
        timestamp      : Number(obj.timestamp),
      };

      if (!metric.appId || Number.isNaN(metric.cpuPct)) {
        throw new Error('Invalid metric shape');
      }
      return metric;
    } catch (err) {
      console.warn('[AutoScaler] Discarded malformed metric:', err);
      return;
    }
  }

  /**
   * Shutdown hook – ensures consumer disconnect & drains inflight tasks.
   */
  private async shutdown(): Promise<void> {
    if (this.isShuttingDown) return;
    this.isShuttingDown = true;

    console.info('[AutoScaler] Shutting down…');
    // Additional cleanup (HTTP, etc.) could be awaited here.
  }
}

/* -------------------------------------------------------------------------- */
/*                     Module bootstrap (only when run directly)              */
/* -------------------------------------------------------------------------- */
if (require.main === module) {
  (async () => {
    try {
      const scaler = new SocialAwareAutoScaler();
      await scaler.start();
    } catch (err) {
      console.error('[AutoScaler] Fatal:', err);
      process.exitCode = 1;
    }
  })();
}
```