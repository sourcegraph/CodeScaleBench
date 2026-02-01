package com.sprintcart.domain.model.catalog;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.LocalDateTime;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Aggregate root that represents a sellable product in the SprintCart catalog.
 * <p>
 * The class is intentionally persistence-agnostic and contains only business
 * logic and invariants. Changes to the entity should be performed through its
 * public methods so that invariants are preserved and domain events are fired.
 */
public final class Product implements Serializable {

    @Serial
    private static final long serialVersionUID = 7710263275463173574L;

    // ------------------------------------------------------------------------
    // Value Objects & Identifiers
    // ------------------------------------------------------------------------

    /**
     * Stable identifier for the product.
     */
    @NotNull
    private final UUID id;

    /**
     * Merchant-defined SKU (stock-keeping unit). Must be unique within the tenant
     * boundary but the uniqueness check is delegated to the application service.
     */
    @NotBlank
    private final String sku;

    // ------------------------------------------------------------------------
    // Mutable state that is allowed to evolve throughout the lifecycle
    // ------------------------------------------------------------------------

    @NotBlank
    private String name;

    private String description;

    /**
     * The canonical price in the store's base currency. Multicurrency pricing
     * is modeled in a separate PriceBook aggregate.
     */
    @NotNull
    @Min(0)
    private BigDecimal price;

    /**
     * The currency in ISO 4217 format (e.g. "USD", "EUR"). We keep it as a plain
     * string in the domain to avoid pulling javax.money into the core.
     */
    @NotBlank
    private String currency;

    /**
     * Category IDs the product currently belongs to. Only IDs are kept here to
     * keep the aggregate smaller and avoid load-explosion.
     */
    @NotNull
    private final Set<UUID> categoryIds = new LinkedHashSet<>();

    /**
     * Stock bookkeeping for this product.
     */
    @NotNull
    private final Inventory inventory;

    /**
     * Version for optimistic concurrency checking. The infrastructure layer is
     * responsible for incrementing it on each successful commit.
     */
    private long version;

    /**
     * Product lifecycle status.
     */
    @NotNull
    private Status status;

    /**
     * Audit timestamps.
     */
    @NotNull
    private final LocalDateTime createdAt;
    @NotNull
    private LocalDateTime updatedAt;
    private LocalDateTime publishedAt;

    // ------------------------------------------------------------------------
    // Constructors & Factory
    // ------------------------------------------------------------------------

    private Product(Builder builder) {
        this.id          = Objects.requireNonNull(builder.id, "id");
        this.sku         = requireNonBlank(builder.sku, "sku");
        this.name        = requireNonBlank(builder.name, "name");
        this.description = builder.description == null ? "" : builder.description.trim();
        this.price       = requirePositive(builder.price, "price");
        this.currency    = requireNonBlank(builder.currency, "currency");
        this.status      = Status.DRAFT;
        this.inventory   = new Inventory(builder.initialStock);
        this.createdAt   = LocalDateTime.now(Clock.systemUTC());
        this.updatedAt   = createdAt;
        this.version     = 0L;
    }

    public static Builder newProduct(UUID id, String sku) {
        return new Builder(id, sku);
    }

    // ------------------------------------------------------------------------
    // Behaviour (Mutations)
    // ------------------------------------------------------------------------

    public void rename(@NotBlank String newName) {
        this.name = requireNonBlank(newName, "newName");
        touch();
    }

    public void changeDescription(String newDescription) {
        this.description = newDescription == null ? "" : newDescription.trim();
        touch();
    }

    /**
     * Reprices the product.
     *
     * @param newPrice    Price as decimal
     * @param newCurrency ISO 4217 currency code
     */
    public void reprice(@NotNull BigDecimal newPrice, @NotBlank String newCurrency) {
        this.price    = requirePositive(newPrice, "newPrice");
        this.currency = requireNonBlank(newCurrency, "newCurrency");
        touch();
    }

    /**
     * Adjusts the on-hand stock. Negative deltas decrease stock, positive deltas
     * increase it. Stock must never fall below zero.
     *
     * @throws IllegalArgumentException if the resulting stock would be negative
     */
    public void adjustStock(int delta) {
        inventory.adjust(delta);
        touch();
    }

    /**
     * Publishes the product and makes it searchable / orderable.
     */
    public void publish() {
        ensureStatus(Status.DRAFT, "Only draft products can be published");
        this.status      = Status.ACTIVE;
        this.publishedAt = LocalDateTime.now(Clock.systemUTC());
        touch();
    }

    /**
     * Retires the product so that it cannot be added to carts anymore. Orders
     * containing the product are still valid.
     */
    public void discontinue() {
        ensureStatus(Status.ACTIVE, "Only active products can be discontinued");
        this.status = Status.DISCONTINUED;
        touch();
    }

    // ------------------------------------------------------------------------
    // Query Methods
    // ------------------------------------------------------------------------

    public boolean isAvailableForSale() {
        return status == Status.ACTIVE && inventory.getOnHand() > 0;
    }

    public UUID getId()                       { return id; }
    public String getSku()                    { return sku; }
    public String getName()                   { return name; }
    public String getDescription()            { return description; }
    public BigDecimal getPrice()              { return price; }
    public String getCurrency()               { return currency; }
    public Set<UUID> getCategoryIds()         { return Collections.unmodifiableSet(categoryIds); }
    public int getOnHandStock()               { return inventory.getOnHand(); }
    public long getVersion()                  { return version; }
    public Status getStatus()                 { return status; }
    public LocalDateTime getCreatedAt()       { return createdAt; }
    public LocalDateTime getUpdatedAt()       { return updatedAt; }
    public LocalDateTime getPublishedAt()     { return publishedAt; }

    // ------------------------------------------------------------------------
    // Aggregate Root helpers
    // ------------------------------------------------------------------------

    private void touch() {
        this.updatedAt = LocalDateTime.now(Clock.systemUTC());
        // In a real system we would also collect DomainEvents here, e.g.:
        // this.domainEvents.add(new ProductChangedEvent(this.id, ...));
    }

    private void ensureStatus(Status expected, String message) {
        if (this.status != expected) {
            throw new IllegalStateException(message + " (expected " + expected + ", found " + status + ')');
        }
    }

    // ------------------------------------------------------------------------
    // Equality — only by identifier
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        return this == o || (o instanceof Product other && id.equals(other.id));
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    // ------------------------------------------------------------------------
    // Nested Types
    // ------------------------------------------------------------------------

    /**
     * Builder that enforces mandatory fields at compile time and keeps the
     * aggregate consistent from day one.
     */
    public static final class Builder {

        private final UUID id;
        private final String sku;
        private String name;
        private String description;
        private BigDecimal price;
        private String currency = "USD"; // default
        private int initialStock = 0;

        private Builder(UUID id, String sku) {
            this.id  = Objects.requireNonNull(id,  "id");
            this.sku = requireNonBlank(sku, "sku");
        }

        public Builder name(String name) {
            this.name = requireNonBlank(name, "name");
            return this;
        }

        public Builder description(String description) {
            this.description = description == null ? "" : description.trim();
            return this;
        }

        public Builder price(BigDecimal price, String currency) {
            this.price    = requirePositive(price, "price");
            this.currency = requireNonBlank(currency, "currency");
            return this;
        }

        public Builder initialStock(int quantity) {
            if (quantity < 0) {
                throw new IllegalArgumentException("Initial stock cannot be negative");
            }
            this.initialStock = quantity;
            return this;
        }

        public Product build() {
            if (name == null) {
                throw new IllegalStateException("Missing mandatory attribute 'name'");
            }
            if (price == null) {
                throw new IllegalStateException("Missing mandatory attribute 'price'");
            }
            return new Product(this);
        }
    }

    /**
     * Encapsulates inventory bookkeeping plus basic invariants.
     */
    private static final class Inventory implements Serializable {

        @Serial
        private static final long serialVersionUID = 6049158314333414268L;

        @Min(0)
        private int onHand;

        Inventory(int initialStock) {
            this.onHand = initialStock;
        }

        int getOnHand() {
            return onHand;
        }

        /**
         * Adjusts the on-hand stock while ensuring it never becomes negative.
         */
        void adjust(int delta) {
            int newQty = onHand + delta;
            if (newQty < 0) {
                throw new IllegalArgumentException("Insufficient stock (requested delta: " + delta + ", current: " + onHand + ')');
            }
            this.onHand = newQty;
        }
    }

    /**
     * Allowed product states.
     */
    public enum Status {
        DRAFT,        // not visible to consumers
        ACTIVE,       // visible and purchasable
        DISCONTINUED  // no longer sellable
    }

    // ------------------------------------------------------------------------
    // Utility helpers
    // ------------------------------------------------------------------------

    private static String requireNonBlank(String value, String attribute) {
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalArgumentException(attribute + " cannot be blank");
        }
        return value.trim();
    }

    private static BigDecimal requirePositive(BigDecimal value, String attribute) {
        if (value == null || value.signum() < 0) {
            throw new IllegalArgumentException(attribute + " must be >= 0");
        }
        // store with scale = 2 for currencies
        return value.setScale(2, BigDecimal.ROUND_HALF_UP);
    }
}