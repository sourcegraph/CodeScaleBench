```csharp
// -----------------------------------------------------------------------------
//  UtilityChain Core Suite – Token Standard Definitions
//  Copyright © UtilityChain Contributors.
//  Licensed under the Business Source License 1.1 (see LICENSE).
// -----------------------------------------------------------------------------
//
//  File:        IURC20.cs
//  Project:     UtilityChain Core Suite (blockchain_defi)
//  Namespace:   UtilityChain.Tokens.Standards
//  Description: Primary interface describing the URC-20 fungible-token standard
//               used by the UtilityChain runtime. The interface is intentionally
//               richer than classical ERC-20, introducing asynchronous execution
//               semantics, first-class event payloads, and role-gated mint/burn
//               extensions that map to the platform’s governance engine.
// -----------------------------------------------------------------------------

using System;
using System.Numerics;
using System.Threading;
using System.Threading.Tasks;

namespace UtilityChain.Tokens.Standards
{
    /// <summary>
    /// URC-20 – UtilityChain Runtime Coin (version 20).
    ///
    /// The specification is largely inspired by Ethereum’s ERC-20 but extends it
    /// with:
    ///  • Asynchronous operations (to accommodate off-chain signing or consensus).
    ///  • First-class <see cref="BigInteger"/> for unlimited precision.
    ///  • Native cancellation support (<see cref="CancellationToken"/>).
    ///  • Domain events with rich payloads for real-time projections.
    ///  • Optional mint/burn hooks governed by UtilityChain’s policy engine.
    ///
    /// Implementations are expected to be thread-safe and re-entrant; all methods
    /// are pure (idempotent) unless explicitly stated otherwise.
    /// </summary>
    public interface IURC20
    {
        // ---------------------------------------------------------------------
        // Metadata
        // ---------------------------------------------------------------------

        /// <summary>Token’s human-readable name (e.g., “UtilityChain Credit”).</summary>
        string Name { get; }

        /// <summary>Token’s ticker symbol (e.g., “UTC”).</summary>
        string Symbol { get; }

        /// <summary>Number of fractional digits the token supports (usually 18).</summary>
        byte Decimals { get; }

        /// <summary>Total number of tokens in existence (inclusive of decimals).</summary>
        BigInteger TotalSupply { get; }

        // ---------------------------------------------------------------------
        // Balance & Allowance Queries
        // ---------------------------------------------------------------------

        /// <summary>
        /// Retrieves the balance of <paramref name="owner"/>.
        /// </summary>
        Task<BigInteger> BalanceOfAsync(
            Address owner,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Returns the remaining amount that <paramref name="spender"/> is allowed
        /// to withdraw from <paramref name="owner"/> via <see cref="TransferFromAsync"/>.
        /// </summary>
        Task<BigInteger> AllowanceAsync(
            Address owner,
            Address spender,
            CancellationToken cancellationToken = default);

        // ---------------------------------------------------------------------
        // State-Mutating Operations
        // ---------------------------------------------------------------------

        /// <summary>
        /// Transfers <paramref name="amount"/> tokens to <paramref name="recipient"/>.
        /// </summary>
        /// <remarks>
        /// Must fire <see cref="TransferOccurred"/> on success.
        /// </remarks>
        Task<bool> TransferAsync(
            Address recipient,
            BigInteger amount,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Allows <paramref name="spender"/> to withdraw up to <paramref name="amount"/>
        /// from caller’s account.
        /// </summary>
        /// <remarks>
        /// Must fire <see cref="ApprovalOccurred"/> on success.
        /// </remarks>
        Task<bool> ApproveAsync(
            Address spender,
            BigInteger amount,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Transfers <paramref name="amount"/> tokens from <paramref name="sender"/>
        /// to <paramref name="recipient"/> provided the caller has sufficient allowance.
        /// </summary>
        /// <remarks>
        /// Must fire <see cref="TransferOccurred"/> on success.
        /// </remarks>
        Task<bool> TransferFromAsync(
            Address sender,
            Address recipient,
            BigInteger amount,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Mints <paramref name="amount"/> new tokens and assigns them to
        /// <paramref name="recipient"/>. Requires caller to possess the “MINTER” role.
        /// </summary>
        /// <remarks>
        /// Implementations must adjust <see cref="TotalSupply"/> and fire
        /// <see cref="MintOccurred"/> and <see cref="TransferOccurred"/> events.
        /// </remarks>
        Task<bool> MintAsync(
            Address recipient,
            BigInteger amount,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Burns <paramref name="amount"/> tokens from <paramref name="holder"/>.
        /// Requires the caller to possess the “BURNER” role or to be <paramref name="holder"/>.
        /// </summary>
        /// <remarks>
        /// Must adjust <see cref="TotalSupply"/> and fire <see cref="BurnOccurred"/>.
        /// </remarks>
        Task<bool> BurnAsync(
            Address holder,
            BigInteger amount,
            CancellationToken cancellationToken = default);

        // ---------------------------------------------------------------------
        // Events
        // ---------------------------------------------------------------------

        /// <summary>
        /// Triggered whenever tokens are moved between two accounts.
        /// </summary>
        event EventHandler<TokenTransferEventArgs>? TransferOccurred;

        /// <summary>
        /// Triggered whenever an allowance is granted or changed.
        /// </summary>
        event EventHandler<TokenApprovalEventArgs>? ApprovalOccurred;

        /// <summary>
        /// Triggered whenever new tokens are minted into circulation.
        /// </summary>
        event EventHandler<TokenMintEventArgs>? MintOccurred;

        /// <summary>
        /// Triggered whenever tokens are destroyed.
        /// </summary>
        event EventHandler<TokenBurnEventArgs>? BurnOccurred;
    }

    // =========================================================================
    // Supporting Domain Types
    // =========================================================================

    /// <summary>
    /// Minimal immutable address representation understood by the UtilityChain
    /// runtime. Internally it wraps a 20-byte value, similar to an Ethereum
    /// address, but may be extended or replaced by a chain-specific structure.
    /// </summary>
    /// <remarks>
    /// The struct intentionally keeps comparison and hashing allocation-free.
    /// </remarks>
    public readonly record struct Address(ReadOnlySpan<byte> Value)
    {
        private const int ExpectedLength = 20;

        public Address(byte[] bytes)
            : this(new ReadOnlySpan<byte>(bytes))
        {
        }

        public Address(ReadOnlySpan<byte> span)
        {
            if (span.Length != ExpectedLength)
                throw new ArgumentException(
                    $"Address must be {ExpectedLength} bytes long.", nameof(span));

            // Copy into fixed-size buffer
            _value = new byte[ExpectedLength];
            span.CopyTo(_value);
        }

        private readonly byte[] _value;

        public ReadOnlySpan<byte> Span => _value;

        public override string ToString() => Convert.ToHexString(_value);
    }

    // -------------------------------------------------------------------------
    // Event Payloads
    // -------------------------------------------------------------------------

    /// <summary>Base class for all token-domain event payloads.</summary>
    public abstract class TokenEventArgs : EventArgs
    {
        protected TokenEventArgs(DateTimeOffset timestamp) => Timestamp = timestamp;

        /// <summary>Time when the event occurred according to node’s clock.</summary>
        public DateTimeOffset Timestamp { get; }
    }

    /// <inheritdoc />
    public sealed class TokenTransferEventArgs : TokenEventArgs
    {
        public TokenTransferEventArgs(
            Address from,
            Address to,
            BigInteger amount,
            DateTimeOffset timestamp)
            : base(timestamp)
        {
            From = from;
            To = to;
            Amount = amount;
        }

        public Address From { get; }
        public Address To { get; }
        public BigInteger Amount { get; }
    }

    /// <inheritdoc />
    public sealed class TokenApprovalEventArgs : TokenEventArgs
    {
        public TokenApprovalEventArgs(
            Address owner,
            Address spender,
            BigInteger amount,
            DateTimeOffset timestamp)
            : base(timestamp)
        {
            Owner = owner;
            Spender = spender;
            Amount = amount;
        }

        public Address Owner { get; }
        public Address Spender { get; }
        public BigInteger Amount { get; }
    }

    /// <inheritdoc />
    public sealed class TokenMintEventArgs : TokenEventArgs
    {
        public TokenMintEventArgs(
            Address recipient,
            BigInteger amount,
            Address minter,
            DateTimeOffset timestamp)
            : base(timestamp)
        {
            Recipient = recipient;
            Amount = amount;
            Minter = minter;
        }

        public Address Recipient { get; }
        public BigInteger Amount { get; }
        public Address Minter { get; }
    }

    /// <inheritdoc />
    public sealed class TokenBurnEventArgs : TokenEventArgs
    {
        public TokenBurnEventArgs(
            Address holder,
            BigInteger amount,
            Address burner,
            DateTimeOffset timestamp)
            : base(timestamp)
        {
            Holder = holder;
            Amount = amount;
            Burner = burner;
        }

        public Address Holder { get; }
        public BigInteger Amount { get; }
        public Address Burner { get; }
    }

    // -------------------------------------------------------------------------
    // Custom Exception Hierarchy
    // -------------------------------------------------------------------------

    /// <summary>
    /// Base class for URC-20 related errors. Consumers should catch this type
    /// when they need fine-grained diagnostics.
    /// </summary>
    public class UrC20Exception : Exception
    {
        public UrC20Exception(string message) : base(message) { }

        public UrC20Exception(string message, Exception innerException)
            : base(message, innerException) { }
    }

    public sealed class InsufficientBalanceException : UrC20Exception
    {
        public InsufficientBalanceException(Address owner, BigInteger attempted)
            : base($"Address {owner} has insufficient balance for {attempted}.")
        {
            Owner = owner;
            Attempted = attempted;
        }

        public Address Owner { get; }
        public BigInteger Attempted { get; }
    }

    public sealed class UnauthorizedOperationException : UrC20Exception
    {
        public UnauthorizedOperationException(string operation, Address caller)
            : base($"Caller {caller} is not authorized to perform '{operation}'.")
        {
            Operation = operation;
            Caller = caller;
        }

        public string Operation { get; }
        public Address Caller { get; }
    }
}
```