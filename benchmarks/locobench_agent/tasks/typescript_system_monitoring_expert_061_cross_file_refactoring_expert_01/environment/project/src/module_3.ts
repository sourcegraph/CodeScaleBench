```typescript
/**************************************************************************************************
 *  File:          src/module_3.ts
 *  Project:       PulseSphere SocialOps  – System-Monitoring
 *  Description:   “Social-Aware Auto-Scaler”
 *
 *  This module consumes both infrastructure metrics and real-time social-interaction signals from
 *  the event backbone (Kafka + NATS), enriches / correlates them, and runs them through a
 *  Chain-of-Responsibility of scaling strategies.  When a strategy emits a scaling decision,
 *  an imperative “ScaleCluster” command is published for the orchestration subsystem.
 *
 *  Patterns in play:
 *    • Observer                    – Kafka/NATS consumers ⇒ notify AutoScaler
 *    • Chain-of-Responsibility     – Strategy chain for scaling decisions
 *    • Strategy                    – Concrete scaling algorithms
 *    • Command                     – ScaleClusterCommand published to “orchestrator.commands”
 *
 *  NOTE: Other helper modules (`./utils/logger`, `./config`, etc.) exist elsewhere in the codebase.
 **************************************************************************************************/

import { Kafka, EachMessagePayload } from 'kafkajs';
import { NatsConnection, connect as connectNats, StringCodec } from 'nats';
import { v4 as uuid } from 'uuid';

import { Logger } from './utils/logger';
import { Config } from './config';

/* ---------------------------------------------------------------------------------------------- */
/* Domain Types                                                                                    */
/* ---------------------------------------------------------------------------------------------- */

export interface SystemMetricEvent {
    clusterId: string;
    cpu: number;            // %
    memory: number;         // %
    rps: number;            // requests / sec
    timestamp: number;      // epoch millis
}

export interface SocialSignalEvent {
    clusterId: string;
    likes: number;
    comments: number;
    shares: number;
    activeUsers: number;
    timestamp: number;      // epoch millis
}

export interface EnrichedTelemetry {
    clusterId: string;
    // infra
    cpu: number;
    memory: number;
    rps: number;
    // social
    likes: number;
    comments: number;
    shares: number;
    activeUsers: number;
    // meta
    windowStart: number;
    windowEnd: number;
}

/* ------------------------------------------------------------------ */
/* Command                                                             */
/* ------------------------------------------------------------------ */
export interface ScaleClusterCommand {
    commandId: string;
    clusterId: string;
    desiredReplicas: number;
    reason: string;
    issuedAt: number;
}

/* ---------------------------------------------------------------------------------------------- */
/* Strategy Pattern                                                                                */
/* ---------------------------------------------------------------------------------------------- */

export interface ScalingStrategy {
    setNext(next: ScalingStrategy | null): void;
    evaluate(t: EnrichedTelemetry): ScaleClusterCommand | null;
}

/**
 * Base abstract strategy that wires up Chain-of-Responsibility plumbing.
 */
abstract class AbstractScalingStrategy implements ScalingStrategy {
    private next: ScalingStrategy | null = null;

    setNext(next: ScalingStrategy | null): void {
        this.next = next;
    }

    evaluate(t: EnrichedTelemetry): ScaleClusterCommand | null {
        const res = this.doEvaluate(t);
        if (res) return res;
        return this.next ? this.next.evaluate(t) : null;
    }

    /**
     * Implement in concrete strategy. Return NULL to delegate to next.
     */
    protected abstract doEvaluate(t: EnrichedTelemetry): ScaleClusterCommand | null;
}

/* --------------------------------------- */
/* Concrete Strategies                     */
/* --------------------------------------- */

/**
 * Always make sure we have at least MIN replicas when baseline load high.
 */
class BaselineLoadStrategy extends AbstractScalingStrategy {
    private readonly MIN_REPLICAS = Config.get<number>('scaling.baseline.minReplicas', 4);
    private readonly CPU_THRESHOLD = Config.get<number>('scaling.baseline.cpuThresholdPct', 70);

    protected doEvaluate(t: EnrichedTelemetry): ScaleClusterCommand | null {
        if (t.cpu > this.CPU_THRESHOLD) {
            const desired = Math.max(
                this.MIN_REPLICAS,
                Math.ceil((t.cpu / this.CPU_THRESHOLD) * this.MIN_REPLICAS)
            );
            return this.buildCommand(t.clusterId, desired, `CPU ${t.cpu}% > ${this.CPU_THRESHOLD}%`);
        }
        return null;
    }

    private buildCommand(clusterId: string, desiredReplicas: number, reason: string): ScaleClusterCommand {
        return {
            commandId: uuid(),
            clusterId,
            desiredReplicas,
            reason: `[BaselineLoad] ${reason}`,
            issuedAt: Date.now(),
        };
    }
}

/**
 * When social engagement bursts (relative delta), pre-scale proactively.
 */
class SocialBurstStrategy extends AbstractScalingStrategy {
    private readonly SOCIAL_DELTA_THRESHOLD = Config.get<number>('scaling.social.deltaThreshold', 1.5);
    private readonly MAX_REPLICAS = Config.get<number>('scaling.social.maxReplicas', 24);

    // naive state store of previous window by cluster
    private previousWindow: Map<string, EnrichedTelemetry> = new Map();

    protected doEvaluate(t: EnrichedTelemetry): ScaleClusterCommand | null {
        const prev = this.previousWindow.get(t.clusterId);
        this.previousWindow.set(t.clusterId, t);

        if (!prev) return null; // need baseline

        const prevEngagement = prev.likes + prev.comments + prev.shares;
        const currEngagement = t.likes + t.comments + t.shares;
        if (prevEngagement === 0) return null;

        const delta = currEngagement / prevEngagement;
        if (delta >= this.SOCIAL_DELTA_THRESHOLD) {
            const desired = Math.min(
                this.MAX_REPLICAS,
                Math.ceil(delta * Config.get<number>('scaling.baseline.minReplicas', 4))
            );
            return this.buildCommand(
                t.clusterId,
                desired,
                `Social engagement spike ${delta.toFixed(2)}×`
            );
        }
        return null;
    }

    private buildCommand(clusterId: string, desiredReplicas: number, reason: string): ScaleClusterCommand {
        return {
            commandId: uuid(),
            clusterId,
            desiredReplicas,
            reason: `[SocialBurst] ${reason}`,
            issuedAt: Date.now(),
        };
    }
}

/**
 * Fallback strategy that intentionally does nothing but avoid NPEs.
 */
class NoopStrategy extends AbstractScalingStrategy {
    protected doEvaluate(): ScaleClusterCommand | null {
        return null;
    }
}

/* ---------------------------------------------------------------------------------------------- */
/* Enricher – correlates infra + social events into single window                                 */
/* ---------------------------------------------------------------------------------------------- */

class TelemetryEnricher {
    private readonly WINDOW_MS = Config.get<number>('enricher.windowMs', 5000);

    // keyed by clusterId
    private infraBuffer: Map<string, SystemMetricEvent[]> = new Map();
    private socialBuffer: Map<string, SocialSignalEvent[]> = new Map();

    public ingestInfra(ev: SystemMetricEvent): void {
        this.pruneOldEvents(this.infraBuffer, ev.timestamp);
        this.pushEvent(this.infraBuffer, ev.clusterId, ev);
    }

    public ingestSocial(ev: SocialSignalEvent): void {
        this.pruneOldEvents(this.socialBuffer, ev.timestamp);
        this.pushEvent(this.socialBuffer, ev.clusterId, ev);
    }

    /**
     * Try to build an EnrichedTelemetry if both infra & social events exist
     * for the same cluster inside current sliding window.
     */
    public tryEnrich(clusterId: string): EnrichedTelemetry | null {
        const infraEvents = this.infraBuffer.get(clusterId);
        const socialEvents = this.socialBuffer.get(clusterId);
        if (!infraEvents?.length || !socialEvents?.length) return null;

        const windowStart = Date.now() - this.WINDOW_MS;
        const recentInfra = infraEvents.filter(e => e.timestamp >= windowStart);
        const recentSocial = socialEvents.filter(e => e.timestamp >= windowStart);

        if (!recentInfra.length || !recentSocial.length) return null;

        // Aggregate – simple mean
        const avg = <T extends { [k: string]: number }>(arr: T[], key: keyof T) =>
            arr.reduce((acc, curr) => acc + (curr[key] as number), 0) / arr.length;

        return {
            clusterId,
            cpu: avg(recentInfra, 'cpu'),
            memory: avg(recentInfra, 'memory'),
            rps: avg(recentInfra, 'rps'),
            likes: avg(recentSocial, 'likes'),
            comments: avg(recentSocial, 'comments'),
            shares: avg(recentSocial, 'shares'),
            activeUsers: avg(recentSocial, 'activeUsers'),
            windowStart,
            windowEnd: Date.now(),
        };
    }

    /* -------------------- helpers ----------------------- */

    private pushEvent<E extends { clusterId: string }>(
        buffer: Map<string, E[]>,
        clusterId: string,
        ev: E
    ) {
        if (!buffer.has(clusterId)) buffer.set(clusterId, []);
        buffer.get(clusterId)!.push(ev);
    }

    private pruneOldEvents<E extends { timestamp: number }>(
        buffer: Map<string, E[]>,
        now: number
    ) {
        const cutoff = now - this.WINDOW_MS;
        buffer.forEach((events, key) =>
            buffer.set(key, events.filter(e => e.timestamp >= cutoff))
        );
    }
}

/* ---------------------------------------------------------------------------------------------- */
/* AutoScaler Service                                                                              */
/* ---------------------------------------------------------------------------------------------- */

export class SocialAwareAutoScaler {
    private readonly kafka = new Kafka(Config.get('kafka'));
    private readonly natsUrl = Config.get<string>('nats.url');
    private natsConn?: NatsConnection;

    private readonly logger = Logger.child({ module: 'SocialAwareAutoScaler' });
    private readonly enricher = new TelemetryEnricher();

    private readonly SCALE_COMMAND_SUBJECT = 'orchestrator.commands';

    /* Strategy chain ends with NOOP to guarantee termination */
    private readonly strategyChain: ScalingStrategy = (() => {
        const baseline = new BaselineLoadStrategy();
        const social = new SocialBurstStrategy();
        baseline.setNext(social);
        social.setNext(new NoopStrategy());
        return baseline;
    })();

    /* ---------------------------- Public API ---------------------------- */

    public async start(): Promise<void> {
        await Promise.all([this.initKafkaConsumers(), this.initNatsProducer()]);
        this.logger.info('SocialAwareAutoScaler started.');
    }

    public async stop(): Promise<void> {
        await this.natsConn?.drain();
        this.logger.info('SocialAwareAutoScaler stopped.');
    }

    /* ---------------------------- Private ------------------------------- */

    private async initKafkaConsumers(): Promise<void> {
        const consumer = this.kafka.consumer({ groupId: 'social-aware-autoscaler' });
        await consumer.connect();
        await consumer.subscribe({ topic: 'system.metrics', fromBeginning: false });
        await consumer.subscribe({ topic: 'social.interactions', fromBeginning: false });

        await consumer.run({
            eachMessage: async (payload: EachMessagePayload) => {
                try {
                    await this.handleKafkaMessage(payload);
                } catch (err) {
                    this.logger.error(err, 'Failed to process Kafka message');
                }
            },
        });
    }

    private async initNatsProducer(): Promise<void> {
        this.natsConn = await connectNats({ servers: this.natsUrl });
        this.logger.info('Connected to NATS at %s', this.natsUrl);
    }

    private async handleKafkaMessage({ topic, message }: EachMessagePayload): Promise<void> {
        if (!message.value) return;
        const parsed = JSON.parse(message.value.toString());

        if (topic === 'system.metrics') {
            const ev = parsed as SystemMetricEvent;
            this.enricher.ingestInfra(ev);
            this.processIfReady(ev.clusterId);
        } else if (topic === 'social.interactions') {
            const ev = parsed as SocialSignalEvent;
            this.enricher.ingestSocial(ev);
            this.processIfReady(ev.clusterId);
        }
    }

    private processIfReady(clusterId: string): void {
        const enriched = this.enricher.tryEnrich(clusterId);
        if (!enriched) return;

        const decision = this.strategyChain.evaluate(enriched);
        if (decision) {
            this.publishScaleCommand(decision).catch(err =>
                this.logger.error(err, 'Failed to publish scale command')
            );
        }
    }

    private async publishScaleCommand(cmd: ScaleClusterCommand): Promise<void> {
        if (!this.natsConn) {
            this.logger.warn('NATS connection not ready; dropping command %s', cmd.commandId);
            return;
        }
        const sc = StringCodec();
        this.natsConn.publish(this.SCALE_COMMAND_SUBJECT, sc.encode(JSON.stringify(cmd)));
        this.logger.info({ cmd }, 'Published ScaleClusterCommand');
    }
}

/* ---------------------------------------------------------------------------------------------- */
/* Module bootstrap (executed only when run directly, not when imported)                          */
/* ---------------------------------------------------------------------------------------------- */

if (require.main === module) {
    (async () => {
        const scaler = new SocialAwareAutoScaler();
        process.on('SIGINT', async () => {
            await scaler.stop();
            process.exit(0);
        });
        process.on('SIGTERM', async () => {
            await scaler.stop();
            process.exit(0);
        });
        try {
            await scaler.start();
        } catch (err) {
            // eslint-disable-next-line no-console
            console.error(err);
            process.exit(1);
        }
    })();
}
```