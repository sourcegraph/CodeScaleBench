```javascript
/**
 * PulseLearn Campus Hub - Auth Service
 * Middleware: validateRequest
 *
 * A tiny but opinionated validation layer built on top of Joi that allows each route
 * to declare the shape of request data it expects.  The middleware will:
 *   1. Validate request.body / request.params / request.query / request.headers
 *   2. Return a uniform ValidationError when something is off
 *   3. Strip unknown keys and expose a sanitized object on req.validated
 *
 * Usage:
 *   const { validateRequest } = require('../middleware/validateRequest');
 *
 *   // Inside an express router file
 *   router.post(
 *     '/login',
 *     validateRequest({
 *       body: Joi.object({
 *         email: Joi.string().email().required(),
 *         password: Joi.string().min(8).required(),
 *       }),
 *     }),
 *     controller.login,
 *   );
 */

'use strict';

const Joi = require('joi');
const { StatusCodes, getReasonPhrase } = require('http-status-codes');

/**
 * A bespoke error that the global error-handler can interpret.
 * Sending a dedicated error class (instead of generic Error)
 * makes it possible to return a specific HTTP code from one place.
 */
class ValidationError extends Error {
  /**
   * @param {string} message – A short description of the failure
   * @param {Joi.ValidationErrorItem[]} details – Joi generated details
   */
  constructor(message, details) {
    super(message);
    this.name = 'ValidationError';
    this.statusCode = StatusCodes.BAD_REQUEST;
    this.details = details;
    // Capture stack while excluding this constructor
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, ValidationError);
    }
  }

  /**
   * Convert to JSON so that our error formatter can use spread operator.
   */
  toJSON() {
    return {
      name: this.name,
      statusCode: this.statusCode,
      message: this.message,
      details: this.details,
    };
  }
}

/**
 * Joi common options used across all validations.
 * - `abortEarly: false`     → report all errors, not just the first
 * - `stripUnknown: true`    → remove keys that are not in the schema
 */
const defaultJoiOptions = {
  abortEarly: false,
  stripUnknown: true,
};

/* -------------------------------------------------------------------------- */
/*                              Helper functions                              */
/* -------------------------------------------------------------------------- */

/**
 * Build a map of segments we care about.
 * @param {import('express').Request} req
 */
const pickRequestSegments = (req) => ({
  body: req.body,
  params: req.params,
  query: req.query,
  headers: req.headers,
});

/**
 * Convenience method to sanitize the data and push it into req.validated.
 * @param {import('express').Request} req
 * @param {string} segment – body | params | query | headers
 * @param {object} value – Joi validated value
 */
const attachValidatedData = (req, segment, value) => {
  if (!req.validated) req.validated = {};
  req.validated[segment] = value;
};

/* -------------------------------------------------------------------------- */
/*                              Public Middleware                             */
/* -------------------------------------------------------------------------- */

/**
 * Factory that returns an Express middleware validating the request
 * against the provided Joi schemas. All four request segments can be
 * specified, but only the ones present inside the `schemas` object will
 * be validated.
 *
 * @example
 *   validateRequest({
 *     body: Joi.object({ email: Joi.string().email() }),
 *     query: Joi.object({ next: Joi.string().uri().optional() })
 *   })
 *
 * @param {{
 *   body?: Joi.ObjectSchema,
 *   params?: Joi.ObjectSchema,
 *   query?: Joi.ObjectSchema,
 *   headers?: Joi.ObjectSchema
 * }} schemas – An object containing Joi schemas for each segment
 *
 * @param {Joi.ValidationOptions=} joiOptions – Optional overrides
 * @returns {import('express').RequestHandler}
 */
function validateRequest(schemas = {}, joiOptions = {}) {
  // Avoid running expensive Joi.compile at every request by compiling once
  const compiledSchemas = Object.entries(schemas).reduce(
    (acc, [segment, schema]) => {
      acc[segment] = Joi.compile(schema);
      return acc;
    },
    {},
  );

  const options = { ...defaultJoiOptions, ...joiOptions };

  /**
   * The actual Express middleware
   */
  return function requestValidator(req, res, next) {
    try {
      const segments = pickRequestSegments(req);
      const validationErrors = [];
      let hasFailure = false;

      for (const [segment, schema] of Object.entries(compiledSchemas)) {
        const data = segments[segment];

        const { error, value } = schema.validate(data, options);

        if (error) {
          hasFailure = true;
          /* Push each individual error so the consumer has full context */
          validationErrors.push(
            ...error.details.map((det) => ({
              segment,
              message: det.message,
              path: det.path,
              type: det.type,
              context: det.context,
            })),
          );
        } else {
          /* Replace original request data with sanitized version */
          attachValidatedData(req, segment, value);
          // For body we also directly replace req.body so downstream middlewares
          // pick up sanitized, de-tainted input.
          if (segment === 'body') {
            req.body = value;
          }
        }
      }

      if (hasFailure) {
        const message = getReasonPhrase(StatusCodes.BAD_REQUEST);
        return next(new ValidationError(message, validationErrors));
      }

      return next();
    } catch (err) {
      // Safety net – should rarely fire, but we don't want to crash the process.
      return next(err);
    }
  };
}

/* -------------------------------------------------------------------------- */
/*                               Module exports                               */
/* -------------------------------------------------------------------------- */

module.exports = {
  validateRequest,
  ValidationError,
};
```