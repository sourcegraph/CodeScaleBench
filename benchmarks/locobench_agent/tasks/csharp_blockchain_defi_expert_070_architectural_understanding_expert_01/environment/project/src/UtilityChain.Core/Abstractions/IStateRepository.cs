```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Core/Abstractions/IStateRepository.cs

using System;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Threading;
using System.Threading.Tasks;

namespace UtilityChain.Core.Abstractions;

/// <summary>
/// Abstraction over the persistent state store used by UtilityChain.
/// A concrete implementation may be backed by LevelDB, RocksDB, LiteDB, an RDBMS, or an in-memory cache.
/// All operations are asynchronous and cancellation-token aware in order to integrate cleanly with the
/// runtime’s cooperative-cancellation model.
/// </summary>
public interface IStateRepository : IAsyncDisposable
{
    /// <summary>
    /// Initializes the underlying storage engine, creating files / tables as needed.
    /// Implementations must be idempotent; calling <see cref="InitialiseAsync"/> more than once
    /// should be a no-op after the first successful initialization.
    /// </summary>
    /// <param name="cancellationToken">Token that signals the caller no longer needs the operation.</param>
    Task InitialiseAsync(CancellationToken cancellationToken = default);

    /// <summary>
    /// Returns a pointer to the latest committed state for a given chain.
    /// </summary>
    /// <param name="chainId">Deterministic identifier of the blockchain instance.</param>
    /// <param name="cancellationToken">Cancellation signal.</param>
    /// <returns>A <see cref="ChainStatePointer"/> describing the head of the chain; null when chain is unknown.</returns>
    ValueTask<ChainStatePointer?> GetHeadAsync(
        string chainId,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Retrieves a typed snapshot for the specified <paramref name="hash"/>.
    /// </summary>
    /// <typeparam name="TState">Concrete type describing the state object.</typeparam>
    /// <param name="hash">Content-addressable identifier (usually SHA-256) for the state record.</param>
    /// <param name="cancellationToken">Cancellation signal.</param>
    /// <returns>A materialized snapshot of <typeparamref name="TState"/> or null if not found.</returns>
    ValueTask<StateSnapshot<TState>?> GetAsync<TState>(
        StateHash hash,
        CancellationToken cancellationToken = default) where TState : notnull;

    /// <summary>
    /// Persists a new state snapshot atomically. Implementations must ensure that either the snapshot
    /// is fully committed and discoverable by subsequent <see cref="GetHeadAsync"/> calls, or not committed at all.
    /// </summary>
    /// <typeparam name="TState">Type describing the state payload.</typeparam>
    /// <param name="snapshot">Snapshot to be persisted.</param>
    /// <param name="cancellationToken">Cancellation signal.</param>
    /// <returns>The resulting content-hash produced by the store.</returns>
    ValueTask<StateHash> PersistAsync<TState>(
        StateSnapshot<TState> snapshot,
        CancellationToken cancellationToken = default) where TState : notnull;

    /// <summary>
    /// Streams state snapshots in ascending order of their block height.
    /// The stream starts at <paramref name="fromHeight"/> (inclusive) and ends with the current head.
    /// </summary>
    /// <typeparam name="TState">Type of the state payload to stream.</typeparam>
    /// <param name="chainId">Target blockchain id.</param>
    /// <param name="fromHeight">Zero-based height from which to begin the stream.</param>
    /// <param name="cancellationToken">Cancellation signal.</param>
    /// <returns>IAsyncEnumerable that lazily fetches snapshots.</returns>
    IAsyncEnumerable<StateSnapshot<TState>> StreamAsync<TState>(
        string chainId,
        long fromHeight,
        CancellationToken cancellationToken = default) where TState : notnull;

    /// <summary>
    /// Indicates whether the repository already contains the specified state hash.
    /// </summary>
    ValueTask<bool> ContainsAsync(
        StateHash hash,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Prunes old snapshots according to the provided <paramref name="policy"/>.
    /// Implementations are expected to apply pruning in a batched, efficient manner.
    /// </summary>
    /// <param name="chainId">Blockchain identifier.</param>
    /// <param name="policy">Retention strategy.</param>
    /// <param name="cancellationToken">Cancellation signal.</param>
    Task PruneAsync(
        string chainId,
        RetentionPolicy policy,
        CancellationToken cancellationToken = default);
}

/// <summary>
/// Lightweight value object representing a unique, content-addressable hash.
/// </summary>
/// <param name="Value">Underlying hash string in hexadecimal form.</param>
public readonly record struct StateHash(string Value)
{
    public static StateHash Empty => new(string.Empty);

    public bool IsEmpty => string.IsNullOrEmpty(Value);

    public override string ToString() => Value;
}

/// <summary>
/// Describes the logical head of the chain at a particular point in time.
/// Primarily used to resume consensus or rebuild indexes.
/// </summary>
/// <param name="ChainId">Deterministic chain identifier.</param>
/// <param name="Height">Block height belonging to <paramref name="Hash"/>.</param>
/// <param name="Hash">Hash of the state snapshot.</param>
public readonly record struct ChainStatePointer(
    string ChainId,
    long Height,
    StateHash Hash);

/// <summary>
/// Generic container for a state payload along with associated metadata.
/// </summary>
/// <typeparam name="TState">Concrete type representing the actual state.</typeparam>
/// <param name="ChainId">Id of the blockchain this snapshot belongs to.</param>
/// <param name="Height">Block height at which the snapshot was taken.</param>
/// <param name="Hash">Content-hash that uniquely identifies this snapshot.</param>
/// <param name="Payload">The application-specific state object.</param>
public sealed record StateSnapshot<TState>(
    string ChainId,
    long Height,
    StateHash Hash,
    TState Payload) : IStateSnapshot
    where TState : notnull;

/// <summary>
/// Untyped view over a state snapshot. Useful for logging, bulk-operations
/// or generically processing snapshots without reflection.
/// </summary>
public interface IStateSnapshot
{
    string ChainId { get; }
    long Height    { get; }
    StateHash Hash { get; }
}

/// <summary>
/// Strategies to determine which old snapshots should be deleted from storage.
/// Enum values are intentionally ordered from most conservative to most aggressive.
/// </summary>
public enum RetentionPolicy
{
    /// <summary>Keep every historical snapshot—no pruning.</summary>
    KeepAll = 0,

    /// <summary>Keep only the latest snapshot for the chain.</summary>
    KeepLatest = 1,

    /// <summary>Keep the latest <c>N</c> snapshots, where <c>N</c> is provided via configuration.</summary>
    KeepLastN = 2,

    /// <summary>Keep snapshots younger than a configured number of hours.</summary>
    KeepByAge = 3
}
```