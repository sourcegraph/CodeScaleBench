package com.sprintcart.application.service;

import com.sprintcart.domain.catalog.command.BulkUpdateCommand;
import com.sprintcart.domain.catalog.command.CreateProductCommand;
import com.sprintcart.domain.catalog.command.UpdateProductCommand;
import com.sprintcart.domain.catalog.event.LowStockEvent;
import com.sprintcart.domain.catalog.event.ProductCreatedEvent;
import com.sprintcart.domain.catalog.event.ProductUpdatedEvent;
import com.sprintcart.domain.catalog.model.Product;
import com.sprintcart.domain.catalog.port.CatalogPort;
import com.sprintcart.domain.marketing.port.AdvertisementPort;
import com.sprintcart.infrastructure.messaging.EventPublisher;
import com.sprintcart.shared.dto.BulkUpdateResultDto;
import com.sprintcart.shared.dto.ProductDto;
import com.sprintcart.shared.search.ProductSearchCriteria;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.ConstraintViolationException;
import jakarta.validation.Validator;
import java.time.Clock;
import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.hibernate.StaleObjectStateException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Application service that orchestrates catalog-related use-cases by
 * delegating to the domain layer (via {@link CatalogPort}) and issuing
 * side-effects such as event publication and ad-campaign pausing.
 *
 * <p>This class sits in the “application” ring of the hexagon and is intentionally
 * kept free of any transport- or persistence-specific code so that it can be reused
 * by REST, GraphQL or batch adapters.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CatalogService {

    private final CatalogPort catalogPort;
    private final AdvertisementPort advertisementPort;
    private final EventPublisher eventPublisher;
    private final Validator validator;
    private final Clock clock;

    /**
     * Fetch a single product by its identifier.
     */
    @Transactional(readOnly = true)
    public ProductDto getProductById(final UUID productId) {
        Product product = catalogPort.findById(productId)
                                     .orElseThrow(() -> new IllegalArgumentException("Product not found: " + productId));
        return ProductDto.from(product);
    }

    /**
     * Search for products based on flexible criteria.
     */
    @Transactional(readOnly = true)
    public Page<ProductDto> searchProducts(final ProductSearchCriteria criteria, final Pageable pageRequest) {
        return catalogPort.search(criteria, pageRequest)
                          .map(ProductDto::from);
    }

    /**
     * Create a new product and broadcast a {@link ProductCreatedEvent}.
     */
    @Transactional
    public ProductDto createProduct(final CreateProductCommand command) {
        validate(command);
        Product created = catalogPort.create(command);
        eventPublisher.publishAsync(new ProductCreatedEvent(created.getId(), Instant.now(clock)));
        return ProductDto.from(created);
    }

    /**
     * Update a product. Handles optimistic locking conflicts gracefully.
     */
    @Transactional
    public ProductDto updateProduct(final UUID productId, final UpdateProductCommand command) {
        validate(command);

        try {
            Product updated = catalogPort.update(productId, command);
            eventPublisher.publishAsync(new ProductUpdatedEvent(updated.getId(), Instant.now(clock)));
            maybePauseAds(updated);
            return ProductDto.from(updated);
        } catch (StaleObjectStateException optimisticLockingFailure) {
            log.warn("Optimistic locking conflict while updating product {}. Retrying once.", productId);
            // Retry once; in practice, use a retry template/backoff.
            Product updated = catalogPort.update(productId, command);
            eventPublisher.publishAsync(new ProductUpdatedEvent(updated.getId(), Instant.now(clock)));
            maybePauseAds(updated);
            return ProductDto.from(updated);
        }
    }

    /**
     * Perform high-throughput updates (price changes, stock adjustments, etc.) in a single transaction.
     */
    @Transactional
    public BulkUpdateResultDto bulkUpdateProducts(final BulkUpdateCommand command) {
        validate(command);

        BulkUpdateResultDto result = catalogPort.bulkUpdate(command);

        // Notify other subsystems asynchronously.
        result.updatedProducts().forEach(p -> {
            eventPublisher.publishAsync(new ProductUpdatedEvent(p.id(), Instant.now(clock)));
            maybePauseAds(p.toDomainModel());
        });

        return result;
    }

    /* --------------------------------------------------------------------- */
    /* Internal helpers                                                      */
    /* --------------------------------------------------------------------- */

    private void validate(final Object object) {
        Set<ConstraintViolation<Object>> violations = validator.validate(object);
        if (!violations.isEmpty()) {
            String message = violations.stream()
                                       .map(ConstraintViolation::getMessage)
                                       .collect(Collectors.joining("; "));
            throw new ConstraintViolationException(message, violations);
        }
    }

    /**
     * Pause ad campaigns and emit low-stock events when stock drops below an automation threshold.
     */
    private void maybePauseAds(final Product product) {
        product.getInventory().ifPresent(inventory -> {
            int threshold = inventory.reorderThreshold();
            int onHand    = inventory.unitsOnHand();
            if (onHand < threshold) {
                log.info("Product {} stock ({}) under threshold ({}). Pausing ads.", product.getId(), onHand, threshold);
                advertisementPort.pauseCampaignsForProduct(product.getId());
                eventPublisher.publishAsync(new LowStockEvent(product.getId(), onHand, threshold, Instant.now(clock)));
            }
        });
    }
}