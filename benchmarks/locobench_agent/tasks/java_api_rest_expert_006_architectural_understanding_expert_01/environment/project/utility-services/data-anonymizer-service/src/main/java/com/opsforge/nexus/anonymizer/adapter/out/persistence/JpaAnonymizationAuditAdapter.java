package com.opsforge.nexus.anonymizer.adapter.out.persistence;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.stream.Collectors;

import javax.persistence.*;
import javax.persistence.criteria.CriteriaBuilder;
import javax.persistence.criteria.CriteriaQuery;
import javax.persistence.criteria.Root;
import javax.transaction.Transactional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.data.domain.*;
import org.springframework.stereotype.Component;

/**
 * Spring‐Data/JPA implementation of the outbound port responsible for
 * persisting {@link AnonymizationAudit} records.
 *
 * This adapter converts pure domain objects to JPA entities and vice-versa,
 * shielding the rest of the system from any JPA/SQL specifics.
 */
@Component
class JpaAnonymizationAuditAdapter implements AnonymizationAuditOutboundPort {

    private static final Logger LOG = LoggerFactory.getLogger(JpaAnonymizationAuditAdapter.class);

    private final EntityManager entityManager;
    private final AuditJpaRepository repository;

    JpaAnonymizationAuditAdapter(EntityManager entityManager, AuditJpaRepository repository) {
        this.entityManager = entityManager;
        this.repository   = repository;
    }

    /* ---------------------------------------------------------------------
     * Outbound-Port Implementation
     * ------------------------------------------------------------------- */

    @Override
    @Transactional
    public AnonymizationAudit save(AnonymizationAudit audit) {
        try {
            AuditJpaEntity persisted = repository.save(AuditJpaEntity.fromDomain(audit));
            return persisted.toDomain();
        } catch (DataAccessException ex) {
            LOG.error("Failed to persist anonymization audit: {}", ex.getMessage(), ex);
            throw new AuditPersistenceException("Unable to persist anonymization audit", ex);
        }
    }

    @Override
    public Optional<AnonymizationAudit> findById(UUID auditId) {
        return repository.findById(auditId).map(AuditJpaEntity::toDomain);
    }

    @Override
    public Optional<AnonymizationAudit> findByRequestId(UUID requestId) {
        return repository.findByRequestId(requestId).map(AuditJpaEntity::toDomain);
    }

    @Override
    public Page<AnonymizationAudit> findAll(Pageable pageable) {
        return repository.findAll(pageable).map(AuditJpaEntity::toDomain);
    }

    @Override
    public List<AnonymizationAudit> findBetween(Instant from, Instant until) {
        CriteriaBuilder cb = entityManager.getCriteriaBuilder();
        CriteriaQuery<AuditJpaEntity> query = cb.createQuery(AuditJpaEntity.class);
        Root<AuditJpaEntity> root = query.from(AuditJpaEntity.class);

        query.select(root)
             .where(cb.between(root.get("anonymizedAt"), from, until))
             .orderBy(cb.asc(root.get("anonymizedAt")));

        return entityManager.createQuery(query)
                            .getResultList()
                            .stream()
                            .map(AuditJpaEntity::toDomain)
                            .collect(Collectors.toUnmodifiableList());
    }

    /* ---------------------------------------------------------------------
     * JPA Helper Types
     * ------------------------------------------------------------------- */

    /**
     * Pure JPA representation of an anonymization audit record.
     */
    @Entity
    @Table(name = "anonymization_audit")
    static class AuditJpaEntity {

        @Id
        @Column(name = "audit_id", nullable = false, updatable = false)
        private UUID id;

        @Column(name = "request_id", nullable = false, unique = true)
        private UUID requestId;

        @Column(name = "data_checksum", nullable = false, length = 128)
        private String originalDataChecksum;

        @Column(name = "algorithm", nullable = false, length = 64)
        private String algorithm;

        @Column(name = "executed_by", nullable = false, length = 128)
        private String executedBy;

        @Column(name = "anonymized_at", nullable = false)
        private Instant anonymizedAt;

        @Lob
        @Column(name = "algorithm_config", nullable = false, columnDefinition = "TEXT")
        private String algorithmConfigJson;

        /* Constructors required by JPA */
        protected AuditJpaEntity() { /* for JPA */ }

        private AuditJpaEntity(UUID id,
                               UUID requestId,
                               String originalDataChecksum,
                               String algorithm,
                               String executedBy,
                               Instant anonymizedAt,
                               String algorithmConfigJson) {
            this.id                    = id;
            this.requestId             = requestId;
            this.originalDataChecksum  = originalDataChecksum;
            this.algorithm             = algorithm;
            this.executedBy            = executedBy;
            this.anonymizedAt          = anonymizedAt;
            this.algorithmConfigJson   = algorithmConfigJson;
        }

        static AuditJpaEntity fromDomain(AnonymizationAudit audit) {
            return new AuditJpaEntity(
                    audit.getId(),
                    audit.getRequestId(),
                    audit.getOriginalDataChecksum(),
                    audit.getAlgorithm(),
                    audit.getExecutedBy(),
                    audit.getAnonymizedAt(),
                    audit.getAlgorithmConfigJson());
        }

        AnonymizationAudit toDomain() {
            return AnonymizationAudit.builder()
                    .id(id)
                    .requestId(requestId)
                    .originalDataChecksum(originalDataChecksum)
                    .algorithm(algorithm)
                    .executedBy(executedBy)
                    .anonymizedAt(anonymizedAt)
                    .algorithmConfigJson(algorithmConfigJson)
                    .build();
        }
    }

    /**
     * Spring-Data repository for {@link AuditJpaEntity}.
     */
    interface AuditJpaRepository extends org.springframework.data.jpa.repository.JpaRepository<AuditJpaEntity, UUID> {
        Optional<AuditJpaEntity> findByRequestId(UUID requestId);
    }

    /* ---------------------------------------------------------------------
     * Port & Exception Definitions — would normally reside in their own
     * packages, but are collocated here for brevity.
     * ------------------------------------------------------------------- */

    /**
     * Outbound port that the application/service layer depends on.
     */
    interface AnonymizationAuditOutboundPort {

        AnonymizationAudit save(AnonymizationAudit audit);

        Optional<AnonymizationAudit> findById(UUID auditId);

        Optional<AnonymizationAudit> findByRequestId(UUID requestId);

        Page<AnonymizationAudit> findAll(Pageable pageable);

        /**
         * Retrieve all audit records anonymized between the given instants.
         *
         * @param from  inclusive lower bound
         * @param until inclusive upper bound
         * @return immutable list of audit records
         */
        List<AnonymizationAudit> findBetween(Instant from, Instant until);
    }

    /**
     * Exception raised when any persistence/SQL-level problem occurs.
     */
    static class AuditPersistenceException extends RuntimeException {
        AuditPersistenceException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * Pure domain model of an anonymization audit.
     *
     * NOTE: In the real project this would live in the domain module and would
     * never reference JPA/Spring.  It is placed here only so that the file
     * compiles stand-alone.
     */
    static final class AnonymizationAudit {

        /* Immutable value-object: all fields are final */
        private final UUID    id;
        private final UUID    requestId;
        private final String  originalDataChecksum;
        private final String  algorithm;
        private final String  executedBy;
        private final Instant anonymizedAt;
        private final String  algorithmConfigJson;

        private AnonymizationAudit(Builder builder) {
            this.id                   = builder.id;
            this.requestId            = builder.requestId;
            this.originalDataChecksum = builder.originalDataChecksum;
            this.algorithm            = builder.algorithm;
            this.executedBy           = builder.executedBy;
            this.anonymizedAt         = builder.anonymizedAt;
            this.algorithmConfigJson  = builder.algorithmConfigJson;
        }

        public static Builder builder() { return new Builder(); }

        /* Getters */
        public UUID getId()                    { return id; }
        public UUID getRequestId()             { return requestId; }
        public String getOriginalDataChecksum(){ return originalDataChecksum; }
        public String getAlgorithm()           { return algorithm; }
        public String getExecutedBy()          { return executedBy; }
        public Instant getAnonymizedAt()       { return anonymizedAt; }
        public String getAlgorithmConfigJson() { return algorithmConfigJson; }

        /* Builder pattern enables fluent, type-safe construction */
        public static final class Builder {
            private UUID    id;
            private UUID    requestId;
            private String  originalDataChecksum;
            private String  algorithm;
            private String  executedBy;
            private Instant anonymizedAt;
            private String  algorithmConfigJson;

            public Builder id(UUID id) {
                this.id = id; return this;
            }
            public Builder requestId(UUID requestId) {
                this.requestId = requestId; return this;
            }
            public Builder originalDataChecksum(String checksum) {
                this.originalDataChecksum = checksum; return this;
            }
            public Builder algorithm(String algorithm) {
                this.algorithm = algorithm; return this;
            }
            public Builder executedBy(String executedBy) {
                this.executedBy = executedBy; return this;
            }
            public Builder anonymizedAt(Instant anonymizedAt) {
                this.anonymizedAt = anonymizedAt; return this;
            }
            public Builder algorithmConfigJson(String json) {
                this.algorithmConfigJson = json; return this;
            }
            public AnonymizationAudit build() {
                if (id == null) id = UUID.randomUUID();
                if (requestId == null)
                    throw new IllegalStateException("requestId is mandatory");
                if (anonymizedAt == null) anonymizedAt = Instant.now();
                return new AnonymizationAudit(this);
            }
        }
    }
}