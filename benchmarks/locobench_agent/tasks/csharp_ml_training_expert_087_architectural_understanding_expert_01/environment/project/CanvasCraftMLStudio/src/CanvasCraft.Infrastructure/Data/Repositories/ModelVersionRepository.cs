```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Domain.Exceptions;
using CanvasCraft.Domain.Models.Registry;
using CanvasCraft.Domain.Repositories;
using CanvasCraft.Infrastructure.Data.Context;
using CanvasCraft.Infrastructure.Data.Specifications;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Infrastructure.Data.Repositories
{
    /// <summary>
    /// Provides CRUD + query semantics over ModelVersion aggregates while 
    /// transparently handling optimistic-concurrency, second-level caching, and
    /// EF-Core change tracking quirks.  All write-ops are executed inside a
    /// <c>IDbContextTransaction</c> boundary supplied by the DbContext itself.
    /// </summary>
    public class ModelVersionRepository : IModelVersionRepository
    {
        private readonly CanvasCraftDbContext _db;
        private readonly ILogger<ModelVersionRepository> _logger;
        private readonly IMemoryCache _cache;

        // Cache keys template
        private static string CacheKey(Guid id) => $"model-version:{id:n}";
        private const string LatestVersionCacheKeyTmpl = "model-latest-{0:n}";

        public ModelVersionRepository(
            CanvasCraftDbContext db,
            IMemoryCache cache,
            ILogger<ModelVersionRepository> logger)
        {
            _db      = db     ?? throw new ArgumentNullException(nameof(db));
            _cache   = cache  ?? throw new ArgumentNullException(nameof(cache));
            _logger  = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        #region IModelVersionRepository

        public async Task<ModelVersion> GetAsync(Guid id, CancellationToken ct = default)
        {
            if (_cache.TryGetValue(CacheKey(id), out ModelVersion cached))
            {
                _logger.LogTrace("Cache hit for ModelVersion {VersionId}", id);
                return cached;
            }

            ModelVersion? version = await _db.ModelVersions
                .Include(v => v.Metadata)
                .FirstOrDefaultAsync(v => v.Id == id, ct);

            if (version is null)
            {
                throw new EntityNotFoundException(nameof(ModelVersion), id);
            }

            _cache.Set(CacheKey(id), version, TimeSpan.FromMinutes(10));
            return version;
        }

        public async Task<ModelVersion> GetLatestAsync(Guid modelId, CancellationToken ct = default)
        {
            string cacheKey = string.Format(LatestVersionCacheKeyTmpl, modelId);

            if (_cache.TryGetValue(cacheKey, out ModelVersion cached))
            {
                _logger.LogTrace("Cache hit for ModelVersion(latest) {ModelId}", modelId);
                return cached;
            }

            ModelVersion? latest = await _db.ModelVersions
                .Where(v => v.ModelId == modelId)
                .OrderByDescending(v => v.SemanticVersion) // SemanticVersion is Comparable struct
                .FirstOrDefaultAsync(ct);

            if (latest is null)
            {
                throw new EntityNotFoundException(
                    $"No versions found for model {modelId:n}");
            }

            _cache.Set(cacheKey, latest, TimeSpan.FromMinutes(5));
            return latest;
        }

        public async Task<IReadOnlyList<ModelVersion>> GetPagedAsync(
            Guid modelId,
            int page,
            int pageSize,
            CancellationToken ct = default)
        {
            if (page <= 0)  throw new ArgumentOutOfRangeException(nameof(page));
            if (pageSize <= 0) throw new ArgumentOutOfRangeException(nameof(pageSize));

            return await _db.ModelVersions
                .Where(v => v.ModelId == modelId)
                .OrderByDescending(v => v.CreatedUtc)
                .Skip((page - 1) * pageSize)
                .Take(pageSize)
                .AsNoTracking()
                .ToListAsync(ct);
        }

        public async Task AddAsync(ModelVersion entity, CancellationToken ct = default)
        {
            ArgumentNullException.ThrowIfNull(entity);

            _logger.LogDebug("Adding ModelVersion {VersionId}", entity.Id);
            await using var tx = await _db.Database.BeginTransactionAsync(ct);

            try
            {
                await _db.ModelVersions.AddAsync(entity, ct);
                await _db.SaveChangesAsync(ct);

                await tx.CommitAsync(ct);

                _cache.Set(CacheKey(entity.Id), entity, TimeSpan.FromMinutes(10));
                _cache.Remove(string.Format(LatestVersionCacheKeyTmpl, entity.ModelId));
            }
            catch (DbUpdateException dbEx)
            {
                await tx.RollbackAsync(ct);
                _logger.LogError(dbEx, "Failed to add ModelVersion {VersionId}", entity.Id);

                throw new DataAccessException("Failed to add model version", dbEx);
            }
        }

        public async Task UpdateAsync(ModelVersion entity, CancellationToken ct = default)
        {
            ArgumentNullException.ThrowIfNull(entity);

            _logger.LogDebug("Updating ModelVersion {VersionId}", entity.Id);
            await using var tx = await _db.Database.BeginTransactionAsync(ct);

            try
            {
                _db.ModelVersions.Update(entity);
                await _db.SaveChangesAsync(ct);

                await tx.CommitAsync(ct);

                // Bust cache
                _cache.Set(CacheKey(entity.Id), entity, TimeSpan.FromMinutes(10));
                _cache.Remove(string.Format(LatestVersionCacheKeyTmpl, entity.ModelId));
            }
            catch (DbUpdateConcurrencyException cx)
            {
                await tx.RollbackAsync(ct);
                _logger.LogWarning(cx,
                    "Concurrency conflict when updating ModelVersion {VersionId}", entity.Id);

                throw new ConcurrencyConflictException(
                    $"ModelVersion {entity.Id} has been modified by someone else", cx);
            }
            catch (DbUpdateException dbEx)
            {
                await tx.RollbackAsync(ct);
                _logger.LogError(dbEx, "Failed to update ModelVersion {VersionId}", entity.Id);

                throw new DataAccessException("Failed to update model version", dbEx);
            }
        }

        public async Task DeleteAsync(Guid id, byte[] rowVersion, CancellationToken ct = default)
        {
            _logger.LogDebug("Deleting ModelVersion {VersionId}", id);

            await using var tx = await _db.Database.BeginTransactionAsync(ct);
            try
            {
                // Build stub with concurrency token to prevent round trip
                var stub = new ModelVersion { Id = id, RowVersion = rowVersion };
                _db.Entry(stub).State = EntityState.Deleted;

                await _db.SaveChangesAsync(ct);
                await tx.CommitAsync(ct);

                _cache.Remove(CacheKey(id));
                // Could also bust latest cache but needs modelId; skip.

            }
            catch (DbUpdateConcurrencyException)
            {
                await tx.RollbackAsync(ct);
                throw new ConcurrencyConflictException(
                    $"ModelVersion {id} already deleted or modified.");
            }
            catch (DbUpdateException dbEx)
            {
                await tx.RollbackAsync(ct);
                _logger.LogError(dbEx, "Failed to delete ModelVersion {VersionId}", id);
                throw new DataAccessException("Failed to delete model version", dbEx);
            }
        }

        public async Task<bool> ExistsAsync(Guid id, CancellationToken ct = default)
        {
            return await _db.ModelVersions
                .AsNoTracking()
                .AnyAsync(v => v.Id == id, ct);
        }

        public async Task<int> CountForModelAsync(Guid modelId, CancellationToken ct = default)
        {
            return await _db.ModelVersions
                .AsNoTracking()
                .CountAsync(v => v.ModelId == modelId, ct);
        }

        #endregion

        #region IDisposable

        // DbContext lifetime is managed externally (DI container). 
        // No unmanaged resources to dispose.

        #endregion
    }
}
```