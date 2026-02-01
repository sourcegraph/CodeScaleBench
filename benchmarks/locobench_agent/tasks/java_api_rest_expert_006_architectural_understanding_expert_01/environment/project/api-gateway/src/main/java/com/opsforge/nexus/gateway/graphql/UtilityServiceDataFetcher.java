```java
package com.opsforge.nexus.gateway.graphql;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.opsforge.nexus.gateway.service.UtilityDispatchService;
import com.opsforge.nexus.gateway.service.model.DispatchResponse;
import graphql.GraphQLException;
import graphql.schema.DataFetcher;
import graphql.schema.DataFetchingEnvironment;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;

/**
 * GraphQL {@link DataFetcher} that acts as a single entry-point for every “utility” exposed at the
 * API-Gateway layer. The actual invocation is delegated to {@link UtilityDispatchService}, which
 * abstracts transport concerns (REST, gRPC, AMQP, etc.). <p/>
 *
 * Design goals:
 * <ul>
 *     <li>Centralised error handling translated into GraphQL exceptions</li>
 *     <li>Optional, pluggable response-level caching using Caffeine</li>
 *     <li>Micrometer metrics for observability</li>
 *     <li>Non-blocking, <b>CF-based</b> execution for back-pressure friendliness</li>
 * </ul>
 */
@Slf4j
@Component
@SuppressWarnings("unchecked")
public class UtilityServiceDataFetcher implements DataFetcher<CompletableFuture<Object>> {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final UtilityDispatchService dispatchService;
    private final Cache<String, Object> responseCache;
    private final Counter cacheHitCounter;
    private final Counter cacheMissCounter;

    public UtilityServiceDataFetcher(final UtilityDispatchService dispatchService,
                                     final MeterRegistry meterRegistry,
                                     @Value("${opsforge.gateway.cache.ttl-seconds:300}") int ttlSeconds,
                                     @Value("${opsforge.gateway.cache.maximum-size:10_000}") long maximumSize) {

        this.dispatchService = Objects.requireNonNull(dispatchService, "dispatchService must not be null");

        this.responseCache = Caffeine.newBuilder()
                .maximumSize(maximumSize)
                .expireAfterWrite(Duration.ofSeconds(ttlSeconds))
                .recordStats()
                .build();

        // Metrics
        this.cacheHitCounter = Counter.builder("graphql.utility.cache.hit")
                                      .description("Number of cache hits for utility responses")
                                      .register(meterRegistry);

        this.cacheMissCounter = Counter.builder("graphql.utility.cache.miss")
                                       .description("Number of cache misses for utility responses")
                                       .register(meterRegistry);

        log.info("UtilityServiceDataFetcher initialised [cacheTtl={}s, cacheSize={}]", ttlSeconds, maximumSize);
    }

    /**
     * Executes a GraphQL field call by routing it to the underlying {@link UtilityDispatchService}.
     */
    @Override
    @NonNull
    public CompletableFuture<Object> get(@NonNull DataFetchingEnvironment env) {
        final String utility = env.getField().getName(); // e.g., convertCsvToJson, md5Checksum, etc.
        final Map<String, Object> arguments = env.getArguments();

        final String cacheKey = buildCacheKey(utility, arguments);
        final boolean cacheable = dispatchService.isCacheable(utility);

        if (cacheable) {
            Object cached = responseCache.getIfPresent(cacheKey);
            if (cached != null) {
                cacheHitCounter.increment();
                return CompletableFuture.completedFuture(cached);
            }
            cacheMissCounter.increment();
        }

        return CompletableFuture
                .supplyAsync(() -> executeUtilityCall(utility, arguments))
                .thenApply(result -> {
                    // Store in cache if appropriate
                    if (cacheable) {
                        responseCache.put(cacheKey, result);
                    }
                    return result;
                });
    }

    /**
     * Delegates execution to the dispatch service, performing error translation along the way.
     */
    private Object executeUtilityCall(final String utility,
                                      final Map<String, Object> args) {

        long startNanos = System.nanoTime();
        try {
            DispatchResponse<?> response = dispatchService.invokeUtility(utility, args);

            // Domain-level errors are mapped here to GraphQL-level exceptions
            if (!response.isSuccess()) {
                throw new GraphQLException(response.getErrorMessage());
            }
            return response.getPayload();

        } catch (IllegalArgumentException ex) {
            log.warn("Bad request when invoking utility '{}': {}", utility, ex.getMessage());
            throw new GraphQLException("Invalid arguments for utility '" + utility + "': " + ex.getMessage(), ex);

        } catch (Exception ex) {
            log.error("Unexpected error when invoking utility '{}'", utility, ex);
            // Wrap checked/unchecked errors into a GraphQL-friendly exception
            throw new CompletionException(new GraphQLException(
                    "Utility '" + utility + "' failed: " + ex.getMessage(), ex));

        } finally {
            long durationMs = (System.nanoTime() - startNanos) / 1_000_000;
            log.debug("Utility '{}' executed in {} ms", utility, durationMs);
        }
    }

    /**
     * Creates a deterministic cache key for a given utility call.
     */
    private static String buildCacheKey(final String utility, final Map<String, Object> args) {
        try {
            return utility + ':' + MAPPER.writeValueAsString(Optional.ofNullable(args).orElse(Map.of()));
        } catch (JsonProcessingException e) {
            // Fallback to naive .toString() representation (should never happen)
            return utility + ':' + Objects.toString(args);
        }
    }
}
```