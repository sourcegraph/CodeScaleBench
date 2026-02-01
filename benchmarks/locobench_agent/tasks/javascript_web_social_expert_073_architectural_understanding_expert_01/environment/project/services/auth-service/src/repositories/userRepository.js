```javascript
/**
 * PulseLearn Campus Hub
 * Repository: UserRepository
 *
 * Responsibilities:
 *  - Encapsulate all persistence-layer logic related to the User aggregate.
 *  - Expose a clean API for the service layer.
 *  - Handle cross-cutting concerns such as transactions, caching, and event publication.
 *
 * Dependencies are injected to keep the module framework-agnostic and easily testable.
 */

'use strict';

const bcrypt = require('bcrypt');
const { Op } = require('sequelize');

const SALT_ROUNDS = 12;
const CACHE_TTL_SECONDS = 60 * 60; // 1 hour

/**
 * Custom Error thrown when a user record cannot be located.
 */
class UserNotFoundError extends Error {
  constructor(message = 'User not found') {
    super(message);
    this.name = 'UserNotFoundError';
    this.code = 'USER_NOT_FOUND';
  }
}

/**
 * Repository implementation for the User entity.
 */
class UserRepository {
  /**
   * @param {Object} deps
   * @param {import('sequelize').Model} deps.UserModel            – Sequelize model for User.
   * @param {import('sequelize').Sequelize} deps.sequelize        – Sequelize instance for transactions.
   * @param {import('ioredis').Redis} [deps.cache]                – Optional redis client.
   * @param {import('../events/eventBus')} [deps.eventBus]        – Domain event bus abstraction.
   * @param {import('../utils/logger').Logger} deps.logger        – Application-level logger.
   */
  constructor({ UserModel, sequelize, cache, eventBus, logger }) {
    if (!UserModel || !sequelize || !logger) {
      throw new Error(
        'UserRepository requires UserModel, sequelize, and logger instances'
      );
    }

    this.UserModel = UserModel;
    this.sequelize = sequelize;
    this.cache = cache;
    this.eventBus = eventBus;
    this.logger = logger.child({ context: 'UserRepository' });
  }

  /* -------------------------------------------------------------------------- */
  /*                              Public API                                    */
  /* -------------------------------------------------------------------------- */

  /**
   * Finds a user by primary key ID.
   *
   * @param {string | number} id
   * @param {object} [options]
   * @param {boolean} [options.withCache=true]
   * @returns {Promise<object>}
   */
  async findById(id, { withCache = true } = {}) {
    const cacheKey = `user:${id}`;

    if (withCache && this.cache) {
      const cached = await this.cache.get(cacheKey);
      if (cached) {
        return JSON.parse(cached);
      }
    }

    const user = await this.UserModel.findByPk(id);
    if (!user) {
      throw new UserNotFoundError(`User with id ${id} not found`);
    }

    const safeUser = this._toSafeUser(user);

    if (withCache && this.cache) {
      await this.cache.set(cacheKey, JSON.stringify(safeUser), 'EX', CACHE_TTL_SECONDS);
    }

    return safeUser;
  }

  /**
   * Finds a user by email.
   *
   * @param {string} email
   * @param {object} [options]
   * @param {boolean} [options.withPassword=false] – When true, returns hashed password.
   * @returns {Promise<object>}
   */
  async findByEmail(email, { withPassword = false } = {}) {
    const user = await this.UserModel.findOne({
      where: { email: { [Op.iLike]: email.trim() } },
      attributes: withPassword ? undefined : { exclude: ['password'] },
    });

    if (!user) {
      throw new UserNotFoundError(`User with email ${email} not found`);
    }

    return user.get({ plain: true });
  }

  /**
   * Creates a new user record in a single atomic transaction.
   *
   * @param {object} payload – DTO containing user properties.
   * @returns {Promise<object>} – Newly created user without password hash.
   */
  async create(payload) {
    const tx = await this.sequelize.transaction();
    try {
      const hashedPassword = await bcrypt.hash(payload.password, SALT_ROUNDS);

      const newUser = await this.UserModel.create(
        {
          ...payload,
          password: hashedPassword,
        },
        { transaction: tx }
      );

      await tx.commit();

      const safeUser = this._toSafeUser(newUser);

      // side-effect: publish domain event
      await this._publishEvent('UserCreated', safeUser);

      return safeUser;
    } catch (err) {
      await tx.rollback();
      this.logger.error(err, 'Failed to create user');
      throw err;
    }
  }

  /**
   * Updates a user. Supports partial updates. Cache is invalidated automatically.
   *
   * @param {string | number} id
   * @param {object} updates
   * @returns {Promise<object>}
   */
  async update(id, updates) {
    const tx = await this.sequelize.transaction();
    try {
      const user = await this.UserModel.findByPk(id, { transaction: tx });
      if (!user) {
        throw new UserNotFoundError(`User with id ${id} not found`);
      }

      // Password update requires hash
      if (updates.password) {
        updates.password = await bcrypt.hash(updates.password, SALT_ROUNDS);
      }

      await user.update(updates, { transaction: tx });
      await tx.commit();

      const safeUser = this._toSafeUser(user);

      await this._invalidateCache(id);
      await this._publishEvent('UserUpdated', safeUser);

      return safeUser;
    } catch (err) {
      await tx.rollback();
      this.logger.error(err, 'Failed to update user');
      throw err;
    }
  }

  /**
   * Soft-deletes a user record.
   *
   * @param {string | number} id
   * @returns {Promise<void>}
   */
  async delete(id) {
    const tx = await this.sequelize.transaction();
    try {
      const result = await this.UserModel.destroy({
        where: { id },
        transaction: tx,
      });

      if (!result) {
        throw new UserNotFoundError(`User with id ${id} not found`);
      }

      await tx.commit();

      await this._invalidateCache(id);
      await this._publishEvent('UserDeleted', { id });
    } catch (err) {
      await tx.rollback();
      this.logger.error(err, 'Failed to delete user');
      throw err;
    }
  }

  /**
   * Paginated listing with flexible filters and sorting.
   *
   * @param {object} [query]
   * @param {number} [query.page=1]
   * @param {number} [query.pageSize=20]
   * @param {object} [query.filters]      – Key/value pairs matching User fields.
   * @param {Array<[string,'ASC'|'DESC']>} [query.sort=[['createdAt','DESC']]]
   * @returns {Promise<{ items: object[], total: number, page: number }>}
   */
  async list({ page = 1, pageSize = 20, filters = {}, sort = [['createdAt', 'DESC']] } = {}) {
    const where = this._buildWhereClause(filters);

    const { rows, count } = await this.UserModel.findAndCountAll({
      where,
      order: sort,
      offset: (page - 1) * pageSize,
      limit: pageSize,
      attributes: { exclude: ['password'] },
    });

    return {
      items: rows.map((r) => r.get({ plain: true })),
      total: count,
      page,
    };
  }

  /* -------------------------------------------------------------------------- */
  /*                              Private helpers                               */
  /* -------------------------------------------------------------------------- */

  /**
   * Returns a plain JS object representation without the password hash.
   *
   * @param {import('sequelize').Model} model
   * @returns {object}
   */
  _toSafeUser(model) {
    const plain = model.get({ plain: true });
    delete plain.password;
    return plain;
  }

  /**
   * Converts simple filter map to Sequelize where clause.
   *
   * @param {object} filters
   * @returns {object}
   */
  _buildWhereClause(filters) {
    const where = {};
    if (!filters) return where;

    for (const [key, value] of Object.entries(filters)) {
      if (value === undefined || value === null) continue;
      // For string filters do case-insensitive like search
      if (typeof value === 'string') {
        where[key] = { [Op.iLike]: `%${value}%` };
      } else {
        where[key] = value;
      }
    }
    return where;
  }

  /**
   * Invalidates cached user entry by id.
   *
   * @param {string | number} id
   * @returns {Promise<void>}
   */
  async _invalidateCache(id) {
    if (!this.cache) return;
    try {
      await this.cache.del(`user:${id}`);
    } catch (err) {
      this.logger.warn(err, 'Failed to invalidate user cache');
    }
  }

  /**
   * Publishes a domain event when an eventBus is available.
   *
   * @param {string} type   – Domain event name.
   * @param {object} payload
   * @returns {Promise<void>}
   */
  async _publishEvent(type, payload) {
    if (!this.eventBus) return;
    try {
      await this.eventBus.publish({
        type,
        occurredAt: new Date().toISOString(),
        payload,
      });
    } catch (err) {
      this.logger.warn(err, `Failed to publish ${type} event`);
    }
  }
}

module.exports = {
  UserRepository,
  UserNotFoundError,
};
```