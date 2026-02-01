```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Linq.Expressions;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Domain.Entities;
using CanvasCraft.Domain.Repositories;
using CanvasCraft.Domain.ValueObjects;
using CanvasCraft.Infrastructure.Data.Context;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Infrastructure.Data.Repositories
{
    /// <summary>
    /// Repository implementation responsible for persisting <see cref="Experiment"/> aggregates.
    /// Combines EF Core for data-access, the Repository pattern for testability, and a small in-memory
    /// cache layer for low-latency reads of hot experiments.
    /// </summary>
    internal sealed class ExperimentRepository : IExperimentRepository
    {
        private static readonly TimeSpan CacheSlidingExpiration = TimeSpan.FromMinutes(3);

        private readonly CanvasCraftDbContext _dbContext;
        private readonly ILogger<ExperimentRepository> _logger;
        private readonly IMemoryCache _memoryCache;

        public ExperimentRepository(
            CanvasCraftDbContext dbContext,
            IMemoryCache memoryCache,
            ILogger<ExperimentRepository> logger)
        {
            _dbContext = dbContext ?? throw new ArgumentNullException(nameof(dbContext));
            _memoryCache = memoryCache ?? throw new ArgumentNullException(nameof(memoryCache));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        #region IExperimentRepository

        /// <inheritdoc />
        public async Task<Experiment?> GetAsync(
            Guid experimentId,
            bool includeArtifacts = false,
            CancellationToken cancellationToken = default)
        {
            if (experimentId == Guid.Empty) throw new ArgumentException("Experiment id cannot be empty.", nameof(experimentId));

            string cacheKey = GetCacheKey(experimentId, includeArtifacts);
            if (_memoryCache.TryGetValue(cacheKey, out Experiment cached))
            {
                return cached;
            }

            IQueryable<Experiment> query = _dbContext.Experiments.AsNoTracking();

            if (includeArtifacts)
            {
                query = query
                    .Include(e => e.Checkpoints)
                    .Include(e => e.Metrics)
                    .Include(e => e.Parameters);
            }

            Experiment? experiment = await query
                .FirstOrDefaultAsync(e => e.Id == experimentId, cancellationToken)
                .ConfigureAwait(false);

            if (experiment != null)
            {
                _memoryCache.Set(cacheKey, experiment,
                    new MemoryCacheEntryOptions
                    {
                        SlidingExpiration = CacheSlidingExpiration,
                        Size = 1 // Keeps memory under control via size-based eviction
                    });
            }

            return experiment;
        }

        /// <inheritdoc />
        public async Task<IReadOnlyList<Experiment>> ListAsync(
            ExperimentQueryOptions options,
            CancellationToken cancellationToken = default)
        {
            options ??= ExperimentQueryOptions.Default;

            IQueryable<Experiment> query = _dbContext.Experiments.AsNoTracking();

            // Filtering
            if (options.Status.HasValue)
                query = query.Where(e => e.Status == options.Status);

            if (!string.IsNullOrWhiteSpace(options.SearchTerm))
                query = query.Where(e =>
                    EF.Functions.ILike(e.Name, $"%{options.SearchTerm}%") ||
                    EF.Functions.ILike(e.Description, $"%{options.SearchTerm}%"));

            // Time range
            if (options.SinceUtc.HasValue)
                query = query.Where(e => e.CreatedUtc >= options.SinceUtc);

            // Ordering
            query = options.Sort switch
            {
                ExperimentSort.CreatedAsc => query.OrderBy(e => e.CreatedUtc),
                ExperimentSort.UpdatedAsc => query.OrderBy(e => e.LastModifiedUtc),
                ExperimentSort.UpdatedDesc => query.OrderByDescending(e => e.LastModifiedUtc),
                _ => query.OrderByDescending(e => e.CreatedUtc)
            };

            // Pagination
            query = query.Skip(options.Offset).Take(options.Limit);

            return await query.ToListAsync(cancellationToken).ConfigureAwait(false);
        }

        /// <inheritdoc />
        public async Task AddAsync(Experiment experiment, CancellationToken cancellationToken = default)
        {
            ValidateExperiment(experiment);

            await _dbContext.Experiments.AddAsync(experiment, cancellationToken).ConfigureAwait(false);
            await PersistAsync(cancellationToken).ConfigureAwait(false);

            // Cache the fresh experiment so subsequent reads are blazing fast
            _memoryCache.Set(GetCacheKey(experiment.Id, includeArtifacts: false),
                experiment,
                new MemoryCacheEntryOptions
                {
                    SlidingExpiration = CacheSlidingExpiration,
                    Size = 1
                });

            _logger.LogInformation("Experiment {ExperimentId} added.", experiment.Id);
        }

        /// <inheritdoc />
        public async Task UpdateAsync(Experiment experiment, CancellationToken cancellationToken = default)
        {
            ValidateExperiment(experiment);

            _dbContext.Experiments.Update(experiment);
            await PersistAsync(cancellationToken).ConfigureAwait(false);

            // Invalidate (not update) cache to avoid stale artifacts for consumers
            _memoryCache.Remove(GetCacheKey(experiment.Id, includeArtifacts: false));
            _memoryCache.Remove(GetCacheKey(experiment.Id, includeArtifacts: true));

            _logger.LogInformation("Experiment {ExperimentId} updated.", experiment.Id);
        }

        /// <inheritdoc />
        public async Task DeleteAsync(Guid experimentId, CancellationToken cancellationToken = default)
        {
            Experiment? entity = await _dbContext.Experiments
                .FirstOrDefaultAsync(e => e.Id == experimentId, cancellationToken)
                .ConfigureAwait(false);

            if (entity is null)
            {
                _logger.LogWarning("Attempt to delete non-existing experiment {ExperimentId}.", experimentId);
                return;
            }

            _dbContext.Experiments.Remove(entity);
            await PersistAsync(cancellationToken).ConfigureAwait(false);

            _memoryCache.Remove(GetCacheKey(experimentId, includeArtifacts: false));
            _memoryCache.Remove(GetCacheKey(experimentId, includeArtifacts: true));

            _logger.LogInformation("Experiment {ExperimentId} deleted.", experimentId);
        }

        /// <inheritdoc />
        public Task<bool> ExistsAsync(Guid experimentId, CancellationToken cancellationToken = default)
        {
            if (experimentId == Guid.Empty) throw new ArgumentException("Experiment id cannot be empty.", nameof(experimentId));

            return _dbContext.Experiments.AnyAsync(e => e.Id == experimentId, cancellationToken);
        }

        #endregion

        #region Private Helpers

        private static string GetCacheKey(Guid experimentId, bool includeArtifacts) =>
            $"{nameof(ExperimentRepository)}_exp_{experimentId:N}_{includeArtifacts}";

        private static void ValidateExperiment(Experiment experiment)
        {
            if (experiment is null) throw new ArgumentNullException(nameof(experiment));
            if (experiment.Id == Guid.Empty) throw new InvalidOperationException("Experiment id must be assigned.");
        }

        /// <summary>
        /// Centralized persistence routine that handles optimistic concurrency exceptions and logs them.
        /// </summary>
        private async Task PersistAsync(CancellationToken cancellationToken)
        {
            try
            {
                await _dbContext.SaveChangesAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (DbUpdateConcurrencyException ex)
            {
                _logger.LogError(ex,
                    "Concurrency exception when saving changes to Experiment repository. {Message}",
                    ex.Message);
                throw new RepositoryConcurrencyException("A concurrency conflict occurred while saving Experiment data.", ex);
            }
            catch (DbUpdateException ex)
            {
                _logger.LogError(ex,
                    "DB update exception when saving changes to Experiment repository. {Message}",
                    ex.Message);
                throw new RepositoryPersistenceException("Unable to persist Experiment data.", ex);
            }
        }

        #endregion
    }

    #region Supporting Types

    /// <summary>
    /// Query options DTO for <see cref="IExperimentRepository.ListAsync"/>.
    /// </summary>
    public sealed class ExperimentQueryOptions
    {
        public static ExperimentQueryOptions Default => new();

        public ExperimentStatus? Status { get; init; }
        public string? SearchTerm { get; init; }
        public DateTimeOffset? SinceUtc { get; init; }
        public ExperimentSort Sort { get; init; } = ExperimentSort.CreatedDesc;

        public int Offset { get; init; } = 0;

        private int _limit = 50;

        /// <summary>
        /// Page size. Capped between 1 and 250.
        /// </summary>
        public int Limit
        {
            get => _limit;
            init => _limit = Math.Clamp(value, 1, 250);
        }
    }

    /// <summary>
    /// Sort options for querying experiments.
    /// </summary>
    public enum ExperimentSort
    {
        CreatedDesc,
        CreatedAsc,
        UpdatedDesc,
        UpdatedAsc
    }

    #endregion
}
```