```typescript
/**
 *  PulseSphere SocialOps — System Monitoring Platform
 *  ---------------------------------------------------
 *  File:        src/module_7.ts
 *  Description: Social-aware telemetry enrichment micro-service.  It listens to raw
 *               social interaction events coming from the event backbone (Kafka),
 *               augments them with real-time sentiment analytics and correlation
 *               metadata, and finally emits enriched telemetry back to the mesh so
 *               that downstream SRE dashboards can act on socially-driven anomalies.
 *
 *  Patterns:    - Observer          (Kafka consumer emits → observers process)
 *               - Strategy          (pluggable sentiment scoring algorithms)
 *               - Command           (async commands for graceful shutdown, flush)
 *               - Chain-of-Resp.    (post-processing pipeline / enricher chain)
 *
 *  NOTE:        This file purposefully avoids any hard dependency on the rest of the
 *               code base so that it can be compiled & unit-tested in isolation.
 *               Production wiring (DI container, mesh sidecars etc.) happens
 *               elsewhere during service bootstrapping.
 */

import 'dotenv/config';                             // env var loading
import { Kafka, Consumer, Producer } from 'kafkajs';
import pino, { Logger } from 'pino';

/* ------------------------------------------------------------------ *
 *                        Domain & Shared Types                        *
 * ------------------------------------------------------------------ */

export interface RawSocialEvent {
  id: string;                       // globally-unique event id
  userId: string;
  verb: 'LIKE' | 'COMMENT' | 'SHARE' | 'STREAM_VIEW';
  content: string;                  // free-text or encoded JSON string
  language?: string;
  timestamp: number;                // epoch millis
}

export interface EnrichedSocialEvent extends RawSocialEvent {
  sentimentScore: number;           // −1 (very negative) to +1 (very positive)
  performative: 'POSITIVE' | 'NEGATIVE' | 'NEUTRAL';
  processingLatencyMs: number;      // ingest → emit latency
  enrichedAt: number;               // epoch millis
}

/* ------------------------------------------------------------------ *
 *                          Strategy Pattern                           *
 * ------------------------------------------------------------------ */

/**
 * SentimentStrategy: contract for pluggable sentiment scoring engines.
 */
export interface SentimentStrategy {
  readonly id: string;
  score(content: string, lang?: string): Promise<number>;
}

/**
 * SimpleKeywordStrategy: extremely lightweight, keywords-based sentiment
 * scoring intended for fall-back scenarios or on-prem deployments that
 * cannot call expensive ML endpoints.
 */
export class SimpleKeywordStrategy implements SentimentStrategy {
  public readonly id = 'simple-keyword-v1';

  private positive = ['love', 'great', 'awesome', 'like', 'good', '🔥', '💯'];
  private negative = ['hate', 'bad', 'terrible', 'angry', '👎', '💩'];

  public async score(content: string): Promise<number> {
    const t = content.toLowerCase();
    const posHits = this.positive.filter((k) => t.includes(k)).length;
    const negHits = this.negative.filter((k) => t.includes(k)).length;
    const total = posHits + negHits;
    if (!total) return 0; // neutral

    const raw = (posHits - negHits) / total;
    return Math.max(-1, Math.min(1, raw));
  }
}

/**
 * ExternalMlStrategy: calls an external ML micro-service over the mesh.
 * In production this might be a BERT-based sentiment classifier.
 */
export class ExternalMlStrategy implements SentimentStrategy {
  public readonly id = 'ml-bert-v2';

  constructor(
    private readonly httpEndpoint: string,
    private readonly httpClient = fetch // global fetch (Node 18+ or polyfill)
  ) {}

  public async score(content: string, lang?: string): Promise<number> {
    const res = await this.httpClient(this.httpEndpoint, {
      method: 'POST',
      body: JSON.stringify({ content, lang }),
      headers: { 'Content-Type': 'application/json' },
      keepalive: true, // allow graceful shutdown flush
    });

    if (!res.ok) {
      throw new Error(`ML API responded with ${res.status}`);
    }

    const { score } = await res.json();
    return Number(score);
  }
}

/* ------------------------------------------------------------------ *
 *                    Sentiment Analyzer (Strategy ctx)                *
 * ------------------------------------------------------------------ */

export class SentimentAnalyzer {
  private readonly strategies: Map<string, SentimentStrategy> = new Map();
  private activeStrategyId: string;

  constructor(defaultStrategy: SentimentStrategy, ...extraStrategies: SentimentStrategy[]) {
    this.registerStrategy(defaultStrategy);
    extraStrategies.forEach((s) => this.registerStrategy(s));
    this.activeStrategyId = defaultStrategy.id;
  }

  public registerStrategy(strategy: SentimentStrategy): void {
    this.strategies.set(strategy.id, strategy);
  }

  public setActiveStrategy(strategyId: string): void {
    if (!this.strategies.has(strategyId)) {
      throw new Error(`Unknown strategy ${strategyId}`);
    }
    this.activeStrategyId = strategyId;
  }

  public async analyze(content: string, lang?: string): Promise<number> {
    const strategy = this.strategies.get(this.activeStrategyId);
    if (!strategy) throw new Error('Active strategy not set');
    return strategy.score(content, lang);
  }
}

/* ------------------------------------------------------------------ *
 *                         Observer / Controller                       *
 * ------------------------------------------------------------------ */

interface TelemetryEnricherOptions {
  kafkaBrokers: string[];
  inTopic: string;
  outTopic: string;
  groupId: string;
  strategy: SentimentAnalyzer;
  logger?: Logger;
}

/**
 * TelemetryEnricherService
 * ------------------------
 * Listens to raw social events, computes sentiment, attaches metadata,
 * and pushes the enriched document back to Kafka for the Telemetry Mesh.
 */
export class TelemetryEnricherService {
  private readonly kafka: Kafka;
  private consumer!: Consumer;
  private producer!: Producer;
  private readonly logger: Logger;
  private isShuttingDown = false;

  constructor(private readonly opts: TelemetryEnricherOptions) {
    this.kafka = new Kafka({ brokers: opts.kafkaBrokers, clientId: 'telemetry-enricher' });
    this.logger = opts.logger ?? pino({ name: 'telemetry-enricher' });
  }

  /* ------------------------- Lifecycle Commands ------------------------- */

  /**
   * Boots the underlying Kafka clients and seeks to the latest committed offsets.
   */
  public async start(): Promise<void> {
    this.consumer = this.kafka.consumer({ groupId: this.opts.groupId });
    this.producer = this.kafka.producer({ allowAutoTopicCreation: false });
    await Promise.all([this.consumer.connect(), this.producer.connect()]);

    await this.consumer.subscribe({ topic: this.opts.inTopic, fromBeginning: false });
    await this.consumer.run({ eachMessage: (args) => this.onMessage(args) });

    // handle SIGTERM / SIGINT for k8s / systemd
    process
      .once('SIGTERM', () => this.stop())
      .once('SIGINT', () => this.stop());

    this.logger.info('TelemetryEnricherService started');
  }

  /**
   * Idempotent shutdown command that closes Kafka connections gracefully.
   */
  public async stop(): Promise<void> {
    if (this.isShuttingDown) return;
    this.isShuttingDown = true;
    this.logger.info('TelemetryEnricherService shutting down … ⏳');

    try {
      await this.consumer?.disconnect();
      await this.producer?.disconnect();
      this.logger.info('TelemetryEnricherService shutdown complete ✅');
    } catch (err) {
      this.logger.error({ err }, 'Error during shutdown');
    } finally {
      process.exit(0);
    }
  }

  /* ---------------------------- Kafka Handler --------------------------- */

  /**
   * Kafka eachMessage handler — executes in parallel within the kafkajs run loop.
   * Responsible for deserialization, enrichment pipeline and production.
   */
  private async onMessage({
    message,
    partition,
    heartbeat,
  }: {
    topic: string;
    partition: number;
    message: { key: Buffer | null; value: Buffer | null; offset: string };
    heartbeat: () => Promise<void>;
  }): Promise<void> {
    const start = Date.now();

    try {
      if (!message.value) {
        this.logger.warn({ partition, offset: message.offset }, 'Received empty message');
        return;
      }

      const raw: RawSocialEvent = JSON.parse(message.value.toString());

      /* ---- Sentiment Analysis (Strategy) ---- */
      const score = await this.opts.strategy.analyze(raw.content, raw.language);

      /* ---- Compose Enriched Event ---- */
      const enriched: EnrichedSocialEvent = {
        ...raw,
        sentimentScore: score,
        performative: score > 0.05 ? 'POSITIVE' : score < -0.05 ? 'NEGATIVE' : 'NEUTRAL',
        processingLatencyMs: Date.now() - raw.timestamp,
        enrichedAt: Date.now(),
      };

      /* ---- Produce to Outbound Topic ---- */
      await this.producer.send({
        topic: this.opts.outTopic,
        messages: [
          {
            key: message.key ?? Buffer.from(enriched.userId),
            value: Buffer.from(JSON.stringify(enriched)),
          },
        ],
      });

      this.logger.debug(
        {
          id: raw.id,
          sentiment: enriched.performative,
          partition,
          latencyMs: enriched.processingLatencyMs,
        },
        'Enriched event produced'
      );

      // keep consumer session alive in case of long processing
      await heartbeat();
    } catch (err) {
      this.logger.error({ err }, 'Failed processing message, committing offset and continuing');
      // Swallow error to avoid consumer crash; offset already committed by kafkajs "eachBatchAutoCommit"
    } finally {
      const duration = Date.now() - start;
      if (duration > 1000) {
        this.logger.warn({ duration }, 'Message processing took unusually long');
      }
    }
  }
}

/* ------------------------------------------------------------------ *
 *                       Service Bootstrap (if run)                    *
 * ------------------------------------------------------------------ */

if (require.main === module) {
  // Stand-alone execution (e.g. docker container)
  // Config is loaded from environment variables for 12-factor compliance.
  const service = new TelemetryEnricherService({
    kafkaBrokers: (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
    inTopic: process.env.KAFKA_RAW_TOPIC ?? 'social.raw',
    outTopic: process.env.KAFKA_ENRICH_TOPIC ?? 'social.enriched',
    groupId: process.env.KAFKA_GROUP_ID ?? 'telemetry-enricher-group',
    strategy: new SentimentAnalyzer(
      new SimpleKeywordStrategy(),
      // External ML strategy can be toggled via env var
      new ExternalMlStrategy(process.env.ML_ENDPOINT ?? 'http://ml-sentiment:8080/score')
    ),
    logger: pino({ level: process.env.LOG_LEVEL ?? 'info' }),
  });

  // optionally switch to ML strategy when the env var is set
  if (process.env.SENTIMENT_STRATEGY_ID) {
    service
      .opts.strategy
      .setActiveStrategy(process.env.SENTIMENT_STRATEGY_ID);
  }

  // eslint-disable-next-line @typescript-eslint/no-floating-promises
  service.start();
}
```
