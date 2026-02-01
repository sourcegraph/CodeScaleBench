```csharp
using System;
using System.Diagnostics.CodeAnalysis;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Staking
{
    /// <summary>
    /// Globally unique identifier for a stake position.
    /// Wrapper type prevents accidental mixing with <see cref="Guid"/>.
    /// </summary>
    public readonly record struct StakeId(Guid Value)
    {
        public static StakeId New() => new(Guid.NewGuid());

        public override string ToString() => Value.ToString("N");
    }

    /// <summary>
    /// Enumerates the lifecycle states of a <see cref="Stake"/>.
    /// </summary>
    public enum StakeStatus : byte
    {
        /// <summary>The stake request has been created but is not yet bonded.</summary>
        Pending = 0,

        /// <summary>The stake is bonded and accruing rewards.</summary>
        Active,

        /// <summary>The stake has been withdrawn and will no longer accrue rewards.</summary>
        Completed,

        /// <summary>The stake has been slashed for validator misbehaviour.</summary>
        Slashed
    }

    /// <summary>
    /// Describes an event that affects a <see cref="Stake"/>.
    /// This file only defines the interface; concrete implementations are emitted by an Event Sourcing package.
    /// </summary>
    public interface IStakeDomainEvent
    {
        DateTimeOffset Timestamp { get; }
        StakeId AggregateId { get; }
    }

    /// <summary>
    /// Publishes domain events into an in-process event bus.
    /// Keeping the interface minimal allows decoupling from the underlying implementation (Proxy Pattern).
    /// </summary>
    public interface IEventPublisher
    {
        ValueTask PublishAsync<TEvent>(TEvent @event, CancellationToken ct = default)
            where TEvent : IStakeDomainEvent;
    }

    /// <summary>
    /// Strategy abstraction for reward calculation.
    /// Implementation may vary depending on consensus algorithm or business rules.
    /// </summary>
    public interface IRewardCalculator
    {
        /// <summary>
        /// Calculates the reward for a stake given the elapsed period.
        /// </summary>
        /// <param name="stakeAmount">Original bonded amount that remains active.</param>
        /// <param name="elapsed">Time since the stake became active.</param>
        /// <returns>The reward denominated in the same asset as <paramref name="stakeAmount"/>.</returns>
        decimal CalculateReward(decimal stakeAmount, TimeSpan elapsed);
    }

    /// <summary>
    /// Represents a single staking position within the chain.
    /// Stake objects are stateful and not thread-safe; external synchronization is required if
    /// they are shared across threads.
    /// </summary>
    public sealed class Stake
    {
        private readonly ILogger<Stake> _log;
        private readonly IRewardCalculator _rewardCalculator;
        private readonly IEventPublisher _eventPublisher;

        private readonly object _gate = new();

        // --- Backing fields --------------------------------------------------
        private decimal _principal;
        private decimal _unclaimedRewards;

        // ------------------ ctor --------------------------------------------
        public Stake(
            StakeId id,
            string delegatorAddress,
            string validatorAddress,
            decimal amount,
            ILogger<Stake> log,
            IRewardCalculator rewardCalculator,
            IEventPublisher eventPublisher)
        {
            ArgumentNullException.ThrowIfNull(log);
            ArgumentNullException.ThrowIfNull(rewardCalculator);
            ArgumentNullException.ThrowIfNull(eventPublisher);

            if (amount <= 0)
                throw new ArgumentOutOfRangeException(nameof(amount), "Staking amount must be positive.");

            Id = id;
            DelegatorAddress = delegatorAddress ?? throw new ArgumentNullException(nameof(delegatorAddress));
            ValidatorAddress = validatorAddress ?? throw new ArgumentNullException(nameof(validatorAddress));
            _principal = amount;

            _log = log;
            _rewardCalculator = rewardCalculator;
            _eventPublisher = eventPublisher;

            CreatedAt = DateTimeOffset.UtcNow;
            Status = StakeStatus.Pending;

            _log.LogInformation("[{StakeId}] Stake created for delegator {Delegator} attempting to bond {Amount}",
                id, delegatorAddress, amount);
        }

        // ------------------ Public properties -------------------------------
        public StakeId Id { get; }

        public string DelegatorAddress { get; }

        public string ValidatorAddress { get; }

        /// <summary>Date when the stake object was instantiated.</summary>
        public DateTimeOffset CreatedAt { get; }

        /// <summary>Date when the stake became active (bonded).</summary>
        public DateTimeOffset? ActivatedAt { get; private set; }

        /// <summary>Date when the stake finished (withdrawn or slashed).</summary>
        public DateTimeOffset? CompletedAt { get; private set; }

        public StakeStatus Status { get; private set; }

        /// <summary>
        /// Principal amount still bonded (excludes rewards).
        /// </summary>
        public decimal Principal
        {
            get
            {
                lock (_gate) { return _principal; }
            }
        }

        /// <summary>Rewards that have accrued but not yet claimed.</summary>
        public decimal UnclaimedRewards
        {
            get
            {
                lock (_gate) { return _unclaimedRewards; }
            }
        }

        // ------------------ Behaviour ---------------------------------------

        /// <summary>
        /// Triggers the state transition from <see cref="StakeStatus.Pending"/> to <see cref="StakeStatus.Active"/>.
        /// </summary>
        public async ValueTask ActivateAsync(CancellationToken ct = default)
        {
            lock (_gate)
            {
                EnsureState(StakeStatus.Pending);
                Status = StakeStatus.Active;
                ActivatedAt = DateTimeOffset.UtcNow;
            }

            await _eventPublisher.PublishAsync(
                new StakeActivated(Id, ActivatedAt!.Value),
                ct).ConfigureAwait(false);

            _log.LogInformation("[{StakeId}] Stake activated at {Timestamp}", Id, ActivatedAt);
        }

        /// <summary>
        /// Calculates the current reward and returns the cumulative value without resetting <see cref="UnclaimedRewards"/>.
        /// </summary>
        public decimal PeekCurrentReward(DateTimeOffset asOf)
        {
            lock (_gate)
            {
                EnsureState(StakeStatus.Active);

                if (ActivatedAt == null)
                {
                    _log.LogWarning("[{StakeId}] PeekCurrentReward called before activation", Id);
                    return 0m;
                }

                var reward = _rewardCalculator.CalculateReward(_principal, asOf - ActivatedAt.Value);
                return reward + _unclaimedRewards;
            }
        }

        /// <summary>
        /// Claims the currently accumulated reward, resetting the counter to zero.
        /// </summary>
        /// <exception cref="InvalidOperationException">If stake is not active.</exception>
        public async ValueTask<decimal> ClaimRewardAsync(DateTimeOffset asOf, CancellationToken ct = default)
        {
            decimal reward;
            lock (_gate)
            {
                EnsureState(StakeStatus.Active);
                reward = _rewardCalculator.CalculateReward(_principal, asOf - ActivatedAt!.Value);
                _unclaimedRewards += reward;
                _rewardCalculator.CalculateReward(_principal, asOf - ActivatedAt!.Value);

                // Reset activation timestamp so that next accrual starts from now
                ActivatedAt = asOf;
                reward = _unclaimedRewards;
                _unclaimedRewards = 0m;
            }

            await _eventPublisher.PublishAsync(
                new RewardClaimed(Id, reward, asOf),
                ct).ConfigureAwait(false);

            _log.LogInformation("[{StakeId}] Delegator {Delegator} claimed reward {Reward}", Id, DelegatorAddress, reward);
            return reward;
        }

        /// <summary>
        /// Withdraws the stake (principal + unclaimed rewards) and marks the stake as <see cref="StakeStatus.Completed"/>.
        /// </summary>
        /// <remarks>For simplicity, rewards are automatically claimed as part of withdrawal.</remarks>
        public async ValueTask<decimal> WithdrawAsync(DateTimeOffset asOf, CancellationToken ct = default)
        {
            decimal totalReturn;

            lock (_gate)
            {
                EnsureState(StakeStatus.Active);

                var reward = _rewardCalculator.CalculateReward(_principal, asOf - ActivatedAt!.Value);
                totalReturn = _principal + reward + _unclaimedRewards;
                _principal = 0m;
                _unclaimedRewards = 0m;
                Status = StakeStatus.Completed;
                CompletedAt = asOf;
            }

            await _eventPublisher.PublishAsync(
                new StakeWithdrawn(Id, totalReturn, asOf),
                ct).ConfigureAwait(false);

            _log.LogInformation("[{StakeId}] Stake withdrawn. Total returned to delegator: {Total}", Id, totalReturn);
            return totalReturn;
        }

        /// <summary>
        /// Reduces the principal as a penalty and moves the stake to <see cref="StakeStatus.Slashed"/>.
        /// </summary>
        /// <param name="slashPercentage">Percentage (0-1) of principal to slash.</param>
        public async ValueTask SlashAsync(
            [Range(0.0, 1.0)] double slashPercentage,
            DateTimeOffset asOf,
            CancellationToken ct = default)
        {
            if (slashPercentage is < 0 or > 1)
                throw new ArgumentOutOfRangeException(nameof(slashPercentage), "Percentage must be between 0 and 1.");

            decimal slashAmount;
            lock (_gate)
            {
                EnsureState(StakeStatus.Active);

                slashAmount = decimal.Round(_principal * (decimal)slashPercentage, 8);
                _principal -= slashAmount;

                Status = StakeStatus.Slashed;
                CompletedAt = asOf;
            }

            await _eventPublisher.PublishAsync(
                new StakeSlashed(Id, slashAmount, asOf),
                ct).ConfigureAwait(false);

            _log.LogWarning("[{StakeId}] Stake slashed by {SlashPercentage:P}. Amount burned: {SlashAmount}",
                Id, slashPercentage, slashAmount);
        }

        // ------------------ Internal helpers --------------------------------
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private void EnsureState(StakeStatus expected)
        {
            if (Status != expected)
            {
                throw new InvalidOperationException(
                    $"Stake {Id} must be in state '{expected}' but is '{Status}'.");
            }
        }

        #region Domain Events

        // Domain events are internal record classes used by the event bus
        private sealed record StakeActivated(StakeId AggregateId, DateTimeOffset Timestamp) : IStakeDomainEvent;

        private sealed record RewardClaimed(StakeId AggregateId, decimal Reward, DateTimeOffset Timestamp) : IStakeDomainEvent;

        private sealed record StakeWithdrawn(StakeId AggregateId, decimal TotalReturned, DateTimeOffset Timestamp) : IStakeDomainEvent;

        private sealed record StakeSlashed(StakeId AggregateId, decimal AmountSlashed, DateTimeOffset Timestamp) : IStakeDomainEvent;

        #endregion
    }

    /// <summary>
    /// Simple APY based calculator used as default strategy when no consensus-specific calculator is provided.
    /// </summary>
    public sealed class FixedApyRewardCalculator : IRewardCalculator
    {
        private readonly decimal _annualPercentageYield;

        public FixedApyRewardCalculator(decimal annualPercentageYield)
        {
            if (annualPercentageYield < 0)
                throw new ArgumentOutOfRangeException(nameof(annualPercentageYield), "APY must be non-negative.");

            _annualPercentageYield = annualPercentageYield;
        }

        public decimal CalculateReward(decimal stakeAmount, TimeSpan elapsed)
        {
            // Continuous compounding approximation: reward = P * (e^(r*t) - 1)
            double r = (double)_annualPercentageYield;
            double t = elapsed.TotalDays / 365.25d;
            decimal reward = stakeAmount * (decimal)(Math.Exp(r * t) - 1);
            return decimal.Round(reward, 8);
        }
    }
}
```