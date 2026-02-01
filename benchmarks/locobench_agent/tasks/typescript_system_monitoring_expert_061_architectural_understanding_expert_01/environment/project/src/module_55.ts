```typescript
/***************************************************************************************************
 *  PulseSphere SocialOps – System Monitoring Platform
 *  -----------------------------------------------------------------------------------------------
 *  File:          src/module_55.ts
 *  Responsibility: “Metric-SocialSignal Enrichment Service”
 *                  Listens to low-level infrastructure metric events, enriches them with
 *                  high-frequency social-interaction signals (likes/comments/shares, etc.),
 *                  and republishes a unified, socially-aware metric record downstream.
 *
 *  Architectural Patterns Illustrated:
 *      • Chain-of-Responsibility – modular enrichment pipeline
 *      • Strategy – pluggable capacity-forecast strategies
 *      • Observer/Event-Driven – Kafka-based pub/sub
 *
 *  External Dependencies:
 *      – kafkajs               (High-throughput, battle-tested Kafka client)
 *      – axios                 (HTTP client for service-mesh look-ups)
 *      – winston               (Structured logging)
 *      – uuid                  (ID generation for correlation context)
 *      – dotenv                (12-Factor configuration management)
 ***************************************************************************************************/

import { Kafka, Consumer, Producer, EachMessagePayload, logLevel as KafkaLogLevel } from 'kafkajs';
import axios, { AxiosInstance } from 'axios';
import winston from 'winston';
import { v4 as uuid } from 'uuid';
import * as dotenv from 'dotenv';

// Load environment variables ASAP
dotenv.config();

/**
 * ---------------------------------------------------------------------------------------------
 *  Configuration Layer
 * ---------------------------------------------------------------------------------------------*/
const CONFIG = {
    kafka: {
        brokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
        clientId: process.env.KAFKA_CLIENT_ID || 'pulse-sphere-socialops-metric-enricher',
        groupId: process.env.KAFKA_GROUP_ID || 'metric-enricher-group',
        sourceTopic: process.env.KAFKA_SOURCE_TOPIC || 'infrastructure.metrics',
        targetTopic: process.env.KAFKA_TARGET_TOPIC || 'enriched.metrics',
        consumerConcurrency: Number(process.env.CONSUMER_CONCURRENCY) || 3,
    },
    services: {
        socialSignalEndpoint: process.env.SOCIAL_SIGNAL_ENDPOINT || 'http://social-graph-query/api/v1/signals',
    },
    enrichment: {
        trendingLikeThreshold: Number(process.env.TRENDING_LIKE_THRESHOLD) || 5000,
    },
    logging: {
        level: (process.env.LOG_LEVEL as winston.LoggerOptions['level']) || 'info',
    },
} as const;

/**
 * ---------------------------------------------------------------------------------------------
 *  Logger
 * ---------------------------------------------------------------------------------------------*/
const logger = winston.createLogger({
    level: CONFIG.logging.level,
    transports: [
        new winston.transports.Console({
            format: winston.format.combine(
                winston.format.colorize({ all: true }),
                winston.format.timestamp(),
                winston.format.printf(({ level, message, timestamp }) => `${timestamp} [${level}]: ${message}`),
            ),
        }),
    ],
});

/**
 * ---------------------------------------------------------------------------------------------
 *  Domain Models
 * ---------------------------------------------------------------------------------------------*/
export interface MetricEvent {
    id: string;
    serviceName: string;
    hostname: string;
    timestamp: number; // epoch millis
    metrics: Record<string, number>;
    // this will be added downstream
    socialSignals?: SocialSignalSnapshot;
    trending?: boolean;
    forecastedCapacity?: ForecastResult;
}

export interface SocialSignalSnapshot {
    likes: number;
    comments: number;
    shares: number;
    liveStreamingPeak: number;
}

export interface ForecastResult {
    projectedRPS: number;
    confidence: number; // 0..1
    strategy: string;
}

/**
 * ---------------------------------------------------------------------------------------------
 *  Chain-of-Responsibility Interfaces
 * ---------------------------------------------------------------------------------------------*/
interface Processor {
    setNext(next: Processor): Processor;
    process(event: MetricEvent): Promise<MetricEvent>;
}

/**
 * ---------------------------------------------------------------------------------------------
 *  Base Processor Class
 * ---------------------------------------------------------------------------------------------*/
abstract class AbstractProcessor implements Processor {
    private _next?: Processor;

    public setNext(next: Processor): Processor {
        this._next = next;
        return next;
    }

    public async process(event: MetricEvent): Promise<MetricEvent> {
        const processed = await this._process(event);
        if (this._next) {
            return this._next.process(processed);
        }
        return processed;
    }

    protected abstract _process(event: MetricEvent): Promise<MetricEvent>;
}

/**
 * ---------------------------------------------------------------------------------------------
 *  Concrete Processor – Social Signal Correlation
 * ---------------------------------------------------------------------------------------------*/
class SocialSignalProcessor extends AbstractProcessor {
    private readonly http: AxiosInstance;

    constructor(endpoint: string) {
        super();
        this.http = axios.create({ baseURL: endpoint, timeout: 3000 });
    }

    protected async _process(event: MetricEvent): Promise<MetricEvent> {
        try {
            const { data } = await this.http.get<SocialSignalSnapshot>('/byService', {
                params: { serviceName: event.serviceName },
            });

            event.socialSignals = data;
            logger.debug(`Social signals attached for [${event.serviceName}] -> ${JSON.stringify(data)}`);
        } catch (err) {
            logger.warn(`Unable to fetch social signals for ${event.serviceName}: ${(err as Error).message}`);
            // Leave socialSignals undefined but continue the chain
        }
        return event;
    }
}

/**
 * ---------------------------------------------------------------------------------------------
 *  Concrete Processor – Trending Detector
 * ---------------------------------------------------------------------------------------------*/
class TrendingDetectionProcessor extends AbstractProcessor {
    protected async _process(event: MetricEvent): Promise<MetricEvent> {
        if (!event.socialSignals) {
            event.trending = false;
            return event;
        }
        const { likes, shares, liveStreamingPeak } = event.socialSignals;
        const trendingScore = likes + shares * 2 + liveStreamingPeak * 3; // naive formula

        event.trending = trendingScore > CONFIG.enrichment.trendingLikeThreshold;
        logger.debug(
            `Trending evaluation for ${event.serviceName}: score=${trendingScore} trending=${event.trending}`,
        );
        return event;
    }
}

/**
 * ---------------------------------------------------------------------------------------------
 *  Strategy Pattern – Capacity Forecasting
 * ---------------------------------------------------------------------------------------------*/
interface ForecastStrategy {
    name: string;
    forecast(event: MetricEvent): Promise<ForecastResult | null>;
}

class SimpleLinearForecastStrategy implements ForecastStrategy {
    public name = 'SimpleLinear';

    public async forecast(event: MetricEvent): Promise<ForecastResult | null> {
        const cpu = event.metrics['cpu_usage'];
        const rps = event.metrics['requests_per_second'];

        if (cpu === undefined || rps === undefined) {
            return null;
        }
        const projectedRPS = cpu > 80 ? rps * 1.5 : rps * 1.1; // naive projection
        return {
            projectedRPS,
            confidence: 0.55,
            strategy: this.name,
        };
    }
}

class MLForecastStrategy implements ForecastStrategy {
    public name = 'MLModel';

    public async forecast(event: MetricEvent): Promise<ForecastResult | null> {
        // In real life, an ML microservice or on-device model would handle this.
        // Here we mock with pseudo-randomness.
        const baseline = event.metrics['requests_per_second'] || 0;
        const projectedRPS = baseline * (1.2 + Math.random() * 0.3);

        return {
            projectedRPS,
            confidence: 0.8,
            strategy: this.name,
        };
    }
}

/**
 * ---------------------------------------------------------------------------------------------
 *  Concrete Processor – Forecast Processor (Strategy Pattern inside)
 * ---------------------------------------------------------------------------------------------*/
class ForecastProcessor extends AbstractProcessor {
    private readonly strategies: ForecastStrategy[];

    constructor(strategies: ForecastStrategy[]) {
        super();
        this.strategies = strategies;
    }

    protected async _process(event: MetricEvent): Promise<MetricEvent> {
        for (const strategy of this.strategies) {
            try {
                const result = await strategy.forecast(event);
                if (result) {
                    event.forecastedCapacity = result;
                    logger.debug(
                        `Forecast added by strategy [${strategy.name}] for service ${event.serviceName}: ${JSON.stringify(
                            result,
                        )}`,
                    );
                    break; // first successful strategy wins
                }
            } catch (err) {
                logger.error(`Forecast strategy [${strategy.name}] failed: ${(err as Error).message}`);
            }
        }
        return event;
    }
}

/**
 * ---------------------------------------------------------------------------------------------
 *  Kafka Connectivity
 * ---------------------------------------------------------------------------------------------*/
class KafkaBridge {
    private readonly kafka: Kafka;
    private readonly consumer: Consumer;
    private readonly producer: Producer;

    constructor() {
        this.kafka = new Kafka({
            clientId: CONFIG.kafka.clientId,
            brokers: CONFIG.kafka.brokers,
            logLevel: KafkaLogLevel.ERROR,
        });

        this.consumer = this.kafka.consumer({ groupId: CONFIG.kafka.groupId });
        this.producer = this.kafka.producer({ allowAutoTopicCreation: true });
    }

    public async init(): Promise<void> {
        await Promise.all([this.producer.connect(), this.consumer.connect()]);
        await this.consumer.subscribe({ topic: CONFIG.kafka.sourceTopic, fromBeginning: false });
        logger.info('KafkaBridge connected.');
    }

    public async runPipeline(pipeline: Processor): Promise<void> {
        await this.consumer.run({
            partitionsConsumedConcurrently: CONFIG.kafka.consumerConcurrency,
            eachMessage: async (payload: EachMessagePayload): Promise<void> => {
                const { topic, partition, message } = payload;
                try {
                    const raw = message.value?.toString('utf8') || '{}';
                    const metricEvent: MetricEvent = JSON.parse(raw);
                    logger.debug(`Received event ${metricEvent.id} on ${topic}.${partition}`);

                    const enrichedEvent = await pipeline.process(metricEvent);

                    await this.producer.send({
                        topic: CONFIG.kafka.targetTopic,
                        messages: [
                            {
                                key: enrichedEvent.id,
                                value: JSON.stringify(enrichedEvent),
                                headers: {
                                    'x-correlation-id': uuid(),
                                    'source-topic': topic,
                                },
                            },
                        ],
                    });

                    logger.debug(`Published enriched event ${enrichedEvent.id} to ${CONFIG.kafka.targetTopic}`);
                } catch (err) {
                    logger.error(
                        `Error processing message at ${topic}[${partition}] offset ${message.offset}: ${
                            (err as Error).stack || (err as Error).message
                        }`,
                    );
                    // Commit offset anyway to avoid poison pill loops – consider DLQ in production
                }
            },
        });
    }

    public async shutdown(): Promise<void> {
        await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
    }
}

/**
 * ---------------------------------------------------------------------------------------------
 *  Bootstrap
 * ---------------------------------------------------------------------------------------------*/
async function bootstrap(): Promise<void> {
    // Build processing pipeline
    const socialProcessor = new SocialSignalProcessor(CONFIG.services.socialSignalEndpoint);
    const trendingProcessor = new TrendingDetectionProcessor();
    const forecastProcessor = new ForecastProcessor([
        new SimpleLinearForecastStrategy(),
        new MLForecastStrategy(),
    ]);

    socialProcessor.setNext(trendingProcessor).setNext(forecastProcessor);

    // Kafka bridge
    const bridge = new KafkaBridge();
    await bridge.init();

    // Graceful shutdown
    const shutdown = async (): Promise<void> => {
        logger.info('Shutting down gracefully...');
        await bridge.shutdown();
        process.exit(0);
    };
    process.on('SIGTERM', shutdown);
    process.on('SIGINT', shutdown);

    logger.info('Metric-SocialSignal Enrichment Service is up and running.');
    await bridge.runPipeline(socialProcessor);
}

// Initialize service
bootstrap().catch((err) => {
    logger.error(`Fatal error on startup: ${(err as Error).stack || (err as Error).message}`);
    process.exit(1);
});
```