```java
package com.commercesphere.enterprise;

import java.lang.management.ManagementFactory;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.util.Optional;
import javax.annotation.PreDestroy;
import javax.sql.DataSource;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.Banner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.SpringApplicationRunListener;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceProperties;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationListener;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.Environment;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.util.StringUtils;

/**
 * CommerceSphere Enterprise Suite bootstrap class.
 *
 * <p>This is the single entry point for the monolithic deployment. Responsibilities:
 * <ul>
 *     <li>Configure Spring Boot defaults (banner, listeners, etc.).</li>
 *     <li>Expose a few diagnostic beans for health-checks and metrics.</li>
 *     <li>Assert baseline infrastructure (e.g. database connectivity) is available at startup.</li>
 *     <li>Register a graceful shutdown hook for container orchestrators (Kubernetes, ECS ...).</li>
 * </ul>
 */
@SpringBootApplication
@EnableConfigurationProperties
@SuppressWarnings("java:S4823") // timezone intentionally hard-coded for deterministic logging
public class CommerceSphereApplication {

    private static final Logger LOGGER = LoggerFactory.getLogger(CommerceSphereApplication.class);
    private static final String DEFAULT_TIME_ZONE = "UTC";

    private Instant startTime = Instant.now();
    private ConfigurableApplicationContext ctx;

    public static void main(String[] args) {

        // Force deterministic JVM timezone for audits
        ZoneId.setDefault(ZoneId.of(DEFAULT_TIME_ZONE));

        new CommerceSphereApplication()
                .launch(args);
    }

    private void launch(String[] args) {
        SpringApplicationBuilder builder = new SpringApplicationBuilder(CommerceSphereApplication.class)
                .bannerMode(Banner.Mode.LOG)
                .listeners((ApplicationListener<ApplicationReadyEvent>) this::onApplicationReady);

        ctx = builder.run(args);
    }

    @PreDestroy
    public void onShutdown() {
        Duration upTime = Duration.between(startTime, Instant.now());
        LOGGER.info("CommerceSphere is shutting down. Uptime: {} seconds.", upTime.getSeconds());
    }

    /**
     * Callback after Spring signals that the application is ready to serve requests.
     */
    private void onApplicationReady(ApplicationReadyEvent event) {
        Duration bootTime = Duration.between(startTime, Instant.now());
        LOGGER.info("CommerceSphere started in {} seconds. Active profiles: {}",
                bootTime.toMillis() / 1000.0,
                String.join(",", event.getApplicationContext().getEnvironment().getActiveProfiles()));
    }

    // -------------------------------------------------------------------------
    // Diagnostics / Infrastructure beans
    // -------------------------------------------------------------------------

    /**
     * Basic health-check verifying database connectivity at startup.
     *
     * This prevents the app from entering a zombie state when the DB is unavailable,
     * failing fast so container orchestrators can react.
     */
    @Bean
    public ApplicationListener<ApplicationReadyEvent> databaseConnectivityVerifier(
            ObjectProvider<DataSource> dataSourceProvider,
            ObjectProvider<DataSourceProperties> dsPropsProvider) {

        return event -> {
            DataSource dataSource = dataSourceProvider.getIfAvailable();
            if (dataSource == null) {
                LOGGER.warn("No DataSource configured ‑ skipping connectivity check.");
                return;
            }

            DataSourceProperties dsProps = dsPropsProvider.getIfAvailable();
            String url = dsProps != null ? dsProps.determineUrl() : "<unknown>";
            LOGGER.info("Verifying DB connectivity to {}", url);

            try (Connection connection = dataSource.getConnection()) {
                if (!connection.isValid(5)) {
                    throw new SQLException("Connection#isValid returned false");
                }
                LOGGER.info("Successfully connected to database.");
            } catch (SQLException ex) {
                LOGGER.error("Database connectivity verification failed: {}", ex.getMessage(), ex);
                // Terminate the JVM – we rely on container orchestration to restart us.
                System.exit(SpringApplication.exit(event.getApplicationContext(), () -> 1));
            }
        };
    }

    /**
     * Record JVM boot time in Micrometer registry for observability dashboards.
     */
    @Bean
    public ApplicationListener<ApplicationReadyEvent> bootTimeMetricsPublisher(MeterRegistry registry) {
        return event -> {
            Duration bootDuration = Duration.between(startTime, Instant.now());
            Timer.builder("commerceSphere.boot.time")
                    .description("Time taken for CommerceSphere to start")
                    .register(registry)
                    .record(bootDuration);
        };
    }

    // -------------------------------------------------------------------------
    // Utility ThreadPool – shared across non-blocking services (e.g., async
    // payment gateway calls, webhooks, etc.).
    // -------------------------------------------------------------------------
    @Bean(name = "asyncExecutor")
    public ThreadPoolTaskExecutor asyncExecutor(Environment env) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix("cs-async-");

        int cores = Runtime.getRuntime().availableProcessors();
        int corePoolSize = Integer.parseInt(env.getProperty("commerceSphere.async.corePoolSize",
                Integer.toString(Math.max(2, cores))));
        int maxPoolSize = Integer.parseInt(env.getProperty("commerceSphere.async.maxPoolSize",
                Integer.toString(cores * 4)));

        executor.setCorePoolSize(corePoolSize);
        executor.setMaxPoolSize(maxPoolSize);
        executor.setQueueCapacity(10_000);
        executor.setAwaitTerminationSeconds(30);
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.initialize();
        return executor;
    }

    // -------------------------------------------------------------------------
    // Version Information Endpoint (exposed via /actuator/info)
    // -------------------------------------------------------------------------
    @Bean
    public org.springframework.boot.info.InfoContributor buildInfoContributor() {
        return builder -> {
            String version = Optional.ofNullable(
                    CommerceSphereApplication.class.getPackage().getImplementationVersion())
                    .orElse("dev-snapshot");
            builder.withDetail("app",
                    java.util.Map.of(
                            "name", "CommerceSphere Enterprise Suite",
                            "version", version,
                            "pid", ManagementFactory.getRuntimeMXBean().getPid(),
                            "buildTime", startTime.toString()
                    ));
        };
    }
}
```