```javascript
/**
 * PulseLearn Campus Hub – Payment Service
 * Event Consumer
 *
 * This consumer listens to payment-related domain events emitted on Kafka and
 * delegates the actual business logic to the service layer.  It handles
 * resilience (retry, DLQ), observability (metrics, structured logs) and
 * graceful shutdown.
 *
 * File: services/payment-service/src/events/consumer.js
 * Author: PulseLearn Engineering
 */

'use strict';

const { Kafka, logLevel } = require('kafkajs');
const { Counter, Histogram, Registry } = require('prom-client');
const pRetry = require('p-retry');
const createLogger = require('../utils/logger');
const config = require('../config');
const paymentService = require('../services/paymentProcessorService');

// ---------------------------------------------------------------------------
// Constants & Configuration
// ---------------------------------------------------------------------------

const logger = createLogger({ service: 'payment-event-consumer' });

const {
  kafka: { clientId, brokers, ssl, sasl, groupId },
  paymentTopics,
  instrumentation: { metricsPort },
} = config;

const MAX_PROCESSING_RETRIES = 5;
const DLQ_TOPIC = paymentTopics.deadLetter;

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

const registry = new Registry();

const messageReceivedCounter = new Counter({
  name: 'payment_consumer_messages_total',
  help: 'Total number of messages received',
  registers: [registry],
});

const messageProcessedCounter = new Counter({
  name: 'payment_consumer_messages_processed_total',
  help: 'Total number of messages successfully processed',
  registers: [registry],
});

const messageFailedCounter = new Counter({
  name: 'payment_consumer_messages_failed_total',
  help: 'Total number of messages that failed permanently',
  registers: [registry],
});

const processingLatencyHistogram = new Histogram({
  name: 'payment_consumer_processing_latency_seconds',
  help: 'Message processing latency in seconds',
  buckets: [0.01, 0.1, 0.5, 1, 2, 5],
  registers: [registry],
});

// ---------------------------------------------------------------------------
// Kafka Consumer Wrapper
// ---------------------------------------------------------------------------

class PaymentEventConsumer {
  constructor() {
    this.kafka = new Kafka({
      clientId,
      brokers,
      ssl,
      sasl,
      logLevel: logLevel.INFO,
      logCreator: () => ({ namespace, level, label, log }) => {
        logger.log({
          level: level === logLevel.ERROR ? 'error' : 'info',
          message: `[${namespace}] ${label} ${log.message}`,
          extra: log,
        });
      },
    });

    this.consumer = this.kafka.consumer({ groupId });
    this.producer = this.kafka.producer();
    this.running = false;
  }

  /**
   * Initialize consumer subscriptions
   */
  async init() {
    await this.consumer.connect();
    await this.producer.connect();

    await Promise.all(
      paymentTopics.inbound.map((topic) => this.consumer.subscribe({ topic, fromBeginning: false })),
    );

    logger.info(`Subscribed to payment topics: ${paymentTopics.inbound.join(', ')}`);
  }

  /**
   * Run the consumer loop
   */
  async run() {
    this.running = true;

    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        messageReceivedCounter.inc();
        const start = process.hrtime.bigint();

        try {
          const parsed = JSON.parse(message.value.toString());
          logger.debug('Received event', { topic, ...parsed });

          await this._processEvent(parsed);
          messageProcessedCounter.inc();
        } catch (err) {
          await this._handleProcessingError(topic, message, err);
        } finally {
          const diff = (Number(process.hrtime.bigint() - start) / 1e9);
          processingLatencyHistogram.observe(diff);
        }
      },
    });

    logger.info('PaymentEventConsumer is running');
  }

  /**
   * Stop consumer gracefully
   */
  async shutdown() {
    if (!this.running) return;
    this.running = false;
    logger.info('Shutting down PaymentEventConsumer ...');
    await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
    logger.info('PaymentEventConsumer stopped');
  }

  // -----------------------------------------------------------------------
  // Private utilities
  // -----------------------------------------------------------------------

  /**
   * Route event to appropriate handler
   * @param {Object} event
   */
  async _processEvent(event) {
    const { type, data, metadata } = event;

    if (!type) {
      throw new Error('Event missing "type" property');
    }

    const handler = this._getHandlerForType(type);

    if (!handler) {
      logger.warn(`No handler implemented for event type "${type}" – ignored`);
      return;
    }

    // Wrap business logic in retry policy
    await pRetry(() => handler(data, metadata), {
      retries: MAX_PROCESSING_RETRIES,
      onFailedAttempt: (err) => {
        logger.warn(
          `Attempt ${err.attemptNumber} failed to process ${type}. ${err.retriesLeft} retries left.`,
          { err },
        );
      },
    });
  }

  /**
   * Resolve event type to service handler
   */
  _getHandlerForType(type) {
    const map = {
      PaymentInitiated: paymentService.handlePaymentInitiated,
      PaymentSucceeded: paymentService.handlePaymentSucceeded,
      PaymentFailed:    paymentService.handlePaymentFailed,
      RefundRequested:  paymentService.handleRefundRequested,
      CoursePurchased:  paymentService.handleCoursePurchased,
    };
    return map[type];
  }

  /**
   * Persist message to Dead-Letter-Queue and track metrics
   */
  async _handleProcessingError(topic, message, err) {
    logger.error('Permanent failure processing message', { err });

    messageFailedCounter.inc();

    // Forward to DLQ (fire-and-forget)
    try {
      await this.producer.send({
        topic: DLQ_TOPIC,
        messages: [
          {
            key: message.key,
            value: message.value,
            headers: {
              'x-original-topic': topic,
              'x-error': Buffer.from(err.message).toString('base64'),
            },
          },
        ],
      });
      logger.info('Message sent to DLQ', { DLQ_TOPIC });
    } catch (dlqErr) {
      logger.error('Failed to write to DLQ – message lost', { dlqErr });
    }
  }
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

const consumer = new PaymentEventConsumer();

(async () => {
  try {
    await consumer.init();
    await consumer.run();
  } catch (err) {
    logger.error('Fatal error starting PaymentEventConsumer', { err });
    process.exit(1);
  }
})();

process
  .once('SIGINT', async () => {
    await consumer.shutdown();
    process.exit(0);
  })
  .once('SIGTERM', async () => {
    await consumer.shutdown();
    process.exit(0);
  });

// ---------------------------------------------------------------------------
// Exported for testing purposes
// ---------------------------------------------------------------------------

module.exports = PaymentEventConsumer;
```