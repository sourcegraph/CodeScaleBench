```javascript
/**
 * PulseLearn Campus Hub – Course Routes
 * -------------------------------------
 * Defines HTTP endpoints for course management operations.  The routes
 * delegate business logic to the CourseService layer and are protected
 * by authentication / authorisation middleware.  Domain events are
 * published through the event bus so that downstream micro-services
 * (notifications, search indexing, achievements, etc.) react in real-time.
 *
 * File path: services/course-service/src/api/courseRoutes.js
 */

'use strict';

const express = require('express');
const { celebrate, Joi, Segments, errors: celebrateErrors } = require('celebrate');
const asyncHandler = require('express-async-handler');

const authMiddleware  = require('../middleware/authMiddleware');      // JWT / session auth
const roleMiddleware  = require('../middleware/roleMiddleware');      // role & permission checks
const CourseService   = require('../services/CourseService');         // domain service layer
const { publishEvent } = require('../infra/eventBus');                // Kafka / NATS producer
const logger          = require('../infra/logger');                   // Winston logger

const router = express.Router();

/* ------------------------------------------------------------------ */
/* Schema Validators (Joi + celebrate)                                */
/* ------------------------------------------------------------------ */

const courseBodySchema = {
  [Segments.BODY]: Joi.object({
    title:       Joi.string().trim().min(3).max(255).required(),
    description: Joi.string().trim().max(4096).allow(''),
    tags:        Joi.array().items(Joi.string().trim().max(64)).unique(),
    isPublic:    Joi.boolean().default(true)
  })
};

const paginationQuerySchema = {
  [Segments.QUERY]: Joi.object({
    page: Joi.number().integer().min(1).default(1),
    size: Joi.number().integer().min(1).max(100).default(20),
    search: Joi.string().trim().allow('')
  })
};

const enrolmentBodySchema = {
  [Segments.BODY]: Joi.object({
    userId: Joi.string().uuid().required()
  })
};

/* ------------------------------------------------------------------ */
/* REST Endpoints                                                     */
/* ------------------------------------------------------------------ */

/**
 * GET /api/v1/courses
 * List courses with optional pagination / full-text search
 */
router.get(
  '/',
  celebrate(paginationQuerySchema),
  authMiddleware.optional,
  asyncHandler(async (req, res) => {
    const { page, size, search } = req.query;
    const result = await CourseService.listCourses({ page, size, search, viewer: req.user });
    res.status(200).json(result);
  })
);

/**
 * GET /api/v1/courses/:courseId
 * Retrieve a single course by id
 */
router.get(
  '/:courseId',
  authMiddleware.optional,
  asyncHandler(async (req, res) => {
    const { courseId } = req.params;
    const course = await CourseService.getCourseById(courseId, req.user);
    res.status(200).json(course);
  })
);

/**
 * POST /api/v1/courses
 * Create a new course (instructors & admins only)
 */
router.post(
  '/',
  celebrate(courseBodySchema),
  authMiddleware.required,
  roleMiddleware(['INSTRUCTOR', 'ADMIN']),
  asyncHandler(async (req, res) => {
    const course = await CourseService.createCourse({
      ...req.body,
      ownerId: req.user.id
    });

    // Publish CourseCreated domain event
    publishEvent('CourseCreated', { courseId: course.id, ownerId: req.user.id })
      .catch(err => logger.error('Failed to publish CourseCreated event', { err }));

    res.status(201).json(course);
  })
);

/**
 * PUT /api/v1/courses/:courseId
 * Update a course (owner or admin)
 */
router.put(
  '/:courseId',
  celebrate(courseBodySchema),
  authMiddleware.required,
  roleMiddleware(['INSTRUCTOR', 'ADMIN']),
  asyncHandler(async (req, res) => {
    const { courseId } = req.params;
    const course = await CourseService.updateCourse(courseId, req.body, req.user);

    publishEvent('CourseUpdated', { courseId })
      .catch(err => logger.error('Failed to publish CourseUpdated event', { err }));

    res.status(200).json(course);
  })
);

/**
 * DELETE /api/v1/courses/:courseId
 * Soft-delete or archive a course (owner or admin)
 */
router.delete(
  '/:courseId',
  authMiddleware.required,
  roleMiddleware(['INSTRUCTOR', 'ADMIN']),
  asyncHandler(async (req, res) => {
    const { courseId } = req.params;
    await CourseService.archiveCourse(courseId, req.user);

    publishEvent('CourseArchived', { courseId })
      .catch(err => logger.error('Failed to publish CourseArchived event', { err }));

    res.status(204).send();
  })
);

/**
 * POST /api/v1/courses/:courseId/enrol
 * Enrol a user into a course (self-service or admin operation)
 */
router.post(
  '/:courseId/enrol',
  celebrate(enrolmentBodySchema),
  authMiddleware.required,
  asyncHandler(async (req, res) => {
    const { courseId } = req.params;
    const { userId }  = req.body;

    const enrolment = await CourseService.enrolUser({ courseId, userId, actor: req.user });

    publishEvent('UserEnrolled', { courseId, userId })
      .catch(err => logger.error('Failed to publish UserEnrolled event', { err }));

    res.status(201).json(enrolment);
  })
);

/**
 * GET /api/v1/courses/:courseId/students
 * List enrolled students (permission restricted)
 */
router.get(
  '/:courseId/students',
  authMiddleware.required,
  roleMiddleware(['INSTRUCTOR', 'ADMIN']),
  asyncHandler(async (req, res) => {
    const { courseId } = req.params;
    const students = await CourseService.listStudents(courseId, req.query);
    res.status(200).json(students);
  })
);

/* ------------------------------------------------------------------ */
/* Error Handling                                                     */
/* ------------------------------------------------------------------ */

// Celebrate-specific validation errors
router.use(celebrateErrors());

// Fallback / unexpected errors (will be picked up by global error handler)
router.use((err, _req, res, _next) => {
  logger.error('Unhandled error in courseRoutes', { err });
  res.status(500).json({ message: 'Internal server error' });
});

module.exports = router;
```