package com.sprintcart.domain.model.order;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

import java.util.Collections;
import java.util.EnumMap;
import java.util.EnumSet;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * OrderStatus models the lifecycle of an {@code Order} in SprintCart Pro.
 *
 * <p>The status map is intentionally opinionated but still generic enough to fit most
 * modern e-commerce flows:
 *
 * <pre>
 * DRAFT  -> PLACED       -> PAID            -> ALLOCATED  -> PACKED  -> SHIPPED -> DELIVERED
 *               \         /  \                    |                       |
 *                \_______/    \___________        |                       |
 *                  |                 |   \_______/                        |
 *                  |                 |        \______ RETURN_REQUESTED ___/
 *                  |                 |                        |          |
 *                  |                 |                   RETURNED     CANCELLED
 *                  |                 |                        |
 *                  |           PAYMENT_FAILED                 |
 *                  \_____________________________ REFUND_PENDING -> REFUNDED
 * </pre>
 *
 * <p>All transitions are validated through {@link #canTransitionTo(OrderStatus)}.
 * Domain services or aggregates must call {@link #assertTransition(OrderStatus)}
 * before mutating an order’s state.
 */
public enum OrderStatus {

    /* ----------------------
     *  Pre-payment statuses
     * ---------------------- */
    DRAFT(false),
    PLACED(false),
    PAYMENT_FAILED(false),

    /* ----------------------
     *  Payment & allocation
     * ---------------------- */
    PAID(false),
    ALLOCATED(false),
    PACKED(false),

    /* ----------------------
     *  Logistics
     * ---------------------- */
    SHIPPED(false),
    DELIVERED(true),

    /* ----------------------
     *  Cancellation / returns
     * ---------------------- */
    CANCELLED(true),
    RETURN_REQUESTED(false),
    RETURNED(false),
    REFUND_PENDING(false),
    REFUNDED(true);

    /** Fast lookup for {@link #fromString(String)}. */
    private static final Map<String, OrderStatus> LOOKUP_BY_VALUE = new EnumMap<>(OrderStatus.class);

    /** Allowed state transitions (source → destinations). */
    private static final Map<OrderStatus, Set<OrderStatus>> ALLOWED_TRANSITIONS =
            new EnumMap<>(OrderStatus.class);

    /** Indicates that no further transitions are expected for this status. */
    private final boolean terminal;

    static {
        /* -------------------------
         * Initialize value lookup
         * ------------------------- */
        for (OrderStatus status : values()) {
            LOOKUP_BY_VALUE.put(status.name(), status); // upper-case key
        }

        /* ------------------------------------------------
         * Allowed transition graph (immutably published)
         * ------------------------------------------------ */
        putTransitions(DRAFT,           PLACED, CANCELLED);
        putTransitions(PLACED,          PAID, PAYMENT_FAILED, CANCELLED);
        putTransitions(PAYMENT_FAILED,  PLACED, CANCELLED);
        putTransitions(PAID,            ALLOCATED, CANCELLED);
        putTransitions(ALLOCATED,       PACKED, CANCELLED);
        putTransitions(PACKED,          SHIPPED, CANCELLED);
        putTransitions(SHIPPED,         DELIVERED, RETURN_REQUESTED);
        putTransitions(DELIVERED,       RETURN_REQUESTED); // Post-delivery return
        putTransitions(RETURN_REQUESTED,RETURNED, REFUND_PENDING);
        putTransitions(RETURNED,        REFUND_PENDING);
        putTransitions(REFUND_PENDING,  REFUNDED);

        // Publish unmodifiable sets
        ALLOWED_TRANSITIONS.replaceAll((k, v) -> Collections.unmodifiableSet(v));
    }

    OrderStatus(boolean terminal) {
        this.terminal = terminal;
    }

    /* -------------------------------------------------------
     *  Public API
     * ------------------------------------------------------- */

    /**
     * Returns {@code true} if the current status is terminal (i.e., no further state
     * transitions are expected from a business perspective).
     */
    public boolean isTerminal() {
        return terminal;
    }

    /**
     * Indicates whether the order can transition from the current status to the
     * requested {@code target} status.
     *
     * @param target the desired next status
     * @return {@code true} when the transition is permitted; {@code false} otherwise
     */
    public boolean canTransitionTo(OrderStatus target) {
        Objects.requireNonNull(target, "target status must not be null");
        return ALLOWED_TRANSITIONS
                .getOrDefault(this, Collections.emptySet())
                .contains(target);
    }

    /**
     * Asserts that the transition from the current status to {@code target} is valid.
     * If the transition is invalid, a {@link TransitionNotAllowedException} is thrown.
     *
     * <p>Aggregates are expected to call this method to enforce the domain invariant
     * “orders may only transition through valid states”.
     *
     * @param target next desired status
     * @throws TransitionNotAllowedException when {@link #canTransitionTo(OrderStatus)} returns {@code false}
     */
    public void assertTransition(OrderStatus target) {
        if (!canTransitionTo(target)) {
            throw new TransitionNotAllowedException(
                    String.format("Cannot transition order from %s to %s", this, target));
        }
    }

    /* -------------------------------------------------------
     *  JSON serialization helpers
     * ------------------------------------------------------- */

    /**
     * Serializes the enum as its upper-case name (canonical form).
     */
    @JsonValue
    public String toJson() {
        return name();
    }

    /**
     * Case-insensitive factory for deserialization purposes.
     *
     * @param value raw text (e.g., from JSON)
     * @return matching {@code OrderStatus}
     * @throws IllegalArgumentException if the value is null or unknown
     */
    @JsonCreator
    public static OrderStatus fromString(String value) {
        if (value == null) {
            throw new IllegalArgumentException("OrderStatus value must not be null");
        }
        OrderStatus status = LOOKUP_BY_VALUE.get(value.trim().toUpperCase());
        if (status == null) {
            throw new IllegalArgumentException("Unknown OrderStatus: " + value);
        }
        return status;
    }

    /* -------------------------------------------------------
     *  Utility
     * ------------------------------------------------------- */

    private static void putTransitions(OrderStatus source, OrderStatus... targets) {
        ALLOWED_TRANSITIONS
                .computeIfAbsent(source, s -> EnumSet.noneOf(OrderStatus.class))
                .addAll(EnumSet.of(targets[0], targets));
    }

    /* -------------------------------------------------------
     *  Domain exception
     * ------------------------------------------------------- */

    /**
     * Thrown when an attempt is made to transition an order to an illegal state.
     */
    public static class TransitionNotAllowedException extends RuntimeException {
        public TransitionNotAllowedException(String message) {
            super(message);
        }
    }
}