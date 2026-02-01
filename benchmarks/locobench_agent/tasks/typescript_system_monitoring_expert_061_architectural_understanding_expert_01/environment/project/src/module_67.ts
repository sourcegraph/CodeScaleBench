```typescript
/***************************************************************************************************
 *  File:        src/module_67.ts
 *  Project:     PulseSphere SocialOps – System Monitoring
 *  Description: Social-signal–aware horizontal auto-scaling strategy, implemented using the
 *               Strategy and Chain-of-Responsibility patterns.  The strategy consumes traditional
 *               infrastructure metrics (CPU, memory) and social-interaction metrics (likes, shares,
 *               comments, live-stream viewers) and decides whether a service needs to scale out /
 *               in.  Recommendations are forwarded to the next handler in the chain (e.g. a
 *               Kubernetes-specific scaler) via an in-process EventEmitter.
 *
 *  NOTE:        This file is self-contained for illustration purposes.  In the full PulseSphere
 *               code-base, most of the auxiliary types (logging, telemetry, etc.) live in shared
 *               packages.
 ***************************************************************************************************/

import { EventEmitter } from 'events';
import { mean, std } from 'mathjs'; // Lightweight, treeshake-friendly subset of MathJS
import { v4 as uuid } from 'uuid';

/* ============================================================================================== */
/* Domain Types                                                                                    */
/* ============================================================================================== */

export interface MetricSample {
    /** Epoch milliseconds. */
    readonly timestamp: number;
    /** Raw value (e.g. CPU usage percentage). */
    readonly value: number;
    /** Additional opaque metadata (host, pod-id, etc.) */
    readonly metadata?: Record<string, unknown>;
}

export interface SocialSignalSample {
    readonly timestamp: number;
    /** Aggregated counts for the sampling period. */
    readonly likes: number;
    readonly comments: number;
    readonly shares: number;
    readonly viewers: number;
}

export interface ScalingRecommendation {
    readonly id: string;                 // Correlatable UUID
    readonly desiredReplicas: number;    // Target replica count
    readonly reason: string;             // Human-readable explanation
    readonly createdAt: number;          // Epoch milliseconds
}

/**
 * Contract for all scaling strategies.
 * Implementations should be stateless and idempotent.
 */
export interface ScalerStrategy {
    evaluate(
        cpu: MetricSample[],
        memory: MetricSample[],
        social: SocialSignalSample[],
        currentReplicas: number,
        minReplicas: number,
        maxReplicas: number
    ): ScalingRecommendation | null;
}

/* ============================================================================================== */
/* Utility Classes                                                                                 */
/* ============================================================================================== */

/**
 * Fixed-capacity ring buffer for high-throughput metric ingestion.
 */
export class RingBuffer<T> {
    private readonly buffer: Array<T | undefined>;
    private writeIdx = 0;
    private size = 0;

    constructor(private readonly capacity: number) {
        if (capacity <= 0 || !Number.isFinite(capacity)) {
            throw new Error(`RingBuffer capacity must be > 0. Got: ${capacity}`);
        }
        this.buffer = new Array<T | undefined>(capacity);
    }

    push(value: T): void {
        this.buffer[this.writeIdx] = value;
        this.writeIdx = (this.writeIdx + 1) % this.capacity;
        this.size = Math.min(this.size + 1, this.capacity);
    }

    toArray(): T[] {
        if (this.size < this.capacity) {
            return this.buffer.slice(0, this.size) as T[];
        }
        // Return in chronological order
        return [...this.buffer.slice(this.writeIdx), ...this.buffer.slice(0, this.writeIdx)] as T[];
    }

    clear(): void {
        this.writeIdx = 0;
        this.size = 0;
        this.buffer.fill(undefined);
    }
}

/* ============================================================================================== */
/* Strategy Implementation                                                                          */
/* ============================================================================================== */

/**
 * Social-signal–aware strategy.
 *
 * Heuristics:
 * 1. If mean CPU > 75 % or memory > 80 % → scale out by 1 replica.
 * 2. If social engagement Z-score > 1.5 (rapid spike) → scale out by 2 replicas.
 * 3. If mean CPU < 35 % AND social engagement Z-score < ‑1 → scale in by 1 replica.
 * All decisions respect min/max replica constraints.
 */
export class SocialAwareScaleStrategy implements ScalerStrategy {
    private static readonly CPU_SCALE_OUT_THRESHOLD = 0.75;
    private static readonly CPU_SCALE_IN_THRESHOLD = 0.35;

    private static readonly MEM_SCALE_OUT_THRESHOLD = 0.8;

    private static readonly SOCIAL_ZSCORE_SPIKE = 1.5;
    private static readonly SOCIAL_ZSCORE_DWINDLE = -1.0;

    evaluate(
        cpu: MetricSample[],
        memory: MetricSample[],
        social: SocialSignalSample[],
        currentReplicas: number,
        minReplicas: number,
        maxReplicas: number
    ): ScalingRecommendation | null {
        if (!cpu.length || !memory.length || !social.length) {
            // Not enough data
            return null;
        }

        const cpuValues = cpu.map(s => s.value / 100); // convert to 0-1
        const memValues = memory.map(s => s.value / 100);
        const socialEngagement = social.map(s => s.likes + s.comments + s.shares + s.viewers);

        const meanCpu = mean(cpuValues);
        const meanMem = mean(memValues);

        const zScoreSocial = this.calculateZScore(
            socialEngagement[socialEngagement.length - 1],
            socialEngagement
        );

        let desiredReplicas = currentReplicas;
        let reason = '';

        // Rule 1 ─ Infra pressure
        if (meanCpu > SocialAwareScaleStrategy.CPU_SCALE_OUT_THRESHOLD || meanMem > SocialAwareScaleStrategy.MEM_SCALE_OUT_THRESHOLD) {
            desiredReplicas += 1;
            reason = `High infra usage (CPU=${(meanCpu * 100).toFixed(1)} %, MEM=${(meanMem * 100).toFixed(1)} %)`;
        }
        // Rule 2 ─ Viral spike
        else if (zScoreSocial > SocialAwareScaleStrategy.SOCIAL_ZSCORE_SPIKE) {
            desiredReplicas += 2;
            reason = `Social spike detected (Z=${zScoreSocial.toFixed(2)})`;
        }
        // Rule 3 ─ Under-utilization
        else if (
            meanCpu < SocialAwareScaleStrategy.CPU_SCALE_IN_THRESHOLD &&
            zScoreSocial < SocialAwareScaleStrategy.SOCIAL_ZSCORE_DWINDLE
        ) {
            desiredReplicas -= 1;
            reason = `Load subsided (CPU=${(meanCpu * 100).toFixed(1)} %, social Z=${zScoreSocial.toFixed(2)})`;
        }

        // Clamp + early exit
        desiredReplicas = Math.max(minReplicas, Math.min(maxReplicas, desiredReplicas));

        if (desiredReplicas === currentReplicas) {
            return null;
        }

        return {
            id: uuid(),
            desiredReplicas,
            reason,
            createdAt: Date.now()
        };
    }

    /**
     * Compute Z-score of current value inside the population array.
     */
    private calculateZScore(current: number, population: number[]): number {
        if (population.length < 2) {
            return 0;
        }
        const μ = mean(population);
        const σ = std(population);
        return σ === 0 ? 0 : (current - μ) / σ;
    }
}

/* ============================================================================================== */
/* Chain of Responsibility: Recommendation Dispatcher                                               */
/* ============================================================================================== */

/**
 * Events emitted by ScalerDispatcher
 */
export enum ScalerEvents {
    RECOMMENDATION = 'recommendation'
}

type RecommendationListener = (rec: ScalingRecommendation) => void;

/**
 * Central dispatcher which receives recommendations from one or more strategies and emits them
 * downstream (e.g. toward a Kubernetes scaler service, Slack bot, etc.).
 */
export class ScalerDispatcher extends EventEmitter {
    private readonly strategies: ScalerStrategy[];

    constructor(strategies: ScalerStrategy[]) {
        super();
        if (!strategies.length) {
            throw new Error('ScalerDispatcher requires at least one strategy.');
        }
        this.strategies = strategies;
    }

    /**
     * Feed latest telemetry into the dispatcher.  The dispatcher runs each strategy in order until
     * one emits a non-null recommendation.  This allows layering of policies.
     */
    public handleTick(
        cpu: MetricSample[],
        memory: MetricSample[],
        social: SocialSignalSample[],
        replicaInfo: { current: number; min: number; max: number }
    ): void {
        for (const strategy of this.strategies) {
            try {
                const rec = strategy.evaluate(
                    cpu,
                    memory,
                    social,
                    replicaInfo.current,
                    replicaInfo.min,
                    replicaInfo.max
                );
                if (rec) {
                    this.emit(ScalerEvents.RECOMMENDATION, rec);
                    break; // Short-circuit the chain
                }
            } catch (err) {
                /* eslint-disable no-console */
                console.error(
                    `[ScalerDispatcher] Strategy ${strategy.constructor.name} threw:`,
                    (err as Error).message
                );
                /* eslint-enable no-console */
                // Continue with next strategy
            }
        }
    }

    public onRecommendation(listener: RecommendationListener): this {
        return this.on(ScalerEvents.RECOMMENDATION, listener);
    }
}

/* ============================================================================================== */
/* Facade for Module Consumers                                                                     */
/* ============================================================================================== */

/**
 * Bundle that keeps buffers of metrics and exposes a simple ingestion API, hiding ring-buffer /
 * sampling intricacies from call-sites.
 */
export class TelemetryWindow {
    private readonly cpuBuf = new RingBuffer<MetricSample>(240);     // ≈4 min @ 1 Hz
    private readonly memBuf = new RingBuffer<MetricSample>(240);
    private readonly socialBuf = new RingBuffer<SocialSignalSample>(120); // ≈2 min @ 1 Hz

    pushCpuSample(value: number): void {
        this.cpuBuf.push({
            timestamp: Date.now(),
            value
        });
    }

    pushMemSample(value: number): void {
        this.memBuf.push({
            timestamp: Date.now(),
            value
        });
    }

    pushSocialSample(sample: Omit<SocialSignalSample, 'timestamp'>): void {
        this.socialBuf.push({
            timestamp: Date.now(),
            ...sample
        });
    }

    snapshot(): {
        cpu: MetricSample[];
        memory: MetricSample[];
        social: SocialSignalSample[];
    } {
        return {
            cpu: this.cpuBuf.toArray(),
            memory: this.memBuf.toArray(),
            social: this.socialBuf.toArray()
        };
    }

    clear(): void {
        this.cpuBuf.clear();
        this.memBuf.clear();
        this.socialBuf.clear();
    }
}

/* ============================================================================================== */
/* Example Usage (to be removed / replaced in production tests)                                    */
/* ============================================================================================== */

if (process.env.NODE_ENV !== 'production') {
    // Quick and dirty demo harness
    const telemetry = new TelemetryWindow();
    const dispatcher = new ScalerDispatcher([new SocialAwareScaleStrategy()]);

    dispatcher.onRecommendation(rec =>
        console.log(
            `[DEMO] Scaling decision: replicas → ${rec.desiredReplicas}. Reason: ${rec.reason}`
        )
    );

    // Simulate incoming data
    setInterval(() => {
        telemetry.pushCpuSample(30 + Math.random() * 40); // CPU 30-70%
        telemetry.pushMemSample(50 + Math.random() * 20); // MEM 50-70%
        telemetry.pushSocialSample({
            likes: Math.floor(Math.random() * 500),
            comments: Math.floor(Math.random() * 120),
            shares: Math.floor(Math.random() * 80),
            viewers: Math.floor(Math.random() * 1000)
        });

        const { cpu, memory, social } = telemetry.snapshot();
        dispatcher.handleTick(cpu, memory, social, {
            current: 4,
            min: 2,
            max: 10
        });
    }, 1000);
}
```