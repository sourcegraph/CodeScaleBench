```java
package com.commercesphere.enterprise.ordering.repository;

import com.commercesphere.enterprise.ordering.domain.Order;
import com.commercesphere.enterprise.ordering.domain.OrderStatus;
import com.commercesphere.enterprise.shared.audit.AuditLogService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import javax.persistence.*;
import javax.persistence.criteria.CriteriaBuilder;
import javax.persistence.criteria.CriteriaQuery;
import javax.persistence.criteria.Predicate;
import javax.persistence.criteria.Root;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * Central data-access component for the Order aggregate.
 * <p>
 * Spring Data will generate the boilerplate CRUD operations by dynamically
 * proxying this interface.  Complex, domain-specific queries live in the
 * {@link OrderRepositoryCustom} extension so that we keep this interface
 * clean and traceable for basic use cases.
 */
@Repository
public interface OrderRepository extends JpaRepository<Order, Long>, OrderRepositoryCustom {

    /**
     * Retrieves a single Order by its externally visible order number.
     *
     * @param orderNumber the functional business key
     * @return the matching Order, if any
     */
    Optional<Order> findByOrderNumber(String orderNumber);

    /**
     * Fetches an Order and upgrades the row-level lock to OPTIMISTIC, throwing
     * an {@link OptimisticLockException} if the {@code @Version} column was
     * modified by another writer in the meantime.
     *
     * @param id the primary key
     * @return the locked Order, if found
     */
    @Lock(LockModeType.OPTIMISTIC)
    Optional<Order> findWithLockingById(Long id);

    /**
     * Streaming, filtered lookup by Account and OrderStatus collection.
     * <p>
     * Implemented automatically by Spring Data, including COUNT(*) query for
     * pagination metadata.
     */
    Page<Order> findByAccountIdAndStatusIn(Long accountId,
                                           List<OrderStatus> statuses,
                                           Pageable pageable);
}

/* ------------------------------------------------------------------------- */
/* ------------------------------  Extension  ------------------------------ */
/* ------------------------------------------------------------------------- */

/**
 * Domain-centric custom repository contract that contains advanced use cases
 * unsuited for the {@link JpaRepository} method naming convention.
 */
interface OrderRepositoryCustom {

    /**
     * Performs a flexible, pageable search across multiple dimensions.
     *
     * @param criteria filtering options encapsulated in a value object
     * @param pageable Spring Data pagination abstraction
     * @return page of matching orders
     */
    Page<Order> searchOrders(OrderSearchCriteria criteria, Pageable pageable);

    /**
     * Writes an Order to the data store and immediately flushes the change,
     * emitting an audit trail entry in the same transaction.
     *
     * @param order       order to persist
     * @param performedBy username or id of the actor
     * @return the managed Order instance
     * @throws OptimisticLockingFailureException propagated when the underlying
     *                                           row version was incremented by a
     *                                           concurrent transaction
     */
    Order saveAndFlushWithAudit(Order order, String performedBy)
            throws OptimisticLockingFailureException;
}

/**
 * Concrete runtime implementation wired by Spring Data via the naming
 * convention "Impl".  Only domain-specific logic lives here; CRUD plumbing is
 * delegated to {@link JpaRepository}.
 */
class OrderRepositoryImpl implements OrderRepositoryCustom {

    private static final Logger log = LoggerFactory.getLogger(OrderRepositoryImpl.class);

    @PersistenceContext
    private EntityManager entityManager;

    private final AuditLogService auditLogService;

    OrderRepositoryImpl(AuditLogService auditLogService) { // Constructor injection
        this.auditLogService = auditLogService;
    }

    /* --------------------------  searchOrders  --------------------------- */

    @Override
    @Transactional(readOnly = true)
    public Page<Order> searchOrders(OrderSearchCriteria criteria, Pageable pageable) {
        CriteriaBuilder cb = entityManager.getCriteriaBuilder();

        // ---------- Main SELECT ----------
        CriteriaQuery<Order> select = cb.createQuery(Order.class);
        Root<Order> root = select.from(Order.class);
        select.where(buildPredicates(criteria, cb, root))
              .orderBy(cb.desc(root.get("createdAt")));

        TypedQuery<Order> dataQuery = entityManager.createQuery(select);
        dataQuery.setFirstResult((int) pageable.getOffset());
        dataQuery.setMaxResults(pageable.getPageSize());
        List<Order> content = dataQuery.getResultList();

        // ---------- COUNT ----------
        CriteriaQuery<Long> count = cb.createQuery(Long.class);
        Root<Order> countRoot = count.from(Order.class);
        count.select(cb.count(countRoot))
             .where(buildPredicates(criteria, cb, countRoot));
        Long total = entityManager.createQuery(count).getSingleResult();

        return new PageImpl<>(content, pageable, total);
    }

    /* ------------------------  saveAndFlushWithAudit  -------------------- */

    @Override
    @Transactional(propagation = Propagation.REQUIRED)
    public Order saveAndFlushWithAudit(Order order, String performedBy) {
        try {
            if (order.getId() == null) {
                entityManager.persist(order);
            } else {
                order = entityManager.merge(order);
            }
            entityManager.flush(); // forces DB round-trip, allowing lock checks

            auditLogService.recordOrderChange(order, performedBy);
            return order;
        } catch (OptimisticLockException e) {
            log.warn("Optimistic locking failed when writing Order[id={}]", order.getId());
            throw new OptimisticLockingFailureException(
                    "Order was modified by another transaction", e);
        } catch (PersistenceException e) {
            log.error("Unexpected JPA error while persisting Order", e);
            throw e; // will be translated by Spring’s @Repository infrastructure
        }
    }

    /* -------------------------  Helper methods  -------------------------- */

    /**
     * Converts the user‐supplied criteria into a Predicate array consumed by
     * the Criteria API.  Extracted for reuse in SELECT and COUNT queries.
     */
    private Predicate[] buildPredicates(OrderSearchCriteria criteria,
                                        CriteriaBuilder cb,
                                        Root<Order> root) {
        List<Predicate> predicates = new ArrayList<>();

        if (criteria.getOrderNumber() != null) {
            predicates.add(cb.equal(root.get("orderNumber"), criteria.getOrderNumber()));
        }

        if (criteria.getAccountId() != null) {
            predicates.add(cb.equal(root.get("accountId"), criteria.getAccountId()));
        }

        if (criteria.getStatus() != null) {
            predicates.add(cb.equal(root.get("status"), criteria.getStatus()));
        }

        if (criteria.getCreatedFrom() != null) {
            predicates.add(cb.greaterThanOrEqualTo(root.get("createdAt"),
                                                   criteria.getCreatedFrom()));
        }

        if (criteria.getCreatedTo() != null) {
            predicates.add(cb.lessThanOrEqualTo(root.get("createdAt"),
                                                criteria.getCreatedTo()));
        }

        return predicates.toArray(new Predicate[0]);
    }
}

/* ------------------------------------------------------------------------- */
/* ---------------------------  Value Objects  ----------------------------- */
/* ------------------------------------------------------------------------- */

/**
 * Immutable, builder-based filter object guarding the repository API against
 * explosion of method overloads as business rules evolve.
 */
final class OrderSearchCriteria {

    private final String orderNumber;
    private final Long accountId;
    private final OrderStatus status;
    private final Instant createdFrom;
    private final Instant createdTo;

    private OrderSearchCriteria(Builder builder) {
        this.orderNumber = builder.orderNumber;
        this.accountId = builder.accountId;
        this.status = builder.status;
        this.createdFrom = builder.createdFrom;
        this.createdTo = builder.createdTo;
    }

    public String getOrderNumber() { return orderNumber; }
    public Long getAccountId()     { return accountId;  }
    public OrderStatus getStatus() { return status;     }
    public Instant getCreatedFrom(){ return createdFrom;}
    public Instant getCreatedTo()  { return createdTo;  }

    /* -----------------------------  Builder  ----------------------------- */

    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        private String orderNumber;
        private Long accountId;
        private OrderStatus status;
        private Instant createdFrom;
        private Instant createdTo;

        private Builder() {}

        public Builder orderNumber(String orderNumber) {
            this.orderNumber = orderNumber;
            return this;
        }

        public Builder accountId(Long accountId) {
            this.accountId = accountId;
            return this;
        }

        public Builder status(OrderStatus status) {
            this.status = status;
            return this;
        }

        public Builder createdFrom(Instant createdFrom) {
            this.createdFrom = createdFrom;
            return this;
        }

        public Builder createdTo(Instant createdTo) {
            this.createdTo = createdTo;
            return this;
        }

        public OrderSearchCriteria build() {
            return new OrderSearchCriteria(this);
        }
    }
}
```