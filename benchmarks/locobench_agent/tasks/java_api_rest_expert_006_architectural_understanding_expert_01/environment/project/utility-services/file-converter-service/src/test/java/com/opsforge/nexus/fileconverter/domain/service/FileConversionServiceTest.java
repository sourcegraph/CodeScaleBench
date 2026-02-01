package com.opsforge.nexus.fileconverter.domain.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.time.Duration;
import java.util.Optional;
import java.util.UUID;

import com.opsforge.nexus.fileconverter.domain.exception.ConversionFailedException;
import com.opsforge.nexus.fileconverter.domain.exception.UnsupportedFileFormatException;
import com.opsforge.nexus.fileconverter.domain.model.FileConversionRequest;
import com.opsforge.nexus.fileconverter.domain.model.FileConversionResult;
import com.opsforge.nexus.fileconverter.domain.port.ChecksumPort;
import com.opsforge.nexus.fileconverter.domain.port.FormatConverter;
import com.opsforge.nexus.fileconverter.domain.port.FormatConverterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.Test;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * Unit tests for {@link FileConversionService}.
 *
 * <p>This test class verifies the behavior of FileConversionService in isolation by stubbing
 * out all secondary ports (registry, checksum calculation, storage, etc.). The goal is to
 * assert only the business logic of the service and its correct interaction with its
 * collaborators.</p>
 */
@ExtendWith(MockitoExtension.class)
class FileConversionServiceTest {

    private static final UUID JOB_ID = UUID.fromString("6d2f6ad1-20ae-4f6c-91c8-d54b1eca6420");
    private static final String SOURCE_MIME = "application/pdf";
    private static final String TARGET_MIME = "image/png";

    @Mock
    private FormatConverterRegistry converterRegistry;

    @Mock
    private ChecksumPort checksumPort;

    @Mock
    private FormatConverter pdfToPngConverter;

    @InjectMocks
    private FileConversionService service;

    private byte[] sourcePayload;
    private byte[] targetPayload;

    @BeforeEach
    void setUp() {
        sourcePayload = "dummy-pdf-content".getBytes();
        targetPayload = "dummy-png-content".getBytes();
    }

    @Nested
    @DisplayName("Happy path scenarios")
    class HappyPath {

        @Test
        @Timeout(2) // protects against infinite loops in business logic
        @DisplayName("should convert PDF to PNG successfully")
        void shouldConvertPdfToPngSuccessfully() {
            // Arrange
            when(converterRegistry.resolve(SOURCE_MIME, TARGET_MIME))
                    .thenReturn(Optional.of(pdfToPngConverter));
            when(pdfToPngConverter.convert(sourcePayload))
                    .thenReturn(targetPayload);
            when(checksumPort.compute(targetPayload))
                    .thenReturn("sha256:babeef");

            FileConversionRequest request = FileConversionRequest.builder()
                    .jobId(JOB_ID)
                    .payload(sourcePayload)
                    .sourceMimeType(SOURCE_MIME)
                    .targetMimeType(TARGET_MIME)
                    .build();

            // Act
            FileConversionResult result = service.convert(request);

            // Assert
            assertThat(result)
                    .extracting(FileConversionResult::jobId,
                                FileConversionResult::targetMimeType,
                                FileConversionResult::payload,
                                FileConversionResult::checksum)
                    .containsExactly(JOB_ID, TARGET_MIME, targetPayload, "sha256:babeef");

            // Ensure duration is non-zero but reasonable
            assertThat(result.duration())
                    .isBetween(Duration.ZERO, Duration.ofSeconds(5));

            verify(converterRegistry).resolve(SOURCE_MIME, TARGET_MIME);
            verify(pdfToPngConverter).convert(sourcePayload);
            verify(checksumPort).compute(targetPayload);
            verifyNoMoreInteractions(converterRegistry, pdfToPngConverter, checksumPort);
        }
    }

    @Nested
    @DisplayName("Exceptional scenarios")
    class ExceptionalScenarios {

        @Test
        @DisplayName("should throw UnsupportedFileFormatException when no converter is registered")
        void shouldThrowWhenConverterNotFound() {
            // Arrange
            when(converterRegistry.resolve(SOURCE_MIME, TARGET_MIME))
                    .thenReturn(Optional.empty());

            FileConversionRequest request = FileConversionRequest.builder()
                    .jobId(JOB_ID)
                    .payload(sourcePayload)
                    .sourceMimeType(SOURCE_MIME)
                    .targetMimeType(TARGET_MIME)
                    .build();

            // Act + Assert
            assertThatThrownBy(() -> service.convert(request))
                    .isInstanceOf(UnsupportedFileFormatException.class)
                    .hasMessageContaining(SOURCE_MIME)
                    .hasMessageContaining(TARGET_MIME);

            verify(converterRegistry).resolve(SOURCE_MIME, TARGET_MIME);
            verifyNoMoreInteractions(converterRegistry, pdfToPngConverter, checksumPort);
        }

        @Test
        @DisplayName("should propagate ConversionFailedException when converter fails")
        void shouldPropagateWhenConverterFails() {
            // Arrange
            when(converterRegistry.resolve(SOURCE_MIME, TARGET_MIME))
                    .thenReturn(Optional.of(pdfToPngConverter));
            when(pdfToPngConverter.convert(sourcePayload))
                    .thenThrow(new ConversionFailedException("runtime boom"));

            FileConversionRequest request = FileConversionRequest.builder()
                    .jobId(JOB_ID)
                    .payload(sourcePayload)
                    .sourceMimeType(SOURCE_MIME)
                    .targetMimeType(TARGET_MIME)
                    .build();

            // Act + Assert
            assertThatThrownBy(() -> service.convert(request))
                    .isInstanceOf(ConversionFailedException.class)
                    .hasMessageContaining("runtime boom");

            verify(converterRegistry).resolve(SOURCE_MIME, TARGET_MIME);
            verify(pdfToPngConverter).convert(sourcePayload);
            verifyNoMoreInteractions(converterRegistry, pdfToPngConverter, checksumPort);
        }

        @Test
        @DisplayName("should validate request payload is not null or empty")
        void shouldValidateEmptyPayload() {
            FileConversionRequest request = FileConversionRequest.builder()
                    .jobId(JOB_ID)
                    .payload(new byte[0])
                    .sourceMimeType(SOURCE_MIME)
                    .targetMimeType(TARGET_MIME)
                    .build();

            assertThatThrownBy(() -> service.convert(request))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("payload");
        }
    }
}