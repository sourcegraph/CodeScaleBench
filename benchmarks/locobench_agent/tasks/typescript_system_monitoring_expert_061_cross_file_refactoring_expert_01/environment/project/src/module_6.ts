```typescript
/**************************************************************************************************
 *  PulseSphere SocialOps — System Monitoring
 *  -----------------------------------------------------------------------------------------------
 *  File:          src/module_6.ts
 *  Responsibility: “Social-Aware Auto-Scaler” module.
 *
 *  Description:
 *      Implements Strategy + Chain-of-Responsibility patterns to decide whether a cluster
 *      should be scaled based on:
 *          • Classic infrastructure metrics (CPU, MEM, RT)
 *          • Real-time social signals   (likes, shares, hashtag velocity, etc.)
 *
 *      A Validator chain cleans & guards inbound telemetry, after which a pluggable Strategy
 *      is selected (based on service configuration) to evaluate the snapshot and emit a
 *      ScalingDecision event onto the platform’s event-bus.
 *
 *  Public API:
 *      ‑ startSocialAwareAutoScaler() : void
 *
 *  -----------------------------------------------------------------------------------------------
 *  NOTE: This file is self-contained and assumes a dependency-injection container will call
 *        startSocialAwareAutoScaler() during service bootstrap.
 **************************************************************************************************/

import { Observable, merge, fromEventPattern, Subject, Subscription } from 'rxjs';
import { debounceTime, map, filter, catchError } from 'rxjs/operators';
import { Kafka, Producer } from 'kafkajs';
import * as os from 'os';
import logger from './utils/logger';                               // project-local Winston wrapper
import { getServiceConfig } from './utils/config';                 // dynamic configuration helper
import { MetricSnapshot, SocialSnapshot, ScalingDecision } from './types/telemetry'; // shared types

/* -------------------------------------------------------------------------------------------------
 * Section 1 — Domain Model
 * ------------------------------------------------------------------------------------------------*/

/**
 * Interface for an object able to validate & possibly mutate raw snapshots.
 */
interface SnapshotValidator {
    setNext(next: SnapshotValidator): SnapshotValidator;
    validate(snapshot: CombinedSnapshot): CombinedSnapshot;
}

/**
 * Union of infrastructure and social telemetry.
 * A single point-in-time snapshot the strategies will consume.
 */
interface CombinedSnapshot {
    infra: MetricSnapshot;
    social: SocialSnapshot;
    receivedAt: number;             // epoch millis when PulseSphere ingested the snapshot
}

/**
 * Contract every Auto-Scaler strategy must obey.
 */
interface AutoScalerStrategy {
    strategyName: string;
    evaluate(snapshot: CombinedSnapshot): ScalingDecision | null;
}

/* -------------------------------------------------------------------------------------------------
 * Section 2 — Chain-of-Responsibility: Snapshot Validators
 * ------------------------------------------------------------------------------------------------*/

/**
 * Base class implementing the chaining mechanics.
 */
abstract class BaseValidator implements SnapshotValidator {
    private next: SnapshotValidator | null = null;

    public setNext(next: SnapshotValidator): SnapshotValidator {
        this.next = next;
        return next;
    }

    public validate(snapshot: CombinedSnapshot): CombinedSnapshot {
        const res = this.handle(snapshot);
        return this.next ? this.next.validate(res) : res;
    }

    protected abstract handle(snapshot: CombinedSnapshot): CombinedSnapshot;
}

/**
 * Rejects obviously stale snapshots.
 */
class StalenessValidator extends BaseValidator {
    protected handle(snapshot: CombinedSnapshot): CombinedSnapshot {
        const ageMs = Date.now() - snapshot.receivedAt;
        const maxStalenessMs = getServiceConfig<number>('scaler.maxStalenessMs', 10_000);

        if (ageMs > maxStalenessMs) {
            throw new Error(`Snapshot staleness ${ageMs}ms exceeds limit ${maxStalenessMs}ms`);
        }
        return snapshot;
    }
}

/**
 * Ensures no NaN/Infinity values creep in.
 */
class NumericSanityValidator extends BaseValidator {
    protected handle(snapshot: CombinedSnapshot): CombinedSnapshot {
        const checkNumeric = (val: number, path: string) => {
            if (!Number.isFinite(val)) {
                throw new Error(`Invalid numeric value at ${path}: ${val}`);
            }
        };

        checkNumeric(snapshot.infra.cpu, 'infra.cpu');
        checkNumeric(snapshot.infra.memory, 'infra.memory');
        checkNumeric(snapshot.infra.responseTime, 'infra.responseTime');
        checkNumeric(snapshot.social.likePerMin, 'social.likePerMin');
        checkNumeric(snapshot.social.sharePerMin, 'social.sharePerMin');
        checkNumeric(snapshot.social.hashtagVelocity, 'social.hashtagVelocity');

        return snapshot;
    }
}

/**
 * Caps outlier social metrics to protect against bogus spikes (e.g. scraping attacks).
 */
class SocialOutlierClampValidator extends BaseValidator {
    protected handle(snapshot: CombinedSnapshot): CombinedSnapshot {
        const clamp = (val: number, max: number) => Math.min(val, max);

        const maxLikeRate = getServiceConfig<number>('scaler.maxLikePerMin', 200_000);
        const maxShareRate = getServiceConfig<number>('scaler.maxSharePerMin', 50_000);
        const maxHashtagVel = getServiceConfig<number>('scaler.maxHashtagVelocity', 5_000);

        snapshot.social.likePerMin = clamp(snapshot.social.likePerMin, maxLikeRate);
        snapshot.social.sharePerMin = clamp(snapshot.social.sharePerMin, maxShareRate);
        snapshot.social.hashtagVelocity = clamp(snapshot.social.hashtagVelocity, maxHashtagVel);

        return snapshot;
    }
}

/* -------------------------------------------------------------------------------------------------
 * Section 3 — Strategy Pattern: Auto-Scaler Strategies
 * ------------------------------------------------------------------------------------------------*/

/**
 * Scales purely on CPU threshold.
 */
class CpuThresholdStrategy implements AutoScalerStrategy {
    public strategyName = 'CPU_THRESHOLD';

    public evaluate(snapshot: CombinedSnapshot): ScalingDecision | null {
        const cpu = snapshot.infra.cpu;
        const cpuScaleUp = getServiceConfig<number>('scaler.cpuScaleUp', 0.80);
        const cpuScaleDown = getServiceConfig<number>('scaler.cpuScaleDown', 0.35);

        if (cpu > cpuScaleUp) {
            return { action: 'SCALE_UP', reason: `CPU ${cpu} > ${cpuScaleUp}` };
        }
        if (cpu < cpuScaleDown) {
            return { action: 'SCALE_DOWN', reason: `CPU ${cpu} < ${cpuScaleDown}` };
        }
        return null; // no-op
    }
}

/**
 * Scales when social engagement surges, regardless of current infra load.
 */
class SocialSpikeStrategy implements AutoScalerStrategy {
    public strategyName = 'SOCIAL_SPIKE';

    public evaluate(snapshot: CombinedSnapshot): ScalingDecision | null {
        const { likePerMin, sharePerMin, hashtagVelocity } = snapshot.social;

        const spikeLike = getServiceConfig<number>('scaler.likeRateSpike', 100_000);
        const spikeShare = getServiceConfig<number>('scaler.shareRateSpike', 25_000);
        const spikeHashtag = getServiceConfig<number>('scaler.hashtagVelSpike', 2_000);

        const spikeDetected =
            likePerMin >= spikeLike ||
            sharePerMin >= spikeShare ||
            hashtagVelocity >= spikeHashtag;

        if (spikeDetected) {
            return {
                action: 'SCALE_UP',
                reason: `Social spike detected — likes=${likePerMin}, shares=${sharePerMin}, hashtagVel=${hashtagVelocity}`,
            };
        }
        return null;
    }
}

/**
 * Hybrid strategy: combines CPU & social signals using weights.
 */
class HybridWeightedStrategy implements AutoScalerStrategy {
    public strategyName = 'HYBRID_WEIGHTED';

    public evaluate(snapshot: CombinedSnapshot): ScalingDecision | null {
        const cpuWeight = getServiceConfig<number>('scaler.hybrid.cpuWeight', 0.6);
        const socialWeight = 1 - cpuWeight;

        const cpuScore = snapshot.infra.cpu; // 0-1
        const socialNorm = normalizeSocial(snapshot.social); // 0-1

        const aggregatedScore = cpuScore * cpuWeight + socialNorm * socialWeight;

        const upBarrier = getServiceConfig<number>('scaler.hybrid.upBarrier', 0.75);
        const downBarrier = getServiceConfig<number>('scaler.hybrid.downBarrier', 0.40);

        if (aggregatedScore >= upBarrier) {
            return {
                action: 'SCALE_UP',
                reason: `Aggregated score ${aggregatedScore.toFixed(2)} >= upBarrier ${upBarrier}`,
            };
        }

        if (aggregatedScore <= downBarrier) {
            return {
                action: 'SCALE_DOWN',
                reason: `Aggregated score ${aggregatedScore.toFixed(2)} <= downBarrier ${downBarrier}`,
            };
        }

        return null;
    }
}

/**
 * Helper: Normalizes social engagement to 0-1 score.
 */
function normalizeSocial(s: SocialSnapshot): number {
    const likeNorm = clamp01(s.likePerMin / getServiceConfig<number>('scaler.norm.likePerMin', 200_000));
    const shareNorm = clamp01(s.sharePerMin / getServiceConfig<number>('scaler.norm.sharePerMin', 50_000));
    const tagNorm = clamp01(s.hashtagVelocity / getServiceConfig<number>('scaler.norm.hashtagVel', 5_000));

    return (likeNorm + shareNorm + tagNorm) / 3; // simple mean
}

function clamp01(v: number): number {
    return Math.max(0, Math.min(1, v));
}

/* -------------------------------------------------------------------------------------------------
 * Section 4 — Strategy Registry & Selector
 * ------------------------------------------------------------------------------------------------*/

const STRATEGY_MAP: Record<string, AutoScalerStrategy> = {
    CPU_THRESHOLD: new CpuThresholdStrategy(),
    SOCIAL_SPIKE: new SocialSpikeStrategy(),
    HYBRID_WEIGHTED: new HybridWeightedStrategy(),
};

function resolveStrategy(): AutoScalerStrategy {
    const conf = getServiceConfig<string>('scaler.strategy', 'HYBRID_WEIGHTED');
    const strategy = STRATEGY_MAP[conf];

    if (!strategy) {
        logger.warn(`Unknown strategy "${conf}", falling back to HYBRID_WEIGHTED`);
        return STRATEGY_MAP['HYBRID_WEIGHTED'];
    }
    return strategy;
}

/* -------------------------------------------------------------------------------------------------
 * Section 5 — Event-Bus (Kafka) Producer
 * ------------------------------------------------------------------------------------------------*/

class DecisionPublisher {
    private kafka = new Kafka({ brokers: getServiceConfig<string[]>('kafka.brokers') });
    private producer: Producer = this.kafka.producer({ allowAutoTopicCreation: true });
    private readonly topic = getServiceConfig<string>('topics.scalingDecisions', 'scaler.decisions');

    async start(): Promise<void> {
        await this.producer.connect();
        logger.info('DecisionPublisher connected to Kafka cluster.');
    }

    async publish(decision: ScalingDecision): Promise<void> {
        await this.producer.send({
            topic: this.topic,
            messages: [{ key: decision.action, value: JSON.stringify(decision) }],
        });
        logger.debug(`Decision published: ${JSON.stringify(decision)}`);
    }

    async stop(): Promise<void> {
        await this.producer.disconnect();
        logger.info('DecisionPublisher disconnected from Kafka.');
    }
}

/* -------------------------------------------------------------------------------------------------
 * Section 6 — Telemetry Stream (mocked w/ OS load & random social data)
 * ------------------------------------------------------------------------------------------------*/

/**
 * In production we ingest data via gRPC stream from the Telemetry Aggregator service.
 * For demo / unit-tests we fabricate an Observable.
 */
function createTelemetryStream(): Observable<CombinedSnapshot> {
    const infra$ = fromEventPattern<MetricSnapshot>(
        handler => {
            const interval = setInterval(() => {
                handler({
                    cpu: os.loadavg()[0] / os.cpus().length,  // naive CPU %
                    memory: (os.totalmem() - os.freemem()) / os.totalmem(),
                    responseTime: Math.random() * 500,         // simulate 0-500ms RT
                });
            }, 1_000);
            return () => clearInterval(interval);
        },
    );

    const social$ = fromEventPattern<SocialSnapshot>(
        handler => {
            const interval = setInterval(() => {
                handler({
                    likePerMin: Math.random() * 150_000,
                    sharePerMin: Math.random() * 40_000,
                    hashtagVelocity: Math.random() * 3_500,
                });
            }, 1_000);
            return () => clearInterval(interval);
        },
    );

    // Pair the latest infra & social every second.
    const combined$ = merge(infra$, social$).pipe(
        debounceTime(300),                            // coalesce bursts
        map(() => latestSnapshot()),                  // capture latest states
        filter(snap => snap !== null),
        map(snap => snap as CombinedSnapshot),
        catchError(err => {
            logger.error(`Telemetry stream error: ${err.message}`);
            return []; // swallow errors, continue stream
        }),
    );

    // Internal state holders
    let lastInfra: MetricSnapshot | null = null;
    let lastSocial: SocialSnapshot | null = null;

    function latestSnapshot(): CombinedSnapshot | null {
        if (!lastInfra || !lastSocial) return null;
        return {
            infra: lastInfra,
            social: lastSocial,
            receivedAt: Date.now(),
        };
    }

    // Side-effects to update internal state
    infra$.subscribe(v => (lastInfra = v));
    social$.subscribe(v => (lastSocial = v));

    return combined$;
}

/* -------------------------------------------------------------------------------------------------
 * Section 7 — Bootstrap Function
 * ------------------------------------------------------------------------------------------------*/

export async function startSocialAwareAutoScaler(): Promise<void> {
    // Assemble validator chain
    const validator = new StalenessValidator();
    validator
        .setNext(new NumericSanityValidator())
        .setNext(new SocialOutlierClampValidator());

    // Instantiate publisher & telemetry stream
    const publisher = new DecisionPublisher();
    await publisher.start();

    const strategy = resolveStrategy();
    logger.info(`Auto-Scaler started with strategy: ${strategy.strategyName}`);

    const subs: Subscription = createTelemetryStream().subscribe({
        next: async (snapshot: CombinedSnapshot) => {
            try {
                const cleanSnap = validator.validate(snapshot);

                const decision = strategy.evaluate(cleanSnap);

                if (decision) {
                    decision.timestamp = Date.now();
                    await publisher.publish(decision);
                }
            } catch (err) {
                logger.warn(`Snapshot dropped: ${err.message}`);
            }
        },
        error: err => {
            logger.error(`Telemetry subscription error: ${err.message}`);
        },
    });

    // Graceful shutdown hook
    const shutdown = async () => {
        logger.info('Graceful shutdown initiated.');
        subs.unsubscribe();
        await publisher.stop();
        process.exit(0);
    };

    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
}

/* -------------------------------------------------------------------------------------------------
 * Section 8 — Auto-start when this file is the entry-point (for local dev)
 * ------------------------------------------------------------------------------------------------*/
if (require.main === module) {
    startSocialAwareAutoScaler().catch(err => {
        logger.error(`Fatal in Auto-Scaler: ${err.stack || err.message}`);
        process.exit(1);
    });
}

/* -------------------------------------------------------------------------------------------------
 * EOF
 * ------------------------------------------------------------------------------------------------*/
```