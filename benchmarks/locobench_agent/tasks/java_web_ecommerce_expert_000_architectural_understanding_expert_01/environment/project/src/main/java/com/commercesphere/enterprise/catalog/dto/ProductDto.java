package com.commercesphere.enterprise.catalog.dto;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Consumer;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

/**
 * Immutable, serializable Data Transfer Object representing a Product that can be exposed
 * through REST endpoints and message queues. The class performs defensive copying of collections,
 * basic bean–validation, and exposes a Builder for convenient instantiation.
 *
 * The DTO purposefully contains only those fields that are safe to expose to external clients;
 * internal bookkeeping fields (e.g., supplier cost or margin) are excluded.
 *
 * NOTE:
 *  – This class is Jackson‐friendly (has JsonCreator/JsonProperty annotations).
 *  – This class is Bean‐Validation‐friendly (jakarta.validation).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class ProductDto implements Serializable {

    @Serial
    private static final long serialVersionUID = 20240609_012345L;

    // ------------------------------------------------------------------------
    // Fields
    // ------------------------------------------------------------------------

    @NotNull
    private final UUID id;

    @NotBlank
    private final String sku;

    @NotBlank
    private final String name;

    private final String description;

    @NotNull
    @Positive
    private final BigDecimal listPrice;

    @NotBlank
    private final String currency;

    private final List<PriceTierDto> tierPrices;

    private final boolean active;

    /**
     * Optimistic-locking version field. Optional.
     */
    private final Integer version;

    private final OffsetDateTime createdAt;
    private final OffsetDateTime lastModifiedAt;

    // ------------------------------------------------------------------------
    // Constructors
    // ------------------------------------------------------------------------

    /**
     * Full constructor. Used by Builder and Jackson.
     */
    @JsonCreator
    private ProductDto(
            @JsonProperty("id") UUID id,
            @JsonProperty("sku") String sku,
            @JsonProperty("name") String name,
            @JsonProperty("description") String description,
            @JsonProperty("listPrice") BigDecimal listPrice,
            @JsonProperty("currency") String currency,
            @JsonProperty("tierPrices") List<PriceTierDto> tierPrices,
            @JsonProperty("active") boolean active,
            @JsonProperty("version") Integer version,
            @JsonProperty("createdAt") OffsetDateTime createdAt,
            @JsonProperty("lastModifiedAt") OffsetDateTime lastModifiedAt) {

        this.id = id;
        this.sku = sku;
        this.name = name;
        this.description = description;
        this.listPrice = listPrice;
        this.currency = currency;
        this.tierPrices = tierPrices == null
                          ? Collections.emptyList()
                          : Collections.unmodifiableList(new ArrayList<>(tierPrices));
        this.active = active;
        this.version = version;
        this.createdAt = createdAt;
        this.lastModifiedAt = lastModifiedAt;

        validateSelf(); // Fail fast if violations are detected.
    }

    // ------------------------------------------------------------------------
    // Validation
    // ------------------------------------------------------------------------

    private void validateSelf() {
        try (ValidatorFactory factory = Validation.buildDefaultValidatorFactory()) {
            Validator validator = factory.getValidator();
            var violations = validator.validate(this);
            if (!violations.isEmpty()) {
                StringBuilder sb = new StringBuilder("ProductDto validation failed:");
                for (ConstraintViolation<ProductDto> v : violations) {
                    sb.append(System.lineSeparator())
                      .append(" – ")
                      .append(v.getPropertyPath())
                      .append(": ")
                      .append(v.getMessage());
                }
                throw new IllegalArgumentException(sb.toString());
            }
        }
    }

    // ------------------------------------------------------------------------
    // Getters
    // ------------------------------------------------------------------------

    public UUID getId() {
        return id;
    }

    public String getSku() {
        return sku;
    }

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    public BigDecimal getListPrice() {
        return listPrice;
    }

    public String getCurrency() {
        return currency;
    }

    public List<PriceTierDto> getTierPrices() {
        return tierPrices;
    }

    public boolean isActive() {
        return active;
    }

    public Integer getVersion() {
        return version;
    }

    public OffsetDateTime getCreatedAt() {
        return createdAt;
    }

    public OffsetDateTime getLastModifiedAt() {
        return lastModifiedAt;
    }

    // ------------------------------------------------------------------------
    // Builder
    // ------------------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    public static Builder builder(ProductDto copy) {
        return new Builder(copy);
    }

    public static final class Builder {
        private UUID id;
        private String sku;
        private String name;
        private String description;
        private BigDecimal listPrice;
        private String currency;
        private List<PriceTierDto> tierPrices = new ArrayList<>();
        private boolean active = true;
        private Integer version;
        private OffsetDateTime createdAt;
        private OffsetDateTime lastModifiedAt;

        private Builder() {
            // intentionally empty
        }

        private Builder(ProductDto copy) {
            this.id = copy.id;
            this.sku = copy.sku;
            this.name = copy.name;
            this.description = copy.description;
            this.listPrice = copy.listPrice;
            this.currency = copy.currency;
            this.tierPrices = new ArrayList<>(copy.tierPrices);
            this.active = copy.active;
            this.version = copy.version;
            this.createdAt = copy.createdAt;
            this.lastModifiedAt = copy.lastModifiedAt;
        }

        public Builder id(UUID id) {
            this.id = id;
            return this;
        }

        public Builder sku(String sku) {
            this.sku = sku;
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

        public Builder listPrice(BigDecimal listPrice) {
            this.listPrice = listPrice;
            return this;
        }

        public Builder currency(String currency) {
            this.currency = currency;
            return this;
        }

        public Builder tierPrices(List<PriceTierDto> tierPrices) {
            this.tierPrices = tierPrices;
            return this;
        }

        public Builder addTierPrice(PriceTierDto tier) {
            this.tierPrices.add(tier);
            return this;
        }

        public Builder active(boolean active) {
            this.active = active;
            return this;
        }

        public Builder version(Integer version) {
            this.version = version;
            return this;
        }

        public Builder createdAt(OffsetDateTime createdAt) {
            this.createdAt = createdAt;
            return this;
        }

        public Builder lastModifiedAt(OffsetDateTime lastModifiedAt) {
            this.lastModifiedAt = lastModifiedAt;
            return this;
        }

        /**
         * Allows to mutate the builder with a lambda:
         *
         * ProductDto.builder()
         *           .apply(b -> b.name("Printer").sku("HP-LJ-1100"))
         *           .build();
         */
        public Builder apply(Consumer<Builder> consumer) {
            consumer.accept(this);
            return this;
        }

        public ProductDto build() {
            // Provide sensible defaults
            if (id == null) {
                id = UUID.randomUUID();
            }
            if (createdAt == null) {
                createdAt = OffsetDateTime.now();
            }
            if (lastModifiedAt == null) {
                lastModifiedAt = createdAt;
            }
            return new ProductDto(
                    id,
                    sku,
                    name,
                    description,
                    listPrice,
                    currency,
                    tierPrices,
                    active,
                    version,
                    createdAt,
                    lastModifiedAt);
        }
    }

    // ------------------------------------------------------------------------
    // Utility Overrides
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ProductDto that)) return false;
        return active == that.active
                && Objects.equals(id, that.id)
                && Objects.equals(sku, that.sku)
                && Objects.equals(name, that.name)
                && Objects.equals(description, that.description)
                && Objects.equals(listPrice, that.listPrice)
                && Objects.equals(currency, that.currency)
                && Objects.equals(tierPrices, that.tierPrices)
                && Objects.equals(version, that.version)
                && Objects.equals(createdAt, that.createdAt)
                && Objects.equals(lastModifiedAt, that.lastModifiedAt);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, sku, name, description, listPrice, currency,
                            tierPrices, active, version, createdAt, lastModifiedAt);
    }

    @Override
    public String toString() {
        return "ProductDto{" +
               "id=" + id +
               ", sku='" + sku + '\'' +
               ", name='" + name + '\'' +
               ", listPrice=" + listPrice +
               ", currency='" + currency + '\'' +
               ", active=" + active +
               ", version=" + version +
               '}';
    }

    // ------------------------------------------------------------------------
    // Nested DTOs
    // ------------------------------------------------------------------------

    /**
     * Represents a quantity‐based tier price. Example:
     *  – 10 units => 90.00 EUR
     *  – 25 units => 85.00 EUR
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class PriceTierDto implements Serializable {

        @Serial
        private static final long serialVersionUID = 20240609_678901L;

        @Positive
        private final int minQuantity;

        @NotNull
        @Positive
        private final BigDecimal price;

        @NotBlank
        private final String currency;

        @JsonCreator
        private PriceTierDto(
                @JsonProperty("minQuantity") int minQuantity,
                @JsonProperty("price") BigDecimal price,
                @JsonProperty("currency") String currency) {

            this.minQuantity = minQuantity;
            this.price = price;
            this.currency = currency;

            validateSelf();
        }

        public static PriceTierDto of(int minQty, BigDecimal price, String currency) {
            return new PriceTierDto(minQty, price, currency);
        }

        private void validateSelf() {
            try (ValidatorFactory factory = Validation.buildDefaultValidatorFactory()) {
                Validator validator = factory.getValidator();
                var violations = validator.validate(this);
                if (!violations.isEmpty()) {
                    StringBuilder sb = new StringBuilder("PriceTierDto validation failed:");
                    for (ConstraintViolation<PriceTierDto> v : violations) {
                        sb.append(System.lineSeparator())
                          .append(" – ")
                          .append(v.getPropertyPath())
                          .append(": ")
                          .append(v.getMessage());
                    }
                    throw new IllegalArgumentException(sb.toString());
                }
            }
        }

        public int getMinQuantity() {
            return minQuantity;
        }

        public BigDecimal getPrice() {
            return price;
        }

        public String getCurrency() {
            return currency;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof PriceTierDto that)) return false;
            return minQuantity == that.minQuantity
                    && Objects.equals(price, that.price)
                    && Objects.equals(currency, that.currency);
        }

        @Override
        public int hashCode() {
            return Objects.hash(minQuantity, price, currency);
        }

        @Override
        public String toString() {
            return "PriceTierDto{" +
                   "minQuantity=" + minQuantity +
                   ", price=" + price +
                   ", currency='" + currency + '\'' +
                   '}';
        }
    }
}