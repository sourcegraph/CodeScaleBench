package com.opsforge.nexus.fileconverter.domain.service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.TimeoutException;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.opsforge.nexus.fileconverter.domain.exception.ConversionFailedException;
import com.opsforge.nexus.fileconverter.domain.exception.InvalidConversionRequestException;
import com.opsforge.nexus.fileconverter.domain.exception.UnsupportedConversionException;
import com.opsforge.nexus.fileconverter.domain.model.ConversionRequest;
import com.opsforge.nexus.fileconverter.domain.model.ConversionResult;
import com.opsforge.nexus.fileconverter.domain.model.FileFormat;
import com.opsforge.nexus.fileconverter.domain.port.in.FileConversionUseCase;
import com.opsforge.nexus.fileconverter.domain.port.out.AuditTrailPort;
import com.opsforge.nexus.fileconverter.domain.port.out.ChecksumPort;
import com.opsforge.nexus.fileconverter.domain.port.out.ConversionEnginePort;

/**
 * Domain service that orchestrates file-format conversions.
 * <p>
 * This class sits in the core domain layer and therefore depends only on
 * <i>ports</i>, never on specific frameworks or technologies. The concrete
 * implementations of those ports are supplied by the application layer.
 * </p>
 */
@SuppressWarnings("java:S3740") // We purposefully keep generics loose for adapter flexibility
public class FileConversionService implements FileConversionUseCase {

    private static final Logger LOGGER = LoggerFactory.getLogger(FileConversionService.class);

    /**
     * Hard upper limit for a single conversion request, after which we abort the ongoing task.
     */
    private static final Duration CONVERSION_TIMEOUT = Duration.ofMinutes(2);

    private final ConversionEnginePort conversionEngine;
    private final ChecksumPort checksumPort;
    private final AuditTrailPort auditTrailPort;
    private final Clock clock;

    /**
     * Creates a new {@link FileConversionService}.
     *
     * @param conversionEngine concrete engine able to perform binary transformation
     * @param checksumPort     port that can produce checksums for binary payloads
     * @param auditTrailPort   port that records an audit trail for compliance
     * @param clock            injected clock to ensure deterministic tests
     */
    public FileConversionService(
            final ConversionEnginePort conversionEngine,
            final ChecksumPort checksumPort,
            final AuditTrailPort auditTrailPort,
            final Clock clock
    ) {
        this.conversionEngine = Objects.requireNonNull(conversionEngine, "conversionEngine must not be null");
        this.checksumPort = Objects.requireNonNull(checksumPort, "checksumPort must not be null");
        this.auditTrailPort = Objects.requireNonNull(auditTrailPort, "auditTrailPort must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    /* =========================================================================
       Public API (In-Port implementation)
       ========================================================================= */

    @Override
    public ConversionResult convert(final ConversionRequest request) {
        validate(request);

        final Instant startedAt = clock.instant();
        final CompletableFuture<ConversionResult> future =
                CompletableFuture.supplyAsync(() -> doConvert(request, startedAt));

        try {
            return future.get(CONVERSION_TIMEOUT.toMillis(), java.util.concurrent.TimeUnit.MILLISECONDS);
        } catch (TimeoutException timeout) {
            final String message = "Conversion timed out after " + CONVERSION_TIMEOUT;
            future.cancel(true); // best-effort cancellation
            LOGGER.warn(message);
            auditTrailPort.recordFailure(request, message, startedAt, clock.instant());
            throw new ConversionFailedException(message, timeout);
        } catch (CompletionException completionException) {
            // Unwrap wrapped exceptions to keep the stacktrace meaningful
            final Throwable rootCause = completionException.getCause() != null
                                        ? completionException.getCause()
                                        : completionException;
            if (rootCause instanceof RuntimeException runtime) {
                throw runtime; // rethrow domain or unchecked exceptions
            }
            throw new ConversionFailedException("Unexpected failure during conversion", rootCause);
        } catch (Exception e) {
            throw new ConversionFailedException("Unexpected interruption while waiting for conversion result", e);
        }
    }

    @Override
    public Map<FileFormat, Set<FileFormat>> listSupportedConversions() {
        return Collections.unmodifiableMap(conversionEngine.getSupportedConversions());
    }

    /* =========================================================================
       Private helpers
       ========================================================================= */

    private ConversionResult doConvert(final ConversionRequest request, final Instant startedAt) {
        LOGGER.debug("Starting conversion: {}", request);

        if (!conversionEngine.canConvert(request.getSourceFormat(), request.getTargetFormat())) {
            final String message = String.format("Unsupported conversion: %s -> %s",
                                                 request.getSourceFormat(),
                                                 request.getTargetFormat());
            auditTrailPort.recordFailure(request, message, startedAt, clock.instant());
            throw new UnsupportedConversionException(message);
        }

        try {
            final byte[] converted = conversionEngine.convert(request);

            // Compute checksum after conversion to guarantee end-to-end integrity
            final String checksum = checksumPort.calculate(converted);

            final Instant finishedAt = clock.instant();
            final Duration duration = Duration.between(startedAt, finishedAt);

            final ConversionResult result = ConversionResult.builder()
                                                            .requestId(request.getRequestId())
                                                            .checksum(checksum)
                                                            .duration(duration)
                                                            .payload(converted)
                                                            .sourceFormat(request.getSourceFormat())
                                                            .targetFormat(request.getTargetFormat())
                                                            .completedAt(finishedAt)
                                                            .build();

            auditTrailPort.recordSuccess(request, result, startedAt, finishedAt);
            LOGGER.info("Conversion succeeded in {} ms (requestId={})", duration.toMillis(), request.getRequestId());

            return result;
        } catch (RuntimeException ex) {
            final String message = "Conversion engine failed";
            auditTrailPort.recordFailure(request, message, startedAt, clock.instant());
            throw new ConversionFailedException(message, ex);
        }
    }

    private void validate(final ConversionRequest request) {
        if (request == null) {
            throw new InvalidConversionRequestException("Request must not be null");
        }
        if (request.getPayload() == null || request.getPayload().length == 0) {
            throw new InvalidConversionRequestException("Payload must not be empty");
        }
        if (request.getSourceFormat() == null) {
            throw new InvalidConversionRequestException("Source format must be provided");
        }
        if (request.getTargetFormat() == null) {
            throw new InvalidConversionRequestException("Target format must be provided");
        }
    }
}