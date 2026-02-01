```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="IPlayerRepository.cs" company="TycoonVerse">
//   Copyright © TycoonVerse. 
//   All rights reserved. Confidential and proprietary.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------

// NOTE:  This interface is part of the Application layer.  No direct data–access technology
//        (SQLite, HTTP, etc.) should be referenced here.  Concrete implementations live in the
//        Infrastructure layer and are injected via DI at runtime.

#nullable enable

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Application.Common.Models;
using TycoonVerse.Domain.Entities;
using TycoonVerse.Domain.Primitives;
using TycoonVerse.Domain.ValueObjects;

namespace TycoonVerse.Application.Interfaces.Repositories
{
    /// <summary>
    /// Repository abstraction for <see cref="Player"/> domain entities.
    /// </summary>
    public interface IPlayerRepository : IDisposable, IAsyncDisposable
    {
        #region Basic CRUD

        /// <summary>
        /// Retrieves a player by its unique identifier.
        /// </summary>
        /// <param name="playerId">The player's identifier.</param>
        /// <param name="ct">Optional <see cref="CancellationToken"/>.</param>
        /// <returns>A <see cref="Player"/> or <c>null</c> if not found.</returns>
        Task<Player?> GetByIdAsync(Guid playerId, CancellationToken ct = default);

        /// <summary>
        /// Persists a new <see cref="Player"/>.
        /// </summary>
        /// <param name="player">Fully constructed player domain entity.</param>
        /// <param name="ct">Optional cancellation token.</param>
        Task AddAsync(Player player, CancellationToken ct = default);

        /// <summary>
        /// Updates an existing player. 
        /// Implementations MUST honor optimistic-concurrency rules via <see cref="IConcurrencyAware.ConcurrencyToken"/>.
        /// </summary>
        /// <param name="player">Player entity with updated state.</param>
        /// <param name="ct">Optional cancellation token.</param>
        Task UpdateAsync(Player player, CancellationToken ct = default);

        /// <summary>
        /// Deletes (soft or hard depending on implementation) the specified player.
        /// </summary>
        /// <param name="playerId">The player identifier.</param>
        /// <param name="ct">Optional cancellation token.</param>
        Task DeleteAsync(Guid playerId, CancellationToken ct = default);

        /// <summary>
        /// Returns paged, filterable player data for dashboards and admin tools.
        /// </summary>
        /// <param name="parameters">Filtering, search, and ordering parameters.</param>
        /// <param name="ct">Optional cancellation token.</param>
        Task<PaginatedList<Player>> GetPagedAsync(PlayerQueryParameters parameters, CancellationToken ct = default);

        #endregion

        #region Wallet Operations

        /// <summary>
        /// Retrieves a snapshot of the player’s wallet (in-game cash & premium currency).
        /// </summary>
        Task<WalletSnapshot> GetWalletAsync(Guid playerId, CancellationToken ct = default);

        /// <summary>
        /// Credits the player's wallet atomically.  A negative <paramref name="amount"/> is rejected.
        /// </summary>
        /// <param name="playerId">Target player.</param>
        /// <param name="amount">Currency amount.</param>
        /// <param name="externalRef">Idempotency key (e.g., IAP transaction id).</param>
        Task<Result> CreditWalletAsync(Guid playerId, Money amount, string externalRef, CancellationToken ct = default);

        /// <summary>
        /// Debits the player's wallet atomically, validating sufficient balance.
        /// </summary>
        Task<Result> DebitWalletAsync(Guid playerId, Money amount, string externalRef, CancellationToken ct = default);

        #endregion

        #region Achievement & Progress

        /// <summary>
        /// Gets a collection of unlocked achievements for a player.
        /// </summary>
        Task<IReadOnlyList<Achievement>> GetUnlockedAchievementsAsync(Guid playerId, CancellationToken ct = default);

        /// <summary>
        /// Unlocks the specified achievement.  The operation must be idempotent.
        /// </summary>
        Task<Result> UnlockAchievementAsync(Guid playerId, AchievementCode achievementCode, CancellationToken ct = default);

        #endregion

        #region Leaderboards

        /// <summary>
        /// Returns a slice of the global leaderboard for display purposes.
        /// </summary>
        Task<IReadOnlyList<LeaderboardEntry>> GetLeaderboardAsync(LeaderboardQuery query, CancellationToken ct = default);

        #endregion

        #region Sync (Offline-First)

        /// <summary>
        /// Calculates changes since the last sync.  Used by the deterministic offline-sync engine.
        /// </summary>
        Task<PlayerSyncPayload> GetDeltaSinceAsync(Guid playerId, DateTime lastSyncUtc, CancellationToken ct = default);

        /// <summary>
        /// Applies a batch of offline mutations coming from the client device.
        /// </summary>
        Task<Result> ApplySyncAsync(PlayerSyncPayload payload, CancellationToken ct = default);

        #endregion

        #region Authentication / Security

        /// <summary>
        /// Reserves (locks) the desired username while the user completes onboarding. 
        /// Returns the reservation id for confirmation.
        /// </summary>
        Task<Result<Guid>> ReserveUsernameAsync(string desiredUsername, CancellationToken ct = default);

        /// <summary>
        /// Confirms username reservation after successful SSO / biometric verification.
        /// </summary>
        Task<Result> ConfirmUsernameReservationAsync(Guid reservationId, Guid playerId, CancellationToken ct = default);

        #endregion
    }
}
```