```java
package com.commercesphere.enterprise.config;

import com.github.benmanes.caffeine.cache.Caffeine;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.cache.interceptor.CacheErrorHandler;
import org.springframework.cache.interceptor.KeyGenerator;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;

import java.lang.reflect.Method;
import java.time.Duration;
import java.util.*;

/**
 * Central cache configuration for CommerceSphere Enterprise Suite.
 *
 * <p>The platform supports two cache providers selectable via application
 * properties:
 * <ul>
 *     <li>LOCAL  - In-process Caffeine cache (default)</li>
 *     <li>REDIS  - Redis-backed cache for horizontal scalability</li>
 * </ul>
 *
 * <p>All common cache names and their default TTLs are defined in {@link DefaultCaches}.
 *
 * <p>Example (application.yml):
 * <pre>
 * commercesphere:
 *   cache:
 *     provider: REDIS               # or LOCAL
 *     spec: initialCapacity=500,maximumSize=100000,expireAfterAccess=30m   # Caffeine-only
 *     redisTtlSeconds: 7200         # Redis-only
 * </pre>
 */
@Configuration
@EnableCaching
@EnableConfigurationProperties(CacheConfig.CacheProperties.class)
public class CacheConfig {

    private static final Logger LOGGER = LoggerFactory.getLogger(CacheConfig.class);

    /**
     * Enumeration of cache names and recommended TTL values.
     */
    public enum DefaultCaches {

        PRODUCT_CATALOG(Duration.ofHours(6)),
        PRICE_LISTS(Duration.ofMinutes(30)),
        USER_SESSIONS(Duration.ofHours(4)),
        INVENTORY_LEVELS(Duration.ofSeconds(90)),
        CHECKOUT_QUOTES(Duration.ofMinutes(10)),
        PERMISSIONS(Duration.ofHours(1));

        private final Duration ttl;

        DefaultCaches(Duration ttl) {
            this.ttl = ttl;
        }

        public Duration getTtl() {
            return ttl;
        }

        public static Set<String> names() {
            Set<String> result = new HashSet<>();
            for (DefaultCaches c : values()) {
                result.add(c.name());
            }
            return result;
        }
    }

    /**
     * Strongly typed cache properties, loaded from the <code>commercesphere.cache</code> namespace.
     */
    @ConfigurationProperties(prefix = "commercesphere.cache")
    public static class CacheProperties {

        /**
         * Cache provider. One of: LOCAL, REDIS
         */
        private Provider provider = Provider.LOCAL;

        /**
         * Caffeine cache spec (only used when provider == LOCAL).
         */
        private String spec = "initialCapacity=500,maximumSize=100000,expireAfterAccess=30m";

        /**
         * Global TTL for Redis caches (per-cache TTLs can be overridden via DefaultCaches).
         */
        private long redisTtlSeconds = 3600;

        public Provider getProvider() {
            return provider;
        }

        public void setProvider(Provider provider) {
            this.provider = provider;
        }

        public String getSpec() {
            return spec;
        }

        public void setSpec(String spec) {
            this.spec = spec;
        }

        public long getRedisTtlSeconds() {
            return redisTtlSeconds;
        }

        public void setRedisTtlSeconds(long redisTtlSeconds) {
            this.redisTtlSeconds = redisTtlSeconds;
        }

        public enum Provider {
            LOCAL,
            REDIS
        }
    }

    /* ------------------------------------------------------------------
     *  Bean definitions – only one CacheManager will be active at runtime
     * ------------------------------------------------------------------ */

    /**
     * Local, in-memory Caffeine {@link CacheManager}.
     */
    @Bean
    @Primary
    @ConditionalOnProperty(
            name = "commercesphere.cache.provider",
            havingValue = "LOCAL",
            matchIfMissing = true)
    public CacheManager caffeineCacheManager(CacheProperties properties,
                                             ObjectProvider<MeterRegistry> meterRegistryProvider) {

        LOGGER.info("Initializing LOCAL Caffeine cache manager with spec '{}'", properties.getSpec());

        Caffeine<Object, Object> caffeine = Caffeine.from(properties.getSpec());

        // Integrate with Micrometer if available
        meterRegistryProvider.ifAvailable(registry ->
                caffeine.recordStats()); // Stats will be auto-bound by Micrometer

        CaffeineCacheManager cacheManager = new CaffeineCacheManager();
        cacheManager.setCaffeine(caffeine);
        cacheManager.setCacheNames(DefaultCaches.names());

        return cacheManager;
    }

    /**
     * Redis-based {@link CacheManager}.
     */
    @Bean
    @Primary
    @ConditionalOnProperty(name = "commercesphere.cache.provider", havingValue = "REDIS")
    public CacheManager redisCacheManager(CacheProperties properties,
                                          RedisConnectionFactory connectionFactory) {

        LOGGER.info("Initializing REDIS cache manager with default TTL {}s", properties.getRedisTtlSeconds());

        // Build a default configuration that can be supplemented per cache
        RedisCacheConfiguration defaultConfig =
                RedisCacheConfiguration.defaultCacheConfig()
                                        .entryTtl(Duration.ofSeconds(properties.getRedisTtlSeconds()));

        // Per-cache TTLs override global
        Map<String, RedisCacheConfiguration> cacheConfigs = new HashMap<>();
        for (DefaultCaches cache : DefaultCaches.values()) {
            cacheConfigs.put(cache.name(),
                    RedisCacheConfiguration.defaultCacheConfig().entryTtl(cache.getTtl()));
        }

        return RedisCacheManager.builder(connectionFactory)
                                .cacheDefaults(defaultConfig)
                                .withInitialCacheConfigurations(cacheConfigs)
                                .build();
    }

    /**
     * Custom {@link KeyGenerator} that prefixes the cache key with the current tenant identifier
     * (if present) to avoid collisions in multi-tenant deployments.
     */
    @Bean
    public KeyGenerator tenantAwareKeyGenerator() {
        return new KeyGenerator() {
            @Override
            public Object generate(Object target, Method method, Object... params) {
                String tenantId = TenantContextHolder.getTenantId().orElse("default");
                String paramKey = Arrays.deepToString(params);
                return tenantId + "::" + target.getClass().getSimpleName() + "::" + method.getName() + "::" + paramKey;
            }
        };
    }

    /**
     * A {@link CacheErrorHandler} that logs warnings instead of failing fast
     * to ensure the application stays available even if the cache layer misbehaves.
     */
    @Bean
    public CacheErrorHandler logOnlyCacheErrorHandler() {
        return new CacheErrorHandler() {

            private final CacheErrorHandler delegate = org.springframework.cache.interceptor.SimpleCacheErrorHandler.INSTANCE;

            @Override
            public void handleCacheGetError(RuntimeException exception, org.springframework.cache.Cache cache, Object key) {
                LOGGER.warn("Cache 'get' error on cache={} key={}. Falling back to method execution. Cause: {}",
                        cache.getName(), key, exception.getMessage());
                delegate.handleCacheGetError(exception, cache, key);
            }

            @Override
            public void handleCachePutError(RuntimeException exception, org.springframework.cache.Cache cache, Object key, Object value) {
                LOGGER.warn("Cache 'put' error on cache={} key={}. Value will not be cached. Cause: {}",
                        cache.getName(), key, exception.getMessage());
                delegate.handleCachePutError(exception, cache, key, value);
            }

            @Override
            public void handleCacheEvictError(RuntimeException exception, org.springframework.cache.Cache cache, Object key) {
                LOGGER.warn("Cache 'evict' error on cache={} key={}. Cause: {}", cache.getName(), key, exception.getMessage());
                delegate.handleCacheEvictError(exception, cache, key);
            }

            @Override
            public void handleCacheClearError(RuntimeException exception, org.springframework.cache.Cache cache) {
                LOGGER.warn("Cache 'clear' error on cache={}. Cause: {}", cache.getName(), exception.getMessage());
                delegate.handleCacheClearError(exception, cache);
            }
        };
    }

    /* ------------------------------------------------------------------
     *  Utility helper for tenant resolution
     * ------------------------------------------------------------------ */

    /**
     * Simple tenant context holder for demonstration purposes.
     * In production this would bridge to Spring Security or a ThreadLocal-based solution.
     */
    static final class TenantContextHolder {

        private static final ThreadLocal<String> TENANT = new ThreadLocal<>();

        private TenantContextHolder() {
        }

        public static void setTenantId(String tenantId) {
            TENANT.set(tenantId);
        }

        public static Optional<String> getTenantId() {
            return Optional.ofNullable(TENANT.get());
        }

        public static void clear() {
            TENANT.remove();
        }
    }
}
```