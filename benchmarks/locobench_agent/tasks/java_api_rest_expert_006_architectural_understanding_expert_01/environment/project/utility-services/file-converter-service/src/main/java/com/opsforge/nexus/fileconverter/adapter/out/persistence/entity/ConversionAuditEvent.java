package com.opsforge.nexus.fileconverter.adapter.out.persistence.entity;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;

import org.hibernate.annotations.GenericGenerator;
import org.hibernate.annotations.Type;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import com.opsforge.nexus.fileconverter.domain.model.ConversionStatus;

/**
 * JPA entity representing an audit event for a file-conversion operation.
 * <p>
 * This model is part of the persistence adapter layer and should never be
 * exposed to callers outside of this package.  The domain-layer aggregate
 * should be used instead.  This entity merely reflects the table schema and
 * participates in Spring-Data JPA auditing.
 */
@Entity
@Table(
        name = "conversion_audit_events",
        indexes = {
                @Index(name = "idx_conv_audit_correlation", columnList = "correlation_id"),
                @Index(name = "idx_conv_audit_created_at", columnList = "created_at")
        }
)
@EntityListeners(AuditingEntityListener.class)
public class ConversionAuditEvent {

    /* ---------- Primary Key ---------- */

    @Id
    @GeneratedValue(generator = "uuid2")
    @GenericGenerator(name = "uuid2", strategy = "org.hibernate.id.UUIDGenerator")
    @Column(name = "id", nullable = false, updatable = false, columnDefinition = "uuid")
    private UUID id;

    /* ---------- Domain Data ---------- */

    /** A caller-supplied correlation identifier that ties a conversion to an external workflow. */
    @NotBlank
    @Column(name = "correlation_id", nullable = false, length = 64, updatable = false)
    private String correlationId;

    /** The MIME/extension of the source file that was converted (e.g. {@code text/csv}). */
    @NotBlank
    @Column(name = "source_format", nullable = false, length = 64, updatable = false)
    private String sourceFormat;

    /** The MIME/extension of the target file (e.g. {@code application/pdf}). */
    @NotBlank
    @Column(name = "target_format", nullable = false, length = 64, updatable = false)
    private String targetFormat;

    /** Final status of the conversion. */
    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private ConversionStatus status;

    /** Optional human-readable error message when the conversion failed. */
    @Lob
    @Column(name = "error_message")
    private String errorMessage;

    /** Original file name including extension. */
    @NotBlank
    @Column(name = "input_file_name", nullable = false, length = 256, updatable = false)
    private String inputFileName;

    /** Resulting file name including extension, if generation succeeded. */
    @Column(name = "output_file_name", length = 256)
    private String outputFileName;

    /** Size of the input file in bytes. */
    @PositiveOrZero
    @Column(name = "file_size_in_bytes")
    private long fileSizeInBytes;

    /** Processing time spent in the converter, expressed in milliseconds. */
    @PositiveOrZero
    @Column(name = "duration_in_ms")
    private long durationInMs;

    /* ---------- Auditing ---------- */

    @CreatedDate
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @LastModifiedDate
    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    /* ---------- Optimistic Locking ---------- */

    @Version
    private long version;

    /* ---------- Constructors ---------- */

    /** Required by JPA.  Use the {@link Builder} to create new instances. */
    protected ConversionAuditEvent() {
        // JPA only
    }

    private ConversionAuditEvent(Builder builder) {
        this.correlationId   = builder.correlationId;
        this.sourceFormat    = builder.sourceFormat;
        this.targetFormat    = builder.targetFormat;
        this.status          = Objects.requireNonNull(builder.status, "status must not be null");
        this.errorMessage    = builder.errorMessage;
        this.inputFileName   = builder.inputFileName;
        this.outputFileName  = builder.outputFileName;
        this.fileSizeInBytes = builder.fileSizeInBytes;
        this.durationInMs    = builder.durationInMs;
    }

    /* ---------- Getters ---------- */

    public UUID getId() {
        return id;
    }

    public String getCorrelationId() {
        return correlationId;
    }

    public String getSourceFormat() {
        return sourceFormat;
    }

    public String getTargetFormat() {
        return targetFormat;
    }

    public ConversionStatus getStatus() {
        return status;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public String getInputFileName() {
        return inputFileName;
    }

    public String getOutputFileName() {
        return outputFileName;
    }

    public long getFileSizeInBytes() {
        return fileSizeInBytes;
    }

    public long getDurationInMs() {
        return durationInMs;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public long getVersion() {
        return version;
    }

    /* ---------- Utilities ---------- */

    @Override
    public String toString() {
        return "ConversionAuditEvent{" +
               "id=" + id +
               ", correlationId='" + correlationId + '\'' +
               ", sourceFormat='" + sourceFormat + '\'' +
               ", targetFormat='" + targetFormat + '\'' +
               ", status=" + status +
               ", inputFileName='" + inputFileName + '\'' +
               ", outputFileName='" + outputFileName + '\'' +
               ", fileSizeInBytes=" + fileSizeInBytes +
               ", durationInMs=" + durationInMs +
               ", createdAt=" + createdAt +
               '}';
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ConversionAuditEvent)) return false;
        ConversionAuditEvent that = (ConversionAuditEvent) o;
        return Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return Objects.hashCode(id);
    }

    /* ---------- Builder ---------- */

    /**
     * Fluent builder used by the persistence adapter to construct an audit event
     * from a domain aggregate.  The builder selectively exposes mutators because
     * the JPA entity itself is immutable from the outside.
     */
    public static final class Builder {

        private String           correlationId;
        private String           sourceFormat;
        private String           targetFormat;
        private ConversionStatus status;
        private String           errorMessage;
        private String           inputFileName;
        private String           outputFileName;
        private long             fileSizeInBytes;
        private long             durationInMs;

        public Builder correlationId(String correlationId) {
            this.correlationId = correlationId;
            return this;
        }

        public Builder sourceFormat(String sourceFormat) {
            this.sourceFormat = sourceFormat;
            return this;
        }

        public Builder targetFormat(String targetFormat) {
            this.targetFormat = targetFormat;
            return this;
        }

        public Builder status(ConversionStatus status) {
            this.status = status;
            return this;
        }

        public Builder errorMessage(String errorMessage) {
            this.errorMessage = errorMessage;
            return this;
        }

        public Builder inputFileName(String inputFileName) {
            this.inputFileName = inputFileName;
            return this;
        }

        public Builder outputFileName(String outputFileName) {
            this.outputFileName = outputFileName;
            return this;
        }

        public Builder fileSizeInBytes(long fileSizeInBytes) {
            this.fileSizeInBytes = fileSizeInBytes;
            return this;
        }

        public Builder durationInMs(long durationInMs) {
            this.durationInMs = durationInMs;
            return this;
        }

        public ConversionAuditEvent build() {
            return new ConversionAuditEvent(this);
        }
    }
}