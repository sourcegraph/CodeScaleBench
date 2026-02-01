```javascript
// pulselearn-campus-hub/services/auth-service/src/config/env.js

/**
 * Centralised environment configuration and validation for the Auth-Service.
 *
 * All environment variables are loaded once, validated against a strict schema
 * (using Joi) and then exposed as a frozen, read-only configuration object.
 *
 * This module **must** be imported before any other local module which relies
 * on environment variables – ideally the very first import in the entrypoint
 * (index.js / server.js).
 */

/* ────────────────────────────────────────────────────────── External Imports ─ */
import fs       from 'node:fs';
import path     from 'node:path';
import dotenv   from 'dotenv';
import Joi      from 'joi';

/* ──────────────────────────────────────────────────────────── Load .env file ─ */
const ENV_PATH = path.resolve(process.cwd(), '.env');

if (fs.existsSync(ENV_PATH)) {
  // Loads variables into process.env *only* once
  dotenv.config({ path: ENV_PATH });
} else if (process.env.NODE_ENV !== 'production') {
  console.warn('[env] No .env file found; relying solely on process.env');
}

/* ─────────────────────────────────────── Schema Definition & Variable Parsing ─ */
const envSchema = Joi.object({
  /* Generic */
  NODE_ENV: Joi.string().valid('development', 'test', 'production').default('development'),
  SERVICE_NAME: Joi.string().default('auth-service'),
  PORT: Joi.number().integer().positive().default(4000),

  /* JWT */
  JWT_ACCESS_SECRET: Joi.string().min(16).required(),
  JWT_ACCESS_TTL:    Joi.string().default('15m'), // e.g., 15m, 2h, 7d (ms library format)
  JWT_REFRESH_SECRET: Joi.string().min(16).required(),
  JWT_REFRESH_TTL:    Joi.string().default('60d'),

  /* OAuth (Google example) */
  GOOGLE_CLIENT_ID:     Joi.string().when('NODE_ENV', {
    is: 'production',
    then: Joi.required(),
    otherwise: Joi.optional()
  }),
  GOOGLE_CLIENT_SECRET: Joi.string().when('GOOGLE_CLIENT_ID', {
    is: Joi.exist(),
    then: Joi.required(),
    otherwise: Joi.optional()
  }),
  GOOGLE_CALLBACK_URL:  Joi.string().uri().optional(),

  /* Database / Cache */
  DATABASE_URL: Joi.string().uri({ scheme: ['postgres', 'mysql', 'mongodb'] }).required(),
  REDIS_URL:    Joi.string().uri({ scheme: [/redis/]}).optional(),

  /* Event Backbone */
  KAFKA_BROKERS: Joi.string() // comma-separated list
    .required()
    .custom((value, helpers) => {
      const brokers = value.split(',').map(b => b.trim());
      if (!brokers.length) return helpers.error('any.invalid');
      return brokers;
    }, 'Kafka broker list parser'),

  /* Security / SSL (optional) */
  SSL_KEY_PATH:  Joi.string().optional(),
  SSL_CERT_PATH: Joi.string().optional(),

  /* Misc */
  LOG_LEVEL: Joi.string().valid('fatal','error','warn','info','debug','trace').default('info')
}).unknown() // allow extra env vars for other services
  .required();

/* ──────────────────────────────────────────── Validate & Format Env Variables ─ */
const { error, value: envVars } = envSchema.validate(process.env, {
  abortEarly: false, // show all errors
  stripUnknown: true
});

if (error) {
  // Construct a readable aggregate error
  const msg = error.details.map(d => `• ${d.message}`).join('\n');
  console.error('\n[env] Invalid or missing environment variables:\n' + msg + '\n');
  process.exit(1);
}

/* ─────────────────────────────────────────────────────── Configuration Object ─ */
const config = Object.freeze({
  env: envVars.NODE_ENV,
  isProd: envVars.NODE_ENV === 'production',
  serviceName: envVars.SERVICE_NAME,
  port: envVars.PORT,

  jwt: {
    access: {
      secret: envVars.JWT_ACCESS_SECRET,
      ttl: envVars.JWT_ACCESS_TTL
    },
    refresh: {
      secret: envVars.JWT_REFRESH_SECRET,
      ttl: envVars.JWT_REFRESH_TTL
    }
  },

  oauth: {
    google: {
      clientId: envVars.GOOGLE_CLIENT_ID,
      clientSecret: envVars.GOOGLE_CLIENT_SECRET,
      callbackUrl: envVars.GOOGLE_CALLBACK_URL
    }
  },

  db: {
    url: envVars.DATABASE_URL
  },

  cache: {
    redisUrl: envVars.REDIS_URL
  },

  kafka: {
    brokers: envVars.KAFKA_BROKERS.split(',').map(b => b.trim())
  },

  ssl: (() => {
    if (!envVars.SSL_KEY_PATH || !envVars.SSL_CERT_PATH) return null;

    try {
      return {
        key: fs.readFileSync(path.resolve(envVars.SSL_KEY_PATH)),
        cert: fs.readFileSync(path.resolve(envVars.SSL_CERT_PATH))
      };
    } catch (err) {
      console.error('[env] Failed to load SSL certificates:', err.message);
      process.exit(1);
    }
  })(),

  logLevel: envVars.LOG_LEVEL
});

/* ──────────────────────────────────────────────────────────── Helper Exports ─ */

/**
 * getEnv
 * A type-safe getter so other modules don’t access process.env directly.
 * 
 * @param {keyof typeof config} key
 * @returns {*} value
 */
const getEnv = (key) => config[key];

/* ────────────────────────────────────────────────────────────────── Exports ─ */
export {
  config as default,
  getEnv
};
```