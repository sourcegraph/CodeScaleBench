using System;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Staking.Strategies
{
    #region Abstractions & DTOs

    /// <summary>
    /// Contract that every staking–reward strategy must fulfil.
    /// The implementation is expected to be stateless and thread-safe.
    /// </summary>
    public interface IRewardStrategy
    {
        /// <summary>
        /// Calculates the reward for the supplied stake position.
        /// </summary>
        /// <param name="stake">Stake metadata.</param>
        /// <param name="asOfUtc">Point-in-time (UTC) that caps the calculation.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <returns>Encapsulated reward result.</returns>
        ValueTask<RewardResult> CalculateAsync(
            StakePosition stake,
            DateTimeOffset asOfUtc,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Immutable value object representing a user’s stake position.
    /// All monetary amounts are expressed in the protocol’s base unit (decimals).
    /// </summary>
    /// <param name="PositionId">Deterministic identifier of the stake.</param>
    /// <param name="StakerAddress">Unique wallet address of the staker.</param>
    /// <param name="Principal">Staked amount in protocol tokens.</param>
    /// <param name="StartUtc">Timestamp when the position was opened.</param>
    /// <param name="LockPeriod">Requested lock-in period (0 for flexible).</param>
    public sealed record StakePosition(
        Guid PositionId,
        string StakerAddress,
        decimal Principal,
        DateTimeOffset StartUtc,
        TimeSpan LockPeriod);

    /// <summary>
    /// Reward calculation outcome.
    /// </summary>
    /// <param name="PositionId">Stake identifier that the reward belongs to.</param>
    /// <param name="RewardAmount">Calculated reward (0 if not eligible).</param>
    /// <param name="CalculatedAtUtc">Timestamp when the reward was computed.</param>
    public sealed record RewardResult(
        Guid PositionId,
        decimal RewardAmount,
        DateTimeOffset CalculatedAtUtc);

    #endregion

    /// <summary>
    /// Configuration object describing a fixed-rate strategy.
    /// </summary>
    /// <param name="AnnualRate">
    /// APR/APY expressed as <c>0.12m</c> → 12 %.
    /// Must be in the range [0, 5] (0 %…500 %).
    /// </param>
    /// <param name="CompoundingInterval">
    /// Frequency at which interest is compounded (<see cref="TimeSpan.Zero"/> disables compounding).
    /// </param>
    /// <param name="MinimumStakeAge">
    /// Minimum duration the stake must be active before it starts earning rewards.
    /// </param>
    public sealed record FixedRewardConfig(
        decimal AnnualRate,
        TimeSpan CompoundingInterval,
        TimeSpan MinimumStakeAge)
    {
        public FixedRewardConfig : this(AnnualRate, CompoundingInterval, MinimumStakeAge)
        {
            if (AnnualRate is < 0m or > 5m)
                throw new ArgumentOutOfRangeException(nameof(AnnualRate), AnnualRate,
                    "AnnualRate must be between 0 and 5 (0 % – 500 %).");

            if (CompoundingInterval < TimeSpan.Zero)
                throw new ArgumentOutOfRangeException(nameof(CompoundingInterval), CompoundingInterval,
                    "CompoundingInterval cannot be negative.");

            if (MinimumStakeAge < TimeSpan.Zero)
                throw new ArgumentOutOfRangeException(nameof(MinimumStakeAge), MinimumStakeAge,
                    "MinimumStakeAge cannot be negative.");
        }
    }

    /// <summary>
    /// Fixed-rate reward strategy.<br/>
    /// <list type="bullet">
    ///     <item>Rewards are calculated from a constant APR/APY.</item>
    ///     <item>Optional compounding is supported by specifying a non-zero interval.</item>
    ///     <item>Stake must satisfy a minimum age before any reward accrues.</item>
    /// </list>
    /// </summary>
    public sealed class FixedRewardStrategy : IRewardStrategy
    {
        private static readonly TimeSpan OneYear = TimeSpan.FromDays(365);

        private readonly FixedRewardConfig _config;
        private readonly ILogger<FixedRewardStrategy>? _logger;

        /// <summary>
        /// Creates a stateless, thread-safe instance of <see cref="FixedRewardStrategy"/>.
        /// </summary>
        /// <param name="config">Strategy parameters.</param>
        /// <param name="logger">Structured logger (optional).</param>
        public FixedRewardStrategy(
            FixedRewardConfig config,
            ILogger<FixedRewardStrategy>? logger = null)
        {
            _config = config ?? throw new ArgumentNullException(nameof(config));
            _logger = logger;
        }

        /// <inheritdoc />
        public ValueTask<RewardResult> CalculateAsync(
            StakePosition stake,
            DateTimeOffset asOfUtc,
            CancellationToken cancellationToken = default)
        {
            ArgumentNullException.ThrowIfNull(stake);

            if (cancellationToken.IsCancellationRequested)
                return ValueTask.FromCanceled<RewardResult>(cancellationToken);

            if (asOfUtc < stake.StartUtc)
            {
                throw new ArgumentException(
                    "The cut-off time cannot be earlier than the stake start date.",
                    nameof(asOfUtc));
            }

            decimal rewardAmount = CalculateInternal(stake, asOfUtc);

            var result = new RewardResult(
                stake.PositionId,
                rewardAmount,
                asOfUtc);

            return ValueTask.FromResult(result);
        }

        #region Internal Logic

        private decimal CalculateInternal(StakePosition stake, DateTimeOffset asOfUtc)
        {
            var stakeAge = asOfUtc - stake.StartUtc;

            // Stake does not meet the minimum age requirement.
            if (stakeAge < _config.MinimumStakeAge)
            {
                _logger?.LogDebug("Stake {PositionId} skipped – minimum age not reached (age={Age}).",
                    stake.PositionId, stakeAge);
                return 0m;
            }

            // Nothing staked – nothing earned.
            if (stake.Principal <= 0)
            {
                _logger?.LogWarning("Stake {PositionId} has non-positive principal: {Principal}.",
                    stake.PositionId, stake.Principal);
                return 0m;
            }

            // Shortcut: no compounding, just simple pro-rata APR.
            if (_config.CompoundingInterval == TimeSpan.Zero)
            {
                double yearFraction = stakeAge.TotalSeconds / OneYear.TotalSeconds;
                decimal reward = stake.Principal *
                                 _config.AnnualRate *
                                 (decimal)yearFraction;

                return Decimal.Round(reward, 8, MidpointRounding.ToZero);
            }

            // Compounded interest.
            double intervalsPerYear =
                OneYear.TotalSeconds / _config.CompoundingInterval.TotalSeconds;

            if (intervalsPerYear <= 0d)
                throw new InvalidOperationException(
                    "CompoundingInterval must be less than 1 year.");

            double totalIntervals =
                stakeAge.TotalSeconds / _config.CompoundingInterval.TotalSeconds;

            double annualRate = (double)_config.AnnualRate;
            double periodicRate = annualRate / intervalsPerYear;

            // Compound formula: A = P * (1 + r) ^ n  –  P
            double compoundFactor = Math.Pow(1d + periodicRate, totalIntervals) - 1d;

            decimal rewardDecimal = stake.Principal * (decimal)compoundFactor;

            return Decimal.Round(rewardDecimal, 8, MidpointRounding.ToZero);
        }

        #endregion
    }
}