```java
package com.commercesphere.enterprise.config;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.binder.executor.ExecutorServiceMetrics;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.task.AsyncConfigurer;
import org.springframework.core.task.AsyncTaskExecutor;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.util.ErrorHandler;
import org.springframework.util.ReflectionUtils;

import javax.annotation.PreDestroy;
import java.lang.reflect.Method;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;

/**
 * AsyncConfig wires a dedicated, instrumented thread pool that backs all
 * @Async method invocations throughout the CommerceSphere monolith.
 *
 * <p>The pool is:
 * <ul>
 *   <li>Sized via externalized configuration for quick tuning in production.</li>
 *   <li>Decorated with MDC propagation for consistent request tracing.</li>
 *   <li>Bridged to Micrometer for insight into utilization and queue depth.</li>
 *   <li>Equipped with a resilient AsyncUncaughtExceptionHandler that logs and
 *       surfaces unexpected errors to the application's centralized
 *       ErrorHandler.</li>
 * </ul>
 */
@Configuration
@EnableAsync
public class AsyncConfig implements AsyncConfigurer, InitializingBean {

    private static final Logger LOGGER = LoggerFactory.getLogger(AsyncConfig.class);

    @Value("${commercesphere.async.corePoolSize:10}")
    private int corePoolSize;

    @Value("${commercesphere.async.maxPoolSize:50}")
    private int maxPoolSize;

    @Value("${commercesphere.async.queueCapacity:10_000}")
    private int queueCapacity;

    @Value("${commercesphere.async.keepAliveSeconds:60}")
    private int keepAliveSeconds;

    private final MeterRegistry meterRegistry;
    private ThreadPoolTaskExecutor internalExecutor;

    public AsyncConfig(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
    }

    @Override
    public void afterPropertiesSet() {
        LOGGER.info("Initializing async thread pool. corePoolSize={}, maxPoolSize={}, queueCapacity={}, keepAlive={}",
                corePoolSize, maxPoolSize, queueCapacity, keepAliveSeconds);
    }

    /**
     * Central asynchronous executor configured for the entire application.
     * Uses a CallerRunsPolicy fallback to guarantee task execution when the
     * queue is saturated, while applying a TaskDecorator that clones the MDC
     * for log correlation across threads.
     */
    @Override
    @Bean(name = "applicationAsyncExecutor")
    public AsyncTaskExecutor getAsyncExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();

        executor.setThreadNamePrefix("cs-async-");
        executor.setCorePoolSize(corePoolSize);
        executor.setMaxPoolSize(maxPoolSize);
        executor.setQueueCapacity(queueCapacity);
        executor.setKeepAliveSeconds(keepAliveSeconds);
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.setTaskDecorator(new MdcTaskDecorator());
        executor.initialize();

        // bind executor for metrics
        Executor instrumented = ExecutorServiceMetrics.monitor(
                meterRegistry,
                executor.getThreadPoolExecutor(),
                "commercesphere.async",
                "purpose",
                "application-async"
        );
        this.internalExecutor = executor;
        return (AsyncTaskExecutor) instrumented;
    }

    /**
     * Handles all uncaught exceptions thrown from @Async methods that return void.
     */
    @Override
    public org.springframework.aop.interceptor.AsyncUncaughtExceptionHandler getAsyncUncaughtExceptionHandler() {
        return new LoggingAsyncExceptionHandler();
    }

    /**
     * Custom ErrorHandler bean for Spring integration (e.g., SimpleAsyncTaskExecutor).
     * Delegates to the same LoggingAsyncExceptionHandler for consistency.
     */
    @Bean
    public ErrorHandler asyncErrorHandler() {
        return throwable -> new LoggingAsyncExceptionHandler().accept(throwable, null, null);
    }

    /**
     * Gracefully shut down the async executor, awaiting completion of queued tasks
     * to avoid data loss during controlled deployments.
     */
    @PreDestroy
    public void shutDown() {
        if (internalExecutor == null) {
            return;
        }
        LOGGER.info("Shutting down async executor. Waiting up to 30s for tasks to finish.");
        internalExecutor.setAwaitTerminationSeconds((int) Duration.ofSeconds(30).toSeconds());
        internalExecutor.shutdown();
    }

    /**
     * Propagates MDC context from the calling thread to the async thread so that
     * log statements contain the same correlation identifiers (e.g., requestId).
     */
    private static class MdcTaskDecorator implements org.springframework.core.task.TaskDecorator {

        @Override
        public Runnable decorate(Runnable runnable) {
            Map<String, String> context = MDC.getCopyOfContextMap();
            return () -> {
                if (context != null) {
                    MDC.setContextMap(context);
                }
                try {
                    runnable.run();
                } finally {
                    MDC.clear();
                }
            };
        }
    }

    /**
     * Async exception handler that logs the root cause and delegates to the
     * application-wide ErrorHandler, if present.
     */
    private static class LoggingAsyncExceptionHandler implements org.springframework.aop.interceptor.AsyncUncaughtExceptionHandler {

        private static final Logger EX_LOGGER = LoggerFactory.getLogger(LoggingAsyncExceptionHandler.class);

        @Override
        public void handleUncaughtException(Throwable ex, Method method, Object... params) {
            accept(ex, method, params);
        }

        void accept(Throwable ex, Method method, Object[] params) {
            EX_LOGGER.error("Unhandled async exception in method '{}': {}", method, ex.toString(), ex);

            // Example hook for centralized error publisher (not shown):
            // errorPublisher.publish(ex, method, params);

            // Attempt to retrieve a globally configured ErrorHandler
            ErrorHandler globalHandler = AsyncConfig.lookupGlobalErrorHandler();
            if (globalHandler != null) {
                try {
                    globalHandler.handleError(ex);
                } catch (Exception handlerEx) {
                    EX_LOGGER.warn("Global ErrorHandler threw an exception while handling async error", handlerEx);
                }
            }
        }
    }

    /**
     * Spring does not expose a direct API to retrieve an ErrorHandler, so we
     * look it up via reflection to avoid tight coupling. This is a best-effort
     * fallback; failing to find one is not considered fatal.
     */
    private static ErrorHandler lookupGlobalErrorHandler() {
        try {
            Class<?> dispatcherClass = Class.forName("org.springframework.aop.interceptor.AsyncExecutionAspectSupport");
            Method method = ReflectionUtils.findMethod(dispatcherClass, "getDefaultErrorHandler");
            if (method != null) {
                ReflectionUtils.makeAccessible(method);
                return (ErrorHandler) method.invoke(null);
            }
        } catch (Exception ex) {
            LOGGER.debug("Unable to locate global ErrorHandler via reflection", ex);
        }
        return null;
    }
}
```