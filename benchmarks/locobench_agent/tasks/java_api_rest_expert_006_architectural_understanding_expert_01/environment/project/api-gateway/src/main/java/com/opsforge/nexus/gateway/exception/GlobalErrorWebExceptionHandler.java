package com.opsforge.nexus.gateway.exception;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.ConstraintViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.web.WebProperties;
import org.springframework.boot.web.error.ErrorAttributeOptions;
import org.springframework.boot.web.reactive.error.AbstractErrorWebExceptionHandler;
import org.springframework.boot.web.reactive.error.ErrorAttributes;
import org.springframework.context.ApplicationContext;
import org.springframework.core.codec.DecodingException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConversionException;
import org.springframework.validation.BindException;
import org.springframework.web.ErrorResponseException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.reactive.function.BodyInserter;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.server.RequestPredicates;
import org.springframework.web.reactive.function.server.RouterFunction;
import org.springframework.web.reactive.function.server.RouterFunctions;
import org.springframework.web.reactive.function.server.ServerCodecConfigurer;
import org.springframework.web.reactive.function.server.ServerRequest;
import org.springframework.web.reactive.function.server.ServerResponse;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * GlobalErrorWebExceptionHandler
 *
 * A Spring WebFlux {@link org.springframework.web.server.WebExceptionHandler} implementation that
 * converts any unhandled exception bubbling up from downstream adapters into a consistent,
 * versioned, JSON error envelope.  The handler relies on {@link ErrorAttributes} to discover
 * common error metadata yet augments it with cross-cutting concerns such as correlation IDs,
 * path information, and validation error details.
 *
 * The output contract is stable and guaranteed not to leak internal stack-traces unless the
 * active Spring profile explicitly enables <code>debug</code>.
 *
 * Example response body:
 * {
 *   "timestamp" : "2023-08-09T18:25:43.511Z",
 *   "status"    : 400,
 *   "error"     : "Bad Request",
 *   "message"   : "First name must not be blank",
 *   "path"      : "/v1/user",
 *   "requestId" : "819c6878-fd4c-4ea0-94d4-46867e8e15b4"
 * }
 */
public class GlobalErrorWebExceptionHandler extends AbstractErrorWebExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalErrorWebExceptionHandler.class);
    private static final String HEADER_REQUEST_ID = "X-Request-Id";

    private final ObjectMapper objectMapper;

    public GlobalErrorWebExceptionHandler(final ErrorAttributes errorAttributes,
                                          final WebProperties webProperties,
                                          final ApplicationContext applicationContext,
                                          final ServerCodecConfigurer codecConfigurer,
                                          final ObjectMapper objectMapper) {
        super(errorAttributes, webProperties.getResources(), applicationContext);
        this.setMessageWriters(codecConfigurer.getWriters());
        this.setMessageReaders(codecConfigurer.getReaders());
        this.objectMapper = objectMapper;
    }

    @Override
    protected RouterFunction<ServerResponse> getRoutingFunction(final ErrorAttributes errorAttributes) {
        return RouterFunctions.route(RequestPredicates.all(), this::renderErrorResponse);
    }

    /**
     * Render an error response as a non-blocking {@link Mono}.
     */
    private Mono<ServerResponse> renderErrorResponse(final ServerRequest request) {
        Throwable throwable          = super.getError(request);
        HttpStatus status            = determineHttpStatus(throwable);
        Map<String, Object> errorMap = populateErrorAttributes(request, throwable, status);

        byte[] jsonBytes;
        try {
            jsonBytes = objectMapper.writeValueAsBytes(errorMap);
        } catch (JsonProcessingException jsonEx) {
            log.warn("Failed to serialize error payload, falling back to minimal contract.", jsonEx);
            jsonBytes = fallbackErrorJson(status);
        }

        BodyInserter<byte[], ReactiveHttpOutputMessage> body = BodyInserters.fromValue(jsonBytes);

        return ServerResponse.status(status)
                             .contentType(MediaType.APPLICATION_JSON)
                             .body(body);
    }

    /**
     * Populate the immutable error contract that will be serialized to JSON.
     */
    private Map<String, Object> populateErrorAttributes(ServerRequest request,
                                                        Throwable error,
                                                        HttpStatus status) {
        Map<String, Object> attributes = new LinkedHashMap<>(8);
        attributes.put("timestamp", Instant.now());
        attributes.put("status", status.value());
        attributes.put("error", status.getReasonPhrase());
        attributes.put("message", resolveErrorMessage(error));
        attributes.put("path", request.path());
        attributes.put("requestId", extractOrGenerateRequestId(request));

        // Add stack-trace only when the application is running in debug mode
        if (log.isDebugEnabled()) {
            attributes.put("trace", buildStackTrace(error));
        }
        return Collections.unmodifiableMap(attributes);
    }

    /**
     * Determines the most appropriate HTTP status for a given exception.
     */
    private HttpStatus determineHttpStatus(Throwable ex) {
        if (ex instanceof ResponseStatusException rse) {
            return rse.getStatusCode();
        }
        if (ex instanceof ErrorResponseException ere) {
            return ere.getStatusCode();
        }
        if (ex instanceof BindException
                || ex instanceof MethodArgumentNotValidException
                || ex instanceof ConstraintViolationException
                || ex instanceof HttpMessageConversionException
                || ex instanceof DecodingException) {
            return HttpStatus.BAD_REQUEST;
        }
        // Fallback to 500
        return HttpStatus.INTERNAL_SERVER_ERROR;
    }

    /**
     * Resolve a human-friendly message for the given exception.
     */
    private String resolveErrorMessage(Throwable ex) {
        if (ex instanceof MethodArgumentNotValidException manve) {
            return manve.getBindingResult().getAllErrors()
                        .stream()
                        .findFirst()
                        .map(objectError -> objectError.getDefaultMessage())
                        .orElse("Validation failed");
        }
        if (ex instanceof BindException be) {
            return be.getAllErrors()
                     .stream()
                     .findFirst()
                     .map(error -> error.getDefaultMessage())
                     .orElse("Binding error");
        }
        if (ex instanceof ConstraintViolationException cve) {
            return cve.getConstraintViolations()
                      .stream()
                      .findFirst()
                      .map(cv -> cv.getMessage())
                      .orElse("Constraint violation");
        }
        String message = ex.getMessage();
        return (message != null && !message.isBlank())
                ? message
                : "Unexpected error";
    }

    /**
     * Retrieves the request ID from the incoming HTTP headers or generates a new one.
     */
    private String extractOrGenerateRequestId(ServerRequest request) {
        return request.headers()
                      .header(HEADER_REQUEST_ID)
                      .stream()
                      .findFirst()
                      .orElse(UUID.randomUUID().toString());
    }

    /**
     * Builds a stack-trace string limited to a sensible number of frames.
     */
    private String buildStackTrace(Throwable ex) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < Math.min(12, ex.getStackTrace().length); i++) {
            sb.append(ex.getStackTrace()[i].toString()).append(System.lineSeparator());
        }
        return sb.toString();
    }

    /**
     * Fallback JSON payload when Jackson serialization fails.
     */
    private byte[] fallbackErrorJson(HttpStatus status) {
        String json = """
                {
                  "status"  : %d,
                  "error"   : "%s",
                  "message" : "Unable to serialize error payload"
                }
                """.formatted(status.value(), status.getReasonPhrase());
        return json.getBytes();
    }
}