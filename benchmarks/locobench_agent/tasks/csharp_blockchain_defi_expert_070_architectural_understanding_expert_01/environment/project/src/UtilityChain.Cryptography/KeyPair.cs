```csharp
using System;
using System.Buffers;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace UtilityChain.Cryptography
{
    /// <summary>
    /// Represents an elliptic-curve key-pair (currently secp256k1) used across the UtilityChain runtime
    /// for account addresses, transaction signing, and governance authentication.
    ///
    /// The implementation purposefully avoids exposing <see cref="ECDsa"/> – instead a lightweight,
    /// serialisable abstraction is provided so that higher-level modules (staking, wallet, consensus)
    /// can depend on <see cref="KeyPair"/> without leaking crypto-specific concerns.
    /// </summary>
    public sealed class KeyPair : IDisposable, IEquatable<KeyPair>
    {
        private const string CurveFriendlyName = "secP256k1";
        private const int PrivateKeySize = 32; // 256-bit
        private const int CompressedPubKeySize = 33;

        private readonly ECDsa _ecdsa;

        #region Construction / Factory Methods

        private KeyPair(ECDsa ecdsa)
        {
            _ecdsa = ecdsa ?? throw new ArgumentNullException(nameof(ecdsa));
        }

        /// <summary>
        /// Generates a fresh secp256k1 key-pair using the system’s CSPRNG.
        /// </summary>
        public static KeyPair Generate()
        {
            var ecdsa = ECDsa.Create(CreateSecp256K1Curve());
            return new KeyPair(ecdsa);
        }

        /// <summary>
        /// Restores a key-pair from a raw 32-byte private key.
        /// </summary>
        /// <param name="privateKey">
        /// 32-byte little-endian private key.
        /// </param>
        /// <exception cref="ArgumentException">
        /// Thrown when the private key length is invalid or outside the curve’s domain.
        /// </exception>
        public static KeyPair FromPrivateKey(ReadOnlySpan<byte> privateKey)
        {
            if (privateKey.Length != PrivateKeySize)
                throw new ArgumentException($"Private key must be {PrivateKeySize} bytes", nameof(privateKey));

            // Defensive copy since ECParameters retains the span
            Span<byte> d = stackalloc byte[PrivateKeySize];
            privateKey.CopyTo(d);

            var parameters = new ECParameters
            {
                Curve = CreateSecp256K1Curve(),
                D = d.ToArray() // ECDsa requires array not span
            };

            // ECDsa will derive Q (public) values when we import with only D populated.
            var ecdsa = ECDsa.Create();
            try
            {
                ecdsa.ImportParameters(parameters);
            }
            catch (CryptographicException ex)
            {
                ecdsa.Dispose();
                throw new ArgumentException("Invalid private key.", nameof(privateKey), ex);
            }

            return new KeyPair(ecdsa);
        }

        /// <summary>
        /// Parses a lower-case hex-encoded private key string.
        /// </summary>
        public static KeyPair FromPrivateKeyHex(string hex)
        {
            if (string.IsNullOrWhiteSpace(hex))
                throw new ArgumentNullException(nameof(hex));

            if (hex.Length != PrivateKeySize * 2)
                throw new ArgumentException("Invalid hex length for secp256k1 private key.", nameof(hex));

            Span<byte> buffer = stackalloc byte[PrivateKeySize];
            if (!HexToBytes(hex.AsSpan(), buffer))
                throw new ArgumentException("Hex string contained invalid characters.", nameof(hex));

            return FromPrivateKey(buffer);
        }

        #endregion

        #region Public API

        /// <summary>
        /// Exports the raw 32-byte private key.
        /// </summary>
        public byte[] ExportPrivateKey()
        {
            EnsureNotDisposed();
            var parameters = _ecdsa.ExportParameters(true);

            // D is sometimes shorter than 32-bytes; pad left with zeros.
            if (parameters.D!.Length == PrivateKeySize)
                return parameters.D;

            return parameters.D!.PadLeft(PrivateKeySize);
        }

        /// <summary>
        /// Returns a hex-encoded private key (lower-case, no 0x prefix).
        /// </summary>
        public string ExportPrivateKeyHex()
            => BytesToHex(ExportPrivateKey());

        /// <summary>
        /// Exports the compressed public key (33-bytes, SEC1 format).
        /// </summary>
        public byte[] ExportPublicKey()
        {
            EnsureNotDisposed();
            var parameters = _ecdsa.ExportParameters(false);
            return CompressPublicKey(parameters.Q.X!, parameters.Q.Y!);
        }

        /// <summary>
        /// Gets a hex-encoded compressed public key (lower-case, no 0x prefix).
        /// </summary>
        public string ExportPublicKeyHex()
            => BytesToHex(ExportPublicKey());

        /// <summary>
        /// Signs the given message digest with deterministic ECDSA (RFC 6979) and
        /// returns the DER-encoded signature.
        ///
        /// Callers are expected to hash the input before calling this method.
        /// </summary>
        /// <remarks>
        /// .NET’s built-in ECDsa implementation already uses deterministic nonces
        /// (<see href="https://github.com/dotnet/runtime/issues/20002"/>).
        /// </remarks>
        public byte[] Sign(ReadOnlySpan<byte> digest)
        {
            EnsureNotDisposed();

            if (digest.IsEmpty)
                throw new ArgumentException("Digest cannot be empty.", nameof(digest));

            return _ecdsa.SignHash(digest);
        }

        /// <summary>
        /// Verifies a signature for the specified message digest (32-byte SHA-256 in most cases).
        /// </summary>
        public bool Verify(ReadOnlySpan<byte> digest, ReadOnlySpan<byte> signature)
        {
            EnsureNotDisposed();

            if (digest.IsEmpty || signature.IsEmpty)
                return false;

            return _ecdsa.VerifyHash(digest, signature);
        }

        #endregion

        #region Helpers

        private static ECCurve CreateSecp256K1Curve()
        {
            // Windows CNG & Linux OpenSSL both recognise this friendly name in .NET 6+
            return ECCurve.CreateFromFriendlyName(CurveFriendlyName);
        }

        private static byte[] CompressPublicKey(ReadOnlySpan<byte> x, ReadOnlySpan<byte> y)
        {
            if (x.Length != PrivateKeySize || y.Length != PrivateKeySize)
                throw new ArgumentException("Invalid public key coordinates.");

            var compressed = new byte[CompressedPubKeySize];
            compressed[0] = (byte)(y[^1] % 2 == 0 ? 0x02 : 0x03); // Even/odd Y-parity
            x.CopyTo(compressed.AsSpan(1));
            return compressed;
        }

        private static string BytesToHex(ReadOnlySpan<byte> bytes)
        {
            return Convert.ToHexString(bytes).ToLowerInvariant();
        }

        private static bool HexToBytes(ReadOnlySpan<char> hex, Span<byte> bytes)
        {
            try
            {
                return Convert.TryFromHexString(hex, bytes, out _);
            }
            catch (FormatException)
            {
                return false;
            }
        }

        private void EnsureNotDisposed()
        {
            ObjectDisposedException.ThrowIf(_ecdsa == null, nameof(KeyPair));
        }

        #endregion

        #region Equality / HashCode / Operators

        public override bool Equals(object? obj) => obj is KeyPair other && Equals(other);

        public bool Equals(KeyPair? other)
        {
            if (other is null) return false;
            if (ReferenceEquals(this, other)) return true;
            return ExportPublicKeyHex().Equals(other.ExportPublicKeyHex(), StringComparison.Ordinal);
        }

        public override int GetHashCode()
        {
            // Use first 4 bytes of pub-key to build a stable hash.
            var pub = ExportPublicKey();
            return BinaryPrimitives.ReadInt32LittleEndian(pub);
        }

        public static bool operator ==(KeyPair? left, KeyPair? right) => Equals(left, right);
        public static bool operator !=(KeyPair? left, KeyPair? right) => !Equals(left, right);

        #endregion

        #region IDisposable

        private bool _disposed;

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _ecdsa.Dispose();
            GC.SuppressFinalize(this);
        }

        #endregion
    }

    internal static class ByteExtensions
    {
        /// <summary>
        /// Pads the specified byte-array (big-endian) on the left with zeros
        /// so that the resulting array is of the provided <paramref name="size"/>.
        /// </summary>
        public static byte[] PadLeft(this byte[] value, int size)
        {
            if (value.Length > size)
                throw new ArgumentException("Value is larger than the target size.", nameof(value));

            if (value.Length == size)
                return (byte[])value.Clone();

            var output = new byte[size];
            Buffer.BlockCopy(value, 0, output, size - value.Length, value.Length);
            return output;
        }
    }
}
```