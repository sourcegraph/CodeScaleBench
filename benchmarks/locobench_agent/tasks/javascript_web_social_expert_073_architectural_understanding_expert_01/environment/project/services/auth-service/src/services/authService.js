```javascript
/**
 * Auth Service
 * ------------
 * Centralized service for handling user authentication & session lifecycle.
 * Responsibilities:
 *   • Local credential authentication
 *   • OAuth/social login hand-off
 *   • JWT access / refresh token issuance & rotation
 *   • Session persistence (Redis)
 *   • Domain-event emission to the platform bus
 *
 * NOTE: This module is **framework-agnostic**. It can be wired into an
 * Express/Koa/Fastify controller layer or invoked from GraphQL resolvers.
 */

'use strict';

/* ────────────────────────────────────────────────────────────────────────── */
/* External Dependencies                                                     */
/* ────────────────────────────────────────────────────────────────────────── */
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const { v4: uuidv4 } = require('uuid');
const createError = require('http-errors');

/* ────────────────────────────────────────────────────────────────────────── */
/* Internal Dependencies (Dependency-Injected — see constructor)             */
/* ────────────────────────────────────────────────────────────────────────── */
// • userRepository          – CRUD operations for User aggregate (DB/ORM)
// • sessionRepository       – Redis cache adapter
// • socialAuthProvider      – Strategy for verifying upstream social token
// • eventBus                – Kafka/NATS producer wrapper
// • logger                  – Winston/Pino logger instance
// • config                  – Centralized configuration module

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants                                                                 */
/* ────────────────────────────────────────────────────────────────────────── */
const ACCESS_TOKEN_TTL = '15m';         // Short-lived JWT (minimize blast radius)
const REFRESH_TOKEN_TTL_SEC = 60 * 60 * 24 * 7; // 7 days (Redis expiry)

/* ────────────────────────────────────────────────────────────────────────── */

class AuthService {
  /**
   * @param {Object} deps
   * @param {import('../repositories/userRepository')} deps.userRepository
   * @param {import('../repositories/sessionRepository')} deps.sessionRepository
   * @param {import('../providers/socialAuthProvider')} deps.socialAuthProvider
   * @param {import('../infrastructure/eventBus')} deps.eventBus
   * @param {import('../utils/logger')} deps.logger
   * @param {import('../config')} deps.config
   */
  constructor ({
    userRepository,
    sessionRepository,
    socialAuthProvider,
    eventBus,
    logger,
    config
  }) {
    this.userRepository = userRepository;
    this.sessionRepository = sessionRepository;
    this.socialAuthProvider = socialAuthProvider;
    this.eventBus = eventBus;
    this.logger = logger;
    this.config = config;
  }

  /* ────────────────────────────────────────────────────────────────────── */
  /* Public API                                                             */
  /* ────────────────────────────────────────────────────────────────────── */

  /**
   * Register a new user with email & password credentials.
   * Emits: UserRegistered
   */
  async registerUser ({ email, password, fullName }) {
    const existing = await this.userRepository.findByEmail(email);
    if (existing) {
      throw createError.Conflict('E-mail already in use');
    }

    const hashed = await bcrypt.hash(password, this.config.security.saltRounds);
    const user = await this.userRepository.create({
      email,
      passwordHash: hashed,
      fullName,
      status: 'PENDING_VERIFICATION'
    });

    // Post-registration side-effects
    this._emitEvent('UserRegistered', { userId: user.id, email });

    // Mask passwordHash before returning
    const sanitized = { ...user, passwordHash: undefined };
    return sanitized;
  }

  /**
   * Authenticate via traditional e-mail/password credentials
   * Emits: UserLoggedIn
   */
  async loginWithEmail ({ email, password, userAgent, ipAddress }) {
    const user = await this.userRepository.findByEmail(email);
    if (!user) {
      throw createError.Unauthorized('Invalid credentials');
    }

    const passwordMatches = await bcrypt.compare(password, user.passwordHash);
    if (!passwordMatches) {
      throw createError.Unauthorized('Invalid credentials');
    }

    return this._issueSession({ user, channel: 'PASSWORD', userAgent, ipAddress });
  }

  /**
   * Authenticate via OAuth/Social provider
   * Emits: UserLoggedIn
   */
  async loginWithSocial ({
    provider,
    accessToken,
    userAgent,
    ipAddress
  }) {
    // Delegates token verification to provider strategy (Google, Facebook…)
    const profile = await this.socialAuthProvider.verifyToken(provider, accessToken);
    if (!profile || !profile.email) {
      throw createError.Unauthorized('Social token verification failed');
    }

    const user = await this._findOrProvisionSocialUser(provider, profile);

    return this._issueSession({ user, channel: provider.toUpperCase(), userAgent, ipAddress });
  }

  /**
   * Rotate/refresh an expired access token using a refresh token.
   */
  async refreshAccessToken (refreshToken) {
    let payload;
    try {
      payload = jwt.verify(refreshToken, this.config.security.refreshTokenSecret);
    } catch (err) {
      this.logger.warn('Invalid refresh token', { err });
      throw createError.Unauthorized('Invalid refresh token');
    }

    const session = await this.sessionRepository.findById(payload.sid);
    if (!session || session.revoked) {
      throw createError.Unauthorized('Session expired');
    }

    // Optional: refresh token rotation
    const accessToken = this._generateAccessToken(session.userId);
    return { accessToken };
  }

  /**
   * Explicit logout: revoke session & clean refresh token.
   * Emits: UserLoggedOut
   */
  async logout (refreshToken) {
    try {
      const { sid } = jwt.verify(refreshToken, this.config.security.refreshTokenSecret);
      await this.sessionRepository.revoke(sid);

      this._emitEvent('UserLoggedOut', { sessionId: sid });

      return { success: true };
    } catch (err) {
      this.logger.warn('Failed logout attempt', { err });
      // Swallow error: do not leak token parsing details
      throw createError.BadRequest('Bad logout request');
    }
  }

  /* ────────────────────────────────────────────────────────────────────── */
  /* Private Helper Methods                                                 */
  /* ---------------------------------------------------------------------- */

  async _issueSession ({ user, channel, userAgent, ipAddress }) {
    const sessionId = uuidv4();

    await this.sessionRepository.create({
      id: sessionId,
      userId: user.id,
      channel,
      userAgent,
      ipAddress,
      createdAt: new Date(),
      revoked: false,
      expiresIn: REFRESH_TOKEN_TTL_SEC
    });

    const accessToken = this._generateAccessToken(user.id);
    const refreshToken = this._generateRefreshToken(sessionId);

    this._emitEvent('UserLoggedIn', { userId: user.id, sessionId, channel });

    return {
      user: { id: user.id, email: user.email, fullName: user.fullName },
      tokens: { accessToken, refreshToken }
    };
  }

  /**
   * Generate a short-lived JWT access token.
   * @private
   */
  _generateAccessToken (userId) {
    return jwt.sign(
      { sub: userId, typ: 'access' },
      this.config.security.accessTokenSecret,
      { expiresIn: ACCESS_TOKEN_TTL }
    );
  }

  /**
   * Generate a long-lived, opaque refresh token bound to a specific session ID.
   * @private
   */
  _generateRefreshToken (sessionId) {
    return jwt.sign(
      { sid: sessionId, typ: 'refresh' },
      this.config.security.refreshTokenSecret,
      { expiresIn: REFRESH_TOKEN_TTL_SEC }
    );
  }

  /**
   * Emit domain events onto central event bus with minimal coupling.
   * Swallows errors to avoid breaking the request flow.
   * @private
   */
  _emitEvent (type, payload) {
    this.eventBus
      .publish(type, payload)
      .catch(err => this.logger.error('Failed to emit event', { type, err }));
  }

  /**
   * Find existing user by provider UID or create one on-the-fly.
   * @private
   */
  async _findOrProvisionSocialUser (provider, profile) {
    let user = await this.userRepository.findBySocialUid(provider, profile.id);

    if (!user) {
      user = await this.userRepository.create({
        email: profile.email,
        fullName: profile.name,
        status: 'ACTIVE',
        social: { [provider]: profile.id }
      });

      this._emitEvent('UserRegistered', { userId: user.id, email: profile.email, provider });
    }

    return user;
  }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Singleton Instance Export (DI container could override if needed)         */
/* ────────────────────────────────────────────────────────────────────────── */

const { userRepository } = require('../repositories/userRepository');
const { sessionRepository } = require('../repositories/sessionRepository');
const socialAuthProvider = require('../providers/socialAuthProvider');
const eventBus = require('../infrastructure/eventBus');
const logger = require('../utils/logger');
const config = require('../config');

module.exports = new AuthService({
  userRepository,
  sessionRepository,
  socialAuthProvider,
  eventBus,
  logger,
  config
});
```