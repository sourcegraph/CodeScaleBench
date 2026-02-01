```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 * -------------------------------------------------
 * Centralised configuration module.
 *
 * Responsibilities
 *  1. Load and merge process-level environment variables from `.env` files.
 *  2. Validate the complete set of variables against an explicit Joi schema.
 *  3. Export a frozen, immutable configuration object that can be safely
 *     shared across the code-base without risk of mutation.
 *  4. Provide helper utilities (`config.get`, `config.masked`) for ergonomic
 *     access and secure logging.
 *
 * NOTE:
 *  • This file is intentionally written in JavaScript (ES2022) so that it can
 *    be consumed by both CommonJS and ESM build targets without transpilation.
 *  • All default values are production-grade sane defaults; override via
 *    environment variables or `.env.{environment}` files.
 */

import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import * as dotenv from 'dotenv';
import Joi from 'joi';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/* -------------------------------------------------------------------------- *
 * Helper utilities                                                           *
 * -------------------------------------------------------------------------- */

/**
 * Parse a duration string such as "250ms", "2s", "10m", "1h" into milliseconds.
 * Falls back to Number(value) when no unit suffix is present.
 *
 * @param {string|number} value
 * @returns {number} The input value in milliseconds.
 */
function parseDuration(value) {
  if (typeof value === 'number') return value;
  const match = /^(\d+(?:\.\d+)?)(ms|s|m|h)?$/i.exec(value.trim());
  if (!match) throw new Error(`Invalid duration string "${value}"`);
  const num = Number(match[1]);
  const unit = (match[2] || 'ms').toLowerCase();
  const multipliers = { ms: 1, s: 1_000, m: 60_000, h: 3_600_000 };
  return num * multipliers[unit];
}

/**
 * Parse a comma-separated list into an array of trimmed strings.
 *
 * @param {string|string[]} value
 * @returns {string[]}
 */
function parseCsv(value) {
  if (Array.isArray(value)) return value;
  return value
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean);
}

/**
 * Deep freeze an object. Adapted from:
 * https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Object/freeze#freezing_arrays
 *
 * @param {object} obj
 * @returns {object} The same object, now frozen recursively.
 */
function deepFreeze(obj) {
  Object.getOwnPropertyNames(obj).forEach((prop) => {
    const val = obj[prop];
    if (val && typeof val === 'object' && !Object.isFrozen(val)) {
      deepFreeze(val);
    }
  });
  return Object.freeze(obj);
}

/* -------------------------------------------------------------------------- *
 * DotEnv loading                                                             *
 * -------------------------------------------------------------------------- */

const NODE_ENV = process.env.NODE_ENV || 'development';
const ENV_FILES = [
  `.env.${NODE_ENV}.local`,
  `.env.${NODE_ENV}`,
  '.env', // fallback
].map((file) => path.resolve(process.cwd(), file));

ENV_FILES.forEach((file) => {
  if (fs.existsSync(file)) {
    dotenv.config({ path: file });
  }
});

/* -------------------------------------------------------------------------- *
 * Schema definition (Joi)                                                    *
 * -------------------------------------------------------------------------- */

const schema = Joi.object({
  /* Application-level ------------------------------------------------------ */
  APP_NAME: Joi.string().default('AgoraPulse'),
  NODE_ENV: Joi.string()
    .valid('development', 'test', 'staging', 'production')
    .default(NODE_ENV),
  LOG_LEVEL: Joi.string()
    .valid('fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent')
    .default(NODE_ENV === 'production' ? 'info' : 'debug'),
  PORT: Joi.number().integer().min(1).max(65535).default(3000),
  HOST: Joi.string().hostname().default('0.0.0.0'),
  COMMIT_SHA: Joi.string().allow('').default(''),

  /* Security --------------------------------------------------------------- */
  JWT_SECRET: Joi.string().min(32).required(),
  CORS_ALLOWED_ORIGINS: Joi.string().default('*'),

  /* Kafka ------------------------------------------------------------------ */
  KAFKA_BROKERS: Joi.string().required(),
  KAFKA_CLIENT_ID: Joi.string().default('agorapulse-core'),
  KAFKA_CONSUMER_GROUP_ID: Joi.string().default('agorapulse-consumers'),
  KAFKA_SSL: Joi.boolean().truthy('true').falsy('false').default(false),

  /* PostgreSQL (feature store) -------------------------------------------- */
  PG_HOST: Joi.string().hostname().default('localhost'),
  PG_PORT: Joi.number().integer().default(5432),
  PG_DATABASE: Joi.string().default('agorapulse_features'),
  PG_USER: Joi.string().default('postgres'),
  PG_PASSWORD: Joi.string().allow('').default(''),

  /* Redis (caching / feature store) --------------------------------------- */
  REDIS_URL: Joi.string().uri().default('redis://localhost:6379'),

  /* MLflow ----------------------------------------------------------------- */
  MLFLOW_TRACKING_URI: Joi.string()
    .uri({ scheme: ['http', 'https'] })
    .default('http://localhost:5000'),
  MLFLOW_EXPERIMENT_NAME: Joi.string().default('agorapulse-default'),

  /* Ray Tune --------------------------------------------------------------- */
  RAY_TUNE_SERVICE_URL: Joi.string()
    .uri({ scheme: ['http', 'https'] })
    .default('http://localhost:8265'),

  /* DVC -------------------------------------------------------------------- */
  DVC_REMOTE_URL: Joi.string().uri().default('s3://agorapulse-dvc'),

  /* Observability ---------------------------------------------------------- */
  PROM_PUSHGATEWAY_URL: Joi.string().uri().default('http://localhost:9091'),
})
  .unknown() // allow additional vars without failing (forward compatibility)
  .required();

const { error, value: env } = schema.validate(process.env, {
  abortEarly: false,
  convert: true,
  allowUnknown: true,
});

if (error) {
  // Log all validation errors before hard exit
  console.error(
    '\n❌  Environment validation failed. Please fix the following issues:\n'
  );
  error.details.forEach((d) => console.error(` • ${d.message}`));
  process.exit(1);
}

/* -------------------------------------------------------------------------- *
 * Derived & structured configuration object                                 *
 * -------------------------------------------------------------------------- */

// Read version from package.json (robustly works in monorepo & pkg managers)
let pkgVersion = '0.0.0-dev';
try {
  const pkgJsonPath = path.resolve(__dirname, '../package.json');
  const pkgJson = JSON.parse(fs.readFileSync(pkgJsonPath, 'utf-8'));
  pkgVersion = pkgJson.version || pkgVersion;
} catch {
  // swallow; will fallback to default
}

const config = {
  app: {
    name: env.APP_NAME,
    env: env.NODE_ENV,
    version: pkgVersion,
    commitSha: env.COMMIT_SHA,
    logLevel: env.LOG_LEVEL,
    host: env.HOST,
    port: Number(env.PORT),
    baseUrl:
      env.PUBLIC_BASE_URL ||
      `http://${env.HOST === '0.0.0.0' ? 'localhost' : env.HOST}:${env.PORT}`,
  },

  security: {
    jwtSecret: env.JWT_SECRET,
    cors: {
      allowedOrigins: parseCsv(env.CORS_ALLOWED_ORIGINS),
    },
  },

  kafka: {
    brokers: parseCsv(env.KAFKA_BROKERS),
    clientId: env.KAFKA_CLIENT_ID,
    consumerGroupId: env.KAFKA_CONSUMER_GROUP_ID,
    ssl: Boolean(env.KAFKA_SSL),
    topics: {
      rawEvents: 'agorapulse.raw-events',
      routedEvents: 'agorapulse.routed-events',
      insights: 'agorapulse.insights',
      retraining: 'agorapulse.retraining',
    },
    // A helper to build topic names w/ namespacing
    topic: (name) => `agorapulse.${name}`,
  },

  database: {
    postgres: {
      host: env.PG_HOST,
      port: Number(env.PG_PORT),
      database: env.PG_DATABASE,
      user: env.PG_USER,
      password: env.PG_PASSWORD,
      ssl: env.NODE_ENV === 'production',
    },
    redis: {
      url: env.REDIS_URL,
      defaultTTL: parseDuration('10m'),
    },
  },

  ml: {
    mlflow: {
      trackingUri: env.MLFLOW_TRACKING_URI,
      experimentName: env.MLFLOW_EXPERIMENT_NAME,
    },
    rayTune: {
      serviceUrl: env.RAY_TUNE_SERVICE_URL,
      // How often to poll Ray for experiment status
      pollIntervalMs: parseDuration('5s'),
    },
    dvc: {
      remoteUrl: env.DVC_REMOTE_URL,
    },
  },

  observability: {
    prometheus: {
      pushGatewayUrl: env.PROM_PUSHGATEWAY_URL,
      pushIntervalMs: parseDuration('15s'),
    },
  },
};

/* -------------------------------------------------------------------------- *
 * Public API (get, masked, raw, etc.)                                        *
 * -------------------------------------------------------------------------- */

/**
 * Lightweight dot-notation getter.
 *
 * @param {string} pathStr e.g. "database.postgres.host"
 * @param {any}    fallback Optional fallback when path is undefined.
 * @returns {any}
 */
function get(pathStr, fallback = undefined) {
  return pathStr.split('.').reduce((acc, key) => {
    if (acc && Object.hasOwn(acc, key)) return acc[key];
    return fallback;
  }, config);
}

/**
 * Return a clone of the configuration with sensitive values masked, suitable
 * for logging or debugging output. Secrets are replaced with "******".
 *
 * @returns {object}
 */
function masked() {
  const SENSITIVE_KEYS = ['password', 'jwtSecret', 'JWT_SECRET'];
  const clone = JSON.parse(JSON.stringify(config));

  function traverse(obj) {
    Object.entries(obj).forEach(([k, v]) => {
      if (SENSITIVE_KEYS.some((s) => k.toLowerCase().includes(s.toLowerCase()))) {
        obj[k] = '******';
      } else if (v && typeof v === 'object') {
        traverse(v);
      }
    });
  }

  traverse(clone);
  return clone;
}

/* -------------------------------------------------------------------------- *
 * Exports                                                                    *
 * -------------------------------------------------------------------------- */

deepFreeze(config); // ensure immutability

export default config;
export { get, masked };
export const CONFIG = config; // Named export for convenience

/* -------------------------------------------------------------------------- *
 * Developer ergonomics                                                       *
 * -------------------------------------------------------------------------- */

if (process.env.DEBUG_CONFIG === 'true') {
  // eslint-disable-next-line no-console
  console.debug(
    '🔧  Effective configuration:\n',
    JSON.stringify(masked(), null, 2)
  );
}
```