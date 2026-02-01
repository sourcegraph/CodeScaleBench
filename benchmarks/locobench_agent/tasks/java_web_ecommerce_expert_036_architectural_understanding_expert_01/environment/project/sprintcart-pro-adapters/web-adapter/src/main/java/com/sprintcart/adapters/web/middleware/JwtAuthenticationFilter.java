package com.sprintcart.adapters.web.middleware;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sprintcart.adapters.web.dto.ApiError;
import com.sprintcart.common.tracing.CorrelationIdHolder;
import com.sprintcart.ports.spi.security.TokenProvider;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import javax.servlet.FilterChain;
import javax.servlet.ServletException;
import javax.servlet.http.Cookie;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.lang.NonNull;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * JwtAuthenticationFilter is a servlet filter that extracts a JWT from the incoming request
 * (Authorization header or the {@code SC_AUTH} HttpOnly cookie), validates it using
 * {@link TokenProvider}, and—if valid—propagates the resulting {@link Authentication}
 * to Spring Security's {@link SecurityContextHolder}.
 *
 * <p>Requests matching {@code EXCLUDED_PATHS} bypass authentication entirely. This includes
 * public API routes, health checks, and static assets.</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final String BEARER_PREFIX = "Bearer ";
    private static final String AUTH_COOKIE_NAME = "SC_AUTH";

    /**
     * Paths that do NOT require authentication.
     */
    private static final List<String> EXCLUDED_PATHS = List.of(
            "/api/public/",
            "/login",
            "/logout",
            "/actuator/",
            "/health",
            "/error",
            "/static/"
    );

    private final TokenProvider tokenProvider;
    private final ObjectMapper objectMapper;

    @Override
    protected boolean shouldNotFilter(@NonNull HttpServletRequest request) {
        final String path = request.getRequestURI();
        return EXCLUDED_PATHS.stream().anyMatch(path::startsWith);
    }

    @Override
    protected void doFilterInternal(
            @NonNull HttpServletRequest request,
            @NonNull HttpServletResponse response,
            @NonNull FilterChain filterChain
    ) throws ServletException, IOException {

        try {
            extractToken(request)
                    .filter(tokenProvider::validateToken)          // validate signature / expiry / etc.
                    .map(tokenProvider::getAuthentication)         // convert to Spring Authentication
                    .ifPresent(SecurityContextHolder.getContext()::setAuthentication);

            // Attach a correlation id for downstream logging/observability (if not already set)
            CorrelationIdHolder.ensureCorrelationId(request);

            filterChain.doFilter(request, response);
        } catch (Exception ex) {
            log.debug("JWT processing failed: {}", ex.getMessage(), ex);
            handleAuthenticationFailure(response, ex);
        } finally {
            // Clear context to avoid leaking authentication between threads
            SecurityContextHolder.clearContext();
        }
    }

    /**
     * Extracts the raw JWT from either the Authorization header or the {@code SC_AUTH} cookie.
     */
    private Optional<String> extractToken(HttpServletRequest request) {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (StringUtils.isNotBlank(header) && header.startsWith(BEARER_PREFIX)) {
            return Optional.of(StringUtils.removeStart(header, BEARER_PREFIX).trim());
        }

        if (request.getCookies() != null) {
            for (Cookie cookie : request.getCookies()) {
                if (AUTH_COOKIE_NAME.equals(cookie.getName()) && StringUtils.isNotBlank(cookie.getValue())) {
                    return Optional.of(cookie.getValue());
                }
            }
        }

        return Optional.empty();
    }

    /**
     * Writes a JSON error response with 401 status code.
     */
    private void handleAuthenticationFailure(HttpServletResponse response, Exception ex) {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());

        ApiError error = ApiError.builder()
                .timestamp(OffsetDateTime.now())
                .status(HttpStatus.UNAUTHORIZED.value())
                .error("Unauthorized")
                .message("Invalid or expired authentication token.")
                .traceId(CorrelationIdHolder.getCurrentId().orElse(null))
                .build();

        try {
            objectMapper.writeValue(response.getWriter(), error);
            response.getWriter().flush();
        } catch (IOException ioEx) {
            log.error("Failed to write unauthorized response: {}", ioEx.getMessage(), ioEx);
        }
    }
}