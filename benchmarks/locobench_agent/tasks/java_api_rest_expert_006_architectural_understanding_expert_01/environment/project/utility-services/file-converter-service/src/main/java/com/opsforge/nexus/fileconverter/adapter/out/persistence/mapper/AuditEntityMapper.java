```java
package com.opsforge.nexus.fileconverter.adapter.out.persistence.mapper;

import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Objects;
import java.util.function.Function;

import com.opsforge.nexus.fileconverter.adapter.out.persistence.entity.AuditEntity;
import com.opsforge.nexus.fileconverter.adapter.out.persistence.entity.enums.ConversionStatusEntity;
import com.opsforge.nexus.fileconverter.domain.AuditRecord;
import com.opsforge.nexus.fileconverter.domain.enums.ConversionStatus;

/**
 * Maps between the pure-domain {@link AuditRecord} and the JPA-persisted
 * {@link AuditEntity}.  Isolation of this translation logic behind a single
 * utility class prevents accidental leakage of persistence-specific concerns
 * into the domain layer and vice-versa.
 *
 * <p>
 * Thread-safe and stateless by design.
 * </p>
 */
public final class AuditEntityMapper {

    private AuditEntityMapper() {
        /* static mapping utility – do not instantiate */
    }

    /**
     * Converts a domain {@link AuditRecord} into a JPA {@link AuditEntity}.
     *
     * @param record domain object, must not be {@code null}
     * @return fully populated {@link AuditEntity}
     * @throws NullPointerException if {@code record} is {@code null}
     */
    public static AuditEntity toEntity(final AuditRecord record) {
        Objects.requireNonNull(record, "record must not be null");

        AuditEntity entity = new AuditEntity();
        entity.setId(record.id());
        entity.setCorrelationId(record.correlationId());
        entity.setSourceFormat(record.sourceFormat());
        entity.setTargetFormat(record.targetFormat());
        entity.setSubmittedAt(asEpochMillis(record.submittedAt()));
        entity.setCompletedAt(asEpochMillis(record.completedAt()));
        entity.setRequester(record.requester());
        entity.setStatus(map(record.status(), AuditEntityMapper::toEntityStatus));

        return entity;
    }

    /**
     * Converts a JPA {@link AuditEntity} into a domain {@link AuditRecord}.
     *
     * @param entity database entity, must not be {@code null}
     * @return immutable {@link AuditRecord}
     * @throws NullPointerException if {@code entity} is {@code null}
     */
    public static AuditRecord toDomain(final AuditEntity entity) {
        Objects.requireNonNull(entity, "entity must not be null");

        return AuditRecord.builder()
                          .id(entity.getId())
                          .correlationId(entity.getCorrelationId())
                          .sourceFormat(entity.getSourceFormat())
                          .targetFormat(entity.getTargetFormat())
                          .submittedAt(asInstant(entity.getSubmittedAt()))
                          .completedAt(asInstant(entity.getCompletedAt()))
                          .requester(entity.getRequester())
                          .status(map(entity.getStatus(), AuditEntityMapper::toDomainStatus))
                          .build();
    }

    /**
     * Applies fields of {@code source} to an already managed {@code target} entity,
     * without touching immutable metadata such as primary key or auditing columns.
     * Designed for <em>update</em> scenarios (PATCH/PUT).
     *
     * @param source domain object carrying new values
     * @param target managed entity that will be mutated
     */
    public static void updateEntity(final AuditRecord source, final AuditEntity target) {
        Objects.requireNonNull(source, "source must not be null");
        Objects.requireNonNull(target, "target must not be null");

        target.setCorrelationId(source.correlationId());
        target.setSourceFormat(source.sourceFormat());
        target.setTargetFormat(source.targetFormat());
        target.setCompletedAt(asEpochMillis(source.completedAt()));
        target.setRequester(source.requester());
        target.setStatus(map(source.status(), AuditEntityMapper::toEntityStatus));
    }

    /* --------------------------------------------------------------------- */
    /*  Internal helpers                                                     */
    /* --------------------------------------------------------------------- */

    private static Long asEpochMillis(final Instant instant) {
        return instant == null ? null : instant.toEpochMilli();
    }

    private static Instant asInstant(final Long millis) {
        return millis == null ? null : Instant.ofEpochMilli(millis).atOffset(ZoneOffset.UTC).toInstant();
    }

    private static ConversionStatusEntity toEntityStatus(final ConversionStatus status) {
        if (status == null) {
            return null;
        }

        return switch (status) {
            case PENDING      -> ConversionStatusEntity.PENDING;
            case IN_PROGRESS  -> ConversionStatusEntity.IN_PROGRESS;
            case COMPLETED    -> ConversionStatusEntity.SUCCESS;
            case ERROR        -> ConversionStatusEntity.FAILED;
        };
    }

    private static ConversionStatus toDomainStatus(final ConversionStatusEntity status) {
        if (status == null) {
            return null;
        }

        return switch (status) {
            case PENDING      -> ConversionStatus.PENDING;
            case IN_PROGRESS  -> ConversionStatus.IN_PROGRESS;
            case SUCCESS      -> ConversionStatus.COMPLETED;
            case FAILED       -> ConversionStatus.ERROR;
        };
    }

    private static <F, T> T map(final F value, final Function<F, T> mapper) {
        return value == null ? null : mapper.apply(value);
    }
}
```