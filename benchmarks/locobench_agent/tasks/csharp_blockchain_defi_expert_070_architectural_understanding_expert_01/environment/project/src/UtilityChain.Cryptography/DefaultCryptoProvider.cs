```csharp
using System;
using System.Buffers;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace UtilityChain.Cryptography
{
    /// <summary>
    /// Default implementation of <see cref="ICryptoProvider"/> that relies exclusively on
    /// <c>System.Security.Cryptography</c> primitives available in .NET 8.
    /// </summary>
    /// <remarks>
    /// The provider purposefully avoids external dependencies so it can be embedded
    /// into the single-binary deployment model of UtilityChain.
    /// </remarks>
    public sealed class DefaultCryptoProvider : ICryptoProvider
    {
        private readonly RandomNumberGenerator _prng = RandomNumberGenerator.Create();

        #region ICryptoProvider – Hashing

        /// <inheritdoc/>
        public byte[] ComputeHash(ReadOnlySpan<byte> data, HashFunction hashFunction = HashFunction.Sha256)
        {
            if (data.IsEmpty) throw new ArgumentException("Data must not be empty.", nameof(data));

            return hashFunction switch
            {
                HashFunction.Sha256 => SHA256.HashData(data),
                HashFunction.Sha384 => SHA384.HashData(data),
                HashFunction.Sha512 => SHA512.HashData(data),
                _                   => throw new NotSupportedException($"Hash function {hashFunction} is not supported.")
            };
        }

        /// <inheritdoc/>
        public string ComputeHashHex(ReadOnlySpan<byte> data, HashFunction hashFunction = HashFunction.Sha256, bool upperCase = false)
        {
            var hash = ComputeHash(data, hashFunction);
            return BytesToHex(hash, upperCase);
        }

        #endregion

        #region ICryptoProvider – Asymmetric keys & signatures

        /// <inheritdoc/>
        public KeyPair GenerateKeyPair(AsymmetricAlgorithmType algorithm = AsymmetricAlgorithmType.ECDsa_P256)
        {
            var ecdsa = ECDsa.Create(algorithm switch
            {
                AsymmetricAlgorithmType.ECDsa_P256 => ECCurve.NamedCurves.nistP256,
                AsymmetricAlgorithmType.ECDsa_P384 => ECCurve.NamedCurves.nistP384,
                AsymmetricAlgorithmType.ECDsa_P521 => ECCurve.NamedCurves.nistP521,
                _                                   => throw new NotSupportedException($"Algorithm {algorithm} is not supported.")
            });

            return new KeyPair(ecdsa);
        }

        /// <inheritdoc/>
        public byte[] SignData(ReadOnlySpan<byte> data, KeyPair keyPair, HashFunction hashFunction = HashFunction.Sha256)
        {
            if (keyPair is null) throw new ArgumentNullException(nameof(keyPair));
            if (data.IsEmpty)    throw new ArgumentException("Data must not be empty.", nameof(data));

            using var ecdsa = ECDsa.Create();
            ecdsa.ImportPkcs8PrivateKey(keyPair.PrivateKey, out _);

            return ecdsa.SignData(data, GetHashAlgorithmName(hashFunction));
        }

        /// <inheritdoc/>
        public bool VerifySignature(ReadOnlySpan<byte> data, byte[] signature, byte[] publicKey, HashFunction hashFunction = HashFunction.Sha256)
        {
            if (data.IsEmpty)              throw new ArgumentException("Data must not be empty.", nameof(data));
            if (signature is null || signature.Length == 0) throw new ArgumentNullException(nameof(signature));
            if (publicKey  is null || publicKey.Length  == 0) throw new ArgumentNullException(nameof(publicKey));

            using var ecdsa = ECDsa.Create();
            ecdsa.ImportSubjectPublicKeyInfo(publicKey, out _);

            return ecdsa.VerifyData(data, signature, GetHashAlgorithmName(hashFunction));
        }

        #endregion

        #region ICryptoProvider – Key derivation & RNG

        /// <inheritdoc/>
        public byte[] DeriveKey(string passphrase, byte[] salt, int keySize = 32, int iterations = 100_000)
        {
            if (string.IsNullOrEmpty(passphrase)) throw new ArgumentException("Passphrase must not be null or empty.", nameof(passphrase));
            if (salt == null || salt.Length < 8)  throw new ArgumentException("Salt must be at least 8 bytes.", nameof(salt));
            if (keySize <= 0)                     throw new ArgumentOutOfRangeException(nameof(keySize));
            if (iterations <= 0)                  throw new ArgumentOutOfRangeException(nameof(iterations));

            using var pbkdf2 = new Rfc2898DeriveBytes(passphrase, salt, iterations, HashAlgorithmName.SHA256);
            return pbkdf2.GetBytes(keySize);
        }

        /// <inheritdoc/>
        public byte[] GenerateRandomBytes(int length)
        {
            if (length <= 0) throw new ArgumentOutOfRangeException(nameof(length));

            var buffer = ArrayPool<byte>.Shared.Rent(length);
            try
            {
                _prng.GetBytes(buffer, 0, length);
                var output = new byte[length];
                Buffer.BlockCopy(buffer, 0, output, 0, length);
                return output;
            }
            finally
            {
                Array.Clear(buffer, 0, length);
                ArrayPool<byte>.Shared.Return(buffer);
            }
        }

        #endregion

        #region Helpers

        private static string BytesToHex(ReadOnlySpan<byte> bytes, bool upperCase)
        {
            var format = upperCase ? "X2" : "x2";
            var sb = new StringBuilder(bytes.Length * 2);
            foreach (var b in bytes)
                sb.Append(b.ToString(format, CultureInfo.InvariantCulture));
            return sb.ToString();
        }

        private static HashAlgorithmName GetHashAlgorithmName(HashFunction hashFunction) =>
            hashFunction switch
            {
                HashFunction.Sha256 => HashAlgorithmName.SHA256,
                HashFunction.Sha384 => HashAlgorithmName.SHA384,
                HashFunction.Sha512 => HashAlgorithmName.SHA512,
                _ => throw new NotSupportedException($"Hash function {hashFunction} is not supported.")
            };

        #endregion

        #region IDisposable

        private bool _disposed;

        /// <inheritdoc/>
        public void Dispose()
        {
            if (_disposed) return;

            _prng?.Dispose();
            _disposed = true;
            GC.SuppressFinalize(this);
        }

        #endregion
    }

    #region Interfaces & shared abstractions

    /// <summary>
    /// Abstraction for cryptographic services consumed by other UtilityChain modules.
    /// </summary>
    public interface ICryptoProvider : IDisposable
    {
        /* Hashing */
        byte[]  ComputeHash(ReadOnlySpan<byte> data, HashFunction hashFunction = HashFunction.Sha256);
        string  ComputeHashHex(ReadOnlySpan<byte> data, HashFunction hashFunction = HashFunction.Sha256, bool upperCase = false);

        /* Asymmetric crypto */
        KeyPair GenerateKeyPair(AsymmetricAlgorithmType algorithm = AsymmetricAlgorithmType.ECDsa_P256);
        byte[]  SignData(ReadOnlySpan<byte> data, KeyPair keyPair, HashFunction hashFunction = HashFunction.Sha256);
        bool    VerifySignature(ReadOnlySpan<byte> data, byte[] signature, byte[] publicKey, HashFunction hashFunction = HashFunction.Sha256);

        /* Key derivation & RNG */
        byte[]  DeriveKey(string passphrase, byte[] salt, int keySize = 32, int iterations = 100_000);
        byte[]  GenerateRandomBytes(int length);
    }

    /// <summary>
    /// Enumerates the hash functions supported by <see cref="DefaultCryptoProvider"/>.
    /// </summary>
    public enum HashFunction
    {
        Sha256,
        Sha384,
        Sha512
    }

    /// <summary>
    /// Enumerates asymmetric algorithms currently supported.
    /// </summary>
    public enum AsymmetricAlgorithmType
    {
        ECDsa_P256,
        ECDsa_P384,
        ECDsa_P521
    }

    /// <summary>
    /// Represents an asymmetric key-pair (public + private).
    /// </summary>
    public sealed class KeyPair : IDisposable
    {
        private readonly ECDsa _ecdsa;

        internal KeyPair(ECDsa ecdsa)
        {
            _ecdsa = ecdsa ?? throw new ArgumentNullException(nameof(ecdsa));
            PrivateKey = _ecdsa.ExportPkcs8PrivateKey();
            PublicKey  = _ecdsa.ExportSubjectPublicKeyInfo();
        }

        /// <summary>
        /// ASN.1 PKCS#8 private key.
        /// </summary>
        public byte[] PrivateKey { get; }

        /// <summary>
        /// ASN.1 X.509 <c>SubjectPublicKeyInfo</c> public key.
        /// </summary>
        public byte[] PublicKey { get; }

        #region IDisposable

        private bool _disposed;

        public void Dispose()
        {
            if (_disposed) return;
            _ecdsa?.Dispose();
            _disposed = true;
            GC.SuppressFinalize(this);
        }

        #endregion
    }

    #endregion
}
```