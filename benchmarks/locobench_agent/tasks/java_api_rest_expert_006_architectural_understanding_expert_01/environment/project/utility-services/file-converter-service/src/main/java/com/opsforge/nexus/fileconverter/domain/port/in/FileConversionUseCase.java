package com.opsforge.nexus.fileconverter.domain.port.in;

import java.nio.ByteBuffer;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Incoming (primary) port that describes the use-cases the File Converter domain
 * exposes to the outside world (e.g. REST controllers, GraphQL resolvers,
 * asynchronous message listeners). <p>
 *
 * The interface is intentionally technology-agnostic and free of any framework
 * dependencies so that the core domain remains portable and fully testable.
 *
 * Implementations live in the {@code application} layer and are wired to
 * outbound ports (secondary adapters) that perform the actual I/O work, such as
 * reading the source file from a blob store or delegating the conversion to an
 * external SaaS.
 */
public interface FileConversionUseCase {

    /**
     * Creates a new conversion job. Depending on the implementation this call
     * may be synchronous or queue an asynchronous background task.
     *
     * @param command immutable command that carries all data required to start
     *                a conversion
     * @return unique immutable {@link ConversionJobId}
     * @throws UnsupportedFileFormatException when either source or target
     *                                        format is not supported by the
     *                                        current deployment
     */
    ConversionJobId submitConversion(ConvertFileCommand command)
            throws UnsupportedFileFormatException;

    /**
     * Returns the current status of a conversion job.
     *
     * @param jobId unique job identifier as returned by
     *              {@link #submitConversion(ConvertFileCommand)}
     * @return {@link ConversionSnapshot} carrying status and additional metadata
     * @throws JobNotFoundException when the job cannot be located
     */
    ConversionSnapshot queryStatus(ConversionJobId jobId) throws JobNotFoundException;

    /**
     * Retrieves the converted payload as a binary buffer <strong>if and only
     * if</strong> the job has successfully completed. Implementations may
     * decide to stream large files; this simplified interface suffices for most
     * cases.
     *
     * @param jobId unique identifier of a completed job
     * @return optional containing the payload or empty when the job is not yet
     *         finished
     * @throws JobNotFoundException               when the job cannot be located
     * @throws ConversionFailedException          when the job finished in
     *                                            {@link ConversionStatus#FAILED}
     * @throws UnsupportedRetrievalStateException when the job is not in a state
     *                                            that allows retrieval
     */
    Optional<ByteBuffer> fetchConvertedPayload(ConversionJobId jobId)
            throws JobNotFoundException,
                   ConversionFailedException,
                   UnsupportedRetrievalStateException;

    /**
     * Attempts to cancel an in-flight conversion. A best-effort operation;
     * implementations must guarantee idempotency.
     *
     * @param jobId job to cancel
     * @throws JobNotFoundException            when the job cannot be located
     * @throws ConversionAlreadyCompletedException when the job is already in a
     *                                            terminal state
     */
    void cancelConversion(ConversionJobId jobId)
            throws JobNotFoundException, ConversionAlreadyCompletedException;
}

/* ========================================================================== */
/* ===============================  Commands  =============================== */
/* ========================================================================== */

/**
 * Immutable command object that starts a new conversion. Acts as the formal
 * boundary between primary adapters and the application service.
 */
final class ConvertFileCommand {

    private final Path sourcePath;
    private final FileFormat sourceFormat;
    private final FileFormat targetFormat;
    private final Map<String, String> metadata; // arbitrary key-value data

    private ConvertFileCommand(Builder builder) {
        this.sourcePath   = builder.sourcePath;
        this.sourceFormat = builder.sourceFormat;
        this.targetFormat = builder.targetFormat;
        this.metadata     = Collections.unmodifiableMap(builder.metadata);
    }

    public Path getSourcePath() {
        return sourcePath;
    }

    public FileFormat getSourceFormat() {
        return sourceFormat;
    }

    public FileFormat getTargetFormat() {
        return targetFormat;
    }

    public Map<String, String> getMetadata() {
        return metadata;
    }

    /* --------------------------  Builder pattern  -------------------------- */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private Path sourcePath;
        private FileFormat sourceFormat;
        private FileFormat targetFormat;
        private Map<String, String> metadata = Collections.emptyMap();

        private Builder() {
        }

        public Builder sourcePath(Path sourcePath) {
            this.sourcePath = sourcePath;
            return this;
        }

        public Builder sourceFormat(FileFormat sourceFormat) {
            this.sourceFormat = sourceFormat;
            return this;
        }

        public Builder targetFormat(FileFormat targetFormat) {
            this.targetFormat = targetFormat;
            return this;
        }

        public Builder metadata(Map<String, String> metadata) {
            this.metadata = metadata == null ? Collections.emptyMap() : metadata;
            return this;
        }

        public ConvertFileCommand build() {
            Objects.requireNonNull(sourcePath,   "sourcePath must not be null");
            Objects.requireNonNull(sourceFormat, "sourceFormat must not be null");
            Objects.requireNonNull(targetFormat, "targetFormat must not be null");
            return new ConvertFileCommand(this);
        }
    }
}

/* ========================================================================== */
/* ==============================  Value Objects  =========================== */
/* ========================================================================== */

/**
 * Value object that uniquely identifies a conversion job across the system.
 */
final class ConversionJobId {

    private final UUID value;

    private ConversionJobId(UUID value) {
        this.value = value;
    }

    public static ConversionJobId random() {
        return new ConversionJobId(UUID.randomUUID());
    }

    public static ConversionJobId of(UUID value) {
        return new ConversionJobId(value);
    }

    public UUID getValue() {
        return value;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ConversionJobId)) return false;
        ConversionJobId that = (ConversionJobId) o;
        return value.equals(that.value);
    }

    @Override
    public int hashCode() {
        return value.hashCode();
    }

    @Override
    public String toString() {
        return value.toString();
    }
}

/**
 * Immutable snapshot that represents the current state of a conversion job.
 */
final class ConversionSnapshot {

    private final ConversionJobId jobId;
    private final ConversionStatus status;
    private final Instant createdAt;
    private final Instant lastUpdatedAt;
    private final String failureReason;

    private ConversionSnapshot(Builder builder) {
        this.jobId         = builder.jobId;
        this.status        = builder.status;
        this.createdAt     = builder.createdAt;
        this.lastUpdatedAt = builder.lastUpdatedAt;
        this.failureReason = builder.failureReason;
    }

    public ConversionJobId getJobId() {
        return jobId;
    }

    public ConversionStatus getStatus() {
        return status;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getLastUpdatedAt() {
        return lastUpdatedAt;
    }

    public Optional<String> getFailureReason() {
        return Optional.ofNullable(failureReason);
    }

    /* --------------------------  Builder pattern  -------------------------- */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private ConversionJobId jobId;
        private ConversionStatus status;
        private Instant createdAt;
        private Instant lastUpdatedAt;
        private String failureReason;

        private Builder() {
        }

        public Builder jobId(ConversionJobId jobId) {
            this.jobId = jobId;
            return this;
        }

        public Builder status(ConversionStatus status) {
            this.status = status;
            return this;
        }

        public Builder createdAt(Instant createdAt) {
            this.createdAt = createdAt;
            return this;
        }

        public Builder lastUpdatedAt(Instant lastUpdatedAt) {
            this.lastUpdatedAt = lastUpdatedAt;
            return this;
        }

        public Builder failureReason(String failureReason) {
            this.failureReason = failureReason;
            return this;
        }

        public ConversionSnapshot build() {
            Objects.requireNonNull(jobId,     "jobId must not be null");
            Objects.requireNonNull(status,    "status must not be null");
            Objects.requireNonNull(createdAt, "createdAt must not be null");
            return new ConversionSnapshot(this);
        }
    }
}

/**
 * Enumerates all file formats currently understood by the system. New formats
 * can be added without impacting persisted state as they map to their string
 * names.
 */
enum FileFormat {
    PDF,
    DOC,
    DOCX,
    XLS,
    XLSX,
    PPT,
    PPTX,
    CSV,
    JSON,
    XML,
    YAML,
    MARKDOWN,
    TXT
}

/**
 * Domain-level job status. Only {@link #COMPLETED} guarantees that the payload
 * can be fetched via {@link FileConversionUseCase#fetchConvertedPayload}.
 */
enum ConversionStatus {
    PENDING,        // job is queued but not yet picked up
    PROCESSING,     // actively being converted
    COMPLETED,      // converted successfully
    FAILED,         // terminal state – see failureReason
    CANCELLED       // terminal state – cancelled by client or system
}

/* ========================================================================== */
/* ============================  Error Handling  ============================ */
/* ========================================================================== */

/**
 * Marker interface for all domain-level exceptions thrown by the File
 * Converter. Allows API layer to implement a uniform exception mapper.
 */
interface FileConverterException {
}

/* ---------------------------  Domain exceptions  -------------------------- */

class UnsupportedFileFormatException extends RuntimeException implements FileConverterException {
    public UnsupportedFileFormatException(String message) {
        super(message);
    }
}

class JobNotFoundException extends RuntimeException implements FileConverterException {
    public JobNotFoundException(ConversionJobId jobId) {
        super("Conversion job not found: " + jobId);
    }
}

class ConversionFailedException extends RuntimeException implements FileConverterException {
    public ConversionFailedException(ConversionJobId jobId, String reason) {
        super("Conversion job " + jobId + " failed: " + reason);
    }
}

class UnsupportedRetrievalStateException extends RuntimeException implements FileConverterException {
    public UnsupportedRetrievalStateException(ConversionJobId jobId, ConversionStatus status) {
        super("Cannot retrieve payload for job " + jobId + " in state " + status);
    }
}

class ConversionAlreadyCompletedException extends RuntimeException implements FileConverterException {
    public ConversionAlreadyCompletedException(ConversionJobId jobId) {
        super("Conversion job " + jobId + " is already completed and immutable");
    }
}