```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.TransactionProcessing/Factories/TransferTransactionFactory.cs
// Project: UtilityChain Core Suite (blockchain_defi)
// Language: C# 12 / .NET 8

using System;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Numerics;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace UtilityChain.TransactionProcessing.Factories
{
    /// <summary>
    /// Factory responsible for composing and signing transfer-type transactions.
    /// The class is built for DI, promotes testability (IClock), and applies
    /// validation, deterministic fee calculation and cryptographic hashing.
    /// </summary>
    public sealed class TransferTransactionFactory : ITransferTransactionFactory
    {
        private readonly IAddressValidator _addressValidator;
        private readonly IFeeCalculator     _feeCalculator;
        private readonly IHashProvider      _hashProvider;
        private readonly IClock             _clock;
        private readonly ILogger<TransferTransactionFactory> _logger;

        public TransferTransactionFactory(
            IAddressValidator                 addressValidator,
            IFeeCalculator                    feeCalculator,
            IHashProvider                     hashProvider,
            IClock                            clock,
            ILogger<TransferTransactionFactory>? logger = null)
        {
            _addressValidator = addressValidator ?? throw new ArgumentNullException(nameof(addressValidator));
            _feeCalculator    = feeCalculator    ?? throw new ArgumentNullException(nameof(feeCalculator));
            _hashProvider     = hashProvider     ?? throw new ArgumentNullException(nameof(hashProvider));
            _clock            = clock            ?? throw new ArgumentNullException(nameof(clock));
            _logger           = logger          ?? NullLogger<TransferTransactionFactory>.Instance;
        }

        /// <inheritdoc />
        public TransferTransaction Create(TokenTransferRequest request, ChainContext context)
        {
            ArgumentNullException.ThrowIfNull(request);
            ArgumentNullException.ThrowIfNull(context);

            _logger.LogTrace("Creating transfer transaction {@Request}", request);

            // ------------------------------------------------------------------
            // Validation
            // ------------------------------------------------------------------
            if (!_addressValidator.IsValid(request.From))
                throw new AddressFormatException($"Sender address '{request.From}' is invalid.");

            if (!_addressValidator.IsValid(request.To))
                throw new AddressFormatException($"Recipient address '{request.To}' is invalid.");

            if (request.Amount <= UInt256.Zero)
                throw new ArgumentOutOfRangeException(nameof(request.Amount), "Transfer amount must be greater than zero.");

            // ------------------------------------------------------------------
            // Fee calculation & header assembly
            // ------------------------------------------------------------------
            var fee       = _feeCalculator.CalculateTransferFee(request.Amount, context.NetworkCongestionLevel);
            var timestamp = _clock.UtcNow;

            var header = new TransactionHeader(
                nonce     : request.Nonce,
                networkId : context.NetworkId,
                timestamp : timestamp,
                expiry    : timestamp.Add(context.TransactionMaxLifetime),
                fee       : fee,
                signer    : request.From);

            // ------------------------------------------------------------------
            // Payload assembly
            // ------------------------------------------------------------------
            var payload = new TransferPayload(
                tokenId : request.TokenId,
                from    : request.From,
                to      : request.To,
                amount  : request.Amount);

            var transaction = new TransferTransaction(header, payload);

            // ------------------------------------------------------------------
            // Hash & return
            // ------------------------------------------------------------------
            var hash = _hashProvider.ComputeHash(transaction);
            transaction.SetHash(hash);

            _logger.LogDebug("Transfer transaction built with hash {Hash}", Convert.ToHexString(hash));

            return transaction;
        }

        /// <inheritdoc />
        public IReadOnlyCollection<TransferTransaction> CreateBatch(IEnumerable<TokenTransferRequest> requests, ChainContext context)
        {
            ArgumentNullException.ThrowIfNull(requests);

            var txList = new List<TransferTransaction>();

            foreach (var request in requests)
            {
                try
                {
                    txList.Add(Create(request, context));
                }
                catch (Exception ex)
                {
                    // The caller can decide whether to re-throw or inspect logs for failures.
                    _logger.LogWarning(ex, "Failed to create transfer transaction for request {@Request}", request);
                }
            }

            return txList;
        }
    }

    #region Interfaces (domain abstractions)

    /// <summary>
    /// DI contract for the transfer factory.
    /// </summary>
    public interface ITransferTransactionFactory
    {
        TransferTransaction Create(TokenTransferRequest request, ChainContext context);
        IReadOnlyCollection<TransferTransaction> CreateBatch(IEnumerable<TokenTransferRequest> requests, ChainContext context);
    }

    /// <summary>Validates structural correctness of chain addresses.</summary>
    public interface IAddressValidator
    {
        bool IsValid(Address address);
    }

    /// <summary>Responsible for dynamic fee calculation.</summary>
    public interface IFeeCalculator
    {
        UInt256 CalculateTransferFee(UInt256 amount, int networkCongestionLevel);
    }

    /// <summary>Provides deterministic cryptographic hashing for transactions.</summary>
    public interface IHashProvider
    {
        byte[] ComputeHash(TransactionBase txn);
    }

    /// <summary>Injectable clock interface to facilitate deterministic testing.</summary>
    public interface IClock
    {
        DateTime UtcNow { get; }
    }

    #endregion

    #region Request & context models

    /// <summary>
    /// DTO that arrives from REST/CLI layer to request a token transfer.
    /// </summary>
    public sealed record TokenTransferRequest
    {
        public required Address  From   { get; init; }
        public required Address  To     { get; init; }
        public required UInt256  Amount { get; init; }
        public required UInt256  Nonce  { get; init; }
        public TokenId           TokenId { get; init; } = TokenId.Native;
    }

    /// <summary>
    /// Snapshot of chain-wide state relevant for transaction creation.
    /// </summary>
    public sealed record ChainContext(
        string   NetworkId,
        int      NetworkCongestionLevel,
        TimeSpan TransactionMaxLifetime);

    #endregion

    #region Transaction domain model

    /// <summary>Base class for all transaction types.</summary>
    public abstract class TransactionBase
    {
        private byte[]? _hash; // Null until signed/hashed.

        protected TransactionBase(TransactionHeader header)
        {
            Header = header ?? throw new ArgumentNullException(nameof(header));
        }

        public TransactionHeader Header { get; }
        public abstract TransactionType Type { get; }

        public byte[] GetHash() =>
            _hash ?? throw new InvalidOperationException("Transaction has not been hashed yet.");

        public void SetHash(byte[] hash)
        {
            ArgumentNullException.ThrowIfNull(hash);
            _hash = hash;
        }

        /// <summary>Serialises the full transaction (header + payload).</summary>
        public ReadOnlySpan<byte> Serialize()
        {
            var payload = SerializePayload();
            var header  = Header.Serialize();

            var buffer = new byte[1 + header.Length + payload.Length];
            buffer[0] = (byte)Type;
            header.CopyTo(buffer.AsSpan(1));
            payload.CopyTo(buffer.AsSpan(1 + header.Length));
            return buffer;
        }

        /// <summary>Serialises the concrete payload implemented by sub-classes.</summary>
        protected abstract ReadOnlySpan<byte> SerializePayload();
    }

    /// <summary>Header portion common to any transaction.</summary>
    public sealed record TransactionHeader(
        UInt256 nonce,
        string  networkId,
        DateTime timestamp,
        DateTime expiry,
        UInt256 fee,
        Address signer)
    {
        public ReadOnlySpan<byte> Serialize()
        {
            // For brevity a naive layout is used: [nonce|networkLen|networkId|timestamp|expiry|fee|signer]
            Span<byte> buffer = stackalloc byte[UInt256.Size + 1 + 32 + 8 + 8 + UInt256.Size + Address.Size];
            var offset = 0;

            nonce.WriteTo(buffer, ref offset);

            var networkBytes = System.Text.Encoding.UTF8.GetBytes(networkId);
            if (networkBytes.Length > 32)
                throw new InvalidOperationException("NetworkId must be <= 32 bytes.");

            buffer[offset++] = (byte)networkBytes.Length;           // length-prefix
            networkBytes.CopyTo(buffer.Slice(offset));
            offset += networkBytes.Length;

            BitConverter.TryWriteBytes(buffer.Slice(offset), timestamp.ToBinary());
            offset += sizeof(long);

            BitConverter.TryWriteBytes(buffer.Slice(offset), expiry.ToBinary());
            offset += sizeof(long);

            fee.WriteTo(buffer, ref offset);
            signer.WriteTo(buffer, ref offset);

            return buffer[..offset].ToArray();
        }
    }

    public enum TransactionType : byte
    {
        Unknown  = 0,
        Transfer = 1,
        Stake    = 2,
        Contract = 3,
        Mint     = 4
    }

    /// <summary>
    /// Concrete transaction that moves value from one address to another.
    /// </summary>
    public sealed class TransferTransaction : TransactionBase
    {
        public TransferPayload Payload { get; }

        public TransferTransaction(TransactionHeader header, TransferPayload payload)
            : base(header)
        {
            Payload = payload ?? throw new ArgumentNullException(nameof(payload));
        }

        public override TransactionType Type => TransactionType.Transfer;

        protected override ReadOnlySpan<byte> SerializePayload() => Payload.Serialize();
    }

    /// <summary>Struct-like payload for a transfer.</summary>
    public sealed record TransferPayload(TokenId TokenId, Address From, Address To, UInt256 Amount)
    {
        public ReadOnlySpan<byte> Serialize()
        {
            Span<byte> buffer = stackalloc byte[TokenId.Size + (Address.Size * 2) + UInt256.Size];
            var offset = 0;
            TokenId.WriteTo(buffer, ref offset);
            From.WriteTo(buffer, ref offset);
            To.WriteTo(buffer, ref offset);
            Amount.WriteTo(buffer, ref offset);
            return buffer[..offset].ToArray();
        }
    }

    #endregion

    #region Primitives  (UInt256, TokenId, Address)

    /// <summary>Primitive 256-bit unsigned integer.</summary>
    public readonly struct UInt256 : IEquatable<UInt256>, IComparable<UInt256>
    {
        public const int Size = 32; // 256 / 8
        private readonly BigInteger _value;

        public static readonly UInt256 Zero = new(BigInteger.Zero);

        public UInt256(BigInteger value)
        {
            if (value.Sign < 0)                 throw new ArgumentOutOfRangeException(nameof(value), "Value must be non-negative.");
            if (value.GetByteCount() > Size)    throw new ArgumentOutOfRangeException(nameof(value), "Value exceeds 256-bits.");
            _value = value;
        }

        public static implicit operator UInt256(int        v) => new(new BigInteger(v));
        public static implicit operator UInt256(BigInteger v) => new(v);
        public static implicit operator BigInteger(UInt256 v) => v._value;

        public int CompareTo(UInt256 other) => _value.CompareTo(other._value);
        public bool Equals(UInt256 other)   => _value.Equals(other._value);
        public override bool Equals(object? obj) => obj is UInt256 u && Equals(u);
        public override int GetHashCode()   => _value.GetHashCode();
        public override string ToString()   => _value.ToString();

        public static UInt256 operator +(UInt256 a, UInt256 b) => new(a._value + b._value);
        public static UInt256 operator -(UInt256 a, UInt256 b) => 
            a._value < b._value ? throw new InvalidOperationException("Result would be negative.") : new UInt256(a._value - b._value);

        public void WriteTo(Span<byte> dest, ref int offset)
        {
            // Serialise as big-endian 32-byte value.
            var src = _value.ToByteArray(isUnsigned: true, isBigEndian: true);
            var pad = Size - src.Length;
            dest.Slice(offset, pad).Clear(); // leading zeros
            offset += pad;
            src.CopyTo(dest.Slice(offset));
            offset += src.Length;
        }

        public static bool operator >(UInt256 left, UInt256 right) => left.CompareTo(right) > 0;
        public static bool operator <(UInt256 left, UInt256 right) => left.CompareTo(right) < 0;
        public static bool operator >=(UInt256 left, UInt256 right) => left.CompareTo(right) >= 0;
        public static bool operator <=(UInt256 left, UInt256 right) => left.CompareTo(right) <= 0;
    }

    /// <summary>32-byte address (similar to ETH addresses without checksum).</summary>
    public readonly struct Address : IEquatable<Address>
    {
        public const int Size = 32;
        private readonly byte[] _bytes;

        public static readonly Address Empty = new(new byte[Size]);

        public Address(byte[] bytes)
        {
            if (bytes == null)                   throw new ArgumentNullException(nameof(bytes));
            if (bytes.Length != Size)            throw new ArgumentException($"Address must be {Size} bytes.", nameof(bytes));
            _bytes = bytes;
        }

        public void WriteTo(Span<byte> dest, ref int offset)
        {
            _bytes.CopyTo(dest.Slice(offset, Size));
            offset += Size;
        }

        public override string ToString()  => Convert.ToHexString(_bytes);
        public bool Equals(Address other)  => _bytes.AsSpan().SequenceEqual(other._bytes);
        public override bool Equals(object? obj) => obj is Address a && Equals(a);
        public override int GetHashCode()  => HashCode.Combine(_bytes);
    }

    /// <summary>Token identifier (defaults to native currency).</summary>
    public readonly struct TokenId : IEquatable<TokenId>
    {
        public const int Size = UInt256.Size;
        private readonly UInt256 _value;

        public static readonly TokenId Native = new(UInt256.Zero);

        public TokenId(UInt256 value) => _value = value;

        public void WriteTo(Span<byte> dest, ref int offset) => _value.WriteTo(dest, ref offset);

        public bool Equals(TokenId other)  => _value.Equals(other._value);
        public override bool Equals(object? obj) => obj is TokenId id && Equals(id);
        public override int GetHashCode()  => _value.GetHashCode();
        public override string ToString()  => _value.ToString();
    }

    #endregion

    #region Exception types

    /// <summary>Raised when a provided address is malformed.</summary>
    [SuppressMessage("Design", "CA1032:Implement standard exception constructors", Justification = "N/A for internal use.")]
    public sealed class AddressFormatException : FormatException
    {
        public AddressFormatException(string message) : base(message) { }
    }

    #endregion
}
```