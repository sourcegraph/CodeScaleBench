package com.sprintcart.domain.model.catalog;

import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import javax.money.Monetary;
import javax.money.MonetaryAmount;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * Domain Aggregate that represents an individual sellable Stock-Keeping-Unit (SKU).
 *
 * <p>The SKU is immutable in its identity but mutable in state. All state-changing
 * operations enforce business invariants and throw {@link DomainException}
 * in case of violation.</p>
 *
 * <p>Persistence code must live in a separate adapter; therefore this class does
 * not contain any JPA/Hibernate annotations.</p>
 */
public class Sku implements Serializable {

    @Serial
    private static final long serialVersionUID = 42L;

    /** Globally unique identifier. Generated once and never changes. */
    private final SkuId id;

    /** Immutable after creation because downstream systems may rely on it. */
    @NotBlank
    private final String code;

    @NotBlank
    private String name;

    private String description;

    @NotNull
    private MonetaryAmount price;

    private MonetaryAmount compareAtPrice;

    @Min(0)
    private int stockOnHand;

    /** Whether inventory for this SKU should be decremented on checkout. */
    private boolean trackInventory;

    @NotNull
    private SkuStatus status;

    /** Arbitrary key/value pairs used by storefront faceting & search. */
    private final Map<String, String> attributes;

    /** When was this SKU first created. Useful for audits/filtering. */
    private final Instant createdAt;

    /** Last time *any* field changed. Simplifies external cache invalidation. */
    private Instant lastModifiedAt;

    /* ---------------------------------------------------------------------
     *  Constructors
     * ------------------------------------------------------------------ */

    private Sku(Builder builder) {
        this.id             = builder.id == null ? new SkuId() : builder.id;
        this.code           = requireNotBlank(builder.code, "code");
        this.name           = requireNotBlank(builder.name, "name");
        this.description    = builder.description;
        this.price          = requirePositiveMoney(builder.price, "price");
        this.compareAtPrice = builder.compareAtPrice == null ? null
                : requirePositiveMoney(builder.compareAtPrice, "compareAtPrice");
        this.trackInventory = builder.trackInventory;
        this.stockOnHand    = builder.stockOnHand;
        if (trackInventory && stockOnHand < 0) {
            throw new DomainException("Initial stock must be non-negative");
        }
        this.status         = builder.status == null ? SkuStatus.ACTIVE : builder.status;
        this.attributes     = new LinkedHashMap<>(builder.attributes);
        this.createdAt      = builder.createdAt == null ? Instant.now() : builder.createdAt;
        this.lastModifiedAt = createdAt;
    }

    /* ---------------------------------------------------------------------
     *  Business Operations
     * ------------------------------------------------------------------ */

    public synchronized void rename(@NotBlank String newName) {
        this.name = requireNotBlank(newName, "name");
        touch();
    }

    public synchronized void reprice(@NotNull MonetaryAmount newPrice) {
        this.price = requirePositiveMoney(newPrice, "price");
        touch();
    }

    public synchronized void changeCompareAtPrice(MonetaryAmount newCompareAtPrice) {
        if (newCompareAtPrice != null) {
            this.compareAtPrice = requirePositiveMoney(newCompareAtPrice, "compareAtPrice");
        } else {
            this.compareAtPrice = null;
        }
        touch();
    }

    /**
     * Increases available stock.
     * @param amount amount to add (must be positive)
     */
    public synchronized void increaseStock(@Min(1) int amount) {
        validateInventoryTracking();
        if (amount <= 0) {
            throw new DomainException("amount must be > 0");
        }
        stockOnHand += amount;
        touch();
    }

    /**
     * Decreases available stock; fails when the resulting stock would be negative.
     * @param amount amount to deduct (must be positive)
     */
    public synchronized void decreaseStock(@Min(1) int amount) {
        validateInventoryTracking();
        if (amount <= 0) {
            throw new DomainException("amount must be > 0");
        }
        if (stockOnHand - amount < 0) {
            throw new DomainException("Insufficient stock for SKU: " + code);
        }
        stockOnHand -= amount;
        touch();
    }

    public synchronized void toggleInventoryTracking(boolean track) {
        if (!track && stockOnHand < 0) {
            throw new DomainException("Cannot disable tracking when stock is negative");
        }
        this.trackInventory = track;
        touch();
    }

    public synchronized void discontinue() {
        this.status = SkuStatus.DISCONTINUED;
        touch();
    }

    public boolean isAvailableForSale() {
        return status == SkuStatus.ACTIVE &&
               (!trackInventory || stockOnHand > 0);
    }

    /* ---------------------------------------------------------------------
     *  Internal Helpers
     * ------------------------------------------------------------------ */

    private void validateInventoryTracking() {
        if (!trackInventory) {
            throw new DomainException("Inventory is not tracked for SKU: " + code);
        }
    }

    private void touch() {
        this.lastModifiedAt = Instant.now();
    }

    private static String requireNotBlank(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainException(field + " must not be blank");
        }
        return value;
    }

    private static MonetaryAmount requirePositiveMoney(MonetaryAmount amount, String field) {
        if (amount == null || amount.isNegativeOrZero()) {
            throw new DomainException(field + " must be a positive amount");
        }
        return amount;
    }

    /* ---------------------------------------------------------------------
     *  Getters – no setters allowed from outside!
     * ------------------------------------------------------------------ */

    public SkuId getId()                   { return id; }
    public String getCode()                { return code; }
    public String getName()                { return name; }
    public String getDescription()         { return description; }
    public MonetaryAmount getPrice()       { return price; }
    public MonetaryAmount getCompareAtPrice() { return compareAtPrice; }
    public int getStockOnHand()            { return stockOnHand; }
    public boolean isTrackInventory()      { return trackInventory; }
    public SkuStatus getStatus()           { return status; }
    public Instant getCreatedAt()          { return createdAt; }
    public Instant getLastModifiedAt()     { return lastModifiedAt; }
    public Map<String, String> getAttributes() {
        return Collections.unmodifiableMap(attributes);
    }

    /* ---------------------------------------------------------------------
     *  Equality based on identity (SKU ID)
     * ------------------------------------------------------------------ */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Sku sku)) return false;
        return id.equals(sku.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "Sku[id=%s, code=%s, name=%s, price=%s, stock=%d, status=%s]"
                .formatted(id, code, name, price, stockOnHand, status);
    }

    /* ---------------------------------------------------------------------
     *  Builder
     * ------------------------------------------------------------------ */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private SkuId id;
        private String code;
        private String name;
        private String description;
        private MonetaryAmount price;
        private MonetaryAmount compareAtPrice;
        private boolean trackInventory = true;
        private int stockOnHand = 0;
        private SkuStatus status;
        private Map<String, String> attributes = new LinkedHashMap<>();
        private Instant createdAt;

        private Builder() {}

        public Builder id(SkuId id) {
            this.id = id;
            return this;
        }

        public Builder code(String code) {
            this.code = code;
            return this;
        }

        public Builder name(String name) {
            this.name = name;
            return this;
        }

        public Builder description(String description) {
            this.description = description;
            return this;
        }

        public Builder price(Number amount, String currencyCode) {
            this.price = Monetary.getDefaultAmountFactory()
                    .setCurrency(currencyCode)
                    .setNumber(amount)
                    .create();
            return this;
        }

        public Builder price(MonetaryAmount price) {
            this.price = price;
            return this;
        }

        public Builder compareAtPrice(Number amount, String currencyCode) {
            this.compareAtPrice = Monetary.getDefaultAmountFactory()
                    .setCurrency(currencyCode)
                    .setNumber(amount)
                    .create();
            return this;
        }

        public Builder compareAtPrice(MonetaryAmount price) {
            this.compareAtPrice = price;
            return this;
        }

        public Builder trackInventory(boolean track) {
            this.trackInventory = track;
            return this;
        }

        public Builder initialStock(int stock) {
            this.stockOnHand = stock;
            return this;
        }

        public Builder status(SkuStatus status) {
            this.status = status;
            return this;
        }

        public Builder attribute(String key, String value) {
            this.attributes.put(key, value);
            return this;
        }

        public Builder createdAt(Instant createdAt) {
            this.createdAt = createdAt;
            return this;
        }

        public Sku build() {
            return new Sku(this);
        }
    }

    /* ---------------------------------------------------------------------
     *  Supporting Types
     * ------------------------------------------------------------------ */

    /**
     * Value Object for SKU identifiers. Wraps a UUID for type-safety.
     */
    public static final class SkuId implements Serializable {

        @Serial
        private static final long serialVersionUID = 1L;
        private final UUID uuid;

        public SkuId() {
            this.uuid = UUID.randomUUID();
        }

        public SkuId(UUID uuid) {
            this.uuid = Objects.requireNonNull(uuid, "uuid");
        }

        public UUID asUuid() {
            return uuid;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof SkuId skuId)) return false;
            return uuid.equals(skuId.uuid);
        }

        @Override
        public int hashCode() {
            return uuid.hashCode();
        }

        @Override
        public String toString() {
            return uuid.toString();
        }
    }

    /**
     * Lifecycle status of a SKU.
     */
    public enum SkuStatus {
        ACTIVE,
        OUT_OF_STOCK,
        DISCONTINUED
    }

    /**
     * Domain-specific runtime exception thrown when invariants are violated.
     */
    public static class DomainException extends RuntimeException {
        public DomainException(String message) {
            super(message);
        }
    }
}