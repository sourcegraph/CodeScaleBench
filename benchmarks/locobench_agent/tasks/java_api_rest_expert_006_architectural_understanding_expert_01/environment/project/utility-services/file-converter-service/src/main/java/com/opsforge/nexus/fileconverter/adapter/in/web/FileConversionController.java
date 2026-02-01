package com.opsforge.nexus.fileconverter.adapter.in.web;

import com.opsforge.nexus.fileconverter.application.port.in.FileConversionUseCase;
import com.opsforge.nexus.fileconverter.application.port.in.FileConversionUseCase.ConvertCommand;
import com.opsforge.nexus.fileconverter.domain.model.ConvertedFile;
import com.opsforge.nexus.fileconverter.domain.model.FileFormat;
import com.opsforge.nexus.sharedkernel.exceptions.UnsupportedFileFormatException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import javax.servlet.http.HttpServletRequest;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;
import java.time.Duration;
import java.time.Instant;
import java.util.Set;

/**
 * REST adapter that exposes file–conversion capabilities via HTTP.
 * <p>
 * Controller follows hexagonal (ports & adapters) architecture:
 * it merely translates the inbound HTTP request into a {@link FileConversionUseCase}
 * command and maps the response back into HTTP semantics,
 * leaving business rules entirely inside the application layer.
 * </p>
 *
 * <p>Versioning strategy: URI versioning (e.g. /api/v1/...)</p>
 *
 * <p>Cross-cutting concerns such as rate-limiting,
 * authentication/authorization and tracing are handled by filters
 * configured at gateway level and are therefore not repeated here.</p>
 */
@Slf4j
@Validated
@RestController
@RequestMapping(path = "/api/{version:v\\d+}/files", produces = MediaType.APPLICATION_JSON_VALUE)
@RequiredArgsConstructor
public class FileConversionController {

    private static final String DEFAULT_CHARSET = "utf-8";

    private final FileConversionUseCase fileConversionUseCase;

    /**
     * Synchronously converts the supplied file into the requested target format and
     * streams the converted content back to the client.
     *
     * <p>For large files or conversions that require heavyweight processing,
     * consider using the asynchronous variant exposed by the same service.</p>
     *
     * @param apiVersion   path variable for URI versioning (validated by regex)
     * @param file         multipart file to convert
     * @param targetFormat target format (e.g. PDF, DOCX, PNG)
     * @return HTTP 200 with the converted file content;
     *         HTTP 400 on validation errors; HTTP 415 on unsupported formats
     */
    @PostMapping(
            path = "/convert",
            consumes = MediaType.MULTIPART_FORM_DATA_VALUE,
            produces = MediaType.ALL_VALUE /* we stream binary, not JSON */
    )
    public ResponseEntity<ByteArrayResource> convertFile(
            @PathVariable("version") String apiVersion,
            @RequestPart("file") @NotNull MultipartFile file,
            @RequestParam("targetFormat") @NotBlank String targetFormat) {

        log.info("v{} - Received convert request for '{}' -> '{}'",
                apiVersion, file.getOriginalFilename(), targetFormat);

        if (file.isEmpty()) {
            throw new IllegalArgumentException("Uploaded file is empty");
        }

        FileFormat toFormat = FileFormat.from(targetFormat);

        ConvertCommand command = ConvertCommand.builder()
                .originalFilename(file.getOriginalFilename())
                .sourceContentType(file.getContentType())
                .targetFormat(toFormat)
                .content(readBytes(file))
                .build();

        ConvertedFile converted = fileConversionUseCase.convert(command);

        ByteArrayResource resource = new ByteArrayResource(converted.getContent()) {
            @Override
            public String getFilename() {
                return converted.getFilename();
            }
        };

        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(converted.getMimeType() + ";charset=" + DEFAULT_CHARSET))
                .contentLength(converted.getContent().length)
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"" + converted.getFilename() + "\"")
                .cacheControl(CacheControl.maxAge(Duration.ofHours(24)).cachePublic())
                .body(resource);
    }

    /**
     * Lists the set of supported target formats.
     * Useful for UI-builders and API-clients to discover capabilities dynamically.
     */
    @GetMapping("/formats")
    public ResponseEntity<Set<FileFormat>> getSupportedFormats() {
        return ResponseEntity.ok(fileConversionUseCase.getSupportedFormats());
    }

    /* ----------------------------------------------------------
     * Exception handling
     * ---------------------------------------------------------- */

    @ExceptionHandler(UnsupportedFileFormatException.class)
    public ResponseEntity<ErrorResponse> handleUnsupportedFormat(
            UnsupportedFileFormatException ex, HttpServletRequest request) {
        return buildErrorResponse(ex, request, 415 /* UNSUPPORTED_MEDIA_TYPE */);
    }

    @ExceptionHandler({IllegalArgumentException.class, org.springframework.web.bind.MethodArgumentNotValidException.class})
    public ResponseEntity<ErrorResponse> handleBadRequest(
            Exception ex, HttpServletRequest request) {
        return buildErrorResponse(ex, request, 400);
    }

    private ResponseEntity<ErrorResponse> buildErrorResponse(
            Exception ex, HttpServletRequest request, int status) {
        log.warn("Request failed: {}", ex.getMessage());
        ErrorResponse error = new ErrorResponse(
                Instant.now().toString(),
                status,
                ex.getClass().getSimpleName(),
                ex.getMessage(),
                request.getRequestURI());
        return ResponseEntity.status(status).body(error);
    }

    /* ----------------------------------------------------------
     * Helpers
     * ---------------------------------------------------------- */

    private byte[] readBytes(MultipartFile file) {
        try {
            return file.getBytes();
        } catch (Exception e) {
            throw new IllegalStateException("Unable to read uploaded file", e);
        }
    }

    /* ----------------------------------------------------------
     * Internal DTOs (not exposed outside the controller layer)
     * ---------------------------------------------------------- */

    /**
     * Minimal JSON error envelope following <a href="https://datatracker.ietf.org/doc/html/rfc7807">RFC-7807</a>
     * conventions (problem-details).  Shared error model is defined in shared-kernel,
     * yet we keep a lightweight fallback here to avoid tight coupling.
     */
    public record ErrorResponse(
            String timestamp,
            int status,
            String error,
            String message,
            String path) {
    }
}