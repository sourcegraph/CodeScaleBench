```javascript
'use strict';

/**
 * PulseLearn Course Service – Application Bootstrapper
 * ----------------------------------------------------
 * Exposes RESTful endpoints to manage courses, publishes / consumes
 * domain events over Kafka, and persists data in PostgreSQL via Sequelize.
 */

import 'dotenv/config';
import http from 'http';
import express from 'express';
import helmet from 'helmet';
import cors from 'cors';
import compression from 'compression';
import morgan from 'morgan';
import { Sequelize, DataTypes } from 'sequelize';
import { Kafka, logLevel } from 'kafkajs';

/* -------------------------------------------------------------------------- */
/*                                 Config                                     */
/* -------------------------------------------------------------------------- */

const {
  NODE_ENV = 'development',
  PORT = 4002,
  DATABASE_URL = 'postgres://pulselearn:pulselearn@localhost:5432/pulselearn',
  KAFKA_BROKERS = 'localhost:9092',
  KAFKA_CLIENT_ID = 'course-service',
  KAFKA_GROUP_ID = 'course-service-consumer',
  SERVICE_NAME = 'course-service',
} = process.env;

/* -------------------------------------------------------------------------- */
/*                              Express Setup                                 */
/* -------------------------------------------------------------------------- */

const app = express();

app.disable('x-powered-by');
app.set('trust proxy', 1);

app.use(helmet());
app.use(
  cors({
    origin: '*', // TODO: whitelist in prod
    methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
  })
);
app.use(compression());
app.use(express.json({ limit: '3mb' }));
app.use(morgan(NODE_ENV === 'production' ? 'combined' : 'dev'));

/* -------------------------------------------------------------------------- */
/*                              Sequelize ORM                                 */
/* -------------------------------------------------------------------------- */

const sequelize = new Sequelize(DATABASE_URL, {
  dialect: 'postgres',
  pool: { max: 10, min: 1, idle: 10000 },
  logging: NODE_ENV === 'production' ? false : console.log,
});

const Course = sequelize.define(
  'Course',
  {
    id: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    title: { type: DataTypes.STRING(255), allowNull: false },
    description: { type: DataTypes.TEXT, allowNull: true },
    price: { type: DataTypes.DECIMAL(10, 2), allowNull: false, defaultValue: 0 },
    isPublished: { type: DataTypes.BOOLEAN, defaultValue: false },
  },
  {
    tableName: 'courses',
    underscored: true,
    timestamps: true,
  }
);

/* -------------------------------------------------------------------------- */
/*                                Kafka                                       */
/* -------------------------------------------------------------------------- */

const kafka = new Kafka({
  clientId: KAFKA_CLIENT_ID,
  brokers: KAFKA_BROKERS.split(','),
  logLevel: NODE_ENV === 'production' ? logLevel.ERROR : logLevel.INFO,
});

const producer = kafka.producer({ allowAutoTopicCreation: true });
const consumer = kafka.consumer({ groupId: KAFKA_GROUP_ID });

async function publishEvent(topic, payload) {
  await producer.send({
    topic,
    messages: [{ key: payload.id || null, value: JSON.stringify(payload) }],
  });
}

async function bootstrapConsumer() {
  await consumer.connect();
  await consumer.subscribe({ topic: 'AssignmentSubmitted', fromBeginning: false });

  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      try {
        const payload = JSON.parse(message.value.toString());

        if (topic === 'AssignmentSubmitted') {
          await handleAssignmentSubmitted(payload);
        }
      } catch (err) {
        /* eslint-disable no-console */
        console.error(`[${SERVICE_NAME}] failed processing message`, err);
        /* eslint-enable no-console */
        // TODO: dead-letter queue
      }
    },
  });
}

async function handleAssignmentSubmitted({ courseId, studentId }) {
  /* Business logic placeholder */
  await Course.update({ updatedAt: new Date() }, { where: { id: courseId } });
  await publishEvent('CourseProgressUpdated', { courseId, studentId, ts: Date.now() });
}

/* -------------------------------------------------------------------------- */
/*                                Routes                                      */
/* -------------------------------------------------------------------------- */

const router = express.Router();

/* Health / readiness probes */
router.get('/health', (req, res) => res.json({ status: 'ok' }));

router.get('/courses', async (_req, res, next) => {
  try {
    const courses = await Course.findAll({ where: { isPublished: true } });
    res.json(courses);
  } catch (err) {
    next(err);
  }
});

router.post('/courses', async (req, res, next) => {
  try {
    const { title, description, price } = req.body;
    const course = await Course.create({ title, description, price });

    await publishEvent('CourseCreated', { courseId: course.id, title, ts: Date.now() });
    res.status(201).json(course);
  } catch (err) {
    next(err);
  }
});

router.patch('/courses/:id/publish', async (req, res, next) => {
  try {
    const { id } = req.params;
    const [affected] = await Course.update({ isPublished: true }, { where: { id } });

    if (!affected) return res.status(404).json({ error: 'Course not found' });

    await publishEvent('CoursePublished', { courseId: id, ts: Date.now() });
    res.sendStatus(204);
  } catch (err) {
    next(err);
  }
});

app.use('/api/v1', router);

/* -------------------------------------------------------------------------- */
/*                           Central Error Handler                            */
/* -------------------------------------------------------------------------- */

app.use((err, _req, res, _next) => {
  /* eslint-disable no-console */
  if (NODE_ENV !== 'test') console.error(err);
  /* eslint-enable no-console */

  const status = err.status || 500;
  res.status(status).json({
    error: err.message || 'Internal Server Error',
    ...(NODE_ENV === 'development' && { stack: err.stack }),
  });
});

/* -------------------------------------------------------------------------- */
/*                          Server & Bootstrap                                */
/* -------------------------------------------------------------------------- */

const server = http.createServer(app);

async function init() {
  try {
    await sequelize.authenticate();
    if (NODE_ENV !== 'production') await sequelize.sync({ alter: true });

    await producer.connect();
    await bootstrapConsumer();

    server.listen(PORT, () =>
      /* eslint-disable no-console */
      console.log(`[${SERVICE_NAME}] listening on :${PORT}`)
      /* eslint-enable no-console */
    );
  } catch (err) {
    /* eslint-disable no-console */
    console.error(`[${SERVICE_NAME}] failed to start`, err);
    /* eslint-enable no-console */
    process.exit(1);
  }
}

init();

/* -------------------------------------------------------------------------- */
/*                          Graceful Shutdown                                 */
/* -------------------------------------------------------------------------- */

async function shutdown(signal) {
  /* eslint-disable no-console */
  console.log(`[${SERVICE_NAME}] ${signal} received – shutting down`);
  /* eslint-enable no-console */

  try {
    await consumer.disconnect();
    await producer.disconnect();
    await sequelize.close();

    server.close(() => process.exit(0));
  } catch (err) {
    /* eslint-disable no-console */
    console.error(`[${SERVICE_NAME}] error during shutdown`, err);
    /* eslint-enable no-console */
    process.exit(1);
  }
}

['SIGTERM', 'SIGINT'].forEach((sig) => process.on(sig, () => shutdown(sig)));

/* -------------------------------------------------------------------------- */
/*                           Exports (Testing)                                */
/* -------------------------------------------------------------------------- */

export default app;
```