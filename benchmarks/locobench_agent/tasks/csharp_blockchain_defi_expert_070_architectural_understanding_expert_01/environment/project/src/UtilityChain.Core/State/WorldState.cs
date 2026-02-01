```csharp
// ---------------------------------------------------------------------------------------------------------------------
//  UtilityChain Core Suite – WorldState
//  File: UtilityChainCoreSuite/src/UtilityChain.Core/State/WorldState.cs
//  Description: Maintains the canonical state tree for accounts, smart–contracts, and governance metadata. 
//               Implements light-weight snapshotting for optimistic block execution, and publishes domain 
//               events to all interested sub-systems (consensus, governance, staking, etc.).
//  --------------------------------------------------------------------------------------------------------------------
//
//  Copyright © UtilityChain Contributors.
//  This file is part of UtilityChain Core Suite, licensed under the MIT License.
// ---------------------------------------------------------------------------------------------------------------------
#nullable enable

using System;
using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Core.State
{
    /// <summary>
    /// Immutable token returned by <see cref="IWorldState.TakeSnapshot"/>. 
    /// Used to revert speculative changes when a block fails validation.
    /// </summary>
    public readonly record struct SnapshotToken(Guid Id, long Version);

    /// <summary>
    /// Aggregate root for domain events raised by <see cref="WorldState"/>.
    /// </summary>
    /// <typeparam name="TEvent">Event payload.</typeparam>
    public interface IEventBus
    {
        void Publish<TEvent>(TEvent @event);
    }

    /// <summary>
    /// Provides hashing utilities such that the world state can remain agnostic 
    /// about the concrete algorithm (SHA-2, Keccak, Blake3, …).
    /// </summary>
    public interface IHashProvider
    {
        byte[] Hash(ReadOnlySpan<byte> data);
    }

    internal sealed class Sha256HashProvider : IHashProvider
    {
        private readonly ArrayPool<byte> _pool = ArrayPool<byte>.Shared;

        public byte[] Hash(ReadOnlySpan<byte> data)
        {
            var rented = _pool.Rent(data.Length);
            data.CopyTo(rented);
            try
            {
                return SHA256.HashData(rented.AsSpan(0, data.Length));
            }
            finally
            {
                _pool.Return(rented);
            }
        }
    }

    /// <summary>
    /// Represents the serializable state of a single chain address.
    /// </summary>
    public sealed class AccountState : ICloneable
    {
        public required string Address { get; init; } = default!;
        public ulong Nonce { get; set; }
        public decimal Balance { get; set; }

        // Contract storage – key/value pairs for EVM-like bytecode or native modules
        public Dictionary<string, byte[]> Storage { get; } = new(StringComparer.Ordinal);

        // Arbitrary data used by staking, governance or NFT modules. 
        // Kept intentionally loose for domain extension.
        public Dictionary<string, object?> Metadata { get; } = new(StringComparer.Ordinal);

        public object Clone()
        {
            var cloned = (AccountState)MemberwiseClone();
            cloned.Storage = new(Storage, StringComparer.Ordinal);
            cloned.Metadata = new(Storage.Count, StringComparer.Ordinal);

            foreach (var (key, value) in Storage)
                cloned.Storage[key] = (byte[])value.Clone();

            foreach (var (key, value) in Metadata)
                cloned.Metadata[key] = value switch
                {
                    ICloneable c => c.Clone(),
                    _ => value
                };

            return cloned;
        }
    }

    /// <summary>
    /// Declarative representation of an account modification, produced 
    /// by transaction execution engines.
    /// </summary>
    public sealed record AccountMutation(
        string Address,
        decimal BalanceDelta,
        ulong? SetNonce = null,
        IReadOnlyDictionary<string, byte[]>? StorageWrites = null,
        IReadOnlyDictionary<string, object?>? MetadataWrites = null
    );

    /// <summary>
    /// Public surface for state-machine interactions throughout the node.
    /// </summary>
    public interface IWorldState
    {
        AccountState GetAccount(string address, bool createIfMissing = false);
        void Apply(AccountMutation mutation);
        SnapshotToken TakeSnapshot();
        void RevertSnapshot(SnapshotToken token);
        ValueTask CommitAsync(CancellationToken cancellationToken = default);
        byte[] ComputeRootHash();
    }

    /// <summary>
    /// Thread-safe, in-memory implementation of <see cref="IWorldState"/>.
    /// Uses copy-on-write semantics for snapshots to minimise allocations.
    /// In production, a persistent variant will write mutations to RocksDB/LMDB.
    /// </summary>
    public sealed class WorldState : IWorldState
    {
        private readonly ReaderWriterLockSlim _lock = new();
        private readonly ILogger<WorldState> _logger;
        private readonly IEventBus _eventBus;
        private readonly IHashProvider _hashProvider;

        // Canonical state – mutated after successful Commit().
        private readonly Dictionary<string, AccountState> _accounts = new(StringComparer.Ordinal);
        private long _version;

        // Speculative layer applied on top of the canonical state until Commit/Revert.
        private readonly Stack<StateSnapshot> _snapshots = new();

        public WorldState(
            ILogger<WorldState> logger,
            IEventBus eventBus,
            IHashProvider? hashProvider = null)
        {
            _logger = logger;
            _eventBus = eventBus;
            _hashProvider = hashProvider ?? new Sha256HashProvider();
        }

        #region Public API ---------------------------------------------------------------------

        public AccountState GetAccount(string address, bool createIfMissing = false)
        {
            ArgumentNullException.ThrowIfNull(address);

            _lock.EnterReadLock();
            try
            {
                if (CurrentLayer.TryGetValue(address, out var account))
                    return account;

                if (!createIfMissing)
                    throw new KeyNotFoundException($"Account '{address}' not found.");

                // Promote read-lock to write-lock
                _lock.ExitReadLock();
                _lock.EnterWriteLock();
                try
                {
                    // Double-check to avoid race condition after lock promotion
                    if (CurrentLayer.TryGetValue(address, out account))
                        return account;

                    account = new AccountState { Address = address };
                    CurrentLayer[address] = account;
                    return account;
                }
                finally
                {
                    _lock.ExitWriteLock();
                    _lock.EnterReadLock(); // restore original lock state
                }
            }
            finally
            {
                _lock.ExitReadLock();
            }
        }

        public void Apply(AccountMutation mutation)
        {
            ArgumentNullException.ThrowIfNull(mutation);

            _lock.EnterWriteLock();
            try
            {
                var target = GetAccount(mutation.Address, createIfMissing: true);

                checked
                {
                    target.Balance += mutation.BalanceDelta;
                }

                if (mutation.SetNonce.HasValue)
                    target.Nonce = mutation.SetNonce.Value;

                if (mutation.StorageWrites is { Count: > 0 })
                    foreach (var (key, value) in mutation.StorageWrites)
                        target.Storage[key] = value;

                if (mutation.MetadataWrites is { Count: > 0 })
                    foreach (var (key, value) in mutation.MetadataWrites)
                        target.Metadata[key] = value;
            }
            finally
            {
                _lock.ExitWriteLock();
            }
        }

        public SnapshotToken TakeSnapshot()
        {
            _lock.EnterWriteLock();
            try
            {
                var snapshot = new StateSnapshot(_version, ShallowClone(CurrentLayer));
                _snapshots.Push(snapshot);
                _logger.LogDebug("Snapshot taken at version {Version}", snapshot.Version);
                return new SnapshotToken(snapshot.Id, snapshot.Version);
            }
            finally
            {
                _lock.ExitWriteLock();
            }
        }

        public void RevertSnapshot(SnapshotToken token)
        {
            _lock.EnterWriteLock();
            try
            {
                if (_snapshots.Count == 0 || _snapshots.Peek().Id != token.Id)
                    throw new InvalidOperationException("Snapshot mismatch or already reverted.");

                var snapshot = _snapshots.Pop();
                RestoreLayer(snapshot.Layer);
                _version = snapshot.Version;
                _logger.LogWarning("State reverted to snapshot {Version}", snapshot.Version);
            }
            finally
            {
                _lock.ExitWriteLock();
            }
        }

        public async ValueTask CommitAsync(CancellationToken cancellationToken = default)
        {
            _lock.EnterWriteLock();
            try
            {
                if (_snapshots.Count == 0)
                    throw new InvalidOperationException("No snapshot to commit.");

                var snapshot = _snapshots.Pop();
                // Merge snapshot layer into canonical layer
                foreach (var (address, account) in snapshot.Layer)
                    _accounts[address] = account;

                _version++;
                var root = ComputeRootHash();

                // Publish event outside the lock to avoid dead-locks in user code
                Task.Run(() =>
                    _eventBus.Publish(new WorldStateCommittedEvent(root, _version)), cancellationToken);
            }
            finally
            {
                _lock.ExitWriteLock();
            }

            await Task.CompletedTask;
        }

        public byte[] ComputeRootHash()
        {
            _lock.EnterReadLock();
            try
            {
                using var hashAlgo = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                foreach (var (address, account) in _accounts)
                {
                    hashAlgo.AppendData(System.Text.Encoding.UTF8.GetBytes(address));
                    hashAlgo.AppendData(BitConverter.GetBytes(account.Balance));
                    hashAlgo.AppendData(BitConverter.GetBytes(account.Nonce));

                    foreach (var (key, value) in account.Storage)
                    {
                        hashAlgo.AppendData(System.Text.Encoding.UTF8.GetBytes(key));
                        hashAlgo.AppendData(value);
                    }
                }
                return hashAlgo.GetHashAndReset();
            }
            finally
            {
                _lock.ExitReadLock();
            }
        }

        #endregion

        #region Internal helpers ----------------------------------------------------------------

        private Dictionary<string, AccountState> CurrentLayer =>
            _snapshots.Count > 0 ? _snapshots.Peek().Layer : _accounts;

        private static Dictionary<string, AccountState> ShallowClone(
            Dictionary<string, AccountState> source)
        {
            var clone = new Dictionary<string, AccountState>(source.Count, StringComparer.Ordinal);
            foreach (var (address, account) in source)
                clone[address] = (AccountState)account.Clone();

            return clone;
        }

        private void RestoreLayer(Dictionary<string, AccountState> target)
        {
            // Dispose modified accounts for GC friendliness in prod systems
            _accounts.Clear();
            foreach (var (address, account) in target)
                _accounts[address] = account;
        }

        #endregion -----------------------------------------------------------------------------
    }

    /// <summary>
    /// Internal representation for a snapshot, stored on a stack.
    /// </summary>
    internal sealed class StateSnapshot
    {
        public Guid Id { get; } = Guid.NewGuid();
        public long Version { get; }
        public Dictionary<string, AccountState> Layer { get; }

        public StateSnapshot(long version, Dictionary<string, AccountState> layer)
        {
            Version = version;
            Layer = layer;
        }
    }

    /// <summary>
    /// Event raised after <see cref="WorldState.CommitAsync"/> finishes successfully.
    /// </summary>
    /// <param name="RootHash">Merkle-like hash of the global state.</param>
    /// <param name="Version">Monotonically increasing world-state version.</param>
    public sealed record WorldStateCommittedEvent(byte[] RootHash, long Version);
}
```