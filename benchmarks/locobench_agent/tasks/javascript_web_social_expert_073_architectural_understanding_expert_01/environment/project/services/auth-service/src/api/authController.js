```javascript
/**
 * PulseLearn Campus Hub – Authentication Controller
 * -------------------------------------------------
 * Exposes HTTP handlers for authentication-related tasks such as:
 *  • Local e-mail/password registration & login
 *  • OAuth-2.0 social login callback
 *  • Stateless JWT refresh & revocation
 *
 * NOTE: The controller delegates business logic to the AuthService
 * layer and communicates relevant domain events through the
 * EventBus abstraction (Kafka/NATS under the hood).
 */

'use strict';

const { StatusCodes, getReasonPhrase } = require('http-status-codes');
const { validationResult } = require('express-validator');

const AuthService = require('../services/authService');
const EventBus = require('../events/eventBus');
const ApiError = require('../errors/ApiError');
const logger = require('../utils/logger');

/**
 * Handle validation middleware result.
 * Throws ApiError if Express-Validator found problems.
 */
const assertValid = (req) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    throw new ApiError(
      StatusCodes.UNPROCESSABLE_ENTITY,
      'Validation failed',
      errors.array()
    );
  }
};

/**
 * POST /api/v1/auth/register
 * Body: { fullName, email, password }
 */
exports.register = async (req, res, next) => {
  try {
    assertValid(req);

    const { fullName, email, password } = req.body;
    const userDto = await AuthService.register({ fullName, email, password });

    // Emit domain-event for downstream micro-services
    await EventBus.publish('UserRegistered', {
      userId: userDto.id,
      email: userDto.email,
      timestamp: Date.now(),
    });

    return res.status(StatusCodes.CREATED).json({
      message: 'Registration successful',
      data: userDto,
    });
  } catch (err) {
    logger.error('Registration failed', { err });
    return next(err);
  }
};

/**
 * POST /api/v1/auth/login
 * Body: { email, password }
 */
exports.login = async (req, res, next) => {
  try {
    assertValid(req);

    const { email, password } = req.body;
    const authPayload = await AuthService.login(email, password);

    // Notify analytics/gamification engines
    await EventBus.publish('UserLoggedIn', {
      userId: authPayload.user.id,
      timestamp: Date.now(),
    });

    return res.status(StatusCodes.OK).json({
      message: 'Login successful',
      ...authPayload, // => { accessToken, refreshToken, user }
    });
  } catch (err) {
    // Map known credential errors to 401 for consistency
    if (err.name === 'InvalidCredentialsError') {
      return next(
        new ApiError(
          StatusCodes.UNAUTHORIZED,
          getReasonPhrase(StatusCodes.UNAUTHORIZED)
        )
      );
    }
    logger.error('Login failed', { err });
    return next(err);
  }
};

/**
 * POST /api/v1/auth/refresh
 * Body: { refreshToken }
 */
exports.refreshToken = async (req, res, next) => {
  try {
    assertValid(req);

    const { refreshToken } = req.body;
    const newTokens = await AuthService.rotateRefreshToken(refreshToken);

    // Optionally broadcast token rotation for session analytics
    await EventBus.publish('RefreshTokenRotated', {
      userId: newTokens.user.id,
      timestamp: Date.now(),
    });

    return res.status(StatusCodes.OK).json({
      message: 'Token refreshed',
      ...newTokens, // => { accessToken, refreshToken }
    });
  } catch (err) {
    if (err.name === 'TokenExpiredError') {
      return next(
        new ApiError(
          StatusCodes.UNAUTHORIZED,
          getReasonPhrase(StatusCodes.UNAUTHORIZED)
        )
      );
    }
    return next(err);
  }
};

/**
 * GET /api/v1/auth/oauth/:provider/callback
 * Called by social providers (e.g., Google) after user grants access.
 * Query params contain state & code; Passport populates req.user.
 */
exports.socialCallback = async (req, res, next) => {
  try {
    if (!req.user) {
      throw new ApiError(
        StatusCodes.UNAUTHORIZED,
        'Social authentication failed'
      );
    }

    const oauthResult = await AuthService.handleSocialLogin(req.user);

    // Provide JWTs through HTML redirect or JSON depending on client type
    if (req.accepts('html')) {
      // Redirect to SPA with tokens in URL fragment (or secure cookie)
      const redirectUrl = `${process.env.FRONTEND_URL}/social/callback#` +
        `accessToken=${oauthResult.accessToken}` +
        `&refreshToken=${oauthResult.refreshToken}`;
      return res.redirect(redirectUrl);
    }

    return res.status(StatusCodes.OK).json({
      message: 'Social login successful',
      ...oauthResult,
    });
  } catch (err) {
    logger.error('Social login callback failed', { err });
    return next(err);
  }
};

/**
 * POST /api/v1/auth/logout
 * Body: { refreshToken }
 */
exports.logout = async (req, res, next) => {
  try {
    assertValid(req);

    const { refreshToken } = req.body;
    await AuthService.logout(refreshToken);

    await EventBus.publish('UserLoggedOut', {
      userId: req.user?.id,
      timestamp: Date.now(),
    });

    return res.status(StatusCodes.NO_CONTENT).send();
  } catch (err) {
    return next(err);
  }
};
```