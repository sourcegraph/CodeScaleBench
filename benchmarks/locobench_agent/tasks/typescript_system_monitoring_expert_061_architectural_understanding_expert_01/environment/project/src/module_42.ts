```typescript
/**
 * PulseSphere SocialOps – System Monitoring
 * -----------------------------------------
 * File:        src/module_42.ts
 * Description: Social-context enrichment micro-service.  Consumes raw infra metrics
 *              from Kafka, correlates them with social-interaction signals and
 *              publishes enriched telemetry events back to the mesh.
 *
 * Architectural notes
 *  - Event-Driven (Kafka) backbone
 *  - Chain-of-Responsibility processing pipeline
 *  - Strategy pattern to allow plug-and-play enrichment logic
 *  - Observer pattern (internal event emitter) for cross-cutting concerns
 *
 * External deps (add to package.json):
 *  "kafkajs": "^2.2.4",
 *  "pino": "^8.15.0",
 *  "zod": "^3.22.4"
 */

import { Kafka, Consumer, Producer, EachMessagePayload, logLevel as KafkaLogLevel } from 'kafkajs';
import { EventEmitter } from 'events';
import * as z from 'zod';
import pino, { Logger } from 'pino';

/* -------------------------------------------------------------------------- */
/*                              Runtime Configuration                          */
/* -------------------------------------------------------------------------- */

interface EnvConfig {
  kafkaBrokers: string[];
  rawMetricsTopic: string;
  enrichedMetricsTopic: string;
  consumerGroupId: string;
  dlqTopic: string;
  serviceName: string;
  logLevel: pino.Level;
}

function loadConfig(): EnvConfig {
  /* Basic env-var validation. In real world we'd use a full config service */
  const cfg = {
    kafkaBrokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    rawMetricsTopic: process.env.RAW_METRICS_TOPIC || 'raw_metrics',
    enrichedMetricsTopic: process.env.ENRICHED_METRICS_TOPIC || 'enriched_metrics',
    dlqTopic: process.env.DLQ_TOPIC || 'system_dlq',
    consumerGroupId: process.env.CONSUMER_GROUP_ID || 'social_context_enricher',
    serviceName: process.env.SERVICE_NAME || 'module_42.social-context-enricher',
    logLevel: (process.env.LOG_LEVEL as pino.Level) || 'info',
  } satisfies EnvConfig;

  return cfg;
}

const CONFIG = loadConfig();

/* -------------------------------------------------------------------------- */
/*                           Structured Logging Setup                         */
/* -------------------------------------------------------------------------- */

const logger: Logger = pino({
  name: CONFIG.serviceName,
  level: CONFIG.logLevel,
  transport:
    process.env.NODE_ENV !== 'production'
      ? { target: 'pino-pretty', options: { colorize: true } }
      : undefined,
});

/* -------------------------------------------------------------------------- */
/*                              Domain Contracts                              */
/* -------------------------------------------------------------------------- */

/**
 * Incoming raw metric as produced by infrastructure monitoring agents.
 */
const RawMetricSchema = z.object({
  ts: z.number(), // epoch millis
  host: z.string(),
  cluster: z.string(),
  service: z.string(),
  metricName: z.string(),
  value: z.number(),
  // Social signals come from a sidecar agent that tags infra with user-interaction metrics
  socialSignals: z
    .object({
      likes: z.number().optional(),
      comments: z.number().optional(),
      shares: z.number().optional(),
      liveViewers: z.number().optional(),
    })
    .optional(),
});
type RawMetric = z.infer<typeof RawMetricSchema>;

/**
 * Enriched metric that downstream SRE tooling will ingest.
 */
type EnrichedMetric = RawMetric & {
  enrichedAt: number;
  impactScore: number; // 0-100 – combined infra + social impact
  stratId: string; // which strategy produced the enrichment
};

/* -------------------------------------------------------------------------- */
/*                        Strategy Pattern – Enrichers                        */
/* -------------------------------------------------------------------------- */

interface EnrichmentStrategy {
  id: string;
  /** Returns `undefined` if the strategy does not apply to the metric */
  enrich(metric: RawMetric): EnrichedMetric | undefined;
}

/**
 * Calculates impactScore based on live viewers spikes (e.g. live streaming)
 */
class LiveViewerSpikeStrategy implements EnrichmentStrategy {
  public readonly id = 'live_viewer_spike';

  enrich(metric: RawMetric): EnrichedMetric | undefined {
    if (!metric.socialSignals?.liveViewers) return;

    const { liveViewers } = metric.socialSignals;

    // Simple heuristic: map 0-200k viewers to 0-100 score.
    const impactScore = Math.min(100, Math.log10(liveViewers + 1) * 25);

    return {
      ...metric,
      enrichedAt: Date.now(),
      impactScore,
      stratId: this.id,
    };
  }
}

/**
 * Calculates impactScore based on high like/comment activity on posts
 */
class EngagementBurstStrategy implements EnrichmentStrategy {
  public readonly id = 'engagement_burst';

  enrich(metric: RawMetric): EnrichedMetric | undefined {
    const { likes = 0, comments = 0, shares = 0 } = metric.socialSignals ?? {};

    const totalInteractions = likes + comments * 2 + shares * 3;
    if (totalInteractions < 100) return;

    // Weighted impact formula
    const impactScore = Math.min(100, Math.sqrt(totalInteractions));

    return {
      ...metric,
      enrichedAt: Date.now(),
      impactScore,
      stratId: this.id,
    };
  }
}

/**
 * Fallback strategy → generic infrastructure load
 */
class InfraLoadStrategy implements EnrichmentStrategy {
  public readonly id = 'infra_load';

  enrich(metric: RawMetric): EnrichedMetric {
    const cpuOrMem = /cpu|memory/i.test(metric.metricName);
    const baselineScore = cpuOrMem ? metric.value : metric.value / 10;

    return {
      ...metric,
      enrichedAt: Date.now(),
      impactScore: Math.min(100, baselineScore),
      stratId: this.id,
    };
  }
}

/* -------------------------------------------------------------------------- */
/*                   Chain-of-Responsibility Processing Steps                 */
/* -------------------------------------------------------------------------- */

interface PipelineStep {
  setNext(step: PipelineStep): PipelineStep;
  handle(msg: EachMessagePayload): Promise<void>;
}

abstract class AbstractStep implements PipelineStep {
  private next?: PipelineStep;

  public setNext(step: PipelineStep): PipelineStep {
    this.next = step;
    return step;
  }

  protected async nextHandle(msg: EachMessagePayload): Promise<void> {
    if (this.next) {
      await this.next.handle(msg);
    }
  }

  public abstract handle(msg: EachMessagePayload): Promise<void>;
}

/**
 * Step 1: Validate and parse incoming Kafka messages
 */
class ValidationStep extends AbstractStep {
  async handle({ message, topic, partition }: EachMessagePayload): Promise<void> {
    try {
      if (!message.value) throw new Error('Empty message');

      const raw = JSON.parse(message.value.toString());
      const parsed: RawMetric = RawMetricSchema.parse(raw);

      // Pass parsed object inside message headers for downstream steps
      message.headers = {
        ...message.headers,
        _parsedMetric: Buffer.from(JSON.stringify(parsed)),
      };
      await this.nextHandle({ message, topic, partition });
    } catch (err) {
      logger.error({ err }, 'Validation failure – routing to DLQ');
      await DLQPublisher.publish(message);
    }
  }
}

/**
 * Step 2: Enrichment
 */
class EnrichmentStep extends AbstractStep {
  private readonly strategies: EnrichmentStrategy[];

  constructor(strategies: EnrichmentStrategy[]) {
    super();
    this.strategies = strategies;
  }

  async handle({ message, topic, partition }: EachMessagePayload): Promise<void> {
    try {
      const parsedBytes = message.headers?._parsedMetric;
      if (!parsedBytes) throw new Error('Missing parsed metric in headers');

      const metric: RawMetric = JSON.parse(parsedBytes.toString());

      let enriched: EnrichedMetric | undefined;
      for (const strat of this.strategies) {
        enriched = strat.enrich(metric);
        if (enriched) break;
      }

      // Guaranteed at least InfraLoadStrategy applies
      if (!enriched) {
        enriched = new InfraLoadStrategy().enrich(metric);
      }

      message.headers = {
        ...message.headers,
        _enrichedMetric: Buffer.from(JSON.stringify(enriched)),
      };

      await this.nextHandle({ message, topic, partition });
    } catch (err) {
      logger.error({ err }, 'Enrichment failure – routing to DLQ');
      await DLQPublisher.publish(message);
    }
  }
}

/**
 * Step 3: Publish enriched metric downstream
 */
class PublishStep extends AbstractStep {
  constructor(private readonly producer: Producer) {
    super();
  }

  async handle({ message }: EachMessagePayload): Promise<void> {
    const enrichedBytes = message.headers?._enrichedMetric;
    if (!enrichedBytes) {
      logger.warn('No enriched metric found – skipping publish');
      return;
    }

    await this.producer.send({
      topic: CONFIG.enrichedMetricsTopic,
      messages: [
        {
          value: enrichedBytes,
          key: message.key,
          headers: {
            stratId: message.headers?.stratId || '',
            sourceService: CONFIG.serviceName,
          },
        },
      ],
    });

    // Optionally notify local observers
    LocalEventBus.emit('metric.enriched', JSON.parse(enrichedBytes.toString()) as EnrichedMetric);
  }
}

/* -------------------------------------------------------------------------- */
/*                  Observer Pattern – Internal Event Bus                     */
/* -------------------------------------------------------------------------- */

class LocalEventBus extends EventEmitter {}
const LocalEventBusSingleton = new LocalEventBus();

/* Convenience re-export */
export const LocalEventBus = LocalEventBusSingleton;

/* -------------------------------------------------------------------------- */
/*                          Dead Letter Queue Publisher                       */
/* -------------------------------------------------------------------------- */

class DLQPublisher {
  private static producer: Producer;

  static async init(kafka: Kafka) {
    this.producer = kafka.producer({ allowAutoTopicCreation: true });
    await this.producer.connect();
  }

  static async publish(failedMessage: EachMessagePayload['message']) {
    if (!this.producer) throw new Error('DLQPublisher not initialised');

    await this.producer.send({
      topic: CONFIG.dlqTopic,
      messages: [
        {
          key: failedMessage.key,
          value: failedMessage.value,
          headers: {
            ...failedMessage.headers,
            _failedAt: Buffer.from(Date.now().toString()),
            _sourceService: Buffer.from(CONFIG.serviceName),
          },
        },
      ],
    });
  }
}

/* -------------------------------------------------------------------------- */
/*                         Main Service Implementation                        */
/* -------------------------------------------------------------------------- */

class SocialContextEnricherService {
  private readonly kafka: Kafka;
  private readonly consumer: Consumer;
  private readonly producer: Producer;
  private readonly pipeline: PipelineStep;
  private shuttingDown = false;

  constructor() {
    this.kafka = new Kafka({
      clientId: CONFIG.serviceName,
      brokers: CONFIG.kafkaBrokers,
      logLevel: KafkaLogLevel.NOTHING,
    });

    this.consumer = this.kafka.consumer({ groupId: CONFIG.consumerGroupId, allowAutoTopicCreation: false });
    this.producer = this.kafka.producer();
    // pipeline wiring
    const validation = new ValidationStep();
    const enrichment = new EnrichmentStep([
      new LiveViewerSpikeStrategy(),
      new EngagementBurstStrategy(),
    ]);
    const publish = new PublishStep(this.producer);

    validation.setNext(enrichment).setNext(publish);

    this.pipeline = validation;
  }

  async start() {
    await Promise.all([this.consumer.connect(), this.producer.connect(), DLQPublisher.init(this.kafka)]);

    await this.consumer.subscribe({ topic: CONFIG.rawMetricsTopic, fromBeginning: false });

    this.consumer.run({
      autoCommit: true,
      eachMessage: async (payload) => {
        if (this.shuttingDown) return;
        await this.pipeline.handle(payload);
      },
    });

    this.handleProcessSignals();

    logger.info(`SocialContextEnricherService started. Listening on topic "${CONFIG.rawMetricsTopic}"`);
  }

  private handleProcessSignals() {
    const graceful = async () => {
      if (this.shuttingDown) return;
      this.shuttingDown = true;
      logger.info('Shutting down gracefully…');
      await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
      process.exit(0);
    };

    process.on('SIGTERM', graceful);
    process.on('SIGINT', graceful);
  }
}

/* -------------------------------------------------------------------------- */
/*                                 Bootstrap                                  */
/* -------------------------------------------------------------------------- */

if (require.main === module) {
  // Only run when executed directly (not when imported for tests)
  const service = new SocialContextEnricherService();
  service.start().catch((err) => {
    logger.fatal({ err }, 'Fatal error while starting service');
    process.exit(1);
  });
}
```
