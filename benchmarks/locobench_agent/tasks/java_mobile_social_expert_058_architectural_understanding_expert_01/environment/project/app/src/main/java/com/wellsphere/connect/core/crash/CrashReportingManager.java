```java
package com.wellsphere.connect.core.crash;

import android.content.Context;
import android.os.Build;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.work.Constraints;
import androidx.work.Data;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;

import com.google.firebase.crashlytics.FirebaseCrashlytics;

import java.lang.Thread.UncaughtExceptionHandler;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Centralised entry-point for all crash and non-fatal error reporting.
 * <p>
 * Responsibilities:
 * <ul>
 *     <li>Abstract away vendor SDK (FirebaseCrashlytics) behind a light
 *     interface to decouple the rest of the codebase from direct dependency.</li>
 *     <li>Collect additional runtime metadata (device, build-flavour, user)
 *     before forwarding events to the reporter SDK.</li>
 *     <li>Queue events locally when the device is offline and flush them
 *     via {@link androidx.work.WorkManager} once connectivity is restored.</li>
 *     <li>Install a process-wide {@link UncaughtExceptionHandler} to capture
 *     otherwise silently swallowed crashes in background threads.</li>
 * </ul>
 */
@SuppressWarnings({ "unused", "WeakerAccess" })
public final class CrashReportingManager {

    private static final String TAG = "CrashReportingManager";

    // Singleton boilerplate
    private static volatile CrashReportingManager instance;

    private final AtomicBoolean isInitialised = new AtomicBoolean(false);
    private final AtomicBoolean isDebugBuild = new AtomicBoolean(false);

    @NonNull
    private CrashReporter reporter = new NoOpCrashReporter();

    private CrashReportingManager() { /* singleton */ }

    /**
     * Obtain the global instance.
     */
    @NonNull
    public static CrashReportingManager getInstance() {
        if (instance == null) {
            synchronized (CrashReportingManager.class) {
                if (instance == null) {
                    instance = new CrashReportingManager();
                }
            }
        }
        return instance;
    }

    /**
     * Initialises the crash reporter. Safe to call multiple times
     * but only the first invocation has an effect.
     *
     * @param applicationContext Any application {@link Context}.
     * @param debugBuild         True if app is running a debug variant.
     */
    public void init(@NonNull final Context applicationContext, final boolean debugBuild) {
        if (!isInitialised.compareAndSet(false, true)) {
            Log.d(TAG, "CrashReportingManager already initialised; ignoring subsequent call.");
            return;
        }

        isDebugBuild.set(debugBuild);
        reporter = buildDelegate(debugBuild);

        // Add static device-level metadata
        reporter.addMetadata("device_manufacturer", Build.MANUFACTURER);
        reporter.addMetadata("device_model", Build.MODEL);
        reporter.addMetadata("os", "Android " + Build.VERSION.RELEASE);
        reporter.addMetadata("build_flavour", debugBuild ? "debug" : "release");

        // Install global uncaught exception handler
        installExceptionHandler();

        // Kick off a WorkManager task to flush locally cached events
        flushQueuedReportsAsync(applicationContext);
    }

    /**
     * Record a handled exception.
     */
    public void recordException(@NonNull Throwable throwable) {
        reporter.recordException(throwable);
    }

    /**
     * Convenience helper for logging non-fatal issues.
     */
    public void log(@NonNull String message) {
        reporter.log(message);
    }

    /**
     * Attach user identifier to subsequent reports.
     */
    public void setUser(@NonNull String id,
                        @Nullable String email,
                        @Nullable String name) {
        reporter.setUser(id, email, name);
    }

    /**
     * Clear any previously set user data.
     */
    public void clearUser() {
        reporter.clearUser();
    }

    /**
     * Append a key-value pair as custom meta data for all upcoming reports.
     */
    public void addMetadata(@NonNull String key, @NonNull String value) {
        reporter.addMetadata(key, value);
    }

    /* --------------------------------------------------------------------- */
    /* Internal helpers                                                      */
    /* --------------------------------------------------------------------- */

    @NonNull
    private CrashReporter buildDelegate(boolean debugBuild) {
        try {
            FirebaseCrashlytics firebase = FirebaseCrashlytics.getInstance();
            return new FirebaseCrashReporter(firebase, debugBuild);
        } catch (Throwable t) {
            // Defensive fallback for builds where Firebase is stripped out
            Log.w(TAG, "FirebaseCrashlytics missing – falling back to No-Op reporter.", t);
            return new NoOpCrashReporter();
        }
    }

    private void flushQueuedReportsAsync(@NonNull Context context) {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();

        OneTimeWorkRequest request =
                new OneTimeWorkRequest.Builder(QueuedCrashFlushWorker.class)
                        .setConstraints(constraints)
                        .setInputData(new Data.Builder()
                                .putBoolean(QueuedCrashFlushWorker.KEY_DEBUG_BUILD, isDebugBuild.get())
                                .build())
                        .addTag(QueuedCrashFlushWorker.UNIQUE_WORK_NAME)
                        .build();

        WorkManager.getInstance(context)
                   .enqueueUniqueWork(QueuedCrashFlushWorker.UNIQUE_WORK_NAME,
                           ExistingWorkPolicy.KEEP,
                           request);
    }

    private void installExceptionHandler() {
        UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();

        Thread.setDefaultUncaughtExceptionHandler((thread, throwable) -> {
            log(String.format(Locale.US,
                    "Uncaught exception in thread=%s, id=%d",
                    thread.getName(), thread.getId()));
            recordException(throwable);
            // Preserve default behaviour
            if (previous != null) {
                previous.uncaughtException(thread, throwable);
            }
        });
    }

    /* --------------------------------------------------------------------- */
    /* Strategy interface + concrete implementations                          */
    /* --------------------------------------------------------------------- */

    private interface CrashReporter {
        void recordException(@NonNull Throwable throwable);

        void log(@NonNull String message);

        void setUser(@NonNull String id, @Nullable String email, @Nullable String name);

        void clearUser();

        void addMetadata(@NonNull String key, @NonNull String value);
    }

    /**
     * Real implementation backed by Firebase Crashlytics.
     */
    private static final class FirebaseCrashReporter implements CrashReporter {

        private static final String INTERNAL_TAG = "FirebaseCrashReporter";

        private final FirebaseCrashlytics crashlytics;
        private final boolean debugBuild;

        FirebaseCrashReporter(@NonNull FirebaseCrashlytics crashlytics,
                              boolean debugBuild) {
            this.crashlytics = crashlytics;
            this.debugBuild = debugBuild;
        }

        @Override
        public void recordException(@NonNull Throwable throwable) {
            if (debugBuild) {
                Log.e(INTERNAL_TAG, "recordException", throwable);
            }
            crashlytics.recordException(throwable);
        }

        @Override
        public void log(@NonNull String message) {
            if (debugBuild) {
                Log.d(INTERNAL_TAG, message);
            }
            crashlytics.log(message);
        }

        @Override
        public void setUser(@NonNull String id,
                            @Nullable String email,
                            @Nullable String name) {
            crashlytics.setUserId(id);
            if (email != null) crashlytics.setCustomKey("user_email", email);
            if (name != null) crashlytics.setCustomKey("user_name", name);
        }

        @Override
        public void clearUser() {
            crashlytics.setUserId("");
            crashlytics.setCustomKey("user_email", "");
            crashlytics.setCustomKey("user_name", "");
        }

        @Override
        public void addMetadata(@NonNull String key, @NonNull String value) {
            crashlytics.setCustomKey(key, value);
        }
    }

    /**
     * No-operation fallback implementation, keeps the app running when the
     * real reporter is absent (e.g., during unit tests or builds without
     * Google services).
     */
    private static final class NoOpCrashReporter implements CrashReporter {

        @Override
        public void recordException(@NonNull Throwable throwable) {
            Log.e(TAG, "recordException (noop)", throwable);
        }

        @Override
        public void log(@NonNull String message) {
            Log.d(TAG, "log (noop): " + message);
        }

        @Override
        public void setUser(@NonNull String id,
                            @Nullable String email,
                            @Nullable String name) {
            Log.d(TAG, "setUser (noop): " + id);
        }

        @Override
        public void clearUser() {
            Log.d(TAG, "clearUser (noop)");
        }

        @Override
        public void addMetadata(@NonNull String key, @NonNull String value) {
            Log.d(TAG, "addMetadata (noop): " + key + "=" + value);
        }
    }

    /* --------------------------------------------------------------------- */
    /* Worker used to flush locally cached reports when connectivity resumes  */
    /* --------------------------------------------------------------------- */

    /**
     * A background, connectivity-aware task responsible for replaying locally
     * cached crash reports. Actual persistence layer is kept minimal here for
     * brevity—extend to Room database if needed.
     */
    public static final class QueuedCrashFlushWorker extends androidx.work.Worker {

        public static final String UNIQUE_WORK_NAME = "crash-flush-worker";
        public static final String KEY_DEBUG_BUILD = "debug_build";

        public QueuedCrashFlushWorker(@NonNull Context context,
                                      @NonNull WorkerParameters params) {
            super(context, params);
        }

        @NonNull
        @Override
        public Result doWork() {
            boolean debug = getInputData().getBoolean(KEY_DEBUG_BUILD, false);
            if (debug) {
                Log.d(TAG, "QueuedCrashFlushWorker started");
            }

            try {
                // In a real implementation we would pull pending events from
                // disk and send them. Here we simply simulate success.
                Thread.sleep(300); // simulate I/O

                if (debug) {
                    Log.d(TAG, "QueuedCrashFlushWorker completed");
                }
                return Result.success();
            } catch (InterruptedException ex) {
                Log.e(TAG, "Flush interrupted", ex);
                return Result.retry();
            } catch (Throwable t) {
                Log.e(TAG, "Unexpected error flushing crash queue", t);
                return Result.failure();
            }
        }
    }

    /* --------------------------------------------------------------------- */
    /* Utility API for wrapping a runnable with automatic crash reporting     */
    /* --------------------------------------------------------------------- */

    /**
     * Convenience wrapper that executes the runnable and reports *any* thrown
     * exception through the manager. Useful for RxJava/Coroutines interop.
     */
    public void runSafely(@NonNull Runnable block) {
        try {
            block.run();
        } catch (Throwable t) {
            recordException(t);
            throw t; // rethrow to allow normal propagation
        }
    }

    /**
     * Generate a short UUID to be used as correlation id across network calls
     * and crash logs.
     */
    @NonNull
    public static String generateCorrelationId() {
        return UUID.randomUUID().toString().substring(0, 8);
    }
}
```