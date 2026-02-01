```java
package com.opsforge.utility.texttransformer;

import java.time.Clock;
import java.util.Map;

import javax.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.Banner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Profile;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.ResponseErrorHandler;
import org.springframework.web.client.RestTemplate;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Caffeine;

/**
 * Spring Boot bootstrap class for the Text-Transformer micro-service.
 *
 * <p>
 * Although this class is mostly responsible for wiring up the Spring context,
 * it also hosts cross-cutting concerns that do not belong to any particular
 * hexagonal port or adapter, e.g. default cache manager, global JSON mapper
 * configuration and a hardened {@link RestTemplate}.
 * </p>
 *
 * <p>
 * All domain logic lives in downstream components and is accessible strictly
 * through application services and inbound ports as mandated by the hexagonal
 * architecture applied across the OpsForge Utility Nexus.
 * </p>
 */
@SpringBootApplication
@EnableAsync
@EnableCaching
@EnableConfigurationProperties(TextTransformerApplication.BuildInfoProperties.class)
public class TextTransformerApplication {

    private static final Logger log = LoggerFactory.getLogger(TextTransformerApplication.class);

    public static void main(String[] args) {
        SpringApplication app = new SpringApplication(TextTransformerApplication.class);
        // Override default banner with a silent one, we print a custom banner later
        app.setBannerMode(Banner.Mode.OFF);
        app.run(args);
    }

    // -------------------------------------------------------------------------
    // System bootstrap helpers
    // -------------------------------------------------------------------------

    /**
     * Prints a custom ASCII banner and build information to the log once the
     * application context has been initialized. This avoids polluting STDOUT
     * and plays nicely with container logs.
     */
    @Bean
    ApplicationRunner printBanner(BuildInfoProperties buildInfo) {
        return args -> {
            String banner = "\n"
                    + "  ______          _____                          _                 \n"
                    + " |  ____|        / ____|                        | |                \n"
                    + " | |__ ___  _ __| (___   ___  _ __   ___ _ __ __| | ___ _ __ ___   \n"
                    + " |  __/ _ \\| '__|\\___ \\ / _ \\| '_ \\ / _ \\ '__/ _` |/ _ \\ '_ ` _ \\  \n"
                    + " | | | (_) | |   ____) | (_) | | | |  __/ | | (_| |  __/ | | | | | \n"
                    + " |_|  \\___/|_|  |_____/ \\___/|_| |_|\\___|_|  \\__,_|\\___|_| |_| |_| \n";
            log.info("\n{}\n:: {} :: version {}\n", banner, buildInfo.getName(), buildInfo.getVersion());
        };
    }

    /**
     * Exposes the system default {@link Clock} so it can be injected wherever
     * time-aware computations are required. Keeping the clock centralized makes
     * it trivial to manipulate during tests.
     */
    @Bean
    public Clock systemClock() {
        return Clock.systemUTC();
    }

    // -------------------------------------------------------------------------
    // Infrastructure & cross-cutting beans
    // -------------------------------------------------------------------------

    /**
     * Central cache manager. The configuration is intentionally conservative
     * because individual repositories/services will usually override these
     * settings through cache-specific annotations if needed.
     */
    @Bean
    public CacheManager cacheManager() {
        CaffeineCacheManager mgr = new CaffeineCacheManager();
        mgr.setCaffeine(Caffeine.newBuilder()
                                .maximumSize(2_000)
                                .recordStats()
                                .build());
        return mgr;
    }

    /**
     * Hardened {@link RestTemplate} that denies non-2xx responses and captures
     * body snippets into the log for debugging purposes.
     */
    @Bean
    @Profile("!test") // Tests should supply their own lightweight RestTemplate
    public RestTemplate restTemplate() {
        RestTemplate template = new RestTemplate();
        template.setErrorHandler(new LoggingErrorHandler());
        return template;
    }

    /**
     * Configures the primary {@link ObjectMapper} used by Spring’s HTTP
     * converters and GraphQL engine. We avoid global singleton usage in favour
     * of DI to make testing and module replacement easier.
     */
    @Bean
    public ObjectMapper objectMapper() {
        return new ObjectMapper()
                .findAndRegisterModules() // automatically registers JavaTimeModule, etc.
                .configure(com.fasterxml.jackson.databind.SerializationFeature.WRITE_DATES_AS_TIMESTAMPS, false)
                .configure(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
    }

    // -------------------------------------------------------------------------
    // Nested components
    // -------------------------------------------------------------------------

    /**
     * Captures build-time information written by the Maven / Gradle build.
     * The file <code>git.properties</code> is typically generated by the
     * <em>git-commit-id-plugin</em>.
     */
    @ConfigurationProperties(prefix = "build")
    public static class BuildInfoProperties {

        /** Artifact name. */
        private String name = "text-transformer-service";

        /** Semver version string. */
        private String version = "DEV-SNAPSHOT";

        /** Arbitrary additional metadata. */
        private Map<String, String> properties;

        public String getName() {
            return name;
        }

        public void setName(String name) {
            this.name = name;
        }

        public String getVersion() {
            return version;
        }

        public void setVersion(String version) {
            this.version = version;
        }

        public Map<String, String> getProperties() {
            return properties;
        }

        public void setProperties(Map<String, String> properties) {
            this.properties = properties;
        }

        @PostConstruct
        void logProperties() {
            if (properties != null && !properties.isEmpty()) {
                log.info("Additional build metadata: {}", properties);
            }
        }
    }

    /**
     * Custom error handler that throws {@link RemoteServiceCallException} for
     * any non-successful HTTP status and logs the first N bytes of the response
     * body to aid troubleshooting without overwhelming the logs.
     */
    private static final class LoggingErrorHandler implements ResponseErrorHandler {

        private static final int MAX_LOGGED_BODY_BYTES = 2_048;

        @Override
        public boolean hasError(ClientHttpResponse response) {
            try {
                return response.getStatusCode().isError();
            } catch (Exception ex) {
                return true; // Fail-fast if we cannot obtain status code
            }
        }

        @Override
        public void handleError(ClientHttpResponse response) {
            try {
                byte[] rawBody = StreamUtils.copyToByteArray(response.getBody());
                String snippet = new String(rawBody, 0, Math.min(rawBody.length, MAX_LOGGED_BODY_BYTES));
                log.warn("Downstream call failed with status={} bodySnippet='{}'",
                        response.getStatusCode(), snippet.replaceAll("\\s+", " "));
                throw new RemoteServiceCallException(response.getStatusCode(), snippet);
            } catch (Exception ioe) {
                throw new RemoteServiceCallException("Unparseable downstream error response", ioe);
            }
        }
    }

    /**
     * An unchecked exception that represents failures when calling third-party
     * services from within the transformer domain. Converting these failures to
     * runtime exceptions enables the use of <em>Spring Retry</em> and
     * simplifies adapter error propagation.
     */
    public static class RemoteServiceCallException extends RuntimeException {
        private static final long serialVersionUID = 8265238481632715323L;

        private final org.springframework.http.HttpStatus status;

        public RemoteServiceCallException(org.springframework.http.HttpStatus status, String body) {
            super("Remote service call failed with status " + status + " — " + body);
            this.status = status;
        }

        public RemoteServiceCallException(String message, Throwable cause) {
            super(message, cause);
            this.status = null;
        }

        public org.springframework.http.HttpStatus getStatus() {
            return status;
        }
    }
}
```