```javascript
/**
 * PulseLearn Campus Hub – Course Service
 * --------------------------------------
 * This service contains all domain logic related to Courses—creation, retrieval,
 * update, deletion, enrollment, and progress tracking.  A typical workflow:
 *
 * 1. Request hits the CourseController                 (MVC)
 * 2. Controller delegates to CourseService             (Service Layer)
 * 3. Service queries DB through Prisma ORM             (Repository Pattern)
 * 4. Service publishes Course domain events to Kafka   (Event Backbone)
 * 5. Service caches hot data in Redis                  (Performance)
 *
 * NOTE: Do not import this file directly from your controllers; always consume
 * it via the service locator (`src/di/index.js`) to keep dependencies swappable
 * and mock-able during tests.
 */

'use strict';

/* ───────────────────────────────── External Dependencies ─────────────────── */
const { PrismaClient, Prisma } = require('@prisma/client');
const { Kafka }           = require('kafkajs');
const Redis               = require('ioredis');
const { v4: uuid }        = require('uuid');
const winston             = require('winston');
const _                   = require('lodash');

/* ───────────────────────────────── Internal Dependencies ─────────────────── */
const { EventTopics }     = require('../constants/event-topics');
const { AppError }        = require('../errors/app-error');
const { ErrorCodes }      = require('../constants/error-codes');

/* ───────────────────────────────── Singleton Instances ───────────────────── */
const prisma  = new PrismaClient();
const redis   = new Redis(process.env.REDIS_URL || 'redis://localhost:6379');

const kafka   = new Kafka({
  clientId: 'course-service',
  brokers : (process.env.KAFKA_BROKERS || 'localhost:9092').split(',')
});
const producer = kafka.producer();

/* ───────────────────────────────── Logger Setup ──────────────────────────── */
const logger = winston.createLogger({
  level    : process.env.NODE_ENV === 'production' ? 'info' : 'debug',
  transports: [
    new winston.transports.Console({
      format: winston.format.combine(
        winston.format.colorize(),
        winston.format.timestamp(),
        winston.format.printf(
          ({ timestamp, level, message, ...meta }) =>
            `${timestamp} [${level}] ${message} ${Object.keys(meta).length ? JSON.stringify(meta) : ''}`
        )
      )
    })
  ]
});

/* ───────────────────────────────── Utility Functions ─────────────────────── */

/**
 * Centralized helper to publish events to Kafka.
 * All events from this service should pass through this function to guarantee
 * consistent headers, tracing IDs, and error handling.
 *
 * @param {String} topic
 * @param {Object} payload
 * @param {Object} [headers={}] - Additional Kafka headers
 */
async function publishEvent(topic, payload, headers = {}) {
  try {
    await producer.connect(); // NOOP after first call
    await producer.send({
      topic,
      messages: [
        {
          key    : uuid(),           // partitioning key
          value  : JSON.stringify(payload),
          headers: {
            'trace-id': uuid(),
            ...headers
          }
        }
      ]
    });
    logger.debug(`Event published: ${topic}`, { payload });
  } catch (err) {
    // We never throw from publishEvent; instead we log and continue.
    logger.error('Failed to publish event', { topic, err: err.stack || err });
  }
}

/**
 * Cache wrapper for GET queries. Uses Redis with JSON serialization.
 * @param {String} key
 * @param {Function} resolver - Function that returns a Promise of the data
 * @param {Number} ttlSeconds - Time-to-live
 */
async function getOrSetCache(key, resolver, ttlSeconds = 60) {
  const cached = await redis.get(key);
  if (cached) {
    return JSON.parse(cached);
  }
  const fresh = await resolver();
  await redis.set(key, JSON.stringify(fresh), 'EX', ttlSeconds);
  return fresh;
}

/* ───────────────────────────────── Domain Service ────────────────────────── */
class CourseService {
  /* ======================================================================= *
   * PUBLIC API                                                              *
   * ======================================================================= */

  /**
   * Creates a brand-new course and its initial metadata.
   * @param {Object} courseData
   * @param {String} creatorId
   * @returns {Promise<Object>} Newly created course
   */
  async createCourse(courseData, creatorId) {
    const { title, description, category, thumbnailUrl, publishedAt } = courseData;

    // Basic validation
    if (!title || title.length < 3) {
      throw new AppError('Course title must be at least 3 characters long', ErrorCodes.VALIDATION);
    }

    try {
      const course = await prisma.$transaction(async (tx) => {
        // 1. Insert into Course table
        const newCourse = await tx.course.create({
          data: {
            id          : uuid(),
            title,
            description,
            category,
            thumbnailUrl,
            publishedAt : publishedAt || null,
            creatorId,
            status      : 'DRAFT'
          }
        });

        // 2. Auto-enroll creator as instructor
        await tx.courseEnrollment.create({
          data: {
            userId  : creatorId,
            courseId: newCourse.id,
            role    : 'INSTRUCTOR'
          }
        });

        return newCourse;
      });

      // 3. Publish event outside transaction
      await publishEvent(EventTopics.COURSE_CREATED, {
        courseId : course.id,
        creatorId,
        timestamp: new Date().toISOString()
      });

      return course;
    } catch (err) {
      logger.error('createCourse failed', { err: err.stack || err });
      if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === 'P2002') {
        // Unique constraint.
        throw new AppError('A course with the same title already exists', ErrorCodes.CONFLICT);
      }
      throw err;
    }
  }

  /**
   * Retrieves a course by its ID, with optional lessons & enrollment info.
   * Makes heavy use of Redis for fast repeated look-ups.
   *
   * @param {String} courseId
   * @param {Object} [options]
   * @param {Boolean} [options.includeLessons=false]
   * @param {Boolean} [options.includeStats=false]
   */
  async getCourseById(courseId, options = {}) {
    if (!courseId) throw new AppError('courseId is required', ErrorCodes.VALIDATION);
    const { includeLessons = false, includeStats = false } = options;

    const cacheKey = `course:${courseId}:${includeLessons}:${includeStats}`;

    return getOrSetCache(
      cacheKey,
      async () => {
        const course = await prisma.course.findUnique({
          where: { id: courseId },
          include: {
            lessons: includeLessons,
            // stats is a materialized view; simulated via compute
          }
        });

        if (!course) {
          throw new AppError('Course not found', ErrorCodes.NOT_FOUND);
        }

        if (includeStats) {
          const [enrolled, completed] = await Promise.all([
            prisma.courseEnrollment.count({ where: { courseId } }),
            prisma.lessonCompletion.count({ where: { courseId } })
          ]);
          course.stats = { enrolled, completed };
        }

        return course;
      },
      30 // seconds
    );
  }

  /**
   * Updates mutable fields of a course.  Immutable fields like id and creatorId
   * are ignored automatically via lodash.pick.
   *
   * @param {String} courseId
   * @param {Object} updates
   * @param {String} requesterId - Authorization performed here.
   */
  async updateCourse(courseId, updates, requesterId) {
    const allowed = ['title', 'description', 'category', 'thumbnailUrl', 'publishedAt', 'status'];
    const sanitized = _.pick(updates, allowed);

    // Early bail-out
    if (_.isEmpty(sanitized)) {
      throw new AppError('No valid fields to update', ErrorCodes.VALIDATION);
    }

    // Authorization: only creator or admin can update
    const course = await prisma.course.findUnique({ where: { id: courseId } });
    if (!course) throw new AppError('Course not found', ErrorCodes.NOT_FOUND);

    const isAdmin = await this.#isAdmin(requesterId);
    if (course.creatorId !== requesterId && !isAdmin) {
      throw new AppError('Forbidden', ErrorCodes.FORBIDDEN, 403);
    }

    try {
      const updated = await prisma.course.update({
        where: { id: courseId },
        data : sanitized
      });

      // Invalidate cache
      await redis.del(`course:${courseId}:*`);

      await publishEvent(EventTopics.COURSE_UPDATED, {
        courseId,
        updaterId: requesterId,
        changes  : Object.keys(sanitized),
        timestamp: new Date().toISOString()
      });

      return updated;
    } catch (err) {
      logger.error('updateCourse failed', { err: err.stack || err });
      throw err;
    }
  }

  /**
   * Enroll a user into a course, supports roles: STUDENT, AUDITOR
   *
   * @param {String} courseId
   * @param {String} userId
   * @param {"STUDENT"|"AUDITOR"} role
   */
  async enrollUser(courseId, userId, role = 'STUDENT') {
    if (!['STUDENT', 'AUDITOR'].includes(role)) {
      throw new AppError('Invalid role', ErrorCodes.VALIDATION);
    }

    try {
      await prisma.courseEnrollment.create({
        data: {
          id      : uuid(),
          courseId,
          userId,
          role
        }
      });

      // Bump course enrollment count metric
      await publishEvent(EventTopics.USER_ENROLLED, {
        courseId,
        userId,
        role,
        timestamp: new Date().toISOString()
      });

      // Evict course stats cache so count is fresh
      await redis.del(`course:${courseId}:false:true`);
    } catch (err) {
      if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === 'P2002') {
        // Unique constraint violation → already enrolled
        throw new AppError('User already enrolled', ErrorCodes.CONFLICT);
      }
      throw err;
    }
  }

  /**
   * Tracks lesson completion for a learner.
   * @param {String} courseId
   * @param {String} lessonId
   * @param {String} userId
   */
  async completeLesson(courseId, lessonId, userId) {
    const idempotencyKey = `${userId}:${lessonId}:completion`;
    const lock = await redis.set(idempotencyKey, '1', 'NX', 'EX', 5);
    if (!lock) {
      // Duplicate submission within 5 seconds
      return;
    }

    try {
      await prisma.lessonCompletion.create({
        data: {
          id       : uuid(),
          courseId,
          lessonId,
          userId
        }
      });

      await publishEvent(EventTopics.LESSON_COMPLETED, {
        courseId,
        lessonId,
        userId,
        timestamp: new Date().toISOString()
      });

      await redis.del(`course:${courseId}:*`);
    } catch (err) {
      if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === 'P2002') {
        // Duplicate completion (idempotent)
        return;
      }
      throw err;
    }
  }

  /**
   * Deletes a course; only admins can perform hard-deletes.
   *
   * @param {String} courseId
   * @param {String} requesterId
   */
  async deleteCourse(courseId, requesterId) {
    const isAdmin = await this.#isAdmin(requesterId);
    if (!isAdmin) {
      throw new AppError('Admin rights required', ErrorCodes.FORBIDDEN, 403);
    }

    await prisma.$transaction([
      prisma.courseEnrollment.deleteMany({ where: { courseId } }),
      prisma.lessonCompletion.deleteMany({ where: { courseId } }),
      prisma.course.delete({ where: { id: courseId } })
    ]);

    await redis.del(`course:${courseId}:*`);

    await publishEvent(EventTopics.COURSE_DELETED, {
      courseId,
      deleterId : requesterId,
      timestamp : new Date().toISOString()
    });

    return { success: true };
  }

  /* ======================================================================= *
   * PRIVATE HELPERS                                                         *
   * ======================================================================= */

  /**
   * Determines if the user is an admin by checking cached claims.
   * @private
   * @param {String} userId
   * @returns {Promise<Boolean>}
   */
  async #isAdmin(userId) {
    const cacheKey = `user:${userId}:isAdmin`;
    const cached   = await redis.get(cacheKey);
    if (cached !== null) return cached === 'true';

    // This would normally hit the Auth/User service. Hard-coded for brevity.
    const isAdmin = await prisma.user.findUnique({
      where : { id: userId },
      select: { roles: true }
    }).then(u => u?.roles.includes('ADMIN') || false);

    await redis.set(cacheKey, isAdmin, 'EX', 60);
    return isAdmin;
  }
}

/* ───────────────────────── Exports (Singleton by Convention) ─────────────── */
module.exports = new CourseService();
```