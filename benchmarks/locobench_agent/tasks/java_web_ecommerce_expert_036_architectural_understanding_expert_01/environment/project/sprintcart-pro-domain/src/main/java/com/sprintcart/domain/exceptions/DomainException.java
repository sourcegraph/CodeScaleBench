package com.sprintcart.domain.exceptions;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

/**
 * Base class for all exceptions thrown from SprintCart Pro's domain layer.
 *
 * <p>SprintCart Pro relies on a Hexagonal Architecture; therefore, its core domain
 * must not depend on transport or persistence concerns.  Nevertheless, outer layers
 * (REST controllers, GraphQL resolvers, message listeners) need structured error
 * information. {@code DomainException} delivers that through:</p>
 *
 * <ul>
 *   <li>An {@link ErrorCode} enum that categorizes the failure in a stable, type-safe
 *       manner.</li>
 *   <li>An immutable context map with key–value pairs that help the caller diagnose
 *       and possibly recover from the error.</li>
 * </ul>
 *
 * <p>The class extends {@link RuntimeException} to avoid polluting domain APIs with
 * checked-exception signatures.  Application services may catch specific codes or
 * let them bubble up for translation into HTTP statuses, GraphQL errors, etc.</p>
 */
public class DomainException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    /** Machine-readable error code describing the failure category. */
    private final ErrorCode code;

    /** Immutable diagnostic context. */
    private final Map<String, Object> context;

    /* --------------------------------------------------------------------- */
    /* Constructors                                                          */
    /* --------------------------------------------------------------------- */

    private DomainException(Builder builder) {
        super(builder.message, builder.cause);
        this.code = builder.code;
        this.context = Collections.unmodifiableMap(new HashMap<>(builder.context));
    }

    public DomainException(ErrorCode code, String message) {
        this(code, message, null, Map.of());
    }

    public DomainException(ErrorCode code, String message, Throwable cause) {
        this(code, message, cause, Map.of());
    }

    public DomainException(ErrorCode code, String message, Map<String, Object> context) {
        this(code, message, null, context);
    }

    public DomainException(
            ErrorCode code,
            String message,
            Throwable cause,
            Map<String, Object> context
    ) {
        super(message, cause);
        this.code = Objects.requireNonNull(code, "code must not be null");
        this.context = Collections.unmodifiableMap(
                context == null ? Map.of() : new HashMap<>(context)
        );
    }

    /* --------------------------------------------------------------------- */
    /* Static factory                                                        */
    /* --------------------------------------------------------------------- */

    /**
     * Starts a fluent builder for {@link DomainException}.
     *
     * <pre>{@code
     *   throw DomainException
     *           .withCode(ErrorCode.VALIDATION_FAILED)
     *           .message("Quantity must be positive")
     *           .context("field", "quantity")
     *           .context("value", -3)
     *           .build();
     * }</pre>
     */
    public static Builder withCode(ErrorCode code) {
        return new Builder(code);
    }

    /* --------------------------------------------------------------------- */
    /* Accessors                                                             */
    /* --------------------------------------------------------------------- */

    public ErrorCode getCode() {
        return code;
    }

    /**
     * Returns an immutable map containing diagnostic information.
     */
    public Map<String, Object> getContext() {
        return context;
    }

    /**
     * Shorthand for {@code getCode() == expected}.
     */
    public boolean is(ErrorCode expected) {
        return this.code == expected;
    }

    /* --------------------------------------------------------------------- */
    /* Builder                                                               */
    /* --------------------------------------------------------------------- */

    public static final class Builder {

        private final ErrorCode code;
        private String message = "";
        private Throwable cause;
        private final Map<String, Object> context = new HashMap<>();

        private Builder(ErrorCode code) {
            this.code = Objects.requireNonNull(code, "code must not be null");
        }

        public Builder message(String message) {
            this.message = Objects.requireNonNullElse(message, "");
            return this;
        }

        public Builder cause(Throwable cause) {
            this.cause = cause;
            return this;
        }

        public Builder context(String key, Object value) {
            this.context.put(Objects.requireNonNull(key), value);
            return this;
        }

        public Builder context(Map<String, Object> kv) {
            if (kv != null) {
                kv.forEach(this::context);
            }
            return this;
        }

        public DomainException build() {
            return new DomainException(this);
        }
    }

    /* --------------------------------------------------------------------- */
    /* ErrorCode catalogue                                                   */
    /* --------------------------------------------------------------------- */

    /**
     * Common domain-level error codes understood by the application layer.
     *
     * <p>Modules are free to implement their own sub-enums that also implement
     * {@code ErrorCode}, allowing type-safe extensibility without inflating the
     * core list below.</p>
     */
    public enum ErrorCode {
        // Generic
        UNKNOWN,

        // Validation & business rules
        VALIDATION_FAILED,
        CONSTRAINT_VIOLATION,
        PRECONDITION_FAILED,
        ILLEGAL_STATE,

        // Security
        UNAUTHORIZED_ACTION,
        FORBIDDEN,

        // Catalogue & inventory
        PRODUCT_NOT_FOUND,
        INSUFFICIENT_STOCK,

        // Orders
        ORDER_NOT_FOUND,
        ORDER_CANNOT_BE_MODIFIED,
        PAYMENT_FAILURE,

        // Automation
        TASK_DEFINITION_ERROR,
        TASK_EXECUTION_ERROR
    }
}