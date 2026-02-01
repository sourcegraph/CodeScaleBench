```java
package com.commercesphere.enterprise.pricing.engine;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Clock;
import java.time.LocalDateTime;
import java.util.Currency;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * PricingRule is the behavioural contract for all dynamic price manipulations
 * executed by the CommerceSphere Pricing Engine.
 *
 * <p>A rule implementation must be:
 * <ul>
 *     <li>Immutable – once constructed, its internal state cannot change.</li>
 *     <li>Stateless – execution must rely solely on the provided
 *         {@link PricingContext} and the internal value object state.</li>
 *     <li>Thread-safe – required as rules are cached and executed by a
 *         shared ThreadPoolExecutor.</li>
 * </ul>
 *
 * <p>The engine calls {@link #apply(PricingContext)} in ascending
 * priority order (lower value = higher priority).  If
 * {@link #isStackable()} returns {@code false}, the engine will halt
 * further processing after the rule is successfully applied.</p>
 */
public abstract class PricingRule implements Comparable<PricingRule> {

    private final UUID id;
    private final String ruleCode;
    private final String description;
    private final int priority;
    private final boolean stackable;
    private final LocalDateTime validFrom;
    private final LocalDateTime validUntil;
    private final List<String> customerGroupWhitelist; // empty == all groups
    private final Clock clock;

    /**
     * Create a new immutable PricingRule.
     *
     * @param id                       unique identifier (usually DB PK)
     * @param ruleCode                 stable business readable code
     * @param description              long-form description for admin UI
     * @param priority                 ordering – lower executes first
     * @param stackable                whether rules after this one should execute
     * @param validFrom                inclusive begin timestamp
     * @param validUntil               exclusive end timestamp
     * @param customerGroupWhitelist   optional customer groups filter
     * @param clock                    clock used for determinism in tests
     */
    protected PricingRule(
            UUID id,
            String ruleCode,
            String description,
            int priority,
            boolean stackable,
            LocalDateTime validFrom,
            LocalDateTime validUntil,
            List<String> customerGroupWhitelist,
            Clock clock) {

        this.id = Objects.requireNonNull(id, "id");
        this.ruleCode = Objects.requireNonNull(ruleCode, "ruleCode");
        this.description = description;
        this.priority = priority;
        this.stackable = stackable;
        this.validFrom = validFrom;
        this.validUntil = validUntil;
        this.customerGroupWhitelist = customerGroupWhitelist == null ? List.of() : List.copyOf(customerGroupWhitelist);
        this.clock = clock == null ? Clock.systemUTC() : clock;
    }

    // ------------------------------------------------------------------ API

    /**
     * Evaluate the rule for the given context.
     *
     * @param ctx   non-null pricing context
     * @return outcome object encapsulating the result of evaluation
     * @throws PricingException if evaluation fails unexpectedly
     */
    public final RuleOutcome apply(PricingContext ctx) throws PricingException {
        Objects.requireNonNull(ctx, "ctx");

        if (!isWithinDateRange()) {
            return RuleOutcome.notApplied(ruleCode, "Rule is out of validity date range");
        }

        if (!isCustomerEligible(ctx)) {
            return RuleOutcome.notApplied(ruleCode, "Customer group not eligible");
        }

        try {
            Money adjustment = calculateAdjustment(ctx);

            if (adjustment.isZero()) {
                return RuleOutcome.notApplied(ruleCode, "Adjustment evaluated to 0");
            }

            Money newPrice = ctx.getCurrentPrice().add(adjustment);

            // price cannot be negative
            if (newPrice.isNegative()) {
                newPrice = Money.zero(newPrice.getCurrency());
            }

            return RuleOutcome.applied(
                    ruleCode,
                    newPrice,
                    adjustment,
                    stackable,
                    Map.of("description", description == null ? "" : description));

        } catch (Exception ex) {
            throw new PricingException("Failed to apply pricing rule: " + ruleCode, ex);
        }
    }

    /**
     * Calculate a monetary adjustment relative to {@link PricingContext#getCurrentPrice()}.
     * Positive adjustments mark a surcharge; negative – a discount.
     */
    protected abstract Money calculateAdjustment(PricingContext ctx);

    /**
     * Whether further rules should be evaluated after this rule is applied.
     */
    public final boolean isStackable() {
        return stackable;
    }

    /**
     * Priority ordering (lower executes first).
     */
    public final int getPriority() {
        return priority;
    }

    /**
     * Rule code as referenced in the admin panel / logs.
     */
    public final String getRuleCode() {
        return ruleCode;
    }

    // ------------------------------------------------------------------ Helpers

    private boolean isWithinDateRange() {
        LocalDateTime now = LocalDateTime.now(clock);
        boolean afterStart = validFrom == null || !now.isBefore(validFrom);
        boolean beforeEnd = validUntil == null || now.isBefore(validUntil);
        return afterStart && beforeEnd;
    }

    private boolean isCustomerEligible(PricingContext ctx) {
        if (customerGroupWhitelist.isEmpty()) {
            return true;
        }
        return ctx.getCustomerGroup() != null && customerGroupWhitelist.contains(ctx.getCustomerGroup());
    }

    @Override
    public int compareTo(PricingRule other) {
        return Integer.compare(this.priority, other.priority);
    }

    // ------------------------------------------------------------------ Value Objects / Helpers

    /**
     * Execution context passed to rules.
     */
    public static final class PricingContext {

        private final String sku;
        private final int quantity;
        private final Money basePrice;
        private final String customerGroup;
        private final Map<String, Object> attributes;

        private Money currentPrice;

        public PricingContext(
                String sku,
                int quantity,
                Money basePrice,
                String customerGroup,
                Map<String, Object> attributes) {

            if (quantity <= 0) throw new IllegalArgumentException("quantity must be > 0");

            this.sku = Objects.requireNonNull(sku, "sku");
            this.quantity = quantity;
            this.basePrice = Objects.requireNonNull(basePrice, "basePrice");
            this.customerGroup = customerGroup;
            this.attributes = attributes == null ? Map.of() : Map.copyOf(attributes);

            this.currentPrice = basePrice; // may mutate while pipeline progresses
        }

        public String getSku() {
            return sku;
        }

        public int getQuantity() {
            return quantity;
        }

        public Money getBasePrice() {
            return basePrice;
        }

        public Money getCurrentPrice() {
            return currentPrice;
        }

        public void setCurrentPrice(Money currentPrice) {
            this.currentPrice = Objects.requireNonNull(currentPrice, "currentPrice");
        }

        public String getCustomerGroup() {
            return customerGroup;
        }

        public Map<String, Object> getAttributes() {
            return attributes;
        }
    }

    /**
     * Outcome of a rule evaluation.
     */
    public static final class RuleOutcome {

        private final boolean applied;
        private final String ruleCode;
        private final Money resultingPrice;
        private final Money adjustment;
        private final boolean stackable;
        private final Map<String, String> meta;

        private RuleOutcome(
                boolean applied,
                String ruleCode,
                Money resultingPrice,
                Money adjustment,
                boolean stackable,
                Map<String, String> meta) {

            this.applied = applied;
            this.ruleCode = ruleCode;
            this.resultingPrice = resultingPrice;
            this.adjustment = adjustment;
            this.stackable = stackable;
            this.meta = meta;
        }

        public static RuleOutcome applied(
                String ruleCode,
                Money resultingPrice,
                Money adjustment,
                boolean stackable,
                Map<String, String> meta) {

            return new RuleOutcome(true, ruleCode, resultingPrice, adjustment, stackable, meta);
        }

        public static RuleOutcome notApplied(
                String ruleCode,
                String reason) {

            return new RuleOutcome(false, ruleCode, null, Money.zero(Currency.getInstance("USD")),
                    true, Map.of("reason", reason));
        }

        public boolean isApplied() {
            return applied;
        }

        public String getRuleCode() {
            return ruleCode;
        }

        public Money getResultingPrice() {
            return resultingPrice;
        }

        public Money getAdjustment() {
            return adjustment;
        }

        public boolean isStackable() {
            return stackable;
        }

        public Map<String, String> getMeta() {
            return meta;
        }
    }

    /**
     * Domain specific exception thrown for any rule processing errors.
     */
    public static class PricingException extends RuntimeException {
        public PricingException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * Minimal Money implementation to avoid external library dependencies.
     * Supports only the functionality required by the pricing engine.
     */
    public static final class Money {

        private final BigDecimal amount;
        private final Currency currency;

        private Money(BigDecimal amount, Currency currency) {
            this.amount = amount.setScale(2, RoundingMode.HALF_UP);
            this.currency = currency;
        }

        public static Money of(BigDecimal amount, Currency currency) {
            return new Money(amount, currency);
        }

        public static Money zero(Currency currency) {
            return new Money(BigDecimal.ZERO, currency);
        }

        public BigDecimal getAmount() {
            return amount;
        }

        public Currency getCurrency() {
            return currency;
        }

        public boolean isZero() {
            return amount.compareTo(BigDecimal.ZERO) == 0;
        }

        public boolean isNegative() {
            return amount.compareTo(BigDecimal.ZERO) < 0;
        }

        public Money add(Money other) {
            validateCurrency(other);
            return new Money(amount.add(other.amount), currency);
        }

        public Money subtract(Money other) {
            validateCurrency(other);
            return new Money(amount.subtract(other.amount), currency);
        }

        public Money multiply(long factor) {
            return new Money(amount.multiply(BigDecimal.valueOf(factor)), currency);
        }

        public int compareTo(Money other) {
            validateCurrency(other);
            return amount.compareTo(other.amount);
        }

        private void validateCurrency(Money other) {
            if (!currency.equals(other.currency)) {
                throw new IllegalArgumentException("Currency mismatch: " + currency + " vs " + other.currency);
            }
        }

        @Override
        public String toString() {
            return currency.getCurrencyCode() + " " + amount;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Money money)) return false;
            return amount.equals(money.amount) && currency.equals(money.currency);
        }

        @Override
        public int hashCode() {
            return Objects.hash(amount, currency);
        }
    }
}
```