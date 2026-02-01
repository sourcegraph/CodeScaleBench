```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using UtilityChain.Common;
using UtilityChain.Common.Cryptography;
using UtilityChain.Common.Events;
using UtilityChain.Data.Abstractions;
using UtilityChain.Domain.Blocks;
using UtilityChain.Domain.Consensus;
using UtilityChain.Domain.Transactions;

namespace UtilityChain.Consensus.Strategies
{
    /// <summary>
    ///     Production–grade Proof-of-Authority consensus strategy.
    ///     Validators are pre-authorised entities whose public keys are stored in an on-chain
    ///     authority registry (<see cref="IAuthorityRegistry" />). Every validator is given a deterministic
    ///     time-slot in which they are expected to propose a new block. The order is based on a simple
    ///     round-robin schedule over the sorted validator set so that all authorities have equal influence.
    ///     
    ///     The strategy is designed to be plug-and-play: the concrete implementation is resolved at
    ///     runtime via dependency injection and registered behind the <see cref="IConsensusStrategy" />
    ///     interface.
    /// </summary>
    /// <remarks>
    ///     Internal data-flow:
    ///     
    ///     ┌─────────────┐      ProposeBlockAsync        ┌────────────────┐
    ///     │ Transaction  │  ───────────────────────────► │ ProofOfAuthority│
    ///     │     Pool     │                              │    Strategy     │
    ///     └─────────────┘                               └────────────────┘
    ///             ▲                                           │
    ///             │            NewBlockCommittedEvent         ▼
    ///             └───────────────────────────────────────────► (event-bus)
    /// </remarks>
    public sealed class ProofOfAuthorityStrategy : IConsensusStrategy, IDisposable
    {
        private readonly IAuthorityRegistry      _authorityRegistry;
        private readonly IBlockRepository        _blockRepository;
        private readonly IDateTimeProvider       _dateTime;
        private readonly IDeterministicScheduler _scheduler;
        private readonly ISignatureService       _signatureService;
        private readonly IEventBus               _eventBus;
        private readonly ILogger<ProofOfAuthorityStrategy> _logger;

        private readonly SemaphoreSlim _proposeLock = new(1, 1);
        private          bool          _disposed;

        public ConsensusAlgorithm Algorithm => ConsensusAlgorithm.ProofOfAuthority;

        public ProofOfAuthorityStrategy(
            IAuthorityRegistry authorityRegistry,
            IBlockRepository blockRepository,
            IDateTimeProvider dateTime,
            IDeterministicScheduler scheduler,
            ISignatureService signatureService,
            IEventBus eventBus,
            ILogger<ProofOfAuthorityStrategy> logger)
        {
            _authorityRegistry = authorityRegistry  ?? throw new ArgumentNullException(nameof(authorityRegistry));
            _blockRepository   = blockRepository    ?? throw new ArgumentNullException(nameof(blockRepository));
            _dateTime          = dateTime           ?? throw new ArgumentNullException(nameof(dateTime));
            _scheduler         = scheduler          ?? throw new ArgumentNullException(nameof(scheduler));
            _signatureService  = signatureService   ?? throw new ArgumentNullException(nameof(signatureService));
            _eventBus          = eventBus           ?? throw new ArgumentNullException(nameof(eventBus));
            _logger            = logger             ?? throw new ArgumentNullException(nameof(logger));
        }

        #region Proposal

        /// <inheritdoc />
        public async Task<Block?> ProposeBlockAsync(
            IReadOnlyCollection<Transaction> transactions,
            WalletKeyPair                 validatorKeyPair,
            CancellationToken             ct = default)
        {
            ArgumentNullException.ThrowIfNull(transactions);
            ArgumentNullException.ThrowIfNull(validatorKeyPair);

            await _proposeLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                // Ensure caller is an authorised validator for the current slot.
                if (!await IsCurrentSlotOwnerAsync(validatorKeyPair.PublicKey, ct))
                {
                    _logger.LogWarning("Validator {Validator} attempted to propose a block outside its slot.",
                        validatorKeyPair.Address);
                    return null;
                }

                // Gather previous block.
                BlockHeader previousHeader =
                    await _blockRepository.GetLatestBlockHeaderAsync(ct).ConfigureAwait(false);

                var newHeader = new BlockHeader
                {
                    Number            = previousHeader.Number + 1,
                    PreviousHash      = previousHeader.Hash,
                    Timestamp         = _dateTime.UtcNow,
                    MerkleRoot        = MerkleTree.ComputeRoot(transactions),
                    ValidatorAddress  = validatorKeyPair.Address,
                    ConsensusMetadata = BuildConsensusMetadata(previousHeader)
                };

                // Sign header.
                newHeader.Signature =
                    _signatureService.Sign(validatorKeyPair.PrivateKey, newHeader.Hash);

                var newBlock = new Block(newHeader, transactions);

                // Persist immediately to minimise fork window.
                await _blockRepository.AddBlockAsync(newBlock, ct).ConfigureAwait(false);

                // Notify subscribers.
                await _eventBus.PublishAsync(new NewBlockCommittedEvent(newBlock), ct);

                _logger.LogInformation("Block #{Number} successfully proposed by {Validator}.",
                    newBlock.Header.Number, newHeader.ValidatorAddress);

                return newBlock;
            }
            finally
            {
                _proposeLock.Release();
            }
        }

        #endregion

        #region Validation

        /// <inheritdoc />
        public async Task<bool> ValidateBlockAsync(Block block, CancellationToken ct = default)
        {
            ArgumentNullException.ThrowIfNull(block);

            // 1. Verify that the validator is authorised.
            if (!await _authorityRegistry.ExistsAsync(block.Header.ValidatorAddress, ct))
            {
                _logger.LogWarning("Block #{Number} rejected: validator {Validator} is not in the authority registry.",
                    block.Header.Number, block.Header.ValidatorAddress);
                return false;
            }

            // 2. Ensure that the validator is the rightful owner of this time-slot.
            if (!await IsValidSlotOwnerAsync(block, ct))
            {
                _logger.LogWarning("Block #{Number} rejected: validator {Validator} is not scheduled for this slot.",
                    block.Header.Number, block.Header.ValidatorAddress);
                return false;
            }

            // 3. Signature verification.
            var publicKey = await _authorityRegistry.GetPublicKeyAsync(block.Header.ValidatorAddress, ct);
            if (!_signatureService.Verify(publicKey, block.Header.Hash, block.Header.Signature))
            {
                _logger.LogWarning("Block #{Number} rejected: invalid signature by {Validator}.",
                    block.Header.Number, block.Header.ValidatorAddress);
                return false;
            }

            // 4. Timestamp monotonicity check.
            var previousHeader = await _blockRepository
               .FindHeaderByNumberAsync(block.Header.Number - 1, ct)
               .ConfigureAwait(false);

            if (previousHeader == null || block.Header.Timestamp <= previousHeader.Timestamp)
            {
                _logger.LogWarning("Block #{Number} rejected: timestamp not greater than previous.", block.Header.Number);
                return false;
            }

            // 5. Validate transactions MerkleRoot.
            if (block.Header.MerkleRoot != MerkleTree.ComputeRoot(block.Transactions))
            {
                _logger.LogWarning("Block #{Number} rejected: invalid Merkle root.", block.Header.Number);
                return false;
            }

            // Additional validations (gas, state transition, etc.) are delegated to the execution engine.

            return true;
        }

        #endregion

        #region Authority Registry Management

        /// <summary>
        ///     Adds a new authority validator. Triggers <see cref="AuthorityAddedEvent"/>.
        /// </summary>
        public async Task AddAuthorityAsync(
            Address            address,
            PublicKey          publicKey,
            CancellationToken  ct = default)
        {
            if (await _authorityRegistry.ExistsAsync(address, ct))
                throw new InvalidOperationException($"Validator {address} already exists in registry.");

            await _authorityRegistry.AddAsync(address, publicKey, ct);

            await _eventBus.PublishAsync(new AuthorityAddedEvent(address), ct);
            _logger.LogInformation("Added new authority {Address}.", address);
        }

        /// <summary>
        ///     Removes an existing authority validator. Triggers <see cref="AuthorityRemovedEvent"/>.
        /// </summary>
        public async Task RemoveAuthorityAsync(Address address, CancellationToken ct = default)
        {
            if (!await _authorityRegistry.ExistsAsync(address, ct))
                throw new InvalidOperationException($"Validator {address} does not exist in registry.");

            await _authorityRegistry.RemoveAsync(address, ct);
            await _eventBus.PublishAsync(new AuthorityRemovedEvent(address), ct);

            _logger.LogInformation("Removed authority {Address}.", address);
        }

        #endregion

        #region Slot Scheduling

        /// <summary>
        ///     Determines whether the supplied <paramref name="publicKey"/> belongs to the
        ///     validator whose turn it is to produce the next block.
        /// </summary>
        private async Task<bool> IsCurrentSlotOwnerAsync(
            PublicKey        publicKey,
            CancellationToken ct)
        {
            IReadOnlyList<Address> authorities =
                await _authorityRegistry.ListAsync(ct).ConfigureAwait(false);

            BlockHeader? latestHeader = await _blockRepository.GetLatestBlockHeaderAsync(ct);
            ulong        nextNumber   = latestHeader.Number + 1;

            int scheduledIndex = _scheduler.SelectValidatorIndex(authorities.Count, nextNumber);
            Address scheduled  = authorities.OrderBy(a => a).ElementAt(scheduledIndex);

            return scheduled == publicKey.Address;
        }

        /// <summary>
        ///     Validates that the validator who produced <paramref name="block"/> was scheduled for its slot.
        /// </summary>
        private async Task<bool> IsValidSlotOwnerAsync(Block block, CancellationToken ct)
        {
            IReadOnlyList<Address> authorities =
                await _authorityRegistry.ListAsync(ct).ConfigureAwait(false);

            int scheduledIndex =
                _scheduler.SelectValidatorIndex(authorities.Count, block.Header.Number);

            Address expected = authorities.OrderBy(a => a).ElementAt(scheduledIndex);

            return expected == block.Header.ValidatorAddress;
        }

        /// <summary>
        ///     Encapsulates consensus-specific metadata such as validator index and extra
        ///     flags that may be used by auxiliary tooling.
        /// </summary>
        private static byte[] BuildConsensusMetadata(BlockHeader previousHeader)
        {
            Span<byte> buffer = stackalloc byte[16];
            BitConverter.TryWriteBytes(buffer, previousHeader.Number);
            BitConverter.TryWriteBytes(buffer.Slice(sizeof(ulong)), previousHeader.Timestamp.ToBinary());

            return buffer.ToArray();
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;

            _proposeLock?.Dispose();
            _disposed = true;

            GC.SuppressFinalize(this);
        }

        #endregion
    }

    #region Helper abstractions (in-file stubs)

    // NOTE: The following interfaces/classes are expected to reside in other
    // project namespaces. They are included here as minimal stubs
    // so that this file is self-contained and demonstrates intent.

    public interface IConsensusStrategy
    {
        ConsensusAlgorithm Algorithm { get; }

        Task<Block?> ProposeBlockAsync(
            IReadOnlyCollection<Transaction> transactions,
            WalletKeyPair                    validatorKeyPair,
            CancellationToken                ct = default);

        Task<bool> ValidateBlockAsync(Block block, CancellationToken ct = default);
    }

    public interface IAuthorityRegistry
    {
        Task<bool> ExistsAsync(Address address, CancellationToken ct);

        Task AddAsync(Address address, PublicKey publicKey, CancellationToken ct);

        Task RemoveAsync(Address address, CancellationToken ct);

        Task<IReadOnlyList<Address>> ListAsync(CancellationToken ct);

        Task<PublicKey> GetPublicKeyAsync(Address address, CancellationToken ct);
    }

    public interface IDeterministicScheduler
    {
        /// <summary>
        ///     Deterministically maps the <paramref name="blockNumber"/> to the index of the
        ///     scheduled validator.
        /// </summary>
        int SelectValidatorIndex(int validatorsCount, ulong blockNumber);
    }

    // Event definitions
    public sealed record NewBlockCommittedEvent(Block Block);
    public sealed record AuthorityAddedEvent(Address Address);
    public sealed record AuthorityRemovedEvent(Address Address);

    // Domain primitives (minimal).
    public readonly record struct Address(string Value)
    {
        public override string ToString() => Value;
    }

    public sealed record PublicKey(Address Address, byte[] Bytes);
    public sealed record WalletKeyPair(PublicKey PublicKey, byte[] PrivateKey)
    {
        public Address Address => PublicKey.Address;
    }

    // Crypto stub.
    public interface ISignatureService
    {
        byte[] Sign(byte[] privateKey, byte[] messageHash);
        bool   Verify(PublicKey publicKey, byte[] messageHash, byte[] signature);
    }

    // Time abstraction.
    public interface IDateTimeProvider
    {
        DateTime UtcNow { get; }
    }

    // Merkle tree computation (placeholder).
    internal static class MerkleTree
    {
        public static byte[] ComputeRoot(IEnumerable<Transaction> txs)
        {
            using var sha = SHA256.Create();
            byte[] concatenated = txs
               .SelectMany(t => t.Hash)
               .ToArray();

            return sha.ComputeHash(concatenated);
        }
    }

    // Block/transaction stubs.
    public sealed record Transaction(byte[] Hash);

    public sealed record Block(BlockHeader Header, IReadOnlyCollection<Transaction> Transactions);

    public sealed record BlockHeader
    {
        public ulong                   Number           { get; init; }
        public byte[]                  PreviousHash     { get; init; } = Array.Empty<byte>();
        public DateTime                Timestamp        { get; init; }
        public byte[]                  MerkleRoot       { get; init; } = Array.Empty<byte>();
        public Address                 ValidatorAddress { get; init; }
        public byte[]                  Signature        { get; set; } = Array.Empty<byte>();
        public byte[]                  ConsensusMetadata { get; set; } = Array.Empty<byte>();

        public byte[] Hash => SHA256.HashData(
            BitConverter.GetBytes(Number)
                .Concat(PreviousHash)
                .Concat(BitConverter.GetBytes(Timestamp.ToBinary()))
                .Concat(MerkleRoot)
                .Concat(Signature)
                .ToArray());
    }

    public enum ConsensusAlgorithm
    {
        ProofOfAuthority,
        ProofOfStake,
        ProofOfWork
    }

    public interface IBlockRepository
    {
        Task<BlockHeader> GetLatestBlockHeaderAsync(CancellationToken ct);
        Task AddBlockAsync(Block block, CancellationToken ct);
        Task<BlockHeader?> FindHeaderByNumberAsync(ulong number, CancellationToken ct);
    }

    // Event bus abstraction.
    public interface IEventBus
    {
        Task PublishAsync<TEvent>(TEvent @event, CancellationToken ct = default);
    }

    #endregion
}
```