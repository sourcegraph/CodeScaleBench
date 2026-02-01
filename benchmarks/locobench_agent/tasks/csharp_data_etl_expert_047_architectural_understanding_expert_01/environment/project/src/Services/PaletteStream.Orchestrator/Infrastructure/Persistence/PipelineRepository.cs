using System;
using System.Collections.Generic;
using System.Linq;
using System.Linq.Expressions;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using PaletteStream.Orchestrator.Domain.Models;
using PaletteStream.Orchestrator.Domain.Repositories;
using PaletteStream.Orchestrator.Infrastructure.Persistence.Contexts;

namespace PaletteStream.Orchestrator.Infrastructure.Persistence
{
    /// <summary>
    /// Concrete EF Core implementation of <see cref="IPipelineRepository"/>.
    /// Responsible for CRUD operations on <see cref="PipelineDefinition"/> entities.
    /// </summary>
    public sealed class PipelineRepository : IPipelineRepository
    {
        private readonly OrchestratorDbContext _dbContext;
        private readonly ILogger<PipelineRepository> _logger;

        public PipelineRepository(OrchestratorDbContext dbContext, ILogger<PipelineRepository> logger)
        {
            _dbContext = dbContext ?? throw new ArgumentNullException(nameof(dbContext));
            _logger    = logger    ?? throw new ArgumentNullException(nameof(logger));
        }

        #region Query operations

        /// <inheritdoc/>
        public async Task<PipelineDefinition?> GetByIdAsync(
            Guid pipelineId,
            CancellationToken cancellationToken = default)
        {
            _logger.LogTrace("Retrieving pipeline definition with id {PipelineId}", pipelineId);

            return await _dbContext
                .PipelineDefinitions
                .AsNoTracking()
                .FirstOrDefaultAsync(p => p.Id == pipelineId, cancellationToken)
                .ConfigureAwait(false);
        }

        /// <inheritdoc/>
        public async Task<IReadOnlyList<PipelineDefinition>> GetAllAsync(
            Expression<Func<PipelineDefinition, bool>>? predicate = null,
            CancellationToken cancellationToken = default)
        {
            _logger.LogTrace("Retrieving all pipeline definitions. Predicate supplied: {HasPredicate}", predicate != null);

            IQueryable<PipelineDefinition> queryable = _dbContext
                .PipelineDefinitions
                .AsNoTracking();

            if (predicate is not null)
            {
                queryable = queryable.Where(predicate);
            }

            return await queryable
                .OrderByDescending(p => p.UpdatedAtUtc)
                .ToListAsync(cancellationToken)
                .ConfigureAwait(false);
        }

        /// <inheritdoc/>
        public async Task<bool> ExistsAsync(
            Guid pipelineId,
            CancellationToken cancellationToken = default)
        {
            return await _dbContext
                .PipelineDefinitions
                .AsNoTracking()
                .AnyAsync(p => p.Id == pipelineId, cancellationToken)
                .ConfigureAwait(false);
        }

        #endregion

        #region Mutation operations

        /// <inheritdoc/>
        public async Task AddAsync(
            PipelineDefinition pipelineDefinition,
            CancellationToken cancellationToken = default)
        {
            ArgumentNullException.ThrowIfNull(pipelineDefinition);

            _logger.LogInformation("Adding pipeline definition {PipelineName} ({PipelineId})",
                pipelineDefinition.Name, pipelineDefinition.Id);

            await _dbContext
                .PipelineDefinitions
                .AddAsync(pipelineDefinition, cancellationToken)
                .ConfigureAwait(false);
        }

        /// <inheritdoc/>
        public void Update(PipelineDefinition pipelineDefinition)
        {
            ArgumentNullException.ThrowIfNull(pipelineDefinition);

            _logger.LogInformation("Updating pipeline definition {PipelineName} ({PipelineId})",
                pipelineDefinition.Name, pipelineDefinition.Id);

            _dbContext.PipelineDefinitions.Update(pipelineDefinition);
        }

        /// <inheritdoc/>
        public void Remove(PipelineDefinition pipelineDefinition)
        {
            ArgumentNullException.ThrowIfNull(pipelineDefinition);

            _logger.LogWarning("Removing pipeline definition {PipelineName} ({PipelineId})",
                pipelineDefinition.Name, pipelineDefinition.Id);

            _dbContext.PipelineDefinitions.Remove(pipelineDefinition);
        }

        /// <inheritdoc/>
        public async Task<int> SaveChangesAsync(
            CancellationToken cancellationToken = default)
        {
            try
            {
                int affected = await _dbContext.SaveChangesAsync(cancellationToken).ConfigureAwait(false);

                _logger.LogDebug("{AffectedRows} row(s) persisted for PipelineDefinition entity set.", affected);

                return affected;
            }
            catch (DbUpdateConcurrencyException ex)
            {
                _logger.LogError(ex,
                    "A concurrency violation occurred while saving pipeline definitions. Exception message: {Message}",
                    ex.Message);

                // Re-throw so higher layers can perform compensating action.
                throw;
            }
            catch (DbUpdateException ex)
            {
                _logger.LogError(ex,
                    "A database update error occurred while saving pipeline definitions. Exception message: {Message}",
                    ex.Message);

                throw;
            }
        }

        #endregion
    }
}

/* -------------------------------------------------------------------------------------------------
 * Supporting infrastructure interfaces and entities (for compilation in isolation only).
 * In the real production codebase these live in their own files / projects under Domain layer.
 * ------------------------------------------------------------------------------------------------- */
namespace PaletteStream.Orchestrator.Domain.Models
{
    /// <summary>
    /// Aggregate root that represents a persisted ETL pipeline.
    /// </summary>
    public sealed class PipelineDefinition
    {
        public Guid     Id             { get; set; } = Guid.NewGuid();
        public string   Name           { get; set; } = string.Empty;
        public string   Version        { get; set; } = "1.0";
        public string   JsonDefinition { get; set; } = "{}";
        public string   Status         { get; set; } = "Draft";
        public DateTime CreatedAtUtc   { get; set; } = DateTime.UtcNow;
        public DateTime UpdatedAtUtc   { get; set; } = DateTime.UtcNow;
    }
}

namespace PaletteStream.Orchestrator.Domain.Repositories
{
    using PaletteStream.Orchestrator.Domain.Models;

    /// <summary>
    /// Abstraction for CRUD operations on <see cref="PipelineDefinition"/> aggregates.
    /// </summary>
    public interface IPipelineRepository
    {
        Task<PipelineDefinition?> GetByIdAsync(Guid pipelineId, CancellationToken cancellationToken = default);

        Task<IReadOnlyList<PipelineDefinition>> GetAllAsync(
            Expression<Func<PipelineDefinition, bool>>? predicate = null,
            CancellationToken cancellationToken = default);

        Task<bool> ExistsAsync(Guid pipelineId, CancellationToken cancellationToken = default);

        Task AddAsync(PipelineDefinition pipelineDefinition, CancellationToken cancellationToken = default);

        void Update(PipelineDefinition pipelineDefinition);

        void Remove(PipelineDefinition pipelineDefinition);

        /// <summary>
        /// Persists all pending changes to the underlying store.
        /// </summary>
        /// <returns>The number of affected rows.</returns>
        Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
    }
}

namespace PaletteStream.Orchestrator.Infrastructure.Persistence.Contexts
{
    using PaletteStream.Orchestrator.Domain.Models;

    /// <summary>
    /// Entity Framework Core <see cref="DbContext"/> used by the Orchestrator service.
    /// </summary>
    public sealed class OrchestratorDbContext : DbContext
    {
        public OrchestratorDbContext(DbContextOptions<OrchestratorDbContext> options)
            : base(options)
        { }

        public DbSet<PipelineDefinition> PipelineDefinitions => Set<PipelineDefinition>();

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);

            // Basic schema specification.
            modelBuilder.Entity<PipelineDefinition>(entity =>
            {
                entity.ToTable("pipeline_definitions", "orchestrator");

                entity.HasKey(e => e.Id);

                entity.Property(e => e.Name)
                    .IsRequired()
                    .HasMaxLength(256);

                entity.Property(e => e.Version)
                    .IsRequired()
                    .HasMaxLength(32);

                entity.Property(e => e.JsonDefinition)
                    .IsRequired();

                entity.Property(e => e.Status)
                    .IsRequired()
                    .HasMaxLength(32);

                entity.Property(e => e.CreatedAtUtc)
                    .HasColumnType("timestamp without time zone")
                    .HasDefaultValueSql("NOW()");

                entity.Property(e => e.UpdatedAtUtc)
                    .HasColumnType("timestamp without time zone")
                    .HasDefaultValueSql("NOW()");
            });
        }
    }
}