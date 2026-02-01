```typescript
/**************************************************************************************************
 *  File:          src/module_45.ts
 *  Project:       PulseSphere SocialOps – System Monitoring
 *  Description:   AdaptiveCapacityPlanner is a micro-component that continuously correlates
 *                 infrastructure metrics with real-time social interaction signals in order to
 *                 produce proactive scaling commands. The planner marries the
 *                 Chain-of-Responsibility and Strategy patterns so that new heuristics can be
 *                 introduced at runtime without impacting existing logic.
 *
 *  NOTE: This module purposefully contains no I/O side-effects outside of the injected
 *        collaborators (Kafka consumer / Orchestration client / Logger). This makes the unit
 *        easily testable and mockable.
 *************************************************************************************************/

import { Kafka, Consumer, EachMessagePayload } from 'kafkajs';
import axios, { AxiosInstance } from 'axios';
import winston, { Logger } from 'winston';

/* -------------------------------------------------------------------------- */
/*                                  Typings                                   */
/* -------------------------------------------------------------------------- */

/**
 * Raw infrastructure metric pushed by telemetry pipeline.
 */
interface InfraMetric {
  clusterId: string;
  timestamp: number; // epoch millis
  cpuUtilization: number; // 0..1
  memoryUtilization: number; // 0..1
}

/**
 * Social signal enriched by PulseSphere social-aware collectors.
 */
interface SocialSignal {
  clusterId: string;
  timestamp: number; // epoch millis
  likeRate: number; // likes/sec
  commentRate: number; // comments/sec
  shareRate: number; // shares/sec
  liveViewers?: number; // present only for live-stream
  influencerHandle?: string; // if part of an influencer event
}

/**
 * Domain object passed down the evaluation pipeline.
 */
interface EvaluationSnapshot {
  clusterId: string;
  windowStart: number;
  windowEnd: number;
  avgCpu: number;
  avgMem: number;
  likeRate: number;
  commentRate: number;
  shareRate: number;
  liveViewers: number;
  influencerDetected: boolean;
}

/**
 * Command sent to the orchestration service.
 */
interface ScalingDecision {
  clusterId: string;
  desiredReplicas: number;
  reason: string;
}

/* -------------------------------------------------------------------------- */
/*                             Strategy / CoR types                           */
/* -------------------------------------------------------------------------- */

interface ScalingStrategy {
  setNext(next: ScalingStrategy): ScalingStrategy;
  evaluate(snapshot: EvaluationSnapshot): ScalingDecision | undefined;
}

/* -------------------------------------------------------------------------- */
/*                              Helper utilities                              */
/* -------------------------------------------------------------------------- */

const calculateMean = (values: number[]): number =>
  values.length === 0 ? 0 : values.reduce((acc, cur) => acc + cur, 0) / values.length;

const withinTimeWindow =
  (from: number, to: number) =>
  <T extends { timestamp: number }>(item: T): boolean =>
    item.timestamp >= from && item.timestamp <= to;

const sleep = (ms: number): Promise<void> => new Promise((res) => setTimeout(res, ms));

/* -------------------------------------------------------------------------- */
/*                          Concrete Strategy objects                         */
/* -------------------------------------------------------------------------- */

/**
 * Handles capacity planning for extreme viral spikes driven by influencers.
 * Highest precedence in the chain.
 */
class InfluencerSurgeStrategy implements ScalingStrategy {
  private next?: ScalingStrategy;
  private static readonly INFLUENCER_VIEWERS_THRESHOLD = 20_000;

  setNext(next: ScalingStrategy): ScalingStrategy {
    this.next = next;
    return next;
  }

  evaluate(snapshot: EvaluationSnapshot): ScalingDecision | undefined {
    if (snapshot.influencerDetected && snapshot.liveViewers >= InfluencerSurgeStrategy.INFLUENCER_VIEWERS_THRESHOLD) {
      const multiplier = Math.ceil(snapshot.liveViewers / InfluencerSurgeStrategy.INFLUENCER_VIEWERS_THRESHOLD);
      return {
        clusterId: snapshot.clusterId,
        desiredReplicas: multiplier * 10, // aggressive scaling
        reason: `Influencer surge detected (${snapshot.liveViewers} viewers)`
      };
    }

    return this.next?.evaluate(snapshot);
  }
}

/**
 * Handles capacity planning for generic trending spikes (hashtags etc.).
 */
class TrendingSpikeStrategy implements ScalingStrategy {
  private next?: ScalingStrategy;
  private static readonly SOCIAL_RATE_THRESHOLD = 5_000;
  private static readonly CPU_HEADROOM = 0.70;

  setNext(next: ScalingStrategy): ScalingStrategy {
    this.next = next;
    return next;
  }

  evaluate(snapshot: EvaluationSnapshot): ScalingDecision | undefined {
    const socialRate =
      snapshot.likeRate + snapshot.commentRate + snapshot.shareRate;

    if (socialRate >= TrendingSpikeStrategy.SOCIAL_RATE_THRESHOLD || snapshot.avgCpu >= TrendingSpikeStrategy.CPU_HEADROOM) {
      const socialMultiplier = Math.ceil(socialRate / TrendingSpikeStrategy.SOCIAL_RATE_THRESHOLD);
      const cpuMultiplier = Math.ceil(snapshot.avgCpu / TrendingSpikeStrategy.CPU_HEADROOM);
      const desiredReplicas = Math.max(2 * socialMultiplier, 2 * cpuMultiplier);

      return {
        clusterId: snapshot.clusterId,
        desiredReplicas,
        reason: `Trending spike: socialRate=${socialRate.toFixed(
          0
        )}/s, cpu=${(snapshot.avgCpu * 100).toFixed(1)}%`
      };
    }

    return this.next?.evaluate(snapshot);
  }
}

/**
 * Baseline strategy: ensures replication count is commensurate to steady-state load.
 */
class BaselineStrategy implements ScalingStrategy {
  private next?: ScalingStrategy; // no further handlers but kept for completeness
  private static readonly TARGET_CPU = 0.5;
  private static readonly MIN_REPLICAS = 3;

  setNext(next: ScalingStrategy): ScalingStrategy {
    this.next = next;
    return next;
  }

  evaluate(snapshot: EvaluationSnapshot): ScalingDecision | undefined {
    const desiredReplicas = Math.max(
      BaselineStrategy.MIN_REPLICAS,
      Math.ceil(snapshot.avgCpu / BaselineStrategy.TARGET_CPU)
    );

    return {
      clusterId: snapshot.clusterId,
      desiredReplicas,
      reason: `Baseline adjustment (cpu=${(snapshot.avgCpu * 100).toFixed(1)}%)`
    };
  }
}

/* -------------------------------------------------------------------------- */
/*                         Orchestration client facade                        */
/* -------------------------------------------------------------------------- */

class OrchestrationClient {
  private readonly http: AxiosInstance;
  constructor(baseURL: string) {
    this.http = axios.create({
      baseURL,
      timeout: 3_000
    });
  }

  async sendScalingCommand(cmd: ScalingDecision): Promise<void> {
    try {
      await this.http.post('/v1/scale', cmd);
    } catch (err) {
      throw new Error(
        `Failed to send scaling command to orchestrator: ${(err as Error).message}`
      );
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                           Adaptive Planner class                           */
/* -------------------------------------------------------------------------- */

export class AdaptiveCapacityPlanner {
  private readonly kafkaConsumer: Consumer;
  private readonly logger: Logger;
  private readonly orchestrationClient: OrchestrationClient;

  /* Sliding-window buffers (sorted by insertion order). */
  private readonly infraBuffer: InfraMetric[] = [];
  private readonly socialBuffer: SocialSignal[] = [];

  /* Configurable time window (ms). */
  private readonly windowSize = 5 * 60 * 1_000; // 5 minutes

  /* Planner evaluation cadence. */
  private readonly evaluationInterval = 30 * 1_000; // 30 seconds

  /* Chain root. */
  private readonly rootStrategy: ScalingStrategy;

  private running = false;

  constructor(
    kafka: Kafka,
    orchestrationClient: OrchestrationClient,
    logger?: Logger
  ) {
    this.kafkaConsumer = kafka.consumer({ groupId: 'adaptive-capacity-planner' });
    this.logger =
      logger ??
      winston.createLogger({
        level: 'info',
        format: winston.format.combine(
          winston.format.timestamp(),
          winston.format.json()
        ),
        transports: [new winston.transports.Console()]
      });
    this.orchestrationClient = orchestrationClient;

    /* Wire strategy chain. */
    const influencer = new InfluencerSurgeStrategy();
    const trending = new TrendingSpikeStrategy();
    const baseline = new BaselineStrategy();
    influencer.setNext(trending).setNext(baseline);
    this.rootStrategy = influencer;
  }

  /******************************* Public API ********************************/

  /**
   * Starts consuming Kafka streams and launches evaluation loop.
   */
  async start(): Promise<void> {
    if (this.running) return;

    await this.kafkaConsumer.connect();
    await this.kafkaConsumer.subscribe({ topic: 'infra.metrics', fromBeginning: false });
    await this.kafkaConsumer.subscribe({ topic: 'social.signals', fromBeginning: false });

    this.kafkaConsumer.run({
      eachMessage: async (payload) => this.handleMessage(payload)
    });

    this.running = true;
    void this.evaluationLoop(); // fire-and-forget
    this.logger.info('AdaptiveCapacityPlanner started.');
  }

  /**
   * Stops the planner gracefully.
   */
  async stop(): Promise<void> {
    this.running = false;
    await this.kafkaConsumer.disconnect();
    this.logger.info('AdaptiveCapacityPlanner stopped.');
  }

  /******************************* Kafka handler ******************************/

  private async handleMessage({ topic, message }: EachMessagePayload): Promise<void> {
    try {
      if (!message.value) return; // guard: empty payload
      const parsed = JSON.parse(message.value.toString());

      if (topic === 'infra.metrics') {
        this.ingestInfraMetric(parsed as InfraMetric);
      } else if (topic === 'social.signals') {
        this.ingestSocialSignal(parsed as SocialSignal);
      }
    } catch (err) {
      this.logger.warn(`Failed to process Kafka message: ${(err as Error).message}`, {
        topic,
        message
      });
    }
  }

  private ingestInfraMetric(metric: InfraMetric): void {
    this.infraBuffer.push(metric);
    this.trimBuffer(this.infraBuffer);
  }

  private ingestSocialSignal(signal: SocialSignal): void {
    this.socialBuffer.push(signal);
    this.trimBuffer(this.socialBuffer);
  }

  /* Removes elements older than window size */
  private trimBuffer<T extends { timestamp: number }>(buffer: T[]): void {
    const threshold = Date.now() - this.windowSize;
    while (buffer.length && buffer[0].timestamp < threshold) buffer.shift();
  }

  /******************************* Evaluation loop ****************************/

  private async evaluationLoop(): Promise<void> {
    while (this.running) {
      const evaluationStart = Date.now();
      try {
        await this.evaluateAndAct();
      } catch (err) {
        this.logger.error(
          `Evaluation cycle failed: ${(err as Error).message}`,
          err as Error
        );
      } finally {
        const timeSpent = Date.now() - evaluationStart;
        await sleep(Math.max(this.evaluationInterval - timeSpent, 0));
      }
    }
  }

  /**
   * Aggregates the most recent window for each clusterId, evaluates the root
   * strategy and sends scaling commands if required.
   */
  private async evaluateAndAct(): Promise<void> {
    const windowEnd = Date.now();
    const windowStart = windowEnd - this.windowSize;

    /* Group infra metrics by clusterId */
    const infraByCluster = new Map<string, InfraMetric[]>();
    for (const metric of this.infraBuffer.filter(withinTimeWindow(windowStart, windowEnd))) {
      if (!infraByCluster.has(metric.clusterId)) infraByCluster.set(metric.clusterId, []);
      infraByCluster.get(metric.clusterId)!.push(metric);
    }

    /* Group social signals by clusterId */
    const socialByCluster = new Map<string, SocialSignal[]>();
    for (const signal of this.socialBuffer.filter(withinTimeWindow(windowStart, windowEnd))) {
      if (!socialByCluster.has(signal.clusterId)) socialByCluster.set(signal.clusterId, []);
      socialByCluster.get(signal.clusterId)!.push(signal);
    }

    /* Evaluate each cluster independently */
    for (const [clusterId, infraMetrics] of infraByCluster.entries()) {
      const socialSignals = socialByCluster.get(clusterId) ?? [];

      if (infraMetrics.length === 0) continue; // nothing to evaluate

      const snapshot: EvaluationSnapshot = {
        clusterId,
        windowStart,
        windowEnd,
        avgCpu: calculateMean(infraMetrics.map((m) => m.cpuUtilization)),
        avgMem: calculateMean(infraMetrics.map((m) => m.memoryUtilization)),
        likeRate: calculateMean(socialSignals.map((s) => s.likeRate)),
        commentRate: calculateMean(socialSignals.map((s) => s.commentRate)),
        shareRate: calculateMean(socialSignals.map((s) => s.shareRate)),
        liveViewers: calculateMean(
          socialSignals
            .filter((s) => typeof s.liveViewers === 'number')
            .map((s) => s.liveViewers as number)
        ),
        influencerDetected: socialSignals.some((s) => Boolean(s.influencerHandle))
      };

      const decision = this.rootStrategy.evaluate(snapshot);

      if (decision) {
        await this.dispatchDecision(decision);
      }
    }
  }

  private async dispatchDecision(decision: ScalingDecision): Promise<void> {
    try {
      await this.orchestrationClient.sendScalingCommand(decision);
      this.logger.info('Scaling command dispatched', decision);
    } catch (err) {
      this.logger.error(
        `Failed to dispatch scaling command: ${(err as Error).message}`,
        decision
      );
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                       Factory helper for dependency-injection             */
/* -------------------------------------------------------------------------- */

export async function createAndStartPlanner(): Promise<AdaptiveCapacityPlanner> {
  const kafka = new Kafka({
    clientId: 'pulse-sphere-capacity-planner',
    brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092']
  });

  const orchestratorBaseUrl =
    process.env.ORCH_BASE_URL ?? 'http://localhost:8080/orchestrator';

  const planner = new AdaptiveCapacityPlanner(
    kafka,
    new OrchestrationClient(orchestratorBaseUrl)
  );
  await planner.start();
  return planner;
}

/**************************************************************************************************
 *  EOF
 *************************************************************************************************/
```