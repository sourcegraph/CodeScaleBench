// src/constants.js
// ============================================================================
// AgoraPulse - Real-Time Social Signal Intelligence
// Global constants, enumerations, and utility helpers shared across the code-base.
// This module is intentionally free of domain logic; it merely centralises all
// “magic values” so they can be version-controlled, documented, and validated.
// ============================================================================

// ---------------------------------------------------------------------------
// Standard / built-in dependencies
// ---------------------------------------------------------------------------
import os from 'node:os';

/* eslint-disable import/prefer-default-export */

/**
 * Ensure an environment variable exists, otherwise throw an explicit error.
 * Never use `process.env.FOO || 'fallback'` for required configuration, as
 * it silently swallows misconfiguration bugs.
 *
 * @param {string} key               - The name of the env var to look up.
 * @param {string | undefined} fallback - Optional fallback value.
 * @returns {string}                 - The resolved value.
 * @throws {Error}                   - If the var is missing and no fallback.
 */
export function getEnvVar(key, fallback) {
  const value = process.env[key] ?? fallback;
  if (value === undefined) {
    throw new Error(
      `[constants] Missing required environment variable: ${key}`,
    );
  }
  return value;
}

/**
 * Deep-freeze an object so neither it, nor any of its nested descendants,
 * can be mutated at runtime.
 *
 * NOTE: Symbol and function properties are preserved but not recursed.
 *
 * @template T
 * @param {T} obj - The object to freeze.
 * @returns {Readonly<T>}
 */
export function deepFreeze(obj) {
  // Skip primitives and null
  if (obj === null || typeof obj !== 'object') return obj;

  // Recursively freeze properties before freezing self
  Object.getOwnPropertyNames(obj).forEach((prop) => {
    // Prevent infinite recursion on self references
    if (
      Object.prototype.hasOwnProperty.call(obj, prop) &&
      obj[prop] !== null &&
      typeof obj[prop] === 'object' &&
      !Object.isFrozen(obj[prop])
    ) {
      deepFreeze(obj[prop]);
    }
  });

  return Object.freeze(obj);
}

// ---------------------------------------------------------------------------
// Environment / runtime configuration
// ---------------------------------------------------------------------------
export const ENVIRONMENT = process.env.NODE_ENV ?? 'development';

export const isProd = ENVIRONMENT === 'production';
export const isDev = ENVIRONMENT === 'development';
export const isTest = ENVIRONMENT === 'test';

/**
 * Logical namespace used to isolate resources in multi-tenant clusters.
 * Convention: kebab-case.
 *
 * The value can be statically defined via `AGORA_NAMESPACE` or computed from
 * `NODE_ENV`.
 */
export const NAMESPACE = getEnvVar(
  'AGORA_NAMESPACE',
  isProd ? 'agora-pulse' : `agora-pulse-${ENVIRONMENT}`,
);

export const SERVICE_NAME = 'agora-pulse-core';

// ---------------------------------------------------------------------------
// Enumerations (strongly typed via Object.freeze)
// ---------------------------------------------------------------------------

/**
 * Social network events that enter the system. These map 1-to-1 to the outer
 * Kafka topics produced by our collector services.
 */
export const SocialEventTypes = deepFreeze({
  TWEET: 'tweet',
  RETWEET: 'retweet',
  LIKE: 'like',
  COMMENT: 'comment',
  EMOJI_REACTION: 'emoji_reaction',
  VOICE_CHAT: 'voice_chat',
  LIVE_STREAM_COMMENT: 'live_stream_comment',
});

/**
 * Kafka topic names used across the platform. A single change here propagates
 * cluster-wide without code modifications elsewhere.
 */
export const KafkaTopics = deepFreeze({
  RAW_INGEST: `${NAMESPACE}.raw.ingest`,
  SOCIAL_EVENTS: `${NAMESPACE}.social.events`,
  FEATURES: `${NAMESPACE}.features`,
  MODEL_INFERENCES: `${NAMESPACE}.model.inferences`,
  MODEL_MONITORING: `${NAMESPACE}.model.monitoring`,
  MODEL_REGISTRY: `${NAMESPACE}.model.registry`,
  CONTROL_PLANE: `${NAMESPACE}.control.plane`,
});

/**
 * Pipeline stage identifiers. Used by RxJS operators, metrics labels,
 * and tracing spans.
 */
export const PipelineStage = deepFreeze({
  INGESTION: 'ingestion',
  FEATURE_ENGINEERING: 'feature_engineering',
  INFERENCE: 'inference',
  POST_PROCESSING: 'post_processing',
  MONITORING: 'monitoring',
});

/**
 * Model lifecycle states mirrored in MLflow’s Model Registry.
 */
export const ModelStatus = deepFreeze({
  CANDIDATE: 'candidate',
  ACTIVE: 'active',
  SHADOW: 'shadow',
  DEPRECATED: 'deprecated',
  ARCHIVED: 'archived',
});

/**
 * Metric thresholds that trigger alerts or auto-retraining. Tuned via SLOs.
 */
export const MetricsThresholds = deepFreeze({
  TOXICITY_FALSE_NEGATIVE_RATE: 0.02, // 2%
  SENTIMENT_DRIFT_KL: 0.1, // KL divergence
  MODEL_LATENCY_P99_MS: 150,
});

/**
 * Default exponential back-off strategy parameters for retryable routines.
 */
export const BackoffStrategy = deepFreeze({
  BASE_MS: 250,
  FACTOR: 2,
  MAX_RETRIES: 5,
  JITTER_RATIO: 0.2,
});

/**
 * OpenTelemetry semantic attribute keys used in tracing instrumentation.
 */
export const Observability = deepFreeze({
  TRACE_ID: 'trace_id',
  SPAN_ID: 'span_id',
  PIPELINE_STAGE: 'pipeline_stage',
  MODEL_VERSION: 'model_version',
  DATASET_ID: 'dataset_id',
});

// ---------------------------------------------------------------------------
// Regexes & miscellaneous constants
// ---------------------------------------------------------------------------
export const REGEX = deepFreeze({
  USERNAME: /^@[A-Za-z0-9_]{1,15}$/, // Twitter-style username
  HASHTAG: /^#[\p{L}0-9_]{1,50}$/u, // Unicode hashtag support
});

/**
 * A single location for default timeouts (ms).
 */
export const Timeouts = deepFreeze({
  HTTP_REQUEST: 5_000,
  KAFKA_PRODUCE: 3_000,
  KAFKA_CONSUME: 1_000,
  MODEL_INFERENCE: 2_500,
});

/**
 * A banner displayed on application start-up. Purely cosmetic.
 */
export const BANNER = `
   ___                       ____        _               
  / _ \\__ _____  ___  ___   / __ \\____ _(_)___  ___ ____ 
 / ___/ _ \`/ __ \\/ _ \\/ _ \\ / /_/ / __ \`/ / __ \\/ _ \`/ _ \\
/_/   \\_,_/ / /_/\\___/_//_/ \\____/\\_,_/_/_/ /_/\\_, / .__/
/  Real-Time Social Signal Intelligence            /___/ 
`.trim();

// ---------------------------------------------------------------------------
// Metadata helpers
// ---------------------------------------------------------------------------

/**
 * Process-level metadata that is often attached to logs or tracing spans.
 */
export const Metadata = deepFreeze({
  hostname: os.hostname(),
  pid: process.pid,
  namespace: NAMESPACE,
  service: SERVICE_NAME,
  environment: ENVIRONMENT,
});

// ---------------------------------------------------------------------------
// Module self-test (fail fast on boot)
// ---------------------------------------------------------------------------
(function assertInternalConsistency() {
  const requiredTopics = Object.values(KafkaTopics);
  if (new Set(requiredTopics).size !== requiredTopics.length) {
    // Duplicate topic names would break idempotency guarantees
    throw new Error('[constants] Duplicate Kafka topic detected.');
  }
})();

/* eslint-enable import/prefer-default-export */
