```javascript
/**
 * paymentController.js
 *
 * The controller layer for the Payment Service.
 * Responsible for HTTP request / response handling, validation, and delegation
 * of business logic to the PaymentService.  All domain-level events are emitted
 * from here so that the service layer remains pure.
 *
 * Project: PulseLearn Campus Hub
 * Author: Payment & Billing Team
 */

'use strict';

const express = require('express');
const { body, param, validationResult } = require('express-validator');
const createError = require('http-errors');

const PaymentService = require('../services/paymentService');
const { emitDomainEvent } = require('../events/eventEmitter');
const logger = require('../utils/logger');
const asyncHandler = require('../middleware/asyncHandler');
const authMiddleware = require('../middleware/authMiddleware');

const router = express.Router();

/* -------------------------------------------------------------------------- */
/*                                VALIDATORS                                  */
/* -------------------------------------------------------------------------- */

/**
 * Centralised request validation middleware.
 */
const validateRequest = (req, _res, next) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    return next(createError(422, { errors: errors.array() }));
  }
  next();
};

/* -------------------------------------------------------------------------- */
/*                              ROUTE HANDLERS                                */
/* -------------------------------------------------------------------------- */

/**
 * POST /payments/checkout-session
 *
 * Creates a checkout session with the PSP (e.g. Stripe).
 */
router.post(
  '/checkout-session',
  authMiddleware,
  [
    body('courseId').isUUID().withMessage('courseId must be a valid UUID'),
    body('amount')
      .isFloat({ gt: 0 })
      .withMessage('amount must be greater than 0'),
    body('currency')
      .isString()
      .isLength({ min: 3, max: 3 })
      .withMessage('currency must be a valid ISO 4217 code'),
    body('successUrl').isURL().withMessage('successUrl must be a valid URL'),
    body('cancelUrl').isURL().withMessage('cancelUrl must be a valid URL')
  ],
  validateRequest,
  asyncHandler(async (req, res, next) => {
    const { courseId, amount, currency, successUrl, cancelUrl } = req.body;
    const userId = req.user.id;

    try {
      const checkoutSession = await PaymentService.createCheckoutSession({
        courseId,
        amount,
        currency,
        successUrl,
        cancelUrl,
        userId
      });

      emitDomainEvent('PaymentInitiated', {
        userId,
        courseId,
        amount,
        currency,
        sessionId: checkoutSession.id
      });

      res.status(201).json({
        message: 'Checkout session created',
        sessionId: checkoutSession.id,
        paymentUrl: checkoutSession.url
      });
    } catch (err) {
      logger.error('Failed to create checkout session', err);
      next(err);
    }
  })
);

/**
 * GET /payments/:paymentId/status
 *
 * Fetches payment status for the given payment identifier.
 */
router.get(
  '/:paymentId/status',
  authMiddleware,
  [param('paymentId').isString().withMessage('Invalid paymentId')],
  validateRequest,
  asyncHandler(async (req, res, next) => {
    const { paymentId } = req.params;
    const userId = req.user.id;

    try {
      const status = await PaymentService.getPaymentStatus({
        paymentId,
        userId
      });

      if (!status) {
        return next(createError(404, 'Payment not found'));
      }

      res.status(200).json(status);
    } catch (err) {
      logger.error(`Failed to fetch status for payment ${paymentId}`, err);
      next(err);
    }
  })
);

/**
 * POST /payments/:paymentId/refund
 *
 * Triggers a refund for a given payment.
 */
router.post(
  '/:paymentId/refund',
  authMiddleware,
  [
    param('paymentId').isString().withMessage('Invalid paymentId'),
    body('reason')
      .optional()
      .isString()
      .isLength({ max: 255 })
      .withMessage('reason must be under 255 chars')
  ],
  validateRequest,
  asyncHandler(async (req, res, next) => {
    const { paymentId } = req.params;
    const { reason } = req.body;
    const userId = req.user.id;

    try {
      const refund = await PaymentService.refundPayment({
        paymentId,
        reason,
        userId
      });

      emitDomainEvent('PaymentRefunded', {
        userId,
        paymentId,
        refundId: refund.id,
        reason
      });

      res.status(200).json({
        message: 'Refund processed',
        refundId: refund.id,
        status: refund.status
      });
    } catch (err) {
      logger.error(`Failed to refund payment ${paymentId}`, err);
      next(err);
    }
  })
);

/**
 * POST /payments/webhook
 *
 * Payment provider webhook endpoint.
 * This route does NOT use authMiddleware because the PSP, not the user,
 * will call it.  Instead, we verify the request signature inside the
 * PaymentService.
 */
router.post(
  '/webhook',
  express.raw({ type: 'application/json' }), // Stripe requires raw body
  asyncHandler(async (req, res, next) => {
    const signature = req.headers['stripe-signature'] || req.headers['x-signature'];
    if (!signature) {
      return next(createError(400, 'Missing webhook signature'));
    }

    try {
      await PaymentService.handleWebhook({ rawBody: req.body, signature });

      // PSP expects 2xx within a short window to consider webhook delivered
      res.status(200).json({ received: true });
    } catch (err) {
      // Do NOT throw; just log and 2xx if you want to avoid PSP retries
      logger.error('Webhook processing failed', err);
      next(err);
    }
  })
);

/* -------------------------------------------------------------------------- */
/*                               ERROR HANDLER                                */
/* -------------------------------------------------------------------------- */

/**
 * Generic error boundary for the payment controller.
 * Ensures consistent JSON error responses.
 */
router.use((err, _req, res, _next) => {
  const statusCode = err.status || err.statusCode || 500;
  const payload =
    err instanceof createError.HttpError
      ? err
      : { message: 'Internal Server Error' };

  res.status(statusCode).json({
    error: {
      status: statusCode,
      message: payload.message || 'Something went wrong'
    }
  });
});

/* -------------------------------------------------------------------------- */
/*                                EXPORTS                                     */
/* -------------------------------------------------------------------------- */

module.exports = router;
```