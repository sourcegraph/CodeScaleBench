package com.commercesphere.enterprise.core.auditing;

import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;

/**
 * Auditable is a marker interface that equips persistence entities
 * with strongly-typed audit metadata (timestamps and principals).
 * <p>
 * The interface provides a small set of mutator helpers that can
 * be invoked by higher-level infrastructure components (for example,
 * Spring Data’s {@code AuditingEntityListener}) or by application
 * services that manage aggregate roots manually.
 *
 * <pre>{@code
 *  public class Product implements Auditable<Long> {
 *      private Instant createdAt;
 *      private Instant lastModifiedAt;
 *      private Long    createdBy;
 *      private Long    lastModifiedBy;
 *      private Long    id;
 *
 *      // getters/setters omitted
 *  }
 * }</pre>
 *
 * @param <U> the type used to represent the acting principal, usually
 *            the primary key of the User entity or a technical client id.
 */
public interface Auditable<U extends Serializable> {

    /* ---------------------------------------------------------------------
     * Getter/Setter contract
     * ------------------------------------------------------------------- */

    Instant getCreatedAt();
    void    setCreatedAt(Instant createdAt);

    Instant getLastModifiedAt();
    void    setLastModifiedAt(Instant lastModifiedAt);

    U       getCreatedBy();
    void    setCreatedBy(U createdBy);

    U       getLastModifiedBy();
    void    setLastModifiedBy(U lastModifiedBy);

    /**
     * Implementations must indicate if they have never been persisted.
     * This is used by the default helpers to decide between
     * {@code create} vs {@code update} semantics.
     */
    boolean isNew();

    /* ---------------------------------------------------------------------
     * Default infrastructure helpers
     * ------------------------------------------------------------------- */

    /**
     * Populates both {@code created} and {@code lastModified} attributes
     * if they have not been set yet.
     *
     * @param actor user or system principal responsible for the operation
     */
    default void touchForCreate(U actor) {
        if (!isNew()) {
            throw new AuditException(
                "touchForCreate() was called on an entity that is not new: " + this);
        }

        Instant now = Instant.now();
        if (getCreatedAt() == null) {
            setCreatedAt(now);
        }
        if (getLastModifiedAt() == null) {
            setLastModifiedAt(now);
        }
        if (getCreatedBy() == null) {
            setCreatedBy(actor);
        }
        if (getLastModifiedBy() == null) {
            setLastModifiedBy(actor);
        }
    }

    /**
     * Updates the {@code lastModified} audit attributes.
     *
     * @param actor user or system principal responsible for the operation
     */
    default void touchForUpdate(U actor) {
        if (isNew()) {
            throw new AuditException(
                "touchForUpdate() was called on an entity that is new: " + this);
        }

        setLastModifiedAt(Instant.now());
        setLastModifiedBy(actor);
    }

    /**
     * Indicates whether the entity was modified after creation.
     */
    default boolean hasBeenModified() {
        return !Objects.equals(getCreatedAt(), getLastModifiedAt()) ||
               !Objects.equals(getCreatedBy(),  getLastModifiedBy());
    }

    /**
     * Convenience method to build an immutable snapshot to expose
     * over REST or WebSocket boundaries without leaking internal setters.
     */
    default AuditStamp<U> toAuditStamp() {
        return new AuditStamp<>(
            getCreatedAt(),
            getCreatedBy(),
            getLastModifiedAt(),
            getLastModifiedBy()
        );
    }

    /* ---------------------------------------------------------------------
     * Helper value objects
     * ------------------------------------------------------------------- */

    /**
     * Immutable value object capturing creation and last-modification
     * metadata in a single place.
     */
    final class AuditStamp<U extends Serializable> implements Serializable {

        private static final long serialVersionUID = 1L;

        private final Instant createdAt;
        private final U       createdBy;
        private final Instant lastModifiedAt;
        private final U       lastModifiedBy;

        private AuditStamp(Instant createdAt,
                           U createdBy,
                           Instant lastModifiedAt,
                           U lastModifiedBy) {

            this.createdAt       = Objects.requireNonNull(createdAt, "createdAt");
            this.createdBy       = createdBy;
            this.lastModifiedAt  = Objects.requireNonNull(lastModifiedAt, "lastModifiedAt");
            this.lastModifiedBy  = lastModifiedBy;
        }

        public Instant getCreatedAt() {
            return createdAt;
        }

        public Optional<U> getCreatedBy() {
            return Optional.ofNullable(createdBy);
        }

        public Instant getLastModifiedAt() {
            return lastModifiedAt;
        }

        public Optional<U> getLastModifiedBy() {
            return Optional.ofNullable(lastModifiedBy);
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof AuditStamp)) return false;
            AuditStamp<?> that = (AuditStamp<?>) o;
            return createdAt.equals(that.createdAt) &&
                   Objects.equals(createdBy, that.createdBy) &&
                   lastModifiedAt.equals(that.lastModifiedAt) &&
                   Objects.equals(lastModifiedBy, that.lastModifiedBy);
        }

        @Override
        public int hashCode() {
            return Objects.hash(createdAt, createdBy, lastModifiedAt, lastModifiedBy);
        }

        @Override
        public String toString() {
            return "AuditStamp{" +
                "createdAt=" + createdAt +
                ", createdBy=" + createdBy +
                ", lastModifiedAt=" + lastModifiedAt +
                ", lastModifiedBy=" + lastModifiedBy +
                '}';
        }
    }
}

/* -------------------------------------------------------------------------
 * Auxiliary types
 * ----------------------------------------------------------------------- */

/**
 * Thrown in case audit metadata cannot be populated or violates
 * the integrity constraints defined by {@link Auditable}.
 */
class AuditException extends RuntimeException {

    private static final long serialVersionUID = 42L;

    AuditException(String message) {
        super(message);
    }

    AuditException(String message, Throwable cause) {
        super(message, cause);
    }
}