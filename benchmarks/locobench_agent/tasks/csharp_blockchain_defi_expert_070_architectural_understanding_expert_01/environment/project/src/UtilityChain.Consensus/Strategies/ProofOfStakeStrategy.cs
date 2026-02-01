```csharp
// -----------------------------------------------------------------------------
//  UtilityChain Core Suite
//  File:    ProofOfStakeStrategy.cs
//  Project: UtilityChain.Consensus
//  Author:  UtilityChain Engineering Team
//  License: Proprietary – All Rights Reserved
// -----------------------------------------------------------------------------

using System;
using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Numerics;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using UtilityChain.Blockchain.Abstractions;
using UtilityChain.Common;
using UtilityChain.Common.Diagnostics;
using UtilityChain.Consensus.Abstractions;
using UtilityChain.Crypto;
using UtilityChain.Events.Abstractions;
using UtilityChain.Mempool.Abstractions;
using UtilityChain.Staking.Abstractions;

namespace UtilityChain.Consensus.Strategies
{
    /// <summary>
    ///     Proof-of-Stake (PoS) consensus implementation based on chain-weight
    ///     with a verifiable random selection (VRF-style) of proposers.
    ///
    ///     The strategy is designed to be plug-and-play within the UtilityChain
    ///     monolith and therefore does *not* perform any network-level gossiping.
    ///     Instead, it emits events onto the internal <see cref="IEventBus"/> so
    ///     that the P2P layer can react accordingly.
    /// </summary>
    public sealed class ProofOfStakeStrategy : IConsensusStrategy, IObserver<StakeChanged>, IDisposable
    {
        private const int EpochDurationSeconds = 10; // 1 block every 10 seconds (example)
        private static readonly BigInteger MaxHashValue = BigInteger.Pow(2, 256) - 1;

        private readonly IBlockFactory _blockFactory;
        private readonly IBlockRepository _blockRepository;
        private readonly ICryptoProvider _cryptoProvider;
        private readonly IEventBus _eventBus;
        private readonly IKeyStore _keyStore;
        private readonly ILogger<ProofOfStakeStrategy> _logger;
        private readonly IMempool _mempool;
        private readonly IStakeRepository _stakeRepository;

        private readonly ConcurrentDictionary<Address, ulong> _cachedStake = new();
        private readonly IDisposable? _stakeSubscription;
        private readonly ReaderWriterLockSlim _stateLock = new();
        private bool _disposed;

        /// <summary>Initializes a new instance of <see cref="ProofOfStakeStrategy"/>.</summary>
        public ProofOfStakeStrategy(
            IStakeRepository stakeRepository,
            IBlockRepository blockRepository,
            IMempool mempool,
            IBlockFactory blockFactory,
            ICryptoProvider cryptoProvider,
            IKeyStore keyStore,
            IEventBus eventBus,
            ILogger<ProofOfStakeStrategy> logger)
        {
            _stakeRepository = stakeRepository ?? throw new ArgumentNullException(nameof(stakeRepository));
            _blockRepository = blockRepository ?? throw new ArgumentNullException(nameof(blockRepository));
            _mempool = mempool ?? throw new ArgumentNullException(nameof(mempool));
            _blockFactory = blockFactory ?? throw new ArgumentNullException(nameof(blockFactory));
            _cryptoProvider = cryptoProvider ?? throw new ArgumentNullException(nameof(cryptoProvider));
            _keyStore = keyStore ?? throw new ArgumentNullException(nameof(keyStore));
            _eventBus = eventBus ?? throw new ArgumentNullException(nameof(eventBus));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));

            // Pre-warm stake cache
            foreach (var balance in _stakeRepository.GetAllStakes())
            {
                _cachedStake.TryAdd(balance.Address, balance.Amount);
            }

            // Subscribe for subsequent stake changes
            _stakeSubscription = _stakeRepository.Subscribe(this);

            _logger.LogInformation("ProofOfStakeStrategy initialized with {ValidatorCount} validators", _cachedStake.Count);
        }

        #region Public API

        /// <inheritdoc/>
        public async ValueTask<ValidationResult> ValidateBlockAsync(Block block, CancellationToken ct = default)
        {
            ArgumentNullException.ThrowIfNull(block);

            using var _ = new LogTiming(_logger, "ValidateBlock[{Height}]", block.Header.Height);

            // 1. Validate basic block structure via factory helper.
            var basic = _blockFactory.ValidateStructure(block);
            if (!basic.IsSuccess)
                return basic;

            // 2. Verify proposer signature.
            if (!_cryptoProvider.Verify(
                    block.Header.HashWithoutSignature,
                    block.Header.ProposerSignature,
                    block.Header.Proposer))
            {
                return ValidationResult.Invalid("Invalid block signature");
            }

            // 3. Check timestamp and monotonicity
            var prev = await _blockRepository.GetBlockAsync(block.Header.PreviousHash, ct).ConfigureAwait(false);
            if (prev is null)
                return ValidationResult.Invalid("Unknown previous block");

            var prevTime = prev.Header.Timestamp;
            if (block.Header.Timestamp <= prevTime ||
                block.Header.Timestamp > DateTimeOffset.UtcNow.AddMinutes(1)) // 1-minute future tolerance
            {
                return ValidationResult.Invalid("Invalid timestamp");
            }

            // 4. Verify proposer eligibility
            if (!IsValidatorEligible(block.Header))
                return ValidationResult.Invalid("Proposer is not eligible for this epoch");

            // 5. Validate each transaction (batched for performance)
            foreach (var tx in block.Transactions)
            {
                ct.ThrowIfCancellationRequested();

                var res = _blockFactory.ValidateTransaction(tx, prevTime);
                if (!res.IsSuccess)
                    return res;
            }

            return ValidationResult.Ok;
        }

        /// <inheritdoc/>
        public async Task<Block?> TryProposeBlockAsync(CancellationToken ct = default)
        {
            // Ensure we are holding validator keys
            if (!_keyStore.TryGetActiveKey(out var validatorKey))
            {
                _logger.LogDebug("Node does not hold any active validator key ‑ aborting proposal attempt");
                return null;
            }

            // Get chain tip
            var tip = await _blockRepository.GetChainTipAsync(ct).ConfigureAwait(false);
            if (tip is null)
            {
                _logger.LogWarning("Cannot propose block without a chain tip");
                return null;
            }

            var epoch = CalculateEpoch(tip.Header.Timestamp.ToUnixTimeSeconds());
            var seed = tip.Header.Hash; // Use parent hash as epoch seed

            // Determine eligibility
            if (!TryIsEligible(validatorKey.PublicKey, epoch, seed, out var hit))
            {
                _logger.LogTrace("Validator not eligible in epoch {Epoch} (hit={Hit})", epoch, hit);
                return null;
            }

            // Gather txs from mempool under size limit
            var txs = _mempool.GetTransactionsForBlock(maxCount: 1000, maxBlockSizeBytes: 1_000_000).ToList();

            // Construct & sign block
            var newBlock = _blockFactory.CreateBlock(
                previousHash: tip.Header.Hash,
                height: tip.Header.Height + 1,
                timestamp: DateTimeOffset.UtcNow,
                proposer: validatorKey.PublicKey,
                transactions: txs);

            newBlock.Header.ProposerSignature = _cryptoProvider.Sign(
                newBlock.Header.HashWithoutSignature,
                validatorKey.PrivateKey);

            _logger.LogInformation("Proposed block #{Height} ({TxCount} txs) [hash={Hash}]", newBlock.Header.Height, txs.Count, newBlock.Header.Hash);

            // Emit event for P2P propagation
            _eventBus.Publish(new BlockProposed(newBlock));

            return newBlock;
        }

        #endregion

        #region Eligibility

        /// <summary>
        ///     Checks whether a block proposer was eligible to create the block
        ///     contained in the header.
        /// </summary>
        private bool IsValidatorEligible(BlockHeader header)
        {
            var epoch = CalculateEpoch(header.Timestamp.ToUnixTimeSeconds());
            return TryIsEligible(header.Proposer, epoch, header.PreviousHash, out _);
        }

        /// <summary>
        ///     Attempts to determine if the validator with <paramref name="validatorAddress"/>
        ///     is eligible for the given <paramref name="epoch"/> and returns the computed
        ///     VRF hit value used for auditability.
        /// </summary>
        private bool TryIsEligible(
            Address validatorAddress,
            long epoch,
            Hash256 seed,
            [NotNullWhen(true)] out BigInteger? hitValue)
        {
            hitValue = null;

            if (!_cachedStake.TryGetValue(validatorAddress, out var stake) || stake == 0)
                return false;

            var totalStake = _cachedStake.Values.Aggregate<ulong, BigInteger>(0, (acc, s) => acc + s);
            if (totalStake == 0)
                return false;

            // Calculate hit = Hash(validatorPubKey || epoch || seed)
            Span<byte> input = stackalloc byte[seed.Length + Address.Length + sizeof(long)];
            seed.AsSpan().CopyTo(input);
            validatorAddress.AsSpan().CopyTo(input.Slice(seed.Length));
            BinaryPrimitives.WriteInt64LittleEndian(input.Slice(seed.Length + Address.Length), epoch);

            var hashBytes = SHA256.HashData(input);
            var hashInt = new BigInteger(hashBytes, isUnsigned: true, isBigEndian: true);
            hitValue = hashInt;

            // Threshold = MaxHash * (stake / totalStake)
            var threshold = MaxHashValue * stake / totalStake;

            return hashInt < threshold;
        }

        #endregion

        #region Observer Pattern Implementation (StakeChanged)

        public void OnCompleted()
        {
            /* no-op – repository completes only on shutdown */
        }

        public void OnError(Exception error)
        {
            _logger.LogError(error, "Stake subscription error");
        }

        public void OnNext(StakeChanged value)
        {
            // Update cache
            _cachedStake.AddOrUpdate(value.Address, value.NewAmount, (_, __) => value.NewAmount);
            _logger.LogDebug("Stake updated: {Address} => {Amount}", value.Address, value.NewAmount);
        }

        #endregion

        #region Helpers

        private static long CalculateEpoch(long unixSeconds)
            => unixSeconds / EpochDurationSeconds;

        #endregion

        #region IDisposable Support

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            _stakeSubscription?.Dispose();
            _stateLock.Dispose();

            _logger.LogDebug("ProofOfStakeStrategy disposed");
        }

        #endregion
    }
}
```