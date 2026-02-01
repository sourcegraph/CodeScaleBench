```typescript
/**
 * PulseSphere SocialOps – Configuration Module
 * ============================================
 * src/config.ts
 *
 * A strongly-typed, runtime-validated configuration layer that powers every
 * PulseSphere service.  Configuration is constructed from three sources
 * (ordered by ascending priority):
 *
 *   1. Hard-coded, version-controlled defaults              (./defaults)
 *   2. Environment-specific override file  (JSON / YAML)    (PULSE_CONFIG_PATH)
 *   3. Process environment variables                        (process.env)
 *
 * On boot-time the config is validated with `zod`; any mismatch terminates the
 * process early to prevent undefined states.  When running in non-production
 * stages, the override file is `fs.watch`-ed and hot-reloaded to offer an
 * improved developer experience.
 *
 * Usage:
 *   import { config } from '@/config';
 *   const { kafka } = config(); // lazy, memoized accessor
 */

import fs from 'node:fs';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { fileURLToPath } from 'node:url';

import dotenv from 'dotenv';
import yaml from 'js-yaml';
import { z } from 'zod';

// ───────────────────────────────────────────────────────────────────────────────
// Bootstrap / Env Loading
// ───────────────────────────────────────────────────────────────────────────────

// Load variables from .env file *once* during module initialization
dotenv.config();

/**
 * Resolve directory of current module (to enable ESM & CJS compatibility)
 */
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ───────────────────────────────────────────────────────────────────────────────
// Configuration Schema (zod) – change with care!
// ───────────────────────────────────────────────────────────────────────────────

const zConfig = z.object({
  app: z.object({
    name: z.string().default('pulse-sphere'),
    version: z.string().default('0.0.0'),
    stage: z.enum(['development', 'staging', 'production', 'test']).default('development'),
  }),

  server: z.object({
    host: z.string().ip().default('0.0.0.0'),
    port: z.number().int().min(1).max(65535).default(8080),
  }),

  kafka: z.object({
    clientId: z.string().default('pulse-sphere-client'),
    brokers: z.array(z.string()).min(1).default(['localhost:9092']),
    /** The maximum size (bytes) of any Kafka message produced  */
    maxMessageBytes: z.number().int().positive().default(1024 * 1024), // 1 MiB
    ssl: z.boolean().default(false),
  }),

  nats: z.object({
    url: z.string().url().default('nats://localhost:4222'),
    name: z.string().default('pulse-sphere-nats'),
  }),

  observability: z.object({
    logLevel: z.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal']).default('info'),
    metricsEnabled: z.boolean().default(true),
    traceSamplingRate: z.number().min(0).max(1).default(0.1),
  }),

  security: z.object({
    jwtSecret: z.string().min(32, { message: 'JWT secret must be at least 32 characters long' }),
    corsAllowedOrigins: z.array(z.string()).default(['*']),
  }),

  backup: z.object({
    snapshotIntervalMinutes: z.number().int().positive().default(60),
    retentionDays: z.number().int().positive().default(7),
    destinationS3Bucket: z.string().optional(),
  }),

  featureFlags: z.object({
    alertingEnabled: z.boolean().default(true),
    autoScalingEnabled: z.boolean().default(false),
    socialContextEnrichment: z.boolean().default(true),
  }),
});

export type Config = z.infer<typeof zConfig>;

// -----------------------------------------------------------------------------
// Default Configuration (source 1)
// -----------------------------------------------------------------------------

const defaults: Config = {
  app: {
    name: 'pulse-sphere',
    version: process.env.npm_package_version ?? '0.0.0',
    stage: (process.env.NODE_ENV as Config['app']['stage']) ?? 'development',
  },
  server: { host: '0.0.0.0', port: 8080 },
  kafka: {
    clientId: 'pulse-sphere-client',
    brokers: ['localhost:9092'],
    maxMessageBytes: 1024 * 1024,
    ssl: false,
  },
  nats: { url: 'nats://localhost:4222', name: 'pulse-sphere-nats' },
  observability: { logLevel: 'info', metricsEnabled: true, traceSamplingRate: 0.1 },
  security: {
    jwtSecret: 'PLEASE_REPLACE_ME_WITH_A_REAL_SECRET___________',
    corsAllowedOrigins: ['*'],
  },
  backup: { snapshotIntervalMinutes: 60, retentionDays: 7, destinationS3Bucket: undefined },
  featureFlags: {
    alertingEnabled: true,
    autoScalingEnabled: false,
    socialContextEnrichment: true,
  },
};

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

/** Deep freeze utility to guarantee immutability after load */
function deepFreeze<T extends Record<string, unknown>>(obj: T): Readonly<T> {
  Object.freeze(obj);
  Object.getOwnPropertyNames(obj).forEach((prop) => {
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    if (obj[prop] !== null
        // eslint-disable-next-line @typescript-eslint/ban-ts-comment
        // @ts-ignore
        && (typeof obj[prop] === 'object')
        // eslint-disable-next-line @typescript-eslint/ban-ts-comment
        // @ts-ignore
        && !Object.isFrozen(obj[prop])) {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      deepFreeze(obj[prop]);
    }
  });
  return obj;
}

/**
 * Merge two POJOs deeply – rhs takes precedence over lhs.
 */
function deepMerge<T extends Record<string, unknown>, U extends Record<string, unknown>>(lhs: T, rhs: U): T & U {
  const result = { ...lhs } as T & U;

  Object.entries(rhs).forEach(([key, value]) => {
    if (value === undefined) return;

    if (Array.isArray(value)) {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      result[key] = value as unknown as (T & U)[keyof (T & U)];
    } else if (value !== null && typeof value === 'object') {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      result[key] = deepMerge(lhs[key] ?? {}, value);
    } else {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      result[key] = value as (T & U)[keyof (T & U)];
    }
  });

  return result;
}

/** Parse boolean valued environment variables safely. */
const toBoolean = (val?: string): boolean | undefined =>
  val === undefined ? undefined : /^(true|1|yes)$/i.test(val);

// -----------------------------------------------------------------------------
// Environment Variable mapping (source 3)
// -----------------------------------------------------------------------------

/**
 * Convert strongly-typed env variables to partial Config object.
 * NB: Keep names consistent & document them inside README / ADR!
 */
function envToConfig(): Partial<Config> {
  return {
    app: {
      stage: process.env.NODE_ENV as Config['app']['stage'] | undefined,
    },

    server: {
      port: process.env.PORT ? Number(process.env.PORT) : undefined,
    },

    kafka: {
      brokers: process.env.KAFKA_BROKERS?.split(',').filter(Boolean),
      clientId: process.env.KAFKA_CLIENT_ID,
      ssl: toBoolean(process.env.KAFKA_SSL),
      maxMessageBytes: process.env.KAFKA_MAX_MSG_BYTES
        ? Number(process.env.KAFKA_MAX_MSG_BYTES)
        : undefined,
    },

    nats: {
      url: process.env.NATS_URL,
      name: process.env.NATS_NAME,
    },

    observability: {
      logLevel: process.env.LOG_LEVEL as Config['observability']['logLevel'] | undefined,
      metricsEnabled: toBoolean(process.env.METRICS_ENABLED),
      traceSamplingRate: process.env.TRACE_SAMPLING_RATE
        ? Number(process.env.TRACE_SAMPLING_RATE)
        : undefined,
    },

    security: {
      jwtSecret: process.env.JWT_SECRET,
      corsAllowedOrigins: process.env.CORS_ALLOWED_ORIGINS?.split(',').filter(Boolean),
    },

    backup: {
      snapshotIntervalMinutes: process.env.BACKUP_SNAPSHOT_INTERVAL
        ? Number(process.env.BACKUP_SNAPSHOT_INTERVAL)
        : undefined,
      retentionDays: process.env.BACKUP_RETENTION_DAYS
        ? Number(process.env.BACKUP_RETENTION_DAYS)
        : undefined,
      destinationS3Bucket: process.env.BACKUP_DESTINATION_BUCKET,
    },

    featureFlags: {
      alertingEnabled: toBoolean(process.env.FEATURE_ALERTING_ENABLED),
      autoScalingEnabled: toBoolean(process.env.FEATURE_AUTOSCALING_ENABLED),
      socialContextEnrichment: toBoolean(process.env.FEATURE_SOCIAL_ENRICHMENT),
    },
  };
}

// -----------------------------------------------------------------------------
// Override File Loader (source 2)
// -----------------------------------------------------------------------------

/** Allowed override file formats */
const SUPPORTED_EXT = new Set(['.json', '.yaml', '.yml']);

function loadOverrideFile(): Record<string, unknown> | undefined {
  const overridePath = process.env.PULSE_CONFIG_PATH;

  if (!overridePath) return undefined;

  const absPath = path.isAbsolute(overridePath)
    ? overridePath
    : path.join(__dirname, overridePath);

  const ext = path.extname(absPath).toLowerCase();
  if (!SUPPORTED_EXT.has(ext)) {
    // eslint-disable-next-line no-console
    console.warn(
      `[config] Unsupported override file extension "${ext}". Supported: ${Array.from(
        SUPPORTED_EXT,
      ).join(', ')}`,
    );
    return undefined;
  }

  if (!fs.existsSync(absPath)) {
    // eslint-disable-next-line no-console
    console.warn(`[config] Override file not found at: ${absPath}`);
    return undefined;
  }

  try {
    const raw = fs.readFileSync(absPath, 'utf8');
    return ext === '.json' ? JSON.parse(raw) : (yaml.load(raw) as Record<string, unknown>);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error(`[config] Failed to load override file: ${err instanceof Error ? err.message : err}`);
    return undefined;
  }
}

// -----------------------------------------------------------------------------
// ConfigManager (Singleton) – public API
// -----------------------------------------------------------------------------

class ConfigManager extends EventEmitter {
  private static _instance: ConfigManager;

  private _config: Readonly<Config>;

  private constructor() {
    super();

    const environment = envToConfig();
    const override = loadOverrideFile();

    const merged = deepMerge(defaults, override ?? {});
    const withEnv = deepMerge(merged, environment);

    // Validate & freeze
    const validated = zConfig.parse(withEnv);

    this._config = deepFreeze(validated);

    this.setupHotReload();
  }

  static instance(): ConfigManager {
    if (!ConfigManager._instance) ConfigManager._instance = new ConfigManager();
    return ConfigManager._instance;
  }

  /** Typed getter shortcut – guarantees immutability */
  get config(): Readonly<Config> {
    return this._config;
  }

  /**
   * Hot reload configuration file (only in non-production and if override file exists).
   * Emits 'reload' event on success.
   */
  private setupHotReload(): void {
    const overridePath = process.env.PULSE_CONFIG_PATH;
    if (!overridePath) return;
    if (this._config.app.stage === 'production') return;

    const absPath = path.isAbsolute(overridePath)
      ? overridePath
      : path.join(__dirname, overridePath);

    fs.watch(
      absPath,
      { persistent: false },
      // eslint-disable-next-line @typescript-eslint/no-misused-promises
      async (_event, filename) => {
        if (!filename) return;

        try {
          const newData = loadOverrideFile();
          if (!newData) return;

          const withEnv = deepMerge(deepMerge(defaults, newData), envToConfig());
          const validated = zConfig.parse(withEnv);
          this._config = deepFreeze(validated);

          this.emit('reload', this._config);
          // eslint-disable-next-line no-console
          console.info('[config] Hot-reloaded configuration');
        } catch (err) {
          // eslint-disable-next-line no-console
          console.error(
            `[config] Failed to hot-reload configuration: ${err instanceof Error ? err.message : err}`,
          );
        }
      },
    );
  }
}

// -----------------------------------------------------------------------------
// Public Export – as lazy getter function
// -----------------------------------------------------------------------------

/**
 * Retrieve the immutable configuration object
 *
 * Example:
 *   import { config } from '@/config';
 *   const port = config().server.port;
 */
export function config(): Readonly<Config> {
  return ConfigManager.instance().config;
}

/**
 * Listen for hot-reload events (only emitted in non-production environments)
 *
 * Example:
 *   import { onConfigReload } from '@/config';
 *   onConfigReload((newCfg) => console.log('Config changed', newCfg));
 */
export function onConfigReload(listener: (cfg: Readonly<Config>) => void): void {
  ConfigManager.instance().on('reload', listener);
}
```