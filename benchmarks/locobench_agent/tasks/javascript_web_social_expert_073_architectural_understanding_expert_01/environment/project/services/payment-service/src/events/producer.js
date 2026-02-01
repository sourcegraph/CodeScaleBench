```javascript
/**
 * pulselearn-campus-hub/services/payment-service/src/events/producer.js
 *
 * A type–safe Kafka event producer used by the payment-service to broadcast
 * payment domain events (PaymentInitiated, PaymentCompleted, PaymentFailed,
 * RefundProcessed) to the PulseLearn Campus Hub event backbone.
 *
 * The module exposes a singleton instance (`paymentEventProducer`) that is
 * lazily connected on first use. All outbound events are JSON-schema validated
 * using AJV before they hit the wire to guarantee contract integrity across
 * micro-services.
 *
 * Production-ready features:
 *   • Secure Kafka connection with SSL/SASL  (if configured)
 *   • Built-in retry & exponential back-off for transient broker errors
 *   • Schema validation w/ detailed diagnostics
 *   • Winston logging for structured observability
 *   • Graceful shutdown hooks for Node.js process signals
 */

'use strict';

const { Kafka, logLevel } = require('kafkajs');
const Ajv                     = require('ajv').default;
const addFormats              = require('ajv-formats');
const { v4: uuid }            = require('uuid');
const winston                 = require('winston');

// -----------------------------------------------------------------------------
// Configuration
// -----------------------------------------------------------------------------
const {
  KAFKA_BROKERS              = 'localhost:9092',
  KAFKA_CLIENT_ID            = 'payment-service',
  KAFKA_SSL                  = 'false',
  KAFKA_SASL_MECHANISM,
  KAFKA_SASL_USERNAME,
  KAFKA_SASL_PASSWORD,
  NODE_ENV                   = 'development',
  PAYMENT_TOPIC              = 'payments',
  EVENTS_VERSION             = 'v1'
} = process.env;

/**
 * Winston logger shared across the payment-service.
 * Adjust transports based on the environment.
 */
const logger = winston.createLogger({
  level       : NODE_ENV === 'production' ? 'info' : 'debug',
  format      : winston.format.combine(
    winston.format.timestamp(),
    winston.format.json()
  ),
  transports  : [
    new winston.transports.Console({
      stderrLevels : ['error']
    })
  ]
});

// -----------------------------------------------------------------------------
// JSON Schemas for Domain Events
// -----------------------------------------------------------------------------
const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);

const baseEventSchema = {
  $id       : 'BaseEvent',
  type      : 'object',
  required  : ['id', 'type', 'occurredAt', 'version', 'data'],
  additionalProperties: false,
  properties: {
    id         : { type: 'string', format: 'uuid' },
    type       : { type: 'string' },
    occurredAt : { type: 'string', format: 'date-time' },
    version    : { type: 'string' },
    correlationId: { type: 'string' },
    data       : { type: 'object' }
  }
};

// Extend base schema for each specific event
const paymentInitiatedSchema = {
  ...baseEventSchema,
  $id       : 'PaymentInitiated',
  properties: {
    ...baseEventSchema.properties,
    type: { const: 'PaymentInitiated' },
    data: {
      type       : 'object',
      required   : ['paymentId', 'userId', 'amount', 'currency', 'method'],
      properties : {
        paymentId : { type: 'string', format: 'uuid' },
        userId    : { type: 'string', format: 'uuid' },
        amount    : { type: 'number', minimum: 0 },
        currency  : { type: 'string', minLength: 3, maxLength: 3 },
        method    : { type: 'string' }
      }
    }
  }
};

const paymentCompletedSchema = {
  ...baseEventSchema,
  $id       : 'PaymentCompleted',
  properties: {
    ...baseEventSchema.properties,
    type: { const: 'PaymentCompleted' },
    data: {
      type       : 'object',
      required   : ['paymentId', 'transactionId'],
      properties : {
        paymentId    : { type: 'string', format: 'uuid' },
        transactionId: { type: 'string' }
      }
    }
  }
};

const paymentFailedSchema = {
  ...baseEventSchema,
  $id       : 'PaymentFailed',
  properties: {
    ...baseEventSchema.properties,
    type: { const: 'PaymentFailed' },
    data: {
      type       : 'object',
      required   : ['paymentId', 'reason'],
      properties : {
        paymentId : { type: 'string', format: 'uuid' },
        reason    : { type: 'string' }
      }
    }
  }
};

const refundProcessedSchema = {
  ...baseEventSchema,
  $id       : 'RefundProcessed',
  properties: {
    ...baseEventSchema.properties,
    type: { const: 'RefundProcessed' },
    data: {
      type       : 'object',
      required   : ['paymentId', 'refundId', 'amount'],
      properties : {
        paymentId : { type: 'string', format: 'uuid' },
        refundId  : { type: 'string', format: 'uuid' },
        amount    : { type: 'number', minimum: 0 }
      }
    }
  }
};

// Pre-compile validators for performance
const validators = {
  PaymentInitiated : ajv.compile(paymentInitiatedSchema),
  PaymentCompleted : ajv.compile(paymentCompletedSchema),
  PaymentFailed    : ajv.compile(paymentFailedSchema),
  RefundProcessed  : ajv.compile(refundProcessedSchema)
};

// -----------------------------------------------------------------------------
// Kafka Producer Implementation
// -----------------------------------------------------------------------------
class PaymentEventProducer {
  constructor() {
    this._kafka = new Kafka({
      clientId: KAFKA_CLIENT_ID,
      brokers : KAFKA_BROKERS.split(','),
      ssl     : KAFKA_SSL === 'true',
      sasl    : KAFKA_SASL_MECHANISM
        ? {
            mechanism: KAFKA_SASL_MECHANISM,
            username : KAFKA_SASL_USERNAME,
            password : KAFKA_SASL_PASSWORD
          }
        : undefined,
      logLevel: logLevel.NOTHING // we rely on Winston
    });

    this._producer = this._kafka.producer({
      // Increase default 30000 ms requestTimeout for large clusters
      allowAutoTopicCreation: false,
      idempotent            : true,
      maxInFlightRequests   : 5
    });

    this._connected = false;
  }

  /**
   * Connect to Kafka lazily (called on first publish attempt).
   */
  async _connect() {
    if (this._connected) return;

    try {
      await this._producer.connect();
      this._connected = true;

      logger.info('Kafka producer connected', {
        service: 'payment-service',
        brokers: KAFKA_BROKERS
      });

      // Ensure process signals are handled only once
      ['SIGINT', 'SIGTERM', 'beforeExit', 'uncaughtException'].forEach(signal => {
        process.once(signal, async () => {
          try {
            await this.disconnect();
            process.exit(0);
          } catch (err) {
            logger.error('Error during graceful shutdown', { error: err.message });
            process.exit(1);
          }
        });
      });
    } catch (err) {
      logger.error('Failed to connect Kafka producer', { error: err.message });
      throw err;
    }
  }

  /**
   * Publishes a validated domain event to Kafka.
   *
   * @param {string} type - Domain event type (e.g. PaymentCompleted)
   * @param {object} data - Payload adhering to the event schema
   * @param {string} [partitionKey] - Optional deterministic partition key
   * @param {string} [correlationId] - Optional correlation id for tracing
   */
  async publish(type, data, { partitionKey, correlationId } = {}) {
    // Guard clause for unknown event type
    const validator = validators[type];
    if (!validator) {
      throw new Error(`Unknown event type "${type}"`);
    }

    // Build final event object
    const event = {
      id           : uuid(),
      type,
      occurredAt   : new Date().toISOString(),
      version      : EVENTS_VERSION,
      correlationId: correlationId || uuid(),
      data
    };

    // Validate payload
    if (!validator(event)) {
      const detail = ajv.errorsText(validator.errors, { separator: ', ' });
      logger.error('Event schema validation failed', { type, detail });
      throw new Error(`Invalid event "${type}": ${detail}`);
    }

    // Lazily connect
    await this._connect();

    try {
      await this._producer.send({
        topic: PAYMENT_TOPIC,
        messages: [
          {
            key  : partitionKey || data.paymentId || event.id,
            value: JSON.stringify(event),
            headers: {
              'x-event-type'      : type,
              'x-event-version'   : EVENTS_VERSION,
              'x-correlation-id'  : event.correlationId
            }
          }
        ]
      });

      logger.debug(`Published event ${type}`, {
        type,
        paymentId   : data.paymentId,
        correlation : event.correlationId
      });
    } catch (err) {
      logger.error('Failed to publish message', { type, error: err.message });
      throw err;
    }
  }

  /**
   * Disconnects the underlying Kafka producer.
   */
  async disconnect() {
    if (!this._connected) return;
    try {
      await this._producer.disconnect();
      this._connected = false;
      logger.info('Kafka producer disconnected');
    } catch (err) {
      logger.warn('Error while disconnecting Kafka producer', { error: err.message });
    }
  }
}

// -----------------------------------------------------------------------------
// Singleton Export
// -----------------------------------------------------------------------------
const paymentEventProducer = new PaymentEventProducer();
module.exports             = paymentEventProducer;
```