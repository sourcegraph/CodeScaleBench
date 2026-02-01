package com.commercesphere.enterprise.reporting.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/**
 * RevenueSummaryDto is a read-only, serializable data-transfer object that encapsulates
 * the monetary results of a transactional period in a single immutable object.
 *
 * The DTO is designed to be:
 *  • JSON-serializable (via Jackson)
 *  • Immutable (all fields are final, exposed through getters only)
 *  • Self-consistent (basic validation rules applied at construction time)
 *
 * Typical usage:
 *
 * <pre>{@code
 * RevenueSummaryDto summary = RevenueSummaryDto.builder()
 *         .periodStart(LocalDate.of(2024, 1, 1))
 *         .periodEnd(LocalDate.of(2024, 1, 31))
 *         .currencyCode("USD")
 *         .grossSales(new BigDecimal("120000.00"))
 *         .returns(new BigDecimal("4500.00"))
 *         .discounts(new BigDecimal("3500.00"))
 *         .taxCollected(new BigDecimal("8600.00"))
 *         .shippingCollected(new BigDecimal("2400.00"))
 *         .addChannelBreakdown("B2B_PORTAL", new BigDecimal("70000.00"))
 *         .addChannelBreakdown("SALES_REP",   new BigDecimal("50000.00"))
 *         .build();
 * }</pre>
 *
 * All monetary values must be in the same currency and expressed as positive values.
 * Negative amounts must be passed using {@link java.math.BigDecimal#negate()} explicitly
 * (validation will fail otherwise).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonDeserialize(builder = RevenueSummaryDto.Builder.class)
public final class RevenueSummaryDto implements Serializable {

    @Serial
    private static final long serialVersionUID = 2951635234072226775L;

    /** Currency of all monetary fields (ISO-4217) */
    private final String currencyCode;

    /** Total sales value before discounts or returns */
    private final BigDecimal grossSales;

    /** Value of merchandise returned during the period */
    private final BigDecimal returns;

    /** Promotional or contractual discounts applied */
    private final BigDecimal discounts;

    /** Tax collected on net sales */
    private final BigDecimal taxCollected;

    /** Shipping/handling revenue collected */
    private final BigDecimal shippingCollected;

    /** Period start (inclusive) */
    private final LocalDate periodStart;

    /** Period end (inclusive) */
    private final LocalDate periodEnd;

    /** Optional breakdown by sales channel (values must sum to grossSales) */
    private final Map<String, BigDecimal> channelBreakdown;

    private RevenueSummaryDto(Builder builder) {
        this.currencyCode      = builder.currencyCode;
        this.grossSales        = builder.grossSales;
        this.returns           = builder.returns;
        this.discounts         = builder.discounts;
        this.taxCollected      = builder.taxCollected;
        this.shippingCollected = builder.shippingCollected;
        this.periodStart       = builder.periodStart;
        this.periodEnd         = builder.periodEnd;
        this.channelBreakdown  = Collections.unmodifiableMap(new LinkedHashMap<>(builder.channelBreakdown));

        validateInvariants();
    }

    /* -------------------------------------------------------------
     *                       Derived Calculations
     * ------------------------------------------------------------- */

    /**
     * Net sales after discounts and returns, but before taxes and shipping.
     */
    public BigDecimal getNetSales() {
        return grossSales
                .subtract(returns)
                .subtract(discounts)
                .setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * Total revenue (net sales + tax + shipping).
     */
    public BigDecimal getTotalRevenue() {
        return getNetSales()
                .add(taxCollected)
                .add(shippingCollected)
                .setScale(2, RoundingMode.HALF_UP);
    }

    /* -------------------------------------------------------------
     *                       Public Getters
     * ------------------------------------------------------------- */

    public String getCurrencyCode() {
        return currencyCode;
    }

    public BigDecimal getGrossSales() {
        return grossSales;
    }

    public BigDecimal getReturns() {
        return returns;
    }

    public BigDecimal getDiscounts() {
        return discounts;
    }

    public BigDecimal getTaxCollected() {
        return taxCollected;
    }

    public BigDecimal getShippingCollected() {
        return shippingCollected;
    }

    public LocalDate getPeriodStart() {
        return periodStart;
    }

    public LocalDate getPeriodEnd() {
        return periodEnd;
    }

    public Map<String, BigDecimal> getChannelBreakdown() {
        return channelBreakdown;
    }

    /* -------------------------------------------------------------
     *                           Builder
     * ------------------------------------------------------------- */

    public static Builder builder() {
        return new Builder();
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class Builder {

        private static final String DEFAULT_CURRENCY = "USD";

        private String currencyCode = DEFAULT_CURRENCY;
        private BigDecimal grossSales = BigDecimal.ZERO;
        private BigDecimal returns = BigDecimal.ZERO;
        private BigDecimal discounts = BigDecimal.ZERO;
        private BigDecimal taxCollected = BigDecimal.ZERO;
        private BigDecimal shippingCollected = BigDecimal.ZERO;
        private LocalDate periodStart;
        private LocalDate periodEnd;
        private final Map<String, BigDecimal> channelBreakdown = new LinkedHashMap<>();

        public Builder() {
            // no-args constructor needed for Jackson deserialization
        }

        @JsonCreator
        public Builder(
                @JsonProperty("currencyCode")      String currencyCode,
                @JsonProperty("grossSales")        BigDecimal grossSales,
                @JsonProperty("returns")           BigDecimal returns,
                @JsonProperty("discounts")         BigDecimal discounts,
                @JsonProperty("taxCollected")      BigDecimal taxCollected,
                @JsonProperty("shippingCollected") BigDecimal shippingCollected,
                @JsonProperty("periodStart")       LocalDate periodStart,
                @JsonProperty("periodEnd")         LocalDate periodEnd,
                @JsonProperty("channelBreakdown")  Map<String, BigDecimal> channelBreakdown
        ) {
            this.currencyCode      = Objects.requireNonNullElse(currencyCode, DEFAULT_CURRENCY);
            this.grossSales        = nullableToZero(grossSales);
            this.returns           = nullableToZero(returns);
            this.discounts         = nullableToZero(discounts);
            this.taxCollected      = nullableToZero(taxCollected);
            this.shippingCollected = nullableToZero(shippingCollected);
            this.periodStart       = periodStart;
            this.periodEnd         = periodEnd;
            if (channelBreakdown != null) {
                this.channelBreakdown.putAll(channelBreakdown);
            }
        }

        public Builder currencyCode(String currencyCode) {
            this.currencyCode = Objects.requireNonNull(currencyCode, "currencyCode");
            return this;
        }

        public Builder grossSales(BigDecimal grossSales) {
            this.grossSales = ensureNonNegative(grossSales, "grossSales");
            return this;
        }

        public Builder returns(BigDecimal returns) {
            this.returns = ensureNonNegative(returns, "returns");
            return this;
        }

        public Builder discounts(BigDecimal discounts) {
            this.discounts = ensureNonNegative(discounts, "discounts");
            return this;
        }

        public Builder taxCollected(BigDecimal taxCollected) {
            this.taxCollected = ensureNonNegative(taxCollected, "taxCollected");
            return this;
        }

        public Builder shippingCollected(BigDecimal shippingCollected) {
            this.shippingCollected = ensureNonNegative(shippingCollected, "shippingCollected");
            return this;
        }

        public Builder periodStart(LocalDate periodStart) {
            this.periodStart = Objects.requireNonNull(periodStart, "periodStart");
            return this;
        }

        public Builder periodEnd(LocalDate periodEnd) {
            this.periodEnd = Objects.requireNonNull(periodEnd, "periodEnd");
            return this;
        }

        public Builder addChannelBreakdown(String channel, BigDecimal amount) {
            Objects.requireNonNull(channel, "channel name");
            this.channelBreakdown.put(channel, ensureNonNegative(amount, "channelBreakdown amount"));
            return this;
        }

        public RevenueSummaryDto build() {
            return new RevenueSummaryDto(this);
        }

        /* ---------------------------------------------------------
         *                 Helper methods for Builder
         * --------------------------------------------------------- */

        private static BigDecimal ensureNonNegative(BigDecimal number, String field) {
            Objects.requireNonNull(number, field);
            if (number.signum() < 0) {
                throw new IllegalArgumentException(field + " must not be negative");
            }
            return number.setScale(2, RoundingMode.HALF_UP);
        }

        private static BigDecimal nullableToZero(BigDecimal number) {
            return number == null ? BigDecimal.ZERO : number.setScale(2, RoundingMode.HALF_UP);
        }
    }

    /* -------------------------------------------------------------
     *                    Private Validation Logic
     * ------------------------------------------------------------- */

    private void validateInvariants() {

        Objects.requireNonNull(currencyCode, "currencyCode");

        if (periodStart == null || periodEnd == null) {
            throw new IllegalStateException("Both periodStart and periodEnd must be provided");
        }
        if (periodEnd.isBefore(periodStart)) {
            throw new IllegalStateException("periodEnd must be equal to or after periodStart");
        }

        // Gross sales must at least be equal to discounts + returns
        if (grossSales.compareTo(returns.add(discounts)) < 0) {
            throw new IllegalStateException(
                    "grossSales (" + grossSales + ") cannot be less than returns + discounts (" +
                    returns.add(discounts) + ')');
        }

        // Channel breakdown must not exceed grossSales
        BigDecimal breakdownSum = channelBreakdown.values()
                                                  .stream()
                                                  .reduce(BigDecimal.ZERO, BigDecimal::add);

        if (breakdownSum.compareTo(grossSales) > 0) {
            throw new IllegalStateException(
                    "Sum of channelBreakdown (" + breakdownSum + ") exceeds grossSales (" + grossSales + ')');
        }
    }

    /* -------------------------------------------------------------
     *            equals, hashCode & toString (IDE generated)
     * ------------------------------------------------------------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof RevenueSummaryDto that)) return false;
        return Objects.equals(currencyCode, that.currencyCode) &&
               Objects.equals(grossSales, that.grossSales) &&
               Objects.equals(returns, that.returns) &&
               Objects.equals(discounts, that.discounts) &&
               Objects.equals(taxCollected, that.taxCollected) &&
               Objects.equals(shippingCollected, that.shippingCollected) &&
               Objects.equals(periodStart, that.periodStart) &&
               Objects.equals(periodEnd, that.periodEnd) &&
               Objects.equals(channelBreakdown, that.channelBreakdown);
    }

    @Override
    public int hashCode() {
        return Objects.hash(currencyCode, grossSales, returns, discounts, taxCollected,
                            shippingCollected, periodStart, periodEnd, channelBreakdown);
    }

    @Override
    public String toString() {
        return "RevenueSummaryDto{" +
               "currencyCode='" + currencyCode + '\'' +
               ", grossSales=" + grossSales +
               ", returns=" + returns +
               ", discounts=" + discounts +
               ", taxCollected=" + taxCollected +
               ", shippingCollected=" + shippingCollected +
               ", periodStart=" + periodStart +
               ", periodEnd=" + periodEnd +
               ", channelBreakdown=" + channelBreakdown +
               '}';
    }
}