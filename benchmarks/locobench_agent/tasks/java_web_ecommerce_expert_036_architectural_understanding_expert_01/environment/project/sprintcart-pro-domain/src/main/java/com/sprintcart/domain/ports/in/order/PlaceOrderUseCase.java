package com.sprintcart.domain.ports.in.order;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * Inbound port that represents the "Place Order" use-case.
 *
 * <p>This interface is agnostic of any delivery mechanism (REST, GraphQL, CLI, etc.)
 * and must be implemented by the application service residing in the domain/service
 * layer. Outbound dependencies (payment gateway, inventory service, etc.) must be
 * injected into that service via secondary ports.</p>
 *
 * <p>Typical interaction flow:
 * <ol>
 *     <li>Client creates a {@link PlaceOrderCommand} containing all information
 *         necessary to attempt an order.</li>
 *     <li>Domain service validates the command, performs credit-card authorization,
 *         reserves inventory, and persists the {@code Order} aggregate.</li>
 *     <li>A domain event <em>OrderPlaced</em> is published to notify interested
 *         outbound adapters (email, webhooks, ERP sync, etc.).</li>
 * </ol>
 * </p>
 */
public interface PlaceOrderUseCase {

    /**
     * Attempts to place an order.
     *
     * @param command immutable value object describing the order intention
     * @return confirmation snapshot immutable over time
     *
     * @throws InvalidOrderException         if any business invariants are violated
     * @throws InventoryUnavailableException if requested quantity cannot be fulfilled
     * @throws PaymentFailedException        if payment authorization fails
     */
    OrderConfirmation place(PlaceOrderCommand command)
            throws InvalidOrderException,
                   InventoryUnavailableException,
                   PaymentFailedException;

    /* ====================================================================== */
    /* =============================  COMMAND  ============================== */
    /* ====================================================================== */

    /**
     * Immutable DTO that carries the intent to place an order.
     */
    final class PlaceOrderCommand {

        private final UUID cartId;
        private final UUID customerId;
        private final ShippingAddress shippingAddress;
        private final PaymentDetails paymentDetails;
        private final List<OrderItem> items;

        private PlaceOrderCommand(Builder builder) {
            this.cartId          = builder.cartId;
            this.customerId      = builder.customerId;
            this.shippingAddress = builder.shippingAddress;
            this.paymentDetails  = builder.paymentDetails;
            this.items           = Collections.unmodifiableList(builder.items);

            validateState();
        }

        private void validateState() {
            if (cartId == null) {
                throw new InvalidOrderException("Cart ID must be provided.");
            }
            if (customerId == null) {
                throw new InvalidOrderException("Customer ID must be provided.");
            }
            if (items == null || items.isEmpty()) {
                throw new InvalidOrderException("Order must contain at least one item.");
            }
            BigDecimal total = items.stream()
                                    .map(OrderItem::totalPrice)
                                    .reduce(BigDecimal.ZERO, BigDecimal::add);
            if (total.compareTo(BigDecimal.ZERO) <= 0) {
                throw new InvalidOrderException("Order total must be greater than zero.");
            }
        }

        public UUID getCartId()           { return cartId; }
        public UUID getCustomerId()       { return customerId; }
        public ShippingAddress getShippingAddress() { return shippingAddress; }
        public PaymentDetails getPaymentDetails()   { return paymentDetails; }
        public List<OrderItem> getItems() { return items; }

        /* ---------------------------  Builder  --------------------------- */

        public static Builder builder() { return new Builder(); }

        public static final class Builder {
            private UUID cartId;
            private UUID customerId;
            private ShippingAddress shippingAddress;
            private PaymentDetails paymentDetails;
            private List<OrderItem> items = List.of();

            private Builder() { }

            public Builder cartId(UUID cartId) {
                this.cartId = cartId;
                return this;
            }

            public Builder customerId(UUID customerId) {
                this.customerId = customerId;
                return this;
            }

            public Builder shippingAddress(ShippingAddress address) {
                this.shippingAddress = address;
                return this;
            }

            public Builder paymentDetails(PaymentDetails paymentDetails) {
                this.paymentDetails = paymentDetails;
                return this;
            }

            public Builder items(List<OrderItem> items) {
                this.items = List.copyOf(items);
                return this;
            }

            public PlaceOrderCommand build() {
                return new PlaceOrderCommand(this);
            }
        }
    }

    /* ====================================================================== */
    /* =============================  OUTPUT  =============================== */
    /* ====================================================================== */

    /**
     * Immutable snapshot returned after an order is successfully placed.
     */
    final class OrderConfirmation {

        private final UUID orderId;
        private final Instant placedAt;
        private final BigDecimal grandTotal;
        private final List<OrderItem> orderLines;

        public OrderConfirmation(UUID orderId,
                                 Instant placedAt,
                                 BigDecimal grandTotal,
                                 List<OrderItem> orderLines) {
            this.orderId     = Objects.requireNonNull(orderId, "orderId");
            this.placedAt    = Objects.requireNonNull(placedAt, "placedAt");
            this.grandTotal  = Objects.requireNonNull(grandTotal, "grandTotal");
            this.orderLines  = List.copyOf(orderLines);
        }

        public UUID getOrderId()      { return orderId; }
        public Instant getPlacedAt()  { return placedAt; }
        public BigDecimal getGrandTotal() { return grandTotal; }
        public List<OrderItem> getOrderLines() { return orderLines; }
    }

    /* ====================================================================== */
    /* ==========================  VALUE OBJECTS  =========================== */
    /* ====================================================================== */

    /**
     * Represents a single order line.
     */
    final class OrderItem {

        private final UUID productId;
        private final String sku;
        private final String name;
        private final int quantity;
        private final BigDecimal unitPrice;

        public OrderItem(UUID productId,
                         String sku,
                         String name,
                         int quantity,
                         BigDecimal unitPrice) {

            if (quantity <= 0) {
                throw new InvalidOrderException("Quantity must be positive");
            }
            if (unitPrice == null || unitPrice.compareTo(BigDecimal.ZERO) < 0) {
                throw new InvalidOrderException("Unit price cannot be negative");
            }

            this.productId = Objects.requireNonNull(productId, "productId");
            this.sku       = Objects.requireNonNull(sku, "sku");
            this.name      = Objects.requireNonNull(name, "name");
            this.quantity  = quantity;
            this.unitPrice = unitPrice;
        }

        public UUID getProductId()   { return productId; }
        public String getSku()       { return sku; }
        public String getName()      { return name; }
        public int getQuantity()     { return quantity; }
        public BigDecimal getUnitPrice() { return unitPrice; }

        public BigDecimal totalPrice() {
            return unitPrice.multiply(BigDecimal.valueOf(quantity));
        }
    }

    /**
     * Shipping address value object.
     */
    final class ShippingAddress {

        private final String fullName;
        private final String line1;
        private final String line2;
        private final String city;
        private final String state;
        private final String postalCode;
        private final String country;

        public ShippingAddress(String fullName,
                               String line1,
                               String line2,
                               String city,
                               String state,
                               String postalCode,
                               String country) {

            this.fullName    = Objects.requireNonNull(fullName, "fullName");
            this.line1       = Objects.requireNonNull(line1, "line1");
            this.line2       = line2; // Optional
            this.city        = Objects.requireNonNull(city, "city");
            this.state       = Objects.requireNonNull(state, "state");
            this.postalCode  = Objects.requireNonNull(postalCode, "postalCode");
            this.country     = Objects.requireNonNull(country, "country");
        }

        public String getFullName()   { return fullName; }
        public String getLine1()      { return line1; }
        public String getLine2()      { return line2; }
        public String getCity()       { return city; }
        public String getState()      { return state; }
        public String getPostalCode() { return postalCode; }
        public String getCountry()    { return country; }
    }

    /**
     * Value object that encapsulates payment method details.
     * For security reasons, only tokens or masked identifiers
     * should be exposed here, never raw card numbers.
     */
    final class PaymentDetails {

        private final PaymentMethod method;
        private final String token; // e.g. Stripe payment intent, PayPal order id, etc.

        public PaymentDetails(PaymentMethod method, String token) {
            this.method = Objects.requireNonNull(method, "method");
            this.token  = Objects.requireNonNull(token, "token");
        }

        public PaymentMethod getMethod() { return method; }
        public String getToken()         { return token; }

        public enum PaymentMethod {
            CREDIT_CARD,
            PAYPAL,
            APPLE_PAY,
            GOOGLE_PAY,
            BANK_TRANSFER
        }
    }

    /* ====================================================================== */
    /* ============================  ERRORS  ================================ */
    /* ====================================================================== */

    /**
     * Parent type for all order related domain exceptions.
     * Wrapped in runtime exception to avoid excessive checked-exception pollution.
     */
    class InvalidOrderException extends RuntimeException {
        public InvalidOrderException(String message) { super(message); }
        public InvalidOrderException(String message, Throwable cause) { super(message, cause); }
    }

    /**
     * Thrown when inventory cannot satisfy the requested quantity.
     */
    class InventoryUnavailableException extends Exception {
        public InventoryUnavailableException(String message) { super(message); }
    }

    /**
     * Thrown when payment authorization fails.
     */
    class PaymentFailedException extends Exception {
        public PaymentFailedException(String message) { super(message); }
        public PaymentFailedException(String message, Throwable cause) { super(message, cause); }
    }
}