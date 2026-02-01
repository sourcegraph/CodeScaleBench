```csharp
// File: TycoonVerse/src/TycoonVerse.Core/DomainServices/FinancialModelService.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Caching.Memory;
using TycoonVerse.Core.Domain;
using TycoonVerse.Core.Domain.Events;
using TycoonVerse.Core.Domain.Repositories;
using TycoonVerse.Core.Domain.ValueObjects;
using TycoonVerse.Core.SharedKernel;
using TycoonVerse.Core.SharedKernel.Results;

namespace TycoonVerse.Core.DomainServices
{
    /// <summary>
    ///     The FinancialModelService is the heart of the simulation engine that
    ///     translates granular, in-game economic events into familiar corporate
    ///     metrics (EBITDA, Cash-Flow, Debt/Equity, etc.).  Consumers include:
    ///     • Player dashboards (read-only, high-frequency)
    ///     • Analytics/telemetry layer (snapshot, low-frequency)
    ///     • AI decision engine (what-if projections)
    ///
    ///     Thread-safety guarantees:
    ///     – All public methods are safe for concurrent invocation across
    ///       multiple companies.  Per-company locks protect write paths.
    /// </summary>
    public sealed class FinancialModelService : IFinancialModelService, IHandle<DomainEvent>
    {
        private readonly IFinancialTransactionRepository _transactionRepository;
        private readonly ICompanyRepository _companyRepository;
        private readonly ITaxStrategyProvider _taxStrategyProvider;
        private readonly IMemoryCache _cache;

        // Per-company locks to guard write operations and point-in-time calculations
        private static readonly ConcurrentDictionary<CompanyId, SemaphoreSlim> _companyLocks =
            new();

        private const int SnapshotCacheSeconds = 5; // small cache window to smooth UI polling

        public FinancialModelService(
            IFinancialTransactionRepository transactionRepository,
            ICompanyRepository companyRepository,
            ITaxStrategyProvider taxStrategyProvider,
            IMemoryCache cache)
        {
            _transactionRepository = transactionRepository ?? throw new ArgumentNullException(nameof(transactionRepository));
            _companyRepository = companyRepository ?? throw new ArgumentNullException(nameof(companyRepository));
            _taxStrategyProvider = taxStrategyProvider ?? throw new ArgumentNullException(nameof(taxStrategyProvider));
            _cache = cache ?? throw new ArgumentNullException(nameof(cache));
        }

        #region IFinancialModelService

        public async Task<Result<FinancialSnapshot>> GetSnapshotAsync(
            CompanyId companyId,
            DateTime asOfUtc,
            CurrencyCode currency,
            CancellationToken ct = default)
        {
            if (companyId == CompanyId.Empty)
                return Result<FinancialSnapshot>.Fail("Invalid company id.");

            var cacheKey = CacheKey.ForSnapshot(companyId, asOfUtc, currency);
            if (_cache.TryGetValue(cacheKey, out FinancialSnapshot cached))
            {
                return Result<FinancialSnapshot>.Ok(cached);
            }

            var companyLock = _companyLocks.GetOrAdd(companyId, _ => new SemaphoreSlim(1, 1));

            await companyLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                // Re-check cache inside lock to avoid stampede
                if (_cache.TryGetValue(cacheKey, out cached))
                {
                    return Result<FinancialSnapshot>.Ok(cached);
                }

                var transactions =
                    await _transactionRepository
                        .GetTransactionsUpToAsync(companyId, asOfUtc, ct)
                        .ConfigureAwait(false);

                var company = await _companyRepository.GetAsync(companyId, ct).ConfigureAwait(false);
                if (company is null)
                    return Result<FinancialSnapshot>.Fail("Company not found.");

                var fxRate = await company.FxProvider.GetRateAsync(currency, ct).ConfigureAwait(false);

                var metrics = CalculateMetrics(transactions, company, fxRate, asOfUtc);

                _cache.Set(
                    cacheKey,
                    metrics,
                    new MemoryCacheEntryOptions
                    {
                        AbsoluteExpirationRelativeToNow = TimeSpan.FromSeconds(SnapshotCacheSeconds)
                    });

                return Result<FinancialSnapshot>.Ok(metrics);
            }
            finally
            {
                companyLock.Release();
            }
        }

        public async Task<Result> RecordTransactionAsync(
            FinancialTransaction transaction,
            CancellationToken ct = default)
        {
            if (transaction is null) return Result.Fail("Transaction cannot be null.");

            var companyLock = _companyLocks.GetOrAdd(transaction.CompanyId, _ => new SemaphoreSlim(1, 1));

            await companyLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                await _transactionRepository.AddAsync(transaction, ct).ConfigureAwait(false);

                // Invalidate cache slices touching this timestamp onward
                ClearSnapshotCache(transaction.CompanyId, transaction.TimestampUtc);
                return Result.Ok();
            }
            finally
            {
                companyLock.Release();
            }
        }

        public async Task<Result<IEnumerable<FinancialSnapshot>>> GenerateSnapshotsAsync(
            CompanyId companyId,
            DateTime fromUtc,
            DateTime toUtc,
            TimeSpan granularity,
            CurrencyCode currency,
            CancellationToken ct = default)
        {
            if (fromUtc > toUtc) return Result<IEnumerable<FinancialSnapshot>>.Fail("Invalid date range.");
            if (granularity <= TimeSpan.Zero) return Result<IEnumerable<FinancialSnapshot>>.Fail("Granularity must be > 0.");

            var snapshots = new List<FinancialSnapshot>();
            var cursor = fromUtc;

            while (cursor <= toUtc)
            {
                var snapResult = await GetSnapshotAsync(companyId, cursor, currency, ct)
                    .ConfigureAwait(false);

                if (!snapResult.Succeeded)
                    return Result<IEnumerable<FinancialSnapshot>>.Fail(snapResult.Error!);

                snapshots.Add(snapResult.Value!);
                cursor = cursor.Add(granularity);
            }

            return Result<IEnumerable<FinancialSnapshot>>.Ok(snapshots);
        }

        #endregion

        #region DomainEvent Handling (Observer Pattern)

        /// <summary>
        ///     Single entry-point for all domain events that may impact the
        ///     company’s financial ledger (purchases, payroll, loans, etc.).
        ///     The events are flattened into FinancialTransaction instances
        ///     stored in the repository.
        /// </summary>
        public async Task HandleAsync(DomainEvent domainEvent, CancellationToken ct = default)
        {
            if (domainEvent is null) return;

            if (!FinancialEventAdapter.TryAdapt(domainEvent, out var transaction))
                return; // Non-financial event – ignore

            await RecordTransactionAsync(transaction!, ct).ConfigureAwait(false);
        }

        #endregion

        #region Private Helpers

        private static FinancialSnapshot CalculateMetrics(
            IReadOnlyCollection<FinancialTransaction> txns,
            Company company,
            decimal fxRate,
            DateTime asOfUtc)
        {
            // Convert all monetary values to the requested currency
            decimal Convert(decimal amount) => amount * fxRate;

            var revenue = Sum(AccountCategory.Revenue);
            var cogs = Sum(AccountCategory.Cogs);
            var opex = Sum(AccountCategory.OperatingExpense);
            var depreciation = Sum(AccountCategory.Depreciation);
            var interest = Sum(AccountCategory.InterestExpense);

            var grossProfit = revenue - cogs;
            var ebitda = grossProfit - opex;
            var ebit = ebitda - depreciation;
            var taxableIncome = ebit - interest;

            var taxStrategy = _taxStrategyProvider.Resolve(company.IncorporationTerritory);
            var taxes = taxStrategy.CalculateTax(taxableIncome);

            var netIncome = taxableIncome - taxes;

            var operatingCashFlow = netIncome + depreciation; // simplified
            var capEx = Sum(AccountCategory.CapEx);
            var financingCashFlow = Sum(AccountCategory.Financing);

            var freeCashFlow = operatingCashFlow - capEx;
            var endingCash = company.InitialCash + Sum(AccountCategory.Cash) + operatingCashFlow - capEx + financingCashFlow;

            var totalDebt = Sum(AccountCategory.Debt);
            var totalEquity = company.PaidInCapital + netIncome; // simplified retained earnings
            var debtToEquity = totalEquity == 0 ? 0m : totalDebt / totalEquity;

            return new FinancialSnapshot(
                company.Id,
                asOfUtc,
                Convert(revenue),
                Convert(cogs),
                Convert(grossProfit),
                Convert(opex),
                Convert(ebitda),
                Convert(depreciation),
                Convert(ebit),
                Convert(interest),
                Convert(taxes),
                Convert(netIncome),
                Convert(operatingCashFlow),
                Convert(capEx),
                Convert(freeCashFlow),
                Convert(endingCash),
                Convert(totalDebt),
                Convert(totalEquity),
                debtToEquity
            );

            decimal Sum(AccountCategory category) =>
                txns
                    .Where(t => t.Category == category)
                    .Sum(t => t.Amount);
        }

        private void ClearSnapshotCache(CompanyId companyId, DateTime fromTimestampUtc)
        {
            foreach (var entry in _cache
                         .Where(kvp => kvp.Key is CacheKey ck &&
                                       ck.CompanyId == companyId &&
                                       ck.AsOfUtc >= fromTimestampUtc)
                         .Select(kvp => kvp.Key)
                         .ToList())
            {
                _cache.Remove(entry);
            }
        }

        #endregion
    }

    #region Data Contracts / Helper Types

    public interface IFinancialModelService
    {
        Task<Result<FinancialSnapshot>> GetSnapshotAsync(
            CompanyId companyId,
            DateTime asOfUtc,
            CurrencyCode currency,
            CancellationToken ct = default);

        Task<Result> RecordTransactionAsync(
            FinancialTransaction transaction,
            CancellationToken ct = default);

        Task<Result<IEnumerable<FinancialSnapshot>>> GenerateSnapshotsAsync(
            CompanyId companyId,
            DateTime fromUtc,
            DateTime toUtc,
            TimeSpan granularity,
            CurrencyCode currency,
            CancellationToken ct = default);
    }

    /// <summary>
    ///     Immutable snapshot of a company’s financial state at a point in time.
    ///     All values are expressed in a single (caller-requested) currency.
    /// </summary>
    public sealed record FinancialSnapshot(
        CompanyId CompanyId,
        DateTime AsOfUtc,
        decimal Revenue,
        decimal Cogs,
        decimal GrossProfit,
        decimal OperatingExpenses,
        decimal Ebitda,
        decimal Depreciation,
        decimal Ebit,
        decimal InterestExpense,
        decimal Taxes,
        decimal NetIncome,
        decimal OperatingCashFlow,
        decimal CapitalExpenditures,
        decimal FreeCashFlow,
        decimal EndingCash,
        decimal TotalDebt,
        decimal TotalEquity,
        decimal DebtToEquity);

    internal sealed record CacheKey(
        CompanyId CompanyId,
        DateTime AsOfUtc,
        CurrencyCode Currency)
    {
        public static CacheKey ForSnapshot(CompanyId id, DateTime asOfUtc, CurrencyCode currency) =>
            new(id, asOfUtc, currency);
    }

    #endregion
}
```