package com.commercesphere.enterprise.ordering.dto;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Currency;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import javax.validation.Valid;
import javax.validation.constraints.DecimalMin;
import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;
import javax.validation.constraints.Positive;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonPropertyOrder;

/**
 * OrderDto is a *data-transfer object* representing an immutable snapshot of an
 * {@code Order} aggregate at a specific point in time.  The DTO is purposely
 * devoid of any business logic so that it can be serialized across process
 * boundaries (REST, messaging, etc.) without pulling in the heavyweight domain
 * model.
 *
 * The class is designed to be:
 *   • Immutable (all setters are private and invoked only by {@link Builder})  
 *   • Serializable (implements {@link Serializable})  
 *   • JSON-friendly (Jackson annotations)  
 *   • Bean-Validation ready (JSR-380 annotations)  
 *
 * When evolving this DTO, keep in mind that it is part of *public contract*
 * and therefore must remain backwards compatible. Always *add* fields—never
 * rename or remove—unless a version bump is coordinated with all downstream
 * consumers (mobile apps, 3rd-party integrations, legacy batch jobs, etc.).
 */
@JsonPropertyOrder({
        "orderId",
        "customerId",
        "status",
        "currency",
        "totalAmount",
        "orderLines",
        "billingAddress",
        "shippingAddress",
        "createdAt",
        "lastModifiedAt",
        "version"
})
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class OrderDto implements Serializable {

    @Serial
    private static final long serialVersionUID = 7811273342264150150L;

    // -----------------------------------------------------------------------
    // Core identifiers
    // -----------------------------------------------------------------------
    @NotNull
    private final UUID orderId;

    @NotNull
    private final UUID customerId;

    @NotNull
    private final OrderStatus status;

    // -----------------------------------------------------------------------
    // Monetary information
    // -----------------------------------------------------------------------
    @NotNull
    private final Currency currency;

    @NotNull
    @DecimalMin(value = "0.00", inclusive = true, message = "Total must be non-negative")
    private final BigDecimal totalAmount;

    // -----------------------------------------------------------------------
    // Order composition
    // -----------------------------------------------------------------------
    @NotEmpty
    @Valid
    private final List<OrderLineDto> orderLines;

    // -----------------------------------------------------------------------
    // Addresses
    // -----------------------------------------------------------------------
    @NotNull @Valid
    private final AddressDto billingAddress;

    @NotNull @Valid
    private final AddressDto shippingAddress;

    // -----------------------------------------------------------------------
    // Audit
    // -----------------------------------------------------------------------
    @NotNull
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    private final Instant createdAt;

    @NotNull
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    private final Instant lastModifiedAt;

    @Positive
    private final long version;

    // -----------------------------------------------------------------------
    // Constructor (package-private). Invoked by Builder & Jackson.
    // -----------------------------------------------------------------------
    @JsonCreator
    OrderDto(
            @JsonProperty("orderId") UUID orderId,
            @JsonProperty("customerId") UUID customerId,
            @JsonProperty("status") OrderStatus status,
            @JsonProperty("currency") Currency currency,
            @JsonProperty("totalAmount") BigDecimal totalAmount,
            @JsonProperty("orderLines") List<OrderLineDto> orderLines,
            @JsonProperty("billingAddress") AddressDto billingAddress,
            @JsonProperty("shippingAddress") AddressDto shippingAddress,
            @JsonProperty("createdAt") Instant createdAt,
            @JsonProperty("lastModifiedAt") Instant lastModifiedAt,
            @JsonProperty("version") long version) {

        this.orderId = orderId;
        this.customerId = customerId;
        this.status = status;
        this.currency = currency;
        this.totalAmount = totalAmount;
        this.orderLines = orderLines == null ? List.of() : List.copyOf(orderLines);
        this.billingAddress = billingAddress;
        this.shippingAddress = shippingAddress;
        this.createdAt = createdAt;
        this.lastModifiedAt = lastModifiedAt;
        this.version = version;
    }

    // -----------------------------------------------------------------------
    // Getters (no setters to enforce immutability)
    // -----------------------------------------------------------------------
    public UUID getOrderId() {
        return orderId;
    }

    public UUID getCustomerId() {
        return customerId;
    }

    public OrderStatus getStatus() {
        return status;
    }

    public Currency getCurrency() {
        return currency;
    }

    public BigDecimal getTotalAmount() {
        return totalAmount;
    }

    public List<OrderLineDto> getOrderLines() {
        return orderLines;
    }

    public AddressDto getBillingAddress() {
        return billingAddress;
    }

    public AddressDto getShippingAddress() {
        return shippingAddress;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getLastModifiedAt() {
        return lastModifiedAt;
    }

    public long getVersion() {
        return version;
    }

    // -----------------------------------------------------------------------
    // Equality & HashCode
    // -----------------------------------------------------------------------
    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof OrderDto that)) return false;
        return version == that.version
                && Objects.equals(orderId, that.orderId)
                && Objects.equals(customerId, that.customerId)
                && status == that.status
                && Objects.equals(currency, that.currency)
                && Objects.equals(totalAmount, that.totalAmount)
                && Objects.equals(orderLines, that.orderLines)
                && Objects.equals(billingAddress, that.billingAddress)
                && Objects.equals(shippingAddress, that.shippingAddress)
                && Objects.equals(createdAt, that.createdAt)
                && Objects.equals(lastModifiedAt, that.lastModifiedAt);
    }

    @Override
    public int hashCode() {
        return Objects.hash(orderId,
                customerId,
                status,
                currency,
                totalAmount,
                orderLines,
                billingAddress,
                shippingAddress,
                createdAt,
                lastModifiedAt,
                version);
    }

    @Override
    public String toString() {
        return "OrderDto{" +
                "orderId=" + orderId +
                ", customerId=" + customerId +
                ", status=" + status +
                ", currency=" + currency +
                ", totalAmount=" + totalAmount +
                ", orderLines=" + orderLines +
                ", billingAddress=" + billingAddress +
                ", shippingAddress=" + shippingAddress +
                ", createdAt=" + createdAt +
                ", lastModifiedAt=" + lastModifiedAt +
                ", version=" + version +
                '}';
    }

    // -----------------------------------------------------------------------
    // Builder
    // -----------------------------------------------------------------------
    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private UUID orderId;
        private UUID customerId;
        private OrderStatus status = OrderStatus.NEW;
        private Currency currency = Currency.getInstance("USD");
        private BigDecimal totalAmount = BigDecimal.ZERO;
        private List<OrderLineDto> orderLines = new ArrayList<>();
        private AddressDto billingAddress;
        private AddressDto shippingAddress;
        private Instant createdAt = Instant.now();
        private Instant lastModifiedAt = Instant.now();
        private long version = 1L;

        public Builder orderId(UUID orderId) {
            this.orderId = orderId;
            return this;
        }

        public Builder customerId(UUID customerId) {
            this.customerId = customerId;
            return this;
        }

        public Builder status(OrderStatus status) {
            this.status = status;
            return this;
        }

        public Builder currency(Currency currency) {
            this.currency = currency;
            return this;
        }

        public Builder totalAmount(BigDecimal totalAmount) {
            this.totalAmount = totalAmount;
            return this;
        }

        public Builder addOrderLine(OrderLineDto orderLine) {
            this.orderLines.add(orderLine);
            return this;
        }

        public Builder orderLines(List<OrderLineDto> orderLines) {
            this.orderLines = new ArrayList<>(orderLines);
            return this;
        }

        public Builder billingAddress(AddressDto billingAddress) {
            this.billingAddress = billingAddress;
            return this;
        }

        public Builder shippingAddress(AddressDto shippingAddress) {
            this.shippingAddress = shippingAddress;
            return this;
        }

        public Builder createdAt(Instant createdAt) {
            this.createdAt = createdAt;
            return this;
        }

        public Builder lastModifiedAt(Instant lastModifiedAt) {
            this.lastModifiedAt = lastModifiedAt;
            return this;
        }

        public Builder version(long version) {
            this.version = version;
            return this;
        }

        /**
         * Finalizes the builder producing an immutable {@link OrderDto}.
         *
         * @throws IllegalStateException when mandatory fields are missing
         */
        public OrderDto build() {
            // rudimentary sanity check
            if (orderId == null) {
                orderId = UUID.randomUUID();
            }
            if (customerId == null) {
                throw new IllegalStateException("customerId must be supplied");
            }
            if (billingAddress == null) {
                throw new IllegalStateException("billingAddress must be supplied");
            }
            if (shippingAddress == null) {
                throw new IllegalStateException("shippingAddress must be supplied");
            }

            // compute total if caller forgot
            if (totalAmount.compareTo(BigDecimal.ZERO) == 0 && !orderLines.isEmpty()) {
                totalAmount = orderLines.stream()
                                        .map(ol -> ol.getUnitPrice().multiply(BigDecimal.valueOf(ol.getQuantity())))
                                        .reduce(BigDecimal.ZERO, BigDecimal::add);
            }

            return new OrderDto(
                    orderId,
                    customerId,
                    status,
                    currency,
                    totalAmount,
                    orderLines,
                    billingAddress,
                    shippingAddress,
                    createdAt,
                    lastModifiedAt,
                    version
            );
        }
    }

    // =======================================================================
    // Sub-DTOs and Enums (Ideally in their own files but included here for
    // brevity and single-file requirement).
    // =======================================================================

    /**
     * Minimalistic OrderLine representation.
     */
    public static final class OrderLineDto implements Serializable {
        @Serial private static final long serialVersionUID = 3936675406936513103L;

        @NotNull private final UUID productId;
        @NotNull @DecimalMin("0.00") private final BigDecimal unitPrice;
        @Positive private final int quantity;
        @NotEmpty private final String sku;

        @JsonCreator
        public OrderLineDto(
                @JsonProperty("productId") UUID productId,
                @JsonProperty("unitPrice") BigDecimal unitPrice,
                @JsonProperty("quantity") int quantity,
                @JsonProperty("sku") String sku) {
            this.productId = productId;
            this.unitPrice = unitPrice;
            this.quantity = quantity;
            this.sku = sku;
        }

        public UUID getProductId() { return productId; }
        public BigDecimal getUnitPrice() { return unitPrice; }
        public int getQuantity() { return quantity; }
        public String getSku() { return sku; }

        @Override
        public String toString() {
            return "OrderLineDto{" +
                    "productId=" + productId +
                    ", unitPrice=" + unitPrice +
                    ", quantity=" + quantity +
                    ", sku='" + sku + '\'' +
                    '}';
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof OrderLineDto that)) return false;
            return quantity == that.quantity
                    && Objects.equals(productId, that.productId)
                    && Objects.equals(unitPrice, that.unitPrice)
                    && Objects.equals(sku, that.sku);
        }

        @Override
        public int hashCode() {
            return Objects.hash(productId, unitPrice, quantity, sku);
        }
    }

    /**
     * Minimalistic Address representation.
     */
    public static final class AddressDto implements Serializable {
        @Serial private static final long serialVersionUID = 1267810577122215066L;

        @NotEmpty private final String street;
        @NotEmpty private final String city;
        @NotEmpty private final String state;
        @NotEmpty private final String postalCode;
        @NotEmpty private final String country;

        @JsonCreator
        public AddressDto(@JsonProperty("street") String street,
                          @JsonProperty("city") String city,
                          @JsonProperty("state") String state,
                          @JsonProperty("postalCode") String postalCode,
                          @JsonProperty("country") String country) {
            this.street = street;
            this.city = city;
            this.state = state;
            this.postalCode = postalCode;
            this.country = country;
        }

        public String getStreet() { return street; }
        public String getCity() { return city; }
        public String getState() { return state; }
        public String getPostalCode() { return postalCode; }
        public String getCountry() { return country; }

        @Override
        public String toString() {
            return "AddressDto{" +
                    "street='" + street + '\'' +
                    ", city='" + city + '\'' +
                    ", state='" + state + '\'' +
                    ", postalCode='" + postalCode + '\'' +
                    ", country='" + country + '\'' +
                    '}';
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof AddressDto that)) return false;
            return Objects.equals(street, that.street)
                    && Objects.equals(city, that.city)
                    && Objects.equals(state, that.state)
                    && Objects.equals(postalCode, that.postalCode)
                    && Objects.equals(country, that.country);
        }

        @Override
        public int hashCode() {
            return Objects.hash(street, city, state, postalCode, country);
        }
    }

    /**
     * Enumeration of high-level *Order state transitions* used by CommerceSphere.
     */
    public enum OrderStatus {
        NEW,
        PENDING_PAYMENT,
        PAYMENT_FAILED,
        PROCESSING,
        READY_FOR_SHIPMENT,
        SHIPPED,
        CANCELLED,
        COMPLETE,
        REFUNDED
    }
}