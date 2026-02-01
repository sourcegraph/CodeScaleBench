```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Staking/StakingService.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using UtilityChain.Abstractions.Events;
using UtilityChain.Abstractions.Staking;
using UtilityChain.Abstractions.Time;
using UtilityChain.Common;
using UtilityChain.Staking.Rewards;

namespace UtilityChain.Staking;

/// <summary>
///     Concrete staking façade exposed to the rest of the monolith.  
///     Implements the application layer surface and encapsulates domain‐level
///     state‐handling, reward calculations, and event publication.
/// </summary>
public sealed class StakingService : IStakingService, IAsyncDisposable
{
    // ---------------------------------------------------------------------
    // Private readonly fields
    // ---------------------------------------------------------------------
    private readonly IEventBus                                _eventBus;
    private readonly ITimeProvider                            _clock;
    private readonly IRewardCalculatorStrategy                _rewardCalculator;
    private readonly IStateRepository<StakeAccountSnapshot>   _repository;
    private readonly ILogger<StakingService>                  _logger;

    // Thread-safe in-memory cache of active accounts. The authoritative
    // snapshot is periodically persisted by the background sync worker.
    private readonly ConcurrentDictionary<Address, StakeAccount> _accounts =
        new();

    // Background worker bookkeeping
    private readonly CancellationTokenSource _cts = new();
    private readonly Task                    _syncTask;

    // ---------------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------------
    public StakingService(
        IEventBus                             eventBus,
        ITimeProvider                         clock,
        IRewardCalculatorStrategyFactory      rewardCalculatorFactory,
        IStateRepository<StakeAccountSnapshot> repository,
        ILogger<StakingService>               logger)
    {
        _eventBus         = eventBus  ?? throw new ArgumentNullException(nameof(eventBus));
        _clock            = clock     ?? throw new ArgumentNullException(nameof(clock));
        _repository       = repository?? throw new ArgumentNullException(nameof(repository));
        _logger           = logger    ?? throw new ArgumentNullException(nameof(logger));

        _rewardCalculator = rewardCalculatorFactory.Create(RewardCalculatorType.Default);

        _syncTask = Task.Run(BackgroundSyncLoopAsync, _cts.Token);

        _eventBus.Subscribe<NewBlockEvent>(OnNewBlock);
    }

    // ---------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------

    /// <inheritdoc />
    public async Task<StakeReceipt> StakeAsync(
        Address address, ulong amount, TimeSpan lockPeriod, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(address);

        if (amount == 0)
            throw new StakingException("Amount must be > 0.");

        var account = _accounts.GetOrAdd(address, _ => new StakeAccount(address));

        // Ensure atomic update per account
        await account.Semaphore.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var stake = account.CreateStake(amount, lockPeriod, _clock.Now);

            _logger.LogInformation(
                "Address {Address} staked {Amount} tokens for {LockPeriod}. New total: {Total}.",
                address, amount, lockPeriod, account.TotalStaked);

            _eventBus.Publish(new StakeCreatedEvent(stake, account.TotalStaked));

            return new StakeReceipt(stake.StakeId, stake.CreatedAt);
        }
        finally
        {
            account.Semaphore.Release();
        }
    }

    /// <inheritdoc />
    public async Task<UnstakeReceipt> UnstakeAsync(
        Address address, StakeId stakeId, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(address);
        ArgumentNullException.ThrowIfNull(stakeId);

        if (!_accounts.TryGetValue(address, out var account))
            throw new StakeNotFoundException(stakeId);

        await account.Semaphore.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var stake = account.GetStake(stakeId);

            if (stake == null)
                throw new StakeNotFoundException(stakeId);

            if (stake.State != StakeState.Locked &&
                stake.State != StakeState.Released)
                throw new InvalidStakeTransitionException(stake.State, StakeState.Withdrawn);

            if (stake.State == StakeState.Locked &&
                _clock.Now < stake.UnlocksAt)
                throw new StakeLockedException(stake.UnlocksAt);

            stake.State = StakeState.Withdrawn;
            account.TotalStaked -= stake.Amount;

            _logger.LogInformation(
                "Stake {StakeId} withdrawn. Address {Address} remaining total: {Total}.",
                stakeId, address, account.TotalStaked);

            _eventBus.Publish(new StakeWithdrawnEvent(stake));

            return new UnstakeReceipt(stake.StakeId, _clock.Now, stake.Amount);
        }
        finally
        {
            account.Semaphore.Release();
        }
    }

    /// <inheritdoc />
    public async Task<IReadOnlyCollection<StakeInfo>> GetStakesAsync(Address address,
        CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(address);

        if (!_accounts.TryGetValue(address, out var account))
            return Array.Empty<StakeInfo>();

        await account.Semaphore.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            return account.ListStakes();
        }
        finally
        {
            account.Semaphore.Release();
        }
    }

    /// <inheritdoc />
    public async Task<decimal> GetAccumulatedRewardsAsync(Address address,
        CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(address);

        if (!_accounts.TryGetValue(address, out var account))
            return 0m;

        await account.Semaphore.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var rewards = _rewardCalculator.Calculate(account, _clock.Now);

            return rewards;
        }
        finally
        {
            account.Semaphore.Release();
        }
    }

    /// <inheritdoc />
    public async Task ClaimRewardsAsync(Address address, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(address);

        if (!_accounts.TryGetValue(address, out var account))
            throw new StakingException("Account not found.");

        await account.Semaphore.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var rewards = _rewardCalculator.Calculate(account, _clock.Now);

            if (rewards <= 0m)
                throw new StakingException("No rewards available.");

            account.RewardsClaimed += rewards;

            _logger.LogInformation("Address {Address} claimed {Rewards} rewards", address, rewards);

            _eventBus.Publish(new RewardsClaimedEvent(address, rewards));
        }
        finally
        {
            account.Semaphore.Release();
        }
    }

    // ---------------------------------------------------------------------
    // Event handling
    // ---------------------------------------------------------------------
    // Called for every new block to update lock expirations and reward indexes
    private void OnNewBlock(NewBlockEvent e)
    {
        foreach (var (_, account) in _accounts)
        {
            // Intentionally fire-and-forget; minimal per-block CPU time
            _ = Task.Run(() =>
            {
                if (!account.Semaphore.Wait(0))
                    return; // Skip busy accounts to maintain block throughput

                try
                {
                    account.ProcessBlock(_clock.Now);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Failed to process staking updates for address {Address}.",
                        account.Address);
                }
                finally
                {
                    account.Semaphore.Release();
                }
            }, _cts.Token);
        }
    }

    // ---------------------------------------------------------------------
    // Background persistence loop
    // ---------------------------------------------------------------------
    private async Task BackgroundSyncLoopAsync()
    {
        var token = _cts.Token;

        try
        {
            while (!token.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromMinutes(1), token).ConfigureAwait(false);

                foreach (var (_, account) in _accounts)
                {
                    if (!account.Semaphore.Wait(0))
                        continue; // Skip active accounts

                    try
                    {
                        var snapshot = account.CreateSnapshot();
                        await _repository.SaveAsync(snapshot, token).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Failed to persist staking snapshot for {Address}.",
                            account.Address);
                    }
                    finally
                    {
                        account.Semaphore.Release();
                    }
                }
            }
        }
        catch (OperationCanceledException)
        {
            // Normal shutdown
        }
        catch (Exception ex)
        {
            _logger.LogCritical(ex, "Unexpected failure in staking background loop.");
        }
    }

    // ---------------------------------------------------------------------
    // Disposable
    // ---------------------------------------------------------------------
    public async ValueTask DisposeAsync()
    {
        _cts.Cancel();

        _eventBus.Unsubscribe<NewBlockEvent>(OnNewBlock);

        try
        {
            await _syncTask.ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failure while stopping staking service sync loop.");
        }

        _cts.Dispose();
    }

    // =====================================================================
    // DOMAIN ENTITIES & VALUE OBJECTS
    // =====================================================================

    #region Domain

    private sealed class StakeAccount
    {
        private readonly ConcurrentDictionary<StakeId, Stake> _stakes = new();
        internal readonly SemaphoreSlim Semaphore             = new(1, 1);

        internal StakeAccount(Address address)
        {
            Address = address;
            Created = DateTimeOffset.UtcNow;
        }

        internal Address      Address         { get; }
        internal DateTimeOffset Created       { get; }
        internal ulong        TotalStaked     { get; set; }
        internal decimal      RewardsClaimed  { get; set; }

        internal Stake CreateStake(ulong amount, TimeSpan lockPeriod, DateTimeOffset now)
        {
            var stake = new Stake(amount, now, lockPeriod);
            _stakes[stake.StakeId] = stake;
            TotalStaked += amount;
            return stake;
        }

        internal Stake? GetStake(StakeId id) => _stakes.TryGetValue(id, out var s) ? s : null;

        internal void ProcessBlock(DateTimeOffset now)
        {
            foreach (var stake in _stakes.Values)
            {
                stake.TryRelease(now);
            }
        }

        internal IReadOnlyCollection<StakeInfo> ListStakes()
        {
            var list = new List<StakeInfo>(_stakes.Count);
            foreach (var s in _stakes.Values)
            {
                list.Add(s.ToInfo());
            }

            return list.AsReadOnly();
        }

        internal StakeAccountSnapshot CreateSnapshot()
        {
            var stakeSnapshots = new List<StakeSnapshot>();

            foreach (var s in _stakes.Values)
            {
                stakeSnapshots.Add(new StakeSnapshot(
                    s.StakeId,
                    s.Amount,
                    s.CreatedAt,
                    s.UnlocksAt,
                    s.State));
            }

            return new StakeAccountSnapshot(
                Address,
                Created,
                TotalStaked,
                RewardsClaimed,
                stakeSnapshots);
        }
    }

    private sealed class Stake
    {
        private static readonly RNGCryptoServiceProvider Rng = new();

        internal Stake(ulong amount, DateTimeOffset createdAt, TimeSpan lockPeriod)
        {
            Amount    = amount;
            CreatedAt = createdAt;
            UnlocksAt = createdAt + lockPeriod;
            State     = StakeState.Locked;
            StakeId   = GenerateId();
        }

        internal ulong           Amount     { get; }
        internal DateTimeOffset  CreatedAt  { get; }
        internal DateTimeOffset  UnlocksAt  { get; }
        internal StakeState      State      { get; set; }
        internal StakeId         StakeId    { get; }

        internal void TryRelease(DateTimeOffset now)
        {
            if (State == StakeState.Locked && now >= UnlocksAt)
            {
                State = StakeState.Released;
            }
        }

        internal StakeInfo ToInfo() => new(
            StakeId,
            Amount,
            CreatedAt,
            UnlocksAt,
            State);

        private static StakeId GenerateId()
        {
            Span<byte> bytes = stackalloc byte[16];
            Rng.GetBytes(bytes);
            return new StakeId(Convert.ToHexString(bytes));
        }
    }

    #endregion
}

// ========================================================================
//  Abstractions & Supporting Contracts
//  (Would usually live in a separate assembly — co-located here for brevity)
// ========================================================================

namespace UtilityChain.Abstractions.Staking
{
    public interface IStakingService
    {
        Task<StakeReceipt>   StakeAsync(Address address, ulong amount, TimeSpan lockPeriod, CancellationToken ct = default);
        Task<UnstakeReceipt> UnstakeAsync(Address address, StakeId stakeId, CancellationToken ct = default);
        Task<IReadOnlyCollection<StakeInfo>> GetStakesAsync(Address address, CancellationToken ct = default);
        Task<decimal>        GetAccumulatedRewardsAsync(Address address, CancellationToken ct = default);
        Task                 ClaimRewardsAsync(Address address, CancellationToken ct = default);
    }

    public readonly record struct Address(string Value)
    {
        public override string ToString() => Value;
    }

    public readonly record struct StakeId(string Value)
    {
        public override string ToString() => Value;
    }

    public enum StakeState
    {
        Locked,
        Released,
        Withdrawn
    }

    public record StakeInfo(
        StakeId           StakeId,
        ulong             Amount,
        DateTimeOffset    CreatedAt,
        DateTimeOffset    UnlocksAt,
        StakeState        State);

    public record StakeReceipt(StakeId StakeId, DateTimeOffset Timestamp);
    public record UnstakeReceipt(StakeId StakeId, DateTimeOffset Timestamp, ulong Amount);
}

namespace UtilityChain.Staking
{
    // Domain exceptions
    public class StakingException : Exception
    {
        public StakingException(string message) : base(message) { }
    }

    public sealed class StakeNotFoundException : StakingException
    {
        public StakeNotFoundException(StakeId id)
            : base($"Stake {id} not found.") { }
    }

    public sealed class StakeLockedException : StakingException
    {
        public StakeLockedException(DateTimeOffset until)
            : base($"Stake is locked until {until}.") { }
    }

    public sealed class InvalidStakeTransitionException : StakingException
    {
        public InvalidStakeTransitionException(StakeState from, StakeState to)
            : base($"Cannot transition stake from {from} to {to}.") { }
    }
}

namespace UtilityChain.Abstractions.Events
{
    public interface IEventBus
    {
        void Publish<TEvent>(TEvent @event);
        void Subscribe<TEvent>(Action<TEvent> handler);
        void Unsubscribe<TEvent>(Action<TEvent> handler);
    }

    public record NewBlockEvent(long Height, DateTimeOffset Timestamp);

    public record StakeCreatedEvent(UtilityChain.Staking.Stake Stake, ulong Total);
    public record StakeWithdrawnEvent(UtilityChain.Staking.Stake Stake);
    public record RewardsClaimedEvent(Address Address, decimal Amount);
}

namespace UtilityChain.Abstractions.Time
{
    public interface ITimeProvider
    {
        DateTimeOffset Now { get; }
    }
}

namespace UtilityChain.Abstractions.Staking
{
    public interface IRewardCalculatorStrategy
    {
        decimal Calculate(object account, DateTimeOffset now);
    }

    public enum RewardCalculatorType
    {
        Default,
        EnergyCredits,
        LiquidityMining
    }

    public interface IRewardCalculatorStrategyFactory
    {
        IRewardCalculatorStrategy Create(RewardCalculatorType type);
    }
}

namespace UtilityChain.Common
{
    public interface IStateRepository<TSnapshot>
    {
        Task SaveAsync(TSnapshot snapshot, CancellationToken ct = default);
    }
}

namespace UtilityChain.Staking.Rewards
{
    // Simple compound APR strategy with 12-second block time assumption
    public sealed class DefaultRewardCalculator : IRewardCalculatorStrategy
    {
        private const decimal Apr = 0.08m; // 8% APR

        public decimal Calculate(object accountObj, DateTimeOffset now)
        {
            if (accountObj is not StakingService.StakeAccount account)
                throw new ArgumentException(nameof(accountObj));

            var secondsYear = 365 * 24 * 60 * 60;
            var accrued     = 0m;

            foreach (var stakeInfo in account.ListStakes())
            {
                if (stakeInfo.State == StakeState.Withdrawn)
                    continue;

                var durationSeconds = (decimal)(now - stakeInfo.CreatedAt).TotalSeconds;
                accrued += stakeInfo.Amount * (Apr * durationSeconds / secondsYear);
            }

            return Math.Round(accrued - account.RewardsClaimed, 8);
        }
    }

    public sealed class RewardCalculatorStrategyFactory : IRewardCalculatorStrategyFactory
    {
        public IRewardCalculatorStrategy Create(RewardCalculatorType type) =>
            type switch
            {
                RewardCalculatorType.Default => new DefaultRewardCalculator(),
                _ => throw new NotSupportedException($"Reward calculator '{type}' is not supported.")
            };
    }
}

namespace UtilityChain.Staking
{
    // Persistence snapshot DTOs
    public record StakeSnapshot(
        StakeId        StakeId,
        ulong          Amount,
        DateTimeOffset CreatedAt,
        DateTimeOffset UnlocksAt,
        StakeState     State);

    public record StakeAccountSnapshot(
        Address                 Address,
        DateTimeOffset          CreatedAt,
        ulong                   TotalStaked,
        decimal                 RewardsClaimed,
        IReadOnlyList<StakeSnapshot> Stakes);
}
```