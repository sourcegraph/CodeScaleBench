```javascript
/**
 * PulseLearn Campus Hub
 * Payment Service – Stripe Integration Layer
 *
 * This service hides direct Stripe SDK calls behind a cohesive,
 * domain-oriented API.  All payment-related workflows pass through
 * this class, making it the single integration point for PulseLearn’s
 * micro-services that need to charge users, create subscriptions, or
 * react to Stripe web­hooks.
 *
 * NOTE: Do not import this service directly inside controllers.  Use the
 * dedicated PaymentController (REST) or PaymentCommandHandlers (event bus)
 * to enforce proper cohesion and transaction boundaries.
 */

'use strict';

/* ──────────────────────────────────────────────────────────────────── */
/* Dependencies                                                        */
/* ──────────────────────────────────────────────────────────────────── */
const Stripe              = require('stripe');
const { v4: uuid }        = require('uuid');
const config              = require('../../config');          // Centralised config loader
const logger              = require('../utils/logger');       // Winston-based logger
const ApiError            = require('../errors/ApiError');    // Custom runtime errors
const { UserRepository }  = require('../repositories');       // Domain repository abstraction

/* ──────────────────────────────────────────────────────────────────── */
/* Stripe Client                                                      */
/* ──────────────────────────────────────────────────────────────────── */
const stripe = new Stripe(config.stripe.secretKey, {
    apiVersion              : '2023-10-16',
    maxNetworkRetries       : 2,
    typescript              : false,
    telemetry               : false,
});

/* ──────────────────────────────────────────────────────────────────── */
/* Constants                                                          */
/* ──────────────────────────────────────────────────────────────────── */
const DEFAULT_CURRENCY     = 'usd';
const WEBHOOK_SECRET       = config.stripe.webhookSecret;   // e.g. whsec_…

/* ──────────────────────────────────────────────────────────────────── */
/* Service Implementation                                             */
/* ──────────────────────────────────────────────────────────────────── */
class StripeService {
    /**
     * Create or fetch a Stripe Customer mapped to the platform user.
     * @param {Object} user  Domain user entity ({ id, email, fullName })
     */
    static async getOrCreateCustomer(user) {
        if (!user) {
            throw new ApiError(400, 'User entity required to create customer');
        }

        if (user.stripeCustomerId) {
            return user.stripeCustomerId;
        }

        try {
            const customer = await stripe.customers.create({
                email   : user.email,
                name    : user.fullName,
                metadata: { userId: user.id },
            });

            // Persist the mapping for future calls
            await UserRepository.setStripeCustomerId(user.id, customer.id);

            logger.info(`Stripe customer created for user ${user.id}`, { customerId: customer.id });
            return customer.id;
        } catch (err) {
            logger.error('Failed to create Stripe customer', { err });
            throw new ApiError(502, 'Payment provider unavailable');
        }
    }

    /**
     * Create a single-payment Checkout Session (e.g., premium course purchase).
     * The session ID is forwarded to the client to redirect the user to the
     * Stripe-hosted checkout page.
     */
    static async createCheckoutSession({ user, priceId, successUrl, cancelUrl }) {
        const customerId = await StripeService.getOrCreateCustomer(user);

        try {
            const session = await stripe.checkout.sessions.create({
                mode           : 'payment',
                customer       : customerId,
                line_items     : [{ price: priceId, quantity: 1 }],
                success_url    : successUrl,
                cancel_url     : cancelUrl,
                client_reference_id: user.id,
                metadata       : { userId: user.id, priceId },
            });

            return session.url; // Pass URL back to front-end
        } catch (err) {
            logger.error('Unable to create checkout session', { err, userId: user.id });
            throw new ApiError(502, 'Payment provider unavailable');
        }
    }

    /**
     * Create a PaymentIntent for in-app purchases exposed via mobile clients.
     */
    static async createPaymentIntent({ user, amountCents, currency = DEFAULT_CURRENCY, description }) {
        const customerId     = await StripeService.getOrCreateCustomer(user);
        const idempotencyKey = uuid();           // Safe guard against duplicate charges

        try {
            const paymentIntent = await stripe.paymentIntents.create({
                amount      : amountCents,
                currency,
                customer    : customerId,
                description,
                metadata    : { userId: user.id },
                automatic_payment_methods: { enabled: true },
            }, { idempotencyKey });

            return {
                clientSecret: paymentIntent.client_secret,
                paymentIntentId: paymentIntent.id,
            };
        } catch (err) {
            logger.error('Failed to create payment intent', { err, userId: user.id });
            throw new ApiError(502, 'Payment provider unavailable');
        }
    }

    /**
     * Attach a saved payment method to the user’s customer object.
     */
    static async attachPaymentMethod({ user, paymentMethodId }) {
        const customerId = await StripeService.getOrCreateCustomer(user);

        try {
            await stripe.paymentMethods.attach(paymentMethodId, { customer: customerId });
            await stripe.customers.update(customerId, { invoice_settings: { default_payment_method: paymentMethodId } });

            logger.info('Payment method attached', { userId: user.id, paymentMethodId });
        } catch (err) {
            logger.warn('Unable to attach payment method', { err, userId: user.id });
            throw new ApiError(400, 'Invalid payment method');
        }
    }

    /**
     * Process an incoming Stripe Webhook and return the event object.
     * Signature validation is performed to ensure authenticity.
     */
    static constructWebhookEvent(rawBody, signature) {
        let event;
        try {
            event = stripe.webhooks.constructEvent(rawBody, signature, WEBHOOK_SECRET);
            logger.debug('Stripe webhook verified', { type: event.type, id: event.id });
        } catch (err) {
            logger.error('Stripe webhook signature verification failed', { err });
            throw new ApiError(400, 'Invalid webhook signature');
        }
        return event;
    }

    /**
     * Issue a partial or full refund.
     */
    static async refundPayment({ paymentIntentId, amountCents }) {
        try {
            const refund = await stripe.refunds.create({
                payment_intent: paymentIntentId,
                amount        : amountCents, // optional − refund full if undefined
                metadata      : { reason: 'User-requested via dashboard' },
            });

            logger.info('Payment refunded', { paymentIntentId, refundId: refund.id });
            return refund;
        } catch (err) {
            logger.error('Refund failed', { err, paymentIntentId });
            throw new ApiError(502, 'Unable to process refund at this moment');
        }
    }

    /* ──────────────────────────────────────────────────────────────── */
    /* Subscription Flows                                              */
    /* ──────────────────────────────────────────────────────────────── */

    /**
     * Create a recurring subscription (e.g., monthly premium plan).
     */
    static async createSubscription({ user, priceId, trialPeriodDays = 0 }) {
        const customerId = await StripeService.getOrCreateCustomer(user);

        try {
            const subscription = await stripe.subscriptions.create({
                customer: customerId,
                items   : [{ price: priceId }],
                trial_period_days: trialPeriodDays,
                expand  : ['latest_invoice.payment_intent'],
                metadata: { userId: user.id, priceId },
            });

            logger.info('Subscription created', { subscriptionId: subscription.id, userId: user.id });
            return subscription;
        } catch (err) {
            logger.error('Subscription creation failed', { err, userId: user.id });
            throw new ApiError(502, 'Unable to create subscription');
        }
    }

    /**
     * Cancel an active subscription at period end.
     */
    static async cancelSubscription({ subscriptionId }) {
        try {
            const subscription = await stripe.subscriptions.update(subscriptionId, {
                cancel_at_period_end: true,
            });

            logger.info('Subscription cancellation scheduled', { subscriptionId });
            return subscription;
        } catch (err) {
            logger.error('Subscription cancellation failed', { err, subscriptionId });
            throw new ApiError(404, 'Subscription not found');
        }
    }
}

/* ──────────────────────────────────────────────────────────────────── */
/* Module Exports                                                     */
/* ──────────────────────────────────────────────────────────────────── */
module.exports = StripeService;
```