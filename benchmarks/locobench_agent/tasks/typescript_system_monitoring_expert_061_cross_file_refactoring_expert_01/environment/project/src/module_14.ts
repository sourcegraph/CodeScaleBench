```typescript
/***************************************************************************************************
 *  PulseSphere SocialOps – src/module_14.ts
 *
 *  Module 14: Social-Aware Alert Orchestrator
 *  -----------------------------------------
 *  Implements a Chain-of-Responsibility that reacts to enriched metrics (infrastructure + social
 *  signals) and decides—via pluggable Strategy objects—how to mitigate incidents in real-time.
 *
 *  Key patterns & responsibilities:
 *    • Chain-of-Responsibility – AlertHandlers (scale-out, cache-purge, notify, …)
 *    • Strategy               – ScalingStrategy (K8s HPA, ServiceMesh override, etc.)
 *    • Observer               – AlertListeners for dashboards / paging
 *    • Event-Driven           – Consumes Kafka topics, publishes NATS events
 *    • Config-Mgmt            – Centralised runtime configuration
 *
 *  External deps:
 *    • kafkajs                 (Kafka client)
 *    • node-nats-streaming     (NATS streaming)
 *    • winston                 (structured logging)
 *
 *  NOTE: Module is self-contained; integration points marked with TODO for other services.
 ***************************************************************************************************/

import { Kafka, Producer, Consumer } from 'kafkajs';
import * as NATS from 'node-nats-streaming';
import * as winston from 'winston';
import { v4 as uuid } from 'uuid';

/**
 * -----------------------------------------------------------------------------------------------
 *  Configuration
 * -----------------------------------------------------------------------------------------------
 */

class ConfigManager {
  private static _instance: ConfigManager;

  private readonly config: {
    kafkaBrokers: string[];
    kafkaTopic: string;
    natsClusterId: string;
    natsClientId: string;
    natsSubject: string;
    scaleOutThreshold: number; // e.g., CPU 80%
    viralTrendingScore: number; // social virality threshold 0-100
  };

  private constructor() {
    this.config = {
      kafkaBrokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
      kafkaTopic: process.env.KAFKA_TOPIC || 'pulsesphere.telemetry',
      natsClusterId: process.env.NATS_CLUSTER_ID || 'pulsesphere',
      natsClientId: process.env.NATS_CLIENT_ID || `alert-orch_${uuid()}`,
      natsSubject: process.env.NATS_SUBJECT || 'pulsesphere.alerts',
      scaleOutThreshold: Number(process.env.SCALE_OUT_THRESHOLD || 80),
      viralTrendingScore: Number(process.env.VIRAL_TRENDING_SCORE || 70)
    };
  }

  static get instance(): ConfigManager {
    if (!ConfigManager._instance) {
      ConfigManager._instance = new ConfigManager();
    }
    return ConfigManager._instance;
  }

  get<T extends keyof ConfigManager['config']>(key: T): ConfigManager['config'][T] {
    return this.config[key];
  }
}

/**
 * -----------------------------------------------------------------------------------------------
 *  Logging
 * -----------------------------------------------------------------------------------------------
 */

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.json()
  ),
  transports: [
    new winston.transports.Console()
  ]
});

/**
 * -----------------------------------------------------------------------------------------------
 *  Domain objects
 * -----------------------------------------------------------------------------------------------
 */

interface SocialSignals {
  likes: number;
  comments: number;
  shares: number;
  activeViewers: number;
  trendingScore: number; // 0-100
}

interface InfraMetrics {
  cpu: number;      // %
  memory: number;   // %
  latency: number;  // ms
  errorRate: number; // %
}

export interface EnrichedMetric {
  timestamp: number;
  service: string;
  infra: InfraMetrics;
  social: SocialSignals;
}

export enum AlertSeverity {
  LOW = 'LOW',
  MEDIUM = 'MEDIUM',
  HIGH = 'HIGH',
  CRITICAL = 'CRITICAL'
}

export class Alert {
  readonly id: string = uuid();
  readonly generatedAt: number = Date.now();

  constructor(
    public readonly service: string,
    public readonly severity: AlertSeverity,
    public readonly metric: EnrichedMetric,
    public readonly message: string
  ) {}
}

/**
 * -----------------------------------------------------------------------------------------------
 *  Observer – Listeners that react to an alert (dashboards, incident responders, etc.)
 * -----------------------------------------------------------------------------------------------
 */

export interface AlertListener {
  onAlert(alert: Alert): Promise<void>;
}

class NatsAlertPublisher implements AlertListener {
  private stan?: NATS.Stan;

  constructor(
    private readonly clusterId = ConfigManager.instance.get('natsClusterId'),
    private readonly clientId = ConfigManager.instance.get('natsClientId'),
    private readonly subject = ConfigManager.instance.get('natsSubject')
  ) {}

  async init(): Promise<void> {
    this.stan = NATS.connect(this.clusterId, this.clientId, { url: 'nats://localhost:4222' });

    return new Promise((resolve, reject) => {
      this.stan!.on('connect', () => {
        logger.info('Connected to NATS', { clusterId: this.clusterId, clientId: this.clientId });
        resolve();
      });
      this.stan!.on('error', (err) => {
        logger.error('Failed to connect to NATS', { error: err });
        reject(err);
      });
    });
  }

  async onAlert(alert: Alert): Promise<void> {
    if (!this.stan) {
      await this.init();
    }

    return new Promise((resolve, reject) => {
      this.stan!.publish(this.subject, JSON.stringify(alert), (err, guid) => {
        if (err) {
          logger.error('Error publishing alert to NATS', { err });
          return reject(err);
        }
        logger.info('Alert published to NATS', { guid, alertId: alert.id });
        resolve();
      });
    });
  }
}

/**
 * -----------------------------------------------------------------------------------------------
 *  Strategy – Scaling strategies can be swapped dynamically
 * -----------------------------------------------------------------------------------------------
 */

interface ScalingStrategy {
  scale(service: string, factor: number): Promise<void>;
}

class KubernetesHpaScaler implements ScalingStrategy {
  async scale(service: string, factor: number): Promise<void> {
    try {
      // TODO: Integrate with official k8s client. Placeholder below.
      logger.info('K8s HPA scaling executed', { service, factor });
    } catch (err) {
      logger.error('K8s scaling error', { err });
      throw err;
    }
  }
}

class ServiceMeshRateLimiterScaler implements ScalingStrategy {
  async scale(service: string, factor: number): Promise<void> {
    try {
      // TODO: Call service mesh API to rate-limit or reroute traffic
      logger.info('ServiceMesh scaling executed', { service, factor });
    } catch (err) {
      logger.error('ServiceMesh scaling error', { err });
      throw err;
    }
  }
}

/**
 * -----------------------------------------------------------------------------------------------
 *  Chain-of-Responsibility – Alert handling pipeline
 * -----------------------------------------------------------------------------------------------
 */

abstract class AlertHandler {
  protected next?: AlertHandler;
  protected listeners: AlertListener[] = [];

  setNext(handler: AlertHandler): AlertHandler {
    this.next = handler;
    return handler;
  }

  attachListener(listener: AlertListener): void {
    this.listeners.push(listener);
  }

  async handle(alert: Alert): Promise<void> {
    const processed = await this.process(alert);
    if (!processed && this.next) {
      await this.next.handle(alert);
    }
  }

  protected async notifyListeners(alert: Alert): Promise<void> {
    await Promise.all(this.listeners.map(l => l.onAlert(alert).catch(err => {
      logger.error('AlertListener failed', { listener: l.constructor.name, err });
    })));
  }

  protected abstract process(alert: Alert): Promise<boolean>;
}

class ScaleOutHandler extends AlertHandler {
  private readonly strategy: ScalingStrategy;

  constructor(strategy: ScalingStrategy) {
    super();
    this.strategy = strategy;
  }

  protected async process(alert: Alert): Promise<boolean> {
    const threshold = ConfigManager.instance.get('scaleOutThreshold');

    if (alert.metric.infra.cpu >= threshold || alert.metric.social.trendingScore >= ConfigManager.instance.get('viralTrendingScore')) {
      const factor = CalculateScaleFactor(alert.metric);
      logger.info('ScaleOutHandler triggered', { service: alert.service, factor });
      await this.strategy.scale(alert.service, factor);
      await this.notifyListeners(alert);
      return true;
    }
    return false;
  }
}

class CachePurgeHandler extends AlertHandler {
  protected async process(alert: Alert): Promise<boolean> {
    if (alert.metric.infra.errorRate > 10) {
      try {
        // TODO: Cache invalidation integration
        logger.info('Cache purge triggered', { service: alert.service });
        await this.notifyListeners(alert);
      } catch (err) {
        logger.error('Cache purge failed', { err });
      }
      return true;
    }
    return false;
  }
}

class NotificationHandler extends AlertHandler {
  protected async process(alert: Alert): Promise<boolean> {
    // Always notify as last resort
    logger.info('NotificationHandler dispatch', { alertId: alert.id, severity: alert.severity });
    await this.notifyListeners(alert);
    return true;
  }
}

/**
 * -----------------------------------------------------------------------------------------------
 *  Helper functions
 * -----------------------------------------------------------------------------------------------
 */

function CalculateScaleFactor(metric: EnrichedMetric): number {
  // Simple proportional algorithm – can be replaced by ML model
  const cpuFactor = metric.infra.cpu / 80;
  const socialFactor = metric.social.trendingScore / 70;
  return Math.max(cpuFactor, socialFactor, 1.0);
}

function determineSeverity(metric: EnrichedMetric): AlertSeverity {
  const { cpu, errorRate } = metric.infra;
  const { trendingScore } = metric.social;

  if (cpu > 90 || errorRate > 20 || trendingScore > 90) {
    return AlertSeverity.CRITICAL;
  }
  if (cpu > 80 || errorRate > 15 || trendingScore > 80) {
    return AlertSeverity.HIGH;
  }
  if (cpu > 70 || errorRate > 10 || trendingScore > 70) {
    return AlertSeverity.MEDIUM;
  }
  return AlertSeverity.LOW;
}

/**
 * -----------------------------------------------------------------------------------------------
 *  Kafka Consumer – transforms EnrichedMetric events into Alerts
 * -----------------------------------------------------------------------------------------------
 */

class MetricConsumer {
  private readonly kafka: Kafka;
  private readonly consumer: Consumer;
  private readonly topic = ConfigManager.instance.get('kafkaTopic');
  private started = false;

  constructor(private readonly alertChain: AlertHandler) {
    this.kafka = new Kafka({ brokers: ConfigManager.instance.get('kafkaBrokers') });
    this.consumer = this.kafka.consumer({ groupId: 'alert-orchestrator' });
  }

  async start(): Promise<void> {
    if (this.started) return;
    await this.consumer.connect();
    await this.consumer.subscribe({ topic: this.topic, fromBeginning: false });

    await this.consumer.run({
      eachMessage: async ({ message }) => {
        try {
          if (!message.value) return;
          const metric: EnrichedMetric = JSON.parse(message.value.toString('utf8'));

          logger.debug('Metric received', { metric });

          const severity = determineSeverity(metric);
          if (severity === AlertSeverity.LOW) return; // Ignore noise

          const alert = new Alert(metric.service, severity, metric, 'Auto-generated alert');
          await this.alertChain.handle(alert);
        } catch (err) {
          logger.error('Failed to process metric message', { err });
        }
      }
    });

    this.started = true;
    logger.info('Metric consumer started');
  }

  async stop(): Promise<void> {
    if (!this.started) return;
    await this.consumer.disconnect();
    this.started = false;
  }
}

/**
 * -----------------------------------------------------------------------------------------------
 *  Bootstrap
 * -----------------------------------------------------------------------------------------------
 */

async function bootstrap(): Promise<void> {
  // Build chain
  const scaleOut = new ScaleOutHandler(new KubernetesHpaScaler());
  const cachePurge = new CachePurgeHandler();
  const notify = new NotificationHandler();

  scaleOut.setNext(cachePurge).setNext(notify);

  // Attach listeners
  const natsPublisher = new NatsAlertPublisher();
  scaleOut.attachListener(natsPublisher);
  cachePurge.attachListener(natsPublisher);
  notify.attachListener(natsPublisher);

  // Start consuming metrics
  const consumer = new MetricConsumer(scaleOut);

  process.on('SIGINT', async () => {
    logger.info('SIGINT received. Graceful shutdown.');
    await consumer.stop();
    process.exit(0);
  });

  try {
    await consumer.start();
  } catch (err) {
    logger.error('Failed to start MetricConsumer', { err });
    process.exit(1);
  }
}

bootstrap().catch(err => {
  logger.error('Unhandled bootstrap error', { err });
  process.exit(1);
});
```