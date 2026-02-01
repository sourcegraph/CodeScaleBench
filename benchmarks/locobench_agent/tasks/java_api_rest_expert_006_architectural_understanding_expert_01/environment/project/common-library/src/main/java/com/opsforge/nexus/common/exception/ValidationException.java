package com.opsforge.nexus.common.exception;

import java.io.Serial;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.StringJoiner;
import java.util.stream.Collectors;

import javax.validation.ConstraintViolation;
import javax.validation.Path;

/**
 * Thrown when a client‐supplied payload does not satisfy the semantic or
 * syntactic requirements declared by the service contract. <p>
 *
 * Unlike a raw {@link javax.validation.ConstraintViolationException}, this
 * exception is specifically tailored for API exposure: it aggregates individual
 * field errors, supplies a deterministic <b>error code</b>, and produces a
 * stable, human-friendly message suitable for external consumption. <p>
 *
 * The exception is intentionally a {@code RuntimeException} so that it can be
 * propagated through layers without littering method signatures. Framework
 * adapters (Spring MVC, GraphQL, Quarkus, etc.) are expected to intercept this
 * exception and translate it to the appropriate wire-level representation
 * (HTTP 400, GraphQL ValidationError, etc.).
 *
 * @author OpsForge
 * @since 1.0.0
 */
public class ValidationException extends RuntimeException {

    @Serial
    private static final long serialVersionUID = -138987654123456789L;

    /**
     * A stable, machine-readable error code associated with every instance of
     * {@link ValidationException}. External clients can rely on the value
     * <b>"VALIDATION_FAILURE"</b> to implement error-handling logic that is
     * agnostic of localized user messages.
     */
    public static final String ERROR_CODE = "VALIDATION_FAILURE";

    /**
     * Aggregated list of field-level errors that led to this exception.
     * Guaranteed to be non-null and, if present, immutable.
     */
    private final List<FieldError> errors;

    /**
     * Creates a new {@link ValidationException} with a generic message and an
     * empty error list.
     */
    public ValidationException() {
        this("Request payload failed validation", Collections.emptyList(), null);
    }

    /**
     * Creates a new {@code ValidationException} with the supplied message and
     * error list.
     *
     * @param message user-friendly explanation of the validation failure
     * @param errors  individual field errors (may be {@code null})
     */
    public ValidationException(final String message, final List<FieldError> errors) {
        this(message, errors, null);
    }

    /**
     * Creates a new {@code ValidationException} with the supplied message, error list
     * and causal throwable.
     *
     * @param message user-friendly explanation of the validation failure
     * @param errors  individual field errors (may be {@code null})
     * @param cause   root cause (may be {@code null})
     */
    public ValidationException(final String message,
                               final List<FieldError> errors,
                               final Throwable cause) {
        super(message, cause);
        this.errors = errors == null ? Collections.emptyList()
                                     : Collections.unmodifiableList(new ArrayList<>(errors));
    }

    /**
     * Creates a {@link ValidationException} from a collection of {@link ConstraintViolation}.
     * The resulting exception’s {@link #getErrors()} list is populated with the
     * extracted details.
     *
     * @param violations bean-validation violations to convert; must not be {@code null}
     * @return a populated {@link ValidationException}
     */
    public static ValidationException from(final Set<ConstraintViolation<?>> violations) {
        if (violations == null || violations.isEmpty()) {
            // Should never be called with empty violations, but guard just in case
            return new ValidationException();
        }

        final List<FieldError> fieldErrors = violations.stream()
                                                       .map(violation -> new FieldError(
                                                               toDotPath(violation.getPropertyPath()),
                                                               String.valueOf(violation.getInvalidValue()),
                                                               violation.getMessage()))
                                                       .collect(Collectors.toList());

        final String message = "Request payload failed validation (" + fieldErrors.size() + " error"
                + (fieldErrors.size() > 1 ? "s" : "") + ")";
        return new ValidationException(message, fieldErrors);
    }

    /**
     * Returns the aggregated, immutable list of individual field errors.
     */
    public List<FieldError> getErrors() {
        return errors;
    }

    /**
     * Converts the exception to a compact debug string.
     */
    @Override
    public String toString() {
        return new StringJoiner(", ", ValidationException.class.getSimpleName() + "[", "]")
                .add("errorCode=" + ERROR_CODE)
                .add("message='" + getMessage() + "'")
                .add("errors=" + errors)
                .toString();
    }

    // ---------------------------------------------------------------------
    // Static helpers
    // ---------------------------------------------------------------------

    /**
     * Converts a Bean Validation {@link Path} to a canonical dot-notation string
     * (e.g. {@code user.address.street}).
     */
    private static String toDotPath(final Path path) {
        final StringBuilder builder = new StringBuilder();
        for (Path.Node node : path) {
            if (node.getName() == null) { continue; }
            if (builder.length() > 0) {
                builder.append('.');
            }
            builder.append(node.getName());
        }
        return builder.toString();
    }

    // ---------------------------------------------------------------------
    // Nested types
    // ---------------------------------------------------------------------

    /**
     * Immutable value object representing a single field error inside a
     * {@link ValidationException}.
     */
    public static final class FieldError implements Serializable {

        @Serial
        private static final long serialVersionUID = -5234509876543212345L;

        /**
         * Name of the field that failed validation (dot-notation for nested
         * objects, e.g. {@code address.street}).
         */
        private final String field;

        /**
         * The value that was rejected (converted to {@code String}).
         */
        private final String rejectedValue;

        /**
         * Reason explaining why the value is invalid (comes from the violated
         * constraint’s {@code message} attribute).
         */
        private final String message;

        public FieldError(final String field,
                          final String rejectedValue,
                          final String message) {
            this.field = field;
            this.rejectedValue = rejectedValue;
            this.message = message;
        }

        public String getField() {
            return field;
        }

        public String getRejectedValue() {
            return rejectedValue;
        }

        public String getMessage() {
            return message;
        }

        @Override
        public String toString() {
            return new StringJoiner(", ", FieldError.class.getSimpleName() + "[", "]")
                    .add("field='" + field + "'")
                    .add("rejectedValue='" + rejectedValue + "'")
                    .add("message='" + message + "'")
                    .toString();
        }
    }

    // ---------------------------------------------------------------------
    //  Builder—useful when exceptions are created manually
    // ---------------------------------------------------------------------

    /**
     * Returns a fluent builder for manually constructing a
     * {@link ValidationException}.
     */
    public static Builder builder() {
        return new Builder();
    }

    @SuppressWarnings("unused")
    public static final class Builder {
        private final List<FieldError> errors = new ArrayList<>();
        private String message = "Request payload failed validation";

        public Builder message(final String message) {
            this.message = message;
            return this;
        }

        public Builder addError(final String field,
                                final Object rejectedValue,
                                final String message) {
            errors.add(new FieldError(field,
                                      rejectedValue == null ? "null" : rejectedValue.toString(),
                                      message));
            return this;
        }

        public ValidationException build() {
            return new ValidationException(message, errors);
        }
    }
}