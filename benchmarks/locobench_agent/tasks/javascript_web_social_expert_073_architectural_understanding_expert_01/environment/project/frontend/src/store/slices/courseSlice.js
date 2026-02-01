```javascript
/**
 * Course Slice
 * -----------------------------------------------------------------------------
 * Centralised Redux Toolkit slice that encapsulates all course–related state,
 * side–effects and reducers for PulseLearn Campus Hub.
 *
 * Responsibilities
 *   • Normalised CRUD state for Course entities using `createEntityAdapter`
 *   • Async thunks for RESTful actions (fetch, create, update, delete, enroll)
 *   • Web-socket side-channel for live domain events (CourseCreated, CourseUpdated, etc.)
 *   • Resilient error handling & request cancellation (AbortController)
 *
 * NOTE: This slice purposefully avoids UI concerns. Keep React hooks/selectors
 *       in `hooks/` and components in `components/`.
 */

import { createSlice, createAsyncThunk, createEntityAdapter } from '@reduxjs/toolkit';
import axios from 'axios';

/* ============================================================================
 * Constants & Configuration
 * ========================================================================== */

const API_BASE_URL = process.env.REACT_APP_API_URL || 'https://api.pulselearn.io';
const COURSES_ENDPOINT = `${API_BASE_URL}/v1/courses`;

/**
 * Generates a cancellable Axios instance with Authorization header.
 * We keep it local to this file; alternatively move to `services/httpClient.js`
 */
const getHttpClient = (signal) =>
  axios.create({
    baseURL: COURSES_ENDPOINT,
    timeout: 10000,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
    },
    signal,
  });

/* ============================================================================
 * Entity Adapter
 * ========================================================================== */

const coursesAdapter = createEntityAdapter({
  selectId: (course) => course.id,
  sortComparer: (a, b) => a.title.localeCompare(b.title),
});

/* ============================================================================
 * Async Thunks
 * ========================================================================== */

/**
 * Fetch paginated / filtered course list
 * params: { page, perPage, search, tags }
 */
export const fetchCourses = createAsyncThunk(
  'courses/fetchCourses',
  async (params = {}, { signal, rejectWithValue }) => {
    try {
      const http = getHttpClient(signal);
      const { data } = await http.get('/', { params });
      return data; // Expected: { results: Course[], meta: {...} }
    } catch (error) {
      if (axios.isCancel(error)) return rejectWithValue({ cancelled: true });
      return rejectWithValue(error.response?.data || error.message);
    }
  },
  {
    condition: (_, { getState }) => {
      // Prevent duplicate requests for the same query before previous completes
      const { courses } = getState();
      return !courses.loading.list;
    },
  },
);

/**
 * Fetch single course by ID
 */
export const fetchCourseById = createAsyncThunk(
  'courses/fetchCourseById',
  async (courseId, { signal, rejectWithValue }) => {
    try {
      const http = getHttpClient(signal);
      const { data } = await http.get(`/${courseId}`);
      return data; // Course
    } catch (error) {
      if (axios.isCancel(error)) return rejectWithValue({ cancelled: true });
      return rejectWithValue(error.response?.data || error.message);
    }
  },
);

/**
 * Create new course (requires teacher/admin priv.)
 */
export const createCourse = createAsyncThunk(
  'courses/createCourse',
  async (payload, { signal, rejectWithValue }) => {
    try {
      const http = getHttpClient(signal);
      const { data } = await http.post('/', payload);
      return data; // Created Course
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  },
);

/**
 * Update course details
 */
export const updateCourse = createAsyncThunk(
  'courses/updateCourse',
  async ({ courseId, updates }, { signal, rejectWithValue }) => {
    try {
      const http = getHttpClient(signal);
      const { data } = await http.patch(`/${courseId}`, updates);
      return data; // Updated Course
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  },
);

/**
 * Delete (archive) course
 */
export const deleteCourse = createAsyncThunk(
  'courses/deleteCourse',
  async (courseId, { signal, rejectWithValue }) => {
    try {
      const http = getHttpClient(signal);
      await http.delete(`/${courseId}`);
      return courseId;
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  },
);

/**
 * Enroll current user into a course
 */
export const enrollInCourse = createAsyncThunk(
  'courses/enrollInCourse',
  async (courseId, { signal, rejectWithValue }) => {
    try {
      const http = getHttpClient(signal);
      const { data } = await http.post(`/${courseId}/enroll`);
      return { courseId, enrollment: data };
    } catch (error) {
      return rejectWithValue(error.response?.data || error.message);
    }
  },
);

/* ============================================================================
 * Slice Definition
 * ========================================================================== */

const initialState = coursesAdapter.getInitialState({
  loading: {
    list: false,
    entity: false,
    mutation: false,
  },
  error: null,
  pagination: {
    currentPage: 1,
    perPage: 20,
    totalPages: 0,
    totalItems: 0,
  },
  lastFetched: null,
});

const courseSlice = createSlice({
  name: 'courses',
  initialState,
  reducers: {
    /**
     * Handle real-time domain events coming over websocket or SSE.
     * See `eventHubMiddleware.js` for publisher side.
     */
    courseEventReceived: (state, action) => {
      const { type, payload } = action.payload;
      switch (type) {
        case 'CourseCreated':
          coursesAdapter.addOne(state, payload);
          break;
        case 'CourseUpdated':
          coursesAdapter.upsertOne(state, payload);
          break;
        case 'CourseDeleted':
          coursesAdapter.removeOne(state, payload.id);
          break;
        default:
          // Ignore unknown events
          break;
      }
    },
    /**
     * Local state reset (e.g. user logged out)
     */
    resetCoursesState: () => initialState,
  },
  extraReducers: (builder) => {
    /* ------------------- fetchCourses ------------------- */
    builder
      .addCase(fetchCourses.pending, (state) => {
        state.loading.list = true;
        state.error = null;
      })
      .addCase(fetchCourses.fulfilled, (state, action) => {
        state.loading.list = false;
        const { results, meta } = action.payload;
        coursesAdapter.setAll(state, results);
        state.pagination = {
          currentPage: meta.page,
          perPage: meta.perPage,
          totalPages: meta.totalPages,
          totalItems: meta.totalItems,
        };
        state.lastFetched = Date.now();
      })
      .addCase(fetchCourses.rejected, (state, action) => {
        state.loading.list = false;
        state.error = action.payload || action.error.message;
      });

    /* ------------------- fetchCourseById ------------------- */
    builder
      .addCase(fetchCourseById.pending, (state) => {
        state.loading.entity = true;
        state.error = null;
      })
      .addCase(fetchCourseById.fulfilled, (state, action) => {
        state.loading.entity = false;
        coursesAdapter.upsertOne(state, action.payload);
      })
      .addCase(fetchCourseById.rejected, (state, action) => {
        state.loading.entity = false;
        state.error = action.payload || action.error.message;
      });

    /* ------------------- createCourse ------------------- */
    builder
      .addCase(createCourse.pending, (state) => {
        state.loading.mutation = true;
        state.error = null;
      })
      .addCase(createCourse.fulfilled, (state, action) => {
        state.loading.mutation = false;
        coursesAdapter.addOne(state, action.payload);
      })
      .addCase(createCourse.rejected, (state, action) => {
        state.loading.mutation = false;
        state.error = action.payload || action.error.message;
      });

    /* ------------------- updateCourse ------------------- */
    builder
      .addCase(updateCourse.pending, (state) => {
        state.loading.mutation = true;
        state.error = null;
      })
      .addCase(updateCourse.fulfilled, (state, action) => {
        state.loading.mutation = false;
        coursesAdapter.upsertOne(state, action.payload);
      })
      .addCase(updateCourse.rejected, (state, action) => {
        state.loading.mutation = false;
        state.error = action.payload || action.error.message;
      });

    /* ------------------- deleteCourse ------------------- */
    builder
      .addCase(deleteCourse.pending, (state) => {
        state.loading.mutation = true;
        state.error = null;
      })
      .addCase(deleteCourse.fulfilled, (state, action) => {
        state.loading.mutation = false;
        coursesAdapter.removeOne(state, action.payload);
      })
      .addCase(deleteCourse.rejected, (state, action) => {
        state.loading.mutation = false;
        state.error = action.payload || action.error.message;
      });

    /* ------------------- enrollInCourse ------------------- */
    builder
      .addCase(enrollInCourse.pending, (state) => {
        state.loading.mutation = true;
        state.error = null;
      })
      .addCase(enrollInCourse.fulfilled, (state, action) => {
        state.loading.mutation = false;
        const { courseId, enrollment } = action.payload;
        const existing = state.entities[courseId];
        if (existing) {
          existing.enrollment = enrollment;
        }
      })
      .addCase(enrollInCourse.rejected, (state, action) => {
        state.loading.mutation = false;
        state.error = action.payload || action.error.message;
      });
  },
});

/* ============================================================================
 * Selectors
 * ========================================================================== */

export const {
  selectById: selectCourseById,
  selectIds: selectCourseIds,
  selectAll: selectAllCourses,
  selectTotal: selectTotalCourses,
} = coursesAdapter.getSelectors((state) => state.courses);

export const selectCourseLoading = (state) => state.courses.loading;
export const selectCourseError = (state) => state.courses.error;
export const selectCoursePagination = (state) => state.courses.pagination;

/* ============================================================================
 * Exports
 * ========================================================================== */

export const { courseEventReceived, resetCoursesState } = courseSlice.actions;
export default courseSlice.reducer;
```
