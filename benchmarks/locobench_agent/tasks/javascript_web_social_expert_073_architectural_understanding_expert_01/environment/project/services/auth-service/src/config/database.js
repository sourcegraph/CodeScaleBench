```javascript
/**
 * PulseLearn Campus Hub – Auth Service
 * ------------------------------------
 * Centralised database configuration and connection handling.
 *
 * This module is intentionally *side-effect free*; it exposes a lazily-created
 * Sequelize instance and a small helper API so that callers can explicitly
 * control connection life-cycle in tests, CLI tools and the running service.
 *
 * Responsibilities:
 *  • Read environment variables & fallback to sane defaults
 *  • Establish connection pool with SSL / IAM authentication support
 *  • Provide graceful shutdown hooks for Kubernetes / Docker
 *  • Expose common helpers (withTransaction, getSequelize)
 */

'use strict';

/* ──────────────────────────────────────────────────────────────────────────
 * Dependencies
 * ──────────────────────────────────────────────────────────────────────── */
const fs            = require('node:fs');
const path          = require('node:path');
const process       = require('node:process');

const { Sequelize } = require('sequelize');          // ORM
const pg            = require('pg');                 // Native driver for better perf
const debug         = require('debug')('auth:db');   // Namespaced debug logger
const once          = require('events').once;

require('dotenv').config({ path: path.resolve(process.cwd(), '.env') });

/* ──────────────────────────────────────────────────────────────────────────
 * Environment variables
 * ──────────────────────────────────────────────────────────────────────── */
const {
  DB_HOST                = 'localhost',
  DB_USER                = 'postgres',
  DB_PASSWORD            = 'postgres',
  DB_NAME                = 'pulselearn_auth',
  DB_PORT                = 5432,
  DB_POOL_MAX            = 10,
  DB_POOL_MIN            = 1,
  DB_POOL_IDLE           = 10_000,
  DB_POOL_ACQUIRE        = 30_000,
  DB_SSL                 = 'false',
  DB_SSL_CA_CERT_PATH,
  NODE_ENV               = 'development',
} = process.env;

/* ──────────────────────────────────────────────────────────────────────────
 * Internal state
 * ──────────────────────────────────────────────────────────────────────── */
let sequelize;              // Lazy-initialised singleton
let _connectionPromise;     // Prevent duplicate authenticate() calls

/* ──────────────────────────────────────────────────────────────────────────
 * Helper utils
 * ──────────────────────────────────────────────────────────────────────── */

/**
 * Builds dialectOptions with optional SSL support.
 * Supports:
 *   • ssl = false            – no SSL
 *   • ssl = true             – require SSL, but don't verify cert
 *   • ssl = <path>           – absolute/relative path to CA .crt file
 */
function buildDialectOptions() {
  if (!DB_SSL || DB_SSL === 'false') {
    return {};
  }

  // ssl="true"
  if (DB_SSL === 'true') {
    return { ssl: { require: true, rejectUnauthorized: false } };
  }

  // ssl="<path to ca>"
  const resolvedPath = DB_SSL_CA_CERT_PATH || DB_SSL;
  const caPath       = path.isAbsolute(resolvedPath)
    ? resolvedPath
    : path.join(process.cwd(), resolvedPath);

  let ca;
  try {
    ca = fs.readFileSync(caPath, 'utf8');
  } catch (err) {
    throw new Error(`Failed to read DB SSL CA cert from ${caPath}: ${err.message}`);
  }

  return {
    ssl: {
      require: true,
      rejectUnauthorized: true,
      ca,
    },
  };
}

/* ──────────────────────────────────────────────────────────────────────────
 * Lazy initialiser
 * ──────────────────────────────────────────────────────────────────────── */
function init() {
  if (sequelize) {
    return sequelize;
  }

  debug('Initialising Sequelize…');

  sequelize = new Sequelize(DB_NAME, DB_USER, DB_PASSWORD, {
    host           : DB_HOST,
    port           : DB_PORT,
    dialect        : 'postgres',
    dialectModule  : pg,
    logging        : NODE_ENV === 'development' ? debug : false,
    pool           : {
      max     : Number(DB_POOL_MAX),
      min     : Number(DB_POOL_MIN),
      idle    : Number(DB_POOL_IDLE),
      acquire : Number(DB_POOL_ACQUIRE),
    },
    dialectOptions : buildDialectOptions(),
    define         : {
      // Global model settings:
      underscored : true,
      freezeTableName: true,
    },
  });

  sequelize
    .authenticate()
    .then(() => debug('Database connection established.'))
    .catch((err) => {
      // eslint-disable-next-line no-console
      console.error('\n❌  Unable to connect to the database:', err);
      process.exitCode = 1;
    });

  return sequelize;
}

/* ──────────────────────────────────────────────────────────────────────────
 * Public API
 * ──────────────────────────────────────────────────────────────────────── */

/**
 * Explicitly establishes a connection (if not already connected).
 * @returns {Promise<Sequelize>}
 */
async function connect() {
  if (_connectionPromise) return _connectionPromise;

  sequelize = init();
  _connectionPromise = sequelize.authenticate();
  await _connectionPromise;
  return sequelize;
}

/**
 * Gracefully closes the Sequelize pool. Safe to call multiple times.
 * @returns {Promise<void>}
 */
async function disconnect() {
  if (!sequelize) return;
  await sequelize.close();
  debug('Database connection closed.');
  sequelize = null;
  _connectionPromise = null;
}

/**
 * Executes callback inside a transaction with automatic commit / rollback.
 *
 * @template T
 * @param {(t: import('sequelize').Transaction) => Promise<T>} cb
 * @returns {Promise<T>}
 */
async function withTransaction(cb) {
  const db = await connect();
  const result = await db.transaction(async (tx) => cb(tx));
  return result;
}

/* ──────────────────────────────────────────────────────────────────────────
 * Graceful shutdown hooks for Docker / Kubernetes
 * ──────────────────────────────────────────────────────────────────────── */
(async () => {
  // Wait until the service receives a termination signal
  // Then close the DB pool before Node.js exits.
  const signals = ['SIGINT', 'SIGTERM', 'SIGQUIT'];

  for (const sig of signals) {
    process.on(sig, async () => {
      debug(`Received ${sig}, shutting down database connections…`);
      try {
        await disconnect();
        // Delay so logs can flush
        setTimeout(() => process.exit(0), 300);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error('Error during DB shutdown:', err);
        process.exit(1);
      }
    });
  }

  // If the parent process disconnects (e.g. nodemon restarts), also close DB.
  if (process.ppid && process.channel) {
    process.on('disconnect', async () => {
      debug('Parent process disconnected. Closing DB pool…');
      await disconnect();
    });
  }
})().catch((err) => {
  // eslint-disable-next-line no-console
  console.error('DB graceful shutdown hook failed:', err);
});

/* ──────────────────────────────────────────────────────────────────────────
 * Exports
 * ──────────────────────────────────────────────────────────────────────── */
module.exports = {
  connect,
  disconnect,
  withTransaction,
  get sequelize() {
    return sequelize || init();
  },
};
```