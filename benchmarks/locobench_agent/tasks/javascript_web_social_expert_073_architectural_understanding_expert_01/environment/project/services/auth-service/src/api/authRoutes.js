```javascript
/**
 *  PulseLearn Campus Hub – Authentication Routes
 *
 *  File path: pulselearn-campus-hub/services/auth-service/src/api/authRoutes.js
 *
 *  Exposes every HTTP endpoint needed for authentication / authorisation
 *  concerns: local (email + password) accounts, social login (Google),
 *  session refreshing, password reset, etc.
 *
 *  NOTE: Controllers/middlewares referenced here live in sibling folders.
 *  This file focuses purely on request → validation → controller mapping.
 */

'use strict';

const express = require('express');
const passport = require('passport');
const rateLimit = require('express-rate-limit');
const { celebrate, Joi, Segments, errors: celebrateErrors } = require('celebrate');
const asyncHandler = require('express-async-handler');

const AuthController = require('../controllers/authController');
const { authenticate, verifyRefreshToken } = require('../middlewares/authMiddleware');
const logger = require('../utils/logger');

const router = express.Router();

/* -------------------------------------------------------------------------- */
/*                           ── Rate-limiter rules ──                         */
/* -------------------------------------------------------------------------- */

const loginLimiter = rateLimit({
  windowMs: 60 * 1000,            // 1 minute
  max: 10,                         // limit each IP to 10 requests per `window`
  standardHeaders: true,           // Return rate limit info in the `RateLimit-*` headers
  legacyHeaders: false,            // Disable `X-RateLimit-*` headers
  handler: (_req, res) => {
    res.status(429).json({
      status: 429,
      message: 'Too many authentication attempts. Please try again later.',
    });
  },
});

/* -------------------------------------------------------------------------- */
/*                              ── Validators ──                              */
/* -------------------------------------------------------------------------- */

const registerSchema = {
  [Segments.BODY]: Joi.object().keys({
    firstName: Joi.string().trim().min(2).max(64).required(),
    lastName: Joi.string().trim().min(2).max(64).required(),
    email: Joi.string().trim().lowercase().email().required(),
    password: Joi.string().min(8).max(128).required(),
    cohortId: Joi.string().uuid().required(), // link user to a campus cohort
  }),
};

const loginSchema = {
  [Segments.BODY]: Joi.object().keys({
    email: Joi.string().trim().lowercase().email().required(),
    password: Joi.string().required(),
  }),
};

const refreshSchema = {
  [Segments.BODY]: Joi.object().keys({
    refreshToken: Joi.string().required(),
  }),
};

const forgotPasswordSchema = {
  [Segments.BODY]: Joi.object().keys({
    email: Joi.string().trim().lowercase().email().required(),
  }),
};

const resetPasswordSchema = {
  [Segments.BODY]: Joi.object().keys({
    password: Joi.string().min(8).max(128).required(),
    token: Joi.string().required(),
  }),
};

/* -------------------------------------------------------------------------- */
/*                             ── Route bindings ──                           */
/* -------------------------------------------------------------------------- */

// Registration
router.post(
  '/v1/auth/register',
  celebrate(registerSchema),
  asyncHandler(AuthController.register),
);

// Local login
router.post(
  '/v1/auth/login',
  loginLimiter,
  celebrate(loginSchema),
  asyncHandler(AuthController.login),
);

// Token refresh
router.post(
  '/v1/auth/refresh-token',
  celebrate(refreshSchema),
  verifyRefreshToken,
  asyncHandler(AuthController.refreshToken),
);

// Logout (invalidate refresh token & destroy server-side session, if any)
router.post(
  '/v1/auth/logout',
  authenticate,
  asyncHandler(AuthController.logout),
);

// Forgot password – send reset email
router.post(
  '/v1/auth/forgot-password',
  celebrate(forgotPasswordSchema),
  asyncHandler(AuthController.forgotPassword),
);

// Reset password – consume reset token
router.post(
  '/v1/auth/reset-password',
  celebrate(resetPasswordSchema),
  asyncHandler(AuthController.resetPassword),
);

/* --------------------------- Social login: Google -------------------------- */

// Redirect user to Google OAuth consent page
router.get(
  '/v1/auth/google',
  passport.authenticate('google', {
    scope: ['profile', 'email'],
    prompt: 'select_account',
  }),
);

// Google OAuth callback URI
router.get(
  '/v1/auth/google/callback',
  passport.authenticate('google', {
    session: false,
    failureRedirect: `${process.env.WEB_APP_URL}/login?provider=google&status=failure`,
  }),
  // On success – issue JWT tokens & redirect back to SPA with short-lived code
  asyncHandler(AuthController.handleOauthSuccess),
);

/* ------------------------- Session sanity-check ping ----------------------- */
/**
 * Very light-weight endpoint for the SPA to determine whether a JWT access
 * token is still valid without forcing a 401 on some other resource.
 */
router.get(
  '/v1/auth/status',
  authenticate,
  asyncHandler((req, res) => {
    res.json({ ok: true, user: req.user });
  }),
);

/* -------------------------------------------------------------------------- */
/*                         ── Celebrate error handler ──                      */
/* -------------------------------------------------------------------------- */

// Attach celebrate's error middleware **after** all routes
router.use(celebrateErrors());

// Unexpected error fall-through (never expose internals to the client)
router.use((err, _req, res, _next) => {
  logger.error(err);

  // In production we only leak limited info
  const status = err.status || 500;
  const message =
    status === 500
      ? 'Unexpected server error.'
      : err.message || 'Unknown error occurred.';

  res.status(status).json({ status, message });
});

module.exports = router;
```