```typescript
/***************************************************************************************************
 *  File:        src/module_59.ts
 *  Project:     PulseSphere SocialOps (system_monitoring)
 *  Description: Social-aware surge-detection & autoscaling orchestration module.
 *
 *  This module ties together infrastructure telemetry, social-interaction signals and a set of
 *  pluggable scaling strategies.  It leverages Chain-of-Responsibility to classify interaction
 *  surges, Strategy for selecting the appropriate scaling algorithm and Command to dispatch the
 *  resulting scaling request to the platform’s deployment-automation subsystem.
 *
 *  NOTE: This file purposefully stands on its own; external imports reference existing
 *  PulseSphere shared utilities and domain objects.
 ***************************************************************************************************/

import { EventEmitter } from 'events';
import { v4 as uuid } from 'uuid';

import {
    InteractionEvent,
    InteractionType,
    MetricEvent,
    MetricType,
} from './domain/events';
import { Logger } from './utils/logger';
import { KafkaProducer } from './infra/kafka';
import {
    ScalingCommand,
    ScalingCommandBus,
    ScaleTarget,
    ScaleDirection,
} from './domain/commands';
import { CircuitBreaker } from './utils/circuitBreaker';
import { Config } from './config';

/* -------------------------------------------------------------------------------------------------
 * Configuration
 * -----------------------------------------------------------------------------------------------*/

const MODULE_NAME = 'SurgeDetectionModule';
const log = new Logger(MODULE_NAME);

const SURGE_THRESHOLD_PERCENT = Config.get<number>('SURGE_THRESHOLD_PERCENT', 250);
const METRIC_WINDOW = Config.get<number>('SURGE_METRIC_WINDOW_SECONDS', 60);

/* -------------------------------------------------------------------------------------------------
 * Domain helpers / DTOs
 * -----------------------------------------------------------------------------------------------*/

type InteractionSurge = {
    type: InteractionType;
    baseline: number;
    current: number;
    deltaPercent: number;
    timestamp: number;
};

/* -------------------------------------------------------------------------------------------------
 * Chain-of-Responsibility: Surge Handlers
 * -----------------------------------------------------------------------------------------------*/

interface SurgeHandler {
    setNext(next: SurgeHandler | null): SurgeHandler;
    handle(event: InteractionEvent): Promise<InteractionSurge | null>;
}

abstract class AbstractSurgeHandler implements SurgeHandler {
    protected next: SurgeHandler | null = null;

    constructor(protected readonly window: number) {}

    setNext(next: SurgeHandler | null): SurgeHandler {
        this.next = next;
        return next!;
    }

    async handle(event: InteractionEvent): Promise<InteractionSurge | null> {
        if (await this.isSurge(event)) {
            return this.buildSurge(event);
        }
        return this.next ? this.next.handle(event) : null;
    }

    protected abstract isSurge(event: InteractionEvent): Promise<boolean>;
    protected abstract buildSurge(event: InteractionEvent): InteractionSurge;
}

/**
 * LikeSurgeHandler detects spikes in "likes".
 */
class LikeSurgeHandler extends AbstractSurgeHandler {
    protected async isSurge(event: InteractionEvent): Promise<boolean> {
        if (event.type !== InteractionType.Like) return false;

        const baseline = await this.fetchBaseline(event);
        const deltaPercent = ((event.count - baseline) / Math.max(baseline, 1)) * 100;

        log.debug(`Like surge check; baseline=${baseline}, current=${event.count}, delta=${deltaPercent}%`);
        return deltaPercent >= SURGE_THRESHOLD_PERCENT;
    }

    protected buildSurge(event: InteractionEvent): InteractionSurge {
        return {
            type: InteractionType.Like,
            baseline: event.metadata.baseline,
            current: event.count,
            deltaPercent: ((event.count - event.metadata.baseline) / Math.max(event.metadata.baseline, 1)) * 100,
            timestamp: Date.now(),
        };
    }

    private async fetchBaseline(event: InteractionEvent): Promise<number> {
        // In production this would query TSDB / Influx / Prometheus, etc.
        // For now, we rely on metadata passed in the event or default to a minimum.
        return event.metadata?.baseline ?? 10;
    }
}

/**
 * CommentSurgeHandler detects spikes in comments.
 */
class CommentSurgeHandler extends AbstractSurgeHandler {
    protected async isSurge(event: InteractionEvent): Promise<boolean> {
        if (event.type !== InteractionType.Comment) return false;

        const median = await this.fetchMedian(event);
        const deltaPercent = ((event.count - median) / Math.max(median, 1)) * 100;
        log.debug(`Comment surge check; median=${median}, current=${event.count}, delta=${deltaPercent}%`);

        return deltaPercent >= SURGE_THRESHOLD_PERCENT;
    }

    protected buildSurge(event: InteractionEvent): InteractionSurge {
        return {
            type: InteractionType.Comment,
            baseline: event.metadata.median,
            current: event.count,
            deltaPercent: ((event.count - event.metadata.median) / Math.max(event.metadata.median, 1)) * 100,
            timestamp: Date.now(),
        };
    }

    private async fetchMedian(event: InteractionEvent): Promise<number> {
        return event.metadata?.median ?? 5;
    }
}

/* -------------------------------------------------------------------------------------------------
 * Strategy Pattern: Scaling Strategies
 * -----------------------------------------------------------------------------------------------*/

interface ScalingStrategy {
    name: string;
    generateCommand(surge: InteractionSurge): ScalingCommand;
}

/**
 * HorizontalPodScalingStrategy scales Pods based on the surge magnitude.
 */
class HorizontalPodScalingStrategy implements ScalingStrategy {
    public name = 'HorizontalPodScalingStrategy';

    generateCommand(surge: InteractionSurge): ScalingCommand {
        const magnitude = Math.ceil(surge.deltaPercent / 100); // 1 replica per +100%
        return {
            id: uuid(),
            target: ScaleTarget.PODS,
            direction: ScaleDirection.Up,
            magnitude,
            reason: `${surge.type} surge (${surge.deltaPercent.toFixed(1)}%)`,
            issuedAt: Date.now(),
        };
    }
}

/**
 * QueueBasedScalingStrategy increases queue partition & consumer counts.
 */
class QueueBasedScalingStrategy implements ScalingStrategy {
    public name = 'QueueBasedScalingStrategy';

    generateCommand(surge: InteractionSurge): ScalingCommand {
        const magnitude = Math.ceil(surge.deltaPercent / 150); // 1 partition per +150%
        return {
            id: uuid(),
            target: ScaleTarget.KAFKA_PARTITIONS,
            direction: ScaleDirection.Up,
            magnitude,
            reason: `${surge.type} surge (${surge.deltaPercent.toFixed(1)}%)`,
            issuedAt: Date.now(),
        };
    }
}

/* -------------------------------------------------------------------------------------------------
 * Surge Correlation Service: orchestrates detection & scaling
 * -----------------------------------------------------------------------------------------------*/

class SurgeCorrelationService extends EventEmitter {
    private readonly surgeHandler: SurgeHandler;
    private readonly scalingStrategies: Map<InteractionType, ScalingStrategy>;
    private readonly producer: KafkaProducer;
    private readonly commandBus: ScalingCommandBus;
    private readonly breaker: CircuitBreaker;

    constructor() {
        super();

        // Compose Chain-of-Responsibility
        const likeHandler = new LikeSurgeHandler(METRIC_WINDOW);
        const commentHandler = new CommentSurgeHandler(METRIC_WINDOW);

        likeHandler.setNext(commentHandler).setNext(null);
        this.surgeHandler = likeHandler;

        // Register strategies
        this.scalingStrategies = new Map([
            [InteractionType.Like, new HorizontalPodScalingStrategy()],
            [InteractionType.Comment, new QueueBasedScalingStrategy()],
        ]);

        // Setup infra dependencies
        this.producer = new KafkaProducer({
            clientId: 'surge-correlator',
            brokers: Config.get<string>('KAFKA_BROKERS', 'kafka-broker:9092').split(','),
        });

        this.commandBus = new ScalingCommandBus(this.producer);
        this.breaker = new CircuitBreaker({
            failureThreshold: 5,
            successThreshold: 2,
            timeout: 10_000,
        });

        // Event listeners
        this.on('interaction', ev => this.processInteraction(ev).catch(err => log.error(err)));
    }

    async processInteraction(event: InteractionEvent): Promise<void> {
        log.trace(`Processing interaction event: ${JSON.stringify(event)}`);

        const surge = await this.surgeHandler.handle(event);
        if (!surge) {
            log.trace('No surge detected.');
            return;
        }

        log.info(
            `Detected ${InteractionType[surge.type]} surge: ${surge.deltaPercent.toFixed(
                1,
            )}% over baseline (${surge.baseline} -> ${surge.current})`,
        );

        const strategy = this.scalingStrategies.get(surge.type);
        if (!strategy) {
            log.warn(`No scaling strategy registered for interaction type ${surge.type}`);
            return;
        }

        const command = strategy.generateCommand(surge);
        await this.dispatchScalingCommand(command);
    }

    private async dispatchScalingCommand(command: ScalingCommand): Promise<void> {
        try {
            await this.breaker.exec(() => this.commandBus.publish(command));
            log.info(
                `Scaling command dispatched. target=${command.target}, x${command.magnitude}, reason=${command.reason}`,
            );
        } catch (err) {
            log.error(
                `Failed to dispatch scaling command (reason: ${(err as Error).message}). Command queued for retry.`,
            );
            // Dead-letter queue fallback
            await this.producer.send({
                topic: 'scaling_commands_dlq',
                messages: [{ key: command.id, value: JSON.stringify(command) }],
            });
        }
    }
}

/* -------------------------------------------------------------------------------------------------
 * Module boot-strap
 * -----------------------------------------------------------------------------------------------*/

const service = new SurgeCorrelationService();

/**
 * Subscribes to global event bus for interaction events.
 * In reality, this would live in the transport-layer adapter; implemented here for brevity.
 */
const globalEventEmitter = new EventEmitter();
globalEventEmitter.on('InteractionEvent', (event: InteractionEvent) => service.emit('interaction', event));

/* -------------------------------------------------------------------------------------------------
 * Graceful shutdown
 * -----------------------------------------------------------------------------------------------*/

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

let shuttingDown = false;
async function shutdown(): Promise<void> {
    if (shuttingDown) return;
    shuttingDown = true;

    log.info('SurgeCorrelationService shutting down...');
    try {
        await service.removeAllListeners();
        await service['producer']?.disconnect();
        log.info('Shutdown complete.');
        process.exit(0);
    } catch (err) {
        log.error('Error during shutdown', err as Error);
        process.exit(1);
    }
}

/***************************************************************************************************
 * End of file
 ***************************************************************************************************/
```