package com.commercesphere.enterprise.core.error;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.lang.Nullable;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.context.request.ServletWebRequest;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import javax.servlet.http.HttpServletRequest;
import javax.validation.ConstraintViolation;
import javax.validation.ConstraintViolationException;
import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * GlobalExceptionHandler centralises exception handling across the entire CommerceSphere Enterprise Suite
 * application. By returning uniform error payloads, external clients and internal UIs can rely on a predictable
 * contract regardless of where the error originated (MVC, REST, service, or repository layers).
 *
 * <p>The handler also injects a correlation id (if available) so that log aggregators and distributed
 * tracing tools can stitch multi-layer requests together for post-mortem analysis.</p>
 */
@ControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger LOGGER = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /* -------------------------------------------------------------------------
     * Domain-specific exception handlers
     * ---------------------------------------------------------------------- */

    @ExceptionHandler(com.commercesphere.enterprise.core.exception.ResourceNotFoundException.class)
    protected ResponseEntity<ApiErrorResponse> handleResourceNotFound(
            com.commercesphere.enterprise.core.exception.ResourceNotFoundException ex,
            WebRequest request) {

        LOGGER.warn("Resource not found: {}", ex.getMessage());
        return buildErrorResponse(ex, HttpStatus.NOT_FOUND, request, null);
    }

    @ExceptionHandler(com.commercesphere.enterprise.core.exception.BusinessException.class)
    protected ResponseEntity<ApiErrorResponse> handleBusinessException(
            com.commercesphere.enterprise.core.exception.BusinessException ex,
            WebRequest request) {

        LOGGER.info("Business rule violation: {}", ex.getMessage());
        return buildErrorResponse(ex, HttpStatus.UNPROCESSABLE_ENTITY, request, ex.getParameters());
    }

    @ExceptionHandler(com.commercesphere.enterprise.payment.gateway.PaymentGatewayException.class)
    protected ResponseEntity<ApiErrorResponse> handlePaymentGatewayException(
            com.commercesphere.enterprise.payment.gateway.PaymentGatewayException ex,
            WebRequest request) {

        LOGGER.error("Payment gateway error", ex);
        return buildErrorResponse(ex, HttpStatus.BAD_GATEWAY, request, null);
    }

    /* -------------------------------------------------------------------------
     * Validation & framework-level exception handlers
     * ---------------------------------------------------------------------- */

    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(
            MethodArgumentNotValidException ex,
            HttpHeaders headers,
            HttpStatus status,
            WebRequest request) {

        Map<String, String> validationErrors = new LinkedHashMap<>();
        for (FieldError fieldError : ex.getBindingResult().getFieldErrors()) {
            validationErrors.put(fieldError.getField(), fieldError.getDefaultMessage());
        }

        ApiErrorResponse body = createBody(
                HttpStatus.BAD_REQUEST,
                "Validation failed",
                ex.getMessage(),
                extractPath(request),
                validationErrors
        );

        LOGGER.debug("Method argument validation failed: {}", validationErrors);
        return new ResponseEntity<>(body, headers, HttpStatus.BAD_REQUEST);
    }

    @ExceptionHandler(ConstraintViolationException.class)
    protected ResponseEntity<ApiErrorResponse> handleConstraintViolation(
            ConstraintViolationException ex,
            WebRequest request) {

        Map<String, String> validationErrors = new LinkedHashMap<>();
        for (ConstraintViolation<?> violation : ex.getConstraintViolations()) {
            validationErrors.put(violation.getPropertyPath().toString(), violation.getMessage());
        }

        return buildErrorResponse(ex, HttpStatus.BAD_REQUEST, request, validationErrors);
    }

    /* -------------------------------------------------------------------------
     * Catch-all handler
     * ---------------------------------------------------------------------- */

    @ExceptionHandler(Exception.class)
    protected ResponseEntity<ApiErrorResponse> handleUncaughtException(Exception ex, WebRequest request) {
        LOGGER.error("Unhandled exception caught by GlobalExceptionHandler", ex);
        return buildErrorResponse(
                new RuntimeException("Internal server error"),
                HttpStatus.INTERNAL_SERVER_ERROR,
                request,
                null
        );
    }

    /* -------------------------------------------------------------------------
     * Helper methods
     * ---------------------------------------------------------------------- */

    /**
     * Builds a consistent {@link ApiErrorResponse} instance and wraps it in a {@link ResponseEntity}.
     */
    private ResponseEntity<ApiErrorResponse> buildErrorResponse(
            Exception ex,
            HttpStatus status,
            WebRequest request,
            @Nullable Map<String, String> validationErrors) {

        ApiErrorResponse body = createBody(
                status,
                ex.getClass().getSimpleName(),
                ex.getMessage(),
                extractPath(request),
                validationErrors == null ? null : Collections.unmodifiableMap(validationErrors)
        );

        return new ResponseEntity<>(body, status);
    }

    /**
     * Creates error payload with a correlation id (if present in the MDC). When no correlation id exists,
     * a new one is generated to ensure every error is traceable.
     */
    private ApiErrorResponse createBody(HttpStatus status,
                                        String error,
                                        String message,
                                        String path,
                                        @Nullable Map<String, String> validationErrors) {

        String correlationId = MDC.get("correlationId");
        if (correlationId == null) {
            correlationId = UUID.randomUUID().toString();
            MDC.put("correlationId", correlationId);
        }

        return new ApiErrorResponse(
                Instant.now(),
                correlationId,
                status.value(),
                error,
                message,
                path,
                validationErrors
        );
    }

    private String extractPath(WebRequest request) {
        if (request instanceof ServletWebRequest) {
            HttpServletRequest servletRequest = ((ServletWebRequest) request).getRequest();
            return servletRequest.getRequestURI();
        }
        return request.getDescription(false); // fallback, e.g., "uri=/endpoint"
    }

    /* -------------------------------------------------------------------------
     * Error payload model
     * ---------------------------------------------------------------------- */

    /**
     * A standard error envelope for all API responses returned by {@link GlobalExceptionHandler}.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class ApiErrorResponse {

        private final Instant timestamp;
        private final String correlationId;
        private final int status;
        private final String error;
        private final String message;
        private final String path;
        private final Map<String, String> validationErrors;

        private ApiErrorResponse(Instant timestamp,
                                 String correlationId,
                                 int status,
                                 String error,
                                 String message,
                                 String path,
                                 @Nullable Map<String, String> validationErrors) {
            this.timestamp = timestamp;
            this.correlationId = correlationId;
            this.status = status;
            this.error = error;
            this.message = message;
            this.path = path;
            this.validationErrors = validationErrors;
        }

        public Instant getTimestamp() {
            return timestamp;
        }

        public String getCorrelationId() {
            return correlationId;
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

        public Map<String, String> getValidationErrors() {
            return validationErrors;
        }
    }
}