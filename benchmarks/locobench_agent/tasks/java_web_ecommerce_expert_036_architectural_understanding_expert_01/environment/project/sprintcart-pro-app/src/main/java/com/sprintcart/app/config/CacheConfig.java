package com.sprintcart.app.config;

import com.github.benmanes.caffeine.cache.Caffeine;
import java.lang.reflect.Method;
import java.time.Duration;
import java.util.Arrays;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.CachingConfigurerSupport;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.interceptor.CacheErrorHandler;
import org.springframework.cache.interceptor.KeyGenerator;
import org.springframework.cache.interceptor.SimpleCacheErrorHandler;
import org.springframework.cache.support.CompositeCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.lang.NonNull;
import org.springframework.lang.Nullable;
import org.springframework.util.DigestUtils;
import org.springframework.util.StringUtils;

/**
 * Centralized cache configuration for SprintCart Pro.
 *
 * <p>The application uses a two–tier cache strategy:</p>
 * <ol>
 *     <li>Local (in–JVM) Caffeine caches for ultra-low latency.</li>
 *     <li>Distributed Redis caches for cross-instance coherence.</li>
 * </ol>
 *
 * <p>If a {@link RedisConnectionFactory} bean is present in the context, both tiers are wired
 * together via a {@link CompositeCacheManager}. Otherwise, the configuration transparently
 * falls back to Caffeine-only.</p>
 *
 * <p>All cache keys are automatically prefixed with the current tenant identifier (see
 * {@link TenantContext}) to guarantee strict data isolation in multi-tenant deployments.</p>
 */
@Configuration
@EnableCaching
public class CacheConfig extends CachingConfigurerSupport {

    private static final Logger log = LoggerFactory.getLogger(CacheConfig.class);

    /* ********************
     *  Cache name constants
     * ********************/
    public static final String PRODUCT_CACHE   = "products";
    public static final String CATEGORY_CACHE  = "categories";
    public static final String PRICE_CACHE     = "prices";
    public static final String INVENTORY_CACHE = "inventory";
    public static final String ORDER_CACHE     = "orders";
    public static final String PAGE_CACHE      = "pages";

    /**
     * Creates the active {@link CacheManager}.
     *
     * @param redisConnectionFactory optional Redis connection factory (autowired if available)
     * @return either a {@link CompositeCacheManager} (Caffeine + Redis) or a
     *         {@link org.springframework.cache.caffeine.CaffeineCacheManager}.
     */
    @Bean
    public CacheManager cacheManager(
            @Nullable RedisConnectionFactory redisConnectionFactory
    ) {

        /* -------- Local Caffeine cache manager -------- */
        org.springframework.cache.caffeine.CaffeineCacheManager caffeine = new org.springframework.cache.caffeine.CaffeineCacheManager(
                PRODUCT_CACHE,
                CATEGORY_CACHE,
                PRICE_CACHE,
                INVENTORY_CACHE,
                ORDER_CACHE,
                PAGE_CACHE
        );
        caffeine.setCaffeine(caffeineSpec());
        caffeine.setAllowNullValues(false);

        /*
         * When Redis is on the classpath & configured, compose both managers
         * so the 1st-level lookup hits Caffeine and falls back to Redis.
         */
        if (redisConnectionFactory != null) {
            log.info("RedisConnectionFactory detected – enabling two-tier (Caffeine → Redis) cache.");
            RedisCacheConfiguration redisConfig = RedisCacheConfiguration.defaultCacheConfig()
                    .serializeKeysWith(RedisCacheConfiguration.keySerializationPair()) // default (String serializer)
                    .serializeValuesWith(RedisCacheConfiguration.valueSerializationPair()) // GenericJackson2Json serializer
                    .entryTtl(Duration.ofMinutes(60)) // sensible default; per-cache overrides happen via @Cacheable
                    .disableCachingNullValues();

            RedisCacheManager redis = RedisCacheManager.builder(redisConnectionFactory)
                    .cacheDefaults(redisConfig)
                    .transactionAware()
                    .build();

            CompositeCacheManager composite = new CompositeCacheManager(caffeine, redis);
            composite.setFallbackToNoOpCache(false);
            return composite;
        }

        log.warn("No RedisConnectionFactory found – falling back to single-node Caffeine cache.");
        return caffeine;
    }

    /**
     * Defines the standard Caffeine cache specification.
     *
     * @return a configured {@link Caffeine} builder
     */
    @Bean
    @ConditionalOnClass(Caffeine.class)
    public Caffeine<Object, Object> caffeineSpec() {
        return Caffeine.newBuilder()
                .recordStats()
                .initialCapacity(256)
                .maximumSize(20_000)
                .expireAfterAccess(10, TimeUnit.MINUTES)
                .expireAfterWrite(30, TimeUnit.MINUTES)
                .removalListener((key, value, cause) ->
                        log.debug("Evicting key [{}] due to [{}]", key, cause));
    }

    /* *****************************************************************************************
     *  ----------  CachingConfigurerSupport customizations (key generator & error handling) ---
     * *****************************************************************************************/

    /**
     * Generates cache keys that respect the current tenant context and avoid long strings by
     * hashing the method parameters.
     *
     * <pre>
     * {@code
     * tenantId:com.sprintcart.domain.ProductService::findAll::5d41402abc4
     * }
     * </pre>
     */
    @Bean
    @Override
    public KeyGenerator keyGenerator() {
        return (Object target, Method method, Object... params) -> {
            String tenant = TenantContext.getTenant().orElse("public");
            String digest = DigestUtils.md5DigestAsHex(Arrays.deepToString(params).getBytes());
            return String.format("%s:%s::%s::%s",
                    tenant,
                    target.getClass().getName(),
                    method.getName(),
                    digest.substring(0, 12) // shorten for readability
            );
        };
    }

    /**
     * Custom {@link CacheErrorHandler} that downgrades cache errors to WARN level
     * instead of propagating them, ensuring the application remains resilient even
     * during partial cache outages.
     */
    @Bean
    @Override
    public CacheErrorHandler errorHandler() {
        return new LoggingCacheErrorHandler();
    }

    /* *****************
     *  Helper classes
     * *****************/

    /**
     * Thread-local holder for the current tenant identifier.
     *
     * <p>This is a minimal implementation. In real deployments, the tenant would be resolved
     * by an authentication filter or part of the request metadata.</p>
     */
    public static final class TenantContext {

        private static final ThreadLocal<String> CURRENT_TENANT = new InheritableThreadLocal<>();

        private TenantContext() {
        }

        /**
         * @return an {@link Optional} containing the current tenant, or empty if none has been set
         */
        public static Optional<String> getTenant() {
            return Optional.ofNullable(CURRENT_TENANT.get());
        }

        /**
         * Sets the tenant for the current thread.
         */
        public static void setTenant(@NonNull String tenant) {
            CURRENT_TENANT.set(StringUtils.trimWhitespace(tenant));
        }

        /**
         * Clears the tenant from the current thread to avoid memory leaks in pooled threads.
         */
        public static void clear() {
            CURRENT_TENANT.remove();
        }
    }

    /**
     * Logs cache errors without bubbling them up.
     */
    private static class LoggingCacheErrorHandler extends SimpleCacheErrorHandler {

        @Override
        public void handleCacheGetError(@NonNull RuntimeException exception, @NonNull org.springframework.cache.Cache cache, @NonNull Object key) {
            log.warn("Cache GET error on cache [{}] for key [{}]: {}", cache.getName(), key, exception.getMessage());
        }

        @Override
        public void handleCachePutError(@NonNull RuntimeException exception, @NonNull org.springframework.cache.Cache cache, @NonNull Object key, @Nullable Object value) {
            log.warn("Cache PUT error on cache [{}] for key [{}]: {}", cache.getName(), key, exception.getMessage());
        }

        @Override
        public void handleCacheEvictError(@NonNull RuntimeException exception, @NonNull org.springframework.cache.Cache cache, @NonNull Object key) {
            log.warn("Cache EVICT error on cache [{}] for key [{}]: {}", cache.getName(), key, exception.getMessage());
        }

        @Override
        public void handleCacheClearError(@NonNull RuntimeException exception, @NonNull org.springframework.cache.Cache cache) {
            log.warn("Cache CLEAR error on cache [{}]: {}", cache.getName(), exception.getMessage());
        }
    }
}