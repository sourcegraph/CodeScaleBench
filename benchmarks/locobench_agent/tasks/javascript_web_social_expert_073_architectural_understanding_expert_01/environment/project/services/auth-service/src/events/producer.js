```javascript
/**
 * PulseLearn Campus Hub – Authentication Service
 * Event Producer
 *
 * This module is responsible for publishing authentication-domain events
 * (UserRegistered, UserLoggedIn, PasswordResetRequested, SessionExpired, etc.)
 * to the central event backbone (NATS JetStream).  All events are JSON-encoded,
 * versioned, and wrapped in a common envelope that carries correlation and
 * causation metadata to enable end-to-end tracing across micro-services.
 *
 * NOTE:
 *   – This file purposefully has no knowledge of web frameworks or database
 *     details.  Its single responsibility is to provide a resilient, observable
 *     publishing mechanism for domain events originating from the auth service.
 */

'use strict';

const { connect, JSONCodec, nanos } = require('nats');
const { v4: uuid } = require('uuid');
const EventEmitter = require('events');
const logger = require('../utils/logger'); // Winston-based logger shared across services
const { natsConfig } = require('../config'); // Centralised config loader

// Constants ------------------------------------------------------------------
const EVENT_STREAM         = 'pl.auth.events';  // JetStream stream name
const DEFAULT_PUBLISH_OPTS = { timeout: 5_000 }; // ms

/**
 * Mapping of semantic event names to JetStream subjects.
 * Subject naming convention:   <service>.<boundedContext>.<entity>.<verb>
 * Example: 'auth.user.registered'
 */
const SUBJECTS = {
  USER_REGISTERED:        'auth.user.registered',
  USER_LOGGED_IN:         'auth.user.loggedIn',
  PASSWORD_RESET_REQUEST: 'auth.user.passwordResetRequested',
  SESSION_EXPIRED:        'auth.session.expired'
};

// ---------------------------------------------------------------------------
// Event Envelope Helpers
// ---------------------------------------------------------------------------

/**
 * Wraps the raw payload in a versioned envelope so any consumer
 * can safely parse, validate, and evolve schemas over time.
 *
 * @param {string}  type           – fully qualified event type
 * @param {object}  data           – domain payload
 * @param {object}  [meta]         – optional metadata overrides
 * @returns {object} envelope
 */
function createEnvelope(type, data, meta = {}) {
  return {
    id:            uuid(),                         // unique event id
    type,                                          
    timestamp:     new Date().toISOString(),       // ISO-8601
    data,
    meta: {
      correlationId: meta.correlationId || uuid(),
      causationId:   meta.causationId   || null,
      version:       meta.version       || 1,
      ...meta.extras // any custom metadata
    }
  };
}

// ---------------------------------------------------------------------------
// Producer Class
// ---------------------------------------------------------------------------

class EventProducer extends EventEmitter {
  constructor() {
    super();

    this._nc       = null;   // NatsConnection
    this._js       = null;   // JetStreamClient
    this._codec    = JSONCodec();
    this._queue    = [];     // message queue for when broker unavailable
    this._isClosed = false;
  }

  // ------------- Public API -----------------------------------------------

  /**
   * Bootstraps the connection.  Returns immediately if already connected.
   * Consumers should call await EventProducer.ready() before first publish.
   */
  async ready() {
    if (this._nc) return;
    await this._connect();
  }

  /**
   * Generic publish function.  Awaits broker ACK if confirmed is true.
   *
   * @param {string} subject                 – NATS subject
   * @param {object} envelope                – event envelope created with `createEnvelope`
   * @param {boolean} [confirmed=true]       – wait for JetStream acknowledgement
   */
  async publish(subject, envelope, confirmed = true) {
    if (this._isClosed) {
      throw new Error('EventProducer is closed.  Cannot publish new messages.');
    }

    if (!this._nc) {
      // Not yet connected: queue the publication request.
      this._queue.push({ subject, envelope, confirmed });
      return;
    }

    try {
      const encoded = this._codec.encode(envelope);
      const pa = await this._js.publish(subject, encoded, DEFAULT_PUBLISH_OPTS);
      if (confirmed) {
        logger.debug(`Event published to ${subject} (seq=${pa.seq})`);
      }
    } catch (err) {
      logger.error(`Failed to publish event to ${subject}: ${err.message}`);
      // Push back onto queue for later retry
      this._queue.push({ subject, envelope, confirmed });
    }
  }

  // -----------------------------------------------------------------------
  // Domain-specific helpers (syntactic sugar)
  // -----------------------------------------------------------------------

  async userRegistered(user, meta = {}) {
    const envelope = createEnvelope('UserRegistered', { user }, meta);
    await this.publish(SUBJECTS.USER_REGISTERED, envelope);
  }

  async userLoggedIn(session, meta = {}) {
    const envelope = createEnvelope('UserLoggedIn', { session }, meta);
    await this.publish(SUBJECTS.USER_LOGGED_IN, envelope);
  }

  async passwordResetRequested(user, meta = {}) {
    const envelope = createEnvelope('PasswordResetRequested', { user }, meta);
    await this.publish(SUBJECTS.PASSWORD_RESET_REQUEST, envelope);
  }

  async sessionExpired(sessionId, meta = {}) {
    const envelope = createEnvelope('SessionExpired', { sessionId }, meta);
    await this.publish(SUBJECTS.SESSION_EXPIRED, envelope);
  }

  // ------------- Lifecycle -------------------------------------------------

  /**
   * Gracefully close the underlying broker connection.
   */
  async close() {
    if (this._isClosed) return;
    this._isClosed = true;

    try {
      await this._flushQueue();
      if (this._nc) {
        await this._nc.drain();
        await this._nc.close();
      }
      this._nc = null;
      this._js = null;
      logger.info('EventProducer connection closed gracefully.');
    } catch (err) {
      logger.warn(`EventProducer encountered error during close: ${err.message}`);
    }
  }

  // -----------------------------------------------------------------------
  // Internal implementation details
  // -----------------------------------------------------------------------

  async _connect() {
    logger.info(`Connecting to NATS @ ${natsConfig.url} ...`);
    this._nc = await connect({
      servers:            natsConfig.url,
      name:               natsConfig.producerName || `auth-service-${uuid()}`,
      maxReconnectAttempts: natsConfig.maxReconnectAttempts ?? 10,
      reconnectTimeWait:    natsConfig.reconnectTimeWait ?? 4_000
    });

    this._js = this._nc.jetstream();

    this._registerNatsListeners();
    await this._flushQueue(); // drain any messages queued before connection
  }

  _registerNatsListeners() {
    this._nc.status().then(async (iter) => {
      for await (const status of iter) {
        switch (status.type) {
          case 'disconnect':
            logger.warn('Producer disconnected from NATS.');
            this.emit('disconnect');
            break;
          case 'reconnecting':
            logger.warn('Producer attempting to reconnect to NATS...');
            this.emit('reconnecting');
            break;
          case 'reconnect':
            logger.info(`Producer reconnected to NATS (connected in ${nanos(status.data)} ns)`);
            this.emit('reconnect');
            break;
          case 'error':
            logger.error(`NATS client error: ${status.data}`);
            this.emit('error', status.data);
            break;
          default:
            logger.debug(`NATS status: ${status.type}`, status.data);
        }
      }
    }).catch(err => {
      logger.error(`Unable to monitor NATS client status: ${err.message}`);
    });

    // Handle process termination signals for graceful shutdown
    ['SIGINT', 'SIGTERM', 'SIGQUIT'].forEach(sig => {
      process.on(sig, async () => {
        logger.info(`Received ${sig}.  Draining event producer...`);
        await this.close();
        process.exit(0);
      });
    });
  }

  /**
   * Flushes the internal message queue by attempting to publish
   * each queued item sequentially.  Messages that still fail are
   * re-queued for later retry.
   */
  async _flushQueue() {
    if (!this._nc || this._nc.isClosed()) return;
    if (!this._queue.length) return;

    logger.info(`Flushing ${this._queue.length} queued events…`);
    const originalQueue = this._queue.splice(0); // copy & clear

    for (const msg of originalQueue) {
      try {
        await this.publish(msg.subject, msg.envelope, msg.confirmed);
      } catch (err) {
        // If we still fail, push back to the end of the queue.
        this._queue.push(msg);
        logger.warn(`Message re-queued due to publish failure: ${err.message}`);
      }
    }

    if (this._queue.length) {
      logger.warn(`${this._queue.length} messages remain queued (broker offline?).`);
    } else {
      logger.info('All queued events successfully published.');
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton Export
// ---------------------------------------------------------------------------
module.exports = new EventProducer();
```