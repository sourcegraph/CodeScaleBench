package com.opsforge.nexus.anonymizer.config;

import java.time.Clock;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import javax.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.actuate.autoconfigure.metrics.MeterRegistryCustomizer;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.opsforge.nexus.anonymizer.core.AnonymizationStrategy;
import com.opsforge.nexus.anonymizer.core.DataAnonymizer;
import com.opsforge.nexus.anonymizer.core.impl.DefaultDataAnonymizer;
import com.opsforge.nexus.anonymizer.properties.AnonymizerProperties;

import io.micrometer.core.instrument.MeterRegistry;

/**
 * Central Spring {@code @Configuration} that wires up the beans required by the
 * Data Anonymizer micro-service.
 *
 * <p>
 * The configuration focuses purely on infrastructural concerns—wiring
 * encryption keys, caches, meters, and strategy plug-ins—while remaining
 * agnostic to higher-level transport layers (REST, GraphQL, messaging).
 * </p>
 */
@Configuration
@EnableCaching
@EnableConfigurationProperties(AnonymizerProperties.class)
public class BeanConfiguration {

    private static final Logger log = LoggerFactory.getLogger(BeanConfiguration.class);

    /**
     * Exposes the system clock as a bean, allowing the domain layer to stay free
     * from {@code java.time.Clock.systemUTC()} calls and easing time-based
     * testing.
     */
    @Bean
    public Clock systemClock() {
        return Clock.systemUTC();
    }

    /**
     * Customizes the default {@link ObjectMapper} so that every component in the
     * micro-service shares the exact same serialization settings.
     */
    @Bean
    @Primary
    public ObjectMapper objectMapper() {
        ObjectMapper mapper = new ObjectMapper();
        mapper.registerModule(new JavaTimeModule()); // Add Java 8 Time support
        mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        return mapper;
    }

    /**
     * Configures a Caffeine-based {@link CacheManager}. The actual settings—TTL,
     * maximum size, etc.—are externalized to {@link AnonymizerProperties} so that
     * operators can tune the service without code changes.
     */
    @Bean
    public CacheManager cacheManager(AnonymizerProperties props) {
        Caffeine<Object, Object> caffeineBuilder = Caffeine.newBuilder()
                .maximumSize(props.getCache().getMaximumSize())
                .expireAfterWrite(props.getCache().getTtl());

        CaffeineCacheManager manager = new CaffeineCacheManager();
        manager.setCaffeine(caffeineBuilder);
        log.info("Initialized CaffeineCacheManager (maxSize={}, ttl={})",
                props.getCache().getMaximumSize(), props.getCache().getTtl());
        return manager;
    }

    /**
     * Registers all {@link AnonymizationStrategy} beans found in the Spring
     * context and provides them to a {@link DataAnonymizer} service capable of
     * delegating to the correct strategy at runtime.
     */
    @Bean
    @ConditionalOnMissingBean
    public DataAnonymizer dataAnonymizer(List<AnonymizationStrategy<?>> strategies) {
        Map<String, AnonymizationStrategy<?>> registry = strategies.stream()
                .collect(Collectors.toMap(AnonymizationStrategy::strategyId, Function.identity()));

        log.info("Wired {} AnonymizationStrategy beans -> {}", registry.size(), registry.keySet());
        return new DefaultDataAnonymizer(registry);
    }

    /**
     * Adds common tags to every Micrometer metric emitted by this micro-service,
     * greatly simplifying Prometheus queries and Grafana dashboards.
     */
    @Bean
    public MeterRegistryCustomizer<MeterRegistry> metricsCommonTagsCustomizer(AnonymizerProperties props) {
        return registry -> registry.config().commonTags("service", "data-anonymizer",
                "environment", props.getEnvironment());
    }

    /**
     * Basic sanity-check ensuring that at least one
     * {@link AnonymizationStrategy} has been registered. Since the strategies are
     * entirely pluggable, it's easy to misconfigure the application context and
     * start the container without any concrete strategy implementation.
     */
    @PostConstruct
    public void validateStrategiesPresent(List<AnonymizationStrategy<?>> strategies) {
        if (strategies.isEmpty()) {
            throw new IllegalStateException(
                    "No AnonymizationStrategy beans found in context. Service cannot start.");
        }
    }
}