package com.sprintcart.adapters.web.rest;

import com.fasterxml.jackson.databind.exc.InvalidFormatException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.ConstraintViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.validation.BindException;
import org.springframework.validation.FieldError;
import org.springframework.web.ErrorResponseException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.NoHandlerFoundException;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * Global exception translator that converts low-level exceptions into JSON:API compliant
 * error documents understood by SprintCart front-end and third-party integrators.
 *
 * <p>The handler is deliberately placed in the web adapter so that it depends only on
 * Spring MVC abstractions and never leaks into the application or domain layers.</p>
 */
@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(basePackages = "com.sprintcart")
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /* ------------------------------------------------------------------------
       DOMAIN EXCEPTIONS
       --------------------------------------------------------------------- */

    /**
     * Thrown when an entity such as Product, Order or Customer does not exist.
     */
    @ExceptionHandler(ResourceNotFoundException.class)
    protected ResponseEntity<Object> handleNotFound(ResourceNotFoundException ex, HttpServletRequest request) {
        return buildResponseEntity(
                ex,
                HttpStatus.NOT_FOUND,
                "Resource not found",
                ex.getMessage(),
                request);
    }

    /**
     * Thrown for domain rule violations (e.g. "cannot cancel shipped order").
     */
    @ExceptionHandler(DomainException.class)
    protected ResponseEntity<Object> handleDomainViolation(DomainException ex, HttpServletRequest request) {
        return buildResponseEntity(
                ex,
                HttpStatus.UNPROCESSABLE_ENTITY,
                "Domain invariants violated",
                ex.getMessage(),
                request);
    }

    /* ------------------------------------------------------------------------
       SPRING & JAVA VALIDATION EXCEPTIONS
       --------------------------------------------------------------------- */

    @ExceptionHandler(MethodArgumentNotValidException.class)
    protected ResponseEntity<Object> handleValidation(MethodArgumentNotValidException ex, HttpServletRequest request) {
        Map<String, List<String>> fieldErrors = ex.getBindingResult()
                                                  .getFieldErrors()
                                                  .stream()
                                                  .collect(Collectors.groupingBy(
                                                          FieldError::getField,
                                                          Collectors.mapping(FieldError::getDefaultMessage, Collectors.toList())));

        return buildResponseEntity(
                ex,
                HttpStatus.BAD_REQUEST,
                "Validation failed",
                "One or more fields are invalid",
                request,
                Map.of("fields", fieldErrors));
    }

    @ExceptionHandler(ConstraintViolationException.class)
    protected ResponseEntity<Object> handleConstraintViolation(ConstraintViolationException ex,
                                                               HttpServletRequest request) {
        Map<String, List<String>> fieldErrors = ex.getConstraintViolations()
                                                  .stream()
                                                  .collect(Collectors.groupingBy(
                                                          GlobalExceptionHandler::extractProperty,
                                                          Collectors.mapping(ConstraintViolation::getMessage, Collectors.toList())));

        return buildResponseEntity(
                ex,
                HttpStatus.BAD_REQUEST,
                "Validation failed",
                "One or more constraints are violated",
                request,
                Map.of("fields", fieldErrors));
    }

    @ExceptionHandler({
            MethodArgumentTypeMismatchException.class,
            InvalidFormatException.class,
            BindException.class
    })
    protected ResponseEntity<Object> handleBadRequest(Exception ex, HttpServletRequest request) {
        return buildResponseEntity(
                ex,
                HttpStatus.BAD_REQUEST,
                "Malformed request",
                ex.getMessage(),
                request);
    }

    /* ------------------------------------------------------------------------
       SECURITY EXCEPTIONS
       --------------------------------------------------------------------- */

    @ExceptionHandler(AccessDeniedException.class)
    protected ResponseEntity<Object> handleAccessDenied(AccessDeniedException ex, HttpServletRequest request) {
        return buildResponseEntity(
                ex,
                HttpStatus.FORBIDDEN,
                "Access denied",
                ex.getMessage(),
                request);
    }

    /* ------------------------------------------------------------------------
       FALLBACK
       --------------------------------------------------------------------- */

    /**
     * Handles any exception that was not explicitly mapped.
     */
    @ExceptionHandler(Exception.class)
    protected ResponseEntity<Object> handleUnknown(Exception ex, HttpServletRequest request) {
        return buildResponseEntity(
                ex,
                HttpStatus.INTERNAL_SERVER_ERROR,
                "Internal server error",
                "An unexpected error occurred",
                request);
    }

    /* ------------------------------------------------------------------------
       INTERNALS
       --------------------------------------------------------------------- */

    private ResponseEntity<Object> buildResponseEntity(
            Throwable ex,
            HttpStatus status,
            String title,
            String detail,
            HttpServletRequest request) {

        return buildResponseEntity(ex, status, title, detail, request, Map.of());
    }

    private ResponseEntity<Object> buildResponseEntity(
            Throwable ex,
            HttpStatus status,
            String title,
            String detail,
            HttpServletRequest request,
            Map<String, Object> extensions) {

        // Generate unique error id to correlate logs with client responses
        String errorId = UUID.randomUUID().toString();

        // Responsible logging—never expose stack traces to clients
        logException(ex, errorId, request);

        ProblemDetail problemDetail = ProblemDetail.forStatusAndDetail(status, detail);
        problemDetail.setTitle(title);
        problemDetail.setProperty("timestamp", Instant.now());
        problemDetail.setProperty("errorId", errorId);
        problemDetail.setProperty("path", request.getRequestURI());
        problemDetail.setProperty("traceId", getTraceId());

        // Add custom extensions if provided
        extensions.forEach(problemDetail::setProperty);

        return new ResponseEntity<>(problemDetail, new HttpHeaders(), status);
    }

    private void logException(Throwable ex, String errorId, HttpServletRequest request) {
        log.error("""
                [errorId: {}] Exception caught while processing {} {}:
                {}: {}
                """,
                errorId,
                request.getMethod(),
                request.getRequestURI(),
                ex.getClass().getSimpleName(),
                ex.getMessage(),
                ex);
    }

    private static String getTraceId() {
        // With Sleuth/Zipkin you could use `Tracer` instead
        return MDC.get("traceId");
    }

    private static String extractProperty(ConstraintViolation<?> violation) {
        // propertyPath: e.g. "createProduct.arg0.name" -> "name"
        String path = violation.getPropertyPath().toString();
        int dot = path.lastIndexOf('.');
        return dot > -1 ? path.substring(dot + 1) : path;
    }

    /* ------------------------------------------------------------------------
       CUSTOM DOMAIN EXCEPTIONS (placeholders)
       --------------------------------------------------------------------- */

    /**
     * Marker for any domain related runtime exception.
     * Implementations should live in the domain module, but we keep simple
     * placeholders here to make this file self-contained.
     */
    public static class DomainException extends RuntimeException {
        public DomainException(String message) {
            super(message);
        }
    }

    /**
     * Thrown when an expected resource cannot be found.
     */
    public static class ResourceNotFoundException extends DomainException {
        public ResourceNotFoundException(String message) {
            super(message);
        }
    }
}