```typescript
/**************************************************************************************************
 *  File:        src/module_38.ts
 *  Project:     PulseSphere SocialOps — system_monitoring
 *
 *  Description:
 *  -------------
 *  Capacity-orchestration module implementing a Strategy + Chain-of-Responsibility pipeline for
 *  proactive autoscaling.  Each strategy inspects a rolling telemetry window enriched with
 *  real-time social-interaction signals.  When any strategy returns a CapacityDecision, the chain
 *  short-circuits and dispatches the recommendation to interested observers (Command / Observer
 *  patterns) and publishes an event to the platform’s event bus (Kafka).
 *
 *  This file is intentionally self-contained.  External types / classes referenced from other
 *  services are assumed to exist in the wider PulseSphere code-base.
 **************************************************************************************************/

// ────────────────────────────────────────────────────── Imports ─────────────────────────────────
import { Kafka } from 'kafkajs';
import { v4 as uuid } from 'uuid';

import {
    MetricSample,
    SocialSignalSample,
    TelemetryWindow,
} from './interfaces/telemetry';                 // Project-local types
import { Logger } from './utils/logger';           // Centralised Winston-based logger
import { CircuitBreaker } from './utils/circuitBreaker';
import { CapacityCommand } from './commands/capacityCommand'; // Command that executes the scale-action

// ──────────────────────────────────────────────── Type Definitions ──────────────────────────────

/**
 * Decision returned by a CapacityStrategy.
 */
export interface CapacityDecision {
    /** Should we scale up? (false implies potential scale-down or no-op). */
    scaleUp: boolean;
    /** Human-readable explanation. */
    reason: string;
    /** Optional replica recommendation (positive integer). */
    recommendedReplicas?: number;
    /** Strategy that produced this decision. */
    strategy: string;
}

/**
 * Chain-of-Responsibility / Strategy abstraction.
 */
export interface CapacityStrategy {
    evaluate(window: TelemetryWindow): Promise<CapacityDecision | null>;
    setNext(strategy: CapacityStrategy): CapacityStrategy;
}

/**
 * Observer for CapacityDecision events.
 */
export interface CapacityDecisionListener {
    onDecision(decision: CapacityDecision, window: TelemetryWindow): void | Promise<void>;
}

// ───────────────────────────────────────── Base / Utility Classes ───────────────────────────────

/**
 * Provides standard chaining logic & helper utilities.
 */
abstract class AbstractStrategy implements CapacityStrategy {
    protected next?: CapacityStrategy;

    public setNext(strategy: CapacityStrategy): CapacityStrategy {
        this.next = strategy;
        return strategy;
    }

    public async evaluate(window: TelemetryWindow): Promise<CapacityDecision | null> {
        try {
            const decision = await this.doEvaluate(window);
            if (decision) {
                return decision;
            }
        } catch (err) {
            Logger.error(
                `[${this.constructor.name}] evaluation failed: ${(err as Error).message}`,
                { err },
            );
        }
        // Delegate to next strategy in chain, if any.
        return this.next ? this.next.evaluate(window) : null;
    }

    protected abstract doEvaluate(
        window: TelemetryWindow,
    ): Promise<CapacityDecision | null>;
}

// ────────────────────────────────────────── Concrete Strategies ─────────────────────────────────

/**
 * Detects sudden bursts in social activity (likes, shares, comments).
 * If the moving average in the last 2 minutes is X% higher than baseline of 15 minutes,
 * we anticipate a virality event and pre-scale.
 */
class TrendingSpikeStrategy extends AbstractStrategy {
    private readonly spikeThresholdPct: number;
    private readonly minRecommendedReplicas: number;

    constructor(spikeThresholdPct = 300 /* 3× baseline */, minReplicas = 3) {
        super();
        this.spikeThresholdPct = spikeThresholdPct;
        this.minRecommendedReplicas = minReplicas;
    }

    protected async doEvaluate(window: TelemetryWindow): Promise<CapacityDecision | null> {
        const { socialSignals } = window;
        if (socialSignals.length < 10) {
            // Not enough data.
            return null;
        }

        const cutOff = Date.now() - 2 * 60 * 1000; // 2 minutes in ms
        const last2Min = socialSignals.filter((s) => s.timestamp >= cutOff);

        const baselineCutOff = Date.now() - 15 * 60 * 1000; // 15 minutes
        const baseline = socialSignals.filter((s) => s.timestamp >= baselineCutOff);

        const last2MinAvg = averageEngagement(last2Min);
        const baselineAvg = averageEngagement(baseline);

        if (baselineAvg === 0) return null;

        const pctIncrease = (last2MinAvg / baselineAvg) * 100;

        if (pctIncrease >= this.spikeThresholdPct) {
            const recommendedReplicas = Math.max(
                Math.ceil(pctIncrease / 100), // simplistic: 1 replica per 100%
                this.minRecommendedReplicas,
            );
            return {
                scaleUp: true,
                reason: `Social engagement spike of ${pctIncrease.toFixed(
                    1,
                )}% detected`,
                recommendedReplicas,
                strategy: this.constructor.name,
            };
        }
        return null;
    }
}

/**
 * Keeps an eye on CPU / latency SLOs.  If error budget consumption exceeds threshold,
 * request immediate scale-up to meet SLO.
 */
class ErrorBudgetBurnStrategy extends AbstractStrategy {
    private readonly errorBudgetBurnRate: number; // e.g. 1.0 means budget fully burned
    private readonly latencyThresholdMs: number;

    constructor(burnRateThreshold = 0.7, latencyThresholdMs = 250) {
        super();
        this.errorBudgetBurnRate = burnRateThreshold;
        this.latencyThresholdMs = latencyThresholdMs;
    }

    protected async doEvaluate(window: TelemetryWindow): Promise<CapacityDecision | null> {
        const { metricSamples } = window;

        const latencySamples = metricSamples.filter(
            (m) => m.name === 'request_latency_ms',
        );
        const avgLatency =
            latencySamples.reduce((acc, x) => acc + x.value, 0) /
            (latencySamples.length || 1);

        const errorBudgetBurn = computeErrorBudgetBurn(metricSamples);

        if (
            errorBudgetBurn >= this.errorBudgetBurnRate ||
            avgLatency > this.latencyThresholdMs
        ) {
            return {
                scaleUp: true,
                reason: `Error budget burn (${(
                    errorBudgetBurn * 100
                ).toFixed(1)}%) or high latency (${avgLatency.toFixed(0)}ms)`,
                recommendedReplicas: undefined,
                strategy: this.constructor.name,
            };
        }
        return null;
    }
}

// ──────────────────────────────────────── Decision Dispatcher ───────────────────────────────────

/**
 * Orchestrates strategy chain evaluation & observer notification.
 */
export class CapacityManager {
    private readonly headStrategy: CapacityStrategy;
    private readonly listeners = new Set<CapacityDecisionListener>();
    private readonly kafkaProducer: Kafka['producer'];
    private readonly breaker: CircuitBreaker;

    constructor(headStrategy: CapacityStrategy, kafka: Kafka, breaker: CircuitBreaker) {
        this.headStrategy = headStrategy;
        this.kafkaProducer = kafka.producer();
        this.breaker = breaker;
    }

    public addListener(listener: CapacityDecisionListener): void {
        this.listeners.add(listener);
    }

    public removeListener(listener: CapacityDecisionListener): void {
        this.listeners.delete(listener);
    }

    /**
     * Evaluate chain and, if a decision is produced, dispatch to observers + event bus.
     */
    public async processWindow(window: TelemetryWindow): Promise<void> {
        const decision = await this.headStrategy.evaluate(window);
        if (!decision) return;

        Logger.info(`[CapacityManager] Decision produced`, { decision });

        // 1. Notify observers via circuit breaker to avoid cascading failures.
        await this.breaker.exec(() =>
            Promise.all(
                [...this.listeners].map((listener) =>
                    Promise.resolve(listener.onDecision(decision, window)),
                ),
            ),
        );

        // 2. Publish to Kafka (fire-and-forget)
        try {
            await this.kafkaProducer.send({
                topic: 'capacity.decisions',
                messages: [
                    {
                        key: uuid(),
                        value: JSON.stringify({
                            decision,
                            capturedAt: Date.now(),
                        }),
                    },
                ],
            });
        } catch (err) {
            Logger.warn(
                `[CapacityManager] Failed to publish decision to Kafka: ${
                    (err as Error).message
                }`,
            );
        }
    }
}

// ─────────────────────────────────────────── Listener Example ──────────────────────────────────

/**
 * Listener that wraps the scaling logic in a Command object.
 */
export class AutoscalerListener implements CapacityDecisionListener {
    public async onDecision(decision: CapacityDecision): Promise<void> {
        if (!decision.scaleUp) return;

        const command = new CapacityCommand({
            action: 'SCALE_UP',
            replicas: decision.recommendedReplicas,
            reason: decision.reason,
            sourceStrategy: decision.strategy,
        });

        try {
            await command.execute();
            Logger.info(
                `[AutoscalerListener] Executed scaling command from strategy ${decision.strategy}`,
            );
        } catch (err) {
            Logger.error(
                `[AutoscalerListener] Failed to execute scaling command: ${(err as Error).message}`,
                { err },
            );
        }
    }
}

// ─────────────────────────────────────────── Helper Functions ──────────────────────────────────

function averageEngagement(signals: SocialSignalSample[]): number {
    if (signals.length === 0) return 0;
    const sum = signals.reduce(
        (acc, s) => acc + s.likes + s.comments + s.shares + s.reactions,
        0,
    );
    return sum / signals.length;
}

/**
 * Simplistic error-budget burn computation.  In real code, SLO metadata would drive this.
 */
function computeErrorBudgetBurn(metricSamples: MetricSample[]): number {
    const errorSamples = metricSamples.filter((m) => m.name === '5xx_errors');
    const requestSamples = metricSamples.filter((m) => m.name === 'requests_total');

    const errors = errorSamples.reduce((acc, x) => acc + x.value, 0);
    const requests = requestSamples.reduce((acc, x) => acc + x.value, 0);

    if (requests === 0) return 0;

    // Assume 0.1% allowable error rate. Burn rate >1 means error budget fully consumed.
    const errorRate = errors / requests;
    return errorRate / 0.001;
}

// ─────────────────────────────────────────── Module Bootstrapping ──────────────────────────────

/**
 * Factory that wires the strategy chain and returns a ready-to-use CapacityManager.
 * This could be invoked by the service’s DI container.
 */
export function createCapacityManager(kafka: Kafka, breaker: CircuitBreaker): CapacityManager {
    // Build strategy chain
    const trending = new TrendingSpikeStrategy();
    const errorBudget = new ErrorBudgetBurnStrategy();

    trending.setNext(errorBudget);

    const manager = new CapacityManager(trending, kafka, breaker);
    manager.addListener(new AutoscalerListener());

    return manager;
}
```
