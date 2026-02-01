package com.commercesphere.enterprise.pricing.service;

import com.commercesphere.enterprise.common.cache.CacheService;
import com.commercesphere.enterprise.pricing.exception.PricingException;
import com.commercesphere.enterprise.pricing.model.PriceBreakdown;
import com.commercesphere.enterprise.pricing.model.PriceRequest;
import com.commercesphere.enterprise.pricing.model.PriceResponse;
import com.commercesphere.enterprise.pricing.model.PricingRule;
import com.commercesphere.enterprise.pricing.repository.ContractRepository;
import com.commercesphere.enterprise.pricing.repository.PricingRuleRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * Service responsible for calculating real-time prices, taking into account:
 *  • Contract-driven negotiated rates
 *  • Tier/volume-based discounts
 *  • Dynamic promotional campaigns
 *  • Currency rounding & precision enforcement
 *
 * The implementation is intentionally stateless from an API perspective,
 * but caches heavy rule/object graphs internally for performance.
 */
public class PricingEngineService {

    private static final Logger LOG = LoggerFactory.getLogger(PricingEngineService.class);

    /**
     * Prices are cached by (accountId, sku, qty, currency) for the duration
     * set in {@link #DEFAULT_CACHE_TTL_SECONDS}. The cache can be invalidated
     * by rule refresh events or administrative commands.
     */
    private static final long DEFAULT_CACHE_TTL_SECONDS = 300;

    private final PricingRuleRepository pricingRuleRepository;
    private final ContractRepository     contractRepository;
    private final CacheService           cacheService;

    /**
     * Local in-memory cache for compiled rule chains.
     * Keyed by ruleId – ensures each distinct rule is compiled once.
     */
    private final Map<Long, CompiledRule> compiledRuleCache = new ConcurrentHashMap<>();

    /**
     * Lock to guard {@link #compiledRuleCache}. Compile actions are rare,
     * reads are frequent, so a RW lock provides maximum throughput.
     */
    private final ReentrantReadWriteLock compiledRuleLock = new ReentrantReadWriteLock();

    public PricingEngineService(final PricingRuleRepository pricingRuleRepository,
                                final ContractRepository contractRepository,
                                final CacheService cacheService) {
        this.pricingRuleRepository = Objects.requireNonNull(pricingRuleRepository);
        this.contractRepository    = Objects.requireNonNull(contractRepository);
        this.cacheService          = Objects.requireNonNull(cacheService);
    }

    /**
     * Calculates the final price for the given request. The method is idempotent,
     * thread-safe, and performs best-effort caching to ensure millisecond-level
     * latencies on high-traffic catalog pages.
     *
     * @param request price request
     * @return detailed price response
     * @throws PricingException when mandatory data is missing or rule evaluation fails
     */
    @Transactional(readOnly = true)
    public PriceResponse calculatePrice(final PriceRequest request) throws PricingException {
        validate(request);

        final String cacheKey = buildCacheKey(request);
        final PriceResponse cached = cacheService.get(cacheKey, PriceResponse.class);
        if (cached != null && !cached.isExpired()) {
            LOG.debug("Price hit from cache for key={}", cacheKey);
            return cached;
        }

        LOG.debug("Cache miss. Starting price calculation for account={}, sku={}",
                  request.getAccountId(), request.getSku());

        final CalculationContext ctx = new CalculationContext(request);

        // 1. Fetch contract-specific negotiated discount, if any.
        applyContractRates(ctx);

        // 2. Load and apply dynamic pricing rules (tier, promo, seasonal, etc.)
        applyPricingRules(ctx);

        // 3. Final rounding/formatting
        finalizePrice(ctx);

        // 4. Build the response
        final PriceResponse response = new PriceResponse(
                ctx.finalPrice,
                ctx.request.getCurrency(),
                ctx.breakdown,
                Instant.now().plusSeconds(DEFAULT_CACHE_TTL_SECONDS)
        );

        // 5. Cache & return
        cacheService.put(cacheKey, response, DEFAULT_CACHE_TTL_SECONDS);
        return response;
    }

    /**
     * Invalidates all pricing caches. Intended for administrative use cases
     * such as emergency rule overrides or nightly maintenance jobs.
     */
    public void invalidateAllCaches() {
        LOG.warn("Global pricing cache invalidation requested.");
        cacheService.evictByPrefix("price:");
        compiledRuleLock.writeLock().lock();
        try {
            compiledRuleCache.clear();
        } finally {
            compiledRuleLock.writeLock().unlock();
        }
    }

    /* ------------------------------------------------------------------------------------- */
    /*                                INTERNAL METHODS                                       */
    /* ------------------------------------------------------------------------------------- */

    private void validate(final PriceRequest request) throws PricingException {
        if (request == null) {
            throw new PricingException("PriceRequest must not be null");
        }
        if (request.getSku() == null || request.getSku().trim().isEmpty()) {
            throw new PricingException("SKU must be provided");
        }
        if (request.getCurrency() == null) {
            throw new PricingException("Currency must be provided");
        }
        if (request.getQuantity() <= 0) {
            throw new PricingException("Quantity must be greater than zero");
        }
    }

    private String buildCacheKey(final PriceRequest request) {
        return new StringBuilder("price:")
                .append(request.getAccountId()).append(':')
                .append(request.getSku()).append(':')
                .append(request.getQuantity()).append(':')
                .append(request.getCurrency().getCurrencyCode())
                .toString();
    }

    /**
     * Applies base contract discounts or surcharges to the context.
     */
    private void applyContractRates(final CalculationContext ctx) {
        contractRepository.findActiveContract(ctx.request.getAccountId(),
                                              ctx.request.getSku(),
                                              ctx.request.getBusinessDate())
                .ifPresent(contract -> {
                    BigDecimal contractPrice = contract.getFixedPrice();
                    if (contractPrice != null) {
                        ctx.applyPrice(contractPrice,
                                       PriceBreakdown.Type.CONTRACT_PRICE,
                                       "Contract fixed price");
                        return;
                    }

                    BigDecimal discount = contract.getDiscountPercent();
                    if (discount != null) {
                        BigDecimal discounted = ctx.basePrice
                                .multiply(BigDecimal.ONE.subtract(discount))
                                .setScale(4, RoundingMode.HALF_EVEN);
                        ctx.applyPrice(discounted,
                                       PriceBreakdown.Type.CONTRACT_DISCOUNT,
                                       "Contract discount " + discount);
                    }
                });
    }

    /**
     * Applies dynamic pricing rules ordered by priority (lowest number first).
     * Rule chains are compiled once and cached locally for performance.
     */
    private void applyPricingRules(final CalculationContext ctx) throws PricingException {
        List<PricingRule> rules = pricingRuleRepository
                .findActiveRules(ctx.request.getSku(), ctx.request.getBusinessDate());

        if (rules.isEmpty()) {
            return;
        }

        // sort rules deterministically
        rules.sort(Comparator.comparingInt(PricingRule::getPriority));

        for (PricingRule rule : rules) {
            CompiledRule compiled = compiledRuleCache.get(rule.getId());
            if (compiled == null) {
                compiled = compileRule(rule);
            }
            if (compiled.apply(ctx)) {
                LOG.debug("Rule {} applied to sku={}", rule.getCode(), ctx.request.getSku());
            }
        }
    }

    /**
     * Compile rule and add to cache. Uses double-checked locking to suit high
     * concurrency scenarios while preventing duplicate compilations.
     */
    private CompiledRule compileRule(final PricingRule rule) throws PricingException {
        CompiledRule compiled = compiledRuleCache.get(rule.getId());
        if (compiled != null) {
            return compiled;
        }

        compiledRuleLock.writeLock().lock();
        try {
            compiled = compiledRuleCache.get(rule.getId());
            if (compiled == null) {
                compiled = CompiledRule.from(rule);
                compiledRuleCache.put(rule.getId(), compiled);
                LOG.info("Rule {} compiled and cached", rule.getCode());
            }
            return compiled;
        } finally {
            compiledRuleLock.writeLock().unlock();
        }
    }

    private void finalizePrice(final CalculationContext ctx) {
        BigDecimal rounded = ctx.finalPrice
                .setScale(ctx.request.getCurrency().getDefaultFractionDigits(), RoundingMode.HALF_EVEN);
        ctx.finalPrice = rounded;
    }

    /* ------------------------------------------------------------------------------------- */
    /*                         INTERNAL DATA STRUCTURES                                      */
    /* ------------------------------------------------------------------------------------- */

    /**
     * Encapsulates all transient values and ensures they can be mutated in-place
     * without exposing state outside the service.
     */
    private static final class CalculationContext {
        private final PriceRequest      request;
        private final BigDecimal        basePrice;
        private BigDecimal              finalPrice;
        private Map<String, PriceBreakdown> breakdown = new ConcurrentHashMap<>();

        private CalculationContext(final PriceRequest request) {
            this.request     = request;
            this.basePrice   = request.getListPrice();
            this.finalPrice  = basePrice;
            this.breakdown.put("LIST_PRICE",
                    new PriceBreakdown(PriceBreakdown.Type.LIST_PRICE, basePrice, "List price"));
        }

        private void applyPrice(final BigDecimal newPrice,
                                final PriceBreakdown.Type type,
                                final String description) {
            Objects.requireNonNull(newPrice,  "price");
            Objects.requireNonNull(type,      "type");
            Objects.requireNonNull(description, "description");

            this.breakdown.put(type.name(),
                    new PriceBreakdown(type, newPrice, description));
            this.finalPrice = newPrice;
        }
    }

    /**
     * A lightweight, pre-validated representation of a {@link PricingRule},
     * compiled into functional code for fast execution.
     */
    private interface CompiledRule {

        /**
         * Evaluates the rule against the context. Returns true if the rule
         * applied and mutated the context, false otherwise.
         */
        boolean apply(CalculationContext ctx);

        /* --------------- Factory Methods --------------- */

        static CompiledRule from(final PricingRule rule) throws PricingException {
            switch (rule.getType()) {
                case VOLUME:
                    return volumeRule(rule);
                case PERCENT:
                    return percentRule(rule);
                case FIXED:
                    return fixedPriceRule(rule);
                default:
                    throw new PricingException("Unsupported rule type: " + rule.getType());
            }
        }

        private static CompiledRule volumeRule(final PricingRule rule) throws PricingException {
            Map<Integer, BigDecimal> tiers = rule.getTiers();
            if (tiers == null || tiers.isEmpty()) {
                throw new PricingException("Volume rule must contain at least one tier");
            }

            // transform to sorted list (ascending)
            List<Map.Entry<Integer, BigDecimal>> tierList = tiers.entrySet().stream()
                    .sorted(Map.Entry.comparingByKey())
                    .collect(Collectors.toList());

            return ctx -> {
                int qty = ctx.request.getQuantity();
                BigDecimal matchingPrice = null;
                for (Map.Entry<Integer, BigDecimal> entry : tierList) {
                    if (qty >= entry.getKey()) {
                        matchingPrice = entry.getValue();
                    }
                }
                if (matchingPrice != null && matchingPrice.compareTo(ctx.finalPrice) < 0) {
                    ctx.applyPrice(matchingPrice,
                                   PriceBreakdown.Type.VOLUME_DISCOUNT,
                                   "Volume tier matched for quantity " + qty);
                    return true;
                }
                return false;
            };
        }

        private static CompiledRule percentRule(final PricingRule rule) throws PricingException {
            BigDecimal percent = rule.getPercent();
            if (percent == null) {
                throw new PricingException("Percent rule missing percent value");
            }
            return ctx -> {
                BigDecimal newPrice = ctx.finalPrice
                        .multiply(BigDecimal.ONE.subtract(percent))
                        .setScale(4, RoundingMode.HALF_EVEN);
                if (newPrice.compareTo(ctx.finalPrice) < 0) {
                    ctx.applyPrice(newPrice,
                                   PriceBreakdown.Type.PROMO_DISCOUNT,
                                   "Percent discount " + percent);
                    return true;
                }
                return false;
            };
        }

        private static CompiledRule fixedPriceRule(final PricingRule rule) throws PricingException {
            BigDecimal fixed = rule.getFixedPrice();
            if (fixed == null) {
                throw new PricingException("Fixed price rule missing fixed price");
            }
            return ctx -> {
                if (fixed.compareTo(ctx.finalPrice) < 0) {
                    ctx.applyPrice(fixed,
                                   PriceBreakdown.Type.PROMO_FIXED,
                                   "Fixed promo price");
                    return true;
                }
                return false;
            };
        }
    }
}