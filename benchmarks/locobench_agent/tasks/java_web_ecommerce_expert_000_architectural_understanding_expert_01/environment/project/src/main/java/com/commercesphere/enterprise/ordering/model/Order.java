package com.commercesphere.enterprise.ordering.model;

import jakarta.persistence.CollectionTable;
import jakarta.persistence.Column;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.MapKeyColumn;
import jakarta.persistence.OneToMany;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Currency;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Order is the root aggregate representing a purchase order placed by a B2B account.
 * <p>
 * Responsibility summary:
 *  • Track order financial totals (tax, shipping, grand total)
 *  • Maintain immutable external UUID for public references
 *  • Guard state transitions through a strict state-machine
 *  • Provide optimistic locking via version field
 *  • Persist extra non-modeled key/value attributes for extensibility
 */
@Entity
@Table(name = "orders")
public class Order implements Serializable {

    @Serial
    private static final long serialVersionUID = -471565114247010128L;

    /* ----------  Persistent fields  ---------- */

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Public-facing immutable identifier.
     * Generated at persist time to avoid leaking internal numeric IDs.
     */
    @Column(name = "external_id", nullable = false, updatable = false, unique = true, length = 36)
    private UUID externalId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private Status status = Status.DRAFT;

    @ElementCollection(fetch = FetchType.LAZY)
    @CollectionTable(name = "order_attributes", joinColumns = @JoinColumn(name = "order_id"))
    @MapKeyColumn(name = "attr_key", length = 100)
    @Column(name = "attr_value", length = 255)
    private Map<String, String> attributes = new HashMap<>();

    @OneToMany(mappedBy = "order", cascade = jakarta.persistence.CascadeType.ALL, orphanRemoval = true)
    private List<OrderLine> lines = new ArrayList<>();

    @PositiveOrZero
    @Column(name = "subtotal_amount", precision = 19, scale = 4, nullable = false)
    private BigDecimal subtotalAmount = BigDecimal.ZERO;

    @PositiveOrZero
    @Column(name = "tax_amount", precision = 19, scale = 4, nullable = false)
    private BigDecimal taxAmount = BigDecimal.ZERO;

    @PositiveOrZero
    @Column(name = "shipping_amount", precision = 19, scale = 4, nullable = false)
    private BigDecimal shippingAmount = BigDecimal.ZERO;

    @PositiveOrZero
    @Column(name = "total_amount", precision = 19, scale = 4, nullable = false)
    private BigDecimal totalAmount = BigDecimal.ZERO;

    @NotNull
    @Column(name = "currency", nullable = false, length = 3)
    private Currency currency = Currency.getInstance("USD");

    @CreationTimestamp
    @Column(name = "created_at", updatable = false, nullable = false)
    private Instant createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    /**
     * Optimistic locking token. Each successful update increments the version.
     */
    @Version
    @Column(nullable = false)
    private int version;

    /* ----------  Domain logic  ---------- */

    /**
     * Allowed status transitions.
     * Immutable map constructed once at class-loading time.
     */
    private static final Map<Status, Set<Status>> ALLOWED_TRANSITIONS = Map.of(
            Status.DRAFT, EnumSet.of(Status.SUBMITTED, Status.CANCELLED),
            Status.SUBMITTED, EnumSet.of(Status.APPROVED, Status.REJECTED, Status.CANCELLED),
            Status.APPROVED, EnumSet.of(Status.SHIPPED, Status.CANCELLED),
            Status.SHIPPED, EnumSet.of(Status.COMPLETED),
            Status.REJECTED, EnumSet.of(Status.CANCELLED),
            Status.CANCELLED, EnumSet.noneOf(Status.class),
            Status.COMPLETED, EnumSet.noneOf(Status.class)
    );

    protected Order() {
        /* Required by JPA */
    }

    public Order(Currency currency) {
        this.currency = Objects.requireNonNull(currency, "currency must not be null");
    }

    @PrePersist
    private void assignExternalId() {
        if (externalId == null) {
            externalId = UUID.randomUUID();
        }
        recalculateTotals(); // Ensure totals are set prior to initial insert
    }

    /* ----------  Business operations  ---------- */

    /**
     * Attach a new line to this order.
     * Recalculates financial totals after insertion.
     *
     * @param line the line to be added
     */
    public synchronized void addLine(@NotNull OrderLine line) {
        Objects.requireNonNull(line, "line must not be null");
        line.setOrder(this);
        lines.add(line);
        recalculateTotals();
    }

    /**
     * Removes a previously attached line, if present.
     * Safety no-ops when the item is not found.
     *
     * @param line the line to remove
     */
    public synchronized void removeLine(@NotNull OrderLine line) {
        Objects.requireNonNull(line, "line must not be null");
        if (lines.remove(line)) {
            line.setOrder(null);
            recalculateTotals();
        }
    }

    /**
     * Performs in-memory subtotal/total calculation.
     * Tax computation is intentionally simplified. In real systems
     * this would delegate to a pluggable tax engine.
     */
    public synchronized void recalculateTotals() {
        subtotalAmount = lines.stream()
                              .map(OrderLine::getExtendedPrice)
                              .reduce(BigDecimal.ZERO, BigDecimal::add);

        // --- Business-specific tax/shipping rules start here ---
        taxAmount = subtotalAmount.multiply(BigDecimal.valueOf(0.07));    // 7% flat sales tax
        shippingAmount = subtotalAmount.compareTo(BigDecimal.valueOf(500)) >= 0
                ? BigDecimal.ZERO                                              // free shipping over $500
                : BigDecimal.valueOf(25.00);
        // --- Business-specific rules end here ---

        totalAmount = subtotalAmount.add(taxAmount).add(shippingAmount);
    }

    /**
     * Request a status change while enforcing allowed transitions.
     *
     * @param target the new status
     * @throws IllegalStateException if transition is not permitted
     */
    public synchronized void transitionTo(@NotNull Status target) {
        Objects.requireNonNull(target, "target status must not be null");

        Set<Status> allowed = ALLOWED_TRANSITIONS.getOrDefault(status, Set.of());
        if (!allowed.contains(target)) {
            throw new IllegalStateException(
                    "Illegal status transition from %s to %s".formatted(status, target));
        }
        this.status = target;
    }

    /* ----------  Accessors  ---------- */

    public Long getId() {
        return id;
    }

    public UUID getExternalId() {
        return externalId;
    }

    public Status getStatus() {
        return status;
    }

    public Map<String, String> getAttributes() {
        return Map.copyOf(attributes);
    }

    public List<OrderLine> getLines() {
        return List.copyOf(lines);
    }

    public BigDecimal getSubtotalAmount() {
        return subtotalAmount;
    }

    public BigDecimal getTaxAmount() {
        return taxAmount;
    }

    public BigDecimal getShippingAmount() {
        return shippingAmount;
    }

    public BigDecimal getTotalAmount() {
        return totalAmount;
    }

    public Currency getCurrency() {
        return currency;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public int getVersion() {
        return version;
    }

    /* ----------  Equality & hashing  ---------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Order that)) return false;
        return externalId.equals(that.externalId);
    }

    @Override
    public int hashCode() {
        return externalId.hashCode();
    }

    /* ----------  Nested types  ---------- */

    /**
     * Order state machine definition.
     */
    public enum Status {
        DRAFT,
        SUBMITTED,
        APPROVED,
        REJECTED,
        SHIPPED,
        COMPLETED,
        CANCELLED
    }

    /**
     * Minimalistic line item representation to keep the file
     * self-contained for compilation in isolation.
     * In the full codebase this would live in its own source file
     * with richer behavior (discounts, promotions, kit handling etc.).
     */
    @Entity
    @Table(name = "order_lines")
    public static class OrderLine implements Serializable {

        @Serial
        private static final long serialVersionUID = 317862176297905L;

        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        private Long id;

        @NotNull
        @Column(name = "sku", nullable = false, length = 64)
        private String sku;

        @NotNull
        @Column(name = "description", nullable = false, length = 255)
        private String description;

        @PositiveOrZero
        @Column(name = "unit_price", precision = 19, scale = 4, nullable = false)
        private BigDecimal unitPrice;

        @PositiveOrZero
        @Column(name = "quantity", nullable = false)
        private int quantity;

        @jakarta.persistence.ManyToOne(fetch = FetchType.LAZY, optional = false)
        @JoinColumn(name = "order_id")
        private Order order;

        protected OrderLine() { /* JPA */ }

        public OrderLine(String sku,
                         String description,
                         BigDecimal unitPrice,
                         int quantity) {
            this.sku = Objects.requireNonNull(sku);
            this.description = Objects.requireNonNull(description);
            this.unitPrice = Objects.requireNonNull(unitPrice);
            if (quantity < 0) {
                throw new IllegalArgumentException("quantity must be positive");
            }
            this.quantity = quantity;
        }

        public BigDecimal getExtendedPrice() {
            return unitPrice.multiply(BigDecimal.valueOf(quantity));
        }

        // --------------- Getters & Setters ---------------
        public Long getId() { return id; }
        public String getSku() { return sku; }
        public String getDescription() { return description; }
        public BigDecimal getUnitPrice() { return unitPrice; }
        public int getQuantity() { return quantity; }

        void setOrder(Order order) { this.order = order; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof OrderLine that)) return false;
            return Objects.equals(id, that.id);
        }

        @Override
        public int hashCode() {
            return Objects.hashCode(id);
        }
    }
}