```javascript
/**
 * PulseLearn Campus Hub – Payment Routes
 *
 * This router defines RESTful endpoints for payment-related operations
 * (checkout, webhook handling, refunds, and history) with proper
 * authentication, request validation, and fault-tolerant error handling.
 *
 * NOTE: Service-layer implementation details are abstracted behind
 * `paymentService`. Each route publishes domain events to the message bus.
 */

const express = require('express');
const { body, param, validationResult } = require('express-validator');

const paymentService = require('../services/paymentService'); // Service-layer abstraction
const authMiddleware = require('../middleware/authenticate'); // JWT/Session authentication
const roleMiddleware = require('../middleware/authorizeRole'); // Role-based authorization
const logger = require('../utils/logger');                    // Winston/Pino logger instance
const EventPublisher = require('../utils/eventPublisher');    // Domain event dispatcher

const router = express.Router();

/* -------------------------------------------------------------------------- */
/*                                Utils / MISC                                */
/* -------------------------------------------------------------------------- */

/**
 * Wrap async route controllers to forward errors to Express error handler.
 * @param {Function} fn
 */
const asyncHandler = fn => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

/**
 * Publish domain event with safe fallback logging.
 * @param {String} eventType
 * @param {Object} payload
 */
const publishEvent = async (eventType, payload) => {
  try {
    await EventPublisher.publish(eventType, payload);
  } catch (err) {
    logger.error(`Failed to publish ${eventType}: ${err.message}`, { err, payload });
  }
};

/* -------------------------------------------------------------------------- */
/*                                   Routes                                   */
/* -------------------------------------------------------------------------- */

/**
 * POST /payments/checkout
 * Creates a payment intent/checkout session for a premium course.
 */
router.post(
  '/checkout',
  authMiddleware,
  [
    body('courseId').isUUID().withMessage('courseId must be a valid UUID'),
    body('paymentProvider')
      .isIn(['stripe', 'paypal'])
      .withMessage('Unsupported payment provider'),
  ],
  asyncHandler(async (req, res) => {
    // Validate request
    const errors = validationResult(req);
    if (!errors.isEmpty()) {
      logger.warn('Checkout validation failed', { errors: errors.array() });
      return res.status(400).json({ errors: errors.array() });
    }

    const { courseId, paymentProvider } = req.body;
    const userId = req.user.id;

    // Delegate to service layer
    const checkoutSession = await paymentService.createCheckoutSession({
      courseId,
      paymentProvider,
      userId,
    });

    await publishEvent('CheckoutSessionCreated', {
      userId,
      courseId,
      paymentProvider,
      sessionId: checkoutSession.id,
    });

    return res.status(201).json({ session: checkoutSession });
  })
);

/**
 * POST /payments/webhook
 * Payment gateway webhook (public endpoint – signature verified by service).
 */
router.post(
  '/webhook',
  express.raw({ type: 'application/json' }), // raw body required by Stripe/PayPal
  asyncHandler(async (req, res) => {
    let event;
    try {
      event = await paymentService.verifyAndParseWebhook(req);
    } catch (err) {
      logger.error('Webhook signature verification failed', err);
      return res.status(400).send(`Webhook Error: ${err.message}`);
    }

    // Process event
    try {
      await paymentService.handleWebhookEvent(event);
      await publishEvent(event.type, event.data);
    } catch (err) {
      logger.error(`Failed to process webhook event ${event.type}`, err);
      // Respond 200 to avoid retries if idempotency handled internally
      return res.status(200).send('Event received but processing failed');
    }

    return res.status(200).send('Received');
  })
);

/**
 * POST /payments/refund/:paymentId
 * Trigger a refund – requires admin or finance role.
 */
router.post(
  '/refund/:paymentId',
  authMiddleware,
  roleMiddleware(['admin', 'finance']),
  [param('paymentId').isString().withMessage('paymentId required')],
  asyncHandler(async (req, res) => {
    const errors = validationResult(req);
    if (!errors.isEmpty()) {
      logger.warn('Refund validation failed', { errors: errors.array() });
      return res.status(400).json({ errors: errors.array() });
    }

    const { paymentId } = req.params;
    const adminId = req.user.id;

    const refund = await paymentService.refundPayment({ paymentId, adminId });

    await publishEvent('PaymentRefunded', {
      paymentId,
      refundId: refund.id,
      adminId,
    });

    return res.status(200).json({ refund });
  })
);

/**
 * GET /payments/history
 * Returns paginated payment history for the authenticated user.
 */
router.get(
  '/history',
  authMiddleware,
  asyncHandler(async (req, res) => {
    const page = parseInt(req.query.page, 10) || 1;
    const limit = Math.min(parseInt(req.query.limit, 10) || 20, 100);
    const userId = req.user.id;

    const history = await paymentService.getPaymentHistory({ userId, page, limit });
    return res.status(200).json(history);
  })
);

/**
 * GET /payments/:paymentId
 * Retrieve details of a specific payment.
 */
router.get(
  '/:paymentId',
  authMiddleware,
  [param('paymentId').isString().withMessage('paymentId must be provided')],
  asyncHandler(async (req, res) => {
    const errors = validationResult(req);
    if (!errors.isEmpty()) {
      return res.status(400).json({ errors: errors.array() });
    }

    const { paymentId } = req.params;
    const userId = req.user.id;

    const payment = await paymentService.getPaymentById({ paymentId, userId });
    if (!payment) {
      return res.status(404).json({ message: 'Payment not found' });
    }
    return res.status(200).json(payment);
  })
);

/* -------------------------------------------------------------------------- */
/*                              Error Handling                                */
/* -------------------------------------------------------------------------- */

// Centralized error handler (must be registered after routes in main app)
// eslint-disable-next-line no-unused-vars
const errorHandler = (err, _req, res, _next) => {
  logger.error('Unhandled error in payment routes', err);
  const status = err.statusCode || 500;
  res.status(status).json({
    message: err.message || 'Internal Server Error',
    ...(process.env.NODE_ENV === 'development' && { stack: err.stack }),
  });
};

router.use(errorHandler);

module.exports = router;
```