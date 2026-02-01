```typescript
/**************************************************************************************************
 *  File:        src/module_31.ts
 *  Project:     PulseSphere SocialOps – system_monitoring
 *  Description: Correlates low-level infrastructure metrics with real-time social-interaction
 *               signals in order to detect anomalies that are likely to impact user experience
 *               during viral traffic spikes.  The module listens to:
 *                 • Kafka   – infrastructure metrics topic
 *                 • NATS    – social-signal subject (likes/comments/shares/streams)
 *               and produces:
 *                 • Alert events via the internal AlertPublisher (fan-out to PagerDuty, Slack…)
 *
 *  Architectural patterns showcased:
 *     • Observer Pattern – RxJS observable streams
 *     • Strategy Pattern – pluggable anomaly-detection algorithms
 *     • Chain-of-Responsibility – strategies executed until one raises an alert
 *
 *  NOTE: All concrete implementations are self-contained to keep the example runnable in
 *        isolation. Replace stubs with your own infrastructure-specific classes as needed.
 **************************************************************************************************/

/* ────────────────────────────────────────── External Dependencies ───────────────────────────── */
import { Kafka, EachMessagePayload } from 'kafkajs';
import { connect, NatsConnection, Subscription } from 'nats';
import {
  bufferTime,
  filter,
  map,
  merge,
  Observable,
  Subject,
  withLatestFrom,
} from 'rxjs';

/* ────────────────────────────────────────────── Types ────────────────────────────────────────── */
export interface MetricEvent {
  timestamp: number;       // epoch-ms
  host: string;            // e.g. ip-10-1-1-42
  metric: string;          // e.g. cpu_load
  value: number;           // e.g. 0.88
}

export interface SocialSignalEvent {
  timestamp: number;       // epoch-ms
  signal: 'like' | 'comment' | 'share' | 'view';
  count: number;           // delta since previous sample
  topic: string;           // hashtag / live-stream id / post id
}

export interface CombinedEvent extends MetricEvent {
  socialDelta: number;     // count of social-interaction deltas in the correlation window
}

export interface AnomalyAlert {
  timestamp: number;
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  reason: string;
  meta: Record<string, unknown>;
}

/* ─────────────────────────────────────── Logger (local stub) ────────────────────────────────── */
class Logger {
  constructor(private scope: string) {}
  info(msg: string, ...rest: unknown[]): void  { console.info (`[INFO] [${this.scope}]`, msg, ...rest); }
  warn(msg: string, ...rest: unknown[]): void  { console.warn (`[WARN] [${this.scope}]`, msg, ...rest); }
  error(msg: string, ...rest: unknown[]): void { console.error(`[ERR ] [${this.scope}]`, msg, ...rest); }
}

/* ───────────────────────────────────── Alert Publisher (stub) ───────────────────────────────── */
class AlertPublisher {
  constructor(private readonly cfg: Config['alerting'], private readonly logger: Logger) {}

  /**
   * Fan-out alert to any configured integrations (PagerDuty, Slack, etc.).
   * In production this should be async/non-blocking to avoid back-pressure on detectors.
   */
  async publish(alert: AnomalyAlert): Promise<void> {
    try {
      // Replace console with real integrations (HTTP POST, gRPC, etc.)
      this.logger.warn(`Dispatching alert ⇒ ${alert.severity}: ${alert.reason}`, alert.meta);
    } catch (err) {
      this.logger.error('Failed to publish alert', err);
    }
  }
}

/* ──────────────────────────────── Runtime Configuration Loader ──────────────────────────────── */
class Config {
  /* Centralised configuration shape */
  public kafkaBrokers: string[];
  public metricTopic: string;
  public natsServers: string;
  public socialSubject: string;

  public bufferWindowMs: number;
  public zScoreThreshold: number;
  public zScoreWindow: number;
  public cpuThreshold: number;
  public memThreshold: number;

  public alerting: {
    slackWebhook?: string;
    pagerDutyKey?: string;
  };

  /* Hydrate configuration from environment variables */
  static loadFromEnv(): Config {
    const cfg = new Config();
    cfg.kafkaBrokers   = (process.env.PS_KAFKA_BROKERS ?? 'localhost:9092').split(',');
    cfg.metricTopic    = process.env.PS_KAFKA_METRIC_TOPIC      ?? 'infra.metrics';
    cfg.natsServers    = process.env.PS_NATS_SERVERS            ?? 'nats://localhost:4222';
    cfg.socialSubject  = process.env.PS_NATS_SOCIAL_SUBJECT     ?? 'social.signals';

    cfg.bufferWindowMs = +(process.env.PS_BUFFER_WINDOW_MS      ?? 15_000);
    cfg.zScoreThreshold= +(process.env.PS_ZSCORE_THRESHOLD      ?? 3);
    cfg.zScoreWindow   = +(process.env.PS_ZSCORE_WINDOW         ?? 20);
    cfg.cpuThreshold   = +(process.env.PS_CPU_THRESHOLD         ?? 0.90);
    cfg.memThreshold   = +(process.env.PS_MEM_THRESHOLD         ?? 0.90);

    cfg.alerting = {
      slackWebhook : process.env.PS_ALERT_SLACK_WEBHOOK,
      pagerDutyKey : process.env.PS_ALERT_PD_KEY,
    };

    return cfg;
  }
}

/* ─────────────────────────────── Strategy-Pattern Interfaces ──────────────────────────────── */
interface AnomalyDetectionStrategy {
  /** Return list of alerts generated for the given time-window */
  detect(window: ReadonlyArray<CombinedEvent>): AnomalyAlert[];
}

/* ────────────────────────────── Concrete Strategy: Z-Score (generic) ────────────────────────── */
class ZScoreStrategy implements AnomalyDetectionStrategy {
  private readonly history: number[] = [];

  constructor(
    private readonly threshold: number, // e.g. 3 ⇒ ±3σ
    private readonly windowSize: number,
    private readonly logger: Logger,
  ) {}

  detect(window: ReadonlyArray<CombinedEvent>): AnomalyAlert[] {
    const alerts: AnomalyAlert[] = [];

    // Track only metric values; keep ring-buffer of last N
    for (const ev of window) {
      this.history.push(ev.value);
      if (this.history.length > this.windowSize) this.history.shift();

      if (this.history.length < this.windowSize) continue; // not enough data yet

      const mean = this.history.reduce((a, b) => a + b, 0) / this.history.length;
      const variance =
        this.history.reduce((a, b) => a + (b - mean) ** 2, 0) / this.history.length;
      const stdDev = Math.sqrt(variance);

      // Avoid divide-by-0
      if (stdDev === 0) continue;

      const zScore = (ev.value - mean) / stdDev;
      if (Math.abs(zScore) >= this.threshold) {
        // escalate severity if social delta is simultaneously high
        const severity: AnomalyAlert['severity'] =
          ev.socialDelta > 50
            ? 'HIGH'
            : Math.abs(zScore) > this.threshold * 1.5
            ? 'MEDIUM'
            : 'LOW';

        alerts.push({
          timestamp: Date.now(),
          severity,
          reason: `Metric ${ev.metric} on ${ev.host} outlier – z=${zScore.toFixed(
            2,
          )}, socialDelta=${ev.socialDelta}`,
          meta: { host: ev.host, metric: ev.metric, value: ev.value, zScore },
        });
      }
    }

    if (alerts.length) {
      this.logger.info(`Z-Score detected ${alerts.length} alert(s)`);
    }
    return alerts;
  }
}

/* ─────────────── Concrete Strategy: Static Thresholds w/ Social Amplification ──────────────── */
class ThresholdStrategy implements AnomalyDetectionStrategy {
  constructor(
    private readonly cpuThreshold: number,
    private readonly memThreshold: number,
    private readonly logger: Logger,
  ) {}

  detect(window: ReadonlyArray<CombinedEvent>): AnomalyAlert[] {
    const alerts: AnomalyAlert[] = [];

    for (const ev of window) {
      if (
        (ev.metric === 'cpu_load' && ev.value >= this.cpuThreshold) ||
        (ev.metric === 'mem_util' && ev.value >= this.memThreshold)
      ) {
        const severity: AnomalyAlert['severity'] =
          ev.socialDelta > 100 ? 'HIGH' : 'MEDIUM';

        alerts.push({
          timestamp: Date.now(),
          severity,
          reason: `Threshold exceeded: ${ev.metric}=${(ev.value * 100).toFixed(1)}%`,
          meta: { host: ev.host, metric: ev.metric, value: ev.value, socialDelta: ev.socialDelta },
        });
      }
    }

    if (alerts.length) {
      this.logger.info(`ThresholdStrategy detected ${alerts.length} alert(s)`);
    }
    return alerts;
  }
}

/* ───────────────────────────── Detector (Delegates to Strategies) ───────────────────────────── */
class SocialSentimentAnomalyDetector {
  constructor(
    private readonly strategies: AnomalyDetectionStrategy[],
    private readonly alertPublisher: AlertPublisher,
    private readonly logger: Logger,
  ) {}

  async analyze(window: ReadonlyArray<CombinedEvent>): Promise<void> {
    try {
      for (const strategy of this.strategies) {
        const alerts = strategy.detect(window);
        for (const alert of alerts) {
          await this.alertPublisher.publish(alert);
          // Chain-of-Responsibility: stop evaluating subsequent strategies if one fires a HIGH alert.
          if (alert.severity === 'HIGH') return;
        }
      }
    } catch (err) {
      this.logger.error('Failed to analyse window', err);
    }
  }
}

/* ─────────────────────────────────────── Stream Bootstrapper ───────────────────────────────── */
export async function startSentimentAnomalyDetector(): Promise<void> {
  const cfg     = Config.loadFromEnv();
  const logger  = new Logger('SentimentDetector');
  const alerts  = new AlertPublisher(cfg.alerting, logger);

  /* ––––– Kafka (Infrastructure Metrics) ––––– */
  const kafka         = new Kafka({ clientId: 'pulsesphere-metrics', brokers: cfg.kafkaBrokers });
  const metricCons    = kafka.consumer({ groupId: 'pulsesphere-metrics-group' });
  await metricCons.connect();
  await metricCons.subscribe({ topic: cfg.metricTopic, fromBeginning: false });

  const metricStream$ = new Subject<MetricEvent>();
  metricCons.run({
    autoCommit: true,
    eachMessage: async ({ message }: EachMessagePayload) => {
      if (!message.value) return;
      try {
        const evt = JSON.parse(message.value.toString()) as MetricEvent;
        metricStream$.next(evt);
      } catch (err) {
        logger.error('Unable to parse metric event', err);
      }
    },
  });

  /* ––––– NATS (Social Interaction Signals) ––––– */
  const natsConn: NatsConnection = await connect({ servers: cfg.natsServers.split(',') });
  const socialSub: Subscription  = natsConn.subscribe(cfg.socialSubject);

  const socialStream$ = new Subject<SocialSignalEvent>();
  (async () => {
    for await (const msg of socialSub) {
      try {
        socialStream$.next(JSON.parse(msg.data.toString()) as SocialSignalEvent);
      } catch (err) {
        logger.error('Unable to parse social signal', err);
      }
    }
  })().catch((err) => logger.error('NATS subscription loop terminated', err));

  /* ––––– Stream Correlation / Windowing ––––– */
  const combined$ = metricStream$.pipe(
    withLatestFrom(socialStream$),
    map(([metric, social]): CombinedEvent => ({
      ...metric,
      socialDelta: social.count,
    })),
  );

  const windowed$ = combined$.pipe(
    bufferTime(cfg.bufferWindowMs),
    filter((bucket) => bucket.length > 0),
  );

  /* ––––– Instantiate Detector & Strategies ––––– */
  const detector = new SocialSentimentAnomalyDetector(
    [
      new ZScoreStrategy(cfg.zScoreThreshold, cfg.zScoreWindow, logger),
      new ThresholdStrategy(cfg.cpuThreshold, cfg.memThreshold, logger),
    ],
    alerts,
    logger,
  );

  windowed$.subscribe({
    next: (window) => detector.analyze(window),
    error: (err) => logger.error('Windowed stream error', err),
  });

  process.on('SIGINT', async () => {
    logger.info('Gracefully shutting down detector…');
    await metricCons.disconnect().catch(() => void 0);
    natsConn.close();
    process.exit(0);
  });

  logger.info('SocialSentimentAnomalyDetector started — monitoring streams.');
}

/* ────────────────────────────────────── Auto-start when executed directly ───────────────────── */
if (require.main === module) {
  // tslint:disable-next-line: no-floating-promises
  startSentimentAnomalyDetector().catch((err) => {
    // eslint-disable-next-line no-console
    console.error('[FATAL] Failed to bootstrap SocialSentimentAnomalyDetector', err);
    process.exit(1);
  });
}
```
