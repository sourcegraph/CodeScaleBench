package com.opsforge.nexus.common.logging;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.Charset;
import java.time.Duration;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.lang.NonNull;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.ContentCachingRequestWrapper;
import org.springframework.web.util.ContentCachingResponseWrapper;

/**
 * Servlet filter that logs essential information about every HTTP request/response pair while
 * propagating a correlation identifier to facilitate distributed tracing.
 *
 * <p>Highlights:</p>
 * <ul>
 *   <li>Wraps the request/response to capture payloads without consuming the streams.</li>
 *   <li>Safely handles large and/or binary payloads by truncating after {@code maxPayloadLength} bytes.</li>
 *   <li>Skips health-check and other noisy endpoints to keep the logs readable.</li>
 *   <li>Automatically generates a correlation ID when none is found in the incoming request.</li>
 *   <li>Stores the correlation ID in {@link MDC} so that it is included in every downstream log entry.</li>
 * </ul>
 *
 * <p>This class lives in the “common-library” module so it does not carry any Spring Boot
 * auto-configuration baggage—the caller must register the filter manually or via component scanning.</p>
 */
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public final class RequestLoggingFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(RequestLoggingFilter.class);

    /** Fallback header for correlation ID propagation. */
    private static final String DEFAULT_CORRELATION_ID_HEADER = "X-Correlation-Id";

    /** Truncation string applied when payload is larger than {@link #maxPayloadLength}. */
    private static final String ELLIPSIS = "...(truncated)";

    /** Endpoints for which logging is disabled in order to reduce noise. */
    private final Set<String> pathsToSkip;

    /** Maximum number of bytes to log for request/response bodies. */
    private final int maxPayloadLength;

    /** Name of the HTTP header that carries the correlation ID. */
    private final String correlationIdHeaderName;

    /**
     * Creates the filter with the provided configuration.
     *
     * @param pathsToSkip             endpoints whose traffic should not be logged
     * @param maxPayloadLength        maximum amount of body payload (in bytes) to include in the logs
     * @param correlationIdHeaderName header to use for correlation ID propagation
     */
    public RequestLoggingFilter(Set<String> pathsToSkip, int maxPayloadLength, String correlationIdHeaderName) {
        this.pathsToSkip = Collections.unmodifiableSet(new HashSet<>(pathsToSkip));
        this.maxPayloadLength = maxPayloadLength;
        this.correlationIdHeaderName =
                StringUtils.hasText(correlationIdHeaderName) ? correlationIdHeaderName : DEFAULT_CORRELATION_ID_HEADER;
    }

    /**
     * Creates a filter with an OpsForge-sane default configuration.
     */
    public static RequestLoggingFilter defaultFilter() {
        return new RequestLoggingFilter(
                Set.of("/health", "/actuator/health", "/readyz", "/livez", "/prometheus"),
                4096,
                DEFAULT_CORRELATION_ID_HEADER
        );
    }

    // --------------------------------------------------------------------- //
    // OncePerRequestFilter implementation
    // --------------------------------------------------------------------- //

    @Override
    protected boolean shouldNotFilter(@NonNull HttpServletRequest request) {
        String path = request.getRequestURI();
        return pathsToSkip.stream().anyMatch(path::startsWith);
    }

    @Override
    protected void doFilterInternal(
            @NonNull HttpServletRequest request,
            @NonNull HttpServletResponse response,
            @NonNull FilterChain filterChain) throws ServletException, IOException {

        long startNanos = System.nanoTime();

        // Wrap request/response so we can read the body multiple times.
        ContentCachingRequestWrapper wrappedRequest = wrapRequest(request);
        ContentCachingResponseWrapper wrappedResponse = wrapResponse(response);

        // Resolve or generate correlation ID and propagate through MDC.
        String correlationId = resolveCorrelationId(wrappedRequest);
        MDC.put("correlationId", correlationId);
        wrappedResponse.setHeader(correlationIdHeaderName, correlationId);

        try {
            filterChain.doFilter(wrappedRequest, wrappedResponse);
        } finally {
            Duration duration = Duration.ofNanos(System.nanoTime() - startNanos);
            logRequestAndResponse(wrappedRequest, wrappedResponse, duration, correlationId);
            // Copy body back to the real response so the client receives it.
            wrappedResponse.copyBodyToResponse();
            MDC.remove("correlationId");
        }
    }

    // --------------------------------------------------------------------- //
    // Helper methods
    // --------------------------------------------------------------------- //

    private ContentCachingRequestWrapper wrapRequest(HttpServletRequest request) {
        return request instanceof ContentCachingRequestWrapper
                ? (ContentCachingRequestWrapper) request
                : new ContentCachingRequestWrapper(request);
    }

    private ContentCachingResponseWrapper wrapResponse(HttpServletResponse response) {
        return response instanceof ContentCachingResponseWrapper
                ? (ContentCachingResponseWrapper) response
                : new ContentCachingResponseWrapper(response);
    }

    /**
     * Logs the request and response details. Payloads are logged only if the content type is
     * textual (e.g., JSON, XML, plain text) and will be truncated when larger than
     * {@link #maxPayloadLength}.
     */
    private void logRequestAndResponse(ContentCachingRequestWrapper request,
                                       ContentCachingResponseWrapper response,
                                       Duration duration,
                                       String correlationId) {

        StringBuilder sb = new StringBuilder(256);
        sb.append("HTTP ")
          .append(request.getMethod())
          .append(' ')
          .append(request.getRequestURI());

        if (StringUtils.hasText(request.getQueryString())) {
            sb.append('?').append(request.getQueryString());
        }
        sb.append(" -> ")
          .append(response.getStatus())
          .append(", ")
          .append(duration.toMillis())
          .append(" ms")
          .append(", cid=")
          .append(correlationId);

        if (log.isDebugEnabled()) {
            appendHeaders("RequestHeaders", request.getHeaderNames(), request::getHeaders, sb);
            appendHeaders("ResponseHeaders", response.getHeaderNames().stream(), response::getHeaders, sb);

            if (hasTextualBody(request.getContentType())) {
                appendPayload("RequestBody", request.getContentAsByteArray(),
                        request.getCharacterEncoding(), sb);
            }
            if (hasTextualBody(response.getContentType())) {
                appendPayload("ResponseBody", response.getContentAsByteArray(),
                        response.getCharacterEncoding(), sb);
            }
        }

        log.info(sb.toString());
    }

    private void appendHeaders(String label,
                               java.util.Enumeration<String> headerNames,
                               java.util.function.Function<String, java.util.Enumeration<String>> valuesSupplier,
                               StringBuilder target) {

        target.append(System.lineSeparator()).append("  ").append(label).append(": ");
        while (headerNames.hasMoreElements()) {
            String name = headerNames.nextElement();
            java.util.Enumeration<String> values = valuesSupplier.apply(name);
            while (values.hasMoreElements()) {
                target.append(name).append('=').append(values.nextElement()).append("; ");
            }
        }
    }

    private void appendHeaders(String label,
                               Stream<String> headerNames,
                               java.util.function.Function<String, java.util.Collection<String>> valuesSupplier,
                               StringBuilder target) {

        target.append(System.lineSeparator()).append("  ").append(label).append(": ");
        headerNames.forEach(name ->
                valuesSupplier.apply(name).forEach(value ->
                        target.append(name).append('=').append(value).append("; ")));
    }

    private void appendPayload(String label,
                               byte[] content,
                               String encoding,
                               StringBuilder target) {

        if (content == null || content.length == 0) {
            return;
        }
        int length = Math.min(content.length, maxPayloadLength);
        String payload = new String(content, 0, length, determineCharset(encoding));
        if (content.length > maxPayloadLength) {
            payload += ELLIPSIS;
        }
        target.append(System.lineSeparator())
              .append("  ")
              .append(label)
              .append(" (")
              .append(content.length)
              .append(" bytes logged): ")
              .append(payload);
    }

    private Charset determineCharset(String encoding) {
        try {
            return StringUtils.hasText(encoding) ? Charset.forName(encoding) : Charset.defaultCharset();
        } catch (Exception ex) {
            // Fallback to default charset when the provided encoding is invalid.
            return Charset.defaultCharset();
        }
    }

    private boolean hasTextualBody(String contentType) {
        if (!StringUtils.hasText(contentType)) {
            return false;
        }
        try {
            MediaType mediaType = MediaType.parseMediaType(contentType);
            return (MediaType.APPLICATION_JSON.includes(mediaType)
                    || MediaType.APPLICATION_XML.includes(mediaType)
                    || MediaType.TEXT_PLAIN.includes(mediaType)
                    || MediaType.APPLICATION_FORM_URLENCODED.includes(mediaType));
        } catch (Exception ignore) {
            // If parsing fails, assume non-textual.
            return false;
        }
    }

    /**
     * Extracts the correlation ID from the incoming request or generates a new one.
     */
    private String resolveCorrelationId(ContentCachingRequestWrapper request) {
        String headerValue = request.getHeader(correlationIdHeaderName);
        if (StringUtils.hasText(headerValue)) {
            return headerValue;
        }
        // Generate a new UUID v4 (without hyphens for log brevity).
        return UUID.randomUUID().toString().replace("-", "");
    }
}