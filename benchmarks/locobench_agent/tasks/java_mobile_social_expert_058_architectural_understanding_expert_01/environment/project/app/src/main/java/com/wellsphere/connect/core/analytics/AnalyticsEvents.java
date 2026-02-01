package com.wellsphere.connect.core.analytics;

import android.content.Context;
import android.os.Bundle;
import android.text.TextUtils;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.firebase.analytics.FirebaseAnalytics;

import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Centralized entry-point for tracking analytics events throughout the
 * WellSphere Connect application.  All modules—UI, data layer, background
 * services—should funnel events through this façade instead of calling
 * vendor SDKs directly.  This indirection ensures that:
 *
 *   1) PHI never leaks to third-party analytics providers.
 *   2) Multiple analytics sinks (Firebase, proprietary, debug logger, etc.)
 *      can be enabled/disabled dynamically.
 *   3) The rest of the code-base does not depend on vendor-specific APIs.
 *
 * Thread-safety: All public APIs are safe to call from any thread.
 */
@SuppressWarnings("WeakerAccess")
public final class AnalyticsEvents {

    //region === Singleton Boilerplate ===
    private static volatile AnalyticsEvents sInstance;

    /**
     * Returns the global AnalyticsEvents instance, creating it if necessary.
     * The {@code context} parameter is only required the first time; thereafter
     * you may safely pass {@code null}.
     */
    public static @NonNull AnalyticsEvents getInstance(@Nullable Context context) {
        if (sInstance == null) {
            synchronized (AnalyticsEvents.class) {
                if (sInstance == null) {
                    if (context == null) {
                        throw new IllegalStateException("AnalyticsEvents not yet initialized.");
                    }
                    sInstance = new AnalyticsEvents(context.getApplicationContext());
                }
            }
        }
        return sInstance;
    }

    private final List<AnalyticsTracker> mTrackers = new CopyOnWriteArrayList<>();
    private final Context mAppContext;
    //endregion

    //region === Constructor ===
    private AnalyticsEvents(@NonNull Context appContext) {
        this.mAppContext = appContext;

        // Register default trackers. Others (e.g., Mixpanel) can be added at runtime.
        try {
            mTrackers.add(new FirebaseAnalyticsTracker(appContext));
        } catch (Throwable t) {
            Log.w(TAG, "Failed to initialize Firebase tracker.", t);
        }

        // Debug logger tracker for QA builds.
        if (BuildConfig.DEBUG) {
            mTrackers.add(new LogcatAnalyticsTracker());
        }
    }
    //endregion

    //region === Public API ===
    /**
     * Logs an analytics event with zero additional parameters.
     */
    public void log(@NonNull Event event) {
        log(event, Collections.emptyMap());
    }

    /**
     * Logs an analytics event with the specified parameters.
     *
     * @param event  Event to record.  Never {@code null}.
     * @param params Optional param map; will be sanitized before forwarding.
     */
    public void log(@NonNull Event event,
                    @Nullable Map<String, Object> params) {

        if (event == null) {
            Log.w(TAG, "Ignoring analytics call with null event.");
            return;
        }

        Map<String, Object> safeParams = sanitize(params);
        for (AnalyticsTracker tracker : mTrackers) {
            try {
                tracker.track(event.getName(), safeParams);
            } catch (Throwable t) {
                Log.e(TAG, "Analytics tracker " + tracker.getClass().getSimpleName()
                        + " threw exception.", t);
            }
        }
    }

    /**
     * Adds the supplied tracker at runtime.
     * Useful for 3rd-party modules that ship their own analytics sink.
     */
    public void registerTracker(@NonNull AnalyticsTracker tracker) {
        if (tracker != null) {
            mTrackers.add(tracker);
        }
    }
    //endregion

    //region === Sanitization Helpers ===
    private static final int MAX_PARAM_LENGTH = 120;
    private static final Set<Class<?>> SUPPORTED_PARAM_TYPES = Set.of(
            String.class, Integer.class, Long.class, Double.class, Float.class, Boolean.class
    );

    /**
     * Scrubs PII/PHI and formats parameters into analytics-safe primitives.
     */
    private @NonNull Map<String, Object> sanitize(@Nullable Map<String, Object> raw) {
        if (raw == null || raw.isEmpty()) {
            return Collections.emptyMap();
        }

        Map<String, Object> sanitized = new HashMap<>();
        for (Map.Entry<String, Object> entry : raw.entrySet()) {
            String key = entry.getKey();
            Object val = entry.getValue();

            if (key == null || val == null) continue; // Skip nulls.
            if (!SUPPORTED_PARAM_TYPES.contains(val.getClass())) continue; // Skip complex types.
            if (val instanceof String) {
                String str = truncate((String) val, MAX_PARAM_LENGTH);
                if (containsPhi(str)) continue; // Drop potential PHI.
                sanitized.put(key, str);
            } else {
                sanitized.put(key, val);
            }
        }
        return sanitized;
    }

    private static String truncate(@NonNull String input, int max) {
        return input.length() <= max ? input : input.substring(0, max);
    }

    /**
     * Extremely naive PHI check. In production consider integrating a proper
     * de-identification library.
     */
    private static boolean containsPhi(@NonNull String value) {
        // Reject if value looks like an email address, phone #, or MRN-like id.
        return value.matches(".*@.*") ||
               value.matches(".*\\d{3}-\\d{2}-\\d{4}.*") || // SSN pattern
               value.matches(".*\\d{10,}.*");
    }
    //endregion

    //region === Event Definitions ===
    /**
     * Enumerates all trackable analytics events in the app.  Keep names stable
     * once released to avoid skewed longitudinal metrics.
     */
    public enum Event {
        // Auth flow
        LOGIN_ATTEMPT("login_attempt"),
        LOGIN_SUCCESS("login_success"),
        LOGIN_FAILURE("login_failure"),
        BIOMETRIC_AUTH_SUCCESS("biometric_auth_success"),
        BIOMETRIC_AUTH_FAILURE("biometric_auth_failure"),

        // Feed & social
        POST_CREATED("post_created"),
        POST_SHARED_EXTERNALLY("post_shared_externally"),
        COMMENT_ADDED("comment_added"),
        IMAGE_UPLOADED("image_uploaded"),

        // Care plans & IAP
        CARE_PLAN_VIEWED("care_plan_viewed"),
        SUBSCRIPTION_PURCHASED("subscription_purchased"),
        SUBSCRIPTION_CANCELLED("subscription_cancelled"),

        // Location & activities
        LOCATION_PERMISSION_GRANTED("location_permission_granted"),
        WORKOUT_SESSION_RECORDED("workout_session_recorded"),

        // Error & crashes
        APP_CRASHED("app_crashed"),
        EXCEPTION_LOGGED("exception_logged");

        private final String mName;

        Event(@NonNull String name) {
            mName = name;
        }

        public @NonNull String getName() {
            return mName;
        }
    }
    //endregion

    //region === AnalyticsTracker Abstraction ===
    /**
     * Strategy interface allowing multiple analytics backends to coexist.
     */
    public interface AnalyticsTracker {
        /**
         * @param eventName   canonical event name
         * @param eventParams sanitized params, may be empty but never null
         */
        void track(@NonNull String eventName,
                   @NonNull Map<String, Object> eventParams);
    }
    //endregion

    //region === Firebase Implementation ===
    /**
     * Thin adapter around FirebaseAnalytics.
     */
    private static final class FirebaseAnalyticsTracker implements AnalyticsTracker {

        private final FirebaseAnalytics firebase;
        // Cache to avoid repeated Bundle allocations for identical param maps.
        private final WeakHashMap<Map<String, Object>, Bundle> bundleCache = new WeakHashMap<>();

        FirebaseAnalyticsTracker(@NonNull Context appContext) {
            firebase = FirebaseAnalytics.getInstance(appContext);
        }

        @Override
        public void track(@NonNull String eventName,
                          @NonNull Map<String, Object> eventParams) {
            Bundle bundle = toBundle(eventParams);
            firebase.logEvent(eventName, bundle);
        }

        private Bundle toBundle(@NonNull Map<String, Object> params) {
            Bundle cached = bundleCache.get(params);
            if (cached != null) return cached;

            Bundle b = new Bundle(params.size());
            for (Map.Entry<String, Object> e : params.entrySet()) {
                String k = e.getKey();
                Object v = e.getValue();
                if (v instanceof String)      b.putString(k, (String) v);
                else if (v instanceof Integer) b.putInt(k, (Integer) v);
                else if (v instanceof Long)    b.putLong(k, (Long) v);
                else if (v instanceof Double)  b.putDouble(k, (Double) v);
                else if (v instanceof Float)   b.putFloat(k, (Float) v);
                else if (v instanceof Boolean) b.putBoolean(k, (Boolean) v);
            }
            bundleCache.put(params, b);
            return b;
        }
    }
    //endregion

    //region === Logcat Implementation ===
    /**
     * Simple tracker that dumps analytics events to Logcat—useful for debug
     * builds and automated tests.
     */
    private static final class LogcatAnalyticsTracker implements AnalyticsTracker {
        @Override
        public void track(@NonNull String eventName,
                          @NonNull Map<String, Object> eventParams) {
            if (eventParams.isEmpty()) {
                Log.d(TAG, "Analytics: " + eventName);
            } else {
                Log.d(TAG, "Analytics: " + eventName + " -> " + eventParams);
            }
        }
    }
    //endregion

    //region === Constants ===
    private static final String TAG = "AnalyticsEvents";
    //endregion
}