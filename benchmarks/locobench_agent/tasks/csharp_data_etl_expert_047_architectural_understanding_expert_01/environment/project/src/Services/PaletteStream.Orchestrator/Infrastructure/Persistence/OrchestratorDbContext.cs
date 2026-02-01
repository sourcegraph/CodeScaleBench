using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.Logging;
using PaletteStream.Orchestrator.Domain.Abstractions;
using PaletteStream.Orchestrator.Domain.Entities;
using PaletteStream.Orchestrator.Infrastructure.Persistence.Configurations;

namespace PaletteStream.Orchestrator.Infrastructure.Persistence
{
    /// <summary>
    /// DbContext for the Orchestrator service.
    /// Tracks ETL job definitions, executions, transformation pipelines,
    /// and handles reliable domain-event dispatching through the outbox.
    /// </summary>
    public sealed class OrchestratorDbContext : DbContext, IUnitOfWork
    {
        private readonly IDomainEventDispatcher _dispatcher;
        private readonly ILogger<OrchestratorDbContext> _logger;

        public OrchestratorDbContext(
            DbContextOptions<OrchestratorDbContext> options,
            IDomainEventDispatcher dispatcher,
            ILogger<OrchestratorDbContext> logger) : base(options)
        {
            _dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        #region DbSets

        public DbSet<JobDefinition> JobDefinitions => Set<JobDefinition>();
        public DbSet<JobRun> JobRuns => Set<JobRun>();
        public DbSet<PipelineStage> PipelineStages => Set<PipelineStage>();
        public DbSet<TransformationStep> TransformationSteps => Set<TransformationStep>();

        /// <summary>
        /// Outbox used for the Transactional Outbox pattern.
        /// Messages are picked up asynchronously and published to the event bus.
        /// </summary>
        public DbSet<OutboxMessage> OutboxMessages => Set<OutboxMessage>();

        #endregion

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            // Apply entity configurations located in this assembly.
            modelBuilder.ApplyConfigurationsFromAssembly(typeof(JobDefinitionConfiguration).Assembly);

            // Store all enums as strings (portable across DB engines, human-readable).
            foreach (var entityType in modelBuilder.Model.GetEntityTypes())
            {
                var enumProps = entityType.ClrType
                                          .GetProperties()
                                          .Where(p => p.PropertyType.IsEnum);

                foreach (var prop in enumProps)
                {
                    modelBuilder.Entity(entityType.Name)
                                .Property(prop.Name)
                                .HasConversion<string>();
                }
            }

            base.OnModelCreating(modelBuilder);
        }

        /// <summary>
        /// Persists all pending changes and dispatches domain events in a single, resilient transaction.
        /// </summary>
        public async Task<int> SaveEntitiesAsync(CancellationToken cancellationToken = default)
        {
            // Publish domain events (e.g., JobRunStarted) BEFORE committing the transaction
            // so that handlers may participate in the same DB TX if required.
            await _dispatcher.DispatchAsync(this, cancellationToken).ConfigureAwait(false);

            var strategy = Database.CreateExecutionStrategy();

            return await strategy.ExecuteAsync(async () =>
            {
                await using var transaction = await BeginTransactionAsync(cancellationToken).ConfigureAwait(false);

                try
                {
                    var result = await base.SaveChangesAsync(cancellationToken).ConfigureAwait(false);
                    await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
                    return result;
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "An error occurred while saving entities in OrchestratorDbContext.");
                    await transaction.RollbackAsync(cancellationToken).ConfigureAwait(false);
                    throw;
                }
            });
        }

        /// <summary>
        /// Creates a new database transaction if one does not already exist.
        /// </summary>
        private Task<IDbContextTransaction> BeginTransactionAsync(CancellationToken token) =>
            Database.CurrentTransaction is null
                ? Database.BeginTransactionAsync(token)
                : Task.FromResult(Database.CurrentTransaction);
    }
}