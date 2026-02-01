package com.sprintcart.app.config;

import java.time.Duration;
import java.util.Collections;
import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;

import javax.validation.Validator;

import org.modelmapper.ModelMapper;
import org.modelmapper.convention.MatchingStrategies;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.MessageSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.support.ReloadableResourceBundleMessageSource;
import org.springframework.core.task.TaskDecorator;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;
import org.springframework.retry.annotation.EnableRetry;
import org.springframework.retry.backoff.ExponentialBackOffPolicy;
import org.springframework.retry.policy.SimpleRetryPolicy;
import org.springframework.retry.support.RetryTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.validation.beanvalidation.LocalValidatorFactoryBean;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.github.benmanes.caffeine.cache.Caffeine;

/**
 * Centralized Spring bean configuration. <br>
 * All low-level infrastructure components that do not fit a dedicated
 * {@code @Configuration} class live here.
 *
 * Keeping bean creation explicit rather than relying on component scanning
 * makes the project’s wiring predictable and easier to reason about.
 */
@Configuration
@EnableCaching
@EnableRetry
public class BeanConfiguration {

    /**
     * Shared mapper for converting between domain models, DTOs and view models.
     * The strict matching strategy catches accidental mismappings early.
     */
    @Bean
    public ModelMapper modelMapper() {
        ModelMapper mapper = new ModelMapper();
        mapper.getConfiguration()
              .setMatchingStrategy(MatchingStrategies.STRICT)
              .setSkipNullEnabled(true);
        return mapper;
    }

    /**
     * Password encoder with a dedicated strength. The cost factor of 12 is a
     * reasonable trade-off between security and performance for high-traffic
     * e-commerce workloads.
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(12);
    }

    /**
     * Canonical ObjectMapper used by Spring MVC and any outbound adapters. The
     * builder is configured to:
     *   • Ignore unknown properties so that forwards compatibility is preserved
     *   • Exclude null values to shrink response payloads
     */
    @Bean
    public ObjectMapper objectMapper() {
        return Jackson2ObjectMapperBuilder.json()
            .modules(new JavaTimeModule())
            .serializationInclusion(JsonInclude.Include.NON_NULL)
            .featuresToDisable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();
    }

    /**
     * i18n message source that also backs javax.validation messages so that
     * validation errors are localized consistently across REST and the SPA.
     */
    @Bean
    public MessageSource messageSource() {
        ReloadableResourceBundleMessageSource source = new ReloadableResourceBundleMessageSource();
        source.setBasename("classpath:i18n/messages");
        source.setDefaultEncoding("UTF-8");
        source.setCacheSeconds(3_600);    // reload once per hour
        source.setFallbackToSystemLocale(false);
        return source;
    }

    /**
     * Integrates Hibernate Validator with the Spring message source so that
     * custom constraint annotations can reuse the i18n bundle.
     */
    @Bean
    public Validator validator(MessageSource messageSource) {
        LocalValidatorFactoryBean factoryBean = new LocalValidatorFactoryBean();
        factoryBean.setValidationMessageSource(messageSource);
        return factoryBean;
    }

    /**
     * Lightweight, in-process cache used for hot data such as store settings,
     * feature flags, or shipping rate tables. For multi-node deployments a
     * higher-level cache abstraction (e.g., Redis) may sit in front.
     */
    @Bean
    public CacheManager cacheManager() {
        Caffeine<Object, Object> caffeine = Caffeine.newBuilder()
                                                   .maximumSize(10_000)
                                                   .expireAfterWrite(Duration.ofMinutes(30))
                                                   .recordStats();
        CaffeineCacheManager manager = new CaffeineCacheManager();
        manager.setCaffeine(caffeine);
        return manager;
    }

    /**
     * Resilient template for outbound integrations (SMTP, payment gateways…).
     * Retry logic is centralized so that services can @Autowired it instead of
     * implementing ad-hoc error handling each time.
     */
    @Bean
    public RetryTemplate retryTemplate() {
        SimpleRetryPolicy retryPolicy = new SimpleRetryPolicy(
            3,                              // max attempts
            Collections.singletonMap(Exception.class, true)
        );

        ExponentialBackOffPolicy backOff = new ExponentialBackOffPolicy();
        backOff.setInitialInterval(500);
        backOff.setMultiplier(2.0);
        backOff.setMaxInterval(5_000);

        RetryTemplate template = new RetryTemplate();
        template.setRetryPolicy(retryPolicy);
        template.setBackOffPolicy(backOff);
        return template;
    }

    /**
     * Thread pool for asynchronous command handling, email dispatching, and any
     * non-blocking background tasks. The MDC-propagating task decorator ensures
     * that log correlation IDs survive the hop to async threads.
     */
    @Bean(name = "taskExecutor")
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix("sprintcart-exec-");
        executor.setCorePoolSize(10);
        executor.setMaxPoolSize(50);
        executor.setQueueCapacity(1_000);
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.setTaskDecorator(new MdcTaskDecorator());
        executor.initialize();
        return executor;
    }

    /**
     * Decorator that copies the SLF4J MDC from the parent thread to the child
     * so that log statements keep the same trace / correlation IDs.
     */
    private static class MdcTaskDecorator implements TaskDecorator {
        @Override
        public Runnable decorate(Runnable runnable) {
            // Grab a snapshot of the MDC before the task executes
            var contextMap = org.slf4j.MDC.getCopyOfContextMap();
            return () -> {
                try {
                    if (contextMap != null) {
                        org.slf4j.MDC.setContextMap(contextMap);
                    }
                    runnable.run();
                } finally {
                    org.slf4j.MDC.clear();
                }
            };
        }
    }
}