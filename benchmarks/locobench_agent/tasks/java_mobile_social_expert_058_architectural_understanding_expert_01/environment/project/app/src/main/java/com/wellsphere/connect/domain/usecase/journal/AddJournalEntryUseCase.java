package com.wellsphere.connect.domain.usecase.journal;

import androidx.annotation.NonNull;

import com.wellsphere.connect.common.analytics.AnalyticsLogger;
import com.wellsphere.connect.common.concurrent.AppExecutors;
import com.wellsphere.connect.common.connectivity.NetworkStatusProvider;
import com.wellsphere.connect.common.error.AppError;
import com.wellsphere.connect.common.error.ValidationException;
import com.wellsphere.connect.domain.model.JournalEntry;
import com.wellsphere.connect.domain.repository.JournalRepository;
import com.wellsphere.connect.domain.sync.SyncScheduler;

import java.time.Clock;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;

/**
 * Use-case responsible for adding a {@link JournalEntry} to the local store and, if network
 * connectivity is available, immediately pushing it to the remote data-source.  When offline,
 * the entry is marked as <i>pending-sync</i> and {@link SyncScheduler} will replay the operation
 * once connectivity is restored.
 *
 * This class performs input validation, triggers analytics, and guarantees that execution
 * happens off the main thread by delegating to {@link AppExecutors#io()}.
 *
 * Thread-safety:  Immutable after construction, all mutable work is executed on single IO thread.
 */
public final class AddJournalEntryUseCase {

    private final JournalRepository journalRepository;
    private final NetworkStatusProvider networkStatusProvider;
    private final SyncScheduler syncScheduler;
    private final AnalyticsLogger analyticsLogger;
    private final AppExecutors executors;
    private final Clock clock;

    public AddJournalEntryUseCase(@NonNull JournalRepository journalRepository,
                                  @NonNull NetworkStatusProvider networkStatusProvider,
                                  @NonNull SyncScheduler syncScheduler,
                                  @NonNull AnalyticsLogger analyticsLogger,
                                  @NonNull AppExecutors executors,
                                  @NonNull Clock clock) {
        this.journalRepository = Objects.requireNonNull(journalRepository);
        this.networkStatusProvider = Objects.requireNonNull(networkStatusProvider);
        this.syncScheduler = Objects.requireNonNull(syncScheduler);
        this.analyticsLogger = Objects.requireNonNull(analyticsLogger);
        this.executors = Objects.requireNonNull(executors);
        this.clock = Objects.requireNonNull(clock);
    }

    /**
     * Adds a new {@link JournalEntry}—either remotely (if online) or locally (if offline).
     *
     * The returned {@link CompletableFuture} never blocks the caller’s thread.  Any exception
     * thrown during validation or persistence is propagated via
     * {@code CompletableFuture::exceptionally}.
     *
     * @param entry A fully-populated {@link JournalEntry} without an ID.
     * @return Future containing the persisted entry (with server-assigned ID if online), or
     *         a locally-generated placeholder ID when offline.
     */
    public CompletableFuture<JournalEntry> execute(@NonNull JournalEntry entry) {
        // Defensive copy so the caller cannot mutate after validation.
        final JournalEntry request = new JournalEntry(entry);

        return CompletableFuture.supplyAsync(() -> {

            validate(request);

            if (request.getId() == null) {
                // Generate a deterministic UUID so we can match with the server later.
                request.setId(UUID.randomUUID().toString());
            }

            boolean isOnline = networkStatusProvider.isConnected();

            JournalEntry persisted;
            if (isOnline) {
                persisted = journalRepository.addRemote(request);
            } else {
                persisted = journalRepository.addLocal(request, /* pendingSync = */ true);
                syncScheduler.scheduleOneShot();
            }

            logAnalytics(persisted, isOnline);

            return persisted;

        }, executors.io()).exceptionally(throwable -> {
            // Unwrap CompletionException for easier upstream handling.
            if (throwable instanceof CompletionException && throwable.getCause() != null) {
                throw new CompletionException(throwable.getCause());
            }
            throw new CompletionException(throwable);
        });
    }

    // -------------------------------------------------------------------------
    // Private helpers
    // -------------------------------------------------------------------------

    /**
     * Performs domain-level validation.  Callers should receive a {@link ValidationException}
     * when their input is semantically incorrect.
     */
    private void validate(@NonNull JournalEntry entry) {
        if (entry.getBody() == null || entry.getBody().trim().isEmpty()) {
            throw new ValidationException("Journal entry body must not be empty.");
        }

        if (entry.getCreatedAt() == null) {
            entry.setCreatedAt(Instant.now(clock));
        }

        Instant now = Instant.now(clock).plusSeconds(60); // Allow 1-minute clock drift.
        if (entry.getCreatedAt().isAfter(now)) {
            throw new ValidationException("Journal entry timestamp cannot be in the future.");
        }

        // Additional validation can be placed here (e.g., media attachment limits, etc.).
    }

    private void logAnalytics(@NonNull JournalEntry entry, boolean uploadedImmediately) {
        analyticsLogger.logEvent("journal_entry_added",
                AnalyticsLogger.Param.of("entry_id", entry.getId()),
                AnalyticsLogger.Param.of("online", uploadedImmediately),
                AnalyticsLogger.Param.of("has_media", !entry.getMediaAttachments().isEmpty()),
                AnalyticsLogger.Param.of("word_count", entry.getBody().split("\\s+").length));
    }

    // -------------------------------------------------------------------------
    // Error types
    // -------------------------------------------------------------------------

    /**
     * Generic application error wrapper used by the UI layer to display fault information.
     * In a larger project this would live in a shared module, but is nested here for clarity.
     */
    public static class AddEntryError extends AppError {
        public static final AddEntryError OFFLINE_QUEUE_FAILED =
                new AddEntryError("offline_queue_failed");
        public static final AddEntryError REMOTE_ADD_FAILED =
                new AddEntryError("remote_add_failed");

        private AddEntryError(String code) {
            super(code);
        }
    }
}