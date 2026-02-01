package com.opsforge.nexus.fileconverter.adapter.in.web.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.io.Serial;
import java.io.Serializable;
import java.net.URI;
import java.util.Base64;
import java.util.Objects;

/**
 * DTO that represents an inbound request to convert a file from one format to another.
 * <p>
 * This class is placed in the “web adapter” layer (hexagonal architecture) and has
 * zero knowledge about internal domain concepts.  It should be mapped to a domain
 * command object inside a dedicated mapper component located in adapter ↔︎ application
 * boundary.
 *
 * Validation annotations ensure that—before any business code is invoked—the request
 * is structurally sane.  Cross-field constraints are expressed via {@link AssertTrue}
 * methods so that Jakarta Bean Validation (JSR 380) can apply them automatically.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class ConversionRequestDto implements Serializable {

    @Serial
    private static final long serialVersionUID = 1L;

    /**
     * Original file format (e.g. “pdf”, “csv”, “docx”).
     */
    @NotBlank(message = "sourceFormat must be provided")
    @Size(max = 20, message = "sourceFormat must be at most 20 characters")
    @Pattern(regexp = "^[A-Za-z0-9]+$", message = "sourceFormat may only contain alphanumeric characters")
    private final String sourceFormat;

    /**
     * Desired file format after conversion.
     */
    @NotBlank(message = "targetFormat must be provided")
    @Size(max = 20, message = "targetFormat must be at most 20 characters")
    @Pattern(regexp = "^[A-Za-z0-9]+$", message = "targetFormat may only contain alphanumeric characters")
    private final String targetFormat;

    /**
     * File content encoded as Base64.  A dedicated multipart endpoint exists for
     * large binary payloads—in this inline request variant we enforce a size limit.
     */
    @NotBlank(message = "payload must be provided")
    @Size(max = 10_000_000, message = "payload is too large") // 10 MB in Base64 form
    private final String base64Payload;

    /**
     * Whether the caller prefers asynchronous processing.  When {@code true}
     * {@link #callbackUrl} becomes mandatory.
     */
    private final boolean async;

    /**
     * URL that will be invoked (HTTP POST) once conversion is finished.  Required
     * for async processing, ignored otherwise.
     */
    private final URI callbackUrl;

    /**
     * Algorithm used to create an optional checksum of the original payload
     * (e.g. “SHA-256”).  Helps the server to detect payload corruption early.
     */
    @Size(max = 15, message = "checksumAlgorithm must be at most 15 characters")
    private final String checksumAlgorithm;

    /**
     * Correlation identifier supplied by the caller for distributed tracing.
     */
    @Size(max = 100, message = "correlationId must be at most 100 characters")
    private final String correlationId;

    /**
     * Processing priority.  HIGH-priority jobs might take precedence in internal
     * queues.  Defaults to NORMAL.
     */
    @NotNull
    private final Priority priority;

    @JsonCreator
    public ConversionRequestDto(
            @JsonProperty("sourceFormat") String sourceFormat,
            @JsonProperty("targetFormat") String targetFormat,
            @JsonProperty("payload") String base64Payload,
            @JsonProperty("async") Boolean async,
            @JsonProperty("callbackUrl") URI callbackUrl,
            @JsonProperty("checksumAlgorithm") String checksumAlgorithm,
            @JsonProperty("correlationId") String correlationId,
            @JsonProperty("priority") Priority priority) {

        // Jackson may pass null for primitives if they are boxed types; provide safe defaults
        this.sourceFormat = sourceFormat;
        this.targetFormat = targetFormat;
        this.base64Payload = base64Payload;
        this.async = Boolean.TRUE.equals(async);
        this.callbackUrl = callbackUrl;
        this.checksumAlgorithm = checksumAlgorithm;
        this.correlationId = correlationId;
        this.priority = priority == null ? Priority.NORMAL : priority;
    }

    /* ------------------------------------------------------------------
     * Cross-field validation section
     * ------------------------------------------------------------------ */

    @AssertTrue(message = "callbackUrl must be provided when async=true")
    @SuppressWarnings("unused") // Invoked by Bean Validation at runtime
    private boolean isCallbackUrlPresentForAsync() {
        return !async || callbackUrl != null;
    }

    @AssertTrue(message = "payload is not valid Base64")
    @SuppressWarnings("unused")
    private boolean isPayloadValidBase64() {
        try {
            // Do not allocate huge memory; just attempt to decode a few bytes
            Base64.getDecoder().decode(base64Payload);
            return true;
        } catch (IllegalArgumentException ex) {
            return false;
        }
    }

    /* ------------------------------------------------------------------
     * Accessors
     * ------------------------------------------------------------------ */

    public String getSourceFormat() {
        return sourceFormat;
    }

    public String getTargetFormat() {
        return targetFormat;
    }

    /**
     * Returns the Base64 encoded payload.
     */
    public String getBase64Payload() {
        return base64Payload;
    }

    public boolean isAsync() {
        return async;
    }

    public URI getCallbackUrl() {
        return callbackUrl;
    }

    public String getChecksumAlgorithm() {
        return checksumAlgorithm;
    }

    public String getCorrelationId() {
        return correlationId;
    }

    public Priority getPriority() {
        return priority;
    }

    /* ------------------------------------------------------------------
     * Utility / builder
     * ------------------------------------------------------------------ */

    /**
     * Produces a mutable builder pre-populated with this DTO’s values.
     */
    public Builder toBuilder() {
        return new Builder()
                .sourceFormat(sourceFormat)
                .targetFormat(targetFormat)
                .payload(base64Payload)
                .async(async)
                .callbackUrl(callbackUrl)
                .checksumAlgorithm(checksumAlgorithm)
                .correlationId(correlationId)
                .priority(priority);
    }

    /**
     * Fluent builder for {@link ConversionRequestDto}.  Useful in tests and
     * when constructing DTOs from non-JSON sources (e.g. GraphQL).
     */
    public static final class Builder {
        private String sourceFormat;
        private String targetFormat;
        private String payload;
        private boolean async;
        private URI callbackUrl;
        private String checksumAlgorithm;
        private String correlationId;
        private Priority priority = Priority.NORMAL;

        public Builder sourceFormat(String sourceFormat) {
            this.sourceFormat = sourceFormat;
            return this;
        }

        public Builder targetFormat(String targetFormat) {
            this.targetFormat = targetFormat;
            return this;
        }

        public Builder payload(String payload) {
            this.payload = payload;
            return this;
        }

        public Builder async(boolean async) {
            this.async = async;
            return this;
        }

        public Builder callbackUrl(URI callbackUrl) {
            this.callbackUrl = callbackUrl;
            return this;
        }

        public Builder checksumAlgorithm(String checksumAlgorithm) {
            this.checksumAlgorithm = checksumAlgorithm;
            return this;
        }

        public Builder correlationId(String correlationId) {
            this.correlationId = correlationId;
            return this;
        }

        public Builder priority(Priority priority) {
            this.priority = priority;
            return this;
        }

        public ConversionRequestDto build() {
            return new ConversionRequestDto(
                    sourceFormat,
                    targetFormat,
                    payload,
                    async,
                    callbackUrl,
                    checksumAlgorithm,
                    correlationId,
                    priority
            );
        }
    }

    /* ------------------------------------------------------------------
     * Equality / HashCode / ToString
     * ------------------------------------------------------------------ */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ConversionRequestDto dto)) return false;
        return async == dto.async
                && Objects.equals(sourceFormat, dto.sourceFormat)
                && Objects.equals(targetFormat, dto.targetFormat)
                && Objects.equals(base64Payload, dto.base64Payload)
                && Objects.equals(callbackUrl, dto.callbackUrl)
                && Objects.equals(checksumAlgorithm, dto.checksumAlgorithm)
                && Objects.equals(correlationId, dto.correlationId)
                && priority == dto.priority;
    }

    @Override
    public int hashCode() {
        return Objects.hash(sourceFormat, targetFormat, base64Payload, async,
                callbackUrl, checksumAlgorithm, correlationId, priority);
    }

    @Override
    public String toString() {
        return "ConversionRequestDto{" +
                "sourceFormat='" + sourceFormat + '\'' +
                ", targetFormat='" + targetFormat + '\'' +
                ", async=" + async +
                ", callbackUrl=" + callbackUrl +
                ", priority=" + priority +
                '}';
    }

    /* ------------------------------------------------------------------
     * Nested types
     * ------------------------------------------------------------------ */

    /**
     * Processing priority enumeration.
     */
    public enum Priority {
        LOW,
        NORMAL,
        HIGH
    }
}