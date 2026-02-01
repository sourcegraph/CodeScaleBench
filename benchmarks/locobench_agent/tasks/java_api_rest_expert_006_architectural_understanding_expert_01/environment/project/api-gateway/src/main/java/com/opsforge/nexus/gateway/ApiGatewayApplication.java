```java
package com.opsforge.nexus.gateway;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import io.github.resilience4j.reactor.circuitbreaker.operator.CircuitBreakerOperator;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.reactivestreams.Publisher;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.web.ResourceProperties;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.cloud.gateway.filter.GatewayFilter;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.cloud.gateway.filter.OrderedGatewayFilter;
import org.springframework.cloud.gateway.filter.factory.RewritePathGatewayFilterFactory;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.RouteLocatorBuilder;
import org.springframework.cloud.gateway.support.ServerWebExchangeUtils;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.*;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;
import org.springframework.util.StringUtils;
import org.springframework.validation.BindException;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.reactive.function.server.HandlerStrategies;
import org.springframework.web.reactive.function.server.RouterFunctions;
import org.springframework.web.reactive.result.method.annotation.ResponseEntityExceptionHandler;
import org.springframework.web.server.*;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.time.ZonedDateTime;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;
import java.util.regex.Pattern;

/**
 * Main bootstrap class for the OpsForge Utility Nexus API-Gateway.
 * <p>
 * Responsibilities:
 *  <ul>
 *      <li>Bootstraps Spring Boot / Spring Cloud Gateway</li>
 *      <li>Configures cross-cutting filters (correlation-id, version rewriting, rate limits, circuit breakers)</li>
 *      <li>Sets up infra beans such as {@link CacheManager}</li>
 *      <li>Exposes opinionated error handling for downstream services</li>
 *  </ul>
 */
@SpringBootApplication
@EnableDiscoveryClient
@EnableConfigurationProperties(ApiGatewayApplication.VersioningProperties.class)
public class ApiGatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(ApiGatewayApplication.class, args);
    }

    /**
     * Component that rewrites inbound `/api/{version}/utility/**` requests to `/utility/**`
     * so that downstream micro-services do not need to version their internal routes.
     */
    @Bean
    public RouteLocator versioningRouteLocator(RouteLocatorBuilder builder,
                                               VersioningProperties versionProps,
                                               CircuitBreakerRegistry cbRegistry) {

        Function<String, GatewayFilter> circuitBreakerFilter = serviceId -> {
            var cb = cbRegistry.circuitBreaker(serviceId);
            return new OrderedGatewayFilter((exchange, chain) -> {
                Publisher<? extends Void> protectedChain =
                        chain.filter(exchange).transformDeferred(CircuitBreakerOperator.of(cb));
                return Mono.from(protectedChain);
            }, Ordered.LOWEST_PRECEDENCE);
        };

        return builder.routes()
                // Example route for the "file-conversion" micro-service
                .route("file-conversion-service", r -> r
                        .path(versionProps.getPrefix() + "/v{version:[1-9][\\d]*}/convert/**")
                        .filters(f -> f
                                .filter(circuitBreakerFilter.apply("file-conversion-service"))
                                .filter(new ApiVersionStripFilter(versionProps))
                                .requestRateLimiter(c -> c.setKeyResolver(exchange ->
                                        Mono.just(Objects.requireNonNull(
                                                exchange.getRequest().getRemoteAddress()).getAddress().getHostAddress())))
                        )
                        .uri("lb://FILE-CONVERSION-SERVICE"))
                // Generic catch-all route for other utilities
                .route("utility-misc", r -> r
                        .path(versionProps.getPrefix() + "/v{version:[1-9][\\d]*}/**")
                        .filters(f -> f
                                .filter(new ApiVersionStripFilter(versionProps))
                        )
                        .uri("lb://UTILITY-MISC-SERVICE"))
                .build();
    }

    /**
     * Global Caffeine cache manager, to be used for response caching and request throttling state.
     */
    @Bean
    @Primary
    public CacheManager caffeineCacheManager() {
        CaffeineCacheManager manager = new CaffeineCacheManager();
        manager.setCaffeine(Caffeine.newBuilder()
                .expireAfterWrite(10, TimeUnit.MINUTES)
                .maximumSize(10_000));
        return manager;
    }

    /**
     * Filter that attaches/propagates a correlation-id header to every request.
     */
    @Bean
    public GlobalFilter correlationIdFilter() {
        return new CorrelationIdFilter();
    }

    /**
     * Application-wide JSON serializer used by the {@link GlobalErrorHandler}.
     */
    @Bean
    public ObjectMapper jacksonMapper() {
        return new ObjectMapper()
                .setSerializationInclusion(JsonInclude.Include.NON_NULL);
    }

    // ---------------------------------------------------------------------------
    //  Value Objects / Configuration
    // ---------------------------------------------------------------------------

    /**
     * Configuration properties that govern how versioned API paths are detected
     * and rewritten before reaching downstream services.
     */
    @Data
    @ConfigurationProperties(prefix = "opsforge.api.versioning")
    public static class VersioningProperties {
        /**
         * Common API prefix before the version part. Example: "/api".
         */
        private String prefix = "/api";
        /**
         * Whether the version segment should be removed before forwarding.
         */
        private boolean stripVersionSegment = true;
    }

    // ---------------------------------------------------------------------------
    //  Internal components
    // ---------------------------------------------------------------------------

    /**
     * Filter that removes the /api/v{n} prefix from incoming requests.
     */
    private static class ApiVersionStripFilter implements GatewayFilter, Ordered {

        private static final Pattern VERSIONED_PATH =
                Pattern.compile("^/(.+?)/v\\d+/(.*)$");

        private final VersioningProperties props;

        private ApiVersionStripFilter(VersioningProperties props) {
            this.props = props;
        }

        @Override
        public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
            ServerHttpRequest request = exchange.getRequest();
            String rawPath = request.getURI().getRawPath();
            String normalizedPrefix = props.getPrefix().endsWith("/")
                    ? props.getPrefix() : props.getPrefix() + "/";
            if (!rawPath.startsWith(normalizedPrefix)) {
                return chain.filter(exchange); // Nothing to do
            }

            // Remove prefix and version segment
            String withoutPrefix = rawPath.substring(normalizedPrefix.length());
            String[] parts = StringUtils.tokenizeToStringArray(withoutPrefix, "/");
            if (parts.length < 2) {
                return chain.filter(exchange); // Unknown format
            }

            // parts[0] = "v{n}"
            String rebasedPath = "/" + String.join("/", Arrays.copyOfRange(parts, 1, parts.length));

            // Build mutated request
            ServerHttpRequest mutated = request.mutate()
                    .path(rebasedPath)
                    .build();

            return chain.filter(exchange.mutate().request(mutated).build());
        }

        @Override
        public int getOrder() {
            return Ordered.LOWEST_PRECEDENCE - 10; // after correlation, before CB
        }
    }

    /**
     * Filter that ensures every request has a correlation-id header
     * (incoming or freshly generated) and that it is propagated downstream.
     */
    @Slf4j
    private static class CorrelationIdFilter implements GlobalFilter, Ordered {

        public static final String CORRELATION_ID_HEADER = "X-Correlation-Id";

        @Override
        public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
            String existing = exchange.getRequest().getHeaders()
                    .getFirst(CORRELATION_ID_HEADER);
            String correlationId = StringUtils.hasText(existing)
                    ? existing
                    : UUID.randomUUID().toString();

            if (!StringUtils.hasText(existing)) {
                // Enrich request with new header
                exchange = exchange.mutate()
                        .request(exchange.getRequest()
                                .mutate()
                                .header(CORRELATION_ID_HEADER, correlationId)
                                .build())
                        .build();
            }

            // Add correlation-id to response for client convenience
            return chain.filter(exchange)
                    .doOnSubscribe(s -> log.debug("Handling request [{}] {}", correlationId,
                            exchange.getRequest().getURI()))
                    .doOnSuccess(aVoid -> exchange.getResponse().getHeaders()
                            .set(CORRELATION_ID_HEADER, correlationId));
        }

        @Override
        public int getOrder() {
            return Ordered.HIGHEST_PRECEDENCE;
        }
    }
}

/**
 * Opinionated {@link org.springframework.web.bind.annotation.ControllerAdvice} that transforms
 * Spring's exceptions into a consistent JSON envelope understood by front-ends.
 */
@Slf4j
@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice
class GlobalErrorHandler extends ResponseEntityExceptionHandler {

    private static final AntPathMatcher PATH_MATCHER = new AntPathMatcher();

    private final ObjectMapper mapper;

    GlobalErrorHandler(ObjectMapper mapper) {
        this.mapper = mapper;
    }

    // 400 – malformed request / validation
    @Override
    protected ResponseEntity<Object> handleBindException(BindException ex, HttpHeaders headers,
                                                         HttpStatusCode status, WebRequest request) {
        return buildResponse(HttpStatus.BAD_REQUEST, "Invalid payload", ex);
    }

    // 405 – wrong HTTP method
    @Override
    protected ResponseEntity<Object> handleHttpRequestMethodNotSupported(HttpRequestMethodNotSupportedException ex,
                                                                         HttpHeaders headers,
                                                                         HttpStatusCode status,
                                                                         WebRequest request) {
        return buildResponse(HttpStatus.METHOD_NOT_ALLOWED, ex.getMessage(), ex);
    }

    // 404 – route not found in Gateway
    @Override
    protected ResponseEntity<Object> handleNoHandlerFoundException(org.springframework.web.servlet.NoHandlerFoundException ex,
                                                                   HttpHeaders headers, HttpStatusCode status,
                                                                   WebRequest request) {
        return buildResponse(HttpStatus.NOT_FOUND, "Route does not exist", ex);
    }

    // Fallback handler
    @ExceptionHandler(Throwable.class)
    public ResponseEntity<ApiError> handleGeneric(Throwable ex) {
        HttpStatus status = (ex instanceof ResponseStatusException rse)
                ? rse.getStatusCode()
                : HttpStatus.INTERNAL_SERVER_ERROR;
        return buildResponse(status, "Unexpected error", ex);
    }

    private ResponseEntity<ApiError> buildResponse(HttpStatus status, String message, Throwable ex) {
        log.error("[{}] {}", status, message, ex);
        ApiError body = new ApiError(
                ZonedDateTime.now(),
                status.value(),
                status.getReasonPhrase(),
                message,
                ex.getClass().getSimpleName());

        return ResponseEntity.status(status)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body);
    }

    @Data
    @AllArgsConstructor
    @NoArgsConstructor
    static class ApiError {
        private ZonedDateTime timestamp;
        private int status;
        private String error;
        private String message;
        private String exception;
    }
}
```