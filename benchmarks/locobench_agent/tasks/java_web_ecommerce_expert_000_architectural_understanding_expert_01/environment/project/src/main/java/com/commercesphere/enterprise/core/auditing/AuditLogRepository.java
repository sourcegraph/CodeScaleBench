package com.commercesphere.enterprise.core.auditing;

import com.commercesphere.enterprise.core.auditing.model.AuditLogEntity;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Component;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import javax.persistence.EntityManager;
import javax.persistence.PersistenceContext;
import javax.persistence.criteria.CriteriaBuilder;
import javax.persistence.criteria.CriteriaQuery;
import javax.persistence.criteria.Predicate;
import javax.persistence.criteria.Root;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * Central Spring Data repository for interacting with {@link AuditLogEntity} records.
 *
 * <p>The repository purposefully exposes both standard CRUD operations and
 * domain–specific helper functions such as {@code purgeOlderThan} to keep the data-set
 * within a compliance-approved retention window.</p>
 *
 * <p>For more advanced use-cases (free-text search, compound filtering, etc.) the
 * {@link AuditLogRepositoryCustom} contract is provided and backed by a manual JPA
 * implementation that leverages the Criteria API.</p>
 */
@Repository
public interface AuditLogRepository extends
        JpaRepository<AuditLogEntity, UUID>,
        JpaSpecificationExecutor<AuditLogEntity>,
        AuditLogRepositoryCustom {

    /**
     * Best-effort attempt to delete log entries older than the provided timestamp.
     *
     * @param threshold timestamp that represents the exclusive upper bound
     * @return the amount of rows actually deleted
     */
    @Modifying
    @Transactional
    @Query("delete from AuditLogEntity l where l.timestamp < :threshold")
    int purgeOlderThan(@Param("threshold") Instant threshold);
}

/* --------------------------------------------------------------------- */
/* ----------------- Custom Repository Extension ----------------------- */
/* --------------------------------------------------------------------- */

/**
 * Contract for repository methods that require hand-written JPA or JDBC
 * interaction and therefore cannot be expressed via Spring-Data query
 * derivation.
 */
interface AuditLogRepositoryCustom {

    /**
     * Persists a collection of audit logs in one transactional batch.
     *
     * @param logs collection of {@link AuditLogEntity} to persist
     */
    void saveInBatch(@NonNull List<AuditLogEntity> logs);

    /**
     * Removes all log entries older than the supplied {@link Duration}.
     *
     * @param olderThan retention duration
     * @return number of rows deleted
     */
    int purge(@NonNull Duration olderThan);

    /**
     * Full-text / criteria based search over audit logs.
     *
     * @param criteria domain filter object
     * @param pageable paging information
     * @return a paged view of {@link AuditLogEntity} that match the criteria
     */
    Page<AuditLogEntity> search(@NonNull AuditSearchCriteria criteria,
                                @NonNull Pageable pageable);
}

/**
 * Concrete implementation of {@link AuditLogRepositoryCustom}. Spring will
 * automatically wire this class to the primary {@link AuditLogRepository}
 * thanks to the naming convention (suffix "Impl").
 */
@Component // Scanned during component-scan even though class is package-private
class AuditLogRepositoryImpl implements AuditLogRepositoryCustom {

    @PersistenceContext
    private EntityManager em;

    @Override
    @Transactional
    public void saveInBatch(@NonNull List<AuditLogEntity> logs) {
        Objects.requireNonNull(logs, "logs must not be null");

        for (int i = 0; i < logs.size(); i++) {
            em.persist(logs.get(i));

            // Flush and clear periodically to avoid memory bloat for very
            // large batches. Tune batch-size according to JVM / DB settings.
            if (i % 50 == 0) {
                em.flush();
                em.clear();
            }
        }
    }

    @Override
    @Transactional
    public int purge(@NonNull Duration olderThan) {
        Objects.requireNonNull(olderThan, "olderThan must not be null");

        Instant threshold = Instant.now().minus(olderThan);
        return em.createQuery("delete from AuditLogEntity l where l.timestamp < :threshold")
                 .setParameter("threshold", threshold)
                 .executeUpdate();
    }

    @Override
    public Page<AuditLogEntity> search(@NonNull AuditSearchCriteria criteria,
                                       @NonNull Pageable pageable) {
        Objects.requireNonNull(criteria, "criteria must not be null");
        Objects.requireNonNull(pageable, "pageable must not be null");

        CriteriaBuilder cb = em.getCriteriaBuilder();

        /* ------------- Main SELECT query ------------- */
        CriteriaQuery<AuditLogEntity> cq = cb.createQuery(AuditLogEntity.class);
        Root<AuditLogEntity> root = cq.from(AuditLogEntity.class);

        List<Predicate> predicates = buildPredicates(criteria, cb, root);
        cq.where(predicates.toArray(new Predicate[0]))
          .orderBy(cb.desc(root.get("timestamp"))); // newest first

        List<AuditLogEntity> rows = em.createQuery(cq)
                                      .setFirstResult((int) pageable.getOffset())
                                      .setMaxResults(pageable.getPageSize())
                                      .getResultList();

        /* ------------- COUNT query ------------- */
        CriteriaQuery<Long> countQuery = cb.createQuery(Long.class);
        Root<AuditLogEntity> countRoot = countQuery.from(AuditLogEntity.class);
        countQuery.select(cb.count(countRoot))
                  .where(buildPredicates(criteria, cb, countRoot)
                         .toArray(new Predicate[0]));

        Long total = em.createQuery(countQuery).getSingleResult();

        return new PageImpl<>(rows, pageable, total);
    }

    /**
     * Helper that converts {@link AuditSearchCriteria} into JPA {@link Predicate}s.
     */
    private static List<Predicate> buildPredicates(AuditSearchCriteria criteria,
                                                   CriteriaBuilder cb,
                                                   Root<AuditLogEntity> root) {

        List<Predicate> predicates = new ArrayList<>();

        if (criteria.getActorId() != null) {
            predicates.add(cb.equal(root.get("actorId"), criteria.getActorId()));
        }
        if (criteria.getAction() != null) {
            predicates.add(cb.equal(root.get("action"), criteria.getAction()));
        }
        if (criteria.getStartTimestamp() != null) {
            predicates.add(cb.greaterThanOrEqualTo(root.get("timestamp"),
                                                   criteria.getStartTimestamp()));
        }
        if (criteria.getEndTimestamp() != null) {
            predicates.add(cb.lessThanOrEqualTo(root.get("timestamp"),
                                                criteria.getEndTimestamp()));
        }
        if (criteria.getCorrelationId() != null) {
            predicates.add(cb.equal(root.get("correlationId"),
                                    criteria.getCorrelationId()));
        }
        if (criteria.getFreeText() != null && !criteria.getFreeText().isBlank()) {
            // Perform a simple LIKE match against the 'details' column.
            predicates.add(cb.like(cb.lower(root.get("details")),
                                   "%" + criteria.getFreeText().toLowerCase() + "%"));
        }
        return predicates;
    }
}

/* --------------------------------------------------------------------- */
/* ---------------------- DTO / Criteria Object ------------------------ */
/* --------------------------------------------------------------------- */

/**
 * Immutable filter object used to express complex search queries against
 * the audit-log table.  Instances should be built via the fluent
 * {@link Builder} for readability.
 */
final class AuditSearchCriteria {

    private final UUID actorId;
    private final String action;
    private final Instant startTimestamp;
    private final Instant endTimestamp;
    private final String correlationId;
    private final String freeText;

    private AuditSearchCriteria(Builder b) {
        this.actorId = b.actorId;
        this.action = b.action;
        this.startTimestamp = b.startTimestamp;
        this.endTimestamp = b.endTimestamp;
        this.correlationId = b.correlationId;
        this.freeText = b.freeText;
    }

    public UUID getActorId() {
        return actorId;
    }

    public String getAction() {
        return action;
    }

    public Instant getStartTimestamp() {
        return startTimestamp;
    }

    public Instant getEndTimestamp() {
        return endTimestamp;
    }

    public String getCorrelationId() {
        return correlationId;
    }

    public String getFreeText() {
        return freeText;
    }

    /* ----------------------- Builder pattern ----------------------- */

    public static Builder builder() {
        return new Builder();
    }

    static final class Builder {

        private UUID actorId;
        private String action;
        private Instant startTimestamp;
        private Instant endTimestamp;
        private String correlationId;
        private String freeText;

        public Builder actorId(UUID actorId) {
            this.actorId = actorId;
            return this;
        }

        public Builder action(String action) {
            this.action = action;
            return this;
        }

        public Builder startTimestamp(Instant startTimestamp) {
            this.startTimestamp = startTimestamp;
            return this;
        }

        public Builder endTimestamp(Instant endTimestamp) {
            this.endTimestamp = endTimestamp;
            return this;
        }

        public Builder correlationId(String correlationId) {
            this.correlationId = correlationId;
            return this;
        }

        public Builder freeText(String freeText) {
            this.freeText = freeText;
            return this;
        }

        public AuditSearchCriteria build() {
            return new AuditSearchCriteria(this);
        }
    }
}