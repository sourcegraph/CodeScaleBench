package com.opsforge.nexus.anonymizer.domain.port.out;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Stream;

/**
 * Outbound port responsible for persisting and retrieving audit information
 * related to data–anonymization jobs. <p>
 *
 * Implementations may forward the audit trail to any durable medium such as
 * relational/NoSQL databases, blob storage, log aggregation systems, or even
 * distributed tracing platforms. <p>
 *
 * The interface intentionally exposes asynchronous and streaming-friendly
 * operations so that adopters can implement non-blocking IO or reactive
 * pipelines without forcing the core domain to depend on specific frameworks. <p>
 *
 * All domain-specific exceptions are wrapped in {@link AuditPortException} in
 * order to keep the port technology-agnostic and avoid leaking lower-level
 * details (JDBC, HTTP, Kafka, etc.) into the domain.
 */
public interface AnonymizationAuditPort {

    /**
     * Persist a new {@link AnonymizationAuditEntry}. The method is expected to
     * be idempotent; i.e., multiple invocations with the same
     * {@code correlationId} <em>must not</em> create duplicate records.
     *
     * @param entry the audit entry to be stored (never {@code null})
     * @return a {@link CompletableFuture} that completes with the stored entry,
     *         potentially enriched with system-generated fields like database
     *         identifiers or timestamps.
     * @throws AuditPortException if the entry could not be persisted
     */
    CompletableFuture<AnonymizationAuditEntry> persist(AnonymizationAuditEntry entry)
            throws AuditPortException;

    /**
     * Retrieve a single audit record by its correlation UUID.
     *
     * @param correlationId unique identifier of the anonymization job
     * @return {@link Optional} containing the matching audit entry or empty if
     *         no record exists
     * @throws AuditPortException if the lookup fails
     */
    Optional<AnonymizationAuditEntry> fetchByCorrelationId(UUID correlationId)
            throws AuditPortException;

    /**
     * Stream audit records matching the supplied {@link AuditQuery}.
     *
     * @param query filtering & paging criteria (never {@code null})
     * @return lazy {@link Stream} of matching entries
     * @throws AuditPortException if the query fails
     */
    Stream<AnonymizationAuditEntry> stream(AuditQuery query) throws AuditPortException;

    /**
     * Remove all audit entries whose {@code occurredAt} timestamp precedes the
     * provided instant. Implementations should execute this method
     * transactionally and may do so in a best-effort / fire-and-forget manner.
     *
     * @param threshold cutoff instant; every record older than this instant
     *                  will be deleted
     * @throws AuditPortException if the deletion fails
     */
    void purgeOlderThan(Instant threshold) throws AuditPortException;

    // -------------------------------------------------------------------------
    // Helper types
    // -------------------------------------------------------------------------

    /**
     * Immutable specification for querying audit entries. Designed as a {@code
     * record} so that it can be instantiated concisely while remaining
     * serializable and hashable. A traditional builder is offered for improved
     * readability when dealing with many optional parameters.
     */
    record AuditQuery(
            UUID correlationId,
            String principal,
            AuditOutcome outcome,
            Instant occurredAfter,
            Instant occurredBefore,
            int page,
            int size
    ) {

        public static final int DEFAULT_PAGE = 0;
        public static final int DEFAULT_SIZE = 50;

        public static Builder builder() {
            return new Builder();
        }

        public static final class Builder {
            private UUID correlationId;
            private String principal;
            private AuditOutcome outcome;
            private Instant occurredAfter;
            private Instant occurredBefore;
            private int page = DEFAULT_PAGE;
            private int size = DEFAULT_SIZE;

            public Builder correlationId(UUID correlationId) {
                this.correlationId = correlationId;
                return this;
            }

            public Builder principal(String principal) {
                this.principal = principal;
                return this;
            }

            public Builder outcome(AuditOutcome outcome) {
                this.outcome = outcome;
                return this;
            }

            public Builder occurredAfter(Instant occurredAfter) {
                this.occurredAfter = occurredAfter;
                return this;
            }

            public Builder occurredBefore(Instant occurredBefore) {
                this.occurredBefore = occurredBefore;
                return this;
            }

            public Builder page(int page) {
                this.page = Math.max(page, 0);
                return this;
            }

            public Builder size(int size) {
                this.size = Math.max(size, 1);
                return this;
            }

            public AuditQuery build() {
                return new AuditQuery(
                        correlationId,
                        principal,
                        outcome,
                        occurredAfter,
                        occurredBefore,
                        page,
                        size
                );
            }
        }
    }

    /**
     * Enumeration describing whether a particular anonymization request was
     * handled successfully or failed with an error.
     */
    enum AuditOutcome {
        SUCCESS,
        FAILURE
    }

    /**
     * Domain exception thrown for any technical error encountered by an
     * {@link AnonymizationAuditPort} implementation. Allows the application
     * layer to decide whether to retry, escalate, or ignore the failure without
     * exposing the underlying infrastructure-specific exception hierarchy.
     */
    class AuditPortException extends Exception {
        public AuditPortException(String message) {
            super(message);
        }

        public AuditPortException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * Canonical audit entry describing a single anonymization event. The record
     * resides in the domain layer because it is required both by inbound
     * adapters (to create entries) and by outbound adapters (to persist them).
     */
    record AnonymizationAuditEntry(
            UUID correlationId,
            String principal,
            AuditOutcome outcome,
            String payloadPath,
            String anonymizationProfile,
            Instant occurredAt,
            String details
    ) {
        public AnonymizationAuditEntry {
            if (correlationId == null) {
                throw new IllegalArgumentException("correlationId must not be null");
            }
            if (principal == null || principal.isBlank()) {
                throw new IllegalArgumentException("principal must not be null or blank");
            }
            if (outcome == null) {
                throw new IllegalArgumentException("outcome must not be null");
            }
            if (occurredAt == null) {
                throw new IllegalArgumentException("occurredAt must not be null");
            }
        }
    }
}