package com.wellsphere.connect.core.analytics;

import android.content.Context;
import android.os.Bundle;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.lifecycle.DefaultLifecycleObserver;
import androidx.lifecycle.LifecycleOwner;

import com.google.firebase.analytics.FirebaseAnalytics;
import com.google.firebase.crashlytics.FirebaseCrashlytics;

import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * AnalyticsManager is the single entry-point for emitting analytics events in the
 * WellSphere Connect Android client.  It multiplexes calls to a set of pluggable
 * {@link AnalyticsProvider}s (Firebase, Crashlytics, in-app logger, etc.) while
 * taking care of thread-safety, lazy initialization, and offline queueing.
 *
 * The manager is lifecycle-aware and is intended to be initialized once in the
 * Application class:
 *
 * <pre>
 * public class App extends Application {
 *     public void onCreate() {
 *         super.onCreate();
 *         AnalyticsManager.init(this);
 *     }
 * }
 * </pre>
 *
 * The class is written as a manually implemented, thread-safe Singleton
 * instead of relying on DI frameworks to keep the demo self-contained.
 */
@SuppressWarnings("unused")
public final class AnalyticsManager implements DefaultLifecycleObserver {

    private static final String TAG = "AnalyticsManager";

    // region Singleton ---------------------------------------------------------------------------

    private static volatile AnalyticsManager sInstance;

    /**
     * Initializes the singleton. Calling this twice is a no-op.
     */
    public static void init(@NonNull Context context) {
        if (sInstance == null) {
            synchronized (AnalyticsManager.class) {
                if (sInstance == null) {
                    sInstance = new AnalyticsManager(context.getApplicationContext());
                }
            }
        }
    }

    /**
     * Returns the already initialized instance, throwing if {@link #init(Context)} was not called.
     */
    @NonNull
    public static AnalyticsManager get() {
        if (sInstance == null) {
            throw new IllegalStateException("AnalyticsManager.init(Context) must be called first");
        }
        return sInstance;
    }

    private AnalyticsManager(Context appContext) {
        mAppContext = appContext;
        bootstrapProviders();
    }
    // endregion ----------------------------------------------------------------------------------

    // region Public API --------------------------------------------------------------------------

    /**
     * Logs an analytics event identified by {@code name}. Arbitrary parameters are allowed but
     * provider implementations may filter/rename them according to their own limitations.
     */
    public void trackEvent(@NonNull String name, @Nullable Map<String, ?> parameters) {
        dispatchOrQueue(new AnalyticsEvent(name, parameters));
    }

    /**
     * Convenience overload with no parameters.
     */
    public void trackEvent(@NonNull String name) {
        trackEvent(name, null);
    }

    /**
     * Reports that the user is currently viewing a specific screen.
     */
    public void trackScreen(@NonNull String screenName) {
        HashMap<String, Object> params = new HashMap<>();
        params.put("screen_name", screenName);
        trackEvent(EventNames.SCREEN_VIEW, params);
    }

    /**
     * Associates the supplied user ID with all subsequent analytics events.
     */
    public void setUserId(@NonNull String userId) {
        mGlobalUserId = userId;
        forEachProvider(provider -> provider.setUserId(userId));
    }

    /**
     * Adds or updates a global user property that will be attached to every event.
     */
    public void setUserProperty(@NonNull String key, @NonNull String value) {
        mGlobalUserProperties.put(key, value);
        forEachProvider(provider -> provider.setUserProperty(key, value));
    }

    /**
     * Removes all known user identifiers and properties—useful when a user explicitly logs out.
     */
    public void clearUser() {
        mGlobalUserId = null;
        mGlobalUserProperties.clear();
        forEachProvider(AnalyticsProvider::clearUser);
    }

    // endregion ----------------------------------------------------------------------------------

    // region Lifecycle hooks ---------------------------------------------------------------------

    @Override
    public void onResume(@NonNull LifecycleOwner owner) {
        trackEvent(EventNames.APP_FOREGROUND);
    }

    @Override
    public void onPause(@NonNull LifecycleOwner owner) {
        trackEvent(EventNames.APP_BACKGROUND);
    }

    // endregion ----------------------------------------------------------------------------------

    // region Internal helpers --------------------------------------------------------------------

    private void dispatchOrQueue(@NonNull AnalyticsEvent event) {
        if (mIsReady.get()) {
            dispatch(event);
        } else {
            mPendingEvents.offer(event);
        }
    }

    private void dispatch(@NonNull AnalyticsEvent event) {
        // Merge in global properties before handing off
        event.putAllGlobal(mGlobalUserProperties);
        if (mGlobalUserId != null) {
            event.put(EventParams.USER_ID, mGlobalUserId);
        }

        forEachProvider(provider -> provider.logEvent(event));
    }

    private void flushPendingQueue() {
        AnalyticsEvent e;
        while ((e = mPendingEvents.poll()) != null) {
            dispatch(e);
        }
    }

    private void forEachProvider(@NonNull ProviderAction action) {
        for (AnalyticsProvider provider : mProviders) {
            try {
                action.run(provider);
            } catch (Throwable t) {
                // Never crash the app due to an analytics failure
                Log.e(TAG, "Provider " + provider.getClass().getSimpleName() + " threw", t);
            }
        }
    }

    private void bootstrapProviders() {
        mExecutor.execute(() -> {
            try {
                // Loading providers can involve I/O or reflection; keep off UI thread.
                mProviders.add(new FirebaseAnalyticsProvider(mAppContext));
                mProviders.add(new CrashlyticsAnalyticsProvider());
                mProviders.add(new LogcatAnalyticsProvider());

                // Apply already cached user context
                if (mGlobalUserId != null) {
                    forEachProvider(p -> p.setUserId(mGlobalUserId));
                }
                for (Map.Entry<String, String> entry : mGlobalUserProperties.entrySet()) {
                    forEachProvider(p -> p.setUserProperty(entry.getKey(), entry.getValue()));
                }

                mIsReady.set(true);
                flushPendingQueue();
            } catch (Throwable t) {
                Log.e(TAG, "Failed to bootstrap analytics providers", t);
            }
        });
    }

    // endregion ----------------------------------------------------------------------------------

    // region Data holders ------------------------------------------------------------------------

    /**
     * Represents a single analytics event with optional parameters.
     */
    private static final class AnalyticsEvent {

        private final String mName;
        private final Map<String, Object> mParams;
        private final long mTimestamp = System.currentTimeMillis();

        AnalyticsEvent(@NonNull String name, @Nullable Map<String, ?> params) {
            this.mName = name;
            this.mParams = params != null ?
                    new HashMap<>(params) : new HashMap<>();
        }

        @NonNull
        String getName() {
            return mName;
        }

        @NonNull
        Map<String, Object> getParams() {
            return Collections.unmodifiableMap(mParams);
        }

        long getTimestamp() {
            return mTimestamp;
        }

        void put(@NonNull String key, @NonNull Object value) {
            mParams.put(key, value);
        }

        void putAllGlobal(@NonNull Map<String, String> globals) {
            mParams.putAll(globals);
        }
    }

    /**
     * Contract for analytics service implementations.
     */
    private interface AnalyticsProvider {

        void logEvent(@NonNull AnalyticsEvent event);

        void setUserId(@NonNull String userId);

        void setUserProperty(@NonNull String key, @NonNull String value);

        void clearUser();
    }

    // endregion ----------------------------------------------------------------------------------

    // region Provider impls ----------------------------------------------------------------------

    /**
     * Firebase Analytics backing implementation.
     */
    private static final class FirebaseAnalyticsProvider implements AnalyticsProvider {

        private final FirebaseAnalytics mFa;

        FirebaseAnalyticsProvider(Context context) {
            mFa = FirebaseAnalytics.getInstance(context);
        }

        @Override
        public void logEvent(@NonNull AnalyticsEvent event) {
            Bundle bundle = new Bundle();
            for (Map.Entry<String, Object> entry : event.getParams().entrySet()) {
                Object value = entry.getValue();
                String key = safeParamKey(entry.getKey());
                if (value instanceof Number) {
                    bundle.putDouble(key, ((Number) value).doubleValue());
                } else if (value instanceof Boolean) {
                    bundle.putString(key, ((Boolean) value) ? "true" : "false");
                } else {
                    bundle.putString(key, String.valueOf(value));
                }
            }
            mFa.logEvent(safeEventName(event.getName()), bundle);
        }

        @Override
        public void setUserId(@NonNull String userId) {
            mFa.setUserId(userId);
        }

        @Override
        public void setUserProperty(@NonNull String key, @NonNull String value) {
            mFa.setUserProperty(safeParamKey(key), value);
        }

        @Override
        public void clearUser() {
            mFa.setUserId(null);
        }

        private static String safeEventName(String raw) {
            return raw.length() > 40 ? raw.substring(0, 40) : raw;
        }

        private static String safeParamKey(String raw) {
            return raw.length() > 24 ? raw.substring(0, 24) : raw;
        }
    }

    /**
     * Crashlytics analytics provider that forwards non-fatal breadcrumbs.
     */
    private static final class CrashlyticsAnalyticsProvider implements AnalyticsProvider {

        private final FirebaseCrashlytics mCrashlytics = FirebaseCrashlytics.getInstance();

        @Override
        public void logEvent(@NonNull AnalyticsEvent event) {
            StringBuilder sb = new StringBuilder(event.getName())
                    .append(" @ ").append(event.getTimestamp());
            for (Map.Entry<String, Object> e : event.getParams().entrySet()) {
                sb.append("\n• ")
                  .append(e.getKey())
                  .append(" = ")
                  .append(e.getValue());
            }
            mCrashlytics.log(sb.toString());
        }

        @Override
        public void setUserId(@NonNull String userId) {
            mCrashlytics.setUserId(userId);
        }

        @Override
        public void setUserProperty(@NonNull String key, @NonNull String value) {
            // Crashlytics only supports custom keys; they are global.
            mCrashlytics.setCustomKey(key, value);
        }

        @Override
        public void clearUser() {
            mCrashlytics.setUserId("");
        }
    }

    /**
     * Debug provider that prints everything to Logcat.
     */
    private static final class LogcatAnalyticsProvider implements AnalyticsProvider {

        @Override
        public void logEvent(@NonNull AnalyticsEvent event) {
            Log.d(TAG, "Event " + event.getName() + " " + event.getParams());
        }

        @Override
        public void setUserId(@NonNull String userId) {
            Log.d(TAG, "SetUserId: " + userId);
        }

        @Override
        public void setUserProperty(@NonNull String key, @NonNull String value) {
            Log.d(TAG, "UserProperty[" + key + "]=" + value);
        }

        @Override
        public void clearUser() {
            Log.d(TAG, "ClearUser");
        }
    }

    // endregion ----------------------------------------------------------------------------------

    // region Constants ----------------------------------------------------------------------------

    /**
     * Canonical event names used throughout the application.
     */
    public static final class EventNames {
        public static final String APP_FOREGROUND = "app_foreground";
        public static final String APP_BACKGROUND = "app_background";
        public static final String SCREEN_VIEW    = "screen_view";
        public static final String SHARE_CLICKED  = "share_clicked";
        public static final String LOGIN_SUCCESS  = "login_success";
        public static final String LOGIN_FAILED   = "login_failed";
        public static final String BIOMETRIC_AUTH = "biometric_auth";
        // Add more as needed – keep them < 40 chars for Firebase
    }

    /**
     * Frequently used parameter keys.
     */
    public static final class EventParams {
        public static final String METHOD        = "method";
        public static final String SCREEN_NAME   = "screen_name";
        public static final String STATUS        = "status";
        public static final String ERROR_MESSAGE = "error_message";
        public static final String USER_ID       = "user_id";
    }

    // endregion ----------------------------------------------------------------------------------

    // region Fields ------------------------------------------------------------------------------

    private final Context mAppContext;
    private final List<AnalyticsProvider> mProviders = new CopyOnWriteArrayList<>();
    private final BlockingQueue<AnalyticsEvent> mPendingEvents = new LinkedBlockingQueue<>();
    private final AtomicBoolean mIsReady = new AtomicBoolean(false);
    private final ExecutorService mExecutor = Executors.newSingleThreadExecutor();

    private volatile String mGlobalUserId;
    private final Map<String, String> mGlobalUserProperties = new HashMap<>();

    // endregion ----------------------------------------------------------------------------------

    // region Helper types ------------------------------------------------------------------------

    private interface ProviderAction {
        void run(AnalyticsProvider provider);
    }

    // endregion ----------------------------------------------------------------------------------
}