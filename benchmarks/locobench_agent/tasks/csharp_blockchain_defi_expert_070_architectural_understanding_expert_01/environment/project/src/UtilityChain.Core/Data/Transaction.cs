```csharp
// -----------------------------------------------------------------------------
// UtilityChain Core Suite
// File: UtilityChain.Core/Data/Transaction.cs
// Author: AI Assistant
// -----------------------------------------------------------------------------
// Copyright (c) UtilityChain.
// Licensed under the MIT license. See LICENSE file in the repository root.
// -----------------------------------------------------------------------------

using System;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace UtilityChain.Core.Data
{
    /// <summary>
    ///     Immutable domain object that represents an on-chain transaction. The record encapsulates
    ///     all data required to verify signatures, enforce nonce-ordering, and deterministically
    ///     serialize the transaction for hashing and consensus.
    /// </summary>
    /// <remarks>
    ///     The object is intentionally self-contained (no external references) so that embedding
    ///     nodes, indexers, or wallets can reuse the struct without pulling the entire monolith.
    /// </remarks>
    public sealed record Transaction : IEquatable<Transaction>
    {
        #region Factory Helpers

        /// <summary>
        ///     Creates a signed transaction from the supplied arguments and ECDSA key.
        ///     The transaction is automatically hashed and validated.
        /// </summary>
        /// <exception cref="ArgumentException">Thrown when validation fails.</exception>
        public static Transaction Create(
            Address            sender,
            Address            recipient,
            long               amount,
            long               fee,
            long               nonce,
            TransactionType    type,
            ReadOnlyMemory<byte> payload,
            ECDsa              signingKey)
        {
            var tx = new Transaction(
                Guid.Empty, // will be replaced after hash
                sender,
                recipient,
                amount,
                fee,
                nonce,
                DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                type,
                payload,
                Array.Empty<byte>() // temp sig
            );

            tx = tx with { Hash = tx.CalculateHash() };
            var signature = tx.Sign(signingKey);

            tx = tx with { Signature = signature };

            tx.ThrowIfInvalid();

            return tx;
        }

        #endregion

        #region Constructors / Init

        [JsonConstructor]
        public Transaction(
            Guid               hash,
            Address            sender,
            Address            recipient,
            long               amount,
            long               fee,
            long               nonce,
            long               timestamp,
            TransactionType    type,
            ReadOnlyMemory<byte> payload,
            ReadOnlyMemory<byte> signature)
        {
            Hash       = hash;
            Sender     = sender;
            Recipient  = recipient;
            Amount     = amount;
            Fee        = fee;
            Nonce      = nonce;
            Timestamp  = timestamp;
            Type       = type;
            Payload    = payload;
            Signature  = signature;
        }

        #endregion

        #region Public Properties

        /// <summary>
        ///     Unique identifier of the transaction produced from SHA-256 over the serialized body.
        ///     The hash is rendered as a GUID for database friendliness but keeps the full 128-bit
        ///     uniqueness guarantee.
        /// </summary>
        public Guid Hash { get; init; }

        public Address            Sender    { get; init; }
        public Address            Recipient { get; init; }
        public long               Amount    { get; init; }  // atomic units (i.e. 8 decimals)
        public long               Fee       { get; init; }  // atomic units
        public long               Nonce     { get; init; }
        public long               Timestamp { get; init; }  // milliseconds since epoch
        public TransactionType    Type      { get; init; }

        /// <summary>
        ///     Arbitrary, contract-specific payload (e.g., encoded function call).
        /// </summary>
        public ReadOnlyMemory<byte> Payload { get; init; }

        /// <summary>
        ///     DER-encoded ECDSA signature over the transaction body.
        /// </summary>
        public ReadOnlyMemory<byte> Signature { get; init; }

        #endregion

        #region Signing / Hashing

        /// <summary>
        ///     Hashes the canonical byte representation of the transaction using SHA-256, truncates
        ///     to 128 bits, and converts the result to a GUID (Big-Endian).
        /// </summary>
        public Guid CalculateHash()
        {
            using var sha = SHA256.Create();
            var bytes = SerializeBody();

            var hash = sha.ComputeHash(bytes);
            Span<byte> guidBytes = stackalloc byte[16];
            hash.AsSpan(0, 16).CopyTo(guidBytes);

            // Convert to GUID (RFC 4122) using big-endian bytes
            if (BitConverter.IsLittleEndian)
            {
                ReverseUuidByteOrder(guidBytes);
            }

            return new Guid(guidBytes);
        }

        /// <summary>
        ///     Signs the transaction using the provided ECDSA key and returns the DER-encoded
        ///     signature bytes.
        /// </summary>
        public ReadOnlyMemory<byte> Sign(ECDsa key)
        {
            if (key == null) throw new ArgumentNullException(nameof(key));

            var body = SerializeBody();
            var sig  = key.SignData(body, HashAlgorithmName.SHA256);

            return sig;
        }

        /// <summary>
        ///     Verifies the transaction signature against the provided ECDSA public key.
        /// </summary>
        public bool VerifySignature(ECDsa key)
        {
            if (key == null) throw new ArgumentNullException(nameof(key));
            if (Signature.IsEmpty) return false;

            return key.VerifyData(
                SerializeBody(),
                Signature.ToArray(),
                HashAlgorithmName.SHA256);
        }

        #endregion

        #region Validation

        /// <summary>
        ///     Performs a series of invariant checks to ensure the transaction is structurally
        ///     valid. Does <b>not</b> check balances or state roots—those checks are handled by
        ///     the consensus engine.
        /// </summary>
        /// <exception cref="ArgumentException">Thrown when validation fails.</exception>
        public void ThrowIfInvalid()
        {
            var errors = ValidateCore().ToArray();
            if (errors.Length > 0)
            {
                throw new ArgumentException(
                    $"Transaction validation failed:{Environment.NewLine} - " +
                    string.Join(Environment.NewLine + " - ", errors));
            }
        }

        private System.Collections.Generic.IEnumerable<string> ValidateCore()
        {
            if (Sender == Recipient)
                yield return "Sender and recipient cannot be the same.";

            if (Amount <= 0)
                yield return "Amount must be positive.";

            if (Fee < 0)
                yield return "Fee cannot be negative.";

            if (Nonce < 0)
                yield return "Nonce cannot be negative.";

            if (Timestamp <= 0 ||
                Timestamp > DateTimeOffset.UtcNow.AddMinutes(5).ToUnixTimeMilliseconds())
                yield return "Timestamp is unrealistic.";

            if (Hash == Guid.Empty)
                yield return "Hash has not been computed.";

            if (Signature.IsEmpty)
                yield return "Signature is missing.";
        }

        #endregion

        #region Serialization Helpers

        /// <summary>
        ///     Serializes the transaction body (all fields except Hash/Signature) in a
        ///     deterministic manner for hashing and signing. JSON is used for readability, but the
        ///     encoder is configured for consistent ordering and invariant culture to prevent hash
        ///     inconsistencies between platforms.
        /// </summary>
        private byte[] SerializeBody()
        {
            var body = new SerializableBody(
                Sender.Value,
                Recipient.Value,
                Amount,
                Fee,
                Nonce,
                Timestamp,
                Type,
                Payload.ToArray());

            return JsonSerializer.SerializeToUtf8Bytes(
                body,
                JsonOptions);
        }

        private static readonly JsonSerializerOptions JsonOptions = new()
        {
            Encoder                 = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            WriteIndented           = false,
            PropertyNamingPolicy    = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition  = JsonIgnoreCondition.Never
        };

        // DTO used exclusively for hashing/signing to avoid accidental inclusion of Hash + Signature
        private sealed record SerializableBody(
            string          sender,
            string          recipient,
            long            amount,
            long            fee,
            long            nonce,
            long            timestamp,
            TransactionType type,
            byte[]          payload);

        #endregion

        #region Equality Overrides

        public bool Equals(Transaction? other) =>
            other is not null && Hash == other.Hash;

        public override int GetHashCode() => Hash.GetHashCode();

        #endregion

        #region Helpers

        private static void ReverseUuidByteOrder(Span<byte> guidBytes)
        {
            // RFC 4122: first three fields are little-endian on Windows GUIDs
            void Swap(int a, int b)
            {
                (guidBytes[a], guidBytes[b]) = (guidBytes[b], guidBytes[a]);
            }

            Swap(0, 3); Swap(1, 2);
            Swap(4, 5);
            Swap(6, 7);
            // Remaining bytes are already in correct order
        }

        #endregion
    }

    /// <summary>
    ///     Represents a 20-byte blockchain address rendered as hex (0x…) or Base58. The struct
    ///     provides equality semantics and basic validation without relying on the broader
    ///     cryptography module.
    /// </summary>
    public readonly struct Address : IEquatable<Address>
    {
        private const int ByteLength = 20;

        public Address(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
                throw new ArgumentException("Address cannot be null or whitespace.", nameof(value));

            if (!IsValidFormat(value))
                throw new FormatException("Address format is invalid.");

            Value = value;
        }

        [JsonConstructor]
        public string Value { get; }

        public bool Equals(Address other) => string.Equals(Value, other.Value, StringComparison.OrdinalIgnoreCase);

        public override bool Equals(object? obj) => obj is Address other && Equals(other);

        public override int GetHashCode() => Value.ToLowerInvariant().GetHashCode();

        public static bool operator ==(Address left, Address right) => left.Equals(right);

        public static bool operator !=(Address left, Address right) => !left.Equals(right);

        public override string ToString() => Value;

        /// <summary>
        ///     Rough validation: checks hex or Base58 and ensures correct byte length after decoding.
        /// </summary>
        private static bool IsValidFormat(string value)
        {
            Span<byte> buffer = stackalloc byte[ByteLength];

            if (value.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
            {
                return ConvertHex(value.AsSpan(2), buffer);
            }

            // Assume Base58 otherwise
            return TryDecodeBase58(value.AsSpan(), buffer);
        }

        #region Hex helpers

        private static bool ConvertHex(ReadOnlySpan<char> hex, Span<byte> buffer)
        {
            if (hex.Length != ByteLength * 2) return false;

            for (var i = 0; i < buffer.Length; i++)
            {
                var high = HexToByte(hex[i * 2]);
                var low  = HexToByte(hex[i * 2 + 1]);

                if (high < 0 || low < 0) return false;

                buffer[i] = (byte)((high << 4) | low);
            }

            return true;

            static int HexToByte(char c) => c switch
            {
                >= '0' and <= '9' => c - '0',
                >= 'a' and <= 'f' => c - 'a' + 10,
                >= 'A' and <= 'F' => c - 'A' + 10,
                _                 => -1
            };
        }

        #endregion

        #region Base58 helpers

        private const string Base58Alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

        private static bool TryDecodeBase58(ReadOnlySpan<char> text, Span<byte> buffer)
        {
            Span<int> indices = stackalloc int[text.Length];
            for (var i = 0; i < text.Length; i++)
            {
                var idx = Base58Alphabet.IndexOf(text[i]);
                if (idx == -1) return false;
                indices[i] = idx;
            }

            // Simple BigInteger conversion (base 58 -> base 256)
            Span<byte> temp = stackalloc byte[64];
            int length = 0;

            foreach (var idx in indices)
            {
                int carry = idx;
                for (int j = 0; j < length; j++)
                {
                    int val = temp[j] * 58 + carry;
                    temp[j] = (byte)(val & 0xFF);
                    carry   = val >> 8;
                }

                while (carry > 0)
                {
                    temp[length++] = (byte)(carry & 0xFF);
                    carry >>= 8;
                }
            }

            // Strip leading zeros
            int leadingZeros = text.TakeWhile(c => c == '1').Count();

            int totalLength = leadingZeros + length;
            if (totalLength != ByteLength) return false;

            // Fill result buffer
            buffer.Slice(0, leadingZeros).Fill(0);
            for (int i = 0; i < length; i++)
            {
                buffer[totalLength - 1 - i] = temp[i];
            }

            return true;
        }

        #endregion
    }

    /// <summary>
    ///     Enumerates all protocol-level transaction categories understood by the core engine.
    ///     The enum is designed to be bit-field friendly (up to 32 unique types).
    /// </summary>
    [Flags]
    public enum TransactionType : byte
    {
        Unknown       = 0,
        Transfer      = 1 << 0,
        ContractCall  = 1 << 1,
        Stake         = 1 << 2,
        Governance    = 1 << 3,
        Mint          = 1 << 4,
        Burn          = 1 << 5
    }
}
```
