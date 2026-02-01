package com.commercesphere.enterprise.user.model;

import jakarta.persistence.*;
import jakarta.validation.constraints.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.util.Assert;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Objects;

/**
 * Domain aggregate that represents a B2B company account in the CommerceSphere platform.
 * <p>
 * The entity encapsulates credit handling, pricing tier assignments, and hierarchical
 * relationships between parent/child accounts.  It is persisted via JPA/Hibernate and
 * guarded with optimistic locking to ensure concurrent modifications are detected.
 */
@Entity
@Table(name = "cs_company_account",
       uniqueConstraints = {
           @UniqueConstraint(name = "uk_cs_company_vat", columnNames = {"vat_number"}),
           @UniqueConstraint(name = "uk_cs_company_tax", columnNames = {"tax_id"})
       })
public class CompanyAccount implements Serializable {

    @Serial
    private static final long serialVersionUID = 6477765645318984703L;
    private static final Logger LOG = LoggerFactory.getLogger(CompanyAccount.class);

    // ------------------------------------------------------------------------
    // Persistent fields
    // ------------------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @NotBlank
    @Size(max = 255)
    @Column(name = "company_name", nullable = false, length = 255)
    private String companyName;

    @NotBlank
    @Size(max = 255)
    @Column(name = "legal_name", nullable = false, length = 255)
    private String legalName;

    @Size(max = 64)
    @Column(name = "vat_number", length = 64, updatable = false)
    private String vatNumber;

    @Size(max = 64)
    @Column(name = "tax_id", length = 64, updatable = false)
    private String taxId;

    @Enumerated(EnumType.STRING)
    @Column(name = "account_status", nullable = false, length = 32)
    private AccountStatus status = AccountStatus.PENDING_ACTIVATION;

    @Enumerated(EnumType.STRING)
    @Column(name = "price_tier", nullable = false, length = 32)
    private PriceTier priceTier = PriceTier.STANDARD;

    @NotNull
    @Positive
    @Column(name = "credit_limit", nullable = false, precision = 19, scale = 4)
    private BigDecimal creditLimit = BigDecimal.ZERO;

    @NotNull
    @PositiveOrZero
    @Column(name = "available_credit", nullable = false, precision = 19, scale = 4)
    private BigDecimal availableCredit = BigDecimal.ZERO;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "parent_account_id", foreignKey = @ForeignKey(name = "fk_company_parent"))
    private CompanyAccount parentAccount;

    @Column(name = "workflow_enabled", nullable = false)
    private boolean approvalWorkflowEnabled = false;

    // ------------------------------------------------------------------------
    // Metadata
    // ------------------------------------------------------------------------

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    @Version
    private Long version;

    // ------------------------------------------------------------------------
    // Transient collaborators
    // ------------------------------------------------------------------------

    /**
     * Spring event publisher injected by the infrastructure layer. Marked as {@code transient}
     * to avoid serialization issues and to indicate that it is not part of the persistent
     * state of the aggregate.
     */
    @Transient
    private transient ApplicationEventPublisher eventPublisher;

    /* ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ */

    protected CompanyAccount() {
        /* for JPA */
    }

    private CompanyAccount(Builder builder) {
        this.companyName = builder.companyName;
        this.legalName = builder.legalName;
        this.vatNumber = builder.vatNumber;
        this.taxId = builder.taxId;
        this.creditLimit = builder.creditLimit;
        this.availableCredit = builder.availableCredit.min(builder.creditLimit);
        this.priceTier = builder.priceTier;
        this.status = builder.status;
        this.approvalWorkflowEnabled = builder.approvalWorkflowEnabled;
    }

    // ------------------------------------------------------------------------
    // Domain factory
    // ------------------------------------------------------------------------

    public static Builder builder(String companyName, String legalName) {
        return new Builder(companyName, legalName);
    }

    // ------------------------------------------------------------------------
    // Domain behavior
    // ------------------------------------------------------------------------

    /**
     * Debits credit from the account.
     *
     * @param amount non-null positive value
     * @throws InsufficientCreditException if the amount exceeds the available credit
     */
    public void debitCredit(BigDecimal amount) throws InsufficientCreditException {
        requireActive();
        validateAmount(amount);

        if (availableCredit.compareTo(amount) < 0) {
            LOG.warn("Attempt to debit {} exceeds available credit {} for account {}", amount, availableCredit, id);
            throw new InsufficientCreditException(id, amount, availableCredit);
        }

        availableCredit = availableCredit.subtract(amount);
        publishDomainEvent(new CreditChangedEvent(this, availableCredit));

        LOG.debug("Debited {} from account {}. New available credit: {}", amount, id, availableCredit);
    }

    /**
     * Credits funds back to the account, capping the value at {@code creditLimit}.
     *
     * @param amount non-null positive value
     */
    public void creditAccount(BigDecimal amount) {
        requireActive();
        validateAmount(amount);

        BigDecimal newCredit = availableCredit.add(amount);
        availableCredit = newCredit.min(creditLimit);
        publishDomainEvent(new CreditChangedEvent(this, availableCredit));

        LOG.debug("Credited {} to account {}. New available credit: {}", amount, id, availableCredit);
    }

    /**
     * Immediately deactivates the company account.  Deactivated accounts are not
     * allowed to transact.
     */
    public void deactivate() {
        if (status == AccountStatus.DEACTIVATED) {
            return;
        }
        status = AccountStatus.DEACTIVATED;
        publishDomainEvent(new StatusChangedEvent(this, status));
        LOG.info("Company account {} deactivated", id);
    }

    /**
     * Reactivates a previously deactivated account.
     */
    public void activate() {
        if (status == AccountStatus.ACTIVE) {
            return;
        }
        status = AccountStatus.ACTIVE;
        publishDomainEvent(new StatusChangedEvent(this, status));
        LOG.info("Company account {} activated", id);
    }

    /**
     * Changes the price tier and publishes a domain event for other bounded contexts
     * (e.g., catalog or pricing services) to react.
     *
     * @param newPriceTier the new tier
     */
    public void changePriceTier(PriceTier newPriceTier) {
        Assert.notNull(newPriceTier, "New price tier cannot be null");

        if (priceTier == newPriceTier) {
            return;
        }
        priceTier = newPriceTier;
        publishDomainEvent(new PriceTierChangedEvent(this, newPriceTier));
        LOG.info("Company account {} changed price tier to {}", id, newPriceTier);
    }

    /* --------------------------------------------------------------------- */
    /* Auxiliary helpers                                                     */
    /* --------------------------------------------------------------------- */

    private void requireActive() {
        if (status != AccountStatus.ACTIVE) {
            throw new IllegalStateException("Account must be active to perform this operation");
        }
    }

    private static void validateAmount(BigDecimal amount) {
        Assert.notNull(amount, "Amount must not be null");
        if (amount.signum() <= 0) {
            throw new IllegalArgumentException("Amount must be positive");
        }
    }

    private void publishDomainEvent(ApplicationEvent event) {
        if (eventPublisher != null) {
            eventPublisher.publishEvent(event);
        }
    }

    // ------------------------------------------------------------------------
    // Getters / setters
    // ------------------------------------------------------------------------

    public Long getId() {
        return id;
    }

    public String getCompanyName() {
        return companyName;
    }

    public String getLegalName() {
        return legalName;
    }

    public String getVatNumber() {
        return vatNumber;
    }

    public String getTaxId() {
        return taxId;
    }

    public AccountStatus getStatus() {
        return status;
    }

    public PriceTier getPriceTier() {
        return priceTier;
    }

    public BigDecimal getCreditLimit() {
        return creditLimit;
    }

    public BigDecimal getAvailableCredit() {
        return availableCredit;
    }

    public CompanyAccount getParentAccount() {
        return parentAccount;
    }

    public boolean isApprovalWorkflowEnabled() {
        return approvalWorkflowEnabled;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    // ------------------------------------------------------------------------
    // Builder
    // ------------------------------------------------------------------------

    public static final class Builder {
        private final String companyName;
        private final String legalName;
        private String vatNumber;
        private String taxId;
        private PriceTier priceTier = PriceTier.STANDARD;
        private BigDecimal creditLimit = BigDecimal.ZERO;
        private BigDecimal availableCredit = BigDecimal.ZERO;
        private AccountStatus status = AccountStatus.PENDING_ACTIVATION;
        private boolean approvalWorkflowEnabled;

        private Builder(String companyName, String legalName) {
            this.companyName = companyName;
            this.legalName = legalName;
        }

        public Builder vatNumber(String vatNumber) {
            this.vatNumber = vatNumber;
            return this;
        }

        public Builder taxId(String taxId) {
            this.taxId = taxId;
            return this;
        }

        public Builder priceTier(PriceTier priceTier) {
            this.priceTier = priceTier;
            return this;
        }

        public Builder creditLimit(BigDecimal creditLimit) {
            this.creditLimit = creditLimit;
            return this;
        }

        public Builder availableCredit(BigDecimal availableCredit) {
            this.availableCredit = availableCredit;
            return this;
        }

        public Builder status(AccountStatus status) {
            this.status = status;
            return this;
        }

        public Builder approvalWorkflowEnabled(boolean enabled) {
            this.approvalWorkflowEnabled = enabled;
            return this;
        }

        public CompanyAccount build() {
            return new CompanyAccount(this);
        }
    }

    // ------------------------------------------------------------------------
    // Domain events
    // ------------------------------------------------------------------------

    public static final class CreditChangedEvent extends ApplicationEvent {
        @Serial
        private static final long serialVersionUID = 437674176023676893L;
        private final BigDecimal newBalance;

        public CreditChangedEvent(CompanyAccount source, BigDecimal newBalance) {
            super(source);
            this.newBalance = newBalance;
        }

        public BigDecimal getNewBalance() {
            return newBalance;
        }

        public Long getAccountId() {
            return ((CompanyAccount) getSource()).getId();
        }
    }

    public static final class StatusChangedEvent extends ApplicationEvent {
        @Serial
        private static final long serialVersionUID = -5432820675587070218L;
        private final AccountStatus newStatus;

        public StatusChangedEvent(CompanyAccount source, AccountStatus newStatus) {
            super(source);
            this.newStatus = newStatus;
        }

        public AccountStatus getNewStatus() {
            return newStatus;
        }

        public Long getAccountId() {
            return ((CompanyAccount) getSource()).getId();
        }
    }

    public static final class PriceTierChangedEvent extends ApplicationEvent {
        @Serial
        private static final long serialVersionUID = -1157444471855402011L;
        private final PriceTier newTier;

        public PriceTierChangedEvent(CompanyAccount source, PriceTier newTier) {
            super(source);
            this.newTier = newTier;
        }

        public PriceTier getNewTier() {
            return newTier;
        }

        public Long getAccountId() {
            return ((CompanyAccount) getSource()).getId();
        }
    }

    // ------------------------------------------------------------------------
    // Custom exception
    // ------------------------------------------------------------------------

    public static class InsufficientCreditException extends RuntimeException {
        @Serial
        private static final long serialVersionUID = -7442446798281302706L;

        public InsufficientCreditException(Long accountId, BigDecimal request, BigDecimal available) {
            super("Insufficient credit for account " + accountId +
                  ". Requested: " + request + " Available: " + available);
        }
    }

    // ------------------------------------------------------------------------
    // Value objects
    // ------------------------------------------------------------------------

    public enum AccountStatus {
        PENDING_ACTIVATION,
        ACTIVE,
        DEACTIVATED,
        SUSPENDED
    }

    public enum PriceTier {
        STANDARD,
        BRONZE,
        SILVER,
        GOLD,
        PLATINUM
    }

    // ------------------------------------------------------------------------
    // Equals / hashCode - uses business key (id) semantics
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof CompanyAccount that)) return false;
        return id != null && Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return 31;
    }

    /* ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ */
}