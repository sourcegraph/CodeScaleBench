package com.sprintcart.domain.exceptions;

import java.io.Serial;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Domain-level exception indicating that a product could not be located in the catalog
 * aggregate root. Infrastructure and presentation layers are responsible for translating
 * this exception into their respective concerns (e.g. HTTP <code>404 Not Found</code>).
 *
 * <p>The exception purposefully carries minimal context so that it can travel across
 * layers without leaking infrastructure details.  Consumers can optionally inspect
 * the {@code productId} or {@code sku} fields for additional telemetry or logging.</p>
 *
 * <p>Usage example:
 * <pre>{@code
 * Product product = catalogRepository.findById(productId)
 *     .orElseThrow(() -> ProductNotFoundException.forId(productId));
 * }</pre></p>
 *
 * NOTE: The domain layer must never depend on framework-specific classes (e.g.
 * Spring's {@code ResponseStatusException}). Keep this class free from such imports.
 *
 * @author  SprintCart Pro
 */
public final class ProductNotFoundException extends RuntimeException {

    @Serial
    private static final long serialVersionUID = 2649558653370159495L;

    /**
     * Unique identifier of the product, if known.
     */
    private final UUID productId;

    /**
     * SKU (stock-keeping unit) of the product, if known.
     */
    private final String sku;

    /**
     * Technical constructor. Prefer the static factory methods
     * {@link #forId(UUID)} or {@link #forSku(String)}.
     */
    private ProductNotFoundException(String message, UUID productId, String sku) {
        super(message);
        this.productId = productId;
        this.sku = sku;
    }

    /* -----------------------------------------------------------------------
     *  Static factories
     * -------------------------------------------------------------------- */

    /**
     * Creates an exception for a missing product identified by {@code productId}.
     *
     * @param productId UUID of the missing product
     * @return immutable {@code ProductNotFoundException}
     */
    public static ProductNotFoundException forId(UUID productId) {
        Objects.requireNonNull(productId, "productId must not be null");
        String message = "Product with ID %s was not found in the catalog".formatted(productId);
        return new ProductNotFoundException(message, productId, null);
    }

    /**
     * Creates an exception for a missing product identified by {@code sku}.
     *
     * @param sku SKU code of the missing product
     * @return immutable {@code ProductNotFoundException}
     */
    public static ProductNotFoundException forSku(String sku) {
        if (sku == null || sku.isBlank()) {
            throw new IllegalArgumentException("sku must not be blank");
        }
        String message = "Product with SKU '%s' was not found in the catalog".formatted(sku);
        return new ProductNotFoundException(message, null, sku);
    }

    /* -----------------------------------------------------------------------
     *  Public accessors
     * -------------------------------------------------------------------- */

    /**
     * Returns the product UUID, if available.
     */
    public Optional<UUID> getProductId() {
        return Optional.ofNullable(productId);
    }

    /**
     * Returns the SKU, if available.
     */
    public Optional<String> getSku() {
        return Optional.ofNullable(sku);
    }

    /* -----------------------------------------------------------------------
     *  Equality & hashCode
     * -------------------------------------------------------------------- */

    @Override
    public int hashCode() {
        return Objects.hash(productId, sku);
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof ProductNotFoundException other)) return false;
        return Objects.equals(productId, other.productId) &&
               Objects.equals(sku, other.sku);
    }
}