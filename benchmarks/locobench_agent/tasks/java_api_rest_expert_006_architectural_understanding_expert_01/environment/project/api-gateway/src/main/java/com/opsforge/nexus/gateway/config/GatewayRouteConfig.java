package com.opsforge.nexus.gateway.config;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.GatewayFilter;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.ratelimit.KeyResolver;
import org.springframework.cloud.gateway.filter.ratelimit.RedisRateLimiter;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.Base64;
import java.util.Optional;
import java.util.UUID;

/**
 * Central routing configuration for OpsForge Utility Nexus API Gateway.
 * <p>
 * It wires together all downstream utility micro-services, attaches
 * cross-cutting filters (rate-limiting, circuit-breaking, correlation-id
 * propagation, etc.) and exposes a single, cohesive contract to callers.
 */
@Configuration
public class GatewayRouteConfig {

    /* --------------------------------------------------------------------- */
    /* Downstream service base URIs (externalised for environment flexibility) */
    /* --------------------------------------------------------------------- */

    @Value("${utility-services.file-conversion.base-uri}")
    private String fileConversionServiceBaseUri;

    @Value("${utility-services.data-anonymization.base-uri}")
    private String dataAnonymizationServiceBaseUri;

    @Value("${utility-services.timezone-scheduler.base-uri}")
    private String timezoneSchedulerServiceBaseUri;

    @Value("${utility-services.checksum.base-uri}")
    private String checksumServiceBaseUri;

    @Value("${utility-services.bulk-text.base-uri}")
    private String bulkTextServiceBaseUri;

    /* --------------------------------------------------------------------- */
    /* Route definitions                                                     */
    /* --------------------------------------------------------------------- */

    @Bean
    public RouteLocator routeLocator(RouteLocatorBuilder builder,
                                     RedisRateLimiter redisRateLimiter,
                                     KeyResolver userKeyResolver) {

        return builder.routes()

                /* ------------------ FILE CONVERSION ------------------ */
                .route("file-conversion-v1", r -> r
                        .path("/api/v1/convert/**")
                        .filters(f -> f
                                .stripPrefix(2)
                                .filter(new CorrelationIdGatewayFilter())
                                .requestRateLimiter(c -> c
                                        .setRateLimiter(redisRateLimiter)
                                        .setKeyResolver(userKeyResolver)
                                        .setStatusCode(HttpStatus.TOO_MANY_REQUESTS))
                                .circuitBreaker(cb -> cb
                                        .setName("fileConversionCircuitBreaker")
                                        .setFallbackUri("forward:/fallback/file-conversion"))
                                .addRequestHeader(HttpHeaders.ACCEPT, "application/json;v=1"))
                        .uri(fileConversionServiceBaseUri))

                /* ---------------- DATA ANONYMIZATION ----------------- */
                .route("data-anonymization-v1", r -> r
                        .path("/api/v1/anonymize/**")
                        .filters(f -> f
                                .stripPrefix(2)
                                .filter(new CorrelationIdGatewayFilter())
                                .requestRateLimiter(c -> c
                                        .setRateLimiter(redisRateLimiter)
                                        .setKeyResolver(userKeyResolver)
                                        .setStatusCode(HttpStatus.TOO_MANY_REQUESTS))
                                .circuitBreaker(cb -> cb
                                        .setName("dataAnonymizationCircuitBreaker")
                                        .setFallbackUri("forward:/fallback/data-anonymization")))
                        .uri(dataAnonymizationServiceBaseUri))

                /* -------------- TIME-ZONE AWARE SCHEDULER ------------- */
                .route("timezone-scheduler-v1", r -> r
                        .path("/api/v1/schedule/**")
                        .filters(f -> f
                                .stripPrefix(2)
                                .filter(new CorrelationIdGatewayFilter())
                                .circuitBreaker(cb -> cb
                                        .setName("schedulerCircuitBreaker")
                                        .setFallbackUri("forward:/fallback/scheduler")))
                        .uri(timezoneSchedulerServiceBaseUri))

                /* ------------------- CHECKSUM TOOL ------------------- */
                .route("checksum-v1", r -> r
                        .path("/api/v1/checksum/**")
                        .filters(f -> f
                                .stripPrefix(2)
                                .filter(new CorrelationIdGatewayFilter()))
                        .uri(checksumServiceBaseUri))

                /* ------------- BULK TEXT TRANSFORMATIONS -------------- */
                .route("bulk-text-v1", r -> r
                        .path("/api/v1/transform/**")
                        .filters(f -> f
                                .stripPrefix(2)
                                .filter(new CorrelationIdGatewayFilter()))
                        .uri(bulkTextServiceBaseUri))

                /* --------------------- GRAPHQL ------------------------ */
                .route("graphql-router", r -> r
                        .path("/graphql/**")
                        .filters(f -> f
                                .filter(new CorrelationIdGatewayFilter()))
                        /* Load-balancer discovery name for the GraphQL orchestrator */
                        .uri("lb://graphql-orchestrator"))

                .build();
    }

    /* --------------------------------------------------------------------- */
    /* Rate-limiting & Key resolution                                        */
    /* --------------------------------------------------------------------- */

    /**
     * Reactive Redis-backed rate limiter.
     * <p>
     * Default values can be overridden via properties:
     * gateway.ratelimit.replenishRate and gateway.ratelimit.burstCapacity
     */
    @Bean
    public RedisRateLimiter redisRateLimiter(
            @Value("${gateway.ratelimit.replenishRate:20}") int replenishRate,
            @Value("${gateway.ratelimit.burstCapacity:10}") int burstCapacity) {

        return new RedisRateLimiter(replenishRate, burstCapacity);
    }

    /**
     * Resolves a unique rate-limit key per consumer.
     * <p>
     * Priorities:
     *   1. JWT subject (Authorization header)
     *   2. X-API-Key header
     *   3. Remote IP address
     */
    @Bean
    public KeyResolver userKeyResolver() {
        return exchange -> Mono.fromSupplier(() -> {
            Optional<String> jwtSub = extractJwtSubject(exchange.getRequest().getHeaders());
            if (jwtSub.isPresent()) {
                return jwtSub.get();
            }

            String apiKey = exchange.getRequest().getHeaders().getFirst("X-API-Key");
            if (apiKey != null && !apiKey.isBlank()) {
                return apiKey;
            }

            return exchange.getRequest().getRemoteAddress() == null
                    ? "anonymous"
                    : exchange.getRequest().getRemoteAddress().getAddress().getHostAddress();
        });
    }

    /* --------------------------------------------------------------------- */
    /* Helper utilities                                                      */
    /* --------------------------------------------------------------------- */

    private Optional<String> extractJwtSubject(HttpHeaders headers) {
        return Optional.ofNullable(headers.getFirst(HttpHeaders.AUTHORIZATION))
                .filter(auth -> auth.startsWith("Bearer "))
                .map(auth -> auth.replaceFirst("Bearer ", ""))
                .flatMap(token -> {
                    try {
                        String[] chunks = token.split("\\.");
                        if (chunks.length < 2) {
                            return Optional.empty();
                        }
                        String payloadJson =
                                new String(Base64.getUrlDecoder().decode(chunks[1]));
                        ObjectMapper mapper = new ObjectMapper();
                        JsonNode node = mapper.readTree(payloadJson);
                        return Optional.ofNullable(node.get("sub")).map(JsonNode::asText);
                    } catch (Exception ignored) {
                        return Optional.empty(); // Malformed token or JSON parsing error
                    }
                });
    }

    /* --------------------------------------------------------------------- */
    /* Correlation-id gateway filter                                          */
    /* --------------------------------------------------------------------- */

    /**
     * Enriches every request with an <code>X-Correlation-Id</code> HTTP header
     * if the client did not set one already, enabling end-to-end tracing across
     * the platform.
     */
    private static final class CorrelationIdGatewayFilter implements GatewayFilter, Ordered {

        static final String CORRELATION_ID_HEADER = "X-Correlation-Id";

        @Override
        public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
            String correlationId = exchange.getRequest().getHeaders().getFirst(CORRELATION_ID_HEADER);
            ServerWebExchange mutatedExchange = exchange;

            if (correlationId == null || correlationId.isBlank()) {
                correlationId = UUID.randomUUID().toString();
                mutatedExchange = exchange.mutate()
                        .request(builder -> builder.header(CORRELATION_ID_HEADER, correlationId))
                        .build();
            }

            mutatedExchange.getAttributes().put(CORRELATION_ID_HEADER, correlationId);
            return chain.filter(mutatedExchange);
        }

        @Override
        public int getOrder() {
            // Execute early but still allow built-in pre-filters (like metrics) to run first
            return -100;
        }
    }
}