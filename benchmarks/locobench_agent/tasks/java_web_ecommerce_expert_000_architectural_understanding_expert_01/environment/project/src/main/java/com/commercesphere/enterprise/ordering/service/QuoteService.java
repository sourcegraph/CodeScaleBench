package com.commercesphere.enterprise.ordering.service;

import com.commercesphere.enterprise.common.event.DomainEventPublisher;
import com.commercesphere.enterprise.common.exception.BusinessRuleViolationException;
import com.commercesphere.enterprise.common.exception.ResourceNotFoundException;
import com.commercesphere.enterprise.common.i18n.MessageCodes;
import com.commercesphere.enterprise.common.logging.AuditLogger;
import com.commercesphere.enterprise.ordering.domain.model.Quote;
import com.commercesphere.enterprise.ordering.domain.model.QuoteItem;
import com.commercesphere.enterprise.ordering.domain.model.enums.QuoteStatus;
import com.commercesphere.enterprise.ordering.domain.repository.QuoteRepository;
import com.commercesphere.enterprise.ordering.dto.CreateQuoteRequest;
import com.commercesphere.enterprise.ordering.dto.UpdateQuoteRequest;
import com.commercesphere.enterprise.ordering.event.QuoteCancelledEvent;
import com.commercesphere.enterprise.ordering.event.QuoteCreatedEvent;
import com.commercesphere.enterprise.ordering.event.QuoteSubmittedEvent;
import com.commercesphere.enterprise.pricing.ContractPricingService;
import com.commercesphere.enterprise.inventory.InventoryService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * QuoteService acts as the orchestration layer for the Quote-to-Cash workflow.
 * <p>
 * Responsibilities:
 *  • Create draft quotes
 *  • Update quote lines, quantities and pricing
 *  • Perform pricing recalculations using the contract‐pricing engine
 *  • Guard quote status transitions (draft → submitted, etc.)
 *  • Emit domain events for downstream consumers (workflow, notification, etc.)
 *  • Persist optimistic‐locked Quote aggregates
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QuoteService {

    private final QuoteRepository quoteRepository;
    private final ContractPricingService contractPricingService;
    private final InventoryService inventoryService;
    private final AuditLogger auditLogger;
    private final DomainEventPublisher eventPublisher;
    private final Clock clock = Clock.systemDefaultZone(); // Clock is injectable for deterministic tests

    /**
     * Creates a draft quote with the supplied request data and persists the aggregate.
     */
    @Transactional
    public Quote createDraftQuote(CreateQuoteRequest request, UUID createdBy) {
        LocalDateTime now = LocalDateTime.now(clock);

        // Build aggregate
        Quote draft = Quote.builder()
                .id(UUID.randomUUID())
                .accountId(request.getAccountId())
                .status(QuoteStatus.DRAFT)
                .currency(request.getCurrency())
                .expirationDate(now.plusDays(request.getValidForDays()))
                .createdAt(now)
                .createdBy(createdBy)
                .items(toQuoteItems(request.getItems()))
                .build();

        // Enrich with pricing before persisting
        recalculatePricing(draft);

        Quote saved = quoteRepository.save(draft);

        auditLogger.info("Quote [{}] created by [{}]", saved.getId(), createdBy);
        eventPublisher.publish(new QuoteCreatedEvent(saved));

        return saved;
    }

    /**
     * Performs an idempotent update to an existing draft quote.
     */
    @Transactional(isolation = Isolation.REPEATABLE_READ)
    public Quote updateQuote(UUID quoteId, UpdateQuoteRequest request, UUID modifiedBy) {
        Quote quote = quoteRepository.findById(quoteId)
                .orElseThrow(() -> new ResourceNotFoundException(MessageCodes.QUOTE_NOT_FOUND, quoteId));

        ensureModifiable(quote);

        applyUpdates(quote, request);
        quote.setUpdatedAt(LocalDateTime.now(clock));
        quote.setUpdatedBy(modifiedBy);

        recalculatePricing(quote);

        Quote saved = quoteRepository.save(quote);
        auditLogger.info("Quote [{}] updated by [{}]", saved.getId(), modifiedBy);
        return saved;
    }

    /**
     * Attempts to submit a draft quote for approval. Inventory is reserved on success.
     */
    @Transactional
    public Quote submitQuote(UUID quoteId, UUID submittedBy) {
        Quote quote = quoteRepository.findById(quoteId)
                .orElseThrow(() -> new ResourceNotFoundException(MessageCodes.QUOTE_NOT_FOUND, quoteId));

        ensureModifiable(quote);

        // Reserve inventory atomically – roll back if not available
        inventoryService.reserveBulk(quote.toInventoryReservation());

        quote.setStatus(QuoteStatus.SUBMITTED);
        quote.setSubmittedAt(LocalDateTime.now(clock));
        quote.setSubmittedBy(submittedBy);

        Quote saved = quoteRepository.save(quote);

        auditLogger.info("Quote [{}] submitted by [{}]", quoteId, submittedBy);
        eventPublisher.publish(new QuoteSubmittedEvent(saved));

        return saved;
    }

    /**
     * Cancels an existing quote regardless of status as long as business rules permit.
     */
    @Transactional
    public void cancelQuote(UUID quoteId, UUID cancelledBy, String reason) {
        Quote quote = quoteRepository.findById(quoteId)
                .orElseThrow(() -> new ResourceNotFoundException(MessageCodes.QUOTE_NOT_FOUND, quoteId));

        if (quote.getStatus() == QuoteStatus.CANCELLED) {
            log.debug("Quote [{}] already cancelled, skipping.", quoteId);
            return; // Idempotent
        }

        if (quote.getStatus() == QuoteStatus.APPROVED || quote.getStatus() == QuoteStatus.INVOICED) {
            throw new BusinessRuleViolationException(
                    MessageCodes.QUOTE_CANCELLATION_FORBIDDEN,
                    "Cannot cancel quote in status " + quote.getStatus());
        }

        // Release any reserved inventory
        inventoryService.releaseBulk(quote.toInventoryReservation());

        quote.setStatus(QuoteStatus.CANCELLED);
        quote.setCancelledAt(LocalDateTime.now(clock));
        quote.setCancelledBy(cancelledBy);
        quote.setCancellationReason(reason);

        quoteRepository.save(quote);

        auditLogger.info("Quote [{}] cancelled by [{}]: {}", quoteId, cancelledBy, reason);
        eventPublisher.publish(new QuoteCancelledEvent(quote));
    }

    /**
     * Forces a pricing recalculation on the quote, re-applying contract‐specific
     * discounts. Typically invoked by scheduled tasks to keep quotes current.
     */
    @Transactional
    public Quote recalculateQuote(UUID quoteId) {
        Quote quote = quoteRepository.findById(quoteId)
                .orElseThrow(() -> new ResourceNotFoundException(MessageCodes.QUOTE_NOT_FOUND, quoteId));

        if (quote.getStatus() != QuoteStatus.DRAFT) {
            throw new BusinessRuleViolationException(
                    MessageCodes.QUOTE_RECALCULATION_FORBIDDEN,
                    "Can only recalculate quotes in DRAFT status");
        }

        recalculatePricing(quote);
        return quoteRepository.save(quote);
    }

    /* ---------------------------------------------------------------------- */
    /* Internal helpers                                                       */
    /* ---------------------------------------------------------------------- */

    private void recalculatePricing(Quote quote) {
        BigDecimal subtotal = BigDecimal.ZERO;

        for (QuoteItem item : quote.getItems()) {
            BigDecimal basePrice = contractPricingService
                    .getPriceForProduct(quote.getAccountId(), item.getProductId(), quote.getCurrency());

            BigDecimal discounted = contractPricingService
                    .applyDiscounts(quote.getAccountId(), item.getProductId(), basePrice, item.getQuantity());

            item.setUnitPrice(discounted);
            item.setTotal(discounted.multiply(BigDecimal.valueOf(item.getQuantity())));
            subtotal = subtotal.add(item.getTotal());
        }

        quote.setSubtotal(subtotal);
        quote.setTax(contractPricingService.calculateTax(subtotal, quote.getCurrency()));
        quote.setGrandTotal(subtotal.add(quote.getTax()));
    }

    private void ensureModifiable(Quote quote) {
        if (quote.getStatus() != QuoteStatus.DRAFT) {
            throw new BusinessRuleViolationException(
                    MessageCodes.QUOTE_MODIFICATION_FORBIDDEN,
                    "Quote is not modifiable in status " + quote.getStatus());
        }
    }

    private List<QuoteItem> toQuoteItems(List<CreateQuoteRequest.Item> items) {
        return items.stream()
                .map(i -> QuoteItem.builder()
                        .id(UUID.randomUUID())
                        .productId(i.getProductId())
                        .quantity(i.getQuantity())
                        .build())
                .toList();
    }

    private void applyUpdates(Quote quote, UpdateQuoteRequest request) {
        // Update basic fields
        if (request.getExpirationDate() != null) {
            quote.setExpirationDate(request.getExpirationDate());
        }

        // Update / sync items
        request.getItems().forEach(cmdItem -> {
            QuoteItem existing = quote.findItem(cmdItem.getItemId())
                    .orElseThrow(() -> new ResourceNotFoundException(
                            MessageCodes.QUOTE_ITEM_NOT_FOUND,
                            cmdItem.getItemId()));

            existing.setQuantity(cmdItem.getQuantity());
        });

        // Remove items not present in request (if flagged)
        if (request.isRemoveMissingItems()) {
            quote.getItems().removeIf(item ->
                    request.getItems().stream()
                            .noneMatch(cmd -> cmd.getItemId().equals(item.getId())));
        }
    }
}