```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="ICompanyRepository.cs" company="TycoonVerse">
//   Copyright (c) TycoonVerse. 
//   This code is part of TycoonVerse – Enterprise Empire Simulator.
//   All rights reserved.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Linq.Expressions;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Domain.Common;
using TycoonVerse.Domain.Entities;
using TycoonVerse.Domain.ValueObjects;

namespace TycoonVerse.Application.Interfaces.Repositories
{
    /// <summary>
    /// Repository abstraction over the <see cref="Company"/> aggregate root.
    /// Exposes both read-write and read-only contracts for flexible composition in
    /// application use-cases (CQRS-style handlers, background jobs, analytics pipelines, etc.).
    /// </summary>
    public interface ICompanyRepository :
        IRepository<Company, CompanyId>,
        IReadonlyRepository<Company, CompanyId>
    {
        #region Query operations ----------------------------------------------------------------

        /// <summary>
        /// Retrieves a paged list of companies ordered by the specified column.
        /// </summary>
        /// <param name="pageNumber">1-based page number.</param>
        /// <param name="pageSize">The size of each page.</param>
        /// <param name="orderBy">Expression used for ordering.</param>
        /// <param name="sortDirection">Ascending or descending sort.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        Task<PagedResult<Company>> GetPagedAsync(
            int pageNumber,
            int pageSize,
            Expression<Func<Company, object>> orderBy,
            SortDirection sortDirection = SortDirection.Ascending,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Performs a free-text search across company names, tickers, and industry tags.
        /// </summary>
        /// <param name="query">Search phrase.</param>
        /// <param name="maxResults">Max results to return.  Defaults to 25.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        Task<IReadOnlyCollection<Company>> SearchAsync(
            string query,
            int maxResults = 25,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Checks if a company with the given government registration number exists.
        /// </summary>
        Task<bool> ExistsAsync(
            string registrationNumber,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Gets a company from a SEO-friendly slug (unique per company).
        /// </summary>
        Task<Company?> GetBySlugAsync(
            string slug,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Retrieves companies that have not been synced with the backend since the provided timestamp.
        /// Used by the deterministic offline-sync subsystem.
        /// </summary>
        /// <param name="minLastSyncedAt">
        /// Cut-off timestamp.  Companies whose <c>LastSyncedAt</c> is less than this value will be returned.
        /// </param>
        /// <param name="batchSize">Maximum number of records to return.</param>
        Task<IReadOnlyCollection<Company>> GetStaleForSyncAsync(
            DateTimeOffset minLastSyncedAt,
            int batchSize,
            CancellationToken cancellationToken = default);

        #endregion

        #region Domain-specific write helpers ---------------------------------------------------

        /// <summary>
        /// Updates high-frequency financial data points of a company without pulling the full aggregate.
        /// A lightweight method used by real-time simulators and analytics collectors.
        /// </summary>
        /// <param name="id">Company identifier.</param>
        /// <param name="cashOnHand">Latest cash amount.</param>
        /// <param name="metrics">Snapshot of calculated metrics (e.g., EBITDA, Debt/Equity).</param>
        /// <param name="expectedRowVersion">
        /// Concurrency token representing the caller's view of the entity.
        /// The update will be rejected if the current version differs.
        /// </param>
        /// <exception cref="ConcurrencyException">
        /// Thrown when <paramref name="expectedRowVersion"/> does not match the persisted value.
        /// </exception>
        Task UpdateFinancialSnapshotAsync(
            CompanyId id,
            MonetaryValue cashOnHand,
            FinancialMetrics metrics,
            ulong expectedRowVersion,
            CancellationToken cancellationToken = default);

        #endregion
    }

    /// <summary>
    /// Sort direction for repository queries.
    /// </summary>
    public enum SortDirection
    {
        Ascending,
        Descending
    }

    /// <summary>
    /// A generic container for paginated results.
    /// </summary>
    /// <typeparam name="T">Entity type.</typeparam>
    public sealed class PagedResult<T>
    {
        public PagedResult(
            IReadOnlyCollection<T> items,
            int page,
            int pageSize,
            long totalCount)
        {
            Items = items ?? throw new ArgumentNullException(nameof(items));
            Page = page >= 1
                ? page
                : throw new ArgumentOutOfRangeException(nameof(page), "Page number must be >= 1.");

            PageSize = pageSize >= 1
                ? pageSize
                : throw new ArgumentOutOfRangeException(nameof(pageSize), "Page size must be >= 1.");

            TotalCount = totalCount >= 0
                ? totalCount
                : throw new ArgumentOutOfRangeException(nameof(totalCount), "Total count cannot be negative.");
        }

        /// <summary>
        /// Items for the current page.
        /// </summary>
        public IReadOnlyCollection<T> Items { get; }

        /// <summary>
        /// 1-based page index.
        /// </summary>
        public int Page { get; }

        /// <summary>
        /// Number of items requested per page.
        /// </summary>
        public int PageSize { get; }

        /// <summary>
        /// Total count of items across all pages.
        /// </summary>
        public long TotalCount { get; }

        /// <summary>
        /// Total number of pages, computed on demand.
        /// </summary>
        public int TotalPages => (int)Math.Ceiling((double)TotalCount / PageSize);
    }
}
```