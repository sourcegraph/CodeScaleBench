```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Governance/Policies/MajorityVotePolicy.cs

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using UtilityChain.Governance.Events;
using UtilityChain.Governance.Models;
using UtilityChain.Governance.State;
using UtilityChain.SharedKernel;
using UtilityChain.SharedKernel.Guards;

namespace UtilityChain.Governance.Policies;

/// <summary>
/// Majority-rule voting policy with configurable quorum and majority thresholds.
/// </summary>
/// <remarks>
///     This class is registered as an <see cref="IVotingPolicy"/> strategy through DI
///     and is selected at runtime by <see cref="Proposal.VotingPolicyKey"/>.  
/// </remarks>
public sealed class MajorityVotePolicy : IVotingPolicy, IDisposable
{
    #region ctor / fields

    private readonly IGovernanceStateProvider _stateProvider;
    private readonly IEventBus _eventBus;
    private readonly ILogger<MajorityVotePolicy> _logger;

    private readonly decimal _quorumPct;
    private readonly decimal _majorityPct;
    private readonly decimal _vetoPct;
    private readonly TimeSpan _gracePeriod;

    private readonly IDisposable _proposalClosedSub;
    private readonly IDisposable _voteCastSub;

    private readonly SemaphoreSlim _evaluationMutex = new(1, 1);

    public MajorityVotePolicy(
        IGovernanceStateProvider stateProvider,
        IEventBus eventBus,
        IOptions<MajorityVotePolicyOptions> options,
        ILogger<MajorityVotePolicy> logger)
    {
        Guard.NotNull(stateProvider);
        Guard.NotNull(eventBus);
        Guard.NotNull(options);
        Guard.NotNull(logger);

        _stateProvider = stateProvider;
        _eventBus      = eventBus;
        _logger        = logger;

        _quorumPct    = options.Value.QuorumPercentage;
        _majorityPct  = options.Value.SimpleMajorityPercentage;
        _vetoPct      = options.Value.VetoPercentage;
        _gracePeriod  = options.Value.GracePeriod;

        // Subscribe to relevant domain events so proposals are evaluated automatically.
        _proposalClosedSub = _eventBus.SubscribeAsync<ProposalClosedEvent>(OnProposalClosedAsync);
        _voteCastSub       = _eventBus.SubscribeAsync<VoteCastEvent>(OnVoteCastAsync);

        _logger.LogInformation(
            "MajorityVotePolicy instantiated: quorum={Quorum:P}, majority={Majority:P}, veto={Veto:P}, grace={Grace}",
            _quorumPct,
            _majorityPct,
            _vetoPct,
            _gracePeriod);
    }

    #endregion

    #region Public API

    /// <inheritdoc />
    public ValueTask EvaluateAsync(ProposalId proposalId, CancellationToken ct = default)
        => EvaluateInternalAsync(proposalId, false, ct);

    #endregion

    #region Event-Driven Evaluation

    private ValueTask OnProposalClosedAsync(ProposalClosedEvent e, CancellationToken ct)
        => EvaluateInternalAsync(e.ProposalId, true, ct);

    private ValueTask OnVoteCastAsync(VoteCastEvent e, CancellationToken ct)
    {
        // A proposal can optionally be set to "auto-close" once consensus is certain,
        // but we only trigger re-evaluation if inside the active window.
        var proposal = _stateProvider.Proposals.Get(e.ProposalId);
        if (proposal is null) return ValueTask.CompletedTask;

        if (proposal.Status is ProposalStatus.Open)
        {
            return EvaluateInternalAsync(proposal.Id, false, ct);
        }

        return ValueTask.CompletedTask;
    }

    #endregion

    #region Evaluation Logic

    private async ValueTask EvaluateInternalAsync(ProposalId proposalId, bool closed, CancellationToken ct)
    {
        await _evaluationMutex.WaitAsync(ct).ConfigureAwait(false);

        try
        {
            var proposal = _stateProvider.Proposals.Get(proposalId);
            if (proposal is null)
            {
                _logger.LogWarning("Proposal {ProposalId} not found during evaluation.", proposalId);
                return;
            }

            if (proposal.Status is ProposalStatus.Finalized)
                return; // nothing to do.

            // If the proposal has not elapsed its grace period, skip unless forcible (closed).
            if (!closed && proposal.EndAt + _gracePeriod > _stateProvider.ChainTime.Now)
                return;

            // Build a summary of voting power distribution.
            var summary = BuildSummary(proposal);

            // Determine outcome.
            var outcome = DetermineOutcome(summary, proposal.RequiredSupport);

            // Commit outcome.
            proposal.Finalize(outcome, summary);

            // Publish domain event.
            await _eventBus.PublishAsync(new ProposalFinalizedEvent(proposal.Id, outcome, summary), ct)
                           .ConfigureAwait(false);

            _logger.LogInformation(
                "Proposal {ProposalId} finalized with outcome {Outcome}. (Yes={Yes:N0}, No={No:N0}, Veto={Veto:N0}, Abstain={Abstain:N0}, Participation={Participation:P})",
                proposal.Id,
                outcome,
                summary.YesPower,
                summary.NoPower,
                summary.VetoPower,
                summary.AbstainPower,
                summary.ParticipationRate);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to evaluate proposal {ProposalId}.", proposalId);
        }
        finally
        {
            _evaluationMutex.Release();
        }
    }

    private static VoteSummary BuildSummary(Proposal proposal)
    {
        var yes     = 0m;
        var no      = 0m;
        var abstain = 0m;
        var veto    = 0m;

        foreach (var vote in proposal.Votes)
        {
            switch (vote.Type)
            {
                case VoteType.Yes:
                    yes += vote.Power;
                    break;
                case VoteType.No:
                    no += vote.Power;
                    break;
                case VoteType.Abstain:
                    abstain += vote.Power;
                    break;
                case VoteType.Veto:
                    veto += vote.Power;
                    break;
            }
        }

        var totalParticipating = yes + no + abstain + veto;

        return new VoteSummary(
            yes,
            no,
            abstain,
            veto,
            totalParticipating,
            proposal.TotalEligiblePower);
    }

    private ProposalOutcome DetermineOutcome(VoteSummary summary, RequiredSupport requiredSupport)
    {
        // Check quorum
        if (summary.ParticipationRate < _quorumPct)
            return ProposalOutcome.Defeated; // quorum not reached

        // Check veto
        if (summary.ParticipationRate > 0 && (summary.VetoPower / summary.ParticipatingPower) >= _vetoPct)
            return ProposalOutcome.Vetoed;

        // Calculate majority
        var yesRate = summary.YesPower / summary.ParticipatingPower;

        var threshold = requiredSupport switch
        {
            RequiredSupport.SuperMajority => 0.66m,
            RequiredSupport.Absolute      => _majorityPct,
            _                              => _majorityPct
        };

        return yesRate >= threshold
            ? ProposalOutcome.Passed
            : ProposalOutcome.Defeated;
    }

    #endregion

    #region IDisposable

    public void Dispose()
    {
        _proposalClosedSub?.Dispose();
        _voteCastSub?.Dispose();
        _evaluationMutex?.Dispose();
        GC.SuppressFinalize(this);
    }

    #endregion
}

/// <summary>
/// Options governing the behavior of <see cref="MajorityVotePolicy"/>.
/// </summary>
public sealed record MajorityVotePolicyOptions
{
    /// <summary>
    /// Minimum percentage of total voting power required for a proposal to be valid (0-1).
    /// </summary>
    public decimal QuorumPercentage { get; init; } = 0.40m;

    /// <summary>
    /// Percentage of affirmative votes required to pass a proposal (0-1).
    /// </summary>
    public decimal SimpleMajorityPercentage { get; init; } = 0.50m;

    /// <summary>
    /// Percentage of veto votes required to automatically reject a proposal (0-1).
    /// </summary>
    public decimal VetoPercentage { get; init; } = 0.33m;

    /// <summary>
    /// Additional time after <see cref="Proposal.EndAt"/> to allow late votes before evaluation.
    /// </summary>
    public TimeSpan GracePeriod { get; init; } = TimeSpan.FromHours(1);
}

#region Internal DTOs

/// <summary>
/// Aggregated voting statistics for a proposal.
/// </summary>
public readonly record struct VoteSummary(
    decimal YesPower,
    decimal NoPower,
    decimal AbstainPower,
    decimal VetoPower,
    decimal ParticipatingPower,
    decimal EligiblePower)
{
    public decimal ParticipationRate =>
        EligiblePower == 0 ? 0 : ParticipatingPower / EligiblePower;
}

#endregion
```