package com.opsforge.nexus.fileconverter.adapter.out.monitoring;

import com.opsforge.nexus.fileconverter.domain.model.ErrorCategory;
import com.opsforge.nexus.fileconverter.application.port.out.MetricsEmitterPort;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.Meter.Type;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/**
 * Micrometer-backed implementation of {@link MetricsEmitterPort}.
 *
 * <p>This adapter is responsible solely for transforming the domain-level metric events exposed
 * by the application layer into concrete Micrometer {@link io.micrometer.core.instrument.Meter}
 * instances.  It does <em>not</em> perform any aggregation or complex business logic&mdash;those
 * concerns belong in either the core domain or the monitoring backend (Prometheus, Datadog, …).
 *
 * <p>All meters are tagged with the source and target formats to facilitate fine-grained alerting
 * and dashboard segmentation.
 */
@Component
public class MicrometerMetricsEmitterAdapter implements MetricsEmitterPort {

    private static final Logger log = LoggerFactory.getLogger(MicrometerMetricsEmitterAdapter.class);

    private static final String TAG_SOURCE_FORMAT = "source_format";
    private static final String TAG_TARGET_FORMAT = "target_format";
    private static final String TAG_ERROR_CATEGORY = "error_category";
    private static final String TAG_DIRECTION = "direction";

    private static final String METRIC_CONVERSION_SUCCESS_TOTAL = "file_converter_conversion_success_total";
    private static final String METRIC_CONVERSION_FAILURE_TOTAL = "file_converter_conversion_failure_total";
    private static final String METRIC_CONVERSION_LATENCY = "file_converter_conversion_latency";
    private static final String METRIC_FILE_SIZE_BYTES = "file_converter_file_size_bytes";

    private final MeterRegistry registry;

    /**
     * Micrometer doesn't allow late mutation of a meter's tag set, therefore we cache counters & timers
     * by a composite key to prevent meter cardinality explosion and redundant registrations.
     */
    private final ConcurrentMap<MetricKey, Counter> successCounters = new ConcurrentHashMap<>();
    private final ConcurrentMap<MetricKey, Counter> failureCounters = new ConcurrentHashMap<>();
    private final ConcurrentMap<MetricKey, Timer> latencyTimers = new ConcurrentHashMap<>();

    /**
     * Distribution summaries don't require caching because they are always registered
     * with well-known, low-cardinality tag sets.
     */
    private final DistributionSummary inputFileSizeSummary;
    private final DistributionSummary outputFileSizeSummary;

    public MicrometerMetricsEmitterAdapter(MeterRegistry registry) {
        this.registry = Objects.requireNonNull(registry, "registry must not be null");

        inputFileSizeSummary = DistributionSummary.builder(METRIC_FILE_SIZE_BYTES)
                                                  .baseUnit("bytes")
                                                  .description("Input file size distribution")
                                                  .tags(TAG_DIRECTION, "in")
                                                  .register(registry);

        outputFileSizeSummary = DistributionSummary.builder(METRIC_FILE_SIZE_BYTES)
                                                   .baseUnit("bytes")
                                                   .description("Output file size distribution")
                                                   .tags(TAG_DIRECTION, "out")
                                                   .register(registry);
    }

    // -------------------------------------------------------------------------
    // MetricsEmitterPort
    // -------------------------------------------------------------------------

    @Override
    public void onConversionSuccess(@NonNull String sourceFormat,
                                    @NonNull String targetFormat,
                                    @NonNull Duration processingTime,
                                    long inputBytes,
                                    long outputBytes) {

        String safeSrc = safeFormat(sourceFormat);
        String safeTgt = safeFormat(targetFormat);

        // ---- COUNTER -------------------------------------------------------------------------
        getSuccessCounter(safeSrc, safeTgt).increment();

        // ---- TIMER ---------------------------------------------------------------------------
        getLatencyTimer(safeSrc, safeTgt).record(processingTime);

        // ---- DISTRIBUTION SUMMARY ------------------------------------------------------------
        if (inputBytes >= 0) {
            inputFileSizeSummary.record(inputBytes);
        }
        if (outputBytes >= 0) {
            outputFileSizeSummary.record(outputBytes);
        }
    }

    @Override
    public void onConversionFailure(@NonNull String sourceFormat,
                                    @NonNull String targetFormat,
                                    @NonNull ErrorCategory category,
                                    @NonNull Duration processingTime) {

        String safeSrc = safeFormat(sourceFormat);
        String safeTgt = safeFormat(targetFormat);

        // ---- COUNTER -------------------------------------------------------------------------
        getFailureCounter(safeSrc, safeTgt, category).increment();

        // Even for failures we still want to record latency; this helps detect slowness patterns.
        getLatencyTimer(safeSrc, safeTgt).record(processingTime);
    }

    // -------------------------------------------------------------------------
    // Internal helpers
    // -------------------------------------------------------------------------

    private Counter getSuccessCounter(String sourceFormat, String targetFormat) {
        MetricKey key = MetricKey.of(sourceFormat, targetFormat);
        return successCounters.computeIfAbsent(key, k ->
            Counter.builder(METRIC_CONVERSION_SUCCESS_TOTAL)
                   .description("Number of successful file conversions")
                   .tags(TAG_SOURCE_FORMAT, k.sourceFormat,
                         TAG_TARGET_FORMAT, k.targetFormat)
                   .register(registry));
    }

    private Counter getFailureCounter(String sourceFormat,
                                      String targetFormat,
                                      ErrorCategory category) {
        MetricKey key = MetricKey.of(sourceFormat, targetFormat, category);
        return failureCounters.computeIfAbsent(key, k ->
            Counter.builder(METRIC_CONVERSION_FAILURE_TOTAL)
                   .description("Number of failed file conversions")
                   .tags(TAG_SOURCE_FORMAT, k.sourceFormat,
                         TAG_TARGET_FORMAT, k.targetFormat,
                         TAG_ERROR_CATEGORY, k.errorCategory.name().toLowerCase())
                   .register(registry));
    }

    private Timer getLatencyTimer(String sourceFormat, String targetFormat) {
        MetricKey key = MetricKey.of(sourceFormat, targetFormat);
        return latencyTimers.computeIfAbsent(key, k ->
            Timer.builder(METRIC_CONVERSION_LATENCY)
                 .description("Latency of file conversions")
                 .tags(TAG_SOURCE_FORMAT, k.sourceFormat,
                       TAG_TARGET_FORMAT, k.targetFormat)
                 .publishPercentileHistogram()       // enables SLA dashboarding
                 .publishPercentiles(0.5, 0.95, 0.99)
                 .register(registry));
    }

    /**
     * Normalises an input format string to ensure we never produce a null or empty tag value,
     * which would violate Micrometer tag semantics and could blow up Prometheus scraping.
     */
    private static String safeFormat(String format) {
        return (format == null || format.isBlank()) ? "unknown" : format.toLowerCase();
    }

    // -------------------------------------------------------------------------
    // Value Object for meter caching
    // -------------------------------------------------------------------------

    private static final class MetricKey {
        private final String sourceFormat;
        private final String targetFormat;
        private final ErrorCategory errorCategory; // Nullable only for success metrics/timers

        private MetricKey(String sourceFormat, String targetFormat, ErrorCategory errorCategory) {
            this.sourceFormat = sourceFormat;
            this.targetFormat = targetFormat;
            this.errorCategory = errorCategory;
        }

        static MetricKey of(String sourceFormat, String targetFormat) {
            return new MetricKey(sourceFormat, targetFormat, null);
        }

        static MetricKey of(String sourceFormat, String targetFormat, ErrorCategory category) {
            return new MetricKey(sourceFormat, targetFormat, category);
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof MetricKey)) return false;
            MetricKey that = (MetricKey) o;
            return Objects.equals(sourceFormat, that.sourceFormat)
                && Objects.equals(targetFormat, that.targetFormat)
                && Objects.equals(errorCategory, that.errorCategory);
        }

        @Override
        public int hashCode() {
            return Objects.hash(sourceFormat, targetFormat, errorCategory);
        }
    }
}