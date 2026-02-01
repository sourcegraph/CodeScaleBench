```java
package com.commercesphere.enterprise.catalog.service;

import com.commercesphere.enterprise.catalog.domain.Product;
import com.commercesphere.enterprise.catalog.domain.command.CreateProductCommand;
import com.commercesphere.enterprise.catalog.domain.command.UpdateProductCommand;
import com.commercesphere.enterprise.catalog.domain.search.ProductSearchCriteria;
import com.commercesphere.enterprise.catalog.dto.ProductDTO;
import com.commercesphere.enterprise.catalog.event.ProductCreatedEvent;
import com.commercesphere.enterprise.catalog.event.ProductDeletedEvent;
import com.commercesphere.enterprise.catalog.exception.DuplicateSkuException;
import com.commercesphere.enterprise.catalog.exception.InventoryUpdateException;
import com.commercesphere.enterprise.catalog.exception.ProductNotFoundException;
import com.commercesphere.enterprise.catalog.mapper.ProductMapper;
import com.commercesphere.enterprise.catalog.repository.CategoryRepository;
import com.commercesphere.enterprise.catalog.repository.ProductRepository;
import com.commercesphere.enterprise.common.audit.AuditAction;
import com.commercesphere.enterprise.common.audit.AuditLogger;
import com.commercesphere.enterprise.inventory.InventoryService;
import com.commercesphere.enterprise.pricing.PriceEngine;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.CachePut;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;

/**
 * Core domain service responsible for product life-cycle management,
 * inventory orchestration and price enrichment.
 *
 * NOTE: All methods are annotated with {@code @Transactional} at class level.
 * Read operations that require no write locking use {@code readOnly = true}.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional
public class ProductService {

    private static final String PRODUCT_CACHE = "catalog.product";

    private final ProductRepository productRepository;
    private final CategoryRepository categoryRepository;
    private final ProductMapper productMapper;
    private final InventoryService inventoryService;
    private final PriceEngine priceEngine;
    private final AuditLogger auditLogger;
    private final ApplicationEventPublisher eventPublisher;

    /* ------------------------------------------------------------------
     * Public API
     * ------------------------------------------------------------------ */

    /**
     * Fetches a single product and enriches it with dynamic price and inventory information.
     */
    @Cacheable(value = PRODUCT_CACHE, key = "#productId")
    @Transactional(readOnly = true)
    public ProductDTO getProduct(UUID productId, Locale locale) {
        Product product = findProductOrThrow(productId);
        ProductDTO dto = productMapper.toDto(product, locale);

        // Enrich DTO with volatile data
        dto.setAvailableQuantity(inventoryService.getAvailableQuantity(productId));
        dto.setCurrentPrice(resolveCurrentPrice(productId, dto.getCustomerSegment()));

        return dto;
    }

    /**
     * Searches products by criteria and performs price enrichment for each hit.
     */
    @Transactional(readOnly = true)
    public Page<ProductDTO> searchProducts(ProductSearchCriteria criteria, Pageable pageable, Locale locale) {
        Page<Product> page = productRepository.search(criteria, pageable);
        return page.map(p -> {
            ProductDTO dto = productMapper.toDto(p, locale);
            dto.setAvailableQuantity(inventoryService.getAvailableQuantity(p.getId()));
            dto.setCurrentPrice(resolveCurrentPrice(p.getId(), dto.getCustomerSegment()));
            return dto;
        });
    }

    /**
     * Creates a brand-new product record along with its initial inventory snapshot.
     */
    @CachePut(value = PRODUCT_CACHE, key = "#result.id")
    public ProductDTO createProduct(CreateProductCommand cmd, Locale locale) {
        validateSkuUnique(cmd.getSku());

        Product product = productMapper.toEntity(cmd, locale);
        product.setId(UUID.randomUUID());
        product.setCreatedAt(OffsetDateTime.now());

        Product saved;
        try {
            saved = productRepository.save(product);
        } catch (DataIntegrityViolationException ex) {
            // Handles rare race conditions when two transactions insert the same SKU concurrently.
            throw new DuplicateSkuException(cmd.getSku(), ex);
        }

        // Initialize on-hand quantity
        inventoryService.seedInventory(saved.getId(), cmd.getInitialQuantity());

        // Audit & Events
        auditLogger.log(AuditAction.CREATE_PRODUCT, saved.getId(), cmd.getCreatedBy());
        eventPublisher.publishEvent(new ProductCreatedEvent(saved.getId(), saved.getSku()));

        log.info("Created product [{}] with SKU='{}'", saved.getId(), saved.getSku());
        return productMapper.toDto(saved, locale);
    }

    /**
     * Updates mutable fields of a product using optimistic locking.
     */
    @CachePut(value = PRODUCT_CACHE, key = "#productId")
    public ProductDTO updateProduct(UUID productId, UpdateProductCommand cmd, Locale locale) {
        Product product = findProductOrThrow(productId);

        // Detect SKU changes
        if (!StringUtils.equals(product.getSku(), cmd.getSku())) {
            validateSkuUnique(cmd.getSku());
            product.setSku(cmd.getSku());
        }

        // Map mutable fields
        productMapper.updateEntity(cmd, product);

        // Persist & audit
        Product saved = productRepository.save(product);
        auditLogger.log(AuditAction.UPDATE_PRODUCT, saved.getId(), cmd.getModifiedBy());

        log.debug("Updated product [{}]", productId);
        return productMapper.toDto(saved, locale);
    }

    /**
     * Soft-deletes a product and evicts it from all caches.
     */
    @CacheEvict(value = PRODUCT_CACHE, key = "#productId")
    public void deleteProduct(UUID productId, String deletedBy) {
        Product product = findProductOrThrow(productId);

        product.markDeleted();
        productRepository.save(product);

        auditLogger.log(AuditAction.DELETE_PRODUCT, productId, deletedBy);
        eventPublisher.publishEvent(new ProductDeletedEvent(productId));

        log.warn("Soft-deleted product [{}] by '{}'", productId, deletedBy);
    }

    /**
     * Adjusts inventory (positive or negative) for the supplied product.
     * Delegates to the InventoryService but keeps audit trail inside the same transaction.
     */
    public int adjustInventory(UUID productId, int delta, String requestedBy) {
        try {
            int resultingQty = inventoryService.adjustQuantity(productId, delta);

            auditLogger.log(
                    AuditAction.ADJUST_INVENTORY,
                    productId,
                    requestedBy,
                    "Delta=" + delta + ", Resulting=" + resultingQty
            );

            // Cache eviction so next read hits updated inventory
            evictProductCache(productId);

            return resultingQty;
        } catch (IllegalArgumentException ex) {
            throw new InventoryUpdateException("Failed to adjust inventory for product " + productId, ex);
        }
    }

    /* ------------------------------------------------------------------
     * Internal helpers
     * ------------------------------------------------------------------ */

    private void validateSkuUnique(String sku) {
        if (productRepository.existsBySkuIgnoreCase(sku)) {
            throw new DuplicateSkuException(sku);
        }
    }

    private Product findProductOrThrow(UUID productId) {
        Optional<Product> productOpt = productRepository.findByIdAndDeletedFalse(productId);
        return productOpt.orElseThrow(() -> new ProductNotFoundException(productId));
    }

    private BigDecimal resolveCurrentPrice(UUID productId, String customerSegment) {
        try {
            return priceEngine.resolvePrice(productId, customerSegment);
        } catch (Exception ex) {
            log.error("Price resolution failed for product {} – falling back to base price", productId, ex);
            return priceEngine.getBasePrice(productId);
        }
    }

    /**
     * Explicitly evicts a product from cache. Useful when side-effects occur outside of the
     * usual @Cache* annotations (e.g., inventory adjustments).
     */
    @CacheEvict(value = PRODUCT_CACHE, key = "#productId")
    protected void evictProductCache(UUID productId) {
        // Method body intentionally left empty. The annotation performs the eviction.
    }
}
```