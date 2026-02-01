```javascript
/**
 * sessionService.js
 * PulseLearn Campus Hub – Authentication Service
 *
 * This service encapsulates all session–related operations such as
 *  • Access/Refresh token issuance & rotation
 *  • Session persistence in Redis (fast in-memory KV store)
 *  • Session revocation & cleanup
 *  • Emitting domain events (SessionCreated / SessionExpired)
 *
 * Author: PulseLearn Engineering
 * Since : 2024-05-09
 */

'use strict';

///////////////////////////////////////////////////////////////////////////////
// External Dependencies
///////////////////////////////////////////////////////////////////////////////
const jwt             = require('jsonwebtoken');
const { v4: uuidv4 }  = require('uuid');
const Redis           = require('ioredis');
const ms              = require('ms');           // Parse / stringify TTL strings
const config          = require('../config');    // Centralised app config
const logger          = require('../utils/logger');
const eventBus        = require('../infra/eventBus'); // NATS / Kafka wrapper

///////////////////////////////////////////////////////////////////////////////
// Redis Client (singleton)
///////////////////////////////////////////////////////////////////////////////
const redis = new Redis({
  host            : config.redis.host,
  port            : config.redis.port,
  password        : config.redis.password,
  db              : config.redis.db,
  enableOfflineQueue: false, // Fail fast – don’t queue if Redis unavailable
});

redis.on('error', err => logger.error('[redis] ', err));

///////////////////////////////////////////////////////////////////////////////
// Constants
///////////////////////////////////////////////////////////////////////////////
const ACCESS_TOKEN_TTL        = ms(config.auth.accessTokenTtl);   // e.g. '15m'
const REFRESH_TOKEN_TTL       = ms(config.auth.refreshTokenTtl);  // e.g. '30d'
const SESSION_PREFIX          = 'auth:sess:';                     // Redis keyspace
const USER_SESSIONS_PREFIX    = 'auth:user-sess:';               // Set of sessionIds

///////////////////////////////////////////////////////////////////////////////
// Helpers
///////////////////////////////////////////////////////////////////////////////
/**
 * Build a Redis key from session id
 */
const sessionKey = sessionId => `${SESSION_PREFIX}${sessionId}`;

/**
 * Build a Redis key for the user’s session set
 */
const userSessionsKey = userId => `${USER_SESSIONS_PREFIX}${userId}`;

///////////////////////////////////////////////////////////////////////////////
// Core Service
///////////////////////////////////////////////////////////////////////////////
class SessionService {

  /**
   * Issue tokens + persist session
   * @param {Object} user      – { id, roles, email } (minimum requirements)
   * @param {String} userAgent – Browser/User-Agent header
   * @param {String} ip        – IP address of request origin
   */
  static async createSession(user, userAgent = 'unknown', ip = '0.0.0.0') {
    const sessionId   = uuidv4();
    const issuedAt    = Date.now();
    const refreshToken = jwt.sign(
      { sid: sessionId, sub: user.id, ver: 1, type: 'refresh' },
      config.auth.jwtSecret,
      { expiresIn: config.auth.refreshTokenTtl }
    );

    // Persist into Redis
    const sessionPayload = {
      userId    : user.id,
      roles     : user.roles,
      email     : user.email,
      userAgent ,
      ip        ,
      iat       : issuedAt,
      exp       : issuedAt + REFRESH_TOKEN_TTL,
      revoked   : false,
      version   : 1,            // For token rotation
    };

    try {
      await redis.multi()
        .hmset(sessionKey(sessionId), sessionPayload)
        .pexpire(sessionKey(sessionId), REFRESH_TOKEN_TTL)
        .sadd(userSessionsKey(user.id), sessionId)
        .exec();
    } catch (err) {
      logger.error('Failed to persist session in Redis', err);
      throw new Error('SESSION_STORE_ERROR');
    }

    const accessToken = this._generateAccessToken(user, sessionId);

    // Emit event
    eventBus.publish('SessionCreated', { sessionId, userId: user.id });

    return { accessToken, refreshToken, sessionId, expiresIn: ACCESS_TOKEN_TTL };
  }

  /**
   * Validate an access token and return its decoded claims
   * @throws Error if invalid / expired
   */
  static verifyAccessToken(token) {
    try {
      return jwt.verify(token, config.auth.jwtSecret);
    } catch (err) {
      logger.debug('Access token verification failed', err);
      throw new Error('INVALID_ACCESS_TOKEN');
    }
  }

  /**
   * Refresh an existing session (rotate tokens)
   * @param {String} refreshToken – JWT refresh token
   */
  static async rotateSession(refreshToken) {
    let decoded;
    try {
      decoded = jwt.verify(refreshToken, config.auth.jwtSecret);
    } catch (err) {
      logger.debug('Refresh token verification failed', err);
      throw new Error('INVALID_REFRESH_TOKEN');
    }

    const { sid: sessionId } = decoded;
    const key = sessionKey(sessionId);
    const session = await redis.hgetall(key);

    // Redis returns empty object if not found
    if (!session || !session.userId) {
      throw new Error('SESSION_NOT_FOUND');
    }
    if (session.revoked === 'true') {
      throw new Error('SESSION_REVOKED');
    }

    // Optional: ensure refresh token hasn't expired based on Redis TTL
    // (JWT expiration already enforced via verify)

    // Bump version to invalidate existing refresh token (rotation)
    const nextVersion = Number(session.version || 1) + 1;

    const newRefreshToken = jwt.sign(
      { sid: sessionId, sub: session.userId, ver: nextVersion, type: 'refresh' },
      config.auth.jwtSecret,
      { expiresIn: config.auth.refreshTokenTtl }
    );

    const updatedFields = {
      version: nextVersion,
      // Refresh expiry – push forward
      exp    : Date.now() + REFRESH_TOKEN_TTL,
    };

    try {
      await redis.multi()
        .hmset(key, updatedFields)
        .pexpire(key, REFRESH_TOKEN_TTL)
        .exec();
    } catch (err) {
      logger.error('Failed updating session record', err);
      throw new Error('SESSION_STORE_ERROR');
    }

    const accessToken = this._generateAccessToken({
      id   : session.userId,
      roles: JSON.parse(session.roles || '[]'),
      email: session.email,
    }, sessionId);

    return { accessToken, refreshToken: newRefreshToken, expiresIn: ACCESS_TOKEN_TTL };
  }

  /**
   * Revoke a single session by sessionId
   */
  static async revokeSession(sessionId, reason = 'USER_LOGOUT') {
    const key = sessionKey(sessionId);
    const session = await redis.hgetall(key);

    if (!session || !session.userId) return; // Already gone

    await redis.multi()
      .hset(key, 'revoked', true)
      .del(key)                                // Physically delete
      .srem(userSessionsKey(session.userId), sessionId)
      .exec();

    eventBus.publish('SessionExpired', { sessionId, userId: session.userId, reason });
  }

  /**
   * Revoke all sessions for a given user
   */
  static async revokeAllSessionsForUser(userId, reason = 'FORCE_LOGOUT') {
    const uKey   = userSessionsKey(userId);
    const sessIds = await redis.smembers(uKey);

    if (!sessIds.length) return;

    const tx = redis.multi();
    sessIds.forEach(sid => {
      tx.hset(sessionKey(sid), 'revoked', true)
        .del(sessionKey(sid))
        .srem(uKey, sid);
    });
    await tx.exec();

    eventBus.publish('UserSessionsExpired', { userId, reason, count: sessIds.length });
  }

  /**
   * Utility to generate stateless access JWT
   */
  static _generateAccessToken(user, sessionId) {
    return jwt.sign(
      {
        sub: user.id,
        sid: sessionId,
        roles: user.roles,
        email: user.email,
        type: 'access',
      },
      config.auth.jwtSecret,
      { expiresIn: config.auth.accessTokenTtl }
    );
  }
}

module.exports = SessionService;
```