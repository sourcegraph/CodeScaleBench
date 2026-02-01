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
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToMany;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

/**
 * Contract represents a legally binding pricing agreement between an account
 * and CommerceSphere.  A single contract can contain multiple tier‐based
 * pricing rules covering any number of SKUs.
 *
 * The entity purposely avoids direct references to other bounded contexts
 * (e.g., Account) to reduce coupling inside the monolith.  Lookups are done
 * through foreign keys exposed as primitive identifiers.
 */
@Entity
@Table(name = "cs_contracts")
public class Contract implements Serializable {

    @Serial
    private static final long serialVersionUID = 2865149478797428839L;

    // ------------------------------------------------------------------------
    // Enums
    // ------------------------------------------------------------------------

    public enum Status {
        DRAFT,
        ACTIVE,
        SUSPENDED,
        TERMINATED,
        EXPIRED
    }

    // ------------------------------------------------------------------------
    // Fields
    // ------------------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @NotBlank
    @Size(max = 64)
    @Column(name = "contract_number", nullable = false, unique = true, length = 64)
    private String contractNumber;

    /**
     * Foreign key reference to the owning account.
     */
    @NotNull
    @Column(name = "account_id", nullable = false)
    private Long accountId;

    @NotNull
    @Column(name = "start_date", nullable = false)
    private LocalDate startDate;

    @Column(name = "end_date")
    private LocalDate endDate;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private Status status = Status.DRAFT;

    /**
     * ISO-4217 currency code.
     */
    @NotBlank
    @Size(min = 3, max = 3)
    @Column(nullable = false, length = 3)
    private String currency;

    @OneToMany(
            mappedBy = "contract",
            cascade = CascadeType.ALL,
            orphanRemoval = true,
            fetch = FetchType.LAZY
    )
    private List<TierPrice> tierPrices = new ArrayList<>();

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at")
    private Instant updatedAt;

    /**
     * Optimistic locking column.
     */
    @Version
    private Long version;

    // ------------------------------------------------------------------------
    // Constructors
    // ------------------------------------------------------------------------

    protected Contract() {
        /* JPA ONLY */
    }

    private Contract(Builder builder) {
        this.contractNumber = builder.contractNumber;
        this.accountId = builder.accountId;
        this.startDate = builder.startDate;
        this.endDate = builder.endDate;
        this.status = builder.status;
        this.currency = builder.currency;
        builder.tierPrices.forEach(this::addTierPrice);
    }

    // ------------------------------------------------------------------------
    // Factory
    // ------------------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    // ------------------------------------------------------------------------
    // Domain logic
    // ------------------------------------------------------------------------

    /**
     * Returns {@code true} when the contract is ACTIVE and the provided date
     * falls within the start/end date range.
     */
    public boolean isActive(LocalDate onDate) {
        Objects.requireNonNull(onDate, "onDate must not be null");
        return status == Status.ACTIVE
                && (onDate.isEqual(startDate) || onDate.isAfter(startDate))
                && (endDate == null || onDate.isBefore(endDate) || onDate.isEqual(endDate));
    }

    /**
     * Resolve the contract price for the given SKU and quantity.
     *
     * @param sku      product identifier
     * @param quantity requested quantity
     * @return optional price; empty when no tier applies
     */
    public Optional<BigDecimal> getPriceFor(String sku, int quantity) {
        Objects.requireNonNull(sku, "sku must not be null");
        if (quantity <= 0) {
            throw new IllegalArgumentException("quantity must be > 0");
        }

        return tierPrices.stream()
                .filter(t -> t.matches(sku, quantity))
                .max(Comparator.comparingInt(TierPrice::getMinQuantity))
                .map(TierPrice::getPrice);
    }

    /**
     * Adds or replaces a tier price ensuring bi-directional relationship
     * integrity.
     */
    public void addTierPrice(TierPrice tierPrice) {
        Objects.requireNonNull(tierPrice, "tierPrice must not be null");
        tierPrice.setContract(this);
        tierPrices.remove(tierPrice); // remove existing with same identity
        tierPrices.add(tierPrice);
    }

    public void removeTierPrice(TierPrice tierPrice) {
        Objects.requireNonNull(tierPrice, "tierPrice must not be null");
        tierPrices.remove(tierPrice);
        tierPrice.setContract(null);
    }

    // ------------------------------------------------------------------------
    // JPA callbacks
    // ------------------------------------------------------------------------

    @PrePersist
    protected void onCreate() {
        createdAt = Instant.now();
        updatedAt = createdAt;
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = Instant.now();
    }

    // ------------------------------------------------------------------------
    // Getters & Setters (No public setters for immutables)
    // ------------------------------------------------------------------------

    public Long getId() {
        return id;
    }

    public String getContractNumber() {
        return contractNumber;
    }

    public Long getAccountId() {
        return accountId;
    }

    public LocalDate getStartDate() {
        return startDate;
    }

    public LocalDate getEndDate() {
        return endDate;
    }

    public Status getStatus() {
        return status;
    }

    public String getCurrency() {
        return currency;
    }

    public List<TierPrice> getTierPrices() {
        return List.copyOf(tierPrices);
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public Long getVersion() {
        return version;
    }

    public void setStatus(Status status) {
        this.status = status;
    }

    // ------------------------------------------------------------------------
    // Equality
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Contract that)) return false;
        // When id is null we fall back to object identity
        return id != null && id.equals(that.id);
    }

    @Override
    public int hashCode() {
        return id == null ? System.identityHashCode(this) : Objects.hash(id);
    }

    // ------------------------------------------------------------------------
    // Builder
    // ------------------------------------------------------------------------

    public static final class Builder {

        private String contractNumber;
        private Long accountId;
        private LocalDate startDate;
        private LocalDate endDate;
        private Status status = Status.DRAFT;
        private String currency;
        private final List<TierPrice> tierPrices = new ArrayList<>();

        private Builder() {
        }

        public Builder contractNumber(String contractNumber) {
            this.contractNumber = contractNumber;
            return this;
        }

        public Builder accountId(Long accountId) {
            this.accountId = accountId;
            return this;
        }

        public Builder startDate(LocalDate startDate) {
            this.startDate = startDate;
            return this;
        }

        public Builder endDate(LocalDate endDate) {
            this.endDate = endDate;
            return this;
        }

        public Builder status(Status status) {
            this.status = status;
            return this;
        }

        public Builder currency(String currency) {
            this.currency = currency;
            return this;
        }

        public Builder addTierPrice(TierPrice tierPrice) {
            this.tierPrices.add(tierPrice);
            return this;
        }

        public Contract build() {
            Objects.requireNonNull(contractNumber, "contractNumber");
            Objects.requireNonNull(accountId, "accountId");
            Objects.requireNonNull(startDate, "startDate");
            Objects.requireNonNull(currency, "currency");

            if (endDate != null && endDate.isBefore(startDate)) {
                throw new IllegalArgumentException("endDate must be after startDate");
            }

            return new Contract(this);
        }
    }

    // ------------------------------------------------------------------------
    // Nested Entity – TierPrice
    // ------------------------------------------------------------------------

    /**
     * TierPrice represents a single pricing rule inside a contract.  It maps
     * a SKU and quantity range to a fixed unit price.
     */
    @Entity
    @Table(name = "cs_contract_tier_prices")
    public static class TierPrice implements Serializable {

        @Serial
        private static final long serialVersionUID = -1022334133127193199L;

        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        private Long id;

        @NotBlank
        @Size(max = 64)
        @Column(nullable = false, length = 64)
        private String sku;

        @NotNull
        @Column(name = "min_qty", nullable = false)
        private Integer minQuantity;

        @Column(name = "max_qty")
        private Integer maxQuantity;

        @NotNull
        @Column(nullable = false, precision = 15, scale = 4)
        private BigDecimal price;

        @ManyToOne(fetch = FetchType.LAZY)
        @JoinColumn(name = "contract_id", nullable = false, updatable = false)
        private Contract contract;

        protected TierPrice() {
            /* JPA ONLY */
        }

        public TierPrice(String sku, int minQuantity, Integer maxQuantity, BigDecimal price) {
            this.sku = Objects.requireNonNull(sku, "sku");
            this.minQuantity = minQuantity;
            this.maxQuantity = maxQuantity;
            this.price = Objects.requireNonNull(price, "price");

            if (minQuantity <= 0) {
                throw new IllegalArgumentException("minQuantity must be > 0");
            }
            if (maxQuantity != null && maxQuantity < minQuantity) {
                throw new IllegalArgumentException("maxQuantity must be >= minQuantity");
            }
            if (price.signum() <= 0) {
                throw new IllegalArgumentException("price must be > 0");
            }
        }

        // --------------------------------------------------------------------
        // Domain helpers
        // --------------------------------------------------------------------

        private boolean matches(String requestedSku, int requestedQty) {
            if (!this.sku.equals(requestedSku)) {
                return false;
            }

            boolean lowerBound = requestedQty >= minQuantity;
            boolean upperBound = maxQuantity == null || requestedQty <= maxQuantity;
            return lowerBound && upperBound;
        }

        // --------------------------------------------------------------------
        // Getters & Setters
        // --------------------------------------------------------------------

        public Long getId() {
            return id;
        }

        public String getSku() {
            return sku;
        }

        public Integer getMinQuantity() {
            return minQuantity;
        }

        public Integer getMaxQuantity() {
            return maxQuantity;
        }

        public BigDecimal getPrice() {
            return price;
        }

        public Contract getContract() {
            return contract;
        }

        private void setContract(Contract contract) {
            this.contract = contract;
        }

        // --------------------------------------------------------------------
        // Equality
        // --------------------------------------------------------------------

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof TierPrice that)) return false;
            return id != null && id.equals(that.id);
        }

        @Override
        public int hashCode() {
            return id == null ? System.identityHashCode(this) : Objects.hash(id);
        }
    }
}