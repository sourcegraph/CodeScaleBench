```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="GovernanceService.cs" company="UtilityChain">
//     © 2024 UtilityChain Contributors. All rights reserved.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------
// ReSharper disable MemberCanBePrivate.Global
// ReSharper disable AutoPropertyCanBeMadeGetOnly.Local

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using UtilityChain.Governance.Events;
using UtilityChain.Governance.Models;
using UtilityChain.SharedKernel.Events;
using UtilityChain.SharedKernel.Time;

namespace UtilityChain.Governance;

/// <summary>
///     Central orchestrator for on-chain governance.
///     Handles proposal lifecycle, voting logic, and policy enforcement.
///     Thread-safe and event-driven.
/// </summary>
/// <remarks>
///     NOTE: This implementation keeps state in-memory. In production, persist proposals and votes to durable storage.
/// </remarks>
public sealed class GovernanceService : IGovernanceService, IDisposable
{
    private readonly ConcurrentDictionary<Guid, ProposalAggregate> _proposals = new();
    private readonly IEnumerable<IGovernancePolicy>               _policies;
    private readonly IEventBus                                     _eventBus;
    private readonly ISystemClock                                  _clock;
    private readonly ReaderWriterLockSlim                          _lifecycleLock = new();

    private bool _disposed;

    public GovernanceService(
        IEnumerable<IGovernancePolicy> policies,
        IEventBus                      eventBus,
        ISystemClock                   clock)
    {
        _policies  = policies ?? throw new ArgumentNullException(nameof(policies));
        _eventBus  = eventBus ?? throw new ArgumentNullException(nameof(eventBus));
        _clock     = clock   ?? throw new ArgumentNullException(nameof(clock));

        // Hook up reactive listeners (Observer pattern) for downstream services
        _eventBus.Subscribe<ProposalCreatedEvent>(OnProposalCreatedAsync);
        _eventBus.Subscribe<ProposalFinalizedEvent>(OnProposalFinalizedAsync);
    }

    #region IGovernanceService

    public Proposal CreateProposal(CreateProposalRequest request, CancellationToken ct = default)
    {
        ThrowIfDisposed();

        if (request is null) throw new ArgumentNullException(nameof(request));

        var proposal = new Proposal(
            Guid.NewGuid(),
            request.Title.Trim(),
            request.Description.Trim(),
            _clock.UtcNow,
            request.VotingDeadline,
            ProposalStatus.Pending);

        if (!_policies.All(p => p.ValidateProposal(proposal)))
            throw new GovernanceException("One or more policies rejected the proposal.");

        var aggregate = new ProposalAggregate(proposal);

        if (!_proposals.TryAdd(proposal.Id, aggregate))
            throw new InvalidOperationException($"Proposal ID collision occurred: {proposal.Id}");

        _eventBus.Publish(new ProposalCreatedEvent(proposal));

        return proposal;
    }

    public VoteReceipt CastVote(Guid proposalId, VoteType voteType, string voterAddress, CancellationToken ct = default)
    {
        ThrowIfDisposed();

        if (string.IsNullOrWhiteSpace(voterAddress))
            throw new ArgumentException("Voter address must be provided.", nameof(voterAddress));

        if (!_proposals.TryGetValue(proposalId, out var aggregate))
            throw new ProposalNotFoundException(proposalId);

        _lifecycleLock.EnterUpgradeableReadLock();
        try
        {
            if (aggregate.Proposal.Status is ProposalStatus.Finalized)
                throw new GovernanceException("Voting period has ended for this proposal.");

            if (aggregate.Proposal.VotingDeadline <= _clock.UtcNow)
            {
                // Attempt to finalize asynchronously—do not block caller
                _ = Task.Run(() => FinalizeAsync(aggregate, default), ct);
                throw new GovernanceException("Voting period has already elapsed.");
            }

            var vote = new Vote(
                aggregate.Proposal.Id,
                voterAddress,
                voteType,
                _clock.UtcNow);

            if (aggregate.HasVoted(voterAddress))
                throw new GovernanceException("Voter has already cast a vote on this proposal.");

            if (!_policies.All(p => p.ValidateVote(aggregate.Proposal, vote)))
                throw new GovernanceException("One or more policies rejected the vote.");

            _lifecycleLock.EnterWriteLock();
            try
            {
                aggregate.AddVote(vote);
            }
            finally
            {
                _lifecycleLock.ExitWriteLock();
            }

            _eventBus.Publish(new VoteCastEvent(vote));

            return new VoteReceipt(vote, aggregate.Tally());
        }
        finally
        {
            _lifecycleLock.ExitUpgradeableReadLock();
        }
    }

    public ProposalTally GetCurrentTally(Guid proposalId)
    {
        ThrowIfDisposed();

        if (!_proposals.TryGetValue(proposalId, out var aggregate))
            throw new ProposalNotFoundException(proposalId);

        return aggregate.Tally();
    }

    public IEnumerable<Proposal> ListProposals(ProposalStatus? status = null)
    {
        ThrowIfDisposed();

        return _proposals.Values
                         .Select(a => a.Proposal)
                         .Where(p => status is null || p.Status == status)
                         .OrderByDescending(p => p.CreatedAt)
                         .ToList(); // Materialize enumeration for thread-safety
    }

    #endregion

    #region Event Handlers

    private Task OnProposalCreatedAsync(ProposalCreatedEvent @event)
    {
        // Additional cross-cutting behavior could be executed here
        // e.g., update search index, notify users, log analytics, etc.
        return Task.CompletedTask;
    }

    private async Task OnProposalFinalizedAsync(ProposalFinalizedEvent @event)
    {
        // Dispatch post-finalization hooks in parallel
        var tasks = _policies.Select(p => p.OnProposalFinalizedAsync(@event.Proposal, @event.Tally));
        await Task.WhenAll(tasks).ConfigureAwait(false);
    }

    #endregion

    #region Lifecycle

    private async Task FinalizeAsync(ProposalAggregate aggregate, CancellationToken ct)
    {
        _lifecycleLock.EnterWriteLock();
        try
        {
            if (aggregate.Proposal.Status is ProposalStatus.Finalized)
                return; // Idempotent

            var tally = aggregate.Tally();

            var decision = _policies
                .Select(p => p.EvaluateResult(aggregate.Proposal, tally))
                .Aggregate(ProposalDecision.Undecided, CombineDecisions);

            aggregate.Finalize(_clock.UtcNow, decision);

            _eventBus.Publish(new ProposalFinalizedEvent(aggregate.Proposal, tally));
        }
        finally
        {
            _lifecycleLock.ExitWriteLock();
        }

        await Task.CompletedTask;
    }

    private static ProposalDecision CombineDecisions(ProposalDecision first, ProposalDecision second)
    {
        // If any policy rejects, the proposal is rejected.
        if (first == ProposalDecision.Rejected || second == ProposalDecision.Rejected)
            return ProposalDecision.Rejected;

        // If any policy approves and none reject, approved.
        if (first == ProposalDecision.Approved || second == ProposalDecision.Approved)
            return ProposalDecision.Approved;

        return ProposalDecision.Undecided;
    }

    #endregion

    #region IDisposable

    public void Dispose()
    {
        if (_disposed) return;

        _lifecycleLock.Dispose();
        _disposed = true;
        GC.SuppressFinalize(this);
    }

    [MemberNotNull(nameof(_lifecycleLock))]
    private void ThrowIfDisposed()
    {
        if (_disposed)
            throw new ObjectDisposedException(nameof(GovernanceService));
    }

    #endregion
}

// ====================================================================================================================
// Below are supporting types used by the GovernanceService. In a real-world project, each would live in its own file.
// ====================================================================================================================

#region Interfaces

/// <summary>Public contract for interacting with on-chain governance.</summary>
public interface IGovernanceService
{
    Proposal CreateProposal(CreateProposalRequest request, CancellationToken ct = default);

    VoteReceipt CastVote(Guid proposalId, VoteType voteType, string voterAddress, CancellationToken ct = default);

    ProposalTally GetCurrentTally(Guid proposalId);

    IEnumerable<Proposal> ListProposals(ProposalStatus? status = null);
}

/// <summary>
///     Strategy interface for governance policy. Multiple policies can be evaluated sequentially.
/// </summary>
public interface IGovernancePolicy
{
    bool ValidateProposal(Proposal proposal);

    bool ValidateVote(Proposal proposal, Vote vote);

    ProposalDecision EvaluateResult(Proposal proposal, ProposalTally tally);

    Task OnProposalFinalizedAsync(Proposal proposal, ProposalTally tally);
}

#endregion

#region Domain Models

public enum VoteType
{
    Abstain = 0,
    Yes     = 1,
    No      = 2
}

public enum ProposalStatus
{
    Pending   = 0,
    Finalized = 1
}

public enum ProposalDecision
{
    Undecided = 0,
    Approved  = 1,
    Rejected  = 2
}

public sealed record CreateProposalRequest(
    string Title,
    string Description,
    DateTimeOffset VotingDeadline);

public sealed record Proposal(
    Guid             Id,
    string           Title,
    string           Description,
    DateTimeOffset   CreatedAt,
    DateTimeOffset   VotingDeadline,
    ProposalStatus   Status,
    ProposalDecision Decision = ProposalDecision.Undecided,
    DateTimeOffset?  FinalizedAt = null);

public sealed record Vote(
    Guid           ProposalId,
    string         VoterAddress,
    VoteType       Type,
    DateTimeOffset CastAt);

/// <summary>A summary of vote counts for a proposal.</summary>
public sealed record ProposalTally(int YesCount, int NoCount, int AbstainCount)
{
    public int Total => YesCount + NoCount + AbstainCount;
}

/// <summary>
///     Immutable receipt returned to the caller after their vote is committed.
/// </summary>
public sealed record VoteReceipt(Vote Vote, ProposalTally CurrentTally);

#endregion

#region Aggregate Root

/// <summary>
///     Aggregate root encapsulating proposal state, votes, and invariants.
///     Provides concurrent-safe access without explicit locks (controlled externally).
/// </summary>
internal sealed class ProposalAggregate
{
    private readonly ConcurrentDictionary<string, Vote> _votes = new(StringComparer.Ordinal);

    public ProposalAggregate(Proposal proposal) => Proposal = proposal;

    public Proposal Proposal { get; private set; }

    public bool HasVoted(string voterAddress) => _votes.ContainsKey(voterAddress);

    public void AddVote(Vote vote)
    {
        if (!_votes.TryAdd(vote.VoterAddress, vote))
            throw new GovernanceException("Duplicate vote detected.");
    }

    public ProposalTally Tally()
    {
        var yes     = _votes.Values.Count(v => v.Type == VoteType.Yes);
        var no      = _votes.Values.Count(v => v.Type == VoteType.No);
        var abstain = _votes.Values.Count(v => v.Type == VoteType.Abstain);
        return new ProposalTally(yes, no, abstain);
    }

    public void Finalize(DateTimeOffset finalizedAt, ProposalDecision decision)
    {
        Proposal = Proposal with
        {
            Status      = ProposalStatus.Finalized,
            FinalizedAt = finalizedAt,
            Decision    = decision
        };
    }
}

#endregion

#region Policies

/// <summary>
///     Default simple-majority policy.
///     Accepts proposal if YES > NO at the end of voting deadline.
///     Requires a minimum turnout of 1 vote.
/// </summary>
public sealed class SimpleMajorityPolicy : IGovernancePolicy
{
    public bool ValidateProposal(Proposal proposal)
    {
        if (proposal.VotingDeadline <= proposal.CreatedAt)
            return false; // Deadline must be in the future

        if (proposal.VotingDeadline - proposal.CreatedAt < TimeSpan.FromHours(1))
            return false; // At least 1 hour voting window

        return true;
    }

    public bool ValidateVote(Proposal proposal, Vote vote)
    {
        // Additional anti-sybil or stake-weight checks could be inserted here
        return true;
    }

    public ProposalDecision EvaluateResult(Proposal proposal, ProposalTally tally)
    {
        if (tally.Total == 0)
            return ProposalDecision.Rejected; // No participation → reject

        return tally.YesCount > tally.NoCount
            ? ProposalDecision.Approved
            : ProposalDecision.Rejected;
    }

    public Task OnProposalFinalizedAsync(Proposal proposal, ProposalTally tally)
    {
        // Persistence or notifications can be handled here
        return Task.CompletedTask;
    }
}

#endregion

#region Exceptions

public sealed class GovernanceException : Exception
{
    public GovernanceException(string message) : base(message) { }

    public GovernanceException(string message, Exception inner) : base(message, inner) { }
}

public sealed class ProposalNotFoundException : GovernanceException
{
    public ProposalNotFoundException(Guid proposalId)
        : base($"Proposal '{proposalId}' was not found.") { }
}

#endregion
```
