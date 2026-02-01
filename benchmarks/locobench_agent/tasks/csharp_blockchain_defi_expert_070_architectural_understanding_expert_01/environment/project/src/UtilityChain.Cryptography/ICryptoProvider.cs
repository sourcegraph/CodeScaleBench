```csharp
// -----------------------------------------------------------------------------
// UtilityChain Core Suite
// (c) 2024 UtilityChain Contributors – MIT License
// -----------------------------------------------------------------------------
// File:    ICryptoProvider.cs
// Project: UtilityChain.Cryptography
// Purpose: Central abstraction for all cryptographic operations used by the
//          UtilityChain monolith.  Every concrete implementation *must* be fully
//          deterministic, thread-safe, and side-channel resistant.
// -----------------------------------------------------------------------------

using System;
using System.Buffers;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;

namespace UtilityChain.Cryptography
{
    #region Enumerations

    /// <summary>
    /// Supported asymmetric signature algorithms.
    /// </summary>
    public enum SignatureAlgorithm
    {
        EcdsaSecp256K1,
        Ed25519,
        Bls12381G2, // BLS 12-381 G2 curve – used in consensus module.
    }

    /// <summary>
    /// Supported hashing algorithms throughout the code-base.
    /// </summary>
    public enum HashAlgorithmType
    {
        Sha256,
        Sha3_256,
        Blake2B,
    }

    /// <summary>
    /// Symmetric authenticated-encryption algorithms.
    /// </summary>
    public enum AeadAlgorithm
    {
        Aes256Gcm,
        ChaCha20Poly1305
    }

    /// <summary>
    /// Describes the high-level purpose a key is generated for.
    /// </summary>
    public enum KeyPurpose
    {
        Signing,
        Encryption,
        Both
    }

    #endregion

    #region Crypto Primitives

    /// <summary>
    /// Wrapper around a public key byte buffer.
    /// </summary>
    public readonly record struct PublicKey
    {
        public ReadOnlyMemory<byte> Bytes { get; }

        public PublicKey(ReadOnlyMemory<byte> bytes)
        {
            if (bytes.IsEmpty) throw new ArgumentException("PublicKey cannot be empty.", nameof(bytes));
            Bytes = bytes;
        }

        public override string ToString() => Convert.ToHexString(Bytes.Span);
    }

    /// <summary>
    /// Wrapper around a private key byte buffer. Implements <see cref="IDisposable"/>
    /// so that callers can intentionally wipe key material from memory.
    /// </summary>
    public sealed class PrivateKey : IDisposable
    {
        private IMemoryOwner<byte>? _owner;

        public Memory<byte> Bytes => _owner?.Memory ?? Memory<byte>.Empty;

        public PrivateKey(IMemoryOwner<byte> owner)
        {
            _owner = owner ?? throw new ArgumentNullException(nameof(owner));
        }

        public void Dispose()
        {
            if (_owner != null)
            {
                // Zero-out in-memory copy to mitigate key leakage.
                Bytes.Span.Clear();
                _owner.Dispose();
                _owner = null;
            }

            GC.SuppressFinalize(this);
        }
    }

    /// <summary>
    /// Key pair record.
    /// </summary>
    /// <param name="PublicKey">Public component.</param>
    /// <param name="PrivateKey">Private component.</param>
    public readonly record struct KeyPair(PublicKey PublicKey, PrivateKey PrivateKey);

    /// <summary>
    /// Symmetric key record – always wraps keying material in memory owner
    /// to facilitate secure zeroisation.
    /// </summary>
    public sealed class SymmetricKey : IDisposable
    {
        private IMemoryOwner<byte>? _owner;

        public Memory<byte> Bytes => _owner?.Memory ?? Memory<byte>.Empty;

        public SymmetricKey(IMemoryOwner<byte> owner)
        {
            _owner = owner ?? throw new ArgumentNullException(nameof(owner));
        }

        public void Dispose()
        {
            if (_owner != null)
            {
                Bytes.Span.Clear();
                _owner.Dispose();
                _owner = null;
            }
            GC.SuppressFinalize(this);
        }
    }

    /// <summary>
    /// User-supplied parameters controlling asymmetric key generation.
    /// </summary>
    public sealed record KeyGenerationParameters(
        SignatureAlgorithm Algorithm,
        KeyPurpose Purpose,
        bool Exportable);

    #endregion

    #region Interface

    /// <summary>
    /// Abstraction layer for all cryptographic primitives used in UtilityChain.
    /// Implementations may leverage OS-provided APIs, managed/unsafe code, or
    /// hardware modules (HSM, TPM) – but must strictly follow functional
    /// behaviour defined here.
    /// </summary>
    public interface ICryptoProvider
    {
        // ---------------------------------------------------------------------
        // Asymmetric Operations
        // ---------------------------------------------------------------------

        /// <summary>
        /// Generates a cryptographically secure key pair.
        /// </summary>
        /// <param name="parameters">Specification of algorithm and usage.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <returns>Generated key pair.</returns>
        Task<KeyPair> GenerateKeyPairAsync(
            KeyGenerationParameters parameters,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Signs data with the provided private key.
        /// </summary>
        /// <param name="data">Data to sign.</param>
        /// <param name="privateKey">Private key.</param>
        /// <param name="algorithm">Algorithm to use (must match key type).</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <returns>Detached signature bytes.</returns>
        Task<byte[]> SignAsync(
            ReadOnlyMemory<byte> data,
            PrivateKey privateKey,
            SignatureAlgorithm algorithm,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Verifies a detached signature.
        /// </summary>
        /// <param name="data">Signed data.</param>
        /// <param name="signature">Signature bytes.</param>
        /// <param name="publicKey">Signing public key.</param>
        /// <param name="algorithm">Algorithm to use.</param>
        /// <returns>True if signature is valid; otherwise false.</returns>
        bool Verify(
            ReadOnlyMemory<byte> data,
            ReadOnlyMemory<byte> signature,
            PublicKey publicKey,
            SignatureAlgorithm algorithm);

        // ---------------------------------------------------------------------
        // Symmetric AEAD Operations
        // ---------------------------------------------------------------------

        /// <summary>
        /// Encrypts data using an authenticated encryption with associated data
        /// algorithm (AEAD).
        /// </summary>
        /// <param name="plaintext">Plaintext to encrypt.</param>
        /// <param name="key">Symmetric key.</param>
        /// <param name="nonce">Unique nonce/IV.</param>
        /// <param name="associatedData">Non-encrypted, authenticated meta-data (optional).</param>
        /// <param name="algorithm">AEAD algorithm.</param>
        /// <returns>Ciphertext (includes authentication tag).</returns>
        byte[] Encrypt(
            ReadOnlyMemory<byte> plaintext,
            SymmetricKey key,
            ReadOnlySpan<byte> nonce,
            ReadOnlySpan<byte> associatedData,
            AeadAlgorithm algorithm);

        /// <summary>
        /// Decrypts data produced by <see cref="Encrypt"/>.
        /// </summary>
        /// <param name="ciphertext">Ciphertext.</param>
        /// <param name="key">Symmetric key.</param>
        /// <param name="nonce">Nonce/IV used during encryption.</param>
        /// <param name="associatedData">Associated data passed during encryption.</param>
        /// <param name="algorithm">AEAD algorithm.</param>
        /// <returns>Plaintext bytes.</returns>
        /// <exception cref="CryptographicException">Thrown when authentication fails.</exception>
        byte[] Decrypt(
            ReadOnlyMemory<byte> ciphertext,
            SymmetricKey key,
            ReadOnlySpan<byte> nonce,
            ReadOnlySpan<byte> associatedData,
            AeadAlgorithm algorithm);

        // ---------------------------------------------------------------------
        // Hashing / Message-digest Operations
        // ---------------------------------------------------------------------

        /// <summary>
        /// Computes a cryptographic hash of the supplied data.
        /// </summary>
        /// <param name="data">Data to hash.</param>
        /// <param name="algorithm">Hashing algorithm.</param>
        /// <returns>Digest bytes.</returns>
        byte[] Hash(
            ReadOnlyMemory<byte> data,
            HashAlgorithmType algorithm);

        /// <summary>
        /// Computes an HMAC for data using given key and algorithm.
        /// </summary>
        /// <param name="data">Data to authenticate.</param>
        /// <param name="key">Secret key.</param>
        /// <param name="algorithm">Underlying hash function.</param>
        /// <returns>HMAC bytes.</returns>
        byte[] ComputeHmac(
            ReadOnlyMemory<byte> data,
            SymmetricKey key,
            HashAlgorithmType algorithm);

        // ---------------------------------------------------------------------
        // Key Derivation
        // ---------------------------------------------------------------------

        /// <summary>
        /// Derives a child key from the master key using HKDF.
        /// </summary>
        /// <param name="masterKey">Master key.</param>
        /// <param name="salt">Optional salt.</param>
        /// <param name="info">Context / usage information.</param>
        /// <param name="length">Desired length of derived key.</param>
        /// <param name="algorithm">Underlying hash function.</param>
        /// <returns>Derived symmetric key.</returns>
        SymmetricKey DeriveKey(
            SymmetricKey masterKey,
            ReadOnlySpan<byte> salt,
            ReadOnlySpan<byte> info,
            int length,
            HashAlgorithmType algorithm);

        // ---------------------------------------------------------------------
        // Random Number Generation
        // ---------------------------------------------------------------------

        /// <summary>
        /// Fills the supplied buffer with cryptographically strong random bytes.
        /// </summary>
        /// <param name="destination">Destination buffer.</param>
        void FillRandom(Span<byte> destination);
    }

    #endregion
}
```