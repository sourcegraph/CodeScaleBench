```java
package com.sprintcart.adapters.persistence.repository;

import com.sprintcart.adapters.persistence.entity.ProductJpaEntity;
import java.util.List;
import java.util.Optional;
import javax.persistence.LockModeType;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

/**
 * Spring Data JPA repository for {@link ProductJpaEntity}.
 *
 * Serves as the data-source specific implementation (Spring Data automatically
 * generates the proxy) of the {@code ProductRepository} port defined in the domain layer.
 *
 * Exposes convenience and domain-specific queries that are frequently used by the
 * CatalogMaintenance use-case, while delegating more complex look-ups to
 * {@link org.springframework.data.jpa.domain.Specification}-based queries.
 *
 * All methods are designed to be side-effect free unless explicitly annotated
 * with {@link Modifying}.
 */
@Repository
public interface ProductSpringDataRepository extends
        JpaRepository<ProductJpaEntity, Long>,
        JpaSpecificationExecutor<ProductJpaEntity> {

    /**
     * Retrieves a product by its SKU, ignoring case.
     */
    Optional<ProductJpaEntity> findBySkuIgnoreCase(String sku);

    /**
     * Retrieves a product by its human-friendly slug.
     */
    Optional<ProductJpaEntity> findBySlug(String slug);

    /**
     * Fetches all active products belonging to a category in one shot, eagerly loading prices.
     * Using an {@link EntityGraph} prevents the N+1 problem when iterating products and their prices.
     */
    @EntityGraph(attributePaths = { "prices" })
    Page<ProductJpaEntity> findByCategoryIdAndActiveTrue(Long categoryId, Pageable pageable);

    /**
     * Performs a case-insensitive search over product title, SKU and description.
     * Uses PostgreSQL ILIKE for full-text search; can be overridden with
     * a database-specific implementation via {@code META-INF/orm.xml}.
     */
    @Query("""
           SELECT p
             FROM ProductJpaEntity p
            WHERE lower(p.title)       LIKE lower(concat('%', :keyword, '%'))
               OR lower(p.sku)         LIKE lower(concat('%', :keyword, '%'))
               OR lower(p.description) LIKE lower(concat('%', :keyword, '%'))
           """)
    Page<ProductJpaEntity> searchByKeyword(@Param("keyword") String keyword, Pageable pageable);

    /**
     * Atomically decrements the available stock if sufficient quantity exists.
     *
     * @return number of rows updated (1 if successful, 0 otherwise)
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Transactional
    @Query("""
           UPDATE ProductJpaEntity p
              SET p.stock = p.stock - :quantity
            WHERE p.id    = :productId
              AND p.stock >= :quantity
           """)
    int decrementStockIfAvailable(@Param("productId") Long productId,
                                  @Param("quantity")   int  quantity);

    /**
     * Locks the product record for the duration of the transaction, preventing
     * concurrent updates that could cause overselling.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT p FROM ProductJpaEntity p WHERE p.id = :id")
    Optional<ProductJpaEntity> findByIdForUpdate(@Param("id") Long id);

    /**
     * Soft-deletes a product. Instead of removing the record, it marks it as inactive so
     * that historical analytics remain intact.
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Transactional
    @Query("""
           UPDATE ProductJpaEntity p
              SET p.active = false,
                  p.deletedAt = current_timestamp
            WHERE p.id = :productId
           """)
    void softDelete(@Param("productId") Long productId);

    /**
     * Re-activates a previously soft-deleted product.
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Transactional
    @Query("""
           UPDATE ProductJpaEntity p
              SET p.active = true,
                  p.deletedAt = null
            WHERE p.id = :productId
           """)
    void restore(@Param("productId") Long productId);

    /**
     * Returns all products whose stock level is below the given threshold.
     * Used by the Automation Studio to trigger "reorder" workflows.
     */
    @Query("SELECT p FROM ProductJpaEntity p WHERE p.stock < :threshold AND p.active = true")
    List<ProductJpaEntity> findLowStockProducts(@Param("threshold") int threshold);
}
```