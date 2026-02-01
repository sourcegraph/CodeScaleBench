package com.opsforge.nexus.fileconverter.domain.port.out;

import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Outbound port responsible for persisting and retrieving conversion–audit information.
 * <p>
 * Implementations are provided by infrastructure-level adapters (e.g. JPA, MongoDB,
 * Kafka-streams, Cloud Audit Log, etc.) and injected into application services
 * via dependency-injection.  No framework specific types are leaked into the
 * domain model to preserve portability and testability.
 */
public interface ConversionAuditPort {

    /**
     * Persists a new audit entry or updates an existing one if the identifier already exists.
     *
     * @param entry the immutable {@link AuditEntry} to persist
     * @return the identifier of the persisted audit entry
     * @throws AuditPersistenceException when the underlying data-store reports a failure
     */
    AuditEntryId save(AuditEntry entry) throws AuditPersistenceException;

    /**
     * Retrieves a previously stored audit entry.
     *
     * @param id the identifier of the audit entry
     * @return the audit entry, or {@link Optional#empty()} if it was not found
     */
    Optional<AuditEntry> fetchById(AuditEntryId id);

    /**
     * Retrieves audit entries that match the supplied {@link AuditFilter},
     * honoring the pagination constraints expressed by {@link PageRequest}.
     *
     * @param filter      filter criteria (nullable attributes are ignored)
     * @param pageRequest pagination request
     * @return an immutable page of {@link AuditEntry}s
     */
    Page<AuditEntry> fetchByFilter(AuditFilter filter, PageRequest pageRequest);

    /**
     * Physically removes all audit entries that are older than the supplied instant.
     *
     * @param threshold exclusive lower-bound; entries &lt; {@code threshold} are removed
     * @throws AuditPersistenceException when the purge operation fails
     */
    void purgeOlderThan(Instant threshold) throws AuditPersistenceException;

    /* ======================================================================================
     *                                Supporting Types
     * ====================================================================================== */

    /**
     * Strongly-typed identifier for audit entries.
     */
    record AuditEntryId(UUID value) {

        public AuditEntryId {
            Objects.requireNonNull(value, "value must not be null");
        }

        public static AuditEntryId random() {
            return new AuditEntryId(UUID.randomUUID());
        }

        @Override
        public String toString() {
            return value.toString();
        }
    }

    /**
     * Immutable value object representing a single conversion run.
     *
     * @param id            unique identifier (may be {@code null} for new entries)
     * @param requestedBy   human user or system principal that initiated the conversion
     * @param sourceFormat  input mime/type or extension (e.g. {@code text/csv})
     * @param targetFormat  output mime/type or extension (e.g. {@code application/pdf})
     * @param fileSizeBytes original file size in bytes
     * @param startedAt     timestamp when the conversion started
     * @param finishedAt    timestamp when the conversion finished (may be {@code null} if still running)
     * @param status        current state
     * @param errorCode     optional domain-specific error code
     * @param errorMessage  optional human-readable error message
     */
    record AuditEntry(
            AuditEntryId id,
            String requestedBy,
            String sourceFormat,
            String targetFormat,
            long fileSizeBytes,
            Instant startedAt,
            Instant finishedAt,
            Status status,
            String errorCode,
            String errorMessage) {

        public AuditEntry {
            Objects.requireNonNull(requestedBy, "requestedBy must not be null");
            Objects.requireNonNull(sourceFormat, "sourceFormat must not be null");
            Objects.requireNonNull(targetFormat, "targetFormat must not be null");
            Objects.requireNonNull(startedAt, "startedAt must not be null");
            Objects.requireNonNull(status, "status must not be null");
        }

        /**
         * Enumerates the lifecycle states of a conversion.
         */
        public enum Status {
            IN_PROGRESS,
            SUCCESS,
            FAILURE
        }
    }

    /**
     * Lightweight criteria bean used for querying the audit log.
     * <p>
     * Every attribute is optional; {@code null} values are ignored by adapters.
     */
    record AuditFilter(
            String requestedBy,
            String sourceFormat,
            String targetFormat,
            AuditEntry.Status status,
            Instant startedFrom,
            Instant startedTo) {
    }

    /**
     * Simple paginated result wrapper.
     *
     * @param <T> contents type
     */
    record Page<T>(List<T> content, long totalElements, int totalPages, int pageNumber, int pageSize) {

        public Page {
            Objects.requireNonNull(content, "content must not be null");
        }

        public static <T> Page<T> empty(PageRequest request) {
            return new Page<>(Collections.emptyList(), 0, 0, request.page(), request.size());
        }

        public boolean hasNext() {
            return pageNumber < totalPages - 1;
        }
    }

    /**
     * Immutable pagination request.
     *
     * @param page zero-based page index
     * @param size requested page size, must be &gt; 0
     */
    record PageRequest(int page, int size) {

        public PageRequest {
            if (page < 0) {
                throw new IllegalArgumentException("page index must be >= 0");
            }
            if (size <= 0) {
                throw new IllegalArgumentException("page size must be > 0");
            }
        }

        public int offset() {
            return page * size;
        }
    }

    /**
     * Marker exception indicating that persistence of an audit entry failed.
     * Keeping the type in the domain layer avoids leaking infrastructure-specific
     * exceptions (e.g. {@code SQLException}) into business logic.
     */
    class AuditPersistenceException extends Exception {
        public AuditPersistenceException(String message) {
            super(message);
        }

        public AuditPersistenceException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}