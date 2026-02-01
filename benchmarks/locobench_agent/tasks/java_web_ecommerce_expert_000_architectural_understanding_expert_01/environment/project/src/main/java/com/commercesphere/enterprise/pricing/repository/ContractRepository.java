package com.commercesphere.enterprise.pricing.repository;

import com.commercesphere.enterprise.pricing.domain.ContractEntity;
import com.commercesphere.enterprise.pricing.domain.ContractStatus;
import com.commercesphere.enterprise.pricing.dto.ContractPricingSummary;
import com.commercesphere.enterprise.pricing.dto.search.ContractSearchCriteria;
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import jakarta.persistence.PersistenceContext;
import jakarta.persistence.TypedQuery;
import jakarta.persistence.criteria.*;
import jakarta.transaction.Transactional;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.util.CollectionUtils;

import java.time.LocalDate;
import java.util.*;

/**
 * Repository facade for performing CRUD and custom data-access operations on {@link ContractEntity}.
 *
 * <p>
 * The default Spring-Data JPA query derivation is combined with a small
 * custom implementation for more sophisticated search requirements and
 * pessimistic locking semantics needed by the pricing engine.
 * </p>
 */
@Repository
public interface ContractRepository extends JpaRepository<ContractEntity, UUID>, ContractRepositoryCustom {

    /**
     * Finds all contracts that are currently active for a given account.
     *
     * @param accountId the owning account.
     * @param asOfDate  the reference date that must be between {@code effectiveStart} and {@code effectiveEnd}.
     * @return list of active contracts or empty list if none found.
     */
    @Query("""
           SELECT c
             FROM ContractEntity c
            WHERE c.accountId = :accountId
              AND c.status     = com.commercesphere.enterprise.pricing.domain.ContractStatus.ACTIVE
              AND :asOfDate BETWEEN c.effectiveStart AND c.effectiveEnd
           """)
    List<ContractEntity> findActiveContractsByAccountId(@Param("accountId") UUID accountId,
                                                        @Param("asOfDate") LocalDate asOfDate);

    /**
     * Obtains a pessimistic write lock on the contract row. The lock is held
     * until the surrounding {@code @Transactional} boundary completes.
     *
     * @param contractId target id.
     * @return the locked contract entity.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT c FROM ContractEntity c WHERE c.id = :contractId")
    Optional<ContractEntity> lockByIdForUpdate(@Param("contractId") UUID contractId);
}

/**
 * Custom extension point for complex pricing queries that cannot be expressed
 * via Spring-Data’s method-name conventions or JPQL annotations.
 */
interface ContractRepositoryCustom {

    /**
     * Aggregates monetary and quantity totals for an entire contract. Intended
     * for billing previews and administrative dashboards.
     *
     * @param contractId contract identifier.
     * @return summarized pricing data, or empty if contract does not exist.
     */
    Optional<ContractPricingSummary> findPricingSummaryByContractId(UUID contractId);

    /**
     * Full-text style contract search supporting pagination, filtering and sorting.
     *
     * @param criteria domain–specific filter object.
     * @param pageable pagination + sorting configuration.
     * @return paginated list of contracts.
     */
    PageImpl<ContractEntity> searchActiveContracts(ContractSearchCriteria criteria, Pageable pageable);

    /**
     * Convenience wrapper that performs pessimistic locking by id. Throws an
     * exception if the contract does not exist.
     *
     * @param contractId identifier of the contract to lock.
     * @throws ContractNotFoundException if contract absent.
     */
    void lockContractForUpdate(UUID contractId);
}

/**
 * Concrete custom repository implementation. Spring automatically wires this
 * class thanks to its naming convention: {@code <repositoryInterfaceName>Impl}.
 */
class ContractRepositoryImpl implements ContractRepositoryCustom {

    @PersistenceContext
    private EntityManager em;

    // ============ Custom Query Implementations ============ //

    @Override
    public Optional<ContractPricingSummary> findPricingSummaryByContractId(UUID contractId) {
        Objects.requireNonNull(contractId, "contractId must not be null");

        /*
         * Performs a JPQL aggregation across all contract line items while
         * leveraging database-side SUM() functions for efficiency.
         */
        TypedQuery<ContractPricingSummary> query = em.createQuery("""
                SELECT new com.commercesphere.enterprise.pricing.dto.ContractPricingSummary(
                           li.contract.id,
                           SUM(li.extendedPrice),
                           SUM(li.quantity))
                  FROM ContractLineItemEntity li
                 WHERE li.contract.id = :contractId
                 GROUP BY li.contract.id
                """, ContractPricingSummary.class);
        query.setParameter("contractId", contractId);
        query.setMaxResults(1);

        return query.getResultStream().findFirst();
    }

    @Override
    public PageImpl<ContractEntity> searchActiveContracts(ContractSearchCriteria criteria, Pageable pageable) {
        CriteriaBuilder cb = em.getCriteriaBuilder();

        /*
         * Build the root query for ContractEntity.
         */
        CriteriaQuery<ContractEntity> cq = cb.createQuery(ContractEntity.class);
        Root<ContractEntity> root = cq.from(ContractEntity.class);

        List<Predicate> predicates = buildSearchPredicates(cb, root, criteria);
        cq.where(predicates.toArray(Predicate[]::new));

        // Sorting
        applySorting(cb, cq, root, pageable.getSort());

        // Pagination
        TypedQuery<ContractEntity> typedQuery = em.createQuery(cq);
        typedQuery.setFirstResult((int) pageable.getOffset());
        typedQuery.setMaxResults(pageable.getPageSize());

        List<ContractEntity> contracts = typedQuery.getResultList();

        // Total count query
        long total = fetchTotalCount(cb, predicates);

        return new PageImpl<>(contracts, pageable, total);
    }

    @Override
    @Transactional
    public void lockContractForUpdate(UUID contractId) {
        Objects.requireNonNull(contractId, "contractId must not be null");

        ContractEntity entity = em.find(ContractEntity.class, contractId, LockModeType.PESSIMISTIC_WRITE);
        if (entity == null) {
            throw new ContractNotFoundException(contractId);
        }
    }

    // ============ Private Helper Methods ============ //

    private List<Predicate> buildSearchPredicates(CriteriaBuilder cb,
                                                  Root<ContractEntity> root,
                                                  ContractSearchCriteria criteria) {
        List<Predicate> predicates = new ArrayList<>();

        // Mandatory status filter – only active contracts should be returned.
        predicates.add(cb.equal(root.get("status"), ContractStatus.ACTIVE));

        if (criteria == null) {
            return predicates;
        }

        Optional.ofNullable(criteria.accountId())
                .ifPresent(accountId -> predicates.add(cb.equal(root.get("accountId"), accountId)));

        Optional.ofNullable(criteria.productId())
                .ifPresent(productId -> predicates.add(cb.isMember(productId, root.get("productIds"))));

        if (criteria.startDate() != null && criteria.endDate() != null) {
            predicates.add(cb.between(cb.literal(criteria.referenceDate()),
                                      root.get("effectiveStart"),
                                      root.get("effectiveEnd")));
        }

        if (!CollectionUtils.isEmpty(criteria.statuses())) {
            CriteriaBuilder.In<ContractStatus> inClause = cb.in(root.get("status"));
            criteria.statuses().forEach(inClause::value);
            predicates.add(inClause);
        }

        return predicates;
    }

    private void applySorting(CriteriaBuilder cb,
                              CriteriaQuery<ContractEntity> cq,
                              Root<ContractEntity> root,
                              Sort sort) {
        List<Order> orders = new ArrayList<>();

        if (sort.isUnsorted()) {
            orders.add(cb.desc(root.get("effectiveStart")));
        } else {
            sort.forEach(order -> {
                Path<Object> path = root.get(order.getProperty());
                orders.add(order.isAscending() ? cb.asc(path) : cb.desc(path));
            });
        }

        cq.orderBy(orders);
    }

    private long fetchTotalCount(CriteriaBuilder cb, List<Predicate> predicates) {
        CriteriaQuery<Long> countQuery = cb.createQuery(Long.class);
        Root<ContractEntity> countRoot = countQuery.from(ContractEntity.class);
        countQuery.select(cb.countDistinct(countRoot));
        countQuery.where(predicates.toArray(Predicate[]::new));
        return em.createQuery(countQuery).getSingleResult();
    }
}

/**
 * Domain-specific exception indicating that a requested Contract could not be
 * located in the underlying datastore.
 */
class ContractNotFoundException extends RuntimeException {

    public ContractNotFoundException(UUID contractId) {
        super("Contract with id " + contractId + " was not found.");
    }
}