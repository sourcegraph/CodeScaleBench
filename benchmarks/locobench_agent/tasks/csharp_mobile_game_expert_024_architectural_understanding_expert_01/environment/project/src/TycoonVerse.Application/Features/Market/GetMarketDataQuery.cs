```csharp
// File: TycoonVerse/src/TycoonVerse.Application/Features/Market/GetMarketDataQuery.cs

using System;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Globalization;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using MediatR;
using Microsoft.Extensions.Logging;
using TycoonVerse.Application.Abstractions.Cache;
using TycoonVerse.Application.Abstractions.Repositories;
using TycoonVerse.Domain.Market;
using TycoonVerse.Domain.SharedKernel.Primitives;

namespace TycoonVerse.Application.Features.Market
{
    /// <summary>
    /// Query object – request a snapshot of market data for a specific region and point-in-time.
    /// </summary>
    public sealed class GetMarketDataQuery : IRequest<Result<MarketSnapshotDto>>
    {
        public GetMarketDataQuery(
            string regionCode,
            IEnumerable<Guid> companyIds,
            DateTime asOfUtc)
        {
            RegionCode  = string.IsNullOrWhiteSpace(regionCode) 
                ? throw new ArgumentException("Region code cannot be null or whitespace.", nameof(regionCode)) 
                : regionCode.ToUpperInvariant();

            CompanyIds  = companyIds?.ToImmutableHashSet() 
                ?? throw new ArgumentNullException(nameof(companyIds));

            if (!CompanyIds.Any())
                throw new ArgumentException("At least one company id must be supplied.", nameof(companyIds));

            AsOfUtc = DateTime.SpecifyKind(asOfUtc, DateTimeKind.Utc);
        }

        /// <summary>The ISO-3166 region code (e.g. “US”, “FR”).</summary>
        public string RegionCode { get; }

        /// <summary>List of companies for which to enrich the market data.</summary>
        public IReadOnlyCollection<Guid> CompanyIds { get; }

        /// <summary>Point-in-time (UTC) for which the snapshot should be generated.</summary>
        public DateTime AsOfUtc { get; }
    }

    /// <summary>
    /// Handles the GetMarketDataQuery request.
    /// </summary>
    internal sealed class GetMarketDataQueryHandler 
        : IRequestHandler<GetMarketDataQuery, Result<MarketSnapshotDto>>
    {
        private const int CacheTtlMinutes = 5;

        private readonly IMarketRepository            _marketRepository;
        private readonly ICompanyRepository           _companyRepository;
        private readonly ICache                       _cache;
        private readonly ILogger<GetMarketDataQueryHandler> _logger;

        public GetMarketDataQueryHandler(
            IMarketRepository                    marketRepository,
            ICompanyRepository                   companyRepository,
            ICache                               cache,
            ILogger<GetMarketDataQueryHandler>   logger)
        {
            _marketRepository  = marketRepository  ?? throw new ArgumentNullException(nameof(marketRepository));
            _companyRepository = companyRepository ?? throw new ArgumentNullException(nameof(companyRepository));
            _cache             = cache             ?? throw new ArgumentNullException(nameof(cache));
            _logger            = logger            ?? throw new ArgumentNullException(nameof(logger));
        }

        public async Task<Result<MarketSnapshotDto>> Handle(
            GetMarketDataQuery query, 
            CancellationToken  cancellationToken)
        {
            string cacheKey = BuildCacheKey(query);

            try
            {
                // 1. Fast-path: return snapshot from cache if available.
                if (_cache.TryGetValue<MarketSnapshotDto>(cacheKey, out var cachedSnapshot))
                    return Result.Success(cachedSnapshot);

                // 2. Retrieve raw market data.
                var commodityPricesTask = _marketRepository
                    .GetCommodityPricesAsync(query.RegionCode, query.AsOfUtc, cancellationToken);

                var fxRatesTask = _marketRepository
                    .GetExchangeRatesAsync(query.AsOfUtc, cancellationToken);

                var companyInfoTask = _companyRepository
                    .GetMarketInfoAsync(query.CompanyIds, query.AsOfUtc, cancellationToken);

                await Task.WhenAll(commodityPricesTask, fxRatesTask, companyInfoTask)
                          .ConfigureAwait(false);

                var snapshot = new MarketSnapshotDto(
                    regionCode:  query.RegionCode,
                    asOfUtc:     query.AsOfUtc,
                    commodities: commodityPricesTask.Result
                                 .Select(CommodityPriceDto.FromDomain)
                                 .ToImmutableArray(),
                    exchangeRates: fxRatesTask.Result
                                   .Select(ExchangeRateDto.FromDomain)
                                   .ToImmutableArray(),
                    companies: companyInfoTask.Result
                               .ToDictionary(kv => kv.Key, kv => CompanyMarketInfoDto.FromDomain(kv.Value))
                               .ToImmutableDictionary());

                // 3. Cache the freshly built snapshot for subsequent queries.
                _cache.Set(cacheKey, snapshot, TimeSpan.FromMinutes(CacheTtlMinutes));

                return Result.Success(snapshot);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                _logger.LogWarning("Market data query was cancelled by caller.");
                return Result.Failure<MarketSnapshotDto>("Request was cancelled.");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to build market snapshot for {RegionCode} @ {AsOf}",
                    query.RegionCode, query.AsOfUtc.ToString("o", CultureInfo.InvariantCulture));

                return Result.Failure<MarketSnapshotDto>("Unable to retrieve market data. Please try again later.");
            }
        }

        private static string BuildCacheKey(GetMarketDataQuery q) =>
            $"MarketSnapshot::{q.RegionCode}::{q.AsOfUtc:yyyyMMddHHmmss}::[{string.Join(',', q.CompanyIds.OrderBy(id => id))}]";
    }

    #region DTOs

    /// <summary>
    /// Lightweight DTO that aggregates all market information required by front-end layers.
    /// </summary>
    public sealed record MarketSnapshotDto(
        string RegionCode,
        DateTime AsOfUtc,
        IReadOnlyList<CommodityPriceDto>   Commodities,
        IReadOnlyList<ExchangeRateDto>     ExchangeRates,
        IReadOnlyDictionary<Guid, CompanyMarketInfoDto> Companies);

    public sealed record CommodityPriceDto(
        string CommodityCode,
        decimal UnitPrice,
        string Currency)
    {
        public static CommodityPriceDto FromDomain(CommodityPrice domain) =>
            new(domain.CommodityCode,
                domain.UnitPrice.Amount,
                domain.UnitPrice.Currency);
    }

    public sealed record ExchangeRateDto(
        string BaseCurrency,
        string QuoteCurrency,
        decimal Rate)
    {
        public static ExchangeRateDto FromDomain(ExchangeRate domain) =>
            new(domain.BaseCurrency,
                domain.QuoteCurrency,
                domain.Rate);
    }

    public sealed record CompanyMarketInfoDto(
        Guid CompanyId,
        decimal OutstandingShares,
        decimal MarketCapitalisation,
        string BaseCurrency)
    {
        public static CompanyMarketInfoDto FromDomain(CompanyMarketInfo domain) =>
            new(domain.CompanyId,
                domain.OutstandingShares,
                domain.MarketCapitalisation.Amount,
                domain.MarketCapitalisation.Currency);
    }

    #endregion
}
```