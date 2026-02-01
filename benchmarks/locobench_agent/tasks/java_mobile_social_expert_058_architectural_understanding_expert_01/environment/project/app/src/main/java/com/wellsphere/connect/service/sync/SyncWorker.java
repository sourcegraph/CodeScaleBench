```java
package com.wellsphere.connect.service.sync;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;

import androidx.annotation.NonNull;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import com.wellsphere.connect.core.analytics.CrashReporter;
import com.wellsphere.connect.core.auth.SessionManager;
import com.wellsphere.connect.core.storage.EncryptedPrefs;
import com.wellsphere.connect.core.util.NetworkUtil;
import com.wellsphere.connect.service.sync.engine.MergeConflictException;
import com.wellsphere.connect.service.sync.engine.SyncEngine;
import com.wellsphere.connect.service.sync.engine.SyncException;
import com.wellsphere.connect.service.sync.repository.OfflineRecordRepository;
import com.wellsphere.connect.service.sync.repository.SyncMetadataRepository;

import java.util.concurrent.TimeUnit;

/**
 * SyncWorker is responsible for pushing locally queued data (vitals, images, posts, etc.)
 * to the WellSphere cloud and pulling down remote changes.  The worker is idempotent,
 * resumable, and network-aware.  It is the single entry-point for any background sync.
 *
 * The worker is executed by the androidx.work.WorkManager according to a set of sensible
 * constraints and retry policies.  All exceptions are carefully mapped to
 * {@link Result} values so callers know whether to retry, fail, or mark success.
 */
public class SyncWorker extends Worker {

    /* **********************  CONSTANTS  ************************* */

    /**
     * Unique name for the periodic work so that the WorkManager replaces duplicates.
     */
    public static final String WORK_NAME_PERIODIC = "com.wellsphere.connect.SYNC_PERIODIC";

    /**
     * Tag attached to all sync requests for easier diagnostics and cancellation.
     */
    public static final String WORK_TAG_SYNC = "TAG_SYNC_WORK";

    /**
     * Maximum back-off time in case of repeated transient errors.
     */
    private static final int MAX_BACKOFF_MINUTES = 30;

    /* **********************  MEMBERS  *************************** */

    private final SyncEngine                syncEngine;
    private final OfflineRecordRepository   offlineRepository;
    private final SyncMetadataRepository    metadataRepository;
    private final SessionManager            sessionManager;
    private final CrashReporter             crashReporter;

    /* **********************  CONSTRUCTOR  *********************** */

    public SyncWorker(@NonNull Context appContext, @NonNull WorkerParameters params) {
        super(appContext, params);

        /*
         * In production the dependencies would be provided through a DI
         * framework (e.g. Hilt).  For brevity, we fall back to service
         * locators / singleton instances.
         */
        this.syncEngine          = SyncEngine.getInstance(appContext);
        this.offlineRepository   = OfflineRecordRepository.getInstance(appContext);
        this.metadataRepository  = SyncMetadataRepository.getInstance(appContext);
        this.sessionManager      = SessionManager.getInstance(appContext);
        this.crashReporter       = CrashReporter.getInstance();
    }

    /* **********************  WORK EXECUTION  ******************** */

    @NonNull
    @Override
    public Result doWork() {
        // 1. Abort early if user is not authenticated.
        if (!sessionManager.isUserAuthenticated()) {
            return Result.failure();
        }

        // 2. Verify that we still have connectivity. WorkManager handles
        //    most of this but we double-check to fail fast.
        if (!NetworkUtil.isConnected(getApplicationContext())) {
            return Result.retry();
        }

        try {
            // 3. Perform the actual sync.
            performSync();

            // 4. Success is reported only if both push/pull completed
            //    without any exception.
            return Result.success();

        } catch (MergeConflictException conflict) {
            /*
             * Merge conflicts should NEVER crash the app.  They are business
             * errors that need user attention.  We mark the work as successful
             * so that WorkManager does not retry automatically, but we
             * generate a notification so the user can resolve the problem.
             */
            conflict.printStackTrace();
            crashReporter.logNonFatal(conflict);
            notifyMergeConflict();
            return Result.success();

        } catch (SyncException | IllegalStateException recoverable) {
            /*
             * Expected transient failures: network blips, 5xx, JSON parse,
             * encryption key rotations, etc.  Ask WorkManager to retry with
             * exponential back-off.
             */
            recoverable.printStackTrace();
            crashReporter.logNonFatal(recoverable);
            return Result.retry();

        } catch (Exception nasty) {
            /*
             * Unknown fatal errors: out-of-memory, database corruption, etc.
             * We let WorkManager know that this work FAILED so it will stop
             * retrying.  Crashlytics et al. will receive the stacktrace via
             * CrashReporter.
             */
            nasty.printStackTrace();
            crashReporter.log(nasty);
            return Result.failure();
        }
    }

    /**
     * Executes the three-phase sync transaction:
     *   1) Push local pending changes
     *   2) Pull remote changes
     *   3) Update sync metadata
     *
     * The method is isolated mainly for testability.
     */
    private void performSync() throws SyncException, MergeConflictException {
        /* === phase 1: PUSH === */
        syncEngine.pushPending(offlineRepository.fetchPendingRecords());

        /* === phase 2: PULL === */
        syncEngine.pullUpdates(metadataRepository.getLastSyncToken());

        /* === phase 3: COMMIT === */
        metadataRepository.setLastSyncTimestamp(System.currentTimeMillis());
    }

    /* **********************  PUBLIC API  ************************ */

    /**
     * Immediately enqueue a one-off sync.  This is used after the user
     * creates new data while online, or when the user manually pulls-to-refresh.
     */
    public static void enqueueOneOffSync(@NonNull Context context) {
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(SyncWorker.class)
                .addTag(WORK_TAG_SYNC)
                .setBackoffCriteria(
                        BackoffPolicy.EXPONENTIAL,
                        WorkManager.MIN_BACKOFF_MILLIS,
                        TimeUnit.MILLISECONDS)
                .setConstraints(defaultConstraints())
                .build();

        WorkManager
                .getInstance(context)
                .enqueue(request);
    }

    /**
     * Schedule (or replace) the periodic background sync.  Called once on
     * login and whenever the user toggles sync preferences.
     */
    public static void schedulePeriodicSync(@NonNull Context context, long repeatIntervalMinutes) {
        PeriodicWorkRequest periodicWork = new PeriodicWorkRequest.Builder(
                        SyncWorker.class,
                        repeatIntervalMinutes,
                        TimeUnit.MINUTES)
                .addTag(WORK_TAG_SYNC)
                .setBackoffCriteria(
                        BackoffPolicy.EXPONENTIAL,
                        WorkManager.MIN_BACKOFF_MILLIS,
                        TimeUnit.MILLISECONDS)
                .setConstraints(defaultConstraints())
                .build();

        WorkManager
                .getInstance(context)
                .enqueueUniquePeriodicWork(
                        WORK_NAME_PERIODIC,
                        ExistingPeriodicWorkPolicy.UPDATE,
                        periodicWork);
    }

    /**
     * Cancels all scheduled or running sync jobs.  This is typically invoked
     * on logout or when the user revokes permissions.
     */
    public static void cancelAllSync(@NonNull Context context) {
        WorkManager.getInstance(context).cancelAllWorkByTag(WORK_TAG_SYNC);
    }

    /* **********************  HELPERS  *************************** */

    private static Constraints defaultConstraints() {
        return new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .setRequiresBatteryNotLow(true)       // don't kill battery
                .setRequiresStorageNotLow(true)       // need room for media tmp files
                .build();
    }

    /**
     * Sends a high-priority notification prompting the user to resolve merge
     * conflicts.  Implementation omitted for brevity.
     */
    private void notifyMergeConflict() {
        // TODO: Implement notification with deep-link to in-app conflict UI
    }
}

/* ********************************************************************
 *  Below are minimal placeholder classes and utilities so that this
 *  single file compiles independently.  In production they live in
 *  proper modules/packages and are fully featured.
 * ******************************************************************** */

/* -------- core/util/NetworkUtil ------------------------------------------------ */
class NetworkUtil {
    static boolean isConnected(Context ctx) {
        ConnectivityManager cm = (ConnectivityManager) ctx.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return false;
        NetworkInfo info = cm.getActiveNetworkInfo();
        return info != null && info.isConnected();
    }
}

/* -------- core/analytics/CrashReporter ---------------------------------------- */
class CrashReporter {
    private static volatile CrashReporter sInstance;

    static CrashReporter getInstance() {
        if (sInstance == null) sInstance = new CrashReporter();
        return sInstance;
    }

    void log(Throwable t) { /* send to crashlytics */ }

    void logNonFatal(Throwable t) { /* send non-fatal */ }
}

/* -------- core/auth/SessionManager -------------------------------------------- */
class SessionManager {
    private static volatile SessionManager sInstance;
    private final EncryptedPrefs prefs = EncryptedPrefs.getInstance();

    static SessionManager getInstance(Context ctx) {
        if (sInstance == null) sInstance = new SessionManager();
        return sInstance;
    }
    boolean isUserAuthenticated() { return prefs.getBoolean("auth", false); }
}

/* -------- core/storage/EncryptedPrefs ----------------------------------------- */
class EncryptedPrefs {
    private static volatile EncryptedPrefs sInstance;
    static EncryptedPrefs getInstance() { if (sInstance == null) sInstance = new EncryptedPrefs(); return sInstance; }
    boolean getBoolean(String k, boolean d) { return d; }
}

/* -------- service/sync/repository/OfflineRecordRepository ---------------------- */
class OfflineRecordRepository {
    static OfflineRecordRepository getInstance(Context ctx) { return new OfflineRecordRepository(); }
    java.util.List<String> fetchPendingRecords() { return java.util.Collections.emptyList(); }
}

/* -------- service/sync/repository/SyncMetadataRepository ----------------------- */
class SyncMetadataRepository {
    private long lastToken = 0;
    static SyncMetadataRepository getInstance(Context ctx) { return new SyncMetadataRepository(); }
    long getLastSyncToken() { return lastToken; }
    void setLastSyncTimestamp(long ts) { lastToken = ts; }
}

/* -------- service/sync/engine/SyncEngine -------------------------------------- */
class SyncEngine {
    private static volatile SyncEngine sInstance;
    static SyncEngine getInstance(Context ctx) { if (sInstance == null) sInstance = new SyncEngine(); return sInstance; }

    void pushPending(java.util.List<String> records) throws SyncException { /* push */ }

    void pullUpdates(long lastToken) throws SyncException, MergeConflictException { /* pull */ }
}

/* -------- service/sync/engine custom exceptions ------------------------------- */
class SyncException extends Exception {
    SyncException() { super(); }
    SyncException(String m) { super(m); }
}
class MergeConflictException extends Exception {
    MergeConflictException() { super(); }
    MergeConflictException(String m) { super(m); }
}
```