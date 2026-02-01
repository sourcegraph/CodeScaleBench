```javascript
/**
 * PulseLearn Campus Hub – Course Service
 * --------------------------------------
 * This is the entry-point for the Course Service.  It is responsible for:
 *   • Bootstrapping the HTTP REST API (Express)
 *   • Establishing database connections (Sequelize → PostgreSQL)
 *   • Wiring Kafka producers / consumers for the event backbone
 *   • Registering middleware, routes, and global error handlers
 *   • Coordinating graceful shutdown of all resources
 *
 * NOTE:
 *   – This file purposefully keeps the service self-contained so that it can be
 *     executed in isolation for local development.  In production, individual
 *     components (routes, models, controllers, etc.) should be extracted into
 *     dedicated modules/packages to conform to the project’s component
 *     architecture guidelines.
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* Dependencies                                                             */
/* ────────────────────────────────────────────────────────────────────────── */
const http              = require('http');
const express           = require('express');
const cors              = require('cors');
const helmet            = require('helmet');
const morgan            = require('morgan');
const { body, param }   = require('express-validator');
const { StatusCodes }   = require('http-status-codes');
const { v4: uuid }      = require('uuid');
const dotenv            = require('dotenv');
const winston           = require('winston');
const { Sequelize, DataTypes, UUIDV4 } = require('sequelize');
const { Kafka }         = require('kafkajs');

/* ────────────────────────────────────────────────────────────────────────── */
/* Environment Setup                                                        */
/* ────────────────────────────────────────────────────────────────────────── */
dotenv.config();               // Load .env variables into process.env

const APP_NAME = 'course-service';

/* Centralised configuration object */
const config = {
  env            : process.env.NODE_ENV            || 'development',
  port           : Number(process.env.PORT)        || 4002,
  dbUri          : process.env.DB_URI              || 'postgres://pl:pl@localhost:5432/pulselearn',
  kafkaBrokers   : (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
  kafkaTopic     : process.env.COURSE_TOPIC        || 'pl.course.events',
  requestTimeout : Number(process.env.REQ_TIMEOUT) || 15000,
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Logger (Winston)                                                         */
/* ────────────────────────────────────────────────────────────────────────── */
const logger = winston.createLogger({
  level : config.env === 'production' ? 'info' : 'debug',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.printf(
      ({ timestamp, level, message, ...meta }) =>
        `${timestamp} [${level.toUpperCase()}] ${message} ${
          Object.keys(meta).length ? JSON.stringify(meta) : ''
        }`
    )
  ),
  transports: [
    new winston.transports.Console({ handleExceptions: true })
  ],
  exitOnError: false,
});

/* Helper wrapper for async handlers to avoid repetitive try/catch blocks */
const asyncHandler =
  (fn) =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next);

/* ────────────────────────────────────────────────────────────────────────── */
/* Database (Sequelize)                                                     */
/* ────────────────────────────────────────────────────────────────────────── */
const sequelize = new Sequelize(config.dbUri, {
  dialect        : 'postgres',
  logging        : (msg) => logger.debug(msg),
  pool           : { max: 10, min: 0, idle: 10_000 },
  define         : { underscored: true },
  retry          : { max: 3 },
});

/* Course model – kept minimal for brevity */
const Course = sequelize.define(
  'Course',
  {
    id          : { type: DataTypes.UUID, defaultValue: UUIDV4, primaryKey: true },
    title       : { type: DataTypes.STRING(255), allowNull: false },
    description : { type: DataTypes.TEXT, allowNull: true },
    instructorId: { type: DataTypes.UUID, allowNull: false, field: 'instructor_id' },
  },
  {
    tableName  : 'courses',
    timestamps : true,
  }
);

/* ────────────────────────────────────────────────────────────────────────── */
/* Kafka (Kafkajs)                                                          */
/* ────────────────────────────────────────────────────────────────────────── */
const kafka    = new Kafka({ clientId: APP_NAME, brokers: config.kafkaBrokers });
const producer = kafka.producer();
const consumer = kafka.consumer({ groupId: `${APP_NAME}-group` });

/**
 * Publishes a domain event to Kafka
 * @param {string} type  – The event name (e.g., CourseCreated)
 * @param {object} payload – Arbitrary event data
 */
const publishEvent = async (type, payload) => {
  const message = {
    key  : type,
    value: JSON.stringify({ type, timestamp: Date.now(), payload }),
  };
  await producer.send({ topic: config.kafkaTopic, messages: [message] });
  logger.info(`Event published: ${type}`, { topic: config.kafkaTopic });
};

/**
 * Subscribes to course-related domain events.
 * In a real-world scenario, the consumer would be placed in a dedicated
 * worker process so that API latency isn’t impacted by message processing.
 */
async function bootstrapConsumer() {
  await consumer.connect();
  await consumer.subscribe({ topic: config.kafkaTopic, fromBeginning: false });

  consumer.run({
    eachMessage: async ({ topic, partition, message }) => {
      try {
        const { type, payload } = JSON.parse(message.value.toString());
        logger.debug(`Received message ${type}`, { topic, partition, offset: message.offset });

        // Handle relevant events only
        if (type === 'EnrollmentCancelled') {
          // Example side-effect: archive progress, reverse charges, etc.
          logger.info(`Handling ${type} for courseId=${payload.courseId}`);
        }
      } catch (err) {
        logger.error('Failed to process kafka message', { err });
      }
    },
  });
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Express App                                                              */
/* ────────────────────────────────────────────────────────────────────────── */
const app = express();

/* Middlewares */
app.use(helmet());
app.use(cors({ origin: '*' }));
app.use(express.json({ limit: '5mb' }));
app.use(
  morgan(config.env === 'production' ? 'combined' : 'dev', {
    stream: { write: (msg) => logger.http(msg.trim()) },
  })
);

/* Healthcheck                                                                       */
app.get('/health', (req, res) => res.status(StatusCodes.OK).json({ status: 'OK', uptime: process.uptime() }));

/* ────────────────────────────────────────────────────────────────────────── */
/* Course Routes                                                             */
/* ────────────────────────────────────────────────────────────────────────── */
const router = express.Router();

/**
 * GET /courses
 * List courses with basic paging
 */
router.get(
  '/',
  asyncHandler(async (req, res) => {
    const limit  = Math.min(Number(req.query.limit) || 20, 100);
    const offset = Number(req.query.offset) || 0;

    const { rows, count } = await Course.findAndCountAll({ limit, offset, order: [['created_at', 'DESC']] });
    res.status(StatusCodes.OK).json({ data: rows, meta: { count, limit, offset } });
  })
);

/**
 * POST /courses
 * Creates a new course
 */
router.post(
  '/',
  [
    body('title').isString().isLength({ min: 3 }).withMessage('Title must be at least 3 chars'),
    body('description').optional({ nullable: true }).isString(),
    body('instructorId').isUUID().withMessage('InstructorId must be a valid UUID'),
  ],
  asyncHandler(async (req, res) => {
    const errors = body('title').validationResult?.(req) || body('instructorId').validationResult?.(req);
    if (!errors?.isEmpty()) {
      return res.status(StatusCodes.BAD_REQUEST).json({ errors: errors.array() });
    }

    const { title, description, instructorId } = req.body;
    const course = await Course.create({ title, description, instructorId });

    await publishEvent('CourseCreated', { courseId: course.id, instructorId });

    res.status(StatusCodes.CREATED).json({ data: course });
  })
);

/**
 * DELETE /courses/:courseId
 * Performs a logical deletion of a course
 */
router.delete(
  '/:courseId',
  [param('courseId').isUUID().withMessage('Invalid course id')],
  asyncHandler(async (req, res) => {
    const { courseId } = req.params;

    const course = await Course.findByPk(courseId);
    if (!course) {
      return res.status(StatusCodes.NOT_FOUND).json({ error: 'Course not found' });
    }

    await course.destroy(); // For demo; production may use soft delete/audit
    await publishEvent('CourseDeleted', { courseId });

    res.status(StatusCodes.NO_CONTENT).send();
  })
);

/* Register under /courses namespace */
app.use('/courses', router);

/* ────────────────────────────────────────────────────────────────────────── */
/* Global Error Handler                                                     */
/* ────────────────────────────────────────────────────────────────────────── */
app.use((err, _req, res, _next) => {
  logger.error(err.message, { stack: err.stack });
  const status = err.status || StatusCodes.INTERNAL_SERVER_ERROR;
  res.status(status).json({
    error  : err.message || 'Internal Server Error',
    details: config.env === 'production' ? undefined : err.stack,
  });
});

/* ────────────────────────────────────────────────────────────────────────── */
/* Server & Graceful Shutdown                                               */
/* ────────────────────────────────────────────────────────────────────────── */
let server;

/**
 * Initializes external resources, then starts the HTTP server.
 */
async function start() {
  logger.info(`Starting ${APP_NAME} in ${config.env} mode`);

  /* 1. Database connectivity */
  await sequelize.authenticate();
  logger.info('Database connection established');

  // In production, migrations would be run separately.
  await sequelize.sync();
  logger.info('Sequelize models synced');

  /* 2. Kafka connectivity */
  await producer.connect();
  await bootstrapConsumer();

  logger.info('Kafka producer & consumer ready');

  /* 3. HTTP server */
  server = http.createServer(app);

  server.listen(config.port, () => {
    logger.info(`${APP_NAME} listening on port ${config.port}`);
  });

  server.setTimeout(config.requestTimeout); // Hard timeout for hanging requests
}

/**
 * Handles shutdown signals by gracefully terminating open resources
 */
async function shutdown(signal) {
  try {
    logger.warn(`Received ${signal}. Shutting down gracefully…`);

    /* 1. Stop accepting new connections */
    if (server) {
      await new Promise((resolve) => server.close(resolve));
      logger.info('HTTP server closed');
    }

    /* 2. Flush Kafka producer & disconnect consumer */
    await producer.disconnect();
    await consumer.disconnect();
    logger.info('Kafka connections closed');

    /* 3. Close DB pool */
    await sequelize.close();
    logger.info('Database connection closed');

    process.exit(0);
  } catch (err) {
    logger.error('Graceful shutdown failed', { err });
    process.exit(1);
  }
}

/* Capture termination / restart signals */
['SIGTERM', 'SIGINT', 'SIGQUIT'].forEach((sig) => process.on(sig, () => shutdown(sig)));

/* Start the service */
start().catch((err) => {
  logger.error('Failed to bootstrap service', { err });
  process.exit(1);
});
```