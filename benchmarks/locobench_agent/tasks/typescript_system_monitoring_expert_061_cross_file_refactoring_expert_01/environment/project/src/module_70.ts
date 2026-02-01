```typescript
/**************************************************************************************************
 *  File:          src/module_70.ts
 *  Project:       PulseSphere SocialOps (system_monitoring)
 *  Description:   ReactiveCapacityPlanner – listens to enriched telemetry on the Event Backbone,
 *                 correlates infrastructure metrics with social-interaction spikes and produces
 *                 scaling commands.  Combines the Strategy pattern for decision making and the
 *                 Chain-of-Responsibility pattern for decision vetting (quotas, budgets, etc.).
 *
 *                 The class is designed to be instantiated and wired by the IoC container that
 *                 glues the 88 micro-services together.  Nevertheless, it can operate stand-alone
 *                 for unit / integration tests.
 *
 *  Patterns:      • Strategy Pattern
 *                 • Chain of Responsibility
 *                 • Observer (via EventEmitter)
 *
 *  Author:        PulseSphere Engineering
 *************************************************************************************************/

import { EventEmitter } from 'events';
import { flatten, sumBy } from 'lodash';

/* Shared domain contracts -------------------------------------------------- */

export interface TelemetryEvent {
    readonly timestamp: number;                         // epoch ms
    readonly serviceName: string;                       // e.g. "feed-service"
    readonly metrics: { [key: string]: number };        // infra metrics
    readonly socialSignals: {                           // social interaction counts
        likes: number;
        comments: number;
        shares: number;
        liveStreams: number;
    };
}

export type EventBatch = ReadonlyArray<TelemetryEvent>;

export type ScalingAction = 'scale_out' | 'scale_in' | 'no_action';

export interface ScalingDecision {
    readonly serviceName: string;
    readonly action: ScalingAction;
    readonly amount: number;                            // replicas (+/-)
    readonly reason: string;
    readonly timestamp: number;                         // epoch ms
}

export interface Command {
    readonly kind: 'CAPACITY_PLANNING';
    readonly payload: ScalingDecision;
    readonly requestId: string;                         // uuid
}

/* ---------------------------------------------------------------------------------------------- */
/* Logger wrapper – plugs into platform-wide logging infra.                                        */

class Logger {
    constructor(private readonly ctx: string) {}
    info  = (msg: string, meta?: unknown) => console.info(`[INFO] ${this.ctx} :: ${msg}`, meta);
    warn  = (msg: string, meta?: unknown) => console.warn(`[WARN] ${this.ctx} :: ${msg}`, meta);
    error = (msg: string, err?: unknown) => console.error(`[ERROR] ${this.ctx} :: ${msg}`, err);
}

/* ---------------------------------------------------------------------------------------------- */
/* Strategy Pattern – various ways to translate events into scaling decisions.                    */

interface ScalingStrategy {
    readonly name: string;
    /**
     * Return a list of scaling decisions for the given batch, or `undefined`
     * when the strategy decides no action is necessary.
     */
    evaluate(batch: EventBatch): ScalingDecision[] | undefined;
}

/**
 * Strategy #1 – pure CPU utilisation.
 */
class CpuBasedScalingStrategy implements ScalingStrategy {
    readonly name = 'cpu_based';
    private readonly cpuUpper = 0.82; // 82%
    private readonly cpuLower = 0.35; // 35%

    evaluate(batch: EventBatch): ScalingDecision[] | undefined {
        const grouped = groupByService(batch);
        const result: ScalingDecision[] = [];

        grouped.forEach((events, serviceName) => {
            const avgCpu = avg(events, e => e.metrics['cpu_utilisation'] ?? 0);
            if (avgCpu > this.cpuUpper) {
                result.push(decision(serviceName, 'scale_out', +1, `CPU ${percent(avgCpu)} > ${percent(this.cpuUpper)}`));
            } else if (avgCpu < this.cpuLower) {
                result.push(decision(serviceName, 'scale_in', -1, `CPU ${percent(avgCpu)} < ${percent(this.cpuLower)}`));
            }
        });

        return result.length ? result : undefined;
    }
}

/**
 * Strategy #2 – social-interaction spike.
 */
class SocialSpikeScalingStrategy implements ScalingStrategy {
    readonly name = 'social_spike';
    private readonly spikeThreshold = 2.2; // 220% of baseline

    /**
     * Baseline social interactions per service. Normally provided by
     * a stateful time-series store; here, mocked in-memory for brevity.
     */
    private readonly baseline: Map<string, number> = new Map();

    evaluate(batch: EventBatch): ScalingDecision[] | undefined {
        const grouped = groupByService(batch);
        const results: ScalingDecision[] = [];

        grouped.forEach((events, serviceName) => {
            const total = sumBy(events, e =>
                e.socialSignals.likes +
                e.socialSignals.comments +
                e.socialSignals.shares +
                e.socialSignals.liveStreams
            );

            const baseline = this.baseline.get(serviceName) ?? (total / 2); // optimistic bootstrap
            this.baseline.set(serviceName, baseline * 0.9 + total * 0.1);    // EWMA

            if (total > baseline * this.spikeThreshold) {
                const multiplier = Math.ceil(total / baseline);
                results.push(decision(serviceName, 'scale_out', multiplier, `Social spike ${total}/${baseline}`));
            }
        });

        return results.length ? results : undefined;
    }
}

/**
 * Strategy #3 – latency SLO breach.
 */
class LatencyBasedScalingStrategy implements ScalingStrategy {
    readonly name = 'latency_based';
    private readonly p95SloMs = 200; // 95th percentile target latency

    evaluate(batch: EventBatch): ScalingDecision[] | undefined {
        const grouped = groupByService(batch);
        const res: ScalingDecision[] = [];

        grouped.forEach((events, serviceName) => {
            const p95 = percentile(events.map(e => e.metrics['latency_ms'] ?? 0), 0.95);
            if (p95 > this.p95SloMs) {
                res.push(decision(serviceName, 'scale_out', +1, `p95 ${p95.toFixed(0)}ms > ${this.p95SloMs}ms`));
            }
        });

        return res.length ? res : undefined;
    }
}

/* ---------------------------------------------------------------------------------------------- */
/* Chain-of-Responsibility – vetting pipeline for decisions.                                       */

interface DecisionVetter {
    setNext(handler: DecisionVetter): DecisionVetter;
    handle(decision: ScalingDecision): ScalingDecision | null;
}

/**
 * Base class for vetters.
 */
abstract class AbstractVetter implements DecisionVetter {
    private next?: DecisionVetter;

    setNext(handler: DecisionVetter): DecisionVetter {
        this.next = handler;
        return handler;
    }

    protected forward(decision: ScalingDecision): ScalingDecision | null {
        return this.next ? this.next.handle(decision) : decision;
    }
}

/**
 * Vetter #1 – ensure we do not exceed quota caps.
 */
class QuotaVetter extends AbstractVetter {
    private readonly quota = 50; // max replicas

    handle(decision: ScalingDecision): ScalingDecision | null {
        const currentReplicas = getCurrentReplicas(decision.serviceName);
        const desired = currentReplicas + decision.amount;

        if (desired > this.quota) {
            logger.warn(`Quota veto: ${decision.serviceName} desired ${desired} > quota ${this.quota}`);
            return null;
        }
        return this.forward(decision);
    }
}

/**
 * Vetter #2 – simple budget control.
 */
class BudgetVetter extends AbstractVetter {
    private readonly monthlyBudgetUsd = 10_000;
    private readonly costPerReplicaUsd = 30;

    handle(decision: ScalingDecision): ScalingDecision | null {
        if (decision.action === 'no_action') return this.forward(decision);

        const projectedCost = projectedMonthlyCostUsd() + this.costPerReplicaUsd * Math.abs(decision.amount);
        if (projectedCost > this.monthlyBudgetUsd) {
            logger.warn(`Budget veto: projected ${projectedCost} > ${this.monthlyBudgetUsd}`);
            return null;
        }
        return this.forward(decision);
    }
}

/**
 * Vetter #3 – fallback that always allows.
 */
class AllowAllVetter extends AbstractVetter {
    handle(decision: ScalingDecision): ScalingDecision | null {
        return this.forward(decision);
    }
}

/* ---------------------------------------------------------------------------------------------- */
/* ReactiveCapacityPlanner – wiring strategies + vetters together.                                */

const logger = new Logger('ReactiveCapacityPlanner');

export interface PlannerOptions {
    /**
     * Number of ms to aggregate events before evaluation.
     * A sensible default is fine for test environments.
     */
    aggregationWindowMs?: number;
}

export class ReactiveCapacityPlanner extends EventEmitter {
    private readonly aggregationWindowMs: number;
    private readonly buffer: TelemetryEvent[] = [];
    private readonly strategies: ScalingStrategy[];
    private readonly vettingPipeline: DecisionVetter;

    constructor(opts: PlannerOptions = {}) {
        super();
        this.aggregationWindowMs = opts.aggregationWindowMs ?? 5_000;
        this.strategies = [
            new SocialSpikeScalingStrategy(),
            new CpuBasedScalingStrategy(),
            new LatencyBasedScalingStrategy()
        ];

        // Build vetting chain: Quota -> Budget -> AllowAll
        const quota = new QuotaVetter();
        quota
            .setNext(new BudgetVetter())
            .setNext(new AllowAllVetter());
        this.vettingPipeline = quota;

        // flush timer
        setInterval(() => this.flushBuffer(), this.aggregationWindowMs);
    }

    /**
     * Observer entry-point – push telemetry events here.
     */
    public ingest(event: TelemetryEvent): void {
        this.buffer.push(event);
    }

    /* ---------------------------------------------------------------------- */
    /* Internal implementation                                                */

    private flushBuffer(): void {
        if (!this.buffer.length) return;

        const batch = [...this.buffer];
        this.buffer.length = 0; // reset

        try {
            const decisions = this.runStrategies(batch)
                .map(dec => this.vettingPipeline.handle(dec))
                .filter((d): d is ScalingDecision => d !== null);

            decisions.forEach(decision => this.emitDecision(decision));
        } catch (err) {
            logger.error('Failed to evaluate scaling strategies', err);
        }
    }

    private runStrategies(batch: EventBatch): ScalingDecision[] {
        const decisions = flatten(
            this.strategies
                .map(s => {
                    try {
                        return s.evaluate(batch) ?? [];
                    } catch (e) {
                        logger.error(`Strategy ${s.name} error`, e);
                        return [];
                    }
                })
        );

        // deduplicate serviceName (first strategy wins)
        const seen = new Set<string>();
        return decisions.filter(d => {
            const uniq = !seen.has(d.serviceName);
            seen.add(d.serviceName);
            return uniq;
        });
    }

    private emitDecision(decision: ScalingDecision): void {
        logger.info(`Decision: ${decision.serviceName} ${decision.action} ${decision.amount} ➜ ${decision.reason}`);

        const command: Command = {
            kind: 'CAPACITY_PLANNING',
            requestId: uuid(),
            payload: decision
        };

        // Side-effect: publish command on the event backbone
        publishCommand(command);

        // Emit event for in-process listeners (unit tests etc.)
        this.emit('decision', decision);
    }
}

/* ---------------------------------------------------------------------------------------------- */
/* Helpers                                                                                        */

function groupByService(batch: EventBatch): Map<string, TelemetryEvent[]> {
    const m = new Map<string, TelemetryEvent[]>();
    batch.forEach(e => {
        const list = m.get(e.serviceName) ?? [];
        list.push(e);
        m.set(e.serviceName, list);
    });
    return m;
}

function decision(
    serviceName: string,
    action: ScalingAction,
    amount: number,
    reason: string
): ScalingDecision {
    return {
        serviceName,
        action,
        amount,
        reason,
        timestamp: Date.now()
    };
}

function percent(n: number): string {
    return (n * 100).toFixed(1) + '%';
}

function avg<T>(arr: T[], sel: (t: T) => number): number {
    if (!arr.length) return 0;
    return arr.reduce((sum, v) => sum + sel(v), 0) / arr.length;
}

function percentile(values: number[], p: number): number {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const idx = Math.floor(sorted.length * p);
    return sorted[idx];
}

/* --------------------------- mocks / stubs ----------------------------------------------------- */
/* In real service, import these from dedicated packages.                                         */

function uuid(): string {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

function publishCommand(cmd: Command): void {
    // Stub – replace with Kafka / NATS producer
    logger.info(`Publishing command ${cmd.requestId}`, cmd.payload);
}

function getCurrentReplicas(_service: string): number {
    // In reality, query orchestrator (e.g., Kubernetes API)
    return 6;
}

function projectedMonthlyCostUsd(): number {
    /* Replace with FinOps integration */
    return 4_800;
}
```