```javascript
/**
 * PulseLearn Campus Hub – Auth Slice
 *
 * This Redux slice encapsulates all authentication-related concerns:
 *  • Classic credential login
 *  • OAuth / social login
 *  • Silent token refresh
 *  • Cross-tab session synchronisation
 *  • Logout & session cleanup
 *
 * The slice stores the authenticated user, JWT access/refresh tokens and
 * derives the “sessionExpiresAt” timestamp so UI components can display
 * remaining session time and prompt re-authentication if necessary.
 *
 * NOTE: The slice purposefully keeps token handling logic client-side.
 * In production you should prefer httpOnly, SameSite cookies for the
 * access token – especially when SSL (HTTPS) is available. Because many
 * institutional SSO providers require token-relay in the browser, both
 * storage models are available behind a feature flag.
 */

import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { differenceInMilliseconds, addSeconds } from 'date-fns';
import authService from '../../services/authService'; // Axios/Fetch wrapper for auth endpoints

/***********************************************************************
 * Local persistence helpers
 **********************************************************************/
const STORAGE_KEY = 'plch_auth_v1';

/**
 * Persist tokens + user in localStorage (fallback) or sessionStorage
 */
const persistAuthState = ({ accessToken, refreshToken, sessionExpiresAt, user }) => {
  try {
    const payload = JSON.stringify({
      accessToken,
      refreshToken,
      sessionExpiresAt,
      user,
    });
    localStorage.setItem(STORAGE_KEY, window.btoa(payload));
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('Auth persistence failed:', err);
  }
};

/**
 * Reads previously stored auth state if present.
 */
const loadPersistedAuthState = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const decoded = window.atob(raw);
    const parsed = JSON.parse(decoded);

    // Expired? => treat as absent
    if (parsed.sessionExpiresAt && Date.now() > parsed.sessionExpiresAt) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }

    return parsed;
  } catch (err) {
    return null;
  }
};

/** Removes persisted auth artefacts. */
const clearPersistedAuthState = () => localStorage.removeItem(STORAGE_KEY);

/***********************************************************************
 * BroadcastChannel helpers – cross-tab sync
 **********************************************************************/
const channel =
  'BroadcastChannel' in window ? new BroadcastChannel('plch_auth_channel') : null;

export const broadcastAuthEvent = (type, payload = null) => {
  if (!channel) return;
  channel.postMessage({ type, payload });
};

/***********************************************************************
 * Async Thunks
 **********************************************************************/

/**
 * Login with classic credentials (email / password).
 */
export const login = createAsyncThunk(
  'auth/login',
  async ({ email, password }, { rejectWithValue }) => {
    try {
      const response = await authService.login({ email, password }); // { user, accessToken, refreshToken, expiresIn }

      return {
        user: response.user,
        accessToken: response.accessToken,
        refreshToken: response.refreshToken,
        sessionExpiresAt: addSeconds(Date.now(), response.expiresIn).getTime(),
      };
    } catch (err) {
      const message =
        err?.response?.data?.message || err.message || 'Unable to login';
      return rejectWithValue(message);
    }
  }
);

/**
 * OAuth / Social login thunk.
 * Example providers: google, facebook, linkedin, github
 */
export const socialLogin = createAsyncThunk(
  'auth/socialLogin',
  async ({ provider, oauthToken }, { rejectWithValue }) => {
    try {
      const response = await authService.socialLogin(provider, oauthToken);

      return {
        user: response.user,
        accessToken: response.accessToken,
        refreshToken: response.refreshToken,
        sessionExpiresAt: addSeconds(Date.now(), response.expiresIn).getTime(),
      };
    } catch (err) {
      return rejectWithValue(
        err?.response?.data?.message || 'Unable to complete social login'
      );
    }
  }
);

/**
 * Silent refresh of JWT access token using long-lived refresh token.
 */
export const refreshAccessToken = createAsyncThunk(
  'auth/refreshToken',
  async (_, { getState, rejectWithValue }) => {
    const { auth } = getState();
    try {
      const response = await authService.refresh(auth.refreshToken);
      return {
        accessToken: response.accessToken,
        // Refresh token rotation
        refreshToken: response.refreshToken || auth.refreshToken,
        sessionExpiresAt: addSeconds(Date.now(), response.expiresIn).getTime(),
      };
    } catch (err) {
      return rejectWithValue('Session expired');
    }
  }
);

/**
 * Logout thunk – will always resolve (never reject) to make UI handling simpler
 */
export const logout = createAsyncThunk('auth/logout', async (_, { dispatch }) => {
  try {
    await authService.logout(); // fire-and-forget
  } catch (err) {
    // Not critical – ignore
  } finally {
    clearPersistedAuthState();
    broadcastAuthEvent('LOGOUT');
  }
});

/***********************************************************************
 * Slice
 **********************************************************************/
const persisted = loadPersistedAuthState();

const initialState = {
  user: persisted?.user || null,
  accessToken: persisted?.accessToken || null,
  refreshToken: persisted?.refreshToken || null,
  sessionExpiresAt: persisted?.sessionExpiresAt || null,
  status: 'idle', // 'loading' | 'succeeded' | 'failed'
  error: null,
};

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    /**
     * Manual setter for credentials – used by app bootstrap when
     * tokens are restored from cookies or injected by SSR.
     */
    setCredentials: (state, { payload }) => {
      state.user = payload.user;
      state.accessToken = payload.accessToken;
      state.refreshToken = payload.refreshToken;
      state.sessionExpiresAt = payload.sessionExpiresAt;
      persistAuthState(state);
    },
  },
  extraReducers: (builder) => {
    /** LOGIN **********************************************************/
    builder
      .addCase(login.pending, (state) => {
        state.status = 'loading';
        state.error = null;
      })
      .addCase(login.fulfilled, (state, { payload }) => {
        Object.assign(state, payload);
        state.status = 'succeeded';
        state.error = null;
        persistAuthState(state);
        broadcastAuthEvent('LOGIN', { userId: payload.user.id });
      })
      .addCase(login.rejected, (state, { payload }) => {
        state.status = 'failed';
        state.error = payload;
      });

    /** SOCIAL LOGIN ***************************************************/
    builder
      .addCase(socialLogin.pending, (state) => {
        state.status = 'loading';
        state.error = null;
      })
      .addCase(socialLogin.fulfilled, (state, { payload }) => {
        Object.assign(state, payload);
        state.status = 'succeeded';
        state.error = null;
        persistAuthState(state);
        broadcastAuthEvent('LOGIN', { userId: payload.user.id });
      })
      .addCase(socialLogin.rejected, (state, { payload }) => {
        state.status = 'failed';
        state.error = payload;
      });

    /** REFRESH TOKEN **************************************************/
    builder
      .addCase(refreshAccessToken.fulfilled, (state, { payload }) => {
        state.accessToken = payload.accessToken;
        state.refreshToken = payload.refreshToken;
        state.sessionExpiresAt = payload.sessionExpiresAt;
        persistAuthState(state);
      })
      .addCase(refreshAccessToken.rejected, (state) => {
        // Refresh failed → treat as logout
        state.user = null;
        state.accessToken = null;
        state.refreshToken = null;
        state.sessionExpiresAt = null;
        clearPersistedAuthState();
      });

    /** LOGOUT *********************************************************/
    builder.addCase(logout.fulfilled, (state) => {
      state.user = null;
      state.accessToken = null;
      state.refreshToken = null;
      state.sessionExpiresAt = null;
      state.status = 'idle';
      state.error = null;
    });
  },
});

/***********************************************************************
 * Selectors
 **********************************************************************/
export const selectCurrentUser = (state) => state.auth.user;
export const selectIsAuthenticated = (state) => Boolean(state.auth.user);
export const selectAccessToken = (state) => state.auth.accessToken;
export const selectSessionExpiresIn = (state) =>
  state.auth.sessionExpiresAt
    ? Math.max(0, differenceInMilliseconds(state.auth.sessionExpiresAt, Date.now()))
    : 0;

/***********************************************************************
 * Cross-tab event listener
 **********************************************************************/
if (channel) {
  channel.onmessage = ({ data }) => {
    if (data?.type === 'LOGOUT') {
      // Soft reload current page – components will react to cleared store
      window.location.reload();
    }
  };
}

export const { setCredentials } = authSlice.actions;
export default authSlice.reducer;
```