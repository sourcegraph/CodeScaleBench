package com.commercesphere.enterprise.ordering.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import javax.validation.Validation;
import javax.validation.Validator;
import javax.validation.ValidatorFactory;
import javax.validation.constraints.DecimalMin;
import javax.validation.constraints.FutureOrPresent;
import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;
import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.Collections;
import java.util.Currency;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * QuoteRequestDto represents a request from a B2B buyer to receive a price quote
 * for a set of {@link Item}s. The DTO is intentionally immutable to ensure
 * thread–safety when it is shared across service boundaries.
 *
 * <p>The class supports:</p>
 * <ul>
 *   <li>Bean–Validation for field–level constraints</li>
 *   <li>Jackson annotations for loss-less JSON serialization</li>
 *   <li>A fluent Builder for ergonomic construction</li>
 * </ul>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class QuoteRequestDto implements Serializable {

    @Serial
    private static final long serialVersionUID = -2843214076903810875L;

    private static final Validator VALIDATOR;

    static {
        try (ValidatorFactory factory = Validation.buildDefaultValidatorFactory()) {
            VALIDATOR = factory.getValidator();
        }
    }

    // ------------------------------------------------------------------------
    // Fields
    // ------------------------------------------------------------------------

    @JsonProperty("quoteId")
    private final UUID quoteId;

    @NotNull(message = "Account ID must be provided")
    @JsonProperty("accountId")
    private final String accountId;

    @NotNull(message = "Customer ID must be provided")
    @JsonProperty("customerId")
    private final String customerId;

    @NotEmpty(message = "Quote item list must not be empty")
    @JsonProperty("items")
    private final List<Item> items;

    @NotNull(message = "Currency must not be null")
    @JsonProperty("currency")
    private final Currency currency;

    @JsonProperty("requestedDate")
    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd")
    @FutureOrPresent(message = "Requested date cannot be in the past")
    private final LocalDate requestedDate;

    @JsonProperty("expiresAt")
    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd")
    @FutureOrPresent(message = "Expiration date must be today or in the future")
    private final LocalDate expiresAt;

    @NotNull(message = "RequestedBy must be provided")
    @JsonProperty("requestedBy")
    private final String requestedBy;

    @JsonProperty("status")
    private final QuoteStatus status;

    @JsonProperty("specialInstructions")
    private final String specialInstructions;

    @JsonProperty("createdAt")
    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", timezone = "UTC")
    private final Instant createdAt;

    // ------------------------------------------------------------------------
    // Constructor
    // ------------------------------------------------------------------------

    @JsonCreator
    private QuoteRequestDto(
            @JsonProperty("quoteId") UUID quoteId,
            @JsonProperty("accountId") String accountId,
            @JsonProperty("customerId") String customerId,
            @JsonProperty("items") List<Item> items,
            @JsonProperty("currency") Currency currency,
            @JsonProperty("requestedDate") LocalDate requestedDate,
            @JsonProperty("expiresAt") LocalDate expiresAt,
            @JsonProperty("requestedBy") String requestedBy,
            @JsonProperty("status") QuoteStatus status,
            @JsonProperty("specialInstructions") String specialInstructions,
            @JsonProperty("createdAt") Instant createdAt) {

        this.quoteId = quoteId;
        this.accountId = accountId;
        this.customerId = customerId;
        this.items = Collections.unmodifiableList(items); // defensive copy
        this.currency = currency;
        this.requestedDate = requestedDate;
        this.expiresAt = expiresAt;
        this.requestedBy = requestedBy;
        this.status = status;
        this.specialInstructions = specialInstructions;
        this.createdAt = createdAt != null ? createdAt : Instant.now();

        // fail–fast: verify bean–level constraints early
        VALIDATOR.validate(this).stream()
                 .findFirst()
                 .ifPresent(violation -> {
                     throw new IllegalArgumentException(violation.getPropertyPath() + ": " + violation.getMessage());
                 });
    }

    // ------------------------------------------------------------------------
    // Accessors
    // ------------------------------------------------------------------------

    public UUID getQuoteId() {
        return quoteId;
    }

    public String getAccountId() {
        return accountId;
    }

    public String getCustomerId() {
        return customerId;
    }

    public List<Item> getItems() {
        return items;
    }

    public Currency getCurrency() {
        return currency;
    }

    public LocalDate getRequestedDate() {
        return requestedDate;
    }

    public LocalDate getExpiresAt() {
        return expiresAt;
    }

    public String getRequestedBy() {
        return requestedBy;
    }

    public QuoteStatus getStatus() {
        return status;
    }

    public String getSpecialInstructions() {
        return specialInstructions;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    /**
     * Computes the gross total for this quote request by delegating to the
     * individual {@link Item}s. All monetary fields share the same {@link #currency}.
     */
    @JsonProperty("grandTotal")
    public BigDecimal getGrandTotal() {
        return items.stream()
                    .map(Item::getExtendedPrice)
                    .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    // ------------------------------------------------------------------------
    // Builder
    // ------------------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {

        private UUID quoteId;
        private String accountId;
        private String customerId;
        private List<Item> items;
        private Currency currency;
        private LocalDate requestedDate;
        private LocalDate expiresAt;
        private String requestedBy;
        private QuoteStatus status = QuoteStatus.PENDING;
        private String specialInstructions;
        private Instant createdAt;

        private Builder() {
        }

        public Builder withQuoteId(UUID quoteId) {
            this.quoteId = quoteId;
            return this;
        }

        public Builder withAccountId(String accountId) {
            this.accountId = accountId;
            return this;
        }

        public Builder withCustomerId(String customerId) {
            this.customerId = customerId;
            return this;
        }

        public Builder withItems(List<Item> items) {
            this.items = items;
            return this;
        }

        public Builder withCurrency(Currency currency) {
            this.currency = currency;
            return this;
        }

        public Builder withRequestedDate(LocalDate requestedDate) {
            this.requestedDate = requestedDate;
            return this;
        }

        public Builder withExpiresAt(LocalDate expiresAt) {
            this.expiresAt = expiresAt;
            return this;
        }

        public Builder withRequestedBy(String requestedBy) {
            this.requestedBy = requestedBy;
            return this;
        }

        public Builder withStatus(QuoteStatus status) {
            this.status = status;
            return this;
        }

        public Builder withSpecialInstructions(String specialInstructions) {
            this.specialInstructions = specialInstructions;
            return this;
        }

        public Builder withCreatedAt(Instant createdAt) {
            this.createdAt = createdAt;
            return this;
        }

        public QuoteRequestDto build() {
            return new QuoteRequestDto(
                    quoteId,
                    accountId,
                    customerId,
                    items,
                    currency,
                    requestedDate,
                    expiresAt,
                    requestedBy,
                    status,
                    specialInstructions,
                    createdAt
            );
        }
    }

    // ------------------------------------------------------------------------
    // inner types
    // ------------------------------------------------------------------------

    /**
     * Enumeration of all possible quote lifecycle states. Persisted as an
     * upper-case String (e.g. <code>"APPROVED"</code>) in the database layer.
     */
    public enum QuoteStatus {
        PENDING,
        APPROVED,
        REJECTED,
        EXPIRED,
        CANCELLED
    }

    /**
     * Item describes a single SKU inside a quote request. The class is a minimal
     * carrier for productId, quantity, discount and monetary totals.
     */
    public static final class Item implements Serializable {

        @Serial
        private static final long serialVersionUID = -3739395942530827855L;

        @NotNull
        @JsonProperty("productId")
        private final String productId;

        @DecimalMin(value = "0.0", inclusive = false)
        @JsonProperty("unitPrice")
        private final BigDecimal unitPrice;

        @DecimalMin(value = "0.0")
        @JsonProperty("discount")
        private final BigDecimal discount;

        @DecimalMin(value = "1")
        @JsonProperty("quantity")
        private final int quantity;

        @JsonCreator
        Item(@JsonProperty("productId") String productId,
             @JsonProperty("unitPrice") BigDecimal unitPrice,
             @JsonProperty("discount") BigDecimal discount,
             @JsonProperty("quantity") int quantity) {

            this.productId = Objects.requireNonNull(productId, "productId cannot be null");
            this.unitPrice = Optional.ofNullable(unitPrice)
                                     .filter(price -> price.compareTo(BigDecimal.ZERO) > 0)
                                     .orElseThrow(() -> new IllegalArgumentException("unitPrice must be > 0"));
            this.discount = Optional.ofNullable(discount).orElse(BigDecimal.ZERO);
            if (this.discount.compareTo(BigDecimal.ZERO) < 0) {
                throw new IllegalArgumentException("discount cannot be negative");
            }
            if (quantity <= 0) {
                throw new IllegalArgumentException("quantity must be at least 1");
            }
            this.quantity = quantity;
        }

        public String getProductId() {
            return productId;
        }

        public BigDecimal getUnitPrice() {
            return unitPrice;
        }

        public BigDecimal getDiscount() {
            return discount;
        }

        public int getQuantity() {
            return quantity;
        }

        /**
         * Calculates the extended price: (unitPrice - discount) * quantity.
         */
        @JsonProperty("extendedPrice")
        public BigDecimal getExtendedPrice() {
            return unitPrice.subtract(discount).multiply(BigDecimal.valueOf(quantity));
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Item item)) return false;
            return quantity == item.quantity &&
                   productId.equals(item.productId) &&
                   unitPrice.equals(item.unitPrice) &&
                   discount.equals(item.discount);
        }

        @Override
        public int hashCode() {
            return Objects.hash(productId, unitPrice, discount, quantity);
        }

        @Override
        public String toString() {
            return "Item{" +
                   "productId='" + productId + '\'' +
                   ", unitPrice=" + unitPrice +
                   ", discount=" + discount +
                   ", quantity=" + quantity +
                   '}';
        }
    }

    // ------------------------------------------------------------------------
    // equals / hashCode / toString
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof QuoteRequestDto that)) return false;
        return Objects.equals(quoteId, that.quoteId) &&
               accountId.equals(that.accountId) &&
               customerId.equals(that.customerId) &&
               items.equals(that.items) &&
               currency.equals(that.currency) &&
               requestedDate.equals(that.requestedDate) &&
               expiresAt.equals(that.expiresAt) &&
               requestedBy.equals(that.requestedBy) &&
               status == that.status &&
               Objects.equals(specialInstructions, that.specialInstructions) &&
               createdAt.equals(that.createdAt);
    }

    @Override
    public int hashCode() {
        return Objects.hash(quoteId, accountId, customerId, items, currency, requestedDate,
                            expiresAt, requestedBy, status, specialInstructions, createdAt);
    }

    @Override
    public String toString() {
        return "QuoteRequestDto{" +
               "quoteId=" + quoteId +
               ", accountId='" + accountId + '\'' +
               ", customerId='" + customerId + '\'' +
               ", items=" + items +
               ", currency=" + currency +
               ", requestedDate=" + requestedDate +
               ", expiresAt=" + expiresAt +
               ", requestedBy='" + requestedBy + '\'' +
               ", status=" + status +
               ", specialInstructions='" + specialInstructions + '\'' +
               ", createdAt=" + createdAt +
               '}';
    }

    // ------------------------------------------------------------------------
    // Misc Helpers
    // ------------------------------------------------------------------------

    /**
     * Returns <code>true</code> if this quote has any items with a negative price
     * (which would indicate data corruption on the calling side).
     */
    @JsonIgnore
    public boolean containsInvalidPricing() {
        return items.stream().anyMatch(i -> i.getExtendedPrice().compareTo(BigDecimal.ZERO) < 0);
    }
}