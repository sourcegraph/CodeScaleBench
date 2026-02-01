package com.sprintcart.adapters.persistence.entity;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.CollectionTable;
import jakarta.persistence.Convert;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Embeddable;
import jakarta.persistence.Embedded;
import jakarta.persistence.Entity;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.JoinTable;
import jakarta.persistence.ManyToMany;
import jakarta.persistence.OneToMany;
import jakarta.persistence.PreRemove;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import jakarta.persistence.Version;

import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.HashSet;
import java.util.Objects;
import java.util.Set;

/**
 * JPA representation of a catalog Product.
 * <p>
 * This entity is deliberately rich in behavior—Hexagonal Architecture dictates that
 * business logic live in the domain layer, but persistence-level invariants (unique
 * constraints, optimistic locking, soft-deletes) are best expressed here.
 */
@Entity
@Table(
    name = "products",
    uniqueConstraints = @UniqueConstraint(name = "ux_product_sku", columnNames = "sku"),
    indexes = {
        @Index(name = "ix_product_name", columnList = "name"),
        @Index(name = "ix_product_deleted", columnList = "deleted")
    }
)
@EntityListeners(AuditingEntityListener.class)
public class ProductEntity implements Serializable {

    @Serial
    private static final long serialVersionUID = 172349823749823L;

    // ------------------------------------------------------------------------
    // Core Identity
    // ------------------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Public-facing immutable identifier.
     */
    @Column(nullable = false, length = 64, updatable = false)
    private String sku;

    @Column(nullable = false, length = 256)
    private String name;

    @Column(length = 4096)
    private String description;

    // ------------------------------------------------------------------------
    // Price & Stock
    // ------------------------------------------------------------------------

    @Embedded
    private Money price;

    @Column(nullable = false)
    private Integer stockQty;

    // ------------------------------------------------------------------------
    // Associations
    // ------------------------------------------------------------------------

    /**
     * Lightweight categorization.
     * CategoryEntity is defined in its own file; we do not cascade deletes to avoid
     * accidental orphan removal of shared categories.
     */
    @ManyToMany(fetch = FetchType.LAZY)
    @JoinTable(
        name = "product_categories",
        joinColumns = @JoinColumn(name = "product_id"),
        inverseJoinColumns = @JoinColumn(name = "category_id")
    )
    private Set<CategoryEntity> categories = new HashSet<>();

    /**
     * Ordered product images.
     */
    @OneToMany(
        mappedBy = "product",
        cascade = CascadeType.ALL,
        orphanRemoval = true,
        fetch = FetchType.LAZY
    )
    private Set<ProductImageEntity> images = new HashSet<>();

    /**
     * Simple free-form tags, e.g. "on-sale", "summer-2024".
     * Using ElementCollection avoids the overhead of a join entity.
     */
    @ElementCollection(fetch = FetchType.LAZY)
    @CollectionTable(name = "product_tags", joinColumns = @JoinColumn(name = "product_id"))
    @Column(name = "tag", length = 64)
    private Set<String> tags = new HashSet<>();

    // ------------------------------------------------------------------------
    // Auditing & Concurrency
    // ------------------------------------------------------------------------

    @CreatedDate
    @Column(nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @LastModifiedDate
    @Column(nullable = false)
    private OffsetDateTime updatedAt;

    /**
     * Soft-delete flag. We rarely hard-delete for compliance reasons.
     */
    @Column(nullable = false)
    private boolean deleted = false;

    /**
     * Optimistic locking token.
     */
    @Version
    private Long version;

    // ------------------------------------------------------------------------
    // Constructors
    // ------------------------------------------------------------------------

    protected ProductEntity() {
        /* JPA */
    }

    private ProductEntity(Builder builder) {
        this.sku = builder.sku;
        this.name = builder.name;
        this.description = builder.description;
        this.price = builder.price;
        this.stockQty = builder.stockQty;
        this.categories = builder.categories;
        this.tags = builder.tags;
    }

    // ------------------------------------------------------------------------
    // Domain-level Behavior
    // ------------------------------------------------------------------------

    /**
     * Adjusts stock by the supplied delta.
     *
     * @throws IllegalStateException if the resulting stock would be negative.
     */
    public void adjustStock(int delta) {
        long candidate = (long) stockQty + delta;
        if (candidate < 0) {
            throw new IllegalStateException(
                "Cannot adjust stock below zero for SKU [" + sku + "]. Requested delta = " + delta
            );
        }
        this.stockQty = (int) candidate;
    }

    /**
     * Updates the selling price. Currency must match the existing currency.
     */
    public void changePrice(Money newPrice) {
        if (!Objects.equals(this.price.currency, newPrice.currency)) {
            throw new IllegalArgumentException("Currency mismatch – cannot change from "
                + this.price.currency + " to " + newPrice.currency);
        }
        this.price = newPrice;
    }

    /**
     * Marks the entity as soft-deleted.
     */
    public void markDeleted() {
        this.deleted = true;
    }

    /**
     * JPA callback to intercept remove operations and turn them into soft-deletes.
     */
    @PreRemove
    private void preRemove() {
        this.deleted = true;
    }

    // ------------------------------------------------------------------------
    // Accessors
    // ------------------------------------------------------------------------

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

    public Money getPrice() {
        return price;
    }

    public Integer getStockQty() {
        return stockQty;
    }

    public Set<CategoryEntity> getCategories() {
        return categories;
    }

    public Set<ProductImageEntity> getImages() {
        return images;
    }

    public Set<String> getTags() {
        return tags;
    }

    public OffsetDateTime getCreatedAt() {
        return createdAt;
    }

    public OffsetDateTime getUpdatedAt() {
        return updatedAt;
    }

    public boolean isDeleted() {
        return deleted;
    }

    public Long getVersion() {
        return version;
    }

    // ------------------------------------------------------------------------
    // Equality & String helpers
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ProductEntity that)) return false;
        return Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return 31; // JPA best practice: use constant hashCode for entities with mutable PK
    }

    @Override
    public String toString() {
        return "ProductEntity{" +
            "id=" + id +
            ", sku='" + sku + '\'' +
            ", name='" + name + '\'' +
            ", deleted=" + deleted +
            '}';
    }

    // ------------------------------------------------------------------------
    // Builder
    // ------------------------------------------------------------------------

    public static class Builder {
        private final String sku;
        private final String name;
        private Money price;
        private String description;
        private int stockQty = 0;
        private Set<CategoryEntity> categories = new HashSet<>();
        private Set<String> tags = new HashSet<>();

        public Builder(String sku, String name, Money price) {
            this.sku = Objects.requireNonNull(sku, "sku");
            this.name = Objects.requireNonNull(name, "name");
            this.price = Objects.requireNonNull(price, "price");
        }

        public Builder description(String description) {
            this.description = description;
            return this;
        }

        public Builder stockQty(int stockQty) {
            if (stockQty < 0) {
                throw new IllegalArgumentException("stockQty must be >= 0");
            }
            this.stockQty = stockQty;
            return this;
        }

        public Builder categories(Set<CategoryEntity> categories) {
            this.categories = Objects.requireNonNullElseGet(categories, HashSet::new);
            return this;
        }

        public Builder tags(Set<String> tags) {
            this.tags = Objects.requireNonNullElseGet(tags, HashSet::new);
            return this;
        }

        public ProductEntity build() {
            return new ProductEntity(this);
        }
    }

    // ------------------------------------------------------------------------
    // Value Objects
    // ------------------------------------------------------------------------

    /**
     * Embedded Money value object — simple because we only need amount & ISO currency.
     * In the future we may migrate to JSR-354 (Moneta) but for DB simplicity we store
     * amount as DECIMAL(19,4) and currency as VARCHAR(3).
     */
    @Embeddable
    public static class Money implements Serializable {

        @Serial
        private static final long serialVersionUID = -820099L;

        @Column(name = "price_amount", nullable = false, precision = 19, scale = 4)
        private BigDecimal amount;

        @Column(name = "price_currency", nullable = false, length = 3)
        private String currency;

        protected Money() {
            /* JPA */
        }

        public Money(BigDecimal amount, String currency) {
            if (amount == null || currency == null) {
                throw new NullPointerException("Money amount and currency must be non-null");
            }
            if (amount.scale() > 4) {
                throw new IllegalArgumentException("Scale of amount cannot exceed 4");
            }
            this.amount = amount;
            this.currency = currency.toUpperCase();
        }

        public BigDecimal getAmount() {
            return amount;
        }

        public String getCurrency() {
            return currency;
        }

        @Override
        public String toString() {
            return amount + " " + currency;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Money money)) return false;
            return amount.compareTo(money.amount) == 0 && currency.equals(money.currency);
        }

        @Override
        public int hashCode() {
            return Objects.hash(amount, currency);
        }
    }
}