package com.sprintcart.application.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import javax.validation.Valid;
import javax.validation.constraints.*;
import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.*;

/**
 * Data-transfer object representing an {@code Order} in SprintCart Pro.
 *
 * <p>This DTO is crafted for the application/service layer and is therefore
 * intentionally decoupled from both the persistence model and the domain
 * aggregate.  It is safe to use across network boundaries (REST, MQ, etc.)
 * and is forward-compat by marking unknown JSON properties as ignorable at
 * the serialization framework level (configured globally).</p>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class OrderDTO implements Serializable {

    @Serial
    private static final long serialVersionUID = 42L;

    // ------------------------------------------------------------------------
    // Core identifiers & metadata
    // ------------------------------------------------------------------------

    @NotNull
    private final UUID id;

    @NotBlank
    @Size(max = 64)
    private final String orderNumber;

    @PastOrPresent
    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss'Z'", timezone = "UTC")
    private final LocalDateTime createdAt;

    @PastOrPresent
    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss'Z'", timezone = "UTC")
    private final LocalDateTime updatedAt;

    @NotNull
    private final OrderStatus status;

    // ------------------------------------------------------------------------
    // Monetary totals
    // ------------------------------------------------------------------------

    @NotNull @PositiveOrZero
    private final BigDecimal subtotal;

    @NotNull @PositiveOrZero
    private final BigDecimal taxTotal;

    @NotNull @PositiveOrZero
    private final BigDecimal shippingTotal;

    @NotNull @PositiveOrZero
    private final BigDecimal grandTotal;

    @NotNull
    private final Currency currency;

    // ------------------------------------------------------------------------
    // Relationships
    // ------------------------------------------------------------------------

    @NotEmpty
    @Valid
    private final List<OrderItemDTO> items;

    @Valid
    private final CustomerSummaryDTO customer;

    @Valid
    private final AddressDTO shippingAddress;

    @Valid
    private final AddressDTO billingAddress;

    @Valid
    private final PaymentSummaryDTO payment;

    @Valid
    private final FulfillmentSummaryDTO fulfillment;

    // ------------------------------------------------------------------------
    // Construction
    // ------------------------------------------------------------------------

    @JsonCreator
    private OrderDTO(
            @JsonProperty("id")                   UUID id,
            @JsonProperty("orderNumber")          String orderNumber,
            @JsonProperty("createdAt")            LocalDateTime createdAt,
            @JsonProperty("updatedAt")            LocalDateTime updatedAt,
            @JsonProperty("status")               OrderStatus status,
            @JsonProperty("subtotal")             BigDecimal subtotal,
            @JsonProperty("taxTotal")             BigDecimal taxTotal,
            @JsonProperty("shippingTotal")        BigDecimal shippingTotal,
            @JsonProperty("grandTotal")           BigDecimal grandTotal,
            @JsonProperty("currency")             Currency currency,
            @JsonProperty("items")                List<OrderItemDTO> items,
            @JsonProperty("customer")             CustomerSummaryDTO customer,
            @JsonProperty("shippingAddress")      AddressDTO shippingAddress,
            @JsonProperty("billingAddress")       AddressDTO billingAddress,
            @JsonProperty("payment")              PaymentSummaryDTO payment,
            @JsonProperty("fulfillment")          FulfillmentSummaryDTO fulfillment
    ) {
        this.id               = Objects.requireNonNull(id,              "id");
        this.orderNumber      = Objects.requireNonNull(orderNumber,     "orderNumber");
        this.createdAt        = Objects.requireNonNull(createdAt,       "createdAt");
        this.updatedAt        = Objects.requireNonNullElse(updatedAt,   createdAt);
        this.status           = Objects.requireNonNull(status,          "status");
        this.subtotal         = Objects.requireNonNull(subtotal,        "subtotal");
        this.taxTotal         = Objects.requireNonNull(taxTotal,        "taxTotal");
        this.shippingTotal    = Objects.requireNonNull(shippingTotal,   "shippingTotal");
        this.grandTotal       = Objects.requireNonNull(grandTotal,      "grandTotal");
        this.currency         = Objects.requireNonNull(currency,        "currency");
        this.items            = Collections.unmodifiableList(
                                    new ArrayList<>(Objects.requireNonNull(items, "items")));
        this.customer         = customer;
        this.shippingAddress  = shippingAddress;
        this.billingAddress   = billingAddress;
        this.payment          = payment;
        this.fulfillment      = fulfillment;
    }

    // ------------------------------------------------------------------------
    // Builder
    // ------------------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private UUID id;
        private String orderNumber;
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
        private OrderStatus status = OrderStatus.PENDING;

        private BigDecimal subtotal       = BigDecimal.ZERO;
        private BigDecimal taxTotal       = BigDecimal.ZERO;
        private BigDecimal shippingTotal  = BigDecimal.ZERO;
        private BigDecimal grandTotal     = BigDecimal.ZERO;
        private Currency currency         = Currency.getInstance(Locale.US);

        private List<OrderItemDTO> items  = new ArrayList<>();
        private CustomerSummaryDTO customer;
        private AddressDTO shippingAddress;
        private AddressDTO billingAddress;
        private PaymentSummaryDTO payment;
        private FulfillmentSummaryDTO fulfillment;

        private Builder() {}

        public Builder id(UUID id) { this.id = id; return this; }
        public Builder orderNumber(String orderNumber) { this.orderNumber = orderNumber; return this; }
        public Builder createdAt(LocalDateTime createdAt) { this.createdAt = createdAt; return this; }
        public Builder updatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; return this; }
        public Builder status(OrderStatus status) { this.status = status; return this; }

        public Builder subtotal(BigDecimal subtotal) { this.subtotal = subtotal; return this; }
        public Builder taxTotal(BigDecimal taxTotal) { this.taxTotal = taxTotal; return this; }
        public Builder shippingTotal(BigDecimal shippingTotal) { this.shippingTotal = shippingTotal; return this; }
        public Builder grandTotal(BigDecimal grandTotal) { this.grandTotal = grandTotal; return this; }
        public Builder currency(Currency currency) { this.currency = currency; return this; }

        public Builder items(List<OrderItemDTO> items) { this.items = items; return this; }
        public Builder addItem(OrderItemDTO item) { this.items.add(item); return this; }

        public Builder customer(CustomerSummaryDTO customer) { this.customer = customer; return this; }
        public Builder shippingAddress(AddressDTO shippingAddress) { this.shippingAddress = shippingAddress; return this; }
        public Builder billingAddress(AddressDTO billingAddress) { this.billingAddress = billingAddress; return this; }
        public Builder payment(PaymentSummaryDTO payment) { this.payment = payment; return this; }
        public Builder fulfillment(FulfillmentSummaryDTO fulfillment) { this.fulfillment = fulfillment; return this; }

        public OrderDTO build() {
            return new OrderDTO(
                    id           != null ? id : UUID.randomUUID(),
                    orderNumber  != null ? orderNumber : createFriendlyNumber(),
                    createdAt    != null ? createdAt : LocalDateTime.now(),
                    updatedAt,
                    status,
                    subtotal,
                    taxTotal,
                    shippingTotal,
                    grandTotal.compareTo(BigDecimal.ZERO) == 0
                            ? subtotal.add(taxTotal).add(shippingTotal)
                            : grandTotal,
                    currency,
                    items,
                    customer,
                    shippingAddress,
                    billingAddress,
                    payment,
                    fulfillment
            );
        }

        /**
         * Generates a human-friendly order number (e.g. SC-20240101-00042).
         * <p>NOTE: In production this would likely be delegated to a domain service
         * or database sequence to guarantee uniqueness across shards.</p>
         */
        private static String createFriendlyNumber() {
            return "SC-" + LocalDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"));
        }
    }

    // ------------------------------------------------------------------------
    // Accessors
    // ------------------------------------------------------------------------

    public UUID getId()                               { return id; }
    public String getOrderNumber()                    { return orderNumber; }
    public LocalDateTime getCreatedAt()               { return createdAt; }
    public LocalDateTime getUpdatedAt()               { return updatedAt; }
    public OrderStatus getStatus()                    { return status; }

    public BigDecimal getSubtotal()                   { return subtotal; }
    public BigDecimal getTaxTotal()                   { return taxTotal; }
    public BigDecimal getShippingTotal()              { return shippingTotal; }
    public BigDecimal getGrandTotal()                 { return grandTotal; }
    public Currency getCurrency()                     { return currency; }

    public List<OrderItemDTO> getItems()              { return items; }
    public CustomerSummaryDTO getCustomer()           { return customer; }
    public AddressDTO getShippingAddress()            { return shippingAddress; }
    public AddressDTO getBillingAddress()             { return billingAddress; }
    public PaymentSummaryDTO getPayment()             { return payment; }
    public FulfillmentSummaryDTO getFulfillment()     { return fulfillment; }

    // ------------------------------------------------------------------------
    // Value semantics
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        return (this == o) ||
               (o instanceof OrderDTO other && Objects.equals(id, other.id));
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "OrderDTO{" +
               "id=" + id +
               ", orderNumber='" + orderNumber + '\'' +
               ", status=" + status +
               '}';
    }

    // ------------------------------------------------------------------------
    // Nested Types
    // ------------------------------------------------------------------------

    public enum OrderStatus {
        PENDING, PAID, FULFILLED, CANCELLED, REFUNDED
    }

    /**
     * Condensed representation of an {@code OrderItem}. This does not attempt to
     * be exhaustive; its purpose is to service read-heavy views quickly while
     * avoiding large graph serialization.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class OrderItemDTO implements Serializable {
        @Serial private static final long serialVersionUID = 1L;

        @NotNull           private final UUID productId;
        @NotBlank          private final String sku;
        @Positive          private final int quantity;
        @PositiveOrZero    private final BigDecimal unitPrice;
        @PositiveOrZero    private final BigDecimal lineTotal;

        @JsonCreator
        public OrderItemDTO(
                @JsonProperty("productId") UUID productId,
                @JsonProperty("sku")       String sku,
                @JsonProperty("quantity")  int quantity,
                @JsonProperty("unitPrice") BigDecimal unitPrice,
                @JsonProperty("lineTotal") BigDecimal lineTotal
        ) {
            this.productId = productId;
            this.sku       = sku;
            this.quantity  = quantity;
            this.unitPrice = unitPrice;
            this.lineTotal = lineTotal != null ? lineTotal : unitPrice.multiply(BigDecimal.valueOf(quantity));
        }

        public UUID getProductId()  { return productId; }
        public String getSku()      { return sku; }
        public int getQuantity()    { return quantity; }
        public BigDecimal getUnitPrice() { return unitPrice; }
        public BigDecimal getLineTotal() { return lineTotal; }
    }

    /**
     * Lightweight representation of a customer.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class CustomerSummaryDTO implements Serializable {
        @Serial private static final long serialVersionUID = 1L;

        @NotNull  private final UUID customerId;
        @Email    private final String email;
        @Size(max = 64) private final String firstName;
        @Size(max = 64) private final String lastName;

        @JsonCreator
        public CustomerSummaryDTO(
                @JsonProperty("customerId") UUID customerId,
                @JsonProperty("email")      String email,
                @JsonProperty("firstName")  String firstName,
                @JsonProperty("lastName")   String lastName
        ) {
            this.customerId = customerId;
            this.email      = email;
            this.firstName  = firstName;
            this.lastName   = lastName;
        }

        public UUID getCustomerId() { return customerId; }
        public String getEmail()    { return email; }
        public String getFirstName(){ return firstName; }
        public String getLastName() { return lastName; }
    }

    /**
     * Immutable address DTO reused for both billing and shipping contexts.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class AddressDTO implements Serializable {
        @Serial private static final long serialVersionUID = 1L;

        @NotBlank private final String line1;
        private final String line2;
        @NotBlank private final String city;
        @NotBlank private final String state;
        @NotBlank private final String postalCode;
        @NotBlank private final String countryCode;

        @JsonCreator
        public AddressDTO(
                @JsonProperty("line1")       String line1,
                @JsonProperty("line2")       String line2,
                @JsonProperty("city")        String city,
                @JsonProperty("state")       String state,
                @JsonProperty("postalCode")  String postalCode,
                @JsonProperty("countryCode") String countryCode
        ) {
            this.line1       = line1;
            this.line2       = line2;
            this.city        = city;
            this.state       = state;
            this.postalCode  = postalCode;
            this.countryCode = countryCode;
        }

        public String getLine1()       { return line1; }
        public String getLine2()       { return line2; }
        public String getCity()        { return city; }
        public String getState()       { return state; }
        public String getPostalCode()  { return postalCode; }
        public String getCountryCode() { return countryCode; }
    }

    /**
     * Short representation of a payment record attached to an order.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class PaymentSummaryDTO implements Serializable {
        @Serial private static final long serialVersionUID = 1L;

        @NotNull private final UUID paymentId;
        @NotBlank private final String provider;
        private final String transactionId;

        @PastOrPresent
        @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss'Z'", timezone = "UTC")
        private final LocalDateTime paidAt;
        @PositiveOrZero private final BigDecimal amount;

        @JsonCreator
        public PaymentSummaryDTO(
                @JsonProperty("paymentId")     UUID paymentId,
                @JsonProperty("provider")      String provider,
                @JsonProperty("transactionId") String transactionId,
                @JsonProperty("paidAt")        LocalDateTime paidAt,
                @JsonProperty("amount")        BigDecimal amount
        ) {
            this.paymentId     = paymentId;
            this.provider      = provider;
            this.transactionId = transactionId;
            this.paidAt        = paidAt;
            this.amount        = amount;
        }

        public UUID getPaymentId()      { return paymentId; }
        public String getProvider()     { return provider; }
        public String getTransactionId(){ return transactionId; }
        public LocalDateTime getPaidAt(){ return paidAt; }
        public BigDecimal getAmount()   { return amount; }
    }

    /**
     * Short representation of fulfillment information.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class FulfillmentSummaryDTO implements Serializable {
        @Serial private static final long serialVersionUID = 1L;

        @NotNull private final UUID fulfillmentId;
        private final String carrier;
        private final String trackingNumber;

        @PastOrPresent
        @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss'Z'", timezone = "UTC")
        private final LocalDateTime shippedAt;

        @PastOrPresent
        @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss'Z'", timezone = "UTC")
        private final LocalDateTime deliveredAt;

        private final FulfillmentStatus status;

        @JsonCreator
        public FulfillmentSummaryDTO(
                @JsonProperty("fulfillmentId")  UUID fulfillmentId,
                @JsonProperty("carrier")        String carrier,
                @JsonProperty("trackingNumber") String trackingNumber,
                @JsonProperty("shippedAt")      LocalDateTime shippedAt,
                @JsonProperty("deliveredAt")    LocalDateTime deliveredAt,
                @JsonProperty("status")         FulfillmentStatus status
        ) {
            this.fulfillmentId = fulfillmentId;
            this.carrier       = carrier;
            this.trackingNumber= trackingNumber;
            this.shippedAt     = shippedAt;
            this.deliveredAt   = deliveredAt;
            this.status        = status != null ? status : FulfillmentStatus.PENDING;
        }

        public UUID getFulfillmentId()  { return fulfillmentId; }
        public String getCarrier()      { return carrier; }
        public String getTrackingNumber(){ return trackingNumber; }
        public LocalDateTime getShippedAt(){ return shippedAt; }
        public LocalDateTime getDeliveredAt(){ return deliveredAt; }
        public FulfillmentStatus getStatus(){ return status; }

        public enum FulfillmentStatus {
            PENDING, SHIPPED, DELIVERED, RETURNED
        }
    }
}