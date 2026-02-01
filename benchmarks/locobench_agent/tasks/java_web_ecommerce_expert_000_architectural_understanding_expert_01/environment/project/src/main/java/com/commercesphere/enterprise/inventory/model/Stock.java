package com.commercesphere.enterprise.inventory.model;

import javax.persistence.*;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotNull;
import java.io.Serializable;
import java.time.ZonedDateTime;
import java.util.Objects;

/**
 * Stock entity representing inventory levels for a specific SKU in a given warehouse.
 *
 * <p>Concurrency is handled using optimistic locking via {@link #version}. All state-mutating
 * methods are synchronized to protect against intra-JVM races when the entity is attached to an
 * extended persistence context (e.g. in long-running Vaadin or WebSocket sessions).</p>
 *
 * <p>Business invariants:
 * <ul>
 *     <li>onHand ≥ 0</li>
 *     <li>reserved ≥ 0</li>
 *     <li>reserved ≤ onHand</li>
 *     <li>available = onHand − reserved</li>
 * </ul>
 * </p>
 */
@Entity
@Table(
        name = "cs_stock",
        uniqueConstraints = @UniqueConstraint(
                name = "uq_stock_warehouse_sku",
                columnNames = {"warehouse_id", "sku"})
)
public class Stock implements Serializable {

    private static final long serialVersionUID = 5134523432542345480L;

    // -------------------------------------------------------------------------
    // Primary & Business Keys
    // -------------------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Logical warehouse identifier (UUID stored as String for portability).
     */
    @NotNull
    @Column(name = "warehouse_id", nullable = false, updatable = false, length = 36)
    private String warehouseId;

    /**
     * Stock Keeping Unit uniquely identifying the product variant.
     */
    @NotNull
    @Column(name = "sku", nullable = false, updatable = false, length = 64)
    private String sku;

    // -------------------------------------------------------------------------
    // Quantities
    // -------------------------------------------------------------------------

    @Min(0)
    @Column(name = "on_hand", nullable = false)
    private int onHand = 0;

    @Min(0)
    @Column(name = "reserved", nullable = false)
    private int reserved = 0;

    @Min(0)
    @Column(name = "reorder_threshold", nullable = false)
    private int reorderThreshold = 0;

    // -------------------------------------------------------------------------
    // Auditing / Concurrency
    // -------------------------------------------------------------------------

    @Column(name = "last_modified_utc", nullable = false)
    private ZonedDateTime lastModifiedUtc;

    /**
     * Optimistic-locking column automatically incremented by JPA provider.
     */
    @Version
    @Column(name = "version", nullable = false)
    private long version;

    // -------------------------------------------------------------------------
    // Constructors & Builders
    // -------------------------------------------------------------------------

    protected Stock() {
        /* For JPA */
    }

    private Stock(Builder builder) {
        this.warehouseId       = builder.warehouseId;
        this.sku               = builder.sku;
        this.onHand            = builder.onHand;
        this.reserved          = builder.reserved;
        this.reorderThreshold  = builder.reorderThreshold;
        this.lastModifiedUtc   = ZonedDateTime.now();
        invariantHolds();
    }

    /**
     * Creates a new {@link Builder} for {@link Stock}.
     */
    public static Builder builder(String warehouseId, String sku) {
        return new Builder(warehouseId, sku);
    }

    /**
     * Builder implementing a staged builder pattern where warehouseId & sku are mandatory.
     */
    public static final class Builder {
        private final String warehouseId;
        private final String sku;
        private int onHand          = 0;
        private int reserved        = 0;
        private int reorderThreshold = 0;

        private Builder(String warehouseId, String sku) {
            this.warehouseId = Objects.requireNonNull(warehouseId, "warehouseId must not be null");
            this.sku         = Objects.requireNonNull(sku, "sku must not be null");
        }

        public Builder onHand(int onHand) {
            this.onHand = onHand;
            return this;
        }

        public Builder reserved(int reserved) {
            this.reserved = reserved;
            return this;
        }

        public Builder reorderThreshold(int threshold) {
            this.reorderThreshold = threshold;
            return this;
        }

        public Stock build() {
            return new Stock(this);
        }
    }

    // -------------------------------------------------------------------------
    // Entity Callbacks
    // -------------------------------------------------------------------------

    @PrePersist
    @PreUpdate
    private void touch() {
        lastModifiedUtc = ZonedDateTime.now();
        invariantHolds();
    }

    // -------------------------------------------------------------------------
    // Derived Columns
    // -------------------------------------------------------------------------

    /**
     * Computed value, not stored in DB.
     */
    @Transient
    public int getAvailable() {
        return onHand - reserved;
    }

    // -------------------------------------------------------------------------
    // Business Logic
    // -------------------------------------------------------------------------

    /**
     * Adds additional stock to the warehouse.
     *
     * @throws IllegalArgumentException if {@code quantity} is negative
     */
    public synchronized void increaseOnHand(int quantity) {
        validateNonNegative(quantity);
        onHand = Math.addExact(onHand, quantity); // protects from integer overflow
    }

    /**
     * Removes stock from "on hand" pool. Caller should ensure business meaning
     * (shipping, shrinkage, etc.)
     *
     * @throws IllegalArgumentException  if {@code quantity} is negative
     * @throws InsufficientStockException if insufficient on-hand quantity
     */
    public synchronized void decreaseOnHand(int quantity) {
        validateNonNegative(quantity);
        if (quantity > onHand) {
            throw new InsufficientStockException(
                    String.format("Cannot remove %d items; only %d on hand for %s/%s",
                            quantity, onHand, warehouseId, sku));
        }
        onHand -= quantity;
    }

    /**
     * Reserves available stock for an order.
     *
     * @throws IllegalArgumentException  if {@code quantity} is negative
     * @throws InsufficientStockException if not enough available stock
     */
    public synchronized void reserve(int quantity) {
        validateNonNegative(quantity);
        if (quantity > getAvailable()) {
            throw new InsufficientStockException(
                    String.format("Cannot reserve %d items; only %d available for %s/%s",
                            quantity, getAvailable(), warehouseId, sku));
        }
        reserved += quantity;
    }

    /**
     * Releases previously reserved stock (e.g. order cancellation).
     *
     * @throws IllegalArgumentException if {@code quantity} is negative or exceeds reserved
     */
    public synchronized void releaseReservation(int quantity) {
        validateNonNegative(quantity);
        if (quantity > reserved) {
            throw new IllegalArgumentException(
                    String.format("Cannot release %d items; only %d reserved for %s/%s",
                            quantity, reserved, warehouseId, sku));
        }
        reserved -= quantity;
    }

    /**
     * Indicates whether available stock has crossed the defined reorder threshold.
     */
    public boolean requiresReorder() {
        return getAvailable() <= reorderThreshold;
    }

    // -------------------------------------------------------------------------
    // Validation & Invariants
    // -------------------------------------------------------------------------

    private static void validateNonNegative(int qty) {
        if (qty < 0) {
            throw new IllegalArgumentException("Quantity must not be negative");
        }
    }

    /**
     * Ensures domain invariants hold.
     */
    private void invariantHolds() {
        if (onHand < 0 || reserved < 0) {
            throw new IllegalStateException("onHand/reserved must not be negative");
        }
        if (reserved > onHand) {
            throw new IllegalStateException("reserved cannot exceed onHand");
        }
    }

    // -------------------------------------------------------------------------
    // Getters (no setters to keep aggregate root integrity)
    // -------------------------------------------------------------------------

    public Long getId() {
        return id;
    }

    public String getWarehouseId() {
        return warehouseId;
    }

    public String getSku() {
        return sku;
    }

    public int getOnHand() {
        return onHand;
    }

    public int getReserved() {
        return reserved;
    }

    public int getReorderThreshold() {
        return reorderThreshold;
    }

    public ZonedDateTime getLastModifiedUtc() {
        return lastModifiedUtc;
    }

    public long getVersion() {
        return version;
    }

    // -------------------------------------------------------------------------
    // Equality
    // -------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Stock)) return false;
        Stock stock = (Stock) o;
        return Objects.equals(warehouseId, stock.warehouseId) &&
               Objects.equals(sku, stock.sku);
    }

    @Override
    public int hashCode() {
        return Objects.hash(warehouseId, sku);
    }

    // -------------------------------------------------------------------------
    // Domain Exception
    // -------------------------------------------------------------------------

    /**
     * Thrown when a stock operation cannot be fulfilled.
     */
    public static class InsufficientStockException extends RuntimeException {
        public InsufficientStockException(String message) {
            super(message);
        }
    }
}