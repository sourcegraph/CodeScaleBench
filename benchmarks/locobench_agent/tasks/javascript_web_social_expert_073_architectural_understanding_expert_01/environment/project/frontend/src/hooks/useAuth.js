```javascript
/**
 * PulseLearn Campus Hub – useAuth hook
 *
 * A production-grade authentication hook that
 *  • Manages JWT access / refresh tokens
 *  • Handles login, logout, social login, token-refresh & session expiry
 *  • Wires Axios interceptors so every outgoing request
 *    automatically contains a valid Authorization header
 *  • Broadcasts auth events across browser tabs
 *
 * Dependencies:
 *    react              ^18.x
 *    axios              ^1.x
 *    jwt-decode         ^3.x
 *    uuid               ^9.x
 *
 * Environment variables required (see .env.*):
 *    VITE_API_BASE_URL
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import jwtDecode from 'jwt-decode';
import { v4 as uuid } from 'uuid';

// -----------------------------------------------------------------------------
// Constants
// -----------------------------------------------------------------------------
const ACCESS_TOKEN_KEY  = 'pl__accessToken';
const REFRESH_TOKEN_KEY = 'pl__refreshToken';
const TAB_BROADCAST_KEY = 'pl__authEvent';
const TOKEN_REFRESH_GRACE_PERIOD = 60; // seconds before expiry to auto-refresh
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

// -----------------------------------------------------------------------------
// Axios instance configured for PulseLearn API
// -----------------------------------------------------------------------------
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // include cookies for CSRF/session protection
  timeout: 15_000,
});

/**
 * Attaches the bearer token if present.
 */
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// -----------------------------------------------------------------------------
// Module-level helper — shared refresh queue to prevent parallel refresh calls
// -----------------------------------------------------------------------------
let refreshPromise = null; // will contain a Promise when a refresh is in flight

const queueTokenRefresh = async () => {
  if (!refreshPromise) {
    refreshPromise = refreshToken()
      .catch((err) => {
        // bubble error to callers
        throw err;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
};

/**
 * Calls backend /auth/refresh to get a new access token.
 */
async function refreshToken() {
  const existingRefreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!existingRefreshToken) throw new Error('No refresh token available');

  const response = await axios.post(
    `${API_BASE_URL}/auth/refresh`,
    { refreshToken: existingRefreshToken },
    { withCredentials: true },
  );

  const { accessToken, refreshToken: newRefreshToken } = response.data;

  persistTokens(accessToken, newRefreshToken);
  return accessToken;
}

/**
 * Persist tokens securely in localStorage.
 */
function persistTokens(accessToken, refreshToken) {
  if (accessToken) localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  // broadcast to all other tabs
  localStorage.setItem(
    TAB_BROADCAST_KEY,
    JSON.stringify({ id: uuid(), type: 'TOKEN_UPDATE' }),
  );
}

/**
 * Clears tokens from localStorage & notify tabs.
 */
function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.setItem(
    TAB_BROADCAST_KEY,
    JSON.stringify({ id: uuid(), type: 'LOGOUT' }),
  );
}

/**
 * Decode JWT and return payload with fallback.
 */
function safeDecode(token) {
  try {
    return jwtDecode(token);
  } catch {
    return null;
  }
}

// -----------------------------------------------------------------------------
// Public Hook
// -----------------------------------------------------------------------------
export default function useAuth() {
  const [accessToken, setAccessToken] = useState(() =>
    localStorage.getItem(ACCESS_TOKEN_KEY),
  );
  const [user, setUser] = useState(() => safeDecode(accessToken));
  const [initialising, setInitialising] = useState(true);

  /**
   * Parse token every time it changes.
   */
  useEffect(() => {
    setUser(safeDecode(accessToken));
  }, [accessToken]);

  /**
   * Handles login with email & password.
   */
  const login = useCallback(async (email, password) => {
    try {
      const { data } = await axios.post(
        `${API_BASE_URL}/auth/login`,
        { email, password },
        { withCredentials: true },
      );
      persistTokens(data.accessToken, data.refreshToken);
      setAccessToken(data.accessToken);
      return { ok: true };
    } catch (err) {
      console.error('[Auth] login failed', err);
      return { ok: false, message: err.response?.data?.message ?? err.message };
    }
  }, []);

  /**
   * Social login flow (OAuth callback comes with ?code=...).
   */
  const socialLogin = useCallback(async (provider, code) => {
    try {
      const { data } = await axios.post(
        `${API_BASE_URL}/auth/social/${provider}/callback`,
        { code },
        { withCredentials: true },
      );
      persistTokens(data.accessToken, data.refreshToken);
      setAccessToken(data.accessToken);
      return { ok: true };
    } catch (err) {
      console.error('[Auth] socialLogin failed', err);
      return { ok: false, message: err.response?.data?.message ?? err.message };
    }
  }, []);

  /**
   * Logout everywhere.
   */
  const logout = useCallback(async () => {
    try {
      await axios.post(
        `${API_BASE_URL}/auth/logout`,
        {},
        { withCredentials: true },
      );
    } catch (err) {
      // backend logout failure is not critical; continue clearing local tokens
      console.warn('[Auth] server logout failed', err);
    } finally {
      clearTokens();
      setAccessToken(null);
    }
  }, []);

  /**
   * Attempt to refresh token silently on mount.
   */
  useEffect(() => {
    let isMounted = true;
    const init = async () => {
      try {
        if (!accessToken) {
          const newToken = await queueTokenRefresh();
          if (isMounted) setAccessToken(newToken);
        }
      } catch (err) {
        // refresh token invalid – force logout
        clearTokens();
        if (isMounted) setAccessToken(null);
      } finally {
        if (isMounted) setInitialising(false);
      }
    };
    init();
    return () => {
      isMounted = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * Intercept API responses to auto-refresh on 401.
   */
  useEffect(() => {
    const resInterceptor = apiClient.interceptors.response.use(
      (r) => r,
      async (error) => {
        const { response, config } = error;
        if (response?.status === 401 && !config._retry) {
          try {
            config._retry = true;
            const newToken = await queueTokenRefresh();
            config.headers.Authorization = `Bearer ${newToken}`;
            return apiClient(config);
          } catch (refreshErr) {
            // Still unauthenticated – logout user
            await logout();
          }
        }
        return Promise.reject(error);
      },
    );
    return () => {
      apiClient.interceptors.response.eject(resInterceptor);
    };
  }, [logout]);

  /**
   * Schedules a timer to refresh token just before expiry.
   */
  useEffect(() => {
    if (!accessToken) return undefined;

    const { exp } = safeDecode(accessToken) ?? {};
    if (!exp) return undefined;

    const now = Date.now() / 1000; // seconds
    const delaySeconds = Math.max(exp - now - TOKEN_REFRESH_GRACE_PERIOD, 1);
    const id = setTimeout(() => {
      queueTokenRefresh().then(setAccessToken).catch(() => logout());
    }, delaySeconds * 1000);

    return () => clearTimeout(id);
  }, [accessToken, logout]);

  /**
   * Listen for token updates from other tabs.
   */
  useEffect(() => {
    const storageListener = (e) => {
      if (e.key !== TAB_BROADCAST_KEY || !e.newValue) return;
      const event = JSON.parse(e.newValue);
      switch (event.type) {
        case 'TOKEN_UPDATE':
          setAccessToken(localStorage.getItem(ACCESS_TOKEN_KEY));
          break;
        case 'LOGOUT':
          setAccessToken(null);
          break;
        default:
      }
    };
    window.addEventListener('storage', storageListener);
    return () => window.removeEventListener('storage', storageListener);
  }, []);

  /**
   * Derived state helpers exposed to consumers.
   */
  const isAuthenticated = useMemo(() => Boolean(user), [user]);

  return {
    user,
    isAuthenticated,
    initialising,
    login,
    socialLogin,
    logout,
    /**
     * Retrieve current access token (read-only).
     * NOTE: Prefer the provided axios instance (apiClient) to perform requests.
     */
    getAccessToken: () => accessToken,
    /**
     * Pre-configured axios client with automatic auth handling.
     */
    apiClient,
  };
}
```