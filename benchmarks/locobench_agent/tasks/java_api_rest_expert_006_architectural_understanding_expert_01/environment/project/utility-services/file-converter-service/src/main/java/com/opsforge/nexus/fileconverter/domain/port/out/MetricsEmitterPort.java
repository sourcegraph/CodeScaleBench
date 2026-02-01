package com.opsforge.nexus.fileconverter.domain.port.out;

import java.time.Duration;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;

/**
 * Outbound port used by the File-Converter domain to publish runtime metrics to a
 * monitoring system (e.g., Prometheus, Datadog, New Relic). <p>
 *
 * <b>Design Goals</b>
 * <ul>
 *   <li>Remain agnostic of the underlying metrics provider (Micrometer, Dropwizard, etc.)</li>
 *   <li>Provide a minimal, yet expressive API for the domain layer to capture operational signals</li>
 *   <li>Encourage type-safety through {@link MetricId} constants instead of arbitrary Strings</li>
 *   <li>Facilitate traceability using key-value <i>tag</i> dimensions</li>
 * </ul>
 *
 * The concrete implementation is supplied by an outbound adapter residing in the infrastructure
 * layer and is wired in via dependency injection (e.g., Spring).
 *
 * @author OpsForge
 * @since 1.0.0
 */
public interface MetricsEmitterPort {

    /* --------------------------------------------------------------------- */
    /* ------------------------------  API  -------------------------------- */
    /* --------------------------------------------------------------------- */

    /**
     * Increments a counter by {@code amount}. Use for monotonic values such as
     * number of files converted or failed requests.
     *
     * @param metricId identifier of the counter
     * @param amount   the positive delta (must be &gt; 0)
     * @param tags     contextual dimensions (may be {@code null} or empty)
     * @throws NullPointerException     if {@code metricId} is {@code null}
     * @throws IllegalArgumentException if {@code amount} is not strictly positive
     */
    void incrementCounter(MetricId metricId, double amount, Map<String, String> tags);

    /**
     * Records an execution duration. Suitable for timing operations such as
     * parsing, transcoding, or I/O round-trips.
     *
     * @param metricId identifier of the timer
     * @param duration execution time; must be non-negative
     * @param tags     contextual dimensions (may be {@code null} or empty)
     * @throws NullPointerException     if {@code metricId} or {@code duration} is {@code null}
     * @throws IllegalArgumentException if {@code duration} is negative
     */
    void recordDuration(MetricId metricId, Duration duration, Map<String, String> tags);

    /**
     * Records the current value of a gauge (e.g., queue size, memory usage).
     *
     * @param metricId identifier of the gauge
     * @param value    instantaneous value
     * @param tags     contextual dimensions (may be {@code null} or empty)
     * @throws NullPointerException if {@code metricId} is {@code null}
     */
    void recordGauge(MetricId metricId, double value, Map<String, String> tags);

    /**
     * Records an occurrence of the given {@linkplain Throwable exception}.
     *
     * @param metricId identifier of the exception counter
     * @param exception must not be {@code null}
     * @param tags      contextual dimensions (may be {@code null} or empty)
     * @throws NullPointerException if {@code metricId} or {@code exception} is {@code null}
     */
    void recordException(MetricId metricId, Throwable exception, Map<String, String> tags);

    /* --------------------------------------------------------------------- */
    /* --------------------------  CONVENIENCE  ---------------------------- */
    /* --------------------------------------------------------------------- */

    /**
     * Convenience overload without tags.
     */
    default void incrementCounter(MetricId metricId, double amount) {
        incrementCounter(metricId, amount, Collections.emptyMap());
    }

    /**
     * Convenience overload without tags.
     */
    default void recordDuration(MetricId metricId, Duration duration) {
        recordDuration(metricId, duration, Collections.emptyMap());
    }

    /**
     * Convenience overload without tags.
     */
    default void recordGauge(MetricId metricId, double value) {
        recordGauge(metricId, value, Collections.emptyMap());
    }

    /**
     * Convenience overload without tags.
     */
    default void recordException(MetricId metricId, Throwable exception) {
        recordException(metricId, exception, Collections.emptyMap());
    }

    /* --------------------------------------------------------------------- */
    /* ---------------------------  HELPERS  ------------------------------- */
    /* --------------------------------------------------------------------- */

    /**
     * Canonical list of metric identifiers produced by the File-Converter utility.
     * Feel free to add additional constants as the domain evolves.
     */
    enum MetricId {

        /* -------- Converter Core -------- */
        FILE_CONVERSION_COUNT,
        FILE_CONVERSION_FAILURE_COUNT,
        FILE_CONVERSION_DURATION,

        /* -------- I/O -------- */
        SOURCE_READ_DURATION,
        TARGET_WRITE_DURATION,

        /* -------- System Health -------- */
        JVM_HEAP_UTILIZATION,
        THREAD_POOL_QUEUE_SIZE
    }

    /**
     * Static utility for tag validation and defensive copying.
     */
    static Map<String, String> sanitizeTags(Map<String, String> tags) {
        if (tags == null || tags.isEmpty()) {
            return Collections.emptyMap();
        }
        // Defensive copy & null-key / null-value protection
        return tags.entrySet()
                   .stream()
                   .filter(e -> Objects.nonNull(e.getKey()) && Objects.nonNull(e.getValue()))
                   .collect(java.util.stream.Collectors.toUnmodifiableMap(Map.Entry::getKey, Map.Entry::getValue));
    }
}