package com.commercesphere.enterprise.inventory.repository;

import com.commercesphere.enterprise.inventory.domain.Stock;
import com.commercesphere.enterprise.inventory.domain.StockAdjustmentReason;
import com.commercesphere.enterprise.shared.exceptions.ConcurrentStockModificationException;
import com.commercesphere.enterprise.shared.exceptions.InvalidBusinessStateException;
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import jakarta.persistence.PersistenceContext;
import jakarta.persistence.TypedQuery;
import jakarta.persistence.criteria.CriteriaBuilder;
import jakarta.persistence.criteria.CriteriaQuery;
import jakarta.persistence.criteria.Predicate;
import jakarta.persistence.criteria.Root;
import jakarta.transaction.Transactional;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * Repository abstraction over {@link Stock} data-store.
 * <p>
 *     This repository exposes two flavors of APIs:
 *     <ol>
 *         <li>Declarative finder methods – delegated to Spring Data JPA</li>
 *         <li>Imperative, fine-grained stock mutation operations – implemented manually to guarantee
 *             repeatable-read semantics and to keep business invariants intact (never going below zero, etc.)</li>
 *     </ol>
 * </p>
 */
@Repository
public interface StockRepository extends JpaRepository<Stock, Long>, StockRepositoryCustom {

    /**
     * Finds a {@link Stock} entry (without locking) for the given SKU code and warehouse.
     */
    @Cacheable(cacheNames = "stock", key = "#root.methodName + #sku + #warehouseId")
    Optional<Stock> findBySkuAndWarehouseId(String sku, UUID warehouseId);

    /**
     * Optimistic concurrency control for administrative batch jobs.
     */
    @Lock(LockModeType.OPTIMISTIC)
    @Query("select s from Stock s where s.sku = :sku and s.warehouseId = :warehouseId")
    Optional<Stock> findWithOptimisticLock(String sku, UUID warehouseId);

    /**
     * Deletes all stock entries for a logical warehouse. Used only during physical warehouse decommission workflow.
     */
    @Modifying
    @CacheEvict(cacheNames = "stock", allEntries = true)
    @Query("delete from Stock s where s.warehouseId = :warehouseId")
    void purgeByWarehouseId(UUID warehouseId);
}

/**
 * Programmatic API that cannot be expressed via Spring Data query derivation.
 */
interface StockRepositoryCustom {

    /**
     * Acquires a pessimistic write lock on a stock row for the given SKU + Warehouse pair.
     * Throws {@link ConcurrentStockModificationException} if the lock cannot be obtained within configured timeout.
     */
    Stock lockForUpdate(String sku, UUID warehouseId);

    /**
     * Atomically increases or decreases the in-stock quantity.
     * <p>
     *     Negative deltas will reduce stock levels, positive deltas will restock.
     *     Implementations have to guarantee
     *     <ul>
     *         <li>No phantom reads</li>
     *         <li>No negative inventory (throws {@link InvalidBusinessStateException})</li>
     *     </ul>
     * </p>
     *
     * @param sku        Product identifier
     * @param warehouseId Warehouse identifier
     * @param delta      Quantity to add (positive) or subtract (negative)
     * @param reason     Enum describing why the adjustment happened
     * @param correlationId Optional correlation ID for audit trail
     */
    void adjustQuantity(String sku,
                        UUID warehouseId,
                        int delta,
                        StockAdjustmentReason reason,
                        UUID correlationId);

    /**
     * Retrieves all items whose availableQuantity is below or equal to the provided threshold.
     * Useful for nightly replenishment jobs.
     */
    List<Stock> findItemsBelowThreshold(int threshold);

}

/**
 * Concrete implementation living in the same compilation unit for simplicity.
 * <p>
 *     Spring will detect this implementation because of the {@code *Impl} naming convention.
 *     Do <strong>not</strong> annotate with {@link Repository}; the marker on the interface is enough.
 * </p>
 */
class StockRepositoryImpl implements StockRepositoryCustom {

    @PersistenceContext
    private EntityManager em;

    @Override
    @Transactional
    public Stock lockForUpdate(String sku, UUID warehouseId) {
        TypedQuery<Stock> query = em.createQuery(
                "select s from Stock s where s.sku = :sku and s.warehouseId = :wid",
                Stock.class
        );
        query.setParameter("sku", sku);
        query.setParameter("wid", warehouseId);
        query.setLockMode(LockModeType.PESSIMISTIC_WRITE);

        try {
            return query.getSingleResult();
        } catch (jakarta.persistence.LockTimeoutException lte) {
            throw new ConcurrentStockModificationException(
                    String.format("Could not acquire lock for SKU %s at warehouse %s", sku, warehouseId), lte
            );
        }
    }

    @Override
    @Transactional
    public void adjustQuantity(String sku,
                               UUID warehouseId,
                               int delta,
                               StockAdjustmentReason reason,
                               UUID correlationId) {

        Stock stock = lockForUpdate(sku, warehouseId);

        int newQuantity = stock.getAvailableQuantity() + delta;
        if (newQuantity < 0) {
            throw new InvalidBusinessStateException(String.format(
                    "Adjustment of %d would make inventory negative (current=%d) for SKU %s in warehouse %s",
                    delta, stock.getAvailableQuantity(), sku, warehouseId
            ));
        }

        stock.setAvailableQuantity(newQuantity);
        stock.setLastAdjustmentReason(reason);
        stock.setLastModifiedAt(Instant.now());
        stock.setLastCorrelationId(correlationId);

        try {
            em.merge(stock);
        } catch (DataIntegrityViolationException dive) {
            // Re-throw with business wording; upper layers log & translate
            throw new ConcurrentStockModificationException(
                    "Stock was concurrently modified while attempting to adjust quantity", dive);
        }
    }

    @Override
    @Transactional
    public List<Stock> findItemsBelowThreshold(int threshold) {
        CriteriaBuilder cb = em.getCriteriaBuilder();
        CriteriaQuery<Stock> cq = cb.createQuery(Stock.class);
        Root<Stock> root = cq.from(Stock.class);

        Predicate predicate = cb.lessThanOrEqualTo(root.get("availableQuantity"), threshold);
        cq.select(root).where(predicate);

        return em.createQuery(cq).getResultList();
    }
}

/*
 * Domain-specific exceptions. They live here for the sake of brevity, but in a real-world codebase
 * they belong in a shared, versioned module.
 */

class StockNotFoundException extends RuntimeException {
    StockNotFoundException(String message) {
        super(message);
    }
}