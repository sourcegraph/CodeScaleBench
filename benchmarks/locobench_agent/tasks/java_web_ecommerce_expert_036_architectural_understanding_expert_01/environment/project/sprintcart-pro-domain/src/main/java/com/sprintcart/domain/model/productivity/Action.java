package com.sprintcart.domain.model.productivity;

import java.io.Serializable;
import java.time.Instant;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * Action represents an atomic, side–effect-producing step that can be
 * chained in an automation rule. The entity is deliberately persistence-agnostic
 * and encapsulates validation and state-transition logic while remaining free of
 * infrastructure concerns (Hexagonal Architecture).
 *
 * Examples of Actions:
 *  • "pause_ad_campaign"
 *  • "reorder_inventory"
 *  • "send_low_stock_email"
 *
 * Domain Invariants:
 *  1. An Action is immutable once it reaches a terminal status (COMPLETED or FAILED).
 *  2. Only the creator or the automation engine may change the status.
 *  3. parameters is an immutable map (defensive copies are returned).
 *
 * Thread-safety: this class is effectively immutable except for status transitions
 * guarded via synchronization on the internal monitor.
 */
public final class Action implements Serializable {

    private static final long serialVersionUID = 5611790829478123819L;

    private final ActionId id;
    private final String name;
    private final Map<String, String> parameters;
    private volatile Status status;
    private final Instant createdAt;
    private volatile Instant updatedAt;
    private final int version;

    /**
     * Factory method to build a NEW action in PENDING status.
     */
    public static Action schedule(String name,
                                  Map<String, String> parameters) {
        return new Action(
            ActionId.random(),
            name,
            parameters,
            Status.PENDING,
            Instant.now(),
            Instant.now(),
            0
        );
    }

    /**
     * Reconstruct an Action from persisted storage.
     * This is intentionally package-private; repositories in the same package may call it.
     */
    static Action restore(ActionId id,
                          String name,
                          Map<String, String> parameters,
                          Status status,
                          Instant createdAt,
                          Instant updatedAt,
                          int version) {
        return new Action(id, name, parameters, status, createdAt, updatedAt, version);
    }

    private Action(ActionId id,
                   String name,
                   Map<String, String> parameters,
                   Status status,
                   Instant createdAt,
                   Instant updatedAt,
                   int version) {

        Objects.requireNonNull(id, "id must not be null");
        Objects.requireNonNull(name, "name must not be null");
        Objects.requireNonNull(parameters, "parameters must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
        Objects.requireNonNull(updatedAt, "updatedAt must not be null");

        this.id = id;
        this.name = sanitizeName(name);
        this.parameters = Collections.unmodifiableMap(parameters);
        this.status = status;
        this.createdAt = createdAt;
        this.updatedAt = updatedAt;
        this.version = version;

        validateState();
    }

    private static String sanitizeName(String rawName) {
        String trimmed = rawName.trim();
        if (trimmed.isEmpty()) {
            throw new IllegalArgumentException("Action name cannot be blank");
        }
        return trimmed.toLowerCase().replace(' ', '_');
    }

    /**
     * Business operation: mark this action as completed.
     * Returns new immutable instance with updated status.
     */
    public Action markCompleted() {
        synchronized (this) {
            ensureNotTerminal();
            return copyWith(Status.COMPLETED);
        }
    }

    /**
     * Business operation: mark this action as failed.
     * Returns new immutable instance with updated status.
     */
    public Action markFailed() {
        synchronized (this) {
            ensureNotTerminal();
            return copyWith(Status.FAILED);
        }
    }

    /**
     * Business operation: mark this action as in progress.
     * Returns new immutable instance with updated status.
     */
    public Action markInProgress() {
        synchronized (this) {
            ensureNotTerminal();
            if (status == Status.IN_PROGRESS) {
                return this; // idempotent
            }
            return copyWith(Status.IN_PROGRESS);
        }
    }

    private void ensureNotTerminal() {
        if (status.isTerminal()) {
            throw new IllegalStateException(
                "Action " + id + " already in terminal status: " + status);
        }
    }

    private Action copyWith(Status newStatus) {
        return new Action(
            this.id,
            this.name,
            this.parameters,
            newStatus,
            this.createdAt,
            Instant.now(),
            this.version + 1
        );
    }

    private void validateState() {
        if (status == Status.IN_PROGRESS && version == 0) {
            throw new IllegalStateException(
                "Cannot create a new Action in IN_PROGRESS status");
        }
    }

    /* ===================== Getters ===================== */

    public ActionId id() { return id; }

    public String name() { return name; }

    /**
     * @return an immutable copy of the parameter map
     */
    public Map<String, String> parameters() { return parameters; }

    public Status status() { return status; }

    public Instant createdAt() { return createdAt; }

    public Instant updatedAt() { return updatedAt; }

    public int version() { return version; }

    /* =================== Value Objects ================== */

    /**
     * Globally unique Action identifier.
     */
    public record ActionId(UUID value) implements Serializable {

        private static final long serialVersionUID = -2283946573428347231L;

        public ActionId {
            Objects.requireNonNull(value, "ActionId value cannot be null");
        }

        public static ActionId random() {
            return new ActionId(UUID.randomUUID());
        }

        @Override
        public String toString() {
            return value.toString();
        }
    }

    /**
     * Lifecycle of an Action.
     */
    public enum Status {
        PENDING(false),
        IN_PROGRESS(false),
        COMPLETED(true),
        FAILED(true);

        private final boolean terminal;

        Status(boolean terminal) {
            this.terminal = terminal;
        }

        public boolean isTerminal() {
            return terminal;
        }
    }

    /* ================ Equality & HashCode =============== */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Action other)) return false;
        return id.equals(other.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    /* ===================== toString ===================== */

    @Override
    public String toString() {
        return "Action{" +
               "id=" + id +
               ", name='" + name + '\'' +
               ", status=" + status +
               ", createdAt=" + createdAt +
               ", updatedAt=" + updatedAt +
               ", version=" + version +
               '}';
    }
}