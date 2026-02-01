```javascript
/**
 * PulseLearn Campus Hub – Course Controller
 *
 * This controller exposes a RESTful interface for manipulating courses in the
 * Course-Service micro-service.  All handlers are thin; business logic is
 * delegated to the service-layer while the controller is responsible for:
 *   • Express route definitions
 *   • Request/response mapping
 *   • Input validation & sanitization
 *   • Authentication / Authorization gate-keeping
 *   • Domain event dispatching
 *
 * NOTE:  The surrounding project already provides common infrastructure such as:
 *        – asyncHandler      • promise-aware middleware wrapper
 *        – logger            • Winston-based structured logger
 *        – error classes     • BadRequestError, NotFoundError, ForbiddenError
 *        – authorize()       • RBAC middleware (Roles = { ADMIN, INSTRUCTOR, STUDENT })
 *        – publishDomainEvent() • decoupled event publisher (Kafka/NATS)
 */

import express from 'express';
import {
  body,
  param,
  query,
  validationResult,
} from 'express-validator';

import CourseService from '../services/courseService.js';
import asyncHandler from '../middleware/asyncHandler.js';
import { authorize, Roles } from '../middleware/authorize.js';
import { publishDomainEvent } from '../events/eventPublisher.js';
import logger from '../utils/logger.js';
import { BadRequestError, NotFoundError } from '../errors/index.js';

const router = express.Router();

/* -------------------------------------------------------------------------- */
/*                                Validations                                 */
/* -------------------------------------------------------------------------- */

/**
 * Convenience helper to bail out early when validation fails
 */
const validateRequest = (req) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    throw new BadRequestError('Validation Error', errors.array());
  }
};

/* ----------------------------- Route Handlers ----------------------------- */

/**
 * GET /api/courses
 * Query Params:
 *   - page (optional) default 1
 *   - limit (optional) default 25
 *   - search (optional) fuzzy title search
 */
router.get(
  '/',
  [
    query('page').optional().isInt({ gt: 0 }).toInt(),
    query('limit').optional().isInt({ gt: 0, lt: 101 }).toInt(),
    query('search').optional().isString().trim(),
  ],
  asyncHandler(async (req, res) => {
    validateRequest(req);

    const { page = 1, limit = 25, search } = req.query;

    const courses = await CourseService.listCourses({ page, limit, search });
    return res.status(200).json(courses);
  })
);

/**
 * GET /api/courses/:courseId
 */
router.get(
  '/:courseId',
  [param('courseId').isUUID()],
  asyncHandler(async (req, res) => {
    validateRequest(req);

    const { courseId } = req.params;
    const course = await CourseService.getCourseById(courseId);

    if (!course) throw new NotFoundError(`Course ${courseId} not found`);

    return res.status(200).json(course);
  })
);

/**
 * POST /api/courses
 * Restricted to ADMIN & INSTRUCTOR roles
 */
router.post(
  '/',
  authorize([Roles.ADMIN, Roles.INSTRUCTOR]),
  [
    body('title').isString().isLength({ min: 3, max: 128 }).trim(),
    body('description').isString().isLength({ min: 10 }).trim(),
    body('visibility').optional().isIn(['public', 'private', 'unlisted']),
    body('price').optional().isFloat({ min: 0 }).toFloat(),
    body('metadata')
      .optional()
      .isObject()
      .custom((md) => Object.keys(md).length <= 50),
  ],
  asyncHandler(async (req, res) => {
    validateRequest(req);

    const instructorId = req.user.id;
    const courseData = { ...req.body, instructorId };

    const createdCourse = await CourseService.createCourse(courseData);

    // Emit domain event for other micro-services
    await publishDomainEvent('CourseCreated', {
      courseId: createdCourse.id,
      instructorId,
    });

    logger.info('Course created', {
      courseId: createdCourse.id,
      instructorId,
    });

    return res.status(201).json(createdCourse);
  })
);

/**
 * PATCH /api/courses/:courseId
 * Only ADMIN or course owner (INSTRUCTOR) may update
 */
router.patch(
  '/:courseId',
  authorize([Roles.ADMIN, Roles.INSTRUCTOR]),
  [
    param('courseId').isUUID(),
    body('title').optional().isString().isLength({ min: 3, max: 128 }).trim(),
    body('description').optional().isString().isLength({ min: 10 }).trim(),
    body('visibility').optional().isIn(['public', 'private', 'unlisted']),
    body('price').optional().isFloat({ min: 0 }).toFloat(),
    body('metadata')
      .optional()
      .isObject()
      .custom((md) => Object.keys(md).length <= 50),
  ],
  asyncHandler(async (req, res) => {
    validateRequest(req);

    const { courseId } = req.params;
    const patch = req.body;
    const user = req.user;

    // Defensive check: only admins or course owner can edit
    if (
      user.role !== Roles.ADMIN &&
      !(await CourseService.isInstructorOfCourse(user.id, courseId))
    ) {
      throw new ForbiddenError('Not authorized to modify this course');
    }

    const updatedCourse = await CourseService.updateCourse(courseId, patch);
    if (!updatedCourse) throw new NotFoundError(`Course ${courseId} not found`);

    await publishDomainEvent('CourseUpdated', {
      courseId,
      editorId: user.id,
    });

    return res.status(200).json(updatedCourse);
  })
);

/**
 * DELETE /api/courses/:courseId
 * Only ADMIN can delete courses (hard delete)
 */
router.delete(
  '/:courseId',
  authorize([Roles.ADMIN]),
  [param('courseId').isUUID()],
  asyncHandler(async (req, res) => {
    validateRequest(req);

    const { courseId } = req.params;
    const deleted = await CourseService.deleteCourse(courseId);
    if (!deleted) throw new NotFoundError(`Course ${courseId} not found`);

    await publishDomainEvent('CourseDeleted', {
      courseId,
      deleterId: req.user.id,
    });

    logger.warn('Course deleted', { courseId, by: req.user.id });
    return res.status(204).send(); // No content
  })
);

/**
 * POST /api/courses/:courseId/enroll
 * Self-service enrollment – STUDENT role
 */
router.post(
  '/:courseId/enroll',
  authorize([Roles.STUDENT]),
  [param('courseId').isUUID()],
  asyncHandler(async (req, res) => {
    validateRequest(req);

    const { courseId } = req.params;
    const studentId = req.user.id;

    const enrollment = await CourseService.enrollStudent(courseId, studentId);
    if (!enrollment)
      throw new BadRequestError('Unable to enroll in specified course');

    await publishDomainEvent('StudentEnrolledInCourse', {
      courseId,
      studentId,
    });

    return res.status(200).json(enrollment);
  })
);

/* -------------------------------------------------------------------------- */
/*                               Export Router                                */
/* -------------------------------------------------------------------------- */

export default router;
```