```java
package com.commercesphere.enterprise.catalog.controller;

import com.commercesphere.enterprise.catalog.dto.ProductCreateRequest;
import com.commercesphere.enterprise.catalog.dto.ProductResponse;
import com.commercesphere.enterprise.catalog.dto.ProductUpdateRequest;
import com.commercesphere.enterprise.catalog.service.ProductService;
import com.commercesphere.enterprise.commons.exception.ResourceNotFoundException;
import com.commercesphere.enterprise.commons.web.PageResponse;
import com.commercesphere.enterprise.commons.web.SortRequest;
import io.micrometer.core.annotation.Timed;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.util.MultiValueMap;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.util.UriComponentsBuilder;

import javax.validation.Valid;
import javax.validation.constraints.Min;
import javax.validation.constraints.Positive;
import java.net.URI;
import java.time.Duration;
import java.util.Optional;

/**
 * REST Controller responsible for CRUD operations on {@code Product} resources.
 * <p>
 * All endpoints are secured by default – explicit role checks are declared where elevated
 * permissions are required (e.g. CREATE/UPDATE/DELETE require {@code ROLE_ADMIN}).
 * <p>
 * Responses leverage conditional caching (ETag &amp; max-age headers) so that high-traffic
 * catalog reads do not overwhelm the application servers.
 */
@Slf4j
@Validated
@RestController
@RequestMapping("/api/v1/products")
@RequiredArgsConstructor
public class ProductController {

    private static final CacheControl DEFAULT_CACHE =
            CacheControl.maxAge(Duration.ofMinutes(5)).cachePublic();

    private final ProductService productService;

    /**
     * Returns a paginated list of products with optional filtering on
     * {@code sku}, {@code name}, {@code categoryId} and {@code active} status.
     */
    @GetMapping
    @Timed(value = "product.list", histogram = true)
    public ResponseEntity<PageResponse<ProductResponse>> listProducts(
            @RequestParam(required = false) String sku,
            @RequestParam(required = false) String name,
            @RequestParam(required = false) Long categoryId,
            @RequestParam(required = false) Boolean active,
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "20") @Positive int size,
            SortRequest sort) {

        Pageable pageable = PageRequest.of(page, size, sort.toSort());

        Page<ProductResponse> products = productService.findProducts(
                Optional.ofNullable(sku).filter(StringUtils::isNotBlank),
                Optional.ofNullable(name).filter(StringUtils::isNotBlank),
                Optional.ofNullable(categoryId),
                Optional.ofNullable(active),
                pageable
        );

        PageResponse<ProductResponse> responseBody = PageResponse.of(products);

        return ResponseEntity.ok()
                .cacheControl(DEFAULT_CACHE)
                .body(responseBody);
    }

    /**
     * Fetches a single product. Response is conditional via ETag header.
     */
    @GetMapping("/{id}")
    @Timed(value = "product.get", histogram = true)
    public ResponseEntity<ProductResponse> getProduct(
            @PathVariable("id") @Positive Long id,
            @RequestHeader(name = "If-None-Match", required = false) String ifNoneMatch) {

        ProductResponse dto = productService.getProductById(id)
                .orElseThrow(() -> new ResourceNotFoundException("Product not found: " + id));

        String eTag = generateETag(dto);

        // Short-circuit if client's cached representation is still fresh
        if (eTag.equals(ifNoneMatch)) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED)
                    .eTag(eTag)
                    .build();
        }

        return ResponseEntity.ok()
                .eTag(eTag)
                .cacheControl(DEFAULT_CACHE)
                .body(dto);
    }

    /**
     * Creates a new product. Only administrators may call this endpoint.
     */
    @PostMapping
    @Timed(value = "product.create", histogram = true)
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<ProductResponse> createProduct(
            @Valid @RequestBody ProductCreateRequest request,
            UriComponentsBuilder uriBuilder) {

        ProductResponse created = productService.createProduct(request);

        URI location = uriBuilder
                .path("/api/v1/products/{id}")
                .buildAndExpand(created.getId())
                .toUri();

        log.info("Product created: id={}, sku={}", created.getId(), created.getSku());

        return ResponseEntity.created(location)
                .eTag(generateETag(created))
                .body(created);
    }

    /**
     * Updates an existing product in full. All nullable fields will overwrite the previous values.
     */
    @PutMapping("/{id}")
    @Timed(value = "product.update", histogram = true)
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<ProductResponse> updateProduct(
            @PathVariable("id") @Positive Long id,
            @Valid @RequestBody ProductUpdateRequest request) {

        ProductResponse updated = productService.updateProduct(id, request);
        log.info("Product updated: id={}", id);

        return ResponseEntity.ok()
                .eTag(generateETag(updated))
                .body(updated);
    }

    /**
     * Partially toggles the {@code active} status of a product.
     */
    @PatchMapping("/{id}/status")
    @Timed(value = "product.toggleStatus", histogram = true)
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Void> toggleProductStatus(
            @PathVariable("id") @Positive Long id,
            @RequestParam("active") boolean active) {

        productService.updateProductStatus(id, active);
        log.info("Product status changed: id={}, active={}", id, active);

        return ResponseEntity.noContent().build();
    }

    /**
     * Soft-deletes a product. The data remains in the database for audit purposes.
     */
    @DeleteMapping("/{id}")
    @Timed(value = "product.delete", histogram = true)
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Void> deleteProduct(@PathVariable("id") @Positive Long id) {
        productService.deleteProduct(id);
        log.warn("Product deleted: id={}", id);
        return ResponseEntity.noContent().build();
    }

    /**
     * Builds a weak ETag using the product's immutable properties. Controllers attempting to
     * optimise caching should ensure the same algorithm is used consistently.
     */
    private String generateETag(ProductResponse dto) {
        int hash = (dto.getId() + dto.getLastModified().toEpochMilli()).hashCode();
        return "W/\"" + Integer.toHexString(hash) + "\"";
    }
}
```