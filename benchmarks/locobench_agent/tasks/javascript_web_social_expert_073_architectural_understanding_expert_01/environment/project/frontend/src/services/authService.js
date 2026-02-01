```javascript
/**
 * PulseLearn Campus Hub – Authentication Service
 * ----------------------------------------------
 * Centralises all logic related to authentication / authorisation on the
 * client-side.  Handles:
 *
 *  • Username/Password sign-in
 *  • Social OAuth login flows
 *  • Token refresh with automatic retry & concurrency control
 *  • Cross-tab session synchronisation (BroadcastChannel + storage events)
 *  • Global auth event dispatching (login, logout, tokenRefresh)
 *
 *  NOTE: The refresh token is assumed to be stored in an httpOnly cookie that
 *  is automatically sent by the browser.  Access tokens are stored in
 *  memory + fallback to `localStorage` for persistence across reloads.
 */

import axios from 'axios';
import jwtDecode from 'jwt-decode';
import { EventEmitter } from 'events';

/* -------------------------------------------------------------------------- */
/*                              Module Constants                              */
/* -------------------------------------------------------------------------- */

const STORAGE_KEY = 'pl.accessToken';
const AUTH_CHANNEL = 'pl-auth-channel';

const API_BASE_URL =
  process.env.REACT_APP_API_GATEWAY_URL?.replace(/\/+$/g, '') || '/api';

/* -------------------------------------------------------------------------- */
/*                          Axios Instance & Helpers                          */
/* -------------------------------------------------------------------------- */

/**
 * Dedicated axios instance so that interceptors do not pollute
 * other API clients.
 */
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // sends httpOnly refresh token cookie
});

/* -------------------------------------------------------------------------- */
/*                              Helper Functions                              */
/* -------------------------------------------------------------------------- */

/**
 * Persist access token in localStorage and memory.
 * @param {string|null} token
 */
function persistToken(token) {
  if (token) {
    localStorage.setItem(STORAGE_KEY, token);
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

/**
 * Returns the token payload (decoded) or null if invalid.
 * @param {string} token
 */
function decodeToken(token) {
  try {
    return jwtDecode(token);
  } catch {
    return null;
  }
}

/**
 * Determine if the JWT is still valid.
 * @param {string} token
 */
function isTokenValid(token) {
  const payload = decodeToken(token);
  if (!payload || !payload.exp) return false;
  const expInMs = payload.exp * 1000; // convert seconds → ms
  return expInMs > Date.now();
}

/* -------------------------------------------------------------------------- */
/*                                 AuthService                                */
/* -------------------------------------------------------------------------- */

class AuthService extends EventEmitter {
  accessToken = localStorage.getItem(STORAGE_KEY);
  refreshPromise = null; // Avoid parallel refresh requests
  broadcastChannel = null;

  constructor() {
    super();
    this.configureInterceptors();
    this.configureTabSync();
  }

  /* --------------------------- Public API Surface -------------------------- */

  /**
   * Perform a traditional username / password login.
   * @param {{email: string, password: string}} credentials
   * @returns {Promise<Object>} user DTO
   */
  async login(credentials) {
    try {
      const res = await apiClient.post('/auth/login', credentials);
      this.setAccessToken(res.data.accessToken);
      this.emit('login', this.getCurrentUser());
      return res.data.user;
    } catch (err) {
      this.handleAuthError(err);
    }
  }

  /**
   * Social OAuth login – expects backend to exchange provider token.
   * @param {'google'|'facebook'|'github'} provider
   * @param {string} providerAccessToken
   */
  async socialLogin(provider, providerAccessToken) {
    try {
      const res = await apiClient.post(`/auth/social/${provider}`, {
        accessToken: providerAccessToken,
      });
      this.setAccessToken(res.data.accessToken);
      this.emit('login', this.getCurrentUser());
      return res.data.user;
    } catch (err) {
      this.handleAuthError(err);
    }
  }

  /**
   * Logs the user out on the server and client.
   * @param {boolean} [broadcast=true] - whether to inform other tabs
   */
  async logout(broadcast = true) {
    try {
      await apiClient.post('/auth/logout'); // ignore failure
    } finally {
      this.setAccessToken(null);
      if (broadcast) this.broadcastChannel?.postMessage({ type: 'LOGOUT' });
      this.emit('logout');
    }
  }

  /**
   * @returns {boolean}
   */
  isAuthenticated() {
    return !!this.accessToken && isTokenValid(this.accessToken);
  }

  /**
   * Returns the current user decoded from the access token.
   * @returns {Object|null}
   */
  getCurrentUser() {
    if (!this.accessToken) return null;
    const payload = decodeToken(this.accessToken);
    return payload?.user || null;
  }

  /**
   * Retrieves a valid access token, refreshing it if necessary.
   * Can be awaited by external callers as well.
   */
  async getAccessToken() {
    if (this.isAuthenticated()) return this.accessToken;
    await this.refreshAccessToken();
    return this.accessToken;
  }

  /* --------------------------- Internal Utilities -------------------------- */

  /**
   * Sets the access token in memory, localStorage & axios default header.
   * @param {string|null} token
   */
  setAccessToken(token) {
    this.accessToken = token;
    persistToken(token);
    if (token) {
      apiClient.defaults.headers.common.Authorization = `Bearer ${token}`;
      if (this.isAuthenticated()) this.scheduleTokenRefresh();
    } else {
      delete apiClient.defaults.headers.common.Authorization;
      this.clearRefreshTimer();
    }
  }

  /**
   * Refreshes the access token using the httpOnly refresh token cookie.
   * Ensures only one refresh request is outstanding.
   */
  async refreshAccessToken() {
    if (this.refreshPromise) return this.refreshPromise;

    this.refreshPromise = (async () => {
      try {
        const res = await apiClient.post('/auth/refresh');
        this.setAccessToken(res.data.accessToken);
        this.emit('tokenRefresh', this.accessToken);
        return this.accessToken;
      } catch (err) {
        // Refresh failed – logout user silently
        await this.logout(false);
        throw err;
      } finally {
        this.refreshPromise = null;
      }
    })();

    return this.refreshPromise;
  }

  /**
   * Global axios interceptors for injecting token & handling 401 responses.
   */
  configureInterceptors() {
    // Request interceptor: inject access token if present
    apiClient.interceptors.request.use(
      async (config) => {
        if (!this.accessToken) return config;
        if (!isTokenValid(this.accessToken)) {
          await this.refreshAccessToken();
        }
        config.headers.Authorization = `Bearer ${this.accessToken}`;
        return config;
      },
      (error) => Promise.reject(error),
    );

    // Response interceptor: attempt refresh on 401, then retry
    apiClient.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config;
        if (
          error.response?.status === 401 &&
          !originalRequest._retry &&
          !originalRequest.url.endsWith('/auth/refresh')
        ) {
          originalRequest._retry = true;
          try {
            await this.refreshAccessToken();
            originalRequest.headers.Authorization = `Bearer ${this.accessToken}`;
            return apiClient(originalRequest);
          } catch {
            // If refresh also fails, propagate logout
            await this.logout();
          }
        }
        return Promise.reject(error);
      },
    );

    // Initialise default header on cold start
    if (this.accessToken) {
      apiClient.defaults.headers.common.Authorization = `Bearer ${this.accessToken}`;
      this.scheduleTokenRefresh();
    }
  }

  /**
   * Handle auth-related errors and expose clean error messages.
   */
  handleAuthError(err) {
    const message =
      err.response?.data?.message ||
      err.message ||
      'Authentication failed. Please try again.';
    /* eslint-disable no-console */
    console.error('[AuthService]', message);
    /* eslint-enable no-console */
    throw new Error(message);
  }

  /* ---------------------- Cross-Tab Session Synchronisation ---------------------- */

  configureTabSync() {
    // BroadcastChannel is modern; we fallback to storage event for older browsers
    if ('BroadcastChannel' in window) {
      this.broadcastChannel = new BroadcastChannel(AUTH_CHANNEL);
      this.broadcastChannel.onmessage = (e) => {
        if (e.data?.type === 'LOGOUT') this.logout(false);
        if (e.data?.type === 'TOKEN_REFRESH' && e.data.token)
          this.setAccessToken(e.data.token);
      };
    } else {
      window.addEventListener('storage', (e) => {
        if (e.key !== STORAGE_KEY) return;
        // localStorage event gives null if removed
        this.setAccessToken(e.newValue);
        if (!e.newValue) this.emit('logout');
      });
    }
  }

  /* --------------------------- Token Refresh Timing --------------------------- */

  refreshTimerId = null;

  scheduleTokenRefresh() {
    this.clearRefreshTimer();
    const payload = decodeToken(this.accessToken);
    if (!payload?.exp) return;
    const msUntilExpiry = payload.exp * 1000 - Date.now();
    // Refresh 60s before expiry
    const refreshInMs = Math.max(msUntilExpiry - 60_000, 0);
    this.refreshTimerId = window.setTimeout(
      () => this.refreshAccessToken(),
      refreshInMs,
    );
  }

  clearRefreshTimer() {
    if (this.refreshTimerId) {
      clearTimeout(this.refreshTimerId);
      this.refreshTimerId = null;
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                           Export a Singleton Instance                       */
/* -------------------------------------------------------------------------- */

const authService = new AuthService();
export default authService;
export { apiClient }; // sometimes useful for external modules
```