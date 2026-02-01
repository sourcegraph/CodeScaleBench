```csharp
using System;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Domain.Common;
using CanvasCraft.Domain.Entities;
using CanvasCraft.Infrastructure.Data.Interceptors;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;

namespace CanvasCraft.Infrastructure.Data
{
    /// <summary>
    ///     Primary Entity Framework Core DbContext for CanvasCraft ML-Studio.
    ///     Responsible for:
    ///         • Authoritative persistence of domain aggregates (experiment tracking, feature store, model registry, etc.)
    ///         • Automatic auditing (Created/Modified stamps & user tracking)
    ///         • Outbox pattern integration for reliable domain-event dispatching
    ///         • Soft-delete filtering
    /// </summary>
    public sealed class CanvasCraftDbContext : DbContext
    {
        // === DbSets ===============================================================================================

        public DbSet<Dataset>                       Datasets                       => Set<Dataset>();
        public DbSet<ExperimentRun>                 ExperimentRuns                => Set<ExperimentRun>();
        public DbSet<FeatureDefinition>             FeatureDefinitions            => Set<FeatureDefinition>();
        public DbSet<ModelCheckpoint>               ModelCheckpoints              => Set<ModelCheckpoint>();
        public DbSet<ModelRegistryEntry>            ModelRegistry                 => Set<ModelRegistryEntry>();
        public DbSet<HyperparameterSweep>           HyperparameterSweeps          => Set<HyperparameterSweep>();
        public DbSet<OutboxMessage>                 OutboxMessages                => Set<OutboxMessage>();

        // === Infrastructure members ==============================================================================

        private readonly IDateTimeProvider          _clock;
        private readonly ICurrentUserProvider       _currentUser;
        private readonly PublishDomainEventsInterceptor _publishDomainEventsInterceptor;

        public CanvasCraftDbContext(
            DbContextOptions<CanvasCraftDbContext>      options, 
            IDateTimeProvider                           clock,
            ICurrentUserProvider                        currentUser,
            PublishDomainEventsInterceptor              publishDomainEventsInterceptor)
            : base(options)
        {
            _clock                           = clock          ?? throw new ArgumentNullException(nameof(clock));
            _currentUser                     = currentUser    ?? throw new ArgumentNullException(nameof(currentUser));
            _publishDomainEventsInterceptor  = publishDomainEventsInterceptor
                                               ?? throw new ArgumentNullException(nameof(publishDomainEventsInterceptor));
        }

        // === Model configuration =================================================================================

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);

            // Automatically apply IEntityTypeConfiguration<T> found in the assembly
            modelBuilder.ApplyConfigurationsFromAssembly(Assembly.GetExecutingAssembly());

            // Global query filters for soft-delete
            foreach (var entityType in modelBuilder.Model.GetEntityTypes()
                         .Where(t => typeof(ISoftDeletable).IsAssignableFrom(t.ClrType)))
            {
                var method = typeof(CanvasCraftDbContext)
                    .GetMethod(nameof(SetSoftDeleteFilter), BindingFlags.NonPublic | BindingFlags.Static)!
                    .MakeGenericMethod(entityType.ClrType);

                method.Invoke(null, new object[] { modelBuilder });
            }
        }

        private static void SetSoftDeleteFilter<TEntity>(ModelBuilder builder) where TEntity : class, ISoftDeletable
        {
            builder.Entity<TEntity>().HasQueryFilter(e => !e.IsDeleted);
        }

        // === SaveChanges overrides ==============================================================================

        public override int SaveChanges(bool acceptAllChangesOnSuccess)
        {
            ApplyAuditing();
            return base.SaveChanges(acceptAllChangesOnSuccess);
        }

        public override Task<int> SaveChangesAsync(
            bool acceptAllChangesOnSuccess,
            CancellationToken cancellationToken = default)
        {
            ApplyAuditing();
            return base.SaveChangesAsync(acceptAllChangesOnSuccess, cancellationToken);
        }

        private void ApplyAuditing()
        {
            var now     = _clock.UtcNow;
            var userId  = _currentUser.UserId;

            foreach (var entry in ChangeTracker.Entries<IAuditableEntity>())
            {
                switch (entry.State)
                {
                    case EntityState.Added:
                        entry.Property(e => e.CreatedAtUtc).CurrentValue  = now;
                        entry.Property(e => e.CreatedBy).CurrentValue      = userId;
                        break;

                    case EntityState.Modified:
                        entry.Property(e => e.LastModifiedAtUtc).CurrentValue = now;
                        entry.Property(e => e.LastModifiedBy).CurrentValue    = userId;
                        break;
                }
            }
        }

        // === Interceptor registration ===========================================================================
        protected override void OnConfiguring(DbContextOptionsBuilder optionsBuilder)
        {
            if (!optionsBuilder.IsConfigured) return;

            // Attach interceptors last to ensure they observe already-configured options.
            optionsBuilder
                .AddInterceptors(_publishDomainEventsInterceptor)
                .ConfigureWarnings(w => w.Throw(RelationalEventId.QueryPossibleUnintendedUseOfEqualsWarning));
        }
    }
}
```

