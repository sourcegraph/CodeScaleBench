```typescript
/**
 * PulseSphere SocialOps – module_28.ts
 *
 * Sentiment-Aware Auto-Scaler
 * ---------------------------------------------------------------
 * This module consumes infrastructure metrics that have been
 * enriched with real-time social-interaction signals.  It analyses
 * them in short windows and publishes scaling commands when a
 * configured Strategy deems it necessary.
 *
 * Patterns employed:
 *  • Strategy Pattern (pluggable scaling algorithms)
 *  • Chain-of-Responsibility (pre-processing / validation pipeline)
 *  • Observer Pattern (hot-reload of configuration)
 *  • Event-Driven (Kafka topics in / out)
 */

import { Kafka, Producer, logLevel } from 'kafkajs';
import { Observable, merge, windowTime, map, filter, catchError, fromEvent, Subscription } from 'rxjs';
import { EventEmitter } from 'events';
import * as fs from 'fs';
import * as path from 'path';

// -----------------------------------------------------------------------------
// Domain Types
// -----------------------------------------------------------------------------

export interface MetricEvent {
  timestamp: number;          // Unix epoch millis
  serviceId: string;          // e.g. auth-api-01
  cpu: number;                // %
  memory: number;             // %
  rps: number;                // requests / sec
  errorRate: number;          // avg last 30s
  social: SocialSignal;       // correlation payload
}

export interface SocialSignal {
  likesDelta: number;         // growth / sec
  commentsDelta: number;
  sharesDelta: number;
  liveStreamSpike: boolean;
}

export interface ScalingDecision {
  serviceId: string;
  action: 'scale_out' | 'scale_in' | 'noop';
  delta: number;              // +n / ‑n replicas
  reason: string;
  timestamp: number;
}

// -----------------------------------------------------------------------------
// Configuration (observer pattern)
// -----------------------------------------------------------------------------

export interface AutoscalerConfig {
  windowSizeSec: number;
  minReplicas: number;
  maxReplicas: number;
  cpuThreshold: number;       // 0-100
  socialBurstShare: number;   // multiplier on sharesDelta that triggers boost
  strategy: 'simple' | 'predictive';
}

const CONFIG_PATH = path.join(process.env.PS_CONFIG_DIR ?? './config', 'autoscaler.json');

class ConfigWatcher extends EventEmitter {
  private current: AutoscalerConfig;

  constructor(private readonly filePath: string) {
    super();
    this.current = ConfigWatcher.loadConfig(filePath);
    this.watch();
  }

  static loadConfig(filePath: string): AutoscalerConfig {
    try {
      const raw = fs.readFileSync(filePath, 'utf-8');
      return JSON.parse(raw) as AutoscalerConfig;
    } catch (err) {
      // Fallback defaults
      return {
        windowSizeSec: 30,
        minReplicas: 2,
        maxReplicas: 50,
        cpuThreshold: 70,
        socialBurstShare: 1000,
        strategy: 'simple',
      };
    }
  }

  private watch(): void {
    fs.watch(this.filePath, { persistent: false }, () => {
      try {
        const next = ConfigWatcher.loadConfig(this.filePath);
        this.current = next;
        this.emit('update', next);
      } catch (err) {
        // Ignore broken updates
        console.error(`[ConfigWatcher] Failed to reload config: ${(err as Error).message}`);
      }
    });
  }

  get value(): AutoscalerConfig {
    return this.current;
  }
}

// -----------------------------------------------------------------------------
// Validation Chain (chain of responsibility)
// -----------------------------------------------------------------------------

interface Validator {
  setNext(v: Validator): Validator;
  validate(event: MetricEvent): boolean;
}

abstract class BaseValidator implements Validator {
  private next?: Validator;
  setNext(v: Validator): Validator {
    this.next = v;
    return v;
  }

  validate(event: MetricEvent): boolean {
    if (!this.doValidate(event)) {
      return false;
    }
    return this.next ? this.next.validate(event) : true;
  }

  protected abstract doValidate(event: MetricEvent): boolean;
}

class SchemaValidator extends BaseValidator {
  protected doValidate(event: MetricEvent): boolean {
    const ok = typeof event.cpu === 'number' &&
               typeof event.memory === 'number' &&
               typeof event.social?.likesDelta === 'number';
    if (!ok) console.warn('[Validator] Schema invalid', event);
    return ok;
  }
}

class RangeValidator extends BaseValidator {
  protected doValidate(event: MetricEvent): boolean {
    const ok = event.cpu >= 0 && event.cpu <= 100 &&
               event.memory >= 0 && event.memory <= 100;
    if (!ok) console.warn('[Validator] Range invalid', event);
    return ok;
  }
}

// -----------------------------------------------------------------------------
// Scaling Strategies
// -----------------------------------------------------------------------------

export interface ScalingStrategy {
  decide(events: MetricEvent[], cfg: AutoscalerConfig): ScalingDecision[];
}

export class SimpleThresholdStrategy implements ScalingStrategy {
  decide(events: MetricEvent[], cfg: AutoscalerConfig): ScalingDecision[] {
    const grouped = new Map<string, MetricEvent[]>();
    for (const ev of events) {
      grouped.set(ev.serviceId, [...(grouped.get(ev.serviceId) ?? []), ev]);
    }

    const decisions: ScalingDecision[] = [];
    for (const [serviceId, evts] of grouped) {
      const avgCpu = evts.reduce((a, b) => a + b.cpu, 0) / evts.length;
      const totalShares = evts.reduce((a, b) => a + b.social.sharesDelta, 0);
      const latest = evts[evts.length - 1];

      if (avgCpu > cfg.cpuThreshold || totalShares > cfg.socialBurstShare) {
        decisions.push({
          serviceId,
          action: 'scale_out',
          delta: 1,
          reason: `CPU: ${avgCpu.toFixed(1)} / SharesΔ: ${totalShares}`,
          timestamp: Date.now(),
        });
      } else if (avgCpu < cfg.cpuThreshold * 0.4) {
        decisions.push({
          serviceId,
          action: 'scale_in',
          delta: -1,
          reason: `CPU below threshold`,
          timestamp: Date.now(),
        });
      } else {
        decisions.push({
          serviceId,
          action: 'noop',
          delta: 0,
          reason: 'within thresholds',
          timestamp: Date.now(),
        });
      }
    }
    return decisions;
  }
}

export class PredictiveTrendStrategy implements ScalingStrategy {
  // Very naive linear trend, placeholder for ML time-series
  decide(events: MetricEvent[], cfg: AutoscalerConfig): ScalingDecision[] {
    const byService = new Map<string, MetricEvent[]>();
    for (const e of events) {
      byService.set(e.serviceId, [...(byService.get(e.serviceId) ?? []), e]);
    }

    const decisions: ScalingDecision[] = [];
    for (const [serviceId, evs] of byService) {
      if (evs.length < 3) continue; // not enough data for trend
      const first = evs[0].rps;
      const last = evs[evs.length - 1].rps;
      const slope = (last - first) / evs.length; // simple trend

      if (slope > 5) {
        decisions.push({
          serviceId,
          action: 'scale_out',
          delta: Math.min(3, Math.ceil(slope / 5)),
          reason: `RPS trend +${slope.toFixed(2)}`,
          timestamp: Date.now(),
        });
      } else if (slope < -3) {
        decisions.push({
          serviceId,
          action: 'scale_in',
          delta: Math.max(-3, Math.floor(slope / 3)),
          reason: `RPS trend ${slope.toFixed(2)}`,
          timestamp: Date.now(),
        });
      } else {
        decisions.push({
          serviceId,
          action: 'noop',
          delta: 0,
          reason: 'stable trend',
          timestamp: Date.now(),
        });
      }
    }
    return decisions;
  }
}

// -----------------------------------------------------------------------------
// Kafka Transport Helpers
// -----------------------------------------------------------------------------

const KAFKA_BROKERS = (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(',');
const INPUT_TOPIC = 'pulsesphere.metrics.enriched';
const OUTPUT_TOPIC = 'pulsesphere.scaler.commands';

const kafka = new Kafka({
  clientId: 'sentiment-autoscaler',
  brokers: KAFKA_BROKERS,
  logLevel: logLevel.NOTHING,
});

const producer: Producer = kafka.producer();

// -----------------------------------------------------------------------------
// Autoscaler Service
// -----------------------------------------------------------------------------

export class SentimentAutoscaler {
  private readonly validators: Validator;
  private readonly configWatcher = new ConfigWatcher(CONFIG_PATH);
  private strategy: ScalingStrategy;
  private kafkaSubscription?: Subscription;

  constructor(private readonly metricStream$: Observable<MetricEvent>) {
    // Build validation chain
    const schema = new SchemaValidator();
    const range = new RangeValidator();
    schema.setNext(range);
    this.validators = schema;

    // initial strategy
    this.strategy = this.buildStrategy(this.configWatcher.value);

    // react to config updates
    this.configWatcher.on('update', (cfg: AutoscalerConfig) => {
      this.strategy = this.buildStrategy(cfg);
      console.info('[Autoscaler] Config updated');
    });
  }

  async start(): Promise<void> {
    await producer.connect();
    console.info('[Autoscaler] Kafka producer connected');

    const cfg = this.configWatcher.value;

    this.kafkaSubscription = this.metricStream$
      .pipe(
        filter(evt => this.validators.validate(evt)),
        windowTime(cfg.windowSizeSec * 1000),
        map(win$ => win$.pipe(
          // Collect events in the window into array
          map(ev => ev),
        )),
      )
      .subscribe(win$ => {
        const collected: MetricEvent[] = [];
        win$.subscribe({
          next: ev => collected.push(ev),
          complete: async () => {
            if (collected.length === 0) return;

            const decisions = this.strategy.decide(collected, this.configWatcher.value);
            for (const d of decisions) await this.publishDecision(d);
          },
        });
      });
  }

  private async publishDecision(decision: ScalingDecision): Promise<void> {
    if (decision.action === 'noop') return;

    try {
      await producer.send({
        topic: OUTPUT_TOPIC,
        messages: [
          {
            key: decision.serviceId,
            value: JSON.stringify(decision),
          },
        ],
      });
      console.info(`[Autoscaler] Published decision`, decision);
    } catch (err) {
      console.error(`[Autoscaler] Failed to publish: ${(err as Error).message}`);
    }
  }

  private buildStrategy(cfg: AutoscalerConfig): ScalingStrategy {
    switch (cfg.strategy) {
      case 'predictive':
        return new PredictiveTrendStrategy();
      case 'simple':
      default:
        return new SimpleThresholdStrategy();
    }
  }

  async shutdown(): Promise<void> {
    this.kafkaSubscription?.unsubscribe();
    await producer.disconnect();
  }
}

// -----------------------------------------------------------------------------
// Example Bootstrap (would normally live elsewhere)
// -----------------------------------------------------------------------------

if (require.main === module) {
  // Fake stream for local dev
  const fakeEmitter = new EventEmitter();
  const fakeStream$ = fromEvent<MetricEvent>(fakeEmitter, 'metric').pipe(
    catchError(err => { console.error(err); return []; }),
  );

  const autoscaler = new SentimentAutoscaler(fakeStream_);
  autoscaler.start().catch(console.error);

  // Emit fake data
  setInterval(() => {
    fakeEmitter.emit('metric', {
      timestamp: Date.now(),
      serviceId: 'feed-svc',
      cpu: Math.random() * 100,
      memory: Math.random() * 100,
      rps: 200 + Math.random() * 50,
      errorRate: Math.random(),
      social: {
        likesDelta: Math.random() * 500,
        commentsDelta: Math.random() * 200,
        sharesDelta: Math.random() * 1000,
        liveStreamSpike: Math.random() > 0.9,
      },
    } as MetricEvent);
  }, 1000);

  // Graceful shutdown
  process.on('SIGINT', async () => {
    console.info('Shutting down autoscaler…');
    await autoscaler.shutdown();
    process.exit(0);
  });
}
```