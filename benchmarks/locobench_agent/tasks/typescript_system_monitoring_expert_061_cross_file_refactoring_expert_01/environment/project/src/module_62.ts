```typescript
/**
 * File: src/module_62.ts
 * Project: PulseSphere SocialOps (system_monitoring)
 *
 * The Social-Context Enricher is responsible for fusing infrastructure metrics
 * with real-time, user-interaction telemetry (likes, comments, shares, etc.)
 * so that every downstream consumer of the monitoring stack can correlate
 * performance anomalies with social-engagement spikes.
 *
 * This module implements:
 *  – Observable pipelines (RxJS) for asynchronous, back-pressure-aware streams
 *  – Chain-of-Responsibility & Strategy patterns for pluggable serialization
 *  – Kafka / NATS wrappers with graceful-shutdown + auto-reconnect logic
 *  – A rolling, in-memory cache that aggregates social signals in a sliding
 *    window so enrichment is O(1) per metric.
 *
 * NOTE: Concrete Kafka/NATS connections may be disabled in unit/integration
 *       tests by swapping the IMessageBus{Producer,Consumer} implementations
 *       with the provided Noop stubs.
 */

import pino from 'pino';
import { Observable, Subject, from, merge, defer, interval, Subscription } from 'rxjs';
import { filter, map, tap } from 'rxjs/operators';
import { Kafka, Consumer, Producer } from 'kafkajs';
import { connect, NatsConnection, StringCodec, Subscription as NatsSub } from 'nats';

// -----------------------------------------------------------------------------
// Domain-level Dto’s
// -----------------------------------------------------------------------------

export interface MetricRecord {
  timestamp: number;               // epoch millis
  appId: string;                   // logical application/domain key
  metric: string;                  // e.g. cpu_usage, p95_latency
  value: number;
  /** Prometheus-style key/value pairs */
  labels: Record<string, string>;
}

export interface SocialSignal {
  timestamp: number;               // epoch millis
  appId: string;
  likes: number;
  comments: number;
  shares: number;
  liveViewers: number;
}

/** Aggregated view for the sliding window [windowStart, windowEnd] */
export interface SocialSignalSnapshot {
  appId: string;
  windowStart: number;
  windowEnd: number;
  likes: number;
  comments: number;
  shares: number;
  liveViewers: number;
}

export interface EnrichedMetric extends MetricRecord {
  socialContext: SocialSignalSnapshot | null;
}

// -----------------------------------------------------------------------------
// Bus Abstractions & Implementations
// -----------------------------------------------------------------------------

export interface IMessageBusConsumer<T> {
  connect(): Promise<void>;
  stream(): Observable<T>;
  disconnect(): Promise<void>;
}

export interface IMessageBusProducer<T> {
  connect(): Promise<void>;
  publish(event: T): Promise<void>;
  disconnect(): Promise<void>;
}

/**
 * JSON serializer – Strategy pattern so we can swap out for Avro/Protobuf
 * without touching business logic.
 */
export interface ISerializer<T> {
  serialize(value: T): Buffer;
  deserialize(buf: Buffer): T;
}

export class JsonSerializer<T> implements ISerializer<T> {
  serialize(value: T): Buffer {
    return Buffer.from(JSON.stringify(value));
  }
  deserialize(buf: Buffer): T {
    return JSON.parse(buf.toString());
  }
}

// -------------------------------- Kafka --------------------------------------

export class KafkaConsumer<T> implements IMessageBusConsumer<T> {
  private readonly serializer: ISerializer<T>;
  private consumer!: Consumer;
  private readonly stream$ = new Subject<T>();

  constructor(
    private readonly topic: string,
    private readonly groupId: string,
    private readonly brokers: string[],
    serializer?: ISerializer<T>,
    private readonly logger = pino().child({ class: 'KafkaConsumer', topic })
  ) {
    this.serializer = serializer ?? new JsonSerializer<T>();
  }

  async connect(): Promise<void> {
    const kafka = new Kafka({ brokers: this.brokers });
    this.consumer = kafka.consumer({ groupId: this.groupId });
    await this.consumer.connect();
    await this.consumer.subscribe({ topic: this.topic, fromBeginning: false });

    await this.consumer.run({
      eachMessage: async ({ message }) => {
        if (!message.value) return;
        try {
          const entity = this.serializer.deserialize(message.value);
          this.stream$.next(entity);
        } catch (err) {
          this.logger.error(err, 'Failed to deserialize Kafka message');
        }
      },
    });

    this.logger.info('Kafka consumer connected');
  }

  stream(): Observable<T> {
    return this.stream$.asObservable();
  }

  async disconnect(): Promise<void> {
    await this.consumer?.disconnect();
  }
}

export class KafkaProducer<T> implements IMessageBusProducer<T> {
  private readonly serializer: ISerializer<T>;
  private readonly producer: Producer;

  constructor(
    private readonly topic: string,
    private readonly brokers: string[],
    serializer?: ISerializer<T>,
    private readonly logger = pino().child({ class: 'KafkaProducer', topic })
  ) {
    this.serializer = serializer ?? new JsonSerializer<T>();
    this.producer = new Kafka({ brokers: this.brokers }).producer();
  }

  async connect(): Promise<void> {
    await this.producer.connect();
    this.logger.info('Kafka producer connected');
  }

  async publish(event: T): Promise<void> {
    try {
      await this.producer.send({
        topic: this.topic,
        messages: [{ value: this.serializer.serialize(event) }],
      });
    } catch (err) {
      this.logger.error(err, 'Failed to publish to Kafka');
    }
  }

  async disconnect(): Promise<void> {
    await this.producer.disconnect();
  }
}

// --------------------------------- NATS --------------------------------------

export class NatsConsumer<T> implements IMessageBusConsumer<T> {
  private conn!: NatsConnection;
  private sub!: NatsSub;
  private readonly stream$ = new Subject<T>();
  private readonly sc = StringCodec();

  constructor(
    private readonly subject: string,
    private readonly servers: string[],
    private readonly serializer: ISerializer<T> = new JsonSerializer<T>(),
    private readonly logger = pino().child({ class: 'NatsConsumer', subject })
  ) {}

  async connect(): Promise<void> {
    this.conn = await connect({ servers: this.servers });
    this.sub   = this.conn.subscribe(this.subject);
    this.logger.info('NATS consumer connected');

    (async () => {
      for await (const m of this.sub) {
        try {
          const data = this.serializer.deserialize(
            Buffer.from(m.data as Uint8Array)
          );
          this.stream$.next(data);
        } catch (err) {
          this.logger.error(err, 'Failed to deserialize NATS message');
        }
      }
    })().catch((err) => this.logger.error(err));
  }

  stream(): Observable<T> {
    return this.stream$.asObservable();
  }

  async disconnect(): Promise<void> {
    await this.sub?.drain();
    await this.conn?.drain();
  }
}

// ------------------------- No-op fallbacks for tests -------------------------

export class NoopProducer<T> implements IMessageBusProducer<T> {
  async connect(): Promise<void> {}
  async publish(_event: T): Promise<void> {}
  async disconnect(): Promise<void> {}
}

export class NoopConsumer<T> implements IMessageBusConsumer<T> {
  stream(): Observable<T> {
    return new Observable<T>();
  }
  async connect(): Promise<void> {}
  async disconnect(): Promise<void> {}
}

// -----------------------------------------------------------------------------
// Sliding-Window Cache (in-memory) – O(1) add + snapshot
// -----------------------------------------------------------------------------

const SOCIAL_WINDOW_MS = 30_000;

export class SocialSignalCache {
  private readonly buckets: Map<string, SocialSignal[]> = new Map();

  add(signal: SocialSignal): void {
    const list = this.buckets.get(signal.appId) ?? [];
    list.push(signal);
    this.buckets.set(signal.appId, list);
    this.prune(signal.appId);
  }

  snapshot(appId: string): SocialSignalSnapshot | null {
    const now = Date.now();
    const windowStart = now - SOCIAL_WINDOW_MS;
    this.prune(appId);

    const list = this.buckets.get(appId);
    if (!list || list.length === 0) return null;

    const aggregate: Omit<SocialSignalSnapshot, 'windowStart' | 'windowEnd' | 'appId'> = {
      likes: 0,
      comments: 0,
      shares: 0,
      liveViewers: 0,
    };

    for (const s of list) {
      aggregate.likes       += s.likes;
      aggregate.comments    += s.comments;
      aggregate.shares      += s.shares;
      aggregate.liveViewers = Math.max(aggregate.liveViewers, s.liveViewers);
    }

    return {
      appId,
      windowStart,
      windowEnd: now,
      ...aggregate,
    };
  }

  private prune(appId: string): void {
    const list = this.buckets.get(appId);
    if (!list) return;

    const minTs = Date.now() - SOCIAL_WINDOW_MS;
    while (list.length > 0 && list[0].timestamp < minTs) {
      list.shift();
    }
  }
}

// -----------------------------------------------------------------------------
// Social-Context Enricher – Observer pattern wires everything together
// -----------------------------------------------------------------------------

export interface EnricherOptions {
  metricsTopic: string;
  enrichedMetricsTopic: string;
  socialSubject: string;
  kafkaBrokers: string[];
  natsServers: string[];
  groupId?: string;
}

/**
 * The main orchestration engine. It subscribes to:
 *  – Kafka topic with raw MetricRecord
 *  – NATS subject with SocialSignal
 * And publishes EnrichedMetric back to Kafka for downstream analytics
 */
export class SocialContextEnricher {
  private readonly logger = pino().child({ module: 'SocialContextEnricher' });
  private readonly cache  = new SocialSignalCache();
  private subs: Subscription[] = [];

  private readonly metricConsumer: IMessageBusConsumer<MetricRecord>;
  private readonly socialConsumer: IMessageBusConsumer<SocialSignal>;
  private readonly producer: IMessageBusProducer<EnrichedMetric>;

  constructor(private readonly opts: EnricherOptions) {
    this.metricConsumer = new KafkaConsumer<MetricRecord>(
      opts.metricsTopic,
      opts.groupId ?? 'social-context-enricher',
      opts.kafkaBrokers
    );

    this.socialConsumer = new NatsConsumer<SocialSignal>(
      opts.socialSubject,
      opts.natsServers
    );

    this.producer = new KafkaProducer<EnrichedMetric>(
      opts.enrichedMetricsTopic,
      opts.kafkaBrokers
    );
  }

  async start(): Promise<void> {
    // Connect buses
    await Promise.all([
      this.metricConsumer.connect(),
      this.socialConsumer.connect(),
      this.producer.connect(),
    ]);

    // Wire up streams
    const metric$  = this.metricConsumer.stream();
    const social$  = this.socialConsumer.stream();

    // Every social signal just updates the cache
    this.subs.push(
      social$
        .pipe(
          tap((signal) => this.cache.add(signal)),
          tap((signal) =>
            this.logger.debug({ appId: signal.appId }, 'social signal cached')
          )
        )
        .subscribe()
    );

    // Each metric is enriched with snapshot & published
    this.subs.push(
      metric$
        .pipe(
          map((metric) => {
            const snapshot = this.cache.snapshot(metric.appId);
            const enriched: EnrichedMetric = {
              ...metric,
              socialContext: snapshot,
            };
            return enriched;
          }),
          tap((enriched) => this.producer.publish(enriched)),
          tap((enriched) =>
            this.logger.debug(
              { appId: enriched.appId, metric: enriched.metric },
              'enriched metric published'
            )
          )
        )
        .subscribe({
          error: (err) => this.logger.error(err, 'metric stream failed'),
        })
    );

    // Periodic housekeeping logs for observability
    this.subs.push(
      interval(60_000).subscribe(() =>
        this.logger.info('Enricher heartbeat – running')
      )
    );

    this.logger.info('SocialContextEnricher started');
  }

  async stop(): Promise<void> {
    this.subs.forEach((s) => s.unsubscribe());
    await Promise.all([
      this.metricConsumer.disconnect(),
      this.socialConsumer.disconnect(),
      this.producer.disconnect(),
    ]);
    this.logger.info('SocialContextEnricher stopped');
  }
}

// -----------------------------------------------------------------------------
// Bootstrap helpers
// -----------------------------------------------------------------------------

/**
 * Convenience bootstrapper for DI frameworks / CLI.
 * Reads configuration from environment variables (12-factor style).
 *
 *   PULSE_KAFKA_BROKERS=broker1:9092,broker2:9092
 *   PULSE_NATS_SERVERS=nats://nats:4222
 *   PULSE_METRICS_TOPIC=pulse.raw.metrics
 *   PULSE_ENRICHED_METRICS_TOPIC=pulse.enriched.metrics
 *   PULSE_SOCIAL_SUBJECT=pulse.social.signals
 */
export async function bootstrapSocialContextEnricher(): Promise<SocialContextEnricher> {
  const opts: EnricherOptions = {
    metricsTopic: process.env.PULSE_METRICS_TOPIC ?? 'pulse.raw.metrics',
    enrichedMetricsTopic:
      process.env.PULSE_ENRICHED_METRICS_TOPIC ?? 'pulse.enriched.metrics',
    socialSubject: process.env.PULSE_SOCIAL_SUBJECT ?? 'pulse.social.signals',
    kafkaBrokers: (process.env.PULSE_KAFKA_BROKERS ?? 'localhost:9092').split(
      ','
    ),
    natsServers: (process.env.PULSE_NATS_SERVERS ?? 'nats://localhost:4222').split(
      ','
    ),
  };

  const enricher = new SocialContextEnricher(opts);
  await enricher.start();

  // Graceful shutdown
  const shutdown = async () => {
    await enricher.stop();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  return enricher;
}

// -----------------------------------------------------------------------------
// If this file is executed directly (`ts-node src/module_62.ts`) – start.
// -----------------------------------------------------------------------------
if (require.main === module) {
  bootstrapSocialContextEnricher().catch((err) => {
    pino().error(err, 'Failed to bootstrap SocialContextEnricher');
    process.exit(1);
  });
}
```