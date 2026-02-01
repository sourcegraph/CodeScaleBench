```java
package com.sprintcart.domain.ports.out.persistence;

import java.time.Duration;
import java.util.Collection;
import java.util.EnumSet;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

import com.sprintcart.domain.exceptions.ConcurrencyException;
import com.sprintcart.domain.exceptions.ReferentialIntegrityException;
import com.sprintcart.domain.exceptions.ValidationException;
import com.sprintcart.domain.model.category.CategoryId;
import com.sprintcart.domain.model.common.MoneyRange;
import com.sprintcart.domain.model.product.Product;
import com.sprintcart.domain.model.product.ProductId;
import com.sprintcart.domain.model.product.ProductStatus;
import com.sprintcart.domain.model.product.Sku;
import com.sprintcart.domain.model.product.StockLevel;
import com.sprintcart.domain.shared.ddd.Page;
import com.sprintcart.domain.shared.ddd.PageRequest;

/**
 * Outbound port that defines persistence operations for {@link Product}s.
 * <p>
 * The interface purposefully exposes a rich set of domain-centric methods rather
 * than CRUD-only signatures in order to:
 * <ul>
 *     <li>Capture transactional invariants (e.g., optimistic locking, stock
 *     adjustments) close to the domain layer</li>
 *     <li>Hide storage-specific concerns—SQL / NoSQL / CQRS / EventStore—from
 *     use cases</li>
 *     <li>Enable adapters (JPA, Mongo, Dynamo, …) to optimise queries without
 *     leaking details upward</li>
 * </ul>
 * <p>
 * Implementations <strong>must</strong> guarantee thread-safety and respect the
 * transactional semantics declared in the method contracts.
 */
public interface ProductRepositoryPort {

    /**
     * Fetches a product by id using the specified {@link FetchPolicy}.
     *
     * @param id          technical identifier of the product
     * @param fetchPolicy graph resolution policy; never {@code null}
     * @return optional product
     */
    Optional<Product> findById(ProductId id, FetchPolicy fetchPolicy);

    /**
     * Persists a product aggregate. The implementation is expected to:
     * <ul>
     *     <li>Perform optimistic locking by comparing {@code product.getVersion()}
     *     against the stored version, throwing {@link ConcurrencyException} on
     *     mismatch</li>
     *     <li>Validate business constraints at the infrastructure level
     *     (non-nulls, unique indexes, etc.) and wrap any persistent violations
     *     into {@link ValidationException}</li>
     * </ul>
     *
     * @param product the aggregate root
     * @return the identifier (can differ from {@code product.getId()} for
     *         brand-new entities)
     * @throws ValidationException   if domain or persistence validation fails
     * @throws ConcurrencyException  if optimistic locking fails
     */
    ProductId save(Product product) throws ValidationException, ConcurrencyException;

    /**
     * Deletes the product with the given identifier.
     *
     * @param id target id
     * @throws ReferentialIntegrityException if the product is referenced by
     *                                       downstream aggregates (e.g.,
     *                                       orders, promotions)
     */
    void delete(ProductId id) throws ReferentialIntegrityException;

    /**
     * Returns {@code true} if any product exists with the given SKU.
     *
     * @param sku product SKU (case-insensitive, trimmed)
     */
    boolean existsBySku(Sku sku);

    /**
     * Retrieves the stock level for the requested products in bulk to prevent
     * <em>N+1</em> queries in high-throughput code paths (e.g., cart
     * validation).
     *
     * @param ids collection of product ids; must not be {@code null}
     * @return map of id → stock level. Missing ids are silently ignored.
     */
    Map<ProductId, StockLevel> fetchStockLevels(Collection<ProductId> ids);

    /**
     * Searches products using the given {@link ProductSearchCriteria} with
     * pagination support.
     *
     * @param criteria   immutable search specification
     * @param pageRequest page & size (zero-based)
     * @return a page of products
     */
    Page<Product> search(ProductSearchCriteria criteria, PageRequest pageRequest);

    /**
     * Attempts to acquire an explicit lock on a product so that multiple
     * workflows (e.g., automation rules vs. user edits) do not concurrently
     * modify critical fields such as price or inventory.
     *
     * @param id       product to lock
     * @param maxWait  maximum time to wait; zero for <em>fail fast</em>
     * @return lock handle which <em>must</em> be closed/released by the caller
     * @throws LockUnavailableException if unable to acquire within {@code maxWait}
     */
    LockHandle lock(ProductId id, Duration maxWait) throws LockUnavailableException;

    // ------------------------------------------------------------------------
    // Helper types
    // ------------------------------------------------------------------------

    /**
     * Fine-grained fetch graph policy to prevent over-fetching in high-volume
     * dashboards while still allowing deep, single-entity reads (e.g., PDP
     * editor).
     */
    enum FetchPolicy {
        /**
         * Only the mandatory attributes required for listing: id, name, default SKU, price.
         */
        SUMMARY,

        /**
         * Includes summary plus full attribute set, images, and tags.
         */
        WITH_ATTRIBUTES,

        /**
         * Includes {@link #WITH_ATTRIBUTES} plus variant matrix and stock
         * levels.
         */
        WITH_VARIANTS,

        /**
         * Full aggregate: variants, relations (cross-sells, bundles),
         * translations, automation bindings, etc.
         */
        FULL
    }

    /**
     * Immutable search criteria for the product catalog.
     * <p>
     * Implemented as a lightweight value object to minimise overhead in the
     * domain layer. A fluent builder is provided for convenience.
     */
    final class ProductSearchCriteria {

        private final String keyword;
        private final Set<CategoryId> categoryIds;
        private final MoneyRange priceRange;
        private final EnumSet<ProductStatus> statuses;
        private final boolean matchAllKeywords;

        private ProductSearchCriteria(Builder builder) {
            this.keyword = builder.keyword;
            this.categoryIds = builder.categoryIds;
            this.priceRange = builder.priceRange;
            this.statuses = builder.statuses.clone();
            this.matchAllKeywords = builder.matchAllKeywords;
        }

        public Optional<String> keyword() {
            return Optional.ofNullable(keyword);
        }

        public Set<CategoryId> categoryIds() {
            return categoryIds;
        }

        public Optional<MoneyRange> priceRange() {
            return Optional.ofNullable(priceRange);
        }

        public EnumSet<ProductStatus> statuses() {
            return statuses;
        }

        public boolean matchAllKeywords() {
            return matchAllKeywords;
        }

        // --------------------------------------------------------------------
        // Builder
        // --------------------------------------------------------------------

        public static Builder builder() {
            return new Builder();
        }

        public static final class Builder {
            private String keyword;
            private Set<CategoryId> categoryIds = Set.of();
            private MoneyRange priceRange;
            private EnumSet<ProductStatus> statuses = EnumSet.noneOf(ProductStatus.class);
            private boolean matchAllKeywords = false;

            private Builder() {
            }

            public Builder keyword(String keyword) {
                this.keyword = (keyword != null && keyword.isBlank()) ? null : keyword;
                return this;
            }

            public Builder categoryIds(Collection<CategoryId> categories) {
                this.categoryIds = categories == null ? Set.of() : Set.copyOf(categories);
                return this;
            }

            public Builder priceRange(MoneyRange priceRange) {
                this.priceRange = priceRange;
                return this;
            }

            public Builder statuses(Collection<ProductStatus> statuses) {
                this.statuses = statuses == null
                        ? EnumSet.noneOf(ProductStatus.class)
                        : EnumSet.copyOf(statuses);
                return this;
            }

            public Builder matchAllKeywords(boolean matchAll) {
                this.matchAllKeywords = matchAll;
                return this;
            }

            public ProductSearchCriteria build() {
                return new ProductSearchCriteria(this);
            }
        }
    }

    /**
     * Technical handle representing a pessimistic lock on a single product
     * record. Implementations may delegate to DB locks, distributed locks
     * (e.g., Redis, Zookeeper), or in-memory synchronisation as long as
     * cross-process exclusivity is guaranteed.
     */
    interface LockHandle extends AutoCloseable {

        /**
         * Unique identifier for observability tooling.
         */
        UUID lockId();

        /**
         * Releases the lock. Implementations <em>must</em> be idempotent.
         */
        @Override
        void close();
    }

    /**
     * Exception thrown when a lock cannot be obtained in the allotted time.
     */
    class LockUnavailableException extends Exception {
        public LockUnavailableException(String message) {
            super(message);
        }

        public LockUnavailableException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
```