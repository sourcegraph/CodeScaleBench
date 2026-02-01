package com.commercesphere.enterprise.pricing.model;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.Currency;
import java.util.Objects;

/**
 * Represents a single tier in a tiered-pricing matrix.
 * <p>
 * Each tier defines an inclusive minimum quantity, an optional inclusive
 * maximum quantity, and a unit price that applies when the purchased quantity
 * falls within that range. The upper bound can be {@code null} to indicate
 * an open-ended tier (e.g., 500+ units).
 * <p>
 * Tiers are grouped inside a {@code PriceBook} (contract, catalog, or promotion)
 * but keep a flattened copy of the currency and price type for fast runtime
 * lookups that avoid unnecessary joins during high-volume calculations.
 */
@Entity
@Table(
    name = "price_tiers",
    indexes = {
        @Index(name = "idx_price_tier_book_id", columnList = "price_book_id"),
        @Index(name = "idx_price_tier_bounds", columnList = "min_qty, max_qty")
    }
)
public class PriceTier implements Serializable {

    @Serial
    private static final long serialVersionUID = 865876812765547582L;

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Foreign key reference to the owning price book.  We keep the association
     * optional at runtime to decouple the domain model from lazy-loading
     * headaches when tiers are cached or serialized independently.
     */
    @ManyToOne(
        optional = false,
        fetch = FetchType.LAZY,
        cascade = {CascadeType.PERSIST, CascadeType.MERGE}
    )
    @JoinColumn(name = "price_book_id", nullable = false, updatable = false)
    private PriceBook priceBook;

    @NotNull
    @Positive
    @Column(name = "min_qty", nullable = false, updatable = false)
    private Integer minimumQuantity;

    /**
     * Upper inclusive bound. If {@code null} the tier has no upper limit.
     */
    @Positive
    @Column(name = "max_qty")
    private Integer maximumQuantity;

    @NotNull
    @Column(name = "unit_price", precision = 19, scale = 4, nullable = false)
    private BigDecimal unitPrice;

    @NotNull
    @Column(name = "currency", length = 3, nullable = false)
    private Currency currency;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "price_type", length = 16, nullable = false)
    private PriceType priceType = PriceType.NET;

    /* --- Audit Columns --------------------------------------------------- */

    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;

    /* --- Constructors ---------------------------------------------------- */

    protected PriceTier() {
        /* JPA ‑ do not use directly */
    }

    public PriceTier(
        @NotNull PriceBook priceBook,
        @NotNull Integer minimumQuantity,
        Integer maximumQuantity,
        @NotNull BigDecimal unitPrice,
        @NotNull Currency currency,
        @NotNull PriceType priceType
    ) {
        this.priceBook = Objects.requireNonNull(priceBook, "priceBook");
        this.minimumQuantity = Objects.requireNonNull(minimumQuantity, "minimumQuantity");
        this.maximumQuantity = maximumQuantity;
        this.unitPrice = Objects.requireNonNull(unitPrice, "unitPrice");
        this.currency = Objects.requireNonNull(currency, "currency");
        this.priceType = Objects.requireNonNull(priceType, "priceType");
        validateBounds();
    }

    /* --- Domain Logic ---------------------------------------------------- */

    /**
     * Returns {@code true} if this tier applies to the supplied quantity.
     */
    public boolean isApplicableForQuantity(int quantity) {
        if (quantity < 0) {
            throw new IllegalArgumentException("Quantity cannot be negative");
        }
        boolean lowerOk = quantity >= minimumQuantity;
        boolean upperOk = maximumQuantity == null || quantity <= maximumQuantity;
        return lowerOk && upperOk;
    }

    /**
     * Calculates the line-item price for a given quantity by multiplying the
     * tier’s unit price with the quantity and rounding according to
     * {@code RoundingMode.HALF_UP}.
     *
     * @throws IllegalArgumentException when the quantity is outside tier bounds
     */
    public BigDecimal calculatePrice(int quantity) {
        if (!isApplicableForQuantity(quantity)) {
            throw new IllegalArgumentException(
                "Quantity " + quantity + " is outside tier bounds [" + minimumQuantity +
                ", " + (maximumQuantity == null ? "∞" : maximumQuantity) + "]"
            );
        }
        return unitPrice
            .multiply(BigDecimal.valueOf(quantity))
            .setScale(unitPrice.scale(), RoundingMode.HALF_UP);
    }

    /* --- Validation ------------------------------------------------------ */

    @PrePersist
    @PreUpdate
    private void validateBounds() {
        if (minimumQuantity == null || minimumQuantity <= 0) {
            throw new IllegalStateException("Minimum quantity must be positive");
        }
        if (maximumQuantity != null && maximumQuantity < minimumQuantity) {
            throw new IllegalStateException("Maximum quantity cannot be less than minimum quantity");
        }
    }

    @PrePersist
    private void onCreate() {
        final OffsetDateTime now = OffsetDateTime.now();
        createdAt = now;
        updatedAt = now;
    }

    @PreUpdate
    private void onUpdate() {
        updatedAt = OffsetDateTime.now();
    }

    /* --- Getters / Setters ---------------------------------------------- */

    public Long getId() {
        return id;
    }

    public PriceBook getPriceBook() {
        return priceBook;
    }

    public Integer getMinimumQuantity() {
        return minimumQuantity;
    }

    public Integer getMaximumQuantity() {
        return maximumQuantity;
    }

    public BigDecimal getUnitPrice() {
        return unitPrice;
    }

    public Currency getCurrency() {
        return currency;
    }

    public PriceType getPriceType() {
        return priceType;
    }

    public OffsetDateTime getCreatedAt() {
        return createdAt;
    }

    public OffsetDateTime getUpdatedAt() {
        return updatedAt;
    }

    /* --- Equality -------------------------------------------------------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof PriceTier other)) return false;
        // Use business key equality instead of PK to support detached entities
        return Objects.equals(priceBook, other.priceBook) &&
               Objects.equals(minimumQuantity, other.minimumQuantity) &&
               Objects.equals(maximumQuantity, other.maximumQuantity) &&
               Objects.equals(unitPrice, other.unitPrice) &&
               Objects.equals(currency, other.currency) &&
               priceType == other.priceType;
    }

    @Override
    public int hashCode() {
        return Objects.hash(priceBook, minimumQuantity, maximumQuantity, unitPrice, currency, priceType);
    }

    @Override
    public String toString() {
        return "PriceTier{" +
               "id=" + id +
               ", priceBook=" + (priceBook == null ? null : priceBook.getId()) +
               ", minimumQuantity=" + minimumQuantity +
               ", maximumQuantity=" + maximumQuantity +
               ", unitPrice=" + unitPrice +
               ", currency=" + currency +
               ", priceType=" + priceType +
               '}';
    }

    /* --- Helper Types ---------------------------------------------------- */

    /**
     * Defines whether the price stored in this tier is inclusive (GROSS) or
     * exclusive (NET) of taxes.  Taxation rules are evaluated downstream.
     */
    public enum PriceType {
        NET,
        GROSS
    }
}