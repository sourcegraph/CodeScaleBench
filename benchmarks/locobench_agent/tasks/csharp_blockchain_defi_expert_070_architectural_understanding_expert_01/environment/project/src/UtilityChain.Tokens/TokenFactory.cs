```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="TokenFactory.cs" company="UtilityChain">
//   Copyright (c) UtilityChain. 
//   This source code is licensed under the MIT license that can be found in the LICENSE file.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace UtilityChain.Tokens;

/// <summary>
/// Creates <see cref="IToken"/> instances based on a registered <see cref="ITokenBuilder"/> implementation.
/// Acts as a central registry for token standards and guarantees that token creation is thread-safe and
/// symbol-unique within the current node runtime.
/// </summary>
public sealed class TokenFactory
{
    #region Singleton

    private static readonly Lazy<TokenFactory> _instance = new(() => new TokenFactory());

    /// <summary>Gets the singleton instance.</summary>
    public static TokenFactory Instance => _instance.Value;

    #endregion

    private readonly ConcurrentDictionary<TokenStandard, ITokenBuilder> _builders = new();
    private readonly ITokenRegistry _registry;

    /// <summary>
    /// Occurs when a new token has been created.
    /// </summary>
    public event EventHandler<TokenCreatedEventArgs>? TokenCreated;

    private TokenFactory()
        : this(new InMemoryTokenRegistry())
    {
    }

    internal TokenFactory(ITokenRegistry registry)
    {
        _registry = registry ?? throw new ArgumentNullException(nameof(registry));

        // Register built-in standards.
        RegisterBuilder(TokenStandard.Fungible, new FungibleTokenBuilder());
        RegisterBuilder(TokenStandard.NonFungible, new NonFungibleTokenBuilder());
    }

    /// <summary>
    /// Registers a token builder for a given standard.
    /// </summary>
    /// <param name="standard">The token standard.</param>
    /// <param name="builder">Concrete builder implementation.</param>
    /// <param name="override">When true, replaces an existing builder.</param>
    /// <exception cref="ArgumentNullException"/>
    /// <exception cref="InvalidOperationException"/>
    public void RegisterBuilder(TokenStandard standard, ITokenBuilder builder, bool @override = false)
    {
        ArgumentNullException.ThrowIfNull(builder);

        if (!_builders.TryAdd(standard, builder) && !@override)
        {
            throw new InvalidOperationException($"Builder for standard '{standard}' already exists.");
        }

        if (@override)
        {
            _builders[standard] = builder;
        }
    }

    /// <summary>
    /// Creates a token according to the specified <see cref="TokenStandard"/> and <see cref="TokenCreationOptions"/>.
    /// </summary>
    /// <exception cref="ArgumentException">Thrown if the token symbol is already registered.</exception>
    /// <exception cref="KeyNotFoundException">Thrown if no builder exists for the requested standard.</exception>
    public async Task<IToken> CreateTokenAsync(
        TokenStandard standard,
        TokenCreationOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        if (!_builders.TryGetValue(standard, out var builder))
        {
            throw new KeyNotFoundException($"No builder registered for standard: {standard}");
        }

        // Ensure symbol uniqueness across the node
        if (!_registry.TryRegisterSymbol(options.Symbol))
        {
            throw new ArgumentException(
                $"Token symbol '{options.Symbol}' is already registered.",
                nameof(options));
        }

        // Delegate the build process
        var token = await builder.BuildAsync(options, cancellationToken).ConfigureAwait(false);

        // Publish event
        TokenCreated?.Invoke(this, new TokenCreatedEventArgs(token));

        return token;
    }
}

#region Supporting Contracts

/// <summary>Represents a blockchain token.</summary>
public interface IToken
{
    string Name { get; }
    string Symbol { get; }
    TokenStandard Standard { get; }
    string ContractAddress { get; }
}

/// <summary>Defines a strategy used by <see cref="TokenFactory"/> to create tokens.</summary>
public interface ITokenBuilder
{
    Task<IToken> BuildAsync(TokenCreationOptions options, CancellationToken cancellationToken = default);
}

/// <summary>
/// Maintains a registry of token symbols to prevent duplicate creation within the current process.
/// In a multi-node deployment additional chain-wide checks should be performed.
/// </summary>
public interface ITokenRegistry
{
    bool TryRegisterSymbol(string symbol);
    bool ContainsSymbol(string symbol);
}

/// <summary>
/// Provides immutable creation parameters for new tokens.
/// </summary>
public sealed record TokenCreationOptions(
    string Name,
    string Symbol,
    string OwnerAddress,
    BigInteger InitialSupply = default,
    byte Decimals = 18,
    IReadOnlyDictionary<string, string>? Metadata = null
)
{
    public string Name { get; init; } = Name.Trim();
    public string Symbol { get; init; } = Symbol.Trim().ToUpperInvariant();
    public string OwnerAddress { get; init; } = OwnerAddress;

    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(Name))
            throw new ArgumentException("Token name must be provided.", nameof(Name));

        if (string.IsNullOrWhiteSpace(Symbol))
            throw new ArgumentException("Token symbol must be provided.", nameof(Symbol));

        if (Symbol.Length > 8)
            throw new ArgumentException("Token symbol cannot exceed 8 characters.", nameof(Symbol));

        if (string.IsNullOrWhiteSpace(OwnerAddress))
            throw new ArgumentException("Owner address must be provided.", nameof(OwnerAddress));

        if (InitialSupply < 0)
            throw new ArgumentException("Initial supply cannot be negative.", nameof(InitialSupply));
    }
}

/// <summary>Supported token standards in UtilityChain.</summary>
public enum TokenStandard
{
    Fungible = 1,      // e.g., ERC-20-like
    NonFungible = 2,   // e.g., ERC-721-like
    // Governor = 3,   // Future extension
}

#endregion

#region Builder Implementations

internal sealed class FungibleTokenBuilder : ITokenBuilder
{
    public Task<IToken> BuildAsync(TokenCreationOptions options, CancellationToken cancellationToken = default)
    {
        options.Validate();

        // Compute deterministic contract address derived from input parameters
        var contractAddress = DeriveContractAddress(options, TokenStandard.Fungible);

        var token = new FungibleToken(
            options.Name,
            options.Symbol,
            options.Decimals,
            options.InitialSupply,
            contractAddress,
            options.OwnerAddress,
            options.Metadata);

        // TODO: Persist token definition to state store or chain.
        return Task.FromResult<IToken>(token);
    }

    private static string DeriveContractAddress(TokenCreationOptions opts, TokenStandard standard)
    {
        using var sha256 = SHA256.Create();
        var bytes = Encoding.UTF8.GetBytes(
            $"{opts.Symbol}|{opts.OwnerAddress}|{standard}|{opts.InitialSupply}|{opts.Decimals}");
        var hash = sha256.ComputeHash(bytes);
        return $"0x{Convert.ToHexString(hash[..20])}";
    }
}

internal sealed class NonFungibleTokenBuilder : ITokenBuilder
{
    public Task<IToken> BuildAsync(TokenCreationOptions options, CancellationToken cancellationToken = default)
    {
        options.Validate();

        var contractAddress = DeriveContractAddress(options, TokenStandard.NonFungible);

        var token = new NonFungibleToken(
            options.Name,
            options.Symbol,
            contractAddress,
            options.OwnerAddress,
            options.Metadata);

        // TODO: Persist token definition to state store or chain.
        return Task.FromResult<IToken>(token);
    }

    private static string DeriveContractAddress(TokenCreationOptions opts, TokenStandard standard)
    {
        using var sha256 = SHA256.Create();
        var bytes = Encoding.UTF8.GetBytes($"{opts.Symbol}|{opts.OwnerAddress}|{standard}");
        var hash = sha256.ComputeHash(bytes);
        return $"0x{Convert.ToHexString(hash[..20])}";
    }
}

#endregion

#region Token Implementations

/// <summary>An ERC-20-like fungible token implementation.</summary>
internal sealed class FungibleToken : IToken
{
    public FungibleToken(
        string name,
        string symbol,
        byte decimals,
        BigInteger initialSupply,
        string contractAddress,
        string ownerAddress,
        IReadOnlyDictionary<string, string>? metadata)
    {
        Name = name;
        Symbol = symbol;
        Decimals = decimals;
        TotalSupply = initialSupply;
        ContractAddress = contractAddress;
        OwnerAddress = ownerAddress;
        Metadata = metadata ?? new Dictionary<string, string>();
    }

    public string Name { get; }
    public string Symbol { get; }
    public TokenStandard Standard => TokenStandard.Fungible;
    public byte Decimals { get; }
    public BigInteger TotalSupply { get; private set; }
    public string ContractAddress { get; }
    public string OwnerAddress { get; }
    public IReadOnlyDictionary<string, string> Metadata { get; }

    // In a real implementation, balances would be kept in state store.
    private readonly ConcurrentDictionary<string, BigInteger> _balances = new();

    public BigInteger BalanceOf(string address) =>
        _balances.TryGetValue(address, out var balance) ? balance : BigInteger.Zero;

    public void Mint(string to, BigInteger amount)
    {
        if (amount <= 0) throw new ArgumentException("Mint amount must be positive.", nameof(amount));

        _balances.AddOrUpdate(to, amount, (_, current) => current + amount);
        TotalSupply += amount;
    }

    public void Burn(string from, BigInteger amount)
    {
        if (!_balances.TryGetValue(from, out var balance) || balance < amount)
            throw new InvalidOperationException("Insufficient balance to burn.");

        _balances[from] = balance - amount;
        TotalSupply -= amount;
    }
}

/// <summary>An ERC-721-like non-fungible token implementation.</summary>
internal sealed class NonFungibleToken : IToken
{
    public NonFungibleToken(
        string name,
        string symbol,
        string contractAddress,
        string ownerAddress,
        IReadOnlyDictionary<string, string>? metadata)
    {
        Name = name;
        Symbol = symbol;
        ContractAddress = contractAddress;
        OwnerAddress = ownerAddress;
        Metadata = metadata ?? new Dictionary<string, string>();
    }

    public string Name { get; }
    public string Symbol { get; }
    public TokenStandard Standard => TokenStandard.NonFungible;
    public string ContractAddress { get; }
    public string OwnerAddress { get; }
    public IReadOnlyDictionary<string, string> Metadata { get; }

    // Maps tokenId -> ownerAddress
    private readonly ConcurrentDictionary<Guid, string> _owners = new();

    public Guid Mint(string to)
    {
        var tokenId = Guid.NewGuid();
        _owners[tokenId] = to;
        return tokenId;
    }

    public void Transfer(Guid tokenId, string from, string to)
    {
        if (!_owners.TryGetValue(tokenId, out var currentOwner) || currentOwner != from)
            throw new InvalidOperationException("Token does not belong to 'from' address.");

        _owners[tokenId] = to;
    }

    public string OwnerOf(Guid tokenId) =>
        _owners.TryGetValue(tokenId, out var owner)
            ? owner
            : throw new KeyNotFoundException("Token ID does not exist.");
}

#endregion

#region Registry & Events

/// <summary>
/// Thread-safe in-memory implementation of <see cref="ITokenRegistry"/> suitable for single-node scenarios.
/// </summary>
internal sealed class InMemoryTokenRegistry : ITokenRegistry
{
    private readonly ConcurrentDictionary<string, byte> _symbols = new(StringComparer.OrdinalIgnoreCase);

    public bool TryRegisterSymbol(string symbol)
        => _symbols.TryAdd(symbol, 0);

    public bool ContainsSymbol(string symbol)
        => _symbols.ContainsKey(symbol);
}

/// <summary>Event data for token creation notifications.</summary>
public sealed class TokenCreatedEventArgs : EventArgs
{
    public TokenCreatedEventArgs(IToken token) => Token = token;
    public IToken Token { get; }
}

#endregion
```