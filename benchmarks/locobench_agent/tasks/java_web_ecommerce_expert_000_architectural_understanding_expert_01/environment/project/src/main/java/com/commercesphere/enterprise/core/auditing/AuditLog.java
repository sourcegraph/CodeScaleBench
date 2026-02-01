package com.commercesphere.enterprise.core.auditing;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;

import javax.persistence.CascadeType;
import javax.persistence.Column;
import javax.persistence.Convert;
import javax.persistence.Entity;
import javax.persistence.EnumType;
import javax.persistence.Enumerated;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Lob;
import javax.persistence.PrePersist;
import javax.persistence.Table;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;
import java.io.IOException;
import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

/**
 * Entity representing a single immutable audit trail entry.
 *
 * <p>Each record captures who performed a given action, on what resource,
 * when it occurred, and additional JSON serialized context.  Every audit
 * trail is versioned via a correlation id, enabling distributed tracing
 * across clustered JVMs.</p>
 *
 * <p>The table should be configured with WRITE-AHEAD logging and reside on
 * hot storage to accommodate compliance-grade retrieval times.</p>
 */
@Entity
@Table(name = "audit_log")
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AuditLog implements Serializable {

    @Serial
    private static final long serialVersionUID = 1436624112437706506L;

    public enum Severity {
        INFO,
        WARN,
        ERROR,
        CRITICAL
    }

    // ---------------------------------------------------------------------
    // Persistent fields
    // ---------------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "audit_id")
    private Long id;

    @NotNull
    @Column(name = "event_timestamp", nullable = false, updatable = false)
    private Instant timestamp;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "severity", nullable = false, length = 10)
    private Severity severity;

    @NotBlank
    @Column(name = "principal", nullable = false, length = 128)
    private String principal;

    @NotBlank
    @Column(name = "action", nullable = false, length = 128)
    private String action;

    @NotBlank
    @Column(name = "resource_type", nullable = false, length = 128)
    private String resourceType;

    @NotBlank
    @Column(name = "resource_id", nullable = false, length = 128)
    private String resourceId;

    @Lob
    @Column(name = "details", columnDefinition = "TEXT")
    private String serializedDetails;

    @Column(name = "ip_address", length = 45)
    private String ipAddress;

    @NotNull
    @Column(name = "correlation_id", nullable = false, updatable = false, length = 36)
    private UUID correlationId;

    // ---------------------------------------------------------------------
    // Constructors
    // ---------------------------------------------------------------------

    protected AuditLog() {
        /* Required by JPA */
    }

    private AuditLog(Builder builder) {
        this.timestamp = builder.timestamp;
        this.severity = builder.severity;
        this.principal = builder.principal;
        this.action = builder.action;
        this.resourceType = builder.resourceType;
        this.resourceId = builder.resourceId;
        this.serializedDetails = builder.serializedDetails;
        this.ipAddress = builder.ipAddress;
        this.correlationId = builder.correlationId;
    }

    // ---------------------------------------------------------------------
    // Lifecycle hooks
    // ---------------------------------------------------------------------

    @PrePersist
    private void onPrePersist() {
        if (timestamp == null) {
            timestamp = Instant.now();
        }
        if (correlationId == null) {
            correlationId = UUID.randomUUID();
        }
    }

    // ---------------------------------------------------------------------
    // Getters
    // ---------------------------------------------------------------------

    public Long getId() {
        return id;
    }

    public Instant getTimestamp() {
        return timestamp;
    }

    public Severity getSeverity() {
        return severity;
    }

    public String getPrincipal() {
        return principal;
    }

    public String getAction() {
        return action;
    }

    public String getResourceType() {
        return resourceType;
    }

    public String getResourceId() {
        return resourceId;
    }

    /**
     * Returns the raw JSON details stored in the record.
     */
    @JsonProperty("details")
    public String getSerializedDetails() {
        return serializedDetails;
    }

    /**
     * Deserializes the details portion into the provided target class.
     *
     * @throws IllegalStateException if the JSON cannot be parsed
     */
    public <T> T getDetailsAs(Class<T> clazz) {
        if (serializedDetails == null) {
            return null;
        }
        try {
            return OBJECT_MAPPER.readValue(serializedDetails, clazz);
        } catch (IOException e) {
            throw new IllegalStateException(
                    "Failed to deserialize audit details to " + clazz.getSimpleName(), e);
        }
    }

    public String getIpAddress() {
        return ipAddress;
    }

    public UUID getCorrelationId() {
        return correlationId;
    }

    // ---------------------------------------------------------------------
    // Utility
    // ---------------------------------------------------------------------

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    @Override
    public int hashCode() {
        return Objects.hash(id, correlationId);
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof AuditLog other)) return false;
        return Objects.equals(id, other.id) &&
               Objects.equals(correlationId, other.correlationId);
    }

    @Override
    public String toString() {
        return "AuditLog{" +
               "id=" + id +
               ", timestamp=" + timestamp +
               ", severity=" + severity +
               ", principal='" + principal + '\'' +
               ", action='" + action + '\'' +
               ", resourceType='" + resourceType + '\'' +
               ", resourceId='" + resourceId + '\'' +
               ", ipAddress='" + ipAddress + '\'' +
               ", correlationId=" + correlationId +
               '}';
    }

    // ---------------------------------------------------------------------
    // Builder
    // ---------------------------------------------------------------------

    /**
     * Fluent builder for {@link AuditLog}.
     *
     * <pre>
     * AuditLog log = AuditLog.builder()
     *                        .principal("john.doe")
     *                        .action("CREATE_PRODUCT")
     *                        .resource("Product", "123")
     *                        .severity(Severity.INFO)
     *                        .details(productDto)
     *                        .ipAddress("192.168.10.2")
     *                        .build();
     * </pre>
     */
    public static class Builder {

        private Instant timestamp;
        private Severity severity = Severity.INFO;
        private String principal;
        private String action;
        private String resourceType;
        private String resourceId;
        private String serializedDetails;
        private String ipAddress;
        private UUID correlationId;

        private Builder() {
        }

        public Builder timestamp(Instant timestamp) {
            this.timestamp = timestamp;
            return this;
        }

        public Builder severity(Severity severity) {
            this.severity = Objects.requireNonNull(severity, "severity");
            return this;
        }

        public Builder principal(String principal) {
            this.principal = Objects.requireNonNull(principal, "principal");
            return this;
        }

        public Builder action(String action) {
            this.action = Objects.requireNonNull(action, "action");
            return this;
        }

        public Builder resource(String type, String id) {
            this.resourceType = Objects.requireNonNull(type, "resourceType");
            this.resourceId = Objects.requireNonNull(id, "resourceId");
            return this;
        }

        public Builder details(Object detailsObj) {
            try {
                this.serializedDetails = OBJECT_MAPPER.writeValueAsString(detailsObj);
            } catch (IOException e) {
                throw new IllegalArgumentException("Failed to serialize audit details object", e);
            }
            return this;
        }

        public Builder rawDetails(String json) {
            this.serializedDetails = json;
            return this;
        }

        public Builder ipAddress(String ipAddress) {
            this.ipAddress = ipAddress;
            return this;
        }

        public Builder correlationId(UUID correlationId) {
            this.correlationId = correlationId;
            return this;
        }

        public AuditLog build() {
            validateState();
            return new AuditLog(this);
        }

        private void validateState() {
            if (principal == null || principal.isBlank()) {
                throw new IllegalStateException("Principal must not be null/blank");
            }
            if (action == null || action.isBlank()) {
                throw new IllegalStateException("Action must not be null/blank");
            }
            if (resourceType == null || resourceType.isBlank()) {
                throw new IllegalStateException("Resource type must not be null/blank");
            }
            if (resourceId == null || resourceId.isBlank()) {
                throw new IllegalStateException("Resource id must not be null/blank");
            }
        }
    }

    public static Builder builder() {
        return new Builder();
    }
}