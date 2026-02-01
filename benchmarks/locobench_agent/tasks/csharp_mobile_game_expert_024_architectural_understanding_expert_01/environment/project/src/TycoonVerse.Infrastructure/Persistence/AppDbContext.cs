```csharp
using System;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using TycoonVerse.Domain.Abstractions;
using TycoonVerse.Domain.Entities;
using TycoonVerse.Domain.ValueObjects;
using TycoonVerse.Infrastructure.Persistence.Extensions;

namespace TycoonVerse.Infrastructure.Persistence;

/// <summary>
/// EF Core DbContext used by the mobile-client runtime.  
/// Handles local persistence (SQLite) while supporting advanced enterprise patterns
/// such as audit-tracking, optimistic concurrency, outbox messaging, and domain-event publication.
/// </summary>
public sealed class AppDbContext : DbContext, IAppDbContext
{
    private readonly IMediator? _mediator;     // optional – only available in production runtime, not during migrations

    public DbSet<PlayerProfile>            Players              => Set<PlayerProfile>();
    public DbSet<Company>                  Companies            => Set<Company>();
    public DbSet<InventoryItem>            InventoryItems       => Set<InventoryItem>();
    public DbSet<MarketOrder>              MarketOrders         => Set<MarketOrder>();
    public DbSet<CompanyFinancialSnapshot> FinancialSnapshots   => Set<CompanyFinancialSnapshot>();
    public DbSet<OutboxMessage>            OutboxMessages       => Set<OutboxMessage>();

    public AppDbContext(DbContextOptions<AppDbContext> options, IMediator? mediator = null) : base(options)
    {
        _mediator = mediator;
        // Performance tweak: disable tracking for read-only queries by default.
        ChangeTracker.QueryTrackingBehavior = QueryTrackingBehavior.NoTracking;
    }

    #region DbContext overrides

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        // Apply IEntityTypeConfiguration<T> found in this assembly (clean separation of config)
        modelBuilder.ApplyConfigurationsFromAssembly(Assembly.GetExecutingAssembly());

        // Composite configurations that span multiple entities
        ConfigureAuditFields(modelBuilder);
        ConfigureOutbox(modelBuilder);

        SeedInitialData(modelBuilder);

        base.OnModelCreating(modelBuilder);
    }

    public override async Task<int> SaveChangesAsync(CancellationToken cancellationToken = default)
    {
        this.ApplyAuditInformation();    // extension method
        this.ConvertDomainEventsToOutboxMessages();

        // SQLite does not persist UTC kind – we enforce string serialization at model config
        var result = await base.SaveChangesAsync(cancellationToken).ConfigureAwait(false);

        // Publish domain events AFTER the transaction commits
        if (_mediator is not null)
        {
            await this.DispatchDomainEventsAsync(_mediator, cancellationToken)
                      .ConfigureAwait(false);
        }

        return result;
    }

    #endregion

    #region Model Configuration helpers

    private static void ConfigureAuditFields(ModelBuilder builder)
    {
        foreach (var entity in builder.Model.GetEntityTypes())
        {
            if (typeof(IAuditableEntity).IsAssignableFrom(entity.ClrType))
            {
                builder.Entity(entity.ClrType).Property<DateTime>("CreatedAtUtc")
                                              .HasColumnType("TEXT")
                                              .IsRequired();

                builder.Entity(entity.ClrType).Property<DateTime>("LastModifiedUtc")
                                              .HasColumnType("TEXT")
                                              .IsRequired();

                // Optimistic concurrency token
                builder.Entity(entity.ClrType).Property<byte[]>("RowVersion")
                                              .IsRowVersion()
                                              .IsConcurrencyToken();
            }
        }
    }

    private static void ConfigureOutbox(ModelBuilder builder)
    {
        builder.Entity<OutboxMessage>(e =>
        {
            e.HasKey(o => o.Id);
            e.Property(o => o.OccurredOnUtc)
             .HasColumnType("TEXT");
            e.Property(o => o.Type)
             .HasMaxLength(256);
            e.HasIndex(o => o.ProcessedOnUtc);
        });
    }

    private static void SeedInitialData(ModelBuilder builder)
    {
        // Only seed lightweight, deterministic data needed locally.
        var playerId = new Guid("11111111-0000-0000-0000-000000000001");
        builder.Entity<PlayerProfile>().HasData(
            new PlayerProfile(playerId, "Tycoon Starter") { WalletBalance = Money.FromDecimal(100_000m) }
        );

        var companyId = new Guid("22222222-0000-0000-0000-000000000001");
        builder.Entity<Company>().HasData(
            new Company(companyId, playerId, "Genesis Logistics", Industry.SupplyChain)
        );
    }

    #endregion
}

#region Extensions / Helper classes

internal static class DbContextDomainEventExtensions
{
    /// <summary>
    /// Converts domain events collected on aggregates implementing <see cref="IHasDomainEvents"/>
    /// into persisted <see cref="OutboxMessage"/> records.
    /// </summary>
    internal static void ConvertDomainEventsToOutboxMessages(this AppDbContext context)
    {
        var domainEntities = context.ChangeTracker
                                    .Entries<IHasDomainEvents>()
                                    .Where(de => de.Entity.DomainEvents.Any())
                                    .ToList();

        foreach (var entry in domainEntities)
        {
            var events = entry.Entity.DomainEvents.ToArray();
            entry.Entity.ClearDomainEvents();

            foreach (var domainEvent in events)
            {
                var outbox = OutboxMessage.Create(domainEvent);
                context.OutboxMessages.Add(outbox);
            }
        }
    }

    /// <summary>
    /// Publishes domain events via MediatR once the transaction has committed.
    /// </summary>
    internal static async Task DispatchDomainEventsAsync(this AppDbContext context,
                                                         IMediator mediator,
                                                         CancellationToken cancellationToken)
    {
        var outbox = context.ChangeTracker
                            .Entries<OutboxMessage>()
                            .Where(o => o.State == EntityState.Added)
                            .Select(o => o.Entity)
                            .ToArray();

        foreach (var message in outbox)
        {
            if (message.TryConvertPayload(out var domainEvent))
            {
                await mediator.Publish(domainEvent, cancellationToken)
                              .ConfigureAwait(false);
            }
        }
    }

    /// <summary>
    /// Automatically sets <see cref="IAuditableEntity"/> timestamps.
    /// </summary>
    internal static void ApplyAuditInformation(this AppDbContext context)
    {
        var entries = context.ChangeTracker.Entries<IAuditableEntity>();

        var utcNow = DateTime.UtcNow;

        foreach (var entry in entries)
        {
            switch (entry.State)
            {
                case EntityState.Added:
                    entry.Property("CreatedAtUtc").CurrentValue = utcNow;
                    entry.Property("LastModifiedUtc").CurrentValue = utcNow;
                    break;
                case EntityState.Modified:
                    entry.Property("LastModifiedUtc").CurrentValue = utcNow;
                    break;
            }
        }
    }
}

#endregion

#region Interfaces

/// <summary>
/// Abstraction over EF Core context used by higher application layers (CQRS handlers).
/// Makes unit-testing easier and hides EF specifics.
/// </summary>
public interface IAppDbContext : IUnitOfWork
{
    DbSet<PlayerProfile>            Players            { get; }
    DbSet<Company>                  Companies          { get; }
    DbSet<InventoryItem>            InventoryItems     { get; }
    DbSet<MarketOrder>              MarketOrders       { get; }
    DbSet<CompanyFinancialSnapshot> FinancialSnapshots { get; }
    DbSet<OutboxMessage>            OutboxMessages     { get; }
}

/// <summary> Marker interface for entities with audit information. </summary>
public interface IAuditableEntity { }

/// <summary> Provides DB-transaction boundary for CQRS commands. </summary>
public interface IUnitOfWork
{
    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}

/// <summary>
/// Aggregates that raise domain events implement this interface.
/// Events are captured and persisted into the outbox until processed.
/// </summary>
public interface IHasDomainEvents
{
    IReadOnlyCollection<IDomainEvent> DomainEvents { get; }
    void ClearDomainEvents();
}

#endregion

#region Outbox implementation

/// <summary>
/// Table that stores a serialized representation of domain events so that they can be reliably
/// processed once connectivity is restored (Offline-first requirement).
/// </summary>
public sealed class OutboxMessage
{
    private OutboxMessage() { }

    public Guid       Id              { get; private set; } = Guid.NewGuid();
    public DateTime   OccurredOnUtc   { get; private set; }
    public DateTime?  ProcessedOnUtc  { get; private set; }
    public string     Type            { get; private set; } = default!;
    public string     Payload         { get; private set; } = default!;

    public static OutboxMessage Create(IDomainEvent domainEvent)
    {
        var type = domainEvent.GetType();
        return new OutboxMessage
        {
            Type          = type.FullName ?? type.Name,
            OccurredOnUtc = domainEvent.OccurredOnUtc,
            Payload       = JsonSerializer.Serialize(domainEvent, type)
        };
    }

    public bool TryConvertPayload(out IDomainEvent? domainEvent)
    {
        var eventType = AppDomain.CurrentDomain
                                 .GetAssemblies()
                                 .SelectMany(x => x.GetTypes())
                                 .FirstOrDefault(t => t.FullName == Type);

        if (eventType is null)
        {
            domainEvent = null;
            return false;
        }

        domainEvent = (IDomainEvent?)JsonSerializer.Deserialize(Payload, eventType);
        return domainEvent is not null;
    }

    public void MarkAsProcessed()
    {
        ProcessedOnUtc = DateTime.UtcNow;
    }
}

#endregion

#region Configuration classes

// Example of strongly-typed EntityTypeConfiguration to keep domain model clean
internal sealed class CompanyConfiguration : IEntityTypeConfiguration<Company>
{
    public void Configure(EntityTypeBuilder<Company> builder)
    {
        builder.HasKey(c => c.Id);

        builder.Property(c => c.Name)
               .IsRequired()
               .HasMaxLength(128);

        builder.Property(c => c.Industry)
               .HasConversion(new EnumToStringConverter<Industry>())
               .HasMaxLength(64);

        builder.Property<byte[]>("RowVersion")
               .IsRowVersion()
               .IsConcurrencyToken();

        // Relationships
        builder.HasMany(c => c.Inventory)
               .WithOne()
               .HasForeignKey(i => i.CompanyId)
               .OnDelete(DeleteBehavior.Cascade);
    }
}

// Additional configurations could be split into separate files—kept here for brevity.

#endregion
```