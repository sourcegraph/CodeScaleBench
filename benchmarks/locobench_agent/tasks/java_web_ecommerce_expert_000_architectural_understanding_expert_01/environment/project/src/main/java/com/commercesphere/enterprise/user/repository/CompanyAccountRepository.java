package com.commercesphere.enterprise.user.repository;

import com.commercesphere.enterprise.user.domain.CompanyAccount;
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import jakarta.persistence.PersistenceContext;
import jakarta.persistence.TypedQuery;
import jakarta.persistence.criteria.CriteriaBuilder;
import jakarta.persistence.criteria.CriteriaQuery;
import jakarta.persistence.criteria.Predicate;
import jakarta.persistence.criteria.Root;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.*;

/**
 * Primary Spring‐Data repository for the {@link CompanyAccount} aggregation root. <br>
 * <ul>
 *     <li>Basic CRUD operations are inherited from {@link JpaRepository}</li>
 *     <li>Domain‐specific read and mutation use‐cases are exposed via {@link CompanyAccountRepositoryCustom}</li>
 * </ul>
 *
 * NOTE: Only queries that cannot be composed through Spring‐Data query derivation
 * reside in {@link CompanyAccountRepositoryImpl}. Doing so keeps the interface clean
 * while still allowing ad–hoc requirements to be implemented efficiently.
 */
@Repository
public interface CompanyAccountRepository
        extends JpaRepository<CompanyAccount, Long>, CompanyAccountRepositoryCustom {

    /**
     * Find the company account that owns the given ERP/CRM identifier.
     *
     * @param companyId unique identifier shared between external systems.
     * @return Optional containing the account if present.
     */
    Optional<CompanyAccount> findByCompanyId(String companyId);

    /**
     * Obtain a pessimistic write lock on the requested account.
     * The lock will be released when the surrounding transaction completes.
     *
     * @param id primary key of the account to lock.
     * @return Optional with locked entity, or empty if not found.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select ca from CompanyAccount ca where ca.id = :id")
    Optional<CompanyAccount> lockById(@Param("id") Long id);

    /**
     * Retrieve direct children for display in hierarchical trees.
     *
     * @param parentAccountId immediate parent ID.
     * @return list of children (may be empty).
     */
    List<CompanyAccount> findByParentAccount_Id(Long parentAccountId);
}

/* *****************************************************************************************
 *                                    CUSTOM EXTENSION
 * ****************************************************************************************/

/**
 * Programmatic extension points required by the domain layer. Implementations are provided via
 * {@link CompanyAccountRepositoryImpl} and wired automatically by Spring‐Data (naming convention).
 */
interface CompanyAccountRepositoryCustom {

    /**
     * Dynamically search company accounts using the provided {@link AccountSearchCriteria}.
     *
     * @param criteria filters to apply.
     * @param pageable pagination + sorting meta data.
     * @return page of matching accounts.
     */
    Page<CompanyAccount> searchAccounts(AccountSearchCriteria criteria, Pageable pageable);

    /**
     * Deactivate the requested account including every descendant in the hierarchy.
     *
     * @param rootAccountId root account whose complete subtree will be disabled.
     */
    void deactivateAccountHierarchy(Long rootAccountId);

    /**
     * Fetch all recursive descendant IDs of an account (including the root one).
     * The method relies on database specific features (e.g. WITH RECURSIVE) but gracefully
     * degrades if unsupported.
     *
     * @param rootAccountId the ancestor account.
     * @return set of IDs representing the entire subtree.
     */
    Set<Long> fetchDescendantIds(Long rootAccountId);
}

/**
 * Concrete implementation of complex repository use-cases that can’t (or shouldn’t) be expressed
 * via Spring-Data query derivation.  Package-private to keep the public API small.
 */
class CompanyAccountRepositoryImpl implements CompanyAccountRepositoryCustom {

    @PersistenceContext
    private EntityManager entityManager;

    @Autowired
    private NamedParameterJdbcTemplate jdbcTemplate;

    private static final String RECURSIVE_SQL =
            """
            WITH RECURSIVE subtree AS (
                SELECT id
                FROM   company_account
                WHERE  id = :rootId
                UNION
                SELECT ca.id
                FROM   company_account ca
                       JOIN subtree s ON ca.parent_id = s.id
            )
            SELECT id
            FROM   subtree
            """;

    @Override
    @Transactional(readOnly = true)
    public Page<CompanyAccount> searchAccounts(@NonNull AccountSearchCriteria criteria, @NonNull Pageable pageable) {

        final CriteriaBuilder cb = entityManager.getCriteriaBuilder();

        // ===================== data query =====================
        final CriteriaQuery<CompanyAccount> dataQuery = cb.createQuery(CompanyAccount.class);
        final Root<CompanyAccount> root = dataQuery.from(CompanyAccount.class);

        List<Predicate> predicates = buildPredicates(criteria, cb, root);
        dataQuery.select(root).where(predicates.toArray(new Predicate[0]));

        if (pageable.getSort().isSorted()) {
            dataQuery.orderBy(pageable.getSort().stream()
                    .map(order -> order.isAscending()
                            ? cb.asc(root.get(order.getProperty()))
                            : cb.desc(root.get(order.getProperty())))
                    .toList());
        }

        TypedQuery<CompanyAccount> typedQuery = entityManager.createQuery(dataQuery)
                .setFirstResult((int) pageable.getOffset())
                .setMaxResults(pageable.getPageSize());

        List<CompanyAccount> results = typedQuery.getResultList();

        // ===================== count query ====================
        final CriteriaQuery<Long> countQuery = cb.createQuery(Long.class);
        final Root<CompanyAccount> countRoot = countQuery.from(CompanyAccount.class);
        countQuery.select(cb.count(countRoot)).where(buildPredicates(criteria, cb, countRoot).toArray(new Predicate[0]));

        Long total = entityManager.createQuery(countQuery).getSingleResult();

        return new PageImpl<>(results, pageable, total);
    }

    @Override
    @Transactional
    public void deactivateAccountHierarchy(Long rootAccountId) {
        Objects.requireNonNull(rootAccountId, "rootAccountId");

        Set<Long> allIds = fetchDescendantIds(rootAccountId);
        if (allIds.isEmpty()) {
            return;
        }

        int updated = entityManager.createQuery(
                        "update CompanyAccount ca set ca.active = false, ca.updatedAt = :ts where ca.id in :ids")
                .setParameter("ids", allIds)
                .setParameter("ts", LocalDateTime.now())
                .executeUpdate();

        // Flush EntityManager so 2nd level caches are invalidated within the same tx
        entityManager.flush();

        // In a real deployment we might publish a domain event here for cache eviction
        // across distributed nodes, e.g. via Kafka or Spring's ApplicationEventPublisher.
    }

    @Override
    @Transactional(readOnly = true)
    public Set<Long> fetchDescendantIds(Long rootAccountId) {
        Objects.requireNonNull(rootAccountId, "rootAccountId");

        try {
            List<Long> ids = jdbcTemplate.queryForList(
                    RECURSIVE_SQL,
                    new MapSqlParameterSource("rootId", rootAccountId),
                    Long.class
            );
            return new HashSet<>(ids);
        } catch (DataAccessException ex) {
            // Fallback: database doesn't support recursive CTEs (very unlikely). We degrade gracefully
            // by performing iterative fetches using JPA, which can be expensive but guarantees correctness.
            return fetchDescendantIdsFallback(rootAccountId);
        }
    }

    /* ------------------------------------------------------------------------
     *                          PRIVATE HELPERS
     * --------------------------------------------------------------------- */

    private List<Predicate> buildPredicates(AccountSearchCriteria criteria,
                                            CriteriaBuilder cb,
                                            Root<CompanyAccount> root) {

        List<Predicate> predicates = new ArrayList<>();

        if (criteria.getActive() != null) {
            predicates.add(cb.equal(root.get("active"), criteria.getActive()));
        }
        if (criteria.getNameContains() != null) {
            predicates.add(cb.like(cb.lower(root.get("name")),
                    "%" + criteria.getNameContains().toLowerCase() + "%"));
        }
        if (criteria.getCreatedAfter() != null) {
            predicates.add(cb.greaterThanOrEqualTo(root.get("createdAt"), criteria.getCreatedAfter()));
        }
        if (criteria.getCreatedBefore() != null) {
            predicates.add(cb.lessThanOrEqualTo(root.get("createdAt"), criteria.getCreatedBefore()));
        }
        if (criteria.getParentAccountId() != null) {
            predicates.add(cb.equal(root.get("parentAccount").get("id"), criteria.getParentAccountId()));
        }

        return predicates;
    }

    /**
     * Fallback recursive traversal using JPA. Uses breadth-first search to avoid deep recursion.
     */
    private Set<Long> fetchDescendantIdsFallback(Long rootAccountId) {

        Set<Long> visited = new HashSet<>();
        Deque<Long> queue = new ArrayDeque<>();
        queue.add(rootAccountId);

        while (!queue.isEmpty()) {
            Long currentId = queue.poll();
            if (!visited.add(currentId)) {
                continue; // already processed
            }

            List<Long> children = entityManager.createQuery(
                            "select ca.id from CompanyAccount ca where ca.parentAccount.id = :parentId", Long.class)
                    .setParameter("parentId", currentId)
                    .getResultList();

            queue.addAll(children);
        }

        return visited;
    }
}

/* *****************************************************************************************
 *                        QUERY CRITERIA VALUE OBJECT
 * ****************************************************************************************/

/**
 * Immutable value object that captures user supplied filters for account search.
 * A builder pattern is offered for ergonomic construction.
 */
final class AccountSearchCriteria {

    private final Boolean active;
    private final String  nameContains;
    private final LocalDateTime createdAfter;
    private final LocalDateTime createdBefore;
    private final Long parentAccountId;

    private AccountSearchCriteria(Builder b) {
        this.active           = b.active;
        this.nameContains     = b.nameContains;
        this.createdAfter     = b.createdAfter;
        this.createdBefore    = b.createdBefore;
        this.parentAccountId  = b.parentAccountId;
    }

    public Boolean getActive() {
        return active;
    }

    public String getNameContains() {
        return nameContains;
    }

    public LocalDateTime getCreatedAfter() {
        return createdAfter;
    }

    public LocalDateTime getCreatedBefore() {
        return createdBefore;
    }

    public Long getParentAccountId() {
        return parentAccountId;
    }

    /* ------------------------  Builder  --------------------------- */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private Boolean active;
        private String  nameContains;
        private LocalDateTime createdAfter;
        private LocalDateTime createdBefore;
        private Long parentAccountId;

        private Builder() {}

        public Builder active(Boolean active) {
            this.active = active;
            return this;
        }
        public Builder nameContains(String nameContains) {
            this.nameContains = nameContains;
            return this;
        }
        public Builder createdAfter(LocalDateTime createdAfter) {
            this.createdAfter = createdAfter;
            return this;
        }
        public Builder createdBefore(LocalDateTime createdBefore) {
            this.createdBefore = createdBefore;
            return this;
        }
        public Builder parentAccountId(Long parentAccountId) {
            this.parentAccountId = parentAccountId;
            return this;
        }
        public AccountSearchCriteria build() {
            return new AccountSearchCriteria(this);
        }
    }
}