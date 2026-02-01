```javascript
/**
 * PulseLearn Campus Hub – Auth Service
 * Config Loader & Validator
 *
 * Purpose:
 *  Centralised, strongly-typed runtime configuration for the authentication
 *  service.  Variables are sourced from environment files and process.env,
 *  validated with Joi, and exposed as an immutable object.  The module reads
 *  SSL key/cert (if enabled) and fails fast on any missing or malformed value,
 *  preventing the app from booting into an invalid state.
 *
 * Usage:
 *  const config = require('./config');
 *
 *  console.log(`Auth service running on port ${config.app.port}`);
 */

'use strict';

const fs = require('fs');
const path = require('path');
const dotenv = require('dotenv');
const Joi = require('joi');

// ---------------------------------------------------------------------------
// 1. Environment bootstrap
// ---------------------------------------------------------------------------

/**
 * Resolve and load the proper .env file based on NODE_ENV.
 * Priority order:
 *   1. .env.{NODE_ENV}
 *   2. .env
 */
(function loadEnv() {
  const nodeEnv = process.env.NODE_ENV || 'development';
  const envPaths = [
    path.join(process.cwd(), `.env.${nodeEnv}`),
    path.join(process.cwd(), '.env')
  ];

  envPaths.forEach(envPath => {
    if (fs.existsSync(envPath)) {
      dotenv.config({ path: envPath });
    }
  });
})();

// ---------------------------------------------------------------------------
// 2. Joi Schema Definition
// ---------------------------------------------------------------------------

const envSchema = Joi.object({
  /* Application */
  NODE_ENV: Joi.string().valid('development', 'production', 'test').default('development'),
  APP_NAME: Joi.string().default('pulselearn-auth-service'),
  PORT: Joi.number().integer().min(1).max(65535).default(4000),
  LOG_LEVEL: Joi.string()
    .valid('fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent')
    .default('info'),

  /* Database */
  DB_HOST: Joi.string().hostname().required(),
  DB_PORT: Joi.number().integer().min(1).max(65535).required(),
  DB_USER: Joi.string().required(),
  DB_PASSWORD: Joi.string().allow(''), // allow empty (e.g., local dev)
  DB_NAME: Joi.string().required(),

  /* Redis (session storage / rate-limit) */
  REDIS_HOST: Joi.string().hostname().required(),
  REDIS_PORT: Joi.number().integer().min(1).max(65535).required(),
  REDIS_PASSWORD: Joi.string().allow(''),

  /* JWT */
  JWT_ACCESS_SECRET: Joi.string().min(32).required(),
  JWT_REFRESH_SECRET: Joi.string().min(32).required(),
  JWT_ACCESS_EXPIRES: Joi.string().default('15m'),   // e.g. 15m, 2h
  JWT_REFRESH_EXPIRES: Joi.string().default('30d'),

  /* OAuth – Google */
  OAUTH_GOOGLE_CLIENT_ID: Joi.string(),
  OAUTH_GOOGLE_CLIENT_SECRET: Joi.string(),
  OAUTH_GOOGLE_CALLBACK_URL: Joi.string().uri(),

  /* OAuth – Facebook */
  OAUTH_FACEBOOK_APP_ID: Joi.string(),
  OAUTH_FACEBOOK_APP_SECRET: Joi.string(),
  OAUTH_FACEBOOK_CALLBACK_URL: Joi.string().uri(),

  /* Session */
  SESSION_COOKIE_NAME: Joi.string().default('pl_session'),
  SESSION_COOKIE_SECURE: Joi.boolean().default(false),

  /* SSL */
  SSL_ENABLED: Joi.boolean().truthy('true').falsy('false').default(false),
  SSL_KEY_PATH: Joi.string().when('SSL_ENABLED', {
    is: true,
    then: Joi.required()
  }),
  SSL_CERT_PATH: Joi.string().when('SSL_ENABLED', {
    is: true,
    then: Joi.required()
  }),

  /* Kafka */
  KAFKA_BROKER_URL: Joi.string().required()
}).unknown(); // allow extra vars for other micro-services

// ---------------------------------------------------------------------------
// 3. Validation
// ---------------------------------------------------------------------------

const { value: envVars, error } = envSchema.prefs({ errors: { label: 'key' } }).validate(process.env);

if (error) {
  // Fail-fast with descriptive message
  // eslint-disable-next-line no-console
  console.error(`❌  Invalid environment variable – ${error.message}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// 4. Build Config Object
// ---------------------------------------------------------------------------

const config = {
  app: {
    name: envVars.APP_NAME,
    env: envVars.NODE_ENV,
    port: envVars.PORT,
    logLevel: envVars.LOG_LEVEL
  },

  database: {
    host: envVars.DB_HOST,
    port: envVars.DB_PORT,
    user: envVars.DB_USER,
    password: envVars.DB_PASSWORD,
    name: envVars.DB_NAME,
    // Constructed URI used by the ORM (e.g., Sequelize / TypeORM)
    get uri() {
      const credentials = envVars.DB_PASSWORD
        ? `${encodeURIComponent(envVars.DB_USER)}:${encodeURIComponent(envVars.DB_PASSWORD)}@`
        : `${encodeURIComponent(envVars.DB_USER)}@`;
      return `postgres://${credentials}${envVars.DB_HOST}:${envVars.DB_PORT}/${envVars.DB_NAME}`;
    }
  },

  redis: {
    host: envVars.REDIS_HOST,
    port: envVars.REDIS_PORT,
    password: envVars.REDIS_PASSWORD
  },

  jwt: {
    access: {
      secret: envVars.JWT_ACCESS_SECRET,
      expiresIn: envVars.JWT_ACCESS_EXPIRES
    },
    refresh: {
      secret: envVars.JWT_REFRESH_SECRET,
      expiresIn: envVars.JWT_REFRESH_EXPIRES
    }
  },

  oauth: {
    google: {
      clientId: envVars.OAUTH_GOOGLE_CLIENT_ID,
      clientSecret: envVars.OAUTH_GOOGLE_CLIENT_SECRET,
      callbackURL: envVars.OAUTH_GOOGLE_CALLBACK_URL
    },
    facebook: {
      appId: envVars.OAUTH_FACEBOOK_APP_ID,
      appSecret: envVars.OAUTH_FACEBOOK_APP_SECRET,
      callbackURL: envVars.OAUTH_FACEBOOK_CALLBACK_URL
    }
  },

  session: {
    cookieName: envVars.SESSION_COOKIE_NAME,
    cookieSecure: envVars.SESSION_COOKIE_SECURE
  },

  ssl: (() => {
    const enabled = envVars.SSL_ENABLED;
    if (!enabled) {
      return { enabled: false };
    }

    // Attempt to synchronously load key/cert pair
    let keyBuffer;
    let certBuffer;
    try {
      keyBuffer = fs.readFileSync(path.resolve(envVars.SSL_KEY_PATH));
      certBuffer = fs.readFileSync(path.resolve(envVars.SSL_CERT_PATH));
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(`❌  Unable to read SSL files: ${err.message}`);
      process.exit(1);
    }

    return {
      enabled: true,
      key: keyBuffer,
      cert: certBuffer
    };
  })(),

  kafka: {
    brokerUrl: envVars.KAFKA_BROKER_URL,
    clientId: `${envVars.APP_NAME}-${envVars.NODE_ENV}`
  },

  /**
   * Helper: some endpoints (e.g. health-check, public assets) can bypass auth
   */
  publicPaths: [
    '/healthz',
    '/docs',
    '/auth/login',
    '/auth/register',
    '/auth/refresh-token',
    /^\/oauth\/(google|facebook)\/callback/i
  ]
};

// Freeze to discourage runtime mutation
Object.freeze(config);

// ---------------------------------------------------------------------------
// 5. Export
// ---------------------------------------------------------------------------

module.exports = config;
```