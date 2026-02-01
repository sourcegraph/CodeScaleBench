using System;
using System.Buffers;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace UtilityChain.TransactionProcessing;

/// <summary>
/// Represents all supported transaction categories on UtilityChain.
/// Extend with caution— altering enumeration order breaks binary compatibility in persisted ledgers.
/// </summary>
public enum TransactionType : byte
{
    Transfer = 0,
    Stake = 1,
    Unstake = 2,
    GovernanceVote = 3,
    ContractCall = 4
}

/// <summary>
/// Immutable representation of a signed, client-submitted transaction.
/// </summary>
/// <param name="Id">Deterministic identifier chosen by the signer.</param>
/// <param name="Type">High-level action requested.</param>
/// <param name="Nonce">Unsigned integer that must monotonically increase per signer.</param>
/// <param name="Payload">Arbitrary, domain-specific bytes (contract calldata, governance proposal, etc.).</param>
/// <param name="SignerPublicKey">Compressed public key in ANSI X9.62 format.</param>
/// <param name="Signature">DER-encoded ECDSA signature.</param>
/// <param name="Timestamp">Unix epoch seconds when the client produced the transaction.</param>
public sealed record Transaction(
    Guid Id,
    TransactionType Type,
    ulong Nonce,
    byte[] Payload,
    byte[] SignerPublicKey,
    byte[] Signature,
    long Timestamp);

/// <summary>
/// Provides immutable, read-only state describing the chain at the point of validation.
/// </summary>
public interface IChainState
{
    /// <summary>Checks if the nonce has already been used by <paramref name="publicKey"/>.</summary>
    ValueTask<bool> IsNonceUniqueAsync(ReadOnlyMemory<byte> publicKey, ulong nonce, CancellationToken ct);

    /// <summary>Returns time as perceived by consensus (seconds since Unix epoch).</summary>
    long GetCurrentUnixTimeSeconds();
}

/// <summary>
/// A single validation step executed against a <see cref="Transaction"/>.
/// </summary>
public interface IValidationRule
{
    string Name { get; }

    /// <summary>
    /// Performs validation. The rule must be idempotent and side-effect free.
    /// </summary>
    ValueTask<ValidationResult> ValidateAsync(TransactionContext context, CancellationToken ct);
}

/// <summary>
/// Container holding all objects required to validate a transaction.
/// Additional services can be resolved via <see cref="ServiceProvider" />.
/// </summary>
public sealed class TransactionContext
{
    public TransactionContext(
        Transaction transaction,
        IChainState chainState,
        IServiceProvider serviceProvider,
        ILoggerFactory loggerFactory)
    {
        Transaction = transaction;
        ChainState = chainState;
        ServiceProvider = serviceProvider;
        LoggerFactory = loggerFactory;
    }

    public Transaction Transaction { get; }

    public IChainState ChainState { get; }

    public IServiceProvider ServiceProvider { get; }

    public ILoggerFactory LoggerFactory { get; }
}

/// <summary>
/// Outcome of a validation process.
/// </summary>
public readonly struct ValidationResult
{
    private ValidationResult(bool isValid, string? errorMessage)
    {
        IsValid = isValid;
        ErrorMessage = errorMessage;
    }

    public bool IsValid { get; }
    public string? ErrorMessage { get; }

    public static ValidationResult Success { get; } = new(true, null);

    public static ValidationResult Fail(string error)
        => new(false, error);

    public override string ToString() => IsValid ? "Success" : $"Failure: {ErrorMessage}";
}

/// <summary>
/// Public entry-point responsible for orchestrating the rule pipeline.
/// </summary>
public sealed class TransactionValidator : ITransactionValidator
{
    private readonly ImmutableArray<IValidationRule> _rules;
    private readonly ILogger<TransactionValidator> _logger;

    public TransactionValidator(IEnumerable<IValidationRule> rules, ILogger<TransactionValidator> logger)
    {
        if (rules is null) throw new ArgumentNullException(nameof(rules));
        _rules = rules.ToImmutableArray();
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <inheritdoc />
    public async ValueTask<ValidationResult> ValidateAsync(
        Transaction transaction,
        IChainState chainState,
        IServiceProvider serviceProvider,
        CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(transaction);
        ArgumentNullException.ThrowIfNull(chainState);
        ArgumentNullException.ThrowIfNull(serviceProvider);

        var context = new TransactionContext(
            transaction,
            chainState,
            serviceProvider,
            serviceProvider.GetRequiredService<ILoggerFactory>());

        for (var i = 0; i < _rules.Length; i++)
        {
            var rule = _rules[i];
            var result = await rule.ValidateAsync(context, ct).ConfigureAwait(false);

            if (!result.IsValid)
            {
                _logger.LogWarning(
                    "Validation failed at rule '{Rule}' for Tx {TxId}: {Reason}",
                    rule.Name,
                    transaction.Id,
                    result.ErrorMessage);

                return result;
            }
        }

        _logger.LogDebug("Tx {TxId} passed all {RuleCount} validation rules.", transaction.Id, _rules.Length);
        return ValidationResult.Success;
    }
}

/// <summary>
/// Contract for DI so other modules can consume the validator.
/// </summary>
public interface ITransactionValidator
{
    ValueTask<ValidationResult> ValidateAsync(
        Transaction transaction,
        IChainState chainState,
        IServiceProvider serviceProvider,
        CancellationToken ct = default);
}

#region Built-in Validation Rules

/// <summary>
/// Ensure the transaction object adheres to structural expectations.
/// </summary>
internal sealed class TransactionStructureRule : IValidationRule
{
    public string Name => nameof(TransactionStructureRule);

    public ValueTask<ValidationResult> ValidateAsync(TransactionContext context, CancellationToken ct)
    {
        var tx = context.Transaction;

        if (tx.Id == Guid.Empty)
            return Fail("Id cannot be empty.");

        if (tx.Payload is null or { Length: 0 })
            return Fail("Payload missing.");

        if (tx.SignerPublicKey is null or { Length: 0 })
            return Fail("Signer public key missing.");

        if (tx.Signature is null or { Length: 0 })
            return Fail("Signature missing.");

        if (tx.Timestamp <= 0)
            return Fail("Invalid timestamp.");

        return Success();

        static ValueTask<ValidationResult> Success() => ValueTask.FromResult(ValidationResult.Success);
        static ValueTask<ValidationResult> Fail(string msg) =>
            ValueTask.FromResult(ValidationResult.Fail(msg));
    }
}

/// <summary>
/// Validates the authenticity of the digital signature.
/// </summary>
internal sealed class SignatureValidationRule : IValidationRule
{
    public string Name => nameof(SignatureValidationRule);

    public async ValueTask<ValidationResult> ValidateAsync(TransactionContext context, CancellationToken ct)
    {
        var tx = context.Transaction;
        try
        {
            if (tx.SignerPublicKey.Length is < 33 or > 140)
                return ValidationResult.Fail("Unsupported public key size.");

            // Import public key (assumes compressed form for P-256)
            using var ecdsa = ECDsa.Create();
            ecdsa.ImportSubjectPublicKeyInfo(tx.SignerPublicKey, out _);

            // Build message hash
            byte[] hash = BuildHash(tx);

            if (!ecdsa.VerifyData(hash.AsSpan(), tx.Signature, HashAlgorithmName.SHA256))
                return ValidationResult.Fail("ECDSA verification failed.");

            return ValidationResult.Success;
        }
        catch (CryptographicException ex)
        {
            return ValidationResult.Fail($"Crypto error: {ex.Message}");
        }
        catch (Exception ex)
        {
            // For non-crypto issues, bubble up to maintain observability
            var logger = context.LoggerFactory.CreateLogger<SignatureValidationRule>();
            logger.LogError(ex, "Unexpected error while validating signature.");
            throw;
        }

        static byte[] BuildHash(Transaction tx)
        {
            var buffer = ArrayPool<byte>.Shared.Rent(1 + 16 + 8 + tx.Payload.Length + 8);
            try
            {
                int offset = 0;
                buffer[offset++] = (byte)tx.Type;
                offset += BitConverter.TryWriteBytes(buffer.AsSpan(offset), tx.Id.ToByteArray()) ? 16 : throw new InvalidOperationException();
                offset += BitConverter.TryWriteBytes(buffer.AsSpan(offset), tx.Nonce) ? 8 : throw new InvalidOperationException();
                tx.Payload.CopyTo(buffer, offset);
                offset += tx.Payload.Length;
                offset += BitConverter.TryWriteBytes(buffer.AsSpan(offset), tx.Timestamp) ? 8 : throw new InvalidOperationException();

                return SHA256.HashData(buffer.AsSpan(0, offset));
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(buffer);
            }
        }
    }
}

/// <summary>
/// Verifies that the client-supplied timestamp is within reasonable boundaries.
/// </summary>
internal sealed class TimestampValidationRule : IValidationRule
{
    // Allow a 5-minute drift in either direction
    private const int AllowedSkewSeconds = 300;

    public string Name => nameof(TimestampValidationRule);

    public ValueTask<ValidationResult> ValidateAsync(TransactionContext context, CancellationToken ct)
    {
        long networkTime = context.ChainState.GetCurrentUnixTimeSeconds();
        long difference = Math.Abs(networkTime - context.Transaction.Timestamp);

        return difference > AllowedSkewSeconds
            ? ValueTask.FromResult(ValidationResult.Fail("Timestamp outside allowed skew."))
            : ValueTask.FromResult(ValidationResult.Success);
    }
}

/// <summary>
/// Ensures transaction nonce has not been reused by the signer.
/// </summary>
internal sealed class NonceValidationRule : IValidationRule
{
    public string Name => nameof(NonceValidationRule);

    public async ValueTask<ValidationResult> ValidateAsync(TransactionContext context, CancellationToken ct)
    {
        var unique = await context.ChainState
            .IsNonceUniqueAsync(context.Transaction.SignerPublicKey, context.Transaction.Nonce, ct)
            .ConfigureAwait(false);

        return unique
            ? ValidationResult.Success
            : ValidationResult.Fail("Duplicate nonce.");
    }
}

#endregion

#region Dependency-Injection Extensions

/// <summary>
/// Service-collection helpers for wiring default validation infrastructure.
/// </summary>
public static class TransactionValidatorServiceCollectionExtensions
{
    /// <summary>
    /// Registers the <see cref="TransactionValidator"/> and the built-in rule set.
    /// </summary>
    public static IServiceCollection AddTransactionValidation(this IServiceCollection services)
    {
        // Register rules
        services.AddSingleton<IValidationRule, TransactionStructureRule>();
        services.AddSingleton<IValidationRule, SignatureValidationRule>();
        services.AddSingleton<IValidationRule, TimestampValidationRule>();
        services.AddSingleton<IValidationRule, NonceValidationRule>();

        // Validator entry-point
        services.AddSingleton<ITransactionValidator, TransactionValidator>();

        return services;
    }
}

#endregion