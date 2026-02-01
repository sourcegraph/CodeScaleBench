```javascript
/**
 * CourseRepository
 * ----------------
 * Repository layer in charge of all persistence-level operations for the Course
 * aggregate.  This class is intentionally kept free of any HTTP concerns so it
 * can be reused by CLI scripts, background workers, and GraphQL resolvers.
 *
 * Responsibilities:
 *  - CRUD for Courses (+ relational entities such as Modules & Enrollments)
 *  - Intelligent read-through / write-through caching to Redis
 *  - Transaction management handed off to the service layer, but supported
 *  - Basic optimistic‐locking via Sequelize’s version counter
 *
 * NOTE:
 *   Every public method either returns a plain JavaScript object or throws.
 */

'use strict';

const { Op } = require('sequelize');
const { v4: uuidv4 } = require('uuid');

const DEFAULT_CACHE_TTL = 60 * 5; // seconds

class CourseRepository {
  /**
   * @param {object} deps
   * @param {import('sequelize').Sequelize['models']} deps.models – Injected Sequelize models
   * @param {import('ioredis').Redis} deps.cache – Shared Redis client
   * @param {import('pino').BaseLogger} deps.logger – Application-wide logger
   */
  constructor({ models, cache, logger }) {
    if (!models?.Course) {
      throw new Error('Course model must be provided to CourseRepository.');
    }

    this.Course = models.Course;
    this.Module = models.Module;
    this.Enrollment = models.Enrollment;
    this.cache = cache;
    this.log = logger.child({ layer: 'repository', entity: 'Course' });
  }

  /* ---------------------------------------------------------------------- *\
     PUBLIC – READ OPERATIONS
  \* ---------------------------------------------------------------------- */

  /**
   * Fetch a single course by its primary key.  Falls back to DB if the cache
   * miss occurs, then hydrates the cache for subsequent requests.
   *
   * @param {string} courseId
   * @param {object} [options]
   * @param {import('sequelize').Transaction} [options.transaction]
   * @returns {Promise<object|null>}
   */
  async findById(courseId, options = {}) {
    const cacheKey = `course:${courseId}`;

    if (this.cache) {
      const cached = await this.cache.get(cacheKey);
      if (cached) {
        this.log.debug({ courseId }, 'Cache hit');
        return JSON.parse(cached);
      }
    }

    const course = await this.Course.findByPk(courseId, {
      transaction: options.transaction,
      include: [
        { model: this.Module, as: 'modules' },
        { model: this.Enrollment, as: 'enrollments' }
      ]
    });

    if (course && this.cache) {
      await this.cache.set(cacheKey, JSON.stringify(course.toJSON()), 'EX', DEFAULT_CACHE_TTL);
    }

    return course ? course.toJSON() : null;
  }

  /**
   * Retrieve courses with arbitrary filtering, sorting, and pagination.
   * Useful for admin dashboards & catalog browsing.
   *
   * @param {object} filters
   * @param {string} [filters.search] – Free-text search
   * @param {string[]} [filters.tags] – Course tag names
   * @param {number} [filters.limit=20]
   * @param {number} [filters.offset=0]
   * @returns {Promise<{rows: object[], count: number}>}
   */
  async list(filters = {}) {
    const {
      search,
      tags = [],
      limit = 20,
      offset = 0
    } = filters;

    /* Build dynamic where-clause */
    const where = {};

    if (search) {
      where[Op.or] = [
        { title: { [Op.iLike]: `%${search}%` } },
        { description: { [Op.iLike]: `%${search}%` } }
      ];
    }

    if (tags.length) {
      where.tags = { [Op.contains]: tags };
    }

    const result = await this.Course.findAndCountAll({
      where,
      order: [['createdAt', 'DESC']],
      limit,
      offset
    });

    return {
      count: result.count,
      rows: result.rows.map((r) => r.toJSON())
    };
  }

  /* ---------------------------------------------------------------------- *\
     PUBLIC – WRITE OPERATIONS
  \* ---------------------------------------------------------------------- */

  /**
   * Persist a new course.
   *
   * @param {object} payload
   * @param {string} payload.title
   * @param {string} payload.description
   * @param {string[]} [payload.tags]
   * @param {import('sequelize').Transaction} [transaction]
   * @returns {Promise<object>}
   */
  async createCourse(payload, transaction) {
    const id = uuidv4();

    const course = await this.Course.create(
      {
        id,
        ...payload
      },
      { transaction }
    );

    this.log.info({ courseId: id }, 'Course created');
    return course.toJSON();
  }

  /**
   * Update course details using optimistic-locking (if enabled on model).
   *
   * @param {string} id
   * @param {object} updates
   * @param {number} [expectedVersion] – For concurrency control
   * @param {import('sequelize').Transaction} [transaction]
   * @returns {Promise<object|null>}
   */
  async updateCourse(id, updates, expectedVersion, transaction) {
    const where = { id };
    if (typeof expectedVersion === 'number') {
      where.version = expectedVersion;
    }

    const [affected, rows] = await this.Course.update(updates, {
      where,
      returning: true,
      transaction
    });

    if (!affected) {
      throw new Error(
        `Course ${id} update failed: version mismatch or not found.`
      );
    }

    // Invalidate cache
    if (this.cache) {
      await this.cache.del(`course:${id}`);
    }

    const updated = rows[0].toJSON();
    this.log.info({ courseId: id }, 'Course updated');
    return updated;
  }

  /**
   * Soft delete course – sets deletedAt timestamp so the record can be restored.
   *
   * @param {string} id
   * @param {import('sequelize').Transaction} [transaction]
   * @returns {Promise<void>}
   */
  async deleteCourse(id, transaction) {
    await this.Course.destroy({ where: { id }, transaction });
    if (this.cache) {
      await this.cache.del(`course:${id}`);
    }
    this.log.warn({ courseId: id }, 'Course deleted (soft)');
  }

  /**
   * Append a module to a course.
   *
   * @param {string} courseId
   * @param {object} modulePayload
   * @param {string} modulePayload.title
   * @param {string} modulePayload.contentUrl
   * @param {import('sequelize').Transaction} [transaction]
   * @returns {Promise<object>}
   */
  async addModule(courseId, modulePayload, transaction) {
    const course = await this.Course.findByPk(courseId, { transaction });
    if (!course) {
      throw new Error(`Course not found: ${courseId}`);
    }

    const module = await this.Module.create(
      {
        id: uuidv4(),
        courseId,
        ...modulePayload
      },
      { transaction }
    );

    // Bust course cache because nested relation changed
    if (this.cache) {
      await this.cache.del(`course:${courseId}`);
    }

    this.log.info({ courseId, moduleId: module.id }, 'Module added');
    return module.toJSON();
  }

  /**
   * Enroll a student into a course.
   *
   * @param {string} courseId
   * @param {string} studentId
   * @param {import('sequelize').Transaction} [transaction]
   * @returns {Promise<object>}
   */
  async enrollStudent(courseId, studentId, transaction) {
    // Idempotency: ensure unique composite index on (courseId, studentId)
    const [enrollment] = await this.Enrollment.findOrCreate({
      where: { courseId, studentId },
      defaults: {
        id: uuidv4(),
        courseId,
        studentId
      },
      transaction
    });

    if (this.cache) {
      await this.cache.del(`course:${courseId}`);
    }

    this.log.info({ courseId, studentId }, 'Student enrolled');
    return enrollment.toJSON();
  }

  /* ---------------------------------------------------------------------- *\
     INTERNAL HELPERS
  \* ---------------------------------------------------------------------- */

  /**
   * Clears all cached courses.  
   * Heavy-handed, but useful for admin-level destructive operations.
   *
   * @returns {Promise<void>}
   */
  async _flushCache() {
    if (!this.cache) return;
    const keys = await this.cache.keys('course:*');
    if (keys.length) await this.cache.del(keys);
  }
}

module.exports = CourseRepository;
```