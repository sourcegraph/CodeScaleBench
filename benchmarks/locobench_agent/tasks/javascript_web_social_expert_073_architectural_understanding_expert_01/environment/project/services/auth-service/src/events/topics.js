```javascript
/**
 * PulseLearn Campus Hub — Auth-Service
 * ------------------------------------
 * Centralised definition for all Kafka/NATS subjects (a.k.a “topics”)
 * that the authentication service publishes to, or listens for.
 *
 * Keeping the naming strategy in a single file guarantees:
 *   • Consistency across producers/consumers
 *   • Simplified refactors (e.g. adding namespaces or version bumps)
 *   • Run-time validation & developer-friendly autocompletion
 *
 * Topic shape (dot-separated):
 *   <namespace>.<domain>.<service>.<event>.<version>
 *
 * Examples:
 *   pulselearn.user.auth.user-registered.v1
 *   pulselearn.user.identity.identity-verified.v1
 *
 * NOTE: We stay compatible with both Kafka & NATS by avoiding characters
 * that are disallowed in either broker.
 */

/* eslint-disable camelcase */
'use strict';

/* ---------------------------------- */
/* 3rd-party dependencies             */
/* ---------------------------------- */
const assert = require('node:assert');

/* ---------------------------------- */
/* Environment controls               */
/* ---------------------------------- */
const ENV_NAMESPACE =
  process.env.EVENT_BUS_NAMESPACE?.trim().toLowerCase() || 'pulselearn';
const VERSION_PREFIX = 'v';

/* ---------------------------------- */
/* Helper utilities                   */
/* ---------------------------------- */

/**
 * Asserts that a string is safe for topic composition.
 * @param {string} segment
 * @param {string} label ‑ Developer-friendly field name.
 */
function validateSegment(segment, label) {
  assert(
    typeof segment === 'string' && segment.length > 0,
    new TypeError(`${label} must be a non-empty string`)
  );

  // Only allow lowercase letters, digits and hyphens (fits Kafka/NATS)
  const SAFE_SEGMENT = /^[a-z0-9-]+$/;
  assert(
    SAFE_SEGMENT.test(segment),
    new TypeError(
      `${label}="${segment}" contains illegal characters; ` +
        'Only lowercase letters, digits and hyphens are permitted.'
    )
  );
}

/**
 * Composes a fully-qualified topic from parts.
 * @param {Object} parts
 * @param {string} parts.namespace   — Logical cluster (e.g., “pulselearn”)
 * @param {string} parts.domain      — Broad bounded-context (e.g., “user”)
 * @param {string} parts.service     — Producing micro-service (e.g., “auth”)
 * @param {string} parts.event       — Domain event (e.g., “user-registered”)
 * @param {number} [parts.version=1] — Semantic version number
 * @returns {string}
 */
function buildTopic({ namespace, domain, service, event, version = 1 }) {
  [namespace, domain, service, event].forEach((seg, idx) =>
    validateSegment(seg, ['namespace', 'domain', 'service', 'event'][idx])
  );
  assert(
    Number.isInteger(version) && version > 0,
    new TypeError('version must be a positive integer')
  );

  return [
    namespace,
    domain,
    service,
    event,
    `${VERSION_PREFIX}${version}`
  ].join('.');
}

/**
 * Extracts parts from a fully-qualified topic. Throws if invalid format.
 * @param {string} topic
 * @returns {Required<Parameters<typeof buildTopic>[0]>}
 */
function parseTopic(topic) {
  validateSegment(topic, 'topic');

  const match = topic.match(
    /^([a-z0-9-]+)\.([a-z0-9-]+)\.([a-z0-9-]+)\.([a-z0-9-]+)\.v(\d+)$/
  );

  if (!match) {
    throw new Error(`Invalid topic format: "${topic}"`);
  }

  const [, namespace, domain, service, event, versionStr] = match;

  return {
    namespace,
    domain,
    service,
    event,
    version: Number(versionStr)
  };
}

/* ---------------------------------- */
/* Topic Catalog                      */
/* ---------------------------------- */

const DOMAIN = 'user';
const SERVICE = 'auth';

/**
 * Outbound topics (events PRODUCED by this service).
 */
const Outbound = Object.freeze({
  USER_REGISTERED: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: SERVICE,
    event: 'user-registered',
    version: 1
  }),

  USER_LOGGED_IN: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: SERVICE,
    event: 'user-logged-in',
    version: 1
  }),

  USER_LOGGED_OUT: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: SERVICE,
    event: 'user-logged-out',
    version: 1
  }),

  PASSWORD_CHANGED: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: SERVICE,
    event: 'password-changed',
    version: 1
  }),

  SESSION_EXPIRED: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: SERVICE,
    event: 'session-expired',
    version: 1
  }),

  MFA_CHALLENGE_PASSED: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: SERVICE,
    event: 'mfa-challenge-passed',
    version: 1
  }),

  ROLE_UPDATED: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: SERVICE,
    event: 'role-updated',
    version: 1
  })
});

/**
 * Inbound topics (events CONSUMED by this service).
 * NB: These are emitted by other bounded contexts.
 */
const Inbound = Object.freeze({
  IDENTITY_VERIFIED: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: 'identity',
    event: 'identity-verified',
    version: 1
  }),

  BADGE_AWARDED: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: 'achievement',
    service: 'gamification',
    event: 'badge-awarded',
    version: 1
  }),

  ACCOUNT_DELETED: buildTopic({
    namespace: ENV_NAMESPACE,
    domain: DOMAIN,
    service: 'profile',
    event: 'account-deleted',
    version: 1
  })
});

/* ---------------------------------- */
/* Runtime helpers                    */
/* ---------------------------------- */

/**
 * Determines if a topic is recognised (i.e., present in Outbound|Inbound).
 * @param {string} topic
 * @returns {boolean}
 */
function isKnownTopic(topic) {
  return (
    Object.values(Outbound).includes(topic) ||
    Object.values(Inbound).includes(topic)
  );
}

/**
 * Throws if the topic is unknown to this service. Useful in guards.
 * @param {string} topic
 */
function assertKnownTopic(topic) {
  if (!isKnownTopic(topic)) {
    throw new Error(`Unknown topic: "${topic}"`);
  }
}

/* ---------------------------------- */
/* Exports                            */
/* ---------------------------------- */

module.exports = {
  // Catalog
  Outbound,
  Inbound,

  // Utilities
  buildTopic,
  parseTopic,
  isKnownTopic,
  assertKnownTopic
};
```