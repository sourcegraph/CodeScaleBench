package com.wellsphere.connect.service.sync;

import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.wellsphere.connect.BuildConfig;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/**
 * SyncConflictResolver is responsible for deterministically resolving conflicts
 * that may arise during bi-directional synchronization between the local device
 * database (Room) and the cloud EHR.
 *
 * <p>This implementation supports the following strategies:</p>
 * <ul>
 *     <li>CLIENT_WINS – always prefer the local copy.</li>
 *     <li>SERVER_WINS – always prefer the remote copy.</li>
 *     <li>LAST_WRITE_WINS – deterministically pick the entity with the newest {@code updatedAt} timestamp.</li>
 *     <li>CUSTOM – delegate to an injectable {@link ConflictStrategy} implementation.</li>
 * </ul>
 *
 * The resolver is thread-safe and stateless. A singleton instance is exposed
 * via {@link #getInstance()} to reduce object churn during large batched syncs.
 *
 * NOTE: This class purposefully contains no Android-specific code beyond simple
 * logging; this keeps the core conflict logic easily unit-testable on the JVM.
 */
public final class SyncConflictResolver {

    private static final String TAG = "SyncConflictResolver";

    /**
     * The canonical singleton instance, lazily and thread-safely created.
     */
    private static volatile SyncConflictResolver instance;

    /**
     * Cache for custom strategies keyed by the entity's canonical class name.
     * This avoids repeated reflection or factory lookups during bulk syncs.
     */
    private final ConcurrentMap<String, ConflictStrategy<? extends SyncableEntity>> customStrategyCache
            = new ConcurrentHashMap<>();

    /**
     * Private constructor to enforce singleton usage.
     */
    private SyncConflictResolver() {
    }

    /**
     * Returns the singleton instance.
     *
     * @return An initialized, shared {@link SyncConflictResolver}.
     */
    public static SyncConflictResolver getInstance() {
        if (instance == null) {
            synchronized (SyncConflictResolver.class) {
                if (instance == null) {
                    instance = new SyncConflictResolver();
                }
            }
        }
        return instance;
    }

    /**
     * Resolves a pair of entities that represent the same logical record but
     * originate from different sources (local vs. remote).
     *
     * @param local   The entity stored on the device (may be {@code null} for pure inserts).
     * @param remote  The entity retrieved from the server (may be {@code null} for local-only data).
     * @param <T>     Concrete entity type implementing {@link SyncableEntity}.
     *
     * @return The authoritative version of the entity, or {@code null} if both are {@code null}.
     */
    @Nullable
    public <T extends SyncableEntity> T resolve(
            @Nullable T local,
            @Nullable T remote
    ) {
        return resolve(local, remote, ResolutionPolicy.LAST_WRITE_WINS, null);
    }

    /**
     * Resolves an entity pair using an explicit policy. A custom strategy may be
     * supplied for {@link ResolutionPolicy#CUSTOM}.
     *
     * @param local            Local copy.
     * @param remote           Remote copy.
     * @param policy           Resolution policy.
     * @param customStrategy   Strategy implementation for custom policy (may be {@code null} if not used).
     * @param <T>              Entity type.
     * @return                 Resolved entity or {@code null}.
     */
    @Nullable
    public <T extends SyncableEntity> T resolve(
            @Nullable T local,
            @Nullable T remote,
            @NonNull ResolutionPolicy policy,
            @Nullable ConflictStrategy<T> customStrategy
    ) {
        if (local == null && remote == null) {
            return null;
        }

        if (policy == ResolutionPolicy.CUSTOM && customStrategy == null) {
            // Provide clear developer feedback during staging.
            IllegalArgumentException ex = new IllegalArgumentException("Custom strategy required for CUSTOM policy.");
            captureError(ex);
            throw ex;
        }

        try {
            switch (policy) {
                case CLIENT_WINS:
                    return preferClient(local, remote);
                case SERVER_WINS:
                    return preferServer(local, remote);
                case LAST_WRITE_WINS:
                    return preferLastWrite(local, remote);
                case CUSTOM:
                    //noinspection unchecked
                    return customStrategy.resolve(local, remote);
                default:
                    // Should never happen; keep compiler happy.
                    return preferLastWrite(local, remote);
            }
        } catch (Exception e) {
            // Fail-safe: record the problem and default to SERVER_WINS to avoid data duplication.
            captureError(e);
            return preferServer(local, remote);
        }
    }

    /**
     * Resolves conflicts for a collection of entity pairs. Each pair is
     * represented by {@link ConflictPair}, which bundles the local and remote
     * copies of the same logical record.
     *
     * @param pairs  Collection of pairs.
     * @param <T>    Entity type.
     * @return       Authoritative list preserving input order.
     */
    @NonNull
    public <T extends SyncableEntity> List<T> resolveBatch(
            @NonNull Collection<ConflictPair<T>> pairs
    ) {
        if (pairs.isEmpty()) return Collections.emptyList();

        List<T> result = new ArrayList<>(pairs.size());
        for (ConflictPair<T> pair : pairs) {
            T resolved = resolve(pair.getLocal(), pair.getRemote());
            if (resolved != null) {
                result.add(resolved);
            }
        }
        return result;
    }

    // -------------------------------------------------------------------------
    // Strategy registration helpers
    // -------------------------------------------------------------------------

    /**
     * Registers a custom strategy for a specific entity class. Registered
     * strategies are reused across subsequent sync waves.
     *
     * @param entityClass     Entity's concrete class.
     * @param strategy        Strategy instance.
     * @param <T>             Entity type.
     */
    public <T extends SyncableEntity> void registerCustomStrategy(
            @NonNull Class<T> entityClass,
            @NonNull ConflictStrategy<T> strategy
    ) {
        Objects.requireNonNull(entityClass, "entityClass == null");
        Objects.requireNonNull(strategy, "strategy == null");

        customStrategyCache.put(entityClass.getCanonicalName(), strategy);
    }

    /**
     * Retrieves a previously registered custom strategy.
     *
     * @param entityClass   Entity class.
     * @param <T>           Entity type.
     * @return              Strategy or {@code null} if none registered.
     */
    @SuppressWarnings("unchecked")
    @Nullable
    public <T extends SyncableEntity> ConflictStrategy<T> getCustomStrategy(
            @NonNull Class<T> entityClass
    ) {
        Objects.requireNonNull(entityClass, "entityClass == null");
        return (ConflictStrategy<T>) customStrategyCache.get(entityClass.getCanonicalName());
    }

    // -------------------------------------------------------------------------
    // Default strategy implementations
    // -------------------------------------------------------------------------

    @Nullable
    private <T extends SyncableEntity> T preferClient(
            @Nullable T local,
            @Nullable T remote
    ) {
        // If local is soft-deleted, favour remote to avoid phantom records.
        return local != null && !local.isMarkedDeleted() ? local : remote;
    }

    @Nullable
    private <T extends SyncableEntity> T preferServer(
            @Nullable T local,
            @Nullable T remote
    ) {
        return remote != null ? remote : local;
    }

    @Nullable
    private <T extends SyncableEntity> T preferLastWrite(
            @Nullable T local,
            @Nullable T remote
    ) {
        if (local == null) return remote;
        if (remote == null) return local;

        Instant localTs  = local.getUpdatedAt();
        Instant remoteTs = remote.getUpdatedAt();

        if (remoteTs.isAfter(localTs)) {
            return remote;
        } else if (localTs.isAfter(remoteTs)) {
            return local;
        }

        // Same timestamp – fall back to revision number.
        return remote.getRevision() > local.getRevision() ? remote : local;
    }

    // -------------------------------------------------------------------------
    // Diagnostics helpers
    // -------------------------------------------------------------------------

    /**
     * Captures any unexpected throwable; during development we simply log, but
     * in production we forward to the global crash reporter.
     */
    private void captureError(@NonNull Throwable t) {
        if (BuildConfig.DEBUG) {
            Log.e(TAG, "Conflict resolution error", t);
        } else {
            // In production, forward to Firebase Crashlytics / Sentry.
            // CrashReporting.logException(t);
        }
    }

    // -------------------------------------------------------------------------
    // Nested helper types
    // -------------------------------------------------------------------------

    /**
     * Strategy abstraction for entity-specific conflict resolution.
     */
    public interface ConflictStrategy<T extends SyncableEntity> {

        /**
         * Resolves two versions of an entity and returns the authoritative copy.
         *
         * @param local   Local entity (may be {@code null}).
         * @param remote  Remote entity (may be {@code null}).
         * @return        Resolved entity (may be {@code null} if both inputs are {@code null}).
         */
        @Nullable
        T resolve(@Nullable T local, @Nullable T remote);
    }

    /**
     * Resolution policies available out-of-the-box.
     */
    public enum ResolutionPolicy {
        CLIENT_WINS,
        SERVER_WINS,
        LAST_WRITE_WINS,
        CUSTOM
    }

    /**
     * Simple wrapper to transport a local/remote pair.
     *
     * @param <T> Entity type.
     */
    public static final class ConflictPair<T extends SyncableEntity> {
        @Nullable private final T local;
        @Nullable private final T remote;

        public ConflictPair(@Nullable T local, @Nullable T remote) {
            this.local = local;
            this.remote = remote;
        }

        @Nullable
        public T getLocal() { return local; }

        @Nullable
        public T getRemote() { return remote; }
    }

    // -------------------------------------------------------------------------
    // Minimal contract for entities that can be synced.
    // (In production this would live in its own file.)
    // -------------------------------------------------------------------------

    public interface SyncableEntity {

        /**
         * Returns the server-issued revision number. Monotonically increasing.
         */
        long getRevision();

        /**
         * Returns the instant when the entity was last mutated on its origin database.
         */
        @NonNull
        Instant getUpdatedAt();

        /**
         * Indicates a soft delete. Soft-deleted records may be retained remotely
         * for audit purposes but hidden from user UI.
         */
        boolean isMarkedDeleted();
    }
}