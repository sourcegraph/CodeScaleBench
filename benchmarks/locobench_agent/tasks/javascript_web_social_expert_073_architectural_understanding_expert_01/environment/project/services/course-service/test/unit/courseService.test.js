```javascript
/**
 * @file courseService.test.js
 * Unit tests for CourseService in PulseLearn Campus Hub.
 *
 * These tests focus exclusively on the behaviour of the CourseService class in isolation.
 * ALL external collaborators (repository, message-bus, logger, etc.) are Jest mocks so that
 * the tests remain deterministic and free of side-effects such as I/O or network traffic.
 */

const { v4: uuid } = require('uuid');
const CourseService = require('../../src/courseService'); // Path: services/course-service/src/courseService.js

// -----------------------------------------------------------------------------
// Mocked collaborators
// -----------------------------------------------------------------------------
const mockCourseRepository = {
  save:             jest.fn(),
  findBySlug:        jest.fn(),
  findById:          jest.fn(),
  enrollStudent:     jest.fn(),
  listByInstructor:  jest.fn(),
  archive:           jest.fn(),
};

const mockEventBus = {
  publish: jest.fn(),
};

const mockLogger = {
  info:  jest.fn(),
  warn:  jest.fn(),
  error: jest.fn(),
};

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------
const buildCoursePayload = (overrides = {}) => ({
  title:       'Advanced Reactive Systems',
  description: 'Learn to build event-driven microservices with Kafka and NATS.',
  instructorId: uuid(),
  visibility:  'PUBLIC',
  ...overrides,
});

// -----------------------------------------------------------------------------
// Test Suite
// -----------------------------------------------------------------------------
describe('CourseService', () => {
  let service;

  beforeEach(() => {
    // Reset mocks *and* create a fresh instance for each test for full isolation.
    jest.clearAllMocks();
    service = new CourseService({
      courseRepository: mockCourseRepository,
      eventBus:         mockEventBus,
      logger:           mockLogger,
    });
  });

  // ---------------------------------------------------------------------------
  // #createCourse
  // ---------------------------------------------------------------------------
  describe('#createCourse', () => {
    it('persists the course and publishes a CourseCreated event', async () => {
      // Arrange
      const payload = buildCoursePayload();
      mockCourseRepository.findBySlug.mockResolvedValue(null); // slug not taken
      mockCourseRepository.save.mockImplementation(async course => ({
        ...course,
        id: uuid(),
        createdAt: new Date(),
      }));

      // Act
      const createdCourse = await service.createCourse(payload);

      // Assert
      expect(mockCourseRepository.findBySlug).toHaveBeenCalledWith(
        service._generateSlug(payload.title),
      );
      expect(mockCourseRepository.save).toHaveBeenCalledTimes(1);
      expect(mockEventBus.publish).toHaveBeenCalledWith('CourseCreated', {
        courseId: createdCourse.id,
        instructorId: payload.instructorId,
      });
      expect(createdCourse).toEqual(
        expect.objectContaining({
          title: payload.title,
          description: payload.description,
          instructorId: payload.instructorId,
        }),
      );
    });

    it('throws a validation error when another course already uses the same slug', async () => {
      // Arrange
      const payload = buildCoursePayload({ title: 'Intro to Testing' });
      mockCourseRepository.findBySlug.mockResolvedValue({ id: uuid() }); // slug taken

      // Act + Assert
      await expect(service.createCourse(payload)).rejects.toThrow(
        /already exists/i,
      );
      expect(mockCourseRepository.save).not.toHaveBeenCalled();
      expect(mockEventBus.publish).not.toHaveBeenCalled();
    });

    it('logs and re-throws if repository.save fails', async () => {
      // Arrange
      const payload = buildCoursePayload();
      const repoError = new Error('db connection lost');
      mockCourseRepository.findBySlug.mockResolvedValue(null);
      mockCourseRepository.save.mockRejectedValue(repoError);

      // Act + Assert
      await expect(service.createCourse(payload)).rejects.toThrow(repoError);
      expect(mockLogger.error).toHaveBeenCalledWith(
        'Failed to create course',
        repoError,
      );
    });
  });

  // ---------------------------------------------------------------------------
  // #enrollStudent
  // ---------------------------------------------------------------------------
  describe('#enrollStudent', () => {
    const courseId   = uuid();
    const studentId  = uuid();

    it('enrolls a student and publishes a CourseEnrollmentCreated event', async () => {
      // Arrange
      mockCourseRepository.findById.mockResolvedValue({ id: courseId });
      mockCourseRepository.enrollStudent.mockResolvedValue({
        courseId,
        studentId,
        enrolledAt: new Date(),
      });

      // Act
      const result = await service.enrollStudent({ courseId, studentId });

      // Assert
      expect(mockCourseRepository.findById).toHaveBeenCalledWith(courseId);
      expect(mockCourseRepository.enrollStudent).toHaveBeenCalledWith({
        courseId,
        studentId,
      });
      expect(mockEventBus.publish).toHaveBeenCalledWith(
        'CourseEnrollmentCreated',
        { courseId, studentId },
      );
      expect(result).toEqual(
        expect.objectContaining({ courseId, studentId }),
      );
    });

    it('throws NotFoundError when the course does not exist', async () => {
      // Arrange
      mockCourseRepository.findById.mockResolvedValue(null);

      // Act + Assert
      await expect(
        service.enrollStudent({ courseId, studentId }),
      ).rejects.toThrow(/not found/i);

      expect(mockCourseRepository.enrollStudent).not.toHaveBeenCalled();
      expect(mockEventBus.publish).not.toHaveBeenCalled();
    });
  });

  // ---------------------------------------------------------------------------
  // #archiveCourse
  // ---------------------------------------------------------------------------
  describe('#archiveCourse', () => {
    const courseId  = uuid();
    const userId    = uuid(); // instructor performing the action

    it('archives an existing course and emits CourseArchived', async () => {
      // Arrange
      mockCourseRepository.findById.mockResolvedValue({
        id: courseId,
        instructorId: userId,
        status: 'ACTIVE',
      });
      mockCourseRepository.archive.mockResolvedValue({
        id: courseId,
        status: 'ARCHIVED',
        archivedAt: new Date(),
      });

      // Act
      const archived = await service.archiveCourse({ courseId, userId });

      // Assert
      expect(mockCourseRepository.archive).toHaveBeenCalledWith(courseId);
      expect(mockEventBus.publish).toHaveBeenCalledWith('CourseArchived', {
        courseId,
      });
      expect(archived.status).toBe('ARCHIVED');
    });

    it('prevents archiving if caller is not the course instructor', async () => {
      // Arrange
      mockCourseRepository.findById.mockResolvedValue({
        id: courseId,
        instructorId: uuid(), // someone else
        status: 'ACTIVE',
      });

      // Act + Assert
      await expect(
        service.archiveCourse({ courseId, userId }),
      ).rejects.toThrow(/permission/i);

      expect(mockCourseRepository.archive).not.toHaveBeenCalled();
      expect(mockEventBus.publish).not.toHaveBeenCalled();
    });
  });

  // ---------------------------------------------------------------------------
  // #listCoursesByInstructor
  // ---------------------------------------------------------------------------
  describe('#listCoursesByInstructor', () => {
    const instructorId = uuid();

    it('delegates to repository and returns mapped DTOs', async () => {
      // Arrange
      mockCourseRepository.listByInstructor.mockResolvedValue([
        { id: uuid(), title: 'Node.js Foundations' },
        { id: uuid(), title: 'GraphQL for Pros' },
      ]);

      // Act
      const list = await service.listCoursesByInstructor(instructorId);

      // Assert
      expect(
        mockCourseRepository.listByInstructor,
      ).toHaveBeenCalledWith(instructorId);
      expect(list).toHaveLength(2);
      list.forEach(item =>
        expect(item).toHaveProperty('title'),
      );
    });
  });
});
```