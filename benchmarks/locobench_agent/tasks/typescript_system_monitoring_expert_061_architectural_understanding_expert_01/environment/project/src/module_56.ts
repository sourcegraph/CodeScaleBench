```typescript
/**
 * File: src/module_56.ts
 *
 * Adaptive Capacity Orchestrator for PulseSphere SocialOps.
 * ---------------------------------------------------------
 * This module listens for enriched “social-context” signals,
 * correlates them with infrastructure-level metrics and, through
 * a Strategy + Chain-of-Responsibility pipeline, decides whether
 * to scale a Kubernetes workload.
 *
 * Design patterns & architectural choices
 * ---------------------------------------
 * • Chain-of-Responsibility :  SignalFilter ➔ OutlierFilter ➔ NoiseFilter …
 * • Strategy                :  ScalingStrategy (burst-aware, cost-optimised)
 * • Command                 :  ScaleCommand (execute / undo for future audit)
 *
 * Notes
 * -----
 * • Network boundary calls (Kubernetes API) are wrapped in a small
 *   retry-with-back-off helper for resilience.
 * • No hard dependency on a particular message bus – any EventEmitter-like
 *   source that emits `socialSignal` & `metricSample` events will do.
 */

import axios, { AxiosInstance, AxiosError } from 'axios';
import EventEmitter from 'events';
import { v4 as uuid } from 'uuid';

/* -------------------------------------------------------------------------- */
/*                                Infrastructure                              */
/* -------------------------------------------------------------------------- */

/**
 * Minimal, console-based logger. In production we forward to Winston/Pino.
 */
class Logger {
  constructor(private readonly scope: string) {}

  debug(msg: string, meta?: Record<string, unknown>): void {
    // eslint-disable-next-line no-console
    console.debug(`[DEBUG] [${this.scope}] ${msg}`, meta ?? '');
  }

  info(msg: string, meta?: Record<string, unknown>): void {
    // eslint-disable-next-line no-console
    console.info(`[INFO ] [${this.scope}] ${msg}`, meta ?? '');
  }

  warn(msg: string, meta?: Record<string, unknown>): void {
    // eslint-disable-next-line no-console
    console.warn(`[WARN ] [${this.scope}] ${msg}`, meta ?? '');
  }

  error(msg: string, meta?: Record<string, unknown>): void {
    // eslint-disable-next-line no-console
    console.error(`[ERROR] [${this.scope}] ${msg}`, meta ?? '');
  }
}

/* -------------------------------------------------------------------------- */
/*                                   Types                                    */
/* -------------------------------------------------------------------------- */

enum SocialActionType {
  LIKE = 'LIKE',
  COMMENT = 'COMMENT',
  SHARE = 'SHARE',
  STREAM_JOIN = 'STREAM_JOIN',
}

interface SocialSignal {
  readonly id: string; // unique per signal
  readonly userId: string;
  readonly action: SocialActionType;
  readonly weight: number; // Pre-computed weight (0…1)
  readonly timestamp: number; // epoch ms
}

interface MetricSample {
  readonly cpu: number; // %
  readonly memory: number; // %
  readonly timestamp: number;
}

interface ClusterState {
  readonly replicas: number;
  readonly avgCpu: number; // %
  readonly avgMemory: number; // %
}

interface ScaleCommand {
  execute(): Promise<void>;
  undo(): Promise<void>;
}

/* -------------------------------------------------------------------------- */
/*                          Chain-of-Responsibility                            */
/* -------------------------------------------------------------------------- */

/**
 * Filtering pipeline for incoming social signals.
 */
interface SignalFilter {
  setNext(filter: SignalFilter): SignalFilter;
  handle(signal: SocialSignal): SocialSignal | null;
}

/**
 * Base class implementing linkage logic.
 */
abstract class AbstractSignalFilter implements SignalFilter {
  private next: SignalFilter | null = null;

  setNext(filter: SignalFilter): SignalFilter {
    this.next = filter;
    return filter;
  }

  handle(signal: SocialSignal): SocialSignal | null {
    const processed = this.process(signal);
    if (!processed) return null;
    return this.next ? this.next.handle(processed) : processed;
  }

  protected abstract process(signal: SocialSignal): SocialSignal | null;
}

/**
 * Filters out signals with weight below a threshold.
 */
class LowWeightFilter extends AbstractSignalFilter {
  constructor(private readonly minWeight: number, private readonly logger: Logger) {
    super();
  }

  protected process(signal: SocialSignal): SocialSignal | null {
    if (signal.weight < this.minWeight) {
      this.logger.debug('Signal dropped – weight below threshold', { id: signal.id, weight: signal.weight });
      return null;
    }
    return signal;
  }
}

/**
 * Removes time-series outliers using Z-score (rudimentary, demo purposes).
 */
class OutlierFilter extends AbstractSignalFilter {
  private readonly history: number[] = [];
  private static readonly MAX_HISTORY = 50;

  constructor(private readonly zThreshold: number, private readonly logger: Logger) {
    super();
  }

  protected process(signal: SocialSignal): SocialSignal | null {
    if (this.history.length >= OutlierFilter.MAX_HISTORY) {
      this.history.shift();
    }
    this.history.push(signal.weight);

    const mean = this.history.reduce((a, b) => a + b, 0) / this.history.length;
    const std = Math.sqrt(this.history.map(x => Math.pow(x - mean, 2)).reduce((a, b) => a + b, 0) / this.history.length);

    const zScore = std === 0 ? 0 : (signal.weight - mean) / std;

    if (Math.abs(zScore) > this.zThreshold) {
      this.logger.debug('Signal dropped – outlier detected', { id: signal.id, zScore });
      return null;
    }

    return signal;
  }
}

/* -------------------------------------------------------------------------- */
/*                               Strategy Pattern                             */
/* -------------------------------------------------------------------------- */

enum ScalingStrategyKind {
  BURST_AWARE = 'BURST_AWARE',
  COST_OPTIMISED = 'COST_OPTIMISED',
}

interface ScalingStrategy {
  /**
   * Decide how many replicas we should target.
   * Return the same replica count to skip scaling.
   */
  computeDesiredReplicas(state: ClusterState, socialScore: number): number;
}

class BurstAwareScalingStrategy implements ScalingStrategy {
  private static readonly MAX_REPLICAS = 500;

  constructor(private readonly maxCpu: number /* % */, private readonly logger: Logger) {}

  computeDesiredReplicas(state: ClusterState, socialScore: number): number {
    // Aggressive: linear multiplier on social score
    const headroom = this.maxCpu - state.avgCpu;
    const urgency = socialScore * 10; // scale social influence

    let desired = state.replicas;

    if (headroom < 15 /* % */ || urgency > 5) {
      desired = Math.min(state.replicas + Math.ceil(urgency), BurstAwareScalingStrategy.MAX_REPLICAS);
      this.logger.info('Burst strategy recommends scale-up', { desired, headroom, urgency });
    } else if (state.avgCpu < 30 && urgency < 2) {
      desired = Math.max(1, Math.floor(state.replicas / 2));
      this.logger.info('Burst strategy recommends partial scale-down', { desired });
    }

    return desired;
  }
}

class CostOptimisedScalingStrategy implements ScalingStrategy {
  private static readonly MIN_REPLICAS = 2;
  private static readonly MAX_REPLICAS = 200;

  constructor(private readonly logger: Logger) {}

  computeDesiredReplicas(state: ClusterState, socialScore: number): number {
    // Conservative: step scaling
    let desired = state.replicas;

    if (state.avgCpu > 80 || socialScore > 8) {
      desired = Math.min(state.replicas + 2, CostOptimisedScalingStrategy.MAX_REPLICAS);
      this.logger.info('Cost strategy recommends small scale-up', { desired });
    } else if (state.avgCpu < 40 && socialScore < 3 && state.replicas > CostOptimisedScalingStrategy.MIN_REPLICAS) {
      desired = Math.max(CostOptimisedScalingStrategy.MIN_REPLICAS, state.replicas - 1);
      this.logger.info('Cost strategy recommends scale-down', { desired });
    }

    return desired;
  }
}

/**
 * Simple factory to pick strategy based on enum or ENV.
 */
class ScalingStrategyFactory {
  static create(kind: ScalingStrategyKind, logger: Logger): ScalingStrategy {
    switch (kind) {
      case ScalingStrategyKind.BURST_AWARE:
        return new BurstAwareScalingStrategy(90 /* cap */, logger);
      case ScalingStrategyKind.COST_OPTIMISED:
      default:
        return new CostOptimisedScalingStrategy(logger);
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                               Command Pattern                              */
/* -------------------------------------------------------------------------- */

/**
 * Encapsulates a single scaling action. In a full implementation we’d persist
 * commands to an event store for audit/rollback capabilities.
 */
class KubernetesScaleCommand implements ScaleCommand {
  constructor(
    private readonly axios: AxiosInstance,
    private readonly namespace: string,
    private readonly deployment: string,
    private readonly desiredReplicas: number,
    private readonly logger: Logger,
  ) {}

  async execute(): Promise<void> {
    try {
      await this.patchReplicas(this.desiredReplicas);
      this.logger.info('Scale command executed', { desiredReplicas: this.desiredReplicas });
    } catch (err) {
      this.logger.error('Failed to execute scale command', { err });
      throw err;
    }
  }

  async undo(): Promise<void> {
    try {
      // For demo, we simply scale back to 1 replica
      await this.patchReplicas(1);
      this.logger.warn('Scale command rolled back to 1 replica');
    } catch (err) {
      this.logger.error('Failed to rollback scale command', { err });
      throw err;
    }
  }

  /* ------------------------------ helpers --------------------------------- */

  private async patchReplicas(replicas: number): Promise<void> {
    const body = {
      spec: { replicas },
    };

    const url = `/apis/apps/v1/namespaces/${this.namespace}/deployments/${this.deployment}`;
    await retryAsync(() => this.axios.patch(url, body, { headers: { 'Content-Type': 'application/merge-patch+json' } }), 3, 500);
  }
}

/* -------------------------------------------------------------------------- */
/*                                 Orchestrator                               */
/* -------------------------------------------------------------------------- */

interface OrchestratorConfig {
  readonly namespace: string;
  readonly deployment: string;
  readonly strategy: ScalingStrategyKind;
  readonly minSignalWeight: number;
  readonly zScoreThreshold: number;
  readonly kubernetesApi: string;
  readonly token?: string;
}

class AdaptiveCapacityOrchestrator {
  private readonly logger = new Logger(AdaptiveCapacityOrchestrator.name);
  private readonly signalFilterPipeline: SignalFilter;
  private readonly strategy: ScalingStrategy;
  private readonly axios: AxiosInstance;

  private socialScore = 0; // moving average of weighted signals
  private readonly scoreHistory: number[] = [];

  constructor(private readonly sourceBus: EventEmitter, private readonly cfg: OrchestratorConfig) {
    /* -------------------- Filters -------------------- */
    this.signalFilterPipeline = new LowWeightFilter(cfg.minSignalWeight, this.logger).setNext(
      new OutlierFilter(cfg.zScoreThreshold, this.logger),
    );

    /* -------------------- Strategy ------------------- */
    this.strategy = ScalingStrategyFactory.create(cfg.strategy, this.logger);

    /* ------------------- Axios kube ------------------ */
    this.axios = axios.create({
      baseURL: cfg.kubernetesApi,
      headers: { Authorization: cfg.token ? `Bearer ${cfg.token}` : undefined },
      // In production we’d use proper TLS config.
      httpsAgent: /* eslint-disable @typescript-eslint/no-var-requires */ new (require('https').Agent)({ rejectUnauthorized: false }),
    });
  }

  start(): void {
    this.logger.info('Adaptive orchestrator starting…');

    this.sourceBus.on('socialSignal', (raw: SocialSignal) => this.onSocialSignal(raw));
    this.sourceBus.on('metricSample', (metric: MetricSample) => this.onMetricSample(metric));
  }

  /* ------------------------------ Event Handlers --------------------------- */

  private onSocialSignal(raw: SocialSignal): void {
    /* add id if missing */
    const signal: SocialSignal = { ...raw, id: raw.id ?? uuid() };

    const filtered = this.signalFilterPipeline.handle(signal);
    if (!filtered) return;

    // Update moving average score (simple / naive)
    this.socialScore = this.calculateMovingAverage(filtered.weight);

    this.logger.debug('Social score updated', { socialScore: this.socialScore });
  }

  private onMetricSample(metric: MetricSample): void {
    /* In a real system we would fetch state from Kubernetes metrics-server */
    const state: ClusterState = {
      replicas: metric.cpu > 0 ? Math.ceil(metric.cpu / 10) : 1, // placeholder mapping
      avgCpu: metric.cpu,
      avgMemory: metric.memory,
    };

    const desiredReplicas = this.strategy.computeDesiredReplicas(state, this.socialScore);

    if (desiredReplicas !== state.replicas) {
      const cmd = new KubernetesScaleCommand(
        this.axios,
        this.cfg.namespace,
        this.cfg.deployment,
        desiredReplicas,
        this.logger,
      );

      cmd
        .execute()
        .catch(async err => {
          this.logger.error('Scaling failed; attempting rollback', { err });
          try {
            await cmd.undo();
          } catch (rollbackErr) {
            this.logger.error('Rollback failed', { rollbackErr });
          }
        })
        .finally(() => {
          // Reset score history to avoid thrashing
          this.scoreHistory.length = 0;
          this.socialScore = 0;
        });
    }
  }

  /* ------------------------------ helpers ---------------------------------- */

  private calculateMovingAverage(newValue: number, window = 20): number {
    if (this.scoreHistory.length >= window) {
      this.scoreHistory.shift();
    }
    this.scoreHistory.push(newValue);

    const avg = this.scoreHistory.reduce((a, b) => a + b, 0) / this.scoreHistory.length;
    return Number(avg.toFixed(2));
  }
}

/* -------------------------------------------------------------------------- */
/*                          Utility – Retry helper                            */
/* -------------------------------------------------------------------------- */

/**
 * Generic async retry with exponential back-off.
 */
async function retryAsync<T>(
  fn: () => Promise<T>,
  retries = 3,
  initialDelayMs = 250,
  factor = 2,
): Promise<T> {
  let attempt = 0;
  let delay = initialDelayMs;

  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      return await fn();
    } catch (err) {
      const axiosErr = err as AxiosError;
      const retriable =
        axiosErr.code === 'ECONNABORTED' ||
        axiosErr.code === 'ENETUNREACH' ||
        (axiosErr.response && axiosErr.response.status >= 500);

      if (!retriable || attempt >= retries) {
        throw err;
      }

      await new Promise(res => setTimeout(res, delay));
      attempt += 1;
      delay *= factor;
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                              Module Exports                                */
/* -------------------------------------------------------------------------- */

export {
  SocialSignal,
  MetricSample,
  AdaptiveCapacityOrchestrator,
  OrchestratorConfig,
  ScalingStrategyKind,
};
```