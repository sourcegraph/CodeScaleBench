package com.opsforge.nexus.gateway.graphql;

import com.opsforge.nexus.common.dto.*;
import com.opsforge.nexus.common.exceptions.DomainException;
import com.opsforge.nexus.gateway.graphql.GraphQLDelegationResolver.GatewayException;
import com.opsforge.nexus.gateway.metrics.GatewayMetricsPublisher;
import com.opsforge.nexus.gateway.service.*;
import graphql.kickstart.tools.GraphQLMutationResolver;
import graphql.kickstart.tools.GraphQLQueryResolver;
import graphql.schema.DataFetchingEnvironment;
import io.micrometer.core.instrument.Tag;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.simple.SimpleTimer;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.Tracer;
import org.apache.commons.lang3.StringUtils;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Component;
import org.springframework.validation.annotation.Validated;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;

/**
 * GraphQLDelegationResolver acts as the API-gateway-level adapter between the public GraphQL
 * contract and the internal utility microservices.
 *
 * <p>All resolver methods are intentionally thin: they only validate inbound parameters,
 * enrich the current execution context (e.g. tracing, metrics, and correlation IDs),
 * and then delegate to the corresponding application service.  Any cross-cutting
 * concerns such as caching, rate-limiting, and monitoring are either applied via
 * Spring AOP or explicitly annotated on the resolver method.</p>
 *
 * <p>Because the gateway is versioned, every resolver receives the “apiVersion” argument.
 * Backwards-compatible changes are supported by branching the delegation logic inside
 * the resolver.  When a breaking change is introduced, a new major version is added
 * to the schema and implemented in-parallel.</p>
 */
@Component
@Validated
public class GraphQLDelegationResolver implements GraphQLQueryResolver, GraphQLMutationResolver {

    private static final String METRIC_PREFIX = "opsforge.gateway";

    private final FileConversionService fileConversionService;
    private final ChecksumService checksumService;
    private final TextTransformService textTransformService;
    private final SchedulerService schedulerService;
    private final DataAnonymizationService dataAnonymizationService;
    private final GatewayMetricsPublisher metricsPublisher;
    private final Tracer tracer;
    private final Clock clock;

    public GraphQLDelegationResolver(FileConversionService fileConversionService,
                                     ChecksumService checksumService,
                                     TextTransformService textTransformService,
                                     SchedulerService schedulerService,
                                     DataAnonymizationService dataAnonymizationService,
                                     GatewayMetricsPublisher metricsPublisher,
                                     Tracer tracer,
                                     Clock clock) {
        this.fileConversionService = Objects.requireNonNull(fileConversionService);
        this.checksumService = Objects.requireNonNull(checksumService);
        this.textTransformService = Objects.requireNonNull(textTransformService);
        this.schedulerService = Objects.requireNonNull(schedulerService);
        this.dataAnonymizationService = Objects.requireNonNull(dataAnonymizationService);
        this.metricsPublisher = Objects.requireNonNull(metricsPublisher);
        this.tracer = Objects.requireNonNull(tracer);
        this.clock = Objects.requireNonNull(clock);
    }

    /* -----------------------------------------------------------
     *  GraphQL Query resolvers
     * -----------------------------------------------------------
     */

    /**
     * Generates a checksum (MD5, SHA-1, SHA-256, etc.) for the supplied payload.
     * <p>
     * The result is cached for 10 minutes because checksum generation is
     * deterministic and CPU-bound.  Caching improves response times for
     * frequently repeated requests such as health-checks or validation jobs.
     */
    @Cacheable(
            cacheNames = {"checksum"},
            key = "#input.algorithm + ':' + #input.base64Payload",
            unless = "#result == null"
    )
    public CompletionStage<ChecksumResultDTO> generateChecksum(@NotNull @Valid ChecksumInputDTO input,
                                                               DataFetchingEnvironment env) {
        final Span span = tracer.spanBuilder("generateChecksum").startSpan();
        final Timer.Sample sample = Timer.start();
        return CompletableFuture.supplyAsync(() -> {
            try {
                meter("checksum.invocation.count");
                ChecksumResultDTO dto = checksumService.generate(input);
                meter("checksum.success.count");
                return dto;
            } catch (DomainException ex) {
                span.recordException(ex);
                meter("checksum.failure.count");
                throw GatewayException.wrap(ex);
            } finally {
                span.end();
                recordLatency("checksum.latency", sample);
            }
        });
    }

    /**
     * Converts a file from one supported format to another.  The operation is
     * asynchronous because conversions may take a long time (e.g., large PDFs).
     *
     * @return a {@link ConversionResultDTO} that contains the location of the
     * converted file or the conversion job ID if the operation is still running.
     */
    public CompletionStage<ConversionResultDTO> convertFileFormat(@NotNull @Valid ConvertFileFormatInputDTO input,
                                                                  String apiVersion,
                                                                  DataFetchingEnvironment env) {
        final Span span = tracer.spanBuilder("convertFileFormat")
                                .setAttribute("apiVersion", apiVersion)
                                .startSpan();
        final Timer.Sample sample = Timer.start();
        return CompletableFuture.supplyAsync(() -> {
            try {
                meter("conversion.invocation.count", Tag.of("apiVersion", apiVersion));
                validateConvertInput(input);
                ConversionResultDTO dto = fileConversionService.convert(input, apiVersion);
                meter("conversion.success.count", Tag.of("apiVersion", apiVersion));
                return dto;
            } catch (DomainException ex) {
                span.recordException(ex);
                meter("conversion.failure.count", Tag.of("apiVersion", apiVersion));
                throw GatewayException.wrap(ex);
            } finally {
                span.end();
                recordLatency("conversion.latency", sample, Tag.of("apiVersion", apiVersion));
            }
        });
    }

    /**
     * Retrieves a paginated list of text transformation rules.  Supports relay-style
     * cursor pagination as well as traditional offset/limit.
     */
    public PaginatedTextTransformRuleDTO listTextTransformRules(@NotNull PaginationInputDTO page,
                                                                String apiVersion) {
        try {
            meter("transformRules.invocation.count", Tag.of("apiVersion", apiVersion));
            return textTransformService.listRules(page, apiVersion);
        } catch (DomainException ex) {
            meter("transformRules.failure.count", Tag.of("apiVersion", apiVersion));
            throw GatewayException.wrap(ex);
        }
    }

    /* -----------------------------------------------------------
     *  GraphQL Mutation resolvers
     * -----------------------------------------------------------
     */

    /**
     * Schedules a job for later execution in a time-zone aware manner.
     */
    public ScheduleJobResultDTO scheduleJob(@NotNull @Valid ScheduleJobInputDTO input,
                                            DataFetchingEnvironment env) {
        final Span span = tracer.spanBuilder("scheduleJob").startSpan();
        final Timer.Sample sample = Timer.start();
        try {
            meter("scheduler.invocation.count");
            ScheduleJobResultDTO dto = schedulerService.scheduleJob(input, Instant.now(clock));
            meter("scheduler.success.count");
            return dto;
        } catch (DomainException ex) {
            span.recordException(ex);
            meter("scheduler.failure.count");
            throw GatewayException.wrap(ex);
        } finally {
            span.end();
            recordLatency("scheduler.latency", sample);
        }
    }

    /**
     * Applies data anonymization transformations to a data set.
     */
    public AnonymizationResultDTO anonymizeDataset(@Valid @NotNull AnonymizationInputDTO input) {
        try {
            meter("anonymization.invocation.count");
            return dataAnonymizationService.anonymize(input);
        } catch (DomainException ex) {
            meter("anonymization.failure.count");
            throw GatewayException.wrap(ex);
        }
    }

    /* -----------------------------------------------------------
     *  Private helper methods
     * -----------------------------------------------------------
     */

    private void validateConvertInput(ConvertFileFormatInputDTO input) {
        if (StringUtils.equalsIgnoreCase(input.getSourceFormat(), input.getTargetFormat())) {
            throw new GatewayException("Source and target formats must differ");
        }
    }

    private void meter(String name, Tag... tags) {
        metricsPublisher.count(METRIC_PREFIX + "." + name, List.of(tags));
    }

    private void recordLatency(String timerName, Timer.Sample sample, Tag... tags) {
        Timer timer = SimpleTimer.builder(METRIC_PREFIX + "." + timerName)
                                 .tags(tags)
                                 .register(metricsPublisher.getRegistry());
        sample.stop(timer);
    }

    /* -----------------------------------------------------------
     *  Local exception type
     * -----------------------------------------------------------
     */

    /**
     * GatewayException is a light wrapper that converts internal {@link DomainException}s
     * to resolver-friendly runtime errors, while preserving rich error metadata.
     * <p>
     * The exception is ultimately translated by the global {@code GraphqlErrorHandler}
     * into a RFC-7807 Problem+JSON structure that is compliant with both REST and
     * GraphQL error specifications.
     */
    public static final class GatewayException extends RuntimeException {

        private static final long serialVersionUID = 4120445362938467096L;

        private GatewayException(String message, Throwable cause) {
            super(message, cause);
        }

        private GatewayException(String message) {
            super(message);
        }

        public static GatewayException wrap(DomainException ex) {
            return new GatewayException(ex.getMessage(), ex);
        }
    }
}