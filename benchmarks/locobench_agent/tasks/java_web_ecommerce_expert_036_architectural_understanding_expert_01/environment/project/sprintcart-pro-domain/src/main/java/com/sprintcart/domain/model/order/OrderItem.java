package com.sprintcart.domain.model.order;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Currency;
import java.util.Objects;
import java.util.UUID;

/**
 * Domain entity representing a single line inside an {@code Order}.
 * <p>
 * The class is purposefully mutable for {@code quantity} and {@code discount} fields because
 * operators may adjust items during the lifecycle of an order (e.g., customer requests a change
 * before fulfillment starts). All state-changing operations are guarded by invariant checks to
 * preserve domain consistency.
 *
 * <strong>Invariant rules:</strong>
 * <ul>
 *     <li>{@code quantity} must always be greater than {@code 0}</li>
 *     <li>{@code unitPrice} must be positive (&gt; 0)</li>
 *     <li>{@code discount} can never exceed {@code unitPrice * quantity}</li>
 *     <li>{@code currency} is fixed for the lifetime of the item</li>
 * </ul>
 *
 * The entity intentionally does <em>not</em> expose setters; instead, clients must use the
 * behavioral methods that implement business rules.
 */
public final class OrderItem implements Serializable {

    @Serial
    private static final long serialVersionUID = 6027723349122402185L;

    /**
     * Unique identifier of the order item, generated independently from the order id
     * so the item can be referenced unambiguously across bounded contexts (e.g.,
     * warehouse, invoicing).
     */
    private final UUID itemId;

    /**
     * SKU or any merchant-recognizable identifier of the sellable.
     * The catalog context owns the meaning of this value.
     */
    private final String sku;

    /**
     * Human-readable product title captured at purchase time to guarantee historical
     * correctness even if the catalog later changes.
     */
    private final String nameSnapshot;

    /**
     * Unit price (gross) as agreed at checkout time. Immutable to guarantee price
     * integrity for downstream processes (refunds, accounting, etc.).
     */
    private final BigDecimal unitPrice;

    /**
     * ISO 4217 currency code—immutably set on item creation.
     */
    private final Currency currency;

    /**
     * Total quantity purchased. May be updated by client services while the order is
     * in pre-fulfillment state.
     */
    private int quantity;

    /**
     * Flat discount applied to this line item (total, not per unit).
     */
    private BigDecimal discount;

    /**
     * Optimistic‐locking field used by persistence adapters. Not part of equals/hashCode.
     */
    private long version;

    /* --------------------------------------------------------------------- */
    /* Constructors                                                          */
    /* --------------------------------------------------------------------- */

    private OrderItem(Builder builder) {
        this.itemId = builder.itemId == null ? UUID.randomUUID() : builder.itemId;
        this.sku = builder.sku;
        this.nameSnapshot = builder.nameSnapshot;
        this.unitPrice = builder.unitPrice;
        this.currency = builder.currency;
        this.quantity = builder.quantity;
        this.discount = builder.discount == null ? BigDecimal.ZERO : builder.discount;
        this.version = 0L;

        validateState();
    }

    /* --------------------------------------------------------------------- */
    /* Factory methods                                                       */
    /* --------------------------------------------------------------------- */

    /**
     * Creates a new {@code OrderItem} using the mandatory attributes.
     */
    public static Builder builder() {
        return new Builder();
    }

    /* --------------------------------------------------------------------- */
    /* Business behavior                                                     */
    /* --------------------------------------------------------------------- */

    /**
     * Adjusts the quantity of this order item. Quantity must remain positive.
     *
     * @param newQuantity new quantity requested by the caller
     * @throws IllegalArgumentException if {@code newQuantity &lt;= 0}
     */
    public void changeQuantity(int newQuantity) {
        if (newQuantity <= 0) {
            throw new IllegalArgumentException("Quantity must be greater than zero");
        }
        this.quantity = newQuantity;
        validateDiscountNotExceedingSubtotal();
    }

    /**
     * Applies or updates a flat discount on this line item.
     *
     * @param discount non-negative discount total; if zero, any previous discount will be removed
     * @throws IllegalArgumentException if {@code discount &lt; 0} or exceeds subtotal
     */
    public void applyDiscount(BigDecimal discount) {
        Objects.requireNonNull(discount, "discount must not be null");
        if (discount.compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("Discount cannot be negative");
        }

        BigDecimal subtotal = calculateSubtotal();
        if (discount.compareTo(subtotal) > 0) {
            throw new IllegalArgumentException(
                    "Discount cannot exceed subtotal: discount=" + discount + ", subtotal=" + subtotal);
        }
        this.discount = discount.setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * Returns the total amount for this line after discount, rounded to two
     * decimal places using HALF_UP strategy.
     */
    public BigDecimal calculateTotal() {
        return calculateSubtotal().subtract(discount).setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * Returns the subtotal (quantity * unitPrice) <em>before</em> discount.
     */
    public BigDecimal calculateSubtotal() {
        return unitPrice.multiply(BigDecimal.valueOf(quantity))
                        .setScale(2, RoundingMode.HALF_UP);
    }

    /* --------------------------------------------------------------------- */
    /* Getters                                                               */
    /* --------------------------------------------------------------------- */

    public UUID getItemId() {
        return itemId;
    }

    public String getSku() {
        return sku;
    }

    public String getNameSnapshot() {
        return nameSnapshot;
    }

    public BigDecimal getUnitPrice() {
        return unitPrice;
    }

    public int getQuantity() {
        return quantity;
    }

    public BigDecimal getDiscount() {
        return discount;
    }

    public Currency getCurrency() {
        return currency;
    }

    public long getVersion() {
        return version;
    }

    /* --------------------------------------------------------------------- */
    /* Invariants and utility                                                */
    /* --------------------------------------------------------------------- */

    private void validateState() {
        Objects.requireNonNull(itemId, "itemId must not be null");
        Objects.requireNonNull(sku, "sku must not be null");
        Objects.requireNonNull(nameSnapshot, "nameSnapshot must not be null");
        Objects.requireNonNull(unitPrice, "unitPrice must not be null");
        Objects.requireNonNull(currency, "currency must not be null");
        if (unitPrice.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Unit price must be positive");
        }
        if (quantity <= 0) {
            throw new IllegalArgumentException("Quantity must be greater than zero");
        }
        if (discount.compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("Discount cannot be negative");
        }
        validateDiscountNotExceedingSubtotal();
    }

    private void validateDiscountNotExceedingSubtotal() {
        BigDecimal subtotal = calculateSubtotal();
        if (discount.compareTo(subtotal) > 0) {
            throw new IllegalArgumentException(
                    "Discount cannot exceed subtotal: discount=" + discount + ", subtotal=" + subtotal);
        }
    }

    /* --------------------------------------------------------------------- */
    /* Equality – identity semantics                                         */
    /* --------------------------------------------------------------------- */

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof OrderItem other)) return false;
        return itemId.equals(other.itemId);
    }

    @Override
    public int hashCode() {
        return itemId.hashCode();
    }

    /* --------------------------------------------------------------------- */
    /* Developer-friendly                                                    */
    /* --------------------------------------------------------------------- */

    @Override
    public String toString() {
        return "OrderItem{" +
               "itemId=" + itemId +
               ", sku='" + sku + '\'' +
               ", nameSnapshot='" + nameSnapshot + '\'' +
               ", unitPrice=" + unitPrice +
               ", currency=" + currency +
               ", quantity=" + quantity +
               ", discount=" + discount +
               '}';
    }

    /* --------------------------------------------------------------------- */
    /* Builder                                                               */
    /* --------------------------------------------------------------------- */

    public static final class Builder {
        private UUID itemId;
        private String sku;
        private String nameSnapshot;
        private BigDecimal unitPrice;
        private Currency currency;
        private int quantity;
        private BigDecimal discount;

        private Builder() { /* use static factory */ }

        public Builder itemId(UUID itemId) {
            this.itemId = itemId;
            return this;
        }

        public Builder sku(String sku) {
            this.sku = sku;
            return this;
        }

        public Builder nameSnapshot(String nameSnapshot) {
            this.nameSnapshot = nameSnapshot;
            return this;
        }

        public Builder unitPrice(BigDecimal unitPrice) {
            this.unitPrice = unitPrice;
            return this;
        }

        public Builder currency(Currency currency) {
            this.currency = currency;
            return this;
        }

        public Builder quantity(int quantity) {
            this.quantity = quantity;
            return this;
        }

        public Builder discount(BigDecimal discount) {
            this.discount = discount;
            return this;
        }

        public OrderItem build() {
            return new OrderItem(this);
        }
    }
}