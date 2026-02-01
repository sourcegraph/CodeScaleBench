package com.commercesphere.enterprise.catalog.model;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.CollectionTable;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Embedded;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import jakarta.persistence.Temporal;
import jakarta.persistence.TemporalType;
import jakarta.persistence.Version;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Collections;
import java.util.Currency;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

/**
 * Product is the central catalog entity inside CommerceSphere Enterprise Suite.
 * It is mapped as a single JPA entity and represents the immutable business concept
 * of a sellable item. Mutation operations operate on defensive copies to guarantee
 * the integrity of the aggregate before it is persisted.
 */
@Entity
@Table(name = "cs_product",
       indexes = {
           @Index(name = "idx_product_sku", columnList = "sku", unique = true),
           @Index(name = "idx_product_status", columnList = "status")
       })
public class Product implements Serializable {

    @Serial
    private static final long serialVersionUID = 2313431449634601960L;

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Stock Keeping Unit – must be unique per product.
     */
    @Column(nullable = false, unique = true, updatable = false, length = 64)
    @NotBlank(message = "SKU must be provided")
    private String sku;

    @Column(nullable = false, length = 128)
    @NotBlank(message = "Product name must be provided")
    private String name;

    @Column(length = 2048)
    @Size(max = 2048, message = "Description too long")
    private String description;

    /**
     * Category identifier maintained outside of the Product aggregate.
     */
    @Column(name = "category_id", nullable = false)
    @NotNull(message = "Category id must be provided")
    private Long categoryId;

    /**
     * Base list price stored in minor units (e.g., cents) to avoid rounding issues.
     */
    @Column(name = "price_minor", nullable = false)
    @DecimalMin(value = "0", inclusive = false)
    private Long priceMinor;

    @Column(name = "currency", length = 3, nullable = false)
    private String currencyCode;

    @Enumerated(EnumType.STRING)
    @Column(length = 32, nullable = false)
    private ProductStatus status = ProductStatus.DRAFT;

    /** Arbitrary attribute map such as color, material, etc. */
    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(name = "cs_product_attribute")
    private Map<String, String> attributes = new HashMap<>();

    @Embedded
    private Dimensions dimensions;

    @Column(name = "weight_grams")
    private Integer weightGrams;

    @Temporal(TemporalType.TIMESTAMP)
    @Column(name = "created_at", updatable = false, nullable = false)
    private Instant createdAt;

    @Temporal(TemporalType.TIMESTAMP)
    @Column(name = "updated_at")
    private Instant updatedAt;

    /**
     * Optimistic lock version column.
     */
    @Version
    private long version;

    /**********************************
     * Constructors & Factory Methods *
     **********************************/

    protected Product() {
        // Required by JPA
    }

    private Product(Builder builder) {
        this.sku = builder.sku;
        this.name = builder.name;
        this.description = builder.description;
        this.categoryId = builder.categoryId;
        this.setPrice(builder.price, builder.currency);
        this.status = builder.status;
        this.attributes = new HashMap<>(builder.attributes);
        this.dimensions = builder.dimensions;
        this.weightGrams = builder.weightGrams;
        this.createdAt = Instant.now();
        this.updatedAt = this.createdAt;
    }

    public static Builder builder(String sku, String name, Long categoryId) {
        return new Builder(sku, name, categoryId);
    }

    /*********************
     * Business Methods  *
     *********************/

    /**
     * Mutates the attribute map in-place. Defensive copy is returned to callers.
     */
    public void addOrUpdateAttribute(@NotBlank String key, @NotBlank String value) {
        Objects.requireNonNull(key, "Attribute key");
        Objects.requireNonNull(value, "Attribute value");

        this.attributes.put(key.trim(), value.trim());
        touch();
    }

    public void removeAttribute(String key) {
        if (this.attributes.remove(key) != null) {
            touch();
        }
    }

    /**
     * Updates the price while validating that the amount is positive.
     */
    public void setPrice(@NotNull BigDecimal price, @NotNull Currency currency) {
        Objects.requireNonNull(price, "Price");
        Objects.requireNonNull(currency, "Currency");

        if (price.scale() > 2) {
            throw new IllegalArgumentException("Price scale must not exceed 2 decimal places");
        }
        if (price.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Price must be greater than zero");
        }
        this.priceMinor = price.movePointRight(2).longValueExact();
        this.currencyCode = currency.getCurrencyCode();
        touch();
    }

    /**
     * Changes status with minimal validation rules.
     */
    public void changeStatus(@NotNull ProductStatus newStatus) {
        Objects.requireNonNull(newStatus, "Status");

        if (this.status == ProductStatus.ARCHIVED) {
            throw new IllegalStateException("Archived products cannot be modified");
        }
        this.status = newStatus;
        touch();
    }

    /*************
     * Accessors *
     *************/

    public Long getId() {
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

    public Long getCategoryId() {
        return categoryId;
    }

    public BigDecimal getPrice() {
        return BigDecimal.valueOf(priceMinor, 2);
    }

    public Currency getCurrency() {
        return Currency.getInstance(currencyCode);
    }

    public ProductStatus getStatus() {
        return status;
    }

    public Map<String, String> getAttributes() {
        return Collections.unmodifiableMap(attributes);
    }

    public Dimensions getDimensions() {
        return dimensions;
    }

    public Integer getWeightGrams() {
        return weightGrams;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    /**********************
     * Internal utilities *
     **********************/

    private void touch() {
        this.updatedAt = Instant.now();
    }

    /************
     * Equality *
     ************/

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Product product)) return false;
        return Objects.equals(sku, product.sku);
    }

    @Override
    public int hashCode() {
        return Objects.hash(sku);
    }

    @Override
    public String toString() {
        return "Product{" +
            "id=" + id +
            ", sku='" + sku + '\'' +
            ", name='" + name + '\'' +
            ", status=" + status +
            '}';
    }

    /***********
     * Builder *
     ***********/

    public static final class Builder {
        private final String sku;
        private final String name;
        private final Long categoryId;

        private String description;
        private BigDecimal price = BigDecimal.ONE;
        private Currency currency = Currency.getInstance("USD");
        private ProductStatus status = ProductStatus.DRAFT;
        private Map<String, String> attributes = new HashMap<>();
        private Dimensions dimensions;
        private Integer weightGrams;

        private Builder(String sku, String name, Long categoryId) {
            this.sku = Objects.requireNonNull(sku, "SKU must not be null").trim();
            this.name = Objects.requireNonNull(name, "Name must not be null").trim();
            this.categoryId = Objects.requireNonNull(categoryId, "Category id must not be null");
        }

        public Builder description(String description) {
            this.description = description;
            return this;
        }

        public Builder price(BigDecimal price, Currency currency) {
            this.price = price;
            this.currency = currency;
            return this;
        }

        public Builder status(ProductStatus status) {
            this.status = status;
            return this;
        }

        public Builder attributes(Map<String, String> attributes) {
            this.attributes = new HashMap<>(attributes);
            return this;
        }

        public Builder dimensions(Dimensions dimensions) {
            this.dimensions = dimensions;
            return this;
        }

        public Builder weightGrams(Integer weightGrams) {
            this.weightGrams = weightGrams;
            return this;
        }

        public Product build() {
            return new Product(this);
        }
    }

    /*****************
     * Value Objects *
     *****************/

    /**
     * Dimensions value-object stored as an embeddable component.
     */
    @jakarta.persistence.Embeddable
    public static class Dimensions implements Serializable {
        @Serial
        private static final long serialVersionUID = 419674220723823758L;

        @Column(name = "length_mm")
        private Integer lengthMm;

        @Column(name = "width_mm")
        private Integer widthMm;

        @Column(name = "height_mm")
        private Integer heightMm;

        protected Dimensions() {
        }

        public Dimensions(Integer lengthMm, Integer widthMm, Integer heightMm) {
            this.lengthMm = lengthMm;
            this.widthMm = widthMm;
            this.heightMm = heightMm;
        }

        public Integer getLengthMm() {
            return lengthMm;
        }

        public Integer getWidthMm() {
            return widthMm;
        }

        public Integer getHeightMm() {
            return heightMm;
        }
    }

    /**
     * Product lifecycle states.
     */
    public enum ProductStatus {
        DRAFT,
        ACTIVE,
        DISCONTINUED,
        ARCHIVED
    }
}