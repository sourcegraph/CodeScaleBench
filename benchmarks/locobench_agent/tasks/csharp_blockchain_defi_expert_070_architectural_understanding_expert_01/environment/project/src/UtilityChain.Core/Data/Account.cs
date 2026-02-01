using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;

namespace UtilityChain.Core.Data;

/// <summary>
///     Represents a wallet or contract account on UtilityChain. 
///     The aggregate is responsible for maintaining key material, token balances, 
///     role membership, and invariants around balance transfers. 
///     All state-changes emit <see cref="AccountEvent"/>s that are dispatched to the 
///     system-wide <see cref="IEventBus"/> for eventual consistency across projections. 
/// </summary>
public sealed class Account : IEquatable<Account>, IDisposable
{
    private readonly ReaderWriterLockSlim _lock = new();
    private readonly ConcurrentDictionary<string, decimal> _tokenBalances = new(StringComparer.OrdinalIgnoreCase);

    private readonly IEventBus _eventBus;
    private readonly ILogger? _logger;

    /// <summary>Unique 160-bit address derived from the public key.</summary>
    public string Address { get; }

    /// <summary>UTC timestamp for when the account was first created on-chain.</summary>
    public DateTimeOffset CreatedUtc { get; }

    /// <summary>UTC timestamp of the most recent state change.</summary>
    public DateTimeOffset LastUpdatedUtc { get; private set; }

    /// <summary>Current nonce used for replay-protection of signed transactions.</summary>
    public long Nonce { get; private set; }

    /// <summary>
    ///     Roles granted to this account. 
    ///     Roles define elevated privileges (Validator, Treasury, Governance, etc.).
    /// </summary>
    public IImmutableSet<AccountRole> Roles => _roles.ToImmutableHashSet();
    private readonly HashSet<AccountRole> _roles = new();

    /// <summary>Public key (compressed) encoded as <c>hex</c>.</summary>
    public string PublicKeyHex => Convert.ToHexString(_publicKeySpan);
    private readonly byte[] _publicKeySpan;

    /// <summary>
    ///     Encrypted private key material, stored in PKCS#8 format. 
    ///     Protection handled by <see cref="ICryptoVault"/> – this aggregate never decrypts it directly.
    /// </summary>
    public ReadOnlyMemory<byte> EncryptedPrivateKey { get; }

    /// <summary>Indicates whether the instance has been disposed.</summary>
    [JsonIgnore]
    public bool IsDisposed => _disposed;
    private bool _disposed;

    #region Construction -----------------------------------------------------

    /// <summary>
    ///     Creates a brand-new account, generating a fresh ECDSA key-pair and deriving an address.
    ///     Private key encryption is delegated to <paramref name="cryptoVault" />.
    /// </summary>
    public static Account CreateNew(
        IEventBus eventBus,
        ICryptoVault cryptoVault,
        ILogger? logger = null,
        IEnumerable<AccountRole>? initialRoles = null,
        string? passphrase = null)
    {
        if (eventBus is null) throw new ArgumentNullException(nameof(eventBus));
        if (cryptoVault is null) throw new ArgumentNullException(nameof(cryptoVault));

        using var ecdsa = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var pubKey = ecdsa.ExportSubjectPublicKeyInfo(); // DER
        var privKey = ecdsa.ExportPkcs8PrivateKey();

        var encryptedPrivateKey = cryptoVault.EncryptPrivateKey(privKey, passphrase);

        var address = ComputeAddress(pubKey);

        var account = new Account(
            address,
            pubKey,
            encryptedPrivateKey,
            eventBus,
            logger,
            initialRoles);

        account.PublishEvent(new AccountCreatedEvent(account.Address, account.PublicKeyHex, account.CreatedUtc));
        logger?.LogInformation("Account {Address} created.", account.Address);

        return account;
    }

    [JsonConstructor]
    private Account(
        string address,
        byte[] publicKey,
        ReadOnlyMemory<byte> encryptedPrivateKey,
        IEventBus eventBus,
        ILogger? logger,
        IEnumerable<AccountRole>? initialRoles = null)
    {
        Address = address;
        _publicKeySpan = publicKey;
        EncryptedPrivateKey = encryptedPrivateKey;
        _eventBus = eventBus;
        _logger = logger;

        CreatedUtc = LastUpdatedUtc = DateTimeOffset.UtcNow;
        Nonce = 0;

        if (initialRoles != null)
            _roles.UnionWith(initialRoles);
    }

    #endregion

    #region Balance Operations ----------------------------------------------

    /// <summary>Returns the current balance for the supplied token symbol.</summary>
    public decimal GetBalance(string symbol) =>
        _tokenBalances.TryGetValue(symbol, out var bal) ? bal : 0m;

    /// <summary>
    ///     Adjusts the balance atomically. Positive amounts credit, negatives debit. 
    ///     Throws if result would be negative.
    /// </summary>
    public void MutateBalance(string symbol, decimal amount, string? reason = null)
    {
        if (string.IsNullOrWhiteSpace(symbol))
            throw new ArgumentException("Token symbol is required.", nameof(symbol));

        _lock.EnterWriteLock();
        try
        {
            var existing = _tokenBalances.TryGetValue(symbol, out var bal) ? bal : 0m;
            var updated = existing + amount;

            if (updated < 0m)
                throw new InvalidOperationException($"Insufficient {symbol} balance: {existing}.");

            _tokenBalances[symbol] = updated;
            LastUpdatedUtc = DateTimeOffset.UtcNow;

            PublishEvent(new BalanceChangedEvent(Address, symbol, existing, updated, reason));
            _logger?.LogDebug(
                CultureInfo.InvariantCulture,
                "Account {Address} balance for {Symbol} changed from {Old} to {New}. {Reason}",
                Address, symbol, existing, updated, reason ?? string.Empty);
        }
        finally
        {
            _lock.ExitWriteLock();
        }
    }

    #endregion

    #region Role Management --------------------------------------------------

    public bool HasRole(AccountRole role) => _roles.Contains(role);

    /// <summary>Grants the specified role to the account, idempotent.</summary>
    public void GrantRole(AccountRole role, string? grantedBy = null)
    {
        _lock.EnterWriteLock();
        try
        {
            if (_roles.Add(role))
            {
                LastUpdatedUtc = DateTimeOffset.UtcNow;
                PublishEvent(new RoleGrantedEvent(Address, role, grantedBy));
                _logger?.LogInformation("Role {Role} granted to {Address} by {GrantedBy}.",
                    role, Address, grantedBy ?? "system");
            }
        }
        finally
        {
            _lock.ExitWriteLock();
        }
    }

    /// <summary>Revokes the specified role from the account, idempotent.</summary>
    public void RevokeRole(AccountRole role, string? revokedBy = null)
    {
        _lock.EnterWriteLock();
        try
        {
            if (_roles.Remove(role))
            {
                LastUpdatedUtc = DateTimeOffset.UtcNow;
                PublishEvent(new RoleRevokedEvent(Address, role, revokedBy));
                _logger?.LogInformation("Role {Role} revoked from {Address} by {RevokedBy}.",
                    role, Address, revokedBy ?? "system");
            }
        }
        finally
        {
            _lock.ExitWriteLock();
        }
    }

    #endregion

    #region Nonce ------------------------------------------------------------

    /// <summary>
    ///     Atomically increments the nonce and returns the pre-increment value.
    ///     This is used during transaction signing to enforce order and replay-protection.
    /// </summary>
    public long ConsumeNonce() => Interlocked.Increment(ref Nonce) - 1;

    #endregion

    #region Serialization ----------------------------------------------------

    /// <summary>Returns a deterministic, canonical JSON representation.</summary>
    public string ToJson() =>
        JsonSerializer.Serialize(this, AccountJsonContext.Default.Account);

    public static Account FromJson(
        string json,
        IEventBus eventBus,
        ILogger? logger,
        ICryptoVault vault)
    {
        var snapshot = JsonSerializer.Deserialize(json, AccountJsonContext.Default.AccountSnapshot)
                       ?? throw new InvalidOperationException("Malformed account JSON.");

        return new Account(
            snapshot.Address,
            snapshot.PublicKey,
            vault.ImportEncryptedKey(snapshot.EncryptedPrivateKey),
            eventBus,
            logger,
            snapshot.Roles);
    }

    #endregion

    #region Equality / Hash --------------------------------------------------

    public bool Equals(Account? other) =>
        other is not null && ReferenceEquals(this, other) || Address.Equals(other?.Address, StringComparison.Ordinal);

    public override bool Equals(object? obj) => Equals(obj as Account);

    public override int GetHashCode() => Address.GetHashCode(StringComparison.Ordinal);

    #endregion

    #region Helpers ----------------------------------------------------------

    private void PublishEvent(AccountEvent @event) => _eventBus.Publish(@event);

    private static string ComputeAddress(byte[] publicKeyInfo)
    {
        // Simple address scheme: addr = RIPEMD160(SHA256(pubKey)).Hex
        using var sha256 = SHA256.Create();
        var sha = sha256.ComputeHash(publicKeyInfo);

        using var ripemd = RIPEMD160.Create();
        var ripe = ripemd.ComputeHash(sha);

        // Prefix "0x" for readability
        return "0x" + Convert.ToHexString(ripe);
    }

    #endregion

    #region IDisposable ------------------------------------------------------

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _lock.Dispose();
        GC.SuppressFinalize(this);
    }

    #endregion
}

#region Supporting Types -----------------------------------------------------

/// <summary>Assigned roles for privilege escalation.</summary>
public enum AccountRole
{
    None = 0,
    Validator,
    Treasury,
    Governance,
    Auditor,
    System
}

/// <summary>Interface for dispatching domain events within the monolith.</summary>
public interface IEventBus
{
    void Publish<TEvent>(TEvent @event) where TEvent : notnull;
}

/// <summary>
///     Interface that abstracts encryption/decryption of private keys.
///     Different vault providers (DPAPI, Azure Key Vault, HSM, etc.) can implement this.
/// </summary>
public interface ICryptoVault
{
    ReadOnlyMemory<byte> EncryptPrivateKey(ReadOnlySpan<byte> pkcs8, string? passphrase);
    ReadOnlyMemory<byte> ImportEncryptedKey(ReadOnlyMemory<byte> encrypted);
}

/// <summary>Logging abstraction (identical subset of Microsoft.Extensions.Logging).</summary>
public interface ILogger
{
    void LogDebug(string message, params object[] parameters);
    void LogInformation(string message, params object[] parameters);
}

#region Events

[JsonPolymorphic(TypeDiscriminatorPropertyName = "$type")]
[JsonDerivedType(typeof(AccountCreatedEvent), "created")]
[JsonDerivedType(typeof(BalanceChangedEvent), "balance-changed")]
[JsonDerivedType(typeof(RoleGrantedEvent), "role-granted")]
[JsonDerivedType(typeof(RoleRevokedEvent), "role-revoked")]
public abstract record AccountEvent(string Address, DateTimeOffset AtUtc);

public sealed record AccountCreatedEvent(
    string Address,
    string PubKey,
    DateTimeOffset AtUtc) : AccountEvent(Address, AtUtc);

public sealed record BalanceChangedEvent(
    string Address,
    string Token,
    decimal OldBalance,
    decimal NewBalance,
    string? Reason) : AccountEvent(Address, DateTimeOffset.UtcNow);

public sealed record RoleGrantedEvent(
    string Address,
    AccountRole Role,
    string? GrantedBy) : AccountEvent(Address, DateTimeOffset.UtcNow);

public sealed record RoleRevokedEvent(
    string Address,
    AccountRole Role,
    string? RevokedBy) : AccountEvent(Address, DateTimeOffset.UtcNow);

#endregion

#region JSON Context --------------------------------------------------------

[JsonSerializable(typeof(Account))]
[JsonSerializable(typeof(AccountSnapshot))]
[JsonSourceGenerationOptions(
    PropertyNamingPolicy = JsonKnownNamingPolicy.CamelCase,
    WriteIndented = false)]
internal partial class AccountJsonContext : JsonSerializerContext;

/// <summary>
///     Snapshot used only for (de)serialization to decouple domain invariants from wire format.
/// </summary>
internal sealed class AccountSnapshot
{
    public string Address { get; init; } = default!;
    public byte[] PublicKey { get; init; } = default!;
    public ReadOnlyMemory<byte> EncryptedPrivateKey { get; init; }
    public IEnumerable<AccountRole> Roles { get; init; } = Enumerable.Empty<AccountRole>();
}

#endregion

#endregion