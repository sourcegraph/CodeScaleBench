```java
package com.opsforge.utilitynexus.setup;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.opsforge.utilitynexus.common.metrics.MetricRegistry;
import com.opsforge.utilitynexus.common.version.ApiVersionRegistry;
import com.opsforge.utilitynexus.common.version.Version;
import com.opsforge.utilitynexus.common.error.ExceptionUnwrapper;
import com.opsforge.utilitynexus.common.error.ModuleInitializationException;
import com.opsforge.utilitynexus.spi.UtilityModule;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.Closeable;
import java.io.IOException;
import java.lang.invoke.MethodHandles;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.Collectors;

/**
 * Central bootstrap class responsible for wiring together:
 *  – Utility modules discovered at runtime (via {@link ServiceLoader})
 *  – Cross-cutting concerns (caching, metrics, version registry)
 *  – Graceful shutdown hooks
 *
 * This class purposefully avoids Spring or Micronaut to demonstrate how
 * OpsForge can be embedded in a host that does not rely on an IoC container
 * (e.g., a serverless runtime or an OSGi container).
 *
 * Usage:
 *   Setup bootstrap = Setup.builder().environment(Environment.PROD).build();
 *   bootstrap.init();   // start all modules
 *   bootstrap.await();  // block current thread until CTRL+C
 */
public final class Setup implements Closeable {

    private static final Logger LOG = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());

    private final Environment environment;
    private final MetricRegistry metricRegistry;
    private final ApiVersionRegistry versionRegistry;
    private final ScheduledExecutorService scheduler;
    private final Cache<String, Object> responseCache;
    private final Map<String, UtilityModule> initializedModules = new ConcurrentHashMap<>();
    private final CountDownLatch shutdownLatch = new CountDownLatch(1);
    private volatile boolean started;

    private Setup(Builder builder) {
        this.environment = builder.environment;
        this.metricRegistry = builder.metricRegistry != null ? builder.metricRegistry : new MetricRegistry();
        this.versionRegistry = new ApiVersionRegistry();
        this.scheduler = Executors.newScheduledThreadPool(Runtime.getRuntime().availableProcessors() * 2,
                r -> new Thread(r, "utility-scheduler-" + UUID.randomUUID()));
        this.responseCache = Caffeine.newBuilder()
                                     .expireAfterWrite(Duration.ofMinutes(15))
                                     .maximumSize(builder.cacheMaxSize)
                                     .recordStats()
                                     .build();

        Runtime.getRuntime().addShutdownHook(new Thread(this::close, "opsforge-shutdown"));
    }

    /* -----------------------------------------------------------------------------------------------------------------
                                              PUBLIC  API
     ---------------------------------------------------------------------------------------------------------------- */

    /**
     * Bootstraps the system: discovers and initializes all utility modules.
     */
    public void init() {
        if (started) {
            LOG.warn("Setup already initialized; skipping.");
            return;
        }
        long ts = System.nanoTime();

        discoverAndInitializeModules();
        Version platformVersion = Version.resolveFromClasspath().orElse(Version.UNKNOWN);
        versionRegistry.setPlatformVersion(platformVersion);

        started = true;
        LOG.info("OpsForge Utility Nexus bootstrapped in {} ms (env={})",
                 TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - ts), environment);
    }

    /**
     * Blocks the current thread until the JVM is terminated.
     *
     * <p>This convenience method is useful for CLI or fat-jar deployments that
     * should keep running (e.g., for HTTP servers).</p>
     */
    public void await() {
        try {
            shutdownLatch.await();
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            LOG.warn("Await interrupted", ie);
        }
    }

    /**
     * Returns an immutable view of all loaded modules keyed by their names.
     */
    public Map<String, UtilityModule> modules() {
        return Collections.unmodifiableMap(initializedModules);
    }

    /**
     * Exposes the shared response cache that modules can leverage to store
     * pre-computed results or rate-limiting tokens.
     */
    public Cache<String, Object> responseCache() {
        return responseCache;
    }

    /* -----------------------------------------------------------------------------------------------------------------
                                              INTERNAL BOOT LOGIC
     ---------------------------------------------------------------------------------------------------------------- */

    private void discoverAndInitializeModules() {
        ServiceLoader<UtilityModule> loader = ServiceLoader.load(UtilityModule.class);
        List<Throwable> fatalErrors = new ArrayList<>();

        for (UtilityModule module : loader) {
            try {
                initModule(module);
            } catch (Throwable t) {
                fatalErrors.add(t);
            }
        }

        if (!fatalErrors.isEmpty()) {
            Exception aggregated = new ModuleInitializationException("One or more modules failed to initialize",
                                                                     fatalErrors.stream()
                                                                                .map(ExceptionUnwrapper::rootCause)
                                                                                .collect(Collectors.toList()));
            LOG.error("Aborting startup. {} modules could not be initialized.", fatalErrors.size(), aggregated);
            throw aggregated;
        }
    }

    private void initModule(UtilityModule module) {
        String name = module.getName();
        long ts = System.nanoTime();
        module.initialize(new ModuleContextImpl(this));

        initializedModules.put(name, module);
        versionRegistry.registerModule(name, module.version());

        LOG.info("Initialized module '{}' in {} ms (version={})",
                 name, TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - ts), module.version());
    }

    /* -----------------------------------------------------------------------------------------------------------------
                                              CLEANUP
     ---------------------------------------------------------------------------------------------------------------- */

    @Override
    public void close() {
        if (!started) {
            return;
        }

        long ts = System.nanoTime();
        List<Throwable> errors = new ArrayList<>();

        initializedModules.values().forEach(m -> {
            try {
                m.shutdown();
            } catch (Throwable t) {
                errors.add(t);
            }
        });

        scheduler.shutdown();
        try {
            if (!scheduler.awaitTermination(10, TimeUnit.SECONDS)) {
                LOG.warn("Scheduler did not terminate within timeout; forcing shutdown.");
                scheduler.shutdownNow();
            }
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
        }

        metricRegistry.close();
        responseCache.invalidateAll();
        responseCache.cleanUp();

        started = false;
        shutdownLatch.countDown();
        LOG.info("OpsForge shutdown complete in {} ms (errorsDuringShutdown={})",
                 TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - ts), errors.size());

        if (!errors.isEmpty()) {
            LOG.debug("Shutdown errors: {}", errors);
        }
    }

    /* -----------------------------------------------------------------------------------------------------------------
                                              BUILDER
     ---------------------------------------------------------------------------------------------------------------- */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private Environment environment = Environment.LOCAL;
        private MetricRegistry metricRegistry;
        private long cacheMaxSize = 10_000;

        private Builder() { /* no-op */ }

        public Builder environment(Environment environment) {
            this.environment = Objects.requireNonNull(environment, "environment");
            return this;
        }

        public Builder metricRegistry(MetricRegistry metricRegistry) {
            this.metricRegistry = Objects.requireNonNull(metricRegistry, "metricRegistry");
            return this;
        }

        public Builder cacheMaxSize(long cacheMaxSize) {
            if (cacheMaxSize <= 0) {
                throw new IllegalArgumentException("cacheMaxSize must be > 0");
            }
            this.cacheMaxSize = cacheMaxSize;
            return this;
        }

        public Setup build() {
            return new Setup(this);
        }
    }

    /* -----------------------------------------------------------------------------------------------------------------
                                              ENVIRONMENT ENUM
     ---------------------------------------------------------------------------------------------------------------- */

    public enum Environment {
        LOCAL, DEV, QA, STAGING, PROD;

        public static Environment from(String raw) {
            if (raw == null || raw.isBlank()) {
                return LOCAL;
            }
            return Arrays.stream(values())
                         .filter(e -> e.name().equalsIgnoreCase(raw))
                         .findFirst()
                         .orElseThrow(() -> new IllegalArgumentException("Unknown env: " + raw));
        }
    }

    /* -----------------------------------------------------------------------------------------------------------------
                                              MODULE CONTEXT
     ---------------------------------------------------------------------------------------------------------------- */

    private static final class ModuleContextImpl implements UtilityModule.ModuleContext {

        private final Setup setup;

        ModuleContextImpl(Setup setup) {
            this.setup = setup;
        }

        @Override
        public Environment environment() {
            return setup.environment;
        }

        @Override
        public ScheduledExecutorService scheduler() {
            return setup.scheduler;
        }

        @Override
        public MetricRegistry metricRegistry() {
            return setup.metricRegistry;
        }

        @Override
        public ApiVersionRegistry versionRegistry() {
            return setup.versionRegistry;
        }

        @Override
        public Cache<String, Object> sharedResponseCache() {
            return setup.responseCache;
        }

        @Override
        public Path tempDirectory() {
            try {
                return Files.createTempDirectory("opsforge-module-");
            } catch (IOException ioe) {
                throw new UncheckedIOException("Unable to create temp dir", ioe);
            }
        }
    }
}
```

```java
package com.opsforge.utilitynexus.common.metrics;

import java.io.Closeable;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Lightweight drop-wizard-style in-memory metric registry. Specific deployments
 * may swap this by implementing the same public methods (Hexagonal Out Port).
 */
public class MetricRegistry implements Closeable {

    private final Map<String, Long> counters = new ConcurrentHashMap<>();

    public void increment(String name) {
        counters.merge(name, 1L, Long::sum);
    }

    public long counter(String name) {
        return counters.getOrDefault(name, 0L);
    }

    @Override
    public void close() {
        counters.clear();
    }
}
```

```java
package com.opsforge.utilitynexus.common.version;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry that keeps track of platform and module versions.
 * Consumed by the /_health and /_about endpoints as well as GraphQL's introspection.
 */
public final class ApiVersionRegistry {

    private final Map<String, Version> moduleVersions = new ConcurrentHashMap<>();
    private volatile Version platformVersion = Version.UNKNOWN;

    public void setPlatformVersion(Version platformVersion) {
        this.platformVersion = platformVersion;
    }

    public Version platformVersion() {
        return platformVersion;
    }

    public void registerModule(String moduleName, Version version) {
        moduleVersions.put(moduleName, version);
    }

    public Optional<Version> versionOf(String moduleName) {
        return Optional.ofNullable(moduleVersions.get(moduleName));
    }

    public Map<String, Version> allModules() {
        return Map.copyOf(moduleVersions);
    }
}
```

```java
package com.opsforge.utilitynexus.common.version;

import java.util.Optional;

/**
 * Semantic version value object.
 */
public record Version(int major, int minor, int patch, String qualifier) {

    public static final Version UNKNOWN = new Version(0, 0, 0, "UNKNOWN");

    public String asString() {
        return "%d.%d.%d%s".formatted(major, minor, patch,
                                      qualifier == null || qualifier.isBlank() ? "" : "-" + qualifier);
    }

    public static Optional<Version> resolveFromClasspath() {
        String v = Version.class.getPackage().getImplementationVersion();
        if (v == null) { // Running from IDE
            return Optional.empty();
        }
        return Optional.of(parse(v));
    }

    public static Version parse(String raw) {
        if (raw == null) throw new IllegalArgumentException("raw is null");
        String[] mainAndQualifier = raw.split("-", 2);
        String[] parts = mainAndQualifier[0].split("\\.");
        if (parts.length < 3) {
            throw new IllegalArgumentException("Invalid semantic version: " + raw);
        }
        int major = Integer.parseInt(parts[0]);
        int minor = Integer.parseInt(parts[1]);
        int patch = Integer.parseInt(parts[2]);
        String qualifier = mainAndQualifier.length == 2 ? mainAndQualifier[1] : "";
        return new Version(major, minor, patch, qualifier);
    }

    @Override
    public String toString() {
        return asString();
    }
}
```

```java
package com.opsforge.utilitynexus.common.error;

import java.util.List;

/**
 * Thrown when one or more utility modules fail to initialize.
 */
public class ModuleInitializationException extends RuntimeException {

    /**
     * Constructs an aggregated exception message.
     *
     * @param message human readable message
     * @param causes  list of root causes
     */
    public ModuleInitializationException(String message, List<Throwable> causes) {
        super(message + " — see suppressed exceptions for details");
        causes.forEach(this::addSuppressed);
    }
}
```

```java
package com.opsforge.utilitynexus.common.error;

/**
 * Utility for peeling off wrapper exceptions (ExecutionException, CompletionException, etc.).
 */
public final class ExceptionUnwrapper {

    private ExceptionUnwrapper() {
    }

    public static Throwable rootCause(Throwable t) {
        Throwable current = t;
        while (current.getCause() != null &&
               (current instanceof java.util.concurrent.ExecutionException
                       || current instanceof java.util.concurrent.CompletionException
                       || current instanceof java.lang.reflect.InvocationTargetException)) {
            current = current.getCause();
        }
        return current;
    }
}
```

```java
package com.opsforge.utilitynexus.spi;

import com.github.benmanes.caffeine.cache.Cache;
import com.opsforge.utilitynexus.common.metrics.MetricRegistry;
import com.opsforge.utilitynexus.common.version.ApiVersionRegistry;
import com.opsforge.utilitynexus.common.version.Version;

import java.nio.file.Path;
import java.util.concurrent.ScheduledExecutorService;

/**
 * Service Provider Interface for utility modules.
 * Implementations must be declared in
 *   META-INF/services/com.opsforge.utilitynexus.spi.UtilityModule
 */
public interface UtilityModule {

    String getName();

    Version version();

    /**
     * Called exactly once during platform startup.
     */
    void initialize(ModuleContext context) throws Exception;

    /**
     * Called during graceful shutdown.
     */
    default void shutdown() {
        // optional
    }

    /**
     * Context object providing shared resources.
     */
    interface ModuleContext {

        Setup.Environment environment();

        ScheduledExecutorService scheduler();

        MetricRegistry metricRegistry();

        ApiVersionRegistry versionRegistry();

        Cache<String, Object> sharedResponseCache();

        Path tempDirectory();
    }
}
```