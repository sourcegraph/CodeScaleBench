package com.sprintcart.adapters.persistence.entity;

import com.sprintcart.adapters.persistence.entity.common.AuditEmbeddable;
import com.sprintcart.adapters.persistence.entity.common.MoneyEmbeddable;
import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Embedded;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToMany;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * JPA entity that represents an Order in the persistence layer.
 * <p>
 * The entity follows Hexagonal Architecture principles: business logic does not leak
 * into this class, and the class is capable of converting itself to and from the
 * corresponding domain aggregate (see OrderMapper). Auditing fields are handled via
 * {@link AuditEmbeddable}. Monetary values are embedded to guarantee currency
 * consistency across the platform.
 */
@Entity
@Table(name = "orders")
public class OrderEntity {

    // ------------------------------------------------------------------------
    // Core columns
    // ------------------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Immutable, unique human-readable identifier shown in the UI
     * (e.g. "WEB-1243"). Generated in the domain layer.
     */
    @Column(name = "external_reference", nullable = false, unique = true, length = 32)
    private String externalReference;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private OrderStatus status = OrderStatus.PENDING_PAYMENT;

    /**
     * Captures the grand-total, including taxes, shipping, discounts, etc.
     * The domain layer is responsible for the calculation—this entity only
     * stores the resulting numbers.
     */
    @Embedded
    private MoneyEmbeddable grandTotal;

    // ------------------------------------------------------------------------
    // Relationships
    // ------------------------------------------------------------------------

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "customer_id")
    private CustomerEntity customer;

    /**
     * All items belonging to this order. Cascade is ALL because an {@code OrderItemEntity}
     * only exists in the context of an {@code OrderEntity}. Orphan removal keeps the DB tidy.
     */
    @OneToMany(
        mappedBy = "order",
        cascade = CascadeType.ALL,
        orphanRemoval = true
    )
    private List<OrderItemEntity> items = new ArrayList<>();

    // ------------------------------------------------------------------------
    // Infrastructure columns
    // ------------------------------------------------------------------------

    @Embedded
    private AuditEmbeddable audit = new AuditEmbeddable();

    @Version
    private Long version;

    // ------------------------------------------------------------------------
    // Constructors
    // ------------------------------------------------------------------------

    protected OrderEntity() {
        /* Required by JPA */
    }

    public OrderEntity(String externalReference, CustomerEntity customer) {
        this.externalReference = Objects.requireNonNull(externalReference, "externalReference");
        this.customer = Objects.requireNonNull(customer, "customer");
        this.status = OrderStatus.PENDING_PAYMENT;
    }

    // ------------------------------------------------------------------------
    // Domain utilities
    // ------------------------------------------------------------------------

    /**
     * Adds an {@link OrderItemEntity} to the order. The method sets up the
     * bi-directional relationship and recalculates the grand total defensively.
     */
    public void addItem(OrderItemEntity item) {
        Objects.requireNonNull(item, "item");
        item.setOrder(this);
        items.add(item);
        recalculateGrandTotal();
    }

    public void removeItem(OrderItemEntity item) {
        if (items.remove(item)) {
            item.setOrder(null);
            recalculateGrandTotal();
        }
    }

    public List<OrderItemEntity> getItems() {
        return Collections.unmodifiableList(items);
    }

    /**
     * Updates the order status. Allowed state transitions are validated in the
     * domain layer; the entity only persists the result.
     */
    public void setStatus(OrderStatus status) {
        this.status = Objects.requireNonNull(status, "status");
    }

    public OrderStatus getStatus() {
        return status;
    }

    public MoneyEmbeddable getGrandTotal() {
        return grandTotal;
    }

    // ------------------------------------------------------------------------
    // Auditing hooks
    // ------------------------------------------------------------------------

    @PrePersist
    void onCreate() {
        audit.setCreatedAt(OffsetDateTime.now());
        audit.setUpdatedAt(audit.getCreatedAt());
    }

    @PreUpdate
    void onUpdate() {
        audit.setUpdatedAt(OffsetDateTime.now());
    }

    // ------------------------------------------------------------------------
    // Private helpers
    // ------------------------------------------------------------------------

    private void recalculateGrandTotal() {
        grandTotal = items.stream()
            .map(OrderItemEntity::getLineTotal)
            .reduce(MoneyEmbeddable.zero(), MoneyEmbeddable::add);
    }

    // ------------------------------------------------------------------------
    // Getters (JPA / serialization)
    // ------------------------------------------------------------------------

    public Long getId() {
        return id;
    }

    public String getExternalReference() {
        return externalReference;
    }

    public CustomerEntity getCustomer() {
        return customer;
    }

    public OffsetDateTime getCreatedAt() {
        return audit.getCreatedAt();
    }

    public OffsetDateTime getUpdatedAt() {
        return audit.getUpdatedAt();
    }

    public Long getVersion() {
        return version;
    }

    // ------------------------------------------------------------------------
    // Equality & String helpers
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof OrderEntity)) return false;
        OrderEntity that = (OrderEntity) o;
        // Equality for detached entities relies on business key
        return Objects.equals(externalReference, that.externalReference);
    }

    @Override
    public int hashCode() {
        return Objects.hash(externalReference);
    }

    @Override
    public String toString() {
        return "OrderEntity{" +
            "id=" + id +
            ", externalReference='" + externalReference + '\'' +
            ", status=" + status +
            '}';
    }

    // ------------------------------------------------------------------------
    // Enumerations
    // ------------------------------------------------------------------------

    public enum OrderStatus {
        PENDING_PAYMENT,
        PAYMENT_AUTHORIZED,
        FULFILLMENT_IN_PROGRESS,
        SHIPPED,
        DELIVERED,
        CANCELLED,
        REFUNDED
    }
}