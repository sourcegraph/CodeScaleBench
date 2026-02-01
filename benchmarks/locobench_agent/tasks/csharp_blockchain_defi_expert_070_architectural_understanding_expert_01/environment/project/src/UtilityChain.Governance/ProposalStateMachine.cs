```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Governance/ProposalStateMachine.cs

using System;
using System.Collections.Concurrent;
using System.Diagnostics.CodeAnalysis;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Governance;

/// <summary>
/// Public-facing DTO for governance proposals.
/// Immutable snapshot captured when state transitions complete.
/// </summary>
public record ProposalSnapshot(
    Guid Id,
    string Title,
    string Description,
    ProposalStatus Status,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    long ForVotes,
    long AgainstVotes,
    long AbstainVotes);

/// <summary>
/// High-level status enumeration for proposals.
/// </summary>
public enum ProposalStatus
{
    Draft     = 0,
    Voting    = 1,
    Queued    = 2,
    Executed  = 3,
    Cancelled = 4,
    Failed    = 5,
    Expired   = 6
}

/// <summary>
/// Discrete events that can trigger state transitions.
/// The state implementation decides if an event is allowed/ignored.
/// </summary>
public enum ProposalEvent
{
    Submit,
    OpenVoting,
    CastVote,
    CloseVoting,
    Queue,
    Execute,
    Cancel,
    Fail,
    Expire
}

/// <summary>
/// Minimal event bus abstraction used by the state machine
/// to publish domain notifications without depending on a specific broker.
/// </summary>
public interface IEventBus
{
    ValueTask PublishAsync<TEvent>(TEvent @event, CancellationToken ct = default);
}

/// <summary>
/// A must-implement marker interface for domain events.
/// </summary>
public interface IDomainEvent
{
    DateTimeOffset OccurredAt { get; }
}

/// <summary>
/// Generic domain-event implementation for proposal state changes.
/// </summary>
public sealed record ProposalStateChanged(
    Guid ProposalId,
    ProposalStatus Previous,
    ProposalStatus Current,
    DateTimeOffset OccurredAt) : IDomainEvent;

/// <summary>
/// Exception thrown when an invalid transition is requested.
/// </summary>
public sealed class InvalidProposalTransitionException : InvalidOperationException
{
    public InvalidProposalTransitionException(string message) : base(message) { }
}

/// <summary>
/// Centralized, thread-safe state machine controlling the lifecycle of a single proposal.
/// </summary>
public sealed class ProposalStateMachine : IDisposable
{
    private readonly ILogger<ProposalStateMachine> _logger;
    private readonly IEventBus _eventBus;
    private readonly object _gate = new();
    private readonly ConcurrentDictionary<string, object?> _extensions = new(StringComparer.Ordinal);
    private ProposalStatus _status;
    private VotingData _votingData;
    private bool _disposed;

    /// <summary>
    /// Creates a new state machine for a proposal in the <see cref="ProposalStatus.Draft"/> state.
    /// </summary>
    public ProposalStateMachine(
        Guid proposalId,
        string title,
        string description,
        ILogger<ProposalStateMachine> logger,
        IEventBus eventBus)
    {
        ProposalId  = proposalId;
        Title       = title  ?? throw new ArgumentNullException(nameof(title));
        Description = description ?? throw new ArgumentNullException(nameof(description));
        _logger     = logger ?? throw new ArgumentNullException(nameof(logger));
        _eventBus   = eventBus ?? throw new ArgumentNullException(nameof(eventBus));

        _status     = ProposalStatus.Draft;
        CreatedAt   = DateTimeOffset.UtcNow;
        UpdatedAt   = CreatedAt;
        _votingData = VotingData.Empty;
    }

    /* ------------------------------------------------------------------ *
     *  Public  API
     * ------------------------------------------------------------------ */

    public Guid           ProposalId  { get; }
    public string         Title       { get; }
    public string         Description { get; }
    public DateTimeOffset CreatedAt   { get; }
    public DateTimeOffset UpdatedAt   { get; private set; }

    /// <summary>
    /// Total votes FOR the proposal.
    /// </summary>
    public long ForVotes => _votingData.ForVotes;

    /// <summary>
    /// Total votes AGAINST the proposal.
    /// </summary>
    public long AgainstVotes => _votingData.AgainstVotes;

    /// <summary>
    /// Total ABSTAIN votes.
    /// </summary>
    public long AbstainVotes => _votingData.AbstainVotes;

    public ProposalStatus Status
    {
        get => _status;
        private set => _status = value;
    }

    /// <summary>
    /// Executes a transition event asynchronously.
    /// </summary>
    /// <exception cref="InvalidProposalTransitionException">
    /// Thrown when the requested event is invalid for the current state.
    /// </exception>
    public async ValueTask HandleAsync(
        ProposalEvent @event,
        long votingWeight             = 0,
        VotingOption option           = VotingOption.None,
        CancellationToken ct          = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        lock (_gate)
        {
            EnsureValidTransition(@event);
            ApplyInternal(@event, votingWeight, option);
        }

        // Off-thread side effects (logging, event bus) intentionally executed outside the lock.
        await PublishStateChangedAsync(ct).ConfigureAwait(false);
    }

    /// <summary>
    /// Captures an immutable snapshot of the proposal for external readers.
    /// </summary>
    public ProposalSnapshot Snapshot()
    {
        lock (_gate)
        {
            return new ProposalSnapshot(
                ProposalId,
                Title,
                Description,
                _status,
                CreatedAt,
                UpdatedAt,
                _votingData.ForVotes,
                _votingData.AgainstVotes,
                _votingData.AbstainVotes);
        }
    }

    /// <summary>
    /// A lightweight extensibility hook used by feature modules (e.g., NFT gating,
    /// quadratic voting) to attach runtime metadata to the state machine.
    /// </summary>
    public void SetExtension<T>(string key, T value) => _extensions[key] = value;

    public bool TryGetExtension<T>(string key, [MaybeNullWhen(false)] out T value)
    {
        if (_extensions.TryGetValue(key, out var boxed) && boxed is T typed)
        {
            value = typed;
            return true;
        }

        value = default;
        return false;
    }

    public void Dispose()
    {
        _disposed = true;
        _extensions.Clear();
        GC.SuppressFinalize(this);
    }

    /* ------------------------------------------------------------------ *
     *  Private  helpers
     * ------------------------------------------------------------------ */

    private void ApplyInternal(ProposalEvent @event, long weight, VotingOption option)
    {
        _logger.LogTrace(
            "Applying event {Event} to proposal {ProposalId} in state {State}",
            @event, ProposalId, _status);

        switch (_status)
        {
            case ProposalStatus.Draft:
                switch (@event)
                {
                    case ProposalEvent.Submit:
                        UpdateState(ProposalStatus.Draft); // Submitting does not change status
                        break;
                    case ProposalEvent.OpenVoting:
                        UpdateState(ProposalStatus.Voting);
                        break;
                    case ProposalEvent.Cancel:
                        UpdateState(ProposalStatus.Cancelled);
                        break;
                    default:
                        ThrowUnexpected(@event);
                        break;
                }
                break;

            case ProposalStatus.Voting:
                switch (@event)
                {
                    case ProposalEvent.CastVote:
                        ApplyVote(weight, option);
                        break;
                    case ProposalEvent.CloseVoting:
                        UpdateState(CalculateVotingOutcome());
                        break;
                    case ProposalEvent.Cancel:
                        UpdateState(ProposalStatus.Cancelled);
                        break;
                    case ProposalEvent.Expire:
                        UpdateState(ProposalStatus.Expired);
                        break;
                    default:
                        ThrowUnexpected(@event);
                        break;
                }
                break;

            case ProposalStatus.Queued:
                switch (@event)
                {
                    case ProposalEvent.Execute:
                        UpdateState(ProposalStatus.Executed);
                        break;
                    case ProposalEvent.Cancel:
                        UpdateState(ProposalStatus.Cancelled);
                        break;
                    case ProposalEvent.Expire:
                        UpdateState(ProposalStatus.Expired);
                        break;
                    default:
                        ThrowUnexpected(@event);
                        break;
                }
                break;

            case ProposalStatus.Executed:
            case ProposalStatus.Cancelled:
            case ProposalStatus.Failed:
            case ProposalStatus.Expired:
                ThrowUnexpected(@event);
                break;

            default:
                ThrowUnexpected(@event);
                break;
        }
    }

    private void ApplyVote(long weight, VotingOption option)
    {
        if (weight <= 0) throw new ArgumentOutOfRangeException(nameof(weight));

        switch (option)
        {
            case VotingOption.For:
                _votingData = _votingData with { ForVotes = checked(_votingData.ForVotes + weight) };
                break;
            case VotingOption.Against:
                _votingData = _votingData with { AgainstVotes = checked(_votingData.AgainstVotes + weight) };
                break;
            case VotingOption.Abstain:
                _votingData = _votingData with { AbstainVotes = checked(_votingData.AbstainVotes + weight) };
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(option), "Invalid voting option.");
        }

        UpdatedAt = DateTimeOffset.UtcNow;
    }

    private ProposalStatus CalculateVotingOutcome()
    {
        // Basic majority rule – override via extensions if needed.
        if (TryGetExtension<Func<VotingData, ProposalStatus>>(ExtensionKeys.CustomOutcome,
                out var customOutcome))
        {
            return customOutcome(_votingData);
        }

        if (_votingData.ForVotes > _votingData.AgainstVotes)
            return ProposalStatus.Queued;

        return ProposalStatus.Failed;
    }

    private void UpdateState(ProposalStatus newStatus)
    {
        if (newStatus == _status) return;

        _logger.LogInformation(
            "Proposal {ProposalId} transitioning {OldState} -> {NewState}",
            ProposalId, _status, newStatus);

        var previous = _status;
        _status      = newStatus;
        UpdatedAt    = DateTimeOffset.UtcNow;

        _pendingEvent = new ProposalStateChanged(ProposalId, previous, newStatus, UpdatedAt);
    }

    // Using a field avoids allocations per transition when no change occurs.
    private ProposalStateChanged? _pendingEvent;

    private async ValueTask PublishStateChangedAsync(CancellationToken ct)
    {
        if (_pendingEvent is { } domainEvent)
        {
            _pendingEvent = null;
            await _eventBus.PublishAsync(domainEvent, ct).ConfigureAwait(false);

            // Serialize for trace logs
            if (_logger.IsEnabled(LogLevel.Trace))
            {
                var json = JsonSerializer.Serialize(domainEvent);
                _logger.LogTrace("Published ProposalStateChanged: {Json}", json);
            }
        }
    }

    private void EnsureValidTransition(ProposalEvent @event)
    {
        if (_status is ProposalStatus.Executed
            or ProposalStatus.Cancelled
            or ProposalStatus.Expired
            or ProposalStatus.Failed)
        {
            throw new InvalidProposalTransitionException(
                $"Proposal is terminal ({_status}) – no further transitions allowed.");
        }

        // Additional rule: CastVote only allowed during Voting.
        if (@event == ProposalEvent.CastVote && _status != ProposalStatus.Voting)
        {
            throw new InvalidProposalTransitionException(
                $"Cannot cast vote when proposal is not in Voting state (current: {_status}).");
        }
    }

    [DoesNotReturn]
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ThrowUnexpected(ProposalEvent @event)
        => throw new InvalidProposalTransitionException($"Event '{@event}' is not valid in the current state.");

    /* ------------------------------------------------------------------ *
     *  Nested records / enums
     * ------------------------------------------------------------------ */

    private sealed record VotingData(long ForVotes, long AgainstVotes, long AbstainVotes)
    {
        public static VotingData Empty { get; } = new(0, 0, 0);
    }

    public enum VotingOption
    {
        None    = 0,
        For     = 1,
        Against = 2,
        Abstain = 3
    }

    public static class ExtensionKeys
    {
        public const string CustomOutcome = "governance.outcome.strategy";
    }
}
```