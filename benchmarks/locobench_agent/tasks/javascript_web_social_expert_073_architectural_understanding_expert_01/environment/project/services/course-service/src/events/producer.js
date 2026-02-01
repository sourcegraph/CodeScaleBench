```javascript
/**
 * PulseLearn Campus Hub – Course Service
 * ---------------------------------------
 * events/producer.js
 *
 * Event producer responsible for publishing domain events originating
 * from the Course Service (e.g. CourseCreated, CourseUpdated) to the
 * message bus. We rely on NATS Streaming (Stan) for at-least-once
 * delivery semantics and use pino for structured logging.
 *
 * This module exposes a singleton instance that is:
 *  – lazily connected (first call to `publish`)
 *  – resilient (auto-reconnects with back-off and drains on shutdown)
 *  – schema-aware (basic validation and version stamping)
 *
 * Environment variables:
 *  NATS_CLUSTER_ID  – cluster identifier configured on the NATS server
 *  NATS_CLIENT_ID   – unique client id for this producer
 *  NATS_URL         – tunneling URL (e.g. nats://user:pass@localhost:4222)
 */

'use strict';

const stan    = require('node-nats-streaming');
const { v4: uuid } = require('uuid');
const pino    = require('pino');

// ---- Configuration ---------------------------------------------------------

const {
  NATS_CLUSTER_ID = 'pulselrn',
  NATS_CLIENT_ID  = `course-svc-producer-${uuid().substring(0, 8)}`,
  NATS_URL        = 'nats://localhost:4222',
  NODE_ENV        = 'development'
} = process.env;

const LOGGER = pino({
  level : NODE_ENV === 'production' ? 'info' : 'debug',
  name  : 'course-service:event-producer'
});

// Publish-side subject naming convention
const SUBJECTS = {
  COURSE_CREATED : 'course.created',
  COURSE_UPDATED : 'course.updated',
  COURSE_ARCHIVED: 'course.archived'
};

// Maximum time in milliseconds the client will wait for an ACK from NATS
const ACK_WAIT_MILLIS = 5_000;

// ---- Internal Helpers ------------------------------------------------------

/**
 * Serialise payload and enrich with envelope metadata.
 * @param {String} eventType
 * @param {Object} data
 */
function buildMessage(eventType, data) {
  return JSON.stringify({
    id         : uuid(),       // event identifier for idempotency
    version    : 1,            // domain event schema version
    timestamp  : new Date().toISOString(),
    emitter    : 'course-service',
    event      : eventType,
    payload    : data
  });
}

/**
 * Simple schema guard for course payloads.
 * In production we could delegate to a proper JSON-schema validator
 * such as Ajv; here we add a minimal safeguard so we do not publish
 * garbage messages onto the bus.
 */
function validateCoursePayload(payload = {}) {
  if (!payload.id || typeof payload.id !== 'string') {
    throw new Error('Invalid payload: "id" is required and must be a string');
  }
  if (!payload.title || typeof payload.title !== 'string') {
    throw new Error('Invalid payload: "title" is required and must be a string');
  }
}

// ---- Producer Implementation ----------------------------------------------

class EventProducer {

  constructor() {
    this._stan   = null;
    this._ready  = false;
    this._queue  = [];
    this._drainInProgress = false;
  }

  /**
   * Lazily create a connection to the NATS Streaming cluster.
   * Connection is initialised only once per process.
   * @returns {Promise<void>}
   */
  async _connect() {
    if (this._stan || this._ready) return;
    LOGGER.info({ cluster: NATS_CLUSTER_ID, client: NATS_CLIENT_ID, url: NATS_URL },
                'Connecting to NATS Streaming…');

    this._stan = stan.connect(NATS_CLUSTER_ID, NATS_CLIENT_ID, { url: NATS_URL });

    // Promisify connection lifecycle
    await new Promise((resolve, reject) => {
      const onConnect = () => {
        this._ready = true;
        LOGGER.info('NATS Streaming connection established ✅');
        this._flushQueue(); // emit messages that were queued before ready
        resolve();
      };

      const onError = (err) => {
        LOGGER.error({ err }, 'Unable to connect to NATS Streaming ❌');
        reject(err);
      };

      this._stan.once('connect', onConnect);
      this._stan.once('error',   onError);
    });

    // Attach common listeners AFTER the initial promise resolution
    this._stan.on('close',  () => LOGGER.warn('NATS connection closed'));
    this._stan.on('reconnect', () => LOGGER.info('NATS reconnected'));
    this._stan.on('disconnect', () => LOGGER.warn('NATS disconnected'));
  }

  /**
   * Drain NATS connection gracefully before process exit.
   */
  async close() {
    if (!this._stan || this._drainInProgress) return;
    this._drainInProgress = true;

    LOGGER.info('Draining NATS Streaming connection before shutdown…');
    await new Promise((resolve) => {
      this._stan.drain(() => {
        LOGGER.info('NATS drain complete, closing connection');
        this._stan.close();
        resolve();
      });
    });
  }

  /**
   * Publish raw subject + message
   * @param {String} subject
   * @param {String} message   – already JSON serialised
   * @param {Object} options   – optional metadata (e.g. persistentName)
   * @returns {Promise<void>}
   */
  async _publish(subject, message, options = {}) {
    await this._connect();

    return new Promise((resolve, reject) => {
      const guid = this._stan.publish(subject, message, (err, ackGuid) => {
        if (err) {
          LOGGER.error({ err, subject, guid }, 'Failed to publish message');
          return reject(err);
        }
        LOGGER.debug({ subject, guid: ackGuid }, 'Event published');
        resolve();
      });

      // Fallback: if no ack within ACK_WAIT_MILLIS, reject
      setTimeout(() => {
        reject(new Error(`ACK timeout after ${ACK_WAIT_MILLIS}ms for guid: ${guid}`));
      }, ACK_WAIT_MILLIS).unref();
    });
  }

  /**
   * Queue messages if connection hasn't been established yet.
   * This prevents any writes being lost during cold starts.
   */
  _queueMessage(subject, message) {
    this._queue.push({ subject, message });
  }

  _flushQueue() {
    if (!this._queue.length || !this._ready) return;

    LOGGER.info(`Flushing ${this._queue.length} queued event(s)`);
    this._queue.forEach(({ subject, message }) => {
      this._stan.publish(subject, message, (err) => {
        if (err) {
          LOGGER.error({ subject, err }, 'Failed to publish queued event');
        }
      });
    });
    this._queue.length = 0;
  }

  // ---------------------------------------------------
  // Domain-specific API
  // ---------------------------------------------------

  /**
   * Course Created domain event publisher.
   * @param {Object} course – plain JS object { id, title, … }
   */
  async courseCreated(course) {
    try {
      validateCoursePayload(course);
      const msg = buildMessage('CourseCreated', course);
      await this._publish(SUBJECTS.COURSE_CREATED, msg);
    } catch (err) {
      LOGGER.error({ err, course }, 'Unable to publish CourseCreated event');
      throw err;
    }
  }

  /**
   * Course Updated domain event publisher.
   * @param {Object} course – plain JS object { id, title, … }
   */
  async courseUpdated(course) {
    try {
      validateCoursePayload(course);
      const msg = buildMessage('CourseUpdated', course);
      await this._publish(SUBJECTS.COURSE_UPDATED, msg);
    } catch (err) {
      LOGGER.error({ err, course }, 'Unable to publish CourseUpdated event');
      throw err;
    }
  }

  /**
   * Course archived event publisher.
   * @param {Object} course – minimal object { id, archivedAt }
   */
  async courseArchived(course) {
    if (!course.id) {
      throw new Error('Invalid payload: "id" is required for archive event');
    }

    const msg = buildMessage('CourseArchived', course);
    try {
      await this._publish(SUBJECTS.COURSE_ARCHIVED, msg);
    } catch (err) {
      LOGGER.error({ err, course }, 'Unable to publish CourseArchived event');
      throw err;
    }
  }
}

// ---- Singleton Export ------------------------------------------------------

const producerInstance = new EventProducer();

// Clean up before the Node process is terminated
['SIGINT', 'SIGTERM', 'SIGQUIT'].forEach((signal) => {
  process.on(signal, async () => {
    LOGGER.info({ signal }, 'Received termination signal');
    await producerInstance.close();
    process.exit(0);
  });
});

module.exports = producerInstance;
```