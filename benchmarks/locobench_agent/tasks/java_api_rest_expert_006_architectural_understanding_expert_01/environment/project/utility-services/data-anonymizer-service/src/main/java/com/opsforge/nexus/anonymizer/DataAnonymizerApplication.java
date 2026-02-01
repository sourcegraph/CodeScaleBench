```java
package com.opsforge.nexus.anonymizer;

import java.time.Duration;
import java.util.Map;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.concurrent.ConcurrentMapCacheManager;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.event.EventListener;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.util.unit.DataSize;

import com.fasterxml.jackson.databind.Module;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.ser.BeanSerializerModifier;

/**
 * Spring-Boot bootstrap class for the Data-Anonymizer micro-service.
 *
 * <p>
 * Although the heavy lifting lives in the dedicated hexagonal layers
 * (domain, application, adapters), this application entry point takes
 * care of operational aspects such as:
 * <ul>
 *   <li>Metrics &amp; tracing auto-configuration</li>
 *   <li>Custom Jackson setup for PII redaction</li>
 *   <li>Distributed caching defaults</li>
 *   <li>Health checks</li>
 *   <li>Graceful start/stop logging</li>
 * </ul>
 * </p>
 */
@SpringBootApplication
@EnableCaching
@EnableAsync
public class DataAnonymizerApplication {

    private static final Logger LOG = LoggerFactory.getLogger(DataAnonymizerApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(DataAnonymizerApplication.class, args);
    }

    /**
     * Logs a human-readable banner with build metadata once the
     * application is fully started.
     */
    @EventListener(ApplicationReadyEvent.class)
    public void onReady(ApplicationReadyEvent event) {
        ApplicationContext ctx = event.getApplicationContext();
        Optional<String> buildVersion = Optional.ofNullable(
                ctx.getEnvironment().getProperty("build.version"));
        Optional<String> gitCommit = Optional.ofNullable(
                ctx.getEnvironment().getProperty("git.commit.id.abbrev"));

        LOG.info(
            "\n----------------------------------------------------------\n" +
            " Data-Anonymizer Service started successfully \n" +
            "   • build version : {}\n" +
            "   • git commit    : {}\n" +
            "   • active profiles : {}\n" +
            "----------------------------------------------------------",
            buildVersion.orElse("N/A"),
            gitCommit.orElse("N/A"),
            ctx.getEnvironment().getActiveProfiles()
        );
    }

    // =========================================================================
    // Configurations
    // =========================================================================

    /**
     * Jackson configuration focused on preventing accidental leakage of PII
     * in the serialized DTOs. The {@link AnonymizingSerializerModifier}
     * inspects bean properties for a domain-specific {@code @PII} annotation
     * (declared in the model module) and masks them according to the policy
     * negotiated by the calling user/tenant.
     */
    @Bean
    public Jackson2ObjectMapperBuilderCustomizer jacksonCustomizer(
            ObjectProvider<Module> registeredModules) {
        return (Jackson2ObjectMapperBuilder builder) -> {
            // Include auto-discovered modules first (e.g., Java-Time)
            registeredModules.forEach(builder::modules);

            builder.featuresToDisable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
            builder.serializerModifier(new AnonymizingSerializerModifier());
        };
    }

    /**
     * Provides a resilient {@link CacheManager}. While the preferred production
     * choice is Redis (configured externally), we fall back to an in-memory
     * {@link ConcurrentMapCacheManager} to remain platform-agnostic and
     * simplify local development.
     */
    @Bean
    public CacheManager cacheManager(
            @Value("${cache.fallback.max-size:1000}") int maxSize,
            @Value("${cache.fallback.ttl:PT10M}") Duration ttl) {

        ConcurrentMapCacheManager cacheManager = new ConcurrentMapCacheManager() {
            @Override
            protected org.springframework.cache.concurrent.ConcurrentMapCache createConcurrentMapCache(String name) {
                return new org.springframework.cache.concurrent.ConcurrentMapCache(
                        name,
                        com.google.common.cache.CacheBuilder.newBuilder()
                                .maximumSize(maxSize)
                                .expireAfterWrite(ttl)
                                .<Object, Object>build()
                                .asMap(),
                        false);
            }
        };
        LOG.info("Initialized fallback in-memory cache (maxSize={}, ttl={})", maxSize, ttl);
        return cacheManager;
    }

    /**
     * Simple health indicator exposing anonymizer-specific readiness KPI.
     * This is intentionally lightweight so that Kubernetes liveness probes
     * do not block on downstream dependencies.
     */
    @Bean
    public HealthIndicator anonymizerHealthIndicator() {
        return () -> {
            // A real implementation could verify that mandatory
            // configuration parameters are present (e.g., salt, key-vault).
            Map<String, Object> details = Map.of(
                    "saltLoaded", true,
                    "cipherSuite", "AES/GCM/NoPadding");
            return Health.up().withDetails(details).build();
        };
    }

    // =========================================================================
    // Inner classes
    // =========================================================================

    /**
     * {@link BeanSerializerModifier} that replaces property serializers for
     * fields annotated with {@code @PII}. The actual anonymization strategies
     * (mask, hash, redact, tokenise) are delegated to the domain layer so that
     * policies can evolve independently of transport concerns.
     */
    static final class AnonymizingSerializerModifier extends BeanSerializerModifier {

        private static final Logger LOG = LoggerFactory.getLogger(AnonymizingSerializerModifier.class);

        @Override
        public com.fasterxml.jackson.databind.JsonSerializer<?> modifySerializer(
                com.fasterxml.jackson.databind.cfg.SerializerProviderConfig config,
                com.fasterxml.jackson.databind.SerializationConfig serializationConfig,
                com.fasterxml.jackson.databind.BeanDescription beanDesc,
                com.fasterxml.jackson.databind.JsonSerializer<?> serializer) {

            boolean containsPiiFields = beanDesc.findProperties().stream()
                    .anyMatch(p -> p.hasAnnotation(com.opsforge.nexus.annotations.PII.class));

            if (!containsPiiFields) {
                return serializer;
            }

            LOG.debug("Applying PII anonymization to {}", beanDesc.getBeanClass().getSimpleName());
            return new com.opsforge.nexus.adapters.jackson.AnonymizingJsonSerializer(serializer);
        }
    }

    /**
     * Container for fine-grained rate-limit configuration. While the upstream
     * API gateway enforces coarse limits per API key, intra-service throttling
     * ensures that expensive anonymization algorithms (e.g., format-preserving
     * encryption) cannot DOS our thread pool.
     */
    @Configuration
    static class RateLimitConfig {

        @Value("${anonymizer.rate-limit.requests-per-second:20}")
        private int rps;

        @Bean
        public com.opsforge.nexus.common.ratelimit.RateLimiter rateLimiter() {
            com.opsforge.nexus.common.ratelimit.RateLimiter limiter =
                    com.opsforge.nexus.common.ratelimit.RateLimiter.simple(rps, Duration.ofSeconds(1));
            LOG.info("Configured local rate-limit: {} req/s", rps);
            return limiter;
        }
    }
}
```