package com.commercesphere.enterprise.pricing.engine;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * TieredPricingRule is responsible for applying tiered‐discount logic to a
 * product’s base price.  A typical B2B wholesaler offers price breaks at
 * quantity boundaries (e.g. 10 units → 5 % off, 100 units → 10 % off).
 * <p>
 * This rule is intentionally immutable and thread-safe.  It can therefore be
 * cached and shared across request invocations without additional locking.
 *
 * <pre>
 * Example:
 * ┌─────────┬────────┬───────────────────────┐
 * │ minQty  │ maxQty │ discount (percentage) │
 * ├─────────┼────────┼───────────────────────┤
 * │ 1       │ 9      │ 0 %                   │
 * │ 10      │ 99     │ 5 %                   │
 * │ 100     │ *      │ 12 %                  │
 * └─────────┴────────┴───────────────────────┘
 * </pre>
 *
 * @implNote Monetary calculations use {@link BigDecimal} with scale = 4 to
 *           reduce rounding errors and comply with PCI-DSS recommendations.
 */
public final class TieredPricingRule implements PricingRule, Serializable {

    @Serial
    private static final long serialVersionUID = -4247601277381231872L;

    private static final Logger LOGGER = LoggerFactory.getLogger(TieredPricingRule.class);

    /**
     * List of ordered, non-overlapping tiers.
     */
    private final List<Tier> tiers;

    /**
     * Name of the rule, primarily for diagnostics and reporting.
     */
    private final String ruleName;

    /**
     * Constructs a new rule instance.  Use {@link Builder} for complex
     * configuration or direct invocation for simple rule creation.
     *
     * @param ruleName human-readable name
     * @param tiers    ordered list of tiers
     */
    private TieredPricingRule(String ruleName, List<Tier> tiers) {
        this.ruleName = ruleName;
        this.tiers = tiers;
    }

    // ---------------------------------------------------------------------    
    // PricingRule implementation
    // ---------------------------------------------------------------------

    /**
     * Applies tiered pricing to the supplied {@link PricingContext}.
     *
     * @param ctx evaluation context
     * @return final unit price after tiered discounts
     * @throws PricingEngineException when validation fails or no suitable tier
     *                                exists
     */
    @Override
    public BigDecimal apply(PricingContext ctx) throws PricingEngineException {

        Objects.requireNonNull(ctx, "PricingContext must not be null");

        LOGGER.debug("Applying TieredPricingRule [{}] to sku={}, quantity={}",
                     ruleName, ctx.getSku(), ctx.getQuantity());

        int requestedQty = ctx.getQuantity();

        // Identify tier
        Tier applicableTier = tiers.stream()
                                   .filter(t -> t.appliesTo(requestedQty))
                                   .findFirst()
                                   .orElseThrow(() -> new PricingEngineException(
                                           "No tier configured for quantity " + requestedQty));

        BigDecimal discountedPrice = applicableTier.calculateUnitPrice(ctx.getBasePrice());

        if (LOGGER.isDebugEnabled()) {
            LOGGER.debug("Tier matched: {}. Base price={}, discounted price={}",
                         applicableTier, ctx.getBasePrice(), discountedPrice);
        }

        return discountedPrice;
    }

    @Override
    public String getName() {
        return ruleName;
    }

    // ---------------------------------------------------------------------    
    // Getters
    // ---------------------------------------------------------------------

    public List<Tier> getTiers() {
        return Collections.unmodifiableList(tiers);
    }

    // ---------------------------------------------------------------------    
    // Builder
    // ---------------------------------------------------------------------

    public static Builder builder(String ruleName) {
        return new Builder(ruleName);
    }

    public static final class Builder {

        private final String ruleName;
        private final List<Tier> tiers = new ArrayList<>();

        private Builder(String ruleName) {
            this.ruleName = Objects.requireNonNull(ruleName, "ruleName");
        }

        /**
         * Adds a discount tier based on percentage off of the {@code basePrice}.
         *
         * @param minQty          inclusive minimum quantity
         * @param maxQty          inclusive maximum quantity.  Use
         *                        {@link Integer#MAX_VALUE} for no upper bound.
         * @param percentageOff   e.g. 0.05 → 5 % off.  Must be in range [0, 1).
         * @return this builder
         */
        public Builder percentageDiscount(int minQty, int maxQty, BigDecimal percentageOff) {
            tiers.add(Tier.percentage(minQty, maxQty, percentageOff));
            return this;
        }

        /**
         * Adds a fixed unit price tier.
         *
         * @param minQty    inclusive minimum quantity
         * @param maxQty    inclusive maximum quantity
         * @param unitPrice final unit price (after discount)
         * @return this builder
         */
        public Builder fixedUnitPrice(int minQty, int maxQty, BigDecimal unitPrice) {
            tiers.add(Tier.fixed(minQty, maxQty, unitPrice));
            return this;
        }

        /**
         * Validates tier configuration and builds the {@link TieredPricingRule}.
         *
         * @return immutable rule
         */
        public TieredPricingRule build() {
            if (tiers.isEmpty()) {
                throw new IllegalStateException("At least one tier must be defined");
            }

            // ---- Sort tiers by minimum quantity
            tiers.sort(Comparator.comparingInt(t -> t.minQty));

            // ---- Validate ranges are contiguous and non-overlapping
            int expectedMin = tiers.get(0).minQty;
            for (Tier t : tiers) {
                if (t.minQty != expectedMin) {
                    throw new IllegalStateException(
                            "Gap or overlap detected in tier configuration around quantity "
                            + expectedMin);
                }
                expectedMin = t.maxQty == Integer.MAX_VALUE ? Integer.MAX_VALUE : t.maxQty + 1;
            }

            return new TieredPricingRule(ruleName, List.copyOf(tiers));
        }
    }

    // ---------------------------------------------------------------------    
    // Tier
    // ---------------------------------------------------------------------

    /**
     * Represents a single pricing tier.
     */
    public static final class Tier implements Serializable {

        @Serial
        private static final long serialVersionUID = -6185848564087181210L;

        private static final MathContext MATH_CONTEXT = new MathContext(16, RoundingMode.HALF_EVEN);

        private final int minQty;
        private final int maxQty;
        private final TierType type;
        private final BigDecimal value; // percentageOff OR fixedUnitPrice

        private Tier(int minQty, int maxQty, TierType type, BigDecimal value) {
            validateRange(minQty, maxQty);
            this.minQty = minQty;
            this.maxQty = maxQty;
            this.type = Objects.requireNonNull(type, "type");
            this.value = value.setScale(4, RoundingMode.HALF_EVEN);
        }

        public static Tier percentage(int minQty, int maxQty, BigDecimal percentageOff) {
            if (percentageOff == null || percentageOff.compareTo(BigDecimal.ZERO) < 0
                || percentageOff.compareTo(BigDecimal.ONE) >= 0) {
                throw new IllegalArgumentException(
                        "percentageOff must be >= 0 and < 1. Provided: " + percentageOff);
            }
            return new Tier(minQty, maxQty, TierType.PERCENTAGE_DISCOUNT, percentageOff);
        }

        public static Tier fixed(int minQty, int maxQty, BigDecimal unitPrice) {
            if (unitPrice == null || unitPrice.compareTo(BigDecimal.ZERO) < 0) {
                throw new IllegalArgumentException("unitPrice must be >= 0");
            }
            return new Tier(minQty, maxQty, TierType.FIXED_UNIT_PRICE, unitPrice);
        }

        private static void validateRange(int minQty, int maxQty) {
            if (minQty <= 0) {
                throw new IllegalArgumentException("minQty must be > 0");
            }
            if (maxQty < minQty) {
                throw new IllegalArgumentException("maxQty must be >= minQty");
            }
        }

        public boolean appliesTo(int quantity) {
            return quantity >= minQty && quantity <= maxQty;
        }

        BigDecimal calculateUnitPrice(BigDecimal basePrice) {
            switch (type) {
                case PERCENTAGE_DISCOUNT -> {
                    BigDecimal discountFactor = BigDecimal.ONE.subtract(value, MATH_CONTEXT);
                    return basePrice.multiply(discountFactor, MATH_CONTEXT)
                                    .setScale(4, RoundingMode.HALF_EVEN);
                }
                case FIXED_UNIT_PRICE -> {
                    return value;
                }
                default -> throw new IllegalStateException("Unexpected type: " + type);
            }
        }

        @Override
        public String toString() {
            return "Tier[min=" + minQty + ", max=" + maxQty + ", " + type + "=" + value + "]";
        }
    }

    private enum TierType {
        PERCENTAGE_DISCOUNT,
        FIXED_UNIT_PRICE
    }

    // ---------------------------------------------------------------------    
    // Supporting Types
    // ---------------------------------------------------------------------

    /**
     * Basic contract for pricing rules used by the engine.
     */
    public interface PricingRule {

        /**
         * Applies the rule to the supplied context.
         *
         * @param ctx context
         * @return calculated unit price
         * @throws PricingEngineException if evaluation fails
         */
        BigDecimal apply(PricingContext ctx) throws PricingEngineException;

        String getName();
    }

    /**
     * Lightweight evaluation context.  In the real system this would be provided
     * by the Pricing Engine and contain far more metadata (currency, contract
     * id, channel, etc.).  Only the essentials are replicated here so that the
     * class can compile in isolation.
     */
    public static final class PricingContext {

        private final String sku;
        private final int quantity;
        private final BigDecimal basePrice;
        private final Instant priceDate;
        private final Map<String, Object> attributes;

        public PricingContext(String sku,
                              int quantity,
                              BigDecimal basePrice,
                              Instant priceDate,
                              Map<String, Object> attributes) {
            if (quantity <= 0) {
                throw new IllegalArgumentException("quantity must be > 0");
            }
            this.sku = Objects.requireNonNull(sku, "sku");
            this.quantity = quantity;
            this.basePrice = Objects.requireNonNull(basePrice, "basePrice");
            this.priceDate = Optional.ofNullable(priceDate).orElseGet(Instant::now);
            this.attributes = attributes == null ? Map.of() : Map.copyOf(attributes);
        }

        public String getSku() {
            return sku;
        }

        public int getQuantity() {
            return quantity;
        }

        public BigDecimal getBasePrice() {
            return basePrice;
        }

        public Instant getPriceDate() {
            return priceDate;
        }

        public Map<String, Object> getAttributes() {
            return attributes;
        }
    }

    /**
     * Exception thrown when the rule cannot be evaluated successfully.
     */
    public static class PricingEngineException extends Exception {

        @Serial
        private static final long serialVersionUID = -9011506066838611871L;

        public PricingEngineException(String message) {
            super(message);
        }

        public PricingEngineException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}