package com.opsforge.nexus.gateway.config;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.github.bucket4j.*;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.TimeUnit;

/**
 * Centralized configuration for request-level rate limiting.
 *
 * <p>The implementation is backed by Bucket4j and Caffeine, allowing five-nines
 * performance without the need for a network round-trip. In clustered
 * environments, the cache can be swapped for Redis or Hazelcast by replacing the
 * {@code Cache<String, Bucket>} bean—thanks to the hexagonal architecture, no
 * other class requires modification.</p>
 *
 * <p>Configuration is externalized under the {@code nexus.gateway.rate-limit}
 * prefix. Example:</p>
 *
 * <pre>{@code
 * nexus:
 *   gateway:
 *     rate-limit:
 *       enabled: true
 *       default:
 *         capacity: 1000
 *         refill-tokens: 1000
 *         refill-period: 1
 *         time-unit: MINUTES
 *       custom-limits:
 *         /api/v1/conversion/**:
 *           capacity: 200
 *           refill-tokens: 200
 *           refill-period: 1
 *           time-unit: MINUTES
 * }</pre>
 */
@Configuration
@EnableConfigurationProperties(RateLimitingConfig.RateLimitProperties.class)
public class RateLimitingConfig {

    private static final Logger log = LoggerFactory.getLogger(RateLimitingConfig.class);

    private static final String HEADER_API_KEY = "X-API-KEY";
    private static final String HEADER_LIMIT_REMAINING = "X-Rate-Limit-Remaining";
    private static final String HEADER_LIMIT_RETRY_AFTER = "Retry-After";

    private final RateLimitProperties props;
    private final MeterRegistry meterRegistry;

    public RateLimitingConfig(RateLimitProperties props, MeterRegistry meterRegistry) {
        this.props = props;
        this.meterRegistry = meterRegistry;
    }

    /**
     * In-memory cache that stores a {@link Bucket} per unique client key.
     * <p>
     * The cache is configured with a TTL equal to twice the longest refill
     * period to avoid unbounded growth.
     * </p>
     */
    @Bean
    public Cache<String, Bucket> bucketCache() {
        long longestRefillSeconds = props.longestRefillPeriodSeconds();
        return Caffeine.newBuilder()
                .expireAfterAccess(2 * longestRefillSeconds, TimeUnit.SECONDS)
                .maximumSize(50_000) // prevent runaway cache in case of DDoS
                .build();
    }

    /**
     * Registers the servlet filter only if rate limiting is enabled in
     * configuration (enabled by default).
     */
    @Bean
    @ConditionalOnProperty(prefix = "nexus.gateway.rate-limit", name = "enabled", havingValue = "true", matchIfMissing = true)
    public RateLimitingFilter rateLimitingFilter(Cache<String, Bucket> bucketCache) {
        return new RateLimitingFilter(props, bucketCache, meterRegistry);
    }

    /**
     * Filter responsible for applying the rate limiting rules.
     */
    static final class RateLimitingFilter extends OncePerRequestFilter implements InitializingBean {

        private final RateLimitProperties props;
        private final Cache<String, Bucket> bucketCache;
        private final Counter rejectedCounter;

        RateLimitingFilter(RateLimitProperties props,
                           Cache<String, Bucket> bucketCache,
                           MeterRegistry meterRegistry) {
            this.props = props;
            this.bucketCache = bucketCache;
            this.rejectedCounter = Counter.builder("nexus.gateway.rate.rejected")
                                          .description("Requests rejected due to rate limit")
                                          .register(meterRegistry);
        }

        @Override
        public void afterPropertiesSet() {
            log.info("Rate limiting enabled with default capacity={} tokens per {} {}",
                    props.getDefaultLimit().capacity,
                    props.getDefaultLimit().refillPeriod,
                    props.getDefaultLimit().timeUnit);
        }

        @Override
        protected void doFilterInternal(HttpServletRequest request,
                                        HttpServletResponse response,
                                        FilterChain filterChain)
                throws ServletException, IOException {

            String routeKey = request.getRequestURI();
            RateLimit limit = props.resolveLimitForRoute(routeKey);
            String clientKey = resolveClientKey(request);

            Bucket bucket = bucketCache.get(clientKey, k -> createBucket(limit));

            ConsumptionProbe probe = bucket.tryConsumeAndReturnRemaining(1);
            if (probe.isConsumed()) {
                // Successful request – propagate remaining tokens downstream
                response.addHeader(HEADER_LIMIT_REMAINING, String.valueOf(probe.getRemainingTokens()));
                filterChain.doFilter(request, response);
            } else {
                // Rate limit exceeded – reject the request
                rejectedCounter.increment();
                long retryAfterSeconds = Duration.ofNanos(probe.getNanosToWaitForRefill()).toSeconds();
                response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
                response.addHeader(HEADER_LIMIT_REMAINING, "0");
                response.addHeader(HEADER_LIMIT_RETRY_AFTER, String.valueOf(retryAfterSeconds));
                response.getWriter().write("Rate limit exceeded. Try again in " + retryAfterSeconds + " seconds.");
                log.warn("Rate limit exceeded for key={} on route={}, retry after {}s", clientKey, routeKey, retryAfterSeconds);
            }
        }

        /**
         * Determines the unique key that identifies the caller. Priority:
         * <ol>
         *     <li>API Key header</li>
         *     <li>X-Forwarded-For header</li>
         *     <li>Remote address</li>
         * </ol>
         */
        private String resolveClientKey(HttpServletRequest request) {
            String apiKey = request.getHeader(HEADER_API_KEY);
            if (StringUtils.hasText(apiKey)) {
                return "api_key:" + apiKey.trim();
            }
            String forwardedFor = request.getHeader("X-Forwarded-For");
            if (StringUtils.hasText(forwardedFor)) {
                return "ip:" + forwardedFor.split(",")[0].trim();
            }
            return "ip:" + request.getRemoteAddr();
        }

        private Bucket createBucket(RateLimit limit) {
            Refill refill = Refill.intervally(limit.refillTokens, Duration.of(limit.refillPeriod, limit.timeUnit.toChronoUnit()));
            Bandwidth bandwidth = Bandwidth.classic(limit.capacity, refill).withInitialTokens(limit.capacity);
            return Bucket4j.builder()
                           .addLimit(bandwidth)
                           .build();
        }
    }

    /**
     * Bindable configuration properties for rate limiting.
     */
    @ConfigurationProperties(prefix = "nexus.gateway.rate-limit")
    public static class RateLimitProperties {

        /**
         * Global switch to enable/disable rate limiting. Defaults to true.
         */
        private boolean enabled = true;

        /**
         * Default limit applied to every route, unless a more specific one exists.
         */
        private RateLimit defaultLimit = new RateLimit();

        /**
         * Custom overrides keyed by Ant-style path patterns.
         */
        private Map<String, RateLimit> customLimits = Map.of();

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public RateLimit getDefaultLimit() {
            return defaultLimit;
        }

        public void setDefaultLimit(RateLimit defaultLimit) {
            this.defaultLimit = Objects.requireNonNull(defaultLimit);
        }

        public Map<String, RateLimit> getCustomLimits() {
            return customLimits;
        }

        public void setCustomLimits(Map<String, RateLimit> customLimits) {
            this.customLimits = Objects.requireNonNullElse(customLimits, Map.of());
        }

        /**
         * Resolves the concrete limit for a given route (request URI).
         */
        public RateLimit resolveLimitForRoute(String route) {
            return customLimits.entrySet()
                               .stream()
                               .filter(entry -> AntPathMatcherHolder.matcher().match(entry.getKey(), route))
                               .map(Map.Entry::getValue)
                               .findFirst()
                               .orElse(defaultLimit);
        }

        /**
         * Calculates the longest refill period among configured limits, used for cache expiry.
         */
        long longestRefillPeriodSeconds() {
            return customLimits.values().stream()
                    .mapToLong(l -> l.timeUnit.toChronoUnit().getDuration().getSeconds() * l.refillPeriod)
                    .max()
                    .orElse(defaultLimit.timeUnit.toChronoUnit().getDuration().getSeconds() * defaultLimit.refillPeriod);
        }
    }

    /**
     * Value object representing a single rate limit definition.
     */
    public static class RateLimit {
        private int capacity = 1000;
        private int refillTokens = 1000;
        private long refillPeriod = 1;
        private TimeUnit timeUnit = TimeUnit.MINUTES;

        public RateLimit() {
        }

        @JsonCreator
        public RateLimit(@JsonProperty("capacity") int capacity,
                         @JsonProperty("refill-tokens") int refillTokens,
                         @JsonProperty("refill-period") long refillPeriod,
                         @JsonProperty("time-unit") TimeUnit timeUnit) {
            this.capacity = capacity;
            this.refillTokens = refillTokens;
            this.refillPeriod = refillPeriod;
            this.timeUnit = timeUnit;
        }

        public int getCapacity() {
            return capacity;
        }

        public void setCapacity(int capacity) {
            this.capacity = capacity;
        }

        public int getRefillTokens() {
            return refillTokens;
        }

        public void setRefillTokens(int refillTokens) {
            this.refillTokens = refillTokens;
        }

        public long getRefillPeriod() {
            return refillPeriod;
        }

        public void setRefillPeriod(long refillPeriod) {
            this.refillPeriod = refillPeriod;
        }

        public TimeUnit getTimeUnit() {
            return timeUnit;
        }

        public void setTimeUnit(TimeUnit timeUnit) {
            this.timeUnit = timeUnit;
        }
    }

    /**
     * Lazily instantiated singleton for {@link org.springframework.util.AntPathMatcher}
     * to avoid unnecessary object creation on every request.
     */
    private static final class AntPathMatcherHolder {
        private static final org.springframework.util.AntPathMatcher MATCHER =
                new org.springframework.util.AntPathMatcher();

        static org.springframework.util.AntPathMatcher matcher() {
            return MATCHER;
        }
    }
}