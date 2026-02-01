```java
package com.commercesphere.enterprise.catalog.repository;

import com.commercesphere.enterprise.catalog.domain.Product;
import com.commercesphere.enterprise.catalog.domain.ProductStatus;
import org.springframework.dao.DataAccessException;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.QueryHints;
import org.springframework.data.repository.query.Param;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import javax.persistence.EntityGraph;
import javax.persistence.EntityManager;
import javax.persistence.LockModeType;
import javax.persistence.PersistenceContext;
import javax.persistence.QueryHint;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

/**
 * Repository abstraction for {@link Product} aggregate.
 *
 * Responsibilities:
 *  - Simple CRUD operations inherited from {@link JpaRepository}
 *  - Fine-grained queries required by the pricing/approval engines
 *  - Inventory reservation with pessimistic locking semantics
 *
 * NOTE:
 * The concrete implementation for complex mutating operations lives in {@link ProductRepositoryImpl}
 */
@Repository
public interface ProductRepository extends JpaRepository<Product, Long>, ProductRepositoryCustom {

    /* -----------------------------------  Derived queries  ----------------------------------- */

    Optional<Product> findBySku(@Param("sku") @NonNull String sku);

    List<Product> findByStatus(@Param("status") @NonNull ProductStatus status);

    @EntityGraph(attributePaths = {"categories", "primaryImage"})
    @Query("select p from Product p where p.categories.slug = :categorySlug and p.status = 'ACTIVE'")
    List<Product> findActiveByCategorySlug(@Param("categorySlug") String categorySlug);

    /* -----------------------------------  Pricing-related projections  ----------------------------------- */

    /**
     * Retrieves tiered pricing for a given account by delegating to a DB-level view that resolves
     * contract pricing, account group overrides, and promotional adjustments.
     *
     * The result is mapped into a lightweight projection (record) to minimize hydration cost.
     */
    @Query(nativeQuery = true,
           value = """
                   SELECT
                       tp.product_id  AS productId,
                       tp.min_qty     AS minQuantity,
                       tp.max_qty     AS maxQuantity,
                       tp.unit_price  AS unitPrice,
                       tp.currency    AS currency
                   FROM v_tiered_pricing tp
                   WHERE tp.product_id = :productId
                     AND tp.account_id = :accountId
                     AND tp.valid_from <= now()
                     AND (tp.valid_to IS NULL OR tp.valid_to >= now())
                   ORDER BY tp.min_qty
                   """)
    List<TieredPriceRow> fetchTieredPricing(@Param("productId") long productId,
                                            @Param("accountId") long accountId);

    /**
     * Projection for tiered pricing native query.
     */
    interface TieredPriceRow {
        Long getProductId();
        Integer getMinQuantity();
        Integer getMaxQuantity();
        java.math.BigDecimal getUnitPrice();
        String getCurrency();
    }
}

/* ============================================================================================= */
/*                              Custom repository declaration                                    */
/* ============================================================================================= */

interface ProductRepositoryCustom {

    /**
     * Locks the product row for write operations so that stock mutations or price changes
     * are executed in a consistent manner across concurrent transactions.
     */
    Product lockById(@NonNull Long id) throws DataAccessException;

    /**
     * Decreases the sellable inventory count for a product if (and only if) sufficient
     * quantity is available. Returns true when the reservation succeeds.
     */
    boolean reserveInventory(@NonNull Long productId, int requestedQty) throws DataAccessException;

    /**
     * Explicitly refreshes the product instance from the database, discarding any
     * first-level cache state that may have been changed within the same transaction.
     */
    void refresh(@NonNull Product product);
}

/* ============================================================================================= */
/*                              Custom repository implementation                                 */
/* ============================================================================================= */

class ProductRepositoryImpl implements ProductRepositoryCustom {

    @PersistenceContext
    private EntityManager em;

    /**
     * NOTE: Spring will decorate this bean with transactional proxies automatically
     * because it lives in the same package scan as the main @Repository.
     */
    @Override
    @Transactional(readOnly = true)
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @QueryHints(@QueryHint(name = "javax.persistence.lock.timeout", value = "3000"))
    public Product lockById(@NonNull Long id) {
        Product product = em.find(Product.class, id, LockModeType.PESSIMISTIC_WRITE);
        if (product == null) {
            throw new IllegalArgumentException("Product %d cannot be locked because it does not exist".formatted(id));
        }
        return product;
    }

    @Override
    @Transactional
    public boolean reserveInventory(@NonNull Long productId, int requestedQty) throws DataAccessException {
        if (requestedQty <= 0) {
            throw new IllegalArgumentException("Requested quantity must be positive");
        }

        /*
         * Implementation strategy:
         * 1) Pessimistically lock the row to avoid race conditions
         * 2) Verify stock availability
         * 3) Perform in-place update
         */
        Product product = lockById(productId);
        if (product.getAvailableQuantity() < requestedQty) {
            return false;
        }

        int updated = em.createQuery("""
                    UPDATE Product p
                       SET p.availableQuantity = p.availableQuantity - :qty,
                           p.updatedAt          = :now
                     WHERE p.id = :id
                    """)
                .setParameter("qty", requestedQty)
                .setParameter("now", OffsetDateTime.now())
                .setParameter("id", productId)
                .executeUpdate();

        // Just in case JPA provider returns unexpected value
        return updated == 1;
    }

    @Override
    public void refresh(@NonNull Product product) {
        em.refresh(product);
    }
}
```