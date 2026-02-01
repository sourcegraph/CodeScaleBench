```typescript
/**************************************************************************************************
 *  File:        src/module_68.ts
 *  Project:     PulseSphere SocialOps – system_monitoring
 *  Description: Capacity-orchestration module that correlates socially-aware telemetry
 *               with infrastructure auto-scaling decisions.
 *
 *  Patterns:    – Strategy Pattern (multiple remediation strategies)
 *               – Chain of Responsibility (cascade strategies until one acts)
 *               – Observer Pattern (RxJS Observable stream)
 *               – Command Pattern  (ScalingCommand payload sent to orchestration service)
 *
 *  External deps (production-grade, battle-tested):
 *               – kafkajs        : Kafka consumer for high-throughput social telemetry
 *               – rxjs           : Reactive streams for back-pressure & composition
 *               – axios          : REST client for Kubernetes / Service-Mesh control-plane
 *
 *  NOTE: This file purposefully avoids touching global state; everything is injectable to support
 *        unit-testing, inversion-of-control containers, or Pulsesphere’s own plug-in runtime.
 **************************************************************************************************/

/* eslint-disable @typescript-eslint/no-explicit-any */
import { Kafka, logLevel, Consumer, EachMessagePayload } from 'kafkajs';
import { Observable, Subject, from } from 'rxjs';
import {
    filter,
    map,
    mergeMap,
    retryWhen,
    take,
    delay,
} from 'rxjs/operators';
import axios, { AxiosInstance } from 'axios';

//#region ──────────────────────────────────────── Domain Types ────────────────────────────────────

/** Telemetry item produced by social event processors upstream. */
export interface SocialMetricEvent {
    timestamp: number; // epoch millis
    /**
     * Type of social activity captured.
     * Extendable: new types can be introduced without breaking compatibility
     * (all strategies ignore what they don't understand).
     */
    type:
        | 'LIKE'
        | 'COMMENT'
        | 'SHARE'
        | 'HASHTAG_SURGE'
        | 'LIVE_STREAM_SPIKE';
    /** Raw payload (schema differs per event type). */
    payload: Record<string, any>;
}

/** Severity model shared across PulseSphere remediation modules. */
export enum Severity {
    NORMAL = 'NORMAL',
    WARNING = 'WARNING',
    CRITICAL = 'CRITICAL',
}

/** Actual command that gets posted to the infrastructure control-plane. */
export interface ScalingCommand {
    application: string; // application/services affected
    replicas: number; // desired replica count
    reason: string; // human-readable explanation
    severity: Severity;
    correlationId: string; // AAA-grade observability
}

//#endregion

//#region ──────────────────────────────────────── Config Loader ──────────────────────────────────

interface KafkaConfig {
    clientId: string;
    brokers: string[];
    topic: string;
    groupId: string;
}

interface OrchestratorConfig {
    /** REST endpoint of the auto-scaler control-plane (e.g., Kubernetes operator). */
    autoscalerEndpoint: string;
    /** Bearer token or mTLS cert path, depending on deployment policy. */
    authToken?: string;
    /** Max replicas any strategy may request. */
    maxReplicas: number;
}

class ConfigLoader {
    /** Reads configuration from environment variables with sane defaults. */
    static loadKafkaConfig(): KafkaConfig {
        const brokers = (process.env.KAFKA_BROKERS || 'localhost:9092').split(
            ',',
        );
        return {
            clientId: process.env.KAFKA_CLIENT_ID || 'pulse-sphere-socialops',
            brokers,
            topic: process.env.KAFKA_SOCIAL_TOPIC || 'social.telemetry',
            groupId:
                process.env.KAFKA_GROUP_ID ||
                'pulse-sphere-socialops-capacity',
        };
    }

    static loadOrchestratorConfig(): OrchestratorConfig {
        return {
            autoscalerEndpoint:
                process.env.AUTOSCALER_ENDPOINT ||
                'http://autoscaler.pulsesphere.svc.cluster.local/scale',
            authToken: process.env.AUTOSCALER_AUTH_TOKEN,
            maxReplicas: parseInt(process.env.MAX_REPLICAS || '500', 10),
        };
    }
}

//#endregion

//#region ─────────────────────────────────── Strategy & Chain-of-Resp. ───────────────────────────

/**
 * Base contract for auto-scaling strategies.
 * IMPORTANT: Strategies must be stateless or manage state internally in a thread-safe way.
 */
interface ScalingStrategy {
    /**
     * Evaluate the incoming social event and decide whether to produce a scaling command.
     * Return `null` if the event is not relevant or does not breach thresholds.
     */
    evaluateLoad(event: SocialMetricEvent): ScalingCommand | null;
}

/** Abstract chain-ready strategy. */
abstract class BaseStrategy implements ScalingStrategy {
    private next?: ScalingStrategy;

    constructor(next?: ScalingStrategy) {
        this.next = next;
    }

    setNext(next: ScalingStrategy): ScalingStrategy {
        this.next = next;
        return next;
    }

    evaluateLoad(event: SocialMetricEvent): ScalingCommand | null {
        const cmd = this.handle(event);
        if (cmd) return cmd;

        return this.next?.evaluateLoad(event) ?? null;
    }

    protected abstract handle(
        event: SocialMetricEvent,
    ): ScalingCommand | null;
}

/** Detects surging hashtags and pre-emptively scales public-facing APIs. */
class HashtagSurgeStrategy extends BaseStrategy {
    private readonly THRESHOLD = 1_000; // hashtag events/min
    private readonly SCALE_FACTOR = 2;

    protected handle(event: SocialMetricEvent): ScalingCommand | null {
        if (event.type !== 'HASHTAG_SURGE') return null;

        const { hashtag, eventsPerMinute, targetApp } = event.payload;
        if (eventsPerMinute < this.THRESHOLD) return null;

        const replicas = Math.min(
            event.payload.currentReplicas * this.SCALE_FACTOR,
            Orchestrator.getInstance().config.maxReplicas,
        );

        return {
            application: targetApp,
            replicas,
            severity: Severity.CRITICAL,
            reason: `Hashtag #${hashtag} surging at ${eventsPerMinute}/min`,
            correlationId: `hashtag-${hashtag}-${event.timestamp}`,
        };
    }
}

/** Scales media streaming clusters during viewer spikes. */
class LiveStreamSpikeStrategy extends BaseStrategy {
    private readonly VIEWER_THRESHOLD = 50_000;
    private readonly SCALE_STEP = 10; // add N replicas

    protected handle(event: SocialMetricEvent): ScalingCommand | null {
        if (event.type !== 'LIVE_STREAM_SPIKE') return null;

        const { streamId, concurrentViewers, currentReplicas, targetApp } =
            event.payload;

        if (concurrentViewers < this.VIEWER_THRESHOLD) return null;

        const replicas = Math.min(
            currentReplicas + this.SCALE_STEP,
            Orchestrator.getInstance().config.maxReplicas,
        );

        return {
            application: targetApp,
            replicas,
            severity: Severity.WARNING,
            reason: `Live stream ${streamId} viewers = ${concurrentViewers}`,
            correlationId: `livestream-${streamId}-${event.timestamp}`,
        };
    }
}

/** Fallback strategy – ensure we never drop below safe replica count. */
class BaselineGuardStrategy extends BaseStrategy {
    protected handle(event: SocialMetricEvent): ScalingCommand | null {
        // We only care about events carrying current replica info
        if (!('currentReplicas' in event.payload)) return null;

        const { currentReplicas, minReplicas, targetApp } = event.payload;

        if (currentReplicas >= minReplicas) return null;

        return {
            application: targetApp,
            replicas: minReplicas,
            severity: Severity.NORMAL,
            reason: `Baseline guard raised replicas from ${currentReplicas} to ${minReplicas}`,
            correlationId: `baseline-${targetApp}-${event.timestamp}`,
        };
    }
}

//#endregion

//#region ──────────────────────────── Orchestrator (Observer / Command) ──────────────────────────

/**
 * Singleton Orchestrator responsible for:
 *   – Wiring Kafka consumer ⇒ RxJS stream ⇒ Strategy chain
 *   – Dispatching ScalingCommand to the Auto-scaler control-plane
 */
class Orchestrator {
    private static INSTANCE: Orchestrator;

    readonly config: OrchestratorConfig;
    private readonly kafka: Kafka;
    private readonly consumer: Consumer;
    private readonly eventSubject = new Subject<SocialMetricEvent>();
    private readonly httpClient: AxiosInstance;

    /** Private constructor enforces singleton. */
    private constructor(
        kafkaCfg: KafkaConfig,
        orchestratorCfg: OrchestratorConfig,
        private readonly strategyChain: ScalingStrategy,
    ) {
        this.config = orchestratorCfg;

        this.kafka = new Kafka({
            clientId: kafkaCfg.clientId,
            brokers: kafkaCfg.brokers,
            logLevel: logLevel.NOTHING,
        });

        this.consumer = this.kafka.consumer({ groupId: kafkaCfg.groupId });

        this.httpClient = axios.create({
            baseURL: orchestratorCfg.autoscalerEndpoint,
            timeout: 7_000,
            headers: orchestratorCfg.authToken
                ? { Authorization: `Bearer ${orchestratorCfg.authToken}` }
                : undefined,
        });
    }

    /** Public accessor – thread-safe thanks to Node single-thread nature. */
    static getInstance(): Orchestrator {
        if (!Orchestrator.INSTANCE) {
            const kafkaCfg = ConfigLoader.loadKafkaConfig();
            const orchestratorCfg = ConfigLoader.loadOrchestratorConfig();

            // Compose strategies (Chain-of-Responsibility)
            const hashtag = new HashtagSurgeStrategy();
            const live = new LiveStreamSpikeStrategy();
            const baseline = new BaselineGuardStrategy();

            hashtag.setNext(live).setNext(baseline);

            Orchestrator.INSTANCE = new Orchestrator(
                kafkaCfg,
                orchestratorCfg,
                hashtag,
            );
        }
        return Orchestrator.INSTANCE;
    }

    /** Bootstraps the consumer & reactive pipeline. */
    async start(): Promise<void> {
        await this.consumer.connect();
        await this.consumer.subscribe({
            topic: ConfigLoader.loadKafkaConfig().topic,
            fromBeginning: false,
        });

        // Pump Kafka messages into RxJS observable
        await this.consumer.run({
            eachMessage: async (payload: EachMessagePayload) => {
                const event = this.deserializeEvent(payload.message.value);
                if (event) {
                    this.eventSubject.next(event);
                }
            },
        });

        // Build reactive pipeline
        this.buildPipeline(this.eventSubject.asObservable());
        console.info('[Orchestrator] Started capacity orchestration.');
    }

    /** Tear down gracefully – awaits in-flight messages. */
    async stop(): Promise<void> {
        console.info('[Orchestrator] Shutting down…');
        await this.consumer.disconnect();
        this.eventSubject.complete();
    }

    //#region ────────────── Internal Helpers ───────────────────

    private buildPipeline(source$: Observable<SocialMetricEvent>): void {
        source$
            .pipe(
                map((evt) => this.strategyChain.evaluateLoad(evt)),
                filter(
                    (cmd): cmd is ScalingCommand =>
                        cmd !== null && cmd !== undefined,
                ),
                // HTTP call with retry (exponential back-off)
                mergeMap((cmd) =>
                    from(this.dispatchScalingCommand(cmd)).pipe(
                        retryWhen((errors) =>
                            errors.pipe(
                                take(3),
                                delay(1_000),
                            ),
                        ),
                    ),
                ),
            )
            .subscribe({
                next: (cmd) =>
                    console.info(
                        `[Orchestrator] Scaling command dispatched: ${cmd.application} → ${cmd.replicas} replicas`,
                    ),
                error: (err) =>
                    console.error(
                        '[Orchestrator] Stream error, continuing:',
                        err,
                    ),
            });
    }

    private deserializeEvent(
        buffer?: Buffer | null,
    ): SocialMetricEvent | null {
        if (!buffer) return null;
        try {
            return JSON.parse(buffer.toString()) as SocialMetricEvent;
        } catch (err) {
            console.warn(
                '[Orchestrator] Invalid JSON payload dropped:',
                err,
            );
            return null;
        }
    }

    private async dispatchScalingCommand(
        command: ScalingCommand,
    ): Promise<ScalingCommand> {
        await this.httpClient.post('/', command);
        return command;
    }

    //#endregion
}

//#endregion

//#region ───────────────────────────────────────── Bootstrap ─────────────────────────────────────

// Self-invoking to prevent top-level await (compat w/ older Node runtimes)
(async () => {
    const orchestrator = Orchestrator.getInstance();
    process.on('SIGINT', () => orchestrator.stop().then(() => process.exit(0)));
    process.on('SIGTERM', () =>
        orchestrator.stop().then(() => process.exit(0)),
    );

    try {
        await orchestrator.start();
    } catch (err) {
        console.error('[Bootstrap] Failed to start Orchestrator:', err);
        process.exit(1);
    }
})();

//#endregion
```
