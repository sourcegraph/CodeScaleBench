package com.opsforge.nexus.fileconverter.config;

import java.time.Duration;
import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCache;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.cache.interceptor.KeyGenerator;
import org.springframework.cache.interceptor.SimpleKeyGenerator;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;

import com.github.benmanes.caffeine.cache.Caffeine;

/**
 * Central cache configuration for the File Converter Service.
 * <p>
 * The CacheConfig honours the following hierarchy when deciding which cache
 * implementation to wire:
 * <ol>
 *     <li>opsforge.cache.type property – supports {@code CAFFEINE} or {@code REDIS}</li>
 *     <li>If property is missing defaults to {@code CAFFEINE}</li>
 * </ol>
 *
 * <p>
 * Each cache can be configured with a dedicated Time-To-Live (TTL) via
 * {@code opsforge.cache.ttl.*}. If no TTL is supplied for a cache, a sensible
 * service-wide default will be applied.
 * </p>
 *
 * <p>
 * Example <code>application.yaml</code>:
 *
 * <pre>{@code
 * opsforge:
 *   cache:
 *     type: REDIS
 *     default-ttl: 10m
 *     ttl:
 *       conversionResults: 5m
 *       mimeTypeLookup: 1h
 * }</pre>
 * </p>
 *
 * <p>
 * The config is intentionally technology-agnostic—should the service migrate
 * from Caffeine to, say, EhCache, only this adapter must change, leaving the
 * rest of the codebase unaffected.
 * </p>
 */
@Configuration
@EnableCaching
@EnableConfigurationProperties(CacheConfig.OpsforgeCacheProperties.class)
public class CacheConfig {

    /**
     * List of cache names used by the File Converter Service.
     * Keeping it centralised protects us from typos while providing
     * a single place to document cache semantics.
     */
    public enum CacheName {
        /**
         * Caches the output of expensive file-format conversions.
         * The key should contain a file checksum + target format.
         */
        CONVERSION_RESULTS,
        /**
         * Caches MIME-type lookups based on file extension / magic bytes.
         */
        MIME_TYPE_LOOKUP,
        /**
         * Caches checksum results to avoid recomputation for identical files.
         */
        CHECKSUM_RESULTS
    }

    /* ------------------------------------------------------------------
     * Public bean definitions
     * ------------------------------------------------------------------ */

    @Bean
    @ConditionalOnMissingBean
    public KeyGenerator keyGenerator() {
        // The build-in SimpleKeyGenerator covers 90% of cases.
        // Replace with a custom implementation if needed.
        return new SimpleKeyGenerator();
    }

    /* ---------- Caffeine fallback (default) -------------------------- */

    @Bean
    @ConditionalOnProperty(
            name = "opsforge.cache.type",
            havingValue = "CAFFEINE",
            matchIfMissing = true
    )
    public CacheManager caffeineCacheManager(
            OpsforgeCacheProperties props,
            ObjectProvider<Caffeine<Object, Object>> caffeineBuilderProvider) {

        CaffeineCacheManager manager = new CaffeineCacheManager(resolveCacheNames());
        Caffeine<Object, Object> caffeineBuilder = caffeineBuilderProvider
                .getIfAvailable(() -> Caffeine.newBuilder()
                                              .recordStats());

        Map<String, Duration> ttlMapping = toLowerCaseKeys(props.ttl());

        manager.setCaffeine(caffeineBuilder);
        manager.setCacheLoader((key, executor) -> null); // no automatic loading

        // Manually configure TTL per cache
        manager.setCacheSpecification(props.spec());

        // Spring does not expose per-cache TTL via builder API.
        // Therefore we create CaffeineCache instances manually.
        Set<String> cacheNames = resolveCacheNames();
        manager.setCaffeine(null); // disable default builder
        manager.setCaches(cacheNames.stream()
                .map(name -> new CaffeineCache(
                        name,
                        caffeineBuilder.expireAfterWrite(
                                ttlMapping.getOrDefault(name.toLowerCase(), props.defaultTtl())
                                           .toMillis())
                                       .build()))
                .collect(Collectors.toList()));

        return manager;
    }

    /* ---------- Redis (remote) -------------------------------------- */

    @Bean
    @ConditionalOnProperty(name = "opsforge.cache.type", havingValue = "REDIS")
    public CacheManager redisCacheManager(
            OpsforgeCacheProperties props,
            RedisConnectionFactory redisConnectionFactory) {

        Map<String, RedisCacheConfiguration> configPerCache = new EnumMap<>(CacheName.class);
        Map<String, Duration> ttlMapping = toLowerCaseKeys(props.ttl());

        ttlMapping.forEach((cacheName, ttl) ->
                configPerCache.put(cacheName,
                        defaultRedisConfig()
                                .entryTtl(ttl)));

        // Apply default configuration for caches without dedicated TTL
        RedisCacheConfiguration defaultConfig = defaultRedisConfig()
                .entryTtl(props.defaultTtl());

        return RedisCacheManager.builder(redisConnectionFactory)
                .cacheDefaults(defaultConfig)
                .withInitialCacheConfigurations(configPerCache)
                .build();
    }

    /* ------------------------------------------------------------------
     * Private helpers
     * ------------------------------------------------------------------ */

    private RedisCacheConfiguration defaultRedisConfig() {
        return RedisCacheConfiguration.defaultCacheConfig()
                .disableCachingNullValues(); // Null-results rarely useful
    }

    private Set<String> resolveCacheNames() {
        return Set.of(CacheName.values())
                  .stream()
                  .map(Enum::name)
                  .collect(Collectors.toUnmodifiableSet());
    }

    private Map<String, Duration> toLowerCaseKeys(Map<String, Duration> original) {
        if (original == null) {
            return Collections.emptyMap();
        }
        return original.entrySet().stream()
                .filter(e -> Objects.nonNull(e.getValue()))
                .collect(Collectors.toUnmodifiableMap(
                        e -> e.getKey().toLowerCase(),
                        Map.Entry::getValue
                ));
    }

    /* ------------------------------------------------------------------
     * Properties object
     * ------------------------------------------------------------------ */

    @ConfigurationProperties(prefix = "opsforge.cache")
    public static class OpsforgeCacheProperties {

        /**
         * Type of cache to wire. Defaults to {@link CacheType#CAFFEINE}.
         */
        private CacheType type = CacheType.CAFFEINE;

        /**
         * Global default TTL. Individual cache TTLs can override this value.
         */
        private Duration defaultTtl = Duration.ofMinutes(30);

        /**
         * Additional Caffeine spec (e.g. "maximumSize=500,expireAfterWrite=10m")
         * leaves the door open for advanced tuning.
         */
        private String spec;

        /**
         * Per-cache TTL overrides. Keys are case-insensitive cache names.
         */
        private Map<String, Duration> ttl = Collections.emptyMap();

        /* ---- getters / setters ---- */

        public CacheType getType() {
            return type;
        }

        public void setType(CacheType type) {
            this.type = Optional.ofNullable(type).orElse(CacheType.CAFFEINE);
        }

        public Duration getDefaultTtl() {
            return defaultTtl;
        }

        public void setDefaultTtl(Duration defaultTtl) {
            if (defaultTtl != null && !defaultTtl.isNegative() && !defaultTtl.isZero()) {
                this.defaultTtl = defaultTtl;
            }
        }

        public String getSpec() {
            return spec;
        }

        public void setSpec(String spec) {
            this.spec = spec;
        }

        public Map<String, Duration> getTtl() {
            return ttl;
        }

        public void setTtl(Map<String, Duration> ttl) {
            this.ttl = Optional.ofNullable(ttl).orElseGet(Collections::emptyMap);
        }
    }

    /**
     * Supported cache backends.
     */
    public enum CacheType {
        CAFFEINE,
        REDIS
    }
}