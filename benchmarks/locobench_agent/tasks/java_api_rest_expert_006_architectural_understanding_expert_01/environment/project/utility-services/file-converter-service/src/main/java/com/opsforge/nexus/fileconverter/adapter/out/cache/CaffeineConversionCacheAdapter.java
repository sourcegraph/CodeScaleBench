package com.opsforge.nexus.fileconverter.adapter.out.cache;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.opsforge.nexus.fileconverter.application.port.out.ConversionCachePort;
import com.opsforge.nexus.fileconverter.domain.model.FileConversionResult;
import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Caffeine-based implementation of {@link ConversionCachePort}. <br>
 * <br>
 * Responsibilities:
 * <ul>
 *     <li>Stores {@link FileConversionResult} instances keyed by a deterministic hash produced by the caller.</li>
 *     <li>Applies size- and time-based eviction policies.</li>
 *     <li>Encapsulates cache invalidation semantics so that business logic remains technology-agnostic.</li>
 * </ul>
 *
 * The adapter is intentionally package-private; only the {@link ConversionCachePort} abstraction is visible
 * to the application layer.
 */
@Component
class CaffeineConversionCacheAdapter implements ConversionCachePort, DisposableBean {

    private static final Logger log = LoggerFactory.getLogger(CaffeineConversionCacheAdapter.class);

    private final Cache<String, FileConversionResult> delegate;
    private final Duration ttl;

    CaffeineConversionCacheAdapter(
            @Value("${utility-nexus.file-converter.cache.max-size:10000}") long maxSize,
            @Value("${utility-nexus.file-converter.cache.ttl-minutes:30}") long ttlMinutes,
            @Value("${utility-nexus.file-converter.cache.initial-capacity:128}") int initialCapacity) {

        this.ttl = Duration.ofMinutes(ttlMinutes);
        this.delegate = Caffeine.newBuilder()
                .maximumSize(maxSize)
                .expireAfterWrite(ttl)
                .initialCapacity(initialCapacity)
                .recordStats()
                .build();

        log.info("Initialized CaffeineConversionCacheAdapter [maxSize={}, ttl={}, initialCapacity={}]",
                maxSize, ttl, initialCapacity);
    }

    /**
     * Attempt to retrieve a cached {@link FileConversionResult}.
     *
     * @param cacheKey The deterministic key built from input file hash + source/target formats.
     * @return Optional containing the cached result if present and not yet expired.
     */
    @Override
    public Optional<FileConversionResult> find(String cacheKey) {
        try {
            FileConversionResult result = delegate.getIfPresent(cacheKey);
            return Optional.ofNullable(result);
        } catch (Exception e) {
            // Defensive: never propagate cache failures to the business layer
            log.warn("Failed to retrieve conversion result from cache for key={}", cacheKey, e);
            return Optional.empty();
        }
    }

    /**
     * Store a conversion result in the cache. Existing entry (if any) will be replaced.
     *
     * @param cacheKey Deterministic cache key.
     * @param result   The conversion result to cache.
     */
    @Override
    public void put(String cacheKey, FileConversionResult result) {
        try {
            delegate.put(cacheKey, result);
        } catch (Exception e) {
            log.warn("Failed to write conversion result to cache for key={}", cacheKey, e);
            // swallow – caching must never break the primary flow
        }
    }

    /**
     * Invalidate a single entry by key.
     *
     * @param cacheKey The key to evict.
     */
    @Override
    public void evict(String cacheKey) {
        delegate.invalidate(cacheKey);
    }

    /**
     * Invalidate all entries for a given predicate (or entire cache if predicate is null).
     * For now, we simply clear the entire cache as our keys are already granular.
     */
    @Override
    public void clear() {
        delegate.invalidateAll();
    }

    /**
     * Expose Caffeine statistics for monitoring tools like Micrometer.
     */
    @Override
    public CacheStats stats() {
        com.github.benmanes.caffeine.cache.stats.CacheStats stats = delegate.stats();
        return new CacheStats(
                stats.hitCount(),
                stats.missCount(),
                stats.evictionCount(),
                stats.loadSuccessCount(),
                stats.loadFailureCount(),
                ttl.toMinutes(),
                delegate.estimatedSize());
    }

    /**
     * Clean up resources on context shutdown.
     */
    @Override
    public void destroy() {
        log.info("Shutting down CaffeineConversionCacheAdapter — estimatedSize={} entries, finalStats={}",
                delegate.estimatedSize(), delegate.stats());
        delegate.invalidateAll();
        delegate.cleanUp();
    }
}