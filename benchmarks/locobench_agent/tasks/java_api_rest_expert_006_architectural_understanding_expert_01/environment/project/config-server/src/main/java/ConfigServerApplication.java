```java
package com.opsforge.utilitynexus.configserver;

import java.time.Duration;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicReference;

import javax.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.actuate.health.CompositeHealthContributor;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthContributor;
import org.springframework.boot.actuate.health.HealthEndpoint;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.cloud.config.environment.Environment;
import org.springframework.cloud.config.server.EnableConfigServer;
import org.springframework.cloud.config.server.environment.EnvironmentRepository;
import org.springframework.context.ApplicationListener;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.concurrent.ConcurrentTaskScheduler;
import org.springframework.security.crypto.encrypt.Encryptors;
import org.springframework.security.crypto.encrypt.TextEncryptor;
import org.springframework.util.Assert;

/**
 * Entry point for the OpsForge Utility Nexus Config Server.
 *
 * <p>This node:
 * <ul>
 *     <li>Hosts a Spring Cloud Config Server that provides versioned, immutable configuration
 *         to all utility microservices.</li>
 *     <li>Encrypts/decrypts sensitive properties via Jasypt-compatible AES-256.</li>
 *     <li>Exposes enhanced health checks that ensure the backing configuration repository
 *         is reachable and up-to-date.</li>
 *     <li>Wires a {@link TaskScheduler} used by Spring’s {@code @Scheduled} components as well
 *         as internal retry/back-off policies.</li>
 * </ul>
 */
@SpringBootApplication
@EnableConfigServer
public class ConfigServerApplication {

    private static final Logger LOG = LoggerFactory.getLogger(ConfigServerApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(ConfigServerApplication.class, args);
    }

    /**
     * TextEncryptor bean leveraged by Spring Cloud Config’s /encrypt and /decrypt endpoints,
     * as well as any {@code {cipher}} property placeholders found in property sources.
     *
     * The password is resolved in the following order:
     * <ol>
     *     <li>Environment variable CONFIG_ENCRYPTION_PASSWORD</li>
     *     <li>Java system property config.encryption.password</li>
     * </ol>
     * <p>
     * Production deployments should supply the password via a secure mechanism such as
     * Kubernetes Secrets or a dedicated secret-management service.
     */
    @Bean
    @Primary
    public TextEncryptor textEncryptor(ConfigurableEnvironment env) {
        String password = resolveRequiredPassword(env);
        // Using a static salt is acceptable for server-side encryption where the salt does not
        // need to be secret—Spring Cloud Config follows the same approach.
        String salt = "deadbeefcafebabe";
        LOG.info("Initializing AES-256 text encryptor for Config Server (salt={}).", salt);
        return Encryptors.text(password, salt);
    }

    /**
     * Scheduler used by internal Spring Cloud components as well as any scheduled jobs we may
     * introduce in the future (e.g., Git repository refresh, metrics push).
     */
    @Bean
    public TaskScheduler taskScheduler() {
        ConcurrentTaskScheduler scheduler = new ConcurrentTaskScheduler();
        // Provide a descriptive thread-name prefix for easier debugging/observability.
        scheduler.setThreadNamePrefix("config-scheduler-");
        scheduler.setErrorHandler(t -> LOG.error("Uncaught task error in Config Server scheduler", t));
        return scheduler;
    }

    /**
     * Overrides the default {@link EnvironmentRepository} to keep track of the last successful
     * fetch. This information is exposed via the custom {@link HealthIndicator}.
     *
     * The decorating pattern avoids rewriting existing repository logic while still giving us
     * insight into repository availability and currency.
     */
    @Bean
    @Primary
    public EnvironmentRepository auditingEnvironmentRepository(EnvironmentRepository delegate) {
        return new AuditingEnvironmentRepository(delegate);
    }

    /**
     * Custom health indicator that surfaces repository availability and freshness. It delegates
     * to Spring Cloud Config’s {@code EnvironmentRepository} rather than performing its own low-level
     * Git or Vault checks, reducing coupling with the underlying storage technology.
     */
    @Bean
    public HealthContributor repositoryHealthIndicator(AuditingEnvironmentRepository repo) {
        return (HealthIndicator) () -> {
            Duration age = repo.ageOfLastSuccess();
            Health.Builder builder = repo.lastFetchSuccessful()
                    ? Health.up()
                    : Health.down();

            return builder
                    .withDetail("repository", repo.getDelegate().getClass().getSimpleName())
                    .withDetail("lastFetchAge", age.toMillis() + "ms")
                    .withDetail("lastFetchSuccessful", repo.lastFetchSuccessful())
                    .build();
        };
    }

    /**
     * Emits an application-ready log entry that includes the active Spring profiles. This is
     * convenient for DevOps teams performing zero-downtime rollouts, as they can verify that
     * the profile combination matches expectation without scraping the entire application log.
     */
    @Bean
    public ApplicationListener<ApplicationReadyEvent> logProfilesOnStartup(ConfigurableEnvironment env) {
        return event -> {
            String[] active = env.getActiveProfiles();
            String[] defaultProfiles = env.getDefaultProfiles();
            LOG.info("Config Server started with active profiles {} (default profiles {}).",
                    active, defaultProfiles);
        };
    }

    // -------------------------------------------------------------------------
    // Internal helper classes
    // -------------------------------------------------------------------------

    /**
     * Wrapper that records whether the last fetch was successful and when it happened.
     */
    static final class AuditingEnvironmentRepository implements EnvironmentRepository {

        private final EnvironmentRepository delegate;

        private final AtomicReference<Long> lastSuccessEpochMilli = new AtomicReference<>(0L);
        private final AtomicReference<Boolean> lastSuccess = new AtomicReference<>(false);

        AuditingEnvironmentRepository(EnvironmentRepository delegate) {
            this.delegate = delegate;
        }

        @Override
        public Environment findOne(String application, String profile, String label) {
            try {
                Environment env = delegate.findOne(application, profile, label);
                markSuccess();
                return env;
            } catch (RuntimeException ex) {
                markFailure(ex);
                throw ex;
            }
        }

        void markSuccess() {
            lastSuccess.set(true);
            lastSuccessEpochMilli.set(System.currentTimeMillis());
        }

        void markFailure(Throwable t) {
            lastSuccess.set(false);
            LOG.warn("Failed to fetch environment from repository – will report DOWN", t);
        }

        boolean lastFetchSuccessful() {
            return lastSuccess.get();
        }

        Duration ageOfLastSuccess() {
            long epoch = lastSuccessEpochMilli.get();
            return (epoch == 0L)
                    ? Duration.ofDays(Long.MAX_VALUE)
                    : Duration.ofMillis(System.currentTimeMillis() - epoch);
        }

        EnvironmentRepository getDelegate() {
            return delegate;
        }
    }

    // -------------------------------------------------------------------------
    // Utility / validation
    // -------------------------------------------------------------------------

    private static String resolveRequiredPassword(ConfigurableEnvironment env) {
        String password = env.getProperty("CONFIG_ENCRYPTION_PASSWORD");
        if (password == null) {
            password = env.getProperty("config.encryption.password");
        }
        Assert.hasText(password, "Encryption password must be provided via CONFIG_ENCRYPTION_PASSWORD or " +
                "config.encryption.password system property");
        return password;
    }

    /**
     * Ensure Spring Cloud Config’s default environment is at least {@link StandardEnvironment}
     * to guarantee property resolution of system environment variables and system properties.
     */
    @PostConstruct
    public void validateEnvironment(ConfigurableEnvironment env) {
        if (!(env instanceof StandardEnvironment)) {
            throw new IllegalStateException("Config Server requires a StandardEnvironment, but got " +
                    env.getClass().getName());
        }
    }
}
```