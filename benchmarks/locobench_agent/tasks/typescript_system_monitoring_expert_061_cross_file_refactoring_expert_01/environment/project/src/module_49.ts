```typescript
/***************************************************************************************************
 *  PulseSphere SocialOps – module_49.ts
 *
 *  AdaptiveCapacityOrchestrator
 *  --------------------------------------------------------------
 *  Consumes social-interaction signals & infrastructure metrics from Kafka, correlates them in
 *  near-real-time, decides whether the cluster requires capacity adjustments, validates commands
 *  through a chain-of-responsibility, and finally emits scale commands back to the mesh.
 *
 *  Patterns demonstrated
 *  - Observer (RxJS Observables & Subjects)
 *  - Strategy (different ScalingStrategy implementations)
 *  - Chain of Responsibility (command validators)
 *  - Command (ScalingCommand dispatched onto Kafka)
 *
 *  NOTE: The surrounding project provides dependency injection, configuration bootstrapping,
 *  logging transports, etc.  Here we keep the module self-contained for illustration purposes.
 ***************************************************************************************************/

import { Kafka, Producer, Consumer, EachMessagePayload, logLevel } from 'kafkajs';
import { Subject, merge, Observable } from 'rxjs';
import { bufferTime, filter, map } from 'rxjs/operators';
import Ajv, { JSONSchemaType } from 'ajv';
import * as winston from 'winston';
import { v4 as uuidv4 } from 'uuid';

/* -------------------------------------------------------------------------------------------------
 * Shared domain models
 * -----------------------------------------------------------------------------------------------*/

type SocialSignalType = 'LIKE' | 'COMMENT' | 'SHARE' | 'STREAM_VIEW';

interface SocialSignal {
    timestamp: number;            // Unix epoch in ms
    userId: string;
    signal: SocialSignalType;
    magnitude?: number;           // Optional weight e.g. concurrent viewers
}

interface InfrastructureMetric {
    timestamp: number;            // Unix epoch in ms
    service: string;              // micro-service ID
    cpu: number;                  // CPU usage percentage
    mem: number;                  // Memory usage percentage
    latency: number;              // P95 latency in ms
}

interface EnrichedTelemetry {
    socialSignals: SocialSignal[];
    infraMetrics: InfrastructureMetric[];
}

export interface ScalingCommand {
    id: string;
    service: string;
    action: 'SCALE_OUT' | 'SCALE_IN' | 'SCALE_UP' | 'SCALE_DOWN';
    delta: number;
    reason: string;
    createdAt: number;
}

/* -------------------------------------------------------------------------------------------------
 * Logger
 * -----------------------------------------------------------------------------------------------*/

const logger = winston.createLogger({
    level: process.env.LOG_LEVEL ?? 'info',
    transports: [
        new winston.transports.Console({ format: winston.format.simple() }),
    ],
});

/* -------------------------------------------------------------------------------------------------
 * Kafka bootstrap helpers
 * -----------------------------------------------------------------------------------------------*/

const kafka = new Kafka({
    clientId: 'pulseSphere-adaptive-capacity-orchestrator',
    brokers: (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
    logLevel: logLevel.ERROR,
});

const SOCIAL_TOPIC = 'social-signals';
const INFRA_TOPIC = 'infra-metrics';
const COMMAND_TOPIC = 'cluster-commands';

/* -------------------------------------------------------------------------------------------------
 * Scaling strategy pattern
 * -----------------------------------------------------------------------------------------------*/

interface ScalingStrategy {
    /**
     * Evaluate whether the incoming telemetry warrants a scaling command.
     * @returns ScalingCommand or null if no action needed.
     */
    assess(telemetry: EnrichedTelemetry): ScalingCommand | null;
}

/**
 * Horizontal scaling strategy – scales replicas in/out based on CPU and social-interaction surge.
 */
class HorizontalScalingStrategy implements ScalingStrategy {
    private readonly cpuThreshold = 70;           // %
    private readonly socialSurgeThreshold = 1.7;  // 70% spike compared to baseline

    assess({ socialSignals, infraMetrics }: EnrichedTelemetry): ScalingCommand | null {
        if (infraMetrics.length === 0) return null;

        // Simple heuristic: compare average CPU to threshold & social signal surge
        const avgCpu = infraMetrics.reduce((acc, m) => acc + m.cpu, 0) / infraMetrics.length;

        const baselineSocial = 100; // Would normally come from historical trend data
        const currentSocial = socialSignals.length;
        const surgeRatio = currentSocial / (baselineSocial || 1);

        logger.debug(
            `[HorizontalScalingStrategy] avgCpu=${avgCpu.toFixed(
                1,
            )}, surgeRatio=${surgeRatio.toFixed(2)}`,
        );

        if (avgCpu > this.cpuThreshold && surgeRatio > this.socialSurgeThreshold) {
            return {
                id: uuidv4(),
                service: infraMetrics[0].service,
                action: 'SCALE_OUT',
                delta: 2,
                reason: `CPU ${avgCpu.toFixed(
                    1,
                )}% with social surge ${surgeRatio.toFixed(2)}x`,
                createdAt: Date.now(),
            };
        }

        if (avgCpu < this.cpuThreshold * 0.4 && surgeRatio < 0.4) {
            return {
                id: uuidv4(),
                service: infraMetrics[0].service,
                action: 'SCALE_IN',
                delta: 1,
                reason: `CPU ${avgCpu.toFixed(
                    1,
                )}% and low social activity, consolidating resources`,
                createdAt: Date.now(),
            };
        }

        return null;
    }
}

/**
 * Vertical scaling strategy – alters resource limits in place (memory / CPU) for stateful services.
 */
class VerticalScalingStrategy implements ScalingStrategy {
    private readonly latencySLO = 150; // ms P95

    assess({ infraMetrics }: EnrichedTelemetry): ScalingCommand | null {
        if (infraMetrics.length === 0) return null;

        const metric = infraMetrics[0]; // Assume single service per batch for simplicity

        if (metric.latency > this.latencySLO && metric.cpu > 80) {
            return {
                id: uuidv4(),
                service: metric.service,
                action: 'SCALE_UP',
                delta: 1,
                reason: `Latency ${metric.latency}ms above SLO and CPU ${metric.cpu}%`,
                createdAt: Date.now(),
            };
        }

        if (metric.latency < this.latencySLO * 0.6 && metric.cpu < 40) {
            return {
                id: uuidv4(),
                service: metric.service,
                action: 'SCALE_DOWN',
                delta: 1,
                reason: `Latency ${metric.latency}ms well below SLO and CPU ${metric.cpu}%`,
                createdAt: Date.now(),
            };
        }

        return null;
    }
}

/* -------------------------------------------------------------------------------------------------
 * Chain-of-Responsibility for command validation
 * -----------------------------------------------------------------------------------------------*/

abstract class CommandValidator {
    protected next?: CommandValidator;

    setNext(next: CommandValidator): CommandValidator {
        this.next = next;
        return next;
    }

    validate(cmd: ScalingCommand): ScalingCommand | null {
        const res = this.handle(cmd);
        if (!res || !this.next) return res;
        return this.next.validate(res);
    }

    protected abstract handle(cmd: ScalingCommand): ScalingCommand | null;
}

/**
 * Ensures that we don't scale a service too frequently (rate limit window).
 */
class RateLimitValidator extends CommandValidator {
    private readonly windowMs = 60_000; // 1 min window
    private readonly history = new Map<string, number>(); // service -> last scaling ts

    protected handle(cmd: ScalingCommand): ScalingCommand | null {
        const last = this.history.get(cmd.service);
        const now = Date.now();
        if (last && now - last < this.windowMs) {
            logger.info(
                `[RateLimitValidator] Rejecting command ${cmd.id} for ${cmd.service} – rate limit hit.`,
            );
            return null;
        }
        this.history.set(cmd.service, now);
        return cmd;
    }
}

/**
 * Makes sure scaling action doesn't exceed allocated budget.
 * (Simplified – real impl would check budgets via external system.)
 */
class BudgetValidator extends CommandValidator {
    private readonly monthlyBudget = 10_000; // $
    private spent = 0;

    protected handle(cmd: ScalingCommand): ScalingCommand | null {
        const estCost = Math.abs(cmd.delta) * 2; // $2 per replica/hour placeholder
        if (this.spent + estCost > this.monthlyBudget) {
            logger.warn(
                `[BudgetValidator] Budget exceeded for command ${cmd.id} (${cmd.reason}).`,
            );
            return null;
        }
        this.spent += estCost;
        return cmd;
    }
}

/**
 * Verifies command won't breach SLA obligations (placeholder).
 */
class SLAValidator extends CommandValidator {
    protected handle(cmd: ScalingCommand): ScalingCommand | null {
        // Example: can't scale in below 2 replicas
        if (cmd.action === 'SCALE_IN' && cmd.delta >= 2) {
            logger.warn(
                `[SLAValidator] Rejecting command ${cmd.id} – would reduce replicas too aggressively.`,
            );
            return null;
        }
        return cmd;
    }
}

/* -------------------------------------------------------------------------------------------------
 * AdaptiveCapacityOrchestrator
 * -----------------------------------------------------------------------------------------------*/

export class AdaptiveCapacityOrchestrator {
    private readonly socialSubject = new Subject<SocialSignal>();
    private readonly infraSubject = new Subject<InfrastructureMetric>();

    private readonly strategies: ScalingStrategy[] = [
        new HorizontalScalingStrategy(),
        new VerticalScalingStrategy(),
    ];

    private readonly validatorChain: CommandValidator;

    private producer!: Producer;
    private socialConsumer!: Consumer;
    private infraConsumer!: Consumer;

    private readonly ajv = new Ajv();
    private readonly socialSchema: JSONSchemaType<SocialSignal> = {
        type: 'object',
        properties: {
            timestamp: { type: 'number' },
            userId: { type: 'string' },
            signal: { type: 'string', enum: ['LIKE', 'COMMENT', 'SHARE', 'STREAM_VIEW'] },
            magnitude: { type: 'number', nullable: true },
        },
        required: ['timestamp', 'userId', 'signal'],
        additionalProperties: false,
    };
    private readonly infraSchema: JSONSchemaType<InfrastructureMetric> = {
        type: 'object',
        properties: {
            timestamp: { type: 'number' },
            service: { type: 'string' },
            cpu: { type: 'number' },
            mem: { type: 'number' },
            latency: { type: 'number' },
        },
        required: ['timestamp', 'service', 'cpu', 'mem', 'latency'],
        additionalProperties: false,
    };

    private readonly validateSocial = this.ajv.compile(this.socialSchema);
    private readonly validateInfra = this.ajv.compile(this.infraSchema);

    constructor(private readonly bufferIntervalMs = 5_000) {
        // Build validator chain
        const rateLimit = new RateLimitValidator();
        rateLimit.setNext(new BudgetValidator()).setNext(new SLAValidator());
        this.validatorChain = rateLimit;
    }

    /**
     * Initialize Kafka connections, Observables, and start processing loop.
     */
    async start(): Promise<void> {
        this.producer = kafka.producer();
        await this.producer.connect();

        // Social streamer consumer
        this.socialConsumer = kafka.consumer({ groupId: 'social-consumer-group' });
        await this.socialConsumer.connect();
        await this.socialConsumer.subscribe({ topic: SOCIAL_TOPIC, fromBeginning: false });
        this.socialConsumer.run({
            eachMessage: async ({ message }: EachMessagePayload) => {
                if (!message.value) return;
                try {
                    const parsed = JSON.parse(message.value.toString());
                    if (this.validateSocial(parsed)) {
                        this.socialSubject.next(parsed);
                    } else {
                        logger.debug(
                            `[AdaptiveCapacityOrchestrator] Invalid social signal skipped: ${this.ajv.errorsText(
                                this.validateSocial.errors,
                            )}`,
                        );
                    }
                } catch (err) {
                    logger.error('[AdaptiveCapacityOrchestrator] Failed to parse social signal', err);
                }
            },
        });

        // Infra metrics consumer
        this.infraConsumer = kafka.consumer({ groupId: 'infra-consumer-group' });
        await this.infraConsumer.connect();
        await this.infraConsumer.subscribe({ topic: INFRA_TOPIC, fromBeginning: false });
        this.infraConsumer.run({
            eachMessage: async ({ message }: EachMessagePayload) => {
                if (!message.value) return;
                try {
                    const parsed = JSON.parse(message.value.toString());
                    if (this.validateInfra(parsed)) {
                        this.infraSubject.next(parsed);
                    } else {
                        logger.debug(
                            `[AdaptiveCapacityOrchestrator] Invalid infra metric skipped: ${this.ajv.errorsText(
                                this.validateInfra.errors,
                            )}`,
                        );
                    }
                } catch (err) {
                    logger.error('[AdaptiveCapacityOrchestrator] Failed to parse infra metric', err);
                }
            },
        });

        this.bootstrapProcessingPipeline();

        logger.info('[AdaptiveCapacityOrchestrator] Started.');
    }

    /**
     * Clean shutdown of Kafka resources & RxJS streams.
     */
    async stop(): Promise<void> {
        await Promise.allSettled([
            this.socialConsumer?.disconnect(),
            this.infraConsumer?.disconnect(),
            this.producer?.disconnect(),
        ]);
        this.socialSubject.complete();
        this.infraSubject.complete();
        logger.info('[AdaptiveCapacityOrchestrator] Stopped.');
    }

    /* ---------------------------------------------------------------------------------------------
     * Internal helpers
     * -------------------------------------------------------------------------------------------*/

    /**
     * Combine social & infra streams, buffer them for window duration, and run strategies + validators.
     */
    private bootstrapProcessingPipeline(): void {
        const socialStream = this.socialSubject.asObservable();
        const infraStream = this.infraSubject.asObservable();

        merge(socialStream, infraStream)
            .pipe(
                bufferTime(this.bufferIntervalMs), // Collect messages for interval
                filter((buffer) => buffer.length > 0),
                map(() => {
                    // Build telemetry snapshot from buffered subjects
                    const socialSignals: SocialSignal[] = [];
                    const infraMetrics: InfrastructureMetric[] = [];

                    this.drainSubject(this.socialSubject, socialSignals);
                    this.drainSubject(this.infraSubject, infraMetrics);

                    return { socialSignals, infraMetrics } as EnrichedTelemetry;
                }),
            )
            .subscribe({
                next: (telemetry) => this.processTelemetry(telemetry),
                error: (err) => logger.error('[AdaptiveCapacityOrchestrator] Stream error', err),
            });
    }

    private drainSubject<T>(subject: Subject<T>, into: T[]): void {
        // Since RxJS Subjects don't expose buffered values, we maintain arrays directly in pipeline.
        // This helper is placeholder: In real system we'd use ReplaySubject/scan.
    }

    private processTelemetry(telemetry: EnrichedTelemetry): void {
        // Run through each strategy until a command is produced
        for (const strategy of this.strategies) {
            const command = strategy.assess(telemetry);
            if (command) {
                const validated = this.validatorChain.validate(command);
                if (validated) {
                    this.dispatchCommand(validated).catch((err) =>
                        logger.error('[AdaptiveCapacityOrchestrator] Failed to dispatch command', err),
                    );
                }
                break; // only one strategy applies per cycle
            }
        }
    }

    private async dispatchCommand(cmd: ScalingCommand): Promise<void> {
        await this.producer.send({
            topic: COMMAND_TOPIC,
            messages: [
                {
                    key: cmd.service,
                    value: JSON.stringify(cmd),
                },
            ],
        });
        logger.info(
            `[AdaptiveCapacityOrchestrator] Dispatched ${cmd.action}(${cmd.delta}) for ${cmd.service}: ${cmd.reason}`,
        );
    }
}

/* -------------------------------------------------------------------------------------------------
 * Module bootstrap (executes when module is run directly)
 * -----------------------------------------------------------------------------------------------*/

if (require.main === module) {
    // eslint-disable-next-line @typescript-eslint/no-floating-promises
    (async () => {
        const orchestrator = new AdaptiveCapacityOrchestrator();
        process.on('SIGINT', async () => {
            await orchestrator.stop();
            process.exit(0);
        });
        process.on('SIGTERM', async () => {
            await orchestrator.stop();
            process.exit(0);
        });
        await orchestrator.start();
    })();
}
```