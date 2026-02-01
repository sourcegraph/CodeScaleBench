```csharp
// ---------------------------------------------------------------------------------------------------------------------
//  UtilityChain Core Suite
//  File: UtilityChainCoreSuite/src/UtilityChain.TransactionProcessing/Factories/StakingTransactionFactory.cs
//  Author: UtilityChain Contributors
//  License: MIT
// ---------------------------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using UtilityChain.TransactionProcessing.Abstractions;
using UtilityChain.TransactionProcessing.Domain;
using UtilityChain.TransactionProcessing.Exceptions;

namespace UtilityChain.TransactionProcessing.Factories
{
    /// <summary>
    /// Factory responsible for creating and signing <see cref="StakingTransaction"/> instances.  This class encapsulates
    /// all domain-level validation, fee calculation, input selection, and cryptographic signing required to build a
    /// fully-formed transaction that can be submitted to the mem-pool.
    /// </summary>
    /// <remarks>
    /// The class purposefully hides the complexity of building a transaction object so that higher-level
    /// orchestration layers (CLI, RPC, wallet UIs) can focus on user-experience concerns.  Domain-specific exceptions
    /// are thrown for any invalid state to make troubleshooting easier for API consumers.
    /// </remarks>
    public sealed class StakingTransactionFactory : IStakingTransactionFactory
    {
        private const string StakeContractAddress = "SMARTCONTRACT::STAKE_MODULE::LOCKBOX";

        private readonly IStakeEligibilityService _eligibilityService;
        private readonly IProtocolFeeCalculator    _feeCalculator;
        private readonly ISigningService           _signingService;
        private readonly ITimeProvider             _timeProvider;
        private readonly ILogger<StakingTransactionFactory> _logger;

        public StakingTransactionFactory(
            IStakeEligibilityService                 eligibilityService,
            IProtocolFeeCalculator                   feeCalculator,
            ISigningService                          signingService,
            ITimeProvider                            timeProvider,
            ILogger<StakingTransactionFactory>       logger)
        {
            _eligibilityService = eligibilityService   ?? throw new ArgumentNullException(nameof(eligibilityService));
            _feeCalculator      = feeCalculator        ?? throw new ArgumentNullException(nameof(feeCalculator));
            _signingService     = signingService       ?? throw new ArgumentNullException(nameof(signingService));
            _timeProvider       = timeProvider         ?? throw new ArgumentNullException(nameof(timeProvider));
            _logger             = logger               ?? throw new ArgumentNullException(nameof(logger));
        }

        /// <inheritdoc/>
        public async Task<StakingTransaction> CreateAsync(
            StakingRequest      request,
            CancellationToken   cancellationToken = default)
        {
            if (request is null) throw new ArgumentNullException(nameof(request));
            if (request.Amount <= 0) throw new TransactionValidationException("Stake amount must be a positive value.");
            if (request.LockPeriod <= 0) throw new TransactionValidationException("Lock period must be greater than zero.");

            _logger.LogDebug("Creating staking transaction for wallet {Wallet}. Amount={Amount}, LockPeriod={LockPeriod}",
                request.WalletAddress,
                request.Amount,
                request.LockPeriod);

            // Grab spendable inputs from the eligibility service
            IReadOnlyList<TransactionInput> spendableInputs = await _eligibilityService
                .GetEligibleInputsAsync(request.WalletAddress, request.Amount, cancellationToken)
                .ConfigureAwait(false);

            decimal inputTotal = spendableInputs.Sum(i => i.Amount);

            if (inputTotal < request.Amount)
            {
                throw new InsufficientBalanceException(
                    request.WalletAddress,
                    request.Amount,
                    inputTotal);
            }

            // Calculate protocol fee
            decimal fee = _feeCalculator.CalculateFee(TransactionType.Stake, request.Amount);

            if (inputTotal < request.Amount + fee)
            {
                throw new InsufficientBalanceException(
                    request.WalletAddress,
                    request.Amount + fee,
                    inputTotal);
            }

            // Build the output set
            var outputs = new List<TransactionOutput>(capacity: 2)
            {
                // Destination output: funds locked in the staking contract
                new TransactionOutput(
                    Address : StakeContractAddress,
                    Amount  : request.Amount),

                // Change output if the user had more UTXO value than needed
            };

            decimal change = inputTotal - request.Amount - fee;

            if (change > 0)
            {
                outputs.Add(new TransactionOutput(
                    Address : request.WalletAddress,
                    Amount  : change));
            }

            // Create unsigned transaction
            var unsignedTx = new StakingTransaction(
                id          : TransactionId.Empty, // Placeholder, will be calculated after signing
                inputs      : spendableInputs,
                outputs     : outputs.ToImmutableList(),
                timestamp   : _timeProvider.Now,
                stakeAmount : request.Amount,
                lockPeriod  : request.LockPeriod);

            // Serialize unsigned tx to generate signing payload
            byte[] payload = unsignedTx.SerializeUnsigned();

            // Perform crypto signing for each input
            var signedInputs = new List<TransactionInput>(spendableInputs.Count);

            foreach (TransactionInput input in spendableInputs)
            {
                Signature signature = await _signingService
                    .SignAsync(payload, request.PrivateKey, cancellationToken)
                    .ConfigureAwait(false);

                signedInputs.Add(input with { Signature = signature });
            }

            // Construct final, fully-signed transaction
            var signedTx = unsignedTx with
            {
                Inputs = signedInputs.ToImmutableList(),
                Id     = TransactionId.ComputeFromHash(ComputeHash(signedInputs, outputs, unsignedTx.Timestamp))
            };

            _logger.LogInformation("Staking transaction {TxId} created for wallet {Wallet}.",
                signedTx.Id,
                request.WalletAddress);

            return signedTx;
        }

        // -----------------------------------------------------------------------------------------------------------------
        //  Helpers
        // -----------------------------------------------------------------------------------------------------------------

        private static byte[] ComputeHash(
            IEnumerable<TransactionInput>  inputs,
            IEnumerable<TransactionOutput> outputs,
            DateTimeOffset                 timestamp)
        {
            using SHA256 sha256 = SHA256.Create();

            void WriteInt(int value, Span<byte> buffer, ref int offset)
            {
                BitConverter.TryWriteBytes(buffer.Slice(offset, sizeof(int)), value);
                offset += sizeof(int);
            }

            void WriteDecimal(decimal value, Span<byte> buffer, ref int offset)
            {
                foreach (int i in decimal.GetBits(value))
                {
                    WriteInt(i, buffer, ref offset);
                }
            }

            // Precompute required buffer length
            int bufferLen = sizeof(long) +                               // timestamp
                            inputs.Count()  * (32 + sizeof(int) + 64) +   // simplistic input estimate
                            outputs.Count() * (42 + sizeof(decimal));     // simplistic output estimate

            Span<byte> tmp = stackalloc byte[bufferLen];
            int curr = 0;

            // Timestamp
            BitConverter.TryWriteBytes(tmp.Slice(curr, sizeof(long)), timestamp.ToUnixTimeSeconds());
            curr += sizeof(long);

            // Inputs
            foreach (TransactionInput input in inputs)
            {
                input.TxId.Value.CopyTo(tmp.Slice(curr, 32));
                curr += 32;

                WriteInt(input.OutputIndex, tmp, ref curr);
                input.Signature!.Value.CopyTo(tmp.Slice(curr, 64));
                curr += 64;
            }

            // Outputs
            foreach (TransactionOutput output in outputs)
            {
                // Address (utf-8, maxlength 42 for user addresses or SC addresses)
                ReadOnlySpan<byte> addrBytes = System.Text.Encoding.UTF8.GetBytes(output.Address);
                addrBytes.CopyTo(tmp.Slice(curr, addrBytes.Length));
                curr += 42;

                WriteDecimal(output.Amount, tmp, ref curr);
            }

            return sha256.ComputeHash(tmp.Slice(0, curr).ToArray());
        }
    }

    // -----------------------------------------------------------------------------------------------------------------
    //  Interfaces
    // -----------------------------------------------------------------------------------------------------------------

    /// <summary>
    /// Public abstraction for building staking transactions.
    /// </summary>
    public interface IStakingTransactionFactory
    {
        /// <summary>
        /// Builds a fully-signed staking transaction from the supplied high-level request.
        /// </summary>
        /// <exception cref="InsufficientBalanceException">
        /// Thrown when the wallet does not hold sufficient spendable funds.
        /// </exception>
        /// <exception cref="TransactionValidationException">
        /// Thrown when user-supplied request data is invalid.
        /// </exception>
        Task<StakingTransaction> CreateAsync(
            StakingRequest    request,
            CancellationToken cancellationToken = default);
    }

    // -----------------------------------------------------------------------------------------------------------------
    //  Records / Models
    // -----------------------------------------------------------------------------------------------------------------

    /// <summary>
    /// Immutable record capturing user-facing parameters required to stake funds.
    /// </summary>
    /// <param name="WalletAddress">Wallet address of the sender.</param>
    /// <param name="Amount">Amount to lock in the staking contract.</param>
    /// <param name="LockPeriod">Number of blocks (or epochs) the funds will remain locked.</param>
    /// <param name="PrivateKey">Caller’s private key used for signing.</param>
    public sealed record StakingRequest(
        string      WalletAddress,
        decimal     Amount,
        int         LockPeriod,
        PrivateKey  PrivateKey);
}

// =====================================================================================================================
//  Supplemental domain and exception types.  In the real codebase, these reside in their respective namespaces/files.
// =====================================================================================================================

namespace UtilityChain.TransactionProcessing.Domain
{
    using System.Collections.Immutable;

    public enum TransactionType { Transfer, Stake, Unstake, Reward }

    public readonly record struct TransactionId(Guid Value)
    {
        public static readonly TransactionId Empty = new(Guid.Empty);

        public static TransactionId ComputeFromHash(byte[] hash) => new(new Guid(hash[..16]));
        public override string ToString() => Value.ToString("N");
    }

    public record TransactionInput(
        TransactionId TxId,
        int           OutputIndex,
        decimal       Amount,
        Signature?    Signature = null);

    public record TransactionOutput(
        string  Address,
        decimal Amount);

    public abstract record Transaction(
        TransactionId                id,
        ImmutableList<TransactionInput>  inputs,
        ImmutableList<TransactionOutput> outputs,
        DateTimeOffset               timestamp,
        TransactionType              type)
    {
        public TransactionId Id          { get; init; } = id;
        public DateTimeOffset Timestamp  { get; init; } = timestamp;
        public TransactionType Type      { get; init; } = type;
        public ImmutableList<TransactionInput> Inputs  { get; init; } = inputs;
        public ImmutableList<TransactionOutput> Outputs { get; init; } = outputs;

        public abstract byte[] SerializeUnsigned();
    }

    public sealed record StakingTransaction(
        TransactionId                id,
        ImmutableList<TransactionInput>  inputs,
        ImmutableList<TransactionOutput> outputs,
        DateTimeOffset               timestamp,
        decimal                      stakeAmount,
        int                          lockPeriod)
        : Transaction(id, inputs, outputs, timestamp, TransactionType.Stake)
    {
        public decimal StakeAmount { get; init; } = stakeAmount;
        public int     LockPeriod  { get; init; } = lockPeriod;

        public override byte[] SerializeUnsigned()
        {
            // Production code would use Protobuf/FlatBuffers/SSZ/etc.
            return System.Text.Encoding.UTF8.GetBytes($"{Timestamp:o}|{StakeAmount}|{LockPeriod}");
        }
    }

    public readonly record struct PublicKey(byte[] Value);
    public readonly record struct PrivateKey(byte[] Value);
    public readonly record struct Signature (byte[] Value);
}

namespace UtilityChain.TransactionProcessing.Abstractions
{
    using System.Threading;
    using System.Threading.Tasks;
    using UtilityChain.TransactionProcessing.Domain;

    public interface ISigningService
    {
        Task<Signature> SignAsync(
            byte[]      payload,
            PrivateKey  privateKey,
            CancellationToken cancellationToken = default);
    }

    public interface IProtocolFeeCalculator
    {
        decimal CalculateFee(TransactionType type, decimal amount);
    }

    public interface ITimeProvider
    {
        DateTimeOffset Now { get; }
    }

    public interface IStakeEligibilityService
    {
        /// <summary>
        /// Returns spendable inputs for the given wallet.  The total value must be equal or greater than
        /// <paramref name="requiredAmount"/>.  An empty collection indicates no eligible inputs.
        /// </summary>
        Task<IReadOnlyList<TransactionInput>> GetEligibleInputsAsync(
            string          walletAddress,
            decimal         requiredAmount,
            CancellationToken cancellationToken = default);
    }
}

namespace UtilityChain.TransactionProcessing.Exceptions
{
    using System;
    using UtilityChain.TransactionProcessing.Domain;

    [Serializable]
    public sealed class TransactionValidationException : Exception
    {
        public TransactionValidationException(string message) : base(message) { }
    }

    [Serializable]
    public sealed class InsufficientBalanceException : Exception
    {
        public InsufficientBalanceException(
            string  wallet,
            decimal required,
            decimal actual)
            : base($"Wallet '{wallet}' has insufficient balance. Required={required}, Actual={actual}") { }
    }
}
```