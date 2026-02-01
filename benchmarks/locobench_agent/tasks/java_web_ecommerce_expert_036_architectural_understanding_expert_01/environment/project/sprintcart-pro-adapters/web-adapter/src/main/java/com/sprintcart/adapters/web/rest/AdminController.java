package com.sprintcart.adapters.web.rest;

import com.sprintcart.application.port.in.admin.AdminBulkCatalogImportCommand;
import com.sprintcart.application.port.in.admin.AdminMetricsQuery;
import com.sprintcart.application.port.in.admin.AdminRefreshKpiCommand;
import com.sprintcart.application.port.in.admin.AdminUpdateUserRolesCommand;
import com.sprintcart.application.port.in.admin.AdminUseCase;
import com.sprintcart.domain.common.PageInfo;
import com.sprintcart.domain.exception.DomainException;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.io.FilenameUtils;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.MimeTypeUtils;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Administrative REST-endpoints.
 * <p>
 * All routes are prefixed with /api/v1/admin and protected by the {@code AdminRoleGuard}
 * (configured in the security adapter).  This controller only performs:
 * <ul>
 *     <li>Input validation</li>
 *     <li>Request ↔ Command/Query mapping</li>
 *     <li>HTTP-specific concerns (status codes, headers, file uploads, etc.)</li>
 * </ul>
 * Any business logic is delegated to the {@link AdminUseCase} port, which is implemented
 * inside the application/service layer.
 */
@Slf4j
@Validated
@RestController
@RequestMapping(path = "/api/v1/admin", produces = MediaType.APPLICATION_JSON_VALUE)
public class AdminController {

    private static final Set<String> ALLOWED_CATALOG_MIME_TYPES =
            Set.of(MimeTypeUtils.APPLICATION_OCTET_STREAM_VALUE,
                   "text/csv",
                   "application/vnd.ms-excel");

    private final AdminUseCase adminUseCase;

    public AdminController(AdminUseCase adminUseCase) {
        this.adminUseCase = adminUseCase;
    }

    // -------------------------------------------------------------------------
    //  KPI / Metrics
    // -------------------------------------------------------------------------

    /**
     * Returns a snapshot of productivity metrics that power the dashboard widgets
     * in the back-office SPA.
     */
    @GetMapping("/metrics/overview")
    public ResponseEntity<MetricsOverviewResponse> getMetricsOverview(
            @RequestParam(defaultValue = "UTC") String timezone) {

        var query = AdminMetricsQuery.builder()
                .requestedAt(Instant.now())
                .targetTimezone(timezone)
                .build();

        var overview = adminUseCase.fetchProductivityMetrics(query);

        var dto = MetricsOverviewResponse.fromDomain(overview);

        return ResponseEntity.ok(dto);
    }

    /**
     * Forces a synchronous re-computation of productivity KPIs.
     * In most environments this happens automatically via an async job,
     * but power-users might require an ad-hoc refresh (e.g. after a bulk import).
     */
    @PostMapping("/kpis/refresh")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public void refreshKpis() {
        adminUseCase.refreshKpis(new AdminRefreshKpiCommand(Instant.now()));
    }

    // -------------------------------------------------------------------------
    //  Bulk Catalog Import
    // -------------------------------------------------------------------------

    /**
     * Upload a CSV/Excel file for bulk product maintenance.  The file is first
     * stored in a temporary object store, then picked up by an async importer
     * that executes a {@code CatalogMaintenance} use case.
     *
     * @throws IllegalArgumentException when the file type is unsupported.
     */
    @PostMapping(path = "/catalog/bulk-upload",
                 consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<BulkImportAcceptedResponse> bulkUploadCatalog(
            @RequestPart("file") @NotNull MultipartFile file,
            @RequestParam(defaultValue = "false") boolean dryRun) throws IOException {

        validateFile(file);

        var importCommand = AdminBulkCatalogImportCommand.builder()
                .originalFilename(sanitizeFilename(file.getOriginalFilename()))
                .mimeType(file.getContentType())
                .bytes(file.getBytes())
                .dryRun(dryRun)
                .build();

        var jobId = adminUseCase.importCatalog(importCommand);

        var responseBody = BulkImportAcceptedResponse.builder()
                .importJobId(jobId)
                .receivedAt(Instant.now())
                .dryRun(dryRun)
                .build();

        return ResponseEntity
                .accepted()
                .header(HttpHeaders.LOCATION, "/api/v1/admin/imports/" + jobId)
                .body(responseBody);
    }

    // -------------------------------------------------------------------------
    //  User Management
    // -------------------------------------------------------------------------

    /**
     * Replace the role set of a user.  This endpoint is idempotent; sending the
     * same payload multiple times will always yield the same state.
     */
    @PostMapping("/users/{userId}/roles")
    public ResponseEntity<Void> updateUserRoles(
            @PathVariable @Positive long userId,
            @RequestBody @Valid RoleUpdateRequest request) {

        var command = AdminUpdateUserRolesCommand.builder()
                .userId(userId)
                .roles(request.getRoles())
                .updatedAt(Instant.now())
                .build();

        adminUseCase.updateUserRoles(command);

        return ResponseEntity.noContent().build();
    }

    // -------------------------------------------------------------------------
    //  Internal Validation Helpers
    // -------------------------------------------------------------------------

    private static void validateFile(MultipartFile file) {
        if (file.isEmpty()) {
            throw new IllegalArgumentException("Uploaded file is empty");
        }
        if (!ALLOWED_CATALOG_MIME_TYPES.contains(file.getContentType())) {
            throw new IllegalArgumentException(
                    "Unsupported file type: " + file.getContentType());
        }
    }

    private static String sanitizeFilename(String original) {
        return FilenameUtils.getName(original); // strips any path traversal
    }

    // -------------------------------------------------------------------------
    //  Exception Handling
    // -------------------------------------------------------------------------

    @ExceptionHandler({DomainException.class})
    public ResponseEntity<ErrorResponse> handleDomainException(DomainException ex) {
        log.warn("Domain exception: {}", ex.getMessage());
        return ResponseEntity.badRequest()
                .body(ErrorResponse.from(ex.getErrorCode(), ex.getMessage()));
    }

    @ExceptionHandler({IllegalArgumentException.class})
    public ResponseEntity<ErrorResponse> handleIllegalArgument(IllegalArgumentException ex) {
        log.debug("Illegal argument: {}", ex.getMessage());
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .body(ErrorResponse.from("VALIDATION_ERROR", ex.getMessage()));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class})
    public ResponseEntity<ErrorResponse> handleValidation(MethodArgumentNotValidException ex) {
        var errors = ex.getBindingResult()
                .getFieldErrors()
                .stream()
                .collect(Collectors.toMap(
                        err -> err.getField(),
                        err -> err.getDefaultMessage(),
                        (a, b) -> b));
        return ResponseEntity.badRequest()
                .body(ErrorResponse.from("VALIDATION_ERROR", "Payload validation failed", errors));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleGeneric(Exception ex) {
        log.error("Unexpected error", ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ErrorResponse.from("INTERNAL_SERVER_ERROR",
                        "An unexpected error occurred. Please contact support."));
    }

    // -------------------------------------------------------------------------
    //  DTOs
    // -------------------------------------------------------------------------

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    private static class MetricsOverviewResponse {
        private long activeOrders;
        private int avgSecondsToFulfillment;
        private double revenuePerMinute;
        private PageInfo pageInfo;

        static MetricsOverviewResponse fromDomain(com.sprintcart.domain.metrics.ProductivityMetrics m) {
            return MetricsOverviewResponse.builder()
                    .activeOrders(m.getActiveOrders())
                    .avgSecondsToFulfillment(m.getAvgSecondsToFulfillment())
                    .revenuePerMinute(m.getRevenuePerMinute())
                    .pageInfo(PageInfo.ofNow())
                    .build();
        }
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    private static class BulkImportAcceptedResponse {
        private String importJobId;
        private Instant receivedAt;
        private boolean dryRun;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class RoleUpdateRequest {
        @NotEmpty
        @Size(max = 10)
        private List<@Size(max = 30) String> roles;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    private static class ErrorResponse {
        private String code;
        private String message;
        private Map<String, String> fieldErrors;

        static ErrorResponse from(String code, String message) {
            return from(code, message, Collections.emptyMap());
        }

        static ErrorResponse from(String code, String message, Map<String, String> fieldErrors) {
            return ErrorResponse.builder()
                    .code(code)
                    .message(message)
                    .fieldErrors(fieldErrors)
                    .build();
        }
    }
}