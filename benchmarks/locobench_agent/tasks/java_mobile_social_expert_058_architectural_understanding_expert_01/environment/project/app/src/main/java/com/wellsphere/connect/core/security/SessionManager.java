```java
package com.wellsphere.connect.core.security;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.VisibleForTesting;
import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import java.io.IOException;
import java.security.GeneralSecurityException;
import java.time.Instant;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ReentrantLock;

/**
 * Manages the authentication session (access / refresh tokens, expiry time, etc.)
 * for the current user. Handles secure persistence, token‐refresh workflow and
 * notifies registered listeners when the session state changes.
 *
 * This class is implemented as a thread-safe singleton. In production builds it
 * leverages EncryptedSharedPreferences for at-rest encryption; older devices
 * gracefully fall back to the regular (non-encrypted) SharedPreferences API.
 */
@SuppressWarnings("WeakerAccess")
public final class SessionManager {

    // region Static API --------------------------------------------------------------------------

    private static final String TAG = "SessionManager";

    private static final String PREF_FILE_NAME =
            "com.wellsphere.connect.session.secure_store";

    // Preference keys
    private static final String KEY_ACCESS_TOKEN  = "access_token";
    private static final String KEY_REFRESH_TOKEN = "refresh_token";
    private static final String KEY_EXPIRES_AT    = "expires_at";      // epoch-seconds
    private static final String KEY_USER_ID       = "user_id";

    // Singleton holder (Bill Pugh idiom)
    private static volatile SessionManager sInstance;

    /**
     * Returns the singleton instance, creating it lazily if necessary.
     */
    public static SessionManager getInstance(@NonNull Context context,
                                             @NonNull TokenRefresher tokenRefresher) {
        if (sInstance == null) {
            synchronized (SessionManager.class) {
                if (sInstance == null) {
                    sInstance = new SessionManager(context.getApplicationContext(),
                                                   tokenRefresher);
                }
            }
        }
        return sInstance;
    }

    @VisibleForTesting
    static void clearForTesting() {
        sInstance = null;
    }

    // endregion ----------------------------------------------------------------------------------

    // region Members -----------------------------------------------------------------------------

    private final SharedPreferences mPrefs;
    private final TokenRefresher    mTokenRefresher;
    private final Set<SessionListener> mListeners =
            Collections.synchronizedSet(new HashSet<>());

    private final ExecutorService mExecutor = Executors.newSingleThreadExecutor();
    private final ReentrantLock   mLock     = new ReentrantLock(true);

    // Cached in-memory representation (to avoid unnecessary JSON parsing / IO)
    private volatile Session mCurrentSession;

    // endregion ----------------------------------------------------------------------------------

    private SessionManager(Context appContext, TokenRefresher tokenRefresher) {
        this.mPrefs          = createSecureStore(appContext);
        this.mTokenRefresher = tokenRefresher;
        this.mCurrentSession = loadSessionFromPrefs();
    }

    // region Public API --------------------------------------------------------------------------

    /**
     * Stores the authentication payload (e.g., after login or token refresh),
     * updates memory cache and broadcasts the change.
     */
    public void login(@NonNull AuthPayload payload) {
        mLock.lock();
        try {
            Session session = new Session(payload.getUserId(),
                                          payload.getAccessToken(),
                                          payload.getRefreshToken(),
                                          payload.getExpiresAtEpochSeconds());

            persistSession(session);
            mCurrentSession = session;
            notifySessionChanged(session);
        } finally {
            mLock.unlock();
        }
    }

    /**
     * Returns {@code true} if a valid (non-expired) session is present.
     */
    public boolean isLoggedIn() {
        Session s = mCurrentSession;
        return s != null && !s.isExpired();
    }

    /**
     * Returns the currently cached session (may be {@code null}).
     * Callers SHOULD verify {@link Session#isExpired()} before usage.
     */
    public Session getActiveSession() {
        return mCurrentSession;
    }

    /**
     * Asynchronously refreshes the access token if it has expired or is about to
     * expire (within {@link Session#GRACE_PERIOD_SECONDS}). If a refresh is not
     * necessary, the current (still-valid) session is emitted immediately.
     */
    public CompletableFuture<Session> refreshSessionIfNeeded() {
        Session snapshot = mCurrentSession;
        if (snapshot == null) {
            return CompletableFuture.failedFuture(new IllegalStateException("No session present."));
        }

        if (!snapshot.shouldRefreshSoon()) {
            return CompletableFuture.completedFuture(snapshot);
        }

        return CompletableFuture.supplyAsync(() -> {
            mLock.lock();
            try {
                Session latest = mCurrentSession;
                if (latest == null) {
                    throw new IllegalStateException("Session cleared while refreshing.");
                }
                // Double-check inside lock to avoid multiple refresh calls.
                if (!latest.shouldRefreshSoon()) {
                    return latest;
                }

                try {
                    AuthPayload newPayload =
                            mTokenRefresher.refresh(latest.getRefreshToken());

                    Session updated = new Session(newPayload.getUserId(),
                                                  newPayload.getAccessToken(),
                                                  newPayload.getRefreshToken(),
                                                  newPayload.getExpiresAtEpochSeconds());
                    persistSession(updated);
                    mCurrentSession = updated;
                    notifySessionChanged(updated);
                    return updated;
                } catch (IOException | AuthException e) {
                    Log.e(TAG, "Token refresh failed", e);
                    // Bubble the error up to the caller
                    throw new RuntimeException(e);
                }
            } finally {
                mLock.unlock();
            }
        }, mExecutor);
    }

    /**
     * Clears session information from both memory and secure storage.
     */
    public void logout() {
        mLock.lock();
        try {
            mPrefs.edit().clear().apply();
            mCurrentSession = null;
            notifySessionChanged(null);
        } finally {
            mLock.unlock();
        }
    }

    /*
     * Listener management
     */
    public void addSessionListener(@NonNull SessionListener listener) {
        mListeners.add(listener);
        // Immediately notify new listener of current state
        listener.onSessionChanged(mCurrentSession);
    }

    public void removeSessionListener(@NonNull SessionListener listener) {
        mListeners.remove(listener);
    }

    // endregion ----------------------------------------------------------------------------------

    // region Internal helpers --------------------------------------------------------------------

    private void notifySessionChanged(Session newSession) {
        for (SessionListener l : mListeners) {
            try {
                l.onSessionChanged(newSession);
            } catch (Throwable t) {
                Log.e(TAG, "Listener threw during onSessionChanged", t);
            }
        }
    }

    private void persistSession(Session s) {
        mPrefs.edit()
                .putString(KEY_USER_ID,       s.getUserId())
                .putString(KEY_ACCESS_TOKEN,  s.getAccessToken())
                .putString(KEY_REFRESH_TOKEN, s.getRefreshToken())
                .putLong  (KEY_EXPIRES_AT,    s.getExpiresAtEpochSeconds())
                .apply();
    }

    private Session loadSessionFromPrefs() {
        String  userId       = mPrefs.getString(KEY_USER_ID, null);
        String  accessToken  = mPrefs.getString(KEY_ACCESS_TOKEN, null);
        String  refreshToken = mPrefs.getString(KEY_REFRESH_TOKEN, null);
        long    expiry       = mPrefs.getLong(KEY_EXPIRES_AT, 0);

        if (userId == null || accessToken == null || refreshToken == null || expiry == 0) {
            return null;
        }
        return new Session(userId, accessToken, refreshToken, expiry);
    }

    private static SharedPreferences createSecureStore(Context ctx) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                MasterKey key = new MasterKey.Builder(ctx)
                        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                        .build();

                return EncryptedSharedPreferences.create(
                        ctx,
                        PREF_FILE_NAME,
                        key,
                        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
                );
            }
        } catch (GeneralSecurityException | IOException e) {
            Log.w(TAG, "Falling back to unencrypted SharedPreferences", e);
        }
        return ctx.getSharedPreferences(PREF_FILE_NAME, Context.MODE_PRIVATE);
    }

    // endregion ----------------------------------------------------------------------------------

    // region Inner types -------------------------------------------------------------------------

    /**
     * Immutable representation of an auth session.
     */
    public static final class Session {

        private static final long GRACE_PERIOD_SECONDS = 60L; // 1-minute buffer

        private final String userId;
        private final String accessToken;
        private final String refreshToken;
        private final long   expiresAtEpochSeconds;

        Session(@NonNull String userId,
                @NonNull String accessToken,
                @NonNull String refreshToken,
                long expiresAtEpochSeconds) {

            this.userId                = userId;
            this.accessToken           = accessToken;
            this.refreshToken          = refreshToken;
            this.expiresAtEpochSeconds = expiresAtEpochSeconds;
        }

        public String getUserId()               { return userId; }
        public String getAccessToken()          { return accessToken; }
        public String getRefreshToken()         { return refreshToken; }
        public long   getExpiresAtEpochSeconds(){ return expiresAtEpochSeconds; }

        /**
         * Returns {@code true} if the session has already expired.
         */
        public boolean isExpired() {
            return Instant.now().getEpochSecond() >= expiresAtEpochSeconds;
        }

        /**
         * Returns {@code true} if the expiration is close enough that a refresh
         * should be attempted now.
         */
        public boolean shouldRefreshSoon() {
            long now = Instant.now().getEpochSecond();
            return expiresAtEpochSeconds - now <= GRACE_PERIOD_SECONDS;
        }

        @Override public String toString() {
            return "Session{uid=" + userId + ", expiresAt=" + expiresAtEpochSeconds + '}';
        }
    }

    /**
     * Auth payload returned by the backend on login / refresh.
     */
    public interface AuthPayload {

        String getUserId();
        String getAccessToken();
        String getRefreshToken();
        long   getExpiresAtEpochSeconds();
    }

    /**
     * Callback for session changes (login, logout, token refresh).
     */
    public interface SessionListener {
        void onSessionChanged(Session newSession);
    }

    /**
     * Abstraction that hits the API to refresh tokens.
     *
     * Implementations typically wrap Retrofit calls, e.g.
     *
     *   @Override public AuthPayload refresh(String refreshToken) throws IOException {
     *       return apiService.refresh(refreshToken).execute().body();
     *   }
     *
     * Any IO / HTTP errors should be surfaced via exception.
     */
    public interface TokenRefresher {

        AuthPayload refresh(@NonNull String refreshToken)
                throws IOException, AuthException;
    }

    /**
     * Exception thrown when authentication refresh fails (401, malformed body, etc.).
     */
    public static class AuthException extends Exception {
        public AuthException(String message) {
            super(message);
        }

        public AuthException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    // endregion ----------------------------------------------------------------------------------
}
```