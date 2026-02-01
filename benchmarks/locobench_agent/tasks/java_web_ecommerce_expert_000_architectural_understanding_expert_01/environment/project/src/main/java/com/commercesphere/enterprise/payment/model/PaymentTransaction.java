package com.commercesphere.enterprise.payment.model;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;

import javax.persistence.*;
import javax.validation.constraints.Digits;
import javax.validation.constraints.NotNull;
import javax.validation.constraints.Size;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Currency;
import java.util.Objects;

/**
 * JPA entity that represents a single payment transaction within the
 * CommerceSphere Enterprise Suite. This model is intentionally rich,
 * providing enough metadata to support reconciliation, charge backs,
 * fraud analytics and compliance reporting (PCI-DSS).
 *
 * Note: Only non-sensitive data is persisted here. Sensitive card data
 * is tokenized and stored off-platform in a PCI vault.
 */
@Entity
@Table(
        name = "payment_transaction",
        indexes = {
                @Index(name = "idx_payment_txn_ext_id", columnList = "external_txn_id"),
                @Index(name = "idx_payment_txn_order_ref", columnList = "order_reference")
        }
)
public class PaymentTransaction implements Serializable {

    private static final long serialVersionUID = -4042988476299993498L;

    // ----------------------------------------------------------------
    // Primary metadata
    // ----------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Functional order reference (not FK) to decouple the payments
     * subsystem from the order lifecycle. This allows failed payments
     * to exist without a persisted Order row.
     */
    @Column(name = "order_reference", nullable = false, length = 64, updatable = false)
    @Size(min = 1, max = 64)
    private String orderReference;

    @Column(name = "external_txn_id", length = 128, unique = true)
    private String externalTransactionId;

    // ----------------------------------------------------------------
    // Financial details
    // ----------------------------------------------------------------

    @Column(name = "amount", nullable = false, precision = 19, scale = 4)
    @NotNull
    @Digits(integer = 15, fraction = 4)
    private BigDecimal amount;

    @Column(name = "currency", nullable = false, length = 3)
    @Convert(converter = CurrencyAttributeConverter.class)
    private Currency currency;

    // ----------------------------------------------------------------
    // Classification
    // ----------------------------------------------------------------

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private Status status = Status.INITIATED;

    @Enumerated(EnumType.STRING)
    @Column(name = "payment_method", nullable = false, length = 32)
    private Method paymentMethod;

    @Enumerated(EnumType.STRING)
    @Column(name = "payment_channel", nullable = false, length = 32)
    private Channel paymentChannel;

    /**
     * e.g. "Adyen", "Stripe", "Braintree"
     */
    @Column(name = "provider", nullable = false, length = 32)
    private String provider;

    // ----------------------------------------------------------------
    // Auditing
    // ----------------------------------------------------------------

    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSSX", timezone = "UTC")
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSSX", timezone = "UTC")
    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    /**
     * Optimistic locking column.
     */
    @Version
    @Column(name = "version", nullable = false)
    @JsonIgnore
    private long version;

    // ----------------------------------------------------------------
    // Constructors
    // ----------------------------------------------------------------

    protected PaymentTransaction() {
        /* JPA-spec requires a default ctor. */
    }

    private PaymentTransaction(Builder builder) {
        this.orderReference = builder.orderReference;
        this.externalTransactionId = builder.externalTransactionId;
        this.amount = builder.amount;
        this.currency = builder.currency;
        this.status = builder.status;
        this.paymentMethod = builder.paymentMethod;
        this.paymentChannel = builder.paymentChannel;
        this.provider = builder.provider;
    }

    // ----------------------------------------------------------------
    // Business helpers
    // ----------------------------------------------------------------

    /**
     * Returns true if the transaction can no longer be modified
     * (captured, refunded, etc.).
     */
    @JsonProperty
    public boolean isSettled() {
        return Status.CAPTURED.equals(status)
                || Status.REFUNDED.equals(status)
                || Status.CANCELLED.equals(status);
    }

    /**
     * Convenience method used by services to transition state.  Will throw
     * IllegalStateException if the transition is considered invalid.
     */
    public void transitionTo(Status targetStatus) {
        if (!status.canTransitionTo(targetStatus)) {
            throw new IllegalStateException(
                    String.format("Illegal state transition %s -> %s", status, targetStatus));
        }
        this.status = targetStatus;
    }

    // ----------------------------------------------------------------
    // JPA callbacks
    // ----------------------------------------------------------------

    @PrePersist
    private void onCreate() {
        Instant now = Instant.now();
        this.createdAt = now;
        this.updatedAt = now;
    }

    @PreUpdate
    private void onUpdate() {
        this.updatedAt = Instant.now();
    }

    // ----------------------------------------------------------------
    // Getters / Setters
    // ----------------------------------------------------------------

    public Long getId() {
        return id;
    }

    public String getOrderReference() {
        return orderReference;
    }

    public String getExternalTransactionId() {
        return externalTransactionId;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public Currency getCurrency() {
        return currency;
    }

    public Status getStatus() {
        return status;
    }

    public Method getPaymentMethod() {
        return paymentMethod;
    }

    public Channel getPaymentChannel() {
        return paymentChannel;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public String getProvider() {
        return provider;
    }

    public long getVersion() {
        return version;
    }

    // ----------------------------------------------------------------
    // Equality / HashCode
    // ----------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof PaymentTransaction)) return false;
        PaymentTransaction that = (PaymentTransaction) o;
        return Objects.equals(externalTransactionId, that.externalTransactionId)
                && Objects.equals(orderReference, that.orderReference);
    }

    @Override
    public int hashCode() {
        return Objects.hash(externalTransactionId, orderReference);
    }

    @Override
    public String toString() {
        return "PaymentTransaction{" +
                "id=" + id +
                ", orderReference='" + orderReference + '\'' +
                ", externalTransactionId='" + externalTransactionId + '\'' +
                ", amount=" + amount +
                ", currency=" + currency +
                ", status=" + status +
                ", paymentMethod=" + paymentMethod +
                ", paymentChannel=" + paymentChannel +
                ", provider='" + provider + '\'' +
                ", createdAt=" + createdAt +
                ", updatedAt=" + updatedAt +
                '}';
    }

    // ----------------------------------------------------------------
    // Builder
    // ----------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {

        private String orderReference;
        private String externalTransactionId;
        private BigDecimal amount;
        private Currency currency;
        private Status status = Status.INITIATED;
        private Method paymentMethod;
        private Channel paymentChannel;
        private String provider;

        private Builder() {
        }

        public Builder orderReference(String orderReference) {
            this.orderReference = orderReference;
            return this;
        }

        public Builder externalTransactionId(String externalTransactionId) {
            this.externalTransactionId = externalTransactionId;
            return this;
        }

        public Builder amount(BigDecimal amount) {
            this.amount = amount;
            return this;
        }

        public Builder currency(Currency currency) {
            this.currency = currency;
            return this;
        }

        public Builder status(Status status) {
            this.status = status;
            return this;
        }

        public Builder paymentMethod(Method paymentMethod) {
            this.paymentMethod = paymentMethod;
            return this;
        }

        public Builder paymentChannel(Channel paymentChannel) {
            this.paymentChannel = paymentChannel;
            return this;
        }

        public Builder provider(String provider) {
            this.provider = provider;
            return this;
        }

        public PaymentTransaction build() {
            Objects.requireNonNull(orderReference, "orderReference is required");
            Objects.requireNonNull(amount, "amount is required");
            Objects.requireNonNull(currency, "currency is required");
            Objects.requireNonNull(paymentMethod, "paymentMethod is required");
            Objects.requireNonNull(paymentChannel, "paymentChannel is required");
            Objects.requireNonNull(provider, "provider is required");

            return new PaymentTransaction(this);
        }
    }

    // ----------------------------------------------------------------
    // Enums
    // ----------------------------------------------------------------

    /**
     * High-level status enumeration reflecting the transaction’s current
     * state within the payment lifecycle.
     */
    public enum Status {
        INITIATED,
        AUTHORIZED,
        CAPTURED,
        DECLINED,
        REFUNDED,
        CANCELLED,
        ERROR;

        /**
         * Defines a basic state machine for legitimate transitions.
         * Feel free to evolve this as the orchestration rules grow.
         */
        public boolean canTransitionTo(Status target) {
            switch (this) {
                case INITIATED:
                    return target == AUTHORIZED || target == DECLINED || target == ERROR;
                case AUTHORIZED:
                    return target == CAPTURED || target == CANCELLED || target == ERROR;
                case CAPTURED:
                    return target == REFUNDED || target == ERROR;
                case DECLINED:
                case CANCELLED:
                case REFUNDED:
                case ERROR:
                    return false;
                default:
                    return false;
            }
        }
    }

    public enum Method {
        CREDIT_CARD,
        ACH,
        WIRE_TRANSFER,
        PURCHASE_ORDER,
        PAYPAL,
        APPLE_PAY
    }

    public enum Channel {
        WEB,
        MOBILE_APP,
        CUSTOMER_SERVICE,
        BATCH_JOB
    }

    // ----------------------------------------------------------------
    // Attribute converter(s)
    // ----------------------------------------------------------------

    /**
     * JPA {@link AttributeConverter} that maps {@link Currency} to its ISO-4217
     * currency code (e.g., "USD").
     */
    @Converter(autoApply = true)
    static class CurrencyAttributeConverter implements AttributeConverter<Currency, String> {

        @Override
        public String convertToDatabaseColumn(Currency attribute) {
            return attribute == null ? null : attribute.getCurrencyCode();
        }

        @Override
        public Currency convertToEntityAttribute(String dbData) {
            return dbData == null ? null : Currency.getInstance(dbData);
        }
    }
}