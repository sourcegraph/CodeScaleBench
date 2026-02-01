package com.opsforge.nexus.fileconverter.adapter.in.web.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;

import java.io.Serial;
import java.io.Serializable;
import java.net.URI;
import java.time.Instant;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;

/**
 * Data Transfer Object representing the outcome of a file–conversion request
 * as it is exposed over HTTP/GraphQL boundaries.
 *
 * <p>The DTO purposefully contains only primitives and
 * serialization-friendly types in order to remain stable
 * and technology-agnostic. Domain objects are mapped to this DTO in the
 * corresponding web adapter.</p>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
@Schema(name = "ConversionResult",
        description = "Represents the completed conversion metadata and download location.")
public final class ConversionResultDto implements Serializable {

    @Serial
    private static final long serialVersionUID = -4092314498405092640L;

    // ------------------------------------------------------------------ //
    // Core metadata                                                      //
    // ------------------------------------------------------------------ //

    @Schema(description = "Unique identifier for the conversion job.",
            example = "c27b79bc-23df-4ef8-82f7-0e9654c0a3e2",
            required = true)
    private final String conversionId;

    @Schema(description = "Original filename supplied by the client.",
            example = "annual-report.docx",
            required = true)
    private final String sourceFileName;

    @Schema(description = "Filename of the newly converted asset.",
            example = "annual-report.pdf",
            required = true)
    private final String targetFileName;

    @Schema(description = "Original file media-type / extension.",
            example = "docx",
            required = true)
    private final String sourceFormat;

    @Schema(description = "Target file media-type / extension.",
            example = "pdf",
            required = true)
    private final String targetFormat;

    @Schema(description = "Byte size of the original file.",
            example = "230144")
    private final long sourceSizeBytes;

    @Schema(description = "Byte size of the converted file.",
            example = "114688")
    private final long targetSizeBytes;

    @Schema(description = "UTC timestamp capturing when the conversion was requested.",
            example = "2024-05-29T15:42:57.406Z",
            required = true)
    private final Instant requestedAt;

    @Schema(description = "UTC timestamp capturing when the conversion finished.",
            example = "2024-05-29T15:42:58.821Z",
            required = true)
    private final Instant completedAt;

    // ------------------------------------------------------------------ //
    // Delivery & integrity                                               //
    // ------------------------------------------------------------------ //

    @Schema(description = "Direct, pre-signed URI to fetch the converted file.")
    private final URI downloadUri;

    @Schema(description = "Checksum (hex-encoded) for integrity verification.",
            example = "6c22100b35d6b1fa2f2c10a73b23144e")
    private final String checksum;

    // ------------------------------------------------------------------ //
    // Status                                                             //
    // ------------------------------------------------------------------ //

    @Schema(description = "Outcome status of the conversion job.", required = true)
    private final Status status;

    @Schema(description = "Optional high-level error message when status=FAILED.")
    private final String errorMessage;

    // ------------------------------------------------------------------ //
    // Additional/future-proof                                            //
    // ------------------------------------------------------------------ //

    @Schema(description = "Service-supplied metadata not part of the formal contract.")
    private final Map<String, String> additionalMetadata;

    /**
     * Status enumeration for a conversion operation.
     */
    public enum Status {
        SUCCESS,
        FAILED
    }

    // ------------------------------------------------------------------ //
    // Constructors                                                       //
    // ------------------------------------------------------------------ //

    private ConversionResultDto(Builder builder) {
        this.conversionId = builder.conversionId;
        this.sourceFileName = builder.sourceFileName;
        this.targetFileName = builder.targetFileName;
        this.sourceFormat = builder.sourceFormat;
        this.targetFormat = builder.targetFormat;
        this.sourceSizeBytes = builder.sourceSizeBytes;
        this.targetSizeBytes = builder.targetSizeBytes;
        this.requestedAt = builder.requestedAt;
        this.completedAt = builder.completedAt;
        this.downloadUri = builder.downloadUri;
        this.checksum = builder.checksum;
        this.status = builder.status;
        this.errorMessage = builder.errorMessage;
        this.additionalMetadata = builder.additionalMetadata == null
                ? Collections.emptyMap()
                : Collections.unmodifiableMap(builder.additionalMetadata);
    }

    // ------------------------------------------------------------------ //
    // Getters (Jackson serializes via getters unless @JsonProperty used) //
    // ------------------------------------------------------------------ //

    @JsonProperty("conversionId")
    public String getConversionId() {
        return conversionId;
    }

    @JsonProperty("sourceFileName")
    public String getSourceFileName() {
        return sourceFileName;
    }

    @JsonProperty("targetFileName")
    public String getTargetFileName() {
        return targetFileName;
    }

    @JsonProperty("sourceFormat")
    public String getSourceFormat() {
        return sourceFormat;
    }

    @JsonProperty("targetFormat")
    public String getTargetFormat() {
        return targetFormat;
    }

    @JsonProperty("sourceSizeBytes")
    public long getSourceSizeBytes() {
        return sourceSizeBytes;
    }

    @JsonProperty("targetSizeBytes")
    public long getTargetSizeBytes() {
        return targetSizeBytes;
    }

    @JsonProperty("requestedAt")
    public Instant getRequestedAt() {
        return requestedAt;
    }

    @JsonProperty("completedAt")
    public Instant getCompletedAt() {
        return completedAt;
    }

    @JsonProperty("downloadUri")
    public URI getDownloadUri() {
        return downloadUri;
    }

    @JsonProperty("checksum")
    public String getChecksum() {
        return checksum;
    }

    @JsonProperty("status")
    public Status getStatus() {
        return status;
    }

    @JsonProperty("errorMessage")
    public String getErrorMessage() {
        return errorMessage;
    }

    @JsonProperty("additionalMetadata")
    public Map<String, String> getAdditionalMetadata() {
        return additionalMetadata;
    }

    // ------------------------------------------------------------------ //
    // Builder                                                            //
    // ------------------------------------------------------------------ //

    /**
     * Creates a new builder instance.
     */
    public static Builder builder() {
        return new Builder();
    }

    /**
     * Fluent builder for {@link ConversionResultDto}.
     */
    public static final class Builder {

        private String conversionId;
        private String sourceFileName;
        private String targetFileName;
        private String sourceFormat;
        private String targetFormat;
        private long sourceSizeBytes;
        private long targetSizeBytes;
        private Instant requestedAt;
        private Instant completedAt;
        private URI downloadUri;
        private String checksum;
        private Status status;
        private String errorMessage;
        private Map<String, String> additionalMetadata;

        private Builder() {
        }

        public Builder conversionId(String conversionId) {
            this.conversionId = conversionId;
            return this;
        }

        public Builder sourceFileName(String sourceFileName) {
            this.sourceFileName = sourceFileName;
            return this;
        }

        public Builder targetFileName(String targetFileName) {
            this.targetFileName = targetFileName;
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

        public Builder sourceSizeBytes(long sourceSizeBytes) {
            this.sourceSizeBytes = sourceSizeBytes;
            return this;
        }

        public Builder targetSizeBytes(long targetSizeBytes) {
            this.targetSizeBytes = targetSizeBytes;
            return this;
        }

        public Builder requestedAt(Instant requestedAt) {
            this.requestedAt = requestedAt;
            return this;
        }

        public Builder completedAt(Instant completedAt) {
            this.completedAt = completedAt;
            return this;
        }

        public Builder downloadUri(URI downloadUri) {
            this.downloadUri = downloadUri;
            return this;
        }

        public Builder checksum(String checksum) {
            this.checksum = checksum;
            return this;
        }

        public Builder status(Status status) {
            this.status = status;
            return this;
        }

        public Builder errorMessage(String errorMessage) {
            this.errorMessage = errorMessage;
            return this;
        }

        public Builder additionalMetadata(Map<String, String> additionalMetadata) {
            this.additionalMetadata = additionalMetadata;
            return this;
        }

        /**
         * Builds the DTO after performing basic validation.
         *
         * @throws IllegalStateException if required fields are missing.
         */
        public ConversionResultDto build() {
            validate();
            return new ConversionResultDto(this);
        }

        private void validate() {
            String missing = "";

            if (conversionId == null) missing += "conversionId, ";
            if (sourceFileName == null) missing += "sourceFileName, ";
            if (targetFileName == null) missing += "targetFileName, ";
            if (sourceFormat == null) missing += "sourceFormat, ";
            if (targetFormat == null) missing += "targetFormat, ";
            if (requestedAt == null) missing += "requestedAt, ";
            if (completedAt == null) missing += "completedAt, ";
            if (status == null) missing += "status, ";

            if (!missing.isEmpty()) {
                throw new IllegalStateException(
                        "Cannot build ConversionResultDto, missing required fields: "
                                + missing.substring(0, missing.length() - 2));
            }

            if (status == Status.FAILED && (errorMessage == null || errorMessage.isBlank())) {
                throw new IllegalStateException(
                        "errorMessage must be provided when status=FAILED");
            }
        }
    }

    // ------------------------------------------------------------------ //
    // equals / hashCode / toString                                       //
    // ------------------------------------------------------------------ //

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ConversionResultDto that)) return false;
        return sourceSizeBytes == that.sourceSizeBytes
                && targetSizeBytes == that.targetSizeBytes
                && Objects.equals(conversionId, that.conversionId)
                && Objects.equals(sourceFileName, that.sourceFileName)
                && Objects.equals(targetFileName, that.targetFileName)
                && Objects.equals(sourceFormat, that.sourceFormat)
                && Objects.equals(targetFormat, that.targetFormat)
                && Objects.equals(requestedAt, that.requestedAt)
                && Objects.equals(completedAt, that.completedAt)
                && Objects.equals(downloadUri, that.downloadUri)
                && Objects.equals(checksum, that.checksum)
                && status == that.status
                && Objects.equals(errorMessage, that.errorMessage)
                && Objects.equals(additionalMetadata, that.additionalMetadata);
    }

    @Override
    public int hashCode() {
        return Objects.hash(conversionId, sourceFileName, targetFileName, sourceFormat,
                targetFormat, sourceSizeBytes, targetSizeBytes, requestedAt, completedAt,
                downloadUri, checksum, status, errorMessage, additionalMetadata);
    }

    @Override
    public String toString() {
        return "ConversionResultDto{" +
                "conversionId='" + conversionId + '\'' +
                ", sourceFileName='" + sourceFileName + '\'' +
                ", targetFileName='" + targetFileName + '\'' +
                ", sourceFormat='" + sourceFormat + '\'' +
                ", targetFormat='" + targetFormat + '\'' +
                ", sourceSizeBytes=" + sourceSizeBytes +
                ", targetSizeBytes=" + targetSizeBytes +
                ", requestedAt=" + requestedAt +
                ", completedAt=" + completedAt +
                ", downloadUri=" + downloadUri +
                ", checksum='" + checksum + '\'' +
                ", status=" + status +
                ", errorMessage='" + errorMessage + '\'' +
                ", additionalMetadata=" + additionalMetadata +
                '}';
    }
}