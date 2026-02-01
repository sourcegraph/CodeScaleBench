```typescript
/* ******************************************************************************************
 *  PulseSphere SocialOps – Socially-Aware Metric Enrichment Pipeline
 *  -----------------------------------------------------------------------------------------
 *  File:        src/module_13.ts
 *  Description: Provides a reusable, production-ready operator that enriches low-level
 *               infrastructure metrics with near-real-time social interaction signals
 *               (likes, comments, shares, stream spikes, etc.).  The enriched telemetry
 *               allows SRE teams to correlate infrastructure anomalies with community
 *               sentiment and viral bursts.
 *
 *  High-Level Features
 *  -----------------------------------------------------------------------------------------
 *  • Built on RxJS streams for push-based, back-pressure-aware processing.
 *  • Implements a Strategy + Observer hybrid to allow plug-and-play correlation strategies.
 *  • Fault-tolerant: protects the pipeline from malformed messages & downstream failures.
 *  • Extensible: callers can provide their own correlation heuristics via DI.
 *
 *  NOTE: All external dependencies (@types et al.) are intentionally kept minimal to avoid
 *        leaking private project APIs in this public snippet. Replace stubs with concrete
 *        implementations where necessary (e.g., Kafka/NATS adapters).
 ******************************************************************************************* */

import { Observable, Subject, Subscription, merge, of, timer } from 'rxjs';
import {
    catchError,
    filter,
    map,
    bufferTime,
    withLatestFrom,
    tap,
    shareReplay,
} from 'rxjs/operators';
import * as lodash from 'lodash';
import debugFactory from 'debug';

const log = debugFactory('pulsesphere:module_13');

/* ============================================================================
 * Types & DTOs
 * ========================================================================== */

/**
 * Enum of the supported infrastructure metric categories
 */
export enum MetricType {
    CPU = 'cpu',
    MEMORY = 'memory',
    DISK = 'disk',
    NETWORK = 'network',
    REDIS = 'redis',
    POSTGRES = 'postgres',
    KAFKA = 'kafka',
}

/**
 * Raw infrastructure metric emitted by lower-level collectors
 */
export interface SystemMetric {
    readonly id: string;               // uuid v4
    readonly ts: number;               // epoch milliseconds
    readonly type: MetricType;
    readonly value: number;            // e.g. cpu utilisation %
    readonly tags?: Record<string, string | number>;
}

/**
 * Social interaction that may influence infra utilisation
 */
export interface SocialInteraction {
    readonly id: string;               // uuid v4
    readonly ts: number;               // epoch milliseconds
    readonly userId: string;
    readonly verb: 'like' | 'comment' | 'share' | 'livestream' | 'follow';
    readonly magnitude?: number;       // e.g. livestream viewer count
    readonly contentId?: string;
}

/**
 * Metric enriched with social context
 */
export interface EnrichedMetric extends SystemMetric {
    // Rolling sum of interactions within correlation window
    socialSignalStrength: number;

    // Optional verbose details for forensic dashboards
    socialBreakdown?: Record<string, number>;
}

/**
 * Strategy used to correlate a batch of SocialInteraction with a single SystemMetric
 */
export interface CorrelationStrategy {
    /**
     * Compute an "impact score" from the provided interactions.  
     * Return 0 if no meaningful correlation exists.
     */
    deriveSignalStrength(
        metric: SystemMetric,
        relatedInteractions: ReadonlyArray<SocialInteraction>,
    ): { score: number; breakdown?: Record<string, number> };
}

/* ============================================================================
 * Default Correlation Strategy
 * ========================================================================== */

/**
 * Baseline correlation:  
 *  – Weights interactions using simple coefficients (configurable).  
 *  – Considers only interactions that occurred within ±windowMs/2 of the metric timestamp.
 */
export class HeuristicCorrelationStrategy implements CorrelationStrategy {
    private readonly coeff: Record<SocialInteraction['verb'], number>;

    constructor(coeffOverrides?: Partial<Record<SocialInteraction['verb'], number>>) {
        this.coeff = Object.freeze({
            like: 1,
            share: 3,
            comment: 2,
            livestream: 5,
            follow: 1,
            ...coeffOverrides,
        });
    }

    deriveSignalStrength(
        _metric: SystemMetric,
        related: ReadonlyArray<SocialInteraction>,
    ) {
        const breakdown: Record<string, number> = {};
        for (const interaction of related) {
            const weight = this.coeff[interaction.verb] ?? 0;
            breakdown[interaction.verb] = (breakdown[interaction.verb] || 0) + weight;
        }
        const score = lodash.sum(Object.values(breakdown));
        return { score, breakdown };
    }
}

/* ============================================================================
 * Config DTO
 * ========================================================================== */

export interface EnricherConfig {
    /**
     * Correlation window (ms).  
     * Social interactions whose timestamps fall inside [metric.ts - windowMs/2, metric.ts + windowMs/2]
     * will be considered for correlation.
     */
    windowMs: number;

    /**
     * Maximum size of social interaction buffer retained in memory.  
     * Acts as a simple circuit breaker to protect against unbounded memory usage.
     */
    socialBufferSize: number;

    /**
     * Strategy used to merge social + metric data.
     */
    correlationStrategy?: CorrelationStrategy;
}

/* ============================================================================
 * SocialContextEnricher
 * ========================================================================== */

/**
 * Combines infrastructure metrics with concurrent social signals.
 *
 * Example usage:
 *
 *    const enricher = new SocialContextEnricher(metric$, social$, { windowMs: 30_000, socialBufferSize: 20_000 });
 *    const enriched$ = enricher.start();
 *    enriched$.subscribe(console.log);
 */
export class SocialContextEnricher {
    private readonly metric$: Observable<SystemMetric>;
    private readonly social$: Observable<SocialInteraction>;
    private readonly cfg: Required<EnricherConfig>;
    private readonly subs = new Subscription();
    private readonly socialBuffer: SocialInteraction[] = [];

    constructor(
        metric$: Observable<SystemMetric>,
        social$: Observable<SocialInteraction>,
        cfg: EnricherConfig,
    ) {
        this.metric$ = metric$;
        this.social$ = social$;
        // Fill in defaults
        this.cfg = {
            windowMs: cfg.windowMs ?? 30_000,
            socialBufferSize: cfg.socialBufferSize ?? 25_000,
            correlationStrategy: cfg.correlationStrategy ?? new HeuristicCorrelationStrategy(),
        };
    }

    /**
     * Starts the enrichment pipeline and returns the enriched stream.
     */
    public start(): Observable<EnrichedMetric> {
        log('Starting SocialContextEnricher with config: %O', this.cfg);

        // 1. Maintain a rolling buffer of social interactions
        const bufferedSocial$ = new Subject<SocialInteraction>();

        // Subscription: feed incoming social events into in-memory buffer
        this.subs.add(
            this.social$
                .pipe(
                    tap((evt) => {
                        this.socialBuffer.push(evt);
                        // Evict old items if buffer is too large
                        if (this.socialBuffer.length > this.cfg.socialBufferSize) {
                            this.socialBuffer.splice(0, this.socialBuffer.length / 2);
                        }
                    }),
                    catchError((err, caught) => {
                        log('Error in social stream: %O', err);
                        return caught; // resume
                    }),
                )
                .subscribe(bufferedSocial$),
        );

        // 2. For each metric, derive correlated social impact
        const enriched$ = this.metric$.pipe(
            map((metric) => this.enrichMetric(metric)),
            catchError((err, caught) => {
                log('Error enriching metric: %O', err);
                return caught;
            }),
            shareReplay({ bufferSize: 0, refCount: true }),
        );

        return enriched$;
    }

    /**
     * Stops background subscriptions and frees resources. Safe to call multiple times.
     */
    public stop(): void {
        this.subs.unsubscribe();
        this.socialBuffer.length = 0;
        log('SocialContextEnricher stopped and buffer cleared.');
    }

    /* ---------------------------------------------------------------------- */
    /*                                Helpers                                 */
    /* ---------------------------------------------------------------------- */

    private enrichMetric(metric: SystemMetric): EnrichedMetric {
        const halfWindow = this.cfg.windowMs / 2;
        const minTs = metric.ts - halfWindow;
        const maxTs = metric.ts + halfWindow;

        // Filter interactions within window bounds
        const related = this.socialBuffer.filter(
            (s) => s.ts >= minTs && s.ts <= maxTs,
        );

        const { score, breakdown } = this.cfg.correlationStrategy.deriveSignalStrength(
            metric,
            related,
        );

        return {
            ...metric,
            socialSignalStrength: score,
            socialBreakdown: Object.keys(breakdown).length ? breakdown : undefined,
        };
    }
}

/* ============================================================================
 * Convenience Factory
 * ========================================================================== */

/**
 * Create an enriched metric pipeline using default settings.  
 * Helpful for quick prototyping in tests or REPLs.
 */
export function createSocialContextPipeline(
    metrics$: Observable<SystemMetric>,
    socials$: Observable<SocialInteraction>,
    partialCfg: Partial<EnricherConfig> = {},
): Observable<EnrichedMetric> {
    const enricher = new SocialContextEnricher(metrics$, socials$, {
        windowMs: 60_000,
        socialBufferSize: 50_000,
        ...partialCfg,
    });

    // Auto-stop when the consumer finishes
    return new Observable<EnrichedMetric>((subscriber) => {
        const sub = enricher.start().subscribe(subscriber);
        return () => {
            sub.unsubscribe();
            enricher.stop();
        };
    });
}

/* ============================================================================
 * Example (Mock) – remove/replace with real sources in production
 * ========================================================================== */
/*
import { interval } from 'rxjs';
import { v4 as uuid } from 'uuid';
import { map } from 'rxjs/operators';

// Mock metric stream (every second)
const metric$ = interval(1000).pipe(
    map((count) => ({
        id: uuid(),
        ts: Date.now(),
        type: MetricType.CPU,
        value: Math.random() * 100,
    })),
);

// Mock social stream (random cadence)
const social$ = interval(700).pipe(
    map(() => ({
        id: uuid(),
        ts: Date.now(),
        userId: `u-${Math.floor(Math.random() * 1000)}`,
        verb: lodash.sample(['like', 'share', 'comment', 'livestream', 'follow']) as any,
        magnitude: Math.floor(Math.random() * 10),
    })),
);

createSocialContextPipeline(metric$, social$).subscribe((e) =>
    log('[EXAMPLE OUTPUT] %O', e),
);
*/

/* ******************************************************************************************
 * End of file: src/module_13.ts
 ******************************************************************************************* */
```