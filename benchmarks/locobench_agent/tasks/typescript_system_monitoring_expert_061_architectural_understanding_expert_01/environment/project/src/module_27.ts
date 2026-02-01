```typescript
/**************************************************************************************************
 *  File:        src/module_27.ts
 *  Project:     PulseSphere SocialOps (system_monitoring)
 *  Description: Social-Aware Auto-Scaler service. Consumes infrastructure metrics and social
 *               interaction signals in real-time, correlates them, and issues scale commands
 *               via the Command Bus. Uses Strategy pattern to allow hot-swapping of
 *               scaling algorithms and Observer pattern (RxJS) for streaming telemetry.
 *
 *  NOTE:        This file purposefully focuses on domain logic and omits framework boilerplate
 *               that lives elsewhere in the codebase (dependency injection, configuration, etc.).
 **************************************************************************************************/

import { Observable, Subscription, merge, timeout, map, filter, bufferTime, tap } from 'rxjs';
import { Logger } from '@pulsesphere/shared/logging';
import { CommandBus } from '@pulsesphere/shared/command-bus';
import { ScaleClusterCommand } from '@pulsesphere/contracts/commands/scale-cluster.command';
import { MetricEvent, SocialEvent, InfraMetricEvent } from '@pulsesphere/contracts/events';
import { CircuitBreaker } from '@pulsesphere/shared/circuit-breaker';

/* -------------------------------------------------------------------------------------------------
 * Domain DTOs
 * -----------------------------------------------------------------------------------------------*/

/**
 * Envelope packing correlated telemetry.
 */
interface CorrelatedSnapshot {
    timestamp: number;              // Epoch millis
    rps: number;                    // Requests per second
    avgLatencyMs: number;           // Mean latency across cluster
    errorRate: number;              // % of non-2xx within window
    activeUsers: number;            // Concurrency (social)
    interactionsPerSecond: number;  // Likes + comments + shares per second
}

/* -------------------------------------------------------------------------------------------------
 * Scaling Strategy ‑ pattern
 * -----------------------------------------------------------------------------------------------*/

/**
 * Computes recommended replica count given correlated metrics and current cluster size.
 */
export interface ScalingStrategy {
    name: string;
    decideTargetReplicas(
        snapshot: CorrelatedSnapshot,
        currentReplicas: number,
        minReplicas: number,
        maxReplicas: number
    ): number;
}

/**
 * A conservative strategy: scale up only when latency AND RPS exceed thresholds.
 */
export class ConservativeScalingStrategy implements ScalingStrategy {
    public readonly name = 'ConservativeScalingStrategy';

    public decideTargetReplicas(
        snapshot: CorrelatedSnapshot,
        currentReplicas: number,
        minReplicas: number,
        maxReplicas: number
    ): number {
        const { rps, avgLatencyMs, interactionsPerSecond } = snapshot;

        // Heuristics
        const latencyThreshold = 250; // ms
        const rpsThreshold      = 1000;
        const socialThreshold   = 500; // interactions / second

        if (avgLatencyMs > latencyThreshold && rps > rpsThreshold) {
            const scaleFactor = 1 + Math.min(interactionsPerSecond / 1000, 2); // up to 3x
            return Math.min(maxReplicas, Math.ceil(currentReplicas * scaleFactor));
        }

        // Consider scale-down if underutilized
        if (avgLatencyMs < latencyThreshold * 0.6 && rps < rpsThreshold * 0.5) {
            return Math.max(minReplicas, Math.floor(currentReplicas * 0.8));
        }

        return currentReplicas; // no change
    }
}

/**
 * An aggressive strategy biased by viral social activity.
 */
export class AggressiveScalingStrategy implements ScalingStrategy {
    public readonly name = 'AggressiveScalingStrategy';

    public decideTargetReplicas(
        snapshot: CorrelatedSnapshot,
        currentReplicas: number,
        minReplicas: number,
        maxReplicas: number
    ): number {
        const { rps, interactionsPerSecond, avgLatencyMs } = snapshot;

        // Weighted score factoring more social signals
        const demandScore =
            rps * 0.4 +
            interactionsPerSecond * 1.2 +
            (avgLatencyMs > 300 ? 1500 : 0);

        const desired = Math.ceil(demandScore / 2500);     // empirically derived divisor
        const bounded = Math.min(maxReplicas, Math.max(minReplicas, desired));

        // Avoid thrashing: limit step size
        if (bounded > currentReplicas) {
            return Math.min(bounded, currentReplicas + 5);
        } else if (bounded < currentReplicas) {
            return Math.max(bounded, currentReplicas - 2);
        }
        return currentReplicas;
    }
}

/* -------------------------------------------------------------------------------------------------
 * Auto-Scaler Service
 * -----------------------------------------------------------------------------------------------*/

export interface AutoScalerOptions {
    minReplicas: number;
    maxReplicas: number;
    evaluationWindowMs: number;       // Buffer window to aggregate telemetry
    scalingCooldownMs: number;        // Guard period between scaling actions
}

/**
 * Consumes MetricEvent & SocialEvent streams, correlates and performs scale operations.
 */
export class SocialAwareAutoScaler {
    private readonly log = new Logger({ service: 'SocialAwareAutoScaler' });
    private readonly subs: Subscription[] = [];
    private lastScaleTimestamp = 0;

    private strategy: ScalingStrategy;

    private readonly breaker = new CircuitBreaker({
        failureThreshold: 5,
        successThreshold: 2,
        timeoutMs: 10000,
    });

    constructor(
        private readonly infraMetrics$:   Observable<InfraMetricEvent>,
        private readonly socialMetrics$:  Observable<SocialEvent>,
        private readonly commandBus:      CommandBus,
        private readonly options:         AutoScalerOptions,
        strategy?:                        ScalingStrategy,
    ) {
        // default or injected strategy
        this.strategy = strategy ?? new ConservativeScalingStrategy();
    }

    /**
     * Replace scaling strategy at runtime (hot-swap).
     */
    public swapStrategy(newStrategy: ScalingStrategy): void {
        this.log.info(`Swapping scaling strategy: ${this.strategy.name} -> ${newStrategy.name}`);
        this.strategy = newStrategy;
    }

    /**
     * Start listening to telemetry streams.
     */
    public start(): void {
        if (this.subs.length) {
            throw new Error('Auto-Scaler already started');
        }

        const { evaluationWindowMs } = this.options;

        // Merge streams while enriching missing fields
        const merged$ = merge<MetricEvent>(
            this.infraMetrics$.pipe(
                map((event) => ({
                    ...event,
                    interactionsPerSecond: 0,
                    activeUsers:           0,
                })),
            ),
            this.socialMetrics$.pipe(
                map((event) => ({
                    timestamp:            event.timestamp,
                    rps:                  0,
                    avgLatencyMs:         0,
                    errorRate:            0,
                    activeUsers:          event.activeUsers,
                    interactionsPerSecond:event.interactionsPerSecond,
                })),
            ),
        );

        // Aggregation buffer
        const sub = merged$
            .pipe(
                bufferTime(evaluationWindowMs, undefined, undefined, { shouldReuseNotification: true }),
                filter((buffer) => buffer.length > 0),
                map((buffer) => this.correlate(buffer)),
                tap((snapshot) => this.log.debug('Correlated snapshot', snapshot)),
            )
            .subscribe({
                next:  (snapshot) => this.maybeScale(snapshot),
                error: (err)      => this.log.error('Correlation stream failed', err),
            });

        this.subs.push(sub);
        this.log.info('SocialAwareAutoScaler started');
    }

    /**
     * Graceful shutdown.
     */
    public stop(): void {
        this.subs.forEach((s) => s.unsubscribe());
        this.subs.length = 0;
        this.log.info('SocialAwareAutoScaler stopped');
    }

    /* -------------------------------------------------------------------------------------------
     * Internal helpers
     * -----------------------------------------------------------------------------------------*/

    /**
     * Merge infra & social events into a single snapshot aggregating the window.
     */
    private correlate(events: MetricEvent[]): CorrelatedSnapshot {
        let rps = 0,
            latencyTotal = 0,
            latencySamples = 0,
            errors = 0,
            activeUsers = 0,
            interactions = 0;

        events.forEach((e) => {
            rps += e.rps ?? 0;
            if (e.avgLatencyMs) {
                latencyTotal += e.avgLatencyMs;
                latencySamples++;
            }
            errors += e.errorRate ? e.errorRate * (e.rps ?? 1) : 0;
            activeUsers = Math.max(activeUsers, e.activeUsers ?? 0);
            interactions += e.interactionsPerSecond ?? 0;
        });

        const snapshot: CorrelatedSnapshot = {
            timestamp:             Date.now(),
            rps:                   rps / events.length,
            avgLatencyMs:          latencySamples ? latencyTotal / latencySamples : 0,
            errorRate:             events.length ? errors / (events.length * (rps || 1)) : 0,
            activeUsers,
            interactionsPerSecond: interactions / events.length,
        };
        return snapshot;
    }

    /**
     * Evaluate snapshot and issue ScaleClusterCommand if required.
     */
    private async maybeScale(snapshot: CorrelatedSnapshot): Promise<void> {
        // Circuit breaker to protect the downstream orchestrator
        if (!this.breaker.canExecute()) {
            this.log.warn('Circuit breaker open; skipping scaling decision');
            return;
        }

        try {
            const clusterState = await this.fetchClusterState().pipe(timeout(5000)).toPromise();
            const { minReplicas, maxReplicas, scalingCooldownMs } = this.options;
            const targetReplicas = this.strategy.decideTargetReplicas(
                snapshot,
                clusterState.currentReplicas,
                minReplicas,
                maxReplicas,
            );

            const now = Date.now();
            const cooldownElapsed = now - this.lastScaleTimestamp >= scalingCooldownMs;

            if (targetReplicas !== clusterState.currentReplicas && cooldownElapsed) {
                this.log.info(
                    `Scaling decision: ${clusterState.currentReplicas} -> ${targetReplicas} replicas (strategy=${this.strategy.name})`,
                );

                const cmd = new ScaleClusterCommand({
                    service:          'social-api',
                    targetReplicas,
                    reason:           `Auto-scale via ${this.strategy.name}`,
                    correlatedMetric: snapshot,
                });

                await this.commandBus.execute(cmd);
                this.lastScaleTimestamp = now;
                this.breaker.success();
            }
        } catch (err) {
            this.breaker.failure();
            this.log.error('Scaling evaluation failed', err);
        }
    }

    /**
     * Retrieve current cluster status (stubbed to Rx for async composability).
     * In production, this would query the orchestrator, e.g., Kubernetes API.
     */
    private fetchClusterState(): Observable<{ currentReplicas: number }> {
        return new Observable((observer) => {
            // TODO: Replace with real implementation (k8s client/service-mesh discovery)
            setTimeout(() => {
                observer.next({ currentReplicas: 12 });
                observer.complete();
            }, 50);
        });
    }
}

/* -------------------------------------------------------------------------------------------------
 * Factory helper (typically wired by IoC container)
 * -----------------------------------------------------------------------------------------------*/

/**
 * Instantiates auto-scaler with streams pulled from the system’s event bus.
 */
export function createSocialAwareAutoScaler(
    infraMetrics$:  Observable<InfraMetricEvent>,
    socialMetrics$: Observable<SocialEvent>,
    commandBus:     CommandBus,
): SocialAwareAutoScaler {
    const opts: AutoScalerOptions = {
        minReplicas:        4,
        maxReplicas:        120,
        evaluationWindowMs: 5_000,
        scalingCooldownMs:  60_000,
    };

    const scaler = new SocialAwareAutoScaler(
        infraMetrics$,
        socialMetrics$,
        commandBus,
        opts,
        new ConservativeScalingStrategy(),
    );

    return scaler;
}
```