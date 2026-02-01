```typescript
/**
 * src/module_39.ts
 *
 * Dynamic Capacity Orchestration – Social-Aware Autoscaler
 * --------------------------------------------------------
 * This module implements an event-driven, strategy-based engine that translates
 * infrastructure + social-interaction metrics into autoscaling actions.
 *
 * Patterns used
 *  • Strategy              – Pluggable ScaleStrategy implementations
 *  • Chain-of-Responsibility – Ordered evaluation of strategies
 *  • Observer (RxJS)       – Streaming metric ingestion
 *
 * External deps (peer dependencies in the monorepo):
 *  • kafkajs        – Kafka client for high-throughput telemetry ingestion
 *  • rxjs           – Reactive Streams
 *  • @pulse/config  – Centralised configuration utility
 *  • @pulse/logger  – Structured logger (wrapping pino)
 */

import { Kafka, Consumer, EachMessagePayload, logLevel } from 'kafkajs';
import {
    Observable,
    Subject,
    combineLatest,
    debounceTime,
    filter,
    map,
    merge,
    takeUntil,
} from 'rxjs';

import { Config } from '@pulse/config';
import { logger } from '@pulse/logger';

/* ------------------------------------------------------------------------- */
/*                              Domain Models                                */
/* ------------------------------------------------------------------------- */

export type InfrastructureMetrics = Readonly<{
    serviceName: string;
    cpuUsagePercent: number;       // 0 – 100
    memoryUsagePercent: number;    // 0 – 100
    requestsPerSecond: number;
    errorRatePercent: number;      // 0 – 100
    replicas: number;
    ts: number;                    // epoch millis
}>;

export type SocialMetrics = Readonly<{
    serviceName: string;
    likesPerMinute: number;
    commentsPerMinute: number;
    sharesPerMinute: number;
    activeLiveStreams: number;
    trendingHashtags: string[];
    trendingScore: number;         // 0 – 100
    ts: number;
}>;

export type MetricBundle = Readonly<{
    infra: InfrastructureMetrics;
    social: SocialMetrics;
}>;

export type ScaleAction =
    | Readonly<{
          serviceName: string;
          action: 'scale_up';
          desiredReplicas: number;
          reason: string;
          ts: number;
      }>
    | Readonly<{
          serviceName: string;
          action: 'scale_down' | 'no_action';
          desiredReplicas?: number;
          reason: string;
          ts: number;
      }>;

/* ------------------------------------------------------------------------- */
/*                        Strategy Pattern Interfaces                        */
/* ------------------------------------------------------------------------- */

/**
 * A strategy receives a MetricBundle and decides whether scaling is required.
 * Returning `null` signals that the strategy cannot (or chooses not to) decide.
 */
export interface ScaleStrategy {
    name: string;
    evaluate(bundle: MetricBundle): Promise<ScaleAction | null>;
}

/* ------------------------------------------------------------------------- */
/*                         Concrete Strategy: Hashtag Surge                  */
/* ------------------------------------------------------------------------- */

class HashtagSurgeStrategy implements ScaleStrategy {
    readonly name = 'HashtagSurgeStrategy';

    constructor(
        private readonly surgeThreshold: number = 65, // trendingScore threshold
        private readonly surgeMultiplier: number = 1.5,
        private readonly maxReplicas: number = 50,
    ) {}

    async evaluate(bundle: MetricBundle): Promise<ScaleAction | null> {
        const { social, infra } = bundle;

        if (social.trendingScore < this.surgeThreshold) {
            return null;
        }

        const desired = Math.min(
            Math.ceil(infra.replicas * this.surgeMultiplier),
            this.maxReplicas,
        );

        if (desired <= infra.replicas) {
            // Already at or above desired replicas
            return null;
        }

        return {
            serviceName: infra.serviceName,
            action: 'scale_up',
            desiredReplicas: desired,
            reason: `Trending score ${social.trendingScore} exceeds threshold ${this.surgeThreshold}`,
            ts: Date.now(),
        };
    }
}

/* ------------------------------------------------------------------------- */
/*                 Concrete Strategy: Resource Saturation                    */
/* ------------------------------------------------------------------------- */

class SaturationStrategy implements ScaleStrategy {
    readonly name = 'SaturationStrategy';

    constructor(
        private readonly cpuThreshold: number = 85,
        private readonly memThreshold: number = 85,
        private readonly errorRateThreshold: number = 10,
        private readonly scaleStep: number = 2,
        private readonly maxReplicas: number = 100,
        private readonly minReplicas: number = 1,
    ) {}

    async evaluate(bundle: MetricBundle): Promise<ScaleAction | null> {
        const { infra } = bundle;
        const { cpuUsagePercent, memoryUsagePercent, errorRatePercent } = infra;

        // Up-scaling logic
        if (
            cpuUsagePercent > this.cpuThreshold ||
            memoryUsagePercent > this.memThreshold ||
            errorRatePercent > this.errorRateThreshold
        ) {
            const desired = Math.min(infra.replicas + this.scaleStep, this.maxReplicas);
            if (desired > infra.replicas) {
                return {
                    serviceName: infra.serviceName,
                    action: 'scale_up',
                    desiredReplicas: desired,
                    reason: `Resource saturation detected (cpu=${cpuUsagePercent}%, mem=${memoryUsagePercent}%, error=${errorRatePercent}%)`,
                    ts: Date.now(),
                };
            }
            return null;
        }

        // Down-scaling logic
        if (
            cpuUsagePercent < this.cpuThreshold * 0.4 &&
            memoryUsagePercent < this.memThreshold * 0.4 &&
            errorRatePercent < this.errorRateThreshold * 0.2 &&
            infra.replicas > this.minReplicas
        ) {
            const desired = Math.max(infra.replicas - this.scaleStep, this.minReplicas);
            return {
                serviceName: infra.serviceName,
                action: 'scale_down',
                desiredReplicas: desired,
                reason: `Resources underutilised (cpu=${cpuUsagePercent}%, mem=${memoryUsagePercent}%)`,
                ts: Date.now(),
            };
        }

        return null;
    }
}

/* ------------------------------------------------------------------------- */
/*                        Chain-of-Responsibility Engine                     */
/* ------------------------------------------------------------------------- */

class ScaleDecisionEngine {
    private readonly strategies: ScaleStrategy[];

    constructor(strategies: ScaleStrategy[]) {
        this.strategies = strategies;
    }

    /**
     * Evaluate all strategies in order. The first non-null action is chosen.
     */
    async decide(bundle: MetricBundle): Promise<ScaleAction> {
        for (const strategy of this.strategies) {
            try {
                const res = await strategy.evaluate(bundle);
                if (res) {
                    logger.debug(
                        {
                            strategy: strategy.name,
                            service: bundle.infra.serviceName,
                            action: res.action,
                        },
                        'Scale strategy produced decision',
                    );
                    return res;
                }
            } catch (err) {
                logger.error(
                    { err, strategy: strategy.name },
                    'Strategy evaluation failed, continuing chain',
                );
            }
        }

        return {
            serviceName: bundle.infra.serviceName,
            action: 'no_action',
            reason: 'No strategy triggered',
            ts: Date.now(),
        };
    }
}

/* ------------------------------------------------------------------------- */
/*                              Kafka Helpers                                */
/* ------------------------------------------------------------------------- */

interface KafkaConsumerConfig {
    brokers: string[];
    groupId: string;
    topic: string;
}

/**
 * Builds an RxJS observable from a Kafka topic.
 */
function kafkaTopic$(
    kafka: Kafka,
    { brokers, groupId, topic }: KafkaConsumerConfig,
): Observable<string> {
    const shutdown$ = new Subject<void>();
    const out$ = new Subject<string>();

    async function start(): Promise<void> {
        const consumer: Consumer = kafka.consumer({ groupId });
        await consumer.connect();
        await consumer.subscribe({ topic, fromBeginning: false });

        await consumer.run({
            eachMessage: async ({ message }: EachMessagePayload) => {
                if (message.value) {
                    out$.next(message.value.toString());
                }
            },
        });

        shutdown$.subscribe(async () => {
            await consumer.disconnect();
            out$.complete();
        });
    }

    // Fire and forget
    start().catch((err) => {
        logger.error({ err, topic }, 'Kafka consumer failure');
        shutdown$.next();
    });

    return out$.asObservable();
}

/* ------------------------------------------------------------------------- */
/*                      Ingestion + Decision Orchestration                   */
/* ------------------------------------------------------------------------- */

class Autoscaler {
    private readonly kafka: Kafka;
    private readonly engine: ScaleDecisionEngine;

    constructor(private readonly cfg: Config) {
        this.kafka = new Kafka({
            brokers: cfg.getStringArray('kafka.brokers'),
            clientId: 'pulse-autoscaler',
            logLevel: logLevel.ERROR,
        });

        this.engine = new ScaleDecisionEngine([
            new HashtagSurgeStrategy(),
            new SaturationStrategy(),
            // Additional strategies can be composed here
        ]);
    }

    run(): void {
        const infraTopicCfg: KafkaConsumerConfig = {
            brokers: this.cfg.getStringArray('kafka.brokers'),
            groupId: 'autoscaler-infra',
            topic: 'infra.metrics',
        };

        const socialTopicCfg: KafkaConsumerConfig = {
            brokers: this.cfg.getStringArray('kafka.brokers'),
            groupId: 'autoscaler-social',
            topic: 'social.metrics',
        };

        const infra$ = kafkaTopic$(this.kafka, infraTopicCfg).pipe(
            map((json) => JSON.parse(json) as InfrastructureMetrics),
        );

        const social$ = kafkaTopic$(this.kafka, socialTopicCfg).pipe(
            map((json) => JSON.parse(json) as SocialMetrics),
        );

        /**
         * Combine latest infra + social metrics for the same service.
         * Assumes at-least-once delivery and merges by serviceName only.
         */
        const bundle$ = combineLatest([infra$, social$]).pipe(
            filter(
                ([infra, social]) =>
                    infra.serviceName === social.serviceName &&
                    Math.abs(infra.ts - social.ts) < 60_000, // 1-minute tolerance
            ),
            map(([infra, social]) => ({ infra, social } as MetricBundle)),
            debounceTime(1_000), // reduce chatter
        );

        bundle$.subscribe({
            next: (bundle) => this.handleBundle(bundle),
            error: (err) => logger.error({ err }, 'Bundle stream error'),
        });
    }

    private async handleBundle(bundle: MetricBundle): Promise<void> {
        const action = await this.engine.decide(bundle);
        if (action.action === 'no_action') {
            logger.debug({ action }, 'No scaling action required');
            return;
        }

        // In real deployment, emit action to Command Bus / Kubernetes Operator
        logger.info({ action }, 'Dispatching scale action');
        // TODO: implement dispatch logic
    }
}

/* ------------------------------------------------------------------------- */
/*                              Bootstrapping                                */
/* ------------------------------------------------------------------------- */

function boot(): void {
    const cfg = Config.load({ namespace: 'pulsesphere.socialops' });

    // Wrap boot in try/catch to ensure process exits cleanly on fatal error
    try {
        const autoscaler = new Autoscaler(cfg);
        autoscaler.run();
        logger.info('Autoscaler initialized');
    } catch (err) {
        logger.fatal({ err }, 'Failed to bootstrap autoscaler');
        process.exit(1);
    }
}

// Execute if launched directly
if (require.main === module) {
    boot();
}
```
