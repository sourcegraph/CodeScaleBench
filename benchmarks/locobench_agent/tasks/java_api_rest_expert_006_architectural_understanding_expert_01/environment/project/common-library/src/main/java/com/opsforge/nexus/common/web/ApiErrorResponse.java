package com.opsforge.nexus.common.web;

import java.io.Serial;
import java.io.Serializable;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonInclude.Include;
import com.fasterxml.jackson.annotation.JsonProperty;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * Immutable DTO that represents the body of an error response returned by every OpsForge
 * micro-service. The class is purposely transport-layer agnostic and can be used by
 * HTTP, GraphQL, gRPC, or internal message listeners alike.
 *
 * <p>All timestamp values are emitted in UTC to prevent implicit time-zone conversions
 * on the client side.</p>
 *
 * <p>For security reasons, the {@code traceId} does <strong>not</strong> expose any
 * sensitive information (it is a random {@link UUID}) and can be safely shared with
 * OpsForge support teams.</p>
 */
@JsonInclude(Include.NON_NULL)
@Schema(name = "ApiErrorResponse",
        description = "Canonical error payload conforming to OpsForge Error Contract")
public final class ApiErrorResponse implements Serializable {

    @Serial
    private static final long serialVersionUID = -6497633034568125475L;

    @Schema(description = "UTC timestamp at which the error was generated",
            example = "2024-03-28T16:31:45.167Z",
            required = true)
    private final ZonedDateTime timestamp;

    @Schema(description = "Numeric HTTP status code, or a synthetic internal code",
            example = "400",
            required = true)
    private final int status;

    @Schema(description = "Short, human-readable reason phrase",
            example = "Bad Request",
            required = true)
    private final String error;

    @Schema(description = "Detailed error message (safe for client display)",
            example = "The field 'email' must be a valid email address")
    private final String message;

    @Schema(description = "Request path that caused the failure",
            example = "/v1/conversion/pdf/merge")
    private final String path;

    @Schema(description = "Unique correlation identifier useful for tracing logs",
            example = "b4079f0a-4e8d-4d3b-87a4-5cca2df6c977",
            required = true)
    private final String traceId;

    @Schema(description = "Map of field-level or constraint-level validation errors",
            example = "{ \"files\": [\"must not be empty\"], \"timeout\": [\"must be greater than 0\"] }")
    @JsonProperty("validation_errors")
    private final Map<String, List<String>> validationErrors;

    private ApiErrorResponse(Builder builder) {
        this.timestamp = builder.timestamp;
        this.status = builder.status;
        this.error = builder.error;
        this.message = builder.message;
        this.path = builder.path;
        this.traceId = builder.traceId;
        this.validationErrors = builder.validationErrors.isEmpty()
                ? null
                : Collections.unmodifiableMap(new LinkedHashMap<>(builder.validationErrors));
    }

    public ZonedDateTime getTimestamp() {
        return timestamp;
    }

    public int getStatus() {
        return status;
    }

    public String getError() {
        return error;
    }

    public String getMessage() {
        return message;
    }

    public String getPath() {
        return path;
    }

    public String getTraceId() {
        return traceId;
    }

    public Map<String, List<String>> getValidationErrors() {
        return validationErrors;
    }

    /**
     * Creates a {@link ResponseEntity} wrapping this error payload, using the contained
     * {@link #status} as HTTP status code.
     */
    public ResponseEntity<ApiErrorResponse> asResponseEntity() {
        return ResponseEntity.status(status).body(this);
    }

    // -------------------------------------------------------------------------
    // Builders & factory methods
    // -------------------------------------------------------------------------

    public static Builder builder(HttpStatus httpStatus) {
        return new Builder()
                .status(httpStatus.value())
                .error(httpStatus.getReasonPhrase());
    }

    public static Builder builder(int code, String reasonPhrase) {
        return new Builder().status(code).error(reasonPhrase);
    }

    /**
     * Convenience factory for simple one-off error responses without validation details.
     */
    public static ApiErrorResponse of(HttpStatus status,
                                      String message,
                                      String path,
                                      String traceId) {
        return builder(status)
                .message(message)
                .path(path)
                .traceId(traceId)
                .build();
    }

    /**
     * Creates error with an auto-generated traceId.
     */
    public static ApiErrorResponse of(HttpStatus status, String message, String path) {
        return of(status, message, path, UUID.randomUUID().toString());
    }

    /**
     * A more fluent builder to construct complex responses.
     */
    public static final class Builder {
        private ZonedDateTime timestamp = ZonedDateTime.now(ZoneOffset.UTC);
        private int status;
        private String error;
        private String message;
        private String path;
        private String traceId = UUID.randomUUID().toString();
        private final Map<String, List<String>> validationErrors = new LinkedHashMap<>();

        private Builder() {
        }

        public Builder timestamp(ZonedDateTime timestamp) {
            this.timestamp = timestamp != null ? timestamp : ZonedDateTime.now(ZoneOffset.UTC);
            return this;
        }

        public Builder status(int status) {
            this.status = status;
            return this;
        }

        public Builder error(String error) {
            this.error = error;
            return this;
        }

        public Builder message(String message) {
            this.message = message;
            return this;
        }

        public Builder path(String path) {
            this.path = path;
            return this;
        }

        public Builder traceId(String traceId) {
            if (traceId != null && !traceId.isBlank()) {
                this.traceId = traceId;
            }
            return this;
        }

        /**
         * Adds a validation error for the specified field or constraint key.
         */
        public Builder addValidationError(String field, String validationMessage) {
            validationErrors.computeIfAbsent(field, k -> new java.util.ArrayList<>())
                            .add(validationMessage);
            return this;
        }

        /**
         * Adds many validation errors at once.
         */
        public Builder validationErrors(Map<String, List<String>> errors) {
            if (errors != null) {
                errors.forEach((field, messages) ->
                        validationErrors.put(field, new java.util.ArrayList<>(messages)));
            }
            return this;
        }

        /**
         * Builds an immutable {@link ApiErrorResponse}.
         */
        public ApiErrorResponse build() {
            return new ApiErrorResponse(this);
        }
    }

    // -------------------------------------------------------------------------
    // Utility overrides
    // -------------------------------------------------------------------------

    @Override
    public String toString() {
        return "ApiErrorResponse{" +
               "timestamp=" + timestamp +
               ", status=" + status +
               ", error='" + error + '\'' +
               ", message='" + message + '\'' +
               ", path='" + path + '\'' +
               ", traceId='" + traceId + '\'' +
               ", validationErrors=" + validationErrors +
               '}';
    }

    @Override
    public int hashCode() {
        int result = timestamp != null ? timestamp.hashCode() : 0;
        result = 31 * result + status;
        result = 31 * result + (error != null ? error.hashCode() : 0);
        result = 31 * result + (message != null ? message.hashCode() : 0);
        result = 31 * result + (path != null ? path.hashCode() : 0);
        result = 31 * result + (traceId != null ? traceId.hashCode() : 0);
        result = 31 * result + (validationErrors != null ? validationErrors.hashCode() : 0);
        return result;
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof ApiErrorResponse other)) return false;
        return status == other.status &&
               java.util.Objects.equals(timestamp, other.timestamp) &&
               java.util.Objects.equals(error, other.error) &&
               java.util.Objects.equals(message, other.message) &&
               java.util.Objects.equals(path, other.path) &&
               java.util.Objects.equals(traceId, other.traceId) &&
               java.util.Objects.equals(validationErrors, other.validationErrors);
    }
}