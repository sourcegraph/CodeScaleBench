```typescript
/**
 *  PulseSphere SocialOps – System Monitoring
 *  File: src/module_47.ts
 *
 *  AdaptiveScalingCoordinator:
 *  • Consumes near-real-time social-interaction signals + infrastructure metrics from Kafka topics
 *  • Periodically aggregates them into a TelemetrySnapshot
 *  • Chooses an appropriate ScalingStrategy (Strategy-Pattern) based on the snapshot
 *  • Executes the generated ScalingCommands through a Chain-of-Responsibility of RemediationHandlers
 *
 *  External deps (provided by the shared workspace docker image):
 *  • kafkajs                – durable Kafka client
 *  • rxjs                   – reactive in-memory streams
 *  • prom-client            – Prometheus metrics exposition
 *  • pino                   – structured logger
 *
 *  NOTE: The file purposefully contains no default export to avoid accidentally initialising the
 *        coordinator when imported by test-suites.  Import { coordinator } where side-effects
 *        are desired (e.g. in the service’s top-level runner).
 */

import { Kafka, EachMessagePayload } from 'kafkajs';
import {
    Subject,
    merge,
    timer,
    Observable,
    Subscription,
} from 'rxjs';
import {
    bufferTime,
    map,
    filter,
    catchError,
} from 'rxjs/operators';
import pino from 'pino';
import * as promClient from 'prom-client';

// -----------------------------------------------------------------------------
// Domain Models
// -----------------------------------------------------------------------------

export interface SocialSignal {
    readonly type: 'like' | 'comment' | 'share' | 'live_stream';
    readonly count: number;
    readonly hashtag?: string;
    readonly timestamp: number; // epoch ms
}

export interface InfraMetric {
    readonly cpu: number;  // %
    readonly mem: number;  // %
    readonly latency: number; // ms
    readonly node: string;
    readonly timestamp: number; // epoch ms
}

export interface AggregatedSocial {
    readonly totalInteractions: number;
    readonly liveStreamSpikes: number;
    readonly hottestHashtag?: string;
}

export interface AggregatedInfra {
    readonly avgCpu: number;
    readonly avgMem: number;
    readonly p95Latency: number;
    readonly nodes: number;
}

export interface TelemetrySnapshot {
    readonly social: AggregatedSocial;
    readonly infra: AggregatedInfra;
}

// -----------------------------------------------------------------------------
// Logger
// -----------------------------------------------------------------------------

const log = pino({
    name: 'AdaptiveScalingCoordinator',
    level: process.env.LOG_LEVEL ?? 'info',
});

// -----------------------------------------------------------------------------
// Prometheus Metrics
// -----------------------------------------------------------------------------

const commandCounter = new promClient.Counter({
    name: 'ps_scaling_commands_total',
    help: 'Total number of scaling commands issued',
    labelNames: ['strategy', 'command'],
});

const snapshotGauge = new promClient.Gauge({
    name: 'ps_snapshot_total_interactions',
    help: 'Total interactions seen in last snapshot',
});

// -----------------------------------------------------------------------------
// Strategy Pattern – ScalingStrategy
// -----------------------------------------------------------------------------

export interface ScalingStrategy {
    readonly id: string;
    /**
     * Decide which commands to run based on telemetry.
     */
    decide(snapshot: TelemetrySnapshot): ScalingCommand[];
}

/**
 * Strategy #1 – Horizontal Pod Autoscaling
 */
class HorizontalScalingStrategy implements ScalingStrategy {
    public readonly id = 'horizontal';

    decide(snapshot: TelemetrySnapshot): ScalingCommand[] {
        const commands: ScalingCommand[] = [];
        const { avgCpu, avgMem } = snapshot.infra;
        const { totalInteractions, liveStreamSpikes } = snapshot.social;

        if (avgCpu > 70 || avgMem > 70 || liveStreamSpikes > 0) {
            const replicas = Math.min(
                Math.ceil(totalInteractions / 10_000) + 3,
                100,
            );
            commands.push(new ScalePodsCommand(replicas));
        }
        return commands;
    }
}

/**
 * Strategy #2 – CDN Cache Warming
 */
class CacheWarmupStrategy implements ScalingStrategy {
    public readonly id = 'cache-warmup';

    decide(snapshot: TelemetrySnapshot): ScalingCommand[] {
        const commands: ScalingCommand[] = [];
        const { hottestHashtag } = snapshot.social;
        if (hottestHashtag) {
            commands.push(new WarmupCacheCommand(`/topic/${hottestHashtag}`));
        }
        return commands;
    }
}

// -----------------------------------------------------------------------------
// Command Pattern – ScalingCommand
// -----------------------------------------------------------------------------

export interface ScalingCommand {
    readonly type: string;
    execute(): Promise<void>;
}

/**
 * Concrete Command – ScalePods
 */
class ScalePodsCommand implements ScalingCommand {
    public readonly type = 'ScalePodsCommand';
    constructor(private readonly replicas: number) {}

    async execute(): Promise<void> {
        log.info(
            { replicas: this.replicas },
            'Executing ScalePodsCommand (stubbed)',
        );
        // Here you would call Kubernetes API / service-mesh sidecar etc.
        // Simulate async network latency:
        await new Promise((res) => setTimeout(res, 200));
    }
}

/**
 * Concrete Command – WarmupCache
 */
class WarmupCacheCommand implements ScalingCommand {
    public readonly type = 'WarmupCacheCommand';
    constructor(private readonly path: string) {}

    async execute(): Promise<void> {
        log.info(
            { path: this.path },
            'Executing WarmupCacheCommand (stubbed)',
        );
        await new Promise((res) => setTimeout(res, 100));
    }
}

// -----------------------------------------------------------------------------
// Chain-of-Responsibility – Remediation Handlers
// -----------------------------------------------------------------------------

export interface RemediationHandler {
    setNext(next: RemediationHandler): RemediationHandler;
    handle(command: ScalingCommand): Promise<void>;
}

abstract class BaseHandler implements RemediationHandler {
    private nextHandler?: RemediationHandler;

    public setNext(next: RemediationHandler): RemediationHandler {
        this.nextHandler = next;
        return next;
    }

    public async handle(command: ScalingCommand): Promise<void> {
        const processed = await this.process(command);
        if (!processed && this.nextHandler) {
            await this.nextHandler.handle(command);
        } else if (!processed) {
            log.warn(
                { command: command.type },
                'No handler processed the command',
            );
        }
    }

    protected abstract process(command: ScalingCommand): Promise<boolean>;
}

/**
 * Handler – Primary Cluster API
 */
class ClusterApiHandler extends BaseHandler {
    protected async process(cmd: ScalingCommand): Promise<boolean> {
        // For demonstration, assume ScalePodsCommand is handled here
        if (cmd instanceof ScalePodsCommand) {
            await cmd.execute();
            return true;
        }
        return false;
    }
}

/**
 * Handler – CDN Management API
 */
class CdnApiHandler extends BaseHandler {
    protected async process(cmd: ScalingCommand): Promise<boolean> {
        if (cmd instanceof WarmupCacheCommand) {
            await cmd.execute();
            return true;
        }
        return false;
    }
}

// -----------------------------------------------------------------------------
// Kafka Consumer utilities (tiny wrapper around kafkajs for rxjs integration)
// -----------------------------------------------------------------------------

interface KafkaConsumerConfig {
    readonly groupId: string;
    readonly topic: string;
}

class RxKafkaConsumer<T> {
    private readonly subject = new Subject<T>();

    constructor(
        private readonly kafka: Kafka,
        private readonly config: KafkaConsumerConfig,
        private readonly parser: (msg: Buffer) => T,
    ) {}

    public messages(): Observable<T> {
        return this.subject.asObservable();
    }

    async start(): Promise<void> {
        const consumer = this.kafka.consumer({ groupId: this.config.groupId });
        await consumer.connect();
        await consumer.subscribe({ topic: this.config.topic });

        await consumer.run({
            eachMessage: async (payload: EachMessagePayload) => {
                try {
                    const parsed = this.parser(payload.message.value!);
                    this.subject.next(parsed);
                } catch (err) {
                    log.error(
                        { err },
                        `Failed to parse message on topic ${this.config.topic}`,
                    );
                }
            },
        });
    }
}

// -----------------------------------------------------------------------------
// Adaptive Scaling Coordinator
// -----------------------------------------------------------------------------

export interface CoordinatorConfig {
    kafkaBrokers: string[];
    windowSizeMs?: number; // defaults to 15s
}

export class AdaptiveScalingCoordinator {
    private readonly kafka: Kafka;
    private readonly socialConsumer: RxKafkaConsumer<SocialSignal>;
    private readonly infraConsumer: RxKafkaConsumer<InfraMetric>;

    private readonly strategies: ScalingStrategy[];
    private readonly handlerChain: RemediationHandler;

    private subscriptions: Subscription[] = [];

    constructor(private readonly cfg: CoordinatorConfig) {
        this.kafka = new Kafka({ brokers: cfg.kafkaBrokers });

        this.socialConsumer = new RxKafkaConsumer<SocialSignal>(
            this.kafka,
            { groupId: 'social-signals-consumer', topic: 'social-signals' },
            (buf) => JSON.parse(buf.toString('utf-8')) as SocialSignal,
        );

        this.infraConsumer = new RxKafkaConsumer<InfraMetric>(
            this.kafka,
            { groupId: 'infra-metrics-consumer', topic: 'infra-metrics' },
            (buf) => JSON.parse(buf.toString('utf-8')) as InfraMetric,
        );

        this.strategies = [
            new HorizontalScalingStrategy(),
            new CacheWarmupStrategy(),
        ];

        // Build handler chain
        const clusterHandler = new ClusterApiHandler();
        const cdnHandler = new CdnApiHandler();
        clusterHandler.setNext(cdnHandler);
        this.handlerChain = clusterHandler;
    }

    async start(): Promise<void> {
        await Promise.all([
            this.socialConsumer.start(),
            this.infraConsumer.start(),
        ]);

        const windowSize = this.cfg.windowSizeMs ?? 15_000;

        // Merge two streams and buffer them
        const social$ = this.socialConsumer.messages();
        const infra$ = this.infraConsumer.messages();

        const subscription = merge(social$, infra$)
            .pipe(bufferTime(windowSize))
            .pipe(
                map((events): TelemetrySnapshot | null => {
                    if (events.length === 0) return null;

                    const socials = events.filter(
                        (e): e is SocialSignal =>
                            (e as SocialSignal).type !== undefined,
                    );
                    const infras = events.filter(
                        (e): e is InfraMetric =>
                            (e as InfraMetric).cpu !== undefined,
                    );

                    const snapshot = this.aggregate(socials, infras);
                    return snapshot;
                }),
                filter((snap): snap is TelemetrySnapshot => snap !== null),
                catchError((err, caught) => {
                    log.error({ err }, 'Stream processing error');
                    return caught;
                }),
            )
            .subscribe((snapshot) => {
                snapshotGauge.set(snapshot.social.totalInteractions);
                this.applyStrategies(snapshot).catch((err) =>
                    log.error({ err }, 'Failed to apply strategies'),
                );
            });

        this.subscriptions.push(subscription);

        log.info('AdaptiveScalingCoordinator started');
    }

    async stop(): Promise<void> {
        for (const sub of this.subscriptions) {
            sub.unsubscribe();
        }
        // Intentionally not disconnecting Kafka here (handled by service shutdown)
        log.info('AdaptiveScalingCoordinator stopped');
    }

    private aggregate(
        socials: SocialSignal[],
        infras: InfraMetric[],
    ): TelemetrySnapshot {
        // Social aggregation
        const totalInteractions = socials.reduce(
            (acc, s) => acc + s.count,
            0,
        );
        const liveStreamSpikes = socials
            .filter((s) => s.type === 'live_stream')
            .reduce((acc, s) => acc + s.count, 0);

        const hashtagFrequency = new Map<string, number>();
        for (const s of socials) {
            if (s.hashtag) {
                hashtagFrequency.set(
                    s.hashtag,
                    (hashtagFrequency.get(s.hashtag) ?? 0) + s.count,
                );
            }
        }
        const hottestHashtag =
            [...hashtagFrequency.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];

        // Infra aggregation
        const avgCpu =
            infras.reduce((acc, m) => acc + m.cpu, 0) /
            Math.max(infras.length, 1);
        const avgMem =
            infras.reduce((acc, m) => acc + m.mem, 0) /
            Math.max(infras.length, 1);
        const sortedLatency = [...infras]
            .map((m) => m.latency)
            .sort((a, b) => a - b);
        const p95Latency =
            sortedLatency[Math.floor(sortedLatency.length * 0.95)] ?? 0;

        const snapshot: TelemetrySnapshot = {
            social: {
                totalInteractions,
                liveStreamSpikes,
                hottestHashtag,
            },
            infra: {
                avgCpu,
                avgMem,
                p95Latency,
                nodes: new Set(infras.map((m) => m.node)).size,
            },
        };

        log.debug({ snapshot }, 'Aggregated snapshot');
        return snapshot;
    }

    private async applyStrategies(
        snapshot: TelemetrySnapshot,
    ): Promise<void> {
        for (const strat of this.strategies) {
            try {
                const commands = strat.decide(snapshot);
                for (const cmd of commands) {
                    commandCounter.inc({
                        strategy: strat.id,
                        command: cmd.type,
                    });
                    await this.handlerChain.handle(cmd);
                }
            } catch (err) {
                log.error(
                    { err, strategy: strat.id },
                    'Strategy processing failed',
                );
            }
        }
    }
}

// -----------------------------------------------------------------------------
// Coordinator singleton instance (lazy) – import elsewhere to start
// -----------------------------------------------------------------------------

export const coordinator = new AdaptiveScalingCoordinator({
    kafkaBrokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
});
```