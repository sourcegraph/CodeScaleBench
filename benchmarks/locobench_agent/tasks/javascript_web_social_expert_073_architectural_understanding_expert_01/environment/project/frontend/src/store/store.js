```javascript
/**
 * PulseLearn Campus Hub – Global Redux Store
 * ------------------------------------------
 * This file wires together the Redux Toolkit store that powers the
 * PulseLearn single–page application.  It adds:
 *
 *  • Feature slices (auth, ui, feed, notifications, etc.)
 *  • Web-socket middleware that listens to the Campus-Bus (Kafka → WS gateway)
 *  • Persisted storage of the user/session for resilient login
 *  • Environment-aware debugging helpers
 *
 * NOTE: only the store is defined here.  Individual feature slices live
 * under `src/store/slices/`.
 */

import { configureStore, combineReducers, getDefaultMiddleware } from '@reduxjs/toolkit';
import { createLogger } from 'redux-logger';
import { persistStore, persistReducer, FLUSH, REHYDRATE, PAUSE, PERSIST, PURGE, REGISTER } from 'redux-persist';
import storage from 'redux-persist/lib/storage'; // defaults to localStorage for web
import debounce from 'lodash.debounce';

import authReducer from './slices/authSlice';
import uiReducer from './slices/uiSlice';
import feedReducer from './slices/feedSlice';
import notificationReducer from './slices/notificationSlice';

/* -------------------------------------------------------------------------- */
/*                             Web-Socket Middleware                          */
/* -------------------------------------------------------------------------- */

/**
 * Returns a Redux middleware that passes dispatched actions to the server
 * (write channel) and emits server events back into Redux (read channel).
 *
 * The backend exposes a KAFKA → WS proxy at /ws that pushes serialized
 * domain events, e.g. `AssignmentSubmitted`, `BadgeAwarded`.
 *
 * The middleware will:
 *   – reconnect with exponential back-off
 *   – authenticate using the JWT from the auth slice
 *   – dispatch "ws/*" meta actions for lifecycle & error monitoring
 */
const createWebSocketMiddleware = (socketUrl) => {
  let socket = null;
  let retryCount = 0;
  let storeRef = null;
  let timeoutId;

  const openSocket = (token) => {
    const urlWithToken = `${socketUrl}?token=${encodeURIComponent(token)}`;
    socket = new WebSocket(urlWithToken);

    socket.onopen = () => {
      retryCount = 0;
      storeRef.dispatch({ type: 'ws/connected' });
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        storeRef.dispatch({ type: `bus/${payload.type}`, payload });
      } catch (err) {
        console.error('WS → invalid JSON', err);
        storeRef.dispatch({ type: 'ws/error', error: err });
      }
    };

    socket.onerror = (err) => {
      console.warn('WS → error', err);
      storeRef.dispatch({ type: 'ws/error', error: err });
    };

    socket.onclose = () => {
      storeRef.dispatch({ type: 'ws/disconnected' });
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (timeoutId || retryCount > 5) return; // Max 5 attempts
    const backoff = Math.min(1000 * 2 ** retryCount, 15000); // cap at 15s
    timeoutId = setTimeout(() => {
      timeoutId = null;
      retryCount += 1;
      const { token } = storeRef.getState().auth;
      if (token) openSocket(token);
    }, backoff);
  };

  return (store) => {
    storeRef = store;

    return (next) => (action) => {
      const result = next(action);

      // If auth token changes (login/logout), (re)connect
      if (action.type.startsWith('auth/')) {
        const { token } = store.getState().auth;

        if (!token && socket) {
          socket.close();
          socket = null;
        }

        if (token && (!socket || socket.readyState !== WebSocket.OPEN)) {
          if (socket) socket.close();
          openSocket(token);
        }
      }

      // Outgoing actions flagged with meta: { remote: true }
      if (action.meta?.remote === true && socket?.readyState === WebSocket.OPEN) {
        try {
          socket.send(JSON.stringify(action));
        } catch (err) {
          console.error('WS ← send failed', err);
          store.dispatch({ type: 'ws/error', error: err });
        }
      }

      return result;
    };
  };
};

/* -------------------------------------------------------------------------- */
/*                           Persisted Reducer Config                         */
/* -------------------------------------------------------------------------- */

const rootPersistConfig = {
  key: 'root',
  version: 1,
  storage,
  whitelist: ['auth'], // only persist auth slice
};

const rootReducer = combineReducers({
  auth: authReducer,
  ui: uiReducer,
  feed: feedReducer,
  notifications: notificationReducer,
});

const persistedReducer = persistReducer(rootPersistConfig, rootReducer);

/* -------------------------------------------------------------------------- */
/*                          Middleware Composition                            */
/* -------------------------------------------------------------------------- */

const websocketMiddleware = createWebSocketMiddleware(import.meta.env.VITE_WS_URL || '/ws');

const middleware = [
  ...getDefaultMiddleware({
    serializableCheck: {
      // Allow redux-persist specific actions to violate serializability checks
      ignoredActions: [FLUSH, REHYDRATE, PAUSE, PERSIST, PURGE, REGISTER],
    },
  }),
  websocketMiddleware,
];

// Add logging only in non-production builds
if (import.meta.env.MODE !== 'production') {
  middleware.push(
    createLogger({
      collapsed: true,
      duration: true,
      diff: true,
    }),
  );
}

/* -------------------------------------------------------------------------- */
/*                                 The Store                                  */
/* -------------------------------------------------------------------------- */

export const store = configureStore({
  reducer: persistedReducer,
  middleware,
  devTools: import.meta.env.MODE !== 'production',
});

// Create the persistor for <PersistGate>
export const persistor = persistStore(store);

/* -------------------------------------------------------------------------- */
/*                         Hot Module Replacement (HMR)                       */
/* -------------------------------------------------------------------------- */

if (import.meta.hot) {
  import.meta.hot.accept(['./slices/authSlice', './slices/uiSlice', './slices/feedSlice', './slices/notificationSlice'], () => {
    const nextRootReducer = combineReducers({
      auth: require('./slices/authSlice').default,
      ui: require('./slices/uiSlice').default,
      feed: require('./slices/feedSlice').default,
      notifications: require('./slices/notificationSlice').default,
    });

    store.replaceReducer(persistReducer(rootPersistConfig, nextRootReducer));
  });
}

/* -------------------------------------------------------------------------- */
/*                            Typed Hooks (optional)                          */
/* -------------------------------------------------------------------------- */
/**
 * These utility hooks are safe in plain JS, but if the project uses TypeScript
 * they become strongly typed by switching to `import { TypedUseSelectorHook }`
 */
import { useDispatch, useSelector } from 'react-redux';

export const useAppDispatch = () => useDispatch();
export const useAppSelector = (selector) => useSelector(selector);

/* -------------------------------------------------------------------------- */
/*                  Persisted Cleanup – debounce state flush                  */
/* -------------------------------------------------------------------------- */
/**
 * Throttle expensive localStorage writes on massive action bursts
 */
persistor.subscribe(
  debounce(() => {
    // Force flush to disk
    persistor.flush();
  }, 500),
);
```