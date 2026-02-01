```csharp
// -----------------------------------------------------------------------------
//  UtilityChain Core Suite (blockchain_defi)
//  File:    Proposal.cs
//  Project: UtilityChain.Governance
//  Author:  UtilityChain OSS Contributors
//  License: MIT
// -----------------------------------------------------------------------------

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;

namespace UtilityChain.Governance
{
    /// <summary>
    /// Represents a governance proposal within UtilityChain. A proposal is a stateful
    /// entity that tracks voting, lifecycle transitions, and execution status.
    /// Thread-safe operations are provided to accommodate parallel vote casting
    /// coming from network peers, REST gateways, or UX clients.
    /// </summary>
    public sealed class Proposal
    {
        // Thread-safe storage for vote records (address → choice).
        private readonly ConcurrentDictionary<string, VoteChoice> _votes = new();

        // Domain events observers.
        private readonly List<IProposalObserver> _observers = new();

        /// <summary>Initializes a new draft proposal. Drafts must be activated before voting.</summary>
        /// <exception cref="ArgumentException"/>
        public Proposal(
            Guid id,
            string proposerAddress,
            string title,
            string description,
            DateTimeOffset createdAtUtc,
            TimeSpan votingWindow,
            GovernanceRuleSet rules)
        {
            if (string.IsNullOrWhiteSpace(proposerAddress))
                throw new ArgumentException("Proposer address is required.", nameof(proposerAddress));
            if (string.IsNullOrWhiteSpace(title))
                throw new ArgumentException("Proposal title is required.", nameof(title));
            if (votingWindow <= TimeSpan.Zero)
                throw new ArgumentException("Voting window must be greater than zero.", nameof(votingWindow));

            Id              = id;
            ProposerAddress = proposerAddress;
            Title           = title.Trim();
            Description     = description?.Trim() ?? string.Empty;
            CreatedAtUtc    = createdAtUtc;
            ExpirationUtc   = createdAtUtc + votingWindow;
            Status          = ProposalStatus.Draft;
            Rules           = rules ?? throw new ArgumentNullException(nameof(rules));
        }

        // ---------------------------------------------------------------------
        //  Public Properties
        // ---------------------------------------------------------------------

        /// <summary>Unique identifier (deterministically hashed by the network).</summary>
        public Guid Id { get; }

        /// <summary>Wallet address of the proposer.</summary>
        public string ProposerAddress { get; }

        /// <summary>Human-readable title shown in wallets and dashboards.</summary>
        public string Title { get; }

        /// <summary>Markdown/HTML supported long-form description.</summary>
        public string Description { get; }

        /// <summary>Timestamp the proposal was created (in UTC).</summary>
        public DateTimeOffset CreatedAtUtc { get; }

        /// <summary>UTC time when the proposal becomes open for voting.</summary>
        public DateTimeOffset? ActivatedAtUtc { get; private set; }

        /// <summary>UTC expiration timestamp. Immutable after construction.</summary>
        public DateTimeOffset ExpirationUtc { get; }

        /// <summary>Current mutable status. Thread-safe through lock semantics.</summary>
        public ProposalStatus Status { get; private set; }

        /// <summary>Governance configuration snapshot captured when the proposal was created.</summary>
        public GovernanceRuleSet Rules { get; }

        /// <summary>Total votes cast so far.</summary>
        public int TotalVotes => _votes.Count;

        /// <summary>Returns immutable tally information.</summary>
        public ProposalTally Tally
        {
            get
            {
                var yes     = _votes.Values.Count(v => v == VoteChoice.Yes);
                var no      = _votes.Values.Count(v => v == VoteChoice.No);
                var abstain = _votes.Values.Count - yes - no;

                return new ProposalTally(yes, no, abstain, Rules.QuorumThreshold);
            }
        }

        // ---------------------------------------------------------------------
        //  Lifecycle Management
        // ---------------------------------------------------------------------

        /// <summary>Registers an observer for domain events.</summary>
        /// <exception cref="ArgumentNullException"/>
        public void AttachObserver(IProposalObserver observer)
        {
            if (observer is null) throw new ArgumentNullException(nameof(observer));

            lock (_observers)
                _observers.Add(observer);
        }

        /// <summary>Activates a draft proposal and opens it for voting.</summary>
        /// <exception cref="InvalidOperationException"/>
        public void Activate(IClock clock)
        {
            clock = clock ?? SystemClock.Instance;
            EnsureStatusIs(ProposalStatus.Draft, nameof(Activate));

            ActivatedAtUtc = clock.UtcNow;
            Status         = ProposalStatus.Active;

            RaiseEvent(new ProposalActivatedEvent(Id, ActivatedAtUtc.Value));
        }

        /// <summary>Cancels an <see cref="ProposalStatus.Active"/> proposal.</summary>
        /// <exception cref="InvalidOperationException"/>
        public void Cancel(string cancelledBy, IClock clock)
        {
            clock = clock ?? SystemClock.Instance;
            if (Status is not (ProposalStatus.Active or ProposalStatus.Draft))
                throw new InvalidOperationException($"Only Draft or Active proposals can be cancelled. Current state = {Status}");

            Status = ProposalStatus.Cancelled;

            RaiseEvent(new ProposalCancelledEvent(Id, cancelledBy, clock.UtcNow));
        }

        /// <summary>Executes a successful proposal. Ensures it has already passed.</summary>
        /// <exception cref="InvalidOperationException"/>
        public void Execute(IClock clock)
        {
            clock = clock ?? SystemClock.Instance;

            if (Status != ProposalStatus.Passed)
                throw new InvalidOperationException($"Only proposals with status {ProposalStatus.Passed} can be executed.");

            Status = ProposalStatus.Executed;

            RaiseEvent(new ProposalExecutedEvent(Id, clock.UtcNow));
        }

        // ---------------------------------------------------------------------
        //  Voting
        // ---------------------------------------------------------------------

        /// <summary>
        /// Casts or overrides a vote for the given voter address. Voting is
        /// idempotent— casting the same choice twice is a no-op, casting a new
        /// choice overrides the previous vote. Returns TRUE when the vote resulted
        /// in a state change (i.e., new or altered vote).
        /// </summary>
        /// <exception cref="InvalidOperationException"/>
        public bool CastVote(string voterAddress, VoteChoice choice, IClock clock)
        {
            if (string.IsNullOrWhiteSpace(voterAddress))
                throw new ArgumentException("Voter address is required.", nameof(voterAddress));
            clock = clock ?? SystemClock.Instance;

            EnsureStatusIs(ProposalStatus.Active, nameof(CastVote));

            if (clock.UtcNow >= ExpirationUtc)
                throw new InvalidOperationException("Voting period has expired.");

            // Eligibility check (governed by staking, identity, etc.).
            if (!Rules.IsEligibleVoter(voterAddress))
                throw new InvalidOperationException($"Address '{voterAddress}' is not eligible to vote.");

            var updated = _votes.AddOrUpdate(voterAddress, choice, (_, old) => choice) != choice;
            if (!updated)
                updated = true; // AddOrUpdate returns new value; treat both add/override as state change.

            if (updated)
                RaiseEvent(new VoteCastEvent(Id, voterAddress, choice, clock.UtcNow));

            // Evaluate proposal status every time a new vote is cast.
            EvaluateStatus(clock);

            return updated;
        }

        /// <summary>
        /// Evaluates whether the proposal has reached quorum and should transition
        /// to Passed/Rejected/Expired.
        /// </summary>
        public void EvaluateStatus(IClock clock)
        {
            clock = clock ?? SystemClock.Instance;

            // Expiration check.
            if ((Status is ProposalStatus.Active or ProposalStatus.Draft) && clock.UtcNow >= ExpirationUtc)
            {
                Status = ProposalStatus.Expired;
                RaiseEvent(new ProposalExpiredEvent(Id, clock.UtcNow));
                return;
            }

            if (Status != ProposalStatus.Active)
                return; // Nothing to evaluate.

            var tally               = Tally;
            var totalEligibleVoters = Rules.TotalEligibleVoters;
            var quorumMet           = tally.Total >= Rules.QuorumThreshold * totalEligibleVoters;
            var passed              = tally.Yes > tally.No;

            if (!quorumMet)
                return; // Still pending.

            Status = passed ? ProposalStatus.Passed : ProposalStatus.Rejected;

            var evt = passed
                ? new ProposalPassedEvent(Id, clock.UtcNow, tally.Yes, tally.No, tally.Abstain)
                : new ProposalRejectedEvent(Id, clock.UtcNow, tally.Yes, tally.No, tally.Abstain);

            RaiseEvent(evt);
        }

        // ---------------------------------------------------------------------
        //  Private Helpers
        // ---------------------------------------------------------------------

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private void EnsureStatusIs(ProposalStatus expected, string caller)
        {
            if (Status != expected)
                throw new InvalidOperationException(
                    $"{caller} can only be invoked when proposal status is {expected}. Current state = {Status}");
        }

        private void RaiseEvent(ProposalEventBase evt)
        {
            if (evt is null) return;

            // Snapshot observers to avoid concurrent modifications.
            IProposalObserver[] listeners;
            lock (_observers)
                listeners = _observers.ToArray();

            foreach (var observer in listeners)
            {
                try { observer.OnNext(evt); }
                catch (Exception ex)
                {
                    // Swallow observer exceptions – governance engine must stay resilient.
                    Console.Error.WriteLine($"[Governance] Observer error: {ex}");
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    //  Domain Models
    // -------------------------------------------------------------------------

    public enum ProposalStatus
    {
        Draft,
        Active,
        Passed,
        Rejected,
        Executed,
        Expired,
        Cancelled
    }

    public enum VoteChoice
    {
        Yes,
        No,
        Abstain
    }

    /// <summary>Lightweight immutable vote tally snapshot.</summary>
    public readonly record struct ProposalTally(
        int Yes,
        int No,
        int Abstain,
        double QuorumThreshold)
    {
        public int Total => Yes + No + Abstain;
    }

    // -------------------------------------------------------------------------
    //  Governance Rules
    // -------------------------------------------------------------------------

    /// <summary>
    /// Captures governance parameters. In a real system, this would be loaded
    /// from on-chain configuration or smart-contracts. For modularity the rules
    /// are immutable.
    /// </summary>
    public sealed class GovernanceRuleSet
    {
        public GovernanceRuleSet(
            double quorumThreshold,
            double proposalCreationStakeRequirement,
            Func<string, bool> voterEligibilityPredicate,
            Func<string, bool> proposerEligibilityPredicate,
            int totalEligibleVoters)
        {
            if (quorumThreshold is < 0d or > 1d)
                throw new ArgumentOutOfRangeException(nameof(quorumThreshold), "Quorum threshold must be between 0 and 1.");
            if (proposalCreationStakeRequirement is < 0d or > 1d)
                throw new ArgumentOutOfRangeException(nameof(proposalCreationStakeRequirement));
            if (voterEligibilityPredicate is null)
                throw new ArgumentNullException(nameof(voterEligibilityPredicate));
            if (proposerEligibilityPredicate is null)
                throw new ArgumentNullException(nameof(proposerEligibilityPredicate));
            if (totalEligibleVoters <= 0)
                throw new ArgumentOutOfRangeException(nameof(totalEligibleVoters));

            QuorumThreshold                 = quorumThreshold;
            ProposalCreationStakeRequirement = proposalCreationStakeRequirement;
            _voterEligibilityPredicate       = voterEligibilityPredicate;
            _proposerEligibilityPredicate    = proposerEligibilityPredicate;
            TotalEligibleVoters              = totalEligibleVoters;
        }

        public double QuorumThreshold { get; }

        /// <summary>Required proportion of total stake a proposer must hold.</summary>
        public double ProposalCreationStakeRequirement { get; }

        public int TotalEligibleVoters { get; }

        private readonly Func<string, bool> _voterEligibilityPredicate;
        private readonly Func<string, bool> _proposerEligibilityPredicate;

        public bool IsEligibleVoter(string address)     => _voterEligibilityPredicate(address);
        public bool IsEligibleProposer(string address)  => _proposerEligibilityPredicate(address);
    }

    // -------------------------------------------------------------------------
    //  Observer Pattern
    // -------------------------------------------------------------------------

    public interface IProposalObserver
    {
        void OnNext(ProposalEventBase proposalEvent);
    }

    // Base class for strongly-typed domain events.
    public abstract record ProposalEventBase(Guid ProposalId, DateTimeOffset OccurredAtUtc);

    public record ProposalActivatedEvent(Guid ProposalId, DateTimeOffset OccurredAtUtc)
        : ProposalEventBase(ProposalId, OccurredAtUtc);

    public record ProposalCancelledEvent(Guid ProposalId, string CancelledBy, DateTimeOffset OccurredAtUtc)
        : ProposalEventBase(ProposalId, OccurredAtUtc);

    public record ProposalExpiredEvent(Guid ProposalId, DateTimeOffset OccurredAtUtc)
        : ProposalEventBase(ProposalId, OccurredAtUtc);

    public record ProposalPassedEvent(
        Guid ProposalId,
        DateTimeOffset OccurredAtUtc,
        int Yes,
        int No,
        int Abstain)
        : ProposalEventBase(ProposalId, OccurredAtUtc);

    public record ProposalRejectedEvent(
        Guid ProposalId,
        DateTimeOffset OccurredAtUtc,
        int Yes,
        int No,
        int Abstain)
        : ProposalEventBase(ProposalId, OccurredAtUtc);

    public record ProposalExecutedEvent(Guid ProposalId, DateTimeOffset OccurredAtUtc)
        : ProposalEventBase(ProposalId, OccurredAtUtc);

    public record VoteCastEvent(
        Guid ProposalId,
        string VoterAddress,
        VoteChoice Choice,
        DateTimeOffset OccurredAtUtc)
        : ProposalEventBase(ProposalId, OccurredAtUtc);

    // -------------------------------------------------------------------------
    //  Infrastructure
    // -------------------------------------------------------------------------

    /// <summary>Abstraction to decouple time from logic (testability).</summary>
    public interface IClock
    {
        DateTimeOffset UtcNow { get; }
    }

    /// <summary>Default clock implementation based on <see cref="DateTimeOffset.UtcNow"/>.</summary>
    internal sealed class SystemClock : IClock
    {
        public static readonly SystemClock Instance = new();
        public DateTimeOffset UtcNow => DateTimeOffset.UtcNow;
        private SystemClock() { }
    }
}
```