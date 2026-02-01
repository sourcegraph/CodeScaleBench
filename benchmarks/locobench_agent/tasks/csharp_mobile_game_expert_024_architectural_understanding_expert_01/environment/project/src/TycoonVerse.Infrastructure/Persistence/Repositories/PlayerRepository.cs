```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using TycoonVerse.Domain.Abstractions.Repositories;
using TycoonVerse.Domain.Entities;
using TycoonVerse.Infrastructure.Persistence.Contexts;
using TycoonVerse.Infrastructure.Persistence.Exceptions;

namespace TycoonVerse.Infrastructure.Persistence.Repositories
{
    /// <summary>
    ///     Production-grade repository for <see cref="Player"/> aggregates.
    ///     Uses EF Core backed by SQLite for local storage and supports
    ///     optimistic concurrency, soft-delete, and offline-sync awareness.
    /// </summary>
    internal sealed class PlayerRepository : IPlayerRepository
    {
        private readonly TycoonVerseDbContext _dbContext;
        private readonly ILogger<PlayerRepository> _logger;

        public PlayerRepository(
            TycoonVerseDbContext dbContext,
            ILogger<PlayerRepository> logger)
        {
            _dbContext = dbContext ?? throw new ArgumentNullException(nameof(dbContext));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        #region Public API — Queries

        public async Task<Player?> GetAsync(
            Guid playerId,
            bool includeDeleted = false,
            CancellationToken cancellationToken = default)
        {
            try
            {
                IQueryable<Player> query = _dbContext.Players;

                if (!includeDeleted)
                    query = query.Where(p => !p.IsDeleted);

                // Include related aggregates in a single roundtrip
                query = query
                    .Include(p => p.Companies) // Owned companies
                    .Include(p => p.Portfolio) // Financial portfolio
                    .ThenInclude(prt => prt.Holdings);

                return await query.FirstOrDefaultAsync(p => p.Id == playerId, cancellationToken);
            }
            catch (OperationCanceledException)
            {
                _logger.LogWarning("GetAsync for Player {PlayerId} was cancelled.", playerId);
                throw;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error retrieving Player {PlayerId}", playerId);
                throw new RepositoryException("Unable to retrieve player.", ex);
            }
        }

        public async Task<Player?> GetByExternalAuthIdAsync(
            string externalAuthId,
            CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(externalAuthId))
                throw new ArgumentException("Value cannot be null or whitespace.", nameof(externalAuthId));

            try
            {
                return await _dbContext.Players
                    .AsNoTracking()
                    .Where(p => p.ExternalAuthId == externalAuthId && !p.IsDeleted)
                    .FirstOrDefaultAsync(cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogError(ex, "Error retrieving Player by ExternalAuthId {ExternalAuthId}", externalAuthId);
                throw new RepositoryException("Unable to retrieve player by external auth id.", ex);
            }
        }

        public async Task<IReadOnlyCollection<Player>> GetUnsyncedAsync(
            DateTimeOffset since,
            CancellationToken cancellationToken = default)
        {
            try
            {
                return await _dbContext.Players
                    .Where(p => p.LastSyncedUtc < since && !p.IsDeleted)
                    .OrderBy(p => p.LastModifiedUtc)
                    .ToListAsync(cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogError(ex, "Error retrieving unsynced Players since {Since}", since);
                throw new RepositoryException("Unable to retrieve unsynced players.", ex);
            }
        }

        #endregion

        #region Public API — Commands

        public async Task AddAsync(Player player, CancellationToken cancellationToken = default)
        {
            if (player is null) throw new ArgumentNullException(nameof(player));

            try
            {
                await _dbContext.Players.AddAsync(player, cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogError(ex, "Error adding Player {PlayerId}", player.Id);
                throw new RepositoryException("Unable to add player.", ex);
            }
        }

        public async Task UpdateAsync(Player player, CancellationToken cancellationToken = default)
        {
            if (player is null) throw new ArgumentNullException(nameof(player));

            try
            {
                _dbContext.Players.Update(player);
                await Task.CompletedTask;
            }
            catch (DbUpdateConcurrencyException ex)
            {
                _logger.LogWarning(ex, "Concurrency conflict while updating Player {PlayerId}", player.Id);
                throw new ConcurrencyException("Concurrency conflict detected.", ex);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogError(ex, "Error updating Player {PlayerId}", player.Id);
                throw new RepositoryException("Unable to update player.", ex);
            }
        }

        public async Task DeleteAsync(
            Guid playerId,
            bool hardDelete = false,
            CancellationToken cancellationToken = default)
        {
            try
            {
                var player = await _dbContext.Players.FirstOrDefaultAsync(p => p.Id == playerId, cancellationToken);
                if (player == null) return;

                if (hardDelete)
                {
                    _dbContext.Players.Remove(player);
                }
                else
                {
                    player.IsDeleted = true;
                    player.DeletedUtc = DateTimeOffset.UtcNow;
                    _dbContext.Players.Update(player);
                }
            }
            catch (DbUpdateConcurrencyException ex)
            {
                _logger.LogWarning(ex, "Concurrency conflict while deleting Player {PlayerId}", playerId);
                throw new ConcurrencyException("Concurrency conflict detected.", ex);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogError(ex, "Error deleting Player {PlayerId}", playerId);
                throw new RepositoryException("Unable to delete player.", ex);
            }
        }

        #endregion

        #region Unit of Work helpers

        public async Task<int> SaveChangesAsync(CancellationToken cancellationToken = default)
        {
            try
            {
                return await _dbContext.SaveChangesAsync(cancellationToken);
            }
            catch (DbUpdateConcurrencyException ex)
            {
                _logger.LogWarning(ex, "Concurrency conflict while saving changes for Players.");
                throw new ConcurrencyException("Concurrency conflict detected.", ex);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogError(ex, "Error saving changes for Player repository.");
                throw new RepositoryException("Unable to commit changes.", ex);
            }
        }

        #endregion
    }
}
```