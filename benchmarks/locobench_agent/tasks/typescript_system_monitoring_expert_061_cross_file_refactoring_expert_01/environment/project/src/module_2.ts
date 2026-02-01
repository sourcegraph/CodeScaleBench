```typescript
/**************************************************************************************************
 * File:        src/module_2.ts
 * Project:     PulseSphere SocialOps (system_monitoring)
 * Description: Telemetry processing pipeline that enriches incoming infrastructure metrics with
 *              social-context signals (likes, comments, shares) and decides—via Strategy &
 *              Chain-of-Responsibility patterns—whether to orchestrate proactive capacity
 *              adjustments. The module exposes a self-contained `TelemetryProcessor` that can be
 *              wired into any event-driven transport (Kafka/NATS/HTTP) and notifies downstream
 *              observers when a scaling decision has been reached.
 *
 * Architectural patterns demonstrated:
 *   • Observer                  – EventEmitter-based subscription to processed telemetry
 *   • Chain-of-Responsibility   – Sequential handlers (validate → surge-detect → scale)
 *   • Strategy                  – Pluggable scaling algorithms (aggressive, conservative, noop)
 *
 * NOTE: This file purposefully avoids external framework bindings (NestJS, Express, etc.) to keep
 *       it transport-agnostic and easily testable. Integrations are expected to wrap the public
 *       `TelemetryProcessor` methods.
 **************************************************************************************************/

import { EventEmitter } from 'events';
import { createLogger, format, transports, Logger } from 'winston';

// ────────────────────────────────────────────────────────────────────────────
//  Domain Types
// ────────────────────────────────────────────────────────────────────────────

/**
 * Represents an incoming telemetry datapoint produced by a system-metrics collector
 * and already enriched with social-engagement metadata upstream.
 */
export interface TelemetryEvent {
    metricName: string;                         // e.g. "api.requests_per_sec"
    value: number;                              // numeric datapoint
    timestamp: number;                          // epoch millis
    /** Social context signals harvested via the PulseSphere mesh sidecar */
    socialSignals: {
        likes: number;
        comments: number;
        shares: number;
        liveViewers: number;
    };
    /** Additional freeform metadata */
    meta?: Record<string, unknown>;
}

/** Lightweight DTO emitted when a scaling request has been decided */
export interface ScalingCommand {
    readonly clusterId: string;
    readonly desiredReplicas: number;
    readonly reason: string;
    readonly issuedAt: number;
}

// ────────────────────────────────────────────────────────────────────────────
//  Observer Pattern
// ────────────────────────────────────────────────────────────────────────────

/**
 * Centralised broadcaster for processed events. Other bounded contexts (alerting,
 * deployment-automation, etc.) can listen to high-level signals without tight coupling.
 */
export class TelemetrySubject extends EventEmitter {
    static readonly EVENTS = {
        SCALING_NEEDED: 'scaling_needed',
        EVENT_REJECTED: 'event_rejected',
    } as const;
}

// ────────────────────────────────────────────────────────────────────────────
//  Chain-of-Responsibility (abstract handler)
// ────────────────────────────────────────────────────────────────────────────

/**
 * Base class for pipeline handlers. Each handler can decide to END or FORWARD the
 * processing. Errors bubble upward and are logged once by the pipeline coordinator.
 */
abstract class Handler {
    protected next?: Handler;

    constructor(protected readonly logger: Logger) {}

    setNext(handler: Handler): Handler {
        this.next = handler;
        return handler;
    }

    async handle(event: TelemetryEvent, subject: TelemetrySubject): Promise<void> {
        const shouldContinue = await this.process(event, subject);
        if (shouldContinue && this.next) {
            return this.next.handle(event, subject);
        }
    }

    /**
     * @returns true  → forward event to next handler
     *          false → stop chain propagation
     */
    protected abstract process(
        event: TelemetryEvent,
        subject: TelemetrySubject,
    ): Promise<boolean>;
}

// ────────────────────────────────────────────────────────────────────────────
//  Concrete Handlers
// ────────────────────────────────────────────────────────────────────────────

/**
 * Performs basic schema & sanity checks. Rejects obviously corrupt data early.
 */
class ValidationHandler extends Handler {
    private static readonly REQUIRED_FIELDS: (keyof TelemetryEvent)[] = [
        'metricName',
        'value',
        'timestamp',
        'socialSignals',
    ];

    protected async process(event: TelemetryEvent, subject: TelemetrySubject): Promise<boolean> {
        for (const field of ValidationHandler.REQUIRED_FIELDS) {
            if (event[field] === undefined || event[field] === null) {
                this.logger.warn(`Telemetry event missing required field "${field}"`, { event });
                subject.emit(TelemetrySubject.EVENTS.EVENT_REJECTED, {
                    reason: `Missing field: ${field}`,
                    event,
                });
                return false; // stop chain
            }
        }
        return true;
    }
}

/**
 * Detects social-driven surges (likes, shares, etc.) that may soon overload
 * infrastructure. If a surge is not detected, the chain stops here.
 */
class SurgeDetectionHandler extends Handler {
    private readonly likeThreshold: number;
    private readonly shareThreshold: number;
    private readonly liveViewerThreshold: number;

    constructor(logger: Logger, cfg?: { like?: number; share?: number; live?: number }) {
        super(logger);
        this.likeThreshold = cfg?.like ?? 1_000;
        this.shareThreshold = cfg?.share ?? 500;
        this.liveViewerThreshold = cfg?.live ?? 10_000;
    }

    protected async process(event: TelemetryEvent): Promise<boolean> {
        const signals = event.socialSignals;
        const surgeDetected =
            signals.likes >= this.likeThreshold ||
            signals.shares >= this.shareThreshold ||
            signals.liveViewers >= this.liveViewerThreshold;

        if (!surgeDetected) {
            this.logger.debug('No social surge detected, skipping scaling.', {
                metric: event.metricName,
                signals,
            });
            // Do NOT continue the chain – no scaling required
            return false;
        }

        this.logger.info('Social surge detected.', {
            metric: event.metricName,
            signals,
        });
        return true; // continue to scaling handler
    }
}

// ────────────────────────────────────────────────────────────────────────────
//  Strategy Pattern for scaling algorithms
// ────────────────────────────────────────────────────────────────────────────

export interface ScalingStrategy {
    /**
     * Calculates how many replicas are needed to sustain observed load.
     *
     * @param currentReplicas Current number of replicas in the cluster
     * @param event           Event responsible for triggering scaling evaluation
     */
    computeDesiredReplicas(currentReplicas: number, event: TelemetryEvent): number;
}

class AggressiveScalingStrategy implements ScalingStrategy {
    computeDesiredReplicas(currentReplicas: number, event: TelemetryEvent): number {
        // Scale up quickly: +50% replicas per detection
        return Math.ceil(currentReplicas * 1.5);
    }
}

class ConservativeScalingStrategy implements ScalingStrategy {
    computeDesiredReplicas(currentReplicas: number, event: TelemetryEvent): number {
        // Step scaling: +1 replica at a time (bounded)
        return currentReplicas + 1;
    }
}

class NoopScalingStrategy implements ScalingStrategy {
    computeDesiredReplicas(currentReplicas: number): number {
        return currentReplicas; // no scaling
    }
}

// ────────────────────────────────────────────────────────────────────────────
//  Scaling Handler (end of chain)
// ────────────────────────────────────────────────────────────────────────────

class ScalingDecisionHandler extends Handler {
    private readonly strategy: ScalingStrategy;
    private readonly clusterIdResolver: (event: TelemetryEvent) => string;
    private readonly minReplicas: number;
    private readonly maxReplicas: number;

    constructor(
        logger: Logger,
        cfg: {
            strategy: ScalingStrategy;
            clusterIdResolver?: (event: TelemetryEvent) => string;
            minReplicas?: number;
            maxReplicas?: number;
        },
    ) {
        super(logger);
        this.strategy = cfg.strategy;
        this.clusterIdResolver = cfg.clusterIdResolver ?? (() => 'default-cluster');
        this.minReplicas = cfg.minReplicas ?? 1;
        this.maxReplicas = cfg.maxReplicas ?? 1_000;
    }

    protected async process(event: TelemetryEvent, subject: TelemetrySubject): Promise<boolean> {
        const clusterId = this.clusterIdResolver(event);
        const currentReplicas = this.resolveCurrentReplicas(clusterId);

        const desired = this.strategy.computeDesiredReplicas(currentReplicas, event);
        const boundedDesired = Math.max(this.minReplicas, Math.min(this.maxReplicas, desired));

        if (boundedDesired === currentReplicas) {
            this.logger.info('Scaling evaluation resulted in no changes.', { clusterId });
            return false; // chain ends
        }

        const cmd: ScalingCommand = {
            clusterId,
            desiredReplicas: boundedDesired,
            reason: 'social-surge',
            issuedAt: Date.now(),
        };

        this.logger.info('Emitting scaling command.', cmd);
        subject.emit(TelemetrySubject.EVENTS.SCALING_NEEDED, cmd);
        return false; // end of chain
    }

    /** Placeholder: in real life we'd query Kubernetes-API, Nomad, etc. */
    private resolveCurrentReplicas(_clusterId: string): number {
        return 3; // mock value for demo purposes
    }
}

// ────────────────────────────────────────────────────────────────────────────
//  Public API – TelemetryProcessor
// ────────────────────────────────────────────────────────────────────────────

export interface TelemetryProcessorOptions {
    scalingStrategy?: 'aggressive' | 'conservative' | 'noop';
    validation?: { like?: number; share?: number; live?: number };
    minReplicas?: number;
    maxReplicas?: number;
}

/**
 * Exposes a high-level facade to process telemetry events. Downstream consumers
 * may subscribe to the `subject` property to react to scaling decisions.
 */
export class TelemetryProcessor {
    /** Observer subject for external consumers */
    public readonly subject = new TelemetrySubject();

    private readonly logger: Logger;
    private readonly pipeline: Handler;

    constructor(private readonly opts: TelemetryProcessorOptions = {}) {
        // Create namespaced logger
        this.logger = createLogger({
            level: process.env.PS_LOG_LEVEL || 'info',
            format: format.combine(
                format.timestamp(),
                format.errors({ stack: true }),
                format.splat(),
                format.json(),
            ),
            transports: [new transports.Console()],
            defaultMeta: { service: 'telemetry-processor' },
        });

        // Build handler chain
        const validator = new ValidationHandler(this.logger);
        const surgeDetector = new SurgeDetectionHandler(this.logger, opts.validation);
        const scaler = new ScalingDecisionHandler(this.logger, {
            strategy: TelemetryProcessor.selectStrategy(opts.scalingStrategy),
            minReplicas: opts.minReplicas,
            maxReplicas: opts.maxReplicas,
        });

        validator.setNext(surgeDetector).setNext(scaler);
        this.pipeline = validator;
    }

    /**
     * Entry-point for new telemetry events.
     */
    async ingest(event: TelemetryEvent): Promise<void> {
        try {
            await this.pipeline.handle(event, this.subject);
        } catch (err) {
            this.logger.error('Unhandled error in telemetry pipeline', { err, event });
        }
    }

    // ────────────────────────────────────────────────────────────────────────
    //  Helpers
    // ────────────────────────────────────────────────────────────────────────

    private static selectStrategy(name: TelemetryProcessorOptions['scalingStrategy']): ScalingStrategy {
        switch (name) {
            case 'aggressive':
                return new AggressiveScalingStrategy();
            case 'conservative':
                return new ConservativeScalingStrategy();
            case 'noop':
            default:
                return new NoopScalingStrategy();
        }
    }
}

// ────────────────────────────────────────────────────────────────────────────
//  Graceful Shutdown Helpers
// ────────────────────────────────────────────────────────────────────────────

const activeProcessors = new Set<TelemetryProcessor>();

/**
 * Registers a processor instance for graceful shutdown. This prevents event loss
 * when the node process receives termination signals (SIGTERM/SIGINT).
 */
export function registerForShutdown(processor: TelemetryProcessor): void {
    if (activeProcessors.size === 0) {
        // Register global listener once
        process.once('SIGTERM', shutdownAll);
        process.once('SIGINT', shutdownAll);
    }
    activeProcessors.add(processor);
}

async function shutdownAll(): Promise<void> {
    // In real life we would flush buffers, commit offsets, etc.
    for (const p of activeProcessors) {
        // eslint-disable-next-line no-await-in-loop
        await new Promise<void>((resolve) => {
            p.subject.removeAllListeners();
            resolve();
        });
    }
    process.exit(0);
}

// ────────────────────────────────────────────────────────────────────────────
//  Example (to be removed in production): Self-contained demo execution
// ────────────────────────────────────────────────────────────────────────────

if (require.main === module) {
    const processor = new TelemetryProcessor({ scalingStrategy: 'aggressive' });

    // Register for shutdown
    registerForShutdown(processor);

    // Subscribe to scaling events
    processor.subject.on(TelemetrySubject.EVENTS.SCALING_NEEDED, (cmd: ScalingCommand) => {
        // eslint-disable-next-line no-console
        console.log('Scaling command received →', cmd);
    });

    // Emit a dummy event
    processor.ingest({
        metricName: 'api.requests_per_sec',
        value: 12_000,
        timestamp: Date.now(),
        socialSignals: {
            likes: 2_000,
            comments: 300,
            shares: 800,
            liveViewers: 15_000,
        },
    });
}
```