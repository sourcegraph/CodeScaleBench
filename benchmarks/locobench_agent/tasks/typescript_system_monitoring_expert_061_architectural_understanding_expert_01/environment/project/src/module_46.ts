```typescript
/**************************************************************************************************
 *  File:          src/module_46.ts
 *  Project:       PulseSphere SocialOps (system_monitoring)
 *  Description:   Social-aware, reactive auto-scaler that correlates infrastructure metrics with
 *                 real-time social-interaction signals, selects an appropriate scaling strategy,
 *                 and dispatches scaling commands through the central command-bus.
 *
 *  Architectural  Patterns Demonstrated
 *  ──────────────────────────────────────────────────────────────────────────────────────────────
 *  • Observer       – RxJS streams subscribe to Kafka topics → pushes data into evaluator.  
 *  • Strategy       – Pluggable scaling algorithms (Aggressive vs. Conservative, etc.).  
 *  • Command        – Generates ScaleUp / ScaleDown commands placed on a bus.  
 *  • Chain-of-Resp  – Validation guards form a lightweight CoR before commands reach the bus.  
 *
 *  External deps are imported via Domain packages (namespace: @pulseSphere/*). These packages are
 *  part of the overall mono-repo but **not** reproduced here. Each import is representative of
 *  realistic production code and can be replaced with actual implementations.
 **************************************************************************************************/

import { merge, Observable, Subject, throttleTime } from 'rxjs';
import { filter, map } from 'rxjs/operators';
import { Kafka, EachMessagePayload } from 'kafkajs';

import { Logger } from '@pulseSphere/common/logger';
import { Guard } from '@pulseSphere/common/guard';
import {
    ScaleUpCommand,
    ScaleDownCommand,
    ScalingCommandBus,
    ScalingCommand
} from '@pulseSphere/ops/command-bus';
import { Config } from '@pulseSphere/config';

/* -------------------------------------------------------------------------------------------------
 * Domain types
 * -----------------------------------------------------------------------------------------------*/
export interface InfraMetrics {
    readonly cpuUsage: number;          // %  (0 – 100)
    readonly memUsage: number;          // %  (0 – 100)
    readonly reqRate: number;          // RPS (requests per second)
    readonly replicaCount: number;     // current replicas
    readonly timestamp: number;        // epoch millis
}

export interface SocialPulse {
    readonly likes: number;
    readonly comments: number;
    readonly shares: number;
    readonly liveStreams: number;
    readonly timestamp: number;        // epoch millis
}

export interface ScalingContext {
    metrics: InfraMetrics;
    social: SocialPulse;
    config: AutoScalerConfig;
}

/* -------------------------------------------------------------------------------------------------
 * Config
 * -----------------------------------------------------------------------------------------------*/
export interface AutoScalerConfig {
    serviceName: string;
    maxReplicas: number;
    minReplicas: number;
    conservativeThreshold: number;      // CPU% under which we attempt scale-down
    aggressiveThreshold: number;        // CPU% over which we attempt scale-up
    socialSpikeMultiplier: number;      // RPS multiplier derived from social delta
    evaluationWindowMs: number;         // Throttle evaluation period
}

const defaultConfig: AutoScalerConfig = {
    serviceName: 'timeline-edge-api',
    maxReplicas: 96,
    minReplicas: 4,
    conservativeThreshold: 35,
    aggressiveThreshold: 65,
    socialSpikeMultiplier: 1.20,
    evaluationWindowMs: 5000
};

/* -------------------------------------------------------------------------------------------------
 * Strategy Pattern – scaling algorithms
 * -----------------------------------------------------------------------------------------------*/
export interface ScalingStrategy {
    readonly name: string;
    decide(ctx: ScalingContext): ScalingCommand | null;
}

/**
 * ConservativeStrategy
 *  – Drifts toward optimal resource use, cautious when scaling down.
 *  – Used when social activity is normal.
 */
class ConservativeStrategy implements ScalingStrategy {
    public readonly name = 'ConservativeStrategy';

    decide(ctx: ScalingContext): ScalingCommand | null {
        const { metrics, config } = ctx;
        if (metrics.cpuUsage < config.conservativeThreshold &&
            metrics.replicaCount > config.minReplicas) {

            const newReplicaCount = Math.max(
                config.minReplicas,
                Math.ceil(metrics.replicaCount * 0.9) // decrease by 10 %
            );

            return new ScaleDownCommand({
                serviceName: config.serviceName,
                from: metrics.replicaCount,
                to: newReplicaCount,
                reason: `CPU below ${config.conservativeThreshold}% (${metrics.cpuUsage}%)`
            });
        }

        return null;
    }
}

/**
 * AggressiveStrategy
 *  – Reacts quickly to spikes; scales up by social-aware multiplier.
 *  – Used when viral social events detected.
 */
class AggressiveStrategy implements ScalingStrategy {
    public readonly name = 'AggressiveStrategy';

    decide(ctx: ScalingContext): ScalingCommand | null {
        const { metrics, social, config } = ctx;

        // Social spike heuristics
        const socialRpsBoost = (social.likes + social.comments + social.shares) *
                               config.socialSpikeMultiplier;

        const projectedLoad = metrics.reqRate + socialRpsBoost;
        const projectedCpu  = (metrics.cpuUsage / metrics.reqRate) * projectedLoad;

        if (projectedCpu > config.aggressiveThreshold &&
            metrics.replicaCount < config.maxReplicas) {

            const factor           = projectedCpu / config.aggressiveThreshold;
            const additionalNeeded = Math.ceil((factor - 1) * metrics.replicaCount);

            const newReplicaCount  = Math.min(
                config.maxReplicas,
                metrics.replicaCount + additionalNeeded
            );

            return new ScaleUpCommand({
                serviceName: config.serviceName,
                from: metrics.replicaCount,
                to: newReplicaCount,
                reason: `Projected CPU ${projectedCpu.toFixed(1)}% (> ${config.aggressiveThreshold}%)`
            });
        }

        return null;
    }
}

/* -------------------------------------------------------------------------------------------------
 * Strategy selector – chooses best strategy for current context
 * -----------------------------------------------------------------------------------------------*/
class StrategyResolver {
    private readonly conservative = new ConservativeStrategy();
    private readonly aggressive   = new AggressiveStrategy();

    resolve(ctx: ScalingContext): ScalingStrategy {
        const socialIntensity = ctx.social.likes + ctx.social.comments + ctx.social.shares;

        // Heuristic: >10 000 aggregate interactions per evaluation window → aggressive
        if (socialIntensity > 10_000) {
            return this.aggressive;
        }

        return this.conservative;
    }
}

/* -------------------------------------------------------------------------------------------------
 * Chain-of-Responsibility (validation guards)
 * -----------------------------------------------------------------------------------------------*/
class ScalingValidationChain {
    private readonly guard = new Guard(Logger.child({ scope: 'ScalingValidation' }));

    validate(cmd: ScalingCommand): void {
        // Guard 1: sanity check
        this.guard.against(cmd.to <= 0, 'Replica target must be positive.');
        this.guard.against(cmd.from === cmd.to, 'Replica count unchanged.');

        // Guard 2: bounds check
        const cfg = cmd.meta.config as AutoScalerConfig;
        this.guard.against(cmd.to > cfg.maxReplicas,
            `Target replicas (${cmd.to}) exceed maximum (${cfg.maxReplicas}).`);
        this.guard.against(cmd.to < cfg.minReplicas,
            `Target replicas (${cmd.to}) below minimum (${cfg.minReplicas}).`);
    }
}

/* -------------------------------------------------------------------------------------------------
 * Observer Pattern – reactive event aggregation
 * -----------------------------------------------------------------------------------------------*/
interface StreamSources {
    infra$: Observable<InfraMetrics>;
    social$: Observable<SocialPulse>;
}

/* -------------------------------------------------------------------------------------------------
 * SocialAwareAutoScaler – main orchestrator
 * -----------------------------------------------------------------------------------------------*/
export class SocialAwareAutoScaler {
    private readonly log = Logger.child({ module: 'SocialAwareAutoScaler' });
    private readonly cfg: AutoScalerConfig;
    private readonly strategyResolver = new StrategyResolver();
    private readonly validationChain  = new ScalingValidationChain();
    private readonly commandBus: ScalingCommandBus;

    // Subjects act as internal multicast streams after Kafka ingestion
    private readonly infraSubject  = new Subject<InfraMetrics>();
    private readonly socialSubject = new Subject<SocialPulse>();

    constructor(
        private readonly kafka: Kafka,
        commandBus: ScalingCommandBus,
        config: Partial<AutoScalerConfig> = {}
    ) {
        this.cfg        = Object.freeze({ ...defaultConfig, ...config });
        this.commandBus = commandBus;
    }

    async init(): Promise<void> {
        await this.createKafkaConsumers();
        this.startEvaluationLoop();
    }

    /* --------------------------------------------------------------------------
     * Kafka consumers → push JSON payloads into Rx subjects
     * ------------------------------------------------------------------------*/
    private async createKafkaConsumers(): Promise<void> {
        // Infrastructure metrics topic
        const infraConsumer = this.kafka.consumer({ groupId: 'autoscaler-infra' });
        await infraConsumer.connect();
        await infraConsumer.subscribe({ topic: 'infra.metrics', fromBeginning: false });

        // Social signal topic
        const socialConsumer = this.kafka.consumer({ groupId: 'autoscaler-social' });
        await socialConsumer.connect();
        await socialConsumer.subscribe({ topic: 'social.signals', fromBeginning: false });

        infraConsumer.run({
            eachMessage: async (payload: EachMessagePayload) => {
                try {
                    const msg     = payload.message.value?.toString() || '{}';
                    const metrics = JSON.parse(msg) as InfraMetrics;
                    this.infraSubject.next(metrics);
                } catch (err) {
                    this.log.warn({ err }, 'Failed to parse infra.metrics message.');
                }
            }
        });

        socialConsumer.run({
            eachMessage: async (payload: EachMessagePayload) => {
                try {
                    const msg    = payload.message.value?.toString() || '{}';
                    const signal = JSON.parse(msg) as SocialPulse;
                    this.socialSubject.next(signal);
                } catch (err) {
                    this.log.warn({ err }, 'Failed to parse social.signals message.');
                }
            }
        });

        this.log.info('Kafka consumers for infra & social streams started.');
    }

    /* --------------------------------------------------------------------------
     * Evaluation loop – merges streams, applies throttling, issues commands
     * ------------------------------------------------------------------------*/
    private startEvaluationLoop(): void {
        const sources: StreamSources = {
            infra$:  this.infraSubject.asObservable(),
            social$: this.socialSubject.asObservable()
        };

        const combined$ = merge(
            sources.infra$.pipe(map(m => ({ type: 'metrics', payload: m }))),
            sources.social$.pipe(map(s => ({ type: 'social',  payload: s })))
        ).pipe(
            throttleTime(this.cfg.evaluationWindowMs)
        );

        let latestMetrics: InfraMetrics | null = null;
        let latestSocial: SocialPulse | null   = null;

        combined$.subscribe({
            next: evt => {
                if (evt.type === 'metrics') latestMetrics = evt.payload as InfraMetrics;
                else                         latestSocial  = evt.payload as SocialPulse;

                if (latestMetrics && latestSocial) {
                    this.handleEvaluation(latestMetrics, latestSocial);
                    // reset after evaluation window
                    latestMetrics = latestSocial = null;
                }
            },
            error: err => this.log.error({ err }, 'Evaluation stream error.')
        });
    }

    /* --------------------------------------------------------------------------
     * Decision & command dispatch
     * ------------------------------------------------------------------------*/
    private handleEvaluation(metrics: InfraMetrics, social: SocialPulse): void {
        const ctx: ScalingContext = { metrics, social, config: this.cfg };
        const strategy            = this.strategyResolver.resolve(ctx);

        this.log.debug({
            strategy: strategy.name,
            cpu:      metrics.cpuUsage,
            rps:      metrics.reqRate,
            social:   { likes: social.likes, comments: social.comments, shares: social.shares }
        }, 'Evaluating scaling decision.');

        const cmd = strategy.decide(ctx);
        if (!cmd) {
            return this.log.info('No scaling action required.');
        }

        // Attach config for downstream validation
        cmd.meta = { ...cmd.meta, config: this.cfg, generatedAt: Date.now() };

        try {
            this.validationChain.validate(cmd);
            this.commandBus.dispatch(cmd);

            this.log.info({
                command: cmd.type,
                from:    cmd.from,
                to:      cmd.to,
                reason:  cmd.reason
            }, 'Scaling command dispatched.');
        } catch (err) {
            this.log.warn({ err, cmd }, 'Scaling command validation failed – command rejected.');
        }
    }
}

/* -------------------------------------------------------------------------------------------------
 * Factory helper – integrates with DI frameworks or manual bootstrapping
 * -----------------------------------------------------------------------------------------------*/
export async function createAndStartAutoScaler(): Promise<SocialAwareAutoScaler> {
    const kafka       = new Kafka({ brokers: Config.get<string[]>('kafka.brokers') });
    const commandBus  = ScalingCommandBus.create({ kafka });

    const scaler = new SocialAwareAutoScaler(
        kafka,
        commandBus,
        Config.get<Partial<AutoScalerConfig>>('autoscaler') || {}
    );

    await scaler.init();
    return scaler;
}
```