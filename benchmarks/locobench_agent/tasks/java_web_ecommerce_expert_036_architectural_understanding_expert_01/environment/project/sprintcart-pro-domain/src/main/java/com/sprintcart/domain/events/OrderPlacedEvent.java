package com.sprintcart.domain.events;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Collections;
import java.util.Currency;
import java.util.List;
import java.util.Objects;
import java.util.StringJoiner;
import java.util.UUID;

/**
 * Domain Event that is raised immediately after an Order is successfully placed.
 *
 * <p>This event is 100 % immutable and therefore thread-safe. It is intentionally kept free of any
 * framework-specific annotations so that it can safely cross bounded contexts (e.g. via an outbox,
 * message broker, or direct in-memory dispatch) without dragging infrastructural concerns into the
 * domain layer.</p>
 *
 * <p>The event comes with minimal yet sufficient data that downstream consumers (e.g. Fraud
 * Detection, Email & SMS Notification, Loyalty Points, Analytics) typically need. Maintaining a
 * slim payload keeps the coupling low and avoids information leaks.</p>
 */
public final class OrderPlacedEvent implements DomainEvent, Serializable {

    @Serial
    private static final long serialVersionUID = 42L;

    private final UUID eventId;
    private final UUID orderId;
    private final UUID customerId;
    private final List<OrderLine> orderLines;
    private final BigDecimal totalAmount;
    private final Currency currency;
    private final Instant occurredOn;
    private final String correlationId;
    private final long version;          // Increments when the schema of the event changes

    private OrderPlacedEvent(Builder builder) {
        this.eventId       = Objects.requireNonNull(builder.eventId, "eventId must not be null");
        this.orderId       = Objects.requireNonNull(builder.orderId, "orderId must not be null");
        this.customerId    = Objects.requireNonNull(builder.customerId, "customerId must not be null");
        this.orderLines    = List.copyOf(builder.orderLines); // defensive copy
        this.totalAmount   = Objects.requireNonNull(builder.totalAmount, "totalAmount must not be null");
        this.currency      = Objects.requireNonNull(builder.currency, "currency must not be null");
        this.occurredOn    = Objects.requireNonNull(builder.occurredOn, "occurredOn must not be null");
        this.correlationId = builder.correlationId; // nullable on purpose
        this.version       = builder.version;
        if (orderLines.isEmpty()) {
            throw new IllegalArgumentException("orderLines must not be empty");
        }
        if (totalAmount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("totalAmount must be greater than zero");
        }
    }

    // -------------------- Factory Methods -------------------------------------------------------

    /**
     * Creates a new {@link OrderPlacedEvent} with a freshly generated event id and timestamp.
     */
    public static Builder builder() {
        return new Builder()
            .eventId(UUID.randomUUID())
            .occurredOn(Instant.now())
            .version(1);
    }

    // -------------------- DomainEvent Interface -------------------------------------------------

    @Override public UUID eventId()        { return eventId;     }
    @Override public Instant occurredOn()  { return occurredOn;  }
    @Override public String eventName()    { return "OrderPlaced"; }
    @Override public long version()        { return version;     }

    // -------------------- Getters ---------------------------------------------------------------

    public UUID getOrderId()                  { return orderId;       }
    public UUID getCustomerId()               { return customerId;    }
    public List<OrderLine> getOrderLines()    { return orderLines;    }
    public BigDecimal getTotalAmount()        { return totalAmount;   }
    public Currency getCurrency()             { return currency;      }
    public String getCorrelationId()          { return correlationId; }

    // -------------------- Boilerplate -----------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof OrderPlacedEvent that)) return false;
        return eventId.equals(that.eventId);
    }

    @Override
    public int hashCode() {
        return eventId.hashCode();
    }

    @Override
    public String toString() {
        return new StringJoiner(", ", OrderPlacedEvent.class.getSimpleName() + "[", "]")
                .add("eventId=" + eventId)
                .add("orderId=" + orderId)
                .add("customerId=" + customerId)
                .add("orderLines=" + orderLines)
                .add("totalAmount=" + totalAmount)
                .add("currency=" + currency)
                .add("occurredOn=" + occurredOn)
                .add("correlationId='" + correlationId + "'")
                .add("version=" + version)
                .toString();
    }

    // ------------------------------------------------------------------------------------------------
    //  Builder
    // ------------------------------------------------------------------------------------------------

    public static final class Builder {
        private UUID eventId;
        private UUID orderId;
        private UUID customerId;
        private List<OrderLine> orderLines = Collections.emptyList();
        private BigDecimal totalAmount;
        private Currency currency;
        private Instant occurredOn;
        private String correlationId;
        private long version;

        private Builder() {}

        public Builder eventId(UUID eventId) {
            this.eventId = eventId;
            return this;
        }

        public Builder orderId(UUID orderId) {
            this.orderId = orderId;
            return this;
        }

        public Builder customerId(UUID customerId) {
            this.customerId = customerId;
            return this;
        }

        public Builder orderLines(List<OrderLine> orderLines) {
            this.orderLines = orderLines != null ? List.copyOf(orderLines) : Collections.emptyList();
            return this;
        }

        public Builder totalAmount(BigDecimal totalAmount) {
            this.totalAmount = totalAmount;
            return this;
        }

        public Builder currency(Currency currency) {
            this.currency = currency;
            return this;
        }

        public Builder occurredOn(Instant occurredOn) {
            this.occurredOn = occurredOn;
            return this;
        }

        /**
         * @param correlationId An optional value to tie together multiple events originating
         *                      from the same use-case execution (e.g. REST call id).
         */
        public Builder correlationId(String correlationId) {
            this.correlationId = correlationId;
            return this;
        }

        /**
         * Version of the event. Must be incremented whenever the event contract changes to
         * facilitate schema evolution strategies (e.g. in Kafka or EventStoreDB).
         */
        public Builder version(long version) {
            this.version = version;
            return this;
        }

        public OrderPlacedEvent build() {
            return new OrderPlacedEvent(this);
        }
    }

    // ------------------------------------------------------------------------------------------------
    //  Snapshot of Line Items (Value Object)
    // ------------------------------------------------------------------------------------------------

    /**
     * Immutable snapshot of an order line at the moment the order was placed.
     */
    public static final class OrderLine implements Serializable {

        @Serial private static final long serialVersionUID = 1L;

        private final UUID productId;
        private final String sku;
        private final int quantity;
        private final BigDecimal unitPrice;
        private final BigDecimal lineTotal;

        public OrderLine(UUID productId,
                         String sku,
                         int quantity,
                         BigDecimal unitPrice,
                         BigDecimal lineTotal) {

            this.productId = Objects.requireNonNull(productId, "productId must not be null");
            this.sku       = Objects.requireNonNull(sku,       "sku must not be null");
            this.unitPrice = Objects.requireNonNull(unitPrice, "unitPrice must not be null");
            this.lineTotal = Objects.requireNonNull(lineTotal, "lineTotal must not be null");

            if (quantity <= 0) {
                throw new IllegalArgumentException("quantity must be positive");
            }
            if (unitPrice.compareTo(BigDecimal.ZERO) <= 0) {
                throw new IllegalArgumentException("unitPrice must be greater than zero");
            }
            if (lineTotal.compareTo(BigDecimal.ZERO) <= 0) {
                throw new IllegalArgumentException("lineTotal must be greater than zero");
            }

            this.quantity = quantity;
        }

        public UUID getProductId()     { return productId; }
        public String getSku()         { return sku;       }
        public int getQuantity()       { return quantity;  }
        public BigDecimal getUnitPrice() { return unitPrice; }
        public BigDecimal getLineTotal() { return lineTotal; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof OrderLine that)) return false;
            return productId.equals(that.productId) &&
                   sku.equals(that.sku) &&
                   unitPrice.equals(that.unitPrice);
        }

        @Override
        public int hashCode() {
            return Objects.hash(productId, sku, unitPrice);
        }

        @Override
        public String toString() {
            return new StringJoiner(", ", OrderLine.class.getSimpleName() + "[", "]")
                    .add("productId=" + productId)
                    .add("sku='" + sku + '\'')
                    .add("quantity=" + quantity)
                    .add("unitPrice=" + unitPrice)
                    .add("lineTotal=" + lineTotal)
                    .toString();
        }
    }
}

