```java
/*
 * Copyright (c) 2024.
 * WellSphere Health Inc. All rights reserved.
 *
 * This source code is proprietary and confidential. Redistribution
 * or modification without prior written permission of WellSphere
 * Health Inc. is strictly prohibited.
 */

package com.wellsphere.connect;

import android.app.Application;
import android.content.Context;
import android.os.StrictMode;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.work.Configuration;
import androidx.work.WorkManager;

import com.google.firebase.crashlytics.FirebaseCrashlytics;
import com.wellsphere.connect.analytics.Analytics;
import com.wellsphere.connect.auth.BiometricAuthManager;
import com.wellsphere.connect.di.AppComponent;
import com.wellsphere.connect.di.DaggerAppComponent;
import com.wellsphere.connect.location.LocationProvider;
import com.wellsphere.connect.sync.BackgroundSyncScheduler;

import java.lang.Thread.UncaughtExceptionHandler;
import java.util.concurrent.Executors;

/**
 * Root {@link Application}. Responsible for eagerly boot-strapping
 * singletons that are required across process restarts and must be
 * ready before any Activity or Service is displayed.
 *
 * The class implements {@link Configuration.Provider} to supply a
 * custom {@link WorkManager} configuration used for deterministic
 * offline sync essential in regulated healthcare scenarios.
 */
public class WellSphereApp extends Application implements Configuration.Provider {

    private static final String TAG = "WellSphereApp";

    /**
     * Process-wide {@link WellSphereApp} reference. Do NOT hold on to
     * Activity Contexts — leak-proofing is non-negotiable in HIPAA-aware
     * environments.
     */
    private static volatile WellSphereApp sInstance;

    private AppComponent appComponent;

    /**
     * Global uncaught exception handler that funnels unexpected crashes
     * through Crashlytics while preserving the default system handler.
     */
    private final UncaughtExceptionHandler crashReportingHandler =
            (thread, throwable) -> {
                FirebaseCrashlytics.getInstance().recordException(throwable);
                Log.e(TAG, "Uncaught exception on thread " + thread.getName(), throwable);
                // Delegate to default handler so that the system can still
                // show the crash dialog and generate tombstones.
                if (defaultExceptionHandler != null) {
                    defaultExceptionHandler.uncaughtException(thread, throwable);
                }
            };

    private UncaughtExceptionHandler defaultExceptionHandler;

    // ----------------------------------------------------------------------------
    // Application lifecycle
    // ----------------------------------------------------------------------------

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(base);
        sInstance = this;
    }

    @Override
    public void onCreate() {
        super.onCreate();

        // Activate strict-mode guards in debug builds.
        if (BuildConfig.DEBUG) {
            enableStrictMode();
        }

        // Initialize dependency injection graph.
        initDependencyGraph();

        // Setup global crash reporting.
        setupCrashReporting();

        // Initialize analytics pipeline.
        Analytics.initialize(this, BuildConfig.DEBUG);

        // Biometric auth initialization (keys, cipher, etc.).
        BiometricAuthManager.initialize(this);

        // Start WorkManager & background sync.
        WorkManager.initialize(this, getWorkManagerConfiguration());
        BackgroundSyncScheduler.schedulePeriodicSync(this);

        // Warm up location services so the first location lock is instant.
        LocationProvider.prefetchLastKnownLocation(this);

        Log.i(TAG, "WellSphereApp started. VersionCode=" + BuildConfig.VERSION_CODE);
    }

    // ----------------------------------------------------------------------------
    // WorkManager configuration
    // ----------------------------------------------------------------------------

    /**
     * Supply a custom {@link WorkManager} configuration. We use a single-threaded
     * executor to guarantee task ordering and to avoid over-loading low-end
     * devices — essential for predictable sync merging logic.
     */
    @NonNull
    @Override
    public Configuration getWorkManagerConfiguration() {
        return new Configuration.Builder()
                .setMinimumLoggingLevel(BuildConfig.DEBUG ? Log.VERBOSE : Log.INFO)
                .setExecutor(Executors.newSingleThreadExecutor())
                .build();
    }

    // ----------------------------------------------------------------------------
    // Public helpers
    // ----------------------------------------------------------------------------

    public static WellSphereApp get() {
        return sInstance;
    }

    public AppComponent appComponent() {
        return appComponent;
    }

    // ----------------------------------------------------------------------------
    // Internal helpers
    // ----------------------------------------------------------------------------

    private void initDependencyGraph() {
        appComponent = DaggerAppComponent.builder()
                .application(this)
                .build();
        appComponent.inject(this);
    }

    private void setupCrashReporting() {
        FirebaseCrashlytics crashlytics = FirebaseCrashlytics.getInstance();
        // Disable Crashlytics for local debug sessions to avoid noise.
        crashlytics.setCrashlyticsCollectionEnabled(!BuildConfig.DEBUG);

        defaultExceptionHandler = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler(crashReportingHandler);
    }

    private void enableStrictMode() {
        StrictMode.ThreadPolicy threadPolicy = new StrictMode.ThreadPolicy.Builder()
                .detectAll()
                .penaltyLog()
                .build();

        StrictMode.VmPolicy vmPolicy = new StrictMode.VmPolicy.Builder()
                .detectAll()
                .penaltyLog()
                .build();

        StrictMode.setThreadPolicy(threadPolicy);
        StrictMode.setVmPolicy(vmPolicy);
    }
}
```