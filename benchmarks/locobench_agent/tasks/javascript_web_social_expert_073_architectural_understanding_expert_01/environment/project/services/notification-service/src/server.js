```javascript
/**
 * PulseLearn Campus Hub – Notification Service
 * File: src/server.js
 *
 * Responsibilities:
 * 1. Listen to domain events from NATS and persist user–facing notifications
 * 2. Expose a REST API for querying / mutating notifications
 * 3. Push real-time notification updates to WebSocket clients (Socket.IO)
 *
 * The file is intentionally self-contained so that `node src/server.js`
 * starts a fully–functional service, assuming required infra is reachable.
 */

/* ──────────────────────────────────────────────────────────────────────────────
 * Environment & Global Setup
 * ─────────────────────────────────────────────────────────────────────────── */
require('dotenv').config(); // Load .env first
require('express-async-errors'); // ↞ surface async route errors to error handler

const http = require('http');
const express = require('express');
const { Server: SocketIOServer } = require('socket.io');
const { connect: natsConnect, StringCodec, JSONCodec } = require('nats');
const { Pool } = require('pg');
const jwt = require('jsonwebtoken');
const morgan = require('morgan');
const winston = require('winston');
const { v4: uuid } = require('uuid');

/* ──────────────────────────────────────────────────────────────────────────────
 * Config
 * ─────────────────────────────────────────────────────────────────────────── */

const CONFIG = {
  serviceName: process.env.SERVICE_NAME || 'notification-service',
  port: parseInt(process.env.PORT, 10) || 4005,
  allowedOrigins: (process.env.ALLOWED_ORIGINS || '')
    .split(',')
    .map((o) => o.trim())
    .filter(Boolean),

  // Security
  jwtPublicKey: process.env.JWT_PUBLIC_KEY || 'insecure-dev-key', // For demo only

  // PostgreSQL
  db: {
    connectionString:
      process.env.DATABASE_URL ||
      'postgresql://postgres:postgres@localhost:5432/pulselearn',
  },

  // NATS
  nats: {
    servers: (process.env.NATS_URL || 'nats://localhost:4222')
      .split(',')
      .map((s) => s.trim()),
    // All events published by PulseLearn use the wildcard: campus.>
    subscriptionSubject: process.env.NATS_SUBJECT || 'campus.>',
    durableName: process.env.NATS_DURABLE_NAME || 'notification-service-durable',
  },
};

/* ──────────────────────────────────────────────────────────────────────────────
 * Logger
 * ─────────────────────────────────────────────────────────────────────────── */

const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  defaultMeta: { service: CONFIG.serviceName },
  transports: [
    new winston.transports.Console({
      format: winston.format.combine(
        winston.format.colorize(),
        winston.format.timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
        winston.format.printf(
          ({ timestamp, level, message, ...meta }) =>
            `${timestamp} ${level} ${message}${
              Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : ''
            }`
        )
      ),
    }),
  ],
});

/* ──────────────────────────────────────────────────────────────────────────────
 * Database Layer
 * ─────────────────────────────────────────────────────────────────────────── */

const db = new Pool({
  connectionString: CONFIG.db.connectionString,
  max: 10,
});

db.on('error', (err) => {
  logger.error('PostgreSQL pool error', { err });
});

async function ensureSchema() {
  await db.query(`
    CREATE TABLE IF NOT EXISTS notifications (
      id UUID PRIMARY KEY,
      user_id UUID NOT NULL,
      event_type TEXT NOT NULL,
      payload JSONB NOT NULL,
      is_read BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_notifications_user_id_created_at
      ON notifications (user_id, created_at DESC);
  `);
  logger.info('✅  Notifications table is ready');
}

/* ──────────────────────────────────────────────────────────────────────────────
 * Repository Layer
 * ─────────────────────────────────────────────────────────────────────────── */

const notificationRepo = {
  async add({ userId, eventType, payload }) {
    const id = uuid();
    await db.query(
      `
      INSERT INTO notifications (id, user_id, event_type, payload)
      VALUES ($1, $2, $3, $4)
    `,
      [id, userId, eventType, payload]
    );
    return { id, userId, eventType, payload, isRead: false, createdAt: new Date() };
  },

  async markRead(notificationId, userId) {
    const { rows } = await db.query(
      `
      UPDATE notifications
      SET is_read = TRUE
      WHERE id = $1 AND user_id = $2
      RETURNING *
    `,
      [notificationId, userId]
    );
    return rows[0] || null;
  },

  async listByUser(userId, { limit = 50, after } = {}) {
    const params = [userId, limit];
    const afterClause = after ? `AND created_at < $3` : '';
    if (after) params.push(after);
    const { rows } = await db.query(
      `
      SELECT *
      FROM notifications
      WHERE user_id = $1
        ${afterClause}
      ORDER BY created_at DESC
      LIMIT $2
    `,
      params
    );
    return rows;
  },
};

/* ──────────────────────────────────────────────────────────────────────────────
 * Authentication Middleware
 * ─────────────────────────────────────────────────────────────────────────── */

function authenticateHttp(req, res, next) {
  try {
    const auth = req.headers.authorization || '';
    const [, token] = auth.split(' ');
    if (!token) {
      return res.status(401).json({ error: 'Missing token' });
    }
    const payload = jwt.verify(token, CONFIG.jwtPublicKey, {
      algorithms: ['RS256', 'HS256'],
    });
    req.user = payload; // user.id, user.role, …
    next();
  } catch (err) {
    res.status(401).json({ error: 'Invalid token' });
  }
}

function authenticateSocket(socket, next) {
  try {
    const token = socket.handshake.auth.token;
    if (!token) return next(new Error('Missing token'));
    const payload = jwt.verify(token, CONFIG.jwtPublicKey, {
      algorithms: ['RS256', 'HS256'],
    });
    socket.user = payload;
    next();
  } catch (err) {
    next(new Error('Invalid token'));
  }
}

/* ──────────────────────────────────────────────────────────────────────────────
 * Express App & Routes
 * ─────────────────────────────────────────────────────────────────────────── */

const app = express();

// HTTP logging
app.use(
  morgan('combined', {
    stream: { write: (msg) => logger.http(msg.trim()) },
  })
);

app.use(express.json());

// Health check
app.get('/healthz', (_req, res) => res.json({ status: 'ok' }));

// Authenticated routes
app.use('/api', authenticateHttp);

// GET /api/notifications
app.get('/api/notifications', async (req, res) => {
  const { after, limit } = req.query;
  const list = await notificationRepo.listByUser(req.user.id, {
    after,
    limit: parseInt(limit, 10) || 50,
  });
  res.json(list);
});

// PATCH /api/notifications/:id/read
app.patch('/api/notifications/:id/read', async (req, res) => {
  const { id } = req.params;
  const updated = await notificationRepo.markRead(id, req.user.id);
  if (!updated) {
    return res.status(404).json({ error: 'Notification not found' });
  }
  res.json(updated);
});

// Centralised error handler
app.use((err, _req, res, _next) => {
  logger.error('Unhandled error', { err });
  res.status(500).json({ error: 'Internal Server Error' });
});

/* ──────────────────────────────────────────────────────────────────────────────
 * WebSocket Layer
 * ─────────────────────────────────────────────────────────────────────────── */

const httpServer = http.createServer(app);

const io = new SocketIOServer(httpServer, {
  cors: {
    origin: (origin, callback) => {
      // Allow requests with no origin (e.g., mobile apps, curl)
      if (!origin) return callback(null, true);
      if (CONFIG.allowedOrigins.includes(origin)) return callback(null, true);
      return callback(new Error('Not allowed by CORS'));
    },
    methods: ['GET', 'POST', 'PATCH'],
    credentials: true,
  },
});

io.use(authenticateSocket);

io.on('connection', (socket) => {
  const userId = socket.user.id;
  logger.info(`🔌  User connected via WS`, { userId });

  socket.join(userId); // Each user has a private room

  socket.on('disconnect', (reason) => {
    logger.info(`🔌  User disconnected`, { userId, reason });
  });
});

/* ──────────────────────────────────────────────────────────────────────────────
 * NATS Integration
 * ─────────────────────────────────────────────────────────────────────────── */

const jc = JSONCodec();
const sc = StringCodec(); // fallback

async function bootstrapNats() {
  const nc = await natsConnect({
    servers: CONFIG.nats.servers,
    name: `${CONFIG.serviceName}-${uuid()}`,
  });

  logger.info(`🛩️  Connected to NATS`, { servers: CONFIG.nats.servers });

  // Graceful NATS shutdown
  const cleanup = () => {
    nc.draining()
      .then(() => logger.info('NATS connection drained'))
      .catch((err) => logger.error('Error draining NATS', { err }));
  };
  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);

  // Subscribe to campus events
  const sub = nc.subscribe(CONFIG.nats.subscriptionSubject, {
    queue: CONFIG.nats.durableName,
  });

  (async () => {
    for await (const msg of sub) {
      let data;
      try {
        data = jc.decode(msg.data);
      } catch (_) {
        data = sc.decode(msg.data);
      }

      handleDomainEvent(msg.subject, data).catch((err) =>
        logger.error('Failed handling domain event', { subject: msg.subject, err })
      );
    }
  })().catch((err) => logger.error('NATS subscription error', { err }));
}

async function handleDomainEvent(subject, event) {
  /*
   * A subject might look like:
   * campus.assignment.submitted
   * campus.quiz.completed
   * campus.badge.awarded
   */
  const eventType = subject.replace(/^campus\./, '');
  const userId = event.recipientId || event.userId; // Domain payload contract
  if (!userId) {
    logger.warn('Event has no userId, ignoring', { subject, event });
    return;
  }

  const notification = await notificationRepo.add({
    userId,
    eventType,
    payload: event,
  });

  // Broadcast via WS
  io.to(userId).emit('notification', notification);
  logger.info('📨  Notification delivered', {
    userId,
    notificationId: notification.id,
  });
}

/* ──────────────────────────────────────────────────────────────────────────────
 * Bootstrap
 * ─────────────────────────────────────────────────────────────────────────── */

async function start() {
  try {
    await ensureSchema();
    await bootstrapNats();

    httpServer.listen(CONFIG.port, () => {
      logger.info(`🚀  ${CONFIG.serviceName} running`, { port: CONFIG.port });
    });

    // Graceful HTTP shutdown
    const shutdown = () => {
      logger.info('Shutting down HTTP server…');
      httpServer.close(() => {
        logger.info('HTTP server closed');
        db.end(() => {
          logger.info('DB pool closed');
          process.exit(0);
        });
      });
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
  } catch (err) {
    logger.error('Failed to bootstrap service', { err });
    process.exit(1);
  }
}

start();
```