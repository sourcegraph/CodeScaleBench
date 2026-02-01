package com.commercesphere.enterprise.reporting.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.Currency;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.TreeMap;
import java.util.stream.Collectors;

import javax.persistence.Entity;
import javax.persistence.Id;
import javax.persistence.Tuple;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.dao.DataAccessException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Service that produces revenue–oriented reports used by the Finance and
 * Accounting teams.  The implementation purposefully performs all
 * monetary arithmetic with BigDecimal in conjunction with ISO‐4217
 * currencies to avoid rounding issues.
 *
 * <p>
 * Most methods are read-only and, therefore, are executed in read-only
 * transactions to keep the write-lock footprint minimal on heavily used
 * OLTP tables such as <code>invoice</code> and <code>order</code>.
 * </p>
 *
 * Note: This is a service-layer façade; business consumers should not
 * call the underlying repositories directly.
 */
@Service
@Transactional(readOnly = true)
public class RevenueReportingService {

    private static final Logger LOGGER = LoggerFactory.getLogger(RevenueReportingService.class);

    private final InvoiceRepository invoiceRepository;
    private final CurrencyConversionService currencyConversionService;
    private final AuditLogService auditLogService;

    public RevenueReportingService(
            InvoiceRepository invoiceRepository,
            CurrencyConversionService currencyConversionService,
            AuditLogService auditLogService) {

        this.invoiceRepository = Objects.requireNonNull(invoiceRepository, "invoiceRepository");
        this.currencyConversionService = Objects.requireNonNull(currencyConversionService, "currencyConversionService");
        this.auditLogService = Objects.requireNonNull(auditLogService, "auditLogService");
    }

    /**
     * Creates an aggregate revenue report in the desired currency.
     *
     * @param from           inclusive start date
     * @param to             inclusive end date
     * @param targetCurrency the currency to which all amounts will be converted
     * @return revenue summary
     */
    @Cacheable(
            value = "revenueSummaryCache",
            key = "{#from, #to, #targetCurrency}"
    )
    public RevenueSummaryReport generateSummary(
            @NonNull LocalDate from,
            @NonNull LocalDate to,
            @NonNull Currency targetCurrency) {

        validateDateRange(from, to);

        try {
            List<RevenueAggregation> aggregates =
                    invoiceRepository.fetchRevenueAggregates(from, to);

            BigDecimal gross = BigDecimal.ZERO;
            BigDecimal discounts = BigDecimal.ZERO;
            BigDecimal taxes = BigDecimal.ZERO;

            for (RevenueAggregation agg : aggregates) {
                Currency sourceCurrency = agg.getCurrency();

                gross = gross.add(convert(agg.getGrossSales(), sourceCurrency, targetCurrency));
                discounts = discounts.add(convert(agg.getDiscounts(), sourceCurrency, targetCurrency));
                taxes = taxes.add(convert(agg.getTaxes(), sourceCurrency, targetCurrency));
            }

            BigDecimal net = gross
                    .subtract(discounts)
                    .add(taxes)
                    .setScale(2, RoundingMode.HALF_UP);

            RevenueSummaryReport summary = new RevenueSummaryReport(
                    from, to, targetCurrency, gross, discounts, taxes, net);

            auditLogService.trackFinanceReportAccess("REVENUE_SUMMARY", from, to);

            return summary;
        } catch (DataAccessException ex) {
            LOGGER.error("Error while generating revenue summary", ex);
            throw new ReportingException("Unable to generate revenue summary", ex);
        }
    }

    /**
     * Returns daily revenue breakdown for a date range in a given
     * currency.  For performance reasons, the method is cached on a
     * per-day basis.
     */
    @Cacheable(
            value = "dailyRevenueCache",
            key = "{#from, #to, #currency}"
    )
    public List<DailyRevenue> getDailyRevenue(
            @NonNull LocalDate from,
            @NonNull LocalDate to,
            @NonNull Currency currency) {

        validateDateRange(from, to);

        try {
            List<DailyRevenueAggregation> aggregates =
                    invoiceRepository.fetchDailyRevenueAggregates(
                            from, to, Sort.by("invoiceDate"));

            Map<LocalDate, BigDecimal> amountByDay = new TreeMap<>();

            for (DailyRevenueAggregation agg : aggregates) {
                BigDecimal converted =
                        convert(agg.getNetSales(), agg.getCurrency(), currency);

                amountByDay.merge(
                        agg.getInvoiceDate(),
                        converted,
                        BigDecimal::add
                );
            }

            return amountByDay.entrySet().stream()
                    .map(e -> new DailyRevenue(e.getKey(), currency, e.getValue()))
                    .collect(Collectors.toList());

        } catch (DataAccessException e) {
            LOGGER.error("Error while retrieving daily revenue", e);
            throw new ReportingException("Unable to retrieve daily revenue", e);
        }
    }

    /**
     * Paginates through invoice-level revenue data.  This is primarily
     * used by the administrative UI to present drill-down capabilities.
     */
    public Page<InvoiceRevenueDto> getInvoiceRevenue(
            @NonNull LocalDate from,
            @NonNull LocalDate to,
            @NonNull Pageable pageable) {

        validateDateRange(from, to);

        try {
            return invoiceRepository
                    .findByIssueDateBetween(from, to, pageable)
                    .map(InvoiceRevenueDto::fromInvoice);
        } catch (DataAccessException e) {
            LOGGER.error("Failed to load invoice revenue page {}", pageable, e);
            throw new ReportingException("Unable to load invoice revenue", e);
        }
    }

    /* --------------- Helper utilities ---------------- */

    private void validateDateRange(LocalDate from, LocalDate to) {
        if (from.isAfter(to)) {
            throw new IllegalArgumentException(
                    String.format("Invalid date range: %s is after %s", from, to));
        }
    }

    private BigDecimal convert(BigDecimal amount, Currency from, Currency to) {
        if (from.equals(to)) {
            return amount;
        }
        return currencyConversionService.convert(amount, from, to);
    }

    /* --------------- DTOs and View Models ---------------- */

    public static final class RevenueSummaryReport {
        private final LocalDate from;
        private final LocalDate to;
        private final Currency currency;
        private final BigDecimal grossSales;
        private final BigDecimal discounts;
        private final BigDecimal taxes;
        private final BigDecimal netSales;

        public RevenueSummaryReport(LocalDate from,
                                    LocalDate to,
                                    Currency currency,
                                    BigDecimal grossSales,
                                    BigDecimal discounts,
                                    BigDecimal taxes,
                                    BigDecimal netSales) {
            this.from = from;
            this.to = to;
            this.currency = currency;
            this.grossSales = grossSales;
            this.discounts = discounts;
            this.taxes = taxes;
            this.netSales = netSales;
        }

        public LocalDate getFrom() { return from; }
        public LocalDate getTo() { return to; }
        public Currency getCurrency() { return currency; }
        public BigDecimal getGrossSales() { return grossSales; }
        public BigDecimal getDiscounts() { return discounts; }
        public BigDecimal getTaxes() { return taxes; }
        public BigDecimal getNetSales() { return netSales; }
    }

    public static final class DailyRevenue {
        private final LocalDate date;
        private final Currency currency;
        private final BigDecimal netSales;

        public DailyRevenue(LocalDate date, Currency currency, BigDecimal netSales) {
            this.date = date;
            this.currency = currency;
            this.netSales = netSales;
        }

        public LocalDate getDate() { return date; }
        public Currency getCurrency() { return currency; }
        public BigDecimal getNetSales() { return netSales; }
    }

    public static final class InvoiceRevenueDto {
        private final String invoiceNumber;
        private final LocalDate invoiceDate;
        private final BigDecimal amount;
        private final Currency currency;

        private InvoiceRevenueDto(String invoiceNumber, LocalDate invoiceDate,
                                  BigDecimal amount, Currency currency) {
            this.invoiceNumber = invoiceNumber;
            this.invoiceDate = invoiceDate;
            this.amount = amount;
            this.currency = currency;
        }

        public static InvoiceRevenueDto fromInvoice(Invoice invoice) {
            return new InvoiceRevenueDto(
                    invoice.getInvoiceNumber(),
                    invoice.getInvoiceDate(),
                    invoice.getGrandTotal(),
                    invoice.getCurrency());
        }

        public String getInvoiceNumber() { return invoiceNumber; }
        public LocalDate getInvoiceDate() { return invoiceDate; }
        public BigDecimal getAmount() { return amount; }
        public Currency getCurrency() { return currency; }
    }

    /* --------------- Repository aggregates ---------------- */

    public static final class RevenueAggregation {
        private final BigDecimal grossSales;
        private final BigDecimal discounts;
        private final BigDecimal taxes;
        private final Currency currency;

        public RevenueAggregation(BigDecimal grossSales, BigDecimal discounts,
                                  BigDecimal taxes, Currency currency) {
            this.grossSales = grossSales;
            this.discounts = discounts;
            this.taxes = taxes;
            this.currency = currency;
        }

        public BigDecimal getGrossSales() { return grossSales; }
        public BigDecimal getDiscounts() { return discounts; }
        public BigDecimal getTaxes() { return taxes; }
        public Currency getCurrency() { return currency; }
    }

    public static final class DailyRevenueAggregation {
        private final LocalDate invoiceDate;
        private final BigDecimal netSales;
        private final Currency currency;

        public DailyRevenueAggregation(LocalDate invoiceDate,
                                       BigDecimal netSales,
                                       Currency currency) {
            this.invoiceDate = invoiceDate;
            this.netSales = netSales;
            this.currency = currency;
        }

        public LocalDate getInvoiceDate() { return invoiceDate; }
        public BigDecimal getNetSales() { return netSales; }
        public Currency getCurrency() { return currency; }
    }

    /* --------------- Repository contracts ---------------- */

    /**
     * A pared-down repository that exposes only the queries required by
     * this service.  The full repository exists elsewhere in the
     * codebase, but we redeclare the relevant subset here for
     * completeness of the example.
     */
    interface InvoiceRepository extends Repository<Invoice, Long> {

        @Query("""
               SELECT new com.commercesphere.enterprise.reporting.service.RevenueReportingService$RevenueAggregation(
                   SUM(i.subtotal), SUM(i.discountTotal), SUM(i.taxTotal), i.currency)
               FROM Invoice i
               WHERE i.invoiceDate BETWEEN :from AND :to
               GROUP BY i.currency
               """)
        List<RevenueAggregation> fetchRevenueAggregates(@Param("from") LocalDate from,
                                                        @Param("to")   LocalDate to);

        @Query("""
               SELECT new com.commercesphere.enterprise.reporting.service.RevenueReportingService$DailyRevenueAggregation(
                   i.invoiceDate, SUM(i.grandTotal), i.currency)
               FROM Invoice i
               WHERE i.invoiceDate BETWEEN :from AND :to
               GROUP BY i.invoiceDate, i.currency
               """)
        List<DailyRevenueAggregation> fetchDailyRevenueAggregates(@Param("from") LocalDate from,
                                                                  @Param("to")   LocalDate to,
                                                                  Sort sort);

        Page<Invoice> findByIssueDateBetween(LocalDate from,
                                             LocalDate to,
                                             Pageable pageable);
    }

    /* --------------- Domain entities (simplified) ---------------- */

    @Entity(name = "Invoice")
    static class Invoice {
        @Id
        private Long id;
        private String invoiceNumber;
        private LocalDate invoiceDate;
        private BigDecimal subtotal;
        private BigDecimal discountTotal;
        private BigDecimal taxTotal;
        private BigDecimal grandTotal;
        private Currency currency;

        /* Getters omitted for brevity */
        public String getInvoiceNumber() { return invoiceNumber; }
        public LocalDate getInvoiceDate() { return invoiceDate; }
        public BigDecimal getGrandTotal() { return grandTotal; }
        public Currency getCurrency() { return currency; }
    }

    /* --------------- Cross-cutting collaborators ---------------- */

    interface CurrencyConversionService {
        BigDecimal convert(BigDecimal amount, Currency from, Currency to);
    }

    interface AuditLogService {
        void trackFinanceReportAccess(String reportCode, LocalDate from, LocalDate to);
    }

    /* --------------- Custom exception ---------------- */

    public static class ReportingException extends RuntimeException {
        public ReportingException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}