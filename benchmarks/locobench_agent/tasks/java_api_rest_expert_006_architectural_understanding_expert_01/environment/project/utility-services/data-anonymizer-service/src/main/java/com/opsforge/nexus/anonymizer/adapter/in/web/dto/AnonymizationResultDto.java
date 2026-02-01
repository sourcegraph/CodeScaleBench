package com.opsforge.nexus.anonymizer.adapter.in.web.dto;

import java.net.URI;
import java.time.Duration;
import java.time.Instant;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;

/**
 * Immutable representation of the REST payload returned to clients once an
 * anonymization job has finished (either synchronously or asynchronously).
 *
 * <p>The DTO is intentionally decoupled from the underlying domain model
 * (hexagonal architecture) so that internal refactorings do not ripple into
 * the public contract.  Only primitives and other DTOs are exposed.</p>
 *
 * <p>Whenever you extend this DTO, remember to bump the media-type version
 * in the corresponding controller and update the OpenAPI definition.</p>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
@Schema(name = "AnonymizationResult",
        description = "Result metadata produced by the Data Anonymizer utility.")
public final class AnonymizationResultDto {

    @Schema(description = "Opaque identifier of the anonymization job.",
            example = "9e66b1c8-46cb-442f-b488-e9b206a89605")
    private final String jobId;

    @Schema(description = "Original filename as supplied by the caller.",
            example = "customers.csv")
    private final String originalFilename;

    @Schema(description = "Filename of the anonymized artifact stored in the object store.",
            example = "customers-anon.csv")
    private final String anonymizedFilename;

    @Schema(description = "Public, time-boxed URI that can be used to download the anonymized file.")
    private final URI downloadUri;

    @Schema(description = "SHA-256 checksum of the anonymized artifact, hex-encoded.",
            example = "1436f1747deb5e6f57661620fbf84ecc8c8b7c6f62f015c1b2e3d3e2e6c4fb4")
    private final String sha256;

    @Schema(description = "Timestamp (UTC) when processing started, in ISO-8601.",
            example = "2024-02-21T10:15:30.00Z")
    private final Instant startedAt;

    @Schema(description = "Timestamp (UTC) when processing finished, in ISO-8601.",
            example = "2024-02-21T10:15:35.12Z")
    private final Instant completedAt;

    @Schema(description = "Processing duration in milliseconds.",
            example = "5123")
    private final long durationMillis;

    @Schema(description = "Total number of records scanned in the source file.",
            example = "200000")
    private final long totalRecords;

    @Schema(description = "Number of records that required anonymization.",
            example = "198745")
    private final long anonymizedRecords;

    @Schema(description = "Per-column anonymization statistics. Key = column name, Value = occurrences.",
            example = "{\"ssn\": 198745, \"email\": 198000}")
    private final Map<String, Long> fieldStatistics;

    /* --------------------------------------------------------------------- */
    /* Constructor & Builder                                                 */
    /* --------------------------------------------------------------------- */

    private AnonymizationResultDto(Builder builder) {
        this.jobId = builder.jobId;
        this.originalFilename = builder.originalFilename;
        this.anonymizedFilename = builder.anonymizedFilename;
        this.downloadUri = builder.downloadUri;
        this.sha256 = builder.sha256;
        this.startedAt = builder.startedAt;
        this.completedAt = builder.completedAt;
        this.durationMillis = builder.durationMillis;
        this.totalRecords = builder.totalRecords;
        this.anonymizedRecords = builder.anonymizedRecords;
        this.fieldStatistics = builder.fieldStatistics == null
                ? Collections.emptyMap()
                : Collections.unmodifiableMap(builder.fieldStatistics);
    }

    public static Builder builder() {
        return new Builder();
    }

    /* --------------------------------------------------------------------- */
    /* Accessors                                                             */
    /* --------------------------------------------------------------------- */

    @JsonProperty("jobId")
    public String getJobId() {
        return jobId;
    }

    @JsonProperty("originalFilename")
    public String getOriginalFilename() {
        return originalFilename;
    }

    @JsonProperty("anonymizedFilename")
    public String getAnonymizedFilename() {
        return anonymizedFilename;
    }

    @JsonProperty("downloadUri")
    public URI getDownloadUri() {
        return downloadUri;
    }

    @JsonProperty("sha256")
    public String getSha256() {
        return sha256;
    }

    @JsonProperty("startedAt")
    public Instant getStartedAt() {
        return startedAt;
    }

    @JsonProperty("completedAt")
    public Instant getCompletedAt() {
        return completedAt;
    }

    @JsonProperty("durationMillis")
    public long getDurationMillis() {
        return durationMillis;
    }

    @JsonProperty("totalRecords")
    public long getTotalRecords() {
        return totalRecords;
    }

    @JsonProperty("anonymizedRecords")
    public long getAnonymizedRecords() {
        return anonymizedRecords;
    }

    @JsonProperty("fieldStatistics")
    public Map<String, Long> getFieldStatistics() {
        return fieldStatistics;
    }

    /* --------------------------------------------------------------------- */
    /* Builder implementation                                                */
    /* --------------------------------------------------------------------- */

    public static final class Builder {
        private String jobId;
        private String originalFilename;
        private String anonymizedFilename;
        private URI downloadUri;
        private String sha256;
        private Instant startedAt;
        private Instant completedAt;
        private long durationMillis;
        private long totalRecords;
        private long anonymizedRecords;
        private Map<String, Long> fieldStatistics;

        private Builder() {
            // hidden
        }

        public Builder jobId(String jobId) {
            this.jobId = jobId;
            return this;
        }

        public Builder originalFilename(String originalFilename) {
            this.originalFilename = originalFilename;
            return this;
        }

        public Builder anonymizedFilename(String anonymizedFilename) {
            this.anonymizedFilename = anonymizedFilename;
            return this;
        }

        public Builder downloadUri(URI downloadUri) {
            this.downloadUri = downloadUri;
            return this;
        }

        public Builder sha256(String sha256) {
            this.sha256 = sha256;
            return this;
        }

        public Builder startedAt(Instant startedAt) {
            this.startedAt = startedAt;
            return this;
        }

        public Builder completedAt(Instant completedAt) {
            this.completedAt = completedAt;
            return this;
        }

        public Builder fieldStatistics(Map<String, Long> fieldStatistics) {
            this.fieldStatistics = fieldStatistics;
            return this;
        }

        public Builder totalRecords(long totalRecords) {
            this.totalRecords = totalRecords;
            return this;
        }

        public Builder anonymizedRecords(long anonymizedRecords) {
            this.anonymizedRecords = anonymizedRecords;
            return this;
        }

        public AnonymizationResultDto build() {
            validate();
            calculateDurationIfNecessary();
            return new AnonymizationResultDto(this);
        }

        /* ------------------------- private helpers ----------------------- */

        private void validate() {
            Objects.requireNonNull(jobId, "jobId must not be null");
            Objects.requireNonNull(originalFilename, "originalFilename must not be null");
            Objects.requireNonNull(anonymizedFilename, "anonymizedFilename must not be null");
            Objects.requireNonNull(downloadUri, "downloadUri must not be null");
            Objects.requireNonNull(sha256, "sha256 must not be null");
            Objects.requireNonNull(startedAt, "startedAt must not be null");
            Objects.requireNonNull(completedAt, "completedAt must not be null");

            if (startedAt.isAfter(completedAt)) {
                throw new IllegalStateException("startedAt must be before completedAt");
            }
            if (totalRecords < 0 || anonymizedRecords < 0) {
                throw new IllegalArgumentException("Record counts cannot be negative");
            }
            if (anonymizedRecords > totalRecords) {
                throw new IllegalArgumentException("anonymizedRecords cannot be greater than totalRecords");
            }
        }

        private void calculateDurationIfNecessary() {
            if (durationMillis <= 0) {
                this.durationMillis = Duration.between(startedAt, completedAt).toMillis();
            }
        }
    }
}