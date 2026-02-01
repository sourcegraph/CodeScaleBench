```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Staking/Strategies/InflationaryRewardStrategy.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Staking.Strategies
{
    #region Abstractions & Shared Models

    /// <summary>
    /// Required contract for any staking-reward strategy.
    /// </summary>
    public interface IRewardStrategy
    {
        /// <summary>Calculates the reward the <paramref name="snapshot"/> is entitled to for the given <paramref name="blockContext"/>.</summary>
        /// <param name="state">Current immutable chain state.</param>
        /// <param name="snapshot">Snapshot of the validator’s stake at <paramref name="blockContext"/>.</param>
        /// <param name="blockContext">Information about the block being produced.</param>
        /// <returns>The reward to be minted for the validator.</returns>
        decimal CalculateReward(in ChainState state, in StakeSnapshot snapshot, in BlockContext blockContext);

        /// <summary>Applies the reward to the chain state. This call <strong>must</strong> be idempotent.</summary>
        /// <param name="state">Mutable chain state.</param>
        /// <param name="snapshot">Stake snapshot used during reward calculation.</param>
        /// <param name="blockContext">Information about the block being produced.</param>
        void ApplyReward(ChainState state, in StakeSnapshot snapshot, in BlockContext blockContext);
    }

    /// <summary>
    /// Immutable chain data required by reward strategies.
    /// </summary>
    public sealed class ChainState
    {
        private readonly ConcurrentDictionary<Guid, decimal> _stakerBalances = new();

        public ChainState(decimal circulatingSupply)
        {
            if (circulatingSupply < 0) throw new ArgumentOutOfRangeException(nameof(circulatingSupply));
            CirculatingSupply = circulatingSupply;
        }

        /// <summary>Total amount of tokens in circulation.</summary>
        public decimal CirculatingSupply { get; private set; }

        /// <summary>Returns the balance for a specific staker, or zero if not found.</summary>
        public decimal GetBalance(Guid stakerId) => _stakerBalances.TryGetValue(stakerId, out var bal) ? bal : 0m;

        /// <summary>Credits a reward to the staker and mints new tokens.</summary>
        internal void Credit(Guid stakerId, decimal amount)
        {
            if (amount <= 0) return;

            _stakerBalances.AddOrUpdate(stakerId, amount, (_, existing) => existing + amount);
            // Inflation: newly minted tokens increase supply.
            _ = Interlocked.Exchange(ref CirculatingSupply, CirculatingSupply + amount);
        }
    }

    /// <summary>
    /// Read-only record providing a point-in-time view of a validator’s stake.
    /// </summary>
    /// <param name="ValidatorId">Unique identifier of the validator.</param>
    /// <param name="Height">Block height the snapshot was captured at.</param>
    /// <param name="ValidatorStake">Validator’s self-bonded or delegated stake.</param>
    /// <param name="TotalStaked">Network-wide total staked amount.</param>
    public readonly record struct StakeSnapshot(
        Guid ValidatorId,
        ulong Height,
        decimal ValidatorStake,
        decimal TotalStaked);

    /// <summary>
    /// Contextual information about the block being produced.
    /// </summary>
    /// <param name="Height">Height of the block being produced.</param>
    /// <param name="Timestamp">UTC timestamp of block production.</param>
    public readonly record struct BlockContext(ulong Height, DateTime Timestamp);

    /// <summary>
    /// Strongly-typed settings for <see cref="InflationaryRewardStrategy"/>.
    /// </summary>
    public sealed class InflationaryRewardStrategyOptions
    {
        /// <summary>Annualised inflation rate applied to circulating supply. Example: 0.02 → 2 % inflation.</summary>
        public decimal AnnualInflationRate { get; init; } = 0.02m;

        /// <summary>Target block time in seconds.</summary>
        public uint BlockTimeSeconds { get; init; } = 5;

        /// <summary>Number of decimals to round token values to (default: 8).</summary>
        public byte TokenDecimals { get; init; } = 8;

        internal uint BlocksPerYear =>
            BlockTimeSeconds == 0
                ? throw new DivideByZeroException("BlockTimeSeconds cannot be zero.")
                : (uint)(365.2422 * 24 * 60 * 60 / BlockTimeSeconds); // Avg. solar year
    }

    #endregion

    /// <summary>
    /// A reward strategy that mints an amount proportional to annual inflation divided
    /// by <c>BlocksPerYear</c>, then distributes it to validators according to stake weight.
    /// </summary>
    public sealed class InflationaryRewardStrategy : IRewardStrategy
    {
        private readonly ILogger<InflationaryRewardStrategy> _logger;
        private readonly InflationaryRewardStrategyOptions _options;
        private readonly decimal _perBlockInflationRate; // pre-computed for efficiency

        public InflationaryRewardStrategy(
            InflationaryRewardStrategyOptions options,
            ILogger<InflationaryRewardStrategy>? logger = null)
        {
            _options = options ?? throw new ArgumentNullException(nameof(options));
            _logger  = logger ?? Microsoft.Extensions.Logging.Abstractions.NullLogger<InflationaryRewardStrategy>.Instance;

            _perBlockInflationRate = _options.AnnualInflationRate / _options.BlocksPerYear;

            if (_perBlockInflationRate <= 0)
            {
                _logger.LogWarning(
                    "Per-block inflation rate is non-positive (value = {Rate}). " +
                    "Reward calculation will always return zero.",
                    _perBlockInflationRate);
            }
        }

        public decimal CalculateReward(in ChainState state, in StakeSnapshot snapshot, in BlockContext blockContext)
        {
            // Defensive checks
            if (snapshot.TotalStaked <= 0m ||
                snapshot.ValidatorStake <= 0m ||
                state.CirculatingSupply <= 0m ||
                _perBlockInflationRate <= 0m)
            {
                return 0m;
            }

            // 1. Compute total new tokens minted this block.
            var newlyMintedForAll = state.CirculatingSupply * _perBlockInflationRate;

            // 2. Determine the validator's pro-rata share.
            var stakeShare = snapshot.ValidatorStake / snapshot.TotalStaked;
            var rawReward  = newlyMintedForAll * stakeShare;

            // 3. Round according to chain's token decimal precision.
            var reward = Decimal.Round(
                rawReward,
                _options.TokenDecimals,
                MidpointRounding.AwayFromZero);

            _logger.LogTrace(
                "Calculated reward for validator {ValidatorId} at height {Height}: {Reward} " +
                "(stakeShare: {StakeShare:P4}, circulating: {Supply}, mintedAll: {MintedAll})",
                snapshot.ValidatorId,
                blockContext.Height,
                reward,
                stakeShare,
                state.CirculatingSupply,
                newlyMintedForAll);

            return reward;
        }

        public void ApplyReward(ChainState state, in StakeSnapshot snapshot, in BlockContext blockContext)
        {
            var reward = CalculateReward(state, snapshot, blockContext);
            if (reward <= 0m) return;

            state.Credit(snapshot.ValidatorId, reward);

            _logger.LogDebug(
                "Reward of {Reward} applied to validator {ValidatorId} at height {Height}. " +
                "New circulating supply: {NewSupply}",
                reward,
                snapshot.ValidatorId,
                blockContext.Height,
                state.CirculatingSupply);
        }
    }
}
```