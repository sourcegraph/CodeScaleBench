```javascript
/**
 * PulseLearn Campus Hub – Notification Slice
 *
 * This slice holds the Redux state for user notifications and provides
 * async thunks to communicate with the backend notification service,
 * as well as helpers for consuming real-time socket events.
 *
 * Conventions:
 *  – REST endpoints are assumed to be rooted at /api/v1/notifications
 *  – Each notification document has the following shape:
 *      {
 *          id:              string,
 *          title:           string,
 *          message:         string,
 *          type:            'INFO' | 'WARNING' | 'SUCCESS' | 'ERROR',
 *          createdAt:       string (ISO-8601),
 *          readAt:          string | null,
 *          metadata:        object
 *      }
 */

import { createSlice, createAsyncThunk, createEntityAdapter } from '@reduxjs/toolkit';
import axios from 'axios';
import { io } from 'socket.io-client';

// -----------------------------------------------------------------------------
// Constants
// -----------------------------------------------------------------------------
const API_BASE_URL = '/api/v1/notifications';
const SOCKET_NAMESPACE = '/notifications';
const RECONNECT_INTERVAL_MS = 10_000;

// -----------------------------------------------------------------------------
// Entity Adapter – provides CRUD selectors & state normalization
// -----------------------------------------------------------------------------
const notificationAdapter = createEntityAdapter({
  sortComparer: (a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt),
});

// -----------------------------------------------------------------------------
// Initial State
// -----------------------------------------------------------------------------
const initialState = notificationAdapter.getInitialState({
  status: 'idle',          // 'idle' | 'loading' | 'succeeded' | 'failed'
  error: null,             // error message, if any
  unreadCount: 0,
});

// -----------------------------------------------------------------------------
// Async Thunks
// -----------------------------------------------------------------------------

/**
 * Fetches the current user’s paginated notifications.
 * @param {Object} params
 * @param {number} params.page - 1-based page index.
 * @param {number} params.pageSize - items per page.
 */
export const fetchNotifications = createAsyncThunk(
  'notifications/fetchNotifications',
  async ({ page = 1, pageSize = 30 } = {}, { rejectWithValue }) => {
    try {
      const res = await axios.get(API_BASE_URL, {
        params: { page, pageSize },
      });
      // Response is expected to be { items, unreadCount }
      return res.data;
    } catch (err) {
      /* eslint-disable-next-line no-console */
      console.error('Failed to fetch notifications:', err);
      return rejectWithValue(err.response?.data?.message ?? 'Unknown error');
    }
  },
);

/**
 * Marks a single notification as read.
 */
export const markNotificationAsRead = createAsyncThunk(
  'notifications/markAsRead',
  async (notificationId, { rejectWithValue }) => {
    try {
      await axios.patch(`${API_BASE_URL}/${notificationId}/read`);
      return notificationId;
    } catch (err) {
      return rejectWithValue(err.response?.data?.message ?? 'Unknown error');
    }
  },
);

/**
 * Marks all notifications as read.
 */
export const markAllAsRead = createAsyncThunk(
  'notifications/markAllAsRead',
  async (_payload, { rejectWithValue }) => {
    try {
      await axios.patch(`${API_BASE_URL}/read-all`);
      return true;
    } catch (err) {
      return rejectWithValue(err.response?.data?.message ?? 'Unknown error');
    }
  },
);

/**
 * Deletes a single notification.
 */
export const deleteNotification = createAsyncThunk(
  'notifications/deleteNotification',
  async (notificationId, { rejectWithValue }) => {
    try {
      await axios.delete(`${API_BASE_URL}/${notificationId}`);
      return notificationId;
    } catch (err) {
      return rejectWithValue(err.response?.data?.message ?? 'Unknown error');
    }
  },
);

// -----------------------------------------------------------------------------
// Slice
// -----------------------------------------------------------------------------
const notificationSlice = createSlice({
  name: 'notifications',
  initialState,
  reducers: {
    /**
     * Optimistically adds a real-time notification received
     * from the websocket channel.
     * @param {import('@reduxjs/toolkit').EntityState} state
     * @param {Object} action
     */
    addIncomingNotification: (state, action) => {
      notificationAdapter.addOne(state, action.payload);
      state.unreadCount += 1;
    },
    clearError: (state) => {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder

      // -----------------------------------------------------------------------
      // fetchNotifications
      // -----------------------------------------------------------------------
      .addCase(fetchNotifications.pending, (state) => {
        state.status = 'loading';
        state.error = null;
      })
      .addCase(fetchNotifications.fulfilled, (state, action) => {
        state.status = 'succeeded';
        const { items, unreadCount } = action.payload;
        notificationAdapter.setAll(state, items);
        state.unreadCount = unreadCount;
      })
      .addCase(fetchNotifications.rejected, (state, action) => {
        state.status = 'failed';
        state.error = action.payload;
      })

      // -----------------------------------------------------------------------
      // markNotificationAsRead
      // -----------------------------------------------------------------------
      .addCase(markNotificationAsRead.fulfilled, (state, action) => {
        const id = action.payload;
        const existing = state.entities[id];
        if (existing && !existing.readAt) {
          existing.readAt = new Date().toISOString();
          state.unreadCount = Math.max(0, state.unreadCount - 1);
        }
      })

      // -----------------------------------------------------------------------
      // markAllAsRead
      // -----------------------------------------------------------------------
      .addCase(markAllAsRead.fulfilled, (state) => {
        Object.values(state.entities).forEach((n) => {
          if (n && !n.readAt) {
            n.readAt = new Date().toISOString();
          }
        });
        state.unreadCount = 0;
      })

      // -----------------------------------------------------------------------
      // deleteNotification
      // -----------------------------------------------------------------------
      .addCase(deleteNotification.fulfilled, (state, action) => {
        const id = action.payload;
        const wasUnread = state.entities[id]?.readAt ? 0 : 1;
        notificationAdapter.removeOne(state, id);
        state.unreadCount = Math.max(0, state.unreadCount - wasUnread);
      })

      // Generic rejected handler
      .addMatcher(
        (action) => action.type.startsWith('notifications/') && action.type.endsWith('/rejected'),
        (state, action) => {
          state.status = 'failed';
          state.error = action.payload ?? 'Unexpected error';
        },
      );
  },
});

export const { addIncomingNotification, clearError } = notificationSlice.actions;

// -----------------------------------------------------------------------------
// Selectors
// -----------------------------------------------------------------------------
export const {
  selectAll: selectAllNotifications,
  selectById: selectNotificationById,
  selectIds: selectNotificationIds,
} = notificationAdapter.getSelectors((state) => state.notifications);

export const selectUnreadNotifications = (state) =>
  selectAllNotifications(state).filter((n) => !n.readAt);

export const selectUnreadCount = (state) => state.notifications.unreadCount;

export const selectNotificationStatus = (state) => state.notifications.status;

// -----------------------------------------------------------------------------
// Real-Time Socket Helpers
// -----------------------------------------------------------------------------

let socketInstance = null;

/**
 * Initializes a singleton Socket.IO connection, listening for server-pushed
 * notifications. It supports automatic reconnection with exponential backoff.
 * Calling this function multiple times returns the same socket.
 *
 * @param {import('redux').Store} store – Redux store instance.
 * @param {string} [jwtToken] – Auth token to send as query param.
 */
export const initNotificationSocket = (store, jwtToken) => {
  if (socketInstance) return socketInstance;

  socketInstance = io(SOCKET_NAMESPACE, {
    path: '/socket.io',
    transports: ['websocket'],
    auth: {
      token: jwtToken,
    },
    reconnectionDelay: RECONNECT_INTERVAL_MS,
    autoConnect: true,
  });

  socketInstance.on('connect_error', (err) => {
    /* eslint-disable-next-line no-console */
    console.error('[NotificationSocket] connection error:', err);
  });

  socketInstance.on('notification', (payload) => {
    // defensive coding: ensure required fields exist
    if (payload?.id && payload?.createdAt) {
      store.dispatch(addIncomingNotification(payload));
    }
  });

  return socketInstance;
};

// -----------------------------------------------------------------------------
// Reducer Export
// -----------------------------------------------------------------------------
export default notificationSlice.reducer;
```
