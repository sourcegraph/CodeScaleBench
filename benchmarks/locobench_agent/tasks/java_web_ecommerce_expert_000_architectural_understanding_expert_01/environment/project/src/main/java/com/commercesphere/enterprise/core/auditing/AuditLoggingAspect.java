package com.commercesphere.enterprise.core.auditing;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.aspectj.lang.JoinPoint;
import org.aspectj.lang.annotation.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.Arrays;
import java.util.Optional;
import java.util.UUID;

/**
 * AuditLoggingAspect is a Spring AOP component responsible for persisting
 * audit-grade logs for every method annotated with {@link Auditable}.
 *
 * <p>The aspect records:
 *  – User identity (if available)
 *  – Method signature
 *  – Serialized method arguments
 *  – Result (on success) or exception type/message (on failure)
 *  – Correlation ID (from MDC or new UUID)
 *
 * <p>Audit entries are persisted via {@link AuditTrailService}.  The aspect
 * is designed to be fail-safe—exceptions thrown while auditing will never
 * propagate to the application flow.
 */
@Aspect
@Component
public class AuditLoggingAspect {

    private static final Logger LOGGER = LoggerFactory.getLogger(AuditLoggingAspect.class);
    private static final String CORRELATION_ID_KEY = "correlationId";

    private final AuditTrailService auditTrailService;
    private final ObjectMapper objectMapper;

    public AuditLoggingAspect(AuditTrailService auditTrailService,
                              ObjectMapper objectMapper) {
        this.auditTrailService = auditTrailService;
        this.objectMapper = objectMapper;
    }

    /* ----------------------------------------------------------------------
     *                       Pointcut Definitions
     * -------------------------------------------------------------------- */

    /**
     * Pointcut that matches any method annotated with @Auditable
     */
    @Pointcut("@annotation(com.commercesphere.enterprise.core.auditing.Auditable)")
    public void auditableMethod() {
        /* Method body is empty because it's just a pointcut reference. */
    }

    /* ----------------------------------------------------------------------
     *                       Advice Implementations
     * -------------------------------------------------------------------- */

    /**
     * Advice executed after a successful method invocation.
     */
    @AfterReturning(pointcut = "auditableMethod()", returning = "result")
    public void logSuccess(JoinPoint joinPoint, Object result) {
        handleAudit(joinPoint, result, null);
    }

    /**
     * Advice executed after an exception is thrown by an auditable method.
     */
    @AfterThrowing(pointcut = "auditableMethod()", throwing = "ex")
    public void logFailure(JoinPoint joinPoint, Throwable ex) {
        handleAudit(joinPoint, null, ex);
    }

    /* ----------------------------------------------------------------------
     *                       Internal Helpers
     * -------------------------------------------------------------------- */

    private void handleAudit(JoinPoint jp, Object result, Throwable ex) {
        try {
            AuditEntry entry = buildAuditEntry(jp, result, ex);
            auditTrailService.record(entry);
        } catch (Exception failure) {
            /*
             * NEVER allow audit failures to disturb the business flow.
             * Log the issue and move on.
             */
            LOGGER.error("Failed to persist audit entry: {}", failure.getMessage(), failure);
        }
    }

    private AuditEntry buildAuditEntry(JoinPoint jp, Object result, Throwable ex) {
        String correlationId = resolveCorrelationId();
        String user = resolveUser();
        String argsJson = toJson(jp.getArgs());
        String resultJson = toJson(result);

        return AuditEntry.builder()
                .timestamp(Instant.now())
                .username(user)
                .operation(jp.getSignature().toShortString())
                .arguments(argsJson)
                .result(resultJson)
                .exception(ex != null ? ex.getClass().getName() + ": " + ex.getMessage() : null)
                .success(ex == null)
                .correlationId(correlationId)
                .build();
    }

    private String resolveCorrelationId() {
        // Try to retrieve from MDC; generate new UUID if missing.
        String existing = MDC.get(CORRELATION_ID_KEY);
        if (existing != null && !existing.isBlank()) {
            return existing;
        }
        String generated = UUID.randomUUID().toString();
        MDC.put(CORRELATION_ID_KEY, generated);
        return generated;
    }

    private String resolveUser() {
        return Optional.ofNullable(SecurityContextHolder.getContext().getAuthentication())
                .filter(Authentication::isAuthenticated)
                .map(Authentication::getName)
                .orElse("anonymous");
    }

    private String toJson(Object obj) {
        if (obj == null) {
            return "null";
        }

        try {
            if (obj.getClass().isArray()) {
                return objectMapper.writeValueAsString(Arrays.asList((Object[]) obj));
            }
            return objectMapper.writeValueAsString(obj);
        } catch (JsonProcessingException e) {
            // Fallback to toString() in case of serialization issues
            LOGGER.debug("Could not serialize object for audit log: {}", e.getMessage());
            return String.valueOf(obj);
        }
    }
}

/* ----------------------------------------------------------------------
 *                       Support Classes / Interfaces
 * -------------------------------------------------------------------- */

/**
 * Marker annotation for auditable methods.
 */
@interface Auditable {
    /**
     * Optional descriptive value that overrides the method signature
     * in the audit record.  Useful for high-level business names such as
     * "Checkout Complete" or "Approve Quote".
     */
    String value() default "";
}

/**
 * Contract for persisting audit trail entries.
 *
 * <p>The actual implementation could write to a database table, message
 * queue, or external log aggregator.  Keeping it abstract allows the aspect
 * to remain oblivious to infrastructure concerns.
 */
@FunctionalInterface
interface AuditTrailService {

    /**
     * Persist the supplied audit entry.
     *
     * @param entry Non-null audit entry
     */
    void record(AuditEntry entry);
}

/**
 * Immutable data class representing a single audit log entry.
 *
 * <p>Package-private to discourage direct instantiation outside the aspect
 * and service layer.
 */
class AuditEntry {

    private final Instant timestamp;
    private final String username;
    private final String operation;
    private final String arguments;
    private final String result;
    private final String exception;
    private final boolean success;
    private final String correlationId;

    private AuditEntry(Builder builder) {
        this.timestamp = builder.timestamp;
        this.username = builder.username;
        this.operation = builder.operation;
        this.arguments = builder.arguments;
        this.result = builder.result;
        this.exception = builder.exception;
        this.success = builder.success;
        this.correlationId = builder.correlationId;
    }

    /* ----------------------  Getters  ---------------------- */

    public Instant getTimestamp()     { return timestamp; }
    public String  getUsername()      { return username; }
    public String  getOperation()     { return operation; }
    public String  getArguments()     { return arguments; }
    public String  getResult()        { return result; }
    public String  getException()     { return exception; }
    public boolean isSuccess()        { return success; }
    public String  getCorrelationId() { return correlationId; }

    /* --------------------  Builder  ------------------------ */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private Instant timestamp;
        private String username;
        private String operation;
        private String arguments;
        private String result;
        private String exception;
        private boolean success;
        private String correlationId;

        private Builder() {
        }

        public Builder timestamp(Instant timestamp) {
            this.timestamp = timestamp;
            return this;
        }

        public Builder username(String username) {
            this.username = username;
            return this;
        }

        public Builder operation(String operation) {
            this.operation = operation;
            return this;
        }

        public Builder arguments(String arguments) {
            this.arguments = arguments;
            return this;
        }

        public Builder result(String result) {
            this.result = result;
            return this;
        }

        public Builder exception(String exception) {
            this.exception = exception;
            return this;
        }

        public Builder success(boolean success) {
            this.success = success;
            return this;
        }

        public Builder correlationId(String correlationId) {
            this.correlationId = correlationId;
            return this;
        }

        public AuditEntry build() {
            return new AuditEntry(this);
        }
    }
}