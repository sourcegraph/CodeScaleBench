package com.opsforge.nexus.fileconverter.adapter.in.web.dto;

import com.opsforge.nexus.fileconverter.domain.model.Checksum;
import com.opsforge.nexus.fileconverter.domain.model.ChecksumAlgorithm;
import com.opsforge.nexus.fileconverter.domain.model.FileConversionJob;
import com.opsforge.nexus.fileconverter.domain.model.FileConversionRequest;
import com.opsforge.nexus.fileconverter.domain.model.FileConversionResult;
import com.opsforge.nexus.fileconverter.domain.model.JobStatus;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * DtoMapper is responsible for translating pure domain models to their
 * web-facing DTO counterparts and vice-versa. Centralising this logic prevents
 * leaky abstractions from contaminating controller code while still allowing
 * the rest of the adapter layer to evolve independently.
 *
 * Thread-safety & statelessness:  the mapper holds no mutable state and can
 * therefore be shared freely between threads (Spring will create a singleton).
 */
@Component
public final class DtoMapper {

    /**
     * ISO-8601 formatter with offset (e.g. 2023-05-01T12:00:00+02:00).  Chosen
     * over local date-time because API consumers are expected to be timezone
     * aware.
     */
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ISO_OFFSET_DATE_TIME;

    // --------------------------------------------------------------------- //
    // Public API –––––––––––––––––––––––––––––––––––––––––––––––––––––––––– //
    // --------------------------------------------------------------------- //

    /**
     * Converts an inbound HTTP request DTO into the corresponding domain
     * request object.  Performs basic syntactic validation and throws a
     * {@link MappingException} when mandatory fields are missing or malformed.
     */
    public FileConversionRequest toDomain(FileConversionRequestDto dto) {
        Objects.requireNonNull(dto, "FileConversionRequestDto must not be null");

        if (!StringUtils.hasText(dto.getSourceFormat())) {
            throw new MappingException("sourceFormat must be provided");
        }
        if (!StringUtils.hasText(dto.getTargetFormat())) {
            throw new MappingException("targetFormat must be provided");
        }
        if (!StringUtils.hasText(dto.getSourceUri())) {
            throw new MappingException("sourceUri must be provided");
        }

        URI sourceUri;
        try {
            sourceUri = new URI(dto.getSourceUri());
        } catch (URISyntaxException e) {
            throw new MappingException("sourceUri is not a valid URI: " + dto.getSourceUri(), e);
        }

        Map<String, String> metadata =
                Optional.ofNullable(dto.getMetadata()).orElse(Collections.emptyMap());

        return new FileConversionRequest(
                dto.getSourceFormat().trim(),
                dto.getTargetFormat().trim(),
                sourceUri,
                metadata.isEmpty() ? Optional.empty() : Optional.of(metadata)
        );
    }

    /**
     * Converts a {@link FileConversionJob} domain object into a DTO that will
     * be rendered in the HTTP response.
     */
    public FileConversionResponseDto toDto(FileConversionJob job) {
        Objects.requireNonNull(job, "FileConversionJob must not be null");

        FileConversionResponseDto response = new FileConversionResponseDto();
        response.setJobId(job.getId().toString());
        response.setStatus(mapStatus(job.getStatus()));
        response.setCreatedAt(formatZonedDateTime(job.getCreatedAt()));
        response.setLastUpdatedAt(formatZonedDateTime(job.getLastUpdatedAt()));

        job.getResult()
           .map(this::mapResult)
           .ifPresent(response::setResult);

        return response;
    }

    // --------------------------------------------------------------------- //
    // Internal helpers ––––––––––––––––––––––––––––––––––––––––––––––––––––– //
    // --------------------------------------------------------------------- //

    private FileConversionResultDto mapResult(FileConversionResult result) {
        FileConversionResultDto dto = new FileConversionResultDto();
        dto.setOutputUri(result.getOutputUri().toString());
        dto.setOutputSize(result.getOutputSizeInBytes());
        dto.setChecksum(mapChecksum(result.getChecksum()));
        return dto;
    }

    private ChecksumDto mapChecksum(Checksum checksum) {
        ChecksumDto dto = new ChecksumDto();
        dto.setAlgorithm(checksum.getAlgorithm().name());
        dto.setValue(checksum.getValue());
        return dto;
    }

    private String mapStatus(JobStatus status) {
        return status.name();
    }

    private String formatZonedDateTime(ZonedDateTime dateTime) {
        return dateTime != null ? DATE_TIME_FORMATTER.format(dateTime) : null;
    }

    // --------------------------------------------------------------------- //
    // Custom Exception –––––––––––––––––––––––––––––––––––––––––––––––––––– //
    // --------------------------------------------------------------------- //

    /**
     * Dedicated exception type for mapping failures.  By using a specific
     * runtime exception we allow the global error handler to translate mapping
     * issues into 4xx responses without conflating them with internal server
     * errors (5xx).
     */
    public static class MappingException extends RuntimeException {
        public MappingException(String message) {
            super(message);
        }

        public MappingException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}