package com.commercesphere.enterprise.pricing.service;

import com.commercesphere.enterprise.pricing.model.Cart;
import com.commercesphere.enterprise.pricing.model.CartItem;
import com.commercesphere.enterprise.pricing.model.Money;
import com.commercesphere.enterprise.pricing.model.Promotion;
import com.commercesphere.enterprise.pricing.repository.PromotionRepository;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Currency;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

/**
 * Central service responsible for evaluating and applying promotions
 * to a cart or order. Business rules such as usage limits, date ranges
 * and tiered discount ladders are enforced here in one canonical spot
 * to prevent duplication across MVC controllers, REST resources or
 * batch import jobs.
 *
 * NOTE:  PromotionService itself does <strong>not</strong> modify persistent
 * state beyond recording usage counts. Any price adjustments are carried
 * out in–memory on the supplied {@link Cart} instance, leaving transaction
 * boundaries to the caller.
 */
@Service
@Validated
public class PromotionService {

    private static final Logger LOG = LoggerFactory.getLogger(PromotionService.class);

    private final PromotionRepository promotionRepository;
    private final ApplicationEventPublisher eventPublisher;
    private final Cache<String, Promotion> promotionCache;

    public PromotionService(PromotionRepository promotionRepository,
                            ApplicationEventPublisher eventPublisher) {
        this.promotionRepository = promotionRepository;
        this.eventPublisher = eventPublisher;
        // Frequently accessed promotions are cached for 30 minutes to avoid
        // round-trips to the database during high-traffic campaigns.
        this.promotionCache = Caffeine.newBuilder()
                                      .expireAfterWrite(30, TimeUnit.MINUTES)
                                      .maximumSize(5_000)
                                      .build();
    }

    /**
     * Applies the best matching promotion to the supplied cart. If a
     * promo code is specified it takes precedence, otherwise the method
     * scans for auto-apply promotions that match the cart context.
     *
     * @param cart      Mutable cart object belonging to a session/order.
     * @param promoCode Optional promotion code entered by the user.
     * @return Immutable result carrying the adjustment numbers.
     * @throws PromotionException if the promo code is invalid or violates limits.
     */
    @Transactional
    public PromotionApplicationResult applyPromotions(@NonNull Cart cart,
                                                      String promoCode) {

        Objects.requireNonNull(cart, "cart required");

        Currency cartCurrency = cart.getCurrency();
        Promotion promotion = selectApplicablePromotion(cart, promoCode)
                .orElseThrow(() -> new PromotionException("No applicable promotion found"));

        validateUsageLimits(promotion, cart.getAccountId());
        Money discount = calculateDiscount(cart, promotion, cartCurrency);

        cart.setPromotionAdjustment(discount.negate()); // Discount is negative in cart
        incrementUsageCounter(promotion, cart.getAccountId());

        eventPublisher.publishEvent(new PromotionAppliedEvent(cart.getId(), promotion.getId()));

        return new PromotionApplicationResult(promotion, discount);
    }

    /**
     * Returns a promotion by its human-readable code if it is currently active.
     */
    public Optional<Promotion> findActivePromotionByCode(String code) {
        if (code == null || code.isBlank()) {
            return Optional.empty();
        }

        Promotion cached = promotionCache.getIfPresent(code.toUpperCase());
        if (cached != null && cached.isActiveAt(Instant.now())) {
            return Optional.of(cached);
        }

        return promotionRepository.findByCode(code.toUpperCase())
                .filter(p -> p.isActiveAt(Instant.now()))
                .map(p -> {
                    promotionCache.put(code.toUpperCase(), p);
                    return p;
                });
    }

    /* --------------------------------------------------------------------- */
    /* Private helper methods                                                */
    /* --------------------------------------------------------------------- */

    private Optional<Promotion> selectApplicablePromotion(Cart cart, String promoCode) {
        // 1) Explicit promo code has priority
        if (promoCode != null && !promoCode.isBlank()) {
            return findActivePromotionByCode(promoCode);
        }

        // 2) Fallback to auto-apply promotions
        List<Promotion> candidates = promotionRepository.findAllAutoApply(Instant.now());
        return candidates.stream()
                .filter(p -> p.matchesCart(cart))
                .findFirst();
    }

    private void validateUsageLimits(Promotion promotion, String accountId) {
        if (!promotion.hasRemainingGlobalUses()) {
            throw new PromotionException("Promotion usage limit reached");
        }
        if (!promotion.hasRemainingUsesForAccount(accountId)) {
            throw new PromotionException("You have already used this promotion");
        }
    }

    private Money calculateDiscount(Cart cart, Promotion promotion, Currency currency) {
        BigDecimal cartTotal = cart.getSubtotal().getAmount();
        if (promotion.getPercentage() != null) {
            BigDecimal percentage = promotion.getPercentage()
                                             .divide(BigDecimal.valueOf(100));
            BigDecimal discountAmount = cartTotal.multiply(percentage);
            return new Money(discountAmount, currency);
        } else if (promotion.getFixedAmount() != null) {
            BigDecimal amount = promotion.getFixedAmount().min(cartTotal);
            return new Money(amount, currency);
        } else {
            LOG.warn("Promotion {} has no discount value; skipping", promotion.getId());
            return Money.zero(currency);
        }
    }

    private void incrementUsageCounter(Promotion promotion, String accountId) {
        try {
            promotionRepository.incrementUsage(promotion.getId(), accountId);
        } catch (Exception ex) {
            // Fail gracefully: the discount is still applied in-memory but the DB
            // update failed. Roll back transaction so cart and usage counters
            // remain consistent.
            LOG.error("Failed to increment promotion usage counter", ex);
            throw new PromotionException("Unable to apply promotion at this time. Please retry.");
        }
    }

    /* --------------------------------------------------------------------- */
    /* Inner classes                                                          */
    /* --------------------------------------------------------------------- */

    /**
     * Immutable DTO used as a return type so callers can easily
     * serialize it to REST responses or audit logs.
     */
    public static final class PromotionApplicationResult {
        private final Promotion promotion;
        private final Money discount;

        public PromotionApplicationResult(Promotion promotion, Money discount) {
            this.promotion = promotion;
            this.discount = discount;
        }

        public Promotion getPromotion() {
            return promotion;
        }

        public Money getDiscount() {
            return discount;
        }
    }

    /**
     * Domain-specific runtime exception so callers can differentiate
     * between pricing errors and generic technical failures.
     */
    public static class PromotionException extends RuntimeException {
        public PromotionException(String message) {
            super(message);
        }

        public PromotionException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * Spring event emitted after a promotion is successfully applied.
     * Opens possibilities for other bounded contexts (analytics, emails)
     * to react without tight coupling.
     */
    public static class PromotionAppliedEvent {
        private final String cartId;
        private final String promotionId;

        public PromotionAppliedEvent(String cartId, String promotionId) {
            this.cartId = cartId;
            this.promotionId = promotionId;
        }

        public String getCartId() {
            return cartId;
        }

        public String getPromotionId() {
            return promotionId;
        }
    }
}