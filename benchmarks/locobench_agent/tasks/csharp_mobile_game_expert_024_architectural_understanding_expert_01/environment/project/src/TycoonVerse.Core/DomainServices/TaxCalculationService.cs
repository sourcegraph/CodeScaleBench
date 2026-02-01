using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;

namespace TycoonVerse.Core.DomainServices
{
    /// <summary>
    ///     Provides deterministic, side–effect free tax calculations for in-game companies.
    ///     The service is domain-centric and is agnostic of Unity, persistence, or UI concerns.
    /// </summary>
    public sealed class TaxCalculationService : ITaxCalculationService
    {
        private readonly ICountryTaxRuleRepository _ruleRepository;

        // Local, thread-safe, in-memory cache so repeated calls in the same session
        // (e.g., annual close on many companies) avoid repository round-trips.
        private readonly ConcurrentDictionary<string, CountryTaxRule> _ruleCache =
            new ConcurrentDictionary<string, CountryTaxRule>(StringComparer.OrdinalIgnoreCase);

        public TaxCalculationService(ICountryTaxRuleRepository ruleRepository)
        {
            _ruleRepository = ruleRepository ?? throw new ArgumentNullException(nameof(ruleRepository));
        }

        /// <inheritdoc />
        public TaxReport CalculateCorporateTax(CompanySnapshot snapshot, FiscalPeriod period)
        {
            if (snapshot is null) throw new ArgumentNullException(nameof(snapshot));
            if (period is null) throw new ArgumentNullException(nameof(period));

            var rule = GetTaxRule(snapshot.CountryCode);

            // 1. Determine taxable income after operating loss carry-forwards.
            decimal taxableIncome = Math.Max(0, snapshot.NetProfit - snapshot.LossCarryForward);

            // 2. Apply deductions (e.g., R&D credits, SEZ incentives).
            taxableIncome -= CalculateDeductions(snapshot, rule);

            taxableIncome = Math.Max(0, taxableIncome); // no negative tax base

            // 3. Progressive brackets.
            decimal taxDue = 0;
            foreach (var bracket in rule.Brackets.OrderBy(b => b.LowerBound))
            {
                if (taxableIncome <= bracket.LowerBound) break;

                decimal upperEffective = bracket.UpperBound ?? decimal.MaxValue;
                decimal taxableAtBracket = Math.Min(taxableIncome, upperEffective) - bracket.LowerBound;
                taxDue += taxableAtBracket * bracket.Rate;
                if (taxableIncome <= upperEffective) break;
            }

            // 4. Minimum alternative tax (if any).
            if (rule.MinimumTax.HasValue)
            {
                taxDue = Math.Max(taxDue, rule.MinimumTax.Value);
            }

            // 5. Finalize report.
            return new TaxReport(
                companyId: snapshot.CompanyId,
                fiscalPeriod: period,
                taxableIncome: taxableIncome,
                taxDue: Decimal.Round(taxDue, 2),
                effectiveRate: taxableIncome == 0 ? 0 : taxDue / taxableIncome
            );
        }

        #region Private helpers

        private CountryTaxRule GetTaxRule(string countryCode)
        {
            if (string.IsNullOrWhiteSpace(countryCode))
                throw new ArgumentException("Country code cannot be null or empty.", nameof(countryCode));

            return _ruleCache.GetOrAdd(
                countryCode,
                code => _ruleRepository.GetByCountry(code)
                           ?? throw new TaxRuleNotFoundException($"No tax rule defined for country '{code}'."));
        }

        private static decimal CalculateDeductions(CompanySnapshot snapshot, CountryTaxRule rule)
        {
            decimal deductions = 0;

            // R&D credit – capped at configurable max percentage of revenue.
            if (rule.RAndDCreditRate.HasValue && snapshot.RAndDSpend > 0)
            {
                decimal maxCredit = snapshot.Revenue * rule.RAndDMaxCreditAsRevenuePct;
                deductions += Math.Min(snapshot.RAndDSpend * rule.RAndDCreditRate.Value, maxCredit);
            }

            // Special Economic Zone incentive – flat percentage rebate on profit.
            if (snapshot.IsInSpecialEconomicZone)
            {
                deductions += snapshot.NetProfit * rule.SezProfitDeductionRate;
            }

            return deductions;
        }

        #endregion
    }

    #region Interfaces & DTOs

    /// <summary>
    ///     Stateless facade for corporate-level tax computations.
    /// </summary>
    public interface ITaxCalculationService
    {
        /// <summary>
        ///     Calculates the tax liability for the supplied company snapshot in the given fiscal period.
        /// </summary>
        /// <exception cref="TaxRuleNotFoundException">
        ///     Thrown when no tax rule exists for the company's domicile country.
        /// </exception>
        TaxReport CalculateCorporateTax(CompanySnapshot snapshot, FiscalPeriod period);
    }

    public interface ICountryTaxRuleRepository
    {
        /// <summary>
        ///     Returns the <see cref="CountryTaxRule"/> for the ISO country code, or null if not found.
        ///     This repository is intentionally simple; the infrastructure layer provides
        ///     caching/persistence concerns (SQLite, remote config, etc.).
        /// </summary>
        CountryTaxRule? GetByCountry(string countryCode);
    }

    #endregion

    #region Entities

    public sealed class CompanySnapshot
    {
        public Guid CompanyId { get; }
        public string CountryCode { get; }
        public decimal Revenue { get; }
        public decimal Expense { get; }
        public decimal NetProfit => Revenue - Expense;
        public decimal LossCarryForward { get; }
        public bool IsInSpecialEconomicZone { get; }
        public decimal RAndDSpend { get; }

        public CompanySnapshot(
            Guid companyId,
            string countryCode,
            decimal revenue,
            decimal expense,
            decimal lossCarryForward,
            bool isInSpecialEconomicZone,
            decimal rAndDSpend)
        {
            CompanyId = companyId;
            CountryCode = countryCode ?? throw new ArgumentNullException(nameof(countryCode));
            Revenue = revenue;
            Expense = expense;
            LossCarryForward = lossCarryForward;
            IsInSpecialEconomicZone = isInSpecialEconomicZone;
            RAndDSpend = rAndDSpend;
        }
    }

    public sealed class FiscalPeriod
    {
        public int Year { get; }
        public int Quarter { get; }

        public FiscalPeriod(int year, int quarter)
        {
            if (quarter < 1 || quarter > 4) throw new ArgumentOutOfRangeException(nameof(quarter));
            Year = year;
            Quarter = quarter;
        }

        public override string ToString() => $"FY{Year}-Q{Quarter}";
    }

    public sealed class TaxReport
    {
        public Guid CompanyId { get; }
        public FiscalPeriod Period { get; }
        public decimal TaxableIncome { get; }
        public decimal TaxDue { get; }
        public decimal EffectiveRate { get; }

        public TaxReport(Guid companyId, FiscalPeriod fiscalPeriod, decimal taxableIncome, decimal taxDue, decimal effectiveRate)
        {
            CompanyId = companyId;
            Period = fiscalPeriod;
            TaxableIncome = taxableIncome;
            TaxDue = taxDue;
            EffectiveRate = effectiveRate;
        }
    }

    #endregion

    #region Tax Rule Aggregates

    /// <summary>
    ///     Aggregate root describing taxation parameters for a specific country.
    /// </summary>
    public sealed class CountryTaxRule
    {
        public string CountryCode { get; }
        public IReadOnlyList<TaxBracket> Brackets { get; }
        public decimal? MinimumTax { get; }

        // Incentive program fields
        public decimal? RAndDCreditRate { get; }
        public decimal RAndDMaxCreditAsRevenuePct { get; }
        public decimal SezProfitDeductionRate { get; }

        public CountryTaxRule(
            string countryCode,
            IEnumerable<TaxBracket> brackets,
            decimal? minimumTax,
            decimal? rAndDCreditRate,
            decimal rAndDMaxCreditAsRevenuePct,
            decimal sezProfitDeductionRate)
        {
            CountryCode = countryCode ?? throw new ArgumentNullException(nameof(countryCode));
            Brackets = brackets?.OrderBy(b => b.LowerBound).ToList() ?? throw new ArgumentNullException(nameof(brackets));

            if (!Brackets.Any())
                throw new ArgumentException("At least one tax bracket must be supplied.", nameof(brackets));

            MinimumTax = minimumTax;
            RAndDCreditRate = rAndDCreditRate;
            RAndDMaxCreditAsRevenuePct = rAndDMaxCreditAsRevenuePct;
            SezProfitDeductionRate = sezProfitDeductionRate;
        }
    }

    public sealed class TaxBracket
    {
        public decimal LowerBound { get; }
        public decimal? UpperBound { get; } // null ⇒ infinity
        public decimal Rate { get; }

        public TaxBracket(decimal lowerBound, decimal? upperBound, decimal rate)
        {
            if (lowerBound < 0) throw new ArgumentOutOfRangeException(nameof(lowerBound));
            if (upperBound.HasValue && upperBound <= lowerBound)
                throw new ArgumentException("Upper bound must be greater than lower bound.", nameof(upperBound));
            if (rate < 0 || rate > 1) throw new ArgumentOutOfRangeException(nameof(rate));

            LowerBound = lowerBound;
            UpperBound = upperBound;
            Rate = rate;
        }
    }

    #endregion

    #region Exceptions

    public sealed class TaxRuleNotFoundException : Exception
    {
        public TaxRuleNotFoundException(string message) : base(message) { }
        public TaxRuleNotFoundException(string message, Exception inner) : base(message, inner) { }
    }

    #endregion
}