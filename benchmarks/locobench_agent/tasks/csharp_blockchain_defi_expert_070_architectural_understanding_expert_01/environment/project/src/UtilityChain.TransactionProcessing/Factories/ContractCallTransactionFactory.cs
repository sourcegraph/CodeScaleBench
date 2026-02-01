```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.TransactionProcessing/Factories/ContractCallTransactionFactory.cs
// Project: UtilityChain Core Suite (blockchain_defi)
// Language: C# 12 / .NET 8
//
// NOTE: Only types that are strictly required for compilation are defined in-file.
//       In the full solution these live in dedicated feature assemblies.
//       Remove the duplicate definitions when integrating into the main code-base.

#nullable enable
using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UtilityChain.Core.Cryptography;
using UtilityChain.Core.Domain;
using UtilityChain.Core.Exceptions;
using UtilityChain.Core.Extensions;
using UtilityChain.Core.Validation;
using UtilityChain.TransactionProcessing.Abstractions;
using UtilityChain.TransactionProcessing.Models;

namespace UtilityChain.TransactionProcessing.Factories;

/// <summary>
/// Factory responsible for constructing, validating and signing smart-contract call transactions.
/// </summary>
public sealed class ContractCallTransactionFactory : IContractCallTransactionFactory
{
    private readonly ISmartContractEncoder          _encoder;
    private readonly IGasEstimator                  _gasEstimator;
    private readonly ITransactionFeeCalculator      _feeCalculator;
    private readonly INonceService                  _nonceService;
    private readonly ISignatureService              _signatureService;
    private readonly INetworkConfiguration          _networkCfg;
    private readonly IDateTimeProvider              _clock;

    /// <summary>
    /// Initializes a new instance of the <see cref="ContractCallTransactionFactory"/> class.
    /// </summary>
    public ContractCallTransactionFactory(
        ISmartContractEncoder     encoder,
        IGasEstimator             gasEstimator,
        ITransactionFeeCalculator feeCalculator,
        INonceService             nonceService,
        ISignatureService         signatureService,
        INetworkConfiguration     networkCfg,
        IDateTimeProvider         clock)
    {
        _encoder          = encoder          ?? throw new ArgumentNullException(nameof(encoder));
        _gasEstimator     = gasEstimator     ?? throw new ArgumentNullException(nameof(gasEstimator));
        _feeCalculator    = feeCalculator    ?? throw new ArgumentNullException(nameof(feeCalculator));
        _nonceService     = nonceService     ?? throw new ArgumentNullException(nameof(nonceService));
        _signatureService = signatureService ?? throw new ArgumentNullException(nameof(signatureService));
        _networkCfg       = networkCfg       ?? throw new ArgumentNullException(nameof(networkCfg));
        _clock            = clock            ?? throw new ArgumentNullException(nameof(clock));
    }

    /// <inheritdoc />
    public async Task<ContractCallTransaction> BuildAsync(
        Address             sender,
        Address             contract,
        string              method,
        IReadOnlyList<object?>  parameters,
        TransactionOptions? options           = null,
        CancellationToken   ct                = default)
    {
        Guard.NotNull(sender);
        Guard.NotNull(contract);
        Guard.NotNullOrWhiteSpace(method);

        options ??= TransactionOptions.Default;

        // Resolve account nonce.
        ulong nonce = await _nonceService.GetNextNonceAsync(sender, ct)
                                         .ConfigureAwait(false);

        // Encode payload.
        byte[] payload = _encoder.EncodeContractCall(contract, method, parameters);

        // Estimate gas usage.
        GasEstimate gas = await _gasEstimator.GetGasEstimateAsync(
            sender,
            contract,
            payload,
            ct).ConfigureAwait(false);

        // Calculate fee based on network policy.
        Money fee = _feeCalculator.CalculateFee(gas, options.Priority);

        if (options.MaxFee != null && fee > options.MaxFee)
        {
            throw new TransactionFeeExceededException(
                $"Calculated fee {fee} exceeds the maximum user supplied fee {options.MaxFee}.");
        }

        // Build the transaction object.
        var tx = new ContractCallTransaction
        {
            Sender        = sender,
            Contract      = contract,
            Nonce         = nonce,
            GasLimit      = gas.Limit,
            GasPrice      = gas.Price,
            Fee           = fee,
            Payload       = payload,
            NetworkId     = _networkCfg.NetworkId,
            Timestamp     = _clock.UtcNow,
            ExpirationUtc = options.AbsoluteExpiration ?? _clock.UtcNow.Add(options.RelativeTtl)
        };

        // Sign the transaction.
        byte[] signature = _signatureService.Sign(sender, tx.BuildSigningMessage());

        tx.SetSignature(signature);

        // Final validation (defensive).
        TransactionValidationResult validation = tx.Validate();
        if (!validation.Success)
        {
            throw new TransactionValidationException($"Contract-call transaction invalid: {validation.Reason}");
        }

        return tx;
    }
}

#region –––––––––––––––––––––– Contracts (interfaces) ––––––––––––––––––––––

// All of these interfaces exist elsewhere in the real solution and are kept
// here for the sake of compiler completeness.  Only signatures relevant to
// the factory have been included.

public interface IContractCallTransactionFactory
{
    Task<ContractCallTransaction> BuildAsync(
        Address             sender,
        Address             contract,
        string              method,
        IReadOnlyList<object?>  parameters,
        TransactionOptions? options           = null,
        CancellationToken   ct                = default);
}

public interface ISmartContractEncoder
{
    byte[] EncodeContractCall(Address contract, string method, IReadOnlyList<object?> parameters);
}

public interface IGasEstimator
{
    Task<GasEstimate> GetGasEstimateAsync(Address sender, Address contract, byte[] payload, CancellationToken ct);
}

public interface ITransactionFeeCalculator
{
    Money CalculateFee(GasEstimate gas, FeePriority priority);
}

public interface INonceService
{
    Task<ulong> GetNextNonceAsync(Address address, CancellationToken ct);
}

public interface ISignatureService
{
    byte[] Sign(Address address, ReadOnlySpan<byte> message);
}

public interface INetworkConfiguration
{
    uint NetworkId { get; }
}

public interface IDateTimeProvider
{
    DateTime UtcNow { get; }
}

#endregion

#region –––––––––––––––––––––– Domain Models ––––––––––––––––––––––

public sealed record Address(string Value)
{
    public override string ToString() => Value;
}

public readonly record struct Money(long Satoshis)
{
    public static bool operator >(Money left, Money right) => left.Satoshis > right.Satoshis;
    public static bool operator <(Money left, Money right) => left.Satoshis < right.Satoshis;
    public override string ToString() => $"{Satoshis} uUC"; // micro UtilityCoin
}

/// <summary>
/// Priority level chosen by sender to influence fee calculation.
/// </summary>
public enum FeePriority { Low, Normal, High }

public sealed class GasEstimate
{
    public required ulong Limit { get; init; }
    public required Money Price { get; init; }
}

/// <summary>
/// Common transaction options the user can submit alongside the transaction payload.
/// </summary>
public sealed class TransactionOptions
{
    public static TransactionOptions Default { get; } = new();

    /// <summary>Absolute expiration date/time (UTC) for the tx.</summary>
    public DateTime? AbsoluteExpiration { get; init; }

    /// <summary>Relative time-to-live if <see cref="AbsoluteExpiration"/> is not set.</summary>
    public TimeSpan  RelativeTtl       { get; init; } = TimeSpan.FromMinutes(30);

    /// <summary>Priority requested by sender for fee calculation.</summary>
    public FeePriority Priority        { get; init; } = FeePriority.Normal;

    /// <summary>
    /// Maximum fee the user is willing to pay; if <c>null</c> there is no limit.
    /// </summary>
    public Money?     MaxFee           { get; init; }
}

/// <summary>
/// Base class for all blockchain transactions.
/// IMPORTANT: In the real implementation this resides in Core.Domain.
/// </summary>
public abstract class Transaction
{
    public required Address Sender     { get; init; }
    public required ulong   Nonce      { get; init; }
    public required DateTime Timestamp { get; init; }

    private byte[]? _signature;
    public byte[]   Signature => _signature ?? Array.Empty<byte>();

    public void SetSignature(byte[] signature) =>
        _signature = signature ?? throw new ArgumentNullException(nameof(signature));

    public abstract ReadOnlyMemory<byte> BuildSigningMessage();

    public abstract TransactionValidationResult Validate();
}

/// <summary>
/// Smart-contract invocation transaction.
/// </summary>
public sealed class ContractCallTransaction : Transaction
{
    public required Address Contract      { get; init; }
    public required byte[]  Payload       { get; init; }
    public required uint    NetworkId     { get; init; }
    public required ulong   GasLimit      { get; init; }
    public required Money   GasPrice      { get; init; }
    public required Money   Fee           { get; init; }
    public required DateTime ExpirationUtc { get; init; }

    public override ReadOnlyMemory<byte> BuildSigningMessage()
    {
        var buffer = new List<byte>(256);

        void Append(Span<byte> bytes) => buffer.AddRange(bytes.ToArray());

        Append(Encoding.UTF8.GetBytes(Sender.Value));
        Append(BitConverter.GetBytes(Nonce));
        Append(Encoding.UTF8.GetBytes(Contract.Value));
        Append(BitConverter.GetBytes(NetworkId));
        Append(BitConverter.GetBytes(GasLimit));
        Append(BitConverter.GetBytes(GasPrice.Satoshis));
        Append(Payload);
        Append(BitConverter.GetBytes(Timestamp.ToBinary()));

        return buffer.ToArray();
    }

    public override TransactionValidationResult Validate()
    {
        if (ExpirationUtc <= Timestamp)
            return TransactionValidationResult.Fail("Expiration must be in the future.");

        if (GasLimit == 0)
            return TransactionValidationResult.Fail("Gas limit cannot be 0.");

        if (Fee.Satoshis == 0)
            return TransactionValidationResult.Fail("Fee cannot be 0.");

        if (Signature.Length == 0)
            return TransactionValidationResult.Fail("Missing signature.");

        return TransactionValidationResult.Successful;
    }
}

public readonly struct TransactionValidationResult
{
    public bool   Success { get; }
    public string? Reason { get; }

    private TransactionValidationResult(bool success, string? reason)
    {
        Success = success;
        Reason  = reason;
    }

    public static TransactionValidationResult Successful { get; } = new(true, null);

    public static TransactionValidationResult Fail(string reason) =>
        new(false, reason ?? "Unknown validation error.");
}

#endregion

#region –––––––––––––––––––––– Cross-cutting Helpers ––––––––––––––––

internal static class Guard
{
    public static void NotNull<T>(T? argument, string? paramName = null) where T : class
    {
        if (argument is null)
            throw new ArgumentNullException(paramName ?? nameof(argument));
    }

    public static void NotNullOrWhiteSpace(string? argument, string? paramName = null)
    {
        if (string.IsNullOrWhiteSpace(argument))
            throw new ArgumentException("Value cannot be null or whitespace.", paramName ?? nameof(argument));
    }
}

#endregion
```