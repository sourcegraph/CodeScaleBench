```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using MediatR;
using Microsoft.Extensions.Logging;
using TycoonVerse.Application.Abstractions.Analytics;
using TycoonVerse.Application.Abstractions.Persistence;
using TycoonVerse.Application.Abstractions.Services;
using TycoonVerse.Domain.PlayerActions;

namespace TycoonVerse.Application.Features.Sync;

/// <summary>
///     Command that triggers a best-effort synchronization of all locally-stored,
///     not-yet-synced player actions with the remote back-end once connectivity is
///     available.  Runs idempotently; re-executing the command will never re-sync
///     already confirmed actions.
/// </summary>
public sealed record SyncPlayerActionsCommand : IRequest<SyncPlayerActionsResult>;

/// <summary>
///     Result object returned after a <see cref="SyncPlayerActionsCommand"/> has finished.
/// </summary>
/// <param name="TotalDispatched">Number of actions sent to the back-end.</param>
/// <param name="TotalConfirmed">Number of actions confirmed by the back-end.</param>
/// <param name="Failed">If true at least one action failed and was re-queued.</param>
public sealed record SyncPlayerActionsResult(int TotalDispatched, int TotalConfirmed, bool Failed);

/// <summary>
///     Command handler that orchestrates the deterministic, transactional sync of
///     player actions created while the device was offline.
/// </summary>
internal sealed class SyncPlayerActionsCommandHandler
    : IRequestHandler<SyncPlayerActionsCommand, SyncPlayerActionsResult>
{
    private readonly IPlayerActionRepository _actionRepository;
    private readonly ISyncService _syncService;
    private readonly IAnalyticsService _analytics;
    private readonly ILogger<SyncPlayerActionsCommandHandler> _logger;

    public SyncPlayerActionsCommandHandler(
        IPlayerActionRepository actionRepository,
        ISyncService syncService,
        IAnalyticsService analytics,
        ILogger<SyncPlayerActionsCommandHandler> logger)
    {
        _actionRepository = actionRepository ?? throw new ArgumentNullException(nameof(actionRepository));
        _syncService = syncService ?? throw new ArgumentNullException(nameof(syncService));
        _analytics = analytics ?? throw new ArgumentNullException(nameof(analytics));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    public async Task<SyncPlayerActionsResult> Handle(
        SyncPlayerActionsCommand request,
        CancellationToken cancellationToken)
    {
        // Load unsynced actions deterministically ordered by creation date so that
        // the back-end can replay game state in exactly the same way as the client.
        IReadOnlyList<PlayerAction> pending = await _actionRepository
            .GetPendingAsync(orderByTimestampAsc: true, cancellationToken)
            .ConfigureAwait(false);

        if (pending.Count == 0)
        {
            _logger.LogDebug("No pending player actions found for sync.");
            return new SyncPlayerActionsResult(0, 0, false);
        }

        _logger.LogInformation("Syncing {Count} player actions...", pending.Count);

        int dispatched = 0;
        int confirmed = 0;
        bool failed = false;

        // Split into small batches to avoid blowing up request size limits and
        // to allow partial progress if connectivity flaps.
        const int BatchSize = 32;
        IEnumerable<IEnumerable<PlayerAction>> batches = pending
            .Select((action, index) => new { action, index })
            .GroupBy(x => x.index / BatchSize, x => x.action);

        foreach (IEnumerable<PlayerAction> batch in batches)
        {
            IReadOnlyList<PlayerAction> batchList = batch.ToList();

            try
            {
                // Dispatch to remote API
                SyncResponse response = await _syncService
                    .PushAsync(batchList, cancellationToken)
                    .ConfigureAwait(false);

                dispatched += batchList.Count;
                confirmed += response.ConfirmedCount;

                // Mark confirmed actions as synced in local storage
                if (response.ConfirmedIds.Any())
                {
                    await _actionRepository
                        .MarkAsSyncedAsync(response.ConfirmedIds, cancellationToken)
                        .ConfigureAwait(false);
                }

                // Re-queue rejected actions for future attempts
                if (response.RejectedItems.Any())
                {
                    failed = true;
                    _logger.LogWarning(
                        "Sync rejected {Rejected} actions.  They will be retried later.",
                        response.RejectedItems.Count);

                    await _actionRepository
                        .MarkAsFailedAsync(response.RejectedItems, cancellationToken)
                        .ConfigureAwait(false);
                }

                // Track analytics for the batch
                _analytics.TrackEvent("player_action_sync_batch", new
                {
                    dispatched = batchList.Count,
                    confirmed = response.ConfirmedCount,
                    rejected = response.RejectedItems.Count,
                    latencyMs = response.Latency.TotalMilliseconds
                });
            }
            catch (Exception ex) when (!ex.IsFatal()) // extension method that filters fatal exceptions
            {
                failed = true;
                _logger.LogError(ex, "Unexpected error while syncing player action batch.  Will retry later.");

                // Any exception aborts the current batch but keeps the loop running,
                // maximizing the amount of data we can still sync.
                // No additional work needed; the unsynced actions remain pending.
            }
        }

        // Emit high-level analytic summary
        _analytics.TrackEvent("player_action_sync_summary", new
        {
            dispatched,
            confirmed,
            failed
        });

        return new SyncPlayerActionsResult(dispatched, confirmed, failed);
    }
}

#region Supporting Abstractions (contracts)

/// <summary>
///     Contract for a repository that stores player actions locally (SQLite).
/// </summary>
public interface IPlayerActionRepository
{
    Task<IReadOnlyList<PlayerAction>> GetPendingAsync(bool orderByTimestampAsc, CancellationToken token);
    Task MarkAsSyncedAsync(IEnumerable<Guid> actionIds, CancellationToken token);
    Task MarkAsFailedAsync(IEnumerable<PlayerAction> actions, CancellationToken token);
}

/// <summary>
///     Contract for a service responsible for pushing local mutations to the
///     authoritative back-end service.
/// </summary>
public interface ISyncService
{
    Task<SyncResponse> PushAsync(IReadOnlyCollection<PlayerAction> actions, CancellationToken token);
}

/// <summary>
///     Response returned by <see cref="ISyncService"/> after a push attempt.
/// </summary>
public sealed class SyncResponse
{
    public SyncResponse(
        IReadOnlyCollection<Guid> confirmedIds,
        IReadOnlyCollection<PlayerAction> rejectedItems,
        TimeSpan latency)
    {
        ConfirmedIds = confirmedIds;
        RejectedItems = rejectedItems;
        Latency = latency;
    }

    /// <summary>IDs of actions that the server accepted and persisted.</summary>
    public IReadOnlyCollection<Guid> ConfirmedIds { get; }

    /// <summary>Actions that the server rejected (validation, conflict, etc.).</summary>
    public IReadOnlyCollection<PlayerAction> RejectedItems { get; }

    /// <summary>Trip time for the entire request-response cycle.</summary>
    public TimeSpan Latency { get; }

    /// <summary>Convenience property for the count of confirmed items.</summary>
    public int ConfirmedCount => ConfirmedIds.Count;
}

#endregion

#region Domain Model (simplified)

/// <summary>
///     Domain entity representing a player action that mutates game state.  Stored
///     locally until server acknowledgement for determinism.  Serializable to JSON.
/// </summary>
public sealed class PlayerAction
{
    public Guid Id { get; init; } = Guid.NewGuid();

    /// <summary>UTC timestamp of when the action was generated on the device.</summary>
    public DateTimeOffset CreatedAtUtc { get; init; } = DateTimeOffset.UtcNow;

    /// <summary>Type discriminator (purchase, negotiation, IPO, etc.).</summary>
    public string ActionType { get; init; } = string.Empty;

    /// <summary>JSON payload containing the domain-specific data for the action.</summary>
    public string PayloadJson { get; init; } = string.Empty;

    /// <summary>Version for optimistic concurrency control.</summary>
    public int Version { get; init; } = 1;
}

#endregion

#region Utility Extensions

internal static class ExceptionExtensions
{
    /// <summary>
    ///     Determines whether the exception is fatal and should not be swallowed
    ///     (e.g., <see cref="OutOfMemoryException"/> or <see cref="StackOverflowException"/>).
    /// </summary>
    public static bool IsFatal(this Exception exception) =>
        exception is OutOfMemoryException
        || exception is StackOverflowException
        || exception is AccessViolationException;
}

#endregion
```