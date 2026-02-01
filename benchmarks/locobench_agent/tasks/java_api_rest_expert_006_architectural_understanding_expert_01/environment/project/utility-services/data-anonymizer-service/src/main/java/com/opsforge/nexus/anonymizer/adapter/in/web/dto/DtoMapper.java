package com.opsforge.nexus.anonymizer.adapter.in.web.dto;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.opsforge.nexus.anonymizer.domain.command.AnonymizationJobCommand;
import com.opsforge.nexus.anonymizer.domain.model.AnonymizationResult;
import com.opsforge.nexus.shared.web.exception.BadRequestException;
import com.opsforge.nexus.shared.web.pagination.PageResponse;
import com.opsforge.nexus.shared.web.pagination.PaginationMetadata;

import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * Maps Web‐layer DTOs to domain commands and vice-versa.
 *
 * <p>
 * Although in most modules we leverage MapStruct for these kinds of conversions,
 * the anonymizer needs deep, JSON-aware mapping in order to support arbitrary
 * payload structures; therefore an imperative mapper is used here.
 * </p>
 *
 * <p>
 * This class is stateless and fully thread-safe.
 * </p>
 */
public final class DtoMapper {

    private static final ObjectMapper JSON = JsonMapper.builder()
            .addModule(new JavaTimeModule())
            .findAndAddModules()
            .build();

    private DtoMapper() {
        /* static util – instantiation not allowed */
    }

    /* ------------------------------------------------------------------
     * Request mapping
     * ------------------------------------------------------------------ */

    /**
     * Converts an {@link AnonymizationRequestDto} coming from the wire into a domain-level
     * {@link AnonymizationJobCommand}.
     *
     * @param dto validated incoming DTO
     * @return domain command
     */
    public static AnonymizationJobCommand toCommand(final AnonymizationRequestDto dto) {

        Objects.requireNonNull(dto, "AnonymizationRequestDto must not be null");

        return AnonymizationJobCommand.builder()
                .correlationId(
                        dto.correlationId() != null
                                ? dto.correlationId()
                                : UUID.randomUUID().toString()
                )
                .payload(dto.payload())
                .strategy(dto.strategy())
                .requestedAt(Instant.now())
                .build();
    }

    /* ------------------------------------------------------------------
     * Response mapping
     * ------------------------------------------------------------------ */

    /**
     * Converts a domain {@link AnonymizationResult} to an externally visible
     * {@link AnonymizationResponseDto}.
     *
     * @param result domain result (never {@code null})
     * @return response DTO
     */
    public static AnonymizationResponseDto toDto(final AnonymizationResult result) {

        Objects.requireNonNull(result, "AnonymizationResult must not be null");

        return AnonymizationResponseDto.builder()
                .correlationId(result.getCorrelationId())
                .processedAt(result.getProcessedAt())
                .durationMs(result.getDuration().toMillis())
                .payload(result.getAnonymizedPayload())
                .build();
    }

    /**
     * Converts a list of {@link AnonymizationResult} plus pagination metadata into
     * a {@link PageResponse} suitable for REST responses.
     *
     * @param items     the source domain objects
     * @param pageMeta  pagination metadata
     * @return paged response
     */
    public static PageResponse<AnonymizationResponseDto> toPageDto(final List<AnonymizationResult> items,
                                                                   final PaginationMetadata pageMeta) {

        final List<AnonymizationResponseDto> content = items == null
                ? Collections.emptyList()
                : items.stream()
                       .map(DtoMapper::toDto)
                       .collect(Collectors.toUnmodifiableList());

        return new PageResponse<>(content, pageMeta);
    }

    /* ------------------------------------------------------------------
     * Utility helpers
     * ------------------------------------------------------------------ */

    /**
     * Serializes an arbitrary object to JSON for logging/tracing purposes.
     *
     * @param object arbitrary object
     * @return JSON string or {@code "<unserializable>"} when conversion fails
     */
    public static String asJsonSilently(final Object object) {
        if (object == null) {
            return "null";
        }

        try {
            return JSON.writeValueAsString(object);
        } catch (JsonProcessingException e) {
            return "<unserializable>";
        }
    }

    /**
     * Deserializes a JSON string that is wrapped within a DTO field. The method will throw
     * a {@link BadRequestException} when the payload cannot be parsed.
     *
     * @param jsonPayload JSON‐encoded payload
     * @param targetClass target class
     * @param <T>         target type
     * @return deserialized object
     */
    public static <T> T parseJsonOrBadRequest(final String jsonPayload, final Class<T> targetClass) {
        try {
            return JSON.readValue(jsonPayload, targetClass);
        } catch (Exception e) {
            throw new BadRequestException("Unable to deserialize JSON payload: " + e.getMessage(), e);
        }
    }
}