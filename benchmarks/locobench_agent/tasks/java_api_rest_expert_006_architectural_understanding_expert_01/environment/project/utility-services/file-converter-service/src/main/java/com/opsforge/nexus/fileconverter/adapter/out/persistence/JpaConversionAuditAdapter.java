package com.opsforge.nexus.fileconverter.adapter.out.persistence;

import com.opsforge.nexus.fileconverter.domain.audit.ConversionAudit;
import com.opsforge.nexus.fileconverter.domain.audit.ConversionAuditId;
import com.opsforge.nexus.fileconverter.domain.audit.ConversionStatus;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.RequiredArgsConstructor;
import lombok.Setter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.Id;
import javax.persistence.Table;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

/**
 * Outbound adapter that persists {@link ConversionAudit} aggregates using Spring-Data JPA.
 *
 * <p>This class represents the only place in the file-converter micro-service that knows
 * anything about JPA or the underlying relational database.  All other layers
 * interact exclusively through the {@link ConversionAuditPersistencePort} abstraction,
 * keeping the core domain completely decoupled from persistence concerns.</p>
 *
 * <p>The implementation is intentionally defensive and logs every exceptional
 * circumstance to facilitate fast triage in production.  Database‐specific problems
 * are wrapped into a service-level {@link PersistenceException} so that calling
 * layers can react uniformly no matter what persistence technology backs this port.</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@Transactional
public class JpaConversionAuditAdapter implements ConversionAuditPersistencePort {

    private final ConversionAuditJpaRepository repository;

    @Override
    public ConversionAudit save(ConversionAudit audit) {
        try {
            ConversionAuditJpaEntity entity = toEntity(audit);
            ConversionAuditJpaEntity persisted = repository.save(entity);
            log.debug("Persisted ConversionAudit [{}]", persisted.getId());
            return toDomain(persisted);
        } catch (DataAccessException dae) {
            log.error("Database exception while persisting audit {}", audit.getId(), dae);
            throw new PersistenceException("Unable to persist conversion audit", dae);
        }
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<ConversionAudit> findById(ConversionAuditId id) {
        try {
            return repository.findById(id.value())
                             .map(this::toDomain);
        } catch (DataAccessException dae) {
            log.error("Database exception while retrieving audit {}", id, dae);
            throw new PersistenceException("Unable to retrieve conversion audit", dae);
        }
    }

    @Override
    @Transactional(readOnly = true)
    public Page<ConversionAudit> findByDateRange(Instant fromInclusive,
                                                 Instant toExclusive,
                                                 Pageable pageable) {
        try {
            return repository
                    .findAllByRequestedAtBetween(fromInclusive, toExclusive, pageable)
                    .map(this::toDomain);
        } catch (DataAccessException dae) {
            log.error("Database exception while querying audits between {} and {}", fromInclusive, toExclusive, dae);
            throw new PersistenceException("Unable to query conversion audits", dae);
        }
    }

    /* -------------------------------------------------------------------- */
    /*  Private mapping helpers – keep the logic close to where it’s used   */
    /* -------------------------------------------------------------------- */

    private ConversionAuditJpaEntity toEntity(ConversionAudit audit) {
        return ConversionAuditJpaEntity.builder()
                .id(audit.getId().value())
                .conversionType(audit.getConversionType())
                .inputFormat(audit.getInputFormat())
                .outputFormat(audit.getOutputFormat())
                .requestedAt(audit.getRequestedAt())
                .completedAt(audit.getCompletedAt())
                .status(audit.getStatus().name())
                .errorMessage(audit.getErrorMessage())
                .build();
    }

    private ConversionAudit toDomain(ConversionAuditJpaEntity entity) {
        return ConversionAudit.builder()
                .id(ConversionAuditId.of(entity.getId()))
                .conversionType(entity.getConversionType())
                .inputFormat(entity.getInputFormat())
                .outputFormat(entity.getOutputFormat())
                .requestedAt(entity.getRequestedAt())
                .completedAt(entity.getCompletedAt())
                .status(ConversionStatus.valueOf(entity.getStatus()))
                .errorMessage(entity.getErrorMessage())
                .build();
    }

    /* -------------------------------------------------------------------- */
    /*                       Nested infrastructure types                    */
    /* -------------------------------------------------------------------- */

    /**
     * Minimal JPA entity used solely by this adapter.  In a real-world project
     * the entity would live in its own file, but nesting it here makes the
     * example self-contained.
     */
    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @Entity
    @Table(name = "conversion_audit")
    static class ConversionAuditJpaEntity {

        @Id
        private UUID id;

        @Column(nullable = false, length = 128)
        private String conversionType;

        @Column(nullable = false, length = 16)
        private String inputFormat;

        @Column(nullable = false, length = 16)
        private String outputFormat;

        @Column(nullable = false)
        private Instant requestedAt;

        private Instant completedAt;

        @Column(nullable = false, length = 32)
        private String status;

        @Column(length = 2048)
        private String errorMessage;
    }

    /**
     * Spring-Data repository that hides SQL specifics from the adapter.
     * Additional query methods can be declared here as new use-cases arise.
     */
    interface ConversionAuditJpaRepository extends JpaRepository<ConversionAuditJpaEntity, UUID> {

        Page<ConversionAuditJpaEntity> findAllByRequestedAtBetween(Instant fromInclusive,
                                                                   Instant toExclusive,
                                                                   Pageable pageable);
    }

    /* -------------------------------------------------------------------- */
    /*                         Port & exception types                       */
    /* -------------------------------------------------------------------- */

    /**
     * Outbound port implemented by the adapter.  Defining it here avoids
     * scattering the example across multiple files while still demonstrating
     * hexagonal principles.
     */
    public interface ConversionAuditPersistencePort {

        ConversionAudit save(ConversionAudit audit);

        Optional<ConversionAudit> findById(ConversionAuditId id);

        Page<ConversionAudit> findByDateRange(Instant fromInclusive,
                                              Instant toExclusive,
                                              Pageable pageable);
    }

    /**
     * Service-level exception thrown when persistence fails.  Using a
     * dedicated type keeps the database driver’s exceptions from leaking
     * into upper layers.
     */
    public static class PersistenceException extends RuntimeException {
        public PersistenceException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}