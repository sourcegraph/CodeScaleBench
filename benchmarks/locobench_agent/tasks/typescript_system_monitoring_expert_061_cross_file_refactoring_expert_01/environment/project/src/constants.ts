```typescript
/**
 *  constants.ts
 *  ==========================================================================
 *  Canonical, platform-wide constants shared by every micro-service in the
 *  PulseSphere SocialOps stack.
 *
 *  ❗  DO NOT store secrets here. Use Vault / Kubernetes Secrets instead.
 */

import ms from 'ms';
import { z } from 'zod';
import { version as pulseSphereVersion } from '../package.json';

/* -------------------------------------------------------------------------- */
/*                                 Enums                                      */
/* -------------------------------------------------------------------------- */

/**
 * NODE_ENV values understood by the platform.
 */
export enum NodeEnvironment {
  Development = 'development',
  Test = 'test',
  Staging = 'staging',
  Production = 'production',
}

/**
 * Canonical micro-service names—used for discovery, observability labels,
 * traffic shadowing and RBAC scopes.
 */
export enum ServiceName {
  API_GATEWAY = 'api-gateway',
  TELEMETRY_INGESTOR = 'telemetry-ingestor',
  SIGNAL_ENRICHER = 'signal-enricher',
  ANOMALY_DETECTOR = 'anomaly-detector',
  CAPACITY_ORCHESTRATOR = 'capacity-orchestrator',
  ALERT_DISPATCHER = 'alert-dispatcher',
  CONFIGURATION_SERVICE = 'configuration-service',
  BACKUP_SERVICE = 'backup-service',
  AUTH_SERVICE = 'auth-service',
}

/**
 * Kafka topic catalogue (append-only; renames are BREAKING).
 */
export enum KafkaTopic {
  RAW_TELEMETRY = 'telemetry.raw.v1',
  ENRICHED_TELEMETRY = 'telemetry.enriched.v1',
  ANOMALY_EVENT = 'anomaly.event.v1',
  ORCHESTRATION_COMMAND = 'orchestration.command.v1',
  USER_SIGNAL = 'user-signal.v1',
  AUDIT_LOG = 'audit.log.v1',
}

/**
 * Feature flag keys toggled via the configuration service.
 */
export enum FeatureFlag {
  ENABLE_REALTIME_TREND_PREDICTION = 'enable_realtime_trend_prediction',
  USE_LATEST_ANOMALY_MODEL = 'use_latest_anomaly_model',
  FAIL_OPEN_ON_RATE_LIMITER = 'fail_open_on_rate_limiter',
  ENABLE_EXPERIMENTAL_UI = 'enable_experimental_ui',
}

/* -------------------------------------------------------------------------- */
/*                          Environment Variable Helpers                      */
/* -------------------------------------------------------------------------- */

/**
 * Retrieve and validate environment variables via zod schema.
 */
function env<T extends z.ZodTypeAny>(
  key: string,
  schema: T,
  fallback?: z.infer<T>,
): z.infer<T> {
  const raw = process.env[key];

  if ((raw === undefined || raw === '') && fallback !== undefined) {
    return fallback;
  }

  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    // eslint-disable-next-line no-console
    console.error(
      `❌  Environment variable ${key} is missing or invalid. ${parsed.error.message}`,
    );
    process.exit(1);
  }

  return parsed.data;
}

/* -------------------------------------------------------------------------- */
/*                               Core Constants                               */
/* -------------------------------------------------------------------------- */

/**
 * Semantic version from package.json
 */
export const APP_VERSION = pulseSphereVersion;

/**
 * Parsed runtime environment.
 */
export const RUNTIME_ENV: NodeEnvironment = env(
  'NODE_ENV',
  z.nativeEnum(NodeEnvironment),
  NodeEnvironment.Development,
);

/**
 * Start service in read-only mode (no mutating operations).
 */
export const READ_ONLY_MODE: boolean = env(
  'READ_ONLY_MODE',
  z
    .string()
    .regex(/^(true|false)$/i)
    .transform(val => val.toLowerCase() === 'true'),
  false,
);

/**
 * Default retry/back-off policy for outbound calls.
 */
export const DEFAULT_RETRY_STRATEGY = {
  maxRetries: env('DEFAULT_MAX_RETRIES', z.coerce.number().int().min(0).max(10), 5),
  initialDelayMs: env('DEFAULT_INITIAL_RETRY_DELAY', z.string(), '500ms'),
  backoffMultiplier: env('DEFAULT_RETRY_MULTIPLIER', z.coerce.number().min(1).max(10), 2),
} as const;

/**
 * Same as above but with parsed delay number.
 */
export const DEFAULT_RETRY_STRATEGY_MS = {
  ...DEFAULT_RETRY_STRATEGY,
  initialDelayMs: ms(DEFAULT_RETRY_STRATEGY.initialDelayMs),
};

/**
 * Istio / Consul side-car ports.
 */
export const SIDECAR_PORTS = {
  HTTP: 15020,
  GRPC: 15021,
  METRICS: 15090,
} as const;

/**
 * Labels automatically attached to all logs, metrics and traces.
 */
export const BASE_OBSERVABILITY_LABELS = {
  service: process.env.SERVICE_NAME ?? 'unknown',
  version: APP_VERSION,
  hostname: process.env.HOSTNAME ?? 'unknown',
} as const;

/* -------------------------------------------------------------------------- */
/*                             Social Signal Types                            */
/* -------------------------------------------------------------------------- */

export const SOCIAL_SIGNAL_TYPES = [
  'like',
  'comment',
  'share',
  'follow',
  'hashtag-trend',
  'live-stream-start',
  'live-stream-end',
  'reaction',
  'mention',
] as const;

export type SocialSignalType = (typeof SOCIAL_SIGNAL_TYPES)[number];

/* -------------------------------------------------------------------------- */
/*                         Platform SLO / Timeouts                            */
/* -------------------------------------------------------------------------- */

export const SLO = {
  apiRequest: ms('250ms'),
  kafkaRoundTrip: ms('500ms'),
  traceEndToEnd: ms('3s'),
  configPropagation: ms('2s'),
} as const;

/* -------------------------------------------------------------------------- */
/*                           Graceful Shutdown                                */
/* -------------------------------------------------------------------------- */

export const SHUTDOWN_SIGNALS = ['SIGINT', 'SIGTERM', 'SIGQUIT'] as const;
export type ShutdownSignal = (typeof SHUTDOWN_SIGNALS)[number];

export const SHUTDOWN_TIMEOUT_MS = ms(
  env('SHUTDOWN_TIMEOUT', z.string(), '15s'),
);

/* -------------------------------------------------------------------------- */
/*                              Helper Types                                  */
/* -------------------------------------------------------------------------- */

export interface RetryPolicy {
  readonly maxRetries: number;
  readonly initialDelayMs: number;
  readonly backoffMultiplier: number;
}

/**
 * Frozen configuration tree usable by DI containers.
 */
export const CONFIG = Object.freeze({
  env: RUNTIME_ENV,
  featureFlags: FeatureFlag,
  kafkaTopics: KafkaTopic,
  service: {
    name: process.env.SERVICE_NAME as ServiceName | undefined,
    ports: SIDECAR_PORTS,
  },
  retry: DEFAULT_RETRY_STRATEGY_MS,
  slo: SLO,
  shutdown: {
    signals: SHUTDOWN_SIGNALS,
    timeoutMs: SHUTDOWN_TIMEOUT_MS,
  },
  appVersion: APP_VERSION,
});

/**
 * Validate SERVICE_NAME early in the bootstrap process.
 */
(function verifyServiceName(): void {
  const raw = process.env.SERVICE_NAME;
  if (!raw) {
    console.warn(
      '⚠️  SERVICE_NAME env var not set; observability data will lack precision.',
    );
    return;
  }
  if (!(Object.values(ServiceName) as string[]).includes(raw)) {
    console.error(`❌  Unknown SERVICE_NAME '${raw}'.`);
    process.exit(1);
  }
})();

/* -------------------------------------------------------------------------- */
/*                             Type Guards                                    */
/* -------------------------------------------------------------------------- */

/**
 * Check if a string is a recognised social signal.
 */
export function isSocialSignalType(value: string): value is SocialSignalType {
  return (SOCIAL_SIGNAL_TYPES as readonly string[]).includes(value);
}

/**
 * Check if a string is a valid feature flag key.
 */
export function isFeatureFlag(value: string): value is FeatureFlag {
  return (Object.values(FeatureFlag) as readonly string[]).includes(value);
}
```