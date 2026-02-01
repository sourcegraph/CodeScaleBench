```javascript
/**
 * PulseLearn Campus Hub – Course Service
 *
 * A thin service-layer wrapper around all Course-related REST endpoints
 * exposed by the Campus Hub API gateway.  Provides CRUD, enrollment,
 * assignment upload, and real-time event subscription utilities.
 *
 * This file intentionally lives outside of React components so that
 * business logic is co-located, testable, and reusable.
 */

import axios from 'axios';
import EventEmitter from 'eventemitter3';
import { getAccessToken, logout } from './authService'; // ← centralised auth utils
import { API_BASE_URL, API_TIMEOUT } from '../config/env';
import { createTTLCache } from '../utils/cache';

/* -------------------------------------------------------------------------- */
/*                                axios client                                */
/* -------------------------------------------------------------------------- */

/**
 * Axios instance pre-configured with:
 *  – Base URL from env config
 *  – JWT bearer token injector
 *  – Global error interceptors
 */
const http = axios.create({
  baseURL: `${API_BASE_URL}/courses`,
  timeout: API_TIMEOUT,
});

// Request interceptor: inject auth token transparently
http.interceptors.request.use(
  async (config) => {
    const token = await getAccessToken();
    if (token) {
      // eslint-disable-next-line no-param-reassign
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (err) => Promise.reject(err),
);

// Response interceptor: unified error parsing & global side-effects
http.interceptors.response.use(
  (res) => res,
  (error) => {
    const status = error?.response?.status;

    // Automatic logout if token expired / invalid
    if (status === 401 || status === 419) {
      logout();
    }

    // Normalise message for callers
    const normalised = {
      message: error?.response?.data?.message || error.message,
      status,
      data: error?.response?.data,
    };
    return Promise.reject(normalised);
  },
);

/* -------------------------------------------------------------------------- */
/*                                in-memory TTL                               */
/* -------------------------------------------------------------------------- */

/**
 * Small helper cache so that list/detail endpoints don’t hammer
 * the backend while users navigate around the SPA.  Keeps entries
 * for 30 seconds by default.
 */
const COURSE_CACHE_TTL = 30 * 1000; // 30s
const courseCache = createTTLCache(COURSE_CACHE_TTL);

/* -------------------------------------------------------------------------- */
/*                          Course Service API Wrapper                        */
/* -------------------------------------------------------------------------- */

export const courseService = {
  // ──────────────────────────────────────────────────────────────────────────
  // Read endpoints
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Fetch paginated list of courses.
   *
   * @param {Object} params
   * @param {number} params.page     - 1-based page index
   * @param {number} params.size     - page size
   * @param {string} params.search   - search term
   * @param {AbortSignal} [signal]   - optional abort signal
   */
  async list({ page = 1, size = 20, search = '' } = {}, signal) {
    const cacheKey = `list:${page}:${size}:${search}`;
    const cached = courseCache.get(cacheKey);
    if (cached) return cached;

    const res = await http.get('/', {
      params: { page, size, search },
      signal,
    });

    courseCache.set(cacheKey, res.data);
    return res.data;
  },

  /**
   * Retrieve a single course by its id.
   *
   * @param {string} courseId
   * @param {AbortSignal} [signal]
   */
  async get(courseId, signal) {
    const cacheKey = `course:${courseId}`;
    const cached = courseCache.get(cacheKey);
    if (cached) return cached;

    const res = await http.get(`/${courseId}`, { signal });

    courseCache.set(cacheKey, res.data);
    return res.data;
  },

  // ──────────────────────────────────────────────────────────────────────────
  // Admin (write) endpoints
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Create a new course.  Requires admin role.
   *
   * @param {Object} payload
   * @returns {Promise<Object>}
   */
  async create(payload) {
    const res = await http.post('/', payload);
    return res.data;
  },

  /**
   * Update existing course.  Requires admin or instructor role.
   *
   * @param {string} courseId
   * @param {Object} patch
   * @returns {Promise<Object>}
   */
  async update(courseId, patch) {
    const res = await http.patch(`/${courseId}`, patch);
    courseCache.del(`course:${courseId}`); // bust local cache
    return res.data;
  },

  /**
   * Permanently delete a course.  Non-recoverable.
   *
   * @param {string} courseId
   */
  async remove(courseId) {
    await http.delete(`/${courseId}`);
    courseCache.del(`course:${courseId}`);
  },

  // ──────────────────────────────────────────────────────────────────────────
  // Enrolment endpoints
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Enroll currently authenticated user into a course.
   *
   * @param {string} courseId
   * @param {"student" | "instructor"} role
   */
  async enroll(courseId, role = 'student') {
    const res = await http.post(`/${courseId}/enroll`, { role });
    courseCache.del(`course:${courseId}`); // ensure subsequent get() reflects updates
    return res.data;
  },

  /**
   * Drop (unenroll) the authenticated user from a course.
   *
   * @param {string} courseId
   */
  async drop(courseId) {
    const res = await http.post(`/${courseId}/drop`);
    courseCache.del(`course:${courseId}`);
    return res.data;
  },

  // ──────────────────────────────────────────────────────────────────────────
  // Assignment submission
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Upload an assignment file for the given course.
   *
   * @param {string} courseId
   * @param {File} file
   * @param {Object} meta - arbitrary metadata e.g. assignmentId
   * @param {function(ProgressEvent):void} [onProgress]
   */
  async submitAssignment(courseId, file, meta = {}, onProgress) {
    const formData = new FormData();
    formData.append('file', file);
    Object.entries(meta).forEach(([k, v]) => formData.append(k, v));

    const res = await http.post(`/${courseId}/assignments`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    });

    return res.data;
  },

  // ──────────────────────────────────────────────────────────────────────────
  // Real-time event subscription
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Listen for server-sent events (SSE) related to a course.  Consumers
   * receive strongly-typed payloads via an EventEmitter.
   *
   * NOTE: This uses native EventSource so that we don’t couple to a
   * heavy WebSocket lib only for one-way notifications.
   *
   * @param {string} courseId
   * @returns {EventEmitter} emitter – fires events by their domain type
   *
   * Usage:
   *   const emitter = courseService.subscribe('course_123');
   *   emitter.on('BadgeAwarded', (evt) => console.log(evt));
   *   emitter.on('SessionExpired', () => history.push('/login'));
   *
   *   // Teardown
   *   emitter.close();
   */
  subscribe(courseId) {
    const source = new EventSource(
      `${API_BASE_URL}/realtime/courses/${courseId}`,
      { withCredentials: true },
    );

    const emitter = new EventEmitter();

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        // Domain event name expected at data.type
        emitter.emit(data.type, data.payload);
      } catch (err) {
        // Pass raw payload for non-JSON events
        emitter.emit('message', event.data);
      }
    };

    source.onerror = (err) => {
      emitter.emit('error', err);
    };

    // Helper to ensure consumer can terminate connection
    emitter.close = () => {
      source.close();
    };

    return emitter;
  },
};

/* -------------------------------------------------------------------------- */
/*                               Named Exports                                */
/* -------------------------------------------------------------------------- */

export default courseService;
```
