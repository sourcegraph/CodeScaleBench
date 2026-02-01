```typescript
/**************************************************************************************************
 * PulseSphere SocialOps – Adaptive Threshold Manager                                             *
 * ------------------------------------------------------------------------------------------------
 * File:        src/module_11.ts                                                                  *
 * Description: Dynamically adjusts alert thresholds for infrastructure metrics by weaving        *
 *              real-time social signals (likes, comments, shares, hashtag bursts) into           *
 *              the decision model. Combines Strategy, Observer and Chain-of-Responsibility       *
 *              patterns to (1) calculate adaptive thresholds, (2) observe social-metric events   *
 *              over Kafka, and (3) escalate incidents through multiple notifiers.                *
 *                                                                                                
 * Author:      PulseSphere Engineering Team                                                      *
 **************************************************************************************************/

/* eslint-disable import/order */
import { Kafka, EachMessagePayload } from 'kafkajs';
import { Counter, Gauge, register } from 'prom-client';
import axios from 'axios';
import winston from 'winston';

/* -------------------------------------------------------------------------------------------------
 * Domain Models
 * -------------------------------------------------------------------------------------------------*/

/**
 * A domain event emitted when a social interaction spike is detected.
 */
export interface SocialMetricEvent {
  readonly tenantId: string;            // e.g. 'acme-social'
  readonly metric: 'LIKE' | 'COMMENT' | 'SHARE' | 'STREAM_VIEW';
  readonly delta: number;               // delta per second
  readonly timestamp: number;           // epoch millis
}

/**
 * Infrastructure alert model.
 */
export interface Alert {
  readonly tenantId: string;
  readonly severity: 'INFO' | 'WARN' | 'CRIT';
  readonly metricName: string;          // e.g. 'cpu_usage'
  readonly observedValue: number;
  readonly threshold: number;
  readonly context: Record<string, unknown>;
}

/* -------------------------------------------------------------------------------------------------
 * Logging
 * -------------------------------------------------------------------------------------------------*/

const logger = winston.createLogger({
  level: process.env.LOG_LEVEL ?? 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.errors({ stack: true }),
    winston.format.json(),
  ),
  transports: [
    new winston.transports.Console({ stderrLevels: ['error', 'warn'] }),
  ],
});

/* -------------------------------------------------------------------------------------------------
 * Strategy Pattern – Threshold calculators
 * -------------------------------------------------------------------------------------------------*/

/**
 * Strategy interface for transforming a base threshold.
 */
export interface ThresholdStrategy {
  /**
   * Compute the adjusted threshold based on a social metric event.
   */
  compute(baseThreshold: number, event: SocialMetricEvent): number;
}

/**
 * Boosts threshold proportionally when sudden spikes (virality) occur.
 */
export class TrendingBoostStrategy implements ThresholdStrategy {
  private readonly boostFactor: number;

  constructor(boostFactor = 1.5) {
    this.boostFactor = boostFactor;
  }

  compute(baseThreshold: number, event: SocialMetricEvent): number {
    // Simple heuristic: amplify threshold when delta exceeds 1k events/second.
    if (event.delta > 1_000) {
      const boosted = baseThreshold * this.boostFactor;
      logger.debug(`TrendingBoostStrategy applied: ${baseThreshold} -> ${boosted}`);
      return boosted;
    }
    return baseThreshold;
  }
}

/**
 * Relaxes threshold during off-peak night hours to reduce false positives.
 */
export class NightTimeRelaxStrategy implements ThresholdStrategy {
  constructor(private readonly relaxFactor = 0.8) {}

  private isNightHour(utcMillis: number): boolean {
    const hour = new Date(utcMillis).getUTCHours();
    return hour >= 0 && hour <= 6; // midnight – 6 AM UTC
  }

  compute(baseThreshold: number, event: SocialMetricEvent): number {
    if (this.isNightHour(event.timestamp)) {
      const relaxed = baseThreshold * this.relaxFactor;
      logger.debug(`NightTimeRelaxStrategy applied: ${baseThreshold} -> ${relaxed}`);
      return relaxed;
    }
    return baseThreshold;
  }
}

/* -------------------------------------------------------------------------------------------------
 * Chain-of-Responsibility – Escalation pipeline
 * -------------------------------------------------------------------------------------------------*/

/**
 * Abstract escalation handler.
 */
abstract class EscalationHandler {
  private nextHandler?: EscalationHandler;

  setNext(handler: EscalationHandler): EscalationHandler {
    this.nextHandler = handler;
    return handler;
  }

  async handle(alert: Alert): Promise<void> {
    const processed = await this.process(alert);
    if (!processed && this.nextHandler) {
      await this.nextHandler.handle(alert);
    }
  }

  /**
   * @returns true if handled, false to delegate.
   */
  protected abstract process(alert: Alert): Promise<boolean>;
}

/**
 * Sends alerts to PagerDuty.
 */
class PagerDutyHandler extends EscalationHandler {
  private readonly routingKey: string;

  constructor(routingKey: string) {
    super();
    this.routingKey = routingKey;
  }

  /* c8 ignore next 14 */
  protected async process(alert: Alert): Promise<boolean> {
    if (alert.severity === 'CRIT') {
      try {
        await axios.post('https://events.pagerduty.com/v2/enqueue', {
          routing_key: this.routingKey,
          event_action: 'trigger',
          payload: {
            summary: `CRITICAL alert for ${alert.metricName}`,
            severity: 'critical',
            source: 'PulseSphere',
            custom_details: alert,
          },
        });
        logger.info(`PagerDuty notified for alert=${alert.metricName}`);
        return true;
      } catch (err) {
        logger.error('PagerDuty notification failed', err as Error);
      }
    }
    return false;
  }
}

/**
 * Posts notifications to Slack.
 */
class SlackHandler extends EscalationHandler {
  constructor(private readonly webhookUrl: string) {
    super();
  }

  protected async process(alert: Alert): Promise<boolean> {
    if (alert.severity !== 'INFO') {
      try {
        await axios.post(this.webhookUrl, {
          text: `*${alert.severity}* alert for *${alert.metricName}* ‑ ` +
                `observed=${alert.observedValue}, threshold=${alert.threshold}`,
        });
        logger.info(`Slack notified for alert=${alert.metricName}`);
        return true;
      } catch (err) {
        logger.error('Slack notification failed', err as Error);
      }
    }
    return false;
  }
}

/**
 * Fallback email notifier.
 */
class EmailHandler extends EscalationHandler {
  constructor(private readonly smtpEndpoint: string) {
    super();
  }

  protected async process(alert: Alert): Promise<boolean> {
    // In production we'd integrate with SES, SendGrid, etc.
    try {
      await axios.post(`${this.smtpEndpoint}/send`, {
        to: 'ops@pulsesphere.io',
        subject: `[PulseSphere] ${alert.severity} alert – ${alert.metricName}`,
        body: JSON.stringify(alert, null, 2),
      });
      logger.info(`Email sent for alert=${alert.metricName}`);
      return true;
    } catch (err) {
      logger.error('Email notification failed', err as Error);
      return false;
    }
  }
}

/* -------------------------------------------------------------------------------------------------
 * Observer Pattern – Kafka social metrics consumer
 * -------------------------------------------------------------------------------------------------*/

class KafkaSocialMetricObserver {
  private readonly kafka: Kafka;

  constructor(private readonly brokers: string[], private readonly groupId: string) {
    this.kafka = new Kafka({ clientId: 'social-metric-consumer', brokers });
  }

  /**
   * Subscribes to topic and invokes callback for each message.
   */
  async onEvent(
    topic: string,
    callback: (event: SocialMetricEvent) => Promise<void>,
  ): Promise<void> {
    const consumer = this.kafka.consumer({ groupId: this.groupId });

    await consumer.connect();
    await consumer.subscribe({ topic, fromBeginning: false });

    await consumer.run({
      // 10 concurrent partitions
      eachMessage: async ({ message }: EachMessagePayload) => {
        try {
          if (!message.value) return;
          const parsed: SocialMetricEvent = JSON.parse(message.value.toString());
          await callback(parsed);
        } catch (err) {
          logger.warn('Failed to process social metric event', err as Error);
        }
      },
    });

    logger.info(`KafkaSocialMetricObserver subscribed to ${topic}`);
  }
}

/* -------------------------------------------------------------------------------------------------
 * Adaptive Threshold Manager – Orchestrates strategies & escalations
 * -------------------------------------------------------------------------------------------------*/

export class AdaptiveThresholdManager {
  private readonly strategies: ThresholdStrategy[] = [];
  private readonly escalationChain: EscalationHandler;
  private readonly cpuUsageGauge: Gauge<number>;
  private readonly thresholdGauge: Gauge<number>;
  private readonly alertCounter: Counter;

  constructor(
    escalationChain: EscalationHandler,
    private readonly defaultThreshold: number,
  ) {
    this.escalationChain = escalationChain;

    // Prometheus metrics
    this.cpuUsageGauge = new Gauge({
      name: 'pulsesphere_cpu_usage',
      help: 'Current CPU usage',
      labelNames: ['tenant'],
    });

    this.thresholdGauge = new Gauge({
      name: 'pulsesphere_cpu_threshold',
      help: 'Dynamically calculated CPU threshold',
      labelNames: ['tenant'],
    });

    this.alertCounter = new Counter({
      name: 'pulsesphere_alert_total',
      help: 'Number of alerts emitted',
      labelNames: ['tenant', 'severity'],
    });
  }

  addStrategy(strategy: ThresholdStrategy): AdaptiveThresholdManager {
    this.strategies.push(strategy);
    return this;
  }

  /**
   * Recalculate thresholds using registered strategies.
   */
  private computeThreshold(event: SocialMetricEvent): number {
    return this.strategies.reduce(
      (threshold, strat) => strat.compute(threshold, event),
      this.defaultThreshold,
    );
  }

  /**
   * Simulates reading infra metric (e.g., CPU) from monitoring stack.
   * In production, this would fetch from Prometheus, Datadog, etc.
   */
  /* c8 ignore next */
  private async getCurrentCpuUsage(tenantId: string): Promise<number> {
    // Placeholder random CPU usage for demonstration.
    return Math.random() * 100;
  }

  /**
   * Processes a social metric event → recompute threshold → evaluate infra metrics →
   * possibly trigger alert & escalation.
   */
  async handleSocialEvent(event: SocialMetricEvent): Promise<void> {
    const tenantLabel = { tenant: event.tenantId };
    const threshold = this.computeThreshold(event);
    this.thresholdGauge.set(tenantLabel, threshold);

    const cpuUsage = await this.getCurrentCpuUsage(event.tenantId);
    this.cpuUsageGauge.set(tenantLabel, cpuUsage);

    if (cpuUsage > threshold) {
      const severity: Alert['severity'] = cpuUsage > threshold * 1.2 ? 'CRIT' : 'WARN';

      const alert: Alert = {
        tenantId: event.tenantId,
        severity,
        metricName: 'cpu_usage',
        observedValue: cpuUsage,
        threshold,
        context: { socialMetric: event },
      };

      this.alertCounter.inc({ ...tenantLabel, severity });
      logger.warn(
        `Alert triggered tenant=${event.tenantId} cpu=${cpuUsage.toFixed(2)} ` +
        `threshold=${threshold.toFixed(2)} severity=${severity}`,
      );

      await this.escalationChain.handle(alert);
    } else {
      logger.debug(
        `CPU within threshold tenant=${event.tenantId} cpu=${cpuUsage.toFixed(2)} ` +
        `threshold=${threshold.toFixed(2)}`,
      );
    }
  }
}

/* -------------------------------------------------------------------------------------------------
 * Bootstrap – wire everything together if executed directly
 * -------------------------------------------------------------------------------------------------*/

if (require.main === module) {
  (async () => {
    try {
      // Build escalation chain: PagerDuty → Slack → Email
      const pagerDuty = new PagerDutyHandler(process.env.PAGERDUTY_KEY ?? 'dummy');
      const slack = new SlackHandler(process.env.SLACK_WEBHOOK ?? 'https://hooks.slack.com/services/dummy');
      const email = new EmailHandler(process.env.SMTP_ENDPOINT ?? 'https://smtp.internal');
      pagerDuty.setNext(slack).setNext(email);

      // Instantiate manager with strategies
      const manager = new AdaptiveThresholdManager(pagerDuty, 75 /* default CPU threshold */)
        .addStrategy(new TrendingBoostStrategy())
        .addStrategy(new NightTimeRelaxStrategy());

      // Observer listens to Kafka topic
      const observer = new KafkaSocialMetricObserver(
        (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
        'adaptive-threshold-group',
      );

      await observer.onEvent('social-metrics', (evt) => manager.handleSocialEvent(evt));

      // Expose Prometheus endpoint
      const port = Number(process.env.METRICS_PORT ?? 9100);
      /* eslint-disable @typescript-eslint/no-var-requires */
      const http = require('http');
      http.createServer((_, res) => {
        res.writeHead(200, { 'Content-Type': register.contentType });
        register.metrics().then((m: string) => res.end(m));
      }).listen(port, () => logger.info(`Metrics exposed on :${port}/`));
    } catch (err) {
      logger.error('Failed to bootstrap AdaptiveThresholdManager', err as Error);
      process.exit(1);
    }
  })();
}
```
