```typescript
/**************************************************************************************************
 *  File:        src/module_41.ts
 *  Project:     PulseSphere SocialOps (system_monitoring)
 *  Description: Social-context–aware capacity-orchestration module.  Listens to a high–frequency
 *               telemetry stream enriched with social-engagement signals and decides—using a
 *               pluggable Strategy pattern—whether to scale clusters pre-emptively.  The module
 *               publishes CapacityCommand messages over NATS for downstream executors (e.g. K8s
 *               Operator, Nomad job-controller, etc.) to consume.
 *
 *  Architectural patterns demonstrated:
 *    • Observer      – RxJS observable pipeline for real-time telemetry ingestion
 *    • Strategy      – Multiple ScalingStrategy implementations can be injected
 *    • Chain-of-Resp – Trend detectors chained to classify viral scenarios
 *    • Command       – Emits self-describing CapacityCommand messages
 *
 *  NOTE: This file purposefully uses only public, stable APIs (nats, rxjs, pino) and domain
 *        interfaces that are assumed to exist elsewhere in the codebase (e.g. TelemetryBus).
 **************************************************************************************************/

/* eslint-disable @typescript-eslint/no-explicit-any */

import { connect, NatsConnection, StringCodec } from 'nats';
import { Observable, Subscription } from 'rxjs';
import { bufferTime, filter } from 'rxjs/operators';
import pino from 'pino';

/* -------------------------------------------------------------------------- */
/*                                Domain Types                                */
/* -------------------------------------------------------------------------- */

/** Fine-grained view of social engagement during a telemetry tick. */
export interface SocialEngagementMetrics {
    likes: number;
    comments: number;
    shares: number;
    activeUsers: number;
}

/** Rich, per-second snapshot coming from the unified telemetry stream. */
export interface MetricSnapshot {
    readonly timestamp: number;          // Unix epoch (ms)
    readonly clusterId: string;          // Logical cluster identifier
    readonly cpuUsage: number;           // % (0-100)
    readonly memoryUsage: number;        // % (0-100)
    readonly social: SocialEngagementMetrics;
}

/** Output of this module – the "Command" in the Command pattern parlance. */
export interface CapacityCommand {
    clusterId: string;
    desiredReplicas: number;
    reason: string;
    issuedAt: number;
}

/* -------------------------------------------------------------------------- */
/*                         Strategy Pattern ‑- Contracts                      */
/* -------------------------------------------------------------------------- */

export interface ScalingStrategy {
    /** 
     * @param snapshots  Time-ordered window of metric points
     * @returns          A CapacityCommand if scaling is required, otherwise null
     */
    decide(snapshots: MetricSnapshot[]): CapacityCommand | null;
}

/* -------------------------------------------------------------------------- */
/*                 Chain-of-Responsibility: Viral Trend Detectors             */
/* -------------------------------------------------------------------------- */

/** Categorises engagement trends into high-level viral events. */
export enum SocialEventType {
    Normal          = 'normal',
    ViralSpike      = 'viral_spike',
    InfluencerJoin  = 'influencer_join',
    HashtagTrend    = 'hashtag_trend'
}

/** Base interface for a single link in the detector chain. */
interface TrendDetector {
    setNext(next: TrendDetector): TrendDetector;
    detect(window: MetricSnapshot[]): SocialEventType | null;
}

/** Abstract link providing default chain traversal. */
abstract class AbstractTrendDetector implements TrendDetector {
    protected next?: TrendDetector;

    setNext(next: TrendDetector): TrendDetector {
        this.next = next;
        return next;
    }

    detect(window: MetricSnapshot[]): SocialEventType | null {
        const result = this.evaluate(window);
        if (result) return result;
        return this.next?.detect(window) ?? null;
    }

    protected abstract evaluate(window: MetricSnapshot[]): SocialEventType | null;
}

/** Detects sudden, large spikes of engagement volume. */
class ViralSpikeDetector extends AbstractTrendDetector {
    private readonly thresholdMultiplier = 3;

    protected evaluate(window: MetricSnapshot[]): SocialEventType | null {
        if (window.length < 2) return null;

        const latest = window[window.length - 1];
        const prev    = window[0]; // earliest in buffer

        const growth = latest.social.activeUsers / Math.max(prev.social.activeUsers, 1);

        if (growth >= this.thresholdMultiplier) {
            return SocialEventType.ViralSpike;
        }
        return null;
    }
}

/** Detects a well-known influencer entering the platform (domain service assumption). */
class InfluencerJoinDetector extends AbstractTrendDetector {
    protected evaluate(): SocialEventType | null {
        /* 
           In the real system we would query a UserPresenceCache or a Kafka topic with join events.
           Omitted here due to scope – return null to defer to next detector.
        */
        return null;
    }
}

/** Detects trending hashtags by heuristic (placeholder). */
class HashtagTrendDetector extends AbstractTrendDetector {
    protected evaluate(): SocialEventType | null {
        return null;
    }
}

/* -------------------------------------------------------------------------- */
/*                      Strategy Implementation – Trend-Aware                 */
/* -------------------------------------------------------------------------- */

export interface TrendAwareStrategyConfig {
    minReplicas: number;
    maxReplicas: number;
    cpuTarget: number;               // desired CPU utilisation %
    socialSpikeReplicaBoost: number; // how many replicas to add on viral spike
}

export class TrendAwareScalingStrategy implements ScalingStrategy {
    private readonly trendDetector: TrendDetector;

    constructor(private readonly cfg: TrendAwareStrategyConfig) {
        // Build detector chain
        const viral     = new ViralSpikeDetector();
        const join      = new InfluencerJoinDetector();
        const hashtag   = new HashtagTrendDetector();
        viral.setNext(join).setNext(hashtag);
        this.trendDetector = viral;
    }

    decide(window: MetricSnapshot[]): CapacityCommand | null {
        if (window.length === 0) return null;

        const latest = window[window.length - 1];
        const avgCpu = window.reduce((acc, s) => acc + s.cpuUsage, 0) / window.length;

        // 1) Decide based on CPU pressure (traditional Autoscaler style)
        let desired = Math.round(latest.cpuUsage / this.cfg.cpuTarget * latest.social.activeUsers / Math.max(window[0].social.activeUsers, 1));
        desired = Math.min(Math.max(desired, this.cfg.minReplicas), this.cfg.maxReplicas);

        // 2) See if social trend demands extra headroom
        const trend = this.trendDetector.detect(window);
        if (trend === SocialEventType.ViralSpike) {
            desired = Math.min(desired + this.cfg.socialSpikeReplicaBoost, this.cfg.maxReplicas);
        }

        // 3) If adjustment is needed, emit command
        const currentReplicas = this.estimateCurrentReplicas(latest.clusterId); // stubbed
        if (desired !== currentReplicas) {
            return {
                clusterId: latest.clusterId,
                desiredReplicas: desired,
                reason: trend ? `Auto-scale due to ${trend}` : 'Auto-scale due to CPU utilisation',
                issuedAt: Date.now()
            };
        }

        return null;
    }

    /** 
     * In production this would query a real source of truth (K8s, Nomad, etc.).
     * Here we mock the response.
     */
    private estimateCurrentReplicas(_clusterId: string): number {
        return this.cfg.minReplicas; // placeholder
    }
}

/* -------------------------------------------------------------------------- */
/*                       Orchestrator (Observer + Command)                    */
/* -------------------------------------------------------------------------- */

export interface OrchestratorConfig extends TrendAwareStrategyConfig {
    natsUrl: string;
    commandTopic: string;
    bufferWindowMs: number; // Sliding window duration fed into strategies
}

export class SocialCapacityOrchestrator {
    private readonly log = pino({ name: 'SocialCapacityOrchestrator' });
    private nats?: NatsConnection;
    private readonly codec = StringCodec();
    private readonly strategy: ScalingStrategy;
    private subscription?: Subscription;

    constructor(
        private readonly telemetry$: Observable<MetricSnapshot>, // Stream provided by TelemetryBus service
        private readonly cfg: OrchestratorConfig
    ) {
        this.strategy = new TrendAwareScalingStrategy(cfg);
    }

    /** Public entry – sets up NATS + stream subscriptions. */
    async init(): Promise<void> {
        await this.connectNats();
        this.attachTelemetryObserver();
        this.log.info('SocialCapacityOrchestrator initialised');
    }

    /** Clean shutdown – flush NATS and unsubscribe from Rx streams. */
    async dispose(): Promise<void> {
        this.subscription?.unsubscribe();
        if (this.nats) {
            await this.nats.drain();
            await this.nats.close();
        }
        this.log.info('SocialCapacityOrchestrator disposed');
    }

    /* ---------------------------------------------------------------------- */
    /*                           Private  Helpers                             */
    /* ---------------------------------------------------------------------- */

    private async connectNats(): Promise<void> {
        try {
            this.nats = await connect({ servers: this.cfg.natsUrl });
            this.log.info(`Connected to NATS at ${this.cfg.natsUrl}`);
        } catch (err) {
            this.log.fatal({ err }, 'Failed to connect to NATS – cannot continue');
            throw err;
        }
    }

    private attachTelemetryObserver(): void {
        this.subscription = this.telemetry$
            .pipe(
                bufferTime(this.cfg.bufferWindowMs),
                filter(buffer => buffer.length > 0)
            )
            .subscribe({
                next: (window) => this.handleWindow(window),
                error: (err) => this.log.error({ err }, 'Telemetry stream error'),
                complete: () => this.log.warn('Telemetry stream completed unexpectedly')
            });
    }

    private handleWindow(window: MetricSnapshot[]): void {
        try {
            const cmd = this.strategy.decide(window);
            if (cmd) this.publishCommand(cmd);
        } catch (err) {
            this.log.error({ err }, 'Failed to evaluate scaling strategy');
        }
    }

    private publishCommand(cmd: CapacityCommand): void {
        if (!this.nats) {
            this.log.error('NATS connection unavailable – cannot publish CapacityCommand');
            return;
        }

        try {
            const payload = this.codec.encode(JSON.stringify(cmd));
            this.nats.publish(this.cfg.commandTopic, payload);
            this.log.info({ cmd }, 'CapacityCommand published');
        } catch (err) {
            this.log.error({ err, cmd }, 'Error publishing CapacityCommand');
        }
    }
}

/* -------------------------------------------------------------------------- */
/*                            Bootstrapping (optional)                        */
/* -------------------------------------------------------------------------- */

/**
 * When this module is executed directly (e.g. in a worker role), spin up the orchestrator.
 * In unit tests or when imported by another service, the bootstrap is skipped.
 */
if (require.main === module) {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { fromEventPattern } = require('rxjs');

    // Demo/example: Convert a mock event emitter into an Observable<MetricSnapshot>
    const mockBus = new (require('events').EventEmitter)();

    const telemetry$ = fromEventPattern<MetricSnapshot>(
        (handler: (s: MetricSnapshot) => void) => mockBus.on('snapshot', handler),
        (handler: (s: MetricSnapshot) => void) => mockBus.off('snapshot', handler)
    );

    const cfg: OrchestratorConfig = {
        natsUrl: process.env.NATS_URL ?? 'nats://localhost:4222',
        commandTopic: 'capacity.command',
        bufferWindowMs: 5_000,
        minReplicas: 2,
        maxReplicas: 50,
        cpuTarget: 65,
        socialSpikeReplicaBoost: 5
    };

    const orchestrator = new SocialCapacityOrchestrator(telemetry$, cfg);
    orchestrator.init()
        .catch(err => {
            pino().fatal({ err }, 'Orchestrator failed to start');
            process.exit(1);
        });

    /* Periodically emit fake snapshots so that `npm start` shows behaviour */
    setInterval(() => {
        const snapshot: MetricSnapshot = {
            timestamp: Date.now(),
            clusterId: 'social-feed-cluster',
            cpuUsage: Math.random() * 100,
            memoryUsage: Math.random() * 100,
            social: {
                likes: Math.floor(Math.random() * 1_000),
                comments: Math.floor(Math.random() * 500),
                shares: Math.floor(Math.random() * 250),
                activeUsers: Math.floor(Math.random() * 10_000) + 100
            }
        };
        mockBus.emit('snapshot', snapshot);
    }, 1_000);
}
```