```javascript
/**
 * PulseLearn Campus Hub – Payment Service
 * ---------------------------------------
 * A thin, well-typed wrapper around the PulseLearn Payment API that
 * encapsulates Stripe client-side logic, token insertion, request caching,
 * and event broadcasting so that UI components can remain framework-agnostic.
 *
 * NOTE: All methods return native Promises and are fully cancellable via
 *       AbortController signals. The service is safe to import from anywhere
 *       (singleton pattern).
 */

import axios from 'axios';
import mitt from 'mitt';
import { loadStripe } from '@stripe/stripe-js'; // Peer dependency
import { getAuthToken } from '../utils/auth';
import { Config } from '../config';

//////////////////////////////////////////////
// Internal helpers
//////////////////////////////////////////////

/**
 * Maps Axios or Stripe errors to a semantic, user-friendly object.
 * @param {any} err – Original error
 * @returns {{code: string, message: string, status?: number}}
 */
const normalizePaymentError = (err) => {
  if (axios.isAxiosError(err)) {
    return {
      code: err.response?.data?.code || 'network_error',
      message:
        err.response?.data?.message ||
        err.message ||
        'A network error occurred. Please try again.',
      status: err.response?.status,
    };
  }

  if (err?.type === 'StripeCardError') {
    return {
      code: err.code,
      message: err.message,
    };
  }

  return {
    code: 'unexpected_error',
    message: 'Something went wrong. Please refresh and try again.',
  };
};

/**
 * Inserts the Bearer token transparently on every request.
 */
const api = axios.create({
  baseURL: Config.API_BASE_URL + '/payments',
  timeout: 10000,
});

api.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) {
    // eslint-disable-next-line no-param-reassign
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

//////////////////////////////////////////////
// Event emitter
//////////////////////////////////////////////

/**
 * @typedef {'PAYMENT_SUCCEEDED' | 'PAYMENT_FAILED' | 'SUBSCRIPTION_UPDATED'} PaymentEvents
 */
const emitter = mitt();

//////////////////////////////////////////////
// PaymentService
//////////////////////////////////////////////

class PaymentService {
  /**************************
   * Singleton plumbing
   **************************/
  static #instance;

  /**
   * Creates or fetches the shared instance.
   * @param {string} publishableKey – Stripe publishable API key.
   * @returns {PaymentService}
   */
  static async getInstance(publishableKey) {
    if (!PaymentService.#instance) {
      PaymentService.#instance = new PaymentService(publishableKey);
      await PaymentService.#instance.#bootstrapStripe();
    }
    return PaymentService.#instance;
  }

  /**************************
   * Private fields
   **************************/
  /** @type {import('@stripe/stripe-js').Stripe | null} */
  #stripe = null;

  /** @type {string} */
  #publishableKey;

  /** Cache to dedupe requests (e.g., subscription fetch). */
  #cache = new Map();

  /**
   * @constructor
   * @param {string} publishableKey
   */
  constructor(publishableKey) {
    if (!publishableKey) {
      throw new Error('PaymentService: publishableKey is required');
    }
    this.#publishableKey = publishableKey;
  }

  /**
   * Loads Stripe.js asynchronously and memoizes the instance.
   * @private
   */
  async #bootstrapStripe() {
    this.#stripe = await loadStripe(this.#publishableKey);
    if (!this.#stripe) {
      throw new Error('Failed to load Stripe.js');
    }
  }

  ////////////////////////////////////////////////////////////
  // Public API
  ////////////////////////////////////////////////////////////

  /**
   * Creates a new payment intent for a course purchase.
   * @param {Object} params
   * @param {string} params.courseId
   * @param {string} [params.promoCode]
   * @param {AbortSignal} [params.signal]
   * @returns {Promise<{clientSecret: string}>}
   */
  async createPaymentIntent({ courseId, promoCode, signal } = {}) {
    try {
      const { data } = await api.post(
        '/intent',
        { courseId, promoCode },
        { signal },
      );

      return { clientSecret: data.clientSecret };
    } catch (err) {
      throw normalizePaymentError(err);
    }
  }

  /**
   * Confirms a card payment on the client side using Stripe.js.
   * Emits either PAYMENT_SUCCEEDED or PAYMENT_FAILED.
   *
   * @param {Object} params
   * @param {string} params.clientSecret
   * @param {import('@stripe/stripe-js').PaymentMethodCreateParams.Card} params.card
   * @param {string} [params.receiptEmail]
   * @returns {Promise<import('@stripe/stripe-js').PaymentIntent>}
   */
  async confirmCardPayment({ clientSecret, card, receiptEmail }) {
    if (!this.#stripe) {
      throw new Error('Stripe not initialized');
    }

    try {
      const { error, paymentIntent } = await this.#stripe.confirmCardPayment(
        clientSecret,
        {
          payment_method: {
            card,
            billing_details: { email: receiptEmail },
          },
        },
      );

      if (error) {
        emitter.emit('PAYMENT_FAILED', normalizePaymentError(error));
        throw normalizePaymentError(error);
      }

      emitter.emit('PAYMENT_SUCCEEDED', paymentIntent);
      return paymentIntent;
    } catch (err) {
      // catch unexpected runtime errors
      const normalized = normalizePaymentError(err);
      emitter.emit('PAYMENT_FAILED', normalized);
      throw normalized;
    }
  }

  /**
   * Retrieves the current user's subscription status.
   * Cached for 30 seconds to prevent excessive polling.
   *
   * @param {AbortSignal} [signal]
   * @returns {Promise<{plan: string, status: string, renewalDate: string | null}>}
   */
  async getSubscriptionStatus(signal) {
    const cacheKey = 'subscription';
    const cached = this.#cache.get(cacheKey);
    const now = Date.now();

    if (cached && now - cached.ts < 30_000) {
      return cached.value;
    }

    try {
      const { data } = await api.get('/subscription', { signal });
      this.#cache.set(cacheKey, { value: data, ts: now });
      return data;
    } catch (err) {
      throw normalizePaymentError(err);
    }
  }

  /**
   * Cancels the active subscription at period end.
   *
   * @param {AbortSignal} [signal]
   * @returns {Promise<{status: 'canceled' | 'active'}>}
   */
  async cancelSubscription(signal) {
    try {
      const { data } = await api.post(
        '/subscription/cancel',
        {},
        { signal },
      );
      emitter.emit('SUBSCRIPTION_UPDATED', data);
      // bust cache
      this.#cache.delete('subscription');
      return data;
    } catch (err) {
      throw normalizePaymentError(err);
    }
  }

  /**
   * Lists invoices for the current user.
   *
   * @param {{limit?: number, signal?: AbortSignal}} params
   * @returns {Promise<Array<{id: string, amount: number, hostedInvoiceUrl: string, created: number}>>}
   */
  async listInvoices({ limit = 20, signal } = {}) {
    try {
      const { data } = await api.get('/invoices', {
        params: { limit },
        signal,
      });
      return data;
    } catch (err) {
      throw normalizePaymentError(err);
    }
  }

  /**
   * Downloads a single invoice PDF via an auto-generated, signed URL.
   * If running in browser, it triggers a file download directly.
   *
   * @param {string} invoiceId
   * @param {AbortSignal} [signal]
   * @returns {Promise<void|Blob>}
   */
  async downloadInvoice(invoiceId, signal) {
    try {
      const { data } = await api.get(`/invoices/${invoiceId}/download`, {
        responseType: 'blob',
        signal,
      });

      // In browsers, create a blob URL & click.
      if (typeof window !== 'undefined') {
        const blobUrl = window.URL.createObjectURL(new Blob([data]));
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = `invoice-${invoiceId}.pdf`;
        link.click();
        window.URL.revokeObjectURL(blobUrl);
        return;
      }

      // In Node (SSR) just return the blob.
      return data;
    } catch (err) {
      throw normalizePaymentError(err);
    }
  }

  /**
   * Subscribes to PaymentService events.
   * @template {PaymentEvents} T
   * @param {T} type
   * @param {(payload: T extends 'PAYMENT_SUCCEEDED' ? import('@stripe/stripe-js').PaymentIntent : any) => void} handler
   */
  on(type, handler) {
    emitter.on(type, handler);
  }

  /**
   * Unsubscribes from PaymentService events.
   * @param {PaymentEvents} type
   * @param {Function} handler
   */
  off(type, handler) {
    emitter.off(type, handler);
  }
}

export default PaymentService;
```