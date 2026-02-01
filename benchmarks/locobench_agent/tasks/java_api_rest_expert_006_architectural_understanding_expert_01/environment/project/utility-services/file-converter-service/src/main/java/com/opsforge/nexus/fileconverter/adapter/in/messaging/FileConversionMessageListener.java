package com.opsforge.nexus.fileconverter.adapter.in.messaging;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.exc.InvalidFormatException;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.opsforge.nexus.fileconverter.application.port.in.FileConversionUseCase;
import com.opsforge.nexus.fileconverter.application.port.in.command.ConversionJobCommand;
import com.opsforge.nexus.fileconverter.application.port.in.result.ConversionJobResult;
import lombok.Builder;
import lombok.Value;
import org.apache.kafka.clients.consumer.Consumer;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.Acknowledgment;
import org.springframework.stereotype.Component;

import javax.validation.ConstraintViolation;
import javax.validation.Validator;
import javax.validation.constraints.NotBlank;
import java.time.Duration;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * Inbound Kafka listener that receives asynchronous file-conversion requests and
 * delegates them to the application layer.  Results (both success and failure)
 * are pushed to a dedicated reply topic so that the caller can react without
 * coupling to implementation details.
 *
 * <p>
 *     Responsibilities:
 *     <ul>
 *         <li>Validate and deserialize inbound JSON messages.</li>
 *         <li>Enforce idempotency to protect against at-least-once delivery semantics.</li>
 *         <li>Translate DTOs to domain commands and invoke the {@link FileConversionUseCase}.</li>
 *         <li>Publish a result message to the <i>results</i> topic.</li>
 *         <li>Implement robust error handling and basic circuit-breaking behaviour.</li>
 *     </ul>
 * </p>
 *
 * <p>The class is intentionally stateless, all mutable concerns are hidden behind
 * thread-safe collaborators supplied through constructor injection.</p>
 */
@Component
public class FileConversionMessageListener {

    private static final Logger log = LoggerFactory.getLogger(FileConversionMessageListener.class);

    private static final String ERROR_CODE_DESERIALIZATION = "DESERIALIZATION_ERROR";
    private static final String ERROR_CODE_VALIDATION      = "VALIDATION_ERROR";
    private static final String ERROR_CODE_PROCESSING      = "PROCESSING_ERROR";

    private final FileConversionUseCase fileConversionUseCase;
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final Validator validator;
    private final ObjectMapper objectMapper;
    private final Cache<String, Boolean> processedMessageCache;
    private final String resultsTopic;

    public FileConversionMessageListener(final FileConversionUseCase fileConversionUseCase,
                                         final KafkaTemplate<String, String> kafkaTemplate,
                                         final Validator validator,
                                         final ObjectMapper objectMapper,
                                         @Value("${nexus.messaging.topics.file-conversion-results}") final String resultsTopic,
                                         @Value("${nexus.messaging.deduplication.ttl-minutes:360}") final long deduplicationTtlMinutes) {

        this.fileConversionUseCase = fileConversionUseCase;
        this.kafkaTemplate         = kafkaTemplate;
        this.validator             = validator;
        this.objectMapper          = objectMapper;
        this.resultsTopic          = resultsTopic;

        /*  Idempotency cache: protects against redeliveries within a time window.
            Caffeine is light-weight and performs very well under high concurrency. */
        this.processedMessageCache = Caffeine.newBuilder()
                                             .expireAfterWrite(Duration.ofMinutes(deduplicationTtlMinutes))
                                             .maximumSize(20_000)
                                             .build();
    }

    /**
     * Main Kafka entry point.  The {@code kafkaListenerContainerFactory} referenced in the
     * annotation enables manual acknowledgments (AckMode.MANUAL) so that a message is only
     * committed once processing is complete.
     */
    @KafkaListener(
            topics = "${nexus.messaging.topics.file-conversion-requests}",
            groupId = "${spring.kafka.consumer.group-id}",
            containerFactory = "kafkaListenerContainerFactory"
    )
    public void onMessage(final ConsumerRecord<String, String> record,
                          final Acknowledgment ack,
                          final Consumer<?, ?> consumer) {

        final String jobId  = record.key();   // jobId is used as Kafka key for natural ordering
        final String payload = record.value();

        /* ===== De-duplication ============================================================ */
        if (processedMessageCache.getIfPresent(jobId) != null) {
            log.info("Duplicate message with key={} skipped (already processed)", jobId);
            ack.acknowledge();
            return;
        }

        log.debug("Received file-conversion request message with key={}", jobId);

        try {
            /* ===== Deserialization ======================================================= */
            FileConversionRequestMessage requestDto =
                    objectMapper.readValue(payload, FileConversionRequestMessage.class);

            /* ===== Validation ============================================================ */
            Set<ConstraintViolation<FileConversionRequestMessage>> violations =
                    validator.validate(requestDto);

            if (!violations.isEmpty()) {
                log.warn("Validation failed for jobId {}: {}", jobId, violations);
                publishFailure(jobId, ERROR_CODE_VALIDATION, violations.toString());
                ack.acknowledge();
                return;
            }

            /* ===== Mapping DTO -> Domain Command ======================================== */
            ConversionJobCommand command = ConversionJobCommand.builder()
                                                               .jobId(requestDto.getJobId())
                                                               .sourceFormat(requestDto.getSourceFormat())
                                                               .targetFormat(requestDto.getTargetFormat())
                                                               .originalFilename(requestDto.getOriginalFilename())
                                                               .base64EncodedFile(requestDto.getBase64EncodedFile())
                                                               .useLosslessCompression(requestDto.isUseLosslessCompression())
                                                               .build();

            /* ===== Invoke Use-Case ======================================================= */
            ConversionJobResult conversionResult = fileConversionUseCase.convertFile(command);

            /* ===== Publish Success Result =============================================== */
            publishSuccess(conversionResult);

            /* ===== Record processed message & commit offset ============================= */
            processedMessageCache.put(jobId, Boolean.TRUE);
            ack.acknowledge();

            log.info("File-conversion job {} processed successfully", jobId);

        } catch (InvalidFormatException | JsonProcessingException e) {
            log.error("Unable to deserialize message with key={}", jobId, e);
            publishFailure(jobId, ERROR_CODE_DESERIALIZATION, e.getOriginalMessage());
            ack.acknowledge(); // Commit so we don't get stuck on poison pill
        } catch (Exception e) {
            log.error("Unexpected error during processing of jobId {}", jobId, e);
            publishFailure(jobId, ERROR_CODE_PROCESSING, e.getMessage());
            ack.acknowledge(); // Depending on retry policy we might nack instead
        }
    }

    /* =====================================================================================
       Private helper methods
       ===================================================================================== */

    private void publishSuccess(final ConversionJobResult result) {
        try {
            FileConversionResultMessage resultDto = FileConversionResultMessage.success(result);
            kafkaTemplate.send(resultsTopic, result.jobId(),
                               objectMapper.writeValueAsString(resultDto));
        } catch (JsonProcessingException e) {
            /* This should never happen; if it does we log and swallow to avoid reprocessing */
            log.error("Failed to serialize success result for jobId {}", result.jobId(), e);
        }
    }

    private void publishFailure(final String jobId,
                                final String errorCode,
                                final String detail) {
        try {
            FileConversionResultMessage resultDto = FileConversionResultMessage.failure(jobId, errorCode, detail);
            kafkaTemplate.send(resultsTopic, jobId, objectMapper.writeValueAsString(resultDto));
        } catch (JsonProcessingException e) {
            log.error("Failed to serialize failure result for jobId {}", jobId, e);
        }
    }

    /* =====================================================================================
       DTOs – These classes live in the adapter layer and are therefore transport-specific.
       Domain models never leak into, nor depend on, these structures.
       ===================================================================================== */

    @Value
    @Builder
    @SuppressWarnings("unused")
    private static class FileConversionRequestMessage {

        @NotBlank
        String jobId;

        @NotBlank
        String sourceFormat;

        @NotBlank
        String targetFormat;

        @NotBlank
        String originalFilename;

        /** Base-64 representation of the file to be converted */
        @NotBlank
        String base64EncodedFile;

        /** Whether to apply lossless compression when available */
        boolean useLosslessCompression;
    }

    @Value
    @Builder
    @SuppressWarnings("unused")
    private static class FileConversionResultMessage {

        String  jobId;
        boolean success;
        String  errorCode; // Null on success
        String  detail;    // Converted file location or error details

        /** Factory for successful result messages */
        static FileConversionResultMessage success(final ConversionJobResult result) {
            return FileConversionResultMessage.builder()
                                              .jobId(result.jobId())
                                              .success(true)
                                              .detail(result.convertedFileLocation())
                                              .build();
        }

        /** Factory for failure result messages */
        static FileConversionResultMessage failure(final String jobId,
                                                   final String errorCode,
                                                   final String detail) {
            return FileConversionResultMessage.builder()
                                              .jobId(jobId)
                                              .success(false)
                                              .errorCode(errorCode)
                                              .detail(detail)
                                              .build();
        }
    }
}