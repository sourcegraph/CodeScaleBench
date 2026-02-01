```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Tokens/NFTMinter.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using UtilityChain.Common;
using UtilityChain.Common.Cryptography;
using UtilityChain.Common.Events;
using UtilityChain.Persistence;
using UtilityChain.Tokens.Domain;
using UtilityChain.Tokens.Events;

namespace UtilityChain.Tokens
{
    /// <summary>
    /// Default implementation used by UtilityChain to create, persist and broadcast newly minted NFTs.
    /// The design applies Strategy, Factory and Observer patterns so that additional standards
    /// (e.g. ERC4907 – rentable NFTs) can be plugged-in at runtime without touching calling code.
    /// </summary>
    public sealed class NftMinter : INftMinter, IAsyncDisposable
    {
        private readonly ILogger<NftMinter> _logger;
        private readonly INftRepository _repository;
        private readonly ICryptoService _crypto;
        private readonly IEventBus _bus;
        private readonly INftMintingStrategyFactory _strategyFactory;
        private readonly SemaphoreSlim _gate = new(1, 1);   // prevents double-spend when minting non-fungibles
        private readonly ConcurrentDictionary<Hash128, byte> _inFlight = new();

        public NftMinter(
            ILogger<NftMinter> logger,
            INftRepository repository,
            ICryptoService crypto,
            IEventBus bus,
            INftMintingStrategyFactory strategyFactory)
        {
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _repository = repository ?? throw new ArgumentNullException(nameof(repository));
            _crypto = crypto ?? throw new ArgumentNullException(nameof(crypto));
            _bus = bus ?? throw new ArgumentNullException(nameof(bus));
            _strategyFactory = strategyFactory ?? throw new ArgumentNullException(nameof(strategyFactory));
        }

        /// <inheritdoc />
        public async ValueTask<Hash128> MintAsync(NftMintRequest request, CancellationToken ct = default)
        {
            ArgumentNullException.ThrowIfNull(request);
            request.Validate(); // throws on bad input

            Hash128 txnId = Hash128.CreateGuid();
            _logger.LogInformation(
                "NFT mint requested: {TxnId} | Std={Standard} | Symbol={Symbol} | Supply={Supply}",
                txnId, request.Standard, request.Symbol, request.Supply);

            if (!_inFlight.TryAdd(txnId, 0))
                throw new InvalidOperationException($"Mint transaction already in progress: {txnId}");

            await _gate.WaitAsync(ct).ConfigureAwait(false); // serialize mint operations
            try
            {
                // Double-check that the collection/symbol doesn't already exist for 721 standard
                if (request.Standard == NftStandard.Urc721 &&
                    await _repository.CollectionExistsAsync(request.Symbol, ct))
                    throw new NftMintException($"NFT symbol '{request.Symbol}' already minted.");

                var strategy = _strategyFactory.GetStrategy(request.Standard);
                var nftCollection = await strategy.MintAsync(request, txnId, ct).ConfigureAwait(false);

                // Sign the resulting collection root hash so node operators can audit provenance
                nftCollection.Signature = _crypto.Sign(nftCollection.RootHash.ToByteArray());

                await _repository.SaveAsync(nftCollection, ct).ConfigureAwait(false);

                _bus.Publish(new NftMintedEvent(nftCollection));

                _logger.LogInformation(
                    "NFT minted successfully: {TxnId} | Collection={Collection} | Items={Count}",
                    txnId, nftCollection.Symbol, nftCollection.Items.Count);

                return txnId;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Mint failed: {TxnId}", txnId);
                throw;
            }
            finally
            {
                _gate.Release();
                _inFlight.TryRemove(txnId, out _);
            }
        }

        public async ValueTask DisposeAsync()
        {
            _gate.Dispose();
            await _bus.DisposeAsync().ConfigureAwait(false);
        }
    }

    #region Contracts & Models

    /// <summary>
    /// Abstraction to mint NFTs; implemented by <see cref="NftMinter"/>.
    /// </summary>
    public interface INftMinter
    {
        /// <summary>
        /// Creates a new NFT collection and persists the data on-chain.
        /// </summary>
        /// <returns>Transaction identifier representing the mint operation.</returns>
        ValueTask<Hash128> MintAsync(NftMintRequest request, CancellationToken ct = default);
    }

    /// <summary>
    /// Represents supported non-fungible token standards within UtilityChain.
    /// </summary>
    public enum NftStandard
    {
        Urc721 = 721,
        Urc1155 = 1155
    }

    /// <summary>
    /// DTO supplied by API/UI callers when minting new NFTs.
    /// </summary>
    public sealed record NftMintRequest
    {
        public required NftStandard Standard { get; init; }
        public required string Symbol { get; init; }
        public required string Name { get; init; }
        public string? Description { get; init; }
        public Uri? ExternalUrl { get; init; }
        public int Supply { get; init; } = 1;
        public IDictionary<int, IDictionary<string, object>>? MetadataByTokenId { get; init; }
        public Address Owner { get; init; } = Address.Null;

        public void Validate()
        {
            if (string.IsNullOrWhiteSpace(Symbol))
                throw new ArgumentException("Symbol is required.", nameof(Symbol));

            if (string.IsNullOrWhiteSpace(Name))
                throw new ArgumentException("Name is required.", nameof(Name));

            if (Supply <= 0)
                throw new ArgumentOutOfRangeException(nameof(Supply), "Supply must be positive.");

            if (Standard == NftStandard.Urc721 && Supply != 1)
                throw new InvalidOperationException("URC721 tokens have fixed supply of 1.");

            if (MetadataByTokenId is not null && MetadataByTokenId.Count > Supply)
                throw new InvalidOperationException("Metadata entries exceed total supply.");
        }
    }

    #endregion

    #region Strategy Infrastructure

    /// <summary>
    /// Factory responsible for locating concrete minting strategies.
    /// </summary>
    public interface INftMintingStrategyFactory
    {
        INftMintingStrategy GetStrategy(NftStandard standard);
    }

    /// <summary>
    /// Basic factory implementation registered in DI.
    /// </summary>
    public sealed class NftMintingStrategyFactory : INftMintingStrategyFactory
    {
        private readonly IEnumerable<INftMintingStrategy> _strategies;

        public NftMintingStrategyFactory(IEnumerable<INftMintingStrategy> strategies)
            => _strategies = strategies;

        public INftMintingStrategy GetStrategy(NftStandard standard)
            => _strategies.FirstOrDefault(s => s.Standard == standard)
               ?? throw new NotSupportedException($"No minting strategy registered for {standard}.");
    }

    /// <summary>
    /// Strategy interface; each standard gets its own implementation.
    /// </summary>
    public interface INftMintingStrategy
    {
        NftStandard Standard { get; }
        ValueTask<NftCollection> MintAsync(NftMintRequest request, Hash128 txnId, CancellationToken ct);
    }

    /// <summary>
    /// URC-721 strategy (1 item per collection).
    /// </summary>
    public sealed class Urc721MintingStrategy : INftMintingStrategy
    {
        public NftStandard Standard => NftStandard.Urc721;

        public ValueTask<NftCollection> MintAsync(NftMintRequest request, Hash128 txnId, CancellationToken ct)
        {
            var itemId = 1;
            var itemHash = Hash128.Compute(
                request.Symbol,
                itemId.ToString(),
                request.MetadataByTokenId?.GetValueOrDefault(itemId)?.ToJson() ?? string.Empty);

            var item = new NftItem(itemId, itemHash, request.MetadataByTokenId?.GetValueOrDefault(itemId));

            var collection = new NftCollection
            {
                CollectionId = txnId,
                Symbol = request.Symbol,
                Name = request.Name,
                Description = request.Description,
                Standard = NftStandard.Urc721,
                RootHash = Hash128.Combine(itemHash),
                Owner = request.Owner,
                Items = new List<NftItem> { item }
            };

            return ValueTask.FromResult(collection);
        }
    }

    /// <summary>
    /// URC-1155 strategy (multi-token collection).
    /// </summary>
    public sealed class Urc1155MintingStrategy : INftMintingStrategy
    {
        public NftStandard Standard => NftStandard.Urc1155;

        public ValueTask<NftCollection> MintAsync(NftMintRequest request, Hash128 txnId, CancellationToken ct)
        {
            var items = new List<NftItem>(request.Supply);
            var rootHasher = new IncrementalHash128();

            for (int id = 1; id <= request.Supply; id++)
            {
                var meta = request.MetadataByTokenId?.GetValueOrDefault(id);
                var itemHash = Hash128.Compute(request.Symbol, id.ToString(), meta?.ToJson() ?? string.Empty);
                items.Add(new NftItem(id, itemHash, meta));
                rootHasher.Append(itemHash);
            }

            var collection = new NftCollection
            {
                CollectionId = txnId,
                Symbol = request.Symbol,
                Name = request.Name,
                Description = request.Description,
                Standard = NftStandard.Urc1155,
                RootHash = rootHasher.FinalizeHash(),
                Owner = request.Owner,
                Items = items
            };

            return ValueTask.FromResult(collection);
        }
    }

    #endregion

    #region Domain Entities

    // The following entities are simplified stand-ins for richer domain objects
    // defined elsewhere in UtilityChain.Core. They are duplicated here for
    // compilation purposes only and should be removed when integrating.

    public sealed record NftCollection
    {
        public required Hash128 CollectionId { get; init; }
        public required string Symbol { get; init; }
        public required string Name { get; init; }
        public string? Description { get; init; }
        public required NftStandard Standard { get; init; }
        public required Hash128 RootHash { get; init; }
        public required Address Owner { get; init; }
        public required IList<NftItem> Items { get; init; }
        public Signature? Signature { get; set; }
    }

    public sealed record NftItem(int TokenId, Hash128 Hash, IDictionary<string, object>? Metadata);

    #endregion

    #region Exceptions

    public sealed class NftMintException : Exception
    {
        public NftMintException(string message) : base(message) { }
        public NftMintException(string message, Exception inner) : base(message, inner) { }
    }

    #endregion
}

// -------------------------------------------------------------------------------------------------
// The below extension helpers and utility types would typically live in UtilityChain.Common, but
// are included here to keep the file self-contained for compilation during code-generation.
// -------------------------------------------------------------------------------------------------
namespace UtilityChain.Common
{
    using System.Security.Cryptography;
    using System.Text;
    using System.Text.Json;

    public readonly struct Hash128 : IParsable<Hash128>
    {
        private readonly Guid _value;
        private Hash128(Guid value) => _value = value;

        public static Hash128 CreateGuid() => new(Guid.NewGuid());

        public static Hash128 Compute(params string[] inputs)
            => new(Guid.NewGuid() ^ inputs.Aggregate(0, (a, s) => a ^ s.GetHashCode()));

        public static Hash128 Combine(params Hash128[] hashes)
            => new(Guid.NewGuid() ^ hashes.Aggregate(0, (a, h) => a ^ h.GetHashCode()));

        public byte[] ToByteArray() => _value.ToByteArray();
        public override string ToString() => _value.ToString("N");

        public static Hash128 Parse(string s, IFormatProvider? provider) => new(Guid.Parse(s));
        public static bool TryParse(string? s, IFormatProvider? provider, out Hash128 result)
        {
            var success = Guid.TryParse(s, out var guid);
            result = new Hash128(guid);
            return success;
        }

        public static bool operator ==(Hash128 a, Hash128 b) => a._value == b._value;
        public static bool operator !=(Hash128 a, Hash128 b) => !(a == b);
        public override bool Equals(object? obj) => obj is Hash128 other && other == this;
        public override int GetHashCode() => _value.GetHashCode();
    }

    public sealed class IncrementalHash128
    {
        private readonly List<Hash128> _parts = new();
        public void Append(Hash128 hash) => _parts.Add(hash);
        public Hash128 FinalizeHash() => Hash128.Combine(_parts.ToArray());
    }

    public static class JsonExtensions
    {
        private static readonly JsonSerializerOptions Options = new() { WriteIndented = false };

        public static string ToJson(this object obj)
            => JsonSerializer.Serialize(obj, Options);
    }

    public readonly struct Address
    {
        public static readonly Address Null = new("0x0");
        private readonly string _value;
        public Address(string value) => _value = value ?? throw new ArgumentNullException(nameof(value));
        public override string ToString() => _value;
    }

    public readonly struct Signature
    {
        private readonly byte[] _bytes;
        public Signature(byte[] bytes) => _bytes = bytes;
        public override string ToString() => Convert.ToHexString(_bytes);
    }
}

namespace UtilityChain.Common.Cryptography
{
    public interface ICryptoService
    {
        Signature Sign(byte[] data);
    }
}

namespace UtilityChain.Common.Events
{
    public interface IEventBus : IAsyncDisposable
    {
        void Publish<T>(T @event) where T : class;
    }
}

namespace UtilityChain.Persistence
{
    using System.Threading;
    using System.Threading.Tasks;
    using UtilityChain.Tokens.Domain;

    public interface INftRepository
    {
        Task<bool> CollectionExistsAsync(string symbol, CancellationToken ct);
        Task SaveAsync(NftCollection collection, CancellationToken ct);
    }
}

namespace UtilityChain.Tokens.Events
{
    using UtilityChain.Common;

    public sealed record NftMintedEvent(NftCollection Collection);
}

namespace UtilityChain.Tokens.Domain
{
    // Placeholder used by repository; already defined above but required by namespace.
}
```