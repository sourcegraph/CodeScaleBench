package com.opsforge.nexus.anonymizer.adapter.out.persistence.entity;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.AttributeConverter;
import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.Transient;
import jakarta.validation.constraints.NotNull;
import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;
import org.hibernate.annotations.GenericGenerator;
import org.hibernate.annotations.Parameter;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

/**
 * JPA entity that captures an immutable audit trail of every data–anonymization job executed by
 * this micro-service. <p>
 *
 * Persisted as <code>anonymization_audit_events</code> with JSONB columns for pre- and post-
 * anonymization payload snapshots, allowing fast, schemaless inspection in PostgreSQL. <p>
 *
 * Even though the entity is part of the outbound persistence adapter, it purposefully models a
 * domain concept (audit event) and should therefore be kept free from any technology-specific
 * annotations except those strictly required for persistence mapping.
 */
@Entity
@Table(name = "anonymization_audit_events")
@EntityListeners(AuditingEntityListener.class)
public class AnonymizationAuditEvent implements Serializable {

    @Serial
    private static final long serialVersionUID = -3464576184191902146L;

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    @Id
    @GeneratedValue(strategy = GenerationType.AUTO, generator = "uuid2")
    @GenericGenerator(
            name = "uuid2",
            strategy = "org.hibernate.id.UUIDGenerator",
            parameters = @Parameter(name = "uuid_gen_strategy_class",
                                     value = "org.hibernate.id.uuid.CustomVersionOneStrategy")
    )
    @Column(name = "id", nullable = false, updatable = false, columnDefinition = "uuid")
    private UUID id;

    /**
     * Correlates all log entries (across micro-services) that belong to the same user request.
     */
    @NotNull
    @Column(name = "correlation_id", nullable = false, columnDefinition = "uuid")
    private UUID correlationId;

    /**
     * Free-form identifier of the system that submitted the anonymization request.
     */
    @NotNull
    @Column(name = "source_system", nullable = false, length = 120)
    private String sourceSystem;

    /**
     * Raw inbound payload before anonymization took place.
     */
    @Convert(converter = JsonNodeAttributeConverter.class)
    @Column(name = "payload_before", columnDefinition = "jsonb")
    private JsonNode payloadBefore;

    /**
     * Resulting payload after anonymization completed.
     */
    @Convert(converter = JsonNodeAttributeConverter.class)
    @Column(name = "payload_after", columnDefinition = "jsonb")
    private JsonNode payloadAfter;

    /**
     * Full list of rule IDs (comma-separated) that were executed.
     */
    @Lob
    @Column(name = "rules_applied", columnDefinition = "text")
    private String rulesApplied;

    /**
     * Lifecycle status of the anonymization job.
     */
    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 24)
    private Status status = Status.IN_PROGRESS;

    @NotNull
    @Column(name = "started_at", nullable = false)
    private Instant startedAt;

    @Column(name = "finished_at")
    private Instant finishedAt;

    @Column(name = "error_message", length = 2048)
    private String errorMessage;

    /* === JPA auditing (created/updated events) ============================ */

    @CreatedDate
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @LastModifiedDate
    @Column(name = "updated_at")
    private Instant updatedAt;

    /* === Constructors ===================================================== */

    protected AnonymizationAuditEvent() {
        // JPA
    }

    private AnonymizationAuditEvent(Builder builder) {
        this.id = builder.id;
        this.correlationId = builder.correlationId;
        this.sourceSystem = builder.sourceSystem;
        this.payloadBefore = builder.payloadBefore;
        this.payloadAfter = builder.payloadAfter;
        this.rulesApplied = builder.rulesApplied;
        this.status = builder.status;
        this.startedAt = builder.startedAt;
        this.finishedAt = builder.finishedAt;
        this.errorMessage = builder.errorMessage;
    }

    /* === Domain-driven behavior =========================================== */

    /**
     * Marks the audit entry as successfully completed.
     */
    public void markCompleted(JsonNode anonymizedPayload, String rulesApplied) {
        this.payloadAfter = anonymizedPayload;
        this.rulesApplied = rulesApplied;
        this.status = Status.COMPLETED;
        this.finishedAt = Instant.now();
    }

    /**
     * Marks the audit entry as failed and persists the root cause for later analysis.
     */
    public void markFailed(Throwable throwable) {
        this.status = Status.FAILED;
        this.errorMessage = throwable.getMessage();
        this.finishedAt = Instant.now();
    }

    /* === JPA validation =================================================== */

    @PrePersist
    @PreUpdate
    private void validateLifeCycle() {
        if (status == Status.COMPLETED && payloadAfter == null) {
            throw new IllegalStateException("Completed audit event must contain payloadAfter");
        }
        if (status == Status.FAILED && errorMessage == null) {
            throw new IllegalStateException("Failed audit event must record errorMessage");
        }
    }

    /* === Utility getters ================================================== */

    public UUID getId() {
        return id;
    }

    public UUID getCorrelationId() {
        return correlationId;
    }

    public String getSourceSystem() {
        return sourceSystem;
    }

    public JsonNode getPayloadBefore() {
        return payloadBefore;
    }

    public JsonNode getPayloadAfter() {
        return payloadAfter;
    }

    public String getRulesApplied() {
        return rulesApplied;
    }

    public Status getStatus() {
        return status;
    }

    public Instant getStartedAt() {
        return startedAt;
    }

    public Instant getFinishedAt() {
        return finishedAt;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    /* === Builder ========================================================== */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {

        private UUID id;
        private UUID correlationId;
        private String sourceSystem;
        private JsonNode payloadBefore;
        private JsonNode payloadAfter;
        private String rulesApplied;
        private Status status = Status.IN_PROGRESS;
        private Instant startedAt = Instant.now();
        private Instant finishedAt;
        private String errorMessage;

        private Builder() {
        }

        public Builder id(UUID id) {
            this.id = id;
            return this;
        }

        public Builder correlationId(UUID correlationId) {
            this.correlationId = correlationId;
            return this;
        }

        public Builder sourceSystem(String sourceSystem) {
            this.sourceSystem = sourceSystem;
            return this;
        }

        public Builder payloadBefore(JsonNode payloadBefore) {
            this.payloadBefore = payloadBefore;
            return this;
        }

        public Builder status(Status status) {
            this.status = status;
            return this;
        }

        public AnonymizationAuditEvent build() {
            Objects.requireNonNull(correlationId, "correlationId must not be null");
            Objects.requireNonNull(sourceSystem, "sourceSystem must not be null");
            Objects.requireNonNull(payloadBefore, "payloadBefore must not be null");
            return new AnonymizationAuditEvent(this);
        }
    }

    /* === Enum ============================================================== */

    public enum Status {
        IN_PROGRESS,
        COMPLETED,
        FAILED
    }

    /* === JSON <-> String converter ======================================== */

    /**
     * Attribute converter that serializes {@link JsonNode} fields to PostgreSQL <code>jsonb</code>
     * and deserializes them transparently when the entity is hydrated.
     */
    public static class JsonNodeAttributeConverter implements AttributeConverter<JsonNode, String> {

        @Override
        public String convertToDatabaseColumn(JsonNode attribute) {
            if (attribute == null) {
                return null;
            }
            try {
                return OBJECT_MAPPER.writeValueAsString(attribute);
            } catch (JsonProcessingException e) {
                // Cannot throw checked exceptions from converter; wrap in runtime-exception
                throw new IllegalStateException("Unable to serialize JsonNode", e);
            }
        }

        @Override
        public JsonNode convertToEntityAttribute(String dbData) {
            if (dbData == null) {
                return null;
            }
            try {
                return OBJECT_MAPPER.readTree(dbData);
            } catch (JsonProcessingException e) {
                throw new IllegalStateException("Unable to deserialize JsonNode", e);
            }
        }
    }

    /* === equals / hashCode =============================================== */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof AnonymizationAuditEvent that)) return false;
        return id != null && id.equals(that.id);
    }

    @Override
    public int hashCode() {
        return 37;
    }
}