```javascript
/**
 * PulseLearn Campus Hub - Auth Service
 * ------------------------------------
 * Centralized Express error-handling middleware.
 * Maps application / third-party errors into normalized HTTP responses,
 * logs useful diagnostic information, and forwards critical events
 * to the observability pipeline (e.g., Sentry, Datadog) when configured.
 *
 * This file purposefully contains no direct Sentry/Datadog references
 * to keep vendor lock-in out of the open-source tree.  Instead we expose
 * hooks (beforeReport / afterReport) that can be wired to exporters in
 * the bootstrap phase.
 */

'use strict';

const { StatusCodes, getReasonPhrase } = require('http-status-codes');
const { TokenExpiredError, JsonWebTokenError, NotBeforeError } = require('jsonwebtoken');
const logger = require('../utils/logger');               // Winston-based logger wrapper
const { isCelebrateError } = require('celebrate');        // Joi request validation
const { AppError, AuthError, ValidationError } = require('../errors'); // Custom domain errors

/**
 * Utility: Shapes an error into a serializable payload that will be sent to the client.
 *  - Never expose internal stack traces or implementation hints in production.
 *  - Follows RFC7807 (Problem Details) structure where possible.
 *
 * @param {Error} err
 * @param {number} statusCode
 * @param {boolean} includeStack
 * @returns {object}
 */
function toClientPayload(err, statusCode, includeStack) {
  /* eslint-disable camelcase */
  const payload = {
    status: statusCode,
    error: getReasonPhrase(statusCode),
    message: err.message || 'Unexpected error',
  };

  // Attach validation details (i.e. Joi) if present and whitelisted
  if (err.details && err.details.length > 0) {
    payload.validation_errors = err.details.map(detail => ({
      message: detail.message,
      path: detail.path,
    }));
  }

  if (includeStack && err.stack) {
    payload.stack = err.stack;
  }

  return payload;
  /* eslint-enable camelcase */
}

/**
 * Node process env is cached, compute only once.
 *
 * @type {boolean}
 */
const isProd = process.env.NODE_ENV === 'production';

/**
 * Optional hooks that can be attached at runtime (e.g., in index.js)
 * to integrate with external monitoring tools.
 *
 * @type {{beforeReport?: function(Error): void, afterReport?: function(Error): void}}
 */
const hooks = {
  beforeReport: null,
  afterReport: null,
};

/**
 * Register third-party hooks dynamically to avoid hard dependencies.
 *
 * @param {'beforeReport'|'afterReport'} hookName
 * @param {function(Error):void} fn
 */
function registerHook(hookName, fn) {
  if (!['beforeReport', 'afterReport'].includes(hookName)) {
    throw new Error(`Unknown hook "${hookName}" for errorHandler`);
  }
  hooks[hookName] = fn;
}

/* -------------------------------------------------------------------------- */
/*                             Error type helpers                             */
/* -------------------------------------------------------------------------- */

/**
 * Extract status code & normalize for known error classes.
 *
 * @param {Error} err
 * @returns {number}
 */
function resolveStatusCode(err) {
  // Custom domain errors already carry HTTP status.
  if (err instanceof AppError && err.statusCode) {
    return err.statusCode;
  }

  // JWT related errors map to 401 or 403 depending on subtype.
  if (
    err instanceof TokenExpiredError ||
    err instanceof JsonWebTokenError ||
    err instanceof NotBeforeError
  ) {
    return StatusCodes.UNAUTHORIZED;
  }

  // celebrate / Joi validation errors
  if (isCelebrateError(err)) {
    return StatusCodes.BAD_REQUEST;
  }

  // Express default 404 handler has no status, keep default
  if (typeof err.status === 'number' && err.status >= 400 && err.status < 600) {
    return err.status;
  }

  // Fallback to generic server error.
  return StatusCodes.INTERNAL_SERVER_ERROR;
}

/**
 * If the error originates from celebrate, unwrap Joi details so that they can
 * be forwarded downstream.
 *
 * @param {Error} err
 * @returns {Error}
 */
function normalizeCelebrate(err) {
  if (!isCelebrateError(err)) return err;

  // celebrate error is a Map keyed by segments (headers, params, …)
  const details = [];
  for (const [segment, joiError] of err.details.entries()) {
    joiError.details.forEach(j => {
      details.push({
        message: j.message,
        path: [segment, ...j.path].filter(Boolean).join('.'),
      });
    });
  }

  return new ValidationError('Validation failed', details);
}

/* -------------------------------------------------------------------------- */
/*                             Middleware export                              */
/* -------------------------------------------------------------------------- */

/**
 * Express error-handling middleware signature (err, req, res, next)
 *
 * @returns {import('express').ErrorRequestHandler}
 */
function errorHandler() {
  // eslint-disable-next-line no-unused-vars
  return function (err, req, res, next) {
    // Let upstream middleware deal with anything after headers are sent.
    if (res.headersSent) {
      return next(err);
    }

    // Step 1: Normalize error, enrich default properties.
    const normalizedError = normalizeCelebrate(err);
    const httpCode = resolveStatusCode(normalizedError);
    const correlationId = req.headers['x-correlation-id'] || req.id; // req.id from express-request-id middleware
    const safePayload = toClientPayload(
      normalizedError,
      httpCode,
      !isProd && process.env.SHOW_STACK === 'true',
    );

    // Step 2: Fire pre-processing hook for observability if configured.
    if (typeof hooks.beforeReport === 'function') {
      try {
        hooks.beforeReport(normalizedError, req);
      } catch (hookErr) {
        logger.warn('beforeReport hook threw an error', { hookErr });
      }
    }

    // Step 3: Log error with contextual metadata.
    logger.error(normalizedError.message, {
      correlationId,
      route: req.originalUrl,
      method: req.method,
      userId: req.user && req.user.id,
      httpCode,
      // Do not log full stack for expected client errors to reduce noise.
      stack: httpCode >= 500 ? normalizedError.stack : undefined,
    });

    // Step 4: Send response and terminate.
    res
      .status(httpCode)
      .set('x-correlation-id', correlationId)
      .json(safePayload);

    // Step 5: Fire post-processing hook (non-blocking).
    if (typeof hooks.afterReport === 'function') {
      setImmediate(() => {
        try {
          hooks.afterReport(normalizedError, req);
        } catch (hookErr) {
          logger.warn('afterReport hook threw an error', { hookErr });
        }
      });
    }
  };
}

/* -------------------------------------------------------------------------- */
/*                                Public API                                  */
/* -------------------------------------------------------------------------- */

module.exports = {
  errorHandler: errorHandler(),
  registerErrorHook: registerHook,
};
```