```javascript
/**
 * PulseLearn Campus Hub
 * -----------------------------------------------------------------------------
 * Centralised API layer for all HTTP & real-time traffic originating
 * from the React front-end.  The module is responsible for:
 *
 *   • HTTP client instantiation & configuration (Axios)
 *   • Automatic JWT injection & refresh-token rotation
 *   • Global request correlation (X-Request-ID)
 *   • Graceful error handling & logout on unrecoverable failures
 *   • Convenience wrappers for the most common verbs
 *   • Server-Sent Events helper for the event-driven UI
 *
 *  Usage example:
 *
 *    import api from '@/services/api';
 *
 *    // REST
 *    const courses = await api.get('/courses');
 *
 *    // Auth
 *    await api.auth.login({ email, password });
 *
 *    // Real-time
 *    const sse = api.events.connect(['AssignmentSubmitted'], evt => {
 *      const data = JSON.parse(evt.data);
 *      // …
 *    });
 *
 * All functions return native Promises and surface errors, allowing
 * consumers to decide how to handle failures within UI components.
 * -----------------------------------------------------------------------------
 */

import axios from 'axios';
import { v4 as uuidv4 } from 'uuid';

/**
 * Constants & helpers
 * -----------------------------------------------------------------------------
 */
const STORAGE_KEY = {
  ACCESS: 'pulselearn.access_token',
  REFRESH: 'pulselearn.refresh_token',
};

const API_BASE_URL =
  process.env.REACT_APP_API_URL ||
  window.__ENV__?.API_URL || // optional runtime-injected env for docker/k8s
  'https://api.pulselearn.io';

const isBrowser = typeof window !== 'undefined';

/**
 * Token persistence helpers
 * -----------------------------------------------------------------------------
 */
let tokens = {
  access: isBrowser ? localStorage.getItem(STORAGE_KEY.ACCESS) : null,
  refresh: isBrowser ? localStorage.getItem(STORAGE_KEY.REFRESH) : null,
};

function persistTokens(nextTokens = {}) {
  tokens = { ...tokens, ...nextTokens };

  if (!isBrowser) return;

  if (nextTokens.access) {
    localStorage.setItem(STORAGE_KEY.ACCESS, nextTokens.access);
  }
  if (nextTokens.refresh) {
    localStorage.setItem(STORAGE_KEY.REFRESH, nextTokens.refresh);
  }
}

function clearTokens() {
  tokens = { access: null, refresh: null };

  if (!isBrowser) return;

  localStorage.removeItem(STORAGE_KEY.ACCESS);
  localStorage.removeItem(STORAGE_KEY.REFRESH);
}

/**
 * Axios client
 * -----------------------------------------------------------------------------
 */
const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15_000,
  withCredentials: true, // send cookies (if backend also uses them)
});

/**
 * Request interceptor
 *   – Adds Authorization / Request-ID headers to every outgoing call.
 */
http.interceptors.request.use(
  config => {
    /* eslint-disable no-param-reassign */
    if (tokens.access) {
      config.headers.Authorization = `Bearer ${tokens.access}`;
    }
    config.headers['X-Request-ID'] = uuidv4();
    /* eslint-enable no-param-reassign */
    return config;
  },
  error => Promise.reject(error),
);

/**
 * Response interceptor
 *   – Handles 401s by attempting a refresh flow once per request.
 *   – Queues parallel requests while a refresh is in flight to avoid
 *     a stampede of refresh calls.
 */
let isRefreshing = false;
let subscribers = [];

function onRrefreshed(newToken) {
  subscribers.forEach(cb => cb(newToken));
  subscribers = [];
}

function addSubscriber(callback) {
  subscribers.push(callback);
}

http.interceptors.response.use(
  response => response,
  async error => {
    const { config, response } = error;
    const isAuthError = response?.status === 401;
    const hasRefreshToken = !!tokens.refresh;
    const originalRequest = config;

    if (!isAuthError || !hasRefreshToken) {
      // Either not a 401 or we have nothing to refresh with.
      return Promise.reject(error);
    }

    if (originalRequest._retry) {
      // We already retried once & it failed again → logout.
      clearTokens();
      return Promise.reject(error);
    }
    originalRequest._retry = true;

    // If another refresh request is already happening, queue.
    if (isRefreshing) {
      return new Promise(resolve => {
        addSubscriber(token => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          resolve(http(originalRequest));
        });
      });
    }

    // Kick off refresh flow
    isRefreshing = true;
    try {
      const newAccess = await refreshToken();
      onRrefreshed(newAccess);

      // Re-issue the original request with new token
      originalRequest.headers.Authorization = `Bearer ${newAccess}`;
      return http(originalRequest);
    } catch (refreshErr) {
      // Refresh failed → hard logout
      clearTokens();
      return Promise.reject(refreshErr);
    } finally {
      isRefreshing = false;
    }
  },
);

/**
 * Auth service
 * -----------------------------------------------------------------------------
 */
async function login({ email, password }) {
  try {
    const { data } = await http.post('/auth/login', { email, password });
    const { accessToken: access, refreshToken: refresh } = data;

    if (!access || !refresh) {
      throw new Error('Invalid auth payload from server');
    }

    persistTokens({ access, refresh });
    return data;
  } catch (err) {
    clearTokens();
    throw err;
  }
}

async function logout() {
  try {
    await http.post('/auth/logout');
  } finally {
    clearTokens();
  }
}

async function refreshToken() {
  const { refresh } = tokens;
  if (!refresh) throw new Error('No refresh token available');

  const { data } = await http.post('/auth/refresh', { refreshToken: refresh });
  const { accessToken: access, refreshToken: nextRefresh } = data;

  if (!access) throw new Error('Failed to refresh token');

  persistTokens({ access, refresh: nextRefresh || refresh });
  return access;
}

/**
 * HTTP verb helpers
 * -----------------------------------------------------------------------------
 */
function unwrap(promise) {
  return promise.then(res => res.data);
}

function get(url, config) {
  return unwrap(http.get(url, config));
}

function post(url, payload, config) {
  return unwrap(http.post(url, payload, config));
}

function put(url, payload, config) {
  return unwrap(http.put(url, payload, config));
}

function patch(url, payload, config) {
  return unwrap(http.patch(url, payload, config));
}

function del(url, config) {
  return unwrap(http.delete(url, config));
}

/**
 * Server-Sent Events helper
 * -----------------------------------------------------------------------------
 * Because native EventSource cannot send custom headers, we pass the
 * JWT via query-param.  The backend should validate the token server-side.
 */
function connectEventStream(topics = [], { onMessage, onError, onOpen } = {}) {
  const params = new URLSearchParams();

  if (topics.length) params.set('topics', topics.join(','));
  if (tokens.access) params.set('access_token', tokens.access);

  const streamUrl = `${API_BASE_URL}/events/stream?${params.toString()}`;
  const source = new EventSource(streamUrl, { withCredentials: true });

  if (onOpen) source.addEventListener('open', onOpen);
  if (onError) source.addEventListener('error', onError);
  if (onMessage) source.addEventListener('message', onMessage);

  return source; // allow caller to .close()
}

/**
 * Exports
 * -----------------------------------------------------------------------------
 */
const api = {
  // raw axios instance if finer control is needed
  client: http,

  // CRUD helpers
  get,
  post,
  put,
  patch,
  delete: del,

  // grouped services
  auth: {
    login,
    logout,
    refresh: refreshToken,
    get tokens() {
      return { ...tokens };
    },
  },

  events: {
    connect: connectEventStream,
  },
};

export default api;
```