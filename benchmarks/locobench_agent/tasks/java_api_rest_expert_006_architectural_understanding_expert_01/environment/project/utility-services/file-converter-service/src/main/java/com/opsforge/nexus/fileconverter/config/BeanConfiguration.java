package com.opsforge.nexus.fileconverter.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.fasterxml.jackson.module.paramnames.ParameterNamesModule;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import org.modelmapper.ModelMapper;
import org.modelmapper.convention.MatchingStrategies;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.validation.beanvalidation.LocalValidatorFactoryBean;

import javax.validation.Validator;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.*;

/**
 * BeanConfiguration wires together cross-cutting infrastructure components that power the
 * File Converter Service.  All beans defined here are technology-agnostic and can be swapped
 * out without affecting domain logic thanks to the project’s strict Hexagonal Architecture.
 *
 * The configuration purposefully avoids any direct reference to Spring MVC or persistence,
 * keeping the service’s core lightweight and test-friendly.
 */
@Configuration
@EnableCaching
@EnableConfigurationProperties(BeanConfiguration.FileConversionProperties.class)
public class BeanConfiguration {

    private static final Logger log = LoggerFactory.getLogger(BeanConfiguration.class);

    /**
     * Shared Jackson {@link ObjectMapper}.  Configured to be:
     *  – JavaTime friendly
     *  – Fail on unknown properties disabled to support forwards-compatibility
     *  – Snake case for property naming
     */
    @Bean
    @Primary
    public ObjectMapper objectMapper() {
        ObjectMapper mapper = new ObjectMapper()
                .registerModules(
                        new ParameterNamesModule(),
                        new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
                .findAndRegisterModules();
        mapper.configure(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
        return mapper;
    }

    /**
     * {@link ModelMapper} is used for DTO ↔ domain object mapping. Strict matching strategy
     * protects us against silent mapping failures when someone adds new fields.
     */
    @Bean
    public ModelMapper modelMapper() {
        ModelMapper mapper = new ModelMapper();
        mapper.getConfiguration()
                .setSkipNullEnabled(true)
                .setFieldMatchingEnabled(true)
                .setFieldAccessLevel(org.modelmapper.config.Configuration.AccessLevel.PRIVATE)
                .setMatchingStrategy(MatchingStrategies.STRICT);
        return mapper;
    }

    /**
     * JSR-380 validator for manual programmatic validation (e.g. when processing files
     * outside the context of MVC where automatic validation kicks in).
     */
    @Bean
    public Validator validator() {
        return new LocalValidatorFactoryBean();
    }

    /**
     * Application-wide CacheManager backed by Caffeine; delegates TTL calculation to the
     * {@link FileConversionProperties#getCacheTtlSeconds()} value.
     */
    @Bean
    public CacheManager cacheManager(FileConversionProperties props) {
        CaffeineCacheManager mgr = new CaffeineCacheManager("conversion-metadata", "preview-cache");
        Caffeine<Object, Object> builder = Caffeine.newBuilder()
                .maximumSize(props.getCacheMaximumSize())
                .expireAfterWrite(Duration.ofSeconds(props.getCacheTtlSeconds()));
        mgr.setCaffeine(builder);
        return mgr;
    }

    /**
     * Thread pool used for CPU-intensive conversion work.  The pool size is calculated at
     * runtime to (cores * concurrencyFactor) where concurrencyFactor is configurable.
     */
    @Bean(destroyMethod = "shutdown")
    @Qualifier("conversionExecutor")
    public ExecutorService conversionExecutor(FileConversionProperties props) {
        int availableProcessors = Runtime.getRuntime().availableProcessors();
        int poolSize = Math.max(1, availableProcessors * props.getConcurrencyFactor());
        log.info("Creating conversionExecutor pool with size {}", poolSize);

        return new ThreadPoolExecutor(
                poolSize,
                poolSize,
                30L,
                TimeUnit.SECONDS,
                new LinkedBlockingQueue<>(props.getExecutorQueueCapacity()),
                new ThreadFactory() {
                    private final ThreadFactory delegate = Executors.defaultThreadFactory();
                    @Override
                    public Thread newThread(Runnable r) {
                        Thread t = delegate.newThread(r);
                        t.setName("conversion-exec-" + t.getId());
                        t.setDaemon(true);
                        return t;
                    }
                },
                new ThreadPoolExecutor.CallerRunsPolicy());
    }

    /**
     * Resilience4j Circuit Breaker protecting outbound calls to external SaaS file conversion
     * engines.  Failure threshold & wait durations can be tuned in configuration.
     */
    @Bean
    @ConditionalOnMissingBean
    public CircuitBreaker externalConverterCircuitBreaker(FileConversionProperties props) {
        CircuitBreakerConfig cfg = CircuitBreakerConfig.custom()
                .failureRateThreshold(props.getCircuitBreakerFailureRate())
                .waitDurationInOpenState(Duration.ofSeconds(props.getCircuitBreakerWaitSeconds()))
                .slidingWindowSize(props.getCircuitBreakerSlidingWindow())
                .minimumNumberOfCalls(props.getCircuitBreakerMinimumCalls())
                .build();
        return CircuitBreaker.of("external-converter", cfg);
    }

    /**
     * Provides a write-restricted temporary folder used during multi-step conversions.
     * The folder is initialised lazily and cleaned on JVM shutdown.
     */
    @Bean
    public TemporaryWorkingDirectory workingDirectory(FileConversionProperties props) {
        return new TemporaryWorkingDirectory(props.getWorkingDirectory());
    }

    // ======================================================================================
    //  Support classes
    // ======================================================================================

    /**
     * Strongly-typed settings for the File Converter Service.  Leveraging
     * {@code @ConfigurationProperties} keeps the property namespace tidy and discoverable
     * (e.g. file-converter.*).
     */
    @ConfigurationProperties(prefix = "file-converter")
    public static class FileConversionProperties {

        /**
         * Allowed output mime types (e.g. image/png, application/pdf)
         */
        private List<String> supportedMimeTypes = List.of();

        /**
         * Maximum number of items to keep in Caffeine cache (per cache).
         */
        private long cacheMaximumSize = 5_000L;

        /**
         * TTL for cache values in seconds.
         */
        private long cacheTtlSeconds = 900;

        /**
         * Multiplier applied to available CPU cores to determine thread pool size.
         */
        private int concurrencyFactor = 2;

        /**
         * Capacity of conversion executor queue before back-pressure kicks in.
         */
        private int executorQueueCapacity = 100;

        /**
         * Circuit breaker config: failure rate percentage before breaker opens.
         */
        private float circuitBreakerFailureRate = 50f;

        /**
         * How long the circuit breaker remains open (seconds).
         */
        private int circuitBreakerWaitSeconds = 30;

        /**
         * Sliding window for circuit breaker metrics.
         */
        private int circuitBreakerSlidingWindow = 20;

        /**
         * Minimum number of calls before statistics are considered valid.
         */
        private int circuitBreakerMinimumCalls = 10;

        /**
         * Directory used for intermediate files; defaults to OS-specific temp dir.
         */
        private String workingDirectory = System.getProperty("java.io.tmpdir");

        // --- getters & setters ---

        public List<String> getSupportedMimeTypes() {
            return supportedMimeTypes;
        }

        public void setSupportedMimeTypes(List<String> supportedMimeTypes) {
            this.supportedMimeTypes = supportedMimeTypes;
        }

        public long getCacheMaximumSize() {
            return cacheMaximumSize;
        }

        public void setCacheMaximumSize(long cacheMaximumSize) {
            this.cacheMaximumSize = cacheMaximumSize;
        }

        public long getCacheTtlSeconds() {
            return cacheTtlSeconds;
        }

        public void setCacheTtlSeconds(long cacheTtlSeconds) {
            this.cacheTtlSeconds = cacheTtlSeconds;
        }

        public int getConcurrencyFactor() {
            return concurrencyFactor;
        }

        public void setConcurrencyFactor(int concurrencyFactor) {
            this.concurrencyFactor = concurrencyFactor;
        }

        public int getExecutorQueueCapacity() {
            return executorQueueCapacity;
        }

        public void setExecutorQueueCapacity(int executorQueueCapacity) {
            this.executorQueueCapacity = executorQueueCapacity;
        }

        public float getCircuitBreakerFailureRate() {
            return circuitBreakerFailureRate;
        }

        public void setCircuitBreakerFailureRate(float circuitBreakerFailureRate) {
            this.circuitBreakerFailureRate = circuitBreakerFailureRate;
        }

        public int getCircuitBreakerWaitSeconds() {
            return circuitBreakerWaitSeconds;
        }

        public void setCircuitBreakerWaitSeconds(int circuitBreakerWaitSeconds) {
            this.circuitBreakerWaitSeconds = circuitBreakerWaitSeconds;
        }

        public int getCircuitBreakerSlidingWindow() {
            return circuitBreakerSlidingWindow;
        }

        public void setCircuitBreakerSlidingWindow(int circuitBreakerSlidingWindow) {
            this.circuitBreakerSlidingWindow = circuitBreakerSlidingWindow;
        }

        public int getCircuitBreakerMinimumCalls() {
            return circuitBreakerMinimumCalls;
        }

        public void setCircuitBreakerMinimumCalls(int circuitBreakerMinimumCalls) {
            this.circuitBreakerMinimumCalls = circuitBreakerMinimumCalls;
        }

        public String getWorkingDirectory() {
            return workingDirectory;
        }

        public void setWorkingDirectory(String workingDirectory) {
            this.workingDirectory = workingDirectory;
        }
    }

    /**
     * Lazily creates an isolated working directory and ensures its cleanup on shutdown.
     */
    public static class TemporaryWorkingDirectory implements InitializingBean, AutoCloseable {

        private final String configuredPath;
        private Path directory;

        public TemporaryWorkingDirectory(String configuredPath) {
            this.configuredPath = configuredPath;
        }

        public Path getDirectory() {
            return directory;
        }

        @Override
        public void afterPropertiesSet() {
            try {
                directory = Files.createTempDirectory(Path.of(configuredPath), "opsforge-converter-");
                deleteOnExit(directory);
                log.debug("Created temporary working directory at {}", directory);
            } catch (IOException e) {
                throw new IllegalStateException("Unable to create temporary working directory", e);
            }
        }

        @Override
        public void close() {
            try {
                if (directory != null) {
                    Files.walk(directory)
                            .sorted((a, b) -> b.compareTo(a)) // delete children first
                            .map(Path::toFile)
                            .forEach(java.io.File::delete);
                    log.debug("Temporary working directory deleted: {}", directory);
                }
            } catch (IOException ex) {
                log.warn("Failed to completely delete temporary working directory {}", directory, ex);
            }
        }

        /**
         * Registers JVM shutdown hook to ensure temp directory is gone even when Spring
         * context fails to close gracefully.
         */
        private void deleteOnExit(Path dir) {
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                try {
                    Files.walk(dir)
                            .sorted((a, b) -> b.compareTo(a))
                            .map(Path::toFile)
                            .forEach(java.io.File::delete);
                } catch (IOException ignored) {
                }
            }, "temp-dir-cleaner-" + dir.getFileName()));
        }
    }
}