package com.opsforge.nexus.fileconverter;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.fasterxml.jackson.module.paramnames.ParameterNamesModule;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.Banner;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.actuate.info.InfoContributor;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.boot.info.BuildProperties;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.context.ApplicationListener;
import org.springframework.context.MessageSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.support.ReloadableResourceBundleMessageSource;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.web.filter.CommonsRequestLoggingFilter;

import javax.annotation.PreDestroy;
import java.time.Duration;
import java.util.Locale;
import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;

/**
 * Main bootstrap class for the File Converter microservice.
 * <p>
 * The class wires common infrastructure beans, such as:
 * <ul>
 *     <li>Thread pool for asynchronous file conversion</li>
 *     <li>Jackson customisation for consistent JSON mapping</li>
 *     <li>i18n message source</li>
 *     <li>Actuator info contributor for build metadata</li>
 * </ul>
 * <p>
 * Hexagonal / clean–architecture rules apply: no business logic is placed here.
 */
@SpringBootApplication
@EnableAsync
@EnableCaching
@EnableScheduling
public class FileConverterApplication implements ApplicationListener<ApplicationReadyEvent> {

    private static final Logger LOGGER = LoggerFactory.getLogger(FileConverterApplication.class);

    private final BuildProperties buildProperties;
    private final MeterRegistry meterRegistry;

    public FileConverterApplication(ObjectProvider<BuildProperties> buildProperties,
                                    ObjectProvider<MeterRegistry> meterRegistry) {
        // Both beans are optional (BuildProperties only exists when built by the Spring Boot plugin)
        this.buildProperties = buildProperties.getIfAvailable();
        this.meterRegistry = meterRegistry.getIfAvailable();
    }

    public static void main(String[] args) {
        SpringApplication application = new SpringApplication(FileConverterApplication.class);
        application.setBanner(FileConverterApplication::printBanner);
        application.run(args);
    }

    private static void printBanner(org.springframework.core.env.Environment environment,
                                    Class<?> sourceClass,
                                    java.io.PrintStream out) {
        out.println(
                "\n" +
                "   ____              ______                    ________                        \n" +
                "  / __ \\____  ____  / ____/___  ____ ___  ___ / ____/ /___  __  ______ ___  ___ \n" +
                " / / / / __ \\/ __ \\/ /   / __ \\/ __ `__ \\/ _ \\\\__  / / __ \\/ / / / __ `__ \\/ _ \\\n" +
                "/ /_/ / /_/ / /_/ / /___/ /_/ / / / / / /  __/__/ / / /_/ / /_/ / / / / / /  __/\n" +
                "\\____/\\____/ .___/\\____/\\____/_/ /_/ /_/\\___/____/_/\\____/\\__,_/_/ /_/ /_/\\___/ \n" +
                "          /_/                                                                    \n");
    }

    @Override
    public void onApplicationEvent(ApplicationReadyEvent event) {
        String version = buildProperties != null ? buildProperties.getVersion() : "development-snapshot";
        LOGGER.info("OpsForge File Converter Service [{}] started with profiles: {}",
                version,
                String.join(",", event.getApplicationContext().getEnvironment().getActiveProfiles()));

        if (meterRegistry != null) {
            meterRegistry.gauge("file_converter.jvm.active_threads", Thread.activeCount());
        }
    }

    /**
     * Dedicated thread pool for CPU–intensive conversions.
     */
    @Bean("conversionExecutor")
    public Executor conversionExecutor() {
        int cores = Runtime.getRuntime().availableProcessors();

        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix("file-converter-");
        executor.setCorePoolSize(Math.max(2, cores));
        executor.setMaxPoolSize(cores * 2);
        executor.setQueueCapacity(1000);
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.setAwaitTerminationSeconds((int) Duration.ofSeconds(60).getSeconds());
        executor.setWaitForTasksToCompleteOnShutdown(true);
        return executor;
    }

    @PreDestroy
    public void onShutdown() {
        LOGGER.info("Shutting down OpsForge File Converter Service gracefully...");
    }

    /**
     * Customise Jackson to play nicely with JavaTime and unknown fields.
     */
    @Bean
    public Jackson2ObjectMapperBuilderCustomizer jacksonCustomizer() {
        return (Jackson2ObjectMapperBuilder builder) -> builder
                .modules(new JavaTimeModule(), new ParameterNamesModule())
                .featuresToDisable(
                        DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES,
                        DeserializationFeature.ADJUST_DATES_TO_CONTEXT_TIME_ZONE)
                .featuresToEnable(
                        DeserializationFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE);
    }

    /**
     * ObjectMapper bean for non-web classes – shares the same settings as MVC.
     */
    @Bean
    public ObjectMapper objectMapper(Jackson2ObjectMapperBuilder builder) {
        return builder.build();
    }

    /**
     * Internationalisation message source (error codes, etc.).
     */
    @Bean
    public MessageSource messageSource() {
        ReloadableResourceBundleMessageSource source = new ReloadableResourceBundleMessageSource();
        source.setBasename("classpath:i18n/messages");
        source.setDefaultEncoding("UTF-8");
        source.setDefaultLocale(Locale.ENGLISH);
        source.setUseCodeAsDefaultMessage(true);
        source.setCacheSeconds(3600); // refresh hourly
        return source;
    }

    /**
     * Simple HTTP request logger for troubleshooting in non-production environments.
     */
    @Bean
    public CommonsRequestLoggingFilter requestLoggingFilter() {
        CommonsRequestLoggingFilter filter = new CommonsRequestLoggingFilter();
        filter.setIncludeQueryString(true);
        filter.setIncludePayload(false);
        filter.setIncludeHeaders(false);
        filter.setAfterMessagePrefix("HTTP ");
        return filter;
    }

    /**
     * Adds build metadata to /actuator/info.
     */
    @Bean
    public InfoContributor buildInfoContributor() {
        return builder -> {
            String version = buildProperties != null ? buildProperties.getVersion() : "development-snapshot";
            builder.withDetail("service", "file-converter-service")
                   .withDetail("version", version);
        };
    }

    /**
     * Logs a friendly startup confirmation.
     */
    @Bean
    public CommandLineRunner startupLogger() {
        return args -> LOGGER.info("File Converter microservice started successfully ✅");
    }
}