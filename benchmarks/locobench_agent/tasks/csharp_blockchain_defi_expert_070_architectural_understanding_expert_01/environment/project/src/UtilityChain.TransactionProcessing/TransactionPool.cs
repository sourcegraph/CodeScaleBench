```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.TransactionProcessing
{
    #region Helper Contracts (minimal stubs)

    /*
     * NOTE:
     * These are intentionally minimal abstractions to keep the sample
     * self-contained. In the real codebase they would be defined in their
     * dedicated assemblies and provide richer functionality.
     */

    /// <summary>
    /// Represents a signed blockchain transaction.
    /// </summary>
    public interface ITransaction
    {
        string Hash { get; }
        int SizeInBytes { get; }
        decimal Fee { get; }              // Total fee included in this tx.
        DateTimeOffset Timestamp { get; } // When the tx was created.
    }

    /// <summary>
    /// Validates business-rules & cryptographic correctness of a transaction.
    /// </summary>
    public interface ITransactionValidator
    {
        /// <summary>
        /// Returns true if the transaction is valid and can be accepted into the pool.
        /// </summary>
        ValueTask<bool> ValidateAsync(ITransaction tx, CancellationToken ct = default);
    }

    /// <summary>
    /// Simple event bus abstraction used by the core to disseminate domain events.
    /// </summary>
    public interface IEventBus
    {
        IDisposable Subscribe<TEvent>(Func<TEvent, Task> handler, bool runHandlersInParallel = false);
        ValueTask PublishAsync<TEvent>(TEvent evt);
    }

    /// <summary>
    /// Raised by the consensus engine whenever a new block is committed.
    /// </summary>
    public sealed record BlockCommittedEvent(ImmutableArray<string> ConfirmedTransactionHashes);

    /// <summary>
    /// Raised during a (rare) chain re-organization so the pool can re-enqueue reverted txs.
    /// </summary>
    public sealed record ChainReorgEvent(ImmutableArray<ITransaction> RevertedTransactions);

    #endregion

    /// <summary>
    /// Thread-safe mem-pool that stores pending transactions until they are included in a block.
    /// Implements TTL, fee-priority queuing and event-driven eviction.
    /// </summary>
    public sealed class TransactionPool : IDisposable
    {
        private readonly ConcurrentDictionary<string, TransactionEntry> _map = new(StringComparer.Ordinal);
        private readonly SortedSet<TransactionEntry> _feeOrdered; // Used for priority enumeration.
        private readonly object _feeLock = new();                 // SortedSet is not thread-safe.
        private readonly ITransactionValidator _validator;
        private readonly IEventBus _bus;
        private readonly ILogger<TransactionPool> _logger;
        private readonly int _maxPoolSizeBytes;
        private readonly TimeSpan _txTimeToLive;
        private long _currentPoolSizeBytes;
        private readonly CancellationTokenSource _cts = new();
        private readonly Task _houseKeeperTask;

        public TransactionPool(
            ITransactionValidator validator,
            IEventBus bus,
            ILogger<TransactionPool> logger,
            int maxPoolSizeBytes = 256 * 1024 * 1024, // 256 MB
            TimeSpan? txTimeToLive = null)
        {
            _validator = validator ?? throw new ArgumentNullException(nameof(validator));
            _bus = bus ?? throw new ArgumentNullException(nameof(bus));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _maxPoolSizeBytes = maxPoolSizeBytes;
            _txTimeToLive = txTimeToLive ?? TimeSpan.FromHours(2);

            _feeOrdered = new SortedSet<TransactionEntry>(TransactionEntry.FeeDescendingComparer);

            // Subscribe to blockchain events:
            _bus.Subscribe<BlockCommittedEvent>(OnBlockCommitted);
            _bus.Subscribe<ChainReorgEvent>(OnChainReorg);

            // Start maintenance loop.
            _houseKeeperTask = Task.Run(HouseKeepingLoopAsync);
        }

        #region Public API

        /// <summary>
        /// Attempts to add <paramref name="tx"/> to the mem-pool.
        /// Returns <c>true</c> on success, <c>false</c> if rejected.
        /// </summary>
        public async ValueTask<bool> TryAddAsync(ITransaction tx, CancellationToken ct = default)
        {
            if (tx is null) throw new ArgumentNullException(nameof(tx));

            // Size check done first to avoid expensive validation if pool is full.
            if (Interlocked.Read(ref _currentPoolSizeBytes) + tx.SizeInBytes > _maxPoolSizeBytes)
            {
                _logger.LogWarning("Pool size limit reached. Rejecting transaction {TxHash}", tx.Hash);
                return false;
            }

            if (_map.ContainsKey(tx.Hash))
            {
                _logger.LogDebug("Transaction {TxHash} already present in pool. Skipping.", tx.Hash);
                return false;
            }

            if (!await _validator.ValidateAsync(tx, ct).ConfigureAwait(false))
            {
                _logger.LogWarning("Transaction {TxHash} failed validation. Rejected.", tx.Hash);
                return false;
            }

            // Create entry and attempt to add atomically.
            var entry = new TransactionEntry(tx);

            if (!_map.TryAdd(tx.Hash, entry))
                return false;

            lock (_feeLock)
            {
                _feeOrdered.Add(entry);
            }

            Interlocked.Add(ref _currentPoolSizeBytes, tx.SizeInBytes);
            _logger.LogInformation("Transaction {TxHash} accepted into the pool. Size: {Size} bytes, Fee: {Fee}",
                                   tx.Hash, tx.SizeInBytes, tx.Fee);

            return true;
        }

        /// <summary>
        /// Removes the transaction if present and returns <c>true</c>. Otherwise <c>false</c>.
        /// </summary>
        public bool Remove(string txHash)
        {
            if (txHash is null) throw new ArgumentNullException(nameof(txHash));

            if (!_map.TryRemove(txHash, out var entry))
                return false;

            lock (_feeLock)
            {
                _feeOrdered.Remove(entry);
            }

            Interlocked.Add(ref _currentPoolSizeBytes, -entry.Transaction.SizeInBytes);
            return true;
        }

        /// <summary>
        /// Returns up to <paramref name="maxCount"/> pending transactions ordered by fee-rate (desc).
        /// </summary>
        public IReadOnlyCollection<ITransaction> GetPendingTransactions(int maxCount)
        {
            if (maxCount <= 0) throw new ArgumentOutOfRangeException(nameof(maxCount));

            var list = new List<ITransaction>(maxCount);

            lock (_feeLock)
            {
                foreach (var entry in _feeOrdered)
                {
                    if (list.Count == maxCount) break;
                    list.Add(entry.Transaction);
                }
            }

            return list;
        }

        /// <summary>
        /// True if the transaction is present in the pool.
        /// </summary>
        public bool Contains(string txHash) => txHash != null && _map.ContainsKey(txHash);

        #endregion

        #region Event Handlers

        private Task OnBlockCommitted(BlockCommittedEvent evt)
        {
            foreach (var hash in evt.ConfirmedTransactionHashes)
            {
                if (Remove(hash))
                    _logger.LogDebug("Evicted confirmed transaction {TxHash} from pool.", hash);
            }
            return Task.CompletedTask;
        }

        private Task OnChainReorg(ChainReorgEvent evt)
        {
            // Attempt to re-add reverted transactions; ignore failures (duplicates, invalid, etc.)
            _ = Parallel.ForEach(evt.RevertedTransactions, async tx =>
            {
                try
                {
                    await TryAddAsync(tx, _cts.Token).ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error re-enqueueing reverted transaction {TxHash}", tx.Hash);
                }
            });

            return Task.CompletedTask;
        }

        #endregion

        #region House-Keeping

        private async Task HouseKeepingLoopAsync()
        {
            var ct = _cts.Token;
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    FlushExpiredTransactions();
                    // House-keeping interval can be tuned; using 30 seconds as a sane default.
                    await Task.Delay(TimeSpan.FromSeconds(30), ct).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    // Expected on shutdown.
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Unexpected error in TransactionPool maintenance loop.");
                }
            }
        }

        private void FlushExpiredTransactions()
        {
            var now = DateTimeOffset.UtcNow;
            var toRemove = new List<TransactionEntry>();

            lock (_feeLock)
            {
                foreach (var entry in _feeOrdered.Reverse()) // Cheap traversal; new txs likely to expire later.
                {
                    if (now - entry.EnqueueTime > _txTimeToLive)
                        toRemove.Add(entry);
                    else
                        break; // Because set is ordered by fee desc, not time; can't break reliably.
                }
            }

            foreach (var entry in toRemove)
            {
                if (Remove(entry.Transaction.Hash))
                    _logger.LogDebug("Expired transaction {TxHash} evicted from pool.", entry.Transaction.Hash);
            }
        }

        #endregion

        #region Disposal

        public void Dispose()
        {
            _cts.Cancel();
            try
            {
                _houseKeeperTask.Wait(TimeSpan.FromSeconds(5));
            }
            catch (AggregateException ae) when (ae.InnerExceptions.All(e => e is TaskCanceledException))
            { /* ignore */ }

            _cts.Dispose();
            _logger.LogInformation("TransactionPool disposed. Remaining txs: {Count}", _map.Count);
        }

        #endregion

        #region Nested types

        /// <summary>
        /// Wraps a transaction together with metadata used for sorting & expiry.
        /// </summary>
        private sealed class TransactionEntry
        {
            public ITransaction Transaction { get; }
            public DateTimeOffset EnqueueTime { get; }

            public TransactionEntry(ITransaction tx)
            {
                Transaction = tx ?? throw new ArgumentNullException(nameof(tx));
                EnqueueTime = DateTimeOffset.UtcNow;
            }

            // Comparison is by fee-rate (fee per byte) in descending order.
            public static IComparer<TransactionEntry> FeeDescendingComparer { get; } =
                Comparer<TransactionEntry>.Create((a, b) =>
                {
                    var feeRateA = a.Transaction.Fee / a.Transaction.SizeInBytes;
                    var feeRateB = b.Transaction.Fee / b.Transaction.SizeInBytes;

                    var cmp = feeRateB.CompareTo(feeRateA); // Descending
                    return cmp != 0 ? cmp : string.CompareOrdinal(a.Transaction.Hash, b.Transaction.Hash);
                });
        }

        #endregion
    }
}
```