package com.sprintcart.domain.events;

import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Domain event that is raised whenever the stock level of a ProductVariant
 * crosses a pre-configured “critical” threshold.
 * <p>
 * The event is pure domain state and contains no infrastructure concerns.
 * Adapters interested in notifications (e.g. Kafka producers, email gateways,
 * automation scripts) will listen to this event and act accordingly.
 *
 * <p>Typical consumer actions:</p>
 * <ul>
 *     <li>Trigger automatic replenishment / purchase order creation</li>
 *     <li>Pause advertising campaigns for the SKU</li>
 *     <li>Notify warehouse managers or merchandisers</li>
 * </ul>
 *
 * This class is immutable and thread-safe.
 */
public final class StockLevelCriticalEvent implements DomainEvent, Serializable {

    @Serial
    private static final long serialVersionUID = 5821475962812644879L;

    /**
     * Unique identifier of this event instance. Useful when persisting to an
     * outbox table or de-duplicating in an event stream.
     */
    private final UUID eventId;

    /**
     * Timestamp (UTC) when the event occurred in the domain.
     */
    private final Instant occurredAt;

    /**
     * Business identifier of the product (aggregate root) whose stock level is critical.
     * We keep it as a String to allow flexible formats (numeric IDs, slugs, hashes, etc.).
     */
    private final String productId;

    /**
     * SKU / variant identifier within the product catalog.
     */
    private final String sku;

    /**
     * Optional warehouse or fulfillment node identifier.
     * Can be {@code null} when stock is tracked globally.
     */
    private final String warehouseId;

    /**
     * The current physical stock that triggered the event.
     */
    private final int currentStock;

    /**
     * The threshold value configured for this SKU. When {@code currentStock <= threshold},
     * the event is emitted.
     */
    private final int threshold;

    /**
     * Computed severity for convenience of downstream consumers.
     */
    private final Severity severity;

    private StockLevelCriticalEvent(Builder builder) {
        this.eventId = builder.eventId;
        this.occurredAt = builder.occurredAt;
        this.productId = builder.productId;
        this.sku = builder.sku;
        this.warehouseId = builder.warehouseId;
        this.currentStock = builder.currentStock;
        this.threshold = builder.threshold;
        this.severity = builder.severity;

        validateInvariants();
    }

    /* -----------------------------------------------------------------------
     * Factory helpers
     * -------------------------------------------------------------------- */

    /**
     * Creates an event instance from primitive values.
     */
    public static StockLevelCriticalEvent of(String productId,
                                             String sku,
                                             String warehouseId,
                                             int currentStock,
                                             int threshold) {

        return new Builder()
                .productId(productId)
                .sku(sku)
                .warehouseId(warehouseId)
                .currentStock(currentStock)
                .threshold(threshold)
                .build();
    }

    /**
     * Creates an event instance for globally tracked inventory (no warehouse).
     */
    public static StockLevelCriticalEvent of(String productId,
                                             String sku,
                                             int currentStock,
                                             int threshold) {
        return of(productId, sku, null, currentStock, threshold);
    }

    /* -----------------------------------------------------------------------
     * Getters (no setters – immutable)
     * -------------------------------------------------------------------- */

    @Override
    public UUID getEventId() {
        return eventId;
    }

    @Override
    public Instant getOccurredAt() {
        return occurredAt;
    }

    public String getProductId() {
        return productId;
    }

    public String getSku() {
        return sku;
    }

    public Optional<String> getWarehouseId() {
        return Optional.ofNullable(warehouseId);
    }

    public int getCurrentStock() {
        return currentStock;
    }

    public int getThreshold() {
        return threshold;
    }

    public Severity getSeverity() {
        return severity;
    }

    /* -----------------------------------------------------------------------
     * Business logic
     * -------------------------------------------------------------------- */

    private void validateInvariants() {
        Objects.requireNonNull(eventId, "eventId");
        Objects.requireNonNull(occurredAt, "occurredAt");
        Objects.requireNonNull(productId, "productId");
        Objects.requireNonNull(sku, "sku");

        if (threshold < 0) {
            throw new IllegalArgumentException("Threshold must be >= 0");
        }
        if (currentStock < 0) {
            throw new IllegalArgumentException("Current stock must be >= 0");
        }
        if (currentStock > threshold) {
            throw new IllegalStateException(
                    "Current stock (" + currentStock + ") must be <= threshold (" + threshold + ")");
        }
    }

    /* -----------------------------------------------------------------------
     * Technical helpers
     * -------------------------------------------------------------------- */

    /**
     * Converts the event into a stable, single-partition key used by most
     * event streams. We use the SKU by default because it is highly selective.
     */
    @Override
    public String partitionKey() {
        return sku;
    }

    @Override
    public String toString() {
        return "StockLevelCriticalEvent{" +
                "eventId=" + eventId +
                ", occurredAt=" + occurredAt +
                ", productId='" + productId + '\'' +
                ", sku='" + sku + '\'' +
                ", warehouseId='" + warehouseId + '\'' +
                ", currentStock=" + currentStock +
                ", threshold=" + threshold +
                ", severity=" + severity +
                '}';
    }

    @Override
    public int hashCode() {
        return Objects.hash(eventId);
    }

    @Override
    public boolean equals(Object obj) {
        return this == obj ||
                (obj instanceof StockLevelCriticalEvent other && Objects.equals(this.eventId, other.eventId));
    }

    /* -----------------------------------------------------------------------
     * Nested types
     * -------------------------------------------------------------------- */

    /**
     * Describes how critical the stock shortage is.
     */
    public enum Severity {
        /**
         * Stock is below threshold but still above zero.
         */
        LOW,
        /**
         * Stock dropped to exactly zero.
         */
        OUT_OF_STOCK,
        /**
         * The system detected negative stock (oversell situation).
         */
        OVERSELL
    }

    /**
     * Builder pattern to keep the constructor private and ensure invariants.
     * This simplifies usage from application services while keeping the domain
     * event immutable.
     */
    public static final class Builder {

        private UUID eventId = UUID.randomUUID();
        private Instant occurredAt = Instant.now();
        private String productId;
        private String sku;
        private String warehouseId;
        private int currentStock;
        private int threshold;
        private Severity severity;

        public Builder eventId(UUID eventId) {
            this.eventId = Objects.requireNonNull(eventId);
            return this;
        }

        public Builder occurredAt(Instant occurredAt) {
            this.occurredAt = Objects.requireNonNull(occurredAt);
            return this;
        }

        public Builder productId(String productId) {
            this.productId = productId;
            return this;
        }

        public Builder sku(String sku) {
            this.sku = sku;
            return this;
        }

        public Builder warehouseId(String warehouseId) {
            this.warehouseId = warehouseId;
            return this;
        }

        public Builder currentStock(int currentStock) {
            this.currentStock = currentStock;
            return this;
        }

        public Builder threshold(int threshold) {
            this.threshold = threshold;
            return this;
        }

        public Builder severity(Severity severity) {
            this.severity = severity;
            return this;
        }

        public StockLevelCriticalEvent build() {
            // Determine severity on the fly when not provided
            if (severity == null) {
                if (currentStock < 0) {
                    severity = Severity.OVERSELL;
                } else if (currentStock == 0) {
                    severity = Severity.OUT_OF_STOCK;
                } else {
                    severity = Severity.LOW;
                }
            }
            return new StockLevelCriticalEvent(this);
        }
    }
}

/**
 * Contract that all domain events must implement. This interface lives in the
 * domain layer to avoid any dependencies on specific messaging frameworks.
 */
interface DomainEvent {

    /**
     * Identifier used for de-duplication and traceability.
     */
    UUID getEventId();

    /**
     * When did the domain change occur?
     */
    Instant getOccurredAt();

    /**
     * Partitioning key to ensure event ordering for a given aggregate when
     * routing to a distributed log (e.g. Kafka, Pulsar).
     */
    String partitionKey();
}