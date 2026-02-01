package com.commercesphere.enterprise.reporting.controller;

import com.commercesphere.enterprise.reporting.dto.DashboardMetricDto;
import com.commercesphere.enterprise.reporting.dto.DashboardTrendPointDto;
import com.commercesphere.enterprise.reporting.service.DashboardService;
import com.commercesphere.enterprise.shared.auth.CurrentUser;
import com.commercesphere.enterprise.shared.auth.UserPrincipal;
import com.commercesphere.enterprise.shared.error.ApiError;
import com.commercesphere.enterprise.shared.error.ResourceNotFoundException;
import com.commercesphere.enterprise.shared.logging.MDCUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;
import org.springframework.core.io.InputStreamResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.util.Assert;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import javax.servlet.http.HttpServletRequest;
import javax.validation.constraints.Positive;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.OutputStreamWriter;
import java.time.LocalDate;
import java.util.List;
import java.util.stream.Collectors;

/**
 * DashboardController exposes read-only administrative dashboard endpoints that
 * surface key performance metrics (KPI) and historical trends for finance,
 * operations, and compliance teams.  All endpoints require the requester to be
 * in the ADMIN or FINANCE role and are fully auditable through the global
 * logging framework.
 *
 * NOTE:  This controller purposefully performs no domain logic; that resides in
 * the underlying {@link DashboardService}.  This design satisfies the layered
 * architecture pattern adopted by CommerceSphere Enterprise Suite.
 */
@Slf4j
@Validated
@RequiredArgsConstructor
@RestController
@RequestMapping("/api/v1/admin/dashboard")
public class DashboardController {

    private final DashboardService dashboardService;

    /**
     * Returns an aggregated, point-in-time snapshot of core metrics such as
     * gross revenue, total orders, average order value, and pending approvals.
     *
     * GET /api/v1/admin/dashboard/overview
     */
    @GetMapping("/overview")
    @PreAuthorize("hasAnyRole('ADMIN','FINANCE')")
    public ResponseEntity<DashboardMetricDto> getOverview(@CurrentUser UserPrincipal user,
                                                          HttpServletRequest request) {
        MDCUtil.addRequestContext(request, user);

        log.info("Fetching dashboard overview for tenant={}, userId={}",
                user.getTenantId(), user.getId());

        try {
            DashboardMetricDto overview = dashboardService.getOverview(user.getTenantId());
            return ResponseEntity.ok(overview);
        } catch (ResourceNotFoundException ex) {
            log.warn("Overview data not found. tenant={}", user.getTenantId(), ex);
            throw new ResponseStatusException(ex.getStatus(), ex.getMessage(), ex);
        } finally {
            MDCUtil.clear();
        }
    }

    /**
     * Returns a list of (date, revenue) pairs for a configurable range.  Client
     * applications typically graph the data as an area or line chart.
     *
     * GET /api/v1/admin/dashboard/trends?daysBack=30
     */
    @GetMapping("/trends")
    @PreAuthorize("hasAnyRole('ADMIN','FINANCE')")
    public ResponseEntity<List<DashboardTrendPointDto>> getRevenueTrend(
            @RequestParam(defaultValue = "30")
            @Positive(message = "daysBack must be a positive integer") int daysBack,
            @CurrentUser UserPrincipal user,
            HttpServletRequest request) {

        MDCUtil.addRequestContext(request, user);

        log.debug("Fetching revenue trend for tenant={}, userId={}, daysBack={}",
                user.getTenantId(), user.getId(), daysBack);

        List<DashboardTrendPointDto> trend = dashboardService
                .getRevenueTrend(user.getTenantId(), LocalDate.now().minusDays(daysBack), LocalDate.now());

        return ResponseEntity.ok(trend);
    }

    /**
     * Streams a CSV export of the revenue trend to the client.  The endpoint is
     * implemented as a blocking call because the maximum dataset (1 year) is
     * capped at <40KB and finishes under 250 ms under load-test conditions.
     *
     * GET /api/v1/admin/dashboard/export?daysBack=365
     */
    @GetMapping("/export")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<InputStreamResource> exportRevenueTrendCsv(
            @RequestParam(defaultValue = "365") @Positive int daysBack,
            @CurrentUser UserPrincipal user,
            HttpServletRequest request) {

        MDCUtil.addRequestContext(request, user);

        List<DashboardTrendPointDto> trend = dashboardService
                .getRevenueTrend(user.getTenantId(), LocalDate.now().minusDays(daysBack), LocalDate.now());

        // Build CSV in-memory; switch to temp file strategy if data size grows.
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (CSVPrinter printer = new CSVPrinter(new OutputStreamWriter(out),
                CSVFormat.DEFAULT.withHeader("date", "revenue"))) {

            for (DashboardTrendPointDto point : trend) {
                printer.printRecord(point.getDate().toString(), point.getRevenue().toPlainString());
            }
            printer.flush();
        } catch (Exception ex) {
            log.error("CSV export failed for tenant={}", user.getTenantId(), ex);
            ApiError apiError = new ApiError("CSV_EXPORT_FAILURE",
                    "Unable to generate the CSV export at this time. Please retry or contact support.");
            throw new ResponseStatusException(apiError.getHttpStatus(), apiError.getMessage(), ex);
        }

        ByteArrayInputStream resource = new ByteArrayInputStream(out.toByteArray());

        HttpHeaders headers = new HttpHeaders();
        headers.setContentDispositionFormData("attachment",
                String.format("revenue_trend_%s_%s.csv", user.getTenantId(), LocalDate.now()));
        headers.setCacheControl("no-cache");

        return ResponseEntity.ok()
                .headers(headers)
                .contentLength(out.size())
                .contentType(MediaType.parseMediaType("text/csv"))
                .body(new InputStreamResource(resource));
    }

    /**
     * Global exception handler scoped to this controller. Converts domain and
     * infrastructure exceptions into consistent HTTP responses.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> handleException(Exception ex) {
        log.error("Unhandled exception in DashboardController", ex);

        ApiError error;
        if (ex instanceof ResourceNotFoundException) {
            error = new ApiError("DASHBOARD_RESOURCE_NOT_FOUND", ex.getMessage());
            return ResponseEntity.status(error.getHttpStatus()).body(error);
        }

        error = new ApiError("DASHBOARD_INTERNAL_ERROR",
                "An unexpected error occurred. Please contact CommerceSphere support.");
        return ResponseEntity.status(error.getHttpStatus()).body(error);
    }
}