package com.commercesphere.enterprise.core.error;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonPropertyOrder;

import javax.servlet.http.HttpServletRequest;
import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * Centralized DTO for returning *all* REST-layer error responses in a
 * consistent, machine-friendly format.  The class purposefully contains
 * only immutable state to guarantee thread-safety when reused by
 * Spring’s {@code ResponseEntityExceptionHandler}.
 *
 * Example payload:
 *
 * {
 *   "timestamp" : "2023-09-22T18:11:03.645Z",
 *   "status"    : 400,
 *   "error"     : "Bad Request",
 *   "message"   : "Validation failed",
 *   "path"      : "/v1/companies",
 *   "traceId"   : "4a1d55f4d34d745e",
 *   "subErrors" : [
 *       {
 *           "object"        : "CompanyDTO",
 *           "field"         : "name",
 *           "rejectedValue" : null,
 *           "message"       : "must not be blank"
 *       }
 *   ]
 * }
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonPropertyOrder({ "timestamp",
                     "status",
                     "error",
                     "message",
                     "path",
                     "traceId",
                     "subErrors"})
public final class ApiErrorResponse implements Serializable {

    @Serial
    private static final long serialVersionUID = -3823318217420231245L;

    @JsonFormat(shape = JsonFormat.Shape.STRING)
    private final Instant timestamp;

    private final int status;
    private final String error;
    private final String message;
    private final String path;
    private final String traceId;
    private final List<ValidationSubError> subErrors;

    /* ===========================  Constructors  =========================== */

    private ApiErrorResponse(Builder builder) {
        this.timestamp = builder.timestamp != null ? builder.timestamp : Instant.now();
        this.status    = builder.status;
        this.error     = builder.error;
        this.message   = builder.message;
        this.path      = builder.path;
        this.traceId   = builder.traceId;
        this.subErrors = builder.subErrors == null ? null :
                         Collections.unmodifiableList(new ArrayList<>(builder.subErrors));
    }

    /* ===========================  Static Factories  =========================== */

    /**
     * Creates a generic error response without any sub-validation errors.
     */
    public static ApiErrorResponse of(int httpStatusCode,
                                      String httpStatusName,
                                      String message,
                                      HttpServletRequest request,
                                      String traceId) {

        return new Builder()
                .withStatus(httpStatusCode)
                .withError(httpStatusName)
                .withMessage(message)
                .withPath(request != null ? request.getRequestURI() : null)
                .withTraceId(traceId)
                .build();
    }

    /**
     * Creates an error response that contains bean-validation errors.
     */
    public static ApiErrorResponse validationError(int httpStatusCode,
                                                   String httpStatusName,
                                                   String message,
                                                   HttpServletRequest request,
                                                   String traceId,
                                                   List<ValidationSubError> subErrors) {

        return new Builder()
                .withStatus(httpStatusCode)
                .withError(httpStatusName)
                .withMessage(message)
                .withPath(request != null ? request.getRequestURI() : null)
                .withTraceId(traceId)
                .withSubErrors(subErrors)
                .build();
    }

    /* ===========================  Public Getters  =========================== */

    public Instant getTimestamp() {
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

    public List<ValidationSubError> getSubErrors() {
        return subErrors;
    }

    /* ===========================  Object Overrides  =========================== */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ApiErrorResponse that)) return false;
        return status == that.status &&
               Objects.equals(timestamp, that.timestamp) &&
               Objects.equals(error, that.error) &&
               Objects.equals(message, that.message) &&
               Objects.equals(path, that.path) &&
               Objects.equals(traceId, that.traceId) &&
               Objects.equals(subErrors, that.subErrors);
    }

    @Override
    public int hashCode() {
        return Objects.hash(timestamp, status, error, message, path, traceId, subErrors);
    }

    @Override
    public String toString() {
        return "ApiErrorResponse{" +
               "timestamp=" + timestamp +
               ", status=" + status +
               ", error='" + error + '\'' +
               ", message='" + message + '\'' +
               ", path='" + path + '\'' +
               ", traceId='" + traceId + '\'' +
               ", subErrors=" + subErrors +
               '}';
    }

    /* ===========================  Builder  =========================== */

    public static class Builder {
        private Instant timestamp;
        private int status;
        private String error;
        private String message;
        private String path;
        private String traceId;
        private List<ValidationSubError> subErrors;

        public Builder withTimestamp(Instant timestamp) {
            this.timestamp = timestamp;
            return this;
        }

        public Builder withStatus(int status) {
            this.status = status;
            return this;
        }

        public Builder withError(String error) {
            this.error = error;
            return this;
        }

        public Builder withMessage(String message) {
            this.message = message;
            return this;
        }

        public Builder withPath(String path) {
            this.path = path;
            return this;
        }

        public Builder withTraceId(String traceId) {
            this.traceId = traceId;
            return this;
        }

        public Builder withSubErrors(List<ValidationSubError> subErrors) {
            this.subErrors = subErrors;
            return this;
        }

        public ApiErrorResponse build() {
            return new ApiErrorResponse(this);
        }
    }

    /* ===========================  Nested Types  =========================== */

    /**
     * Describes a single bean validation failure in a user-friendly manner.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ValidationSubError implements Serializable {

        @Serial
        private static final long serialVersionUID = -8739897561239601143L;

        private final String object;         // The DTO or domain object name
        private final String field;          // The specific property that failed
        private final Object rejectedValue;  // The actual value that was rejected
        private final String message;        // Human readable message

        public ValidationSubError(String object,
                                  String field,
                                  Object rejectedValue,
                                  String message) {
            this.object        = object;
            this.field         = field;
            this.rejectedValue = rejectedValue;
            this.message       = message;
        }

        public String getObject() {
            return object;
        }

        public String getField() {
            return field;
        }

        public Object getRejectedValue() {
            return rejectedValue;
        }

        public String getMessage() {
            return message;
        }

        @Override
        public String toString() {
            return "ValidationSubError{" +
                   "object='" + object + '\'' +
                   ", field='" + field + '\'' +
                   ", rejectedValue=" + rejectedValue +
                   ", message='" + message + '\'' +
                   '}';
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof ValidationSubError that)) return false;
            return Objects.equals(object, that.object) &&
                   Objects.equals(field, that.field) &&
                   Objects.equals(rejectedValue, that.rejectedValue) &&
                   Objects.equals(message, that.message);
        }

        @Override
        public int hashCode() {
            return Objects.hash(object, field, rejectedValue, message);
        }
    }
}