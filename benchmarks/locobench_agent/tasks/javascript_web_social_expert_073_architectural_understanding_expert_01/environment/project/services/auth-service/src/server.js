```javascript
/**
 * PulseLearn Campus Hub – Auth Service
 * ------------------------------------
 * Entry-point & HTTP server definition
 *
 * This file wires together:
 *   • Environment/bootstrap configuration
 *   • Database connection (Sequelize → PostgreSQL / fallback SQLite)
 *   • Centralised logger (Winston)
 *   • NATS event-bus publisher
 *   • Express application with security/rate-limiting middleware
 *   • Basic auth routes (register / login / refresh-token / logout)
 *   • Global error-handling and graceful shutdown logic
 *
 * NOTE:
 *  – This is a self-contained demo that is fully runnable.                             *
 *  – Replace in-memory SQLite with a real Postgres instance for production deployment. *
 */

import 'dotenv/config';
import http from 'node:http';
import process from 'node:process';

import express from 'express';
import helmet from 'helmet';
import morgan from 'morgan';
import cors from 'cors';
import compression from 'compression';
import cookieParser from 'cookie-parser';
import rateLimit from 'express-rate-limit';
import { Sequelize, DataTypes, ValidationError } from 'sequelize';
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import { connect as natsConnect, StringCodec } from 'nats';
import { v4 as uuid } from 'uuid';
import winston from 'winston';

/* -------------------------------------------------------------------------- */
/*                               Configuration                                */
/* -------------------------------------------------------------------------- */

const {
  NODE_ENV = 'development',
  PORT = 4000,
  JWT_SECRET = 'super-secret', // Make sure to override in PROD
  JWT_EXPIRATION = '15m',
  REFRESH_TOKEN_SECRET = 'refresh-secret',
  REFRESH_TOKEN_EXPIRATION = '7d',
  DATABASE_URL,
  NATS_URL = 'nats://localhost:4222',
} = process.env;

/* -------------------------------------------------------------------------- */
/*                                    Log                                    */
/* -------------------------------------------------------------------------- */

const logger = winston.createLogger({
  level: NODE_ENV === 'production' ? 'info' : 'debug',
  format: winston.format.combine(
    winston.format.colorize(),
    winston.format.timestamp(),
    winston.format.splat(),
    winston.format.printf(
      ({ timestamp, level, message, ...meta }) =>
        `${timestamp} [${level}]: ${message} ${
          Object.keys(meta).length ? JSON.stringify(meta) : ''
        }`
    )
  ),
  transports: [new winston.transports.Console()],
});

/* -------------------------------------------------------------------------- */
/*                                Database Init                               */
/* -------------------------------------------------------------------------- */

const sequelize = new Sequelize(DATABASE_URL || 'sqlite::memory:', {
  logging: (msg) => logger.debug(msg),
});

const User = sequelize.define(
  'User',
  {
    id: {
      type: DataTypes.UUID,
      primaryKey: true,
      defaultValue: uuid,
    },
    email: {
      type: DataTypes.STRING,
      unique: true,
      allowNull: false,
      validate: { isEmail: true },
    },
    passwordHash: { type: DataTypes.STRING, allowNull: false },
    name: { type: DataTypes.STRING, allowNull: false },
    refreshToken: { type: DataTypes.STRING }, // single active refresh-token strategy
  },
  {
    tableName: 'users',
    timestamps: true,
    scopes: {
      withoutSecret: {
        attributes: { exclude: ['passwordHash', 'refreshToken'] },
      },
    },
  }
);

/* -------------------------------------------------------------------------- */
/*                               Event Bus (NATS)                             */
/* -------------------------------------------------------------------------- */

const stringCodec = StringCodec();
let natsConnection;

/**
 * Publish domain event to NATS bus
 * @param {string} type - Event type (e.g., UserRegistered)
 * @param {object} payload - The event payload
 */
async function publishEvent(type, payload) {
  if (!natsConnection) {
    logger.warn('NATS connection not ready, skipping publish...');
    return;
  }
  const msg = {
    id: uuid(),
    type,
    ts: new Date().toISOString(),
    payload,
  };
  natsConnection.publish(`pulselearn.auth.${type}`, stringCodec.encode(JSON.stringify(msg)));
  logger.debug('Event published: %s', type);
}

/* -------------------------------------------------------------------------- */
/*                        JWT / Token helper functions                        */
/* -------------------------------------------------------------------------- */

function signAccessToken(claims) {
  return jwt.sign(claims, JWT_SECRET, { expiresIn: JWT_EXPIRATION });
}

function signRefreshToken({ userId }) {
  return jwt.sign({ userId }, REFRESH_TOKEN_SECRET, {
    expiresIn: REFRESH_TOKEN_EXPIRATION,
  });
}

function verifyAccessToken(token) {
  return jwt.verify(token, JWT_SECRET);
}

/* -------------------------------------------------------------------------- */
/*                              Express Setup                                 */
/* -------------------------------------------------------------------------- */

const app = express();

// ── Security & performance middleware ──────────────────────────────────────
app.use(helmet());
app.use(compression());
app.use(
  cors({
    origin: '*', // TODO: tighten for production
    credentials: true,
  })
);
app.use(cookieParser());
app.use(express.json({ limit: '1mb' }));

// ── Rate limiter ───────────────────────────────────────────────────────────
const authLimiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 20,
  legacyHeaders: false,
});
app.use('/api/v1/auth', authLimiter);

// ── Logging ────────────────────────────────────────────────────────────────
if (NODE_ENV !== 'test') {
  app.use(morgan('combined', { stream: { write: (msg) => logger.http(msg.trim()) } }));
}

/* -------------------------------------------------------------------------- */
/*                                Auth Routes                                 */
/* -------------------------------------------------------------------------- */

app.post('/api/v1/auth/register', async (req, res, next) => {
  try {
    const { email, password, name } = req.body || {};

    if (!email || !password || !name) {
      return res.status(400).json({ error: 'Missing required fields.' });
    }

    const passwordHash = await bcrypt.hash(password, 12);

    const user = await User.create({ email, passwordHash, name });

    // Issue tokens
    const accessToken = signAccessToken({ userId: user.id });
    const refreshToken = signRefreshToken({ userId: user.id });
    await user.update({ refreshToken });

    // Publish domain event
    await publishEvent('UserRegistered', { userId: user.id, email, name });

    res
      .status(201)
      .cookie('refresh_token', refreshToken, {
        httpOnly: true,
        secure: NODE_ENV === 'production',
        sameSite: 'strict',
        maxAge: 1000 * 60 * 60 * 24 * 7, // 7 days
      })
      .json({ accessToken });
  } catch (err) {
    if (err instanceof ValidationError) {
      return res.status(400).json({ error: err.errors.map((e) => e.message) });
    }
    if (err.name === 'SequelizeUniqueConstraintError') {
      return res.status(409).json({ error: 'Email already registered.' });
    }
    return next(err);
  }
});

app.post('/api/v1/auth/login', async (req, res, next) => {
  try {
    const { email, password } = req.body || {};
    if (!email || !password) {
      return res.status(400).json({ error: 'Missing credentials.' });
    }

    const user = await User.scope('defaultScope').findOne({ where: { email } });
    if (!user) {
      await publishEvent('LoginFailed', { reason: 'user-not-found', email });
      return res.status(401).json({ error: 'Invalid email or password.' });
    }

    const passwordMatches = await bcrypt.compare(password, user.passwordHash);
    if (!passwordMatches) {
      await publishEvent('LoginFailed', { reason: 'bad-password', userId: user.id });
      return res.status(401).json({ error: 'Invalid email or password.' });
    }

    // Tokens
    const accessToken = signAccessToken({ userId: user.id });
    const refreshToken = signRefreshToken({ userId: user.id });
    await user.update({ refreshToken });

    await publishEvent('UserLoggedIn', { userId: user.id });

    return res
      .cookie('refresh_token', refreshToken, {
        httpOnly: true,
        secure: NODE_ENV === 'production',
        sameSite: 'strict',
        maxAge: 1000 * 60 * 60 * 24 * 7,
      })
      .json({ accessToken });
  } catch (err) {
    return next(err);
  }
});

app.post('/api/v1/auth/refresh-token', async (req, res, next) => {
  try {
    const token =
      req.cookies?.refresh_token ||
      req.body?.refreshToken ||
      req.headers['x-refresh-token'];

    if (!token) {
      return res.status(401).json({ error: 'Refresh token required.' });
    }

    let payload;
    try {
      payload = jwt.verify(token, REFRESH_TOKEN_SECRET);
    } catch {
      return res.status(401).json({ error: 'Invalid refresh token.' });
    }

    const user = await User.findByPk(payload.userId);
    if (!user || user.refreshToken !== token) {
      return res.status(401).json({ error: 'Refresh token revoked.' });
    }

    // Issue new tokens
    const accessToken = signAccessToken({ userId: user.id });
    const newRefreshToken = signRefreshToken({ userId: user.id });
    await user.update({ refreshToken: newRefreshToken });

    await publishEvent('TokenRefreshed', { userId: user.id });

    return res
      .cookie('refresh_token', newRefreshToken, {
        httpOnly: true,
        secure: NODE_ENV === 'production',
        sameSite: 'strict',
        maxAge: 1000 * 60 * 60 * 24 * 7,
      })
      .json({ accessToken });
  } catch (err) {
    return next(err);
  }
});

app.post('/api/v1/auth/logout', async (req, res, next) => {
  try {
    const token =
      req.cookies?.refresh_token ||
      req.body?.refreshToken ||
      req.headers['x-refresh-token'];

    if (token) {
      const payload = jwt.decode(token);
      if (payload?.userId) {
        await User.update({ refreshToken: null }, { where: { id: payload.userId } });
        await publishEvent('UserLoggedOut', { userId: payload.userId });
      }
    }

    res
      .clearCookie('refresh_token', {
        httpOnly: true,
        secure: NODE_ENV === 'production',
        sameSite: 'strict',
      })
      .json({ ok: true });
  } catch (err) {
    return next(err);
  }
});

// ── Health check & fallback ────────────────────────────────────────────────
app.get('/healthz', (req, res) => res.json({ ok: true, ts: new Date().toISOString() }));
app.use((req, res) => res.status(404).json({ error: 'Not Found' }));

/* -------------------------------------------------------------------------- */
/*                         Error-handling Middleware                          */
/* -------------------------------------------------------------------------- */

app.use((err, req, res, _next) => {
  logger.error('Error: %o', err);
  const status = err.status || 500;
  res.status(status).json({
    error: err.message || 'Internal Server Error',
  });
});

/* -------------------------------------------------------------------------- */
/*                              Server Launcher                               */
/* -------------------------------------------------------------------------- */

const server = http.createServer(app);

async function bootstrap() {
  try {
    // Connect DB
    await sequelize.sync({ alter: NODE_ENV !== 'production' });
    logger.info('Database connected.');

    // Connect NATS
    natsConnection = await natsConnect({ servers: NATS_URL });
    natsConnection.closed().then((err) => {
      if (err) {
        logger.error('NATS closed with error: %o', err);
      } else {
        logger.warn('NATS connection closed.');
      }
    });
    logger.info('NATS connected: %s', NATS_URL);

    // Start HTTP server
    server.listen(PORT, () => {
      logger.info('Auth service listening on port %d [%s]', PORT, NODE_ENV);
    });
  } catch (err) {
    logger.error('Failed to bootstrap service: %o', err);
    process.exit(1);
  }
}

bootstrap();

/* -------------------------------------------------------------------------- */
/*                          Graceful Shutdown logic                           */
/* -------------------------------------------------------------------------- */

const signals = ['SIGTERM', 'SIGINT', 'SIGQUIT'];
signals.forEach((sig) =>
  process.on(sig, async () => {
    logger.info('Received %s – shutting down gracefully…', sig);
    try {
      await server.close();
      if (natsConnection) await natsConnection.drain();
      await sequelize.close();
      logger.info('Clean shutdown complete. Bye 👋');
      process.exit(0);
    } catch (err) {
      logger.error('Error during shutdown: %o', err);
      process.exit(1);
    }
  })
);
```