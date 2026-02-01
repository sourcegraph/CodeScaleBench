```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="KeyStore.cs" company="UtilityChain">
//   © UtilityChain Core Suite – All Rights Reserved
//   Unauthorized copying of this file, via any medium is strictly prohibited.
//   Proprietary and confidential.
// </copyright>
// <summary>
//   A production-grade keystore for UtilityChain’s lightweight desktop wallet. 
//   Manages creation, import, encryption, decryption, and persistence of asymmetric key pairs.
//   Implements observable events so that UI components or services can react to state changes.
// </summary>
// --------------------------------------------------------------------------------------------------------------------

using System;
using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.IO;
using System.Linq;
using System.Reactive.Subjects;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace UtilityChain.Wallet
{
    /// <summary>
    /// Raised whenever the keystore mutates.
    /// </summary>
    public enum KeyStoreEventType
    {
        KeyAdded,
        KeyRemoved,
        KeyUnlocked,
        KeyLocked,
        Persisted
    }

    public sealed record KeyStoreEvent(KeyStoreEventType Type, string Address);

    /// <summary>
    /// A strongly encrypted keystore suitable for hot-wallet usage.  
    /// Uses PBKDF2 for key derivation and AES-GCM for authenticated encryption.
    /// </summary>
    public sealed class KeyStore : IObservable<KeyStoreEvent>, IDisposable
    {
        private const int SaltSize    = 16;   // 128-bit salt for PBKDF2
        private const int KeySize     = 32;   // 256-bit AES key
        private const int NonceSize   = 12;   // 96-bit nonce for GCM
        private const int TagSize     = 16;   // 128-bit auth tag
        private const int Pbkdf2Iter  = 100_000;

        // Persisted data container
        private sealed record KeyEntry(
            string Address,
            string PublicKey,
            byte[] EncryptedPrivateKey, // cipher text || tag (tag appended)
            byte[] Salt,
            byte[] Nonce,
            DateTimeOffset CreatedUtc);

        // In-memory unlocked key cache
        private readonly ConcurrentDictionary<string, byte[]> _unlockedPrivKeys = new(StringComparer.OrdinalIgnoreCase);

        // Persistent storage
        private readonly ConcurrentDictionary<string, KeyEntry> _entries = new(StringComparer.OrdinalIgnoreCase);

        private readonly string _filePath;
        private readonly SemaphoreSlim _fileLock = new(1, 1);
        private readonly Subject<KeyStoreEvent> _subject = new();

        private readonly JsonSerializerOptions _jsonOpts = new()
        {
            WriteIndented = false,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
        };

        private bool _disposed;

        #region Factory

        public static async Task<KeyStore> LoadOrCreateAsync(string filePath, CancellationToken ct = default)
        {
            var ks = new KeyStore(filePath);
            if (File.Exists(filePath))
            {
                await ks.RestoreAsync(ct).ConfigureAwait(false);
            }
            else
            {
                await ks.PersistAsync(ct).ConfigureAwait(false); // create empty file
            }
            return ks;
        }

        private KeyStore(string filePath)
        {
            _filePath = filePath ?? throw new ArgumentNullException(nameof(filePath));
        }

        #endregion

        #region Public API

        /// <summary>
        /// Creates a new asymmetric key pair and persists it encrypted with the provided passphrase.
        /// </summary>
        /// <param name="passphrase">User-supplied passphrase. Will be cleared after use.</param>
        public async Task<string> CreateAsync(ReadOnlyMemory<char> passphrase, CancellationToken ct = default)
        {
            EnsureNotDisposed();

            var (pub, priv) = GenerateKeyPair();
            var address     = DeriveAddress(pub);

            var entry = EncryptPrivateKey(address, pub, priv, passphrase.Span);

            if (!_entries.TryAdd(address, entry))
                throw new InvalidOperationException("Address already exists in keystore.");

            // unlock in memory
            _unlockedPrivKeys[address] = priv;

            await PersistAsync(ct).ConfigureAwait(false);

            _subject.OnNext(new KeyStoreEvent(KeyStoreEventType.KeyAdded, address));
            _subject.OnNext(new KeyStoreEvent(KeyStoreEventType.KeyUnlocked, address));
            return address;
        }

        /// <summary>
        /// Imports a raw private key into the keystore.
        /// </summary>
        public async Task<string> ImportAsync(ReadOnlyMemory<byte> privateKey, ReadOnlyMemory<char> passphrase, CancellationToken ct = default)
        {
            EnsureNotDisposed();

            if (privateKey.IsEmpty)   throw new ArgumentException("Private key cannot be empty.", nameof(privateKey));
            if (passphrase.IsEmpty)   throw new ArgumentException("Passphrase cannot be empty.", nameof(passphrase));

            var (pub, privCopy) = DerivePublicKey(privateKey);
            var address         = DeriveAddress(pub);

            var entry = EncryptPrivateKey(address, pub, privCopy, passphrase.Span);

            if (!_entries.TryAdd(address, entry))
                throw new InvalidOperationException("Address already exists in keystore.");

            ClearPrivKey(ref privCopy);

            await PersistAsync(ct).ConfigureAwait(false);

            _subject.OnNext(new KeyStoreEvent(KeyStoreEventType.KeyAdded, address));
            return address;
        }

        /// <summary>
        /// Unlocks and returns the private key for the specified address.
        /// </summary>
        public byte[] Unlock(string address, ReadOnlyMemory<char> passphrase)
        {
            EnsureNotDisposed();
            address = Normalize(address);

            if (_unlockedPrivKeys.TryGetValue(address, out var cached))
            {
                return cached.ToArray(); // return copy
            }

            if (!_entries.TryGetValue(address, out var entry))
                throw new KeyNotFoundException($"Address '{address}' not present in keystore.");

            var plaintext = Decrypt(entry, passphrase.Span);
            _unlockedPrivKeys[address] = plaintext.ToArray(); // cache a copy

            _subject.OnNext(new KeyStoreEvent(KeyStoreEventType.KeyUnlocked, address));
            return plaintext;
        }

        /// <summary>
        /// Removes a key from the unlocked cache.  Does not affect disk.
        /// </summary>
        public void Lock(string address)
        {
            EnsureNotDisposed();
            if (string.IsNullOrWhiteSpace(address)) return;

            address = Normalize(address);
            if (_unlockedPrivKeys.TryRemove(address, out var priv))
                ClearPrivKey(ref priv);

            _subject.OnNext(new KeyStoreEvent(KeyStoreEventType.KeyLocked, address));
        }

        /// <summary>
        /// Permanently deletes key pair from disk.
        /// </summary>
        public async Task DeleteAsync(string address, CancellationToken ct = default)
        {
            EnsureNotDisposed();
            address = Normalize(address);

            if (!_entries.TryRemove(address, out var removed))
                throw new KeyNotFoundException($"Address '{address}' not present in keystore.");

            if (_unlockedPrivKeys.TryRemove(address, out var priv))
                ClearPrivKey(ref priv);

            await PersistAsync(ct).ConfigureAwait(false);
            _subject.OnNext(new KeyStoreEvent(KeyStoreEventType.KeyRemoved, address));
        }

        /// <summary>
        /// Returns immutable snapshot of wallet addresses known to the keystore.
        /// </summary>
        public ImmutableArray<string> ListAddresses()
        {
            EnsureNotDisposed();
            return _entries.Keys.Order().ToImmutableArray();
        }

        #endregion

        #region Persistence

        private async Task PersistAsync(CancellationToken ct)
        {
            await _fileLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                using var fs = new FileStream(_filePath, FileMode.Create, FileAccess.Write, FileShare.None, 4096, true);
                await JsonSerializer.SerializeAsync(fs, _entries.Values, _jsonOpts, ct).ConfigureAwait(false);
            }
            finally
            {
                _fileLock.Release();
            }

            _subject.OnNext(new KeyStoreEvent(KeyStoreEventType.Persisted, string.Empty));
        }

        private async Task RestoreAsync(CancellationToken ct)
        {
            await _fileLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                var json = await File.ReadAllTextAsync(_filePath, ct).ConfigureAwait(false);
                if (string.IsNullOrWhiteSpace(json)) return;

                var entries = JsonSerializer.Deserialize<IEnumerable<KeyEntry>>(json, _jsonOpts) ?? Enumerable.Empty<KeyEntry>();
                foreach (var e in entries)
                {
                    _entries[e.Address] = e;
                }
            }
            finally
            {
                _fileLock.Release();
            }
        }

        #endregion

        #region Encryption Helpers

        private static KeyEntry EncryptPrivateKey(string address, string publicKey, byte[] privateKey, ReadOnlySpan<char> passphrase)
        {
            var salt = RandomNumberGenerator.GetBytes(SaltSize);
            using var pbkdf2 = new Rfc2898DeriveBytes(passphrase.ToArray(), salt, Pbkdf2Iter, HashAlgorithmName.SHA256);
            var aesKey = pbkdf2.GetBytes(KeySize);

            var nonce   = RandomNumberGenerator.GetBytes(NonceSize);
            var cipher  = new byte[privateKey.Length];
            var tagBuf  = new byte[TagSize];

            using (var aes = new AesGcm(aesKey))
            {
                aes.Encrypt(nonce, privateKey, cipher, tagBuf);
            }

            var encryptedConcat = new byte[cipher.Length + tagBuf.Length];
            Buffer.BlockCopy(cipher, 0, encryptedConcat, 0, cipher.Length);
            Buffer.BlockCopy(tagBuf, 0, encryptedConcat, cipher.Length, tagBuf.Length);

            ClearPrivKey(ref aesKey);

            return new KeyEntry(
                Address: address,
                PublicKey: publicKey,
                EncryptedPrivateKey: encryptedConcat,
                Salt: salt,
                Nonce: nonce,
                CreatedUtc: DateTimeOffset.UtcNow);
        }

        private static byte[] Decrypt(KeyEntry entry, ReadOnlySpan<char> passphrase)
        {
            var cipherLen = entry.EncryptedPrivateKey.Length - TagSize;
            var cipher = entry.EncryptedPrivateKey.AsSpan(0, cipherLen);
            var tag    = entry.EncryptedPrivateKey.AsSpan(cipherLen, TagSize);

            using var pbkdf2 = new Rfc2898DeriveBytes(passphrase.ToArray(), entry.Salt, Pbkdf2Iter, HashAlgorithmName.SHA256);
            var aesKey = pbkdf2.GetBytes(KeySize);

            var plaintext = new byte[cipherLen];
            try
            {
                using var aes = new AesGcm(aesKey);
                aes.Decrypt(entry.Nonce, cipher, tag, plaintext);
            }
            catch (CryptographicException)
            {
                ClearPrivKey(ref aesKey);
                ArrayPool<byte>.Shared.Return(plaintext);
                throw new UnauthorizedAccessException("Invalid passphrase.");
            }

            ClearPrivKey(ref aesKey);
            return plaintext;
        }

        #endregion

        #region Key Generation Helpers

        private static (string PublicKey, byte[] PrivateKey) GenerateKeyPair()
        {
            using var ecdsa = ECDsa.Create(ECCurve.NamedCurves.nistP256);
            var privKey = ecdsa.ExportECPrivateKey();
            var pubKey  = Convert.ToHexString(ecdsa.ExportSubjectPublicKeyInfo());
            return (pubKey, privKey);
        }

        private static (string PublicKey, byte[] PrivateKey) DerivePublicKey(ReadOnlyMemory<byte> privKey)
        {
            using var ecdsa = ECDsa.Create();
            ecdsa.ImportECPrivateKey(privKey.Span, out _);
            var pubKey = Convert.ToHexString(ecdsa.ExportSubjectPublicKeyInfo());
            return (pubKey, privKey.ToArray());
        }

        private static string DeriveAddress(string publicKeyHex)
        {
            using var sha = SHA256.Create();
            var hash = sha.ComputeHash(Convert.FromHexString(publicKeyHex));
            // Take last 20 bytes (similar to Ethereum) and prefix with "UC"
            return "UC" + Convert.ToHexString(hash[^20..]).ToLowerInvariant();
        }

        #endregion

        #region IObservable Implementation

        public IDisposable Subscribe(IObserver<KeyStoreEvent> observer)
        {
            return _subject.Subscribe(observer);
        }

        #endregion

        #region Utils 

        private static string Normalize(string address) => address?.Trim().ToLowerInvariant() ?? string.Empty;

        private static void ClearPrivKey(ref byte[]? key)
        {
            if (key is null) return;
            CryptographicOperations.ZeroMemory(key);
            key = null!;
        }

        private void EnsureNotDisposed()
        {
            if (_disposed) throw new ObjectDisposedException(nameof(KeyStore));
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            foreach (var (_, priv) in _unlockedPrivKeys)
            {
                ClearPrivKey(ref priv);
            }

            _subject.OnCompleted();
            _subject.Dispose();
            _fileLock.Dispose();
        }

        #endregion
    }
}
```