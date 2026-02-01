package com.commercesphere.enterprise.ordering.model;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Embeddable;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GenerationType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.JoinTable;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.MapKeyColumn;
import jakarta.persistence.OneToMany;
import jakarta.persistence.OrderBy;
import jakarta.persistence.Table;
import jakarta.persistence.Temporal;
import jakarta.persistence.TemporalType;
import jakarta.persistence.Version;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Collections;
import java.util.Currency;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * Domain aggregate representing a quote in the quote-to-cash workflow.
 * Supports optimistic locking, auditing, and basic state transitions.
 *
 * Business rules:
 *  1. Approved or Rejected quotes are immutable.
 *  2. Totals must be re-calculated after every modification.
 *  3. A quote automatically expires after the configured TTL (handled by scheduler elsewhere).
 */
@Table(name = "cs_quotes")
@jakarta.persistence.Entity
public class Quote implements Serializable {

    @Serial
    private static final long serialVersionUID = -2263341189169389956L;

    // ------------------------------------------------------------------ //
    // Persistence attributes                                             //
    // ------------------------------------------------------------------ //

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "quote_id", nullable = false, updatable = false)
    private UUID id;

    @NotNull
    @Size(max = 40)
    @Column(name = "quote_number", nullable = false, unique = true, updatable = false)
    private String quoteNumber;

    @NotNull
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "account_id", nullable = false)
    private Account account;

    @NotNull
    @Temporal(TemporalType.TIMESTAMP)
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Temporal(TemporalType.TIMESTAMP)
    @Column(name = "expires_at")
    private Instant expiresAt;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private QuoteStatus status = QuoteStatus.DRAFT;

    @NotNull
    @Column(name = "currency", nullable = false, length = 3)
    private Currency currency;

    @Positive
    @Column(name = "grand_total", precision = 19, scale = 4, nullable = false)
    private BigDecimal grandTotal = BigDecimal.ZERO;

    /**
     * Line items keyed by SKU for fast lookup and deduplication.
     */
    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "cs_quote_items",
        joinColumns = @JoinColumn(name = "quote_id")
    )
    @MapKeyColumn(name = "sku")
    @OrderBy("position ASC")
    private Map<String, QuoteLineItem> items = new LinkedHashMap<>();

    @Version
    @Column(name = "version")
    private long version;

    // ------------------------------------------------------------------ //
    // Constructors                                                       //
    // ------------------------------------------------------------------ //

    protected Quote() {
        /* JPA spec requirement */
    }

    private Quote(Builder builder) {
        this.quoteNumber = builder.quoteNumber;
        this.account = Objects.requireNonNull(builder.account, "account");
        this.currency = Objects.requireNonNull(builder.currency, "currency");
        this.createdAt = Instant.now();
        this.expiresAt = builder.expiresAt;
        builder.items.forEach(this::addOrUpdateItem);
    }

    // ------------------------------------------------------------------ //
    // Domain behavior                                                    //
    // ------------------------------------------------------------------ //

    /**
     * Adds or replaces a new item. Calculates totals.
     *
     * @throws IllegalStateException if quote is immutable
     */
    public void addOrUpdateItem(String sku, QuoteLineItem item) {
        assertMutable();
        Objects.requireNonNull(sku, "sku");
        Objects.requireNonNull(item, "item");
        items.put(sku, item);
        recalculateTotals();
    }

    /**
     * Removes an item by SKU.
     */
    public void removeItem(String sku) {
        assertMutable();
        if (items.remove(sku) != null) {
            recalculateTotals();
        }
    }

    /**
     * Approves the quote making it unmodifiable.
     */
    public void approve() {
        assertState(QuoteStatus.SUBMITTED);
        transitionTo(QuoteStatus.APPROVED);
    }

    /**
     * Rejects the quote making it unmodifiable.
     */
    public void reject() {
        assertState(QuoteStatus.SUBMITTED);
        transitionTo(QuoteStatus.REJECTED);
    }

    /**
     * Submits the quote for approval.
     */
    public void submit() {
        assertState(QuoteStatus.DRAFT);
        if (items.isEmpty()) {
            throw new IllegalStateException("Cannot submit quote without items");
        }
        transitionTo(QuoteStatus.SUBMITTED);
    }

    /**
     * Recalculates the grand total from the current set of items.
     */
    public void recalculateTotals() {
        this.grandTotal = items.values().stream()
                               .map(QuoteLineItem::lineTotal)
                               .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    // ------------------------------------------------------------------ //
    // Helper methods                                                     //
    // ------------------------------------------------------------------ //

    private void transitionTo(QuoteStatus next) {
        this.status = next;
    }

    private void assertMutable() {
        if (status.isTerminal()) {
            throw new IllegalStateException("Quote is " + status + " and may not be modified");
        }
    }

    private void assertState(QuoteStatus expected) {
        if (this.status != expected) {
            throw new IllegalStateException("Quote status must be " + expected + " but is " + status);
        }
    }

    // ------------------------------------------------------------------ //
    // Getters                                                            //
    // ------------------------------------------------------------------ //

    public UUID getId() {
        return id;
    }

    public String getQuoteNumber() {
        return quoteNumber;
    }

    public Account getAccount() {
        return account;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getExpiresAt() {
        return expiresAt;
    }

    public QuoteStatus getStatus() {
        return status;
    }

    public Currency getCurrency() {
        return currency;
    }

    public BigDecimal getGrandTotal() {
        return grandTotal;
    }

    public Map<String, QuoteLineItem> getItems() {
        return Collections.unmodifiableMap(items);
    }

    public long getVersion() {
        return version;
    }

    // ------------------------------------------------------------------ //
    // Equality / HashCode / toString                                     //
    // ------------------------------------------------------------------ //

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Quote quote)) return false;
        return id != null && id.equals(quote.id);
    }

    @Override
    public int hashCode() {
        return 31;
    }

    @Override
    public String toString() {
        return "Quote{" +
               "id=" + id +
               ", quoteNumber='" + quoteNumber + '\'' +
               ", status=" + status +
               ", grandTotal=" + grandTotal +
               ", currency=" + currency +
               '}';
    }

    // ------------------------------------------------------------------ //
    // Builder                                                            //
    // ------------------------------------------------------------------ //

    public static class Builder {
        private final String quoteNumber;
        private final Account account;
        private final Currency currency;
        private Instant expiresAt;
        private final Map<String, QuoteLineItem> items = new LinkedHashMap<>();

        public Builder(String quoteNumber, Account account, Currency currency) {
            this.quoteNumber = Objects.requireNonNull(quoteNumber, "quoteNumber");
            this.account = Objects.requireNonNull(account, "account");
            this.currency = Objects.requireNonNull(currency, "currency");
        }

        public Builder expiresAt(Instant expiresAt) {
            this.expiresAt = expiresAt;
            return this;
        }

        public Builder addItem(String sku, QuoteLineItem item) {
            this.items.put(sku, item);
            return this;
        }

        public Quote build() {
            return new Quote(this);
        }
    }

    // ------------------------------------------------------------------ //
    // Nested types                                                       //
    // ------------------------------------------------------------------ //

    /**
     * Represents the lifecycle of a quote.
     */
    public enum QuoteStatus {
        DRAFT(false),
        SUBMITTED(false),
        APPROVED(true),
        REJECTED(true),
        EXPIRED(true);

        private final boolean terminal;

        QuoteStatus(boolean terminal) {
            this.terminal = terminal;
        }

        public boolean isTerminal() {
            return terminal;
        }
    }

    /**
     * Value object for a single line item in a quote.
     */
    @Embeddable
    public static class QuoteLineItem implements Serializable {

        @Serial
        private static final long serialVersionUID = 6761917651442040465L;

        @NotNull
        @Size(max = 64)
        @Column(name = "sku", nullable = false, insertable = false, updatable = false)
        private String sku;

        @NotNull
        @Size(max = 255)
        @Column(name = "description", nullable = false)
        private String description;

        @NotNull
        @Positive
        @Column(name = "quantity", nullable = false)
        private int quantity;

        @NotNull
        @Positive
        @Column(name = "unit_price", precision = 19, scale = 4, nullable = false)
        private BigDecimal unitPrice;

        @Column(name = "position")
        private int position;

        protected QuoteLineItem() {
            /* For JPA */
        }

        public QuoteLineItem(String sku,
                             String description,
                             int quantity,
                             BigDecimal unitPrice,
                             int position) {
            this.sku = Objects.requireNonNull(sku, "sku");
            this.description = Objects.requireNonNull(description, "description");
            this.quantity = quantity;
            this.unitPrice = Objects.requireNonNull(unitPrice, "unitPrice");
            this.position = position;
        }

        public BigDecimal lineTotal() {
            return unitPrice.multiply(BigDecimal.valueOf(quantity));
        }

        public String getSku() {
            return sku;
        }

        public String getDescription() {
            return description;
        }

        public int getQuantity() {
            return quantity;
        }

        public BigDecimal getUnitPrice() {
            return unitPrice;
        }

        public int getPosition() {
            return position;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof QuoteLineItem item)) return false;
            return Objects.equals(sku, item.sku);
        }

        @Override
        public int hashCode() {
            return Objects.hash(sku);
        }
    }
}