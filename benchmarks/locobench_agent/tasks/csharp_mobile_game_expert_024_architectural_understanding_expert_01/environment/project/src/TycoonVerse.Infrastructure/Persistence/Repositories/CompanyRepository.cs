```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Linq.Expressions;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;
using TycoonVerse.Domain.Companies;
using TycoonVerse.Domain.Repositories;
using TycoonVerse.Infrastructure.Persistence.Context;

namespace TycoonVerse.Infrastructure.Persistence.Repositories
{
    /// <summary>
    /// Concrete implementation of <see cref="ICompanyRepository"/> which persists <see cref="Company"/> aggregates
    /// using Entity-Framework-Core against a local SQLite database. An in-memory cache is leveraged to minimize
    /// expensive disk reads while still guaranteeing repeatable operations for deterministic offline play.
    /// </summary>
    public sealed class CompanyRepository : ICompanyRepository, IDisposable
    {
        // ReSharper disable once InconsistentNaming
        private const string CacheKeyPrefix = "company/";
        
        private readonly TycoonDbContext _dbContext;
        private readonly IMemoryCache _cache;
        private readonly ILogger<CompanyRepository> _logger;
        private readonly SemaphoreSlim _lock = new(initialCount: 1, maxCount: 1);

        private bool _disposed;

        public CompanyRepository(
            TycoonDbContext dbContext,
            IMemoryCache cache,
            ILogger<CompanyRepository> logger)
        {
            _dbContext = dbContext ?? throw new ArgumentNullException(nameof(dbContext));
            _cache     = cache     ?? throw new ArgumentNullException(nameof(cache));
            _logger    = logger    ?? throw new ArgumentNullException(nameof(logger));
        }

        #region Query

        public async Task<Company?> GetByIdAsync(
            Guid companyId,
            bool useCache            = true,
            CancellationToken token  = default)
        {
            string cacheKey = CacheKeyPrefix + companyId;

            if (useCache && _cache.TryGetValue(cacheKey, out Company cachedCompany))
            {
                _logger.LogTrace("Cache hit for Company {CompanyId}", companyId);
                return cachedCompany;
            }

            _logger.LogTrace("Cache miss for Company {CompanyId}", companyId);
            var entity = await _dbContext.Companies
                                         .AsNoTracking()
                                         .FirstOrDefaultAsync(c => c.Id == companyId, token);

            if (entity != null && useCache)
            {
                _cache.Set(cacheKey, entity, TimeSpan.FromMinutes(30));
            }

            return entity;
        }

        public async Task<IReadOnlyCollection<Company>> ListAsync(
            CancellationToken token = default)
        {
            _logger.LogTrace("Listing all companies from storage.");
            return await _dbContext.Companies
                                   .AsNoTracking()
                                   .ToListAsync(token);
        }

        public async Task<IReadOnlyCollection<Company>> FindAsync(
            Expression<Func<Company, bool>> predicate,
            CancellationToken token = default)
        {
            _logger.LogTrace("Running custom company query: {Query}", predicate);
            return await _dbContext.Companies
                                   .AsNoTracking()
                                   .Where(predicate)
                                   .ToListAsync(token);
        }

        #endregion

        #region Command

        public async Task AddAsync(
            Company company,
            CancellationToken token = default)
        {
            ArgumentNullException.ThrowIfNull(company);

            await _lock.WaitAsync(token);
            try
            {
                _logger.LogInformation("Adding new Company {CompanyName} ({CompanyId})", company.Name, company.Id);
                await _dbContext.Companies.AddAsync(company, token);
                await SaveChangesInternalAsync(token);

                CacheEntity(company);
            }
            finally
            {
                _lock.Release();
            }
        }

        public async Task UpdateAsync(
            Company company,
            CancellationToken token = default)
        {
            ArgumentNullException.ThrowIfNull(company);

            await _lock.WaitAsync(token);
            try
            {
                _logger.LogInformation("Updating Company {CompanyName} ({CompanyId})", company.Name, company.Id);
                _dbContext.Companies.Update(company);
                await SaveChangesInternalAsync(token);

                CacheEntity(company);
            }
            finally
            {
                _lock.Release();
            }
        }

        public async Task DeleteAsync(
            Guid companyId,
            CancellationToken token = default)
        {
            await _lock.WaitAsync(token);
            try
            {
                _logger.LogInformation("Deleting Company ({CompanyId})", companyId);
                var entity = await _dbContext.Companies.FirstOrDefaultAsync(c => c.Id == companyId, token);

                if (entity == null)
                {
                    _logger.LogWarning("Attempted to delete Company ({CompanyId}) which does not exist.", companyId);
                    return;
                }

                _dbContext.Companies.Remove(entity);
                await SaveChangesInternalAsync(token);

                _cache.Remove(CacheKeyPrefix + companyId);
            }
            finally
            {
                _lock.Release();
            }
        }

        /// <summary>
        /// Marks a company as successfully synchronized with the backend service once connectivity returns. 
        /// Clears the <see cref="Company.IsDirty"/> flag and updates <see cref="Company.LastSyncedUtc"/>.
        /// </summary>
        public async Task MarkSyncedAsync(
            Guid companyId,
            DateTime utcSyncTime,
            CancellationToken token = default)
        {
            await _lock.WaitAsync(token);
            try
            {
                var company = await _dbContext.Companies.FirstOrDefaultAsync(c => c.Id == companyId, token);
                if (company == null) return;

                company.IsDirty       = false;
                company.LastSyncedUtc = utcSyncTime;
                _dbContext.Companies.Update(company);

                _logger.LogInformation("Company {CompanyId} marked as synced at {UtcSyncTime}", companyId, utcSyncTime);

                await SaveChangesInternalAsync(token);
                CacheEntity(company);
            }
            finally
            {
                _lock.Release();
            }
        }

        #endregion

        #region Private Helpers

        private void CacheEntity(Company company)
        {
            string cacheKey = CacheKeyPrefix + company.Id;
            _cache.Set(cacheKey, company, TimeSpan.FromMinutes(30));
        }

        private async Task SaveChangesInternalAsync(CancellationToken token)
        {
            try
            {
                await _dbContext.SaveChangesAsync(token);
            }
            catch (DbUpdateConcurrencyException ex)
            {
                _logger.LogError(ex, "Concurrency conflict detected while persisting Company aggregate.");
                throw;
            }
            catch (DbUpdateException ex)
            {
                _logger.LogError(ex, "Storage update failed.");
                throw;
            }
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;
            _dbContext.Dispose();
            _lock.Dispose();
            _disposed = true;
            GC.SuppressFinalize(this);
        }

        #endregion
    }
}
```