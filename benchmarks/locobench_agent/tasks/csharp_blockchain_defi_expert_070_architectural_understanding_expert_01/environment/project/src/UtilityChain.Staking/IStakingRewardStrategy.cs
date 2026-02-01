```csharp
// -----------------------------------------------------------------------------
// UtilityChain Core Suite – Staking Module
// -----------------------------------------------------------------------------
// File:    IStakingRewardStrategy.cs
// Project: UtilityChain.Staking
// Author:  UtilityChain Engineering Team
// License: MIT (https://github.com/utilitychain/core-suite/blob/main/LICENSE)
// -----------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;

namespace UtilityChain.Staking
{
    /// <summary>
    /// Strategy abstraction used by the <c>StakingService</c> to calculate and
    /// distribute rewards at the end of every epoch.
    /// </summary>
    /// <remarks>
    /// A strategy must be <b>stateless</b> and <b>thread-safe</b>. All state that
    /// is needed to compute rewards has to be supplied via the
    /// <see cref="EpochSnapshot"/> parameter. Implementations are resolved by the
    /// internal <c>RewardStrategyFactory</c> using DI and the strategy identifier
    /// (<see cref="Id"/>) configured in <c>staking.toml</c>.
    /// </remarks>
    public interface IStakingRewardStrategy
    {
        /// <summary>
        /// Machine-readable identifier used for persistence and remote selection.
        /// </summary>
        string Id { get; }

        /// <summary>
        /// Human-friendly name that may be displayed in UIs and logs.
        /// </summary>
        string Name { get; }

        /// <summary>
        /// Semantic version used to guarantee deterministic replay of reward
        /// calculations across nodes. Changing the algorithm requires a version bump.
        /// </summary>
        string Version { get; }

        /// <summary>
        /// Executes the reward calculation for a completed epoch.
        /// </summary>
        /// <param name="epochSnapshot">
        ///     Immutable snapshot of chain state at the end of the epoch.
        /// </param>
        /// <param name="wireTransfer">
        ///     Delegate that must be invoked by the strategy for every reward
        ///     distribution. This indirection allows the runtime to keep track of
        ///     total inflation and provides a single audit point.
        /// </param>
        /// <param name="cancellationToken">Cancellation propagation token.</param>
        /// <returns>
        ///     A <see cref="RewardStatistics"/> object containing aggregated
        ///     information that will be written to the consensus log.
        /// </returns>
        /// <exception cref="OperationCanceledException">
        ///     Thrown if <paramref name="cancellationToken"/> is signalled.
        /// </exception>
        ValueTask<RewardStatistics> ExecuteAsync(
            in EpochSnapshot epochSnapshot,
            RewardTransferDelegate wireTransfer,
            CancellationToken cancellationToken = default);
    }

    #region ────────────────────────────── Supporting Contracts ─────────────────────────────

    /// <summary>
    /// Represents a unique account / wallet address within UtilityChain.
    /// </summary>
    public readonly struct Address : IEquatable<Address>
    {
        public Address(string value)
        {
            Value = value ?? throw new ArgumentNullException(nameof(value));
        }

        public string Value { get; }

        public bool Equals(Address other) =>
            string.Equals(Value, other.Value, StringComparison.OrdinalIgnoreCase);

        public override bool Equals(object? obj) => obj is Address other && Equals(other);

        public override int GetHashCode() =>
            StringComparer.OrdinalIgnoreCase.GetHashCode(Value);

        public static implicit operator Address(string value) => new(value);

        public static implicit operator string(Address address) => address.Value;

        public override string ToString() => Value;
    }

    /// <summary>
    /// Immutable value type that represents a non-negative token quantity with
    /// 18 decimal places of precision (compatible with ERC-20).
    /// </summary>
    public readonly struct TokenAmount : IComparable<TokenAmount>,
                                         IEquatable<TokenAmount>,
                                         IFormattable
    {
        private readonly decimal _value;

        public TokenAmount(decimal value)
        {
            if (value < 0)
                throw new ArgumentOutOfRangeException(nameof(value), "Token amount cannot be negative.");

            _value = decimal.Round(value, 18, MidpointRounding.AwayFromZero);
        }

        public decimal Value => _value;

        public int CompareTo(TokenAmount other) => _value.CompareTo(other._value);

        public bool Equals(TokenAmount other) => _value == other._value;

        public override bool Equals(object? obj) => obj is TokenAmount other && Equals(other);

        public override int GetHashCode() => _value.GetHashCode();

        public override string ToString() => _value.ToString("0.##################");

        public string ToString(string? format, IFormatProvider? provider) =>
            _value.ToString(format, provider);

        #region Operators

        public static TokenAmount operator +(TokenAmount a, TokenAmount b) =>
            new(a._value + b._value);

        public static TokenAmount operator -(TokenAmount a, TokenAmount b)
        {
            if (a._value < b._value)
                throw new InvalidOperationException("Resulting token amount would be negative.");

            return new TokenAmount(a._value - b._value);
        }

        public static TokenAmount operator *(TokenAmount a, decimal mul) =>
            new(a._value * mul);

        public static TokenAmount operator /(TokenAmount a, decimal div) =>
            new(a._value / div);

        public static bool operator >(TokenAmount a, TokenAmount b) => a._value > b._value;
        public static bool operator <(TokenAmount a, TokenAmount b) => a._value < b._value;
        public static bool operator >=(TokenAmount a, TokenAmount b) => a._value >= b._value;
        public static bool operator <=(TokenAmount a, TokenAmount b) => a._value <= b._value;

        #endregion
    }

    /// <summary>
    /// Immutable record that represents a single staking position.
    /// </summary>
    /// <param name="Account">Owner of the stake.</param>
    /// <param name="Amount">Total amount staked by the account.</param>
    /// <param name="LockedUntil">Date/time until which the stake is locked.</param>
    /// <param name="LastClaimEpoch">Epoch when the account last claimed rewards.</param>
    public sealed record StakePosition(
        Address Account,
        TokenAmount Amount,
        DateTimeOffset LockedUntil,
        long LastClaimEpoch);

    /// <summary>
    /// Immutable snapshot of all information required by a reward strategy to
    /// perform its calculation for a specific epoch.
    /// </summary>
    public sealed record EpochSnapshot
    {
        public EpochSnapshot(
            long epochNumber,
            DateTimeOffset startedAt,
            DateTimeOffset endedAt,
            IReadOnlyList<StakePosition> stakePositions,
            TokenAmount totalNetworkFees,
            TokenAmount inflationPool)
        {
            EpochNumber      = epochNumber;
            StartedAt        = startedAt;
            EndedAt          = endedAt;
            StakePositions   = stakePositions ?? throw new ArgumentNullException(nameof(stakePositions));
            TotalNetworkFees = totalNetworkFees;
            InflationPool    = inflationPool;
        }

        public long EpochNumber { get; }
        public DateTimeOffset StartedAt { get; }
        public DateTimeOffset EndedAt { get; }

        /// <summary>
        /// All staking positions that were valid at <see cref="EndedAt"/>.
        /// </summary>
        public IReadOnlyList<StakePosition> StakePositions { get; }

        /// <summary>
        /// Total transaction fees collected during the epoch (in base tokens).
        /// </summary>
        public TokenAmount TotalNetworkFees { get; }

        /// <summary>
        /// Amount of new tokens that may be minted for inflationary rewards.
        /// </summary>
        public TokenAmount InflationPool { get; }
    }

    /// <summary>
    /// Aggregated statistics returned by a reward strategy once it completed.
    /// </summary>
    public sealed record RewardStatistics(
        long Epoch,
        int RewardedAccounts,
        TokenAmount TotalDistributed,
        TimeSpan ComputationTime);

    /// <summary>
    /// Delegate invoked by <see cref="IStakingRewardStrategy"/> implementations to
    /// credit reward tokens to a recipient. Implementations must be idempotent and
    /// deterministic; if the same transfer is requested twice with identical
    /// parameters it must either succeed both times or fail both times.
    /// </summary>
    /// <param name="recipient">
    ///     The address that will receive the tokens.
    /// </param>
    /// <param name="amount">
    ///     Amount of tokens to transfer (must be > 0).
    /// </param>
    /// <param name="metadata">
    ///     Optional opaque metadata that will be persisted in the ledger for
    ///     auditing purposes (e.g. JSON or CBOR).
    /// </param>
    /// <param name="ct">
    ///     Cancellation propagation token.
    /// </param>
    public delegate ValueTask RewardTransferDelegate(
        Address recipient,
        TokenAmount amount,
        ReadOnlyMemory<byte> metadata,
        CancellationToken ct = default);

    #endregion
}
```