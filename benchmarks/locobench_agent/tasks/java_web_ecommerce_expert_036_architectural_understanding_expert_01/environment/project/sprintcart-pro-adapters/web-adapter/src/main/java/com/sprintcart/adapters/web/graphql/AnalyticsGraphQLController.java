package com.sprintcart.adapters.web.graphql;

import com.sprintcart.application.analytics.AnalyticsQueryUseCase;
import com.sprintcart.domain.analytics.DashboardMetrics;
import com.sprintcart.domain.analytics.SalesBucket;
import com.sprintcart.domain.analytics.TimeGranularity;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PastOrPresent;
import jakarta.validation.constraints.Size;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.ControllerAdvice;
import org.springframework.graphql.data.method.annotation.ExceptionHandler;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.stereotype.Controller;
import org.springframework.validation.annotation.Validated;

import java.time.LocalDate;
import java.util.List;
import java.util.stream.Collectors;

/**
 * GraphQL Controller that exposes read-only analytics queries for
 * dashboards, reports, and productivity insights.
 *
 * All heavy lifting is delegated to {@link AnalyticsQueryUseCase},
 * which represents the primary (application) port for analytics reads.
 *
 * The controller purposefully avoids exposing domain objects directly;
 * instead, it converts them to lightweight DTOs that are stable for
 * public consumption.
 */
@Controller
@Validated
public class AnalyticsGraphQLController {

    private static final Logger log = LoggerFactory.getLogger(AnalyticsGraphQLController.class);

    private final AnalyticsQueryUseCase analyticsQuery;

    public AnalyticsGraphQLController(AnalyticsQueryUseCase analyticsQuery) {
        this.analyticsQuery = analyticsQuery;
    }

    /**
     * Returns aggregated KPI metrics for the given date range.
     */
    @QueryMapping
    public DashboardMetricsDTO dashboardMetrics(
            @Argument @Valid DateRangeInput range) {

        verifyRange(range);

        DashboardMetrics metrics = analyticsQuery.getDashboardMetrics(
                range.toDomainStart(), range.toDomainEnd());

        return DashboardMetricsDTO.from(metrics);
    }

    /**
     * Returns a list of sales buckets—time-series values representing order revenue,
     * grouped by the requested granularity (e.g., DAY, WEEK, MONTH).
     */
    @QueryMapping
    public List<SalesBucketDTO> salesOverTime(
            @Argument @Valid DateRangeInput range,
            @Argument TimeGranularity granularity) {

        verifyRange(range);

        List<SalesBucket> buckets = analyticsQuery.getSalesOverTime(
                range.toDomainStart(),
                range.toDomainEnd(),
                granularity);

        return buckets.stream()
                .map(SalesBucketDTO::from)
                .collect(Collectors.toList());
    }

    /**
     * A simple guard ensuring the date range is not inverted.
     */
    private void verifyRange(DateRangeInput range) {
        if (range.getStart().isAfter(range.getEnd())) {
            throw new IllegalArgumentException("start must be before or equal to end");
        }
    }

    /* ──────────────────────────────────────────
     * DTOs & GraphQL-friendly representations
     * ──────────────────────────────────────────
     */

    public static class DateRangeInput {

        @NotNull
        @PastOrPresent
        private LocalDate start;

        @NotNull
        private LocalDate end;

        public LocalDate getStart() { return start; }
        public void setStart(LocalDate start) { this.start = start; }

        public LocalDate getEnd() { return end; }
        public void setEnd(LocalDate end) { this.end = end; }

        public LocalDate toDomainStart() {
            return start;
        }

        public LocalDate toDomainEnd() {
            return end;
        }
    }

    public static class DashboardMetricsDTO {

        private Double revenue;
        private Integer orders;
        private Integer averageOrderValue;
        private Integer itemsSold;
        private Double conversionRate;

        public Double getRevenue() { return revenue; }
        public Integer getOrders() { return orders; }
        public Integer getAverageOrderValue() { return averageOrderValue; }
        public Integer getItemsSold() { return itemsSold; }
        public Double getConversionRate() { return conversionRate; }

        static DashboardMetricsDTO from(DashboardMetrics metrics) {
            DashboardMetricsDTO dto = new DashboardMetricsDTO();
            dto.revenue = metrics.totalRevenue();
            dto.orders = metrics.orderCount();
            dto.averageOrderValue = metrics.averageOrderValue();
            dto.itemsSold = metrics.itemsSold();
            dto.conversionRate = metrics.conversionRate();
            return dto;
        }
    }

    public static class SalesBucketDTO {

        private LocalDate bucketStart;
        private LocalDate bucketEnd;
        private Double revenue;

        public LocalDate getBucketStart() { return bucketStart; }
        public LocalDate getBucketEnd() { return bucketEnd; }
        public Double getRevenue() { return revenue; }

        static SalesBucketDTO from(SalesBucket bucket) {
            SalesBucketDTO dto = new SalesBucketDTO();
            dto.bucketStart = bucket.bucketStart();
            dto.bucketEnd = bucket.bucketEnd();
            dto.revenue = bucket.revenue();
            return dto;
        }
    }

    /* ──────────────────────────────────────────
     * Exception handling
     * ──────────────────────────────────────────
     */

    @ControllerAdvice
    public static class AnalyticsGraphQLErrorHandler {

        private static final Logger log =
                LoggerFactory.getLogger(AnalyticsGraphQLErrorHandler.class);

        @ExceptionHandler(IllegalArgumentException.class)
        public String handleIllegalArgument(IllegalArgumentException ex) {
            log.debug("Client side error: {}", ex.getMessage());
            return ex.getMessage();
        }

        @ExceptionHandler(Exception.class)
        public String handleUnexpected(Exception ex) {
            log.error("Unexpected analytics error", ex);
            return "Unknown error while processing analytics query";
        }
    }
}