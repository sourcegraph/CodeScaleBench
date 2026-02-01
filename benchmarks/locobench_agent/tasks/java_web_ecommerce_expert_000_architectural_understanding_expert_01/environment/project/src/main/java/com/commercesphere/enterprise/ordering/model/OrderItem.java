package com.commercesphere.enterprise.ordering.model;

import jakarta.persistence.Basic;
import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Embeddable;
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
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.io.Serializable;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.Currency;
import java.util.Objects;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Domain model representing a single line item within an {@link Order}.
 * <p>
 * OrderItem is responsible for encapsulating all pricing logic that is specific
 * to the item level (e.g. per–SKU discounts, taxes). Aggregate-level validation is
 * delegated to the parent {@code Order} entity.
 *
 * <p>
 * <b>Concurrency:</b> Optimistically locked via {@link #version}.
 * </p>
 */
@Entity
@Table(name = "cs_order_items")
public class OrderItem implements Serializable {

    private static final Logger LOGGER = LoggerFactory.getLogger(OrderItem.class);
    private static final long serialVersionUID = 6404208761528332382L;

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Owning side of the relationship; lazy to avoid Cartesian explosions when
     * fetching order collections.
     */
    @NotNull
    @ManyToOne(fetch = FetchType.LAZY, optional = false, cascade = {CascadeType.PERSIST})
    @JoinColumn(name = "order_id", nullable = false, updatable = false)
    private Order order;

    @NotBlank
    @Column(name = "sku", nullable = false, length = 64)
    private String sku;

    @NotBlank
    @Column(name = "product_name", nullable = false, length = 256)
    private String productName;

    @NotNull
    @Positive
    @Column(name = "quantity", nullable = false)
    private Integer quantity;

    @Embedded
    private Money unitPrice;

    @Embedded
    @Column(name = "discount_amount")
    private Money discountAmount;

    @Embedded
    @Column(name = "tax_amount")
    private Money taxAmount;

    @Embedded
    @Column(name = "total_amount")
    private Money totalAmount;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private Status status = Status.OPEN;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false, nullable = false)
    private OffsetDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "modified_at")
    private OffsetDateTime modifiedAt;

    @Version
    private Long version;

    /* ------------------------- Business Methods -------------------------- */

    /**
     * Replaces current quantity with the provided amount and triggers a pricing
     * recalculation. Quantity cannot be lower than 1 and modifications are
     * disallowed when the item is already finalized.
     *
     * @param newQuantity new quantity, must be &gt;= 1
     */
    public void changeQuantity(@Min(1) int newQuantity) {
        ensureMutable();
        if (newQuantity < 1) {
            throw new IllegalArgumentException("Quantity must be >= 1");
        }
        this.quantity = newQuantity;
        recalculatePrices();
        LOGGER.debug("Quantity updated to {} for OrderItem[{}]", newQuantity, id);
    }

    /**
     * Applies an absolute discount amount to the item and triggers a pricing
     * recalculation. Negative discounts are forbidden.
     *
     * @param discount monetary amount in the same currency as {@code unitPrice}
     */
    public void applyDiscount(@NotNull Money discount) {
        ensureMutable();
        if (!discount.isPositiveOrZero()) {
            throw new IllegalArgumentException("Discount cannot be negative");
        }
        if (!discount.getCurrency().equals(unitPrice.getCurrency())) {
            throw new IllegalArgumentException("Currency mismatch for discount");
        }
        this.discountAmount = discount;
        recalculatePrices();
        LOGGER.debug("Discount {} applied for OrderItem[{}]", discount, id);
    }

    /**
     * Finalizes the item, preventing further modifications.
     */
    public void seal() {
        if (status == Status.FINALIZED) {
            return; // Idempotent
        }
        recalculatePrices(); // ensure totals are accurate
        status = Status.FINALIZED;
        LOGGER.info("OrderItem[{}] sealed at {}", id, OffsetDateTime.now());
    }

    /**
     * Calculates total = (unitPrice * quantity) - discount + tax
     */
    public void recalculatePrices() {
        Money subTotal = unitPrice.multiply(quantity);
        Money discounted = discountAmount == null ? Money.zero(unitPrice.getCurrency()) : discountAmount;
        Money taxableBase = subTotal.subtract(discounted);
        Money tax = taxAmount == null ? Money.zero(unitPrice.getCurrency()) : taxAmount;

        this.totalAmount = taxableBase.add(tax);
    }

    /* --------------------------- Helpers --------------------------------- */

    private void ensureMutable() {
        if (status == Status.FINALIZED) {
            throw new IllegalStateException("OrderItem is finalized and cannot be modified");
        }
    }

    /* ------------------------- Getters/Setters --------------------------- */

    public Long getId() {
        return id;
    }

    public Order getOrder() {
        return order;
    }

    public void setOrder(@NotNull Order order) {
        this.order = order;
    }

    public String getSku() {
        return sku;
    }

    public void setSku(@NotBlank String sku) {
        this.sku = sku;
    }

    public String getProductName() {
        return productName;
    }

    public void setProductName(@NotBlank String productName) {
        this.productName = productName;
    }

    public Integer getQuantity() {
        return quantity;
    }

    public Money getUnitPrice() {
        return unitPrice;
    }

    public void setUnitPrice(@NotNull Money unitPrice) {
        this.unitPrice = unitPrice;
        recalculatePrices();
    }

    public Money getDiscountAmount() {
        return discountAmount;
    }

    public Money getTaxAmount() {
        return taxAmount;
    }

    public void setTaxAmount(Money taxAmount) {
        this.taxAmount = taxAmount;
        recalculatePrices();
    }

    public Money getTotalAmount() {
        return totalAmount;
    }

    public Status getStatus() {
        return status;
    }

    /* --------------------------- Overrides ------------------------------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof OrderItem)) return false;
        OrderItem orderItem = (OrderItem) o;
        return Objects.equals(id, orderItem.id);
    }

    @Override
    public int hashCode() {
        return Objects.hashCode(id);
    }

    /* ---------------------------- Enums ---------------------------------- */

    public enum Status {
        OPEN, FINALIZED
    }

    /* -------------------- Value Object: Money ---------------------------- */

    /**
     * Immutable monetary amount that encapsulates {@link Currency} and
     * {@link BigDecimal} arithmetic with scale awareness.
     */
    @Embeddable
    public static class Money implements Serializable {

        private static final long serialVersionUID = -2857509428371192157L;

        @NotNull
        @Basic(optional = false)
        @Column(name = "amount", precision = 19, scale = 4, nullable = false)
        private BigDecimal amount;

        @NotNull
        @Convert(converter = CurrencyAttributeConverter.class)
        @Column(name = "currency", length = 3, nullable = false)
        private Currency currency;

        protected Money() { /* for JPA */ }

        private Money(BigDecimal amount, Currency currency) {
            this.amount = amount.setScale(4, RoundingMode.HALF_UP);
            this.currency = currency;
        }

        public static Money of(@NotNull BigDecimal amount, @NotNull Currency currency) {
            return new Money(amount, currency);
        }

        public static Money zero(Currency currency) {
            return new Money(BigDecimal.ZERO, currency);
        }

        public Money add(Money other) {
            validateCurrency(other);
            return new Money(amount.add(other.amount), currency);
        }

        public Money subtract(Money other) {
            validateCurrency(other);
            return new Money(amount.subtract(other.amount), currency);
        }

        public Money multiply(int multiplier) {
            return new Money(amount.multiply(BigDecimal.valueOf(multiplier)), currency);
        }

        public boolean isPositiveOrZero() {
            return amount.compareTo(BigDecimal.ZERO) >= 0;
        }

        private void validateCurrency(Money other) {
            if (!currency.equals(other.currency)) {
                throw new IllegalArgumentException("Currency mismatch: " + currency + " vs " + other.currency);
            }
        }

        public BigDecimal getAmount() {
            return amount;
        }

        public Currency getCurrency() {
            return currency;
        }

        @Override
        public String toString() {
            return amount + " " + currency.getCurrencyCode();
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Money)) return false;
            Money money = (Money) o;
            return amount.equals(money.amount) && currency.equals(money.currency);
        }

        @Override
        public int hashCode() {
            return Objects.hash(amount, currency);
        }
    }
}

/* ------------------------------------------------------------------------- */
/*  Auxiliary Converter (isolated outside entity to respect SRP)             */
/* ------------------------------------------------------------------------- */

package com.commercesphere.enterprise.ordering.model;

import jakarta.persistence.AttributeConverter;
import jakarta.persistence.Converter;
import java.util.Currency;

/**
 * JPA AttributeConverter translating {@link Currency} to the ISO 4217 code and
 * back. This allows us to persist currencies as VARCHAR(3) while keeping the
 * type-safe {@code java.util.Currency} in the domain model.
 */
@Converter(autoApply = true)
public class CurrencyAttributeConverter implements AttributeConverter<Currency, String> {

    @Override
    public String convertToDatabaseColumn(Currency attribute) {
        return attribute == null ? null : attribute.getCurrencyCode();
    }

    @Override
    public Currency convertToEntityAttribute(String dbData) {
        return dbData == null ? null : Currency.getInstance(dbData);
    }
}