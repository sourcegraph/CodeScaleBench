```java
package com.sprintcart.app;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthEndpoint;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationListener;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Profile;
import org.springframework.context.event.ContextRefreshedEvent;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;

import javax.annotation.PreDestroy;
import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
import java.time.Instant;

/**
 * Entry point for the SprintCart Pro application.
 *
 * <p>This class does a bit more than the average {@code main()}—it performs crucial
 * boot-time validations, configures core infrastructure beans, and exposes a dev-only
 * banner for a friendlier local experience.</p>
 */
@SpringBootApplication(scanBasePackages = "com.sprintcart")
@EnableConfigurationProperties(SprintCartProApplication.PaymentGatewayProperties.class)
@RequiredArgsConstructor
public class SprintCartProApplication implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(SprintCartProApplication.class);

    private static final String DEV_BANNER = """
             ███████╗██████╗ ██╗███╗   ██╗████████╗ ██████╗ ██████╗ 
             ██╔════╝██╔══██╗██║████╗  ██║╚══██╔══╝██╔═══██╗██╔══██╗
             █████╗  ██████╔╝██║██╔██╗ ██║   ██║   ██║   ██║██████╔╝
             ██╔══╝  ██╔══██╗██║██║╚██╗██║   ██║   ██║   ██║██╔══██╗
             ███████╗██║  ██║██║██║ ╚████║   ██║   ╚██████╔╝██║  ██║
             ╚══════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
            """;

    private final ApplicationContext applicationContext;
    private final DataSource dataSource;
    private final PaymentGatewayProperties paymentGatewayProperties;
    private final HealthEndpoint healthEndpoint;

    private Instant bootStartedAt;

    public static void main(String[] args) {
        configureSystemProperties();
        SpringApplication.run(SprintCartProApplication.class, args);
    }

    @Override
    public void run(ApplicationArguments args) {
        bootStartedAt = Instant.now();

        verifyDatabaseConnectivity();
        verifyPaymentGatewayConfig();
        reportApplicationHealthStatus();

        log.info("SprintCart Pro is up and running in {} ms 🚀",
                 Duration.between(bootStartedAt, Instant.now()).toMillis());
    }

    /**
     * Executes on shutdown—ideal for flushing metrics, closing pools, etc.
     */
    @PreDestroy
    public void onShutdown() {
        log.info("Gracefully shutting down SprintCart Pro...");
    }

    /* ------------------------------------------------------------------
     * Boot-time validations
     * ------------------------------------------------------------------ */

    private void verifyDatabaseConnectivity() {
        log.debug("Checking connectivity to the primary database...");
        try (Connection connection = dataSource.getConnection()) {
            if (!connection.isValid(5)) { // 5-second timeout
                throw new IllegalStateException("Primary database connection is not valid");
            }
            log.info("Primary database connectivity: OK ({})", connection.getMetaData().getURL());
        } catch (SQLException ex) {
            throw new IllegalStateException("Unable to connect to primary database", ex);
        }
    }

    private void verifyPaymentGatewayConfig() {
        log.debug("Validating payment gateway configuration...");
        if (StringUtils.isAnyBlank(paymentGatewayProperties.getApiKey(),
                                   paymentGatewayProperties.getEndpoint())) {
            throw new IllegalStateException("""
                    Payment gateway settings are incomplete.
                    Please make sure 'sprintcart.payment-gateway.api-key' and
                    'sprintcart.payment-gateway.endpoint' are provided.
                    """);
        }
        log.info("Payment gateway configuration: OK (endpoint={})", paymentGatewayProperties.getEndpoint());
    }

    private void reportApplicationHealthStatus() {
        Health health = healthEndpoint.health();
        if (health.getStatus().isUp()) {
            log.info("Aggregate application health status: {}", health.getStatus());
        } else {
            log.warn("Aggregate application health status: {}", health.getStatus());
        }
    }

    /* ------------------------------------------------------------------
     * Spring-managed beans
     * ------------------------------------------------------------------ */

    /**
     * Customizes the global {@link ObjectMapper} used by Spring for JSON (de)serialization.
     * Ensures ISO-8601 date handling and registers JavaTimeModule for {@code java.time.*} support.
     */
    @Bean
    public ObjectMapper objectMapper(Jackson2ObjectMapperBuilder builder) {
        builder.featuresToDisable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        builder.modules(new JavaTimeModule());
        return builder.build();
    }

    /**
     * Cool banner that prints only on the 'dev' profile so that production logs stay clean.
     */
    @Bean
    @Profile("dev")
    public ApplicationListener<ContextRefreshedEvent> devProfileBanner() {
        return event -> log.info("\n{}", DEV_BANNER);
    }

    /* ------------------------------------------------------------------
     * Utility methods
     * ------------------------------------------------------------------ */

    private static void configureSystemProperties() {
        // Ensures consistent locale/time-zone across JVM instances; critical for price/time computations.
        System.setProperty("user.timezone", "UTC");
    }

    /* ------------------------------------------------------------------
     * Nested configuration classes
     * ------------------------------------------------------------------ */

    /**
     * Holds configuration for outbound payment gateway integration.
     *
     * <pre>
     * Example (application.yml):
     * sprintcart:
     *   payment-gateway:
     *     endpoint: https://api.stripe.com
     *     api-key: sk_live_******
     * </pre>
     */
    @ConfigurationProperties(prefix = "sprintcart.payment-gateway")
    public static class PaymentGatewayProperties {
        /**
         * Base URL of the payment gateway REST API.
         */
        private String endpoint;

        /**
         * Secret API key used to authenticate requests.
         */
        private String apiKey;

        public String getEndpoint() {
            return endpoint;
        }

        public void setEndpoint(String endpoint) {
            this.endpoint = endpoint;
        }

        public String getApiKey() {
            return apiKey;
        }

        public void setApiKey(String apiKey) {
            this.apiKey = apiKey;
        }
    }
}
```