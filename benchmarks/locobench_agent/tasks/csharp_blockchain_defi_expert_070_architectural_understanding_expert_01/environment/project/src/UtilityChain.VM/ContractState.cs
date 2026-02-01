```csharp
using System;
using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using UtilityChain.Common;          // Shared helpers (hashing, encoding, etc.)
using UtilityChain.Cryptography;    // Abstractions for Merkle roots, hashing
using UtilityChain.VM.Internal;     // IStateSnapshot, IStateProvider, etc.

namespace UtilityChain.VM
{
    /// <summary>
    ///     Represents the mutable state of a deployed smart-contract inside the UtilityChain
    ///     virtual machine. A <see cref="ContractState" /> is a versioned, thread-safe,
    ///     key-value store that supports optimistic transactions with commit / rollback
    ///     semantics. A cryptographic hash of the state is produced on every commit so the
    ///     state can be included in the VM’s global state root for consensus verification.
    /// </summary>
    /// <remarks>
    ///     IMPLEMENTATION NOTES
    ///     ‑ Underlying data is stored in a <see cref="ConcurrentDictionary{TKey,TValue}" />
    ///       to support concurrent reads. Writes are serialized via <see cref="ReaderWriterLockSlim" />.
    ///     ‑ State transactions are lightweight; they only record the diff (changed keys)
    ///       so rollbacks are O(#changes).
    ///     ‑ All public methods are noexcept; user-code errors are surfaced as
    ///       <see cref="VirtualMachineException" /> to unify error handling.
    /// </remarks>
    public sealed class ContractState : IStateSnapshot, IDisposable
    {
        #region Nested types

        private sealed record StorageEntry(byte[] Key, byte[] Value);

        private sealed class TransactionContext
        {
            internal readonly Dictionary<string, StorageEntry> Diff = new(StringComparer.Ordinal);
            internal readonly HashSet<string> DeletedKeys = new(StringComparer.Ordinal);

            internal void Reset()
            {
                Diff.Clear();
                DeletedKeys.Clear();
            }
        }

        #endregion

        private readonly ConcurrentDictionary<string, byte[]> _store = new(StringComparer.Ordinal);
        private readonly ReaderWriterLockSlim _rwLock          = new(LockRecursionPolicy.SupportsRecursion);
        private readonly IMerkleRootCalculator _merkleRoot;   // Injected via DI
        private readonly ArrayPool<byte> _bufferPool           = ArrayPool<byte>.Shared;

        private TransactionContext? _currentTx;
        private bool _disposed;

        public ContractState(IMerkleRootCalculator merkleRoot)
        {
            _merkleRoot = merkleRoot ?? throw new ArgumentNullException(nameof(merkleRoot));
        }

        #region Snapshot metadata

        public ulong Revision     { get; private set; }
        public string Hash        { get; private set; } = string.Empty;
        public DateTimeOffset Ts  { get; private set; } = DateTimeOffset.UtcNow;

        #endregion

        #region Reading

        /// <inheritdoc />
        public bool TryGet(ReadOnlySpan<byte> key, [NotNullWhen(true)] out byte[]? value)
        {
            ThrowIfDisposed();

            var keyHex = key.ToHex();

            // If we are inside a transaction prefer the staged value
            if (_currentTx is { } tx)
            {
                if (tx.DeletedKeys.Contains(keyHex))
                {
                    value = null;
                    return false;
                }

                if (tx.Diff.TryGetValue(keyHex, out var entry))
                {
                    value = entry.Value;
                    return true;
                }
            }

            // Fallback to committed store
            return _store.TryGetValue(keyHex, out value);
        }

        #endregion

        #region Writing

        /// <inheritdoc />
        public void Put(ReadOnlySpan<byte> key, ReadOnlySpan<byte> value)
        {
            if (value.IsEmpty) throw new VirtualMachineException("Value cannot be empty.");
            WriteInternal(key, value, isDelete: false);
        }

        /// <inheritdoc />
        public void Delete(ReadOnlySpan<byte> key) => WriteInternal(key, ReadOnlySpan<byte>.Empty, isDelete: true);

        private void WriteInternal(ReadOnlySpan<byte> key, ReadOnlySpan<byte> value, bool isDelete)
        {
            ThrowIfDisposed();

            var keyHex = key.ToHex();

            _rwLock.EnterWriteLock();
            try
            {
                if (_currentTx is null)
                    throw new VirtualMachineException("Attempted to mutate state outside of an active transaction.");

                if (isDelete)
                {
                    _currentTx.DeletedKeys.Add(keyHex);
                    _currentTx.Diff.Remove(keyHex);
                }
                else
                {
                    var valueCopy = value.ToArray(); // Defensive copy
                    _currentTx.Diff[keyHex] = new StorageEntry(key.ToArray(), valueCopy);
                    _currentTx.DeletedKeys.Remove(keyHex);
                }
            }
            finally
            {
                _rwLock.ExitWriteLock();
            }
        }

        #endregion

        #region Transaction lifecycle

        /// <inheritdoc />
        public void Begin()
        {
            ThrowIfDisposed();

            _rwLock.EnterWriteLock();
            try
            {
                if (_currentTx is not null)
                    throw new VirtualMachineException("Nested transactions are not supported.");

                _currentTx = new TransactionContext();
            }
            finally
            {
                _rwLock.ExitWriteLock();
            }
        }

        /// <inheritdoc />
        public void Commit()
        {
            ThrowIfDisposed();

            _rwLock.EnterWriteLock();
            try
            {
                if (_currentTx is null)
                    throw new VirtualMachineException("No active transaction to commit.");

                foreach (string delKey in _currentTx.DeletedKeys)
                    _store.TryRemove(delKey, out _);

                foreach ((string _, StorageEntry entry) in _currentTx.Diff)
                    _store[entry.Key.ToHex()] = entry.Value;

                Revision++;
                Hash = ComputeStateRoot();
                Ts = DateTimeOffset.UtcNow;

                _currentTx.Reset();
                _currentTx = null;
            }
            finally
            {
                _rwLock.ExitWriteLock();
            }
        }

        /// <inheritdoc />
        public void Rollback()
        {
            ThrowIfDisposed();

            _rwLock.EnterWriteLock();
            try
            {
                if (_currentTx is null)
                    throw new VirtualMachineException("No active transaction to rollback.");

                _currentTx.Reset();
                _currentTx = null;
            }
            finally
            {
                _rwLock.ExitWriteLock();
            }
        }

        #endregion

        #region Serialization

        /// <summary>
        ///     Serializes the entire committed store to a compact JSON document.
        ///     The output is intended for auditing and should not be used for consensus.
        /// </summary>
        public byte[] ToJson()
        {
            ThrowIfDisposed();

            _rwLock.EnterReadLock();
            try
            {
                return JsonSerializer.SerializeToUtf8Bytes(_store, JsonSerializerOptionsCache.CamelCase);
            }
            finally
            {
                _rwLock.ExitReadLock();
            }
        }

        /// <summary>
        ///     Restores the state from a JSON blob previously produced by <see cref="ToJson" />.
        ///     Existing state will be overwritten.
        /// </summary>
        public void LoadJson(ReadOnlySpan<byte> json)
        {
            ThrowIfDisposed();

            Dictionary<string, byte[]> data;
            try
            {
                data = JsonSerializer.Deserialize<Dictionary<string, byte[]>>(json, JsonSerializerOptionsCache.CamelCase)
                       ?? throw new InvalidOperationException("Deserialized JSON produced null.");
            }
            catch (JsonException ex)
            {
                throw new VirtualMachineException("Invalid state JSON.", ex);
            }

            _rwLock.EnterWriteLock();
            try
            {
                _store.Clear();
                foreach ((string k, byte[] v) in data)
                    _store[k] = v;

                Revision++;
                Hash = ComputeStateRoot();
                Ts = DateTimeOffset.UtcNow;
            }
            finally
            {
                _rwLock.ExitWriteLock();
            }
        }

        #endregion

        #region Helpers

        private string ComputeStateRoot()
        {
            // Prepare deterministic byte concatenation => hash
            using var sha = SHA256.Create();

            foreach (var kvp in _store)
            {
                sha.TransformBlock(Encoding.UTF8.GetBytes(kvp.Key), 0, kvp.Key.Length, null, 0);
                sha.TransformBlock(kvp.Value, 0, kvp.Value.Length, null, 0);
            }

            sha.TransformFinalBlock(Array.Empty<byte>(), 0, 0);
            return sha.Hash!.ToHex(); // Extensions from UtilityChain.Common
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(ContractState));
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;

            _rwLock.Dispose();
            _disposed = true;
        }

        #endregion
    }

    #region Supporting types

    /// <summary>
    ///     Shared JSON options cache.
    /// </summary>
    internal static class JsonSerializerOptionsCache
    {
        internal static readonly JsonSerializerOptions CamelCase = new()
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            WriteIndented        = false
        };
    }

    /// <summary>
    ///     Utility extensions used by the VM.
    /// </summary>
    internal static class ByteExtensions
    {
        private const string HexAlphabet = "0123456789abcdef";

        public static string ToHex(this byte[] bytes) => bytes.AsSpan().ToHex();

        public static string ToHex(this ReadOnlySpan<byte> span)
        {
            var chars = new char[span.Length * 2];
            for (var i = 0; i < span.Length; i++)
            {
                var b = span[i];
                chars[i * 2]     = HexAlphabet[b >> 4];
                chars[i * 2 + 1] = HexAlphabet[b & 0xF];
            }

            return new string(chars);
        }
    }

    #endregion
}
```