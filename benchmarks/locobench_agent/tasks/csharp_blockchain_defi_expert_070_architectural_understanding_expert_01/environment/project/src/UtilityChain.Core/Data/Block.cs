using System;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace UtilityChain.Core.Data
{
    /// <summary>
    /// Represents an immutable block in the UtilityChain ledger.
    /// </summary>
    public sealed class Block : IEquatable<Block>
    {
        private const int MaxTransactionsPerBlock = 10_000;
        private const int DefaultDifficulty = 4;                       // Leading zeroes required for PoW

        private readonly Lazy<string> _hashLazy;

        private Block(
            int height,
            string previousHash,
            DateTimeOffset timestamp,
            ImmutableArray<ITransaction> transactions,
            long nonce,
            string merkleRoot,
            byte[] signature,
            byte[] producerPublicKey)
        {
            Height            = height;
            PreviousHash      = previousHash;
            Timestamp         = timestamp;
            Transactions      = transactions;
            Nonce             = nonce;
            MerkleRoot        = merkleRoot;
            Signature         = signature;
            ProducerPublicKey = producerPublicKey;

            _hashLazy = new Lazy<string>(ComputeHashInternal, isThreadSafe: true);
        }

        #region Public Properties

        /// <summary>The height (index) of the block—0 for the genesis block.</summary>
        public int Height { get; }

        /// <summary>SHA-256 hash of the previous block’s header.</summary>
        public string PreviousHash { get; }

        /// <summary>Timestamp (UTC) when the block was produced.</summary>
        public DateTimeOffset Timestamp { get; }

        /// <summary>The immutable list of transactions contained in the block.</summary>
        public IReadOnlyList<ITransaction> Transactions { get; }

        /// <summary>Proof-of-work nonce that satisfies the network’s difficulty target.</summary>
        public long Nonce { get; }

        /// <summary>Merkle root of the transaction list.</summary>
        public string MerkleRoot { get; }

        /// <summary>Digital signature of the block header (excluding <see cref="Hash"/>).</summary>
        public byte[] Signature { get; }

        /// <summary>Public key of the entity that produced the block.</summary>
        public byte[] ProducerPublicKey { get; }

        /// <summary>Cached SHA-256 hash of the block header + signature.</summary>
        public string Hash => _hashLazy.Value;

        #endregion

        #region Genesis

        /// <summary>Returns the singleton genesis block (deterministically generated).</summary>
        public static Block Genesis => _genesis.Value;

        private static readonly Lazy<Block> _genesis = new(() =>
        {
            var emptyTx  = ImmutableArray<ITransaction>.Empty;
            var merkle   = ComputeMerkleRoot(emptyTx);
            var dummyKey = Encoding.UTF8.GetBytes("UtilityChain-Genesis-Key");

            return new Block(
                height: 0,
                previousHash: new string('0', 64),
                timestamp: DateTimeOffset.UnixEpoch,
                transactions: emptyTx,
                nonce: 0,
                merkleRoot: merkle,
                signature: Array.Empty<byte>(),
                producerPublicKey: dummyKey
            );
        }, isThreadSafe: true);

        #endregion

        #region Mining / Creation

        /// <summary>
        /// Mines a new block using the provided transactions and ECDSA key pair.
        /// </summary>
        /// <param name="previousBlock">The head of the current chain.</param>
        /// <param name="pendingTransactions">Transactions to include.</param>
        /// <param name="key">ECDSA key pair of the producer.</param>
        /// <param name="difficulty">Network difficulty (optional).</param>
        /// <param name="cancellationToken">Token for aborting the mining loop.</param>
        /// <returns>A fully-formed, signed block.</returns>
        /// <exception cref="OperationCanceledException">Thrown if mining is cancelled.</exception>
        /// <exception cref="ArgumentNullException">Thrown if a required parameter is missing.</exception>
        public static Block Mine(
            Block previousBlock,
            IEnumerable<ITransaction> pendingTransactions,
            ECDsa key,
            int? difficulty = null,
            CancellationToken cancellationToken = default)
        {
            if (previousBlock       is null) throw new ArgumentNullException(nameof(previousBlock));
            if (pendingTransactions is null) throw new ArgumentNullException(nameof(pendingTransactions));
            if (key                is null) throw new ArgumentNullException(nameof(key));

            int    height       = checked(previousBlock.Height + 1);
            var    txArray      = pendingTransactions.Take(MaxTransactionsPerBlock).ToImmutableArray();
            string merkleRoot   = ComputeMerkleRoot(txArray);
            int    targetZeros  = difficulty.GetValueOrDefault(DefaultDifficulty);
            string targetPrefix = new string('0', targetZeros);

            long   nonce;
            string candidateHash;

            using var sha256 = SHA256.Create();
            DateTimeOffset timestamp = DateTimeOffset.UtcNow;

            for (nonce = 0;; nonce++)
            {
                cancellationToken.ThrowIfCancellationRequested();

                candidateHash = CalculateHash(
                    sha256,
                    height,
                    previousBlock.Hash,
                    timestamp,
                    merkleRoot,
                    nonce);

                if (candidateHash.StartsWith(targetPrefix, StringComparison.Ordinal))
                    break;
            }

            // Sign the header
            byte[] headerBytes = Encoding.UTF8.GetBytes($"{height}{previousBlock.Hash}{timestamp:O}{merkleRoot}{nonce}");
            byte[] signature   = key.SignData(headerBytes, HashAlgorithmName.SHA256);
            byte[] pubKey      = key.ExportSubjectPublicKeyInfo();

            return new Block(
                height,
                previousBlock.Hash,
                timestamp,
                txArray,
                nonce,
                merkleRoot,
                signature,
                pubKey
            );
        }

        #endregion

        #region Validation

        /// <summary>
        /// Validates the block’s PoW, Merkle root, transaction limit, and digital signature.
        /// </summary>
        /// <param name="difficulty">Required network difficulty.</param>
        /// <returns><c>true</c> if the block is internally consistent.</returns>
        public bool Validate(int difficulty = DefaultDifficulty)
        {
            string targetPrefix = new string('0', difficulty);

            if (!Hash.StartsWith(targetPrefix, StringComparison.Ordinal))
                return false;

            if (Transactions.Count > MaxTransactionsPerBlock)
                return false;

            if (!string.Equals(MerkleRoot, ComputeMerkleRoot(Transactions), StringComparison.Ordinal))
                return false;

            if (ProducerPublicKey.Length > 0)
            {
                using var ecdsa = ECDsa.Create();
                ecdsa.ImportSubjectPublicKeyInfo(ProducerPublicKey, out _);

                byte[] headerBytes = Encoding.UTF8.GetBytes($"{Height}{PreviousHash}{Timestamp:O}{MerkleRoot}{Nonce}");
                if (!ecdsa.VerifyData(headerBytes, Signature, HashAlgorithmName.SHA256))
                    return false;
            }

            return true;
        }

        #endregion

        #region Private Helpers

        private string ComputeHashInternal()
        {
            using var sha256 = SHA256.Create();
            return CalculateHash(sha256, Height, PreviousHash, Timestamp, MerkleRoot, Nonce);
        }

        private static string CalculateHash(
            SHA256 sha256,
            int height,
            string previousHash,
            DateTimeOffset timestamp,
            string merkleRoot,
            long nonce)
        {
            string raw = $"{height}{previousHash}{timestamp:O}{merkleRoot}{nonce}";
            byte[] bytes = Encoding.UTF8.GetBytes(raw);
            byte[] digest = sha256.ComputeHash(bytes);
            return BitConverter.ToString(digest)
                               .Replace("-", string.Empty)
                               .ToLowerInvariant();
        }

        private static string ComputeMerkleRoot(IReadOnlyList<ITransaction> transactions)
        {
            using var sha256 = SHA256.Create();

            if (transactions is null or { Count: 0 })
            {
                byte[] emptyHash = sha256.ComputeHash(Array.Empty<byte>());
                return BitConverter.ToString(emptyHash).Replace("-", string.Empty).ToLowerInvariant();
            }

            List<byte[]> layer = transactions
                .Select(tx => sha256.ComputeHash(tx.Id.ToByteArray()))
                .ToList();

            while (layer.Count > 1)
            {
                List<byte[]> next = new();

                for (int i = 0; i < layer.Count; i += 2)
                {
                    byte[] left  = layer[i];
                    byte[] right = i + 1 < layer.Count ? layer[i + 1] : left;
                    next.Add(sha256.ComputeHash(left.Concat(right).ToArray()));
                }

                layer = next;
            }

            return BitConverter.ToString(layer[0]).Replace("-", string.Empty).ToLowerInvariant();
        }

        #endregion

        #region Overrides / Equality

        public override string ToString()
        {
            var view = new
            {
                Height,
                PreviousHash,
                Hash,
                Timestamp,
                Nonce,
                MerkleRoot,
                TxCount = Transactions.Count
            };

            return JsonSerializer.Serialize(view);
        }

        public bool Equals(Block? other)
        {
            if (other is null) return false;
            if (ReferenceEquals(this, other)) return true;
            return Hash == other.Hash;
        }

        public override bool Equals(object? obj) => Equals(obj as Block);

        public override int GetHashCode() => Hash.GetHashCode(StringComparison.Ordinal);

        #endregion
    }

    /// <summary>
    /// Minimal transaction abstraction required for block assembly.
    /// Actual implementations live in separate domain modules.
    /// </summary>
    public interface ITransaction
    {
        /// <summary>Deterministic identifier of the transaction.</summary>
        Guid Id { get; }
    }
}