```csharp
// -----------------------------------------------------------------------------
//  UtilityChain Core Suite – Token Standards
//  File: IURC721.cs
// -----------------------------------------------------------------------------
//  Copyright
//      © 2024 UtilityChain Contributors. All rights reserved.
//  License
//      Licensed under the UtilityChain Community License (UCCL).
//      You may obtain a copy of the License in the project root.
// -----------------------------------------------------------------------------
//  Description
//      Definition of the URC-721 Non-Fungible Token standard. URC-721 is the
//      UtilityChain-specific counterpart to the public-chain ERC-721 standard.
//      The interface is intentionally opinionated toward enterprise/consortium
//      deployments and integrates with the in-process event bus used by the
//      wider UtilityChain runtime.
// -----------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace UtilityChain.Tokens.Standards
{
    #region Supporting Domain Types

    /// <summary>
    /// Represents a UtilityChain account address.
    /// </summary>
    public readonly struct Address : IEquatable<Address>
    {
        private static readonly Regex _regex = new(@"^0x[a-fA-F0-9]{40}$", RegexOptions.Compiled);

        public string Value { get; }

        public Address(string value)
        {
            if (string.IsNullOrWhiteSpace(value) || !_regex.IsMatch(value))
                throw new ArgumentException("Invalid address format. Expected 0x-prefixed 40-byte hex string.", nameof(value));

            Value = value.ToLowerInvariant();
        }

        public static implicit operator string(Address address) => address.Value;
        public static explicit operator Address(string value) => new(value);

        public bool Equals(Address other) => Value == other.Value;
        public override bool Equals(object? obj) => obj is Address other && Equals(other);
        public override int GetHashCode() => Value.GetHashCode(StringComparison.Ordinal);
        public override string ToString() => Value;
    }

    /// <summary>
    /// Type-safe wrapper around a 256-bit token identifier.
    /// </summary>
    public readonly struct TokenId : IEquatable<TokenId>, IComparable<TokenId>
    {
        public ulong High { get; }
        public ulong MidHigh { get; }
        public ulong MidLow { get; }
        public ulong Low { get; }

        public TokenId(ulong low)
            : this(0UL, 0UL, 0UL, low) { }

        public TokenId(ulong midLow, ulong low)
            : this(0UL, 0UL, midLow, low) { }

        public TokenId(ulong high, ulong midHigh, ulong midLow, ulong low)
        {
            High = high;
            MidHigh = midHigh;
            MidLow = midLow;
            Low = low;
        }

        public static implicit operator TokenId(ulong value) => new(value);
        public static explicit operator ulong(TokenId tokenId) => tokenId.Low;

        public bool Equals(TokenId other) =>
            High == other.High && MidHigh == other.MidHigh &&
            MidLow == other.MidLow && Low == other.Low;

        public override bool Equals(object? obj) => obj is TokenId other && Equals(other);
        public override int GetHashCode() =>
            HashCode.Combine(High, MidHigh, MidLow, Low);

        public int CompareTo(TokenId other)
        {
            if (High != other.High) return High.CompareTo(other.High);
            if (MidHigh != other.MidHigh) return MidHigh.CompareTo(other.MidHigh);
            if (MidLow != other.MidLow) return MidLow.CompareTo(other.MidLow);
            return Low.CompareTo(other.Low);
        }

        public override string ToString() =>
            $"0x{High:x16}{MidHigh:x16}{MidLow:x16}{Low:x16}".TrimStart('0');
    }

    /// <summary>
    /// Strongly-typed metadata payload compliant with the JSON schema adopted
    /// by popular NFT wallets and marketplaces.
    /// </summary>
    public record TokenMetadata(
        string Name,
        string Description,
        Uri Image,
        IReadOnlyDictionary<string, string> Attributes);

    #endregion Supporting Domain Types

    #region Event Payloads

    /// <summary>
    /// Raised when a token is transferred between two <see cref="Address"/>es.
    /// </summary>
    public readonly record struct TokenTransferEvent(Address From, Address To, TokenId TokenId);

    /// <summary>
    /// Raised when <see cref="Owner"/> approves <see cref="Spender"/> to
    /// transfer <see cref="TokenId"/>.
    /// </summary>
    public readonly record struct TokenApprovalEvent(Address Owner, Address Spender, TokenId TokenId);

    /// <summary>
    /// Raised when an operator is granted blanket transfer authorization over
    /// all tokens owned by <see cref="Owner"/>.
    /// </summary>
    public readonly record struct OperatorApprovalEvent(Address Owner, Address Operator, bool Approved);

    #endregion Event Payloads

    /// <summary>
    /// URC-721 Non-Fungible Token standard (UtilityChain).
    /// </summary>
    /// <remarks>
    /// The interface mirrors ERC-721 verbatim wherever possible but introduces
    /// additional features such as rich metadata retrieval and event streaming
    /// via <see cref="IObservable{T}"/> for tighter integration with the
    /// UtilityChain event bus.
    /// </remarks>
    public interface IURC721 :
        IObservable<TokenTransferEvent>,
        IObservable<TokenApprovalEvent>,
        IObservable<OperatorApprovalEvent>
    {
        #region Core Token Operations

        /// <summary>
        /// Returns the number of tokens owned by <paramref name="owner"/>.
        /// </summary>
        /// <exception cref="ArgumentNullException"/>
        ulong BalanceOf(Address owner);

        /// <summary>
        /// Returns the owner of the specified <paramref name="tokenId"/>.
        /// </summary>
        /// <exception cref="KeyNotFoundException">The token does not exist.</exception>
        Address OwnerOf(TokenId tokenId);

        /// <summary>
        /// Securely transfers <paramref name="tokenId"/> from <paramref name="from"/>
        /// to <paramref name="to"/>. The call MUST throw when the recipient
        /// contract is unable to handle URC-721 tokens.
        /// </summary>
        void SafeTransferFrom(Address from, Address to, TokenId tokenId, ReadOnlySpan<byte> data = default);

        /// <summary>
        /// Transfers <paramref name="tokenId"/> from <paramref name="from"/> to
        /// <paramref name="to"/>. The caller is responsible for ensuring
        /// <paramref name="to"/> is capable of receiving the token.
        /// </summary>
        void TransferFrom(Address from, Address to, TokenId tokenId);

        /// <summary>
        /// Approves <paramref name="spender"/> to transfer <paramref name="tokenId"/>.
        /// </summary>
        void Approve(Address spender, TokenId tokenId);

        /// <summary>
        /// Approves or revokes <paramref name="operator"/> as an operator for
        /// all tokens owned by the caller.
        /// </summary>
        void SetApprovalForAll(Address @operator, bool approved);

        /// <summary>
        /// Returns the approved address for <paramref name="tokenId"/>, or
        /// <see cref="Address"/> with an empty value if no approval exists.
        /// </summary>
        Address GetApproved(TokenId tokenId);

        /// <summary>
        /// Returns <c>true</c> if <paramref name="operator"/> is authorized to
        /// manage all of <paramref name="owner"/>'s assets.
        /// </summary>
        bool IsApprovedForAll(Address owner, Address @operator);

        #endregion Core Token Operations

        #region Mint / Burn (UtilityChain Extension)

        /// <summary>
        /// Mints a new token and assigns it to <paramref name="to"/>.
        /// </summary>
        /// <param name="to">Recipient address.</param>
        /// <param name="tokenId">New token identifier.</param>
        /// <param name="metadata">Optional metadata payload.</param>
        void Mint(Address to, TokenId tokenId, TokenMetadata? metadata = null);

        /// <summary>
        /// Burns (destroys) <paramref name="tokenId"/> permanently.
        /// </summary>
        void Burn(TokenId tokenId);

        #endregion Mint / Burn

        #region Metadata & Enumeration

        /// <summary>
        /// Returns a URI pointing to metadata json for <paramref name="tokenId"/>.
        /// </summary>
        /// <exception cref="KeyNotFoundException">Token not found.</exception>
        Uri TokenUri(TokenId tokenId);

        /// <summary>
        /// Returns the rich metadata record for <paramref name="tokenId"/>, if
        /// metadata is stored on-chain or in the local data store.
        /// </summary>
        TokenMetadata? GetTokenMetadata(TokenId tokenId);

        /// <summary>
        /// Enumerates all <see cref="TokenId"/> values owned by
        /// <paramref name="owner"/>.
        /// </summary>
        IReadOnlyCollection<TokenId> TokensOf(Address owner);

        /// <summary>
        /// Enumerates every minted token in the collection. The implementation
        /// SHOULD return a snapshot to guarantee consistency.
        /// </summary>
        IReadOnlyCollection<TokenId> AllTokens();

        #endregion Metadata & Enumeration
    }
}
```