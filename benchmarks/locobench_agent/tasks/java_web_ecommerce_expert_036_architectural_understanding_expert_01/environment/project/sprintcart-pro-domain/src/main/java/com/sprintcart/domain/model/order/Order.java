package com.sprintcart.domain.model.order;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Aggregate-root representing a customer Order in SprintCart Pro.
 * <p>
 * In keeping with Hexagonal Architecture, the class is free of persistence
 * annotations and infrastructure concerns. All invariants are enforced
 * internally and state transitions emit domain events that can be handled
 * by outbound adapters (e.g. e-mail, ERP, payment gateway).
 */
public class Order {

    /* ----------------------------------------------------------------------
     * Static factory
     * -------------------------------------------------------------------- */

    /**
     * Creates a new draft order. At this point the order is not yet confirmed.
     */
    public static Order draft(CustomerId customerId) {
        return new Order(new OrderId(), customerId, OrderStatus.DRAFT, Instant.now());
    }

    /* ----------------------------------------------------------------------
     * Fields
     * -------------------------------------------------------------------- */

    private final OrderId id;
    private final CustomerId customerId;
    private final Instant createdAt;

    private OrderStatus status;

    // Mutable timestamps capturing lifecycle events. Null when not reached.
    private Instant confirmedAt;
    private Instant paidAt;
    private Instant cancelledAt;
    private Instant shippedAt;
    private Instant deliveredAt;

    private final Set<LineItem> lineItems = new LinkedHashSet<>();
    private ShippingAddress shippingAddress;

    private BigDecimal grandTotal = BigDecimal.ZERO.setScale(2, RoundingMode.HALF_UP);

    /**
     * Uncommitted domain events that occurred on this aggregate.
     * Cleared by the infrastructure layer after publishing.
     */
    private final List<DomainEvent> domainEvents = new ArrayList<>();

    /* ----------------------------------------------------------------------
     * Constructors
     * -------------------------------------------------------------------- */

    private Order(OrderId id,
                  CustomerId customerId,
                  OrderStatus status,
                  Instant createdAt) {
        this.id = id;
        this.customerId = customerId;
        this.status = status;
        this.createdAt = createdAt;
    }

    /* ----------------------------------------------------------------------
     * Business operations
     * -------------------------------------------------------------------- */

    /**
     * Adds or updates an item in the order. Works only while in DRAFT.
     */
    public void addOrUpdateItem(ProductSnapshot product, int quantity) {
        assertEditable();
        if (quantity <= 0) {
            throw new IllegalArgumentException("Quantity must be positive");
        }

        LineItem existing = lineItems.stream()
                                     .filter(li -> li.productId.equals(product.getId()))
                                     .findFirst().orElse(null);

        if (existing == null) {
            lineItems.add(new LineItem(product, quantity));
        } else {
            existing.incrementQuantity(quantity);
        }
        recalculateGrandTotal();
    }

    /**
     * Removes an item from the order. Works only while in DRAFT.
     */
    public void removeItem(UUID productId) {
        assertEditable();
        lineItems.removeIf(li -> li.productId.equals(productId));
        recalculateGrandTotal();
    }

    /**
     * Sets/updates the shipping address. Works only while in DRAFT.
     */
    public void updateShippingAddress(ShippingAddress address) {
        assertEditable();
        this.shippingAddress = Objects.requireNonNull(address);
    }

    /**
     * Confirms the order, preserving immutable snapshot of pricing and items.
     */
    public void confirm() {
        if (status != OrderStatus.DRAFT) {
            throw new IllegalStateException(
                    "Only DRAFT orders can be confirmed. Current state: " + status);
        }
        if (lineItems.isEmpty()) {
            throw new IllegalStateException("Cannot confirm order with no items");
        }
        if (shippingAddress == null) {
            throw new IllegalStateException("Shipping address not set");
        }

        this.status = OrderStatus.CONFIRMED;
        this.confirmedAt = Instant.now();

        recordEvent(new OrderConfirmed(id, customerId, grandTotal, confirmedAt));
    }

    /**
     * Marks the order as paid.
     */
    public void markPaid() {
        requireState(OrderStatus.CONFIRMED);
        this.status = OrderStatus.PAID;
        this.paidAt = Instant.now();

        recordEvent(new OrderPaid(id, paidAt));
    }

    /**
     * Cancels the order. Allowed while CONFIRMED or PAID (with refund logic
     * handled by external service via event).
     */
    public void cancel(String reason) {
        if (status != OrderStatus.CONFIRMED && status != OrderStatus.PAID) {
            throw new IllegalStateException("Cannot cancel order in state: " + status);
        }
        this.status = OrderStatus.CANCELLED;
        this.cancelledAt = Instant.now();

        recordEvent(new OrderCancelled(id, cancelledAt, reason));
    }

    /**
     * Marks the order as shipped.
     */
    public void markShipped(String carrier, String trackingNumber) {
        requireState(OrderStatus.PAID);
        this.status = OrderStatus.SHIPPED;
        this.shippedAt = Instant.now();

        recordEvent(new OrderShipped(id, shippedAt, carrier, trackingNumber));
    }

    /**
     * Marks the order as delivered.
     */
    public void markDelivered() {
        requireState(OrderStatus.SHIPPED);
        this.status = OrderStatus.DELIVERED;
        this.deliveredAt = Instant.now();

        recordEvent(new OrderDelivered(id, deliveredAt));
    }

    /* ----------------------------------------------------------------------
     * Read-only getters
     * -------------------------------------------------------------------- */

    public OrderId getId() {
        return id;
    }

    public CustomerId getCustomerId() {
        return customerId;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public OrderStatus getStatus() {
        return status;
    }

    public Instant getConfirmedAt() {
        return confirmedAt;
    }

    public Instant getPaidAt() {
        return paidAt;
    }

    public Instant getCancelledAt() {
        return cancelledAt;
    }

    public Instant getShippedAt() {
        return shippedAt;
    }

    public Instant getDeliveredAt() {
        return deliveredAt;
    }

    public Set<LineItem> getLineItems() {
        return Collections.unmodifiableSet(lineItems);
    }

    public ShippingAddress getShippingAddress() {
        return shippingAddress;
    }

    public BigDecimal getGrandTotal() {
        return grandTotal;
    }

    public List<DomainEvent> getDomainEvents() {
        return Collections.unmodifiableList(domainEvents);
    }

    /**
     * Clears the event list. Should be invoked by the event dispatcher in the
     * infrastructure layer after successful publication.
     */
    public void flushEvents() {
        domainEvents.clear();
    }

    /* ----------------------------------------------------------------------
     * Helpers
     * -------------------------------------------------------------------- */

    private void recalculateGrandTotal() {
        this.grandTotal = lineItems.stream()
                                   .map(LineItem::getSubtotal)
                                   .reduce(BigDecimal.ZERO, BigDecimal::add)
                                   .setScale(2, RoundingMode.HALF_UP);
    }

    private void assertEditable() {
        if (status != OrderStatus.DRAFT) {
            throw new IllegalStateException("Order is not editable once confirmed");
        }
    }

    private void requireState(OrderStatus expected) {
        if (status != expected) {
            throw new IllegalStateException(
                    "Expected state " + expected + " but order is " + status);
        }
    }

    private void recordEvent(DomainEvent event) {
        domainEvents.add(event);
    }

    /* ----------------------------------------------------------------------
     * Inner types
     * -------------------------------------------------------------------- */

    /**
     * Value object representing the Order identifier.
     */
    public static final class OrderId {
        private final UUID value;

        public OrderId() {
            this(UUID.randomUUID());
        }

        public OrderId(UUID value) {
            this.value = Objects.requireNonNull(value);
        }

        public UUID getValue() {
            return value;
        }

        @Override public boolean equals(Object o) {
            return this == o || (o instanceof OrderId other && value.equals(other.value));
        }

        @Override public int hashCode() {
            return value.hashCode();
        }

        @Override public String toString() {
            return value.toString();
        }
    }

    /**
     * Value object representing the Customer identifier.
     */
    public static final class CustomerId {
        private final UUID value;

        public CustomerId(UUID value) {
            this.value = Objects.requireNonNull(value);
        }

        public UUID getValue() {
            return value;
        }

        @Override public boolean equals(Object o) {
            return this == o || (o instanceof CustomerId other && value.equals(other.value));
        }

        @Override public int hashCode() {
            return value.hashCode();
        }

        @Override public String toString() {
            return value.toString();
        }
    }

    /**
     * Immutable snapshot of product data captured at the time of ordering.
     * Prevents later catalog changes from affecting historical orders.
     */
    public static final class ProductSnapshot {
        private final UUID id;
        private final String sku;
        private final String name;
        private final BigDecimal unitPrice;

        public ProductSnapshot(UUID id, String sku, String name, BigDecimal unitPrice) {
            this.id = Objects.requireNonNull(id);
            this.sku = Objects.requireNonNull(sku);
            this.name = Objects.requireNonNull(name);
            this.unitPrice = unitPrice.setScale(2, RoundingMode.HALF_UP);
        }

        public UUID getId() { return id; }
        public String getSku() { return sku; }
        public String getName() { return name; }
        public BigDecimal getUnitPrice() { return unitPrice; }
    }

    /**
     * Entity representing an item inside an Order.
     */
    public static class LineItem {
        private final UUID productId;
        private final String sku;
        private final String name;
        private int quantity;
        private final BigDecimal unitPrice;

        LineItem(ProductSnapshot product, int quantity) {
            this.productId = product.getId();
            this.sku = product.getSku();
            this.name = product.getName();
            this.quantity = quantity;
            this.unitPrice = product.getUnitPrice();
        }

        void incrementQuantity(int delta) {
            quantity += delta;
        }

        public UUID getProductId() { return productId; }
        public String getSku() { return sku; }
        public String getName() { return name; }
        public int getQuantity() { return quantity; }
        public BigDecimal getUnitPrice() { return unitPrice; }

        public BigDecimal getSubtotal() {
            return unitPrice.multiply(BigDecimal.valueOf(quantity))
                            .setScale(2, RoundingMode.HALF_UP);
        }

        @Override public int hashCode() { return productId.hashCode(); }

        @Override public boolean equals(Object obj) {
            return this == obj ||
                   (obj instanceof LineItem other && productId.equals(other.productId));
        }
    }

    /**
     * Immutable value object representing shipping address.
     */
    public record ShippingAddress(
            String recipientName,
            String street,
            String city,
            String state,
            String postalCode,
            String country
    ) {
        public ShippingAddress {
            Objects.requireNonNull(recipientName);
            Objects.requireNonNull(street);
            Objects.requireNonNull(city);
            Objects.requireNonNull(state);
            Objects.requireNonNull(postalCode);
            Objects.requireNonNull(country);
        }
    }

    /**
     * Permitted order lifecycle states.
     */
    public enum OrderStatus {
        DRAFT,
        CONFIRMED,
        PAID,
        SHIPPED,
        DELIVERED,
        CANCELLED
    }

    /* ----------------------------------------------------------------------
     * Domain Event hierarchy
     * -------------------------------------------------------------------- */

    /**
     * Marker interface for Order-related events.
     */
    public sealed interface DomainEvent permits OrderConfirmed,
                                               OrderPaid,
                                               OrderCancelled,
                                               OrderShipped,
                                               OrderDelivered {
        Instant occurredAt();
    }

    public record OrderConfirmed(
            OrderId orderId,
            CustomerId customerId,
            BigDecimal grandTotal,
            Instant occurredAt) implements DomainEvent {}

    public record OrderPaid(
            OrderId orderId,
            Instant occurredAt) implements DomainEvent {}

    public record OrderCancelled(
            OrderId orderId,
            Instant occurredAt,
            String reason) implements DomainEvent {}

    public record OrderShipped(
            OrderId orderId,
            Instant occurredAt,
            String carrier,
            String trackingNumber) implements DomainEvent {}

    public record OrderDelivered(
            OrderId orderId,
            Instant occurredAt) implements DomainEvent {}
}