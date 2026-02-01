package com.commercesphere.enterprise.pricing.model;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import jakarta.persistence.Embedded;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToMany;
import jakarta.persistence.OrderBy;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.io.Serializable;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Currency;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

/**
 * ContractPrice represents the pricing terms negotiated for a specific contract and product.
 * <p>
 * A ContractPrice can be one of several types:
 * <ul>
 *     <li>FIXED – The same unit price applies regardless of ordered quantity</li>
 *     <li>TIERED – Unit price varies according to quantity breaks</li>
 *     <li>DISCOUNT – A percentage discount off of list price; stored in {@link #unitPrice} as a negative percentage</li>
 * </ul>
 * <p>
 * The object is responsible for determining the correct effective unit price at runtime,
 * taking date validity and quantity tiering into account.
 */
@Entity
@Table(
        name = "contract_prices",
        uniqueConstraints = @UniqueConstraint(
                name = "uc_contract_product_currency",
                columnNames = {"contract_id", "product_sku", "currency"}
        )
)
public class ContractPrice implements Serializable {

    private static final long serialVersionUID = -3015339309417298460L;

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * External identifier of the contract the price belongs to.
     */
    @NotBlank
    @Column(name = "contract_id", nullable = false, updatable = false, length = 64)
    private String contractId;

    /**
     * Product SKU for which this contract price applies.
     */
    @NotBlank
    @Column(name = "product_sku", nullable = false, updatable = false, length = 64)
    private String productSku;

    /**
     * Currency code (ISO-4217) in which monetary amounts are specified.
     * Stored separately from the {@link Money} embeddable to facilitate unique constraints.
     */
    @NotBlank
    @Column(name = "currency", nullable = false, length = 3, updatable = false)
    private String currencyCode;

    /**
     * Type of price calculation to apply.
     */
    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "price_type", nullable = false, length = 16)
    private PriceType priceType = PriceType.FIXED;

    /**
     * The base unit price—meaning depends on {@link #priceType}.
     */
    @Valid
    @NotNull
    @Embedded
    private Money unitPrice;

    /**
     * Tiers used when {@link #priceType} == {@link PriceType#TIERED}.
     */
    @Valid
    @OneToMany(
            mappedBy = "contractPrice",
            cascade = CascadeType.ALL,
            orphanRemoval = true,
            fetch = FetchType.LAZY
    )
    @OrderBy("minQuantity ASC")
    private List<PriceTier> tierPrices = new ArrayList<>();

    /**
     * Date range during which the price is active.
     */
    @NotNull
    @Column(name = "effective_from", nullable = false)
    private LocalDate effectiveFrom;

    @Column(name = "effective_to")
    private LocalDate effectiveTo;

    /**
     * Audit columns – managed automatically by JPA lifecycle callbacks.
     */
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    protected ContractPrice() {
        /* JPA */ }

    private ContractPrice(Builder builder) {
        this.contractId = builder.contractId;
        this.productSku = builder.productSku;
        this.currencyCode = builder.currency.getCurrencyCode();
        this.priceType = builder.priceType;
        this.unitPrice = builder.unitPrice;
        this.tierPrices = builder.tierPrices;
        this.effectiveFrom = builder.effectiveFrom;
        this.effectiveTo = builder.effectiveTo;

        // Establish bidirectional relationship for tiers
        this.tierPrices.forEach(t -> t.setContractPrice(this));
    }

    /**
     * Computes the effective unit price for the given date and quantity.
     *
     * @param quantity order quantity
     * @param date     date of order
     * @return computed Money representing unit price
     * @throws IllegalStateException when no valid price is found
     */
    public Money getEffectiveUnitPrice(int quantity, LocalDate date) {
        Objects.requireNonNull(date, "date cannot be null");
        if (quantity <= 0) {
            throw new IllegalArgumentException("quantity must be positive");
        }

        if (!isEffective(date)) {
            throw new IllegalStateException(
                    String.format("Price not effective on %s (valid %s – %s)", date, effectiveFrom, effectiveTo)
            );
        }

        switch (priceType) {
            case FIXED:
                return unitPrice;
            case DISCOUNT:
                // Assume unitPrice.amount is negative discount percentage. e.g., -10 means 10% discount
                BigDecimal discount = unitPrice.getAmount().abs()
                        .setScale(4, RoundingMode.HALF_UP)
                        .divide(BigDecimal.valueOf(100), RoundingMode.HALF_UP);
                // In real scenario, we'd fetch current list price from catalog, but here we just apply discount
                // to pre-negotiated baseline price stored inside unitPrice.referenceAmount
                BigDecimal listPrice = unitPrice.getReferenceAmount()
                        .orElseThrow(() -> new IllegalStateException("Reference amount required for DISCOUNT price"));
                BigDecimal discounted = listPrice.multiply(BigDecimal.ONE.subtract(discount))
                        .setScale(2, RoundingMode.HALF_UP);
                return new Money(discounted, unitPrice.getCurrency(), Optional.of(listPrice));
            case TIERED:
                // Find the highest matching tier <= quantity
                return tierPrices.stream()
                        .filter(tp -> tp.getMinQuantity() <= quantity)
                        .max((a, b) -> Integer.compare(a.getMinQuantity(), b.getMinQuantity()))
                        .map(PriceTier::getUnitPrice)
                        .orElseThrow(() -> new IllegalStateException(
                                "No tiered price defined for quantity " + quantity
                        ));
            default:
                throw new IllegalStateException("Unhandled price type: " + priceType);
        }
    }

    /**
     * Determines whether the price is applicable on the given date.
     */
    public boolean isEffective(LocalDate date) {
        if (date == null) {
            return false;
        }
        boolean afterStart = !date.isBefore(effectiveFrom);
        boolean beforeEnd = effectiveTo == null || !date.isAfter(effectiveTo);
        return afterStart && beforeEnd;
    }

    @PrePersist
    private void onCreate() {
        this.createdAt = OffsetDateTime.now();
        this.updatedAt = this.createdAt;
    }

    @PreUpdate
    private void onUpdate() {
        this.updatedAt = OffsetDateTime.now();
    }

    // -------------------- Builder --------------------

    public static Builder builder(String contractId,
                                  String productSku,
                                  Currency currency,
                                  Money unitPrice,
                                  LocalDate effectiveFrom) {
        return new Builder(contractId, productSku, currency, unitPrice, effectiveFrom);
    }

    public static final class Builder {
        private final String contractId;
        private final String productSku;
        private final Currency currency;
        private final Money unitPrice;
        private final LocalDate effectiveFrom;

        private PriceType priceType = PriceType.FIXED;
        private List<PriceTier> tierPrices = new ArrayList<>();
        private LocalDate effectiveTo;

        private Builder(String contractId,
                        String productSku,
                        Currency currency,
                        Money unitPrice,
                        LocalDate effectiveFrom) {
            this.contractId = Objects.requireNonNull(contractId, "contractId");
            this.productSku = Objects.requireNonNull(productSku, "productSku");
            this.currency = Objects.requireNonNull(currency, "currency");
            this.unitPrice = Objects.requireNonNull(unitPrice, "unitPrice");
            this.effectiveFrom = Objects.requireNonNull(effectiveFrom, "effectiveFrom");
        }

        public Builder priceType(PriceType priceType) {
            this.priceType = Objects.requireNonNull(priceType, "priceType");
            return this;
        }

        public Builder tierPrices(List<PriceTier> tierPrices) {
            this.tierPrices = Objects.requireNonNull(tierPrices, "tierPrices");
            return this;
        }

        public Builder effectiveTo(LocalDate effectiveTo) {
            this.effectiveTo = effectiveTo;
            return this;
        }

        public ContractPrice build() {
            return new ContractPrice(this);
        }
    }

    // -------------------- Equals / HashCode --------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ContractPrice)) return false;
        ContractPrice that = (ContractPrice) o;
        return Objects.equals(contractId, that.contractId) &&
                Objects.equals(productSku, that.productSku) &&
                Objects.equals(currencyCode, that.currencyCode);
    }

    @Override
    public int hashCode() {
        return Objects.hash(contractId, productSku, currencyCode);
    }

    // -------------------- Enumerations --------------------

    public enum PriceType {
        FIXED,
        TIERED,
        DISCOUNT
    }

    // -------------------- Embeddables & Nested Entities --------------------

    /**
     * Simple Money value object.
     * For simplicity, we embed referenceAmount for discount calculations.
     */
    @Embeddable
    public static class Money implements Serializable {
        private static final long serialVersionUID = -3132254282793932837L;

        @Column(name = "amount", nullable = false, precision = 19, scale = 4)
        private BigDecimal amount;

        @Column(name = "currency", nullable = false, length = 3)
        private String currencyCode;

        /**
         * Optional reference amount (e.g., list price) used for calculations in cases like DISCOUNT.
         */
        @Column(name = "reference_amount", precision = 19, scale = 4)
        private BigDecimal referenceAmount;

        protected Money() {
            /* JPA */ }

        public Money(@NotNull BigDecimal amount, @NotNull Currency currency) {
            this(amount, currency, null);
        }

        public Money(@NotNull BigDecimal amount,
                     @NotNull Currency currency,
                     BigDecimal referenceAmount) {
            this.amount = amount.setScale(4, RoundingMode.HALF_UP);
            this.currencyCode = currency.getCurrencyCode();
            this.referenceAmount = referenceAmount == null ? null :
                    referenceAmount.setScale(4, RoundingMode.HALF_UP);
        }

        public BigDecimal getAmount() {
            return amount;
        }

        public Currency getCurrency() {
            return Currency.getInstance(currencyCode);
        }

        public Optional<BigDecimal> getReferenceAmount() {
            return Optional.ofNullable(referenceAmount);
        }

        @Override
        public String toString() {
            return amount + " " + currencyCode;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Money)) return false;
            Money money = (Money) o;
            return amount.compareTo(money.amount) == 0 &&
                    Objects.equals(currencyCode, money.currencyCode);
        }

        @Override
        public int hashCode() {
            return Objects.hash(amount, currencyCode);
        }
    }

    /**
     * PriceTier represents a quantity break for {@link PriceType#TIERED} prices.
     */
    @Entity
    @Table(name = "contract_price_tiers")
    public static class PriceTier implements Serializable {
        private static final long serialVersionUID = 3202196816142225214L;

        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        private Long id;

        /**
         * Inclusive minimum quantity for which this tier applies.
         */
        @Positive
        @Column(name = "min_quantity", nullable = false)
        private int minQuantity;

        @Valid
        @Embedded
        private Money unitPrice;

        @ManyToOne(fetch = FetchType.LAZY)
        @JoinColumn(name = "contract_price_id", nullable = false)
        private ContractPrice contractPrice;

        protected PriceTier() {
            /* JPA */ }

        public PriceTier(int minQuantity, Money unitPrice) {
            if (minQuantity <= 0) {
                throw new IllegalArgumentException("minQuantity must be positive");
            }
            this.minQuantity = minQuantity;
            this.unitPrice = Objects.requireNonNull(unitPrice, "unitPrice");
        }

        public int getMinQuantity() {
            return minQuantity;
        }

        public Money getUnitPrice() {
            return unitPrice;
        }

        private void setContractPrice(ContractPrice contractPrice) {
            this.contractPrice = contractPrice;
        }

        @Override
        public String toString() {
            return "Tier " + minQuantity + "+ = " + unitPrice;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof PriceTier)) return false;
            PriceTier tier = (PriceTier) o;
            return minQuantity == tier.minQuantity &&
                    Objects.equals(unitPrice, tier.unitPrice);
        }

        @Override
        public int hashCode() {
            return Objects.hash(minQuantity, unitPrice);
        }
    }
}