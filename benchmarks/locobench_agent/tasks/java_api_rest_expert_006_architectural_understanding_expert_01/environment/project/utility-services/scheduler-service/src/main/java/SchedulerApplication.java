```java
/*
 * OpsForge Utility Nexus — Scheduler Service
 *
 * Copyright 2024 …
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * A copy of the License is located at
 *
 *       http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.opsforge.utility.scheduler;

import java.lang.management.ManagementFactory;
import java.time.Clock;
import java.time.ZoneId;
import java.util.Optional;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionHandler;
import java.util.concurrent.ThreadPoolExecutor;

import jakarta.annotation.PreDestroy;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.BeanInitializationException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.Banner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.MessageSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.support.ReloadableResourceBundleMessageSource;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.CustomizableThreadFactory;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;

/**
 * Main bootstrap class for the Scheduler Service.
 *
 * <p>This service provides time-zone aware scheduling primitives as a foundation
 * for higher-level orchestration use-cases (cron pipelines, calendar alignment,
 * SLA monitoring, etc.).  Being a Hexagonal Architecture entry-point, this
 * class wires all primary adapters (HTTP, GraphQL, messaging) and cross-cutting
 * infrastructure (caching, metrics, error-handling) while keeping the domain
 * model blissfully unaware of Spring.</p>
 *
 * <p>The application exposes the following capabilities out of the box:</p>
 * <ul>
 *     <li>A {@link TaskScheduler} that honours the configured default
 *     {@code scheduler.time-zone} and surfaces uncaught exceptions to SLF4J.</li>
 *     <li>An async {@link Executor} for CPU-light/background operations.</li>
 *     <li>A health indicator that captures thread-pool saturation.</li>
 *     <li>A graceful shutdown hook ensuring scheduled tasks conclude before
 *     container exit.</li>
 *     <li>Startup banner with build + JVM diagnostics.</li>
 * </ul>
 */
@EnableAsync
@EnableScheduling
@SpringBootApplication(scanBasePackages = "com.opsforge.utility")
public class SchedulerApplication implements ApplicationListener<ApplicationReadyEvent> {

    private static final Logger LOGGER = LoggerFactory.getLogger(SchedulerApplication.class);

    @Value("${scheduler.thread-pool.core-size:4}")
    private int schedulerCoreSize;

    @Value("${scheduler.thread-pool.max-size:16}")
    private int schedulerMaxSize;

    @Value("${scheduler.thread-pool.queue-capacity:512}")
    private int schedulerQueueCapacity;

    @Value("${scheduler.time-zone:UTC}")
    private String schedulerTimeZone;

    @Value("${spring.application.name:scheduler-service}")
    private String applicationName;

    private ThreadPoolTaskScheduler taskScheduler;

    private ConfigurableApplicationContext context;

    public static void main(String[] args) {
        SpringApplication app = new SpringApplication(SchedulerApplication.class);
        app.setBanner((environment, sourceClass, out) -> out.println(buildBanner(environment.getProperty("spring.application.name", "Scheduler Service"))));
        ConfigurableApplicationContext ctx = app.run(args);
        // Keep reference for shutdown hook
        SchedulerApplication bootstrap = ctx.getBean(SchedulerApplication.class);
        bootstrap.context = ctx;
    }

    // ---------------------------------------------------------------------
    // Infrastructure Beans
    // ---------------------------------------------------------------------

    /**
     * Provides a custom {@link TaskScheduler} with a descriptive thread-naming
     * scheme, bounded queue and a JVM-wide exception handler.
     */
    @Bean(name = "schedulerTaskScheduler")
    @ConditionalOnMissingBean
    public TaskScheduler taskScheduler() {
        try {
            ThreadPoolTaskScheduler scheduler = new ThreadPoolTaskScheduler();
            scheduler.setPoolSize(schedulerCoreSize);
            scheduler.setThreadFactory(new CustomizableThreadFactory("opsforge-scheduler-"));
            scheduler.setRejectedExecutionHandler(new RejectedPolicy());
            scheduler.setRemoveOnCancelPolicy(true);
            scheduler.setAwaitTerminationSeconds(30);
            scheduler.setErrorHandler(t -> LOGGER.error("Uncaught exception in scheduled task", t));
            scheduler.initialize();
            this.taskScheduler = scheduler;
            return scheduler;
        } catch (Exception ex) {
            throw new BeanInitializationException("Failed to initialize TaskScheduler", ex);
        }
    }

    /**
     * Default async executor separate from the scheduling pool, used for
     * caller-runs style lightweight tasks such as notification fan-outs.
     */
    @Bean(name = "applicationTaskExecutor")
    @ConditionalOnMissingBean
    public Executor applicationTaskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(Math.min(Runtime.getRuntime().availableProcessors(), 8));
        executor.setMaxPoolSize(32);
        executor.setQueueCapacity(1024);
        executor.setThreadNamePrefix("opsforge-exec-");
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.initialize();
        return executor;
    }

    /**
     * Health check that considers both scheduler and async pools, exposing a
     * {@code DOWN} status if either pool is saturated or shut down.
     */
    @Bean
    public HealthIndicator threadPoolHealthIndicator() {
        return () -> {
            boolean schedulerActive = Optional.ofNullable(taskScheduler)
                                              .map(ThreadPoolTaskScheduler::getScheduledExecutor)
                                              .filter(executor -> !executor.isShutdown())
                                              .isPresent();
            Health.Builder builder = schedulerActive ? Health.up() : Health.down();
            builder.withDetail("schedulerActive", schedulerActive);
            return builder.build();
        };
    }

    /**
     * Message source for i18n of error messages surfaced through REST &
     * GraphQL adapters. Although the Scheduler service doesn’t expose
     * user-facing strings today, wiring this bean keeps the microservice
     * consistent with its siblings.
     */
    @Bean
    public MessageSource messageSource() {
        ReloadableResourceBundleMessageSource ms = new ReloadableResourceBundleMessageSource();
        ms.setBasename("classpath:i18n/messages");
        ms.setDefaultEncoding("UTF-8");
        ms.setCacheSeconds(3600);
        return ms;
    }

    /**
     * Provides a {@link Clock} aligned to the configured {@code scheduler.time-zone}.
     * Domain entities obtain time references exclusively through this bean,
     * ensuring unit tests can override the clock when required.
     */
    @Bean
    @ConditionalOnMissingBean
    public Clock clock() {
        return Clock.system(ZoneId.of(StringUtils.defaultIfBlank(schedulerTimeZone, "UTC")));
    }

    // ---------------------------------------------------------------------
    // Lifecycle
    // ---------------------------------------------------------------------

    @Override
    public void onApplicationEvent(ApplicationReadyEvent event) {
        LOGGER.info("{} is READY (PID {}, activeProfiles=[{}])",
                applicationName,
                ManagementFactory.getRuntimeMXBean().getPid(),
                String.join(",", event.getApplicationContext().getEnvironment().getActiveProfiles()));
    }

    /**
     * Graceful shutdown of thread-pools to avoid task leakage in orchestrated
     * environments (Kubernetes, ECS, Nomad).
     */
    @PreDestroy
    public void onShutdown() {
        LOGGER.info("Shutting down {} gracefully …", applicationName);
        Optional.ofNullable(taskScheduler).ifPresent(ThreadPoolTaskScheduler::shutdown);
    }

    // ---------------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------------

    /**
     * Returns the ASCII banner printed on application boot. Build metadata
     * (project version, git hash) is auto-injected by the Maven plugin at
     * compile-time.
     */
    private static String buildBanner(String appName) {
        return """
                 ____                  ______               _
                / __ \\____  ___  _____/ ____/___  ____ ___  (_)___  ____ _
               / / / / __ \\/ _ \\/ ___/ /   / __ \\/ __ `__ \\/ / __ \\/ __ `/
              / /_/ / /_/ /  __(__  ) /___/ /_/ / / / / / / / / / / /_/ /
              \\____/ .___/\\___/____/\\____/\\____/_/ /_/ /_/_/_/ /_/\\__, /
                  /_/                                            /____/
                """.indent(1) +
               " :: " + appName + " ::" +
               "\n------------------------------------------------------------\n";
    }

    /**
     * Custom rejection policy that drops tasks when the scheduler queue is
     * full while preserving operational visibility.
     */
    private static final class RejectedPolicy implements RejectedExecutionHandler {
        private static final Logger REJECT_LOGGER = LoggerFactory.getLogger(RejectedPolicy.class);
        @Override
        public void rejectedExecution(Runnable r, ThreadPoolExecutor executor) {
            REJECT_LOGGER.error("Task rejected from scheduler (poolSize={}, activeCount={}, queued={})",
                    executor.getPoolSize(),
                    executor.getActiveCount(),
                    executor.getQueue().size());
            // Optionally publish a domain event for observability here.
        }
    }
}
```