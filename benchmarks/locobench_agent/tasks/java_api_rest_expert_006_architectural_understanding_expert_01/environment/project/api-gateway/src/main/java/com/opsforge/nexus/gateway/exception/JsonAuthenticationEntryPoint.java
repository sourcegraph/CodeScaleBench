package com.opsforge.nexus.gateway.exception;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.MessageSource;
import org.springframework.context.i18n.LocaleContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.time.Instant;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * AuthenticationEntryPoint that returns a JSON error payload instead of the default
 * HTML or plain-text response when an unauthenticated client tries to access a protected resource.
 *
 * <p>Example response:
 * <pre>{@code
 * {
 *   "timestamp": "2023-12-24T18:03:11.431Z",
 *   "status": 401,
 *   "error": "Unauthorized",
 *   "message": "Authentication is required to access this resource.",
 *   "path": "/v1/convert/pdf",
 *   "traceId": "16cc995dc38a45aa9bf86fb2a29cbe72"
 * }
 * }</pre>
 */
@Component
public class JsonAuthenticationEntryPoint implements AuthenticationEntryPoint {

    private static final Logger LOGGER = LoggerFactory.getLogger(JsonAuthenticationEntryPoint.class);
    private static final String TRACE_HEADER = "X-Trace-Id";

    private final ObjectMapper objectMapper;
    private final MessageSource messageSource;

    public JsonAuthenticationEntryPoint(ObjectMapper objectMapper, MessageSource messageSource) {
        this.objectMapper = objectMapper;
        this.messageSource = messageSource;
    }

    @Override
    public void commence(HttpServletRequest request,
                         HttpServletResponse response,
                         AuthenticationException authException) throws IOException, ServletException {

        if (response.isCommitted()) {
            LOGGER.debug("Response already committed. Unable to send JSON error message.");
            return;
        }

        Locale clientLocale = LocaleContextHolder.getLocale();
        String localizedMessage = messageSource.getMessage(
                "auth.required",
                null,
                "Authentication is required to access this resource.",
                clientLocale
        );

        String traceId = resolveOrGenerateTraceId(request, response);

        ErrorPayload payload = ErrorPayload.builder()
                .timestamp(Instant.now().toString())
                .status(HttpStatus.UNAUTHORIZED.value())
                .error(HttpStatus.UNAUTHORIZED.getReasonPhrase())
                .message(localizedMessage)
                .path(request.getRequestURI())
                .traceId(traceId)
                .build();

        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");

        try {
            response.getWriter().write(objectMapper.writeValueAsString(payload));
        } catch (JsonProcessingException ex) {
            LOGGER.error("Failed to serialize JSON authentication error payload. Falling back to plain text.", ex);
            response.getWriter().write("Unauthorized");
        }
    }

    /**
     * Returns the trace/correlation identifier that should be associated with the response.
     * If the client already supplied a trace ID header then we echo it back, otherwise we
     * generate one to ensure the downstream logging infrastructure can correlate messages.
     *
     * @param request  {@link HttpServletRequest} incoming request
     * @param response {@link HttpServletResponse} outgoing response
     * @return non-empty correlation identifier
     */
    private String resolveOrGenerateTraceId(HttpServletRequest request, HttpServletResponse response) {
        String traceId = Optional.ofNullable(request.getHeader(TRACE_HEADER))
                .filter(StringUtils::isNotBlank)
                .orElse(UUID.randomUUID().toString().replace("-", ""));

        // Ensure the ID is visible to the caller for further chained requests.
        response.setHeader(TRACE_HEADER, traceId);
        return traceId;
    }

    /**
     * Simple POJO used to serialize the JSON error response.
     * Implemented manually instead of using records for compatibility with Java 8.
     */
    private static final class ErrorPayload {

        private final String timestamp;
        private final int status;
        private final String error;
        private final String message;
        private final String path;
        private final String traceId;

        private ErrorPayload(Builder builder) {
            this.timestamp = builder.timestamp;
            this.status = builder.status;
            this.error = builder.error;
            this.message = builder.message;
            this.path = builder.path;
            this.traceId = builder.traceId;
        }

        public static Builder builder() {
            return new Builder();
        }

        // Getters are required for Jackson serialization.

        public String getTimestamp() {
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

        private static final class Builder {
            private String timestamp;
            private int status;
            private String error;
            private String message;
            private String path;
            private String traceId;

            Builder timestamp(String timestamp) {
                this.timestamp = timestamp;
                return this;
            }

            Builder status(int status) {
                this.status = status;
                return this;
            }

            Builder error(String error) {
                this.error = error;
                return this;
            }

            Builder message(String message) {
                this.message = message;
                return this;
            }

            Builder path(String path) {
                this.path = path;
                return this;
            }

            Builder traceId(String traceId) {
                this.traceId = traceId;
                return this;
            }

            ErrorPayload build() {
                return new ErrorPayload(this);
            }
        }
    }
}